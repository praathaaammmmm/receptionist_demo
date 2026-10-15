"""QR appointment check-in (demo).

A confirmed appointment can be given one opaque random token, shown as a QR
code. At arrival, reception scans or types it; this module decides whether the
token may be used and, once staff confirm, marks the patient ARRIVED.

Safety rules, all enforced here on the server:
- the token is random and carries no information; nothing can be read from the QR;
- a refused token (unknown, cancelled, wrong day, expired, no longer valid)
  returns only a short message, never the patient or appointment behind it;
- check-in is always a staff action: there is no patient self-check-in;
- it only ever performs CONFIRMED -> ARRIVED, through the normal status rules.
"""
import re
import secrets
from datetime import datetime, timedelta

import segno
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import config, utils
from ..models import (
    SOURCE_STAFF,
    STATUS_ARRIVED,
    STATUS_CONFIRMED,
    Appointment,
    CheckinToken,
    TimelineEvent,
)
from . import appointments
from .errors import ValidationError

READY, ALREADY, REFUSED = "READY", "ALREADY_CHECKED_IN", "REFUSED"

NOT_RECOGNISED = "This QR code is not recognised. Please check the code, or find the booking by the patient's name."
NO_LONGER_VALID = "This QR code is no longer valid. Please find the booking by the patient's name."
WRONG_DAY = "This QR code is for a different day and cannot be used today."
EXPIRED = "This QR code has expired. Please find the booking by the patient's name."
NOT_OPEN_YET = "This QR code cannot be used yet. Check-in opens closer to the appointment time."
ALREADY_MESSAGE = "Patient already checked in"

_TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")


def clean_token(raw: str | None) -> str:
    """What reception typed, pasted or scanned, without stray spaces or line breaks."""
    return "".join((raw or "").split())


def window(appointment: Appointment) -> tuple[datetime, datetime]:
    """When this appointment can be checked in: only on its own date, around its start time."""
    day_start, day_end = utils.day_bounds(appointment.start_time.date())
    before = config.CHECKIN_OPENS_MINUTES_BEFORE
    opens = day_start if before is None else max(day_start, appointment.start_time - timedelta(minutes=before))
    closes = min(day_end, appointment.start_time + timedelta(minutes=config.CHECKIN_CLOSES_MINUTES_AFTER))
    return opens, closes


def can_generate(appointment: Appointment, now: datetime | None = None) -> bool:
    """A QR can be issued for a confirmed booking that is today or later and not yet past its window."""
    now = now or utils.now()
    return appointment.status == STATUS_CONFIRMED and now < window(appointment)[1]


def generate(db: Session, appointment_id: int, now: datetime | None = None) -> CheckinToken:
    """The appointment's check-in token, created on first request. One appointment, one token."""
    now = now or utils.now()
    appointment = appointments.get_appointment(db, appointment_id)
    if appointment.checkin_token is not None:
        return appointment.checkin_token
    if appointment.status != STATUS_CONFIRMED:
        raise ValidationError("A check-in QR can only be generated for a confirmed booking.")
    if not can_generate(appointment, now):
        raise ValidationError("This booking is in the past, so a check-in QR cannot be generated.")
    record = CheckinToken(appointment_id=appointment.id, token=secrets.token_urlsafe(24), created_at=now)
    db.add(record)
    db.commit()
    return record


def qr_payload(record: CheckinToken) -> str:
    """Exactly what the QR code encodes: the opaque token and nothing else."""
    return record.token


def qr_svg(record: CheckinToken, scale: int = 7) -> str:
    code = segno.make(qr_payload(record), error="m", micro=False)
    return code.svg_inline(scale=scale, dark="#091D3E", light="#FFFFFF", border=3)


def _find(db: Session, token: str) -> CheckinToken | None:
    if not _TOKEN_SHAPE.match(token):
        return None
    stmt = (
        select(CheckinToken)
        .options(joinedload(CheckinToken.appointment).joinedload(Appointment.patient))
        .where(CheckinToken.token == token)
    )
    return db.scalar(stmt)


def inspect(db: Session, raw_token: str, now: datetime | None = None) -> dict:
    """Decide what reception may do with a token. Changes nothing.

    Returns {"state", "message", "appointment", "token"}. `appointment` is only
    set when the token is usable right now or the patient is already checked in;
    every refusal leaves it empty so no patient data can be shown.
    """
    now = now or utils.now()
    token = clean_token(raw_token)

    def refused(message: str) -> dict:
        return {"state": REFUSED, "message": message, "appointment": None, "token": None}

    if not token:
        return refused("Please scan or enter a check-in code.")
    record = _find(db, token)
    if record is None:
        return refused(NOT_RECOGNISED)

    appointment = record.appointment
    if appointment.status == STATUS_ARRIVED:
        return {"state": ALREADY, "message": ALREADY_MESSAGE, "appointment": appointment, "token": record}
    if appointment.status != STATUS_CONFIRMED:
        # Cancelled, completed, no-show (or anything unexpected): say nothing about whose it was.
        return refused(NO_LONGER_VALID)
    opens, closes = window(appointment)
    if now.date() != appointment.start_time.date():
        return refused(EXPIRED if now.date() > appointment.start_time.date() else WRONG_DAY)
    if now >= closes:
        return refused(EXPIRED)
    if now < opens:
        return refused(NOT_OPEN_YET)
    return {"state": READY, "message": "Booking found. Confirm with the patient, then mark them as arrived.",
            "appointment": appointment, "token": record}


def mark_arrived(db: Session, raw_token: str, now: datetime | None = None) -> dict:
    """Staff-confirmed check-in. A repeat is harmless: nothing is changed the second time."""
    now = now or utils.now()
    result = inspect(db, raw_token, now)
    if result["state"] != READY:
        return result
    appointment, record = result["appointment"], result["token"]
    # Audit and analytics event, saved in the same transaction as the status change below.
    db.add(
        TimelineEvent(
            kind="QR_CHECKIN",
            source=SOURCE_STAFF,
            occurred_at=now,
            patient_id=appointment.patient_id,
            appointment_id=appointment.id,
            detail="Checked in at reception with the demo appointment QR.",
        )
    )
    record.used_at = now
    appointment = appointments.set_status(db, appointment.id, STATUS_ARRIVED, actor=SOURCE_STAFF)
    return {"state": "CHECKED_IN", "message": "Patient marked as arrived.", "appointment": appointment, "token": record}
