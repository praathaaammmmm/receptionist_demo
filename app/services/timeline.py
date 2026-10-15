"""Read-only patient timeline for reception.

Built on demand from records that already exist (appointments, callback tasks,
simulated calls, doctor outcomes, draft recommendations) plus the small
TimelineEvent log of status changes. Nothing is copied.

Staff-safe by construction: this module never reads a doctor's consultation
summary, follow-up note or recommendation note, so they cannot leak into the
timeline whatever the template does.

To add a new kind of event later (QR check-in, notification sent): record a
TimelineEvent with a new `kind` and give it a title in EVENT_TITLES.
"""
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from .. import utils
from ..models import (
    NEXT_STEPS,
    SOURCE_DOCTOR,
    SOURCE_LABELS,
    SOURCE_STAFF,
    SOURCE_VOICE_DEMO,
    SOURCE_WEBSITE,
    SOURCE_WEBSITE_AI,
    STATUS_CANCELLED,
    STATUS_PENDING,
    Appointment,
    CallbackTask,
    CallLog,
    ConsultationOutcome,
    Patient,
    Notification,
    TimelineEvent,
    TreatmentRecommendation,
    WaitlistEntry,
)

EVENT_TITLES = {
    "PATIENT_REGISTERED": "Patient registered",
    "APPOINTMENT_CREATED": "Appointment booked",
    "APPOINTMENT_CONFIRMED": "Appointment confirmed",
    "APPOINTMENT_ARRIVED": "Patient arrived",
    "APPOINTMENT_COMPLETED": "Consultation completed",
    "APPOINTMENT_CANCELLED": "Appointment cancelled",
    "APPOINTMENT_NO_SHOW": "Marked as no-show",
    "CALLBACK_CREATED": "Callback requested",
    "CALLBACK_IN_PROGRESS": "Callback started",
    "CALLBACK_COMPLETED": "Callback completed",
    "CALL": "Simulated AI call",
    "QR_CHECKIN": "QR check-in at reception",
    "NOTIFICATION_QUEUED": "Notification queued",
    "NOTIFICATION_SENT": "Notification sent (simulated)",
    "NOTIFICATION_DELIVERED": "Notification delivered (simulated)",
    "NOTIFICATION_FAILED": "Notification failed (simulated)",
    "NOTIFICATION_RETRIED": "Notification retried",
    "WAITLIST_JOINED": "Joined the waitlist",
    "WAITLIST_OFFERED": "Waitlist slot offered",
    "WAITLIST_BOOKED": "Booked from the waitlist",
    "OUTCOME_RECORDED": "Consultation outcome recorded",
    "RECOMMENDATION_DRAFTED": "Doctor recommendation drafted",
    "RECOMMENDATION_READY": "Doctor marked recommendation ready",
    "FOLLOWUP_REQUESTED": "Doctor sent follow-up to reception",
    "FOLLOWUP_SCHEDULED": "Procedure follow-up scheduled",
    "CONSULTATION_FOLLOWUP_SCHEDULED": "Consultation follow-up scheduled",
}
CALL_OUTCOMES = {
    "BOOKING_CREATED": "Booking created",
    "CALLBACK_CREATED": "Callback created",
    "FAQ_ANSWERED": "Question answered",
    "ENDED": "Ended with no booking or callback",
}
# Order for events that share a timestamp: the thing must exist before it can change.
_RANK = {"REGISTERED": -1, "CREATED": 0, "CALL": 1, "CHANGE": 2, "OUTCOME": 3, "RECOMMENDATION": 4}
# An assistant booking registers the patient moments before the booking itself.
_REGISTERED_WITH_BOOKING = timedelta(seconds=60)


def _icon(kind: str) -> str:
    if kind == "PATIENT_REGISTERED":
        return "person"
    if kind == "CALL":
        return "call"
    if kind.startswith("QR_"):
        return "qr"
    if kind.startswith("WAITLIST"):
        return "list"
    if kind.startswith("NOTIFICATION"):
        return "message"
    if kind.startswith("CALLBACK"):
        return "callback"
    if kind in ("OUTCOME_RECORDED", "RECOMMENDATION_DRAFTED", "RECOMMENDATION_READY", "FOLLOWUP_REQUESTED"):
        return "doctor"
    return "calendar"  # appointments, and a sensible default for kinds added later


def _appointment_text(a: Appointment) -> str:
    return f"{a.service.name} with {a.doctor.name} on {utils.fmt_date(a.start_time)} at {utils.fmt_time(a.start_time)}"


def _event(kind, at, source, *, detail=None, rank="CHANGE", order=0, title=None, approximate=False, status=None, **refs) -> dict:
    if status is None and kind.startswith(("APPOINTMENT_", "CALLBACK_")):
        # The state the record was in after this event: CONFIRMED, IN_PROGRESS...
        status = kind.split("_", 1)[1]
        status = {"CREATED": "PENDING" if kind.startswith("APPOINTMENT") else "OPEN"}.get(status, status)
    return {
        "kind": kind,
        "icon": _icon(kind),
        "status": status,
        "title": title or EVENT_TITLES.get(kind, kind.replace("_", " ").capitalize()),
        "at": at,
        "source": source,
        "source_label": SOURCE_LABELS.get(source, source.replace("_", " ").title()),
        "detail": detail,
        "approximate": approximate,  # True when the exact time of a change was never recorded
        "appointment_id": refs.get("appointment_id"),
        "callback_task_id": refs.get("callback_task_id"),
        "call_log_id": refs.get("call_log_id"),
        "is_notification": "notification_id" in refs,
        "_sort": (at, _RANK[rank], order),
    }


def build(db: Session, patient: Patient, now=None) -> list[dict]:
    """Every known event for one patient, newest first."""
    now = now or utils.now()
    appointments = db.scalars(
        select(Appointment)
        .options(joinedload(Appointment.doctor), joinedload(Appointment.service))
        .where(Appointment.patient_id == patient.id)
    ).all()
    appointment_ids = [a.id for a in appointments]
    # Callback tasks belong to a name and mobile number, so they are matched by mobile.
    callbacks = db.scalars(select(CallbackTask).where(CallbackTask.mobile == patient.mobile)).all()
    callback_ids = [c.id for c in callbacks]

    call_filters = [CallLog.caller_mobile == patient.mobile]
    if appointment_ids:
        call_filters.append(CallLog.appointment_id.in_(appointment_ids))
    if callback_ids:
        call_filters.append(CallLog.callback_task_id.in_(callback_ids))
    calls = db.scalars(select(CallLog).where(or_(*call_filters))).all()
    by_voice_appointments = {c.appointment_id for c in calls if c.appointment_id}
    by_voice_callbacks = {c.callback_task_id for c in calls if c.callback_task_id}

    def channel(record_source: str, came_by_voice: bool) -> str:
        if record_source == "AI_DEMO":
            return SOURCE_VOICE_DEMO if came_by_voice else SOURCE_WEBSITE_AI
        return SOURCE_WEBSITE if record_source == "WEBSITE" else SOURCE_STAFF

    change_filters = [TimelineEvent.patient_id == patient.id]
    if appointment_ids:
        change_filters.append(TimelineEvent.appointment_id.in_(appointment_ids))
    if callback_ids:
        change_filters.append(TimelineEvent.callback_task_id.in_(callback_ids))
    changes = db.scalars(select(TimelineEvent).where(or_(*change_filters))).all()
    recorded = {(c.appointment_id, c.callback_task_id, c.kind) for c in changes}
    appointment_by_id = {a.id: a for a in appointments}
    callback_by_id = {c.id: c for c in callbacks}

    events = []
    first = min(appointments, key=lambda a: (a.created_at, a.id), default=None)
    registered_by, registered_at = SOURCE_STAFF, patient.created_at
    if first is not None:
        # A patient exists before their first booking, even when both were saved in the same moment.
        registered_at = min(registered_at, first.created_at)
        if abs(first.created_at - patient.created_at) <= _REGISTERED_WITH_BOOKING and first.source == "AI_DEMO":
            registered_by = channel(first.source, first.id in by_voice_appointments)
    events.append(
        _event("PATIENT_REGISTERED", registered_at, registered_by, rank="REGISTERED",
               detail="Patient record created for this mobile number.")
    )
    for a in appointments:
        events.append(
            _event("APPOINTMENT_CREATED", a.created_at, channel(a.source, a.id in by_voice_appointments),
                   detail=_appointment_text(a), rank="CREATED", order=a.id, appointment_id=a.id)
        )
        # Status set before the timeline existed: show it, and say the time is unknown.
        if a.status != STATUS_PENDING and (a.id, None, f"APPOINTMENT_{a.status}") not in recorded:
            events.append(
                _event(f"APPOINTMENT_{a.status}", a.created_at, SOURCE_STAFF, detail=_appointment_text(a),
                       order=a.id, approximate=True, appointment_id=a.id)
            )
    for c in callbacks:
        events.append(
            _event("CALLBACK_CREATED", c.created_at, channel(c.source, c.id in by_voice_callbacks),
                   detail=c.reason, rank="CREATED", order=c.id, callback_task_id=c.id)
        )
        if c.status != "OPEN" and (None, c.id, f"CALLBACK_{c.status}") not in recorded:
            events.append(
                _event(f"CALLBACK_{c.status}", c.created_at, SOURCE_STAFF, detail=c.reason, order=c.id,
                       approximate=True, callback_task_id=c.id)
            )
    waiting = db.scalars(
        select(WaitlistEntry).options(joinedload(WaitlistEntry.service), joinedload(WaitlistEntry.doctor))
        .where(WaitlistEntry.patient_id == patient.id)
    ).all()
    for entry in waiting:
        dates = utils.fmt_date(entry.date_from) if entry.date_from == entry.date_to else f"{utils.fmt_date(entry.date_from)} to {utils.fmt_date(entry.date_to)}"
        events.append(
            _event("WAITLIST_JOINED", entry.created_at, channel(entry.source, False), rank="CREATED", order=entry.id,
                   status="WAITING",
                   detail=f"{entry.service.name} · {entry.doctor.name if entry.doctor else 'any doctor'} · {dates} · "
                          f"{entry.time_preference.lower()} · currently {entry.status.lower()}")
        )
    # Outbox entries for this patient: only the message type, channel and status, never the text or staff notes.
    for n_id, n_type, n_channel, n_created, n_appointment in db.execute(
        select(Notification.id, Notification.type, Notification.channel, Notification.created_at, Notification.appointment_id)
        .where(Notification.patient_id == patient.id)
    ):
        label = n_type.replace("_", " ").capitalize()
        events.append(
            _event("NOTIFICATION_QUEUED", n_created, SOURCE_STAFF, rank="OUTCOME", order=n_id, status="QUEUED",
                   detail=f"{label} · {'Email' if n_channel == 'EMAIL' else 'WhatsApp'} · simulated, not sent",
                   appointment_id=n_appointment, notification_id=n_id)
        )
    for change in changes:
        if change.kind.startswith("NOTIFICATION_"):
            events.append(
                _event(change.kind, change.occurred_at, change.source, detail=change.detail, rank="RECOMMENDATION",
                       order=change.id, status=change.kind.split("_", 1)[1], appointment_id=change.appointment_id,
                       notification_id=0)
            )
            continue
        if change.kind.startswith("WAITLIST_"):
            events.append(
                _event(change.kind, change.occurred_at, change.source, detail=change.detail, order=change.id,
                       status=change.kind.split("_", 1)[1], appointment_id=change.appointment_id)
            )
            continue
        if change.appointment_id in appointment_by_id:
            detail = _appointment_text(appointment_by_id[change.appointment_id])
        elif change.callback_task_id in callback_by_id:
            task = callback_by_id[change.callback_task_id]
            detail = task.reason
            if change.kind == "CALLBACK_COMPLETED" and task.notes:
                detail += f" Staff note: {task.notes}"
        else:
            detail = None
        events.append(
            _event(change.kind, change.occurred_at, change.source, detail=change.detail or detail, order=change.id,
                   appointment_id=change.appointment_id, callback_task_id=change.callback_task_id)
        )
    for call in calls:
        outcome = CALL_OUTCOMES.get(call.outcome, "In progress")
        call_status = call.outcome if call.completed_at or call.outcome else "IN_CALL"
        length = f", {call.duration_seconds // 60}:{call.duration_seconds % 60:02d} min" if call.duration_seconds is not None else ""
        events.append(
            _event("CALL", call.started_at, SOURCE_VOICE_DEMO, detail=f"{outcome}{length}. Simulated call, not a real phone call.",
                   rank="CALL", order=call.id, status=call_status, call_log_id=call.id, appointment_id=call.appointment_id,
                   callback_task_id=call.callback_task_id)
        )
    if appointment_ids:
        # Only the non-clinical columns are selected: the doctor's summary and notes stay in the doctor workspace.
        outcomes = db.execute(
            select(ConsultationOutcome.appointment_id, ConsultationOutcome.next_step, ConsultationOutcome.updated_at,
                   ConsultationOutcome.id).where(ConsultationOutcome.appointment_id.in_(appointment_ids))
        ).all()
        for appointment_id, next_step, updated_at, outcome_id in outcomes:
            events.append(
                _event("OUTCOME_RECORDED", updated_at, SOURCE_DOCTOR, rank="OUTCOME", order=outcome_id,
                       detail=f"Next step: {NEXT_STEPS.get(next_step, next_step)}. Entered by the doctor.",
                       appointment_id=appointment_id)
            )
        drafts = db.execute(
            select(TreatmentRecommendation.appointment_id, TreatmentRecommendation.procedure, TreatmentRecommendation.status,
                   TreatmentRecommendation.created_at, TreatmentRecommendation.id)
            .where(TreatmentRecommendation.appointment_id.in_(appointment_ids))
        ).all()
        for appointment_id, procedure, status, created_at, draft_id in drafts:
            events.append(
                _event("RECOMMENDATION_DRAFTED", created_at, SOURCE_DOCTOR, rank="RECOMMENDATION", order=draft_id,
                       detail=f"{procedure} · {status.replace('_', ' ')}. Entered by the doctor; read-only here.", status="DRAFT",
                       appointment_id=appointment_id)
            )

    events.sort(key=lambda e: e["_sort"], reverse=True)
    # Where reception can open the related record. Bookings are listed on the dashboard from today on.
    today_start, _ = utils.day_bounds(now.date())
    for e in events:
        e.pop("_sort")
        a = appointment_by_id.get(e["appointment_id"])
        if e["kind"] == "CALL":
            e["link"], e["link_label"] = "/#call-activity", "AI call activity"
        elif e["is_notification"]:
            e["link"], e["link_label"] = "/notifications", "Notification centre"
        elif e["callback_task_id"] and not e["kind"].startswith("APPOINTMENT"):
            e["link"], e["link_label"] = "/#callback-tasks", f"Callback C-{e['callback_task_id']}"
        elif e["kind"].startswith("WAITLIST") and a is None:
            e["link"], e["link_label"] = "/waitlist", "Waitlist"
        elif a is not None and a.start_time >= today_start and a.status != STATUS_CANCELLED:
            e["link"], e["link_label"] = f"/#appointment-{a.id}", f"Booking #{a.id}"
        else:
            e["link"], e["link_label"] = None, (f"Booking #{a.id}" if a is not None else None)
    return events


def has_activity(events: list[dict]) -> bool:
    """True once anything beyond the registration itself has happened."""
    return any(e["kind"] != "PATIENT_REGISTERED" for e in events)


def recent_activity(db: Session, limit: int = 6, now=None) -> list[dict]:
    """The latest events across all patients, for the dashboard panel.

    Finds the patients touched most recently in each kind of record, then reuses
    build() for just those patients, so the panel can never show anything the
    patient timeline would not.
    """
    look = max(limit * 2, 10)
    patient_ids: set[int] = set()
    mobiles: set[str] = set()
    patient_ids.update(db.scalars(select(Appointment.patient_id).order_by(Appointment.created_at.desc(), Appointment.id.desc()).limit(look)))
    patient_ids.update(db.scalars(select(Patient.id).order_by(Patient.created_at.desc(), Patient.id.desc()).limit(look)))
    patient_ids.update(
        p for p in db.scalars(select(TimelineEvent.patient_id).order_by(TimelineEvent.id.desc()).limit(look)) if p
    )
    callback_ids = [c for c in db.scalars(select(TimelineEvent.callback_task_id).order_by(TimelineEvent.id.desc()).limit(look)) if c]
    if callback_ids:
        mobiles.update(db.scalars(select(CallbackTask.mobile).where(CallbackTask.id.in_(callback_ids))))
    mobiles.update(db.scalars(select(CallbackTask.mobile).order_by(CallbackTask.id.desc()).limit(look)))
    patient_ids.update(db.scalars(select(WaitlistEntry.patient_id).order_by(WaitlistEntry.id.desc()).limit(look)))
    mobiles.update(m for m in db.scalars(select(CallLog.caller_mobile).order_by(CallLog.id.desc()).limit(look)) if m)
    recent_appointments = select(Appointment.id).order_by(Appointment.id.desc()).limit(look * 3)
    patient_ids.update(
        db.scalars(
            select(Appointment.patient_id)
            .join(ConsultationOutcome, ConsultationOutcome.appointment_id == Appointment.id)
            .where(Appointment.id.in_(recent_appointments))
        )
    )
    if mobiles:
        patient_ids.update(db.scalars(select(Patient.id).where(Patient.mobile.in_(mobiles))))
    if not patient_ids:
        return []

    items = []
    for patient in db.scalars(select(Patient).where(Patient.id.in_(patient_ids))):
        for event in build(db, patient, now):
            # Outbox entries have their own dashboard panel; keep this list about what happened to patients.
            if not event["approximate"] and not event["is_notification"]:
                items.append({**event, "patient": patient})
    items.sort(key=lambda e: e["at"], reverse=True)  # stable: keeps each patient's own order for ties
    return items[:limit]
