"""Clinic-wide closed days (Sunday), with the clock fixed so weekdays are predictable."""
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import Slot

from .test_assistant import Chat, slot_options

WEDNESDAY = datetime(2026, 10, 14, 10, 0)  # window: Wed 14 ... Tue 20, Sunday is the 18th
MONDAY = datetime(2026, 10, 12, 10, 0)  # window: Mon 12 ... Sun 18, next Monday is outside it
SUNDAY = date(2026, 10, 18)
NEXT_MONDAY = date(2026, 10, 19)
CLOSED_AND_NEXT = "Smriti Raj Dentistry is closed on Sunday. The next available appointments are on Monday."


@pytest.fixture
def client_at(monkeypatch, tmp_path):
    """Build a freshly seeded app as if it were started at the given moment."""

    def build(moment: datetime) -> TestClient:
        monkeypatch.setattr("app.utils.now", lambda: moment)
        return TestClient(create_app(f"sqlite:///{tmp_path / 'closed.db'}"))

    return build


def offered_days(reply) -> list[date]:
    """Dates of the slot options in a reply, read from labels like 'Mon, 19 Oct · 9:00 AM · Dr. X'."""
    days = []
    for option in slot_options(reply):
        day = option["label"].split(" · ")[0]
        days.append(WEDNESDAY.date() if day == "Today" else datetime.strptime(f"{day} 2026", "%a, %d %b %Y").date())
    return days


def to_date_step(chat):
    reply = chat.send("I want to book a consultation.")
    reply = chat.pick(reply, "New patient")
    chat.send("Asha Example")
    reply = chat.send("5550710001")
    reply = chat.pick(reply, "Skip")
    reply = chat.pick(reply, "General Consultation")
    return chat.pick(reply, "No preference")


def test_sunday_is_closed_and_disabled_in_staff_booking_flow(client_at):
    client = client_at(WEDNESDAY)

    # Booking screen: Sunday stays visible, is labelled, and cannot be selected.
    page = client.get("/bookings/new").text
    sunday_chip = page.split(f'value="{SUNDAY.isoformat()}"')[1].split("</label>")[0]
    assert "disabled" in sunday_chip
    assert "Clinic closed" in sunday_chip
    monday_chip = page.split(f'value="{NEXT_MONDAY.isoformat()}"')[1].split("</label>")[0]
    assert "disabled" not in monday_chip and "Clinic closed" not in monday_chip
    # Deep links to a closed day fall back to an open one.
    assert f'"date": "{SUNDAY.isoformat()}"' not in client.get(f"/bookings/new?date={SUNDAY.isoformat()}").text

    # Availability screen: an explanation instead of an empty slot list, and nothing to book.
    for doctor in client.get("/api/doctors").json():
        closed = client.get(f"/availability?doctor_id={doctor['id']}&date={SUNDAY.isoformat()}").text
        assert "Clinic closed" in closed
        assert "Smriti Raj Dentistry is closed on Sunday. No appointments can be booked on this day." in closed
        assert f"date={SUNDAY.isoformat()}&slot_id=" not in closed
        assert "slots available" not in closed
        assert client.get(f"/api/doctors/{doctor['id']}/slots", params={"date": SUNDAY.isoformat()}).json() == []
    open_day = client.get(f"/availability?doctor_id=1&date={NEXT_MONDAY.isoformat()}").text
    assert f"date={NEXT_MONDAY.isoformat()}&slot_id=" in open_day
    assert "No appointments can be booked on this day." not in open_day


def test_clinic_closed_day_overrides_doctor_working_days(client_at):
    client = client_at(WEDNESDAY)
    # A doctor ticked as working every day still gets no Sunday slots.
    response = client.post(
        "/settings/doctors/1",
        data={
            "name": "Dr. Anika Rao", "speciality": "General Dentistry", "work_start": "09:00", "work_end": "17:00",
            "consultation_minutes": "30", "working_days": ["0", "1", "2", "3", "4", "5", "6"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert client.get("/api/doctors/1/slots", params={"date": SUNDAY.isoformat()}).json() == []
    assert len(client.get("/api/doctors/1/slots", params={"date": NEXT_MONDAY.isoformat()}).json()) == 16

    # Even a Sunday slot that somehow exists in the database cannot be booked.
    with client.app.state.session_factory() as db:
        stray = Slot(doctor_id=1, start_time=datetime(2026, 10, 18, 10, 0), end_time=datetime(2026, 10, 18, 10, 30))
        db.add(stray)
        db.commit()
        stray_id = stray.id
    refused = client.post("/api/appointments", json={"patient_id": 1, "slot_id": stray_id, "service_id": 1})
    assert refused.status_code == 400
    assert refused.json()["message"] == "Smriti Raj Dentistry is closed on Sunday. Please choose another day."
    assert client.get("/api/doctors/1/slots", params={"date": SUNDAY.isoformat()}).json() == []


def test_assistant_does_not_offer_sunday_and_explains_when_asked(client_at):
    chat = Chat(client_at(WEDNESDAY))
    reply = to_date_step(chat)
    day_labels = [o["label"] for o in reply["options"] if o["action"] == "pick"]
    assert day_labels == ["Earliest available", "Today", "Thu, 15 Oct", "Fri, 16 Oct", "Sat, 17 Oct", "Mon, 19 Oct", "Tue, 20 Oct"]

    # Typing the closed day at the day step is answered explicitly.
    reply = chat.send("Sunday please")
    assert reply["messages"][0]["text"] == CLOSED_AND_NEXT
    assert reply["state"]["step"] == "slot"

    # So is a general question, outside any booking.
    question = Chat(chat.client).send("Can I come in on Sunday?")
    assert question["messages"][0]["text"] == CLOSED_AND_NEXT
    assert question["state"]["flow"] is None


def test_assistant_offers_only_monday_or_later_after_sunday_request(client_at):
    client = client_at(WEDNESDAY)
    chat = Chat(client)
    reply = chat.send("I want to book a consultation on Sunday.")
    assert reply["messages"][0]["text"] == CLOSED_AND_NEXT

    reply = chat.pick(reply, "New patient")
    chat.send("Asha Example")
    reply = chat.send("5550710002")
    reply = chat.pick(reply, "Skip")
    reply = chat.pick(reply, "General Consultation")
    reply = chat.pick(reply, "No preference")  # the day question is skipped: it was already answered
    assert reply["state"]["step"] == "slot"

    days = offered_days(reply)
    assert len(days) == 3
    for _ in range(4):
        reply = chat.pick(reply, "Show other times")
        days += offered_days(reply)
    assert days[0] == NEXT_MONDAY
    assert all(day >= NEXT_MONDAY for day in days)
    assert SUNDAY not in days

    reply = chat.send(action="slot", value=slot_options(reply)[0]["value"])
    booking = chat.pick(reply, "Confirm booking")["booking"]
    assert booking["status"] == "PENDING"
    saved = next(a for a in client.get("/api/appointments").json() if a["id"] == booking["reference"])
    assert saved["start_time"][:10] >= NEXT_MONDAY.isoformat()


def test_assistant_explains_closure_when_next_open_day_is_beyond_the_window(client_at):
    """On a Monday the following Monday cannot be booked yet; the assistant must still say why."""
    chat = Chat(client_at(MONDAY))
    reply = to_date_step(chat)
    reply = chat.send("Sunday")
    texts = [m["text"] for m in reply["messages"]]
    assert texts[0] == "Smriti Raj Dentistry is closed on Sunday."
    assert "up to 7 days ahead" in texts[1]
    labels = [o["label"] for o in slot_options(reply)]
    assert len(labels) == 3
    assert not [label for label in labels if label.startswith("Sun,")]
