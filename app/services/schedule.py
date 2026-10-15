"""Doctor weekly schedule and blocked periods (leave, training...).

A block is an overlay on the doctor's consultation slots: slots inside it are
never offered to reception or the assistant (see availability.slots_for_day and
appointments.create_appointment). Blocks never move or cancel appointments.
"""
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import config, utils
from ..models import (
    BLOCK_REASONS,
    STATUS_ARRIVED,
    STATUS_CONFIRMED,
    STATUS_PENDING,
    Appointment,
    DoctorBlock,
)
from . import availability, clinic
from .errors import NotFoundError, NotPermittedError, ValidationError

# Appointments that still expect the patient to be seen.
ACTIVE_STATUSES = (STATUS_PENDING, STATUS_CONFIRMED, STATUS_ARRIVED)
APPOINTMENT_CONFLICT = "This time cannot be blocked because it has a scheduled patient appointment."
MAX_WEEK_OFFSET = 26


def _active_appointments(db: Session, doctor_id: int, start: datetime, end: datetime) -> list[Appointment]:
    stmt = select(Appointment).where(
        Appointment.doctor_id == doctor_id,
        Appointment.status.in_(ACTIVE_STATUSES),
        Appointment.start_time < end,
        Appointment.end_time > start,
    )
    return list(db.scalars(stmt))


def create_block(
    db: Session,
    doctor_id: int,
    *,
    day: date,
    start: time | None = None,
    end: time | None = None,
    reason: str = "LEAVE",
    now: datetime | None = None,
) -> DoctorBlock:
    """Block a whole day, or part of one, for a doctor."""
    now = now or utils.now()
    availability.get_doctor(db, doctor_id)
    if reason not in BLOCK_REASONS:
        raise ValidationError("Please choose a reason for the blocked time.")
    if availability.is_closed(day):
        # The clinic-wide rule is not something a doctor's schedule can change either way.
        raise ValidationError(f"{clinic.closed_day_message(db, day)} There is nothing to block on that day.")
    if (start is None) != (end is None):
        raise ValidationError("Please enter both a start and an end time, or leave both empty for the whole day.")
    if start is None:
        begins, finishes = utils.day_bounds(day)
    else:
        begins, finishes = datetime.combine(day, start), datetime.combine(day, end)
        if finishes <= begins:
            raise ValidationError("The end time must be after the start time.")
    if finishes <= now or day < now.date():
        raise ValidationError("Only future time can be blocked.")
    if start is not None and begins <= now:
        raise ValidationError("Only future time can be blocked.")

    if _active_appointments(db, doctor_id, begins, finishes):
        raise ValidationError(APPOINTMENT_CONFLICT)
    if availability.is_blocked(db, doctor_id, begins, finishes):
        raise ValidationError("Some of that time is already blocked.")

    block = DoctorBlock(doctor_id=doctor_id, start_time=begins, end_time=finishes, reason=reason)
    db.add(block)
    db.commit()
    return block


def remove_block(db: Session, doctor_id: int, block_id: int, now: datetime | None = None) -> None:
    now = now or utils.now()
    availability.get_doctor(db, doctor_id)
    block = db.get(DoctorBlock, block_id)
    if block is None:
        raise NotFoundError("We could not find that blocked period.")
    if block.doctor_id != doctor_id:
        raise NotPermittedError("That blocked period is on another doctor's schedule.")
    if block.end_time <= now:
        raise ValidationError("Past blocked periods are kept and cannot be removed.")
    if _active_appointments(db, doctor_id, block.start_time, block.end_time):
        raise ValidationError(
            "This blocked period cannot be removed because it has a scheduled patient appointment."
        )
    db.delete(block)
    db.commit()


def upcoming_blocks(db: Session, doctor_id: int, now: datetime | None = None) -> list[DoctorBlock]:
    now = now or utils.now()
    stmt = (
        select(DoctorBlock)
        .where(DoctorBlock.doctor_id == doctor_id, DoctorBlock.end_time > now)
        .order_by(DoctorBlock.start_time)
    )
    return list(db.scalars(stmt))


def week_start(offset: int = 0, today: date | None = None) -> date:
    """Weeks are counted from today, so week 0 is exactly the bookable 7-day window."""
    today = today or utils.now().date()
    offset = max(-MAX_WEEK_OFFSET, min(MAX_WEEK_OFFSET, offset))
    return today + timedelta(days=7 * offset)


def week(db: Session, doctor_id: int, start_day: date, now: datetime | None = None) -> list[dict]:
    """Seven days of one doctor's schedule: appointments, free slots and blocked periods."""
    now = now or utils.now()
    doctor = availability.get_doctor(db, doctor_id)
    week_begin, _ = utils.day_bounds(start_day)
    week_end = week_begin + timedelta(days=7)
    bookable = set(availability.window_days(now.date()))

    appointments = db.scalars(
        select(Appointment)
        .options(joinedload(Appointment.patient), joinedload(Appointment.service))
        .where(Appointment.doctor_id == doctor_id, Appointment.start_time >= week_begin, Appointment.start_time < week_end)
        .order_by(Appointment.start_time, Appointment.id)
    ).all()
    blocks = availability.blocks_between(db, week_begin, week_end, doctor_id)

    days = []
    for offset in range(7):
        day = start_day + timedelta(days=offset)
        day_begin, day_end = utils.day_bounds(day)
        closed = availability.is_closed(day)
        working = not closed and day.weekday() in doctor.working_day_set
        free = [] if closed else [v.slot for v in availability.slots_for_day(db, doctor_id, day, now) if v.available]
        entries = [{"kind": "appointment", "start": a.start_time, "end": a.end_time, "appointment": a}
                   for a in appointments if day_begin <= a.start_time < day_end]
        entries += [{"kind": "slot", "start": s.start_time, "end": s.end_time, "slot": s} for s in free]
        entries += [{"kind": "block", "start": max(b.start_time, day_begin), "end": min(b.end_time, day_end), "block": b}
                    for b in blocks if b.start_time < day_end and b.end_time > day_begin]
        entries.sort(key=lambda e: (e["start"], {"block": 0, "appointment": 1, "slot": 2}[e["kind"]]))
        days.append(
            {
                "date": day,
                "is_today": day == now.date(),
                "is_past": day < now.date(),
                "closed": closed,
                "working": working,
                # Days beyond the 7-day window have no slots yet; they open as the window rolls forward.
                "bookable": day in bookable,
                "hours": (doctor.work_start, doctor.work_end) if working else None,
                "entries": entries,
                "available": len(free),
                "booked": sum(1 for e in entries if e["kind"] == "appointment" and e["appointment"].is_active),
            }
        )
    return days


def booking_window_days() -> int:
    return config.SLOT_WINDOW_DAYS
