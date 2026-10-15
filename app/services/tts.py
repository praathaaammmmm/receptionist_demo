"""Optional local text-to-speech for the call demo, using a downloaded Piper voice.

Everything runs on this machine: no cloud service, no API key, and nothing is
recorded. If the piper package or the voice file is missing, `available()` is
False and the call demo uses the browser's own voice or text simulation mode.
"""
import importlib.util
import io
import json
import re
import threading
import wave
from collections import OrderedDict
from pathlib import Path

from .. import config
from .errors import ClinicError, ValidationError

MAX_CHARS = 900
_CACHE_SIZE = 64

_lock = threading.Lock()
_loaded: dict = {"path": None, "voice": None}
_cache: OrderedDict = OrderedDict()


class VoiceUnavailableError(ClinicError):
    status_code = 503
    code = "voice_unavailable"
    default_message = "The demo voice is not installed, so replies are shown as text only."


def model_path() -> Path:
    return config.VOICE_DIR / f"{config.VOICE_NAME}.onnx"


def available() -> bool:
    path = model_path()
    return (
        path.is_file()
        and path.with_name(path.name + ".json").is_file()
        and importlib.util.find_spec("piper") is not None
    )


def speaker_id() -> int | None:
    """Numeric id of the configured speaker in a multi-speaker voice, or None for the default."""
    wanted = str(config.VOICE_SPEAKER or "").strip()
    if not wanted:
        return None
    if wanted.isdigit():
        return int(wanted)
    try:
        speakers = json.loads(model_path().with_name(model_path().name + ".json").read_text())["speaker_id_map"]
    except (OSError, ValueError, KeyError):
        return None
    return speakers.get(wanted)


def prepare(text: str) -> str:
    """Turn transcript text into something that reads naturally aloud."""
    text = text.replace("•", ", ").replace("·", ", ").replace("—", ", ")
    text = re.sub(r"#(\d+)", r"number \1", text)
    # Read phone numbers digit by digit instead of as one enormous number.
    text = re.sub(r"\d{7,}", lambda m: " ".join(m.group()), text)
    text = re.sub(r"\s*\n+\s*", ". ", text)
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"([.:,])\s*[.,]", r"\1", text).strip(" ,")


def synthesize(text: str) -> bytes:
    """WAV audio for the given text. Raises VoiceUnavailableError if no voice is installed."""
    text = prepare(text or "")
    if not text:
        raise ValidationError("There is nothing to say.")
    if len(text) > MAX_CHARS:
        raise ValidationError("That is too long to read aloud.")
    if not available():
        raise VoiceUnavailableError()

    path = model_path()
    speaker = speaker_id()
    key = (str(path), speaker, text)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        try:
            if _loaded["path"] != path:
                from piper import PiperVoice

                _loaded.update(path=path, voice=PiperVoice.load(str(path)))
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wav_file:
                if speaker is None:
                    _loaded["voice"].synthesize_wav(text, wav_file)
                else:
                    from piper import SynthesisConfig

                    _loaded["voice"].synthesize_wav(text, wav_file, syn_config=SynthesisConfig(speaker_id=speaker))
        except Exception as exc:  # a broken install must never take the demo down
            raise VoiceUnavailableError() from exc
        audio = buffer.getvalue()
        _cache[key] = audio
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
        return audio
