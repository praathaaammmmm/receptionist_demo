"""Phase 12: procedure follow-up scheduler."""
import pytest

from app.models import ProcedureFollowup, TreatmentRecommendation
from app.seed import reset_demo_data

from .test_closed_days import WEDNESDAY, client_at  # noqa: F401  (fixture)
from .test_timeline import ticking  # noqa: F401  (fixture)

THURSDAY, FRIDAY = "2026-10-15", "2026-10-16"
SECRET_NOTE, SECRET_SUMMARY = "SECRET-DOCTOR-NOTE", "SECRET-DOCTOR-SUMMARY"


@pytest.fixture
def client(client_at):  # noqa: F811
    """Seeded app, clock fixed at Wednesday 14 Oct 2026, 10:00."""
    return client_at(WEDNESDAY)


def doctor_post(client, doctor_id, path, **data):
    return client.post(f"/doctor/{doctor_id}/{path}", data=data, follow_redirects=False)


def draft_recommendation(client, procedure="Implant consultation"):
    """Take the seeded confirmed booking (Demo Patient One, Dr. Anika Rao) through to a DRAFT recommendation."""
    seeded = next(a for a in client.get("/api/appointments", params={"scope": "today"}).json() if a["status"] == "CONFIRMED")
    appointment_id = seeded["id"]
    for path, data in (
        (f"appointments/{appointment_id}/status", {"status": "ARRIVED"}),
        (f"appointments/{appointment_id}/outcome", {"summary": SECRET_SUMMARY, "next_step": "PROCEDURE_DISCUSSION"}),
        (f"appointments/{appointment_id}/status", {"status": "COMPLETED"}),
        (f"appointments/{appointment_id}/recommendations", {"procedure": procedure, "doctor_note": SECRET_NOTE}),
    ):
        assert doctor_post(client, 1, path, **data).status_code == 303
    [recommendation] = client.get(f"/api/appointments/{appointment_id}/consultation").json()["recommendations"]
    return recommendation["id"], appointment_id, seeded["patient"]["id"]


def state(client, appointment_id):
    return client.get(f"/api/appointments/{appointment_id}/consultation").json()["recommendations"][0]


def ready(client, recommendation_id, doctor_id=1):
    return doctor_post(client, doctor_id, f"recommendations/{recommendation_id}/ready")


def free_slots(client, doctor_id=1, day=THURSDAY):
    return [s for s in client.get(f"/api/doctors/{doctor_id}/slots", params={"date": day}).json() if s["available"]]


def schedule(client, recommendation_id, slot_id, note=None):
    return client.post(f"/api/follow-ups/{recommendation_id}/schedule", json={"slot_id": slot_id, "note": note})


def all_appointments(client):
    return client.get("/api/appointments", params={"scope": "today"}).json() + client.get("/api/appointments").json()


def test_only_the_creating_doctor_can_mark_ready(client):
    recommendation_id, appointment_id, _ = draft_recommendation(client)
    assert state(client, appointment_id)["status"] == "DRAFT"

    other = ready(client, recommendation_id, doctor_id=2)
    assert other.status_code == 403 and "Only the doctor who created this recommendation" in other.text
    assert state(client, appointment_id)["status"] == "DRAFT"
    # Reception and the public have no route to release (or approve) a recommendation.
    for path in (f"/follow-ups/{recommendation_id}/ready", f"/api/follow-ups/{recommendation_id}/ready",
                 f"/api/recommendations/{recommendation_id}/ready", f"/recommendations/{recommendation_id}/ready"):
        assert client.post(path, json={}).status_code in (404, 405)
    assert state(client, appointment_id)["status"] == "DRAFT"

    released = ready(client, recommendation_id)
    assert released.status_code == 303 and "notice=recommendation_ready" in released.headers["location"]
    assert state(client, appointment_id)["status"] == "READY_FOR_SCHEDULING"
    again = ready(client, recommendation_id)
    assert again.status_code == 400 and "already been marked ready" in again.text
    assert ready(client, 9999).status_code == 404

    # Doctor workspace: the creating doctor gets the button on a draft, and sees the state afterwards.
    workspace = client.get(f"/doctor?doctor_id=1&appointment_id={appointment_id}").text
    assert "Ready for scheduling" in workspace and "Waiting for reception to book a follow-up." in workspace
    assert "Mark ready for scheduling" not in workspace


def test_reception_sees_only_the_operational_fields(client):
    recommendation_id, appointment_id, patient_id = draft_recommendation(client, "Aligner assessment")
    assert client.get("/api/follow-ups").json() == {"awaiting": [], "scheduled": []}  # drafts are not visible to reception here
    ready(client, recommendation_id)

    [item] = client.get("/api/follow-ups").json()["awaiting"]
    assert item == {
        "id": recommendation_id,
        "patient": {"id": patient_id, "name": "Demo Patient One"},
        "doctor": {"id": 1, "name": "Dr. Anika Rao"},
        "procedure": "Aligner assessment",
        "state": "READY_FOR_SCHEDULING",
        "state_label": "Ready for scheduling",
        "created_at": "2026-10-14T10:00:00",
        "followup_appointment_id": None,
        "followup_start_time": None,
    }
    menu = client.get("/").text.split('<nav class="nav"')[1].split("</nav>")[0]
    assert 'href="/follow-ups"' in menu and "<span>Follow-ups</span>" in menu
    staff_pages = [client.get(path).text for path in (
        "/follow-ups", f"/follow-ups?schedule={recommendation_id}", "/", f"/patients/{patient_id}", "/patients", "/analytics", "/notifications",
    )]
    page = staff_pages[0]
    assert "Procedure follow-ups" in page and "Aligner assessment" in page and "Demo Patient One" in page and "Dr. Anika Rao" in page
    assert "Ready for scheduling" in page and "recommended Wed, 14 Oct" in page
    for text in staff_pages + [client.get("/api/follow-ups").text, client.get(f"/api/patients/{patient_id}/timeline").text]:
        assert SECRET_NOTE not in text and SECRET_SUMMARY not in text
    # The note does exist: only the doctor workspace shows it.
    assert SECRET_NOTE in client.get(f"/doctor?doctor_id=1&appointment_id={appointment_id}").text
    # Reception cannot create or edit recommendations from this page.
    assert "doctor_note" not in page and 'name="procedure"' not in page


def test_staff_can_schedule_only_released_recommendations(client):
    recommendation_id, appointment_id, patient_id = draft_recommendation(client)
    slot = free_slots(client)[0]
    before = len(all_appointments(client))

    refused = schedule(client, recommendation_id, slot["id"])
    assert refused.status_code == 400 and "has not marked this recommendation ready" in refused.json()["message"]
    assert len(all_appointments(client)) == before and state(client, appointment_id)["status"] == "DRAFT"
    assert schedule(client, 9999, slot["id"]).status_code == 404

    ready(client, recommendation_id)
    booked = schedule(client, recommendation_id, slot["id"], note="  Patient prefers mornings  ")
    assert booked.status_code == 201
    followup = booked.json()
    assert followup["patient"]["id"] == patient_id and followup["doctor"]["id"] == 1 and followup["start_time"] == slot["start_time"]
    assert followup["status"] == "PENDING" and followup["source"] == "STAFF" and followup["service"]["name"] == "Dental Implants"
    assert followup["reason"] == (
        "Procedure discussion / follow-up: Implant consultation. A discussion appointment, not treatment delivery. "
        "Scheduling note: Patient prefers mornings"
    )
    assert len(all_appointments(client)) == before + 1

    # The recommendation is now SCHEDULED and linked to exactly that booking.
    linked = state(client, appointment_id)
    assert linked["status"] == "SCHEDULED" and linked["followup_appointment_id"] == followup["id"]
    listing = client.get("/api/follow-ups").json()
    assert listing["awaiting"] == [] and listing["scheduled"][0]["followup_appointment_id"] == followup["id"]
    assert listing["scheduled"][0]["followup_start_time"] == slot["start_time"]
    with client.app.state.session_factory() as db:
        link = db.query(ProcedureFollowup).one()
        assert (link.recommendation_id, link.appointment_id, link.staff_note) == (recommendation_id, followup["id"], "Patient prefers mornings")


def test_follow_up_uses_the_normal_booking_conflict_checks(client):
    recommendation_id, appointment_id, _ = draft_recommendation(client)
    ready(client, recommendation_id)
    slots = free_slots(client)
    before = len(all_appointments(client))

    # Someone else books the chosen slot first.
    client.post("/api/appointments", json={"patient_id": 2, "slot_id": slots[0]["id"], "service_id": 1})
    taken = schedule(client, recommendation_id, slots[0]["id"])
    assert taken.status_code == 409
    assert taken.json()["message"] == "This slot has just been booked. Please choose another available time."
    page = client.post(f"/follow-ups/{recommendation_id}/schedule", data={"slot_id": slots[0]["id"], "date": THURSDAY}, follow_redirects=False)
    assert page.status_code == 409 and "This slot has just been booked." in page.text and "Schedule: Implant consultation" in page.text

    # Another doctor's slot, a blocked time and a time that has passed are all refused too.
    wrong_doctor = schedule(client, recommendation_id, free_slots(client, doctor_id=2)[0]["id"])
    assert wrong_doctor.status_code == 400 and "must be booked with Dr. Anika Rao" in wrong_doctor.json()["message"]
    client.post("/doctor/1/blocks", data={"date": FRIDAY, "start_time": "", "end_time": "", "reason": "LEAVE"})
    friday = client.get("/api/doctors/1/slots", params={"date": FRIDAY}).json()[0]
    blocked = schedule(client, recommendation_id, friday["id"])
    assert blocked.status_code == 400 and "not available at that time" in blocked.json()["message"]
    past = client.get("/api/doctors/1/slots", params={"date": "2026-10-14"}).json()[0]
    assert schedule(client, recommendation_id, past["id"]).status_code == 400
    assert schedule(client, recommendation_id, 999999).status_code == 404

    # None of those created anything or changed the recommendation.
    assert len(all_appointments(client)) == before + 1  # only the other patient's booking
    assert state(client, appointment_id)["status"] == "READY_FOR_SCHEDULING"
    with client.app.state.session_factory() as db:
        assert db.query(ProcedureFollowup).count() == 0
    assert schedule(client, recommendation_id, slots[1]["id"]).status_code == 201  # a free slot still works


def test_duplicate_follow_up_is_refused(client):
    recommendation_id, appointment_id, _ = draft_recommendation(client)
    ready(client, recommendation_id)
    slots = free_slots(client)
    first = schedule(client, recommendation_id, slots[0]["id"]).json()
    before = len(all_appointments(client))

    for attempt in (schedule(client, recommendation_id, slots[1]["id"]),
                    client.post(f"/follow-ups/{recommendation_id}/schedule", data={"slot_id": slots[2]["id"], "date": THURSDAY}, follow_redirects=False)):
        assert attempt.status_code == 400 and "A follow-up is already booked for this recommendation." in attempt.text
    assert len(all_appointments(client)) == before
    assert state(client, appointment_id)["followup_appointment_id"] == first["id"]
    assert [s["available"] for s in client.get("/api/doctors/1/slots", params={"date": THURSDAY}).json() if s["id"] in (slots[1]["id"], slots[2]["id"])] == [True, True]
    with client.app.state.session_factory() as db:
        assert db.query(ProcedureFollowup).count() == 1
    # A scheduled recommendation cannot be released or re-drafted either.
    assert ready(client, recommendation_id).status_code == 400
    # The scheduling panel is not offered for it.
    assert "Book follow-up" not in client.get(f"/follow-ups?schedule={recommendation_id}").text


def test_timeline_dashboard_calendar_notifications_and_analytics_update(ticking):  # noqa: F811
    client = ticking
    recommendation_id, appointment_id, patient_id = draft_recommendation(client)

    def awaiting_on_dashboard():
        panel = client.get("/").text.split('id="followup-summary"')[1].split("</section>")[0]
        assert "Procedure follow-ups awaiting scheduling" in panel
        return int(panel.split("<dd>")[1].split("</dd>")[0])

    def analytics():
        return client.get("/api/analytics").json()["followups"]

    assert awaiting_on_dashboard() == 0
    assert {r["code"]: r["value"] for r in analytics()["states"]} == {"DRAFT": 1, "READY_FOR_SCHEDULING": 0, "SCHEDULED": 0}

    ready(client, recommendation_id)
    assert awaiting_on_dashboard() == 1 and analytics()["awaiting"] == 1 and analytics()["booked"] == 0

    slot = free_slots(client)[0]
    followup = schedule(client, recommendation_id, slot["id"]).json()
    assert awaiting_on_dashboard() == 0
    assert {r["code"]: r["value"] for r in analytics()["states"]} == {"DRAFT": 0, "READY_FOR_SCHEDULING": 0, "SCHEDULED": 1}
    assert analytics()["booked"] == 1

    # Timeline: the doctor released it, then staff scheduled it.
    events = [e for e in client.get(f"/api/patients/{patient_id}/timeline").json()["events"] if not e["kind"].startswith("NOTIFICATION_")]
    assert [(e["kind"], e["source_label"]) for e in events[:4]] == [
        ("FOLLOWUP_SCHEDULED", "Staff"), ("APPOINTMENT_CREATED", "Staff"), ("RECOMMENDATION_READY", "Doctor"), ("RECOMMENDATION_DRAFTED", "Doctor"),
    ]
    assert events[0]["title"] == "Procedure follow-up scheduled" and events[0]["appointment_id"] == followup["id"]
    assert events[0]["detail"] == "Procedure discussion / follow-up for Implant consultation: Thu, 15 Oct at 9:00 AM with Dr. Anika Rao"
    assert events[2]["title"] == "Doctor marked recommendation ready" and events[2]["icon"] == "doctor"
    assert events[2]["detail"] == "Implant consultation · ready for reception to schedule a follow-up"
    timeline_page = client.get(f"/patients/{patient_id}").text
    assert "Procedure follow-up scheduled" in timeline_page and "follow-up booked Thu, 15 Oct at 9:00 AM" in timeline_page
    assert SECRET_NOTE not in timeline_page and SECRET_SUMMARY not in timeline_page

    # Dashboard row, doctor workspace and calendar all show the linked follow-up; the doctor's view of it is read-only.
    row = client.get("/").text.split(f'id="appointment-{followup["id"]}"')[1].split("</tr>")[0]
    assert "Procedure discussion / follow-up" in row and "not treatment delivery" in row and "PENDING" in row
    workspace = client.get(f"/doctor?doctor_id=1&appointment_id={appointment_id}").text
    assert "Follow-up booked by reception: Thu, 15 Oct at 9:00 AM" in workspace and "(read-only)" in workspace
    assert f"/follow-ups/{recommendation_id}" not in workspace
    thursday = next(d for d in client.get("/api/doctors/1/schedule").json()["days"] if d["date"] == THURSDAY)
    assert any(e.get("appointment_id") == followup["id"] and e["status"] == "PENDING" for e in thursday["entries"])
    assert not [s for s in client.get("/api/doctors/1/slots", params={"date": THURSDAY}).json() if s["id"] == slot["id"] and s["available"]]

    # It is a normal booking: confirming it queues the usual confirmation, and it counts in the analytics funnel.
    created_before = client.get("/api/analytics").json()["headline"]["bookings"]
    client.post(f"/api/appointments/{followup['id']}/status", json={"status": "CONFIRMED"})
    confirmations = [n for n in client.get("/api/notifications", params={"type": "APPOINTMENT_CONFIRMATION"}).json() if n["appointment_id"] == followup["id"]]
    assert len(confirmations) == 1 and "Thu, 15 Oct at 9:00 AM with Dr. Anika Rao" in confirmations[0]["message"]
    assert SECRET_NOTE not in confirmations[0]["message"] and "Implant" not in confirmations[0]["message"]
    assert client.get("/api/analytics").json()["headline"]["bookings"] == created_before
    staff_source = next(s for s in client.get("/api/analytics").json()["sources"] if s["code"] == "STAFF")
    assert staff_source["confirmed"] >= 2
    page = client.get("/analytics").text
    assert "Procedure follow-ups" in page and SECRET_NOTE not in page and "Implant consultation" not in page.split('id="main"')[1]


def test_demo_reset_clears_follow_ups(client):
    recommendation_id, _, _ = draft_recommendation(client)
    ready(client, recommendation_id)
    schedule(client, recommendation_id, free_slots(client)[0]["id"])
    with client.app.state.session_factory() as db:
        reset_demo_data(db)
        assert db.query(ProcedureFollowup).count() == 0 and db.query(TreatmentRecommendation).count() == 0
    assert client.get("/follow-ups").status_code == 200
    assert "No procedure follow-ups are waiting." in client.get("/follow-ups").text
