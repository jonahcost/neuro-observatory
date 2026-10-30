import time

from fastapi.testclient import TestClient

from neuro_engine.app import create_app
from neuro_engine.config import EngineSettings


def test_health():
    with TestClient(create_app(EngineSettings())) as client:
        time.sleep(0.05)
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["protocolVersion"] == 2
    acquisition = body["acquisition"]
    assert acquisition["state"] == "streaming"
    assert acquisition["deviceKind"] == "synthetic"
    assert acquisition["synthetic"] is True
    assert acquisition["channelCount"] == 16
    assert acquisition["nominalSampleRateHz"] == 125
