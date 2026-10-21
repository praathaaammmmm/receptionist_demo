"""Controlled language-model understanding for the voice agent.

The model reads the caller's words and returns a routing decision only: an intent from a fixed
list, up to two ids of approved answers, and any preferred doctor or time the caller mentioned.
It never writes what the agent says. The conversation turns the decision into approved wording,
so the model cannot invent facts, quote prices, promise schedules, claim bookings or give advice.

It also cannot act. Urgent symptoms, the 112 instruction, clinical refusals, phone validation,
callback confirmation, the one-callback rule, transfers and ending the call stay in policy.py
and conversation.py, which check every decision. Any error, timeout or invalid reply raises
LLMUnavailable and the caller's turn is handled by the rule-based policy instead.

Providers (VOICE_AGENT_LLM_PROVIDER): "ollama" (local, no key), "anthropic" (ANTHROPIC_API_KEY
or another credential the Anthropic SDK finds), or "none".
"""
import json
import time
from dataclasses import dataclass
from typing import Protocol

from .. import config
from . import knowledge_base
from .context import RuntimeContext

INTENTS = (
    "answer", "not_in_knowledge", "clinical", "treatment_suitability", "appointment_request", "reschedule_request",
    "cancellation_request", "booking_status", "appointment_availability", "doctor_schedule", "human_request",
    "callback_request", "panel", "insurance", "treatment_cost", "missed_call", "website_enquiry", "complaint",
    "patient_records", "greeting", "goodbye",
)
DOCTORS = ("raj_tiwary", "smriti_raj", "no_preference", "not_mentioned")
MAX_ANSWERS = 2
DEFAULT_MODELS = {"ollama": "qwen3:8b", "anthropic": "claude-opus-5-5"}

_PREAMBLE = """You route phone callers for Smriti Raj Dentistry, a dental clinic. Callers speak English, Hindi or
Hinglish. You never diagnose, advise, quote prices, promise times or book anything.

"""
_ROUTING = """ROUTING TASK FOR THIS DEMO
You do not speak to the caller directly here. For the caller's latest words, return one JSON routing decision.
The system then speaks only the approved wording for the answers you choose, and runs every safety rule and tool
itself, after the caller confirms. Never answer from your own knowledge.

Intents:
- answer: the caller asked something one or two approved answers below directly answer. Put their ids in answer_ids.
- not_in_knowledge: a question the approved answers do not cover. Never stretch an answer to fit.
- clinical: symptoms, pain, swelling, medicines, dosage, remedies, aftercare or recovery, results of an X-ray or test,
  whether something is serious, or which procedure they need. Never use "answer" for these.
- treatment_suitability: whether a treatment suits them or is safe for them.
- appointment_request: wants a new appointment. reschedule_request: already has an appointment and wants another
  day or time (for example "I can't make it, can we do Monday"). cancellation_request, booking_status ("is my
  appointment confirmed"), appointment_availability (free slots), doctor_schedule (when a doctor is in): staff handle
  all of these by callback.
- human_request: wants a person, reception or the doctor on the phone. callback_request: asks to be called back.
- panel: CGHS, ECHS, CISF, DU, Air India or any panel. insurance: insurance or claims. treatment_cost: price of treatment.
- missed_call, website_enquiry, complaint, patient_records: as named.
- greeting: only a greeting. goodbye: the caller is finished.
Also fill preferred_doctor (raj_tiwary, smriti_raj, no_preference or not_mentioned) and preferred_time (the caller's own
words for a day or time, or an empty string).
Two common mistakes to avoid:
- "What time do you open or close", "are you open on Saturday": that is answer with hours, not appointment_availability.
- Asking whether the clinic does or treats something, in any words ("crooked teeth" means braces and aligners, "kids"
  means children's dentistry): that is answer with the matching service id. treatment_suitability is only when they
  ask whether a treatment is right or safe for them personally.

Approved answers (id: what it answers):
"""


class LLMUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Decision:
    intent: str
    answer_ids: tuple[str, ...]
    preferred_doctor: str
    preferred_time: str
    caller_need: str
    provider: str
    model: str
    seconds: float


class Provider(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, user: str, schema: dict, timeout: float) -> dict: ...


def answer_ids() -> list[str]:
    return [item for item, _ in knowledge_base.catalogue()]


def decision_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": list(INTENTS)},
            "answer_ids": {"type": "array", "items": {"type": "string", "enum": answer_ids()}},
            "preferred_doctor": {"type": "string", "enum": list(DOCTORS)},
            "preferred_time": {"type": "string"},
        },
        "required": ["intent", "answer_ids", "preferred_doctor", "preferred_time"],
        "additionalProperties": False,
    }


_SYSTEM: str | None = None


def system_prompt(context: RuntimeContext | None = None) -> str:
    """The routing instructions and the approved-answer catalogue. Kept short and identical on every turn,
    so a local model can reuse its cached prompt. It needs no clinic facts or runtime context: the model only
    picks intents and answer ids, and the facts are spoken from approved wording (rendered by prompt.py)."""
    global _SYSTEM
    if _SYSTEM is None:
        items = "\n".join(f"- {item}: {summary}" for item, summary in knowledge_base.catalogue())
        _SYSTEM = _PREAMBLE + _ROUTING + items + "\n"
    return _SYSTEM


def validate(raw: dict, provider: str, model: str, seconds: float) -> Decision:
    """Accept only the fixed intents and known answer ids; anything else is unusable."""
    if not isinstance(raw, dict) or raw.get("intent") not in INTENTS:
        raise LLMUnavailable("The model returned no valid intent.")
    known = set(answer_ids())
    ids = tuple(dict.fromkeys(i for i in raw.get("answer_ids") or () if isinstance(i, str) and i in known))[:MAX_ANSWERS]
    intent = raw["intent"]
    if intent == "answer" and not ids:
        intent = "not_in_knowledge"
    doctor = raw.get("preferred_doctor") if raw.get("preferred_doctor") in DOCTORS else "not_mentioned"
    when = " ".join(str(raw.get("preferred_time") or "").split())[:80]
    need = " ".join(str(raw.get("caller_need") or "").split())[:200]
    return Decision(intent, ids if intent == "answer" else (), doctor, when, need, provider, model, round(seconds, 2))


class OllamaProvider:
    """A local model served by Ollama (http://127.0.0.1:11434), with JSON-schema constrained output."""

    name = "ollama"

    def __init__(self, model: str, url: str):
        self.model, self.url = model, url.rstrip("/")

    def complete_json(self, system: str, user: str, schema: dict, timeout: float) -> dict:
        import httpx

        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "think": False,
            "keep_alive": "2h",
            "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 160},
        }
        try:
            response = httpx.post(f"{self.url}/api/chat", json=body, timeout=timeout)
            response.raise_for_status()
            return json.loads(response.json()["message"]["content"])
        except Exception as exc:  # noqa: BLE001 - any failure means "use the rules"
            raise LLMUnavailable(f"Ollama: {type(exc).__name__}") from exc


class AnthropicProvider:
    """Claude through the official Anthropic SDK, with a JSON-schema structured output."""

    name = "anthropic"

    def __init__(self, model: str):
        self.model = model

    def complete_json(self, system: str, user: str, schema: dict, timeout: float) -> dict:
        try:
            import anthropic
        except ImportError as exc:
            raise LLMUnavailable("Anthropic SDK not installed") from exc
        try:
            client = anthropic.Anthropic(timeout=timeout, max_retries=0)
            response = client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable("Anthropic: connection failed") from exc
        except anthropic.APIStatusError as exc:
            raise LLMUnavailable(f"Anthropic: HTTP {exc.status_code}") from exc
        except anthropic.AnthropicError as exc:  # e.g. no credentials configured
            raise LLMUnavailable(f"Anthropic: {type(exc).__name__}") from exc
        if response.stop_reason != "end_turn":  # refusal, max_tokens, ...: never guess from a partial reply
            raise LLMUnavailable(f"Anthropic: stopped ({response.stop_reason})")
        text = next((block.text for block in response.content if block.type == "text"), "")
        try:
            return json.loads(text)
        except ValueError as exc:
            raise LLMUnavailable("Anthropic: invalid JSON") from exc


def provider_from_config() -> Provider | None:
    name = config.VOICE_AGENT_LLM_PROVIDER
    model = config.VOICE_AGENT_LLM_MODEL or DEFAULT_MODELS.get(name, "")
    if name == "ollama":
        return OllamaProvider(model, config.VOICE_AGENT_LLM_URL)
    if name == "anthropic":
        return AnthropicProvider(model)
    return None


class Router:
    """Turns caller words into a validated Decision, or raises LLMUnavailable."""

    def __init__(self, provider: Provider, timeout: float | None = None):
        self.provider = provider
        self.timeout = timeout or config.VOICE_AGENT_LLM_TIMEOUT_SECONDS

    def status(self) -> dict:
        return {"enabled": True, "provider": self.provider.name, "model": self.provider.model}

    def warm_up(self) -> None:
        """Load the model ahead of the caller's first question (Ollama keeps it loaded for 30 minutes)."""
        if self.provider.name != "ollama":
            return
        import threading

        def run():  # the real routing prompt, so the model's prompt cache is warm too
            try:
                self.provider.complete_json(system_prompt(), json.dumps({"caller_said": "hello", "selected_language": "en"}),
                                            decision_schema(), timeout=120)
            except LLMUnavailable:
                pass

        threading.Thread(target=run, daemon=True).start()

    def route(self, text: str, *, context: RuntimeContext, language: str, state: str, history: list[tuple[str, str]],
              heard: str | None = None, callback_created: bool = False) -> Decision:
        payload = {"caller_said": text, "selected_language": language}
        if heard and heard != text:
            payload["speech_recognised_as"] = heard
        if state != "listening":  # history matters only while details are being collected
            payload["recent_conversation"] = [f"{who}: {said}" for who, said in history[-4:]]
        user = json.dumps(payload, ensure_ascii=False)
        started = time.perf_counter()
        raw = self.provider.complete_json(system_prompt(context), user, decision_schema(), self.timeout)
        return validate(raw, self.provider.name, self.provider.model, time.perf_counter() - started)


def router_from_config() -> Router | None:
    provider = provider_from_config()
    return Router(provider) if provider else None
