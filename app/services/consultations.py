"""Doctor consultation workspace: arrival, completion, doctor-entered outcome and
draft treatment recommendations.

Demo only. This is not a medical record, a diagnosis tool or a prescription
system. Everything here is entered by the doctor; nothing is generated, edited
or approved by reception or by the assistant. Every write is scoped to the
doctor the appointment belongs to.
"""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import config, utils
from ..models import (
    FOLLOWUP_CLOSED,
    FOLLOWUP_DURATIONS,
    FOLLOWUP_TIMEFRAMES,
    FOLLOWUP_TYPES,
    NEXT_STEPS,
    PRIORITIES,
    RECOMMENDATION_DRAFT,
    RECOMMENDATION_READY,
    SOURCE_DOCTOR,
    STATUS_ARRIVED,
    STATUS_COMPLETED,
    STATUS_CONFIRMED,
    STATUS_NO_SHOW,
    STATUS_PENDING,
    Appointment,
    ConsultationFollowup,
    ConsultationOutcome,
    ConsultationStart,
    TimelineEvent,
    TreatmentRecommendation,
)
from . import appointments, availability
from .errors import NotFoundError, NotPermittedError, ValidationError

# What a doctor may set from the workspace. Confirming and cancelling stay with reception.
DOCTOR_STATUSES = (STATUS_ARRIVED, STATUS_COMPLETED, STATUS_NO_SHOW)
WORKSPACE_STATUSES = (STATUS_CONFIRMED, STATUS_ARRIVED, STATUS_COMPLETED, STATUS_NO_SHOW)


def _clean(value: str | None, limit: int) -> str | None:
    value = "\n".join(line.strip() for line in (value or "").strip().splitlines())
    return value[:limit] or None


def appointment_for_doctor(db: Session, doctor_id: int, appointment_id: int) -> Appointment:
    """The appointment, only if it is on this doctor's list."""
    availability.get_doctor(db, doctor_id)
    appointment = appointments.get_appointment(db, appointment_id)
    if appointment.doctor_id != doctor_id:
        raise NotPermittedError("That appointment is on another doctor's list.")
    return appointment


def todays_list(db: Session, doctor_id: int, now=None) -> list[Appointment]:
    """Today's confirmed, arrived, completed and no-show appointments for one doctor."""
    start, end = utils.day_bounds((now or utils.now()).date())
    stmt = (
        select(Appointment)
        .options(joinedload(Appointment.patient), joinedload(Appointment.service))
        .where(
            Appointment.doctor_id == doctor_id,
            Appointment.start_time >= start,
            Appointment.start_time < end,
            Appointment.status.in_(WORKSPACE_STATUSES),
        )
        .order_by(Appointment.start_time, Appointment.id)
    )
    return list(db.scalars(stmt))


def awaiting_confirmation(db: Session, doctor_id: int, now=None) -> int:
    """Today's bookings reception has not confirmed yet (shown as a count only)."""
    start, end = utils.day_bounds((now or utils.now()).date())
    stmt = select(Appointment.id).where(
        Appointment.doctor_id == doctor_id,
        Appointment.start_time >= start,
        Appointment.start_time < end,
        Appointment.status == STATUS_PENDING,
    )
    return len(db.scalars(stmt).all())


def set_status(db: Session, doctor_id: int, appointment_id: int, new_status: str) -> Appointment:
    appointment_for_doctor(db, doctor_id, appointment_id)
    if new_status not in DOCTOR_STATUSES:
        raise NotPermittedError("Confirming and cancelling bookings is done at reception.")
    return appointments.set_status(db, appointment_id, new_status, actor=SOURCE_DOCTOR)


def start_consultation(db: Session, doctor_id: int, appointment_id: int) -> ConsultationStart:
    """The doctor starts seeing an arrived patient. The appointment stays ARRIVED; this only
    records the workspace stage "In consultation" (and a timeline entry)."""
    appointment = appointment_for_doctor(db, doctor_id, appointment_id)
    if appointment.status != STATUS_ARRIVED:
        raise ValidationError("A consultation can be started once the patient has arrived.")
    if appointment.consultation_start is not None:
        raise ValidationError("This consultation has already been started.")
    started = ConsultationStart(appointment_id=appointment.id, doctor_id=doctor_id, started_at=utils.now())
    db.add(started)
    db.add(
        TimelineEvent(
            kind="CONSULTATION_STARTED", source=SOURCE_DOCTOR, occurred_at=started.started_at,
            patient_id=appointment.patient_id, appointment_id=appointment.id, detail=None,
        )
    )
    db.commit()
    return started


def save_outcome(
    db: Session,
    doctor_id: int,
    appointment_id: int,
    *,
    summary: str,
    next_step: str,
    follow_up_note: str | None = None,
) -> ConsultationOutcome:
    appointment = appointment_for_doctor(db, doctor_id, appointment_id)
    if appointment.status not in (STATUS_ARRIVED, STATUS_COMPLETED):
        raise ValidationError("An outcome can be entered once the patient has arrived.")
    summary = _clean(summary, 1000)
    if not summary:
        raise ValidationError("Please enter a short consultation summary.")
    if next_step not in NEXT_STEPS:
        raise ValidationError("Please choose a next step.")

    outcome = appointment.outcome
    if outcome is None:
        outcome = ConsultationOutcome(appointment_id=appointment.id, doctor_id=doctor_id)
        db.add(outcome)
    outcome.summary = summary
    outcome.next_step = next_step
    outcome.follow_up_note = _clean(follow_up_note, 500)
    outcome.updated_at = utils.now()
    db.commit()
    return outcome


def create_recommendation(
    db: Session, doctor_id: int, appointment_id: int, *, procedure: str, doctor_note: str | None = None
) -> TreatmentRecommendation:
    """A DRAFT recommendation, chosen by the doctor from the approved demo list."""
    appointment = appointment_for_doctor(db, doctor_id, appointment_id)
    if appointment.status != STATUS_COMPLETED:
        raise ValidationError("A recommendation can be drafted once the consultation is completed.")
    if procedure not in config.DEMO_PROCEDURES:
        raise ValidationError("Please choose a procedure from the list.")
    if any(r.procedure == procedure for r in appointment.recommendations):
        raise ValidationError("That recommendation is already drafted for this consultation.")

    recommendation = TreatmentRecommendation(
        appointment_id=appointment.id,
        doctor_id=doctor_id,
        patient_id=appointment.patient_id,
        procedure=procedure,
        doctor_note=_clean(doctor_note, 1000),
        status=RECOMMENDATION_DRAFT,
    )
    db.add(recommendation)
    db.commit()
    return recommendation


def followup_preference(
    duration: str | int | None, timeframe: str | None, by_date: str | None, *, durations=FOLLOWUP_DURATIONS
) -> dict | None:
    """Validate the doctor's preferred length and timing. All optional; None if nothing chosen."""
    duration = str(duration or "").strip()
    timeframe = (timeframe or "").strip()
    by_date = (by_date or "").strip()
    if not (duration or timeframe or by_date):
        return None
    minutes = None
    if duration:
        if not duration.isdigit() or int(duration) not in durations:
            allowed = ", ".join(str(d) for d in durations[:-1]) + f" or {durations[-1]}"
            raise ValidationError(f"Please choose a follow-up length of {allowed} minutes.")
        minutes = int(duration)
    if timeframe and timeframe not in FOLLOWUP_TIMEFRAMES:
        raise ValidationError("Please choose when the follow-up should happen.")
    today = utils.now().date()
    target = None
    if timeframe == "DATE" or (by_date and not timeframe):
        try:
            target = date.fromisoformat(by_date)
        except ValueError:
            raise ValidationError("Please choose the date the follow-up should happen by.") from None
        if not today < target <= today + timedelta(days=365):
            raise ValidationError("The follow-up date must be after today and within a year.")
        timeframe = "DATE"
    elif timeframe:
        target = today + timedelta(days=FOLLOWUP_TIMEFRAMES[timeframe][1])
    return {"duration_minutes": minutes, "timeframe": timeframe or None, "by_date": target}


def clean_priority(priority: str | None) -> str | None:
    priority = (priority or "").strip()
    if priority and priority not in PRIORITIES:
        raise ValidationError("Please choose a priority: routine, soon or priority.")
    return priority or None


def create_followup_request(
    db: Session, appointment: Appointment, doctor_id: int, preference: dict | None, detail: str, *,
    draft: bool = False, followup_type: str | None = None, priority: str | None = None,
) -> ConsultationFollowup:
    """One follow-up request per consultation. A request the doctor had closed is reopened instead.

    A draft stays with the doctor; anything else goes straight onto reception's list."""
    if followup_type and followup_type not in ("CONSULTATION", "REVIEW"):
        raise ValidationError("Please choose a consultation follow-up or a review / check-up.")
    priority = clean_priority(priority)
    request = appointment.followup_request
    if request is not None and request.status != FOLLOWUP_CLOSED:
        raise ValidationError("This follow-up has already been sent to reception.")
    if request is None:
        request = ConsultationFollowup(appointment_id=appointment.id, doctor_id=doctor_id, patient_id=appointment.patient_id)
        db.add(request)
    request.status = RECOMMENDATION_DRAFT if draft else RECOMMENDATION_READY
    request.created_at = utils.now()
    request.close_reason = None
    request.followup_type = followup_type if followup_type == "REVIEW" else None
    request.priority = priority
    planning = preference or {}
    request.duration_minutes = planning.get("duration_minutes")
    request.timeframe = planning.get("timeframe")
    request.by_date = planning.get("by_date")
    label = FOLLOWUP_TYPES[request.type_code]
    db.add(
        TimelineEvent(
            kind="FOLLOWUP_CREATED" if draft else "FOLLOWUP_REQUESTED", source=SOURCE_DOCTOR, occurred_at=utils.now(),
            patient_id=appointment.patient_id, appointment_id=appointment.id,
            detail=f"{label} · draft, not yet sent to reception" if draft else detail.replace("Consultation follow-up", label, 1),
        )
    )
    db.commit()
    db.refresh(request)
    return request


def mark_followup_ready(db: Session, doctor_id: int, request_id: int) -> ConsultationFollowup:
    """The requesting doctor hands a draft follow-up to reception."""
    availability.get_doctor(db, doctor_id)
    request = db.get(ConsultationFollowup, request_id)
    if request is None:
        raise NotFoundError("We could not find that follow-up request.")
    if request.doctor_id != doctor_id:
        raise NotPermittedError("Only the doctor who created this follow-up can send it to reception.")
    if request.status != RECOMMENDATION_DRAFT:
        raise ValidationError("This follow-up has already been sent to reception.")
    request.status = RECOMMENDATION_READY
    request.created_at = utils.now()
    db.add(
        TimelineEvent(
            kind="FOLLOWUP_READY", source=SOURCE_DOCTOR, occurred_at=utils.now(), patient_id=request.patient_id,
            appointment_id=request.appointment_id, detail=f"{request.type_label} · ready for reception to schedule",
        )
    )
    db.commit()
    return request


def request_followup(
    db: Session, doctor_id: int, appointment_id: int, *, duration=None, timeframe=None, by_date=None,
    priority=None, followup_type=None,
) -> ConsultationFollowup:
    """The doctor explicitly sends a consultation follow-up to reception for scheduling.

    Saving an outcome never does this by itself. It needs a completed consultation
    whose saved next step is "Follow-up consultation", and can be sent once. The
    doctor may add a preferred length and timeframe; nothing is booked automatically.
    """
    appointment = appointment_for_doctor(db, doctor_id, appointment_id)
    if appointment.status != STATUS_COMPLETED:
        raise ValidationError("Mark the consultation completed before sending the follow-up to reception.")
    if appointment.outcome is None or appointment.outcome.next_step != "FOLLOW_UP_CONSULTATION":
        raise ValidationError("Save the outcome with the next step “Follow-up consultation” first.")
    preference = followup_preference(duration, timeframe, by_date)
    return create_followup_request(
        db, appointment, doctor_id, preference, "Consultation follow-up · sent to reception for scheduling",
        priority=priority, followup_type=followup_type,
    )


def mark_ready(
    db: Session, doctor_id: int, recommendation_id: int, *, priority=None, timeframe=None, by_date=None
) -> TreatmentRecommendation:
    """The recommending doctor releases a draft so reception can book a follow-up. Nobody else can.
    Optional planning fields (priority, suggested timeframe) travel with it to reception."""
    availability.get_doctor(db, doctor_id)
    recommendation = db.get(TreatmentRecommendation, recommendation_id)
    if recommendation is None:
        raise NotFoundError("We could not find that recommendation.")
    if recommendation.doctor_id != doctor_id:
        raise NotPermittedError("Only the doctor who created this recommendation can mark it ready for scheduling.")
    if recommendation.status != RECOMMENDATION_DRAFT:
        raise ValidationError("This recommendation has already been marked ready for scheduling.")
    recommendation.priority = clean_priority(priority)
    planning = followup_preference(None, timeframe, by_date) or {}
    recommendation.timeframe = planning.get("timeframe")
    recommendation.by_date = planning.get("by_date")
    recommendation.status = RECOMMENDATION_READY
    db.add(
        TimelineEvent(
            kind="RECOMMENDATION_READY", source=SOURCE_DOCTOR, occurred_at=utils.now(),
            patient_id=recommendation.patient_id, appointment_id=recommendation.appointment_id,
            detail=f"{recommendation.procedure} · ready for reception to schedule a follow-up",
        )
    )
    db.commit()
    return recommendation


def recommendations_by_patient(db: Session, patient_ids: list[int]) -> dict[int, list[TreatmentRecommendation]]:
    """Read-only lookup for reception screens."""
    grouped: dict[int, list[TreatmentRecommendation]] = {}
    if not patient_ids:
        return grouped
    stmt = (
        select(TreatmentRecommendation)
        .options(joinedload(TreatmentRecommendation.doctor))
        .where(TreatmentRecommendation.patient_id.in_(patient_ids))
        .order_by(TreatmentRecommendation.id.desc())
    )
    for recommendation in db.scalars(stmt):
        grouped.setdefault(recommendation.patient_id, []).append(recommendation)
    return grouped
