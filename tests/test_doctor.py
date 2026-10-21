"""Phase 5: doctor consultation workspace."""
import inspect

import pytest

from app import config
from app.seed import reset_demo_data
from app.services import assistant

from .test_booking import book
from .test_closed_days import WEDNESDAY, client_at  # noqa: F401  (fixture)


def set_status(client, appointment_id, status):
    return client.post(f"/api/appointments/{appointment_id}/status", json={"status": status})


def doctor_post(client, doctor_id, appointment_id, action, **data):
    return client.post(f"/doctor/{doctor_id}/appointments/{appointment_id}/{action}", data=data, follow_redirects=False)


def consultation(client, appointment_id):
    return client.get(f"/api/appointments/{appointment_id}/consultation").json()


@pytest.fixture
def appointment(client, new_patient, free_slot, service_id):
    """A freshly booked PENDING appointment (doctor 1)."""
    return book(client, new_patient, free_slot, service_id).json()


@pytest.fixture
def confirmed(client, appointment):
    assert set_status(client, appointment["id"], "CONFIRMED").status_code == 200
    return appointment


@pytest.fixture
def completed(client, confirmed):
    doctor_id = confirmed["doctor"]["id"]
    assert doctor_post(client, doctor_id, confirmed["id"], "status", status="ARRIVED").status_code == 303
    assert doctor_post(client, doctor_id, confirmed["id"], "status", status="COMPLETED").status_code == 303
    return confirmed


def test_valid_consultation_transitions(client, confirmed, new_patient, service_id):
    doctor_id, appointment_id = confirmed["doctor"]["id"], confirmed["id"]
    arrived = doctor_post(client, doctor_id, appointment_id, "status", status="ARRIVED")
    assert arrived.status_code == 303 and "notice=arrived" in arrived.headers["location"]
    assert consultation(client, appointment_id)["status"] == "ARRIVED"
    done = doctor_post(client, doctor_id, appointment_id, "status", status="COMPLETED")
    assert done.status_code == 303 and "notice=completed" in done.headers["location"]
    assert consultation(client, appointment_id)["status"] == "COMPLETED"

    # CONFIRMED -> NO_SHOW and ARRIVED -> NO_SHOW are both allowed.
    slots = [s for s in client.get(f"/api/doctors/1/slots", params={"date": confirmed["start_time"][:10]}).json() if s["available"]]
    for path in (["CONFIRMED", "NO_SHOW"], ["CONFIRMED", "ARRIVED", "NO_SHOW"]):
        other = book(client, new_patient, slots.pop(), service_id).json()
        for status in path:
            assert set_status(client, other["id"], status).status_code == 200, (path, status)
        assert consultation(client, other["id"])["status"] == "NO_SHOW"


@pytest.mark.parametrize(
    "path, refused",
    [
        ([], "ARRIVED"),  # pending bookings must be confirmed by reception first
        ([], "COMPLETED"),
        ([], "NO_SHOW"),
        (["CONFIRMED"], "COMPLETED"),  # cannot complete without arriving
        (["CONFIRMED", "ARRIVED"], "CANCELLED"),  # cancelling stays a pre-arrival action
        (["CONFIRMED", "ARRIVED"], "CONFIRMED"),
        (["CONFIRMED", "ARRIVED", "COMPLETED"], "ARRIVED"),
        (["CONFIRMED", "ARRIVED", "COMPLETED"], "NO_SHOW"),
        (["CONFIRMED", "ARRIVED", "COMPLETED"], "CANCELLED"),
        (["CONFIRMED", "NO_SHOW"], "ARRIVED"),
        (["CANCELLED"], "ARRIVED"),
        (["CONFIRMED"], "DISCHARGED"),
    ],
)
def test_invalid_transitions_are_refused(client, appointment, path, refused):
    for status in path:
        assert set_status(client, appointment["id"], status).status_code == 200
    before = consultation(client, appointment["id"])["status"]
    response = set_status(client, appointment["id"], refused)
    assert response.status_code == 400
    assert "cannot be changed" in response.json()["message"]
    assert consultation(client, appointment["id"])["status"] == before


def test_existing_cancel_flow_is_unchanged(client, appointment, free_slot):
    assert set_status(client, appointment["id"], "CONFIRMED").json()["status"] == "CONFIRMED"
    assert set_status(client, appointment["id"], "CANCELLED").json()["status"] == "CANCELLED"
    slots = client.get(f"/api/doctors/1/slots", params={"date": free_slot["start_time"][:10]}).json()
    assert next(s for s in slots if s["id"] == free_slot["id"])["available"] is True


def test_doctor_cannot_confirm_or_cancel_from_the_workspace(client, appointment):
    doctor_id = appointment["doctor"]["id"]
    for status in ("CONFIRMED", "CANCELLED"):
        response = doctor_post(client, doctor_id, appointment["id"], "status", status=status)
        assert response.status_code == 403
        assert "done at reception" in response.text
    assert consultation(client, appointment["id"])["status"] == "PENDING"


def test_doctor_can_only_act_on_their_own_appointments(client, confirmed):
    own, other = confirmed["doctor"]["id"], 2
    assert own != other
    appointment_id = confirmed["id"]

    refused = doctor_post(client, other, appointment_id, "status", status="ARRIVED")
    assert refused.status_code == 403
    assert "another doctor" in refused.text
    assert consultation(client, appointment_id)["status"] == "CONFIRMED"

    doctor_post(client, own, appointment_id, "status", status="ARRIVED")
    refused = doctor_post(client, other, appointment_id, "outcome", summary="Not mine", next_step="NO_FOLLOW_UP")
    assert refused.status_code == 403
    assert consultation(client, appointment_id)["outcome"] is None

    saved = doctor_post(
        client, own, appointment_id, "outcome",
        summary="Reviewed with patient.", next_step="FOLLOW_UP_CONSULTATION", follow_up_note="Review in two weeks",
    )
    assert saved.status_code == 303 and "notice=outcome_saved" in saved.headers["location"]
    outcome = consultation(client, appointment_id)["outcome"]
    assert outcome["summary"] == "Reviewed with patient."
    assert outcome["next_step"] == "FOLLOW_UP_CONSULTATION"
    assert outcome["next_step_label"] == "Follow-up consultation"
    assert outcome["follow_up_note"] == "Review in two weeks"
    assert outcome["doctor_id"] == own and outcome["entered_by"] == "doctor"

    # The other doctor's workspace does not open this appointment at all.
    page = client.get(f"/doctor?doctor_id={other}&appointment_id={appointment_id}").text
    assert "Reviewed with patient." not in page
    assert "Doctor-entered consultation outcome" not in page
    assert "Reviewed with patient." in client.get(f"/doctor?doctor_id={own}&appointment_id={appointment_id}").text


def test_outcome_needs_an_arrived_patient_and_valid_fields(client, confirmed):
    doctor_id, appointment_id = confirmed["doctor"]["id"], confirmed["id"]
    early = doctor_post(client, doctor_id, appointment_id, "outcome", summary="Too early", next_step="NO_FOLLOW_UP")
    assert early.status_code == 400 and "once the patient has arrived" in early.text

    doctor_post(client, doctor_id, appointment_id, "status", status="ARRIVED")
    assert doctor_post(client, doctor_id, appointment_id, "outcome", summary="  ", next_step="NO_FOLLOW_UP").status_code == 400
    assert doctor_post(client, doctor_id, appointment_id, "outcome", summary="Fine", next_step="PRESCRIBE").status_code == 400
    assert consultation(client, appointment_id)["outcome"] is None

    assert doctor_post(client, doctor_id, appointment_id, "outcome", summary="First", next_step="NO_FOLLOW_UP").status_code == 303
    assert doctor_post(client, doctor_id, appointment_id, "outcome", summary="Edited", next_step="PROCEDURE_DISCUSSION").status_code == 303
    outcome = consultation(client, appointment_id)["outcome"]
    assert (outcome["summary"], outcome["next_step"]) == ("Edited", "PROCEDURE_DISCUSSION")  # one outcome, updated in place


def test_draft_recommendation_only_after_completed(client, confirmed):
    doctor_id, appointment_id = confirmed["doctor"]["id"], confirmed["id"]
    for status in (None, "ARRIVED"):
        if status:
            doctor_post(client, doctor_id, appointment_id, "status", status=status)
        early = doctor_post(client, doctor_id, appointment_id, "recommendations", procedure="Implant consultation")
        assert early.status_code == 400
        assert "once the consultation is completed" in early.text
        assert consultation(client, appointment_id)["recommendations"] == []

    doctor_post(client, doctor_id, appointment_id, "status", status="COMPLETED")
    assert doctor_post(client, doctor_id, appointment_id, "recommendations", procedure="Whitening").status_code == 400
    assert doctor_post(client, 2, appointment_id, "recommendations", procedure="Implant consultation").status_code == 403

    saved = doctor_post(
        client, doctor_id, appointment_id, "recommendations", procedure="Implant consultation", doctor_note="Discuss options at next visit."
    )
    assert saved.status_code == 303 and "notice=recommendation_saved" in saved.headers["location"]
    [draft] = consultation(client, appointment_id)["recommendations"]
    assert draft["procedure"] == "Implant consultation"
    assert draft["status"] == "DRAFT"
    assert draft["doctor"]["id"] == doctor_id
    assert draft["patient_id"] == confirmed["patient"]["id"]
    assert draft["appointment_id"] == appointment_id
    assert draft["doctor_note"] == "Discuss options at next visit."
    assert draft["created_at"]

    again = doctor_post(client, doctor_id, appointment_id, "recommendations", procedure="Implant consultation")
    assert again.status_code == 400 and "already drafted" in again.text
    assert config.DEMO_PROCEDURES == [
        "Implant consultation", "Root canal treatment assessment", "Aligner assessment", "Crown/bridge assessment",
    ]


def test_staff_and_assistant_views_of_recommendations_are_read_only(client, completed):
    doctor_id, appointment_id = completed["doctor"]["id"], completed["id"]
    doctor_post(client, doctor_id, appointment_id, "outcome", summary="Private clinical summary", next_step="PROCEDURE_DISCUSSION")
    doctor_post(client, doctor_id, appointment_id, "recommendations", procedure="Aligner assessment", doctor_note="Doctor-only note")

    # Reception dashboard and patient view show a read-only indicator, never the doctor's notes or a form.
    dashboard = client.get("/").text
    assert "Doctor recommendation: Aligner assessment · DRAFT" in dashboard
    assert "Next step: Procedure discussion" in dashboard
    patients = client.get("/patients", params={"q": completed["patient"]["mobile"]}).text
    assert "Doctor recommendation: Aligner assessment · DRAFT" in patients
    assert "entered by the doctor, read-only" in patients
    for page in (dashboard, patients):
        assert "Private clinical summary" not in page
        assert "Doctor-only note" not in page
        assert "/recommendations" not in page and "/outcome" not in page
        assert "Save draft recommendation" not in page

    # There is no staff or public way to create, edit or approve one.
    api = client.get("/openapi.json").json()["paths"]
    writers = [p for p, methods in api.items() if ("recommend" in p or "consultation" in p) and set(methods) - {"get"}]
    # Phase 12 added one staff write route: booking a follow-up for a recommendation the doctor has released.
    # It cannot create, edit or approve a recommendation (see tests/test_followups.py).
    # A later change added the same for consultation follow-ups the doctor has explicitly sent to reception.
    assert sorted(writers) == ["/api/follow-ups/consultation/{request_id}/schedule", "/api/follow-ups/{recommendation_id}/schedule"]
    for method, path in (
        ("post", f"/api/appointments/{appointment_id}/consultation"),
        ("post", f"/api/appointments/{appointment_id}/recommendations"),
        ("post", "/api/recommendations"),
        ("post", "/api/recommendations/1/approve"),
        ("put", "/api/recommendations/1"),
        ("post", f"/appointments/{appointment_id}/recommendations"),
    ):
        assert getattr(client, method)(path, json={"procedure": "Implant consultation", "status": "APPROVED"}).status_code in (404, 405)
    [draft] = consultation(client, appointment_id)["recommendations"]
    assert draft["status"] == "DRAFT"
    assert consultation(client, appointment_id)["read_only"] is True

    # The assistant has no path to the consultation service at all.
    source = inspect.getsource(assistant)
    assert not hasattr(assistant, "consultations")
    assert "TreatmentRecommendation" not in source and "ConsultationOutcome" not in source


def test_workspace_lists_todays_confirmed_patients_for_the_selected_doctor(client_at):  # noqa: F811
    client = client_at(WEDNESDAY)
    todays = client.get("/api/appointments", params={"scope": "today"}).json()
    confirmed = next(a for a in todays if a["status"] == "CONFIRMED")
    pending = [a for a in todays if a["status"] == "PENDING"]
    doctor_id = confirmed["doctor"]["id"]

    page = client.get(f"/doctor?doctor_id={doctor_id}")
    assert page.status_code == 200
    assert "Treatment decisions are entered and controlled by the doctor." in page.text
    assert "not a medical record" in page.text
    for doctor in client.get("/api/doctors").json():
        assert doctor["name"] in page.text  # switcher
    listing = page.text.split("today’s list")[1]
    assert confirmed["patient"]["name"] in listing
    assert confirmed["patient"]["mobile"] in listing
    assert confirmed["service"]["name"] in listing
    assert confirmed["source"] in listing
    assert "CONFIRMED" in listing and "Mark patient arrived" in listing
    for other in pending:  # unconfirmed bookings are reception's job, not listed for the doctor
        if other["doctor"]["id"] == doctor_id:
            assert f"appointments/{other['id']}/status" not in listing

    another = next(d["id"] for d in client.get("/api/doctors").json() if d["id"] != doctor_id)
    assert f"appointments/{confirmed['id']}/status" not in client.get(f"/doctor?doctor_id={another}").text

    # The receptionist dashboard reflects the new statuses, without a Cancel button once arrived.
    doctor_post(client, doctor_id, confirmed["id"], "status", status="ARRIVED")
    dashboard = client.get("/").text
    assert "ARRIVED" in dashboard
    row = dashboard.split(f'action="/appointments/{confirmed["id"]}/status"')
    assert len(row) == 1  # no confirm/cancel form left for this booking
    doctor_post(client, doctor_id, confirmed["id"], "status", status="COMPLETED")
    assert "COMPLETED" in client.get("/").text
    assert client.get("/api/dashboard/summary").status_code == 200


def test_demo_reset_clears_outcomes_and_recommendations(client, completed):
    doctor_id, appointment_id = completed["doctor"]["id"], completed["id"]
    doctor_post(client, doctor_id, appointment_id, "outcome", summary="Summary", next_step="NO_FOLLOW_UP")
    doctor_post(client, doctor_id, appointment_id, "recommendations", procedure="Crown/bridge assessment")
    with client.app.state.session_factory() as db:
        reset_demo_data(db)
    assert "Doctor recommendation" not in client.get("/").text
    assert client.get("/doctor").status_code == 200


# --- Regression: saving and updating the doctor's outcome ("Update outcome" looked as if it did nothing) -----------
SUMMARY, NOTE = "Private outcome summary text", "Private follow-up note text"


def outcome_form(page_text):
    """The outcome form as rendered, and the values it shows."""
    form = page_text.split('id="outcome-form"')[1].split("</form>")[0]
    selected = [o for o in form.split("<option")[1:] if " selected" in o.split(">")[0]]
    return {
        "html": form,
        "summary": form.split("<textarea")[1].split(">", 1)[1].split("</textarea>")[0],
        "next_step": selected[0].split('value="')[1].split('"')[0] if selected else None,
        "follow_up_note": form.split('name="follow_up_note"')[1].split('value="')[1].split('"')[0],
    }


@pytest.fixture
def arrived(client, confirmed):
    assert doctor_post(client, confirmed["doctor"]["id"], confirmed["id"], "status", status="ARRIVED").status_code == 303
    return confirmed


def test_arrived_appointment_saves_an_outcome_and_stays_in_the_consultation_panel(client, arrived):
    doctor_id, appointment_id = arrived["doctor"]["id"], arrived["id"]
    page = client.get(f"/doctor?doctor_id={doctor_id}&appointment_id={appointment_id}").text
    # The form posts to this doctor and this appointment, with the three expected fields.
    assert f'action="/doctor/{doctor_id}/appointments/{appointment_id}/outcome"' in page
    form = outcome_form(page)
    assert all(f'name="{field}"' in form["html"] for field in ("summary", "next_step", "follow_up_note"))
    assert ">Save outcome</button>" in form["html"] and "Mark completed" in page
    assert "Save draft recommendation" not in page  # recommendation stays unavailable until COMPLETED

    saved = doctor_post(client, doctor_id, appointment_id, "outcome", summary=SUMMARY, next_step="FOLLOW_UP_CONSULTATION", follow_up_note=NOTE)
    assert saved.status_code == 303
    # The doctor is sent back to the consultation panel, not the top of the page.
    assert saved.headers["location"] == f"/doctor?doctor_id={doctor_id}&appointment_id={appointment_id}&notice=outcome_saved#consultation"
    after = client.get(saved.headers["location"]).text
    panel = after.split('id="consultation"')[1]
    assert 'id="consultation-notice"' in panel and "Consultation outcome saved." in panel  # success notice inside the panel
    assert "Consultation outcome saved." not in after.split('id="consultation"')[0]  # ...and not stranded at the top
    assert 'id="outcome-saved"' in panel and ">Update outcome</button>" in panel
    assert consultation(client, appointment_id)["outcome"]["summary"] == SUMMARY
    assert consultation(client, appointment_id)["status"] == "ARRIVED"  # saving an outcome does not change the status

    # The doctor can then complete the consultation, and only then draft a recommendation.
    done = doctor_post(client, doctor_id, appointment_id, "status", status="COMPLETED")
    assert done.status_code == 303 and done.headers["location"].endswith("notice=completed#consultation")
    assert "Save draft recommendation" in client.get(done.headers["location"]).text


def test_saved_outcome_is_still_shown_after_reloading_the_page(client, arrived):
    doctor_id, appointment_id = arrived["doctor"]["id"], arrived["id"]
    doctor_post(client, doctor_id, appointment_id, "outcome", summary=SUMMARY, next_step="PROCEDURE_DISCUSSION", follow_up_note=NOTE)
    for _ in range(2):  # a plain reload, with no notice in the address
        form = outcome_form(client.get(f"/doctor?doctor_id={doctor_id}&appointment_id={appointment_id}").text)
        assert (form["summary"], form["next_step"], form["follow_up_note"]) == (SUMMARY, "PROCEDURE_DISCUSSION", NOTE)

    # Updating replaces the stored values, and the new ones are what is rendered.
    doctor_post(client, doctor_id, appointment_id, "outcome", summary="Second version", next_step="NO_FOLLOW_UP", follow_up_note="")
    form = outcome_form(client.get(f"/doctor?doctor_id={doctor_id}&appointment_id={appointment_id}").text)
    assert (form["summary"], form["next_step"], form["follow_up_note"]) == ("Second version", "NO_FOLLOW_UP", "")
    assert consultation(client, appointment_id)["outcome"]["follow_up_note"] is None


@pytest.mark.parametrize(
    "data, message",
    [
        ({"summary": "   ", "next_step": "NO_FOLLOW_UP", "follow_up_note": "Typed note"}, "Please enter a short consultation summary."),
        ({"summary": "", "next_step": "NO_FOLLOW_UP", "follow_up_note": "Typed note"}, "Please enter a short consultation summary."),
        ({"summary": "Typed summary", "next_step": "", "follow_up_note": "Typed note"}, "Please choose a next step."),
        ({"summary": "Typed summary", "next_step": "PRESCRIBE", "follow_up_note": "Typed note"}, "Please choose a next step."),
    ],
)
def test_invalid_outcome_shows_an_inline_error_and_keeps_what_was_typed(client, arrived, data, message):
    doctor_id, appointment_id = arrived["doctor"]["id"], arrived["id"]
    refused = doctor_post(client, doctor_id, appointment_id, "outcome", **data)
    assert refused.status_code == 400
    panel = refused.text.split('id="consultation"')[1]
    error = panel.split('id="outcome-error"')[1].split("</div>")[0]
    assert message in error and "Nothing was saved" in error and 'role="alert"' in panel.split('id="outcome-error"')[1][:40]
    assert panel.index('id="outcome-error"') < panel.index('id="outcome-form"')  # shown right above the form
    form = outcome_form(refused.text)
    assert form["follow_up_note"] == "Typed note" and form["summary"] == data["summary"]  # nothing the doctor typed is lost
    assert 'aria-invalid="true"' in form["html"]
    assert consultation(client, appointment_id)["outcome"] is None

    # An existing outcome is left untouched by a rejected update.
    doctor_post(client, doctor_id, appointment_id, "outcome", summary=SUMMARY, next_step="NO_FOLLOW_UP")
    assert doctor_post(client, doctor_id, appointment_id, "outcome", **data).status_code == 400
    assert consultation(client, appointment_id)["outcome"]["summary"] == SUMMARY


def test_pending_and_confirmed_appointments_cannot_save_an_outcome(client, appointment):
    doctor_id, appointment_id = appointment["doctor"]["id"], appointment["id"]
    for status in ("PENDING", "CONFIRMED"):
        if status == "CONFIRMED":
            assert set_status(client, appointment_id, "CONFIRMED").status_code == 200
        refused = doctor_post(client, doctor_id, appointment_id, "outcome", summary=SUMMARY, next_step="NO_FOLLOW_UP")
        assert refused.status_code == 400, status
        assert "An outcome can be entered once the patient has arrived." in refused.text
        assert consultation(client, appointment_id)["outcome"] is None
        page = client.get(f"/doctor?doctor_id={doctor_id}&appointment_id={appointment_id}").text
        assert 'id="outcome-form"' not in page and "An outcome can be entered once the patient has arrived." in page
    for final in ("NO_SHOW",):  # and not for a patient who never arrived
        set_status(client, appointment_id, final)
        assert doctor_post(client, doctor_id, appointment_id, "outcome", summary=SUMMARY, next_step="NO_FOLLOW_UP").status_code == 400


def test_completed_outcome_can_still_be_corrected_by_the_same_doctor(client, arrived):
    """Current rule: the outcome stays editable after completion (one record, updated in place)."""
    doctor_id, appointment_id = arrived["doctor"]["id"], arrived["id"]
    doctor_post(client, doctor_id, appointment_id, "outcome", summary=SUMMARY, next_step="NO_FOLLOW_UP")
    doctor_post(client, doctor_id, appointment_id, "status", status="COMPLETED")
    page = client.get(f"/doctor?doctor_id={doctor_id}&appointment_id={appointment_id}").text
    assert ">Update outcome</button>" in page and "You can still correct it." in page
    assert "Mark completed" not in page.split('id="consultation"')[1]  # nothing left to complete

    corrected = doctor_post(client, doctor_id, appointment_id, "outcome", summary="Corrected summary", next_step="PROCEDURE_DISCUSSION")
    assert corrected.status_code == 303
    outcome = consultation(client, appointment_id)["outcome"]
    assert (outcome["summary"], outcome["next_step"]) == ("Corrected summary", "PROCEDURE_DISCUSSION")
    assert consultation(client, appointment_id)["status"] == "COMPLETED"
    # Another doctor still cannot touch it.
    assert doctor_post(client, 2, appointment_id, "outcome", summary="Not mine", next_step="NO_FOLLOW_UP").status_code == 403
    assert consultation(client, appointment_id)["outcome"]["summary"] == "Corrected summary"


def test_doctor_outcome_text_stays_out_of_reception_patient_and_analytics_views(client, arrived):
    doctor_id, appointment_id = arrived["doctor"]["id"], arrived["id"]
    doctor_post(client, doctor_id, appointment_id, "outcome", summary=SUMMARY, next_step="FOLLOW_UP_CONSULTATION", follow_up_note=NOTE)
    patient_id = arrived["patient"]["id"]
    for path in ("/", "/patients", f"/patients/{patient_id}", f"/api/patients/{patient_id}/timeline", "/analytics", "/api/analytics",
                 "/notifications", "/follow-ups", "/waitlist", "/check-in", "/assistant", "/call-demo"):
        text = client.get(path).text
        assert SUMMARY not in text and NOTE not in text, path
    assert "Next step: Follow-up consultation" in client.get("/").text  # reception still sees the next step only
