"""Phase 2: patient-facing assistant and callback tasks."""
from datetime import date, timedelta

import pytest

from app import config, knowledge


class Chat:
    """Drives the assistant endpoint the way the public page does, carrying state between turns."""

    def __init__(self, client):
        self.client, self.state, self.transcript = client, None, []

    def send(self, text="", action=None, value=None):
        response = self.client.post(
            "/api/assistant/message", json={"text": text, "action": action, "value": value, "state": self.state}
        )
        assert response.status_code == 200, response.text
        reply = response.json()
        self.state = reply["state"]
        self.transcript += [m["text"] for m in reply["messages"]]
        return reply

    def pick(self, reply, label_part):
        option = next(o for o in reply["options"] if label_part in o["label"])
        return self.send(action=option["action"], value=option["value"])

    @property
    def text(self):
        return "\n".join(self.transcript)


@pytest.fixture
def chat(client):
    return Chat(client)


def slot_options(reply):
    return [o for o in reply["options"] if o["action"] == "slot"]


def to_slot_offer(chat, name="Asha Example", mobile="555 070 0001"):
    """Run the booking conversation up to the point where three times are offered (from tomorrow)."""
    reply = chat.send("I want to book a consultation.")
    reply = chat.pick(reply, "New patient")
    assert reply["state"]["step"] == "name"
    chat.send(name)
    reply = chat.send(mobile)
    reply = chat.pick(reply, "Skip")
    reply = chat.pick(reply, "Root Canal Treatment")
    reply = chat.pick(reply, "No preference")
    days = [o for o in reply["options"] if o["action"] == "pick" and o["value"] != "earliest"]
    return chat.send(action="pick", value=days[1]["value"])  # days[0] is today


def callbacks(client, **params):
    return client.get("/api/callbacks", params=params).json()


def test_assistant_page_is_public_and_shows_no_patient_data(client):
    page = client.get("/assistant")
    assert page.status_code == 200
    assert "AI Appointment Assistant" in page.text
    assert knowledge.CLINIC_WEBSITE in page.text
    assert "cannot give dental or medical advice" in page.text
    assert "Demo Patient" not in page.text
    assert "555010" not in page.text


def test_faq_is_answered_from_approved_knowledge_without_a_callback(chat, client):
    reply = chat.send("What are your opening hours?")
    assert reply["messages"][0]["text"] == knowledge.CLINIC_HOURS
    reply = chat.send("Do you offer dental implants?")
    assert "Dental Implants is one of the services we offer" in reply["messages"][0]["text"]
    assert "can't give dental or medical advice" in reply["messages"][0]["text"]
    reply = chat.send("Who are your doctors?")
    assert "Dr. Anika Rao" in reply["messages"][0]["text"]
    assert callbacks(client) == []


def test_ai_booking_offers_three_slots_and_appears_in_dashboard(chat, client):
    reply = to_slot_offer(chat)
    offered = slot_options(reply)
    assert len(offered) == 3

    reply = chat.send(action="slot", value=offered[0]["value"])
    assert reply["state"]["step"] == "confirm"
    assert "Asha Example" in reply["messages"][-1]["text"]
    reply = chat.pick(reply, "Confirm booking")

    booking = reply["booking"]
    assert booking["status"] == "PENDING"
    assert booking["service"] == "Root Canal Treatment"
    assert f"#{booking['reference']}" in chat.text

    upcoming = client.get("/api/appointments", params={"scope": "upcoming"}).json()
    saved = next(a for a in upcoming if a["id"] == booking["reference"])
    assert saved["source"] == "AI_DEMO"
    assert saved["status"] == "PENDING"
    assert saved["patient"]["name"] == "Asha Example"
    assert saved["patient"]["mobile"] == "5550700001"

    dashboard = client.get("/").text
    assert "Asha Example" in dashboard
    assert "AI_DEMO" in dashboard


def test_assistant_booking_reuses_existing_patient_without_revealing_details(chat, client):
    before = len(client.get("/api/patients").json())
    reply = to_slot_offer(chat, name="Someone Else", mobile="5550100001")  # seeded Demo Patient One
    reply = chat.send(action="slot", value=slot_options(reply)[0]["value"])
    reply = chat.pick(reply, "Confirm booking")
    assert reply["booking"]
    assert len(client.get("/api/patients").json()) == before
    assert "Demo Patient One" not in chat.text
    assert "patient.one@example.com" not in chat.text
    saved = next(a for a in client.get("/api/appointments").json() if a["id"] == reply["booking"]["reference"])
    assert saved["patient"]["name"] == "Demo Patient One"
    assert "Name given: Someone Else" in saved["reason"]


def test_taken_slot_shows_friendly_message_and_fresh_options(chat, client, new_patient, service_id):
    reply = to_slot_offer(chat)
    chosen = slot_options(reply)[0]["value"]
    reply = chat.send(action="slot", value=chosen)

    # Someone else takes the slot before the patient confirms.
    rival = client.post(
        "/api/appointments", json={"patient_id": new_patient["id"], "slot_id": chosen, "service_id": service_id}
    )
    assert rival.status_code == 201

    reply = chat.pick(reply, "Confirm booking")
    assert reply["booking"] is None
    assert reply["messages"][0]["text"] == config.SLOT_TAKEN_MESSAGE
    fresh = slot_options(reply)
    assert len(fresh) == 3
    assert chosen not in [o["value"] for o in fresh]

    reply = chat.send(action="slot", value=fresh[0]["value"])
    assert chat.pick(reply, "Confirm booking")["booking"]["status"] == "PENDING"


def test_speak_to_a_person_creates_open_callback(chat, client):
    reply = chat.send("I want to speak to a person.")
    assert reply["state"]["flow"] == "callback"
    assert callbacks(client) == []  # nothing is created until we know who to call
    chat.send("Ravi Example")
    reply = chat.send("555 070 0002")

    assert knowledge.CALLBACK_PROMISE in chat.text
    assert "Our staff will contact you during clinic hours." in chat.text
    tasks = callbacks(client)
    assert len(tasks) == 1
    assert tasks[0]["status"] == "OPEN"
    assert tasks[0]["source"] == "AI_DEMO"
    assert tasks[0]["name"] == "Ravi Example"
    assert tasks[0]["mobile"] == "5550700002"
    assert reply["callback"] == {"reference": f"C-{tasks[0]['id']}", "status": "OPEN", "mobile": "5550700002"}
    assert "Ravi Example" in client.get("/").text


def test_cghs_enquiry_creates_callback_and_never_confirms_eligibility(chat, client):
    reply = chat.send("Am I eligible for treatment under CGHS?")
    assert "can't confirm CGHS or ECHS eligibility" in reply["messages"][0]["text"]
    reply = chat.pick(reply, "CGHS")
    chat.send("Meena Example")
    chat.send("5550700003")

    tasks = callbacks(client)
    assert len(tasks) == 1
    assert tasks[0]["status"] == "OPEN"
    assert "CGHS/ECHS enquiry" in tasks[0]["reason"]
    assert "Scheme: CGHS" in tasks[0]["reason"]
    assert "Eligibility has not been confirmed" in tasks[0]["reason"]
    lowered = chat.text.lower()
    for approval in ("you are eligible", "you're eligible", "is covered", "are covered", "approved"):
        assert approval not in lowered
    assert knowledge.CALLBACK_PROMISE in chat.text


@pytest.mark.parametrize(
    "question",
    [
        "My tooth hurts a lot, which antibiotic should I take?",
        "Do I need a root canal?",
        "Is an implant safe if I am pregnant?",
    ],
)
def test_clinical_question_creates_callback_instead_of_advice(chat, client, question):
    appointments_before = client.get("/api/appointments").json()
    reply = chat.send(question)
    assert reply["state"]["flow"] == "callback"
    assert "can't suggest a diagnosis or treatment" in reply["messages"][0]["text"]
    chat.send("Kiran Example")
    chat.send("5550700004")

    tasks = callbacks(client)
    assert len(tasks) == 1
    assert tasks[0]["status"] == "OPEN"
    assert tasks[0]["reason"].startswith("Clinical question the assistant did not answer")
    assert question in tasks[0]["reason"]
    assert client.get("/api/appointments").json() == appointments_before  # nothing was booked
    assert "Yes," not in chat.text


def test_unsupported_question_creates_callback(chat, client):
    reply = chat.send("Do you accept my insurance card?")
    assert "don't have approved information" in reply["messages"][0]["text"]
    # A question typed where a name is expected is not stored as a name.
    assert chat.send("Can you just tell me?")["state"]["step"] == "name"
    chat.send("Leela Example")
    chat.send("5550700005")
    tasks = callbacks(client)
    assert [t["reason"] for t in tasks] == ['Question the assistant could not answer: "Do you accept my insurance card?"']


def test_callback_status_transitions(chat, client):
    chat.send("I want to speak to a person.")
    chat.send("Ravi Example")
    chat.send("5550700006")
    task = callbacks(client)[0]
    url = f"/api/callbacks/{task['id']}/status"
    assert client.get("/api/callbacks/summary").json() == {"open": 1, "in_progress": 0, "completed": 0}

    response = client.post(url, json={"status": "IN_PROGRESS", "notes": "Left a voicemail"})
    assert response.status_code == 200
    assert response.json()["status"] == "IN_PROGRESS"
    assert response.json()["notes"] == "Left a voicemail"

    assert client.post(url, json={"status": "OPEN"}).status_code == 400
    assert client.post(url, json={"status": "DONE"}).status_code == 400
    assert client.post(url, json={"status": "COMPLETED"}).json()["status"] == "COMPLETED"
    assert client.post(url, json={"status": "IN_PROGRESS"}).status_code == 400
    assert client.get("/api/callbacks/summary").json() == {"open": 0, "in_progress": 0, "completed": 1}
    assert client.post("/api/callbacks/9999/status", json={"status": "COMPLETED"}).status_code == 404


def test_staff_complete_callback_from_dashboard(chat, client):
    chat.send("I want to speak to a person.")
    chat.send("Ravi Example")
    chat.send("5550700007")
    task = callbacks(client)[0]
    assert "Callback tasks" in client.get("/").text

    response = client.post(
        f"/callbacks/{task['id']}/status", data={"status": "COMPLETED", "notes": "Spoke to patient"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?notice=callback_completed"
    done = callbacks(client)[0]
    assert done["status"] == "COMPLETED"
    assert done["notes"] == "Spoke to patient"
    assert "Callback task completed." in client.get("/?notice=callback_completed").text


def test_assistant_endpoint_is_rate_limited(client):
    for _ in range(config.ASSISTANT_RATE_LIMIT):
        assert client.post("/api/assistant/message", json={"action": "start"}).status_code == 200
    blocked = client.post("/api/assistant/message", json={"action": "start"})
    assert blocked.status_code == 429
    assert blocked.json()["error"] == "rate_limited"
    assert client.get("/api/dashboard/summary").status_code == 200  # staff API is unaffected


def test_assistant_offers_no_sunday_slots(chat):
    reply = chat.send("I want to book a consultation.")
    reply = chat.pick(reply, "New patient")
    chat.send("Asha Example")
    reply = chat.send("5550700009")
    reply = chat.pick(reply, "Skip")
    reply = chat.pick(reply, "General Consultation")
    reply = chat.pick(reply, "No preference")

    # Sunday is no longer offered as a day. Sending it anyway (as an out-of-date page
    # might) must be explained, never silently turned into another day.
    days = [date.fromisoformat(o["value"]) for o in reply["options"] if o["action"] == "pick" and o["value"] != "earliest"]
    assert days and all(d.weekday() != 6 for d in days)
    sunday = next(d for d in (date.today() + timedelta(days=i) for i in range(7)) if d.weekday() == 6)
    reply = chat.send(action="pick", value=sunday.isoformat())
    assert reply["messages"][0]["text"].startswith("Smriti Raj Dentistry is closed on Sunday.")

    labels = [o["label"] for o in slot_options(reply)]
    for _ in range(5):
        reply = chat.pick(reply, "Show other times")
        labels += [o["label"] for o in slot_options(reply)]
    assert len(labels) == 18
    assert not [label for label in labels if label.startswith("Sun,")]
    if date.today().weekday() == 6:
        assert not [label for label in labels if label.startswith("Today")]
