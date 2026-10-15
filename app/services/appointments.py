"""Booking rules. Routes, templates and (later) the AI assistant all go through here."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .. import utils
from ..models import (
    BOOKING_SOURCES,
    STATUS_ARRIVED,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_CONFIRMED,
    STATUS_NO_SHOW,
    STATUS_PENDING,
    SOURCE_STAFF,
    Appointment,
    TimelineEvent,
    Service,
    Slot,
)
from . import availability, clinic, notifications, patients
from .errors import NotFoundError, SlotTakenError, ValidationError

# Staff may confirm a pending booking, or cancel any active one. Cancelled is final.
ALLOWED_TRANSITIONS = {
    STATUS_PENDING: {STATUS_CONFIRMED, STATUS_CANCELLED},
    STATUS_CONFIRMED: {STATUS_CANCELLED, STATUS_ARRIVED, STATUS_NO_SHOW},
    # Consultation day: arrived patients are seen or marked no-show. These three are final.
    STATUS_ARRIVED: {STATUS_COMPLETED, STATUS_NO_SHOW},
    STATUS_COMPLETED: set(),
    STATUS_NO_SHOW: set(),
    STATUS_CANCELLED: set(),
}


def _with_details():
    return select(Appointment).options(
        joinedload(Appointment.patient),
        joinedload(Appointment.doctor),
        joinedload(Appointment.service),
    )


def list_services(db: Session) -> list[Service]:
    return list(db.scalars(select(Service).order_by(Service.id)))


def get_appointment(db: Session, appointment_id: int) -> Appointment:
    appointment = db.scalar(_with_details().where(Appointment.id == appointment_id))
    if appointment is None:
        raise NotFoundError("We could not find that booking.")
    return appointment


def create_appointment(
    db: Session,
    *,
    patient_id: int,
    slot_id: int,
    service_id: int,
    reason: str | None = None,
    source: str = "STAFF",
    is_demo: bool = False,
    now: datetime | None = None,
) -> Appointment:
    now = now or utils.now()
    patient = patients.get_patient(db, patient_id)
    service = db.get(Service, service_id)
    if service is None:
        raise ValidationError("Please choose a reason for the visit.")
    if source not in BOOKING_SOURCES:
        raise ValidationError("Please choose a valid booking source.")
    slot = db.get(Slot, slot_id)
    if slot is None:
        raise NotFoundError("That time is no longer offered. Please choose another available time.")
    if availability.is_closed(slot.start_time.date()):
        raise ValidationError(f"{clinic.closed_day_message(db, slot.start_time)} Please choose another day.")
    if slot.start_time <= now:
        raise ValidationError("That time has already passed. Please choose another available time.")
    if availability.is_blocked(db, slot.doctor_id, slot.start_time, slot.end_time):
        raise ValidationError("The doctor is not available at that time. Please choose another available time.")
    if not availability.is_free(db, slot.doctor_id, slot.start_time, slot.end_time):
        raise SlotTakenError()

    appointment = Appointment(
        patient_id=patient.id,
        doctor_id=slot.doctor_id,
        service_id=service.id,
        reason=(reason or "").strip() or None,
        start_time=slot.start_time,
        end_time=slot.end_time,
        status=STATUS_PENDING,
        source=source,
        is_demo=is_demo,
        created_at=now,
    )
    db.add(appointment)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race with another booking: the unique index rejected the insert.
        db.rollback()
        raise SlotTakenError() from None
    return get_appointment(db, appointment.id)


def set_status(db: Session, appointment_id: int, new_status: str, actor: str = SOURCE_STAFF) -> Appointment:
    appointment = get_appointment(db, appointment_id)
    if new_status == appointment.status:
        return appointment
    if new_status not in ALLOWED_TRANSITIONS.get(appointment.status, set()):
        current, wanted = (str(s).replace("_", "-").lower() for s in (appointment.status, new_status))
        raise ValidationError(f"A {current} booking cannot be changed to {wanted}.")
    appointment.status = new_status
    # Remember when and by whom, for the patient timeline (no other table keeps this).
    db.add(
        TimelineEvent(
            kind=f"APPOINTMENT_{new_status}",
            source=actor,
            occurred_at=utils.now(),
            patient_id=appointment.patient_id,
            appointment_id=appointment.id,
        )
    )
    # Simulated outbox entry (never sent). One per appointment and event.
    if new_status == STATUS_CONFIRMED:
        notifications.queue_for_appointment(db, "APPOINTMENT_CONFIRMATION", appointment)
    elif new_status == STATUS_CANCELLED:
        notifications.queue_for_appointment(db, "APPOINTMENT_CANCELLATION", appointment)
    # A follow-up or procedure plan booked into this appointment moves with it (completed, or reopened).
    from . import care_queue  # local import: care_queue builds on this module

    care_queue.on_appointment_status(db, appointment, new_status)
    db.commit()
    return appointment


def list_today(db: Session, now: datetime | None = None) -> list[Appointment]:
    """Every booking that starts today, including cancelled ones."""
    start, end = utils.day_bounds((now or utils.now()).date())
    stmt = (
        _with_details()
        .where(Appointment.start_time >= start, Appointment.start_time < end)
        .order_by(Appointment.start_time, Appointment.id)
    )
    return list(db.scalars(stmt))


def list_upcoming(db: Session, now: datetime | None = None, limit: int = 50) -> list[Appointment]:
    """Active bookings from tomorrow onwards."""
    _, tomorrow = utils.day_bounds((now or utils.now()).date())
    stmt = (
        _with_details()
        .where(Appointment.start_time >= tomorrow, Appointment.status != STATUS_CANCELLED)
        .order_by(Appointment.start_time, Appointment.id)
        .limit(limit)
    )
    return list(db.scalars(stmt))


def dashboard_summary(db: Session, now: datetime | None = None) -> dict:
    now = now or utils.now()
    today_start, today_end = utils.day_bounds(now.date())
    window_end = today_start + timedelta(days=len(availability.window_days(now.date())))
    today = list_today(db, now)
    pending = db.scalars(
        select(Appointment.id).where(
            Appointment.status == STATUS_PENDING, Appointment.start_time >= today_start
        )
    ).all()
    return {
        "todays_bookings": sum(1 for a in today if a.is_active),
        "pending_bookings": len(pending),
        "available_slots_today": availability.count_available(db, today_start, today_end, now),
        "available_slots_week": availability.count_available(db, today_start, window_end, now),
    }
