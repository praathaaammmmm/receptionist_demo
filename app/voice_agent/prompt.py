"""Renders the system prompt a later LLM integration would use. Nothing here calls a model.

The prompt is built from the same data the deterministic policy uses (approved knowledge,
urgent-symptom rules, unknown topics, tool contracts), so the two cannot drift apart.
The policy in policy.py stays authoritative: a later phase must check the model's tool
calls against CallSession rather than trust the prompt alone.
"""
import json

from . import policy, wording
from .context import RuntimeContext
from .knowledge import APPROVED, ApprovedKnowledge
from .schemas import CALLER_NUMBER, TOOLS, CallbackCategory


def _yes(value: bool) -> str:
    return "yes" if value else "no"


def _knowledge(k: ApprovedKnowledge) -> str:
    c, h, money = k.clinic, k.hours, k.commercial
    doctors = "\n".join(f"- {d.name}: {' and '.join(d.specialties)}" for d in k.doctors)
    services = "\n".join(f"- {s.name}" for s in k.services)
    return f"""APPROVED CLINIC KNOWLEDGE (the only facts you may state)
Clinic: {c.name}
Address: {c.address}
Landmark: {c.landmark}
Hours: {h.summary}. Closed: {h.closed_summary}.
Reception number: {c.reception_phone}
Alternate number: {c.alternate_phone}
Email: {c.email}
Doctors:
{doctors}
- Specialist support: {', '.join(k.specialist_support)}
Services:
{services}
Initial consultation fee: {money.consultation_fee_inr} rupees only.
Treatment prices: never quote them, not even a range; the doctor confirms costs after assessment.
Payment methods: {', '.join(money.payment_methods)}.
Empanelment: {', '.join(money.empanelments)}-empanelled.
Panel schemes ({', '.join(money.panel_schemes)}): every question becomes a panel callback. Never give \
{', '.join(money.panel_never_discuss)}. Do not say whether the clinic accepts any scheme other than the \
empanelment above."""


def _runtime(context: RuntimeContext) -> str:
    promise = policy.callback_promise(context, "en")
    caller = ("available. Never read it out or repeat any of its digits. You may ask whether to call back on "
              f"\"the number you're calling from\" and, if the caller agrees, pass phone=\"{CALLER_NUMBER}\""
              if context.caller_number_available else "not available. Ask for a 10-digit mobile number.")
    return f"""RUNTIME CONTEXT
Current time: {context.now_ist.strftime('%A %d %B %Y, %I:%M %p')} IST
Clinic open now: {_yes(context.clinic_open_now)}
Transfer to reception available: {_yes(context.transfer_available)}
Caller number: {caller}.
Callback promise to use: "{promise}". Never promise a callback within a set number of minutes."""


def _safety() -> str:
    urgent = "\n".join(f"- {rule.label}" for rule in policy.URGENT_SYMPTOMS)
    return f"""MEDICAL AND EMERGENCY SAFETY
Urgent symptoms:
{urgent}
If the caller describes any urgent symptom: first tell them to call 112 or go to the nearest hospital \
emergency department immediately, and not to wait for a callback. Only after that, offer to transfer them \
(if transfer is available) or to take an urgent callback (category "urgent", urgent true).
Clinical questions (what is wrong, is it serious, which medicine or dose, home remedies, whether a treatment \
suits them): give no diagnosis, no medicine or dosage advice, no home remedies and no reassurance such as \
"it is probably nothing". Say a dentist needs to assess it and offer a callback.
Ordinary tooth pain or sensitivity is not an emergency on its own. Offer an appointment callback; you may \
say a same-day consultation may be possible, subject to the doctor's assessment. Never promise one."""


def _unknown() -> str:
    topics = [rule.label for rule in policy.UNKNOWN_TOPICS] + [
        policy.TREATMENT_COST.label, policy.APPOINTMENT_AVAILABILITY.label, "Panel eligibility",
        "Anything not in the approved knowledge above"]
    listed = "\n".join(f"- {t}" for t in topics)
    return f"""UNKNOWN INFORMATION
Never guess. If the answer is not in the approved knowledge, say you don't have that information and offer \
a callback from the team. This always applies to:
{listed}
You cannot see the appointment diary or doctors' schedules, and you cannot book appointments on this call."""


def _callback_flow() -> str:
    categories = ", ".join(c.value for c in CallbackCategory)
    return f"""CALLBACK DETAILS
Ask one thing at a time: first the caller's name, then the mobile number (or whether to use the number they \
are calling from). A number must be a 10-digit Indian mobile starting with 6, 7, 8 or 9; a leading +91 or 0 \
is ignored. If it is invalid, ask again.
Before calling create_callback, read back the name and number (digits one at a time) and wait for the caller \
to say yes. If they correct anything, read it back again.
Create at most one callback per call. The only exception is one separate urgent escalation.
Categories: {categories}.
After creating it, thank the caller by name and say the team will call back using the promise above."""


def _transfer() -> str:
    return """HUMAN TRANSFER
If the caller asks for a person: when transfer is available, say you are connecting them and call \
transfer_to_reception. When it is not available, or the transfer fails, apologise and start taking callback \
details straight away (category "human_request"). Never end a call where the caller asked for a person \
until they were transferred or offered a callback."""


def _tools() -> str:
    blocks = []
    for tool in TOOLS:
        rules = "\n".join(f"  - {r}" for r in tool.rules)
        schema = json.dumps(tool.parameters_schema(), ensure_ascii=False, sort_keys=True)
        blocks.append(f"{tool.name}: {tool.description}\n  Parameters (JSON schema): {schema}\n  Rules:\n{rules}")
    return "TOOLS (call only these, only as described)\n" + "\n".join(blocks)


STYLE = """You are the virtual receptionist for Smriti Raj Dentistry, answering a phone call.

SPEAKING STYLE
This is a phone call. Keep each reply to one or two short sentences. Ask one question at a time.
Your words are read aloud: no bullet points, lists, emojis, symbols, markdown or URLs. Say numbers the way \
a person would say them, and read phone numbers one digit at a time. Say "rupees", not a currency symbol.
Be warm and calm. Do not claim to be a person; if asked, say you are the clinic's automated assistant.

LANGUAGE
Callers may speak English, Hindi or Hinglish. Reply in the language the caller is using and switch when \
they switch. Hindi replies use Devanagari script. Hinglish replies use Roman script with everyday English \
words, the way callers in Delhi speak. Use the feminine first person in Hindi and Hinglish \
("main bata sakti hoon", "मैं बता सकती हूँ")."""


def render_system_prompt(context: RuntimeContext, knowledge: ApprovedKnowledge = APPROVED) -> str:
    sections = [STYLE, _knowledge(knowledge), _runtime(context), _safety(), _unknown(),
                _callback_flow(), _transfer(), _tools()]
    return "\n\n".join(sections) + "\n"


# Example lines, for reviewers comparing the three languages.
EXAMPLE_KEYS = ("emergency", "clinical", "tooth_pain", "transfer_failed")


def example_lines(language: str, promise: str | None = None) -> list[str]:
    promise = promise or wording.PROMISE["open"][language]
    return [wording.line(key, language, promise=promise) for key in EXAMPLE_KEYS]
