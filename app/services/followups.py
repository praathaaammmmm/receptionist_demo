"""Procedure follow-up scheduler (demo).

When a doctor marks a recommendation READY_FOR_SCHEDULING, reception can book a
"Procedure discussion / follow-up" appointment for it with the same doctor.

Boundaries:
- the appointment is created by the normal booking service, so slot conflicts,
  closed days, blocked time, the calendar, notifications, the timeline and
  analytics all behave exactly as for any other booking;
- it is a discussion appointment in a consultation slot, not delivery of the
  procedure; no room, chair, equipment, lab, payment or insurance step exists;
- reception sees the patient, doctor, procedure label, state and date only.
  This module never reads the doctor's free-text note.
"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .. import config, utils
from ..models import (
    CONSULTATION_FOLLOWUP_LABEL,
    FOLLOWUP_LABEL,
    RECOMMENDATION_DRAFT,
    RECOMMENDATION_READY,
    RECOMMENDATION_SCHEDULED,
    SOURCE_STAFF,
    STATUS_CANCELLED,
    Appointment,
    ConsultationFollowup,
    Doctor,
    Patient,
    ProcedureFollowup,
    Service,
    Slot,
    TimelineEvent,
    TreatmentRecommendation,
)
from . import appointments
from .errors import NotFoundError, ValidationError


def _with_details():
    return select(TreatmentRecommendation).options(
        joinedload(TreatmentRecommendation.patient),
        joinedload(TreatmentRecommendation.doctor),
        joinedload(TreatmentRecommendation.followup).joinedload(ProcedureFollowup.appointment),
    )


def get_recommendation(db: Session, recommendation_id: int) -> TreatmentRecommendation:
    recommendation = db.scalar(_with_details().where(TreatmentRecommendation.id == recommendation_id))
    if recommendation is None:
        raise NotFoundError("We could not find that recommendation.")
    return recommendation


def awaiting(db: Session) -> list[TreatmentRecommendation]:
    """Recommendations the doctor has released and reception has not yet booked, oldest first."""
    stmt = _with_details().where(TreatmentRecommendation.status == RECOMMENDATION_READY).order_by(TreatmentRecommendation.id)
    return list(db.scalars(stmt))


def recently_scheduled(db: Session, limit: int = 8) -> list[TreatmentRecommendation]:
    stmt = (
        _with_details()
        .where(TreatmentRecommendation.status == RECOMMENDATION_SCHEDULED)
        .order_by(TreatmentRecommendation.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def awaiting_count(db: Session) -> int:
    return len(db.scalars(select(TreatmentRecommendation.id).where(TreatmentRecommendation.status == RECOMMENDATION_READY)).all())


def service_for(db: Session, procedure: str) -> Service:
    name = config.PROCEDURE_SERVICES.get(procedure, config.FOLLOWUP_DEFAULT_SERVICE)
    service = db.scalar(select(Service).where(Service.name == name)) or db.scalars(select(Service).order_by(Service.id)).first()
    if service is None:
        raise ValidationError("No service is set up to book this follow-up under.")
    return service


def schedule(db: Session, recommendation_id: int, slot_id: int, staff_note: str | None = None) -> Appointment:
    """Book the follow-up for a released recommendation, in a free slot of the recommending doctor."""
    recommendation = get_recommendation(db, recommendation_id)
    if recommendation.status == RECOMMENDATION_DRAFT:
        raise ValidationError("The doctor has not marked this recommendation ready for scheduling yet.")
    if recommendation.status == RECOMMENDATION_SCHEDULED or recommendation.followup is not None:
        raise ValidationError("A follow-up is already booked for this recommendation.")
    if recommendation.status != RECOMMENDATION_READY:
        raise ValidationError("This recommendation cannot be scheduled.")
    slot = db.get(Slot, slot_id)
    if slot is None:
        raise NotFoundError("That time is no longer offered. Please choose another available time.")
    if slot.doctor_id != recommendation.doctor_id:
        raise ValidationError(f"The follow-up must be booked with {recommendation.doctor.name}, who made the recommendation.")

    note = " ".join((staff_note or "").split())[:300]
    reason = f"{FOLLOWUP_LABEL}: {recommendation.procedure}. A discussion appointment, not treatment delivery."
    if note:
        reason += f" Scheduling note: {note}"
    # The normal booking service: slot-taken, closed-day, blocked-time and past-time refusals all apply.
    appointment = appointments.create_appointment(
        db,
        patient_id=recommendation.patient_id,
        slot_id=slot.id,
        service_id=service_for(db, recommendation.procedure).id,
        reason=reason,
        source="STAFF",
    )
    recommendation = get_recommendation(db, recommendation_id)
    db.add(ProcedureFollowup(recommendation_id=recommendation.id, appointment_id=appointment.id, staff_note=note or None))
    recommendation.status = RECOMMENDATION_SCHEDULED
    db.add(
        TimelineEvent(
            kind="FOLLOWUP_SCHEDULED", source=SOURCE_STAFF, occurred_at=utils.now(), patient_id=recommendation.patient_id,
            appointment_id=appointment.id,
            detail=f"{FOLLOWUP_LABEL} for {recommendation.procedure}: {utils.fmt_date(appointment.start_time)} at "
                   f"{utils.fmt_time(appointment.start_time)} with {appointment.doctor.name}",
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # Two people scheduled the same recommendation at once: keep the first, release this slot again.
        db.rollback()
        duplicate = db.get(Appointment, appointment.id)
        duplicate.status = STATUS_CANCELLED
        db.commit()
        raise ValidationError("A follow-up is already booked for this recommendation.") from None
    return appointments.get_appointment(db, appointment.id)


# ---- Consultation follow-ups: a doctor's explicit request, with no procedure recommendation ---------
def _requests():
    return select(ConsultationFollowup).options(
        joinedload(ConsultationFollowup.patient),
        joinedload(ConsultationFollowup.doctor),
        joinedload(ConsultationFollowup.followup_appointment),
    )


def get_request(db: Session, request_id: int) -> ConsultationFollowup:
    request = db.scalar(_requests().where(ConsultationFollowup.id == request_id))
    if request is None:
        raise NotFoundError("We could not find that follow-up request.")
    return request


def consultation_awaiting(db: Session) -> list[ConsultationFollowup]:
    stmt = _requests().where(ConsultationFollowup.status == RECOMMENDATION_READY).order_by(ConsultationFollowup.id)
    return list(db.scalars(stmt))


def consultation_scheduled(db: Session, limit: int = 8) -> list[ConsultationFollowup]:
    stmt = (
        _requests()
        .where(ConsultationFollowup.status == RECOMMENDATION_SCHEDULED)
        .order_by(ConsultationFollowup.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def schedule_consultation(db: Session, request_id: int, slot_id: int, staff_note: str | None = None) -> Appointment:
    """Book the follow-up consultation a doctor asked for, in a free slot of that doctor."""
    request = get_request(db, request_id)
    if request.status == RECOMMENDATION_SCHEDULED or request.followup_appointment_id is not None:
        raise ValidationError("A follow-up is already booked for this request.")
    if request.status != RECOMMENDATION_READY:
        raise ValidationError("This follow-up request cannot be scheduled.")
    slot = db.get(Slot, slot_id)
    if slot is None:
        raise NotFoundError("That time is no longer offered. Please choose another available time.")
    if slot.doctor_id != request.doctor_id:
        raise ValidationError(f"The follow-up must be booked with {request.doctor.name}, who asked for it.")

    note = " ".join((staff_note or "").split())[:300]
    reason = f"{CONSULTATION_FOLLOWUP_LABEL}, requested by the doctor."
    if note:
        reason += f" Scheduling note: {note}"
    original = appointments.get_appointment(db, request.appointment_id)
    # The normal booking service again: every conflict, closed-day and blocked-time rule applies.
    appointment = appointments.create_appointment(
        db, patient_id=request.patient_id, slot_id=slot.id, service_id=original.service_id, reason=reason, source="STAFF"
    )
    request = get_request(db, request_id)
    request.status = RECOMMENDATION_SCHEDULED
    request.followup_appointment_id = appointment.id
    request.staff_note = note or None
    db.add(
        TimelineEvent(
            kind="CONSULTATION_FOLLOWUP_SCHEDULED", source=SOURCE_STAFF, occurred_at=utils.now(), patient_id=request.patient_id,
            appointment_id=appointment.id,
            detail=f"{CONSULTATION_FOLLOWUP_LABEL}: {utils.fmt_date(appointment.start_time)} at "
                   f"{utils.fmt_time(appointment.start_time)} with {appointment.doctor.name}",
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = db.get(Appointment, appointment.id)
        duplicate.status = STATUS_CANCELLED
        db.commit()
        raise ValidationError("A follow-up is already booked for this request.") from None
    return appointments.get_appointment(db, appointment.id)


# ---- One worklist for reception, covering both kinds ------------------------------------------------
@dataclass
class WorkItem:
    """What reception sees for a follow-up of either kind. No clinical text."""

    kind: str  # "procedure" | "consultation"
    id: int
    label: str
    patient: Patient
    doctor: Doctor
    status: str
    created_at: datetime
    followup_appointment: Appointment | None

    @property
    def key(self) -> str:
        return f"{self.kind}-{self.id}"


def _item(record) -> WorkItem:
    if isinstance(record, ConsultationFollowup):
        return WorkItem("consultation", record.id, CONSULTATION_FOLLOWUP_LABEL, record.patient, record.doctor, record.status,
                        record.created_at, record.followup_appointment)
    return WorkItem("procedure", record.id, record.procedure, record.patient, record.doctor, record.status, record.created_at,
                    record.followup.appointment if record.followup else None)


def worklist(db: Session) -> list[WorkItem]:
    """Everything a doctor has released and reception has not booked yet, oldest first."""
    return sorted((_item(r) for r in awaiting(db) + consultation_awaiting(db)), key=lambda i: (i.created_at, i.kind, i.id))


def worklist_scheduled(db: Session, limit: int = 8) -> list[WorkItem]:
    items = [_item(r) for r in recently_scheduled(db, limit) + consultation_scheduled(db, limit)]
    return sorted(items, key=lambda i: (i.followup_appointment.created_at, i.id), reverse=True)[:limit]


def work_item(db: Session, kind: str, item_id: int) -> WorkItem:
    return _item(get_request(db, item_id) if kind == "consultation" else get_recommendation(db, item_id))


def consultation_awaiting_count(db: Session) -> int:
    return len(db.scalars(select(ConsultationFollowup.id).where(ConsultationFollowup.status == RECOMMENDATION_READY)).all())
