"""Consultation follow-ups: the doctor explicitly sends a follow-up to reception, with no
procedure recommendation. Also re-checks that the procedure-discussion path is unchanged."""
import pytest

from app.models import ConsultationFollowup
from app.seed import reset_demo_data

from .test_closed_days import WEDNESDAY, client_at  # noqa: F401  (fixture)
from .test_timeline import ticking  # noqa: F401  (fixture)

THURSDAY = "2026-10-15"
SUMMARY, NOTE, DOCTOR_NOTE = "SECRET-OUTCOME-SUMMARY", "SECRET-FOLLOWUP-NOTE", "SECRET-RECOMMENDATION-NOTE"
SEND = "Send follow-up to reception for scheduling"


@pytest.fixture
def client(client_at):  # noqa: F811
    """Seeded app, clock fixed at Wednesday 14 Oct 2026, 10:00."""
    return client_at(WEDNESDAY)


def doctor_post(client, doctor_id, path, **data):
    return client.post(f"/doctor/{doctor_id}/{path}", data=data, follow_redirects=False)


def seeded_consultation(client, next_step="FOLLOW_UP_CONSULTATION", complete=True):
    """The seeded confirmed booking (Demo Patient One, Dr. Anika Rao): arrived, outcome saved, optionally completed."""
    seeded = next(a for a in client.get("/api/appointments", params={"scope": "today"}).json() if a["status"] == "CONFIRMED")
    appointment_id = seeded["id"]
    assert doctor_post(client, 1, f"appointments/{appointment_id}/status", status="ARRIVED").status_code == 303
    assert doctor_post(client, 1, f"appointments/{appointment_id}/outcome", summary=SUMMARY, next_step=next_step, follow_up_note=NOTE).status_code == 303
    if complete:
        assert doctor_post(client, 1, f"appointments/{appointment_id}/status", status="COMPLETED").status_code == 303
    return appointment_id, seeded["patient"]["id"]


def send(client, appointment_id, doctor_id=1):
    return doctor_post(client, doctor_id, f"appointments/{appointment_id}/follow-up-request")


def workspace(client, appointment_id, doctor_id=1):
    return client.get(f"/doctor?doctor_id={doctor_id}&appointment_id={appointment_id}").text


def requests(client):
    return client.get("/api/follow-ups/consultation").json()


def free_slots(client, doctor_id=1, day=THURSDAY):
    return [s for s in client.get(f"/api/doctors/{doctor_id}/slots", params={"date": day}).json() if s["available"]]


def schedule(client, request_id, slot_id, note=None):
    return client.post(f"/api/follow-ups/consultation/{request_id}/schedule", json={"slot_id": slot_id, "note": note})


def test_saving_an_outcome_does_not_create_a_follow_up_request(client):
    appointment_id, _ = seeded_consultation(client)
    # Next step "Follow-up consultation" is saved and the consultation is completed, yet reception has nothing yet.
    assert requests(client) == {"awaiting": [], "scheduled": []}
    assert "No procedure follow-ups are waiting." in client.get("/follow-ups").text

    page = workspace(client, appointment_id)
    panel = page.split('id="follow-up-request"')[1].split("</div>")[0]
    assert "Saving an outcome does not ask reception to book anything." in panel  # the doctor is told plainly
    assert f">{SEND}</button>" in page
    assert f'action="/doctor/1/appointments/{appointment_id}/follow-up-request"' in page


def test_doctor_sends_a_consultation_follow_up_to_reception(client):
    appointment_id, patient_id = seeded_consultation(client)
    sent = send(client, appointment_id)
    assert sent.status_code == 303
    assert sent.headers["location"] == f"/doctor?doctor_id=1&appointment_id={appointment_id}&notice=followup_sent#consultation"
    after = client.get(sent.headers["location"]).text
    assert "Follow-up sent to reception." in after.split('id="consultation"')[1]
    assert "Sent to reception today" in after and "Waiting for reception to book it." in after
    assert f">{SEND}</button>" not in after  # it can only be sent once

    # Reception sees exactly: patient, doctor, the label, a doctor-approved state and the created date.
    [item] = requests(client)["awaiting"]
    assert item == {
        "id": item["id"],
        "patient": {"id": patient_id, "name": "Demo Patient One"},
        "doctor": {"id": 1, "name": "Dr. Anika Rao"},
        "label": "Consultation follow-up",
        "state": "READY_FOR_SCHEDULING",
        "state_label": "Ready for scheduling",
        "approved_by": "doctor",
        "created_at": "2026-10-14T10:00:00",
        "followup_appointment_id": None,
        "followup_start_time": None,
    }
    page = client.get("/follow-ups").text
    row = page.split(f'id="consultation-followup-{item["id"]}"')[1].split("</li>")[0]
    assert "Consultation follow-up" in row and "Demo Patient One" in row and "Dr. Anika Rao" in row
    assert "Ready for scheduling" in row and "Doctor-approved" in row and "sent by the doctor Wed, 14 Oct" in row
    assert "Schedule follow-up" in row and "kind=consultation" in row

    # No procedure recommendation was needed or created.
    assert client.get(f"/api/appointments/{appointment_id}/consultation").json()["recommendations"] == []
    assert client.get("/api/follow-ups").json() == {"awaiting": [], "scheduled": []}
    # Sending twice is refused.
    again = send(client, appointment_id)
    assert again.status_code == 400 and "already been sent to reception" in again.text
    with client.app.state.session_factory() as db:
        assert db.query(ConsultationFollowup).count() == 1


def test_follow_up_request_needs_a_completed_consultation_with_that_next_step(client):
    appointment_id, _ = seeded_consultation(client, complete=False)  # still ARRIVED
    early = send(client, appointment_id)
    assert early.status_code == 400 and "Mark the consultation completed before sending" in early.text
    page = workspace(client, appointment_id)
    assert f">{SEND}</button>" not in page
    assert "Mark the consultation completed, then you can send the follow-up to reception." in page

    # Another doctor cannot send it, and reception/public have no route for it.
    doctor_post(client, 1, f"appointments/{appointment_id}/status", status="COMPLETED")
    assert send(client, appointment_id, doctor_id=2).status_code == 403
    for path in (f"/follow-ups/consultation/{appointment_id}/request", f"/api/follow-ups/consultation/{appointment_id}/request",
                 f"/appointments/{appointment_id}/follow-up-request"):
        assert client.post(path, json={}).status_code in (404, 405)
    assert requests(client)["awaiting"] == []

    # A different next step does not offer or allow it.
    doctor_post(client, 1, f"appointments/{appointment_id}/outcome", summary=SUMMARY, next_step="NO_FOLLOW_UP")
    wrong_step = send(client, appointment_id)
    assert wrong_step.status_code == 400 and "next step “Follow-up consultation” first" in wrong_step.text
    assert f">{SEND}</button>" not in workspace(client, appointment_id)
    doctor_post(client, 1, f"appointments/{appointment_id}/outcome", summary=SUMMARY, next_step="FOLLOW_UP_CONSULTATION")
    assert send(client, appointment_id).status_code == 303


def test_reception_never_sees_the_doctors_summary_or_note(client):
    appointment_id, patient_id = seeded_consultation(client)
    send(client, appointment_id)
    request_id = requests(client)["awaiting"][0]["id"]
    for path in ("/follow-ups", f"/follow-ups?schedule={request_id}&kind=consultation", "/", f"/patients/{patient_id}", "/patients",
                 "/analytics", "/notifications", "/api/follow-ups/consultation", f"/api/patients/{patient_id}/timeline", "/api/analytics"):
        text = client.get(path).text
        assert SUMMARY not in text and NOTE not in text, path
    assert SUMMARY in workspace(client, appointment_id)  # the doctor still sees their own text


def test_reception_schedules_it_with_normal_booking_rules(client):
    appointment_id, patient_id = seeded_consultation(client)
    send(client, appointment_id)
    request_id = requests(client)["awaiting"][0]["id"]
    slots = free_slots(client)
    panel = client.get(f"/follow-ups?schedule={request_id}&kind=consultation").text.split('id="schedule"')[1]
    assert "Schedule: Consultation follow-up" in panel and f'action="/follow-ups/consultation/{request_id}/schedule"' in panel

    # The usual refusals: slot just taken, another doctor's slot, a time that has passed.
    client.post("/api/appointments", json={"patient_id": 2, "slot_id": slots[0]["id"], "service_id": 1})
    taken = schedule(client, request_id, slots[0]["id"])
    assert taken.status_code == 409 and taken.json()["message"] == "This slot has just been booked. Please choose another available time."
    page = client.post(f"/follow-ups/consultation/{request_id}/schedule", data={"slot_id": slots[0]["id"], "date": THURSDAY}, follow_redirects=False)
    assert page.status_code == 409 and "This slot has just been booked." in page.text and "Schedule: Consultation follow-up" in page.text
    assert schedule(client, request_id, free_slots(client, doctor_id=2)[0]["id"]).status_code == 400
    assert schedule(client, request_id, client.get("/api/doctors/1/slots", params={"date": "2026-10-14"}).json()[0]["id"]).status_code == 400
    assert requests(client)["awaiting"][0]["state"] == "READY_FOR_SCHEDULING"

    booked = schedule(client, request_id, slots[1]["id"], note="Call the day before")
    assert booked.status_code == 201
    followup = booked.json()
    assert followup["patient"]["id"] == patient_id and followup["doctor"]["id"] == 1 and followup["start_time"] == slots[1]["start_time"]
    assert followup["status"] == "PENDING" and followup["source"] == "STAFF"
    assert followup["reason"] == "Consultation follow-up, requested by the doctor. Scheduling note: Call the day before"
    listing = requests(client)
    assert listing["awaiting"] == [] and listing["scheduled"][0]["followup_appointment_id"] == followup["id"]
    assert listing["scheduled"][0]["state"] == "SCHEDULED"

    # One follow-up per request.
    again = schedule(client, request_id, slots[2]["id"])
    assert again.status_code == 400 and "already booked" in again.json()["message"]
    assert schedule(client, 9999, slots[2]["id"]).status_code == 404
    # The doctor sees the booking read-only.
    assert f"Follow-up booked by reception: Thu, 15 Oct at {slots[1]['start_label']}" in workspace(client, appointment_id)


def test_timeline_calendar_dashboard_notifications_and_analytics_update(ticking):  # noqa: F811
    client = ticking
    appointment_id, patient_id = seeded_consultation(client)

    def dashboard_counts():
        panel = client.get("/").text.split('id="followup-summary"')[1].split("</section>")[0]
        assert "Consultation follow-ups awaiting scheduling" in panel
        return [int(x.split("</dd>")[0]) for x in panel.split("<dd>")[1:]]  # [procedure, consultation]

    def analytics():
        return client.get("/api/analytics").json()["followups"]["consultation"]

    assert dashboard_counts() == [0, 0] and analytics() == {"requested": 0, "awaiting": 0, "scheduled": 0}
    send(client, appointment_id)
    assert dashboard_counts() == [0, 1] and analytics() == {"requested": 1, "awaiting": 1, "scheduled": 0}

    request_id = requests(client)["awaiting"][0]["id"]
    slot = free_slots(client)[0]
    followup = schedule(client, request_id, slot["id"]).json()
    assert dashboard_counts() == [0, 0] and analytics() == {"requested": 1, "awaiting": 0, "scheduled": 1}

    events = [e for e in client.get(f"/api/patients/{patient_id}/timeline").json()["events"] if not e["kind"].startswith("NOTIFICATION_")]
    assert [(e["kind"], e["source_label"]) for e in events[:4]] == [
        ("CONSULTATION_FOLLOWUP_SCHEDULED", "Staff"), ("APPOINTMENT_CREATED", "Staff"),
        ("FOLLOWUP_REQUESTED", "Doctor"), ("APPOINTMENT_COMPLETED", "Doctor"),
    ]
    assert events[0]["title"] == "Consultation follow-up scheduled" and events[0]["appointment_id"] == followup["id"]
    assert events[0]["detail"] == "Consultation follow-up: Thu, 15 Oct at 9:00 AM with Dr. Anika Rao"
    assert events[2]["title"] == "Doctor sent follow-up to reception" and events[2]["icon"] == "doctor"
    assert events[2]["detail"] == "Consultation follow-up · sent to reception for scheduling"

    # Dashboard row, patient page and calendar.
    row = client.get("/").text.split(f'id="appointment-{followup["id"]}"')[1].split("</tr>")[0]
    assert "Consultation follow-up" in row and "PENDING" in row
    patient_page = client.get(f"/patients/{patient_id}").text
    assert "Consultation follow-up scheduled" in patient_page and SUMMARY not in patient_page and NOTE not in patient_page
    thursday = next(d for d in client.get("/api/doctors/1/schedule").json()["days"] if d["date"] == THURSDAY)
    assert any(e.get("appointment_id") == followup["id"] for e in thursday["entries"])
    assert not [s for s in client.get("/api/doctors/1/slots", params={"date": THURSDAY}).json() if s["id"] == slot["id"] and s["available"]]

    # A normal booking: confirming queues the usual confirmation; analytics page shows the counts without clinical text.
    client.post(f"/api/appointments/{followup['id']}/status", json={"status": "CONFIRMED"})
    confirmations = [n for n in client.get("/api/notifications", params={"type": "APPOINTMENT_CONFIRMATION"}).json() if n["appointment_id"] == followup["id"]]
    assert len(confirmations) == 1 and SUMMARY not in confirmations[0]["message"] and NOTE not in confirmations[0]["message"]
    page = client.get("/analytics").text
    assert "Consultation follow-ups" in page and "Sent to reception" in page and SUMMARY not in page


def test_procedure_discussion_workflow_is_unchanged(client):
    """Draft recommendation -> Mark ready for scheduling -> Procedure discussion follow-up, alongside the new path."""
    appointment_id, patient_id = seeded_consultation(client, next_step="PROCEDURE_DISCUSSION")
    page = workspace(client, appointment_id)
    assert f">{SEND}</button>" not in page  # the consultation path is not offered for a procedure discussion
    assert "use “Draft treatment recommendation” and mark it ready" in page

    assert doctor_post(client, 1, f"appointments/{appointment_id}/recommendations", procedure="Implant consultation", doctor_note=DOCTOR_NOTE).status_code == 303
    recommendation = client.get(f"/api/appointments/{appointment_id}/consultation").json()["recommendations"][0]
    assert recommendation["status"] == "DRAFT" and client.get("/api/follow-ups").json()["awaiting"] == []
    assert doctor_post(client, 1, f"recommendations/{recommendation['id']}/ready").status_code == 303
    [item] = client.get("/api/follow-ups").json()["awaiting"]
    assert item["procedure"] == "Implant consultation" and item["state"] == "READY_FOR_SCHEDULING"
    assert requests(client) == {"awaiting": [], "scheduled": []}  # it did not become a consultation follow-up

    listing = client.get("/follow-ups").text
    assert "Implant consultation" in listing and "recommended Wed, 14 Oct" in listing and DOCTOR_NOTE not in listing
    booked = client.post(f"/api/follow-ups/{recommendation['id']}/schedule", json={"slot_id": free_slots(client)[0]["id"]})
    assert booked.status_code == 201
    assert booked.json()["reason"].startswith("Procedure discussion / follow-up: Implant consultation.")
    assert client.get(f"/api/appointments/{appointment_id}/consultation").json()["recommendations"][0]["status"] == "SCHEDULED"
    kinds = [e["kind"] for e in client.get(f"/api/patients/{patient_id}/timeline").json()["events"]]
    assert "FOLLOWUP_SCHEDULED" in kinds and "RECOMMENDATION_READY" in kinds and "FOLLOWUP_REQUESTED" not in kinds


def test_both_kinds_share_receptions_list_and_reset_clears_them(client):
    appointment_id, _ = seeded_consultation(client)
    send(client, appointment_id)
    doctor_post(client, 1, f"appointments/{appointment_id}/recommendations", procedure="Aligner assessment")
    recommendation = client.get(f"/api/appointments/{appointment_id}/consultation").json()["recommendations"][0]
    doctor_post(client, 1, f"recommendations/{recommendation['id']}/ready")

    page = client.get("/follow-ups").text
    awaiting = page.split('id="awaiting"')[1].split("</section>")[0]
    assert awaiting.count('class="followup ') == 2 and "Consultation follow-up" in awaiting and "Aligner assessment" in awaiting
    panel = client.get("/").text.split('id="followup-summary"')[1].split("</section>")[0]
    assert [int(x.split("</dd>")[0]) for x in panel.split("<dd>")[1:]] == [1, 1]

    with client.app.state.session_factory() as db:
        reset_demo_data(db)
        assert db.query(ConsultationFollowup).count() == 0
    assert requests(client) == {"awaiting": [], "scheduled": []}
