"""Doctor-side "Confirm appointment": the assigned doctor confirms their own PENDING booking.

Clock fixed at Wednesday 14 Oct 2026, 10:00. Doctor 1 is Dr. Anika Rao, doctor 2 Dr. Vikram Shah.
"""
import pytest

from app.models import DoctorPatientNote, TimelineEvent

from .test_closed_days import WEDNESDAY, client_at  # noqa: F401  (fixture)
from .test_doctor_workspace import book_today, doctor_post, workspace

CONFIRM_PROMPT = "Confirm this appointment? Reception and the patient will see it as confirmed."
NOTE = "SECRET-CONFIRM-PRIVATE-NOTE"


@pytest.fixture
def client(client_at):  # noqa: F811
    return client_at(WEDNESDAY)


@pytest.fixture
def pending(client):
    """A new PENDING booking for doctor 1, today."""
    booked = book_today(client, "Paula Pending", "555 400 0001")
    assert booked["status"] == "PENDING"
    return booked


def confirm(client, appointment_id, doctor_id=1):
    return doctor_post(client, f"appointments/{appointment_id}/confirm", doctor_id)


def status_of(client, appointment_id):
    return client.get(f"/api/appointments/{appointment_id}/consultation").json()["status"]


def confirmations(client, appointment_id):
    return [n for n in client.get("/api/notifications").json()
            if n["appointment_id"] == appointment_id and n["type"] == "APPOINTMENT_CONFIRMATION"]


def confirmed_events(client, appointment_id):
    with client.app.state.session_factory() as db:
        return db.query(TimelineEvent).filter_by(appointment_id=appointment_id, kind="APPOINTMENT_CONFIRMED").all()


def panel(client, appointment_id, doctor_id=1):
    return workspace(client, doctor_id, appointment_id=appointment_id)


def test_pending_booking_offers_confirm_with_a_prompt(client, pending):
    text = panel(client, pending["id"])
    state = text.split('id="booking-state"')[1].split("</div>\n  </div>")[0]
    assert "Awaiting confirmation." in state
    assert f'action="/doctor/1/appointments/{pending["id"]}/confirm" data-confirm="{CONFIRM_PROMPT}"' in state
    assert '<button class="btn btn-sm btn-primary" type="submit">Confirm appointment</button>' in state
    # Today's pending bookings are listed on the workspace so the doctor can find them.
    listed = workspace(client).split('id="awaiting-confirmation"')[1].split("</ul>")[0]
    assert f'id="pending-{pending["id"]}"' in listed and "Paula Pending" in listed and "Confirm appointment" in listed


def test_assigned_doctor_confirms_and_every_view_follows(client, pending):
    before_analytics = {f["code"]: f["value"] for f in client.get("/api/analytics").json()["funnel"]}
    before_dashboard = client.get("/api/dashboard/summary").json()["pending_bookings"]

    done = confirm(client, pending["id"])
    assert done.status_code == 303 and "notice=doctor_confirmed" in done.headers["location"]
    assert status_of(client, pending["id"]) == "CONFIRMED"

    # Success feedback in the consultation panel, the next state and its next actions.
    text = client.get(done.headers["location"]).text
    assert "Appointment confirmed." in text.split('id="consultation-notice"')[1].split("</div>")[0]
    state = text.split('id="booking-state"')[1].split("</div>\n  </div>")[0]
    assert "Waiting for patient arrival/check-in." in state
    assert "Mark patient arrived" in state and "Open QR check-in" in state and "Confirm appointment" not in state

    # Doctor queue and calendar.
    day = workspace(client)
    assert f'id="queue-{pending["id"]}"' in day and f'id="pending-{pending["id"]}"' not in day
    calendar = client.get("/doctor/calendar", params={"doctor_id": 1}).text
    assert f'cal-appt is-confirmed" id="cal-appt-{pending["id"]}"' in calendar
    # Reception dashboard and analytics.
    assert client.get("/api/dashboard/summary").json()["pending_bookings"] == before_dashboard - 1
    row = client.get("/").text.split(f'id="appointment-{pending["id"]}"')[1].split("</tr>")[0]
    assert "pill-confirmed" in row
    after_analytics = {f["code"]: f["value"] for f in client.get("/api/analytics").json()["funnel"]}
    assert after_analytics["confirmed"] == before_analytics["confirmed"] + 1
    # Patient timeline: recorded once, by the doctor.
    events = client.get(f"/api/patients/{pending['patient']['id']}/timeline").json()["events"]
    [event] = [e for e in events if e["title"] == "Appointment confirmed"]
    assert event["source_label"] == "Doctor"
    # The simulated confirmation notification, once.
    assert len(confirmations(client, pending["id"])) == 1


def test_confirming_twice_changes_nothing_more(client, pending):
    assert "notice=doctor_confirmed" in confirm(client, pending["id"]).headers["location"]
    again = confirm(client, pending["id"])
    assert again.status_code == 303 and "notice=already_confirmed" in again.headers["location"]
    # Reception confirming afterwards is also a no-op.
    assert client.post(f"/api/appointments/{pending['id']}/status", json={"status": "CONFIRMED"}).status_code == 200
    assert len(confirmations(client, pending["id"])) == 1
    assert len(confirmed_events(client, pending["id"])) == 1


def test_another_doctor_cannot_confirm(client, pending):
    refused = confirm(client, pending["id"], doctor_id=2)
    assert refused.status_code == 403 and "another doctor" in refused.text
    assert status_of(client, pending["id"]) == "PENDING"
    assert confirmations(client, pending["id"]) == [] and confirmed_events(client, pending["id"]) == []
    # Doctor 2 is not offered the action for doctor 1's booking either.
    assert f'/appointments/{pending["id"]}/confirm' not in workspace(client, 2, appointment_id=pending["id"])


@pytest.mark.parametrize("statuses", [["CANCELLED"], ["CONFIRMED", "ARRIVED"], ["CONFIRMED", "NO_SHOW"],
                                      ["CONFIRMED", "ARRIVED", "COMPLETED"]])
def test_only_pending_bookings_can_be_confirmed(client, statuses):
    booked = book_today(client, "Late Larry", "555 400 0002", *statuses)
    refused = confirm(client, booked["id"])
    assert refused.status_code == 400 and "Only a pending appointment can be confirmed" in refused.text
    assert status_of(client, booked["id"]) == statuses[-1]
    assert "Confirm appointment</button>" not in panel(client, booked["id"])


def test_reception_confirm_is_unchanged_and_generic_doctor_status_still_refuses(client, pending):
    assert doctor_post(client, f"appointments/{pending['id']}/status", status="CONFIRMED").status_code == 403
    assert status_of(client, pending["id"]) == "PENDING"
    staff = client.post(f"/api/appointments/{pending['id']}/status", json={"status": "CONFIRMED"})
    assert staff.status_code == 200 and staff.json()["status"] == "CONFIRMED"
    assert len(confirmations(client, pending["id"])) == 1
    events = client.get(f"/api/patients/{pending['patient']['id']}/timeline").json()["events"]
    assert [e["source_label"] for e in events if e["title"] == "Appointment confirmed"] == ["Staff"]


def test_confirming_exposes_no_private_doctor_content(client, pending):
    with client.app.state.session_factory() as db:
        db.add(DoctorPatientNote(patient_id=pending["patient"]["id"], doctor_id=1, body=NOTE))
        db.commit()
    confirm(client, pending["id"])
    for path in ("/", f"/patients/{pending['patient']['id']}", "/api/notifications",
                 f"/api/patients/{pending['patient']['id']}/timeline", "/doctor/calendar?doctor_id=1"):
        assert NOTE not in client.get(path).text, path
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if p.endswith("/confirm")]  # a workspace form action, not a public API
