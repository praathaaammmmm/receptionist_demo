"""Doctor workspace: daily summary, next patient, filterable queue, consultation lifecycle,
follow-up handoff, operational patient context and calendar links.

Clock fixed at Wednesday 14 Oct 2026, 10:00. Doctor 1 is Dr. Anika Rao; the seeded confirmed
booking for today is Demo Patient One.
"""
import re
from datetime import datetime, timedelta

import pytest

from app.models import Appointment, ConsultationStart, Slot

from .test_closed_days import WEDNESDAY, client_at  # noqa: F401  (fixture)

TODAY = "2026-10-14"
SUMMARY, NOTE, DOCTOR_NOTE = "SECRET-WS-SUMMARY", "SECRET-WS-NOTE", "SECRET-WS-RECOMMENDATION-NOTE"


@pytest.fixture
def client(client_at):  # noqa: F811
    return client_at(WEDNESDAY)


def doctor_post(client, path, doctor_id=1, **data):
    return client.post(f"/doctor/{doctor_id}/{path}", data=data, follow_redirects=False)


def free_slots(client, doctor_id=1, day=TODAY):
    return [s for s in client.get(f"/api/doctors/{doctor_id}/slots", params={"date": day}).json() if s["available"]]


def new_patient(client, name, mobile):
    response = client.post("/api/patients", json={"name": name, "mobile": mobile})
    assert response.status_code == 201
    return response.json()["id"]


def book_today(client, name, mobile, *statuses, doctor_id=1, slot_index=0):
    patient_id = new_patient(client, name, mobile)
    slot = free_slots(client, doctor_id)[slot_index]
    booked = client.post("/api/appointments", json={"patient_id": patient_id, "slot_id": slot["id"], "service_id": 1}).json()
    for status in statuses:
        assert client.post(f"/api/appointments/{booked['id']}/status", json={"status": status}).status_code == 200, status
    return booked


def start(client, appointment_id, doctor_id=1):
    return doctor_post(client, f"appointments/{appointment_id}/start", doctor_id)


def workspace(client, doctor_id=1, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"/doctor?doctor_id={doctor_id}{'&' + query if query else ''}").text


def counts(page):
    return {key: int(n) for key, n in re.findall(r'show=(\w+)#queue"><strong>(\d+)</strong>', page)}


def queue_names(page):
    table = page.split('id="queue"')[1].split("</table>")[0]
    return re.findall(r'title="Open consultation">([^<]+)</a>', table)


def next_card(page):
    return page.split('class="next-patient')[1].split("</article>")[0]


@pytest.fixture
def day(client):
    """A full day for doctor 1: one per stage, plus the seeded confirmed booking (Demo Patient One)."""
    waiting = book_today(client, "Wanda Waiting", "555 300 0001", "CONFIRMED", "ARRIVED")
    seeing = book_today(client, "Ivan Inside", "555 300 0002", "CONFIRMED", "ARRIVED")
    done = book_today(client, "Cora Complete", "555 300 0003", "CONFIRMED", "ARRIVED", "COMPLETED")
    absent = book_today(client, "Nell Noshow", "555 300 0004", "CONFIRMED", "NO_SHOW")
    assert start(client, seeing["id"]).status_code == 303
    return {"waiting": waiting, "seeing": seeing, "done": done, "absent": absent}


def test_daily_counts_and_filters(client, day):
    page = workspace(client)
    assert counts(page) == {"upcoming": 1, "waiting": 1, "in_consultation": 1, "completed": 1, "no_show": 1}
    assert len(queue_names(page)) == 5  # "All today"

    expected = {
        "upcoming": ["Demo Patient One"], "waiting": ["Wanda Waiting"], "in_consultation": ["Ivan Inside"],
        "completed": ["Cora Complete"], "no_show": ["Nell Noshow"],
    }
    for show, names in expected.items():
        filtered = workspace(client, show=show)
        assert queue_names(filtered) == names, show
        active = filtered.split('class="filter-tabs"')[1].split("</nav>")[0]
        assert re.search(rf'class="filter-tab is-active" aria-current="page" href="[^"]*show={show}#queue"', active)
    # An unknown filter falls back to everything rather than an error.
    assert len(queue_names(workspace(client, show="nonsense"))) == 5


def test_next_patient_prefers_the_one_in_consultation_then_waiting_then_upcoming(client, day):
    card = next_card(workspace(client))
    assert "With you now" in card and "Ivan Inside" in card
    assert "Write outcome" in card and "Complete consultation" in card

    doctor_post(client, f"appointments/{day['seeing']['id']}/status", status="COMPLETED")
    card = next_card(workspace(client))
    assert "Next patient" in card and "Wanda Waiting" in card
    assert ">Start consultation</button>" in card  # Arrived → Start consultation

    doctor_post(client, f"appointments/{day['waiting']['id']}/status", status="NO_SHOW")
    card = next_card(workspace(client))
    assert "Demo Patient One" in card and ">Mark arrived</button>" in card  # Confirmed → Mark arrived


def test_next_patient_card_masks_the_mobile_and_shows_operational_flags_only(client, day):
    card = next_card(workspace(client))
    assert "••••••0002" in card and "5553000002" not in card
    for label in ("Time", "Service", "Booked via", "Arrival", "Stage"):
        assert f"<dt>{label}</dt>" in card
    assert "STAFF" in card  # booking source badge


def test_flags_show_open_callback_previous_no_show_and_waitlist_origin(client):
    booked = book_today(client, "Flora Flags", "555 300 0010", "CONFIRMED")
    client.post("/api/callbacks", json={"name": "Flora Flags", "mobile": "555 300 0010", "reason": "Asked about parking"})
    with client.app.state.session_factory() as db:  # an earlier missed visit for the same patient
        past = datetime(2026, 10, 12, 11, 0)
        slot = Slot(doctor_id=2, start_time=past, end_time=past + timedelta(minutes=45))
        db.add(slot)
        db.add(Appointment(patient_id=booked["patient"]["id"], doctor_id=2, service_id=1, start_time=past,
                           end_time=past + timedelta(minutes=45), status="NO_SHOW"))
        db.commit()
    row = workspace(client).split(f'id="queue-{booked["id"]}"')[1].split("</tr>")[0]
    assert "Open callback" in row and "Previous no-show" in row
    assert "Asked about parking" not in row  # the callback reason itself is not shown


def test_start_consultation_lifecycle(client, day):
    confirmed = next(a for a in client.get("/api/appointments", params={"scope": "today"}).json()
                     if a["status"] == "CONFIRMED" and a["doctor"]["id"] == 1)
    early = start(client, confirmed["id"])
    assert early.status_code == 400 and "once the patient has arrived" in early.text

    waiting_id = day["waiting"]["id"]
    assert start(client, waiting_id, doctor_id=2).status_code == 403  # another doctor's patient
    started = start(client, waiting_id)
    assert started.status_code == 303
    assert started.headers["location"] == f"/doctor?doctor_id=1&appointment_id={waiting_id}&notice=consultation_started#consultation"
    assert start(client, waiting_id).status_code == 400  # only once

    # The appointment status stays ARRIVED for reception; the stage is the workspace's own.
    assert client.get(f"/api/appointments/{waiting_id}/consultation").json()["status"] == "ARRIVED"
    page = workspace(client, appointment_id=waiting_id)
    assert "Consultation · In consultation" in page
    assert re.search(r'<li class=" is-current" aria-current="step">In consultation</li>', page)

    # Outcome can be saved while in consultation, then completed, then still corrected.
    assert doctor_post(client, f"appointments/{waiting_id}/outcome", summary=SUMMARY, next_step="NO_FOLLOW_UP").status_code == 303
    assert doctor_post(client, f"appointments/{waiting_id}/status", status="COMPLETED").status_code == 303
    assert doctor_post(client, f"appointments/{waiting_id}/outcome", summary="Corrected", next_step="NO_FOLLOW_UP").status_code == 303
    assert client.get(f"/api/appointments/{waiting_id}/consultation").json()["outcome"]["summary"] == "Corrected"
    assert start(client, waiting_id).status_code == 400  # a completed visit cannot be started again

    # Starting is recorded on the staff-safe timeline, without clinical text.
    events = client.get(f"/api/patients/{day['waiting']['patient']['id']}/timeline").json()
    titles = [e["title"] for e in (events["events"] if isinstance(events, dict) else events)]
    assert "Consultation started" in titles


def test_completing_without_an_outcome_asks_a_clearer_question(client, day):
    page = workspace(client, appointment_id=day["seeing"]["id"])
    complete = page.split('id="consultation"')[1]
    complete = complete[complete.rindex("<form", 0, complete.index('value="COMPLETED"')):complete.index('value="COMPLETED"')]
    assert "No consultation outcome has been saved" in complete

    doctor_post(client, f"appointments/{day['seeing']['id']}/outcome", summary=SUMMARY, next_step="NO_FOLLOW_UP")
    page = workspace(client, appointment_id=day["seeing"]["id"]).split('id="consultation"')[1]
    complete = page[page.rindex("<form", 0, page.index('value="COMPLETED"')):page.index('value="COMPLETED"')]
    assert "No consultation outcome" not in complete and "This cannot be undone." in complete


def test_doctor_cannot_open_or_act_on_another_doctors_appointment(client, day):
    seeing = day["seeing"]["id"]
    page = workspace(client, doctor_id=2, appointment_id=seeing)
    assert 'id="consultation"' not in page and "Ivan Inside" not in page
    for path, data in ((f"appointments/{seeing}/start", {}), (f"appointments/{seeing}/status", {"status": "COMPLETED"}),
                       (f"appointments/{seeing}/outcome", {"summary": "x", "next_step": "NO_FOLLOW_UP"}),
                       (f"appointments/{seeing}/follow-up-request", {})):
        assert doctor_post(client, path, doctor_id=2, **data).status_code == 403, path
    # The calendar does not highlight another doctor's appointment either.
    assert "is-current" not in client.get(f"/doctor/calendar?doctor_id=2&appointment_id={seeing}").text.split('class="cal"')[1]


def test_previous_and_next_patient_navigation(client, day):
    order = [a["id"] for a in sorted(
        (a for a in client.get("/api/appointments", params={"scope": "today"}).json()
         if a["doctor"]["id"] == 1 and a["status"] in ("CONFIRMED", "ARRIVED", "COMPLETED", "NO_SHOW")),
        key=lambda a: (a["start_time"], a["id"]),
    )]
    middle = order[2]
    page = workspace(client, appointment_id=middle)
    assert f'appointment_id={order[1]}#consultation" rel="prev"' in page
    assert f'appointment_id={order[3]}#consultation" rel="next"' in page
    first = workspace(client, appointment_id=order[0])
    assert 'rel="prev"' not in first and 'rel="next"' in first
    assert "← Back to today’s schedule" in page


def test_follow_up_handoff_is_explicit_and_private(client, day):
    appointment_id = day["seeing"]["id"]
    patient_id = day["seeing"]["patient"]["id"]
    doctor_post(client, f"appointments/{appointment_id}/outcome", summary=SUMMARY, next_step="FOLLOW_UP_CONSULTATION", follow_up_note=NOTE)

    handoff = workspace(client, appointment_id=appointment_id).split('id="follow-up-request"')[1].split("</ol>")[0]
    assert "Saving an outcome does not ask reception to book anything." in handoff
    assert re.search(r'class="is-current" aria-current="step">Not sent<', handoff)
    assert client.get("/api/follow-ups/consultation").json()["awaiting"] == []  # saving alone creates nothing

    doctor_post(client, f"appointments/{appointment_id}/status", status="COMPLETED")
    sent = doctor_post(client, f"appointments/{appointment_id}/follow-up-request")
    assert sent.status_code == 303
    handoff = workspace(client, appointment_id=appointment_id).split('id="follow-up-request"')[1].split("</ol>")[0]
    assert re.search(r'aria-current="step">Ready for reception<', handoff)

    # Reception sees the request, not the doctor's words, and no procedure was needed.
    [item] = client.get("/api/follow-ups/consultation").json()["awaiting"]
    assert item["patient"]["id"] == patient_id and item["label"] == "Consultation follow-up" and item["state"] == "READY_FOR_SCHEDULING"
    for path in ("/follow-ups", "/", f"/patients/{patient_id}", f"/api/patients/{patient_id}/timeline", "/api/follow-ups/consultation"):
        text = client.get(path).text
        assert SUMMARY not in text and NOTE not in text, path
    assert client.get(f"/api/appointments/{appointment_id}/consultation").json()["recommendations"] == []

    slot = free_slots(client, day="2026-10-15")[0]
    assert client.post(f"/api/follow-ups/consultation/{item['id']}/schedule", json={"slot_id": slot["id"]}).status_code in (200, 201)
    handoff = workspace(client, appointment_id=appointment_id).split('id="follow-up-request"')[1].split("</ol>")[0]
    assert re.search(r'aria-current="step">Scheduled<', handoff)


def test_procedure_recommendation_flow_is_unchanged_and_separate(client, day):
    appointment_id = day["done"]["id"]
    doctor_post(client, f"appointments/{appointment_id}/outcome", summary=SUMMARY, next_step="PROCEDURE_DISCUSSION")
    assert doctor_post(client, f"appointments/{appointment_id}/recommendations",
                       procedure="Implant consultation", doctor_note=DOCTOR_NOTE).status_code == 303
    page = workspace(client, appointment_id=appointment_id)
    treatment = page.split('id="consult-treatment"')[1]
    assert re.search(r'class="is-current" aria-current="step">Draft<', treatment)
    [draft] = client.get(f"/api/appointments/{appointment_id}/consultation").json()["recommendations"]
    assert doctor_post(client, f"recommendations/{draft['id']}/ready", appointment_id=appointment_id).status_code == 303
    treatment = workspace(client, appointment_id=appointment_id).split('id="consult-treatment"')[1]
    assert re.search(r'aria-current="step">Ready for reception<', treatment)
    followups = client.get("/follow-ups").text
    assert "Implant consultation" in followups and DOCTOR_NOTE not in followups
    assert client.get("/api/follow-ups/consultation").json()["awaiting"] == []  # no consultation request created


def test_patient_context_is_operational_only(client, day):
    """Another visit's outcome and recommendation note never appear in a later consultation's context."""
    patient_id = day["done"]["patient"]["id"]
    earlier = day["done"]["id"]
    doctor_post(client, f"appointments/{earlier}/outcome", summary=SUMMARY, next_step="PROCEDURE_DISCUSSION", follow_up_note=NOTE)
    doctor_post(client, f"appointments/{earlier}/recommendations", procedure="Aligner assessment", doctor_note=DOCTOR_NOTE)
    later_slot = free_slots(client)[0]
    later = client.post("/api/appointments", json={"patient_id": patient_id, "slot_id": later_slot["id"], "service_id": 1}).json()
    for status in ("CONFIRMED", "ARRIVED"):
        client.post(f"/api/appointments/{later['id']}/status", json={"status": status})

    page = workspace(client, appointment_id=later["id"])
    context = page.split('id="consult-context"')[1]
    assert "Other visits <span class=\"muted\">(1)</span>" in context
    assert "COMPLETED" in context and "Aligner assessment" in context and "Draft" in context
    assert f'href="/patients/{patient_id}/timeline">Open full patient timeline</a>' in context
    for secret in (SUMMARY, NOTE, DOCTOR_NOTE):
        assert secret not in page


def test_calendar_and_timeline_links_open_the_right_records(client, day):
    appointment_id = day["seeing"]["id"]
    patient_id = day["seeing"]["patient"]["id"]
    page = workspace(client, appointment_id=appointment_id)
    calendar_href = f"/doctor/calendar?doctor_id=1&amp;appointment_id={appointment_id}#cal-appt-{appointment_id}"
    assert calendar_href in page or calendar_href.replace("&amp;", "&") in page
    assert f'href="/patients/{patient_id}/timeline">Patient timeline</a>' in page
    assert "View in calendar" in workspace(client).split('id="queue"')[1]  # from every queue row

    calendar = client.get(f"/doctor/calendar?doctor_id=1&appointment_id={appointment_id}").text
    item = calendar.split(f'id="cal-appt-{appointment_id}"')[0].rsplit("<a ", 1)[1] + calendar.split(f'id="cal-appt-{appointment_id}"')[1].split(">")[0]
    assert "is-current" in item and 'aria-current="true"' in item
    assert f'href="/doctor?doctor_id=1&appointment_id={appointment_id}#consultation"' in item  # "Open consultation"
    assert calendar.count("is-current") == 1
    assert client.get(f"/patients/{patient_id}/timeline").status_code == 200
    assert "Ivan Inside" in client.get(f"/patients/{patient_id}/timeline").text

    # An appointment in a later week opens that week (beyond the booking window, so it is inserted directly).
    with client.app.state.session_factory() as db:
        when = datetime(2026, 10, 22, 11, 0)
        later = Appointment(patient_id=patient_id, doctor_id=1, service_id=1, start_time=when,
                            end_time=when + timedelta(minutes=30), status="CONFIRMED")
        db.add(later)
        db.commit()
        later_id = later.id
    calendar = client.get(f"/doctor/calendar?doctor_id=1&appointment_id={later_id}").text
    assert "Dr. Anika Rao · Wed, 21 Oct to Tue, 27 Oct" in calendar
    assert f'id="cal-appt-{later_id}"' in calendar and "is-current" in calendar


def test_reset_clears_consultation_starts(client, day):
    from app.seed import reset_demo_data

    with client.app.state.session_factory() as db:
        assert db.query(ConsultationStart).count() == 1
        reset_demo_data(db)
        assert db.query(ConsultationStart).count() == 0
