"""Local text-to-speech for the call demo, using downloaded Piper voice packs.

Everything runs on this machine: no cloud service, no API key, and nothing is
recorded. Each demo language has its own voice pack (see the VOICE_* settings in
app/config.py): English uses a British English voice (Cori); Hindi and Hinglish use
the Hindi voice (Hinglish replies are spoken from their reviewed Devanagari speech
text). A pack is loaded only when it is first needed and then kept.

If a language's pack (or the piper package) is missing, `available(language)` is
False and that language runs as text only. Another language's voice is never
used in its place.
"""
import importlib.util
import io
import json
import re
import threading
import wave
from collections import OrderedDict
from pathlib import Path

from .. import config, knowledge_translations
from .errors import ClinicError, ValidationError

MAX_CHARS = 900
_CACHE_SIZE = 64
LANGUAGES = knowledge_translations.LANGUAGE_CODES

_lock = threading.Lock()
_voices: dict = {}  # model path -> loaded PiperVoice, filled on first use
_cache: OrderedDict = OrderedDict()


class VoiceUnavailableError(ClinicError):
    status_code = 503
    code = "voice_unavailable"
    default_message = knowledge_translations.VOICE_MISSING_MESSAGE


def _language(language: str | None) -> str:
    language = language or "en"
    if language not in LANGUAGES:
        raise ValidationError("That language is not available in the call demo.")
    return language


def voice_for(language: str | None = "en") -> tuple[str, str]:
    """(voice pack name, speaker) for a demo language. Hinglish is spoken by the Hindi voice."""
    if _language(language) in ("hi", "hinglish"):
        return config.VOICE_HINDI, config.VOICE_HINDI_SPEAKER
    return config.VOICE_ENGLISH, config.VOICE_ENGLISH_SPEAKER


def model_path(language: str | None = "en") -> Path:
    return config.VOICE_DIR / f"{voice_for(language)[0]}.onnx"


def pack_installed(language: str | None = "en") -> bool:
    """Both files of the language's voice pack are present."""
    path = model_path(language)
    return path.is_file() and path.with_name(path.name + ".json").is_file()


def available(language: str | None = "en") -> bool:
    return pack_installed(language) and importlib.util.find_spec("piper") is not None


def speaker_id(language: str | None = "en") -> int | None:
    """Numeric id of the configured speaker in a multi-speaker voice, or None for the default."""
    wanted = str(voice_for(language)[1] or "").strip()
    if not wanted:
        return None
    if wanted.isdigit():
        return int(wanted)
    path = model_path(language)
    try:
        speakers = json.loads(path.with_name(path.name + ".json").read_text())["speaker_id_map"]
    except (OSError, ValueError, KeyError):
        return None
    return speakers.get(wanted)


def status(language: str | None = "en") -> dict:
    """What the call demo tells the presenter about one language's voice."""
    language = _language(language)
    voice, speaker = voice_for(language)
    return {
        "language": language,
        "label": knowledge_translations.LANGUAGES[language]["voice_label"],
        "voice": voice,
        "speaker": speaker or None,
        "available": available(language),
        "installed": pack_installed(language),
    }


def prepare(text: str, language: str | None = "en") -> str:
    """Turn transcript text into something that reads naturally aloud."""
    language = _language(language)
    words = knowledge_translations.SPEECH_WORDS.get("hi" if language == "hinglish" else language, {})
    text = text.replace("•", ", ").replace("·", ", ").replace("—", ", ")
    for written, spoken in words.items():
        text = re.sub(rf"(?<![\w-]){re.escape(written)}(?![\w-])", spoken, text)
    text = re.sub(r"#(\d+)", rf"{words.get('number', 'number')} \1", text)
    text = re.sub(r"\(\s*\)", "", text)  # a status word the Hindi voice leaves unsaid
    # Read phone numbers digit by digit instead of as one enormous number.
    text = re.sub(r"\d{7,}", lambda m: " ".join(m.group()), text)
    text = re.sub(r"\s*\n+\s*", ". ", text)
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"([.:,।])\s*[.,]", r"\1", text).strip(" ,")


def _load(path: Path):
    """The Piper voice for this model file, loaded on first request only."""
    if path not in _voices:
        from piper import PiperVoice

        _voices[path] = PiperVoice.load(str(path))
    return _voices[path]


def synthesize(text: str, language: str | None = "en") -> bytes:
    """WAV audio for the text in the given language. Raises VoiceUnavailableError if its pack is missing."""
    language = _language(language)
    text = prepare(text or "", language)
    if not text:
        raise ValidationError("There is nothing to say.")
    if len(text) > MAX_CHARS:
        raise ValidationError("That is too long to read aloud.")
    if not available(language):
        raise VoiceUnavailableError()

    path = model_path(language)
    speaker = speaker_id(language)
    key = (str(path), speaker, text)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        try:
            voice = _load(path)
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav_file:
                if speaker is None:
                    voice.synthesize_wav(text, wav_file)
                else:
                    from piper import SynthesisConfig

                    voice.synthesize_wav(text, wav_file, syn_config=SynthesisConfig(speaker_id=speaker))
        except Exception as exc:  # a broken install must never take the demo down
            raise VoiceUnavailableError() from exc
        audio = buffer.getvalue()
        _cache[key] = audio
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
        return audio


# --- Voice agent demo: cancellable synthesis and a cache for approved fixed phrases only -------------
# The call demo keeps using synthesize() above. The voice agent uses synthesize_turn(): it checks for
# cancellation between Piper's audio chunks, keeps each voice loaded, and caches only approved fixed
# phrases (never anything containing a caller's name, number or words).

class SynthesisCancelled(Exception):
    pass


_load_lock = threading.Lock()
_model_locks: dict[str, threading.Lock] = {}
_fixed_allowed: set[tuple] = set()  # (model path, speaker, prepared text) of approved fixed phrases
_fixed_audio: dict[tuple, bytes] = {}
_SENTENCE = re.compile(r"(?<=[.?!।])\s+")


def speech_parts(text: str, min_chars: int = 24) -> list[str]:
    """A reply split into sentences, so the first can play while the next is generated.
    Very short sentences are joined to the next one."""
    parts, buffer = [], ""
    for sentence in _SENTENCE.split(" ".join((text or "").split())):
        buffer = f"{buffer} {sentence}".strip()
        if len(buffer) >= min_chars:
            parts.append(buffer)
            buffer = ""
    if buffer:
        if parts and len(buffer) < min_chars:
            parts[-1] = f"{parts[-1]} {buffer}"
        else:
            parts.append(buffer)
    return parts


def _key(text: str, language: str) -> tuple:
    return (str(model_path(language)), speaker_id(language), prepare(text, language))


def allow_fixed_phrases(texts: list[str], language: str) -> None:
    """Mark approved, caller-free phrases (split into the same parts the page requests) as cacheable."""
    for text in texts:
        for part in speech_parts(text):
            _fixed_allowed.add(_key(part, language))


def _loaded(path: Path):
    with _load_lock:
        voice = _load(path)
        lock = _model_locks.setdefault(str(path), threading.Lock())
    return voice, lock


def synthesize_turn(text: str, language: str | None = "en", cancel: threading.Event | None = None) -> tuple[bytes, bool]:
    """(WAV audio, served from the fixed-phrase cache) for one reply part. Raises SynthesisCancelled as soon
    as `cancel` is set between audio chunks, and VoiceUnavailableError if the language's pack is missing."""
    language = _language(language)
    spoken = prepare(text or "", language)
    if not spoken:
        raise ValidationError("There is nothing to say.")
    if len(spoken) > MAX_CHARS:
        raise ValidationError("That is too long to read aloud.")
    if not available(language):
        raise VoiceUnavailableError()
    key = _key(text, language)
    if key in _fixed_audio:
        return _fixed_audio[key], True
    path = model_path(language)
    speaker = speaker_id(language)
    try:
        voice, lock = _loaded(path)
        from piper import SynthesisConfig

        config_ = SynthesisConfig(speaker_id=speaker) if speaker is not None else None
        frames, params = [], None
        with lock:
            if cancel is not None and cancel.is_set():
                raise SynthesisCancelled()
            for chunk in voice.synthesize(spoken, syn_config=config_):
                if cancel is not None and cancel.is_set():
                    raise SynthesisCancelled()
                params = params or (chunk.sample_channels, chunk.sample_width, chunk.sample_rate)
                frames.append(chunk.audio_int16_bytes)
        if params is None:
            raise ValidationError("There is nothing to say.")
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(params[0])
            wav_file.setsampwidth(params[1])
            wav_file.setframerate(params[2])
            wav_file.writeframes(b"".join(frames))
    except (SynthesisCancelled, ValidationError):
        raise
    except Exception as exc:  # a broken install must never take the demo down
        raise VoiceUnavailableError() from exc
    audio = buffer.getvalue()
    if key in _fixed_allowed:
        _fixed_audio[key] = audio
    return audio, False


def warm_fixed_phrases(texts: list[str], language: str) -> int:
    """Load the language's voice and pre-generate the given approved phrases. Returns how many were made."""
    if not available(language):
        return 0
    allow_fixed_phrases(texts, language)
    made = 0
    for text in texts:
        for part in speech_parts(text):
            try:
                synthesize_turn(part, language)
                made += 1
            except (ClinicError, SynthesisCancelled):
                pass
    return made
