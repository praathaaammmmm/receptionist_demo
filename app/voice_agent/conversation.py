"""A complete voice-agent conversation built on the Phase 1 policy.

Every decision is checked by policy.py (safety paths, transfer and callback rules via
CallSession) and every spoken line comes from wording.py or knowledge_base.py. This module
keeps track of where the call is: listening, offering a callback, or collecting name, number,
reason and (for appointments) visit preferences.

Understanding a free-form question may use an optional language-model router (llm.py). It runs
only after the deterministic safety rules: urgent symptoms, clinical questions, ordinary tooth
pain and treatment suitability are always decided by policy.py. The router can only choose an
intent and approved answer ids; if it fails, the rule-based policy handles the turn.

No database, telephony or booking here. Creating a callback calls the `save_callback` function
the caller of `handle()` passes in (the demo uses the existing callback service).

Hinglish is shown in Roman script and spoken by the Hindi voice from the Hindi version of the
same approved line, so each message carries `text` (shown) and `speech_text` (spoken).
"""
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from . import knowledge_base, policy, wording
from .context import RuntimeContext
from .phone import InvalidPhone, normalize_indian_mobile
from .schemas import (
    CALLER_NUMBER,
    CallbackCategory,
    CallbackDetails,
    CreateCallbackArgs,
    Language,
    NextAction,
    PolicyPath,
    PolicyResponse,
)

MAX_TEXT = 500
MAX_TURNS = 80


class State(StrEnum):
    LISTENING = "listening"
    OFFER_CALLBACK = "offer_callback"
    OFFER_TRANSFER = "offer_transfer"
    CAPTURE_NAME = "capture_name"
    CAPTURE_PHONE_CHOICE = "capture_phone_choice"  # use the number they are calling from?
    CAPTURE_PHONE = "capture_phone"
    CAPTURE_REASON = "capture_reason"
    CAPTURE_PATIENT_TYPE = "capture_patient_type"
    CAPTURE_DOCTOR = "capture_doctor"
    CAPTURE_TIME = "capture_time"
    CONFIRM = "confirm_details"
    ENDED = "ended"


STATE_LABELS = {
    State.LISTENING: "Listening for the caller's request",
    State.OFFER_CALLBACK: "Offered a callback, waiting for yes or no",
    State.OFFER_TRANSFER: "Offered a transfer to reception",
    State.CAPTURE_NAME: "Collecting callback details: name",
    State.CAPTURE_PHONE_CHOICE: "Collecting callback details: confirm calling number",
    State.CAPTURE_PHONE: "Collecting callback details: mobile number",
    State.CAPTURE_REASON: "Collecting callback details: reason",
    State.CAPTURE_PATIENT_TYPE: "Collecting visit details: new or existing patient",
    State.CAPTURE_DOCTOR: "Collecting visit details: preferred doctor",
    State.CAPTURE_TIME: "Collecting visit details: preferred day and time",
    State.CONFIRM: "Reading back details for confirmation",
    State.ENDED: "Call ended",
}

# Appointment enquiries also collect new/existing patient, preferred doctor and preferred time.
LEAD_TOPICS = {"appointment_request", "appointment_availability", "doctor_schedule", "how_to_book", "tooth_pain"}
# Topics whose reason is asked with a specific question rather than taken from the caller's first words.
REASON_PROMPTS = {
    "appointment_request": "ask_reason_appointment", "how_to_book": "ask_reason_appointment",
    "reschedule_request": "ask_reason_reschedule", "cancellation_request": "ask_reason_cancel",
    "booking_status": "ask_reason_status", "human_request": "ask_reason", "callback_request": "ask_reason",
}

# A line to say: rendered in any language from the same approved wording.
Say = Callable[[str], str]


@dataclass
class Message:
    text: str
    speech_text: str


@dataclass
class Pending:
    """The callback being offered or collected."""

    category: CallbackCategory
    urgent: bool = False
    reason: str | None = None
    topic: str | None = None
    patient_type: str | None = None
    doctor: str | None = None
    time: str | None = None


@dataclass
class Turn:
    messages: list[Message] = field(default_factory=list)
    path: str | None = None
    topic: str | None = None
    source: str | None = None  # approved_knowledge, callback_required, safety_fallback, emergency_escalation
    engine: str = "rules"  # "llm" when a language model understood the caller
    engine_note: str | None = None
    handled_by: str = "rule"  # "rule", "llm", or "fallback" (rules after the language model failed)
    timings: dict | None = None  # this turn only, for the page's timing panel; never stored
    transfer: dict | None = None
    callback_created: CallbackDetails | None = None
    callback_id: int | None = None


class ConversationEnded(Exception):
    pass


_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_DIGIT_WORDS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                "six": "6", "seven": "7", "eight": "8", "nine": "9"}
_NAME_LEADS = re.compile(
    r"^(?:(?:my|the) name is|name is|this is|i am|i'm|it's|it is|mera naam|naam|main|मेरा नाम|नाम|मैं)\s+", re.I)
_NAME_TAILS = re.compile(r"\s+(?:hai|hoon|hu|here|speaking|है|हूँ|हूं)$", re.I)
_NEW = re.compile(r"\b(?:new|first|never|not (?:been|visited)|pehli|pahli|naya|nayi|nahi aaya|nahin aaya)\b|पहली|नया|नई|कभी नहीं", re.I)
_EXISTING = re.compile(r"\b(?:existing|before|old|already|visited|been there|pehle|purana|purani|aa chuka|aa chuki|yes|haan)\b"
                       r"|पहले|पुराना|पुरानी|आ चुक|हाँ|हां", re.I)
_NO_PREFERENCE = re.compile(r"\b(?:no preference|any|anyone|either|doesn'?t matter|koi bhi|kisi se bhi|no)\b|कोई भी|किसी से भी", re.I)


def extract_phone(text: str) -> str:
    """Digits as said or typed: Devanagari digits and English digit words become digits."""
    text = text.translate(_DEVANAGARI_DIGITS).lower()
    text = re.sub(r"\b(" + "|".join(_DIGIT_WORDS) + r")\b", lambda m: _DIGIT_WORDS[m.group(1)], text)
    return re.sub(r"[^\d+]", "", text)


def extract_name(text: str) -> str | None:
    name = " ".join(text.strip().strip(".।!?,").split())
    for _ in range(2):
        name = _NAME_LEADS.sub("", name).strip()
        name = _NAME_TAILS.sub("", name).strip()
    if not name or len(name) > 60 or re.search(r"\d", name) or not re.search(r"\w", name):
        return None
    if len(name.split()) > 5:  # a sentence, not a name
        return None
    return " ".join(w[:1].upper() + w[1:] if w.isascii() else w for w in name.split())


def parse_patient_type(text: str) -> str:
    if _NEW.search(text):
        return "new"
    return "existing" if _EXISTING.search(text) else "unknown"


def parse_doctor(text: str, allow_no_preference: bool = True) -> str | None:
    """A named doctor, "no_preference", or None when the words name neither."""
    text = policy.matching_text(text)
    if re.search(r"smriti|स्मृति", text, re.I):
        return "smriti_raj"
    if re.search(r"\braj\b|tiwar|तिवारी|राज", text, re.I):
        return "raj_tiwary"
    if allow_no_preference and _NO_PREFERENCE.search(text):
        return "no_preference"
    return None


def _clean(text: str, limit: int = 300) -> str:
    return " ".join(text.split())[:limit].strip(" .।")


class Conversation:
    def __init__(self, context: RuntimeContext, language: Language | str = Language.EN, router=None):
        self.context = context
        self.language = Language(language)
        self.session = policy.CallSession(context)
        self.router = router  # llm.Router or None
        self.state = State.LISTENING
        self.pending: Pending | None = None
        self.name: str | None = None
        self.phone: str | None = None  # 10 digits, or CALLER_NUMBER
        self.reason: str | None = None
        self.turns = 0
        self.answered = False  # at least one approved fact was given
        self.asked_anything_else = False
        self.transfer: dict | None = None
        self.last_path: str | None = None
        self.last_topic: str | None = None
        self.last_source: str | None = None
        self.history: list[tuple[str, str]] = []  # ("caller" or "agent", words), for the router's context

    # --- Rendering --------------------------------------------------------------------------

    def _say(self, turn: Turn, *lines: Say) -> None:
        for say in lines:
            text = say(self.language)
            # Hinglish is spoken by the Hindi voice, from the Hindi version of the same approved line.
            speech = say(Language.HI) if self.language == Language.HINGLISH else text
            turn.messages.append(Message(text, speech))

    @staticmethod
    def _line(key: str, **params) -> Say:
        return lambda lang: wording.line(key, lang, **params)

    def _line_with_promise(self, key: str) -> Say:
        return lambda lang: wording.line(key, lang, promise=policy.callback_promise(self.context, lang))

    # --- Opening and closing ------------------------------------------------------------------

    def start(self) -> Turn:
        turn = Turn(path="greeting", source=policy.SOURCE_APPROVED)
        lines = [self._line("greeting")]
        if not self.context.clinic_open_now:
            lines.append(self._line("closed_now"))
        lines.append(self._line("capabilities_transfer" if self.context.transfer_available else "capabilities_callback"))
        lines += [self._line("recording_notice"), self._line("how_can_help")]
        self._say(turn, *lines)
        self.history.append(("agent", " ".join(m.text for m in turn.messages)))
        return turn

    def end(self) -> None:
        """The caller hung up or pressed End. Always allowed; the call log records what happened."""
        self.state = State.ENDED

    @property
    def ended(self) -> bool:
        return self.state == State.ENDED

    def _close(self, turn: Turn) -> None:
        decision = self.session.can_end_call()
        if not decision.allowed:  # asked for a person and has not been transferred or offered a callback
            self._offer(Pending(CallbackCategory.HUMAN_REQUEST, topic="human_request"))
            self._say(turn, self._line_with_promise("end_offer_callback"))
            self.session.callback_offered = True
            turn.source = policy.SOURCE_CALLBACK
            return
        self._say(turn, self._line("goodbye"))
        self.state = State.ENDED

    # --- Turns ----------------------------------------------------------------------------------

    def handle(self, text: str, language: Language | str | None,
               save_callback: Callable[[CallbackDetails, str | None], int], heard: str | None = None,
               uncertain: bool = False) -> Turn:
        """One caller turn. `text` is what the caller confirmed (typed, or a transcript they may have edited);
        `heard` is the original transcript, passed to the router for context only. `uncertain` speech (a
        low-confidence transcript the caller has not reviewed) is never acted on: no model, no state change."""
        if self.ended:
            raise ConversationEnded("This call has ended.")
        if language:
            self.language = Language(language)
        text = " ".join((text or "").split())[:MAX_TEXT]
        turn = Turn()
        if uncertain:
            turn.path, turn.source, turn.engine_note = "low_confidence", policy.SOURCE_SAFETY, \
                "Low-confidence speech: not acted on until the caller confirms or repeats it"
            self._say(turn, self._line("low_confidence_retry"))
            return turn
        self.turns += 1
        if self.turns > MAX_TURNS:
            self._say(turn, self._line("goodbye"))
            self.state = State.ENDED
            return turn
        if not text:
            self._say(turn, self._line("not_heard"))
            return turn
        self.history.append(("caller", text))

        handler = {
            State.LISTENING: self._listening,
            State.OFFER_CALLBACK: self._offer_callback,
            State.OFFER_TRANSFER: self._offer_transfer,
            State.CAPTURE_NAME: self._capture_name,
            State.CAPTURE_PHONE_CHOICE: self._capture_phone_choice,
            State.CAPTURE_PHONE: self._capture_phone,
            State.CAPTURE_REASON: self._capture_reason,
            State.CAPTURE_PATIENT_TYPE: self._capture_patient_type,
            State.CAPTURE_DOCTOR: self._capture_doctor,
            State.CAPTURE_TIME: self._capture_time,
            State.CONFIRM: self._confirm,
        }[self.state]
        self._heard = heard
        handler(text, turn, save_callback)
        turn.path = turn.path or self.last_path
        turn.topic = turn.topic or self.last_topic
        if turn.source is None:  # collecting details for a callback
            turn.source = policy.SOURCE_CALLBACK if self.state != State.LISTENING or turn.callback_created else self.last_source
        self.last_source = turn.source
        self.history.append(("agent", " ".join(m.text for m in turn.messages)))
        return turn

    def _understand(self, text: str, turn: Turn):
        """(response renderer, decision) for a free-form question. Safety rules first, then the router, then rules."""
        rules = lambda lang: policy.respond(text, self.context, lang)  # noqa: E731
        found = policy.classify(text)
        safety = found.path in (PolicyPath.EMERGENCY, PolicyPath.CLINICAL, PolicyPath.TOOTH_PAIN) \
            or found.topic == "treatment_suitability"
        if safety:
            turn.engine_note = "Safety rule (never sent to a language model)"
            return rules, None
        # Explicit requests the rules recognise for certain (a person, a panel, reschedule, cancel, booking
        # status and similar) are routed deterministically; the model handles everything else.
        if found.path in (PolicyPath.HUMAN_REQUEST, PolicyPath.PANEL) or found.topic in policy.EXPLICIT_INTENTS:
            turn.engine_note = "Rule-based policy (explicit request)"
            return rules, None
        # A clear rule match answers at once; the model is asked only when the rules cannot place the words.
        if found.topic not in policy.UNMATCHED_TOPICS:
            turn.engine_note = "Rule-based policy (clear match)"
            return rules, None
        if self.router is None:
            turn.engine_note = "Rule-based policy (no language model configured)"
            return rules, None
        from .llm import LLMUnavailable

        try:
            decision = self.router.route(
                text, context=self.context, language=self.language.value, state=self.state.value,
                history=self.history[:-1], heard=getattr(self, "_heard", None),
                callback_created=bool(self.session.callbacks))
        except LLMUnavailable as exc:
            turn.engine_note = f"Rule-based policy (language model unavailable: {exc})"
            turn.handled_by = "fallback"
            return rules, None
        turn.engine = turn.handled_by = "llm"
        turn.engine_note = f"Understood by {decision.provider} {decision.model} in {decision.seconds:.1f}s; " \
                           f"reply from approved wording"
        return (lambda lang: self._from_decision(decision, text, lang)), decision

    def _from_decision(self, decision, text: str, language: str) -> PolicyResponse:
        """The approved response for a router decision. Never the model's own words."""
        intent = decision.intent
        if intent == "answer":
            responses = []
            for answer in decision.answer_ids:
                if answer in knowledge_base.SERVICE_ANSWER_IDS:
                    responses.append(policy.approved_answer("services", language, (knowledge_base.SERVICE_ANSWER_IDS[answer],)))
                else:
                    responses.append(policy.approved_answer(answer, language))
            offer = next((r for r in responses if r.next_action == NextAction.OFFER_CALLBACK), None)
            return PolicyResponse(
                path=PolicyPath.ANSWER, language=Language(language), text=" ".join(r.text for r in responses),
                next_action=offer.next_action if offer else NextAction.CONTINUE,
                callback_category=offer.callback_category if offer else None,
                topic="+".join(decision.answer_ids), matched_rules=decision.answer_ids)
        if intent == "clinical":
            return policy.clinical_response(language)
        if intent == "panel":
            return policy.panel_response(language, text)
        if intent == "human_request":
            return policy.human_request_response(self.context, language)
        if intent == "callback_request":
            return PolicyResponse(path=PolicyPath.CALLBACK_REQUEST, language=Language(language),
                                  text=wording.line("callback_request", language),
                                  next_action=NextAction.CAPTURE_CALLBACK, topic="callback_request",
                                  callback_category=CallbackCategory.OTHER)
        if intent == "not_in_knowledge":
            return policy.unknown_information("not_approved", language)
        return policy.unknown_information(intent, language)  # every other intent is a callback topic

    def _listening(self, text: str, turn: Turn, save_callback) -> None:
        if policy.is_goodbye(text) or (self.asked_anything_else and policy.is_no(text) and len(text.split()) <= 4):
            self.asked_anything_else = False
            turn.path, turn.source = "closing", policy.SOURCE_APPROVED
            return self._close(turn)
        if policy.is_greeting(text):
            turn.path, turn.source = "greeting", policy.SOURCE_APPROVED
            return self._say(turn, self._line("greeting_reply"))
        self.asked_anything_else = False
        render, decision = self._understand(text, turn)
        if decision is not None and decision.intent == "goodbye":
            turn.path, turn.source = "closing", policy.SOURCE_APPROVED
            return self._close(turn)
        if decision is not None and decision.intent == "greeting":
            turn.path, turn.source = "greeting", policy.SOURCE_APPROVED
            return self._say(turn, self._line("greeting_reply"))
        response = self.session.note(render(self.language))
        turn.path, turn.topic = response.path.value, response.topic
        turn.source = policy.response_source(response.path)
        self.last_path, self.last_topic = turn.path, turn.topic
        rerender = lambda lang: render(lang).text  # noqa: E731
        preferences = self._preferences_from(text, decision)

        if response.path == PolicyPath.ANSWER:
            self.answered = True
            if response.next_action == NextAction.OFFER_CALLBACK:  # e.g. how to book, directions
                self._say(turn, rerender)
                self._offer(Pending(response.callback_category, topic=response.topic, **preferences))
            else:
                self._say(turn, rerender, self._line("anything_else"))
                self.asked_anything_else = True
        elif response.path == PolicyPath.EMERGENCY:
            self._say(turn, rerender)
            self._offer(Pending(CallbackCategory.URGENT, urgent=True, reason=text, topic=response.topic))
            if response.next_action == NextAction.TRANSFER:
                self.state = State.OFFER_TRANSFER
        elif response.path == PolicyPath.HUMAN_REQUEST:
            self.pending = Pending(CallbackCategory.HUMAN_REQUEST, topic="human_request")
            if response.next_action == NextAction.TRANSFER:
                self._attempt_transfer(turn, urgent=False)
            else:
                self._say(turn, rerender)
                self.transfer = turn.transfer = {"attempted": False, "result": "unavailable", "simulated": True}
                self._begin_capture(turn, ask=False)
        elif response.path == PolicyPath.CALLBACK_REQUEST:
            self.pending = Pending(CallbackCategory.OTHER, topic="callback_request")
            self._say(turn, rerender)
            self._begin_capture(turn, ask=False)
        else:  # unknown information, panel, clinical or ordinary tooth pain: offer a callback
            topic = response.topic
            reason = text
            named = [s for s in policy.matched_services(text) if s != "checkup"]  # "a consultation" is not a reason
            if topic in REASON_PROMPTS and not (topic == "appointment_request" and named):
                reason = None  # asked with a specific question
            self._say(turn, rerender)
            self._offer(Pending(response.callback_category, reason=reason, topic=topic, **preferences))

    @staticmethod
    def _preferences_from(text: str, decision) -> dict:
        """A doctor or time the caller already named, so the agent does not ask again."""
        doctor = parse_doctor(text, allow_no_preference=False)
        when = None
        if decision is not None:
            if decision.preferred_doctor in ("raj_tiwary", "smriti_raj"):
                doctor = decision.preferred_doctor
            when = decision.preferred_time or None
        return {"doctor": doctor, "time": when}

    def _offer(self, pending: Pending) -> None:
        self.pending = pending
        self.state = State.OFFER_CALLBACK

    def _attempt_transfer(self, turn: Turn, urgent: bool) -> None:
        """No reception line exists in this prototype, so every transfer is simulated as unanswered."""
        self._say(turn, self._line("transfer"))
        failed = self.session.transfer_result(False, self.language, urgent=urgent)
        self.transfer = turn.transfer = {"attempted": True, "result": "failed", "simulated": True}
        self._say(turn, lambda lang: policy.transfer_failed_response(self.context, lang, urgent).text)
        self.state = State.CAPTURE_NAME
        turn.path = turn.path or failed.path.value

    def _begin_capture(self, turn: Turn, ask: bool = True) -> None:
        if self._already_has_callback():
            self._say(turn, self._line_with_promise("callback_already"), self._line("anything_else"))
            self.pending, self.state, self.asked_anything_else = None, State.LISTENING, True
            return
        self.session.callback_offered = True
        if ask:
            self._say(turn, self._line("ask_name"))
        self.state = State.CAPTURE_NAME

    def _already_has_callback(self) -> bool:
        if not self.session.callbacks:
            return False
        urgent_escalation = (self.pending and self.pending.urgent and len(self.session.callbacks) == 1
                             and not self.session.callbacks[0].urgent)
        return not urgent_escalation

    def _offer_callback(self, text: str, turn: Turn, save_callback) -> None:
        if policy.is_no(text):
            self.pending, self.state = None, State.LISTENING
            self._say(turn, self._line("callback_declined"), self._line("anything_else"))
            self.asked_anything_else = True
        elif policy.is_yes(text):
            self._begin_capture(turn)
        else:  # a new question instead of an answer
            self.state = State.LISTENING
            self._listening(text, turn, save_callback)

    def _offer_transfer(self, text: str, turn: Turn, save_callback) -> None:
        if policy.is_yes(text):
            self._attempt_transfer(turn, urgent=True)
        elif policy.is_no(text):
            self.state = State.OFFER_CALLBACK
            self._say(turn, self._line_with_promise("emergency_callback"))
        else:
            self.state = State.LISTENING
            self._listening(text, turn, save_callback)

    # --- Callback details ---------------------------------------------------------------------

    def _capture_name(self, text: str, turn: Turn, save_callback) -> None:
        name = extract_name(text)
        if not name:
            return self._say(turn, self._line("ask_name_again"))
        self.name = name
        if self.context.caller_number_available:
            self.state = State.CAPTURE_PHONE_CHOICE
            self._say(turn, self._line("ask_use_caller_number"))
        else:
            self.state = State.CAPTURE_PHONE
            self._say(turn, self._line("ask_phone"))

    def _capture_phone_choice(self, text: str, turn: Turn, save_callback) -> None:
        if len(re.sub(r"\D", "", extract_phone(text))) >= 6:  # they said a number instead
            return self._capture_phone(text, turn, save_callback)
        if policy.is_yes(text):
            self.phone = CALLER_NUMBER
            return self._after_phone(turn)
        self.state = State.CAPTURE_PHONE
        self._say(turn, self._line("ask_phone"))

    def _capture_phone(self, text: str, turn: Turn, save_callback) -> None:
        try:
            self.phone = normalize_indian_mobile(extract_phone(text))
        except InvalidPhone:
            self.state = State.CAPTURE_PHONE
            return self._say(turn, self._line("invalid_phone"))
        self._after_phone(turn)

    def _after_phone(self, turn: Turn) -> None:
        pending = self.pending
        self.reason = pending.reason if pending and pending.reason else None
        if not self.reason:
            self.state = State.CAPTURE_REASON
            ask = REASON_PROMPTS.get(pending.topic if pending else None)
            if not ask:
                ask = "ask_reason_appointment" if pending and pending.category == CallbackCategory.APPOINTMENT else "ask_reason"
            return self._say(turn, self._line(ask))
        self._next_lead_question(turn)

    def _capture_reason(self, text: str, turn: Turn, save_callback) -> None:
        self.reason = _clean(text)
        self._next_lead_question(turn)

    def _wants_lead_details(self) -> bool:
        return bool(self.pending and self.pending.topic in LEAD_TOPICS)

    def _next_lead_question(self, turn: Turn) -> None:
        """Appointment enquiries: new or existing, preferred doctor, preferred time; skip anything already known."""
        pending = self.pending
        if self._wants_lead_details():
            if pending.patient_type is None:
                self.state = State.CAPTURE_PATIENT_TYPE
                return self._say(turn, self._line("ask_patient_type"))
            if pending.doctor is None:
                self.state = State.CAPTURE_DOCTOR
                return self._say(turn, self._line("ask_doctor"))
            if pending.time is None:
                self.state = State.CAPTURE_TIME
                return self._say(turn, self._line("ask_time"))
        self._read_back(turn)

    def _capture_patient_type(self, text: str, turn: Turn, save_callback) -> None:
        self.pending.patient_type = parse_patient_type(text)
        self._next_lead_question(turn)

    def _capture_doctor(self, text: str, turn: Turn, save_callback) -> None:
        self.pending.doctor = parse_doctor(text) or "no_preference"
        self._next_lead_question(turn)

    def _capture_time(self, text: str, turn: Turn, save_callback) -> None:
        self.pending.time = _clean(text, 80) or "any time"
        self._next_lead_question(turn)

    def _preferences_line(self, language: str) -> str | None:
        pending = self.pending
        if not self._wants_lead_details():
            return None
        return wording.line(
            "confirm_preferences", language,
            patient_type=wording.PATIENT_TYPES[pending.patient_type or "unknown"][language],
            doctor=wording.DOCTOR_CHOICES[pending.doctor or "no_preference"][language],
            time=pending.time or "-",
        )

    def _staff_notes(self) -> str:
        notes = [f"Caller language: {wording.LANGUAGE_NAMES[self.language]}."]
        pending = self.pending
        if self._wants_lead_details():
            notes += [
                f"{wording.PATIENT_TYPES[pending.patient_type or 'unknown']['staff']}.",
                f"Preferred doctor: {wording.DOCTOR_CHOICES[pending.doctor or 'no_preference']['staff']}.",
                f"Preferred day/time: {pending.time or 'not given'}.",
                "Wants a consultation: yes.",
            ]
        if self.phone == CALLER_NUMBER:
            notes.append("Callback number: the number the caller called from.")
        return " ".join(notes)

    def _read_back(self, turn: Turn) -> None:
        self.state = State.CONFIRM
        name, phone, reason = self.name, self.phone, self.reason
        self._say(turn, lambda lang: policy.confirm_details_line(name, phone, lang, reason, self._preferences_line(lang)))

    def _confirm(self, text: str, turn: Turn, save_callback) -> None:
        if policy.is_no(text):
            self.name = self.phone = None
            if self.pending:
                self.pending.patient_type = self.pending.doctor = self.pending.time = None
            self.state = State.CAPTURE_NAME
            return self._say(turn, self._line("details_retry"))
        if not policy.is_yes(text):
            return self._say(turn, self._line("confirm_yes_no"))
        pending = self.pending or Pending(CallbackCategory.OTHER)
        args = CreateCallbackArgs(
            name=self.name, phone=self.phone, language=self.language, reason=self.reason or pending.topic or "Callback",
            category=pending.category, urgent=pending.urgent, notes=self._staff_notes(),
        )
        try:
            details = self.session.create_callback(args, confirmed=True)
        except policy.CallbackRefused:
            self.state, self.pending = State.LISTENING, None
            self._say(turn, self._line_with_promise("callback_already"), self._line("anything_else"))
            self.asked_anything_else = True
            return
        try:
            turn.callback_id = save_callback(details, pending.topic)
        except Exception:
            self.session.callbacks.remove(details)  # not saved: the caller may try again
            return self._say(turn, self._line("callback_not_saved"))
        turn.callback_created = details
        self.state, self.pending, self.asked_anything_else = State.LISTENING, None, True
        self._say(turn, lambda lang: wording.line("callback_created", lang, name=details.name,
                                                  promise=policy.callback_promise(self.context, lang)),
                  self._line("anything_else"))
