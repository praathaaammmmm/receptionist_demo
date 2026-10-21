"""Doctor-side manual arrival (demo): the assigned doctor marks their CONFIRMED patient as arrived.

Clock fixed at Wednesday 14 Oct 2026, 10:00. Doctor 1 is Dr. Anika Rao; the seeded confirmed booking
today is Demo Patient One at 11:00.
"""
import pytest

from app.models import Appointment, TimelineEvent

from .test_checkin import arrive, token_for
from .test_closed_days import WEDNESDAY, client_at  # noqa: F401  (fixture)
from .test_doctor_workspace import book_today, doctor_post, workspace

PROMPT = "Mark this patient as arrived? Use this only when the patient is physically present."
DEMO_NOTE = ("For this demo, the doctor can manually mark a confirmed patient as arrived. "
             "In production, reception check-in or QR scanning can be the standard process.")


@pytest.fixture
def client(client_at):  # noqa: F811
    return client_at(WEDNESDAY)


@pytest.fixture
def confirmed(client):
    return book_today(client, "Arun Arrives", "555 500 0001", "CONFIRMED")


def mark_arrived(client, appointment_id, doctor_id=1):
    return doctor_post(client, f"appointments/{appointment_id}/status", doctor_id, status="ARRIVED")


def status_of(client, appointment_id):
    return client.get(f"/api/appointments/{appointment_id}/consultation").json()["status"]


def timeline(client, patient_id):
    return [e for e in client.get(f"/api/patients/{patient_id}/timeline").json()["events"] if not e["kind"].startswith("NOTIFICATION_")]


def state_block(text):
    return text.split('id="booking-state"')[1].split('<div class="consult-grid">')[0]


def test_confirmed_appointment_offers_mark_patient_arrived_with_prompt_and_demo_note(client, confirmed):
    block = state_block(workspace(client, appointment_id=confirmed["id"]))
    assert f'action="/doctor/1/appointments/{confirmed["id"]}/status" data-confirm="{PROMPT}"' in block
    assert '<button class="btn btn-sm btn-primary" type="submit">Mark patient arrived</button>' in block
    assert DEMO_NOTE in block


def test_assigned_doctor_marks_arrived_and_every_view_follows(client, confirmed):
    appointment_id, patient_id = confirmed["id"], confirmed["patient"]["id"]
    before = {f["code"]: f["value"] for f in client.get("/api/analytics").json()["funnel"]}

    done = mark_arrived(client, appointment_id)
    assert done.status_code == 303 and "notice=arrived_by_doctor" in done.headers["location"]
    assert status_of(client, appointment_id) == "ARRIVED"
    with client.app.state.session_factory() as db:
        a = db.get(Appointment, appointment_id)
        assert (a.arrived_at, a.arrived_by) == (WEDNESDAY, "DOCTOR")

    # Success message beside the action, and the next steps are open.
    text = client.get(done.headers["location"]).text
    assert "Patient marked arrived." in text.split('id="consultation-notice"')[1].split("</div>")[0]
    block = state_block(text)
    assert "Marked arrived by doctor 10:00 AM" in block
    assert "Start consultation" in block and "Save consultation outcome" in block and "Send follow-up to reception" in block
    assert "Mark patient arrived" not in block
    assert 'name="summary"' in text  # the outcome form is available once arrived
    assert f'/appointments/{appointment_id}/care/follow-up" class="form send-to-reception"' in text

    # Timeline: the doctor's arrival, and no QR event.
    events = timeline(client, patient_id)
    [arrived] = [e for e in events if e["kind"] == "APPOINTMENT_ARRIVED"]
    assert arrived["title"] == "Patient marked arrived by Dr. Anika Rao" and arrived["source_label"] == "Doctor"
    assert arrived["detail"].startswith("Marked arrived by doctor.")
    assert not [e for e in events if e["kind"] == "QR_CHECKIN"]
    with client.app.state.session_factory() as db:
        assert db.query(TimelineEvent).filter_by(kind="QR_CHECKIN").count() == 0
    assert "Patient marked arrived by Dr. Anika Rao" in client.get(f"/patients/{patient_id}").text

    # Queue, calendar, reception dashboard and analytics.
    queue = workspace(client).split(f'id="queue-{appointment_id}"')[1].split("</tr>")[0]
    assert "pill-arrived" in queue and "Marked arrived by doctor" in queue and "Start consultation" in queue
    assert f'cal-appt is-arrived" id="cal-appt-{appointment_id}"' in client.get("/doctor/calendar", params={"doctor_id": 1}).text
    row = client.get("/").text.split(f'id="appointment-{appointment_id}"')[1].split("</tr>")[0]
    assert "pill-arrived" in row
    after = {f["code"]: f["value"] for f in client.get("/api/analytics").json()["funnel"]}
    assert after["arrived"] == before["arrived"] + 1

    # The rest of the journey works: start, outcome, follow-up to reception.
    assert doctor_post(client, f"appointments/{appointment_id}/start").status_code == 303
    assert doctor_post(client, f"appointments/{appointment_id}/care/follow-up", timeframe="WEEK_1").status_code == 303
    [item] = client.get("/api/follow-ups/consultation").json()["awaiting"]
    assert item["patient"]["id"] == patient_id


def test_another_doctor_cannot_mark_arrived(client, confirmed):
    refused = mark_arrived(client, confirmed["id"], doctor_id=2)
    assert refused.status_code == 403
    assert status_of(client, confirmed["id"]) == "CONFIRMED"


def test_pending_must_be_confirmed_first(client):
    pending = book_today(client, "Pia Pending", "555 500 0002")
    refused = mark_arrived(client, pending["id"])
    assert refused.status_code == 400 and "Confirm this appointment before marking the patient arrived." in refused.text
    assert status_of(client, pending["id"]) == "PENDING"
    assert "Mark patient arrived</button>" not in state_block(workspace(client, appointment_id=pending["id"]))


@pytest.mark.parametrize("statuses", [["CANCELLED"], ["CONFIRMED", "NO_SHOW"], ["CONFIRMED", "ARRIVED", "COMPLETED"]])
def test_not_available_after_cancel_no_show_or_completion(client, statuses):
    booked = book_today(client, "Nia Nope", "555 500 0003", *statuses)
    assert mark_arrived(client, booked["id"]).status_code == 400
    assert status_of(client, booked["id"]) == statuses[-1]
    assert "Mark patient arrived" not in workspace(client, appointment_id=booked["id"]).split('id="consultation"')[1]


def test_qr_check_in_is_unchanged_and_labelled_apart(client):
    seeded = next(a for a in client.get("/api/appointments", params={"scope": "today"}).json() if a["status"] == "CONFIRMED")
    assert arrive(client, token_for(client, seeded["id"]))["state"] == "CHECKED_IN"
    assert status_of(client, seeded["id"]) == "ARRIVED"
    events = timeline(client, seeded["patient"]["id"])
    [qr] = [e for e in events if e["kind"] == "QR_CHECKIN"]
    assert qr["title"] == "QR check-in at reception" and qr["source_label"] == "Staff"
    [arrived] = [e for e in events if e["kind"] == "APPOINTMENT_ARRIVED"]
    assert arrived["title"] == "Patient arrived" and "by Dr." not in arrived["title"]
    block = state_block(workspace(client, appointment_id=seeded["id"]))
    assert "QR check-in 10:00 AM" in block and "Marked arrived by doctor" not in block
