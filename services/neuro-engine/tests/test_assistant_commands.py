from __future__ import annotations

import asyncio
import json
from pathlib import Path

from neuro_engine.acquisition.clock import VirtualClock
from neuro_engine.acquisition.service import AcquisitionService
from neuro_engine.acquisition.synthetic import SyntheticEegAdapter
from neuro_engine.analysis.band_power import (
    BandPowerAnalyzer,
    ChannelMeasurement,
    Finding,
    FindingStore,
)
from neuro_engine.assistant.commands import execute, parse_text
from neuro_engine.assistant.runtime import LlamaRuntime
from neuro_engine.assistant.service import AssistantService
from neuro_engine.assistant.session import SessionController
from neuro_engine.config import EngineSettings
from neuro_engine.recordings.scenario import write_alpha_step
from neuro_engine.streaming.hub import StreamHub


def _session(tmp_path: Path) -> tuple[SessionController, FindingStore, AssistantService]:
    clock = VirtualClock()
    settings = EngineSettings()
    service = AcquisitionService(lambda: SyntheticEegAdapter(settings.synthetic, clock), StreamHub(), clock)
    store = FindingStore()
    analyzer = BandPowerAnalyzer(store)
    service.add_accepted_listener(analyzer.on_accepted)
    model = LlamaRuntime(tmp_path, enabled=False)
    session = SessionController(service, settings, clock, tmp_path / "recordings", analyzer, on_cancel=model.cancel)
    return session, store, AssistantService(session, store, model)


def test_lexicon_parses_the_demo_phrases() -> None:
    assert parse_text("Show the rear channels")["intent"] == "emphasize_channels"
    assert parse_text("Which channels changed most?")["question"] == "changed-most"
    assert parse_text("Show me that segment")["intent"] == "seek_to_finding"
    assert parse_text("Mark this moment")["intent"] == "add_marker"
    assert parse_text("Show the white matter boundary")["displayMode"] == "white"


def test_live_seek_and_ambiguous_segment_do_not_move_the_source(tmp_path: Path) -> None:
    session, store, assistant = _session(tmp_path)

    async def run() -> tuple[dict, dict]:
        await session.service.start()
        await asyncio.sleep(0)
        refused = await assistant.intent({"text": "Show me that segment", "sessionGeneration": session.generation})
        unclear = await execute(
            {"intent": "clarify", "clarification": "Which segment do you mean?"},
            session,
            store,
            requested_generation=session.generation,
        )
        await session.service.stop()
        return refused, unclear

    refused, unclear = asyncio.run(run())
    assert refused["ok"] is False
    assert "cannot jump backward" in str(refused["message"])
    assert unclear["intent"] == "clarify"
    assert session.source == "synthetic"


def test_replay_command_opens_the_cited_interval(tmp_path: Path) -> None:
    write_alpha_step(tmp_path / "recordings" / "alpha-step")
    session, _store, assistant = _session(tmp_path)

    async def run() -> dict:
        await session.replay("alpha-step")
        for _ in range(400):
            await asyncio.sleep(0)
            if any(item.band == "alpha" for item in session.analyzer.store.findings):
                break
        result = await assistant.intent({"text": "Show me that segment", "sessionGeneration": session.generation})
        await session.service.stop()
        return result

    result = asyncio.run(run())
    assert result["ok"] is True
    assert result["intent"] == "seek_to_finding"
    assert result["seekSampleIndex"] is not None
    assert "O1" in result["channels"] or "O2" in result["channels"]


def test_missing_model_still_answers_from_findings(tmp_path: Path) -> None:
    session, _store, assistant = _session(tmp_path)

    async def run() -> dict:
        await session.service.start()
        await asyncio.sleep(0)
        answer = await assistant.intent({"text": "Which channels changed most?", "sessionGeneration": 0})
        stale = await assistant.intent({"text": "Show the rear channels", "sessionGeneration": 99})
        await session.service.stop()
        return {"answer": answer, "stale": stale, "model": assistant.snapshot()["model"]}

    outcome = asyncio.run(run())
    assert outcome["model"] == "unavailable"
    assert outcome["answer"]["intent"] == "answer"
    assert outcome["stale"]["intent"] == "cancelled"


def test_unknown_finding_id_is_not_cited(tmp_path: Path) -> None:
    session, _store, assistant = _session(tmp_path)

    async def run() -> dict:
        await session.service.start()
        await asyncio.sleep(0)
        result = await assistant.intent(
            {
                "intent": "answer",
                "question": "changed-most",
                "findingIds": ["not-a-real-finding"],
                "sessionGeneration": session.generation,
            }
        )
        await session.service.stop()
        return result

    result = asyncio.run(run())
    assert "could not tie" in result["message"]


def test_model_transport_is_dropped_when_the_session_changes(tmp_path: Path) -> None:
    session, _store, assistant = _session(tmp_path)

    async def slow(_messages, _schema):
        await asyncio.sleep(30)
        return {"choices": [{"message": {"content": "{\"intent\":\"clarify\",\"clarification\":\"late\"}"}}]}

    assistant.model.use_transport(slow)

    async def run() -> dict:
        await session.service.start()
        task = asyncio.create_task(assistant.intent({"text": "What happened in the frontal channels?", "sessionGeneration": 0}))
        for _ in range(20):
            await asyncio.sleep(0)
            if assistant.model._inflight is not None:
                break
        await session.use_synthetic()
        result = await asyncio.wait_for(task, timeout=1)
        await session.service.stop()
        return result

    result = asyncio.run(run())
    assert result["intent"] == "cancelled" or "Cancelled" in str(result.get("message"))


def test_model_prose_is_replaced_by_the_stored_measurement(tmp_path: Path) -> None:
    session, store, assistant = _session(tmp_path)
    finding = Finding(
        finding_id="finding-alpha",
        session_generation=0,
        stream_id="stream-a",
        recording_id=None,
        source_kind="synthetic",
        device_id="synthetic-0",
        method="band-power",
        method_version="1",
        band="alpha",
        first_sample_index=10,
        last_sample_index=20,
        first_sample_time_us=0,
        last_sample_time_us=80_000,
        nominal_sample_rate_hz=125.0,
        channels=(
            ChannelMeasurement(
                index=13,
                label="O1",
                reference="synthetic",
                unit="uV",
                power_uv2=1800.0,
                baseline_uv2=200.0,
                change_db=9.5,
                rms_uv=30.0,
                accepted_sample_fraction=1.0,
                quality="good",
            ),
        ),
        quality="good",
        synthetic=True,
        created_us=80_000,
    )
    store.add(finding)

    async def run() -> dict:
        await session.service.start()
        result = await assistant.intent(
            {
                "intent": "answer",
                "answer": "O1 changed by 1000 dB.",
                "findingIds": ["finding-alpha"],
                "sessionGeneration": session.generation,
            }
        )
        await session.service.stop()
        return result

    result = asyncio.run(run())
    assert result["ok"] is True
    assert "1000" not in result["message"]
    assert "+9.5 dB" in result["message"]
    assert "generated, not measured" in result["message"]


def test_an_explanation_question_is_not_a_seek(tmp_path: Path) -> None:
    session, _store, assistant = _session(tmp_path)

    async def transport(_messages, _schema):
        return {"choices": [{"message": {"content": json.dumps({"intent": "seek_to_finding"})}}]}

    assistant.model.use_transport(transport)

    async def run() -> dict:
        await session.service.start()
        result = await assistant.intent({"text": "Explain Fp1 and Fp2 to me", "sessionGeneration": session.generation})
        await session.service.stop()
        return result

    result = asyncio.run(run())
    assert result["intent"] == "clarify"
    assert "cannot jump backward" not in result["message"]
    assert "left this stream" in result["message"]
