"""Phase 7: read-only patient timeline."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Appointment
from app.seed import reset_demo_data

from .test_assistant import Chat, slot_options
from .test_booking import book
from .test_call_demo import Call

SECRETS = ("SECRET-SUMMARY", "SECRET-FOLLOWUP", "SECRET-NOTE")


@pytest.fixture
def ticking(monkeypatch, tmp_path):
    """Seeded app whose clock moves forward one second every time it is read, starting
    Wednesday 14 Oct 2026 10:00, so every event has its own timestamp."""
    clock = {"now": datetime(2026, 10, 14, 10, 0)}

    def tick():
        clock["now"] += timedelta(seconds=1)
        return clock["now"]

    monkeypatch.setattr("app.utils.now", tick)
    return TestClient(create_app(f"sqlite:///{tmp_path / 'timeline.db'}"))


def timeline(client, patient_id, notifications=False):
    """A patient's timeline events. Outbox lines (Phase 10) are left out unless asked for,
    so these tests keep checking the clinical/operational sequence they were written for."""
    response = client.get(f"/api/patients/{patient_id}/timeline")
    assert response.status_code == 200
    return [e for e in response.json()["events"] if notifications or not e["kind"].startswith("NOTIFICATION_")]


def patient_id_for(client, mobile):
    return client.get("/api/patients", params={"q": mobile}).json()[0]["id"]


def ai_booking(client, name, mobile, day="2026-10-15"):
    chat = Chat(client)
    reply = chat.send("I want to book a consultation.")
    reply = chat.pick(reply, "New patient")
    chat.send(name)
    reply = chat.send(mobile)
    reply = chat.pick(reply, "Skip")
    reply = chat.pick(reply, "General Consultation")
    reply = chat.pick(reply, "Dr. Anika Rao")
    reply = chat.send(action="pick", value=day)
    reply = chat.send(action="slot", value=slot_options(reply)[0]["value"])
    return chat.pick(reply, "Confirm booking")["booking"]["reference"]


def doctor(client, appointment_id, action, **data):
    response = client.post(f"/doctor/1/appointments/{appointment_id}/{action}", data=data, follow_redirects=False)
    assert response.status_code == 303, response.text[:300]


def full_journey(client, name="Timeline Example", mobile="5556660001"):
    """Website AI booking -> reception confirms -> doctor sees the patient -> voice-demo callback -> reception calls back."""
    appointment_id = ai_booking(client, name, mobile)
    assert client.post(f"/api/appointments/{appointment_id}/status", json={"status": "CONFIRMED"}).status_code == 200
    doctor(client, appointment_id, "status", status="ARRIVED")
    doctor(client, appointment_id, "outcome", summary=SECRETS[0], next_step="PROCEDURE_DISCUSSION", follow_up_note=SECRETS[1])
    doctor(client, appointment_id, "status", status="COMPLETED")
    doctor(client, appointment_id, "recommendations", procedure="Aligner assessment", doctor_note=SECRETS[2])

    call = Call(client)
    call.shortcut("I want to speak to a person.")
    call.send(name)
    call.send(mobile)
    call.end()
    task = client.get("/api/callbacks").json()[-1]
    client.post(f"/api/callbacks/{task['id']}/status", json={"status": "IN_PROGRESS", "notes": "Rang, no answer"})
    client.post(f"/api/callbacks/{task['id']}/status", json={"status": "COMPLETED", "notes": "Spoke to patient"})
    return patient_id_for(client, mobile), appointment_id, task["id"], call.id


def test_events_are_listed_newest_first_with_their_source(ticking):
    patient_id, appointment_id, task_id, call_id = full_journey(ticking)
    events = timeline(ticking, patient_id)

    assert [(e["kind"], e["source_label"]) for e in events] == [
        ("CALLBACK_COMPLETED", "Staff"),
        ("CALLBACK_IN_PROGRESS", "Staff"),
        ("CALLBACK_CREATED", "Voice Demo"),
        ("CALL", "Voice Demo"),
        ("RECOMMENDATION_DRAFTED", "Doctor"),
        ("APPOINTMENT_COMPLETED", "Doctor"),
        ("OUTCOME_RECORDED", "Doctor"),
        ("APPOINTMENT_ARRIVED", "Doctor"),
        ("APPOINTMENT_CONFIRMED", "Staff"),
        ("APPOINTMENT_CREATED", "Website AI"),
        ("PATIENT_REGISTERED", "Website AI"),  # the assistant registered the patient as part of the booking
    ]
    stamps = [e["at"] for e in events]
    assert stamps == sorted(stamps, reverse=True) and len(set(stamps)) == len(stamps)
    assert not any(e["approximate"] for e in events)

    by_kind = {e["kind"]: e for e in events}
    assert by_kind["APPOINTMENT_CREATED"]["title"] == "Appointment booked"
    assert "General Consultation with Dr. Anika Rao on Thu, 15 Oct" in by_kind["APPOINTMENT_CREATED"]["detail"]
    assert by_kind["APPOINTMENT_CREATED"]["appointment_id"] == appointment_id
    assert by_kind["CALLBACK_CREATED"]["detail"] == "Asked to speak to a person."
    assert by_kind["CALLBACK_COMPLETED"]["detail"] == "Asked to speak to a person. Staff note: Spoke to patient"
    assert by_kind["CALL"]["call_log_id"] == call_id and "Callback created" in by_kind["CALL"]["detail"]
    assert "not a real phone call" in by_kind["CALL"]["detail"]
    assert by_kind["OUTCOME_RECORDED"]["detail"] == "Next step: Procedure discussion. Entered by the doctor."
    assert by_kind["RECOMMENDATION_DRAFTED"]["detail"].startswith("Aligner assessment · DRAFT.")

    # Links go to where reception can open the related record.
    assert by_kind["APPOINTMENT_CONFIRMED"]["link"] == f"/#appointment-{appointment_id}"
    assert by_kind["CALLBACK_IN_PROGRESS"]["link"] == "/#callback-tasks"
    assert by_kind["CALLBACK_IN_PROGRESS"]["link_label"] == f"Callback C-{task_id}"
    assert by_kind["CALL"]["link"] == "/#call-activity"
    dashboard = ticking.get("/").text
    assert f'id="appointment-{appointment_id}"' in dashboard and 'id="callback-tasks"' in dashboard and 'id="call-activity"' in dashboard


def test_timeline_hides_doctor_summary_and_notes_from_reception(ticking):
    patient_id, appointment_id, _, _ = full_journey(ticking)
    # The doctor did write them...
    saved = ticking.get(f"/api/appointments/{appointment_id}/consultation").json()
    assert saved["outcome"]["summary"] == SECRETS[0] and saved["recommendations"][0]["doctor_note"] == SECRETS[2]

    # ...but neither the page nor the JSON timeline carries them, only the next step and the procedure.
    page = ticking.get(f"/patients/{patient_id}/timeline")
    assert page.status_code == 200
    api = ticking.get(f"/api/patients/{patient_id}/timeline")
    for body in (page.text, api.text):
        for secret in SECRETS:
            assert secret not in body
    assert "Next step: Procedure discussion" in page.text
    assert "Aligner assessment · DRAFT" in page.text
    assert "not shown here" in page.text
    assert api.json()["read_only"] is True

    # Read-only: nothing to submit on the page, and no way to write to a timeline.
    assert "<form" not in page.text.split('id="main"')[1]
    assert ticking.post(f"/patients/{patient_id}/timeline").status_code == 405
    assert ticking.post(f"/api/patients/{patient_id}/timeline", json={}).status_code == 405
    for label in ("Staff", "Website AI", "Voice Demo", "Doctor"):
        assert f">{label}</span>" in page.text


def test_timeline_fills_in_after_booking_callback_and_doctor_outcome(ticking):
    patient = ticking.post("/api/patients", json={"name": "Step Example", "mobile": "5556660002"}).json()
    page = ticking.get(f"/patients/{patient['id']}/timeline").text
    assert "No activity yet for Step Example." in page  # useful empty state
    assert [(e["kind"], e["source_label"]) for e in timeline(ticking, patient["id"])] == [("PATIENT_REGISTERED", "Staff")]

    # Staff booking.
    slot = next(s for s in ticking.get("/api/doctors/1/slots", params={"date": "2026-10-16"}).json() if s["available"])
    booked = book(ticking, patient, slot, 1, reason="Front desk note").json()
    assert [(e["kind"], e["source_label"]) for e in timeline(ticking, patient["id"])] == [
        ("APPOINTMENT_CREATED", "Staff"), ("PATIENT_REGISTERED", "Staff"),
    ]
    assert "No activity yet" not in ticking.get(f"/patients/{patient['id']}/timeline").text

    # Website-assistant callback for the same mobile number joins the same timeline.
    chat = Chat(ticking)
    chat.send("Do you accept my insurance card?")
    chat.send("Step Example")
    chat.send("555 666 0002")
    kinds = [(e["kind"], e["source_label"]) for e in timeline(ticking, patient["id"])]
    assert kinds[0] == ("CALLBACK_CREATED", "Website AI")
    assert "insurance card" in timeline(ticking, patient["id"])[0]["detail"]

    # Doctor outcome after arrival.
    ticking.post(f"/api/appointments/{booked['id']}/status", json={"status": "CONFIRMED"})
    doctor(ticking, booked["id"], "status", status="ARRIVED")
    doctor(ticking, booked["id"], "outcome", summary="Private", next_step="FOLLOW_UP_CONSULTATION")
    kinds = [e["kind"] for e in timeline(ticking, patient["id"])]
    assert kinds == [
        "OUTCOME_RECORDED", "APPOINTMENT_ARRIVED", "APPOINTMENT_CONFIRMED", "CALLBACK_CREATED", "APPOINTMENT_CREATED",
        "PATIENT_REGISTERED",
    ]
    assert "Next step: Follow-up consultation" in ticking.get(f"/patients/{patient['id']}/timeline").text

    # Other patients' events never appear here.
    other = ticking.post("/api/patients", json={"name": "Other Example", "mobile": "5556660003"}).json()
    assert [e["kind"] for e in timeline(ticking, other["id"])] == ["PATIENT_REGISTERED"]


def test_cancel_and_no_show_are_recorded(ticking):
    patient = ticking.post("/api/patients", json={"name": "Change Example", "mobile": "5556660004"}).json()
    free = [s for s in ticking.get("/api/doctors/1/slots", params={"date": "2026-10-16"}).json() if s["available"]]
    first, second = (book(ticking, patient, s, 1).json() for s in free[:2])
    ticking.post(f"/api/appointments/{first['id']}/status", json={"status": "CANCELLED"})
    ticking.post(f"/api/appointments/{second['id']}/status", json={"status": "CONFIRMED"})
    doctor(ticking, second["id"], "status", status="NO_SHOW")

    events = timeline(ticking, patient["id"])
    assert [(e["kind"], e["source_label"]) for e in events[:3]] == [
        ("APPOINTMENT_NO_SHOW", "Doctor"), ("APPOINTMENT_CONFIRMED", "Staff"), ("APPOINTMENT_CANCELLED", "Staff"),
    ]
    cancelled = next(e for e in events if e["kind"] == "APPOINTMENT_CANCELLED")
    assert cancelled["link"] is None and cancelled["link_label"] == f"Booking #{first['id']}"  # no longer on the dashboard
    assert events[0]["title"] == "Marked as no-show"


def test_same_second_events_keep_their_logical_order(client, new_patient, free_slot, service_id):
    """With the real clock a booking and its confirmation can share a timestamp."""
    booked = book(client, new_patient, free_slot, service_id).json()
    client.post(f"/api/appointments/{booked['id']}/status", json={"status": "CONFIRMED"})
    assert [e["kind"] for e in timeline(client, new_patient["id"])] == [
        "APPOINTMENT_CONFIRMED", "APPOINTMENT_CREATED", "PATIENT_REGISTERED",
    ]


def test_status_changes_from_before_the_timeline_are_shown_without_a_time(client, new_patient, free_slot, service_id):
    booked = book(client, new_patient, free_slot, service_id).json()
    with client.app.state.session_factory() as db:  # as if confirmed before this feature existed
        db.get(Appointment, booked["id"]).status = "CONFIRMED"
        db.commit()
    events = timeline(client, new_patient["id"])
    assert [(e["kind"], e["approximate"]) for e in events] == [
        ("APPOINTMENT_CONFIRMED", True), ("APPOINTMENT_CREATED", False), ("PATIENT_REGISTERED", False),
    ]
    assert "Time not recorded" in client.get(f"/patients/{new_patient['id']}/timeline").text


def test_timeline_is_reachable_from_dashboard_and_patient_list(client, new_patient, free_slot, service_id):
    book(client, new_patient, free_slot, service_id)
    link = f'href="/patients/{new_patient["id"]}/timeline"'
    assert link in client.get("/").text
    assert link in client.get("/patients", params={"q": new_patient["mobile"]}).text
    page = client.get(f"/patients/{new_patient['id']}/timeline")
    assert page.status_code == 200
    assert "Patient timeline" in page.text and new_patient["name"] in page.text and "Demo data only" in page.text

    # Seeded patients get a timeline from their sample bookings.
    seeded = timeline(client, 1)
    assert [e["kind"] for e in seeded[-2:]] == ["APPOINTMENT_CREATED", "PATIENT_REGISTERED"]
    assert client.get("/patients/9999/timeline").status_code == 404
    assert client.get("/api/patients/9999/timeline").status_code == 404


def test_callback_task_on_dashboard_links_to_timeline_once_patient_exists(client, new_patient):
    chat = Chat(client)
    chat.send("I want to speak to a person.")
    chat.send(new_patient["name"])
    chat.send(new_patient["mobile"])
    section = client.get("/").text.split('id="callback-tasks"')[1].split("</section>")[0]
    assert f'href="/patients/{new_patient["id"]}/timeline"' in section


def test_demo_reset_clears_timeline_events(ticking):
    patient_id, *_ = full_journey(ticking)
    with ticking.app.state.session_factory() as db:
        reset_demo_data(db)
    assert ticking.get(f"/patients/{patient_id}/timeline").status_code == 404
    seeded = timeline(ticking, 1)
    assert [e["kind"] for e in seeded] == ["APPOINTMENT_CONFIRMED", "APPOINTMENT_CREATED", "PATIENT_REGISTERED"]  # seed confirms patient one


def test_patient_detail_page_and_view_timeline_action(ticking):
    patient_id, appointment_id, task_id, _ = full_journey(ticking)

    # Patients page: a "View timeline" action for every patient listed, and the name opens the record.
    listing = ticking.get("/patients").text
    shown = [p["id"] for p in ticking.get("/api/patients").json()]
    assert len(shown) >= 5
    for pid in shown:
        assert f'href="/patients/{pid}/timeline">View timeline</a>' in listing
        assert f'href="/patients/{pid}"' in listing

    # Detail route and timeline address show the same page, with a Timeline section.
    detail = ticking.get(f"/patients/{patient_id}")
    assert detail.status_code == 200
    assert detail.text == ticking.get(f"/patients/{patient_id}/timeline").text
    assert 'id="details"' in detail.text and 'id="timeline"' in detail.text
    assert 'href="#timeline">Timeline' in detail.text and "<h2>Timeline</h2>" in detail.text
    assert "Timeline Example" in detail.text and "5556660001" in detail.text
    assert "Doctor recommendation: Aligner assessment · DRAFT" in detail.text  # read-only marker in Details
    assert ticking.get("/patients/9999").status_code == 404
    assert ticking.post(f"/patients/{patient_id}", data={"name": "x"}).status_code == 405  # nothing to edit here

    # Every event carries an icon, a source, a timestamp, and a status where one applies.
    events = timeline(ticking, patient_id)
    assert all(e["icon"] and e["source_label"] and e["at"] and e["title"] for e in events)
    by_kind = {e["kind"]: e for e in events}
    assert {k: by_kind[k]["icon"] for k in ("PATIENT_REGISTERED", "APPOINTMENT_CREATED", "CALLBACK_CREATED", "CALL", "RECOMMENDATION_DRAFTED")} == {
        "PATIENT_REGISTERED": "person", "APPOINTMENT_CREATED": "calendar", "CALLBACK_CREATED": "callback",
        "CALL": "call", "RECOMMENDATION_DRAFTED": "doctor",
    }
    assert {k: by_kind[k]["status"] for k in (
        "APPOINTMENT_CREATED", "APPOINTMENT_CONFIRMED", "APPOINTMENT_ARRIVED", "APPOINTMENT_COMPLETED",
        "CALLBACK_CREATED", "CALLBACK_IN_PROGRESS", "CALLBACK_COMPLETED", "CALL", "RECOMMENDATION_DRAFTED", "OUTCOME_RECORDED",
    )} == {
        "APPOINTMENT_CREATED": "PENDING", "APPOINTMENT_CONFIRMED": "CONFIRMED", "APPOINTMENT_ARRIVED": "ARRIVED",
        "APPOINTMENT_COMPLETED": "COMPLETED", "CALLBACK_CREATED": "OPEN", "CALLBACK_IN_PROGRESS": "IN_PROGRESS",
        "CALLBACK_COMPLETED": "COMPLETED", "CALL": "CALLBACK_CREATED", "RECOMMENDATION_DRAFTED": "DRAFT", "OUTCOME_RECORDED": None,
    }
    assert detail.text.count('class="event-icon"') == len(timeline(ticking, patient_id, notifications=True))
    for secret in SECRETS:
        assert secret not in detail.text


def test_dashboard_recent_activity_links_to_the_right_patient_timeline(ticking):
    patient_id, *_ = full_journey(ticking)
    other = ticking.post("/api/patients", json={"name": "Later Example", "mobile": "5556660010"}).json()

    dashboard = ticking.get("/").text
    panel = dashboard.split('id="recent-activity"')[1].split("</section>")[0]
    assert "Recent patient activity" in panel
    rows = panel.split('<li class="activity')[1:]
    assert len(rows) == 6

    # Newest first: the patient registered last is on top, then the first patient's latest events.
    def link(row):
        return row.split('href="')[1].split('"')[0]

    assert link(rows[0]) == f"/patients/{other['id']}/timeline" and "Later Example" in rows[0] and "Patient registered" in rows[0]
    assert [link(r) for r in rows[1:5]] == [f"/patients/{patient_id}/timeline"] * 4
    assert ["Callback completed" in rows[1], "Callback started" in rows[2], "Callback requested" in rows[3], "Simulated AI call" in rows[4]] == [True] * 4
    assert "Voice Demo" in rows[3] and "Staff" in rows[1]
    for secret in SECRETS:
        assert secret not in dashboard

    # Each link opens that patient's timeline, and only theirs.
    opened = ticking.get(link(rows[1]))
    assert opened.status_code == 200 and "Timeline Example" in opened.text and "Later Example" not in opened.text
    assert "Callback completed" in opened.text
    opened_other = ticking.get(link(rows[0]))
    assert "Later Example" in opened_other.text and "Timeline Example" not in opened_other.text
    assert "No activity yet for Later Example." in opened_other.text


def test_dashboard_activity_panel_has_an_empty_state(ticking):
    from app.models import Appointment, Notification, Patient, TimelineEvent
    from sqlalchemy import delete

    with ticking.app.state.session_factory() as db:
        for model in (Notification, TimelineEvent, Appointment, Patient):
            db.execute(delete(model))
        db.commit()
    panel = ticking.get("/").text.split('id="recent-activity"')[1].split("</section>")[0]
    assert "No patient activity yet." in panel and "<li" not in panel
