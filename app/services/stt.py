"""Speech-to-text for the voice agent demo, behind a small adapter.

The page records one phrase with the browser's MediaRecorder and posts the audio here. The
default adapter, LocalWhisper, transcribes it on this machine with faster-whisper. Audio is
decoded from memory, transcribed and dropped: it is never written to a file, a log or the
database, and nothing is sent to any other service.

Anything with the SpeechToText shape (status() and transcribe()) can replace LocalWhisper,
for example a production or Pipecat speech provider, without touching the page or the
conversation. The app keeps one instance in app.state.transcriber.

The model is loaded on the first transcription, never at startup, and never downloaded by the
app (see scripts/download_stt_model.py). Without it the page offers typed input only.
"""
import importlib.util
import io
import logging
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .. import config
from .errors import ClinicError, ValidationError

log = logging.getLogger(__name__)
LANGUAGES = ("en", "hi", "hinglish")
SAMPLE_RATE = 16000
MIN_BYTES = 200

# Approved proper nouns and clinic terms, given to Whisper as a spelling hint (never used to rewrite
# what was said). Hindi gets the same terms in Devanagari so the transcript stays in Devanagari.
CLINIC_VOCABULARY = (
    "Smriti Raj Dentistry", "Dwarka", "Dr Raj Tiwary", "Dr Smriti Raj", "appointment", "callback", "consultation",
    "root canal", "implant", "braces", "aligners", "CGHS", "reception", "periodontist", "orthodontist",
)
CLINIC_VOCABULARY_HI = (
    "स्मृति राज डेंटिस्ट्री", "द्वारका", "डॉक्टर राज तिवारी", "डॉक्टर स्मृति राज", "अपॉइंटमेंट", "कॉलबैक", "कंसल्टेशन",
    "रूट कैनाल", "इम्प्लांट", "ब्रेसेस", "अलाइनर", "सीजीएचएस", "रिसेप्शन", "पेरियोडॉन्टिस्ट", "ऑर्थोडॉन्टिस्ट",
)
_PROMPTS = {
    "en": "Calling " + ", ".join(CLINIC_VOCABULARY) + ".",
    "hi": "नमस्ते, मुझे अपॉइंटमेंट चाहिए। क्या रविवार को क्लिनिक खुला है? " + ", ".join(CLINIC_VOCABULARY_HI) + "।",
    "hinglish": "Haan ji, mujhe appointment chahiye. Sunday ko clinic khula hai kya? Mujhe reception se callback "
                "chahiye. Consultation fee kitni hai? " + ", ".join(CLINIC_VOCABULARY) + ".",
}
# Decoding settings for one short conversational phrase.
_DECODE = dict(
    temperature=0.0,  # one pass: no slow re-decoding at higher temperatures
    without_timestamps=True,
    condition_on_previous_text=False,
    vad_filter=True,  # trims leading and trailing silence
    vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 200},
    max_new_tokens=128,
)
# Whisper language code per demo language. There is no separate Hinglish model: Hinglish uses the same
# multilingual model in English mode, so mixed Hindi-English speech comes back in Roman script, guided by
# the Roman Hinglish hint above. The selected conversation language stays Hinglish whatever the script.
_WHISPER_LANGUAGE = {"en": "en", "hi": "hi", "hinglish": "en"}
MODES = {
    "en": "English",
    "hi": "Hindi (Devanagari)",
    "hinglish": "Hinglish: the same multilingual model in English mode with a Roman-Hinglish spelling hint "
                "(there is no separate Hinglish model)",
}
LOW_CONFIDENCE_MESSAGE = "I may not have caught that clearly. Please say that again, or type your message."
# Below these, a transcript is flagged as uncertain (it is still shown, and can be edited or retried).
MIN_AVG_LOGPROB = -0.9
MAX_NO_SPEECH = 0.6
MAX_COMPRESSION = 2.4


class SpeechUnavailableError(ClinicError):
    status_code = 503
    code = "stt_unavailable"
    default_message = "Microphone transcription is not available on this demo server. Please type instead."


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str
    audio_seconds: float
    processing_seconds: float
    model: str
    device: str
    confidence: float = 1.0  # 0 to 1, from Whisper's average token log-probability
    low_confidence: bool = False
    detected_language: str | None = None  # the language Whisper decoded in (set by the caller's choice)
    script: str | None = None  # "latin", "devanagari", "mixed" or None: what the transcript is written in
    timings: dict | None = None  # milliseconds for this request only; never stored


def script_of(text: str) -> str | None:
    devanagari = sum(1 for ch in text if "\u0900" <= ch <= "\u097f")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    if not devanagari and not latin:
        return None
    if devanagari and latin:
        return "mixed"
    return "devanagari" if devanagari else "latin"


class SpeechToText(Protocol):
    def status(self) -> dict: ...

    def transcribe(self, audio: bytes, language: str, content_type: str | None = None) -> Transcript: ...


def model_dir(name: str | None = None) -> Path:
    return config.VOICE_AGENT_STT_DIR / (name or config.VOICE_AGENT_STT_MODEL)


def model_installed(name: str | None = None) -> bool:
    folder = model_dir(name)
    return (folder / "model.bin").is_file() and (folder / "config.json").is_file()


def package_installed() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def _preload_cuda_libraries() -> None:
    """Make pip-installed NVIDIA runtime libraries (nvidia-cublas-cu12, nvidia-cudnn-cu12) visible to
    CTranslate2. Harmless when they are absent or already on the system library path."""
    import ctypes

    spec = importlib.util.find_spec("nvidia")
    for root in (spec.submodule_search_locations or []) if spec else []:
        for pattern in ("cublas/lib/libcublasLt.so.*", "cublas/lib/libcublas.so.*", "cudnn/lib/libcudnn*.so.*"):
            for library in sorted(Path(root).glob(pattern)):
                try:
                    ctypes.CDLL(str(library), mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass


def decode(audio: bytes):
    """Any browser recording (WebM/Opus, Ogg, WAV, MP4) as 16 kHz mono float32, decoded in memory."""
    import av
    import numpy as np

    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    chunks = []
    with av.open(io.BytesIO(audio), mode="r") as container:
        for frame in container.decode(audio=0):
            frame.pts = None
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):  # flush
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        raise ValueError("no audio")
    return np.concatenate(chunks).astype(np.float32) / 32768.0


class LocalWhisper:
    """faster-whisper on this machine. Thread-safe; one transcription at a time."""

    def __init__(self, name: str | None = None):
        self.name = name or config.VOICE_AGENT_STT_MODEL
        self._model = None
        self._device = None
        self._lock = threading.Lock()
        self._failed: set[str] = set()  # devices that could not run the model

    def status(self) -> dict:
        installed, package = model_installed(self.name), package_installed()
        return {
            "available": installed and package,
            "engine": "faster-whisper",
            "model": self.name,
            "installed": installed,
            "package": package,
            "loaded": self._model is not None,
            "device": self._device,
            "runs": "on this demo server",
            "modes": MODES,
        }

    def _load(self, device: str):
        from faster_whisper import WhisperModel

        if device == "cuda":
            _preload_cuda_libraries()
        compute = config.VOICE_AGENT_STT_COMPUTE_TYPE or ("float16" if device == "cuda" else "int8")
        model = WhisperModel(str(model_dir(self.name)), device=device, compute_type=compute)
        self._model, self._device = model, device
        return model

    def _devices(self) -> list[str]:
        wanted = config.VOICE_AGENT_STT_DEVICE
        if wanted in ("cpu", "cuda"):
            return [wanted]
        try:
            import ctranslate2

            return ["cuda", "cpu"] if ctranslate2.get_cuda_device_count() > 0 else ["cpu"]
        except Exception:  # noqa: BLE001 - any CUDA probing problem means CPU
            return ["cpu"]

    def warm_up(self) -> bool:
        """Load the model and run it once, so the caller's first phrase is not slow. Never downloads."""
        if not self.status()["available"]:
            return False
        import numpy as np

        quiet = (np.random.default_rng(0).standard_normal(SAMPLE_RATE) * 0.001).astype(np.float32)
        with self._lock:
            for device in [d for d in self._devices() if d not in self._failed]:
                try:
                    if self._model is None:
                        self._load(device)
                    list(self._model.transcribe(quiet, language="en", beam_size=1, without_timestamps=True)[0])
                    return True
                except Exception as exc:  # noqa: BLE001
                    log.warning("speech-to-text warm-up on %s failed: %s", device, exc)
                    self._model = self._device = None
                    self._failed.add(device)
        return False

    def _run(self, samples, language: str):
        segments, _info = self._model.transcribe(
            samples,
            language=_WHISPER_LANGUAGE[language],
            initial_prompt=_PROMPTS[language],
            beam_size=5 if self._device == "cuda" else 1,  # wider search only where it is cheap
            **_DECODE,
        )
        segments = list(segments)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        if not segments or not text:
            return "", 0.0, True
        weights = [max(segment.end - segment.start, 0.01) for segment in segments]
        avg = sum(s.avg_logprob * w for s, w in zip(segments, weights)) / sum(weights)
        no_speech = max(segment.no_speech_prob for segment in segments)
        compression = max(segment.compression_ratio for segment in segments)
        low = avg < MIN_AVG_LOGPROB or no_speech > MAX_NO_SPEECH or compression > MAX_COMPRESSION
        return text, round(math.exp(avg), 2), low

    def transcribe(self, audio: bytes, language: str, content_type: str | None = None) -> Transcript:
        if language not in LANGUAGES:
            raise ValidationError("That language is not available for transcription.")
        if not self.status()["available"]:
            raise SpeechUnavailableError()
        if len(audio) < MIN_BYTES:
            raise ValidationError("No speech was recorded. Please try again.")
        if len(audio) > config.VOICE_AGENT_STT_MAX_BYTES:
            raise ValidationError("That recording is too long. Please say one short phrase at a time.")
        started = time.perf_counter()
        try:
            samples = decode(audio)  # in memory only
        except Exception as exc:  # noqa: BLE001 - any undecodable upload
            raise ValidationError("The recording could not be read. Please try again.") from exc
        finally:
            del audio
        decoded = time.perf_counter()
        seconds = len(samples) / SAMPLE_RATE
        if seconds > config.VOICE_AGENT_STT_MAX_SECONDS:
            raise ValidationError("That recording is too long. Please say one short phrase at a time.")
        with self._lock:
            result = None
            devices = [self._device] if self._model is not None else [d for d in self._devices() if d not in self._failed]
            for device in devices:
                try:
                    if self._model is None:
                        self._load(device)
                    result = self._run(samples, language)
                    break
                except Exception as exc:  # noqa: BLE001 - e.g. missing CUDA libraries: try the CPU
                    log.warning("speech-to-text on %s failed: %s", device, exc)
                    self._model = self._device = None
                    self._failed.add(device)
            del samples
            if result is None:
                raise SpeechUnavailableError()
        text, confidence, low = result
        finished = time.perf_counter()
        return Transcript(
            text=" ".join(text.split())[:500],
            language=language,
            audio_seconds=round(seconds, 2),
            processing_seconds=round(time.perf_counter() - started, 2),
            model=self.name,
            device=self._device or "cpu",
            confidence=confidence,
            low_confidence=low,
            detected_language=_WHISPER_LANGUAGE[language],
            script=script_of(text),
            timings={"decode_ms": round((decoded - started) * 1000), "stt_ms": round((finished - decoded) * 1000)},
        )
