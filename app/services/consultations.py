"""Doctor consultation workspace: arrival, completion, doctor-entered outcome and
draft treatment recommendations.

Demo only. This is not a medical record, a diagnosis tool or a prescription
system. Everything here is entered by the doctor; nothing is generated, edited
or approved by reception or by the assistant. Every write is scoped to the
doctor the appointment belongs to.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import config, utils
from ..models import (
    NEXT_STEPS,
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


def request_followup(db: Session, doctor_id: int, appointment_id: int) -> ConsultationFollowup:
    """The doctor explicitly sends a consultation follow-up to reception for scheduling.

    Saving an outcome never does this by itself. It needs a completed consultation
    whose saved next step is "Follow-up consultation", and can be sent once.
    """
    appointment = appointment_for_doctor(db, doctor_id, appointment_id)
    if appointment.status != STATUS_COMPLETED:
        raise ValidationError("Mark the consultation completed before sending the follow-up to reception.")
    if appointment.outcome is None or appointment.outcome.next_step != "FOLLOW_UP_CONSULTATION":
        raise ValidationError("Save the outcome with the next step “Follow-up consultation” first.")
    if appointment.followup_request is not None:
        raise ValidationError("This follow-up has already been sent to reception.")
    request = ConsultationFollowup(
        appointment_id=appointment.id, doctor_id=doctor_id, patient_id=appointment.patient_id, status=RECOMMENDATION_READY
    )
    db.add(request)
    db.add(
        TimelineEvent(
            kind="FOLLOWUP_REQUESTED", source=SOURCE_DOCTOR, occurred_at=utils.now(), patient_id=appointment.patient_id,
            appointment_id=appointment.id, detail="Consultation follow-up · sent to reception for scheduling",
        )
    )
    db.commit()
    return request


def mark_ready(db: Session, doctor_id: int, recommendation_id: int) -> TreatmentRecommendation:
    """The recommending doctor releases a draft so reception can book a follow-up. Nobody else can."""
    availability.get_doctor(db, doctor_id)
    recommendation = db.get(TreatmentRecommendation, recommendation_id)
    if recommendation is None:
        raise NotFoundError("We could not find that recommendation.")
    if recommendation.doctor_id != doctor_id:
        raise NotPermittedError("Only the doctor who created this recommendation can mark it ready for scheduling.")
    if recommendation.status != RECOMMENDATION_DRAFT:
        raise ValidationError("This recommendation has already been marked ready for scheduling.")
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
