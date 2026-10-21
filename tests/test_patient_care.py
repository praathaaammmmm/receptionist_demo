"""Doctor patient controls: flags, private doctor notes, care requests and the patient overview.

Clock fixed at Wednesday 14 Oct 2026, 10:00. Doctor 1 is Dr. Anika Rao; her seeded confirmed booking
today is Demo Patient One.
"""
import pytest

from app.models import ConsultationFollowup, DoctorPatientNote, Patient

from .test_closed_days import WEDNESDAY, client_at  # noqa: F401  (fixture)

NOTE = "SECRET-PRIVATE-DOCTOR-NOTE about sensitivity"
SUMMARY = "SECRET-CARE-OUTCOME"


@pytest.fixture
def client(client_at):  # noqa: F811
    return client_at(WEDNESDAY)


def post(client, path, doctor_id=1, **data):
    return client.post(f"/doctor/{doctor_id}/{path}", data=data, follow_redirects=False)


@pytest.fixture
def visit(client):
    """Doctor 1's seeded confirmed booking for today, with the patient arrived."""
    seeded = next(a for a in client.get("/api/appointments", params={"scope": "today"}).json()
                  if a["status"] == "CONFIRMED" and a["doctor"]["id"] == 1)
    assert client.post(f"/api/appointments/{seeded['id']}/status", json={"status": "ARRIVED"}).status_code == 200
    return {"id": seeded["id"], "patient_id": seeded["patient"]["id"], "mobile": seeded["patient"]["mobile"]}


def page(client, visit, doctor_id=1):
    return client.get(f"/doctor?doctor_id={doctor_id}&appointment_id={visit['id']}").text


def overview(text):
    return text.split('id="patient-overview"')[1].split('id="consult-context"')[0]


def timeline(client, patient_id):
    data = client.get(f"/api/patients/{patient_id}/timeline").json()
    return data["events"] if isinstance(data, dict) else data


def checked(text, code):
    box = overview(text).split(f'value="{code}"')[1].split(">")[0]
    return "checked" in box


def test_doctor_sets_updates_and_clears_their_own_flags(client, visit):
    done = post(client, f"appointments/{visit['id']}/care/flags", flags=["NEEDS_FOLLOW_UP", "PRIORITY_REVIEW"])
    assert done.status_code == 303
    assert done.headers["location"] == f"/doctor?doctor_id=1&appointment_id={visit['id']}&notice=care_flags#patient-overview"
    text = client.get(done.headers["location"]).text
    assert "Patient flags saved." in overview(text)  # feedback inside the overview, beside the form
    assert checked(text, "NEEDS_FOLLOW_UP") and checked(text, "PRIORITY_REVIEW") and not checked(text, "DOCTOR_REVIEW_BEFORE_BOOKING")

    post(client, f"appointments/{visit['id']}/care/flags", flags=["PRIORITY_REVIEW", "DOCTOR_REVIEW_BEFORE_BOOKING"])
    text = page(client, visit)
    assert not checked(text, "NEEDS_FOLLOW_UP") and checked(text, "PRIORITY_REVIEW") and checked(text, "DOCTOR_REVIEW_BEFORE_BOOKING")

    unchanged = post(client, f"appointments/{visit['id']}/care/flags", flags=["PRIORITY_REVIEW", "DOCTOR_REVIEW_BEFORE_BOOKING"])
    assert "notice=care_flags_unchanged" in unchanged.headers["location"]
    post(client, f"appointments/{visit['id']}/care/flags")  # nothing ticked: clear them all
    text = page(client, visit)
    assert not any(checked(text, code) for code in ("NEEDS_FOLLOW_UP", "PRIORITY_REVIEW", "DOCTOR_REVIEW_BEFORE_BOOKING"))
    assert post(client, f"appointments/{visit['id']}/care/flags", flags=["VIP"]).status_code == 400


def test_flag_changes_are_on_the_timeline_by_name_only(client, visit):
    post(client, f"appointments/{visit['id']}/outcome", summary=SUMMARY, next_step="FOLLOW_UP_CONSULTATION")
    post(client, f"appointments/{visit['id']}/care/flags", flags=["PRIORITY_REVIEW"])
    post(client, f"appointments/{visit['id']}/care/flags")
    events = [e for e in timeline(client, visit["patient_id"]) if e["kind"].startswith("PATIENT_FLAG")]
    assert [(e["kind"], e["title"], e["detail"], e["source"]) for e in sorted(events, key=lambda e: e["kind"], reverse=True)] == [
        ("PATIENT_FLAG_SET", "Doctor flag set", "Priority review · Dr. Anika Rao", "DOCTOR"),
        ("PATIENT_FLAG_CLEARED", "Doctor flag cleared", "Priority review · Dr. Anika Rao", "DOCTOR"),
    ]
    page_text = client.get(f"/patients/{visit['patient_id']}/timeline").text
    assert "Doctor flag set" in page_text and SUMMARY not in page_text


def test_reception_sees_the_flag_and_its_meaning_only(client, visit):
    post(client, f"appointments/{visit['id']}/care/flags", flags=["DOCTOR_REVIEW_BEFORE_BOOKING"])
    detail = client.get(f"/patients/{visit['patient_id']}").text
    assert "Doctor flag: Do not schedule without doctor review" in detail
    assert "Check with the doctor before booking any new appointment for this patient." in detail
    assert "Doctor flag: Do not schedule without doctor review" in client.get("/").text  # dashboard booking row
    post(client, f"appointments/{visit['id']}/care/flags")
    assert "Doctor flag:" not in client.get(f"/patients/{visit['patient_id']}").text


def test_private_doctor_notes_stay_in_that_doctors_workspace(client, visit):
    saved = post(client, f"appointments/{visit['id']}/care/notes", body=NOTE)
    assert saved.status_code == 303 and "notice=care_note" in saved.headers["location"]
    own = overview(page(client, visit))
    assert NOTE in own
    assert "Private doctor notes — not visible to reception or patient." in own
    assert "Last updated by Dr. Anika Rao, today at 10:00 AM." in own

    post(client, f"appointments/{visit['id']}/care/notes", body=NOTE + " (edited)")
    assert NOTE + " (edited)" in page(client, visit)
    with client.app.state.session_factory() as db:
        [stored] = db.query(DoctorPatientNote).all()
        assert stored.doctor_id == 1 and stored.body.endswith("(edited)")

    pid = visit["patient_id"]
    for path in ("/", "/patients", f"/patients?q={visit['mobile']}", f"/patients/{pid}", f"/patients/{pid}/timeline",
                 f"/api/patients/{pid}/timeline", "/analytics", "/api/analytics", "/notifications", "/api/notifications",
                 "/follow-ups", "/api/follow-ups", "/api/follow-ups/consultation", "/waitlist", "/check-in", "/assistant",
                 "/call-demo", "/api/calls", "/api/callbacks", "/api/appointments?scope=today", "/api/dashboard/summary",
                 f"/api/appointments/{visit['id']}/consultation", "/doctor/calendar?doctor_id=1", "/doctor?doctor_id=1",
                 "/doctor?doctor_id=2", "/openapi.json"):
        assert "SECRET-PRIVATE-DOCTOR-NOTE" not in client.get(path).text, path


def test_another_doctor_cannot_see_or_change_the_first_doctors_controls(client, visit):
    post(client, f"appointments/{visit['id']}/care/notes", body=NOTE)
    post(client, f"appointments/{visit['id']}/care/flags", flags=["PRIORITY_REVIEW"])
    for path, data in (("care/notes", {"body": "Overwritten"}), ("care/flags", {"flags": []}),
                       ("care/callback", {"reason": "CONFIRM_APPOINTMENT"}), ("care/follow-up", {"timeframe": "WEEK_1"})):
        refused = post(client, f"appointments/{visit['id']}/{path}", doctor_id=2, **data)
        assert refused.status_code == 403, path
    assert "SECRET-PRIVATE-DOCTOR-NOTE" in page(client, visit)
    assert checked(page(client, visit), "PRIORITY_REVIEW")
    assert "SECRET-PRIVATE-DOCTOR-NOTE" not in page(client, visit, doctor_id=2)

    # Doctor 2 seeing the same patient has their own, separate overview: no flags or note from doctor 1.
    slot = next(s for s in client.get("/api/doctors/2/slots", params={"date": "2026-10-14"}).json() if s["available"])
    other = client.post("/api/appointments", json={"patient_id": visit["patient_id"], "slot_id": slot["id"], "service_id": 1}).json()
    for status in ("CONFIRMED", "ARRIVED"):
        client.post(f"/api/appointments/{other['id']}/status", json={"status": status})
    theirs = client.get(f"/doctor?doctor_id=2&appointment_id={other['id']}").text
    assert "SECRET-PRIVATE-DOCTOR-NOTE" not in theirs and not checked(theirs, "PRIORITY_REVIEW")
    post(client, f"appointments/{other['id']}/care/notes", doctor_id=2, body="Doctor two's own note")
    assert "Doctor two's own note" not in page(client, visit)


def test_callback_request_uses_a_fixed_operational_reason(client, visit):
    before = client.get("/api/notifications").text
    sent = post(client, f"appointments/{visit['id']}/care/callback", reason="ARRANGE_FOLLOW_UP", notes=SUMMARY)
    assert sent.status_code == 303 and "notice=care_callback" in sent.headers["location"]
    [task] = [t for t in client.get("/api/callbacks").json() if t["mobile"] == visit["mobile"]]
    assert task["reason"] == "Please call to arrange follow-up (requested by Dr. Anika Rao)"
    assert task["status"] == "OPEN" and SUMMARY not in str(task)  # extra fields are ignored
    assert "Please call to arrange follow-up" in client.get("/").text  # on reception's callback list
    assert client.get("/api/notifications").text.count("CALLBACK_ACKNOWLEDGEMENT") == before.count("CALLBACK_ACKNOWLEDGEMENT")
    assert any(e["title"] == "Doctor asked reception to call" for e in timeline(client, visit["patient_id"]))

    for bad in ("", "Patient has an abscess, call urgently"):
        assert post(client, f"appointments/{visit['id']}/care/callback", reason=bad).status_code == 400
    assert len([t for t in client.get("/api/callbacks").json() if t["mobile"] == visit["mobile"]]) == 1


def test_follow_up_request_from_the_overview_with_preferences(client, visit):
    # No outcome, no procedure, consultation not completed: the doctor can still ask for a follow-up.
    sent = post(client, f"appointments/{visit['id']}/care/follow-up", duration="45", timeframe="WEEK_2")
    assert sent.status_code == 303 and "notice=care_followup" in sent.headers["location"]
    [item] = client.get("/api/follow-ups/consultation").json()["awaiting"]
    assert item["patient"]["id"] == visit["patient_id"] and item["state"] == "READY_FOR_SCHEDULING"
    assert client.get(f"/api/appointments/{visit['id']}/consultation").json()["status"] == "ARRIVED"  # nothing booked or changed

    followups = client.get("/follow-ups").text
    row = followups.split(f'id="consultation-followup-{item["id"]}"')[1].split("</li>")[0]
    assert "Doctor’s preference: 45 min · within 2 weeks · by Wed, 28 Oct" in row
    assert "Waiting" in overview(page(client, visit))
    assert post(client, f"appointments/{visit['id']}/care/follow-up").status_code == 400  # one per consultation

    # Reception schedules it through the normal flow; the doctor then sees it as scheduled.
    slot = next(s for s in client.get("/api/doctors/1/slots", params={"date": "2026-10-16"}).json() if s["available"])
    booked = client.post(f"/api/follow-ups/consultation/{item['id']}/schedule", json={"slot_id": slot["id"]})
    assert booked.status_code in (200, 201)
    text = overview(page(client, visit))
    assert "Scheduled" in text and "Booked Fri, 16 Oct" in text
    assert "No longer needed" not in text
    assert "SECRET" not in client.get("/follow-ups").text


@pytest.mark.parametrize("data, message", [
    ({"duration": "20"}, "15, 30 or 45 minutes"),
    ({"timeframe": "SOMEDAY"}, "when the follow-up should happen"),
    ({"timeframe": "DATE"}, "the date the follow-up should happen by"),
    ({"timeframe": "DATE", "by_date": "2026-10-14"}, "after today and within a year"),
])
def test_follow_up_preferences_are_validated(client, visit, data, message):
    refused = post(client, f"appointments/{visit['id']}/care/follow-up", **data)
    assert refused.status_code == 400 and message in refused.text
    assert client.get("/api/follow-ups/consultation").json()["awaiting"] == []


def test_follow_up_needs_an_arrived_patient(client):
    seeded = next(a for a in client.get("/api/appointments", params={"scope": "today"}).json()
                  if a["status"] == "CONFIRMED" and a["doctor"]["id"] == 1)
    refused = post(client, f"appointments/{seeded['id']}/care/follow-up", timeframe="WEEK_1")
    assert refused.status_code == 400 and "once the patient has arrived" in refused.text


def test_doctor_closes_a_waiting_follow_up_and_can_ask_again(client, visit):
    post(client, f"appointments/{visit['id']}/care/follow-up", timeframe="MONTH_1")
    with client.app.state.session_factory() as db:
        request_id = db.query(ConsultationFollowup).one().id
    assert post(client, f"follow-ups/{request_id}/close", doctor_id=2, appointment_id=visit["id"], reason="NOT_NEEDED").status_code == 403
    assert post(client, f"follow-ups/{request_id}/close", appointment_id=visit["id"]).status_code == 400  # a reason is required
    closed = post(client, f"follow-ups/{request_id}/close", appointment_id=visit["id"], reason="NOT_NEEDED")
    assert closed.status_code == 303 and "notice=care_followup_closed" in closed.headers["location"]
    assert client.get("/api/follow-ups/consultation").json()["awaiting"] == []
    assert "Closed" in overview(page(client, visit))
    assert any(e["title"] == "Doctor closed follow-up request" for e in timeline(client, visit["patient_id"]))
    assert post(client, f"follow-ups/{request_id}/close", appointment_id=visit["id"], reason="NOT_NEEDED").status_code == 400

    again = post(client, f"appointments/{visit['id']}/care/follow-up", timeframe="WEEK_1")
    assert again.status_code == 303
    [item] = client.get("/api/follow-ups/consultation").json()["awaiting"]
    assert item["id"] == request_id  # the same request, reopened


def test_closing_is_refused_once_reception_has_booked(client, visit):
    post(client, f"appointments/{visit['id']}/care/follow-up")
    [item] = client.get("/api/follow-ups/consultation").json()["awaiting"]
    slot = next(s for s in client.get("/api/doctors/1/slots", params={"date": "2026-10-16"}).json() if s["available"])
    client.post(f"/api/follow-ups/consultation/{item['id']}/schedule", json={"slot_id": slot["id"]})
    refused = post(client, f"follow-ups/{item['id']}/close", appointment_id=visit["id"], reason="NOT_NEEDED")
    assert refused.status_code == 400 and "already booked" in refused.text


def test_overview_shows_patient_information_and_history_with_this_doctor(client, visit):
    text = overview(page(client, visit))
    for label in ("Patient information", "Operational flags", "Follow-up", "Visits with Dr. Anika Rao", "Doctor notes", "Quick actions"):
        assert label in text
    assert "Demo Patient One" in text and visit["mobile"] in text and "Registered" in text
    assert "<strong>0</strong> completed" in text and "<strong>0</strong> no-shows" in text
    assert "this visit" in text and "No upcoming appointment with you." in text
    assert f'href="/patients/{visit["patient_id"]}/timeline"' in text


def test_doctors_cannot_edit_identity_delete_records_or_touch_bookings_they_do_not_own(client, visit):
    with client.app.state.session_factory() as db:
        before = db.get(Patient, visit["patient_id"])
        identity = (before.name, before.mobile, before.email, before.created_at)
    for method, path in (("post", f"/doctor/1/patients/{visit['patient_id']}"), ("post", f"/doctor/1/appointments/{visit['id']}/care/patient"),
                         ("delete", f"/doctor/1/appointments/{visit['id']}"), ("post", f"/doctor/1/appointments/{visit['id']}/delete"),
                         ("delete", f"/api/patients/{visit['patient_id']}"), ("post", f"/doctor/1/appointments/{visit['id']}/care/delete")):
        assert getattr(client, method)(path).status_code in (404, 405), path
    # Even a care form with extra identity fields leaves the patient untouched.
    post(client, f"appointments/{visit['id']}/care/notes", body="x", mobile="5550000000", name="Changed")
    with client.app.state.session_factory() as db:
        after = db.get(Patient, visit["patient_id"])
        assert (after.name, after.mobile, after.email, after.created_at) == identity
    # Confirming and cancelling stay with reception.
    for status in ("CONFIRMED", "CANCELLED"):
        assert post(client, f"appointments/{visit['id']}/status", status=status).status_code == 403
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if "care" in p or "note" in p.lower() or "flag" in p.lower()]


# ---- "Needs follow-up" is advisory; "Send follow-up to reception" creates the real request ---------
NO_REQUEST = "No follow-up request has been sent to reception yet."


def patient_page(client, patient_id):
    text = client.get(f"/patients/{patient_id}").text
    return text.split('aria-label="Patient record sections"')[1].split('id="timeline"')[0]  # the patient card only


def awaiting_section(client):
    return client.get("/follow-ups").text.split('id="awaiting"')[1].split("</section>")[0]


def test_needs_follow_up_flag_alone_creates_nothing_for_reception(client, visit):
    assert post(client, f"appointments/{visit['id']}/care/flags", flags=["NEEDS_FOLLOW_UP"]).status_code == 303
    assert client.get("/api/follow-ups/consultation").json()["awaiting"] == []
    assert "consultation-followup-" not in awaiting_section(client)
    with client.app.state.session_factory() as db:
        assert db.query(ConsultationFollowup).count() == 0

    card = patient_page(client, visit["patient_id"])
    assert "Doctor flag: Needs follow-up" in card
    assert "The doctor has marked that this patient may need a follow-up. Create or send a follow-up request from Doctor Workspace." in card
    assert NO_REQUEST in card
    assert "Check Follow-ups" not in card and "View follow-up" not in card and 'href="/follow-ups' not in card


def test_workspace_keeps_the_flag_and_the_send_action_separate(client, visit):
    text = overview(page(client, visit))
    flags_card = text.split('id="ov-flags"')[1].split("</section>")[0]
    followup_card = text.split('id="ov-followup"')[1].split("</section>")[0]
    assert 'value="NEEDS_FOLLOW_UP"' in flags_card and "Send follow-up to reception" in flags_card  # the hint points to it
    assert "/care/follow-up" not in flags_card
    assert '/care/follow-up" class="form send-to-reception"' in followup_card
    assert '<button class="btn btn-primary" type="submit">Send follow-up to reception</button>' in followup_card


def test_send_follow_up_to_reception_appears_immediately_and_on_the_patient_page(client, visit):
    post(client, f"appointments/{visit['id']}/care/flags", flags=["NEEDS_FOLLOW_UP"])
    sent = post(client, f"appointments/{visit['id']}/care/follow-up", timeframe="WEEK_1")
    assert sent.status_code == 303 and "notice=care_followup" in sent.headers["location"]
    assert "Follow-up sent to reception. It is ready for scheduling." in client.get(sent.headers["location"]).text

    [item] = client.get("/api/follow-ups/consultation").json()["awaiting"]
    assert item["patient"]["id"] == visit["patient_id"]
    assert f'id="consultation-followup-{item["id"]}"' in awaiting_section(client)

    card = patient_page(client, visit["patient_id"])
    request = card.split(f'data-followup-request="{item["id"]}"')[1].split("</p>")[0]
    assert "Consultation follow-up" in request and "Ready for reception" in request and "Dr. Anika Rao" in request
    assert f'href="/follow-ups?kind=consultation&amp;schedule={item["id"]}">View follow-up</a>' in request
    assert NO_REQUEST not in card and "Check Follow-ups" not in card

    # Booked by reception: the patient page follows the state.
    slot = next(s for s in client.get("/api/doctors/1/slots", params={"date": "2026-10-16"}).json() if s["available"])
    client.post(f"/api/follow-ups/consultation/{item['id']}/schedule", json={"slot_id": slot["id"]})
    request = patient_page(client, visit["patient_id"]).split(f'data-followup-request="{item["id"]}"')[1].split("</p>")[0]
    assert "Scheduled" in request and "booked Fri, 16 Oct" in request and 'href="/follow-ups">View follow-up</a>' in request
    assert "SECRET" not in client.get(f"/patients/{visit['patient_id']}").text


def test_patient_page_shows_closed_requests_and_hides_drafts(client, visit):
    post(client, f"appointments/{visit['id']}/care/flags", flags=["NEEDS_FOLLOW_UP"])
    post(client, f"appointments/{visit['id']}/care/follow-up")
    with client.app.state.session_factory() as db:
        request_id = db.query(ConsultationFollowup).one().id
    post(client, f"follow-ups/{request_id}/close", appointment_id=visit["id"], reason="NOT_NEEDED")
    request = patient_page(client, visit["patient_id"]).split(f'data-followup-request="{request_id}"')[1].split("</p>")[0]
    assert "Closed" in request and "View follow-up" in request

    with client.app.state.session_factory() as db:
        db.get(ConsultationFollowup, request_id).status = "DRAFT"  # a draft never reached reception
        db.commit()
    card = patient_page(client, visit["patient_id"])
    assert "data-followup-request" not in card and NO_REQUEST in card
