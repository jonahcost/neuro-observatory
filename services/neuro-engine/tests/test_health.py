from fastapi.testclient import TestClient

from neuro_engine.main import app


def test_health():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["channels"] == 16
    assert response.json()["sampleRateHz"] == 125
