"""Re-words call-demo replies in the caller's chosen language: English, Hindi or Hinglish.

The assistant decides what to say exactly as it does in English (same rules, same
bookings and callbacks). This only swaps each approved message, button label and
input label for its version in app/knowledge_translations.py. Values the server
needs back (option values, conversation state) are never changed.

Every message also carries `speech_text`, the words the local voice reads aloud. English
and Hindi speak what the transcript shows. Hinglish shows Roman Hindi but speaks its
reviewed Devanagari version with the Hindi voice. Nothing is transliterated at run time.
"""
import copy
import re

from .. import knowledge_translations as wording

_WEEKDAY = re.compile(r"\b(" + "|".join(sorted(wording.HINDI_WEEKDAYS, key=len, reverse=True)) + r")\b")
_MONTH = re.compile(r"\b(\d{1,2}) (" + "|".join(wording.HINDI_MONTHS) + r")\b")


def normalize(language) -> str:
    return language if language in wording.LANGUAGE_CODES else wording.DEFAULT_LANGUAGE


def _hindi_dates(text: str) -> str:
    """Hindi weekday and month names; day numbers and times stay exactly as they are."""
    text = _WEEKDAY.sub(lambda m: wording.HINDI_WEEKDAYS[m.group(1)], text)
    return _MONTH.sub(lambda m: f"{m.group(1)} {wording.HINDI_MONTHS[m.group(2)]}", text)


def _value(name: str, value, language: str):
    if not isinstance(value, str):
        return value
    if name == "status" and value in wording.STATUS_WORDS:
        return wording.STATUS_WORDS[value][language]
    if name == "day":  # "Today" in an offered time
        value = localize_label(value, language)
    for written, said in wording.DATA_WORDS.get(language, {}).items():
        value = value.replace(written, said)
    return _hindi_dates(value) if language == "hi" else value


def _spoken_value(name: str, value, language: str):
    """A data value as the Hindi voice should hear it: Hindi dates and approved name pronunciations."""
    if not isinstance(value, str):
        return value
    if name == "status" and value in wording.STATUS_WORDS:
        return wording.STATUS_WORDS[value][f"{language}_speech"]
    value = _value(name, value, "hi")
    for written, said in wording.SPEECH_NAMES.items():
        value = value.replace(written, said)
    return value


def message(key: str, language: str, **params) -> dict:
    """One approved message in the given language."""
    return localize_message({"text": wording.MESSAGES[key]["en"].format(**params), "key": key, "params": params}, language)


def localize_message(msg: dict, language: str) -> dict:
    """The message in the language, with `text` for the transcript and `speech_text` for the voice."""
    msg = dict(msg)
    if language == "en":
        msg["speech_text"] = msg["text"]
        return msg
    english = msg.get("text")
    raw = msg.get("params") or {}
    versions = wording.MESSAGES.get(msg.get("key"))
    if versions is None and english in wording.SERVICE_MESSAGES:
        versions = wording.SERVICE_MESSAGES[english]
    if versions is None:  # no approved translation: shown and spoken as written
        msg["speech_text"] = english
        return msg
    msg["text"] = versions[language].format(**{n: _value(n, v, language) for n, v in raw.items()})
    spoken = versions["hinglish_speech" if language == "hinglish" else "hi"]
    msg["speech_text"] = spoken.format(**{n: _spoken_value(n, v, language) for n, v in raw.items()})
    return msg


def localize_label(label: str, language: str, params: dict | None = None) -> str:
    if language == "en" or not isinstance(label, str):
        return label
    if label in wording.LABELS:
        return wording.LABELS[label][language]
    if params and "service" in params:  # "Book for <service>"
        return wording.LABELS["Book for {service}"][language].format(service=params["service"])
    # Offered times look like "Today · 4:30 PM · Dr. Anika Rao": only the day part is worded.
    parts = [wording.LABELS[part][language] if part in wording.LABELS else part for part in label.split(" · ")]
    label = " · ".join(parts)
    return _hindi_dates(label) if language == "hi" else label


def localize_reply(reply: dict, language: str) -> dict:
    """The reply in the chosen language, with the offered times also read out as options 1, 2 and 3."""
    language = normalize(language)
    reply = copy.deepcopy(reply)
    messages = [localize_message(m, language) for m in reply.get("messages", [])]
    slots = [o for o in reply.get("options", []) if o.get("action") == "slot" and o.get("params")]
    for number, option in enumerate(slots, start=1):
        messages.append(message("slot_option", language, number=number, **option["params"]))
    reply["messages"] = messages
    for option in reply.get("options", []):
        option["label"] = localize_label(option["label"], language, option.get("params"))
    spec = reply.get("input")
    if isinstance(spec, dict):
        reply["input"] = {**spec, **{k: localize_label(spec[k], language) for k in ("label", "placeholder") if k in spec}}
    reply["language"] = language
    return reply
