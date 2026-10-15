"""Doctor consultation workspace (demo).

The only place where consultation outcomes and draft treatment recommendations
can be written. There is no login in this demo: the doctor is chosen with a
switcher, and every action is checked against that doctor's own list.
"""
from datetime import date, time

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from .. import config, schemas
from ..database import get_db
from ..models import BLOCK_REASONS, NEXT_STEPS, STATUS_ARRIVED, STATUS_COMPLETED, STATUS_CONFIRMED, STATUS_NO_SHOW
from ..services import appointments, availability, consultations, schedule
from ..services.errors import ClinicError
from .pages import NOTICES, redirect, render

router = APIRouter()

STATUS_NOTICES = {STATUS_ARRIVED: "arrived", STATUS_COMPLETED: "completed", STATUS_NO_SHOW: "no_show"}


def schedule_view(request: Request, db: Session, doctor_id: int | None, week: int = 0, error: ClinicError | None = None, form: dict | None = None):
    """The Schedule tab: one doctor's week, plus their blocked periods."""
    doctors = availability.list_doctors(db)
    doctor = next((d for d in doctors if d.id == doctor_id), doctors[0])
    week = max(-schedule.MAX_WEEK_OFFSET, min(schedule.MAX_WEEK_OFFSET, week))
    start = schedule.week_start(week)
    days = schedule.week(db, doctor.id, start)
    context = {
        "active": "doctor-calendar",
        "view": "schedule",
        "doctors": doctors,
        "doctor": doctor,
        "week": week,
        "days": days,
        "blocks": schedule.upcoming_blocks(db, doctor.id),
        "block_reasons": BLOCK_REASONS,
        "form": form or {},
        "booking_days": schedule.booking_window_days(),
    }
    if error is not None:
        context["notice"] = ("error", error.message)
    response = render(request, db, "doctor.html", **context)
    if error is not None:
        response.status_code = error.status_code
    return response


def workspace(
    request: Request,
    db: Session,
    doctor_id: int | None,
    appointment_id: int | None,
    error: ClinicError | None = None,
    outcome_form: dict | None = None,
):
    doctors = availability.list_doctors(db)
    doctor = next((d for d in doctors if d.id == doctor_id), doctors[0])
    selected = None
    if appointment_id is not None:
        try:
            selected = consultations.appointment_for_doctor(db, doctor.id, appointment_id)
        except ClinicError:
            selected = None
    todays = consultations.todays_list(db, doctor.id)
    context = {
        "active": "doctor",
        "view": "today",
        "doctors": doctors,
        "doctor": doctor,
        "appointments": todays,
        "awaiting": consultations.awaiting_confirmation(db, doctor.id),
        "counts": {
            "waiting": sum(a.status == STATUS_CONFIRMED for a in todays),
            "in_clinic": sum(a.status == STATUS_ARRIVED for a in todays),
            "completed": sum(a.status == STATUS_COMPLETED for a in todays),
            "no_show": sum(a.status == STATUS_NO_SHOW for a in todays),
        },
        "selected": selected,
        "procedures": config.DEMO_PROCEDURES,
        "next_steps": NEXT_STEPS,
    }
    # Feedback belongs where the doctor is working. With a consultation open, the result of an
    # action is shown inside that panel (and the page stays there) instead of at the top of the page.
    message = ("error", error.message) if error is not None else NOTICES.get(request.query_params.get("notice", ""))
    if selected is not None and outcome_form is not None and error is not None:
        # A rejected outcome: say why beside the form and keep everything the doctor typed.
        context.update(outcome_error=error.message, outcome_form=outcome_form, notice=None)
    elif selected is not None:
        context.update(panel_notice=message, notice=None)
    else:
        context["notice"] = message
    response = render(request, db, "doctor.html", **context)
    if error is not None:
        response.status_code = error.status_code
    return response


@router.get("/doctor", include_in_schema=False)
def doctor_workspace(
    request: Request,
    doctor_id: int | None = None,
    appointment_id: int | None = None,
    view: str = "today",
    week: int = 0,
    db: Session = Depends(get_db),
):
    if view == "schedule":
        # Old address for the calendar: send it to the one shared calendar page.
        return redirect("/doctor/calendar", doctor_id=doctor_id, week=week or None)
    return workspace(request, db, doctor_id, appointment_id)


@router.get("/doctor/calendar", include_in_schema=False)
def doctor_calendar(request: Request, doctor_id: int | None = None, week: int = 0, db: Session = Depends(get_db)):
    """The doctor's weekly schedule. Opened from the "Doctor calendar" menu item and from the
    "Weekly schedule" tab in the doctor workspace."""
    return schedule_view(request, db, doctor_id, week)


@router.post("/doctor/{doctor_id}/blocks", include_in_schema=False)
def doctor_create_block(
    request: Request,
    doctor_id: int,
    day: str = Form("", alias="date"),
    start_time: str = Form(""),
    end_time: str = Form(""),
    reason: str = Form(""),
    week: int = Form(0),
    db: Session = Depends(get_db),
):
    form = {"date": day, "start_time": start_time, "end_time": end_time, "reason": reason}
    try:
        try:
            block_day = date.fromisoformat(day)
            start = time.fromisoformat(start_time) if start_time else None
            end = time.fromisoformat(end_time) if end_time else None
        except ValueError:
            raise ClinicError("Please enter a valid date and times.") from None
        schedule.create_block(db, doctor_id, day=block_day, start=start, end=end, reason=reason)
    except ClinicError as exc:
        return schedule_view(request, db, doctor_id, week, exc, form)
    return redirect("/doctor/calendar", doctor_id=doctor_id, week=week or None, notice="block_saved")


@router.post("/doctor/{doctor_id}/blocks/{block_id}/remove", include_in_schema=False)
def doctor_remove_block(
    request: Request, doctor_id: int, block_id: int, week: int = Form(0), db: Session = Depends(get_db)
):
    try:
        schedule.remove_block(db, doctor_id, block_id)
    except ClinicError as exc:
        return schedule_view(request, db, doctor_id, week, exc)
    return redirect("/doctor/calendar", doctor_id=doctor_id, week=week or None, notice="block_removed")


@router.get("/api/doctors/{doctor_id}/schedule", tags=["schedule"])
def doctor_schedule(doctor_id: int, start: date | None = None, db: Session = Depends(get_db)):
    """Read-only: seven days of a doctor's appointments, free slots and blocked periods."""
    start = start or schedule.week_start(0)
    return {
        "doctor_id": doctor_id,
        "start": start.isoformat(),
        "days": [schemas.schedule_day_out(d) for d in schedule.week(db, doctor_id, start)],
        "blocks": [schemas.block_out(b) for b in schedule.upcoming_blocks(db, doctor_id)],
    }


@router.post("/doctor/{doctor_id}/appointments/{appointment_id}/status", include_in_schema=False)
def doctor_set_status(
    request: Request, doctor_id: int, appointment_id: int, status: str = Form(...), db: Session = Depends(get_db)
):
    try:
        consultations.set_status(db, doctor_id, appointment_id, status)
    except ClinicError as exc:
        return workspace(request, db, doctor_id, appointment_id, exc)
    return redirect(
        "/doctor", "consultation", doctor_id=doctor_id, appointment_id=appointment_id, notice=STATUS_NOTICES.get(status, "saved")
    )


@router.post("/doctor/{doctor_id}/appointments/{appointment_id}/outcome", include_in_schema=False)
def doctor_save_outcome(
    request: Request,
    doctor_id: int,
    appointment_id: int,
    summary: str = Form(""),
    next_step: str = Form(""),
    follow_up_note: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        consultations.save_outcome(
            db, doctor_id, appointment_id, summary=summary, next_step=next_step, follow_up_note=follow_up_note
        )
    except ClinicError as exc:
        typed = {"summary": summary, "next_step": next_step, "follow_up_note": follow_up_note}
        return workspace(request, db, doctor_id, appointment_id, exc, outcome_form=typed)
    return redirect("/doctor", "consultation", doctor_id=doctor_id, appointment_id=appointment_id, notice="outcome_saved")


@router.post("/doctor/{doctor_id}/appointments/{appointment_id}/recommendations", include_in_schema=False)
def doctor_create_recommendation(
    request: Request,
    doctor_id: int,
    appointment_id: int,
    procedure: str = Form(""),
    doctor_note: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        consultations.create_recommendation(db, doctor_id, appointment_id, procedure=procedure, doctor_note=doctor_note)
    except ClinicError as exc:
        return workspace(request, db, doctor_id, appointment_id, exc)
    return redirect("/doctor", "consultation", doctor_id=doctor_id, appointment_id=appointment_id, notice="recommendation_saved")


@router.post("/doctor/{doctor_id}/appointments/{appointment_id}/follow-up-request", include_in_schema=False)
def doctor_request_followup(request: Request, doctor_id: int, appointment_id: int, db: Session = Depends(get_db)):
    """The doctor explicitly sends a consultation follow-up to reception. Saving an outcome never does this."""
    try:
        consultations.request_followup(db, doctor_id, appointment_id)
    except ClinicError as exc:
        return workspace(request, db, doctor_id, appointment_id, exc)
    return redirect("/doctor", "consultation", doctor_id=doctor_id, appointment_id=appointment_id, notice="followup_sent")


@router.post("/doctor/{doctor_id}/recommendations/{recommendation_id}/ready", include_in_schema=False)
def doctor_mark_ready(
    request: Request, doctor_id: int, recommendation_id: int, appointment_id: int = Form(0), db: Session = Depends(get_db)
):
    """The recommending doctor releases a draft for reception to schedule a follow-up."""
    try:
        recommendation = consultations.mark_ready(db, doctor_id, recommendation_id)
    except ClinicError as exc:
        return workspace(request, db, doctor_id, appointment_id or None, exc)
    return redirect(
        "/doctor", "consultation", doctor_id=doctor_id, appointment_id=recommendation.appointment_id, notice="recommendation_ready"
    )


@router.get("/api/appointments/{appointment_id}/consultation", tags=["consultation"])
def consultation_summary(appointment_id: int, db: Session = Depends(get_db)):
    """Read-only: the doctor-entered outcome and draft recommendations for an appointment."""
    appointment = appointments.get_appointment(db, appointment_id)
    return {
        "appointment_id": appointment.id,
        "status": appointment.status,
        "outcome": schemas.outcome_out(appointment.outcome) if appointment.outcome else None,
        "recommendations": [schemas.recommendation_out(r) for r in appointment.recommendations],
        "read_only": True,
    }
