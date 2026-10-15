"""Call log for the browser voice-call simulation.

This records what happened in a simulated call. It is not telephony: no real
call is received, placed or recorded. The conversation itself is handled by
app/services/assistant.py, exactly as for the website assistant.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import utils
from ..models import (
    CALL_BOOKING_CREATED,
    CALL_CALLBACK_CREATED,
    CALL_CHANNEL_VOICE_DEMO,
    CALL_ENDED,
    CALL_FAQ_ANSWERED,
    CallLog,
)
from .errors import NotFoundError, ValidationError

# A call keeps its most significant outcome: a booking outranks a callback, which outranks an answer.
_RANK = {None: 0, CALL_ENDED: 0, CALL_FAQ_ANSWERED: 1, CALL_CALLBACK_CREATED: 2, CALL_BOOKING_CREATED: 3}


def start_call(db: Session, channel: str = CALL_CHANNEL_VOICE_DEMO) -> CallLog:
    call = CallLog(channel=channel, started_at=utils.now())
    db.add(call)
    db.commit()
    return call


def get_call(db: Session, call_id: int) -> CallLog:
    call = db.get(CallLog, call_id)
    if call is None:
        raise NotFoundError("We could not find that demo call.")
    return call


def get_active_call(db: Session, call_id: int) -> CallLog:
    call = get_call(db, call_id)
    if call.completed_at is not None:
        raise ValidationError("This demo call has ended. Please start a new one.")
    return call


def _raise_outcome(call: CallLog, outcome: str) -> None:
    if _RANK[outcome] > _RANK[call.outcome]:
        call.outcome = outcome


def record_turn(db: Session, call: CallLog, reply: dict) -> CallLog:
    """Update the log from one assistant reply: caller details, links and outcome."""
    data = reply.get("state", {}).get("data", {})
    if isinstance(data.get("name"), str) and data["name"]:
        call.caller_name = data["name"][:120]
    if isinstance(data.get("mobile"), str) and data["mobile"]:
        call.caller_mobile = data["mobile"][:20]

    booking, callback = reply.get("booking"), reply.get("callback")
    if booking:
        call.appointment_id = booking["reference"]
        _raise_outcome(call, CALL_BOOKING_CREATED)
    if callback:
        call.callback_task_id = int(str(callback["reference"]).rpartition("-")[2])
        _raise_outcome(call, CALL_CALLBACK_CREATED)
    if reply.get("answered"):
        _raise_outcome(call, CALL_FAQ_ANSWERED)
    db.commit()
    return call


def end_call(db: Session, call_id: int) -> CallLog:
    """Close the call. With no booking, callback or answer the outcome is ENDED. Safe to repeat."""
    call = get_call(db, call_id)
    if call.completed_at is None:
        call.completed_at = utils.now()
        call.outcome = call.outcome or CALL_ENDED
        db.commit()
    return call


def list_recent(db: Session, limit: int = 8) -> list[CallLog]:
    stmt = (
        select(CallLog)
        .options(joinedload(CallLog.appointment), joinedload(CallLog.callback_task))
        .order_by(CallLog.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))
