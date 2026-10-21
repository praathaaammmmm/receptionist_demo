"""Runtime call context: what the agent knows about this moment and this caller.

All times are India Standard Time. IST has no daylight saving, so a fixed +05:30
offset is exact and does not depend on the host's timezone database.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from . import phone
from .knowledge import APPROVED, OpeningHours

IST = timezone(timedelta(hours=5, minutes=30), "IST")


@dataclass(frozen=True)
class RuntimeContext:
    now_ist: datetime
    clinic_open_now: bool
    transfer_available: bool
    # Normalised caller ID, if any. Never read aloud or put in a prompt; it is used for a
    # callback only after the caller agrees to be called back on the number they are calling from.
    caller_number: str | None = field(default=None, repr=False)

    @property
    def caller_number_available(self) -> bool:
        return self.caller_number is not None


def to_ist(moment: datetime) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("Call times must be timezone-aware.")
    return moment.astimezone(IST)


def _within(moment: datetime, start: time, end: time, hours: OpeningHours) -> bool:
    return moment.weekday() in hours.days and start <= moment.time() < end


def is_clinic_open(moment: datetime, hours: OpeningHours = APPROVED.hours) -> bool:
    return _within(to_ist(moment), hours.opens, hours.closes, hours)


def in_transfer_window(moment: datetime, hours: OpeningHours = APPROVED.hours) -> bool:
    return _within(to_ist(moment), hours.transfer_from, hours.transfer_until, hours)


def next_working_day(day: date, hours: OpeningHours = APPROVED.hours) -> date:
    day += timedelta(days=1)
    while day.weekday() not in hours.days:
        day += timedelta(days=1)
    return day


def build_runtime_context(
    now: datetime | None = None,
    *,
    staff_available: bool | None = None,
    caller_number: str | None = None,
    hours: OpeningHours = APPROVED.hours,
) -> RuntimeContext:
    """The context for one call.

    staff_available overrides the transfer window when it is given: False when reception
    is busy or away, True when staff can take a transfer outside the usual window.
    An invalid or withheld caller ID becomes None; the agent then asks for a number.
    """
    now_ist = to_ist(now) if now is not None else datetime.now(IST)
    transfer = in_transfer_window(now_ist, hours) if staff_available is None else staff_available
    try:
        number = phone.normalize_indian_mobile(caller_number) if caller_number else None
    except phone.InvalidPhone:
        number = None
    return RuntimeContext(
        now_ist=now_ist.replace(microsecond=0),
        clinic_open_now=is_clinic_open(now_ist, hours),
        transfer_available=transfer,
        caller_number=number,
    )
