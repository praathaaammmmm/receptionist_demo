"""Callback tasks: requests for the front desk to phone someone.

Creating a task records the request only. Nothing here places a call.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import utils
from ..models import (
    BOOKING_SOURCES,
    CALLBACK_COMPLETED,
    CALLBACK_IN_PROGRESS,
    CALLBACK_OPEN,
    CALLBACK_STATUSES,
    SOURCE_STAFF,
    CallbackTask,
    TimelineEvent,
)
from . import notifications, patients
from .errors import NotFoundError, ValidationError

# Staff move a task forward only. Completed is final.
ALLOWED_TRANSITIONS = {
    CALLBACK_OPEN: {CALLBACK_IN_PROGRESS, CALLBACK_COMPLETED},
    CALLBACK_IN_PROGRESS: {CALLBACK_COMPLETED},
    CALLBACK_COMPLETED: set(),
}


def _clean(value: str | None, limit: int) -> str | None:
    value = " ".join((value or "").split())
    return value[:limit] or None


def create_callback(
    db: Session,
    *,
    name: str,
    mobile: str,
    reason: str,
    email: str | None = None,
    source: str = "AI_DEMO",
    notes: str | None = None,
) -> CallbackTask:
    name = _clean(name, 120)
    if not name:
        raise ValidationError("Please enter a name for the callback.")
    mobile = patients.normalize_mobile(mobile)
    reason = _clean(reason, 500)
    if not reason:
        raise ValidationError("Please say what the callback is about.")
    if source not in BOOKING_SOURCES:
        raise ValidationError("Please choose a valid source.")

    # The same open request from the same number is one task, not several.
    existing = db.scalar(
        select(CallbackTask).where(
            CallbackTask.mobile == mobile,
            CallbackTask.reason == reason,
            CallbackTask.status == CALLBACK_OPEN,
        )
    )
    if existing:
        return existing

    task = CallbackTask(
        name=name,
        mobile=mobile,
        email=_clean(email, 120),
        reason=reason,
        source=source,
        status=CALLBACK_OPEN,
        notes=_clean(notes, 500),
    )
    db.add(task)
    db.flush()  # the task needs its id before the acknowledgement can refer to it
    # Simulated acknowledgement in the outbox (never sent).
    notifications.queue(
        db, "CALLBACK_ACKNOWLEDGEMENT", key=f"callback:{task.id}", name=task.name, mobile=task.mobile, email=task.email,
        patient_id=notifications.patient_id_for_mobile(db, task.mobile), callback_task_id=task.id,
    )
    db.commit()
    return task


def get_callback(db: Session, task_id: int) -> CallbackTask:
    task = db.get(CallbackTask, task_id)
    if task is None:
        raise NotFoundError("We could not find that callback task.")
    return task


def set_status(db: Session, task_id: int, new_status: str, notes: str | None = None) -> CallbackTask:
    task = get_callback(db, task_id)
    if new_status not in CALLBACK_STATUSES:
        raise ValidationError("Please choose a valid callback status.")
    if new_status != task.status and new_status not in ALLOWED_TRANSITIONS[task.status]:
        current, wanted = task.status.replace("_", " ").lower(), new_status.replace("_", " ").lower()
        raise ValidationError(f"A callback task that is {current} cannot be changed to {wanted}.")
    if new_status != task.status:
        db.add(
            TimelineEvent(
                kind=f"CALLBACK_{new_status}", source=SOURCE_STAFF, occurred_at=utils.now(), callback_task_id=task.id
            )
        )
    task.status = new_status
    if notes is not None:
        task.notes = _clean(notes, 500)
    db.commit()
    return task


def list_active(db: Session) -> list[CallbackTask]:
    """Open and in-progress tasks, oldest first."""
    stmt = (
        select(CallbackTask)
        .where(CallbackTask.status != CALLBACK_COMPLETED)
        .order_by(CallbackTask.created_at, CallbackTask.id)
    )
    return list(db.scalars(stmt))


def list_recently_completed(db: Session, limit: int = 5) -> list[CallbackTask]:
    stmt = (
        select(CallbackTask)
        .where(CallbackTask.status == CALLBACK_COMPLETED)
        .order_by(CallbackTask.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def list_all(db: Session, status: str | None = None) -> list[CallbackTask]:
    stmt = select(CallbackTask).order_by(CallbackTask.created_at, CallbackTask.id)
    if status:
        stmt = stmt.where(CallbackTask.status == status)
    return list(db.scalars(stmt))


def counts(db: Session) -> dict:
    found = dict(db.execute(select(CallbackTask.status, func.count()).group_by(CallbackTask.status)).all())
    return {
        "open": found.get(CALLBACK_OPEN, 0),
        "in_progress": found.get(CALLBACK_IN_PROGRESS, 0),
        "completed": found.get(CALLBACK_COMPLETED, 0),
    }
