"""Phase 8: QR appointment check-in."""
import re
from datetime import datetime

import pytest

from app.models import CheckinToken, TimelineEvent
from app.seed import reset_demo_data
from app.services import assistant, checkin

from .test_closed_days import WEDNESDAY, client_at  # noqa: F401  (fixture)

THURSDAY = "2026-10-15"
PRIVATE = ("Demo Patient One", "5550100001", "patient.one@example.com", "Dr. Anika Rao", "General Consultation")


@pytest.fixture
def client(client_at):  # noqa: F811
    """Seeded app with the clock fixed at Wednesday 14 Oct 2026, 10:00."""
    return client_at(WEDNESDAY)


@pytest.fixture
def confirmed(client):
    """The seeded booking that is CONFIRMED for today (Demo Patient One, Dr. Anika Rao, 11:00)."""
    appointment = next(a for a in client.get("/api/appointments", params={"scope": "today"}).json() if a["status"] == "CONFIRMED")
    assert appointment["patient"]["name"] == "Demo Patient One" and appointment["start_time"] == "2026-10-14T11:00:00"
    return appointment


def token_for(client, appointment_id):
    response = client.post(f"/api/appointments/{appointment_id}/checkin-token")
    assert response.status_code == 201, response.text
    return response.json()["token"]


def lookup(client, token):
    return client.post("/api/check-in/lookup", json={"token": token}).json()


def arrive(client, token):
    return client.post("/api/check-in/arrive", json={"token": token}).json()


def status_of(client, appointment_id):
    return client.get(f"/api/appointments/{appointment_id}/consultation").json()["status"]


def events(client, patient_id, kind):
    return [e for e in client.get(f"/api/patients/{patient_id}/timeline").json()["events"] if e["kind"] == kind]


def book_tomorrow(client, patient_id=2, status=None):
    slot = next(s for s in client.get("/api/doctors/1/slots", params={"date": THURSDAY}).json() if s["available"])
    booked = client.post("/api/appointments", json={"patient_id": patient_id, "slot_id": slot["id"], "service_id": 1}).json()
    if status:
        client.post(f"/api/appointments/{booked['id']}/status", json={"status": status})
    return booked


def assert_no_patient_data(text):
    for private in PRIVATE:
        assert private not in text


def test_qr_token_is_opaque_and_carries_no_patient_data(client, confirmed):
    generated = client.post(f"/api/appointments/{confirmed['id']}/checkin-token").json()
    token = generated["token"]
    assert generated["qr_payload"] == token  # the QR encodes the token and nothing else
    assert re.fullmatch(r"[A-Za-z0-9_-]{32}", token)
    for leaked in ("Demo", "Patient", "5550100001", "Anika", "2026", "10-14", "1100", str(confirmed["id"]).zfill(4)):
        assert leaked.lower() not in token.lower()

    # One token per appointment, and different appointments get unrelated tokens.
    assert token_for(client, confirmed["id"]) == token
    other = token_for(client, book_tomorrow(client, status="CONFIRMED")["id"])
    assert other != token and len({token, other}) == 2
    with client.app.state.session_factory() as db:
        record = db.query(CheckinToken).filter_by(appointment_id=confirmed["id"]).one()
        assert checkin.qr_payload(record) == token
        assert "Demo Patient" not in checkin.qr_svg(record)

    # Printable card: clearly labelled, shows the code, and the card itself has no personal details.
    page = client.get(f"/appointments/{confirmed['id']}/checkin-qr")
    assert page.status_code == 200
    card = page.text.split('class="qr-card"')[1].split("</section>")[0]
    assert "Demo appointment check-in QR" in card and token in card and "<svg" in card
    assert_no_patient_data(card)
    download = client.get(f"/appointments/{confirmed['id']}/checkin-qr.svg")
    assert download.status_code == 200 and download.headers["content-type"].startswith("image/svg+xml")
    assert "attachment" in download.headers["content-disposition"]
    assert_no_patient_data(download.text)
    assert client.get("/appointments/9999/checkin-qr.svg").status_code == 404


def test_valid_confirmed_appointment_checks_in(client, confirmed):
    token = token_for(client, confirmed["id"])

    # Step 1: looking the code up shows the booking on the staff screen but changes nothing.
    found = client.post("/check-in", data={"token": f"  {token}\n"})
    assert found.status_code == 200
    assert "Booking found" in found.text and "Demo Patient One" in found.text and "5550100001" in found.text
    assert "Mark patient arrived" in found.text
    assert lookup(client, token)["state"] == "READY"
    assert status_of(client, confirmed["id"]) == "CONFIRMED"

    # Step 2: reception confirms the arrival.
    done = client.post("/check-in/arrive", data={"token": token}, follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"] == f"/check-in?arrived={confirmed['id']}"
    assert status_of(client, confirmed["id"]) == "ARRIVED"
    confirmation = client.get(done.headers["location"]).text
    assert "Checked in" in confirmation and "Demo Patient One" in confirmation and "ARRIVED" in confirmation
    with client.app.state.session_factory() as db:
        assert db.query(CheckinToken).filter_by(token=token).one().used_at == WEDNESDAY


def test_repeat_scan_is_idempotent(client, confirmed):
    token = token_for(client, confirmed["id"])
    assert arrive(client, token)["state"] == "CHECKED_IN"
    patient_id = confirmed["patient"]["id"]
    with client.app.state.session_factory() as db:
        events_before = db.query(TimelineEvent).count()
        used_at = db.query(CheckinToken).filter_by(token=token).one().used_at

    for _ in range(3):
        again = arrive(client, token)
        assert again["state"] == "ALREADY_CHECKED_IN" and again["message"] == "Patient already checked in"
    page = client.post("/check-in", data={"token": token}).text
    assert "Patient already checked in" in page and "No change made" in page and "Mark patient arrived" not in page
    form_again = client.post("/check-in/arrive", data={"token": token}, follow_redirects=False)
    assert form_again.status_code == 200 and "Patient already checked in" in form_again.text

    assert status_of(client, confirmed["id"]) == "ARRIVED"
    with client.app.state.session_factory() as db:
        assert db.query(TimelineEvent).count() == events_before  # nothing written the second time
        assert db.query(CheckinToken).filter_by(token=token).one().used_at == used_at
    assert len(events(client, patient_id, "APPOINTMENT_ARRIVED")) == 1
    assert len(events(client, patient_id, "QR_CHECKIN")) == 1


def refused(client, token, message):
    """A refused code gives the message and nothing about the booking, on both the API and the page."""
    result = lookup(client, token)
    assert result == {"state": "REFUSED", "message": message, "appointment": None, "checked_in_at": None}
    assert arrive(client, token) == result
    for path in ("/check-in", "/check-in/arrive"):
        page = client.post(path, data={"token": token}, follow_redirects=False)
        assert page.status_code == 200
        assert message.replace("'", "&#39;") in page.text
        assert "Mark patient arrived" not in page.text
        assert_no_patient_data(page.text)
        assert "Demo Patient Two" not in page.text and "5550100002" not in page.text


def test_invalid_codes_are_refused_without_exposing_data(client, confirmed):
    token_for(client, confirmed["id"])
    for bad in ("nope", "x" * 32, "A" * 200, "'; DROP TABLE checkin_tokens;--", "../../etc/passwd"):
        refused(client, bad, checkin.NOT_RECOGNISED)
    assert lookup(client, "   ")["message"] == "Please scan or enter a check-in code."
    assert client.post("/api/check-in/lookup", json={"token": "x" * 500}).status_code == 422
    assert status_of(client, confirmed["id"]) == "CONFIRMED"


def test_wrong_date_and_expired_codes_are_refused(client, confirmed, monkeypatch):
    today_token = token_for(client, confirmed["id"])
    tomorrow = book_tomorrow(client, status="CONFIRMED")
    tomorrow_token = token_for(client, tomorrow["id"])

    refused(client, tomorrow_token, checkin.WRONG_DAY)  # right code, wrong day
    assert status_of(client, tomorrow["id"]) == "CONFIRMED"

    # The check-in window closes an hour after the 11:00 start.
    monkeypatch.setattr("app.utils.now", lambda: datetime(2026, 10, 14, 11, 59))
    assert lookup(client, today_token)["state"] == "READY"
    monkeypatch.setattr("app.utils.now", lambda: datetime(2026, 10, 14, 12, 0))
    refused(client, today_token, checkin.EXPIRED)

    # Next day: yesterday's code has expired; today's is now usable.
    monkeypatch.setattr("app.utils.now", lambda: datetime(2026, 10, 15, 8, 0))
    refused(client, today_token, checkin.EXPIRED)
    assert lookup(client, tomorrow_token)["state"] == "READY"
    assert status_of(client, confirmed["id"]) == "CONFIRMED"

    # A clinic can also require patients to be close to their time.
    monkeypatch.setattr("app.config.CHECKIN_OPENS_MINUTES_BEFORE", 30)
    slot_start = datetime.fromisoformat(tomorrow["start_time"])
    monkeypatch.setattr("app.utils.now", lambda: slot_start.replace(hour=slot_start.hour - 1))
    refused(client, tomorrow_token, checkin.NOT_OPEN_YET)


def test_non_confirmed_statuses_cannot_be_checked_in(client, confirmed):
    # PENDING: no QR can even be generated.
    pending = next(a for a in client.get("/api/appointments").json() if a["status"] == "PENDING")
    assert client.post(f"/api/appointments/{pending['id']}/checkin-token").status_code == 400
    page = client.post(f"/appointments/{pending['id']}/checkin-qr", follow_redirects=False)
    assert page.status_code == 400 and "only be generated for a confirmed booking" in page.text
    assert status_of(client, pending["id"]) == "PENDING"

    # CANCELLED after the QR was issued.
    token = token_for(client, confirmed["id"])
    client.post(f"/api/appointments/{confirmed['id']}/status", json={"status": "CANCELLED"})
    refused(client, token, checkin.NO_LONGER_VALID)
    assert status_of(client, confirmed["id"]) == "CANCELLED"


@pytest.mark.parametrize("path, final", [(["ARRIVED", "COMPLETED"], "COMPLETED"), (["NO_SHOW"], "NO_SHOW"), (["ARRIVED"], "ARRIVED")])
def test_finished_or_arrived_bookings_cannot_be_checked_in_again(client, confirmed, path, final):
    token = token_for(client, confirmed["id"])
    for status in path:  # e.g. the doctor marked the patient from the workspace
        assert client.post(f"/api/appointments/{confirmed['id']}/status", json={"status": status}).status_code == 200
    result = arrive(client, token)
    if final == "ARRIVED":
        assert result["state"] == "ALREADY_CHECKED_IN" and result["message"] == "Patient already checked in"
    else:
        assert result == {"state": "REFUSED", "message": checkin.NO_LONGER_VALID, "appointment": None, "checked_in_at": None}
    assert status_of(client, confirmed["id"]) == final
    assert events(client, confirmed["patient"]["id"], "QR_CHECKIN") == []


def test_check_in_updates_dashboard_doctor_workspace_and_timeline(client, confirmed):
    appointment_id, patient_id, doctor_id = confirmed["id"], confirmed["patient"]["id"], confirmed["doctor"]["id"]

    def dashboard_row():
        return client.get("/").text.split(f'id="appointment-{appointment_id}"')[1].split("</tr>")[0]

    def doctor_list():
        return client.get(f"/doctor?doctor_id={doctor_id}").text.split("today’s list")[1].split("</table>")[0]

    assert "CONFIRMED" in dashboard_row() and "Generate check-in QR" in dashboard_row()
    assert "Mark patient arrived" in doctor_list()

    token = token_for(client, appointment_id)
    assert "View check-in QR" in dashboard_row() and "Generate check-in QR" not in dashboard_row()
    assert arrive(client, token)["state"] == "CHECKED_IN"

    row = dashboard_row()
    assert "ARRIVED" in row and "CONFIRMED" not in row and "check-in QR" not in row  # no QR action once arrived
    listing = doctor_list()
    assert "ARRIVED" in listing and "Mark completed" in listing and "Mark patient arrived" not in listing  # doctor sees it at once
    week = client.get(f"/api/doctors/{doctor_id}/schedule").json()["days"][0]["entries"]
    assert next(e for e in week if e.get("appointment_id") == appointment_id)["status"] == "ARRIVED"

    timeline = [e for e in client.get(f"/api/patients/{patient_id}/timeline").json()["events"] if not e["kind"].startswith("NOTIFICATION_")]
    kinds = [e["kind"] for e in timeline]
    assert kinds[:2] == ["APPOINTMENT_ARRIVED", "QR_CHECKIN"]
    qr = timeline[1]
    assert qr["title"] == "QR check-in at reception" and qr["source_label"] == "Staff" and qr["icon"] == "qr"
    assert qr["appointment_id"] == appointment_id and qr["at"] == WEDNESDAY.isoformat()
    assert timeline[0]["source_label"] == "Staff" and timeline[0]["status"] == "ARRIVED"
    page = client.get(f"/patients/{patient_id}/timeline").text
    assert "QR check-in at reception" in page and token not in page  # the code itself is never shown on the timeline

    # Analytics-ready: one structured event row with kind, source, time, patient and appointment.
    with client.app.state.session_factory() as db:
        [event] = db.query(TimelineEvent).filter_by(kind="QR_CHECKIN").all()
        assert (event.source, event.patient_id, event.appointment_id, event.occurred_at) == ("STAFF", patient_id, appointment_id, WEDNESDAY)
    assert any(e["kind"] == "QR_CHECKIN" or e["kind"] == "APPOINTMENT_ARRIVED" for e in [{"kind": k} for k in kinds])
    assert "Patient arrived" in client.get("/").text.split('id="recent-activity"')[1].split("</section>")[0]


def test_qr_actions_and_navigation_are_where_staff_expect_them(client, confirmed):
    for path in ("/", "/patients", "/doctor", "/check-in"):
        menu = client.get(path).text.split('<nav class="nav"')[1].split("</nav>")[0]
        assert 'href="/check-in"' in menu and "<span>QR check-in</span>" in menu
    page = client.get("/check-in").text
    assert "Enter check-in code" in page and 'name="token"' in page and "Scan with camera" in page
    assert "Typing or pasting the code always works" in page and "patients cannot check themselves in" in page

    # Dashboard: only confirmed bookings from today on get the action.
    dashboard = client.get("/").text
    assert dashboard.count("Generate check-in QR") == 1
    assert f'action="/appointments/{confirmed["id"]}/checkin-qr"' in dashboard
    # Patient detail page offers it too, and shows the QR once generated.
    patient = client.get(f"/patients/{confirmed['patient']['id']}").text
    assert f'action="/appointments/{confirmed["id"]}/checkin-qr"' in patient and "Generate check-in QR" in patient
    generated = client.post(f"/appointments/{confirmed['id']}/checkin-qr", follow_redirects=False)
    assert generated.status_code == 303 and generated.headers["location"] == f"/appointments/{confirmed['id']}/checkin-qr"
    assert "View check-in QR" in client.get(f"/patients/{confirmed['patient']['id']}").text

    # Not a patient feature: the public pages and the assistant have nothing to do with it.
    for public in ("/assistant", "/call-demo"):
        assert "check-in" not in client.get(public).text.lower().replace("check-in qr", "check-in")
    assert not hasattr(assistant, "checkin")


def test_demo_reset_clears_check_in_tokens(client, confirmed):
    token = token_for(client, confirmed["id"])
    with client.app.state.session_factory() as db:
        reset_demo_data(db)
        assert db.query(CheckinToken).count() == 0
    assert lookup(client, token)["state"] == "REFUSED"
