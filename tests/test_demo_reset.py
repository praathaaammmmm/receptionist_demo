"""Phase 4: developer-only demo reset."""
import subprocess
import sys
from pathlib import Path

from app.seed import reset_demo_data

from .test_assistant import Chat
from .test_call_demo import Call

ROOT = Path(__file__).resolve().parent.parent


def counts(client):
    return {
        "doctors": len(client.get("/api/doctors").json()),
        "services": len(client.get("/api/services").json()),
        "patients": len(client.get("/api/patients").json()),
        "appointments": len(client.get("/api/appointments", params={"scope": "today"}).json())
        + len(client.get("/api/appointments").json()),
        "callbacks": len(client.get("/api/callbacks").json()),
        "calls": len(client.get("/api/calls").json()),
    }


def test_reset_restores_seeded_state_and_clears_callbacks_and_calls(client):
    seeded = counts(client)
    assert seeded == {"doctors": 3, "services": 4, "patients": 4, "appointments": 4, "callbacks": 0, "calls": 0}

    # Make a mess: a callback, a call log, an extra patient, and an edited clinic and doctor.
    chat = Chat(client)
    chat.send("I want to speak to a person.")
    chat.send("Ravi Example")
    chat.send("5550990001")
    Call(client).end()
    client.post("/api/patients", json={"name": "Extra Patient", "mobile": "5550990002"})
    client.post("/settings/clinic", data={"name": "Renamed Clinic", "address": "x", "phone": "1"})
    client.post(
        "/settings/doctors/1",
        data={"name": "Dr. Changed", "speciality": "Changed", "work_start": "10:00", "work_end": "12:00",
              "consultation_minutes": "60", "working_days": ["0"]},
    )
    messy = counts(client)
    assert messy["callbacks"] == 1 and messy["calls"] == 1 and messy["patients"] == 5

    with client.app.state.session_factory() as db:
        result = reset_demo_data(db)

    assert counts(client) == seeded
    assert result["callback_tasks"] == 0 and result["call_logs"] == 0 and result["slots"] > 100
    assert client.get("/api/clinic").json()["name"] == "Smriti Raj Dentistry"
    doctors = client.get("/api/doctors").json()
    assert [d["name"] for d in doctors] == ["Dr. Anika Rao", "Dr. Vikram Shah", "Dr. Meera Iyer"]
    assert all(6 not in d["working_days"] for d in doctors)  # still closed on Sunday
    assert client.get("/").status_code == 200
    # The reset demo is immediately usable again.
    assert Chat(client).send("What are your opening hours?")["answered"] == "hours"


def test_reset_is_not_reachable_from_any_route(client):
    paths = list(client.get("/openapi.json").json()["paths"])
    assert "/api/appointments" in paths
    assert not [p for p in paths if "reset" in p.lower() or "seed" in p.lower()]
    for path in ("/reset", "/api/reset", "/api/demo/reset", "/settings/reset"):
        assert client.post(path).status_code in (404, 405)
    for page in ("/", "/settings", "/assistant", "/call-demo"):
        assert "reset_demo" not in client.get(page).text


def test_reset_script_runs_against_a_demo_database(tmp_path):
    env = {"DATABASE_URL": f"sqlite:///{tmp_path / 'reset.db'}", "PATH": "/usr/bin:/bin"}
    cancelled = subprocess.run(
        [sys.executable, "scripts/reset_demo.py"], cwd=ROOT, env=env, input="no\n", capture_output=True, text=True
    )
    assert cancelled.returncode == 1
    assert "Demo data only — never run against real patient data." in cancelled.stdout
    assert "Nothing was changed" in cancelled.stdout

    done = subprocess.run(
        [sys.executable, "scripts/reset_demo.py", "--yes"], cwd=ROOT, env=env, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    assert "Demo reset complete" in done.stdout
    assert "doctors: 3" in done.stdout and "call logs: 0" in done.stdout

    refused = subprocess.run(
        [sys.executable, "scripts/reset_demo.py", "--yes"], cwd=ROOT,
        env={**env, "DATABASE_URL": "postgresql://example/production"}, capture_output=True, text=True,
    )
    assert refused.returncode == 2
    assert "Refusing to reset" in refused.stdout
