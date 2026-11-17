"""Build assistant.v1 documents and route text or structured intents."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from neuro_engine.acquisition.service import AcquisitionState
from neuro_engine.analysis.band_power import FindingStore
from neuro_engine.analysis.blink import CLASSIFIER_ENABLED
from neuro_engine.assistant.commands import execute, parse_text
from neuro_engine.assistant.runtime import INTENT_SCHEMA, LlamaRuntime, ModelUnavailable
from neuro_engine.assistant.session import SessionController
from neuro_engine.protocol.assistant_v1 import document_dict, parse_document

_SYSTEM = (
    "You are the local Neuro Observatory assistant. Answer only from the findings JSON. "
    "Do not invent channels, times, or measurements. If evidence is missing, stale, or low quality, say so. "
    "Scalp band power is not a cortical image and not a diagnosis. "
    "Synthetic findings are generated, not measured from a person. "
    "Reply with one JSON object matching the schema. Use only finding ids that appear in the prompt."
)


class AssistantService:
    def __init__(self, session: SessionController, store: FindingStore, model: LlamaRuntime) -> None:
        self.session = session
        self.store = store
        self.model = model

    def snapshot(self) -> dict[str, Any]:
        session = self.session
        health = session.service.health()
        evidence = session.analyzer.evidence
        if session.paused or (session.service.state is AcquisitionState.STREAMING and "no-recent-data" in health.reasons):
            evidence = "stale"
        stream = session.service.current_stream
        document = {
            "type": "assistant.snapshot",
            "schemaVersion": 1,
            "sessionGeneration": session.generation,
            "streamId": None if stream is None else stream.stream_id,
            "source": session.source,
            "recordingId": session.recording_id,
            "paused": session.paused,
            "evidence": evidence,
            "model": self.model.status if self.model.status in {"unavailable", "ready", "starting"} else "unavailable",
            "classifier": "enabled" if CLASSIFIER_ENABLED else "disabled",
            "analysisSamplesExpired": session.analyzer.expired,
            "findings": [item.to_wire() for item in self.store.findings],
            "markers": [item.to_wire() for item in self.store.markers],
            "lines": [line[:400] for line in self.store.lines if line],
        }
        return document_dict(parse_document(document))

    async def intent(self, body: dict[str, Any]) -> dict[str, Any]:
        generation = body.get("sessionGeneration")
        requested = generation if isinstance(generation, int) else None
        if isinstance(body.get("intent"), str):
            proposal = body
        else:
            text = str(body.get("text") or "")
            proposal = parse_text(text)
            if proposal is None:
                proposal = await self._model_proposal(text)
        if proposal.get("intent") == "cancelled":
            cancelled = await execute(
                {"intent": "clarify", "clarification": "Cancelled because the session changed."},
                self.session,
                self.store,
                requested_generation=self.session.generation + 1,
            )
            return document_dict(parse_document(cancelled))
        result = await execute(proposal, self.session, self.store, requested_generation=requested)
        return document_dict(parse_document(result))

    async def _model_proposal(self, text: str) -> dict[str, Any]:
        if self.model.status != "ready":
            return {
                "intent": "clarify",
                "clarification": (
                    "The local language model is not installed, so I can only run the listed commands "
                    "and report findings already on screen."
                ),
            }
        findings = [
            {
                "findingId": item.finding_id,
                "band": item.band,
                "method": item.method,
                "samples": [item.first_sample_index, item.last_sample_index],
                "channels": [
                    {"label": channel.label, "changeDb": channel.change_db, "quality": channel.quality}
                    for channel in item.channels
                ],
                "synthetic": item.synthetic,
            }
            for item in self.store.query(generation=self.session.generation)
        ]
        messages = [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "evidence": self.session.analyzer.evidence,
                        "source": self.session.source,
                        "recordingId": self.session.recording_id,
                        "findings": findings,
                        "text": text,
                        "schema": INTENT_SCHEMA,
                    }
                ),
            },
        ]
        started = self.session.generation
        try:
            payload = await self.model.complete(messages)
        except asyncio.CancelledError:
            return {"intent": "cancelled", "clarification": "Cancelled because the session changed."}
        except (ModelUnavailable, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            if self.session.generation != started:
                return {"intent": "cancelled", "clarification": "Cancelled because the session changed."}
            return {
                "intent": "clarify",
                "clarification": "The local language model is unavailable. Findings on screen are unchanged.",
            }
        if self.session.generation != started:
            return {"intent": "cancelled", "clarification": "Cancelled because the session changed."}
        return _proposal_from_completion(payload)


def _proposal_from_completion(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content) if isinstance(content, str) else content
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return {"intent": "clarify", "clarification": "I could not tie that claim to a current finding."}
    if not isinstance(parsed, dict) or "intent" not in parsed:
        return {"intent": "clarify", "clarification": "I could not tie that claim to a current finding."}
    return parsed
