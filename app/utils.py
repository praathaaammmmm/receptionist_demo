from datetime import date, datetime, time, timedelta


def now() -> datetime:
    """Clinic-local wall-clock time (the demo stores naive local datetimes)."""
    return datetime.now().replace(microsecond=0)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min)
    return start, start + timedelta(days=1)


def fmt_time(value: datetime | time) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def fmt_date(value: datetime | date) -> str:
    return value.strftime("%a, %d %b")
