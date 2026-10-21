from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(autouse=True)
def no_voice_pack(request, monkeypatch, tmp_path):
    """Tests run as if the optional voice pack were absent, unless marked `real_voice`."""
    if "real_voice" not in request.keywords:
        monkeypatch.setattr("app.config.VOICE_DIR", tmp_path / "no-voices")


@pytest.fixture(autouse=True)
def no_speech_model_or_language_model(request, monkeypatch, tmp_path):
    """Tests run without the local speech-to-text model and without a language model, whatever is installed
    or set in the environment, unless marked `real_stt`."""
    if "real_stt" not in request.keywords:
        monkeypatch.setattr("app.config.VOICE_AGENT_STT_DIR", tmp_path / "no-stt")
    monkeypatch.setattr("app.config.VOICE_AGENT_LLM_PROVIDER", "none")
    if "real_reference" not in request.keywords:  # no reference clips, no worker (port 9 refuses connections)
        monkeypatch.setattr("app.config.VOICE_AGENT_REFERENCE_DIR", tmp_path / "no-reference")
        monkeypatch.setattr("app.config.VOICE_AGENT_REFERENCE_WORKER_URL", "http://127.0.0.1:9")


@pytest.fixture
def client(tmp_path):
    """A fresh, seeded demo database per test."""
    app = create_app(f"sqlite:///{tmp_path / 'test.db'}")
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def new_patient(client):
    response = client.post("/api/patients", json={"name": "Test Patient", "mobile": "555 020 0001"})
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def free_slot(client):
    """First available slot from tomorrow onwards (never 'past', whatever time the tests run)."""
    doctor = client.get("/api/doctors").json()[0]
    for offset in range(1, 7):
        day = date.today() + timedelta(days=offset)
        slots = client.get(f"/api/doctors/{doctor['id']}/slots", params={"date": day.isoformat()}).json()
        for slot in slots:
            if slot["available"]:
                return slot
    pytest.fail("No free seeded slot found")


@pytest.fixture
def service_id(client):
    return client.get("/api/services").json()[0]["id"]
