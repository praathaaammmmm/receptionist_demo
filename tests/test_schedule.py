"""Phase 6: doctor weekly schedule and blocked periods."""
from datetime import date, datetime

import pytest

from app.models import DoctorBlock
from app.seed import reset_demo_data

from .test_assistant import Chat, slot_options
from .test_closed_days import WEDNESDAY, client_at  # noqa: F401  (fixture)

THURSDAY, FRIDAY, SUNDAY = "2026-10-15", "2026-10-16", "2026-10-18"
CONFLICT = "This time cannot be blocked because it has a scheduled patient appointment."


@pytest.fixture
def client(client_at):  # noqa: F811
    """Seeded app with the clock fixed at Wednesday 14 Oct 2026, 10:00."""
    return client_at(WEDNESDAY)


def block(client, doctor_id, day, start="", end="", reason="LEAVE"):
    return client.post(
        f"/doctor/{doctor_id}/blocks", data={"date": day, "start_time": start, "end_time": end, "reason": reason},
        follow_redirects=False,
    )


def slots(client, doctor_id, day):
    return client.get(f"/api/doctors/{doctor_id}/slots", params={"date": day}).json()


def schedule(client, doctor_id, start=None):
    return client.get(f"/api/doctors/{doctor_id}/schedule", params={"start": start} if start else {}).json()


def day_of(week, day):
    return next(d for d in week["days"] if d["date"] == day)


def times(entries, kind):
    return [e["start_time"][11:16] for e in entries if e["kind"] == kind]


def test_weekly_calendar_shows_appointments_and_available_slots(client):
    week = schedule(client, 1)
    assert [d["date"] for d in week["days"]] == [f"2026-10-{n}" for n in range(14, 21)]

    today = day_of(week, "2026-10-14")
    seeded = [e for e in today["entries"] if e["kind"] == "appointment"]
    assert seeded and seeded[0]["status"] == "CONFIRMED" and seeded[0]["patient"] == "Demo Patient One"
    assert today["booked"] == len([e for e in seeded if e["status"] != "CANCELLED"])
    assert today["available"] == len(times(today["entries"], "slot")) > 0
    assert seeded[0]["start_time"][11:16] not in times(today["entries"], "slot")  # a booked time is not also free

    # A new booking appears immediately and its slot stops being offered.
    target = next(s for s in slots(client, 1, THURSDAY) if s["available"])
    before = day_of(week, THURSDAY)
    booked = client.post("/api/appointments", json={"patient_id": 2, "slot_id": target["id"], "service_id": 1}).json()
    after = day_of(schedule(client, 1), THURSDAY)
    entry = next(e for e in after["entries"] if e.get("appointment_id") == booked["id"])
    assert entry["status"] == "PENDING" and entry["start_time"] == target["start_time"]
    assert after["available"] == before["available"] - 1
    assert after["booked"] == before["booked"] + 1
    assert target["start_time"][11:16] not in times(after["entries"], "slot")

    # Cancelling keeps the cancelled entry visible and frees the slot again.
    client.post(f"/api/appointments/{booked['id']}/status", json={"status": "CANCELLED"})
    cancelled = day_of(schedule(client, 1), THURSDAY)
    assert next(e for e in cancelled["entries"] if e.get("appointment_id") == booked["id"])["status"] == "CANCELLED"
    assert cancelled["available"] == before["available"] and cancelled["booked"] == before["booked"]

    page = client.get("/doctor?doctor_id=1&view=schedule").text
    assert "Weekly schedule" in page and "Demo Patient One" in page and "demo-only switcher" in page
    for label in ("Available", "Pending", "Confirmed", "Arrived", "Completed", "No-show", "Cancelled", "Blocked"):
        assert label in page.split('class="cal-legend"')[1].split("</ul>")[0]


def test_doctor_can_move_between_weeks(client):
    next_week = client.get("/doctor?doctor_id=1&view=schedule&week=1")
    assert next_week.status_code == 200
    assert "Wed, 21 Oct to Tue, 27 Oct" in next_week.text
    assert "Slots open 7 days ahead." in next_week.text  # beyond the booking window: hours shown, no slots yet
    assert "week=2" in next_week.text and "week=0" in next_week.text and "This week" in next_week.text
    last_week = client.get("/doctor?doctor_id=1&view=schedule&week=-1")
    assert last_week.status_code == 200 and "Wed, 07 Oct to Tue, 13 Oct" in last_week.text
    assert schedule(client, 1, "2026-10-21")["days"][0]["bookable"] is False
    assert client.get("/doctor?doctor_id=1&view=schedule&week=999").status_code == 200  # clamped, not an error


def test_blocked_period_removes_matching_slots_everywhere(client):
    before = slots(client, 1, THURSDAY)
    summary_before = client.get("/api/dashboard/summary").json()["available_slots_week"]
    saved = block(client, 1, THURSDAY, "10:00", "12:00", "TRAINING")
    assert saved.status_code == 303 and "notice=block_saved" in saved.headers["location"]

    after = slots(client, 1, THURSDAY)
    blocked = [s["start_label"] for s in after if s["status"] == "BLOCKED"]
    assert blocked == ["10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM"]
    assert not any(s["available"] for s in after if s["status"] == "BLOCKED")
    assert len([s for s in after if s["available"]]) == len([s for s in before if s["available"]]) - 4
    assert client.get("/api/dashboard/summary").json()["available_slots_week"] == summary_before - 4
    assert [s["status"] for s in slots(client, 2, THURSDAY)].count("BLOCKED") == 0  # other doctors unaffected

    day = day_of(schedule(client, 1), THURSDAY)
    assert [(e["reason"], e["start_time"][11:16], e["end_time"][11:16]) for e in day["entries"] if e["kind"] == "block"] == [
        ("TRAINING", "10:00", "12:00")
    ]
    assert not set(times(day["entries"], "slot")) & {"10:00", "10:30", "11:00", "11:30"}
    assert "Blocked · Training" in client.get("/doctor?doctor_id=1&view=schedule").text
    # Staff availability screen explains it rather than offering a booking link.
    staff = client.get(f"/availability?doctor_id=1&date={THURSDAY}").text
    assert staff.count("Doctor unavailable") == 4


def test_staff_and_assistant_cannot_book_blocked_time(client):
    target = next(s for s in slots(client, 1, THURSDAY) if s["start_label"] == "10:00 AM")
    assert block(client, 1, THURSDAY, "10:00", "12:00").status_code == 303

    # Staff booking API (also used by the staff booking screen).
    refused = client.post("/api/appointments", json={"patient_id": 2, "slot_id": target["id"], "service_id": 1})
    assert refused.status_code == 400
    assert refused.json()["message"] == "The doctor is not available at that time. Please choose another available time."

    # Patient assistant: asks for that doctor and day, and is never offered the blocked times.
    chat = Chat(client)
    reply = chat.send("I want to book a consultation.")
    reply = chat.pick(reply, "New patient")
    chat.send("Asha Example")
    reply = chat.send("5553330001")
    reply = chat.pick(reply, "Skip")
    reply = chat.pick(reply, "General Consultation")
    reply = chat.pick(reply, "Dr. Anika Rao")
    reply = chat.send(action="pick", value=THURSDAY)
    labels = []
    for _ in range(5):
        labels += [o["label"] for o in slot_options(reply)]
        reply = chat.pick(reply, "Show other times")
    thursday = [label for label in labels if label.startswith("Thu, 15 Oct")]
    assert "Thu, 15 Oct · 9:00 AM · Dr. Anika Rao" in thursday and "Thu, 15 Oct · 12:00 PM · Dr. Anika Rao" in thursday
    assert not [label for label in thursday if any(t in label for t in ("10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM"))]

    # Even a forged selection of the blocked slot is refused and fresh times are offered.
    chat.send(action="slot", value=target["id"])
    forced = chat.send(action="confirm")
    assert forced["booking"] is None
    assert "not available at that time" in forced["messages"][0]["text"]
    assert len(slot_options(forced)) == 3
    assert not [a for a in client.get("/api/appointments").json() if a["start_time"] == target["start_time"]]


def test_whole_day_block_means_no_times_that_day(client):
    assert block(client, 1, FRIDAY, reason="LEAVE").status_code == 303
    assert all(s["status"] == "BLOCKED" for s in slots(client, 1, FRIDAY))
    day = day_of(schedule(client, 1), FRIDAY)
    assert day["available"] == 0 and [e["all_day"] for e in day["entries"] if e["kind"] == "block"] == [True]
    chat = Chat(client)
    reply = chat.send("I want to book a consultation.")
    reply = chat.pick(reply, "New patient")
    chat.send("Asha Example")
    reply = chat.send("5553330002")
    reply = chat.pick(reply, "Skip")
    reply = chat.pick(reply, "General Consultation")
    reply = chat.pick(reply, "Dr. Anika Rao")
    reply = chat.send(action="pick", value=FRIDAY)
    assert all(o["label"].startswith("Sat, 17 Oct") for o in slot_options(reply))


def test_blocking_fails_when_it_overlaps_an_active_appointment(client):
    target = next(s for s in slots(client, 1, THURSDAY) if s["start_label"] == "11:00 AM")
    booked = client.post("/api/appointments", json={"patient_id": 2, "slot_id": target["id"], "service_id": 1}).json()

    for start, end in (("10:00", "12:00"), ("11:15", "11:20"), ("", "")):
        refused = block(client, 1, THURSDAY, start, end)
        assert refused.status_code == 400
        assert CONFLICT in refused.text
    assert schedule(client, 1)["blocks"] == []
    assert block(client, 1, THURSDAY, "11:30", "12:30").status_code == 303  # touching, not overlapping, is fine

    # Once the appointment is cancelled it no longer stands in the way.
    client.post(f"/api/appointments/{booked['id']}/status", json={"status": "CANCELLED"})
    assert block(client, 1, THURSDAY, "10:00", "11:30").status_code == 303


def test_removing_a_future_block_restores_availability(client):
    available_before = [s["id"] for s in slots(client, 1, THURSDAY) if s["available"]]
    block(client, 1, THURSDAY, "10:00", "12:00")
    [saved] = schedule(client, 1)["blocks"]
    assert len([s for s in slots(client, 1, THURSDAY) if s["available"]]) == len(available_before) - 4

    other_doctor = client.post(f"/doctor/2/blocks/{saved['id']}/remove", follow_redirects=False)
    assert other_doctor.status_code == 403
    assert len(schedule(client, 1)["blocks"]) == 1

    removed = client.post(f"/doctor/1/blocks/{saved['id']}/remove", follow_redirects=False)
    assert removed.status_code == 303 and "notice=block_removed" in removed.headers["location"]
    assert schedule(client, 1)["blocks"] == []
    assert [s["id"] for s in slots(client, 1, THURSDAY) if s["available"]] == available_before
    rebooked = client.post("/api/appointments", json={"patient_id": 2, "slot_id": available_before[2], "service_id": 1})
    assert rebooked.status_code == 201
    assert client.post("/doctor/1/blocks/9999/remove", follow_redirects=False).status_code == 404


def test_past_blocks_cannot_be_removed(client):
    with client.app.state.session_factory() as db:
        old = DoctorBlock(doctor_id=1, start_time=datetime(2026, 10, 12, 9, 0), end_time=datetime(2026, 10, 12, 12, 0), reason="LEAVE")
        db.add(old)
        db.commit()
        old_id = old.id
    refused = client.post(f"/doctor/1/blocks/{old_id}/remove", follow_redirects=False)
    assert refused.status_code == 400 and "Past blocked periods" in refused.text


def test_sunday_stays_clinic_closed_and_cannot_be_blocked(client):
    refused = block(client, 1, SUNDAY)
    assert refused.status_code == 400
    assert "Smriti Raj Dentistry is closed on Sunday. There is nothing to block on that day." in refused.text
    assert schedule(client, 1)["blocks"] == []

    sunday = day_of(schedule(client, 1), SUNDAY)
    assert sunday["closed"] is True and sunday["working"] is False and sunday["entries"] == [] and sunday["available"] == 0
    assert slots(client, 1, SUNDAY) == []
    page = client.get("/doctor?doctor_id=1&view=schedule").text
    assert "Smriti Raj Dentistry is closed on Sunday." in page and "Clinic closed" in page


@pytest.mark.parametrize(
    "day, start, end, reason, message",
    [
        ("2026-10-13", "", "", "LEAVE", "Only future time can be blocked."),  # yesterday
        ("2026-10-14", "09:00", "09:30", "LEAVE", "Only future time can be blocked."),  # earlier today
        (THURSDAY, "12:00", "11:00", "LEAVE", "The end time must be after the start time."),
        (THURSDAY, "10:00", "", "LEAVE", "Please enter both a start and an end time"),
        (THURSDAY, "", "", "HOLIDAY", "Please choose a reason"),
        ("not-a-date", "", "", "LEAVE", "Please enter a valid date and times."),
    ],
)
def test_block_requests_are_validated(client, day, start, end, reason, message):
    refused = block(client, 1, day, start, end, reason)
    assert refused.status_code == 400
    assert message in refused.text
    assert schedule(client, 1)["blocks"] == []


def test_blocks_cannot_overlap_and_reset_clears_them(client):
    assert block(client, 1, THURSDAY, "10:00", "12:00").status_code == 303
    again = block(client, 1, THURSDAY, "11:00", "13:00")
    assert again.status_code == 400 and "already blocked" in again.text
    for reason in ("PERSONAL", "TRAINING", "OTHER"):
        assert block(client, 2, THURSDAY, "14:00", "15:00", reason).status_code in (303, 400)
    with client.app.state.session_factory() as db:
        reset_demo_data(db)
    assert schedule(client, 1)["blocks"] == [] and schedule(client, 2)["blocks"] == []
    assert not [s for s in slots(client, 1, THURSDAY) if s["status"] == "BLOCKED"]


def test_doctor_calendar_is_reachable_from_the_menu_and_the_workspace(client):
    # Sidebar/top navigation item on every staff page.
    for path in ("/", "/patients", "/availability", "/settings", "/doctor", "/patients/1/timeline"):
        menu = client.get(path).text.split('<nav class="nav"')[1].split("</nav>")[0]
        assert 'href="/doctor/calendar"' in menu, path
        assert "<span>Doctor calendar</span>" in menu, path

    # "Weekly schedule" tab inside the doctor workspace, keeping the selected doctor.
    workspace = client.get("/doctor?doctor_id=2").text
    tabs = workspace.split('class="tabs"')[1].split("</nav>")[0]
    assert 'href="/doctor/calendar?doctor_id=2">Weekly schedule</a>' in tabs
    assert 'href="/doctor?doctor_id=2">Today</a>' in tabs

    # Both open the same calendar view.
    from_menu = client.get("/doctor/calendar")
    from_tab = client.get("/doctor/calendar?doctor_id=2")
    assert from_menu.status_code == from_tab.status_code == 200
    for page in (from_menu.text, from_tab.text):
        assert "Weekly schedule" in page and 'class="cal"' in page and page.count('class="cal-day') == 7
        assert "Previous week" in page and "Next week" in page
        menu = page.split('<nav class="nav"')[1].split("</nav>")[0]
        active = menu.split('href="/doctor/calendar"')[1].split(">")[0]
        assert 'aria-current="page"' in active and "is-active" in active
    assert "Dr. Vikram Shah · Wed, 14 Oct to Tue, 20 Oct" in from_tab.text
    assert "Dr. Anika Rao · Wed, 14 Oct to Tue, 20 Oct" in from_menu.text  # defaults to the first doctor

    # The calendar keeps the doctor switcher and week controls on the same address...
    for doctor_id in (1, 2, 3):
        assert f'href="/doctor/calendar?doctor_id={doctor_id}"' in from_tab.text
    assert 'href="/doctor/calendar?doctor_id=2&week=1"' in from_tab.text
    assert 'href="/doctor/calendar?doctor_id=2&week=-1"' in from_tab.text
    assert 'href="/doctor?doctor_id=2">Today</a>' in from_tab.text  # ...and the tab back to today's list

    # The earlier address still works and lands on the same page.
    old = client.get("/doctor?doctor_id=2&view=schedule&week=1", follow_redirects=False)
    assert old.status_code == 303
    assert old.headers["location"] == "/doctor/calendar?doctor_id=2&week=1"


def test_calendar_renders_slots_bookings_blocks_and_closed_sunday(client):
    target = next(s for s in slots(client, 3, FRIDAY) if s["available"])
    client.post("/api/appointments", json={"patient_id": 2, "slot_id": target["id"], "service_id": 3})
    assert block(client, 3, FRIDAY, "15:00", "16:00", "PERSONAL").headers["location"].startswith("/doctor/calendar?doctor_id=3")

    page = client.get("/doctor/calendar?doctor_id=3").text
    friday = next(c for c in page.split('<section class="cal-day')[1:] if "16 Oct" in c.split("</header>")[0])
    assert "cal-appt is-pending" in friday and "Demo Patient Two" in friday and "PENDING" in friday
    assert "Blocked · Personal" in friday and "3:00 PM – 4:00 PM" in friday
    assert friday.count('class="cal-item cal-slot"') == 13  # 16 slots, one booked, two blocked
    assert ">3:00 PM</span>" not in friday.split("Blocked")[0].split("cal-slot")[-1]
    sunday = next(c for c in page.split('<section class="cal-day')[1:] if "18 Oct" in c.split("</header>")[0])
    assert "is-closed" in sunday.split(">")[0] and "Clinic closed" in sunday and "cal-slot" not in sunday
    assert "demo-only switcher" in page
