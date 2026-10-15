"""Waitlist and cancellation fill (demo).

Staff capture patients who want an earlier or unavailable time. When a booking
is cancelled, its slot shows up as "newly available" next to the waiting
patients it suits. Everything after that is a staff decision:

- nothing is booked, reserved or sent automatically;
- an offer is only a note that staff have told the patient about a slot, and the
  slot stays open to everyone until it is actually booked;
- a booking is made only once staff confirm the patient accepted, through the
  normal booking service, so double-booking protection is unchanged.

"Newly available" is worked out from cancelled appointments whose slot is free
right now. Nothing extra is stored for it, and a slot disappears from the list
as soon as it is booked, blocked or in the past.
"""
from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import utils
from ..models import (
    BOOKING_SOURCES,
    CONTACT_PREFERENCES,
    SOURCE_STAFF,
    STATUS_CANCELLED,
    TIME_PREFERENCES,
    WAITLIST_BOOKED,
    WAITLIST_CLOSED,
    WAITLIST_OFFERED,
    WAITLIST_WAITING,
    Appointment,
    Service,
    Slot,
    TimelineEvent,
    WaitlistEntry,
)
from . import appointments, availability, notifications, patients
from .errors import NotFoundError, ValidationError

NOON = time(12, 0)
ACTIVE = (WAITLIST_WAITING, WAITLIST_OFFERED)


def _with_details():
    return select(WaitlistEntry).options(
        joinedload(WaitlistEntry.patient),
        joinedload(WaitlistEntry.service),
        joinedload(WaitlistEntry.doctor),
        joinedload(WaitlistEntry.offered_slot).joinedload(Slot.doctor),
    )


def get_entry(db: Session, entry_id: int) -> WaitlistEntry:
    entry = db.scalar(_with_details().where(WaitlistEntry.id == entry_id))
    if entry is None:
        raise NotFoundError("We could not find that waitlist entry.")
    return entry


def slot_text(slot: Slot) -> str:
    return f"{utils.fmt_date(slot.start_time)} at {utils.fmt_time(slot.start_time)} with {slot.doctor.name}"


def _event(db: Session, kind: str, entry: WaitlistEntry, detail: str, appointment_id: int | None = None) -> None:
    db.add(
        TimelineEvent(
            kind=kind, source=SOURCE_STAFF, occurred_at=utils.now(), patient_id=entry.patient_id,
            appointment_id=appointment_id, detail=detail[:255],
        )
    )


def create_entry(
    db: Session,
    *,
    patient_id: int,
    service_id: int,
    doctor_id: int | None = None,
    date_from: date,
    date_to: date,
    time_preference: str = "ANY",
    contact_preference: str = "PHONE",
    note: str | None = None,
    source: str = "STAFF",
    now: datetime | None = None,
) -> WaitlistEntry:
    now = now or utils.now()
    patient = patients.get_patient(db, patient_id)
    if db.get(Service, service_id) is None:
        raise ValidationError("Please choose the service the patient is waiting for.")
    if doctor_id is not None:
        availability.get_doctor(db, doctor_id)
    if date_to < date_from:
        raise ValidationError("The last preferred date must be on or after the first.")
    if date_to < now.date():
        raise ValidationError("The preferred dates are in the past.")
    if time_preference not in TIME_PREFERENCES:
        raise ValidationError("Please choose a preferred time of day.")
    if contact_preference not in CONTACT_PREFERENCES:
        raise ValidationError("Please choose how the patient prefers to be contacted.")
    if source not in BOOKING_SOURCES:
        raise ValidationError("Please choose a valid source.")

    entry = WaitlistEntry(
        patient_id=patient.id,
        service_id=service_id,
        doctor_id=doctor_id,
        date_from=date_from,
        date_to=date_to,
        time_preference=time_preference,
        contact_preference=contact_preference,
        note=" ".join((note or "").split())[:500] or None,
        source=source,
        status=WAITLIST_WAITING,
        created_at=now,
    )
    db.add(entry)
    db.commit()
    return get_entry(db, entry.id)


def list_entries(db: Session, statuses: tuple[str, ...] | None = None) -> list[WaitlistEntry]:
    stmt = _with_details().order_by(WaitlistEntry.created_at, WaitlistEntry.id)
    if statuses:
        stmt = stmt.where(WaitlistEntry.status.in_(statuses))
    return list(db.scalars(stmt))


def matches(entry: WaitlistEntry, slot: Slot) -> bool:
    """Does this free slot suit what the patient asked for? (Doctor, dates and time of day.)"""
    if entry.doctor_id is not None and entry.doctor_id != slot.doctor_id:
        return False
    if not entry.date_from <= slot.start_time.date() <= entry.date_to:
        return False
    if entry.time_preference == "MORNING":
        return slot.start_time.time() < NOON
    if entry.time_preference == "AFTERNOON":
        return slot.start_time.time() >= NOON
    return True


def newly_available(db: Session, now: datetime | None = None) -> list[dict]:
    """Future slots freed by a cancellation and still free, each with the waiting patients they suit."""
    now = now or utils.now()
    cancelled = db.scalars(
        select(Appointment)
        .where(Appointment.status == STATUS_CANCELLED, Appointment.start_time > now)
        .order_by(Appointment.start_time)
    ).all()
    waiting = list_entries(db, ACTIVE)
    opportunities, seen = [], set()
    for appointment in cancelled:
        slot = db.scalar(
            select(Slot).options(joinedload(Slot.doctor))
            .where(Slot.doctor_id == appointment.doctor_id, Slot.start_time == appointment.start_time)
        )
        if slot is None or slot.id in seen:
            continue
        seen.add(slot.id)
        views = availability.slots_for_day(db, slot.doctor_id, slot.start_time.date(), now)
        if not any(v.slot.id == slot.id and v.available for v in views):
            continue  # rebooked, blocked or closed since the cancellation
        candidates = [
            e for e in waiting
            if (e.status == WAITLIST_WAITING and matches(e, slot)) or (e.status == WAITLIST_OFFERED and e.offered_slot_id == slot.id)
        ]
        opportunities.append({"slot": slot, "candidates": candidates})
    return opportunities


def offer(db: Session, entry_id: int, slot_id: int, now: datetime | None = None) -> WaitlistEntry:
    """Record that staff have offered this slot to the patient. The slot is NOT reserved."""
    now = now or utils.now()
    entry = get_entry(db, entry_id)
    if entry.status != WAITLIST_WAITING:
        raise ValidationError(f"Only a waiting patient can be offered a slot. This entry is {entry.status.lower()}.")
    slot = db.scalar(select(Slot).options(joinedload(Slot.doctor)).where(Slot.id == slot_id))
    if slot is None:
        raise NotFoundError("That time is no longer offered.")
    views = availability.slots_for_day(db, slot.doctor_id, slot.start_time.date(), now)
    if not any(v.slot.id == slot.id and v.available for v in views):
        raise ValidationError("That time is no longer available, so it cannot be offered.")
    entry.status = WAITLIST_OFFERED
    entry.offered_slot_id = slot.id
    _event(db, "WAITLIST_OFFERED", entry, f"Offered {slot_text(slot)}. Not reserved until booked.")
    # Simulated outbox entry for the offer (never sent); reception still makes the real contact.
    notifications.queue(
        db, "WAITLIST_OFFER", key=f"waitlist:{entry.id}:slot:{slot.id}", name=entry.patient.name,
        mobile=entry.patient.mobile, email=entry.patient.email, prefer_email=entry.contact_preference == "EMAIL",
        patient_id=entry.patient_id, when=slot.start_time, doctor=slot.doctor.name, service=entry.service.name,
        waitlist_entry_id=entry.id,
    )
    db.commit()
    return get_entry(db, entry.id)


def return_to_waiting(db: Session, entry_id: int) -> WaitlistEntry:
    """The patient declined or could not be reached: keep them on the list."""
    entry = get_entry(db, entry_id)
    if entry.status != WAITLIST_OFFERED:
        raise ValidationError("Only an offered entry can be returned to waiting.")
    entry.status = WAITLIST_WAITING
    entry.offered_slot_id = None
    db.commit()
    return get_entry(db, entry.id)


def close(db: Session, entry_id: int) -> WaitlistEntry:
    entry = get_entry(db, entry_id)
    if entry.status not in ACTIVE:
        raise ValidationError(f"This waitlist entry is already {entry.status.lower()}.")
    entry.status = WAITLIST_CLOSED
    entry.offered_slot_id = None
    db.commit()
    return get_entry(db, entry.id)


def book(db: Session, entry_id: int, *, accepted: bool) -> Appointment:
    """Book the offered slot, once staff confirm the patient accepted it.

    Goes through the normal booking service: if the slot was taken in the
    meantime the usual "slot has just been booked" refusal applies and the entry
    stays as it was.
    """
    entry = get_entry(db, entry_id)
    if entry.status != WAITLIST_OFFERED or entry.offered_slot is None:
        raise ValidationError("Offer a slot to the patient first. A booking is made only from an offered slot.")
    if not accepted:
        raise ValidationError("Please confirm that the patient has accepted this time before booking it.")
    slot = entry.offered_slot
    appointment = appointments.create_appointment(
        db,
        patient_id=entry.patient_id,
        slot_id=slot.id,
        service_id=entry.service_id,
        reason="Booked from the waitlist after the patient accepted the offered time.",
        source="STAFF",
    )
    entry = get_entry(db, entry_id)
    entry.status = WAITLIST_BOOKED
    entry.appointment_id = appointment.id
    _event(db, "WAITLIST_BOOKED", entry, f"Booked {slot_text(slot)} from the waitlist.", appointment.id)
    db.commit()
    return appointment


def counts(db: Session, now: datetime | None = None) -> dict:
    entries = list_entries(db, ACTIVE)
    return {
        "waiting": sum(e.status == WAITLIST_WAITING for e in entries),
        "offered": sum(e.status == WAITLIST_OFFERED for e in entries),
        "newly_available": len(newly_available(db, now)),
    }
