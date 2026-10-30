"""HTTP and WebSocket integration against a real-time synthetic stream."""

from __future__ import annotations

import itertools
import json
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from neuro_engine.acquisition.service import AcquisitionState
from neuro_engine.acquisition.synthetic import SyntheticConfig
from neuro_engine.app import create_app
from neuro_engine.config import EngineSettings
from neuro_engine.protocol import v2
from neuro_engine.protocol.integrity import StreamIntegrityTracker

ORIGIN = {"origin": "http://localhost:4200"}


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = EngineSettings(synthetic=SyntheticConfig(seed=7, block_size=5), status_interval_s=0.2)
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def receive_messages(ws: WebSocketTestSession, count: int) -> list[dict]:
    return [json.loads(ws.receive_text()) for _ in range(count)]


def test_acquisition_runs_without_any_client(client: TestClient) -> None:
    time.sleep(0.5)
    body = client.get("/api/v2/stream").json()
    assert body["status"]["counters"]["samplesAcquired"] >= 40
    assert body["metadata"]["provenance"]["kind"] == "synthetic"
    assert client.app.state.engine.hub.subscriber_count == 0  # type: ignore[attr-defined]


def test_stream_endpoint_messages_match_the_canonical_schema(
    client: TestClient, schema_validator: Draft202012Validator
) -> None:
    time.sleep(0.1)
    body = client.get("/api/v2/stream").json()
    schema_validator.validate(body["metadata"])
    schema_validator.validate(body["status"])


def test_websocket_sends_metadata_first_then_valid_contiguous_blocks(
    client: TestClient, schema_validator: Draft202012Validator
) -> None:
    time.sleep(0.2)  # join mid-stream
    with client.websocket_connect("/ws/v2/eeg", headers=ORIGIN) as ws:
        messages = receive_messages(ws, 25)
    for message in messages:
        schema_validator.validate(message)
    assert messages[0]["type"] == "stream.metadata"
    assert messages[1]["type"] == "stream.status"
    metadata = v2.validate_server_message(messages[0])
    assert isinstance(metadata, v2.StreamMetadata)
    assert [c.label for c in metadata.channels][:3] == ["Fp1", "Fp2", "F3"]
    assert metadata.timebase.timestamp_source == "synthetic-nominal"

    tracker = StreamIntegrityTracker()
    tracker.on_metadata(metadata)
    blocks = []
    for raw in messages[1:]:
        message = v2.validate_server_message(raw, metadata)
        if isinstance(message, v2.EegBlock):
            assert tracker.on_block(message) == "accepted"
            blocks.append(message)
    counters = tracker.snapshot()
    assert counters.inconsistent_blocks == 0 and counters.transport_dropped_blocks == 0
    assert blocks[0].first_sample_index > 0  # acquisition started before the client connected
    for previous, current in itertools.pairwise(blocks):
        assert current.first_sample_index == previous.first_sample_index + previous.sample_count
        assert current.first_sample_time_us - previous.first_sample_time_us == previous.sample_count * 8_000
        assert len(current.samples) == 16 and all(len(row) == 5 for row in current.samples)


def test_two_clients_receive_identical_samples(client: TestClient) -> None:
    with (
        client.websocket_connect("/ws/v2/eeg", headers=ORIGIN) as first,
        client.websocket_connect("/ws/v2/eeg") as second,
    ):
        a = receive_messages(first, 15)
        b = receive_messages(second, 15)
    blocks_a = {m["blockSequence"]: m for m in a if m["type"] == "eeg.block"}
    blocks_b = {m["blockSequence"]: m for m in b if m["type"] == "eeg.block"}
    shared = set(blocks_a) & set(blocks_b)
    assert shared
    for sequence in shared:
        assert blocks_a[sequence] == blocks_b[sequence]


def test_disallowed_origin_is_rejected(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as excinfo,
        client.websocket_connect("/ws/v2/eeg", headers={"origin": "https://evil.example"}) as ws,
    ):
        ws.receive_text()
    assert excinfo.value.code == 1008


def test_client_messages_are_refused_with_1003(client: TestClient) -> None:
    with client.websocket_connect("/ws/v2/eeg", headers=ORIGIN) as ws:
        ws.send_text("hello")
        with pytest.raises(WebSocketDisconnect) as excinfo:
            while True:
                ws.receive_text()
    assert excinfo.value.code == 1003


def test_retired_v1_endpoint_is_gone(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/eeg") as ws:
        ws.receive_text()


def test_disconnecting_clients_release_subscriptions_and_shutdown_stops_acquisition() -> None:
    settings = EngineSettings(synthetic=SyntheticConfig(block_size=5))
    app = create_app(settings)
    with TestClient(app) as test_client:
        with test_client.websocket_connect("/ws/v2/eeg", headers=ORIGIN) as ws:
            receive_messages(ws, 3)
            assert app.state.engine.hub.subscriber_count == 1
        deadline = time.monotonic() + 2
        while app.state.engine.hub.subscriber_count and time.monotonic() < deadline:
            time.sleep(0.01)
        assert app.state.engine.hub.subscriber_count == 0
        assert app.state.engine.service.state is AcquisitionState.STREAMING
    assert app.state.engine.service.state is AcquisitionState.STOPPED
