"""Phase 13: grouped navigation, one button system, confirmations, breadcrumbs and settings sections.

These pin the markup the interaction layer depends on. Routes, data and form posts are covered by
the existing tests and are unchanged.
"""
import re
from pathlib import Path

import pytest

from .test_closed_days import WEDNESDAY, client_at  # noqa: F401  (fixture)

TODAY = "2026-10-14"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(client_at):  # noqa: F811
    return client_at(WEDNESDAY)


def book_today(client, status="CONFIRMED", patient_id=2):
    slot = next(s for s in client.get("/api/doctors/1/slots", params={"date": TODAY}).json() if s["available"])
    booked = client.post("/api/appointments", json={"patient_id": patient_id, "slot_id": slot["id"], "service_id": 1}).json()
    if status != "PENDING":
        assert client.post(f"/api/appointments/{booked['id']}/status", json={"status": status}).status_code == 200
    return booked


def nav(html):
    return html[html.index('<nav class="nav"'):html.index("</nav>", html.index('<nav class="nav"'))]


def group_of(html, key):
    start = html.index(f'data-group="{key}"')
    return html[start:html.index("</details>", start)]


def test_navigation_is_grouped_in_the_agreed_order(client):
    menu = nav(client.get("/").text)
    labels = re.findall(r'class="nav-group-label[^"]*">(?:<span>)?([^<]+)<', menu)
    assert labels == ["Overview", "Reception", "Clinical", "Communication", "Insights"]
    expected = {
        "reception": ["/bookings/new", "/patients", "/check-in", "/waitlist"],
        "clinical": ["/doctor", "/doctor/calendar", "/follow-ups"],
        "communication": ["/notifications", "/assistant", "/call-demo"],
        "insights": ["/analytics"],
    }
    for key, hrefs in expected.items():
        assert re.findall(r'<a href="([^"]+)" class="nav-link', group_of(menu, key)) == hrefs
    # Settings sits apart at the bottom; Dashboard is the only Overview item.
    assert menu.index('href="/settings"') > menu.index('data-group="insights"')
    assert 'class="nav-bottom"' in menu
    for label in ("Book appointment", "Patients", "QR check-in", "Waitlist", "Doctor workspace", "Doctor calendar",
                  "Follow-ups", "Notifications", "Patient assistant", "Call demo", "Analytics", "Settings"):
        assert f"<span>{label}</span>" in menu


def test_patient_facing_tools_are_marked_as_demo(client):
    menu = nav(client.get("/").text)
    for href in ("/assistant", "/call-demo"):
        link = menu[menu.index(f'href="{href}"'):menu.index("</a>", menu.index(f'href="{href}"'))]
        assert "is-demo" in link and 'class="nav-tag"' in link and "Demo" in link
    staff = menu[menu.index('href="/notifications"'):menu.index("</a>", menu.index('href="/notifications"'))]
    assert "nav-tag" not in staff


@pytest.mark.parametrize("path, group, label", [
    ("/patients", "reception", "Patients"),
    ("/check-in", "reception", "QR check-in"),
    ("/doctor/calendar", "clinical", "Doctor calendar"),
    ("/follow-ups", "clinical", "Follow-ups"),
    ("/notifications", "communication", "Notifications"),
    ("/analytics", "insights", "Analytics"),
])
def test_active_page_and_its_group_are_marked(client, path, group, label):
    menu = nav(client.get(path).text)
    assert menu.count('aria-current="page"') == 1
    current = menu[:menu.index(f"<span>{label}</span>")]
    assert 'aria-current="page"' in current[current.rindex("<a "):]
    assert re.search(rf'class="nav-group has-active" data-group="{group}"', menu)
    assert menu.count("has-active") == 1


def test_nav_groups_are_collapsible_and_the_drawer_is_wired(client):
    html = client.get("/").text
    assert html.count('<details class="nav-group') == 4
    assert '<button class="menu-toggle" type="button" aria-controls="site-nav" aria-expanded="false">' in html
    assert 'id="site-nav"' in html
    script = (ROOT / "app/static/js/app.js").read_text()
    for feature in ('"navGroups"', "nav-open", "aria-expanded", "dataset.confirm",
                    "is-loading", "aria-disabled", "pageshow", "details.more-menu", "Escape"):
        assert feature in script


def test_dashboard_quick_actions(client):
    html = client.get("/").text
    actions = html[html.index('aria-label="Quick actions"'):html.index("</nav>", html.index('aria-label="Quick actions"'))]
    hrefs = re.findall(r'href="([^"]+)"', actions)
    assert hrefs == ["/bookings/new", "/check-in", "#callback-tasks", "#todays-bookings"]
    for label in ("Create booking", "Check in patient", "View callbacks", "View today’s schedule"):
        assert label in actions
    assert 'id="todays-bookings"' in html and 'id="callback-tasks"' in html
    for section in ("followup-summary", "waitlist-summary", "notification-summary"):
        assert f'id="{section}"' in html


def test_cancel_sits_in_more_actions_with_a_confirmation(client):
    booked = book_today(client, "PENDING")
    html = client.get("/").text
    row = html[html.index(f'id="appointment-{booked["id"]}"'):]
    row = row[:row.index("</tr>")]
    assert ">Confirm</button>" in row  # the main action stays visible
    menu = row[row.index('<details class="more-menu">'):row.index("</details>")]
    assert 'value="CANCELLED"' in menu and "btn-danger" in menu and "data-confirm=" in menu
    # The confirmation is in the page; the post itself is unchanged.
    response = client.post(f"/appointments/{booked['id']}/status", data={"status": "CANCELLED"}, follow_redirects=False)
    assert response.status_code == 303


def test_irreversible_doctor_actions_ask_first_and_saves_do_not(client):
    booked = book_today(client, "CONFIRMED")
    page = client.get(f"/doctor?doctor_id=1&appointment_id={booked['id']}").text
    arrive = page[page.rindex("<form", 0, page.index('value="ARRIVED"')):page.index('value="ARRIVED"')]
    assert "data-confirm=" in arrive
    no_show = page[page.rindex("<form", 0, page.index('value="NO_SHOW"')):page.index('value="NO_SHOW"')]
    assert "data-confirm=" in no_show
    assert page.rindex('<details class="more-menu">', 0, page.index('value="NO_SHOW"')) > page.rindex("</details>", 0, page.index('value="NO_SHOW"'))

    client.post(f"/api/appointments/{booked['id']}/status", json={"status": "ARRIVED"})
    page = client.get(f"/doctor?doctor_id=1&appointment_id={booked['id']}").text
    outcome = page[page.rindex("<form", 0, page.index("Save outcome")):page.index("Save outcome")]
    assert "data-confirm" not in outcome  # ordinary saves never ask
    complete = page[page.rindex("<form", 0, page.index('value="COMPLETED"')):page.index('value="COMPLETED"')]
    assert "data-confirm=" in complete


def test_qr_check_in_and_callback_completion_ask_first(client):
    booked = book_today(client, "CONFIRMED")
    token = client.post(f"/api/appointments/{booked['id']}/checkin-token").json()["token"]
    page = client.post("/check-in", data={"token": token}).text
    assert re.search(r'<form method="post" action="/check-in/arrive" data-confirm="[^"]+">', page)

    client.post("/api/callbacks", json={"name": "Asha Test", "mobile": "555 020 0100", "reason": "Please call me back"})
    html = client.get("/").text
    task = html[html.index("Asha Test"):]
    task = task[:task.index("</li>")]
    assert re.search(r'value="COMPLETED" data-confirm="[^"]+"', task)
    assert 'value="IN_PROGRESS">' in task  # moving to "in progress" is an ordinary save


@pytest.mark.parametrize("path, trail", [
    ("/patients/2", ["Patients"]),
    ("/doctor/calendar?doctor_id=1", ["Doctor workspace", "Doctor calendar"]),
    ("/check-in", ["Dashboard", "Reception", "QR check-in"]),
])
def test_breadcrumbs_on_deeper_pages(client, path, trail):
    html = client.get(path).text
    crumbs = html[html.index('<nav class="breadcrumbs"'):html.index("</nav>", html.index('<nav class="breadcrumbs"'))]
    for label in trail:
        assert label in crumbs
    assert crumbs.count('aria-current="page"') == 1


def test_breadcrumbs_on_qr_and_follow_up_scheduling(client):
    booked = book_today(client, "CONFIRMED")
    client.post(f"/api/appointments/{booked['id']}/checkin-qr")
    html = client.get(f"/appointments/{booked['id']}/checkin-qr").text
    assert '<nav class="breadcrumbs"' in html and "Check-in QR" in html
    assert '<nav class="breadcrumbs"' not in client.get("/follow-ups").text  # only while scheduling


def test_settings_is_split_into_explained_sections_without_reset(client):
    html = client.get("/settings").text
    tabs = html[html.index('class="settings-tabs"'):html.index("</nav>", html.index('class="settings-tabs"'))]
    assert re.findall(r'href="#([a-z-]+)"', tabs) == ["clinic", "doctors", "services", "schedule", "demo-data"]
    for section in ("clinic", "doctors", "services", "schedule", "demo-data"):
        assert f'id="{section}"' in html
    assert html.count('class="affects"') == 4
    assert "awaiting owner approval" in html
    # Closed days are stated, not hidden, and marked on the working-day ticks.
    schedule = html[html.index('id="schedule"'):html.index('id="demo-data"')]
    assert "<strong>Sunday</strong>" in schedule and "Monday to Saturday" in schedule
    assert html.count("clinic closed</span>") == 3  # one per doctor, on Sunday
    assert "reset" not in re.sub(r"no reset control", "", html.lower())
    # Every existing form post is still there.
    for action in ("/settings/clinic", "/settings/doctors/1", "/settings/services/1"):
        assert f'action="{action}"' in html


def test_placeholders_clear_once_the_owner_supplies_real_details(client):
    before = client.get("/settings").text
    clinic_part = before[before.index('id="clinic"'):before.index('id="doctors"')]
    assert clinic_part.count("awaiting owner approval") == 3
    client.post("/settings/clinic", data={"name": "Smriti Raj Dentistry", "address": "Real address", "phone": "+91 1",
                                          "email": "desk@clinic.test", "currency_symbol": "₹"})
    after = client.get("/settings").text
    assert "awaiting owner approval" not in after[after.index('id="clinic"'):after.index('id="doctors"')]


def test_settings_availability_change_reaches_the_calendar(client):
    """The Settings journey: change a doctor's hours and the schedule reflects them."""
    response = client.post("/settings/doctors/1", data={
        "name": "Dr. Anika Rao", "speciality": "General Dentistry", "work_start": "11:00", "work_end": "13:00",
        "consultation_minutes": "30", "working_days": ["0", "1", "2", "3", "4", "5"],
    }, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/settings?notice=saved"
    slots = client.get("/api/doctors/1/slots", params={"date": "2026-10-15"}).json()
    assert [s["start_time"][11:16] for s in slots] == ["11:00", "11:30", "12:00", "12:30"]
    assert "11:00" in client.get("/doctor/calendar?doctor_id=1").text


def test_button_system_and_motion_rules_exist():
    css = (ROOT / "app/static/css/app.css").read_text()
    for rule in (".btn-primary", ".btn-danger", ".btn-ghost", ".btn:focus-visible", ".btn:active",
                 '.btn[aria-disabled="true"]', ".btn.is-loading", ".more-menu", ".breadcrumbs", ".toast",
                 ".quick-actions", ".settings-tabs", ".menu-toggle", ".nav-group-label"):
        assert rule in css
    assert "--t: 200ms" in css
    assert "prefers-reduced-motion: reduce" in css
    durations = [int(ms) for ms in re.findall(r"\b(\d{3,4})ms\b", css)]
    assert not re.search(r"\b\d+(\.\d+)?s (var|ease|linear)", css)  # no second-long transitions
    assert all(ms <= 250 or ms == 700 for ms in durations), durations  # 700ms is only the busy spinner's loop
