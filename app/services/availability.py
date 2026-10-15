"""Doctor slots and availability.

Slots are stored rows; a slot is free when no active (non-cancelled)
appointment for the same doctor overlaps it. Cancelling an appointment
therefore frees its slot with no extra bookkeeping.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import config, utils
from ..models import STATUS_CANCELLED, Appointment, Doctor, DoctorBlock, Slot
from .errors import NotFoundError


@dataclass
class SlotView:
    slot: Slot
    status: str  # AVAILABLE | BOOKED | BLOCKED | PAST

    @property
    def available(self) -> bool:
        return self.status == "AVAILABLE"


def is_closed(day: date) -> bool:
    """Clinic-wide closed day, independent of any doctor's own working days."""
    return day.weekday() in config.CLINIC_CLOSED_WEEKDAYS


def next_open_day(day: date) -> date:
    """The first day after `day` on which the clinic is open."""
    for offset in range(1, 8):
        candidate = day + timedelta(days=offset)
        if not is_closed(candidate):
            return candidate
    return day


def window_days(today: date | None = None) -> list[date]:
    today = today or utils.now().date()
    return [today + timedelta(days=i) for i in range(config.SLOT_WINDOW_DAYS)]


def get_doctor(db: Session, doctor_id: int) -> Doctor:
    doctor = db.get(Doctor, doctor_id)
    if doctor is None:
        raise NotFoundError("We could not find that doctor.")
    return doctor


def list_doctors(db: Session) -> list[Doctor]:
    return list(db.scalars(select(Doctor).order_by(Doctor.id)))


def _build_slots(doctor: Doctor, day: date) -> list[Slot]:
    if is_closed(day) or day.weekday() not in doctor.working_day_set:
        return []
    step = timedelta(minutes=doctor.consultation_minutes)
    start = datetime.combine(day, doctor.work_start)
    closing = datetime.combine(day, doctor.work_end)
    slots = []
    while start + step <= closing:
        slots.append(Slot(doctor_id=doctor.id, start_time=start, end_time=start + step))
        start += step
    return slots


def ensure_slots(db: Session, today: date | None = None) -> None:
    """Seed any missing slots for the rolling window. Safe to call repeatedly."""
    days = window_days(today)
    window_start, _ = utils.day_bounds(days[0])
    _, window_end = utils.day_bounds(days[-1])
    for doctor in list_doctors(db):
        seeded_days = {
            start.date()
            for start in db.scalars(
                select(Slot.start_time).where(
                    Slot.doctor_id == doctor.id,
                    Slot.start_time >= window_start,
                    Slot.start_time < window_end,
                )
            )
        }
        for day in days:
            if day not in seeded_days:
                db.add_all(_build_slots(doctor, day))
    db.commit()


def regenerate_slots(db: Session, doctor: Doctor, today: date | None = None) -> None:
    """Rebuild a doctor's slots from today onwards after their hours change.

    Existing appointments are untouched; new slots that overlap them simply
    show as booked.
    """
    today = today or utils.now().date()
    window_start, _ = utils.day_bounds(today)
    db.execute(delete(Slot).where(Slot.doctor_id == doctor.id, Slot.start_time >= window_start))
    for day in window_days(today):
        db.add_all(_build_slots(doctor, day))
    db.commit()


def _active_appointments(
    db: Session, start: datetime, end: datetime, doctor_id: int | None = None
) -> list[Appointment]:
    stmt = select(Appointment).where(
        Appointment.status != STATUS_CANCELLED,
        Appointment.start_time < end,
        Appointment.end_time > start,
    )
    if doctor_id is not None:
        stmt = stmt.where(Appointment.doctor_id == doctor_id)
    return list(db.scalars(stmt))


def is_free(db: Session, doctor_id: int, start: datetime, end: datetime) -> bool:
    return not _active_appointments(db, start, end, doctor_id)


def blocks_between(db: Session, start: datetime, end: datetime, doctor_id: int | None = None) -> list[DoctorBlock]:
    """Doctor-blocked periods (leave, training...) overlapping [start, end)."""
    stmt = select(DoctorBlock).where(DoctorBlock.start_time < end, DoctorBlock.end_time > start)
    if doctor_id is not None:
        stmt = stmt.where(DoctorBlock.doctor_id == doctor_id)
    return list(db.scalars(stmt.order_by(DoctorBlock.start_time)))


def is_blocked(db: Session, doctor_id: int, start: datetime, end: datetime) -> bool:
    return bool(blocks_between(db, start, end, doctor_id))


def _status(slot: Slot, busy: list[Appointment], now: datetime, blocks: list[DoctorBlock] = ()) -> str:
    if any(a.start_time < slot.end_time and a.end_time > slot.start_time for a in busy):
        return "BOOKED"
    if any(b.start_time < slot.end_time and b.end_time > slot.start_time for b in blocks):
        return "BLOCKED"
    if slot.start_time <= now:
        return "PAST"
    return "AVAILABLE"


def slots_for_day(db: Session, doctor_id: int, day: date, now: datetime | None = None) -> list[SlotView]:
    now = now or utils.now()
    get_doctor(db, doctor_id)
    if is_closed(day):
        return []
    start, end = utils.day_bounds(day)
    slots = db.scalars(
        select(Slot)
        .where(Slot.doctor_id == doctor_id, Slot.start_time >= start, Slot.start_time < end)
        .order_by(Slot.start_time)
    )
    busy = _active_appointments(db, start, end, doctor_id)
    blocks = blocks_between(db, start, end, doctor_id)
    return [SlotView(slot, _status(slot, busy, now, blocks)) for slot in slots]


def count_available(db: Session, start: datetime, end: datetime, now: datetime | None = None) -> int:
    """Number of free, still-in-the-future slots across all doctors in [start, end)."""
    now = now or utils.now()
    slots = db.scalars(select(Slot).where(Slot.start_time >= start, Slot.start_time < end))
    busy_by_doctor: dict[int, list[Appointment]] = {}
    for appointment in _active_appointments(db, start, end):
        busy_by_doctor.setdefault(appointment.doctor_id, []).append(appointment)
    blocks_by_doctor: dict[int, list[DoctorBlock]] = {}
    for block in blocks_between(db, start, end):
        blocks_by_doctor.setdefault(block.doctor_id, []).append(block)
    return sum(
        1
        for slot in slots
        if not is_closed(slot.start_time.date())
        and _status(slot, busy_by_doctor.get(slot.doctor_id, []), now, blocks_by_doctor.get(slot.doctor_id, ()))
        == "AVAILABLE"
    )
