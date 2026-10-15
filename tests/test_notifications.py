"""Phase 10: Notification Centre (simulated outbox; nothing is ever sent)."""
import http.client
import inspect
import smtplib
import socket
import urllib.request

import pytest

from app import notification_templates
from app.models import Notification
from app.seed import reset_demo_data
from app.services import notifications as outbox

from .test_assistant import Chat
from .test_closed_days import WEDNESDAY, client_at  # noqa: F401  (fixture)
from .test_timeline import ticking  # noqa: F401  (fixture)

THURSDAY, SATURDAY = "2026-10-15", "2026-10-17"
LABEL = "Demo notification simulation — no messages are sent."


@pytest.fixture
def client(client_at):  # noqa: F811
    """Seeded app with the clock fixed at Wednesday 14 Oct 2026, 10:00."""
    return client_at(WEDNESDAY)


def listing(client, **filters):
    return client.get("/api/notifications", params=filters).json()


def for_appointment(client, appointment_id, kind=None):
    return [n for n in listing(client) if n["appointment_id"] == appointment_id and (kind is None or n["type"] == kind)]


def book(client, patient_id=2, day=THURSDAY, label="10:00 AM", doctor_id=1):
    slot = next(s for s in client.get(f"/api/doctors/{doctor_id}/slots", params={"date": day}).json() if s["start_label"] == label)
    return client.post("/api/appointments", json={"patient_id": patient_id, "slot_id": slot["id"], "service_id": 1}).json()


def set_status(client, appointment_id, status):
    response = client.post(f"/api/appointments/{appointment_id}/status", json={"status": status})
    assert response.status_code == 200, response.text


def act(client, notification_id, action):
    return client.post(f"/api/notifications/{notification_id}/{action}")


def test_confirming_an_appointment_queues_exactly_one_confirmation(client):
    booked = book(client)
    assert for_appointment(client, booked["id"]) == []  # a pending booking sends nothing

    set_status(client, booked["id"], "CONFIRMED")
    [queued] = for_appointment(client, booked["id"])
    assert queued["type"] == "APPOINTMENT_CONFIRMATION" and queued["type_label"] == "Appointment confirmation"
    assert queued["status"] == "QUEUED" and queued["channel"] == "WHATSAPP" and queued["attempts"] == 1
    assert queued["recipient_name"] == "Demo Patient Two" and queued["patient_id"] == 2 and queued["simulated"] is True
    assert queued["message"] == (
        "Hello Demo Patient Two, your appointment at Smriti Raj Dentistry is confirmed for Thu, 15 Oct at 10:00 AM "
        "with Dr. Anika Rao. Please arrive 10 minutes early. To change or cancel it, call us on +00 00000 00000."
    )
    # List views mask the contact detail.
    assert queued["recipient_contact"] == "••••••0002" and "5550100002" not in client.get("/api/notifications").text


def test_duplicate_confirmation_notifications_are_prevented(client):
    booked = book(client)
    set_status(client, booked["id"], "CONFIRMED")
    for _ in range(3):  # confirming again, by API or by the dashboard button, is a no-op
        set_status(client, booked["id"], "CONFIRMED")
        client.post(f"/appointments/{booked['id']}/status", data={"status": "CONFIRMED"})
    assert len(for_appointment(client, booked["id"], "APPOINTMENT_CONFIRMATION")) == 1

    with client.app.state.session_factory() as db:
        from app.services import appointments

        appointment = appointments.get_appointment(db, booked["id"])
        first = outbox.queue_for_appointment(db, "APPOINTMENT_CONFIRMATION", appointment)
        again = outbox.queue_for_appointment(db, "APPOINTMENT_CONFIRMATION", appointment)
        db.commit()
        assert first.id == again.id
        assert db.query(Notification).filter_by(dedupe_key=f"APPOINTMENT_CONFIRMATION:appointment:{booked['id']}").count() == 1
    # Even after it has been sent, the same event does not queue a second one.
    [queued] = for_appointment(client, booked["id"], "APPOINTMENT_CONFIRMATION")
    act(client, queued["id"], "send")
    set_status(client, booked["id"], "CONFIRMED")
    assert len(for_appointment(client, booked["id"], "APPOINTMENT_CONFIRMATION")) == 1


def test_cancellation_waitlist_offer_and_callback_create_the_right_types(client):
    booked = book(client)
    set_status(client, booked["id"], "CONFIRMED")
    set_status(client, booked["id"], "CANCELLED")
    assert [n["type"] for n in for_appointment(client, booked["id"])] == ["APPOINTMENT_CANCELLATION", "APPOINTMENT_CONFIRMATION"]
    cancellation = for_appointment(client, booked["id"], "APPOINTMENT_CANCELLATION")[0]
    assert cancellation["status"] == "QUEUED" and "has been cancelled" in cancellation["message"]

    # Waitlist offer: by email when the patient prefers it and has an address, otherwise WhatsApp.
    slot_id = client.get("/api/waitlist/opportunities").json()[0]["slot"]["id"]
    entry = {"service_id": 3, "doctor_id": 1, "date_from": THURSDAY, "date_to": THURSDAY, "time_preference": "ANY"}
    by_email = client.post("/api/waitlist", json={**entry, "patient_id": 3, "contact_preference": "EMAIL"}).json()
    no_address = client.post("/api/waitlist", json={**entry, "patient_id": 4, "contact_preference": "EMAIL"}).json()
    assert listing(client, type="WAITLIST_OFFER") == []  # joining the waitlist notifies nobody
    for waiting in (by_email, no_address):
        assert client.post(f"/api/waitlist/{waiting['id']}/offer", json={"slot_id": slot_id}).status_code == 200
    offers = {n["waitlist_entry_id"]: n for n in listing(client, type="WAITLIST_OFFER")}
    assert offers[by_email["id"]]["channel"] == "EMAIL" and offers[by_email["id"]]["recipient_contact"] == "p•••@example.com"
    assert offers[by_email["id"]]["message"].startswith("Subject: A consultation time is available at Smriti Raj Dentistry\n\n")
    assert offers[no_address["id"]]["channel"] == "WHATSAPP"
    assert "Thu, 15 Oct at 10:00 AM with Dr. Anika Rao" in offers[no_address["id"]]["message"]
    assert "not reserved" in offers[no_address["id"]]["message"]

    # Callback acknowledgement, for a registered patient and for a caller with no record.
    for name, mobile in (("Demo Patient One", "5550100001"), ("New Caller", "5558880001")):
        chat = Chat(client)
        chat.send("I want to speak to a person.")
        chat.send(name)
        chat.send(mobile)
    acks = listing(client, type="CALLBACK_ACKNOWLEDGEMENT")
    assert len(acks) == 2 and {a["patient_id"] for a in acks} == {1, None}
    assert all(a["callback_task_id"] and a["status"] == "QUEUED" for a in acks)
    assert "has received your request for a call" in acks[0]["message"]

    # Demo-safe wording everywhere: no prices, fees or clinical advice.
    for item in listing(client):
        text = item["message"].lower()
        assert not any(word in text for word in ("₹", "fee", "price", "cost", "treatment", "diagnos", "medicine", "prescri"))


def test_reminders_are_queued_once_for_soon_confirmed_appointments(client):
    assert listing(client, type="APPOINTMENT_REMINDER") == []
    later = book(client, patient_id=3, day=SATURDAY)
    set_status(client, later["id"], "CONFIRMED")  # three days away: no reminder yet
    pending = book(client, patient_id=4, day=THURSDAY, label="9:00 AM")  # tomorrow, but not confirmed

    client.get("/notifications")  # the demo has no scheduler: opening the centre or dashboard queues what is due
    client.get("/")
    client.get("/notifications")
    reminders = listing(client, type="APPOINTMENT_REMINDER")
    assert len(reminders) == 1  # the seeded booking confirmed for 11:00 today, once
    assert reminders[0]["recipient_name"] == "Demo Patient One" and "this is a reminder" in reminders[0]["message"]
    assert not for_appointment(client, later["id"], "APPOINTMENT_REMINDER")
    assert not for_appointment(client, pending["id"], "APPOINTMENT_REMINDER")
    assert notification_templates.REMINDER_HOURS_BEFORE == 24


def test_staff_status_transitions_and_retry(client):
    booked = book(client)
    set_status(client, booked["id"], "CONFIRMED")
    [queued] = for_appointment(client, booked["id"])
    nid = queued["id"]

    assert act(client, nid, "deliver").status_code == 400  # cannot be delivered before it is sent
    assert act(client, nid, "retry").status_code == 400
    assert act(client, nid, "send").json()["status"] == "SENT"
    assert act(client, nid, "send").status_code == 400
    assert act(client, nid, "fail").json()["status"] == "FAILED"
    assert act(client, nid, "deliver").status_code == 400

    retried = act(client, nid, "retry").json()
    assert retried["status"] == "QUEUED" and retried["attempts"] == 2  # same entry, attempt count tracks the retry
    assert len(for_appointment(client, booked["id"])) == 1
    assert act(client, nid, "send").json()["status"] == "SENT"
    assert act(client, nid, "deliver").json()["status"] == "DELIVERED"
    for action in ("send", "deliver", "fail", "retry"):  # delivered is final
        assert act(client, nid, action).status_code == 400
    assert act(client, nid, "explode").status_code == 400
    assert act(client, 9999, "send").status_code == 404

    # The same actions from the staff page.
    set_status(client, booked["id"], "CANCELLED")
    other = for_appointment(client, booked["id"], "APPOINTMENT_CANCELLATION")[0]["id"]
    sent = client.post(f"/notifications/{other}/send", follow_redirects=False)
    assert sent.status_code == 303 and sent.headers["location"] == "/notifications?notice=notification_sent"
    assert "No message left this app." in client.get(sent.headers["location"]).text
    refused = client.post(f"/notifications/{other}/send", follow_redirects=False)
    assert refused.status_code == 400 and "cannot be changed" in refused.text
    assert client.get("/api/notifications/summary").json()["delivered"] == 1


def test_notification_centre_page_is_labelled_searchable_and_masks_contacts(client):
    booked = book(client)
    set_status(client, booked["id"], "CONFIRMED")
    set_status(client, booked["id"], "CANCELLED")
    menu = client.get("/").text.split('<nav class="nav"')[1].split("</nav>")[0]
    assert 'href="/notifications"' in menu and "<span>Notifications</span>" in menu

    page = client.get("/notifications")
    assert page.status_code == 200 and LABEL in page.text
    assert "Appointment confirmation" in page.text and "Cancellation update" in page.text and "Appointment reminder" in page.text
    assert "WhatsApp" in page.text and "QUEUED" in page.text and f"Booking #{booked['id']}" in page.text
    assert "Preview" in page.text and "Hello Demo Patient Two, your appointment" in page.text  # message preview
    assert ">Send</button>" in page.text and ">Mark failed</button>" in page.text
    assert "5550100002" not in page.text and "5550100001" not in page.text and "••••••0002" in page.text

    assert {n["type"] for n in listing(client, type="APPOINTMENT_CANCELLATION")} == {"APPOINTMENT_CANCELLATION"}
    assert {n["recipient_name"] for n in listing(client, q="patient two")} == {"Demo Patient Two"}
    assert {n["type"] for n in listing(client, q="reminder")} == {"APPOINTMENT_REMINDER"}
    assert listing(client, status="DELIVERED") == [] and listing(client, channel="EMAIL") == []
    assert len(listing(client, status="QUEUED", channel="WHATSAPP")) == len(listing(client))
    filtered = client.get("/notifications", params={"q": "cancelled", "status": "QUEUED"}).text
    assert "Cancellation update" in filtered.split('class="outbox"')[1] and "Appointment confirmation" not in filtered.split('class="outbox"')[1]
    assert "No notifications match these filters." in client.get("/notifications", params={"q": "zzzz"}).text

    # Not a public feature.
    for public in ("/assistant", "/call-demo"):
        assert "notification" not in client.get(public).text.lower()


def test_notifications_appear_on_dashboard_and_patient_timeline(ticking):  # noqa: F811
    client = ticking
    patient = client.post("/api/patients", json={"name": "Notify Example", "mobile": "5552223333", "notes": "INTERNAL-PATIENT-NOTE"}).json()
    booked = book(client, patient_id=patient["id"])
    set_status(client, booked["id"], "CONFIRMED")
    [queued] = for_appointment(client, booked["id"])
    for action in ("send", "fail", "retry", "send", "deliver"):
        assert act(client, queued["id"], action).status_code == 200

    summary = client.get("/").text.split('id="notification-summary"')[1].split("</section>")[0]
    assert LABEL in summary and 'href="/notifications?status=DELIVERED"' in summary
    counts = client.get("/api/notifications/summary").json()
    assert counts["delivered"] == 1 and counts["total"] == counts["queued"] + counts["sent"] + counts["delivered"] + counts["failed"]
    assert f"<strong>{counts['delivered']}</strong>" in summary and f"<strong>{counts['queued']}</strong>" in summary

    every = [e for e in client.get(f"/api/patients/{patient['id']}/timeline").json()["events"] if e["kind"].startswith("NOTIFICATION_")]
    # Loading the dashboard also queued this booking's reminder (it is within 24 hours); look at the confirmation's own history.
    assert [e["detail"] for e in every if e["detail"].startswith("Appointment reminder")] == ["Appointment reminder · WhatsApp · simulated, not sent"]
    events = [e for e in every if e["detail"].startswith("Appointment confirmation")]
    assert [e["kind"] for e in events] == [
        "NOTIFICATION_DELIVERED", "NOTIFICATION_SENT", "NOTIFICATION_RETRIED", "NOTIFICATION_FAILED", "NOTIFICATION_SENT", "NOTIFICATION_QUEUED",
    ]
    assert [e["status"] for e in events] == ["DELIVERED", "SENT", "RETRIED", "FAILED", "SENT", "QUEUED"]
    assert all(e["source_label"] == "Staff" and e["icon"] == "message" and e["link"] == "/notifications" for e in events)
    assert events[-1]["detail"] == "Appointment confirmation · WhatsApp · simulated, not sent"
    assert events[0]["detail"] == "Appointment confirmation · WhatsApp · attempt 2 · simulated, not sent"

    # The timeline shows type and status only: not the message text, not internal notes.
    page = client.get(f"/patients/{patient['id']}/timeline").text
    section = page.split('id="timeline"')[1]
    assert "Notification delivered (simulated)" in section and "Notification retried" in section
    assert "Please arrive 10 minutes early" not in section and "INTERNAL-PATIENT-NOTE" not in section
    # Outbox lines stay out of the dashboard's recent patient activity list.
    assert "Notification" not in client.get("/").text.split('id="recent-activity"')[1].split("</section>")[0]


def test_no_external_call_is_made(client, monkeypatch):
    """Every network door is wired to fail; the whole notification flow must still work."""
    def blocked(*args, **kwargs):
        raise AssertionError("the notification simulation attempted an external call")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(http.client.HTTPConnection, "request", blocked)
    monkeypatch.setattr(smtplib.SMTP, "connect", blocked)
    monkeypatch.setattr(smtplib.SMTP, "sendmail", blocked)

    booked = book(client)
    set_status(client, booked["id"], "CONFIRMED")
    [queued] = for_appointment(client, booked["id"])
    for action in ("send", "fail", "retry", "send", "deliver"):
        assert act(client, queued["id"], action).status_code == 200
    set_status(client, booked["id"], "CANCELLED")
    slot_id = client.get("/api/waitlist/opportunities").json()[0]["slot"]["id"]
    entry = client.post("/api/waitlist", json={"patient_id": 3, "service_id": 1, "date_from": THURSDAY, "date_to": THURSDAY, "contact_preference": "EMAIL"}).json()
    assert client.post(f"/api/waitlist/{entry['id']}/offer", json={"slot_id": slot_id}).status_code == 200
    chat = Chat(client)
    chat.send("I want to speak to a person.")
    chat.send("Demo Patient One")
    chat.send("5550100001")
    assert client.get("/notifications").status_code == 200 and client.get("/").status_code == 200
    assert {n["type"] for n in listing(client)} >= {
        "APPOINTMENT_CONFIRMATION", "APPOINTMENT_CANCELLATION", "APPOINTMENT_REMINDER", "WAITLIST_OFFER", "CALLBACK_ACKNOWLEDGEMENT",
    }

    # And there is nothing in the code that could send: no network, mail or messaging client is imported.
    for module in (outbox, notification_templates):
        source = inspect.getsource(module)
        for forbidden in ("import requests", "import httpx", "import smtplib", "import socket", "urllib", "http.client", "twilio", "webhook(", "api_key"):
            assert forbidden not in source, (module.__name__, forbidden)


def test_staff_notes_never_reach_notifications(client):
    task = client.post("/api/callbacks", json={"name": "Demo Patient One", "mobile": "5550100001", "reason": "Wants a call", "notes": "PRIVATE-STAFF-NOTE"}).json()
    client.post(f"/api/callbacks/{task['id']}/status", json={"status": "IN_PROGRESS", "notes": "ANOTHER-PRIVATE-NOTE"})
    [ack] = listing(client, type="CALLBACK_ACKNOWLEDGEMENT")
    for text in (ack["message"], client.get("/notifications").text):
        assert "PRIVATE-STAFF-NOTE" not in text and "ANOTHER-PRIVATE-NOTE" not in text and "Wants a call" not in text
    events = [e for e in client.get("/api/patients/1/timeline").json()["events"] if e["kind"].startswith("NOTIFICATION_")]
    assert events and all("PRIVATE" not in (e["detail"] or "") for e in events)


def test_demo_reset_clears_and_reseeds_the_outbox(client):
    booked = book(client)
    set_status(client, booked["id"], "CONFIRMED")
    assert len(listing(client)) >= 2
    with client.app.state.session_factory() as db:
        reset_demo_data(db)
    # Only the seeded confirmed booking's confirmation remains.
    assert [(n["type"], n["recipient_name"], n["status"]) for n in listing(client)] == [
        ("APPOINTMENT_CONFIRMATION", "Demo Patient One", "QUEUED")
    ]
