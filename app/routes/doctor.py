"""Doctor consultation workspace (demo).

The only place where consultation outcomes and draft treatment recommendations
can be written. There is no login in this demo: the doctor is chosen with a
switcher, and every action is checked against that doctor's own list.
"""
from datetime import date, time, timedelta

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from .. import config, schemas, utils
from ..database import get_db
from ..models import BLOCK_REASONS, DOCTOR_CALLBACK_REASONS, FOLLOWUP_DURATIONS, FOLLOWUP_TIMEFRAMES, NEXT_STEPS, PATIENT_FLAGS, STATUS_ARRIVED, STATUS_COMPLETED, STATUS_CONFIRMED, STATUS_NO_SHOW
from ..services import appointments, availability, consultations, patient_care, schedule, workspace as board_service
from ..services.errors import ClinicError
from .pages import NOTICES, redirect, render

router = APIRouter()

STATUS_NOTICES = {STATUS_ARRIVED: "arrived", STATUS_COMPLETED: "completed", STATUS_NO_SHOW: "no_show"}


def schedule_view(
    request: Request, db: Session, doctor_id: int | None, week: int = 0, error: ClinicError | None = None,
    form: dict | None = None, appointment_id: int | None = None,
):
    """The Schedule tab: one doctor's week, plus their blocked periods."""
    doctors = availability.list_doctors(db)
    doctor = next((d for d in doctors if d.id == doctor_id), doctors[0])
    # "View in calendar" from the workspace: open the week holding that appointment and highlight it.
    highlight = None
    if appointment_id is not None:
        try:
            highlight = consultations.appointment_for_doctor(db, doctor.id, appointment_id)
        except ClinicError:
            highlight = None
    if highlight is not None:
        week = (highlight.start_time.date() - schedule.week_start(0)).days // 7
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
        "highlight_id": highlight.id if highlight is not None else None,
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
    show: str = "all",
    care: bool = False,
    note_form: str | None = None,
):
    doctors = availability.list_doctors(db)
    doctor = next((d for d in doctors if d.id == doctor_id), doctors[0])
    selected = None
    if appointment_id is not None:
        try:
            selected = consultations.appointment_for_doctor(db, doctor.id, appointment_id)
        except ClinicError:
            selected = None
    board = board_service.day_board(db, doctor.id, show)
    todays = [v.appointment for v in board.visits]
    context = {
        "active": "doctor",
        "view": "today",
        "doctors": doctors,
        "doctor": doctor,
        "appointments": todays,
        "board": board,
        "filters": board_service.FILTERS,
        "stage_labels": board_service.STAGE_LABELS,
        "stage_of": board_service.stage,
        "mask_mobile": board_service.mask_mobile,
        "arrival_of": board_service.arrival,
        "awaiting": consultations.awaiting_confirmation(db, doctor.id),
        "counts": {
            "waiting": sum(a.status == STATUS_CONFIRMED for a in todays),
            "in_clinic": sum(a.status == STATUS_ARRIVED for a in todays),
            "completed": sum(a.status == STATUS_COMPLETED for a in todays),
            "no_show": sum(a.status == STATUS_NO_SHOW for a in todays),
        },
        "selected": selected,
        "neighbours": board_service.neighbours(board, selected) if selected is not None else (None, None),
        "context": board_service.patient_context(db, selected) if selected is not None else None,
        "handoff": board_service.handoff_state(selected) if selected is not None else None,
        "handoff_steps": board_service.HANDOFF_STEPS,
        "recommendation_steps": board_service.RECOMMENDATION_STEPS,
        "overview": patient_care.overview(db, doctor.id, selected) if selected is not None else None,
        "patient_flags": PATIENT_FLAGS,
        "callback_reasons": DOCTOR_CALLBACK_REASONS,
        "followup_durations": FOLLOWUP_DURATIONS,
        "followup_timeframes": FOLLOWUP_TIMEFRAMES,
        "note_form": note_form,
        "tomorrow": utils.now().date() + timedelta(days=1),
        "procedures": config.DEMO_PROCEDURES,
        "next_steps": NEXT_STEPS,
    }
    # Feedback belongs where the doctor is working. With a consultation open, the result of an
    # action is shown inside that panel (and the page stays there) instead of at the top of the page.
    notice_key = request.query_params.get("notice", "")
    message = ("error", error.message) if error is not None else NOTICES.get(notice_key)
    if selected is not None and (care or notice_key.startswith("care_")):
        # Patient overview actions report inside the overview, where the doctor clicked.
        context.update(care_notice=message, notice=None)
    elif selected is not None and outcome_form is not None and error is not None:
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
    show: str = "all",
    db: Session = Depends(get_db),
):
    if view == "schedule":
        # Old address for the calendar: send it to the one shared calendar page.
        return redirect("/doctor/calendar", doctor_id=doctor_id, week=week or None)
    return workspace(request, db, doctor_id, appointment_id, show=show)


@router.get("/doctor/calendar", include_in_schema=False)
def doctor_calendar(
    request: Request, doctor_id: int | None = None, week: int = 0, appointment_id: int | None = None, db: Session = Depends(get_db)
):
    """The doctor's weekly schedule. Opened from the "Doctor calendar" menu item, the "Weekly
    schedule" tab, and "View in calendar" (which highlights one of this doctor's appointments)."""
    return schedule_view(request, db, doctor_id, week, appointment_id=appointment_id)


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


@router.post("/doctor/{doctor_id}/appointments/{appointment_id}/start", include_in_schema=False)
def doctor_start_consultation(request: Request, doctor_id: int, appointment_id: int, db: Session = Depends(get_db)):
    """Arrived → In consultation. Only for this doctor's own arrived patients."""
    try:
        consultations.start_consultation(db, doctor_id, appointment_id)
    except ClinicError as exc:
        return workspace(request, db, doctor_id, appointment_id, exc)
    return redirect("/doctor", "consultation", doctor_id=doctor_id, appointment_id=appointment_id, notice="consultation_started")


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
def doctor_request_followup(
    request: Request, doctor_id: int, appointment_id: int,
    duration: str = Form(""), timeframe: str = Form(""), by_date: str = Form(""), db: Session = Depends(get_db),
):
    """The doctor explicitly sends a consultation follow-up to reception. Saving an outcome never does this."""
    try:
        consultations.request_followup(db, doctor_id, appointment_id, duration=duration, timeframe=timeframe, by_date=by_date)
    except ClinicError as exc:
        return workspace(request, db, doctor_id, appointment_id, exc)
    return redirect("/doctor", "consultation", doctor_id=doctor_id, appointment_id=appointment_id, notice="followup_sent")


# ---- Patient overview: flags, private notes and care requests. Each goes through one of the doctor's own
# appointments; none edits patient details, deletes anything or books a slot. ------------------------------------
def _care_done(doctor_id: int, appointment_id: int, notice: str):
    return redirect("/doctor", "patient-overview", doctor_id=doctor_id, appointment_id=appointment_id, notice=notice)


@router.post("/doctor/{doctor_id}/appointments/{appointment_id}/care/flags", include_in_schema=False)
def doctor_set_flags(request: Request, doctor_id: int, appointment_id: int, flags: list[str] = Form([]), db: Session = Depends(get_db)):
    try:
        changes = patient_care.set_flags(db, doctor_id, appointment_id, flags)
    except ClinicError as exc:
        return workspace(request, db, doctor_id, appointment_id, exc, care=True)
    return _care_done(doctor_id, appointment_id, "care_flags" if changes else "care_flags_unchanged")


@router.post("/doctor/{doctor_id}/appointments/{appointment_id}/care/notes", include_in_schema=False)
def doctor_save_note(request: Request, doctor_id: int, appointment_id: int, body: str = Form(""), db: Session = Depends(get_db)):
    try:
        patient_care.save_note(db, doctor_id, appointment_id, body)
    except ClinicError as exc:
        return workspace(request, db, doctor_id, appointment_id, exc, care=True, note_form=body)
    return _care_done(doctor_id, appointment_id, "care_note")


@router.post("/doctor/{doctor_id}/appointments/{appointment_id}/care/callback", include_in_schema=False)
def doctor_request_callback(request: Request, doctor_id: int, appointment_id: int, reason: str = Form(""), db: Session = Depends(get_db)):
    try:
        patient_care.request_callback(db, doctor_id, appointment_id, reason)
    except ClinicError as exc:
        return workspace(request, db, doctor_id, appointment_id, exc, care=True)
    return _care_done(doctor_id, appointment_id, "care_callback")


@router.post("/doctor/{doctor_id}/appointments/{appointment_id}/care/follow-up", include_in_schema=False)
def doctor_care_followup(
    request: Request, doctor_id: int, appointment_id: int,
    duration: str = Form(""), timeframe: str = Form(""), by_date: str = Form(""), db: Session = Depends(get_db),
):
    try:
        patient_care.request_followup(db, doctor_id, appointment_id, duration=duration, timeframe=timeframe, by_date=by_date)
    except ClinicError as exc:
        return workspace(request, db, doctor_id, appointment_id, exc, care=True)
    return _care_done(doctor_id, appointment_id, "care_followup")


@router.post("/doctor/{doctor_id}/follow-ups/{request_id}/close", include_in_schema=False)
def doctor_close_followup(
    request: Request, doctor_id: int, request_id: int, appointment_id: int = Form(0), reason: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        patient_care.close_followup(db, doctor_id, request_id, reason)
    except ClinicError as exc:
        return workspace(request, db, doctor_id, appointment_id or None, exc, care=True)
    return _care_done(doctor_id, appointment_id, "care_followup_closed")


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
