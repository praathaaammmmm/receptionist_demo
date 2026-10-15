"""Demo Notification Centre: staff outbox screen and API.

SIMULATION ONLY. No message is sent by any route here; the actions change a
status in the local database and nothing else.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import notification_templates as templates
from ..database import get_db
from ..models import NOTIFICATION_STATUSES
from ..services import notifications
from ..services.errors import ClinicError
from .pages import redirect, render

router = APIRouter()
ACTION_NOTICES = {"send": "notification_sent", "deliver": "notification_delivered", "fail": "notification_failed", "retry": "notification_retried"}


def notification_out(n, full: bool = False) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "type_label": notifications.type_label(n.type),
        "channel": n.channel,
        "status": n.status,
        "attempts": n.attempts,
        "patient_id": n.patient_id,
        "recipient_name": n.recipient_name,
        # List views never carry the full contact detail.
        "recipient_contact": n.recipient_contact if full else notifications.mask_contact(n.recipient_contact),
        "message": n.message,
        "appointment_id": n.appointment_id,
        "callback_task_id": n.callback_task_id,
        "waitlist_entry_id": n.waitlist_entry_id,
        "created_at": n.created_at.isoformat(),
        "updated_at": n.updated_at.isoformat(),
        "simulated": True,
    }


def page(request: Request, db: Session, filters: dict, error: ClinicError | None = None):
    notifications.queue_due_reminders(db)
    context = {
        "active": "notifications",
        "items": notifications.search(db, q=filters["q"], status=filters["status"], channel=filters["channel"], kind=filters["type"]),
        "counts": notifications.counts(db),
        "filters": filters,
        "statuses": NOTIFICATION_STATUSES,
        "channels": templates.CHANNELS,
        "types": {key: value["label"] for key, value in templates.TEMPLATES.items()},
        "mask": notifications.mask_contact,
        "type_label": notifications.type_label,
        "reminder_hours": templates.REMINDER_HOURS_BEFORE,
    }
    if error is not None:
        context["notice"] = ("error", error.message)
    response = render(request, db, "notifications.html", **context)
    if error is not None:
        response.status_code = error.status_code
    return response


@router.get("/notifications", include_in_schema=False)
def notifications_page(
    request: Request, q: str = "", status: str = "", channel: str = "", type: str = "", db: Session = Depends(get_db)
):
    return page(request, db, {"q": q, "status": status, "channel": channel, "type": type})


@router.post("/notifications/{notification_id}/{action}", include_in_schema=False)
def notification_action(request: Request, notification_id: int, action: str, db: Session = Depends(get_db)):
    try:
        notifications.act(db, notification_id, action)
    except ClinicError as exc:
        return page(request, db, {"q": "", "status": "", "channel": "", "type": ""}, exc)
    return redirect("/notifications", notice=ACTION_NOTICES[action])


@router.get("/api/notifications", tags=["notifications"])
def api_list(q: str = "", status: str = "", channel: str = "", type: str = "", db: Session = Depends(get_db)):
    """The simulated outbox, newest first. Contact details are masked."""
    return [notification_out(n) for n in notifications.search(db, q=q, status=status, channel=channel, kind=type)]


@router.get("/api/notifications/summary", tags=["notifications"])
def api_summary(db: Session = Depends(get_db)):
    return notifications.counts(db)


@router.post("/api/notifications/{notification_id}/{action}", tags=["notifications"])
def api_action(notification_id: int, action: str, db: Session = Depends(get_db)):
    """Simulate send / deliver / fail / retry. Nothing is sent anywhere."""
    return notification_out(notifications.act(db, notification_id, action))
