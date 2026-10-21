"""Browser voice agent demo: server-side sessions around app/voice_agent/conversation.py.

Each call is an independent in-memory session with its own runtime context, built in IST
when the call starts. Nothing is written while the call runs except a callback the caller
has confirmed, which goes through the existing callback service. When the call ends (the
caller says goodbye or End is pressed) it is logged once through the existing call log.

Demo only: no telephony, no recording, no LLM and no booking. Sessions live in memory, so
restarting the server ends any call in progress.
"""
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime

from sqlalchemy.orm import Session

from .. import utils
from ..models import CALL_CALLBACK_CREATED, CALL_CHANNEL_VOICE_AGENT, CALL_ENDED, CALL_FAQ_ANSWERED
from ..schemas import VoiceAgentStart
from ..voice_agent import wording
from ..voice_agent.context import RuntimeContext, build_runtime_context
from ..voice_agent.conversation import STATE_LABELS, Conversation, ConversationEnded, Turn
from ..voice_agent.schemas import CALLER_NUMBER, CallbackDetails
from . import callbacks, calls, notifications, tts
from .errors import ClinicError, NotFoundError

# Sample caller ID for the "caller number present" simulation. Never shown or spoken until the
# caller agrees to be called back on it.
DEMO_CALLER_NUMBER = "9876543210"
MAX_SESSIONS = 200
IDLE_SECONDS = 2 * 60 * 60
CALLBACK_SOURCE = "AI_DEMO"


class CallEndedError(ClinicError):
    status_code = 409
    code = "call_ended"
    default_message = "This demo call has ended. Please start a new one."


@dataclass
class DemoSession:
    id: str
    conversation: Conversation
    started_at: datetime
    simulation: dict
    last_seen: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)
    callback_ids: list[int] = field(default_factory=list)
    urgent_callback_id: int | None = None
    call_log_id: int | None = None
    outcome: str | None = None


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, DemoSession] = {}
        self._lock = threading.Lock()

    def add(self, session: DemoSession) -> None:
        with self._lock:
            now = time.monotonic()
            for key in [k for k, s in self._sessions.items() if now - s.last_seen > IDLE_SECONDS]:
                del self._sessions[key]
            while len(self._sessions) >= MAX_SESSIONS:
                del self._sessions[min(self._sessions, key=lambda k: self._sessions[k].last_seen)]
            self._sessions[session.id] = session

    def get(self, session_id: str) -> DemoSession:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise NotFoundError("This demo call is no longer available. Please start a new one.")
        session.last_seen = time.monotonic()
        return session


def build_context(options: VoiceAgentStart, now: datetime | None = None) -> RuntimeContext:
    """Fresh IST context for a new call, with any demo simulation applied explicitly."""
    staff = {"auto": None, "available": True, "unavailable": False}[options.transfer]
    context = build_runtime_context(
        now, staff_available=staff, caller_number=DEMO_CALLER_NUMBER if options.caller_id == "present" else None
    )
    if options.clinic != "auto":
        open_now = options.clinic == "open"
        # Simulating open or closed hours also simulates the transfer window, unless transfer is set too.
        context = replace(context, clinic_open_now=open_now,
                          transfer_available=staff if staff is not None else open_now)
    return context


def start(store: SessionStore, options: VoiceAgentStart, now: datetime | None = None,
          router=None) -> tuple[DemoSession, Turn]:
    """A new call. Writes nothing: the call is logged only when it ends."""
    context = build_context(options, now)
    conversation = Conversation(context, options.language, router=router)
    if router is not None:
        router.warm_up()
    session = DemoSession(
        id=secrets.token_urlsafe(16),
        conversation=conversation,
        started_at=utils.now(),
        simulation={"transfer": options.transfer, "caller_id": options.caller_id, "clinic": options.clinic},
    )
    store.add(session)
    return session, conversation.start()


def _save_callback(db: Session, session: DemoSession, details: CallbackDetails, intent: str | None = None) -> int:
    label = wording.STAFF_INTENT_LABELS.get(intent or "", wording.STAFF_CATEGORY_LABELS[details.category])
    if details.urgent:
        label = wording.STAFF_CATEGORY_LABELS[details.category]
    task = callbacks.create_callback(
        db,
        name=details.name,
        mobile=details.phone,
        reason=f"{label}: {details.reason}",
        source=CALLBACK_SOURCE,
        notes=f"Voice agent demo call. {details.notes or ''}".strip(),
    )
    session.callback_ids.append(task.id)
    if details.urgent:
        session.urgent_callback_id = task.id
    return task.id


def _finish(db: Session, session: DemoSession) -> None:
    """Log the call exactly once."""
    if session.call_log_id is not None:
        return
    conversation = session.conversation
    conversation.end()
    confirmed = conversation.session.callbacks
    call = calls.log_finished_call(
        db,
        channel=CALL_CHANNEL_VOICE_AGENT,
        started_at=session.started_at,
        language=conversation.language.value,
        caller_name=confirmed[0].name if confirmed else None,
        caller_mobile=confirmed[0].phone if confirmed else None,
        callback_task_id=session.urgent_callback_id or (session.callback_ids[0] if session.callback_ids else None),
        answered=conversation.answered,
    )
    session.call_log_id, session.outcome = call.id, call.outcome


def message(db: Session, store: SessionStore, session_id: str, text: str, language: str | None,
            heard: str | None = None, uncertain: bool = False) -> tuple[DemoSession, Turn]:
    session = store.get(session_id)
    with session.lock:
        if session.conversation.ended:
            raise CallEndedError()
        try:
            started = time.perf_counter()
            turn = session.conversation.handle(
                text, language, lambda details, intent: _save_callback(db, session, details, intent), heard=heard,
                uncertain=uncertain)
            turn.timings = {"intent_ms": round((time.perf_counter() - started) * 1000), "handled_by": turn.handled_by}
        except ConversationEnded as exc:
            raise CallEndedError() from exc
        if session.conversation.ended:  # the caller said goodbye
            _finish(db, session)
    return session, turn


def end(db: Session, store: SessionStore, session_id: str) -> tuple[DemoSession, bool]:
    """End the call. Safe to repeat: the second and later calls change nothing. Returns (session, already_ended)."""
    session = store.get(session_id)
    with session.lock:
        already = session.call_log_id is not None
        _finish(db, session)
    return session, already


def _outcome(session: DemoSession) -> str | None:
    if session.outcome:
        return session.outcome
    if session.callback_ids:
        return CALL_CALLBACK_CREATED
    return CALL_FAQ_ANSWERED if session.conversation.answered else None


def _links(db: Session, session: DemoSession) -> list[dict]:
    links = [{"id": "dashboard", "label": "Dashboard", "href": "/"}]
    if session.call_log_id:
        links.append({"id": "calls", "label": "Call activity", "href": "/#call-activity"})
    if session.callback_ids:
        links.append({"id": "callbacks", "label": "Callback queue", "href": f"/#callback-{session.callback_ids[-1]}"})
        for details in session.conversation.session.callbacks[:1]:
            patient_id = notifications.patient_id_for_mobile(db, details.phone)
            if patient_id:
                links.append({"id": "timeline", "label": "Patient timeline", "href": f"/patients/{patient_id}/timeline"})
    else:
        links.append({"id": "callbacks", "label": "Callback queue", "href": "/#callback-tasks"})
    return links


log = logging.getLogger(__name__)

# Approved lines with no caller details in them: pre-generated at startup and kept, per language and voice.
FIXED_PHRASE_KEYS = (
    "greeting", "closed_now", "capabilities_transfer", "capabilities_callback", "recording_notice", "how_can_help",
    "one_moment", "low_confidence_retry", "anything_else", "confirm_question", "offer_short", "goodbye",
    "greeting_reply", "not_heard", "ask_name", "ask_phone", "ask_use_caller_number", "invalid_phone",
)
# Approved lines that may also be cached when first spoken (still without any caller details).
CACHEABLE_KEYS = tuple(key for key, versions in wording.LINES.items()
                       if not any("{" in text for text in versions.values()))


def _speech_language(language: str) -> str:
    return "hi" if language == "hinglish" else language  # Hinglish is spoken from the Hindi lines


def warm_up(app) -> None:
    """Background start-up work so the first call is quick: load the speech-to-text model and Piper voices,
    pre-generate fixed phrases, and load the language model. Loads only what is installed; downloads nothing."""
    try:
        for language in ("en", "hi"):
            lines = [wording.LINES[key][language] for key in CACHEABLE_KEYS]
            tts.allow_fixed_phrases(lines, language)
            tts.warm_fixed_phrases([wording.LINES[key][language] for key in FIXED_PHRASE_KEYS], language)
        if app.state.voice_agent_router is not None:
            app.state.voice_agent_router.warm_up()
        warm = getattr(app.state.transcriber, "warm_up", None)
        if warm is not None:  # a replacement speech-to-text adapter may not need warming
            warm()
    except Exception:  # noqa: BLE001 - warming is best effort
        log.exception("voice agent warm-up failed")


SOURCE_LABELS = {
    "approved_knowledge": "Approved knowledge",
    "callback_required": "Callback required",
    "safety_fallback": "Safety fallback",
    "emergency_escalation": "Emergency escalation",
}


def _lead(conversation: Conversation) -> dict | None:
    pending = conversation.pending
    if pending is None or not (pending.patient_type or pending.doctor or pending.time):
        return None
    return {
        "patient_type": wording.PATIENT_TYPES[pending.patient_type]["staff"] if pending.patient_type else None,
        "doctor": wording.DOCTOR_CHOICES[pending.doctor]["staff"] if pending.doctor else None,
        "time": pending.time,
    }


def _grouped(number: str) -> str:
    return f"{number[:5]} {number[5:]}"


def _caller(conversation: Conversation) -> dict:
    confirmed = conversation.session.callbacks
    if confirmed:
        number = confirmed[-1].phone
        return {"name": confirmed[-1].name, "phone": _grouped(number), "phone_status": "confirmed for callback"}
    caller_id = "present, not read out" if conversation.context.caller_number_available else "unknown"
    if conversation.phone == CALLER_NUMBER:
        phone, status = None, "calling number chosen, awaiting confirmation"
    elif conversation.phone:
        phone, status = _grouped(conversation.phone), "awaiting confirmation"
    else:
        phone, status = None, f"caller ID {caller_id}"
    return {"name": conversation.name, "phone": phone, "phone_status": status}


def snapshot(db: Session, session: DemoSession, turn: Turn | None = None) -> dict:
    """Everything the page shows: the reply, and what the clinic team sees."""
    conversation = session.conversation
    context = conversation.context
    language = conversation.language.value
    messages = [{"text": m.text, "speech_text": m.speech_text} for m in (turn.messages if turn else [])]
    pending = conversation.pending
    callback = None
    if turn and turn.callback_created:
        details = turn.callback_created
        callback = {
            "id": turn.callback_id,
            "reference": f"C-{turn.callback_id}",
            "category": details.category.value,
            "category_label": wording.STAFF_CATEGORY_LABELS[details.category],
            "urgent": details.urgent,
            "href": f"/#callback-{turn.callback_id}",
        }
    return {
        "session_id": session.id,
        "state": conversation.state.value,
        "state_label": STATE_LABELS[conversation.state],
        "language": language,
        "ended": conversation.ended,
        "input_enabled": not conversation.ended,
        "messages": messages,
        "speech": {
            "text": " ".join(m["speech_text"] for m in messages),
            "language": language,
            # Sentence by sentence, so the first can play while the rest is generated.
            "parts": [part for m in messages for part in tts.speech_parts(m["speech_text"])],
        } if messages else None,
        # This turn only: returned to the page, never stored.
        "timings": getattr(turn, "timings", None) if turn else None,
        "decision": {
            "path": turn.path if turn else None,
            "topic": turn.topic if turn else None,
            "category": pending.category.value if pending else None,
            "urgent": bool(pending and pending.urgent),
            "source": turn.source if turn else None,
            "source_label": SOURCE_LABELS.get(turn.source) if turn else None,
            "engine": turn.engine if turn else None,
            "engine_note": turn.engine_note if turn else None,
        },
        "lead": _lead(conversation),
        "detected_reason": conversation.reason or (pending.reason if pending else None),
        "caller": _caller(conversation),
        "callback_created": callback,
        "callbacks": [
            {"id": cid, "reference": f"C-{cid}", "href": f"/#callback-{cid}", "urgent": details.urgent,
             "category_label": wording.STAFF_CATEGORY_LABELS[details.category]}
            for cid, details in zip(session.callback_ids, conversation.session.callbacks)
        ],
        "transfer": conversation.transfer,
        "outcome": _outcome(session) or (CALL_ENDED if conversation.ended else None),
        "call_log_id": session.call_log_id,
        "links": _links(db, session),
        "context": {
            "now_ist": context.now_ist.strftime("%a %d %b %Y, %I:%M %p IST"),
            "clinic_open_now": context.clinic_open_now,
            "transfer_available": context.transfer_available,
            "caller_number_available": context.caller_number_available,
            "simulation": session.simulation,
        },
    }
