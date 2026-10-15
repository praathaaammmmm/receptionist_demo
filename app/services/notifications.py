"""Demo Notification Centre: a simulated outbox.

NO MESSAGE IS EVER SENT. This module only writes rows to the local database.
It has no WhatsApp, email or SMS client, no provider key, no webhook and makes
no network call; "Send" and "Mark delivered" just change a status so the
clinic can see what an outbox would look like.
"""
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from .. import notification_templates as templates
from .. import utils
from ..models import (
    NOTIFICATION_DELIVERED,
    NOTIFICATION_FAILED,
    NOTIFICATION_QUEUED,
    NOTIFICATION_SENT,
    NOTIFICATION_STATUSES,
    SOURCE_STAFF,
    STATUS_CONFIRMED,
    Appointment,
    Notification,
    Patient,
    TimelineEvent,
)
from . import clinic
from .errors import NotFoundError, ValidationError

# What staff may do from each status. Delivered is final; a failed message can be retried.
ACTIONS = {
    "send": ({NOTIFICATION_QUEUED}, NOTIFICATION_SENT),
    "deliver": ({NOTIFICATION_SENT}, NOTIFICATION_DELIVERED),
    "fail": ({NOTIFICATION_QUEUED, NOTIFICATION_SENT}, NOTIFICATION_FAILED),
    "retry": ({NOTIFICATION_FAILED}, NOTIFICATION_QUEUED),
}


def type_label(kind: str) -> str:
    return templates.TEMPLATES.get(kind, {}).get("label", kind.replace("_", " ").capitalize())


def channel_label(channel: str) -> str:
    return templates.CHANNELS.get(channel, channel.title())


def mask_contact(contact: str) -> str:
    """Enough to recognise the contact, not enough to copy it from a list."""
    if "@" in contact:
        name, _, domain = contact.partition("@")
        return f"{name[:1]}•••@{domain}"
    return "•" * max(len(contact) - 4, 0) + contact[-4:]


def _render(db: Session, kind: str, channel: str, *, patient_name: str, when: datetime | None, doctor: str = "", service: str = "") -> str:
    profile = clinic.get_clinic(db)
    values = {
        "patient": patient_name,
        "clinic": profile.name,
        "phone": profile.phone,
        "date": utils.fmt_date(when) if when else "",
        "time": utils.fmt_time(when) if when else "",
        "doctor": doctor,
        "service": service,
    }
    template = templates.TEMPLATES[kind]
    body = template["body"].format(**values)
    return f"Subject: {template['subject'].format(**values)}\n\n{body}" if channel == "EMAIL" else body


def queue(
    db: Session,
    kind: str,
    *,
    key: str,
    name: str,
    mobile: str,
    email: str | None = None,
    prefer_email: bool = False,
    patient_id: int | None = None,
    when: datetime | None = None,
    doctor: str = "",
    service: str = "",
    appointment_id: int | None = None,
    callback_task_id: int | None = None,
    waitlist_entry_id: int | None = None,
) -> Notification:
    """Add one QUEUED outbox entry for an event, unless that event already has one.

    Does not commit: it joins the caller's transaction, so the notification
    exists exactly when the action that caused it succeeds.
    """
    dedupe_key = f"{kind}:{key}"
    existing = db.scalar(select(Notification).where(Notification.dedupe_key == dedupe_key))
    if existing is not None:
        return existing
    channel = "EMAIL" if prefer_email and email else "WHATSAPP"
    now = utils.now()
    notification = Notification(
        type=kind,
        channel=channel,
        status=NOTIFICATION_QUEUED,
        recipient_name=name,
        recipient_contact=email if channel == "EMAIL" else mobile,
        message=_render(db, kind, channel, patient_name=name, when=when, doctor=doctor, service=service),
        dedupe_key=dedupe_key,
        created_at=now,
        updated_at=now,
        patient_id=patient_id,
        appointment_id=appointment_id,
        callback_task_id=callback_task_id,
        waitlist_entry_id=waitlist_entry_id,
    )
    db.add(notification)
    return notification


def queue_for_appointment(db: Session, kind: str, appointment: Appointment) -> Notification:
    patient = appointment.patient
    return queue(
        db, kind, key=f"appointment:{appointment.id}", name=patient.name, mobile=patient.mobile, email=patient.email,
        patient_id=patient.id, when=appointment.start_time, doctor=appointment.doctor.name,
        service=appointment.service.name, appointment_id=appointment.id,
    )


def queue_due_reminders(db: Session, now: datetime | None = None) -> int:
    """Queue a reminder for each confirmed appointment starting soon that does not have one yet.

    There is no background scheduler in the demo: this runs when staff open the
    dashboard or the notification centre.
    """
    now = now or utils.now()
    horizon = now + timedelta(hours=templates.REMINDER_HOURS_BEFORE)
    due = db.scalars(
        select(Appointment)
        .options(joinedload(Appointment.patient), joinedload(Appointment.doctor), joinedload(Appointment.service))
        .where(Appointment.status == STATUS_CONFIRMED, Appointment.start_time > now, Appointment.start_time <= horizon)
    ).all()
    have = set(db.scalars(select(Notification.dedupe_key).where(Notification.type == "APPOINTMENT_REMINDER")))
    created = 0
    for appointment in due:
        if f"APPOINTMENT_REMINDER:appointment:{appointment.id}" not in have:
            queue_for_appointment(db, "APPOINTMENT_REMINDER", appointment)
            created += 1
    if created:
        db.commit()
    return created


def get_notification(db: Session, notification_id: int) -> Notification:
    notification = db.get(Notification, notification_id)
    if notification is None:
        raise NotFoundError("We could not find that notification.")
    return notification


def act(db: Session, notification_id: int, action: str) -> Notification:
    """Simulate a staff action: send, deliver, fail or retry. Only a status changes; nothing leaves the app."""
    notification = get_notification(db, notification_id)
    if action not in ACTIONS:
        raise ValidationError("That action is not available for a notification.")
    allowed_from, new_status = ACTIONS[action]
    if notification.status not in allowed_from:
        raise ValidationError(f"A {notification.status.lower()} notification cannot be changed with “{action}”.")
    now = utils.now()
    if action == "retry":
        notification.attempts += 1
    notification.status = new_status
    notification.updated_at = now
    kind = "NOTIFICATION_RETRIED" if action == "retry" else f"NOTIFICATION_{new_status}"
    attempt = f" · attempt {notification.attempts}" if notification.attempts > 1 else ""
    db.add(
        TimelineEvent(
            kind=kind, source=SOURCE_STAFF, occurred_at=now, patient_id=notification.patient_id,
            appointment_id=notification.appointment_id, callback_task_id=notification.callback_task_id,
            detail=f"{type_label(notification.type)} · {channel_label(notification.channel)}{attempt} · simulated, not sent",
        )
    )
    db.commit()
    return notification


def search(
    db: Session, *, q: str = "", status: str = "", channel: str = "", kind: str = "", limit: int = 200
) -> list[Notification]:
    stmt = select(Notification).options(joinedload(Notification.patient)).order_by(Notification.id.desc())
    if status in NOTIFICATION_STATUSES:
        stmt = stmt.where(Notification.status == status)
    if channel in templates.CHANNELS:
        stmt = stmt.where(Notification.channel == channel)
    if kind in templates.TEMPLATES:
        stmt = stmt.where(Notification.type == kind)
    term = (q or "").strip()
    if term:
        stmt = stmt.where(
            or_(
                Notification.recipient_name.icontains(term, autoescape=True),
                Notification.message.icontains(term, autoescape=True),
                Notification.type.icontains(term.replace(" ", "_"), autoescape=True),
            )
        )
    return list(db.scalars(stmt.limit(limit)))


def counts(db: Session) -> dict:
    found = dict(db.execute(select(Notification.status, func.count()).group_by(Notification.status)).all())
    result = {status.lower(): found.get(status, 0) for status in NOTIFICATION_STATUSES}
    result["total"] = sum(found.values())
    return result


def patient_id_for_mobile(db: Session, mobile: str) -> int | None:
    return db.scalar(select(Patient.id).where(Patient.mobile == mobile))
