"""Patient-facing appointment concierge: a deterministic, tool-guided conversation.

No AI model is called. Each turn is classified with fixed rules, answered only
from app/knowledge.py and the clinic data in the database, and acted on through
the same patient, availability, appointment and callback services the reception
screens use.

The conversation state travels with the client and is treated as untrusted:
every value is re-validated by the underlying services before anything is saved.
Replies never include stored patient records, only what the visitor typed.
"""
import re
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .. import config, knowledge, utils
from .. import knowledge_translations as wording
from ..models import Doctor, Service, Slot
from . import appointments, availability, callbacks, clinic, patients, waitlist
from .errors import ClinicError, DuplicatePatientError, ValidationError

SOURCE = "AI_DEMO"
SLOTS_PER_OFFER = 3

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# --- Intent rules (checked in this order) ------------------------------------
_HUMAN = re.compile(
    r"\b(speak|talk|chat)\b.*\b(person|human|someone|somebody|staff|receptionist|doctor|dentist|team)\b"
    r"|\bcall ?back\b|\bcall me\b|\bring me\b|\bhuman\b|\breal person\b|\breceptionist\b"
    r"|\b(person|insaan|kisi) se baat\b|व्यक्ति से बात|इंसान से बात|किसी से बात",
    re.I,
)
_SCHEME = re.compile(r"\b(cghs|echs)\b", re.I)
# Anything that sounds like symptoms, medicines, suitability or outcomes is never answered.
_CLINICAL = re.compile(
    r"\b(pain\w*|aches?|aching|hurts?|hurting|sore|swell\w*|swollen|bleed\w*|infect\w*|pus|abscess|fever"
    r"|numb\w*|sensitiv\w*|medicines?|medication\w*|antibiotics?|painkillers?|tablets?|dos(e|age)"
    r"|diagnos\w*|symptoms?|cavity|cavities|decay\w*|broken|cracked|chipped|loose|wisdom|extract\w*"
    r"|surgery|an(a)?esth\w*|pregnan\w*|diabet\w*|allerg\w*|safe|safety|risks?|risky|side effects?"
    r"|recover\w*|heal\w*|cure\w*|emergenc\w*|urgent\w*|x-?rays?|suitable|candidate|success\w*"
    r"|guarantee\w*|permanent\w*|results?)\b"
    r"|\bshould i\b|\bdo i need\b|\bam i\b|\bis it normal\b|\bwhat causes\b|\bwhich treatment\b"
    r"|\bbest treatment\b|\bhow long\b|\bhow many\b|\bwill it\b|\bdoes it\b|\bcan i (eat|drink|smoke|take)\b"
    # The same safety rule for Hindi and Hinglish: pain, medicine, swelling, bleeding, fever.
    r"|\b(dard|dawa|dawai|dawaai|davai|sujan|soojan|khoon|bukhar)\b|दर्द|दवा|सूजन|खून|बुखार",
    re.I,
)
_BOOK = re.compile(
    r"\b(book\w*|appointments?|schedul\w*|reserv\w*|slots?|availab\w*|consultations?|visit)\b"
    r"|बुक|अपॉइंटमेंट|कंसल्टेशन",
    re.I,
)
_GREETING = re.compile(r"^\W*(hi|hello|hey|namaste|good (morning|afternoon|evening))\b|^\W*(नमस्ते|नमस्कार)", re.I)
_THANKS = re.compile(r"\b(thanks?|thank you|that'?s all|bye|goodbye|dhanyavaad|shukriya)\b|धन्यवाद|शुक्रिया", re.I)


# --- Reply helpers ------------------------------------------------------------
def _opt(label: str, action: str, value=None) -> dict:
    return {"label": label, "action": action, "value": value}


FREE_INPUT = {"type": "text", "label": "Your message", "placeholder": "Ask about hours, services or booking"}
_PERSON = _opt("Speak to a person", "intent", "human")
_BOOKING = _opt("Book a consultation", "intent", "book")
_RESTART = _opt("Start over", "reset")


def _t(key: str, tone: str | None = None, **params) -> dict:
    """One approved message by key. The text is English; the call demo can re-word it per language."""
    message = {"text": wording.MESSAGES[key]["en"].format(**params), "key": key, "params": params}
    if tone:
        message["tone"] = tone
    return message


def _reply(state: dict, messages, options=(), input: dict | None = None, **extra) -> dict:
    return {
        "messages": [m if isinstance(m, dict) else {"text": m} for m in messages],
        "options": list(options),
        "input": input or FREE_INPUT,
        "state": state,
        "booking": None,
        "callback": None,
        "waitlist": None,
        "answered": None,  # id of the approved answer given this turn, if any
        "mode": knowledge.ASSISTANT_MODE,
        **extra,
    }


def _clean_state(state) -> dict:
    if not isinstance(state, dict) or len(repr(state)) > 4000:
        state = {}
    data = state.get("data")
    flow = state.get("flow")
    step = state.get("step")
    return {
        "flow": flow if flow in ("booking", "callback") else None,
        "step": step if isinstance(step, str) else None,
        "data": dict(data) if isinstance(data, dict) else {},
    }


def _idle(data: dict) -> dict:
    """Back to open conversation, remembering only the contact details already given."""
    kept = {k: data[k] for k in ("name", "mobile", "email") if isinstance(data.get(k), str)}
    return {"flow": None, "step": None, "data": kept}


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _looks_like_name(text: str) -> bool:
    """Reject empty input, numbers and whole questions typed where a name is expected."""
    return (
        2 <= len(text) <= 120
        and len(text.split()) <= 6
        and re.search(r"[^\W\d_]", text) is not None
        and not re.search(r"[?\d@]", text)
    )


_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# Other ways callers name a weekday (Hindi and Hinglish).
_WEEKDAY_ALIASES = {6: ("रविवार", "इतवार", "ravivar", "raviwar", "itwar", "itvaar")}


def _closed_weekday_in(text: str) -> int | None:
    """The clinic-closed weekday the patient mentioned by name, if any."""
    for weekday in config.CLINIC_CLOSED_WEEKDAYS:
        name = _WEEKDAYS[weekday]
        if re.search(rf"\b{name}s?\b|\b{name[:3]}\b", text, re.I):
            return weekday
        if any(alias in text.lower() for alias in _WEEKDAY_ALIASES.get(weekday, ())):
            return weekday
    return None


def _explain_closed_day(db: Session, data: dict, weekday: int) -> list[dict]:
    """Say why the requested day is unavailable and point the search at the next open day.

    Never skips the closed day silently: the patient is always told the clinic is closed.
    """
    now = utils.now()
    closed_day = next(d for d in (now.date() + timedelta(days=i) for i in range(7)) if d.weekday() == weekday)
    name = clinic.get_clinic(db).name
    data.update(date=availability.next_open_day(closed_day).isoformat(), date_done=True, skip=0)
    found = _find_slots(db, data, now)
    if found:
        return [_t("closed_day_next", clinic=name, weekday=f"{closed_day:%A}", next_weekday=f"{found[0][0].start_time:%A}")]
    # The next open day is beyond the booking window, so be clear about what is being offered instead.
    data["date"] = None
    return [_t("closed_day", clinic=name, weekday=f"{closed_day:%A}"), _t("booking_window")]


def _pick_by_text(text: str, choices: list[tuple[str, object]]):
    """Match typed text against option labels; returns the value only if exactly one fits."""
    needle = text.strip().lower()
    if len(needle) < 2:
        return None
    hits = [value for label, value in choices if needle in label.lower() or label.lower() in needle]
    return hits[0] if len(hits) == 1 else None


# --- Entry point ---------------------------------------------------------------
def respond(db: Session, *, text: str = "", action: str | None = None, value=None, state=None) -> dict:
    state = _clean_state(state)
    text = " ".join((text or "").split())[:500]

    if action in ("start", "reset"):
        return _welcome(db)
    if action == "say":  # a suggested prompt behaves exactly like typing it
        text, action, value = " ".join(str(value or "").split())[:500], None, None
        state = _idle(state["data"])
    if action == "intent":
        state = _idle(state["data"])
        if isinstance(value, str) and value.startswith("book"):
            # "book" or "book:<service id>" when the patient was just asking about that service
            return _start_booking(db, state, db.get(Service, _as_int(value.partition(":")[2]) or 0))
        if value == "human":
            return _start_callback(db, state, "human")
        return _welcome(db)

    if state["flow"] == "booking":
        return _booking_turn(db, state, text, action, value)
    if state["flow"] == "callback":
        return _callback_turn(db, state, text, action, value)
    return _route(db, state, text)


def _welcome(db: Session) -> dict:
    name = clinic.get_clinic(db).name
    return _reply(
        _idle({}),
        [_t("welcome", clinic=name), _t("no_advice")],
        [_opt(prompt, "say", prompt) for prompt in knowledge.SUGGESTED_PROMPTS],
    )


def _route(db: Session, state: dict, text: str) -> dict:
    if not text:
        return _reply(state, [_t("how_can_i_help")], [_BOOKING, _PERSON])
    if _HUMAN.search(text):
        return _start_callback(db, state, "human")
    if _SCHEME.search(text):
        return _start_callback(db, state, "cghs", text)
    if _CLINICAL.search(text):
        return _start_callback(db, state, "clinical", text)

    service = _mentioned_service(db, text)
    closed_weekday = _closed_weekday_in(text)
    if closed_weekday is not None:
        if _BOOK.search(text):
            return _start_booking(db, state, service, closed_weekday)
        return _reply(state, _explain_closed_day(db, {}, closed_weekday), [_BOOKING, _PERSON], answered="closed_day")
    topic = _match_topic(text)
    if topic and topic["id"] == "fees":
        return _answer(db, state, topic)
    if _BOOK.search(text):
        return _start_booking(db, state, service)
    if service:
        return _reply(
            state,
            [_t("service_answer", service=service.name), _t("book_question")],
            [{**_opt(f"Book for {service.name}", "intent", f"book:{service.id}"), "params": {"service": service.name}}, _PERSON],
            answered="service",
        )
    if topic:
        return _answer(db, state, topic)
    if _GREETING.search(text):
        return _welcome(db)
    if _THANKS.search(text):
        return _reply(state, [_t("thanks")], [_BOOKING, _PERSON])
    return _start_callback(db, state, "unsupported", text)


# --- Approved answers ------------------------------------------------------------
def _match_topic(text: str) -> dict | None:
    for topic in knowledge.TOPICS:
        if any(re.search(pattern, text, re.I) for pattern in topic["patterns"]):
            return topic
    return None


def _mentioned_service(db: Session, text: str) -> Service | None:
    for service in appointments.list_services(db):
        patterns = knowledge.SERVICE_ALIASES.get(service.name, [re.escape(service.name)])
        if any(re.search(pattern, text, re.I) for pattern in patterns):
            return service
    return None


def _answer(db: Session, state: dict, topic: dict) -> dict:
    profile = clinic.get_clinic(db)
    services = appointments.list_services(db)
    params = {
        "clinic": profile.name,
        "address": profile.address,
        "phone": profile.phone,
        "email": profile.email or "not listed",
        "doctors": "\n".join(f"• {d.name}, {d.speciality}" for d in availability.list_doctors(db)),
        "services": "\n".join(f"• {s.name}" for s in services),
        "fees": "\n".join(f"• {s.name}: {profile.currency_symbol}{s.fee} (demo)" for s in services),
    }
    message = {"text": topic["answer"].format(**params), "key": f"topic_{topic['id']}", "params": params}
    return _reply(state, [message], [_BOOKING, _PERSON], answered=topic["id"])


# --- Booking flow ------------------------------------------------------------------
_BOOKING_STEPS = (
    ("patient_type", "patient_type"),
    ("name", "name"),
    ("mobile", "mobile"),
    ("email", "email_done"),
    ("service", "service_id"),
    ("doctor", "doctor_done"),
    ("date", "date_done"),
    ("slot", "slot_id"),
    ("confirm", "confirmed"),
)


def _start_booking(
    db: Session, state: dict, service: Service | None = None, closed_weekday: int | None = None
) -> dict:
    data = {k: v for k, v in state["data"].items() if k in ("name", "mobile", "email")}
    if "email" in data:
        data["email_done"] = True
    if service:
        data["service_id"] = service.id
    state = {"flow": "booking", "step": None, "data": data}
    prefix = _explain_closed_day(db, data, closed_weekday) if closed_weekday is not None else []
    return _advance(db, state, prefix + [_t("booking_guidance")])


def _advance(db: Session, state: dict, prefix=()) -> dict:
    data = state["data"]
    state["step"] = next(step for step, key in _BOOKING_STEPS if not data.get(key))
    return _booking_prompt(db, state, prefix)


def _open_days(today: date) -> list[date]:
    """Bookable days offered to patients: the slot window without clinic-closed days."""
    return [d for d in availability.window_days(today) if not availability.is_closed(d)]


def _day_label(day: date, today: date) -> str:
    return "Today" if day == today else utils.fmt_date(day)


def _booking_prompt(db: Session, state: dict, prefix=()) -> dict:
    step, data, messages = state["step"], state["data"], list(prefix)
    tail = [_PERSON, _RESTART]
    if step == "patient_type":
        messages.append(_t("ask_patient_type"))
        return _reply(
            state, messages, [_opt("New patient", "pick", "new"), _opt("Existing patient", "pick", "existing")] + tail
        )
    if step == "name":
        messages.append(_t("ask_name"))
        return _reply(
            state, messages, tail, {"type": "text", "label": "Full name", "placeholder": "Full name", "autocomplete": "name"}
        )
    if step == "mobile":
        messages.append(_t("ask_mobile"))
        return _reply(
            state, messages, tail, {"type": "tel", "label": "Mobile number", "placeholder": "Mobile number", "autocomplete": "tel"}
        )
    if step == "email":
        messages.append(_t("ask_email"))
        return _reply(
            state,
            messages,
            [_opt("Skip", "skip")] + tail,
            {"type": "email", "label": "Email (optional)", "placeholder": "Email (optional)", "autocomplete": "email"},
        )
    if step == "service":
        messages.append(_t("ask_service"))
        return _reply(state, messages, [_opt(s.name, "pick", s.id) for s in appointments.list_services(db)] + tail)
    if step == "doctor":
        messages.append(_t("ask_doctor"))
        options = [_opt("No preference", "pick", "any")]
        options += [_opt(f"{d.name}, {d.speciality}", "pick", d.id) for d in availability.list_doctors(db)]
        if data.get("no_slots"):
            options.append(_opt("Join waitlist", "waitlist"))
        return _reply(state, messages, options + tail)
    if step == "date":
        today = utils.now().date()
        messages.append(_t("ask_date"))
        options = [_opt("Earliest available", "pick", "earliest")]
        options += [_opt(_day_label(d, today), "pick", d.isoformat()) for d in _open_days(today)]
        return _reply(state, messages, options + tail)
    if step == "slot":
        return _offer_slots(db, state, messages)
    return _confirm_prompt(db, state, messages)


def _find_slots(db: Session, data: dict, now: datetime, ignore_date: bool = False) -> list[tuple[Slot, Doctor]]:
    """Available slots in time order, honouring the preferred doctor and earliest preferred day."""
    doctors = availability.list_doctors(db)
    preferred = _as_int(data.get("doctor_id"))
    if preferred:
        doctors = [d for d in doctors if d.id == preferred]
    days = availability.window_days(now.date())
    try:
        start = days[0] if ignore_date else date.fromisoformat(str(data.get("date") or ""))
    except ValueError:
        start = days[0]
    found = []
    for day in (d for d in days if d >= start and not availability.is_closed(d)):
        todays = [
            (view.slot, doctor)
            for doctor in doctors
            for view in availability.slots_for_day(db, doctor.id, day, now)
            if view.available
        ]
        found += sorted(todays, key=lambda pair: (pair[0].start_time, pair[1].id))
    return found


def _offer_slots(db: Session, state: dict, messages: list) -> dict:
    data, now = state["data"], utils.now()
    found = _find_slots(db, data, now)
    if not found and data.get("date"):
        found = _find_slots(db, data, now, ignore_date=True)
        if found:
            messages.append(_t("slots_from_later"))
    if not found:
        # Remember who they wanted, so the waitlist request can carry it.
        data["waitlist_doctor_id"] = data.get("doctor_id")
        data["no_slots"] = True
        data.pop("doctor_done", None)
        data.pop("doctor_id", None)
        state["step"] = "doctor"
        messages.append(_t("no_slots"))
        return _booking_prompt(db, state, messages)
    data.pop("no_slots", None)
    data["waitlist_doctor_id"] = data.get("doctor_id")

    skip = _as_int(data.get("skip")) or 0
    if skip >= len(found):
        skip = 0
        messages.append(_t("slots_wrapped"))
    data["skip"] = skip
    offered = found[skip : skip + SLOTS_PER_OFFER]
    today = now.date()
    messages.append(_t("slots_three" if len(offered) == SLOTS_PER_OFFER else "slots_some"))
    options = []
    for slot, doctor in offered:
        day, time = _day_label(slot.start_time.date(), today), utils.fmt_time(slot.start_time)
        option = _opt(f"{day} · {time} · {doctor.name}", "slot", slot.id)
        option["params"] = {"day": day, "time": time, "doctor": doctor.name}
        options.append(option)
    if len(found) > SLOTS_PER_OFFER:
        options.append(_opt("Show other times", "more"))
    options.append(_opt("Change day", "change_date"))
    options.append(_opt("Join waitlist", "waitlist"))  # for when none of the offered times suit
    return _reply(state, messages, options + [_PERSON, _RESTART])


def _confirm_prompt(db: Session, state: dict, messages: list) -> dict:
    data = state["data"]
    slot = db.get(Slot, _as_int(data.get("slot_id")) or 0)
    service = db.get(Service, _as_int(data.get("service_id")) or 0)
    if slot is None or service is None:
        data.pop("slot_id", None)
        if service is None:
            data.pop("service_id", None)
        return _advance(db, state, messages + [_t("choose")])
    messages.append(
        _t(
            "confirm_details",
            name=str(data.get("name")),
            mobile=str(data.get("mobile")),
            service=service.name,
            doctor=slot.doctor.name,
            date=utils.fmt_date(slot.start_time),
            time=utils.fmt_time(slot.start_time),
            minutes=slot.duration_minutes,
        )
    )
    return _reply(
        state,
        messages,
        [_opt("Confirm booking", "confirm"), _opt("Choose another time", "change_time"), _PERSON, _RESTART],
    )


def _booking_turn(db: Session, state: dict, text: str, action, value) -> dict:
    data, step = state["data"], state["step"]

    def retry(message) -> dict:
        return _booking_prompt(db, state, [message])

    # No suitable time: the patient can ask to be put on the waitlist instead of booking.
    if action == "waitlist" and step in ("slot", "doctor") and data.get("name") and data.get("mobile") and data.get("service_id"):
        state["step"] = "waitlist_time"
        return _waitlist_prompt(state)
    if step == "waitlist_time":
        choice = value if action == "pick" else _pick_by_text(text, [("morning", "MORNING"), ("afternoon", "AFTERNOON"), ("any time", "ANY")])
        if choice not in ("MORNING", "AFTERNOON", "ANY"):
            return _waitlist_prompt(state, [_t("choose")])
        return _join_waitlist(db, state, choice)

    if step == "patient_type":
        choice = value if action == "pick" else _pick_by_text(text, [("new patient", "new"), ("existing patient", "existing")])
        if choice not in ("new", "existing"):
            return retry(_t("choose"))
        data["patient_type"] = choice
    elif step == "name":
        if not _looks_like_name(text):
            return retry(_t("enter_full_name"))
        data["name"] = text
    elif step == "mobile":
        try:
            data["mobile"] = patients.normalize_mobile(text)
        except ValidationError as exc:
            return retry(exc.message)
    elif step == "email":
        if action == "skip" or text.lower() in ("", "skip", "no", "none", "no thanks"):
            data["email"] = ""
        elif _EMAIL_RE.match(text) and len(text) <= 120:
            data["email"] = text
        else:
            return retry(_t("bad_email"))
        data["email_done"] = True
    elif step == "service":
        services = appointments.list_services(db)
        chosen = value if action == "pick" else _pick_by_text(text, [(s.name, s.id) for s in services])
        if _as_int(chosen) not in [s.id for s in services]:
            return retry(_t("choose"))
        data["service_id"] = _as_int(chosen)
    elif step == "doctor":
        doctors = availability.list_doctors(db)
        chosen = value if action == "pick" else _pick_by_text(
            text, [("no preference", "any"), ("any doctor", "any")] + [(d.name, d.id) for d in doctors]
        )
        if chosen == "any":
            data["doctor_id"] = None
        elif _as_int(chosen) in [d.id for d in doctors]:
            data["doctor_id"] = _as_int(chosen)
        else:
            return retry(_t("choose"))
        data["doctor_done"] = True
    elif step == "date":
        today = utils.now().date()
        days = _open_days(today)
        closed_weekday = _requested_closed_weekday(text, action, value)
        if closed_weekday is not None:
            return _advance(db, state, _explain_closed_day(db, data, closed_weekday))
        chosen = value if action == "pick" else _pick_by_text(
            text, [("earliest available", "earliest")] + [(_day_label(d, today), d.isoformat()) for d in days]
        )
        if chosen == "earliest":
            data["date"] = None
        elif chosen in [d.isoformat() for d in days]:
            data["date"] = chosen
        else:
            return retry(_t("choose"))
        data["date_done"] = True
        data["skip"] = 0
    elif step == "slot":
        if action == "more":
            data["skip"] = (_as_int(data.get("skip")) or 0) + SLOTS_PER_OFFER
            return _booking_prompt(db, state)
        if action == "change_date":
            data.pop("date_done", None)
            return _advance(db, state)
        closed_weekday = _requested_closed_weekday(text, action, value)
        if closed_weekday is not None:
            return _booking_prompt(db, state, _explain_closed_day(db, data, closed_weekday))
        if action != "slot" or db.get(Slot, _as_int(value) or 0) is None:
            return retry(_t("choose_time"))
        data["slot_id"] = _as_int(value)
    elif step == "confirm":
        if action == "change_time":
            data.pop("slot_id", None)
            return _advance(db, state)
        if action != "confirm":
            return retry(_t("choose"))
        return _book(db, state)
    return _advance(db, state)


def _waitlist_prompt(state: dict, prefix=()) -> dict:
    messages = list(prefix) + [_t("waitlist_offer")]
    options = [_opt("Morning", "pick", "MORNING"), _opt("Afternoon", "pick", "AFTERNOON"), _opt("Any time", "pick", "ANY")]
    return _reply(state, messages, options + [_PERSON, _RESTART])


def _join_waitlist(db: Session, state: dict, time_preference: str) -> dict:
    """Record a waitlist request. Nothing is booked, reserved or promised."""
    data = state["data"]
    today = utils.now().date()
    days = availability.window_days(today)
    try:
        first = date.fromisoformat(str(data.get("date") or ""))
    except ValueError:
        first = today
    try:
        name = str(data.get("name") or "")
        mobile = patients.normalize_mobile(str(data.get("mobile") or ""))
        patient = patients.find_by_mobile(db, mobile)
        if patient is None:
            try:
                patient = patients.create_patient(db, name=name, mobile=mobile, email=data.get("email") or None)
            except DuplicatePatientError as exc:
                patient = exc.patient
        entry = waitlist.create_entry(
            db,
            patient_id=patient.id,
            service_id=_as_int(data.get("service_id")) or 0,
            doctor_id=_as_int(data.get("waitlist_doctor_id")),
            date_from=max(first, today),
            date_to=days[-1],
            time_preference=time_preference,
            contact_preference="PHONE",
            note="Joined through the appointment assistant.",
            source=SOURCE,
        )
    except ClinicError as exc:
        state["step"] = "slot"
        return _booking_prompt(db, state, [{"text": exc.message, "tone": "notice"}])
    return _reply(
        _idle(data),
        [_t("waitlist_joined", "success", name=name), _t("waitlist_details", reference=entry.id)],
        [_BOOKING, _PERSON],
        waitlist={"reference": f"W-{entry.id}", "status": entry.status},
    )


def _requested_closed_weekday(text: str, action, value) -> int | None:
    """A closed day asked for by name, or sent as a date by an out-of-date page."""
    if action == "pick":
        try:
            day = date.fromisoformat(str(value))
        except ValueError:
            return None
        return day.weekday() if availability.is_closed(day) else None
    return _closed_weekday_in(text) if action is None else None


def _book(db: Session, state: dict) -> dict:
    data = state["data"]
    try:
        name = str(data.get("name") or "")
        mobile = patients.normalize_mobile(str(data.get("mobile") or ""))
        # Attach to the existing record for this mobile number, or register a new patient.
        patient = patients.find_by_mobile(db, mobile)
        if patient is None:
            try:
                patient = patients.create_patient(db, name=name, mobile=mobile, email=data.get("email") or None)
            except DuplicatePatientError as exc:
                patient = exc.patient
        note = "Booked through the appointment assistant"
        note += " as a new patient." if data.get("patient_type") == "new" else " as an existing patient."
        if patient.name.strip().lower() != name.strip().lower():
            note += f" Name given: {name}."
        appointment = appointments.create_appointment(
            db,
            patient_id=patient.id,
            slot_id=_as_int(data.get("slot_id")) or 0,
            service_id=_as_int(data.get("service_id")) or 0,
            reason=note,
            source=SOURCE,
        )
    except ClinicError as exc:
        # Slot just taken (or no longer valid): same friendly message staff see, then fresh options.
        data.pop("slot_id", None)
        data["skip"] = 0
        state["step"] = "slot"
        return _offer_slots(db, state, [{"text": exc.message, "tone": "notice"}])

    booking = {
        "reference": appointment.id,
        "service": appointment.service.name,
        "doctor": appointment.doctor.name,
        "date": utils.fmt_date(appointment.start_time),
        "time": utils.fmt_time(appointment.start_time),
        "duration_minutes": int((appointment.end_time - appointment.start_time).total_seconds() // 60),
        "status": appointment.status,
    }
    return _reply(
        _idle(data),
        [
            _t("booking_saved", "success", name=name),
            _t("booking_status", status=appointment.status, reference=appointment.id),
        ],
        [_PERSON, _opt("Ask something else", "reset")],
        booking=booking,
    )


# --- Callback flow -----------------------------------------------------------------
def _start_callback(db: Session, state: dict, category: str, question: str = "") -> dict:
    data = state["data"]
    data["cb"] = {"category": category, "question": question[:300]}
    state["flow"] = "callback"
    intro = _t(f"callback_{category}")
    if category == "cghs":
        state["step"] = "scheme"
        return _callback_prompt(state, [intro], ask=False)
    if data.get("name") and data.get("mobile"):
        return _create_callback(db, state, [intro])
    state["step"] = "name"
    return _callback_prompt(state, [intro])


def _callback_prompt(state: dict, prefix=(), ask: bool = True) -> dict:
    step, messages = state["step"], list(prefix)
    tail = [_opt("No thanks", "reset")]
    if step == "scheme":
        if ask:
            messages.append(_t("ask_scheme"))
        return _reply(
            state, messages, [_opt("CGHS", "pick", "CGHS"), _opt("ECHS", "pick", "ECHS"), _opt("Not sure", "pick", "Not sure")] + tail
        )
    if step == "name":
        messages.append(_t("ask_callback_name"))
        return _reply(state, messages, tail, {"type": "text", "label": "Name", "placeholder": "Name", "autocomplete": "name"})
    messages.append(_t("ask_callback_mobile"))
    return _reply(
        state, messages, tail, {"type": "tel", "label": "Mobile number", "placeholder": "Mobile number", "autocomplete": "tel"}
    )


def _callback_turn(db: Session, state: dict, text: str, action, value) -> dict:
    data, step = state["data"], state["step"]
    request = data.get("cb") if isinstance(data.get("cb"), dict) else {"category": "human", "question": ""}
    data["cb"] = request

    if step == "scheme":
        choice = value if action == "pick" else _pick_by_text(text, [("cghs", "CGHS"), ("echs", "ECHS"), ("not sure", "Not sure")])
        if choice not in ("CGHS", "ECHS", "Not sure"):
            return _callback_prompt(state, [_t("choose")])
        request["scheme"] = choice
        state["step"] = "name"
    elif step == "name":
        if not _looks_like_name(text):
            return _callback_prompt(state, [_t("enter_name")])
        data["name"] = text
        state["step"] = "mobile"
    else:
        try:
            data["mobile"] = patients.normalize_mobile(text)
        except ValidationError as exc:
            return _callback_prompt(state, [exc.message])

    if not data.get("name"):
        state["step"] = "name"
        return _callback_prompt(state)
    if not data.get("mobile"):
        state["step"] = "mobile"
        return _callback_prompt(state)
    return _create_callback(db, state)


def _callback_reason(request: dict) -> str:
    category, question = request.get("category"), str(request.get("question") or "")
    if category == "cghs":
        scheme = request.get("scheme") or "Not sure"
        reason = f"CGHS/ECHS enquiry. Scheme: {scheme}. Eligibility has not been confirmed."
        return reason + (f' Patient asked: "{question}"' if question else "")
    if category == "clinical":
        return f'Clinical question the assistant did not answer: "{question}"'
    if category == "unsupported":
        return f'Question the assistant could not answer: "{question}"'
    return "Asked to speak to a person."


def _create_callback(db: Session, state: dict, prefix=()) -> dict:
    data = state["data"]
    request = data.get("cb") if isinstance(data.get("cb"), dict) else {}
    try:
        task = callbacks.create_callback(
            db,
            name=str(data.get("name") or ""),
            mobile=str(data.get("mobile") or ""),
            email=data.get("email") or None,
            reason=_callback_reason(request),
            source=SOURCE,
        )
    except ClinicError as exc:
        data.pop("name", None)
        data.pop("mobile", None)
        state["step"] = "name"
        return _callback_prompt(state, list(prefix) + [exc.message])

    messages = list(prefix)
    messages.append(_t("callback_saved", "success", name=task.name))
    messages.append(_t("callback_reference", reference=task.id))
    return _reply(
        _idle(data),
        messages,
        [_BOOKING, _opt("Ask something else", "reset")],
        callback={"reference": f"C-{task.id}", "status": task.status, "mobile": task.mobile},
    )
