"""Phase 9: waitlist and cancellation fill."""
import pytest

from app.models import WaitlistEntry
from app.seed import reset_demo_data

from .test_assistant import Chat, slot_options
from .test_closed_days import WEDNESDAY, client_at  # noqa: F401  (fixture)
from .test_timeline import ticking  # noqa: F401  (fixture: a clock that moves, so event order is real)

THURSDAY, FRIDAY, SATURDAY = "2026-10-15", "2026-10-16", "2026-10-17"


@pytest.fixture
def client(client_at):  # noqa: F811
    """Seeded app with the clock fixed at Wednesday 14 Oct 2026, 10:00."""
    return client_at(WEDNESDAY)


def slot_at(client, doctor_id, day, label):
    return next(s for s in client.get(f"/api/doctors/{doctor_id}/slots", params={"date": day}).json() if s["start_label"] == label)


def book(client, patient_id, slot, service_id=1):
    response = client.post("/api/appointments", json={"patient_id": patient_id, "slot_id": slot["id"], "service_id": service_id})
    assert response.status_code == 201, response.text
    return response.json()


def cancel(client, appointment_id):
    assert client.post(f"/api/appointments/{appointment_id}/status", json={"status": "CANCELLED"}).status_code == 200


def join(client, patient_id, **overrides):
    body = {"patient_id": patient_id, "service_id": 3, "doctor_id": 1, "date_from": THURSDAY, "date_to": FRIDAY,
            "time_preference": "MORNING", "contact_preference": "PHONE", "note": "Prefers an early visit", **overrides}
    response = client.post("/api/waitlist", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def opportunities(client):
    return client.get("/api/waitlist/opportunities").json()


def appointment_count(client):
    return len(client.get("/api/appointments", params={"scope": "today"}).json()) + len(client.get("/api/appointments").json())


def timeline_events(client, patient_id):
    """Timeline events without the outbox lines added in Phase 10."""
    events = client.get(f"/api/patients/{patient_id}/timeline").json()["events"]
    return [e for e in events if not e["kind"].startswith("NOTIFICATION_")]


def timeline_kinds(client, patient_id):
    return [e["kind"] for e in timeline_events(client, patient_id)]


@pytest.fixture
def freed(client):
    """Demo Patient Two's Thursday 10:00 booking with Dr. Anika Rao, cancelled: a newly available slot."""
    slot = slot_at(client, 1, THURSDAY, "10:00 AM")
    cancel(client, book(client, 2, slot)["id"])
    return slot


def test_staff_can_add_existing_and_new_patients_to_the_waitlist(client):
    page = client.get("/waitlist")
    assert page.status_code == 200 and "Add to waitlist" in page.text and "Nobody is on the waitlist." in page.text
    menu = client.get("/").text.split('<nav class="nav"')[1].split("</nav>")[0]
    assert 'href="/waitlist"' in menu and "<span>Waitlist</span>" in menu

    form = {"service_id": "2", "doctor_id": "2", "date_from": THURSDAY, "date_to": SATURDAY, "time_preference": "AFTERNOON",
            "contact_preference": "MESSAGE", "note": "Call after 5pm"}
    added = client.post("/waitlist", data={**form, "patient_id": "3"}, follow_redirects=False)
    assert added.status_code == 303 and added.headers["location"] == "/waitlist?notice=waitlist_added"
    [entry] = client.get("/api/waitlist").json()
    assert entry["patient"]["name"] == "Demo Patient Three" and entry["status"] == "WAITING" and entry["source"] == "STAFF"
    assert (entry["service"], entry["doctor"], entry["date_from"], entry["date_to"]) == ("Dental Implants", "Dr. Vikram Shah", THURSDAY, SATURDAY)
    assert (entry["time_preference"], entry["contact_preference"], entry["note"]) == ("AFTERNOON", "MESSAGE", "Call after 5pm")

    # A new patient is registered on the way; any doctor, any time.
    before = len(client.get("/api/patients").json())
    client.post("/waitlist", data={"new_name": "Waiting Example", "new_mobile": "555 444 0001", "service_id": "1", "doctor_id": "",
                                   "date_from": THURSDAY, "date_to": THURSDAY, "time_preference": "ANY", "contact_preference": "PHONE"})
    assert len(client.get("/api/patients").json()) == before + 1
    newest = client.get("/api/waitlist").json()[-1]
    assert newest["patient"]["mobile"] == "5554440001" and newest["doctor"] is None

    listing = client.get("/waitlist").text
    assert "Demo Patient Three" in listing and "Waiting Example" in listing and "Call after 5pm" in listing
    assert client.get("/api/waitlist/summary").json() == {"waiting": 2, "offered": 0, "newly_available": 0}

    for bad, message in (
        ({"patient_id": "", "new_name": "", "new_mobile": ""}, "choose an existing patient or enter a new patient"),
        ({"patient_id": "3", "date_from": FRIDAY, "date_to": THURSDAY}, "on or after the first"),
        ({"patient_id": "3", "date_from": "2026-10-01", "date_to": "2026-10-02"}, "in the past"),
        ({"patient_id": "3", "time_preference": "NIGHT"}, "preferred time of day"),
        ({"patient_id": "3", "date_from": ""}, "enter the preferred dates"),
    ):
        refused = client.post("/waitlist", data={**form, **bad}, follow_redirects=False)
        assert refused.status_code == 400 and message in refused.text, bad
    assert len(client.get("/api/waitlist").json()) == 2


def test_cancellation_produces_matching_candidates(client):
    entry = join(client, 3)  # Dr. Anika Rao, Thu-Fri mornings
    slot = slot_at(client, 1, THURSDAY, "10:00 AM")
    booked = book(client, 2, slot)
    assert opportunities(client) == []  # a booked slot is not an opportunity

    cancel(client, booked["id"])
    [found] = opportunities(client)
    assert found["slot"]["id"] == slot["id"] and found["slot"]["doctor"] == "Dr. Anika Rao"
    assert found["slot"]["start_time"] == "2026-10-15T10:00:00"
    assert [c["id"] for c in found["candidates"]] == [entry["id"]]
    assert found["candidates"][0]["service"] == "Root Canal Treatment"  # the requested service is visible to staff

    page = client.get("/waitlist").text
    section = page.split('id="newly-available"')[1].split("</section>")[0]
    assert "10:00 AM" in section and "Dr. Anika Rao" in section and "1 matching candidate" in section
    assert "Demo Patient Three" in section and "Root Canal Treatment" in section and "Mark offered" in section
    assert client.get("/api/waitlist/summary").json() == {"waiting": 1, "offered": 0, "newly_available": 1}

    # Nothing happened automatically: still waiting, no new booking, the slot is simply free.
    assert client.get("/api/waitlist").json()[0]["status"] == "WAITING"
    assert slot_at(client, 1, THURSDAY, "10:00 AM")["available"] is True
    # Once someone books it normally it is no longer "newly available".
    book(client, 4, slot)
    assert opportunities(client) == []


def test_incompatible_preferences_are_excluded(client, freed):
    suits = join(client, 3)  # Dr. Anika Rao, Thu-Fri, morning
    any_doctor = join(client, 4, doctor_id=None, time_preference="ANY", date_from=THURSDAY, date_to=THURSDAY)
    other_doctor = join(client, 1, doctor_id=2)
    afternoon = join(client, 1, time_preference="AFTERNOON")
    wrong_dates = join(client, 1, date_from=FRIDAY, date_to=SATURDAY)

    [found] = opportunities(client)
    matched = {c["id"] for c in found["candidates"]}
    assert matched == {suits["id"], any_doctor["id"]}
    assert not matched & {other_doctor["id"], afternoon["id"], wrong_dates["id"]}

    # An afternoon cancellation for the other doctor suits a different set of people.
    late = slot_at(client, 2, THURSDAY, "2:30 PM")
    cancel(client, book(client, 2, late)["id"])
    by_slot = {o["slot"]["id"]: {c["id"] for c in o["candidates"]} for o in opportunities(client)}
    assert by_slot[late["id"]] == {any_doctor["id"]} | ({other_doctor["id"]} if False else set())
    assert by_slot[freed["id"]] == {suits["id"], any_doctor["id"]}
    section = client.get("/waitlist").text.split('id="newly-available"')[1].split("</section>")[0]
    assert section.count('class="opportunity"') == 2


def test_staff_offer_changes_status_without_reserving(client, freed):
    entry = join(client, 3)
    offered = client.post(f"/waitlist/{entry['id']}/offer", data={"slot_id": freed["id"]}, follow_redirects=False)
    assert offered.status_code == 303 and offered.headers["location"] == "/waitlist?notice=waitlist_offered"
    current = client.get("/api/waitlist").json()[0]
    assert current["status"] == "OFFERED" and current["offered_slot_id"] == freed["id"] and current["appointment_id"] is None
    assert client.get("/api/waitlist/summary").json() == {"waiting": 0, "offered": 1, "newly_available": 1}

    # Offering reserves nothing: the slot is still free and no booking exists.
    assert slot_at(client, 1, THURSDAY, "10:00 AM")["available"] is True
    page = client.get("/waitlist").text
    assert "Patient has accepted this time" in page and "Book this slot" in page and "not reserved" in page

    # Only a waiting entry can be offered; declined offers go back to waiting; closed is final.
    assert client.post(f"/api/waitlist/{entry['id']}/offer", json={"slot_id": freed["id"]}).status_code == 400
    assert client.post(f"/api/waitlist/{entry['id']}/status", json={"status": "WAITING"}).json()["status"] == "WAITING"
    assert client.post(f"/api/waitlist/{entry['id']}/status", json={"status": "WAITING"}).status_code == 400
    assert client.post(f"/api/waitlist/{entry['id']}/status", json={"status": "BOOKED"}).status_code == 400  # never set directly
    taken = slot_at(client, 1, THURSDAY, "9:30 AM")
    assert taken["available"] is False
    assert client.post(f"/api/waitlist/{entry['id']}/offer", json={"slot_id": taken["id"]}).status_code == 400  # not a free slot
    assert client.post(f"/api/waitlist/{entry['id']}/status", json={"status": "CLOSED"}).json()["status"] == "CLOSED"
    assert client.post(f"/api/waitlist/{entry['id']}/offer", json={"slot_id": freed["id"]}).status_code == 400
    assert client.post("/api/waitlist/9999/offer", json={"slot_id": freed["id"]}).status_code == 404


def test_waitlist_booking_creates_one_appointment_and_marks_entry_booked(client, freed):
    entry = join(client, 3)
    before = appointment_count(client)

    # Not before an offer, and not without the patient's acceptance.
    assert client.post(f"/api/waitlist/{entry['id']}/book", json={"accepted": True}).status_code == 400
    client.post(f"/api/waitlist/{entry['id']}/offer", json={"slot_id": freed["id"]})
    not_accepted = client.post(f"/waitlist/{entry['id']}/book", data={}, follow_redirects=False)
    assert not_accepted.status_code == 400 and "confirm that the patient has accepted" in not_accepted.text
    assert appointment_count(client) == before

    booked = client.post(f"/waitlist/{entry['id']}/book", data={"accepted": "yes"}, follow_redirects=False)
    assert booked.status_code == 303 and booked.headers["location"].startswith("/?booked=")
    appointment_id = int(booked.headers["location"].split("=")[1])
    assert appointment_count(client) == before + 1

    saved = next(a for a in client.get("/api/appointments").json() if a["id"] == appointment_id)
    assert saved["patient"]["name"] == "Demo Patient Three" and saved["doctor"]["name"] == "Dr. Anika Rao"
    assert saved["start_time"] == "2026-10-15T10:00:00" and saved["service"]["name"] == "Root Canal Treatment"
    assert saved["status"] == "PENDING" and saved["source"] == "STAFF" and "waitlist" in saved["reason"]

    done = client.get("/api/waitlist").json()[0]
    assert done["status"] == "BOOKED" and done["appointment_id"] == appointment_id
    assert opportunities(client) == [] and slot_at(client, 1, THURSDAY, "10:00 AM")["available"] is False
    assert client.get("/api/waitlist/summary").json() == {"waiting": 0, "offered": 0, "newly_available": 0}
    # Booking twice is impossible.
    assert client.post(f"/api/waitlist/{entry['id']}/book", json={"accepted": True}).status_code == 400
    assert appointment_count(client) == before + 1


def test_duplicate_booking_is_still_refused_from_the_waitlist(client, freed):
    first, second = join(client, 3), join(client, 4)
    for entry in (first, second):  # the same slot can be offered to two people; it is not reserved
        assert client.post(f"/api/waitlist/{entry['id']}/offer", json={"slot_id": freed["id"]}).status_code == 200
    assert client.post(f"/api/waitlist/{first['id']}/book", json={"accepted": True}).status_code == 201
    before = appointment_count(client)

    refused = client.post(f"/api/waitlist/{second['id']}/book", json={"accepted": True})
    assert refused.status_code == 409
    assert refused.json()["message"] == "This slot has just been booked. Please choose another available time."
    page = client.post(f"/waitlist/{second['id']}/book", data={"accepted": "yes"}, follow_redirects=False)
    assert page.status_code == 409 and "This slot has just been booked." in page.text

    assert appointment_count(client) == before
    still = next(e for e in client.get("/api/waitlist").json() if e["id"] == second["id"])
    assert still["status"] == "OFFERED" and still["appointment_id"] is None
    # Reception puts them back on the list for the next opening.
    assert client.post(f"/api/waitlist/{second['id']}/status", json={"status": "WAITING"}).json()["status"] == "WAITING"


def test_timeline_and_dashboard_reflect_the_waitlist(ticking):  # noqa: F811
    client = ticking
    freed = slot_at(client, 1, THURSDAY, "10:00 AM")
    cancel(client, book(client, 2, freed)["id"])
    dashboard = client.get("/").text.split('id="waitlist-summary"')[1].split("</section>")[0]
    assert "Waiting patients" in dashboard and "Newly available slots" in dashboard
    assert "10:00 AM" in dashboard and "0 waiting patients suit this time" in dashboard

    entry = join(client, 3)
    assert timeline_kinds(client, 3)[0] == "WAITLIST_JOINED"
    dashboard = client.get("/").text.split('id="waitlist-summary"')[1].split("</section>")[0]
    counts = [c.split("</dd>")[0] for c in dashboard.split("<dd>")[1:]]
    assert counts == ["1", "0", "1"] and "1 waiting patient suits this time" in dashboard
    assert f'href="/waitlist#slot-{freed["id"]}"' in dashboard

    client.post(f"/api/waitlist/{entry['id']}/offer", json={"slot_id": freed["id"]})
    appointment = client.post(f"/api/waitlist/{entry['id']}/book", json={"accepted": True}).json()

    events = timeline_events(client, 3)
    kinds = [e["kind"] for e in events]
    assert kinds[:4] == ["WAITLIST_BOOKED", "APPOINTMENT_CREATED", "WAITLIST_OFFERED", "WAITLIST_JOINED"]
    by_kind = {e["kind"]: e for e in events}
    assert by_kind["WAITLIST_JOINED"]["title"] == "Joined the waitlist" and by_kind["WAITLIST_JOINED"]["source_label"] == "Staff"
    assert "Root Canal Treatment · Dr. Anika Rao" in by_kind["WAITLIST_JOINED"]["detail"]
    assert by_kind["WAITLIST_OFFERED"]["detail"] == "Offered Thu, 15 Oct at 10:00 AM with Dr. Anika Rao. Not reserved until booked."
    assert by_kind["WAITLIST_OFFERED"]["status"] == "OFFERED" and by_kind["WAITLIST_OFFERED"]["link"] == "/waitlist"
    assert by_kind["WAITLIST_BOOKED"]["appointment_id"] == appointment["id"] and by_kind["WAITLIST_BOOKED"]["icon"] == "list"
    assert events[1]["appointment_id"] == appointment["id"] and events[1]["source_label"] == "Staff"  # the new booking
    page = client.get("/patients/3/timeline").text
    assert "Joined the waitlist" in page and "Waitlist slot offered" in page and "Booked from the waitlist" in page

    dashboard = client.get("/").text
    summary = dashboard.split('id="waitlist-summary"')[1].split("</section>")[0]
    assert [c.split("</dd>")[0] for c in summary.split("<dd>")[1:]] == ["0", "0", "0"]
    assert "Booked from the waitlist" in dashboard.split('id="recent-activity"')[1].split("</section>")[0]
    assert f'id="appointment-{appointment["id"]}"' in dashboard


def test_assistant_offers_join_waitlist_and_never_books_or_exposes_the_list(client):
    join(client, 3, note="PRIVATE-STAFF-NOTE")
    before = appointment_count(client)
    chat = Chat(client)
    reply = chat.send("I want to book a consultation.")
    reply = chat.pick(reply, "New patient")
    chat.send("Hopeful Example")
    reply = chat.send("5554440009")
    reply = chat.pick(reply, "Skip")
    reply = chat.pick(reply, "Aligners")
    reply = chat.pick(reply, "Dr. Meera Iyer")
    reply = chat.send(action="pick", value=FRIDAY)
    assert len(slot_options(reply)) == 3 and "Join waitlist" in [o["label"] for o in reply["options"]]

    reply = chat.pick(reply, "Join waitlist")  # none of the offered times suit
    assert reply["state"]["step"] == "waitlist_time"
    reply = chat.pick(reply, "Afternoon")
    assert reply["waitlist"]["status"] == "WAITING" and reply["booking"] is None
    assert "You are on our waitlist" in chat.text and "Nothing has been booked." in chat.text
    assert "our staff will contact you during clinic hours" in chat.text

    entry = client.get("/api/waitlist").json()[-1]
    assert entry["patient"]["name"] == "Hopeful Example" and entry["source"] == "AI_DEMO" and entry["status"] == "WAITING"
    assert (entry["service"], entry["doctor"], entry["date_from"], entry["time_preference"]) == ("Aligners", "Dr. Meera Iyer", FRIDAY, "AFTERNOON")
    assert appointment_count(client) == before
    assert timeline_kinds(client, entry["patient"]["id"])[0] == "WAITLIST_JOINED"

    # Public pages and replies never show who else is waiting.
    for text in (chat.text, client.get("/assistant").text, client.get("/call-demo").text):
        assert "Demo Patient Three" not in text and "PRIVATE-STAFF-NOTE" not in text


def test_assistant_offers_waitlist_when_a_doctor_has_no_free_times(client):
    # Dr. Vikram Shah set to consult only on Sunday, when the clinic is closed: no slots at all.
    client.post("/settings/doctors/2", data={"name": "Dr. Vikram Shah", "speciality": "Implantology & Oral Surgery", "work_start": "10:00",
                                              "work_end": "18:00", "consultation_minutes": "45", "working_days": ["6"]})
    chat = Chat(client)
    reply = chat.send("I want to book a consultation.")
    reply = chat.pick(reply, "New patient")
    chat.send("Patient Example")
    reply = chat.send("5554440010")
    reply = chat.pick(reply, "Skip")
    reply = chat.pick(reply, "Dental Implants")
    reply = chat.pick(reply, "Dr. Vikram Shah")
    reply = chat.pick(reply, "Earliest available")
    assert "no free consultation times" in reply["messages"][0]["text"] and "join the waitlist" in reply["messages"][0]["text"]
    assert slot_options(reply) == [] and "Join waitlist" in [o["label"] for o in reply["options"]]
    reply = chat.pick(reply, "Join waitlist")
    reply = chat.pick(reply, "Any time")
    entry = client.get("/api/waitlist").json()[-1]
    assert (entry["patient"]["name"], entry["doctor"], entry["time_preference"]) == ("Patient Example", "Dr. Vikram Shah", "ANY")
    assert reply["waitlist"]["reference"] == f"W-{entry['id']}"


def test_demo_reset_clears_the_waitlist(client, freed):
    join(client, 3)
    with client.app.state.session_factory() as db:
        reset_demo_data(db)
        assert db.query(WaitlistEntry).count() == 0
    assert client.get("/api/waitlist").json() == [] and client.get("/waitlist").status_code == 200
