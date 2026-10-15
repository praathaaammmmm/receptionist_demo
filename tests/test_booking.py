import pytest
from sqlalchemy.exc import IntegrityError

from app import config
from app.models import Appointment


def slot_state(client, slot):
    day = slot["start_time"][:10]
    slots = client.get(f"/api/doctors/{slot['doctor_id']}/slots", params={"date": day}).json()
    return next(s for s in slots if s["id"] == slot["id"])


def book(client, patient, slot, service_id, **extra):
    body = {"patient_id": patient["id"], "slot_id": slot["id"], "service_id": service_id, **extra}
    return client.post("/api/appointments", json=body)


def test_seed_data(client):
    doctors = client.get("/api/doctors").json()
    assert len(doctors) == 3
    assert all(d["is_demo"] for d in doctors)
    assert [s["name"] for s in client.get("/api/services").json()] == [
        "General Consultation",
        "Dental Implants",
        "Root Canal Treatment",
        "Aligners",
    ]
    assert client.get("/api/clinic").json()["is_demo"] is True


def test_create_patient(client):
    response = client.post(
        "/api/patients",
        json={"name": "Asha Example", "mobile": "+1 (555) 020-0101", "email": "asha@example.com", "notes": "Test"},
    )
    assert response.status_code == 201
    patient = response.json()
    assert patient["name"] == "Asha Example"
    assert patient["mobile"] == "15550200101"
    assert patient["is_demo"] is False

    by_name = client.get("/api/patients", params={"q": "asha"}).json()
    by_mobile = client.get("/api/patients", params={"q": "0200101"}).json()
    assert [p["id"] for p in by_name] == [patient["id"]]
    assert [p["id"] for p in by_mobile] == [patient["id"]]


def test_duplicate_mobile_is_rejected(client, new_patient):
    response = client.post("/api/patients", json={"name": "Someone Else", "mobile": "5550200001"})
    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "duplicate_patient"
    assert body["patient"]["id"] == new_patient["id"]


def test_patient_requires_name_and_valid_mobile(client):
    assert client.post("/api/patients", json={"name": " ", "mobile": "5550200002"}).status_code == 400
    assert client.post("/api/patients", json={"name": "No Phone", "mobile": "12"}).status_code == 400


def test_create_appointment(client, new_patient, free_slot, service_id):
    before = client.get("/api/dashboard/summary").json()

    response = book(client, new_patient, free_slot, service_id, reason="Check-up", source="AI_DEMO")
    assert response.status_code == 201
    appointment = response.json()
    assert appointment["status"] == "PENDING"
    assert appointment["source"] == "AI_DEMO"
    assert appointment["patient"]["id"] == new_patient["id"]
    assert appointment["doctor"]["id"] == free_slot["doctor_id"]
    assert appointment["service"]["id"] == service_id
    assert appointment["reason"] == "Check-up"
    assert appointment["start_time"] == free_slot["start_time"]
    assert appointment["end_time"] == free_slot["end_time"]
    assert appointment["created_at"]

    assert slot_state(client, free_slot)["status"] == "BOOKED"
    upcoming = client.get("/api/appointments", params={"scope": "upcoming"}).json()
    assert appointment["id"] in [a["id"] for a in upcoming]

    after = client.get("/api/dashboard/summary").json()
    assert after["pending_bookings"] == before["pending_bookings"] + 1
    assert after["available_slots_week"] == before["available_slots_week"] - 1


def test_invalid_booking_source_is_rejected(client, new_patient, free_slot, service_id):
    assert book(client, new_patient, free_slot, service_id, source="PHONE").status_code == 400
    assert slot_state(client, free_slot)["available"] is True


def test_duplicate_doctor_time_is_rejected(client, new_patient, free_slot, service_id):
    assert book(client, new_patient, free_slot, service_id).status_code == 201

    other = client.post("/api/patients", json={"name": "Second Patient", "mobile": "5550200009"}).json()
    response = book(client, other, free_slot, service_id)
    assert response.status_code == 409
    assert response.json()["message"] == (
        "This slot has just been booked. Please choose another available time."
    )
    assert response.json()["message"] == config.SLOT_TAKEN_MESSAGE


def test_database_blocks_double_booking_race(client, new_patient, free_slot, service_id):
    """Even if two requests pass the availability check together, the unique index holds."""
    first = book(client, new_patient, free_slot, service_id).json()

    with client.app.state.session_factory() as db:
        existing = db.get(Appointment, first["id"])
        db.add(
            Appointment(
                patient_id=existing.patient_id,
                doctor_id=existing.doctor_id,
                service_id=existing.service_id,
                start_time=existing.start_time,
                end_time=existing.end_time,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_cancel_frees_the_slot(client, new_patient, free_slot, service_id):
    appointment = book(client, new_patient, free_slot, service_id).json()
    assert slot_state(client, free_slot)["available"] is False

    response = client.post(f"/api/appointments/{appointment['id']}/status", json={"status": "CANCELLED"})
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert slot_state(client, free_slot)["available"] is True

    # The freed slot can be booked again.
    rebooked = book(client, new_patient, free_slot, service_id)
    assert rebooked.status_code == 201
    assert rebooked.json()["id"] != appointment["id"]


def test_confirm_then_cancelled_is_final(client, new_patient, free_slot, service_id):
    appointment = book(client, new_patient, free_slot, service_id).json()
    url = f"/api/appointments/{appointment['id']}/status"
    assert client.post(url, json={"status": "CONFIRMED"}).json()["status"] == "CONFIRMED"
    assert client.post(url, json={"status": "CANCELLED"}).json()["status"] == "CANCELLED"
    assert client.post(url, json={"status": "CONFIRMED"}).status_code == 400


def test_reception_pages_render(client, new_patient, free_slot, service_id):
    appointment = book(client, new_patient, free_slot, service_id).json()
    for path in ("/", f"/?booked={appointment['id']}", "/patients", "/patients?q=test",
                 "/availability", "/bookings/new", "/settings"):
        response = client.get(path)
        assert response.status_code == 200, path
    assert "Test Patient" in client.get("/").text

    # Dashboard buttons post a form and redirect back.
    response = client.post(
        f"/appointments/{appointment['id']}/status", data={"status": "CANCELLED"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert slot_state(client, free_slot)["available"] is True


def test_editing_doctor_hours_rebuilds_slots_and_keeps_bookings(client, new_patient, free_slot, service_id):
    assert book(client, new_patient, free_slot, service_id).status_code == 201
    doctor_id, day = free_slot["doctor_id"], free_slot["start_time"][:10]

    response = client.post(
        f"/settings/doctors/{doctor_id}",
        data={
            "name": "Dr. Renamed Example",
            "speciality": "General Dentistry",
            "work_start": "09:00",
            "work_end": "11:00",
            "consultation_minutes": "20",
            "working_days": ["0", "1", "2", "3", "4", "5", "6"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    doctor = next(d for d in client.get("/api/doctors").json() if d["id"] == doctor_id)
    assert doctor["name"] == "Dr. Renamed Example"
    slots = client.get(f"/api/doctors/{doctor_id}/slots", params={"date": day}).json()
    assert len(slots) == 6
    assert {s["duration_minutes"] for s in slots} == {20}
    # The existing 30-minute booking still blocks both new 20-minute slots it overlaps.
    blocked = [s for s in slots if s["start_time"] < free_slot["end_time"] and s["end_time"] > free_slot["start_time"]]
    assert len(blocked) == 2
    assert all(s["status"] == "BOOKED" for s in blocked)
    assert any(s["available"] for s in slots)


def test_no_availability_on_sunday_when_clinic_is_closed(client):
    """The demo clinic is closed on Sunday: no seeded doctor has Sunday slots."""
    from datetime import date, timedelta

    sunday = next(d for d in (date.today() + timedelta(days=i) for i in range(7)) if d.weekday() == 6)
    doctors = client.get("/api/doctors").json()
    assert len(doctors) == 3
    for doctor in doctors:
        assert 6 not in doctor["working_days"]
        slots = client.get(f"/api/doctors/{doctor['id']}/slots", params={"date": sunday.isoformat()}).json()
        assert slots == []
