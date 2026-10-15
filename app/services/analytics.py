"""Owner analytics: aggregated counts built only from records the demo already stores.

Privacy by construction: every function here returns numbers and fixed labels.
Nothing reads a patient's name, mobile, email or notes, and nothing reads a
doctor's free-text summary or notes.

Honesty rules:
- no invented, estimated or projected figures (no revenue, satisfaction or
  "conversion" claims): if the demo did not record it, it is not shown;
- percentages are shares of the sample bookings in the selected period, shown
  for orientation only.
"""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import utils
from ..models import (
    CALLBACK_COMPLETED,
    CALLBACK_IN_PROGRESS,
    CALLBACK_OPEN,
    NEXT_STEPS,
    NOTIFICATION_STATUSES,
    RECOMMENDATION_STATES,
    STATUS_ARRIVED,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_CONFIRMED,
    STATUS_NO_SHOW,
    WAITLIST_STATUSES,
    Appointment,
    CallbackTask,
    CallLog,
    ConsultationFollowup,
    ConsultationOutcome,
    Notification,
    ProcedureFollowup,
    TimelineEvent,
    TreatmentRecommendation,
    WaitlistEntry,
)

RANGES = {"today": "Today", "week": "This week", "all": "All demo data"}

SOURCES = {
    "STAFF": "Staff",
    "WEBSITE_AI": "Website AI assistant",
    "VOICE_DEMO": "Voice demo",
    "WAITLIST": "Waitlist replacement",
    "WEBSITE_FORM": "Website form (sample)",
}
FUNNEL = [
    ("created", "Bookings created"),
    ("confirmed", "Confirmed appointments"),
    ("arrived", "Patients arrived"),
    ("completed", "Consultations completed"),
    ("no_show", "No-shows"),
    ("cancelled", "Cancellations"),
]
CALL_OUTCOMES = [("BOOKING_CREATED", "Booking created"), ("CALLBACK_CREATED", "Callback created"),
                 ("FAQ_ANSWERED", "FAQ answered"), ("ENDED", "Ended")]


def period(range_key: str, now: datetime | None = None) -> tuple[str, datetime | None, datetime | None]:
    """(key, start, end) for a filter. "week" is Monday to Sunday of the current week."""
    now = now or utils.now()
    key = range_key if range_key in RANGES else "all"
    today_start, today_end = utils.day_bounds(now.date())
    if key == "today":
        return key, today_start, today_end
    if key == "week":
        monday = today_start - timedelta(days=now.weekday())
        return key, monday, monday + timedelta(days=7)
    return key, None, None


def _within(column, start, end):
    return [] if start is None else [column >= start, column < end]


def _count_by(db: Session, model, column, time_column, start, end) -> dict:
    stmt = select(column, func.count()).where(*_within(time_column, start, end)).group_by(column)
    return {key: count for key, count in db.execute(stmt)}


def _stages(status: str, ever_confirmed: bool, ever_arrived: bool) -> dict:
    """Which funnel stages one booking has reached so far."""
    return {
        "created": 1,
        "confirmed": int(ever_confirmed or status in (STATUS_CONFIRMED, STATUS_ARRIVED, STATUS_COMPLETED, STATUS_NO_SHOW)),
        "arrived": int(ever_arrived or status in (STATUS_ARRIVED, STATUS_COMPLETED)),
        "completed": int(status == STATUS_COMPLETED),
        "no_show": int(status == STATUS_NO_SHOW),
        "cancelled": int(status == STATUS_CANCELLED),
    }


def compute(db: Session, range_key: str = "all", now: datetime | None = None) -> dict:
    now = now or utils.now()
    key, start, end = period(range_key, now)

    # ---- Bookings: funnel and source, for bookings CREATED in the period ----------------
    bookings = db.execute(
        select(Appointment.id, Appointment.status, Appointment.source).where(*_within(Appointment.created_at, start, end))
    ).all()
    ids = [b.id for b in bookings]
    by_voice = set(db.scalars(select(CallLog.appointment_id).where(CallLog.appointment_id.in_(ids)))) if ids else set()
    by_waitlist = set(db.scalars(select(WaitlistEntry.appointment_id).where(WaitlistEntry.appointment_id.in_(ids)))) if ids else set()
    reached = {"APPOINTMENT_CONFIRMED": set(), "APPOINTMENT_ARRIVED": set()}
    if ids:
        for kind, appointment_id in db.execute(
            select(TimelineEvent.kind, TimelineEvent.appointment_id)
            .where(TimelineEvent.kind.in_(reached), TimelineEvent.appointment_id.in_(ids))
        ):
            reached[kind].add(appointment_id)

    def source_of(booking) -> str:
        if booking.id in by_waitlist:
            return "WAITLIST"
        if booking.id in by_voice:  # a linked call log proves it came through the voice demo
            return "VOICE_DEMO"
        if booking.source == "AI_DEMO":
            return "WEBSITE_AI"
        return "WEBSITE_FORM" if booking.source == "WEBSITE" else "STAFF"

    funnel = {stage: 0 for stage, _ in FUNNEL}
    sources = {code: {stage: 0 for stage, _ in FUNNEL} for code in SOURCES}
    for booking in bookings:
        stages = _stages(booking.status, booking.id in reached["APPOINTMENT_CONFIRMED"], booking.id in reached["APPOINTMENT_ARRIVED"])
        row = sources[source_of(booking)]
        for stage, hit in stages.items():
            funnel[stage] += hit
            row[stage] += hit
    total = funnel["created"]

    # ---- Operations: records created (or events recorded) in the period -----------------
    callbacks = _count_by(db, CallbackTask, CallbackTask.status, CallbackTask.created_at, start, end)
    calls = db.execute(
        select(CallLog.outcome, CallLog.completed_at).where(*_within(CallLog.started_at, start, end))
    ).all()
    call_outcomes = {code: 0 for code, _ in CALL_OUTCOMES}
    in_progress = 0
    for outcome, completed_at in calls:
        if completed_at is None:
            in_progress += 1
        elif outcome in call_outcomes:
            call_outcomes[outcome] += 1
    waitlist = _count_by(db, WaitlistEntry, WaitlistEntry.status, WaitlistEntry.created_at, start, end)
    notifications = _count_by(db, Notification, Notification.status, Notification.created_at, start, end)
    events = _count_by(db, TimelineEvent, TimelineEvent.kind, TimelineEvent.occurred_at, start, end)
    # Only the fixed "next step" category is counted; the doctor's written summary and notes are never read.
    next_steps = _count_by(db, ConsultationOutcome, ConsultationOutcome.next_step, ConsultationOutcome.created_at, start, end)
    recommendations = db.scalar(
        select(func.count()).select_from(TreatmentRecommendation).where(*_within(TreatmentRecommendation.created_at, start, end))
    )

    recommendation_states = _count_by(db, TreatmentRecommendation, TreatmentRecommendation.status, TreatmentRecommendation.created_at, start, end)
    followups_booked = db.scalar(
        select(func.count()).select_from(ProcedureFollowup).where(*_within(ProcedureFollowup.created_at, start, end))
    )

    consultation_states = _count_by(db, ConsultationFollowup, ConsultationFollowup.status, ConsultationFollowup.created_at, start, end)

    def rows(pairs, values, of=None):
        of = of if of is not None else sum(values.get(code, 0) for code, _ in pairs)
        return [{"code": code, "label": label, "value": values.get(code, 0),
                 "share": round(100 * values.get(code, 0) / of) if of else 0} for code, label in pairs]

    arrivals = events.get("APPOINTMENT_ARRIVED", 0)
    qr = events.get("QR_CHECKIN", 0)
    return {
        "range": key,
        "range_label": RANGES[key],
        "period_start": start.isoformat() if start else None,
        "period_end": end.isoformat() if end else None,
        "sample_data": True,
        "funnel": rows(FUNNEL, funnel, of=total),
        "sources": [
            {"code": code, "label": label, **sources[code], "share": round(100 * sources[code]["created"] / total) if total else 0}
            for code, label in SOURCES.items()
            if code != "WEBSITE_FORM" or sources[code]["created"]
        ],
        "callbacks": rows([(CALLBACK_OPEN, "Open"), (CALLBACK_IN_PROGRESS, "In progress"), (CALLBACK_COMPLETED, "Completed")], callbacks),
        "calls": {"total": len(calls), "in_progress": in_progress, "outcomes": rows(CALL_OUTCOMES, call_outcomes)},
        "waitlist": rows([(s, s.capitalize()) for s in WAITLIST_STATUSES], waitlist),
        "notifications": rows([(s, s.capitalize()) for s in NOTIFICATION_STATUSES], notifications),
        "checkin": {"arrivals": arrivals, "qr_checkins": qr, "other_arrivals": max(arrivals - qr, 0),
                    "qr_share": round(100 * qr / arrivals) if arrivals else 0},
        "doctor": {
            "outcomes": sum(next_steps.values()),
            "next_steps": rows(list(NEXT_STEPS.items()), next_steps),
            "recommendations_drafted": recommendations or 0,
        },
        "followups": {
            "states": rows(list(RECOMMENDATION_STATES.items()), recommendation_states),
            "awaiting": recommendation_states.get("READY_FOR_SCHEDULING", 0),
            "booked": followups_booked or 0,
            # Consultation follow-ups a doctor sent to reception (no procedure recommendation involved).
            "consultation": {
                "requested": sum(consultation_states.values()),
                "awaiting": consultation_states.get("READY_FOR_SCHEDULING", 0),
                "scheduled": consultation_states.get("SCHEDULED", 0),
            },
        },
        "headline": {
            "bookings": total,
            "completed": funnel["completed"],
            "open_callbacks": callbacks.get(CALLBACK_OPEN, 0),
            "ai_calls": len(calls),
        },
    }
