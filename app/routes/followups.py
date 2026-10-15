"""Procedure follow-ups: reception's list of doctor-released recommendations to schedule.

Reception sees the patient, doctor, procedure label, state and created date,
and books a follow-up. The doctor's free-text note is never loaded here.
"""
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..models import CONSULTATION_FOLLOWUP_LABEL, FOLLOWUP_LABEL, FOLLOWUP_STATES, RECOMMENDATION_STATES
from ..services import availability, followups
from ..services.errors import ClinicError
from .pages import redirect, render

router = APIRouter()


class ScheduleBody(BaseModel):
    slot_id: int
    note: str | None = None


def recommendation_out(r) -> dict:
    """Staff-safe view: no doctor note."""
    followup = r.followup
    return {
        "id": r.id,
        "patient": {"id": r.patient.id, "name": r.patient.name},
        "doctor": {"id": r.doctor.id, "name": r.doctor.name},
        "procedure": r.procedure,
        "state": r.status,
        "state_label": FOLLOWUP_STATES.get(r.status, r.status),
        "created_at": r.created_at.isoformat(),
        "followup_appointment_id": followup.appointment_id if followup else None,
        "followup_start_time": followup.appointment.start_time.isoformat() if followup else None,
    }


def request_out(r) -> dict:
    """Staff-safe view of a consultation follow-up request: no summary, no doctor note."""
    return {
        "id": r.id,
        "patient": {"id": r.patient.id, "name": r.patient.name},
        "doctor": {"id": r.doctor.id, "name": r.doctor.name},
        "label": CONSULTATION_FOLLOWUP_LABEL,
        "state": r.status,
        "state_label": FOLLOWUP_STATES.get(r.status, r.status),
        "approved_by": "doctor",
        "created_at": r.created_at.isoformat(),
        "followup_appointment_id": r.followup_appointment_id,
        "followup_start_time": r.followup_appointment.start_time.isoformat() if r.followup_appointment else None,
    }


def page(
    request: Request, db: Session, schedule: int | None = None, day: str | None = None, error: ClinicError | None = None,
    kind: str = "procedure",
):
    kind = "consultation" if kind == "consultation" else "procedure"
    selected, slots, days, chosen_day = None, [], availability.window_days(), None
    if schedule is not None:
        try:
            selected = followups.work_item(db, kind, schedule)
        except ClinicError:
            selected = None
    if selected is not None:
        open_days = [d for d in days if not availability.is_closed(d)]
        try:
            chosen_day = date.fromisoformat(day or "")
        except ValueError:
            chosen_day = None
        if chosen_day not in open_days:
            # Default to the first day on which the doctor still has a free slot.
            chosen_day = next(
                (d for d in open_days if any(v.available for v in availability.slots_for_day(db, selected.doctor.id, d))),
                open_days[0] if open_days else None,
            )
        if chosen_day:
            slots = [v for v in availability.slots_for_day(db, selected.doctor.id, chosen_day) if v.available]
    context = {
        "active": "followups",
        "awaiting": followups.worklist(db),
        "scheduled": followups.worklist_scheduled(db),
        "selected": selected,
        "slots": slots,
        "days": days,
        "chosen_day": chosen_day,
        "states": FOLLOWUP_STATES,
        "followup_label": FOLLOWUP_LABEL,
        "consultation_label": CONSULTATION_FOLLOWUP_LABEL,
    }
    if error is not None:
        context["notice"] = ("error", error.message)
    response = render(request, db, "followups.html", **context)
    if error is not None:
        response.status_code = error.status_code
    return response


@router.get("/follow-ups", include_in_schema=False)
def followups_page(
    request: Request, schedule: int | None = None, date: str | None = None, kind: str = "procedure", db: Session = Depends(get_db)
):
    return page(request, db, schedule, date, kind=kind)


@router.post("/follow-ups/consultation/{request_id}/schedule", include_in_schema=False)
def consultation_followup_schedule(
    request: Request, request_id: int, slot_id: int = Form(0), note: str = Form(""), day: str = Form("", alias="date"),
    db: Session = Depends(get_db),
):
    try:
        appointment = followups.schedule_consultation(db, request_id, slot_id, note)
    except ClinicError as exc:
        return page(request, db, request_id, day, exc, kind="consultation")
    return redirect("/", booked=appointment.id)


@router.post("/follow-ups/{recommendation_id}/schedule", include_in_schema=False)
def followups_schedule(
    request: Request, recommendation_id: int, slot_id: int = Form(0), note: str = Form(""), day: str = Form("", alias="date"),
    db: Session = Depends(get_db),
):
    try:
        appointment = followups.schedule(db, recommendation_id, slot_id, note)
    except ClinicError as exc:
        return page(request, db, recommendation_id, day, exc)
    return redirect("/", booked=appointment.id)


@router.get("/api/follow-ups/consultation", tags=["follow-ups"])
def api_consultation_list(db: Session = Depends(get_db)):
    """Consultation follow-ups a doctor has sent to reception. Never includes the doctor's summary or note."""
    return {
        "awaiting": [request_out(r) for r in followups.consultation_awaiting(db)],
        "scheduled": [request_out(r) for r in followups.consultation_scheduled(db)],
    }


@router.post("/api/follow-ups/consultation/{request_id}/schedule", status_code=201, tags=["follow-ups"])
def api_consultation_schedule(request_id: int, body: ScheduleBody, db: Session = Depends(get_db)):
    return schemas.appointment_out(followups.schedule_consultation(db, request_id, body.slot_id, body.note))


@router.get("/api/follow-ups", tags=["follow-ups"])
def api_list(db: Session = Depends(get_db)):
    """Recommendations awaiting scheduling and recently scheduled ones. Never includes a doctor's note."""
    return {
        "awaiting": [recommendation_out(r) for r in followups.awaiting(db)],
        "scheduled": [recommendation_out(r) for r in followups.recently_scheduled(db)],
    }


@router.post("/api/follow-ups/{recommendation_id}/schedule", status_code=201, tags=["follow-ups"])
def api_schedule(recommendation_id: int, body: ScheduleBody, db: Session = Depends(get_db)):
    return schemas.appointment_out(followups.schedule(db, recommendation_id, body.slot_id, body.note))
