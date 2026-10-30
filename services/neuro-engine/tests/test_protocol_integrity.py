"""Shared integrity scenarios, also executed by packages/protocol/src/integrity.spec.ts."""

from __future__ import annotations

import pytest
from conftest import FIXTURE_ROOT, load_fixture_json

from neuro_engine.protocol import v2
from neuro_engine.protocol.integrity import StreamIntegrityTracker

SCENARIOS = sorted(p.name for p in (FIXTURE_ROOT / "integrity").glob("*.json"))


def test_scenarios_exist() -> None:
    assert len(SCENARIOS) >= 7


@pytest.mark.parametrize("name", SCENARIOS)
def test_tracker_matches_shared_scenario(name: str) -> None:
    scenario = load_fixture_json(f"integrity/{name}")
    tracker = StreamIntegrityTracker()
    for step in scenario["steps"]:
        message = v2.validate_server_message(step["message"])
        if isinstance(message, v2.StreamMetadata):
            verdict = tracker.on_metadata(message)
        elif isinstance(message, v2.EegBlock):
            verdict = tracker.on_block(message)
        else:
            verdict = "ignored"
        assert verdict == step["expect"]
    assert tracker.snapshot().as_wire_dict() == scenario["expectedCounters"]
