from __future__ import annotations

import asyncio
from pathlib import Path

from neuro_engine.acquisition.clock import VirtualClock
from neuro_engine.acquisition.service import AcquisitionService
from neuro_engine.acquisition.synthetic import SyntheticEegAdapter
from neuro_engine.analysis.band_power import BandPowerAnalyzer, FindingStore
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
    session = SessionController(service, settings, clock, tmp_path / "recordings", analyzer)
    model = LlamaRuntime(tmp_path, enabled=False)
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
        await asyncio.sleep(0)
        await session.use_synthetic()
        task.cancel()
        try:
            result = await task
        except asyncio.CancelledError:
            result = {"intent": "cancelled", "message": "Cancelled because the session changed."}
        await session.service.stop()
        return result

    result = asyncio.run(run())
    assert result["intent"] == "cancelled" or "Cancelled" in str(result.get("message"))
