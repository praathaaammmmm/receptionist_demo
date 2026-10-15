"""Phase 11: owner analytics (aggregated sample-data figures only)."""
from datetime import datetime

import pytest

from app.models import Appointment, CallbackTask, Notification

from .test_assistant import Chat, slot_options
from .test_call_demo import Call
from .test_closed_days import WEDNESDAY, client_at  # noqa: F401  (fixture)

THURSDAY = "2026-10-15"
SECRETS = ("SECRET-SUMMARY", "SECRET-FOLLOWUP", "SECRET-DOCTOR-NOTE", "SECRET-STAFF-NOTE", "SECRET-PATIENT-NOTE")


@pytest.fixture
def client(client_at):  # noqa: F811
    """Seeded app, clock fixed at Wednesday 14 Oct 2026, 10:00.
    Seed: 4 bookings (1 confirmed by staff, 3 pending: one staff, one website form, one AI)."""
    return client_at(WEDNESDAY)


def analytics(client, range="all"):
    response = client.get("/api/analytics", params={"range": range})
    assert response.status_code == 200
    return response.json()


def values(rows):
    return {r["code"]: r["value"] for r in rows}


def free_slots(client, doctor_id=1, day=THURSDAY):
    return [s for s in client.get(f"/api/doctors/{doctor_id}/slots", params={"date": day}).json() if s["available"]]


def staff_booking(client, slot, patient_id=2, *statuses):
    booked = client.post("/api/appointments", json={"patient_id": patient_id, "slot_id": slot["id"], "service_id": 1}).json()
    for status in statuses:
        assert client.post(f"/api/appointments/{booked['id']}/status", json={"status": status}).status_code == 200
    return booked


def assistant_booking(driver, name, mobile):
    reply = driver.send("I want to book a consultation.") if isinstance(driver, Chat) else driver.shortcut("I need to book a consultation.")
    reply = driver.pick(reply, "New patient")
    driver.send(name)
    reply = driver.send(mobile)
    reply = driver.pick(reply, "Skip")
    reply = driver.pick(reply, "General Consultation")
    reply = driver.pick(reply, "Dr. Meera Iyer")
    reply = driver.send(action="pick", value=THURSDAY)
    reply = driver.send(action="slot", value=slot_options(reply)[0]["value"])
    return driver.pick(reply, "Confirm booking")["booking"]["reference"]


def test_funnel_counts_follow_known_appointment_statuses(client):
    assert values(analytics(client)["funnel"]) == {"created": 4, "confirmed": 1, "arrived": 0, "completed": 0, "no_show": 0, "cancelled": 0}

    slots = free_slots(client)
    staff_booking(client, slots[0], 2, "CONFIRMED", "ARRIVED", "COMPLETED")
    staff_booking(client, slots[1], 3, "CONFIRMED", "NO_SHOW")
    staff_booking(client, slots[2], 4, "CANCELLED")
    staff_booking(client, slots[3], 2, "CONFIRMED", "ARRIVED", "NO_SHOW")  # arrived, then left before being seen
    staff_booking(client, slots[4], 3, "CONFIRMED", "CANCELLED")  # was confirmed before it was cancelled

    data = analytics(client)
    funnel = values(data["funnel"])
    assert funnel == {"created": 9, "confirmed": 5, "arrived": 2, "completed": 1, "no_show": 2, "cancelled": 2}
    shares = {r["code"]: r["share"] for r in data["funnel"]}
    assert shares["created"] == 100 and shares["confirmed"] == 56 and shares["completed"] == 11
    assert data["headline"]["bookings"] == 9 and data["headline"]["completed"] == 1
    assert data["sample_data"] is True
    # Stages narrow: nobody completes without arriving, or arrives without being confirmed.
    assert funnel["created"] >= funnel["confirmed"] >= funnel["arrived"] >= funnel["completed"]


def test_source_attribution_including_voice_demo_and_waitlist(client):
    website = assistant_booking(Chat(client), "Web Example", "5550001111")
    call = Call(client)
    voice = assistant_booking(call, "Voice Example", "5550002222")
    call.end()
    # A waitlist replacement: cancel a staff booking, offer its slot, book it.
    slot = free_slots(client)[0]
    cancelled = staff_booking(client, slot, 2, "CANCELLED")
    entry = client.post("/api/waitlist", json={"patient_id": 4, "service_id": 1, "date_from": THURSDAY, "date_to": THURSDAY}).json()
    client.post(f"/api/waitlist/{entry['id']}/offer", json={"slot_id": slot["id"]})
    replacement = client.post(f"/api/waitlist/{entry['id']}/book", json={"accepted": True}).json()
    client.post(f"/api/appointments/{voice}/status", json={"status": "CONFIRMED"})

    # Both assistant bookings are stored with the same booking source; only the call log tells them apart.
    stored = {a["id"]: a["source"] for a in client.get("/api/appointments").json()}
    assert stored[website] == stored[voice] == "AI_DEMO" and stored[replacement["id"]] == cancelled["source"] == "STAFF"

    by_source = {s["code"]: s for s in analytics(client)["sources"]}
    assert {code: s["created"] for code, s in by_source.items()} == {
        "STAFF": 3,  # two seeded + the cancelled one
        "WEBSITE_AI": 2,  # one seeded + this chat booking
        "VOICE_DEMO": 1,
        "WAITLIST": 1,
        "WEBSITE_FORM": 1,  # the seeded sample web-form booking
    }
    assert by_source["VOICE_DEMO"]["confirmed"] == 1 and by_source["WEBSITE_AI"]["confirmed"] == 0
    assert by_source["STAFF"]["cancelled"] == 1 and by_source["STAFF"]["confirmed"] == 1
    assert by_source["WAITLIST"]["label"] == "Waitlist replacement" and by_source["VOICE_DEMO"]["label"] == "Voice demo"
    assert sum(s["created"] for s in by_source.values()) == analytics(client)["headline"]["bookings"] == 8


def test_callback_waitlist_notification_checkin_call_and_doctor_counts(client):
    # Callbacks: one open, one in progress, one completed.
    ids = [client.post("/api/callbacks", json={"name": f"Caller {i}", "mobile": f"555000333{i}", "reason": f"Reason {i}"}).json()["id"] for i in range(3)]
    client.post(f"/api/callbacks/{ids[1]}/status", json={"status": "IN_PROGRESS"})
    client.post(f"/api/callbacks/{ids[2]}/status", json={"status": "COMPLETED"})
    # Calls: FAQ answered, callback created, ended, and one left in progress.
    faq = Call(client); faq.shortcut("What are your opening hours?"); faq.end()
    person = Call(client); person.shortcut("I want to speak to a person."); person.send("Caller Four"); person.send("5550003334"); person.end()
    Call(client).end()
    Call(client)
    # Waitlist: waiting, offered, closed.
    slot = free_slots(client)[0]
    staff_booking(client, slot, 2, "CONFIRMED", "CANCELLED")
    entries = [client.post("/api/waitlist", json={"patient_id": p, "service_id": 1, "date_from": THURSDAY, "date_to": THURSDAY}).json()["id"] for p in (2, 3, 4)]
    client.post(f"/api/waitlist/{entries[1]}/offer", json={"slot_id": slot["id"]})
    client.post(f"/api/waitlist/{entries[2]}/status", json={"status": "CLOSED"})
    # Check-in: the seeded confirmed booking arrives by QR; another is marked arrived by the doctor.
    seeded = next(a for a in client.get("/api/appointments", params={"scope": "today"}).json() if a["status"] == "CONFIRMED")
    token = client.post(f"/api/appointments/{seeded['id']}/checkin-token").json()["token"]
    assert client.post("/api/check-in/arrive", json={"token": token}).json()["state"] == "CHECKED_IN"
    other = staff_booking(client, free_slots(client)[1], 3, "CONFIRMED")
    client.post(f"/doctor/1/appointments/{other['id']}/status", data={"status": "ARRIVED"})
    # Doctor: outcome + completion + draft recommendation on the QR patient.
    for action, data in (("outcome", {"summary": SECRETS[0], "next_step": "PROCEDURE_DISCUSSION", "follow_up_note": SECRETS[1]}),
                         ("status", {"status": "COMPLETED"}), ("recommendations", {"procedure": "Implant consultation", "doctor_note": SECRETS[2]})):
        assert client.post(f"/doctor/1/appointments/{seeded['id']}/{action}", data=data, follow_redirects=False).status_code == 303
    # Notifications: send one, fail one.
    queued = client.get("/api/notifications", params={"status": "QUEUED"}).json()
    client.post(f"/api/notifications/{queued[0]['id']}/send")
    client.post(f"/api/notifications/{queued[1]['id']}/fail")

    data = analytics(client)
    assert values(data["callbacks"]) == {"OPEN": 2, "IN_PROGRESS": 1, "COMPLETED": 1}  # 3 staff-made + 1 from the call
    assert data["calls"]["total"] == 4 and data["calls"]["in_progress"] == 1
    assert values(data["calls"]["outcomes"]) == {"BOOKING_CREATED": 0, "CALLBACK_CREATED": 1, "FAQ_ANSWERED": 1, "ENDED": 1}
    assert values(data["waitlist"]) == {"WAITING": 1, "OFFERED": 1, "BOOKED": 0, "CLOSED": 1}
    assert data["checkin"] == {"arrivals": 2, "qr_checkins": 1, "other_arrivals": 1, "qr_share": 50}
    assert data["doctor"]["outcomes"] == 1 and data["doctor"]["recommendations_drafted"] == 1
    assert values(data["doctor"]["next_steps"]) == {"NO_FOLLOW_UP": 0, "FOLLOW_UP_CONSULTATION": 0, "PROCEDURE_DISCUSSION": 1}

    with client.app.state.session_factory() as db:
        stored = {status: db.query(Notification).filter_by(status=status).count() for status in ("QUEUED", "SENT", "DELIVERED", "FAILED")}
        assert db.query(CallbackTask).count() == 4
    assert values(data["notifications"]) == stored
    assert stored["SENT"] == 1 and stored["FAILED"] == 1 and stored["DELIVERED"] == 0 and stored["QUEUED"] >= 3
    assert data["headline"]["open_callbacks"] == 2 and data["headline"]["ai_calls"] == 4


def test_date_filters_today_week_and_all(client):
    staff_booking(client, free_slots(client)[0], 2, "CONFIRMED")  # created "today" (Wed 14 Oct)
    client.post("/api/callbacks", json={"name": "Caller", "mobile": "5550004441", "reason": "Reason"})
    with client.app.state.session_factory() as db:
        seeded = db.query(Appointment).order_by(Appointment.id).all()
        seeded[1].created_at = datetime(2026, 10, 12, 9, 0)  # Monday of this week
        seeded[2].created_at = datetime(2026, 10, 11, 23, 59)  # Sunday: last week
        seeded[3].created_at = datetime(2026, 10, 5, 9, 0)  # the week before
        db.query(CallbackTask).one().created_at = datetime(2026, 10, 13, 9, 0)  # yesterday
        db.commit()

    today, week, everything = analytics(client, "today"), analytics(client, "week"), analytics(client, "all")
    assert (today["headline"]["bookings"], week["headline"]["bookings"], everything["headline"]["bookings"]) == (2, 3, 5)
    assert (values(today["funnel"])["confirmed"], values(everything["funnel"])["confirmed"]) == (2, 2)
    assert (today["headline"]["open_callbacks"], week["headline"]["open_callbacks"], everything["headline"]["open_callbacks"]) == (0, 1, 1)
    assert today["range_label"] == "Today" and today["period_start"] == "2026-10-14T00:00:00" and today["period_end"] == "2026-10-15T00:00:00"
    assert week["range_label"] == "This week" and week["period_start"] == "2026-10-12T00:00:00" and week["period_end"] == "2026-10-19T00:00:00"
    assert everything["range_label"] == "All demo data" and everything["period_start"] is None
    assert analytics(client, "decade")["range"] == "all"  # unknown filters fall back to everything

    page = client.get("/analytics", params={"range": "week"}).text
    assert 'href="/analytics?range=today"' in page and 'href="/analytics?range=week"' in page and 'href="/analytics?range=all"' in page
    assert 'aria-current="true" href="/analytics?range=week"' in page
    # A period with nothing in it explains itself instead of showing empty charts.
    with client.app.state.session_factory() as db:
        for appointment in db.query(Appointment).all():
            appointment.created_at = datetime(2026, 10, 1, 9, 0)
        db.commit()
    empty = client.get("/analytics", params={"range": "today"}).text
    assert "No bookings were created in this period" in empty and "No callback tasks were created in this period." in empty


def test_analytics_page_has_no_patient_details_or_doctor_notes(client):
    patient = client.post("/api/patients", json={"name": "Private Person", "mobile": "5559876543", "email": "private.person@example.com", "notes": SECRETS[4]}).json()
    booked = staff_booking(client, free_slots(client)[0], patient["id"], "CONFIRMED", "ARRIVED")
    client.post(f"/doctor/1/appointments/{booked['id']}/outcome", data={"summary": SECRETS[0], "next_step": "NO_FOLLOW_UP", "follow_up_note": SECRETS[1]})
    client.post(f"/doctor/1/appointments/{booked['id']}/status", data={"status": "COMPLETED"})
    client.post(f"/doctor/1/appointments/{booked['id']}/recommendations", data={"procedure": "Aligner assessment", "doctor_note": SECRETS[2]})
    client.post("/api/callbacks", json={"name": "Private Person", "mobile": "5559876543", "reason": "SECRET-REASON", "notes": SECRETS[3]})

    page = client.get("/analytics")
    assert page.status_code == 200
    menu = page.text.split('<nav class="nav"')[1].split("</nav>")[0]
    assert 'href="/analytics"' in menu and "<span>Analytics</span>" in menu
    main = page.text.split('id="main"')[1].split("<footer")[0]
    api = client.get("/api/analytics").text
    names = [p["name"] for p in client.get("/api/patients").json()] + ["Private Person"]
    mobiles = [p["mobile"] for p in client.get("/api/patients").json()]
    for body in (main, api):
        for private in names + mobiles + ["private.person@example.com", "patient.one@example.com", "SECRET-REASON", "Aligner assessment", *SECRETS]:
            assert private not in body, private
        assert "Dr. " not in body  # no per-doctor or per-patient breakdown at all

    # It is clearly sample data, with definitions and no invented business figures.
    assert "Demo analytics — sample data only." in main and "not real conversion rates" in main
    assert "How these figures are calculated" in main and "Appointment funnel" in main and "Bookings by source" in main
    for claim in ("revenue: ", "₹", "satisfaction score", "NPS"):
        assert claim not in main
    assert "No revenue, satisfaction, forecast or real conversion figures" in main
    assert "Consultations completed" in main and "Voice demo" in main and "Waitlist replacement" in main
    for public in ("/assistant", "/call-demo"):
        assert "/analytics" not in client.get(public).text
