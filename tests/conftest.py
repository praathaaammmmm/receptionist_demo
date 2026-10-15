from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(autouse=True)
def no_voice_pack(request, monkeypatch, tmp_path):
    """Tests run as if the optional voice pack were absent, unless marked `real_voice`."""
    if "real_voice" not in request.keywords:
        monkeypatch.setattr("app.config.VOICE_DIR", tmp_path / "no-voices")


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
