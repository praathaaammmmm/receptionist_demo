"""Voice Agent Phase 3.1: latency and speech-recognition quality.

Speech-to-text configuration per language, model and voice reuse, cancellable cached speech, timings that are
never stored, the low-confidence guard, and regression phrases in English, Hindi and Hinglish.
"""
import io
import shutil
import subprocess
import threading
import wave
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import config
from app.models import CallLog
from app.services import stt, tts, voice_agent_demo
from app.voice_agent import llm, policy, wording
from app.voice_agent.context import IST, build_runtime_context
from app.voice_agent.conversation import Conversation

from .test_voice_agent_demo import API, Call, callbacks, give_details

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
MONDAY = datetime(2026, 10, 19, 11, 0, tzinfo=IST)


def wav_bytes(seconds=1.0, rate=16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\0\1" * int(seconds * rate))
    return buffer.getvalue()


@pytest.fixture
def installed_model(monkeypatch, tmp_path):
    """A stand-in model folder, so LocalWhisper believes the model is installed."""
    monkeypatch.setattr(config, "VOICE_AGENT_STT_DIR", tmp_path)
    folder = tmp_path / config.VOICE_AGENT_STT_MODEL
    folder.mkdir()
    for name in ("model.bin", "config.json"):
        (folder / name).write_text("x")
    return folder


class FakeWhisperModel:
    created = []

    def __init__(self, path, device, compute_type):
        self.path, self.device, self.compute_type = path, device, compute_type
        self.calls = []
        FakeWhisperModel.created.append(self)

    def transcribe(self, samples, **kwargs):
        self.calls.append(kwargs)
        segment = SimpleNamespace(text=" Sunday ko clinic khula hai kya? ", start=0, end=1, avg_logprob=-0.15,
                                  no_speech_prob=0.01, compression_ratio=1.1)
        return iter([segment]), SimpleNamespace(language=kwargs.get("language"))


@pytest.fixture
def fake_whisper(monkeypatch, installed_model):
    import faster_whisper

    FakeWhisperModel.created = []
    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(config, "VOICE_AGENT_STT_DEVICE", "cuda")
    monkeypatch.setattr(config, "VOICE_AGENT_STT_COMPUTE_TYPE", "")
    monkeypatch.setattr(stt, "_preload_cuda_libraries", lambda: None)
    return FakeWhisperModel


# --- Speech-to-text configuration -----------------------------------------------------------

@pytest.mark.parametrize("language, whisper_language", [("en", "en"), ("hi", "hi"), ("hinglish", "en")])
def test_selected_language_reaches_the_right_stt_settings(fake_whisper, language, whisper_language):
    result = stt.LocalWhisper().transcribe(wav_bytes(), language, "audio/wav")
    kwargs = fake_whisper.created[0].calls[0]
    assert kwargs["language"] == whisper_language
    assert kwargs["vad_filter"] is True and kwargs["temperature"] == 0.0 and kwargs["without_timestamps"] is True
    assert kwargs["beam_size"] == 5 and kwargs["condition_on_previous_text"] is False
    vocabulary = stt.CLINIC_VOCABULARY_HI if language == "hi" else stt.CLINIC_VOCABULARY
    for term in vocabulary:
        assert term in kwargs["initial_prompt"], term
    assert result.detected_language == whisper_language and result.script == "latin"
    assert set(result.timings) == {"decode_ms", "stt_ms"}


def test_gpu_uses_float16_and_the_model_is_loaded_once(fake_whisper):
    whisper = stt.LocalWhisper()
    for language in ("en", "hi", "hinglish", "en"):
        whisper.transcribe(wav_bytes(), language)
    assert len(fake_whisper.created) == 1  # reused for every request, never reloaded
    model = fake_whisper.created[0]
    assert model.device == "cuda" and model.compute_type == "float16" and len(model.calls) == 4


def test_warm_up_loads_once_and_later_requests_reuse_it(fake_whisper):
    whisper = stt.LocalWhisper()
    assert whisper.warm_up() is True
    whisper.transcribe(wav_bytes(), "en")
    assert len(fake_whisper.created) == 1 and whisper.status()["loaded"] is True


def test_warm_up_without_the_model_loads_nothing():
    whisper = stt.LocalWhisper()
    assert whisper.warm_up() is False and whisper.status()["loaded"] is False


def test_cpu_uses_int8_and_a_quick_search(fake_whisper, monkeypatch):
    monkeypatch.setattr(config, "VOICE_AGENT_STT_DEVICE", "cpu")
    stt.LocalWhisper().transcribe(wav_bytes(), "hi")
    model = fake_whisper.created[0]
    assert model.compute_type == "int8" and model.calls[0]["beam_size"] == 1


def test_transcript_script_is_reported_not_rewritten():
    assert stt.script_of("संडे को क्लिनिक खुला है क्या?") == "devanagari"
    assert stt.script_of("Sunday को clinic") == "mixed"
    assert stt.script_of("...") is None


def test_transcribe_response_carries_this_requests_timings_only(client, fake_whisper):
    client.app.state.transcriber = stt.LocalWhisper()
    body = client.post(f"{API}/transcribe?language=hinglish", content=wav_bytes(),
                       headers={"content-type": "audio/wav"}).json()
    assert body["text"] == "Sunday ko clinic khula hai kya?" and body["detected_language"] == "en"
    assert body["script"] == "latin" and body["low_confidence"] is False and body["stored"] is False
    assert set(body["timings"]) == {"decode_ms", "stt_ms", "server_ms"}


def test_no_audio_file_remains_after_a_request(client, fake_whisper, tmp_path):
    client.app.state.transcriber = stt.LocalWhisper()
    watched = [tmp_path, Path(config.BASE_DIR / "data")]
    before = {p for folder in watched if folder.exists() for p in folder.rglob("*")}
    client.post(f"{API}/transcribe?language=en", content=wav_bytes(), headers={"content-type": "audio/wav"})
    after = {p for folder in watched if folder.exists() for p in folder.rglob("*")}
    assert {p for p in after - before if p.suffix in (".wav", ".webm", ".ogg", ".mp4", ".tmp")} == set()


# --- Speech (Piper) -------------------------------------------------------------------------

class FakePiperVoice:
    loads = 0

    def __init__(self):
        self.calls = []

    @classmethod
    def load(cls, path):
        cls.loads += 1
        return cls()

    def synthesize(self, text, syn_config=None):
        self.calls.append(text)
        for word in text.split():
            yield SimpleNamespace(sample_rate=16000, sample_width=2, sample_channels=1, audio_int16_bytes=b"\0\0" * 80)


@pytest.fixture
def fake_piper(monkeypatch, tmp_path):
    import piper

    FakePiperVoice.loads = 0
    monkeypatch.setattr(piper, "PiperVoice", FakePiperVoice)
    monkeypatch.setattr(tts, "available", lambda language="en": True)
    monkeypatch.setattr(tts, "_voices", {})
    monkeypatch.setattr(tts, "_fixed_audio", {})
    monkeypatch.setattr(tts, "_fixed_allowed", set())
    monkeypatch.setattr(tts, "speaker_id", lambda language="en": None)
    return FakePiperVoice


def test_voice_is_loaded_once_and_reused(fake_piper):
    for text in ("One sentence.", "Another sentence.", "And a third."):
        tts.synthesize_turn(text, "en")
    tts.synthesize_turn("नमस्ते।", "hi")
    assert fake_piper.loads == 2  # one per voice pack, never per reply


def test_only_approved_fixed_phrases_are_cached(fake_piper):
    tts.allow_fixed_phrases([wording.line("one_moment", "en")], "en")
    first, cached_first = tts.synthesize_turn("One moment, please.", "en")
    again, cached_again = tts.synthesize_turn("One moment, please.", "en")
    assert (cached_first, cached_again) == (False, True) and first is again
    tts.synthesize_turn("Thank you, Asha Verma.", "en")
    _, cached_name = tts.synthesize_turn("Thank you, Asha Verma.", "en")
    assert cached_name is False  # a caller's name is never kept
    assert all("Asha" not in key[2] for key in tts._fixed_audio)


def test_cancelled_synthesis_stops_and_is_not_cached(fake_piper):
    cancel = threading.Event()
    cancel.set()
    tts.allow_fixed_phrases(["How can I help you today?"], "en")
    with pytest.raises(tts.SynthesisCancelled):
        tts.synthesize_turn("How can I help you today?", "en", cancel)
    assert tts._fixed_audio == {}


def test_reply_is_split_into_sentences_without_losing_words():
    for language in ("en", "hi", "hinglish"):
        for key in ("emergency", "clinical", "hours", "tooth_pain"):
            text = wording.line(key, language)
            parts = tts.speech_parts(text)
            assert " ".join(parts) == " ".join(text.split()) and all(parts)
    assert tts.speech_parts("Hello! How can I help you today?") == ["Hello! How can I help you today?"]


def test_speech_endpoint_returns_audio_with_timing_headers(client, fake_piper):
    response = client.post(f"{API}/speech", json={"text": "One moment, please.", "language": "en"})
    assert response.status_code == 200 and response.headers["content-type"] == "audio/wav"
    assert response.headers["x-phrase-cache"] in ("hit", "miss") and int(response.headers["x-synthesis-ms"]) >= 0
    assert response.headers["cache-control"] == "no-store"


def test_speech_endpoint_without_a_voice_pack_is_text_only(client):
    response = client.post(f"{API}/speech", json={"text": "Hello.", "language": "hi"})
    assert response.status_code == 503 and response.json()["error"] == "voice_unavailable"


def test_fixed_phrases_are_registered_and_pre_generated_at_startup(fake_piper):
    app = SimpleNamespace(state=SimpleNamespace(voice_agent_router=None, transcriber=SimpleNamespace()))
    voice_agent_demo.warm_up(app)
    for key in ("greeting", "one_moment", "low_confidence_retry", "anything_else", "goodbye"):
        for language in ("en", "hi"):
            for part in tts.speech_parts(wording.LINES[key][language]):
                assert tts._key(part, language) in tts._fixed_audio, (key, language)
    assert not any("{" in key[2] for key in tts._fixed_allowed)  # no line with caller details


@pytest.mark.skipif(NODE is None, reason="Node.js is needed to run the audio scenarios")
@pytest.mark.parametrize("scenario", [
    "plays_parts_in_order_requesting_one_ahead",
    "a_newer_turn_cancels_the_older_queue",
    "end_call_stops_and_discards_late_audio",
    "mute_cancels_pending_audio",
    "a_previous_calls_queue_never_plays_into_a_new_call",
    "idle_waits_for_the_current_sentence",
])
def test_stale_audio_never_plays(scenario):
    result = subprocess.run([NODE, str(ROOT / "tests/js/voice_agent_audio_harness.js"), scenario],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and result.stdout.strip() == "ok", result.stderr or result.stdout


# --- Low confidence: never acted on ----------------------------------------------------------

def low(call, text, reviewed=False):
    response = call.client.post(f"{API}/{call.id}/message", json={
        "text": text, "speech_confidence": "low", "reviewed": reviewed, "heard": text})
    assert response.status_code == 200
    call.last = response.json()
    return call.last


def test_unreviewed_low_confidence_speech_creates_nothing(client):
    call = Call(client)
    call.say("I want to book a consultation.")
    give_details(call, reason="Cleaning")
    before = len(callbacks(client))
    reply = low(call, "yes")
    assert reply["state"] == "confirm_details"  # nothing moved on
    assert reply["messages"][0]["text"] == wording.line("low_confidence_retry", "en")
    assert reply["decision"]["path"] == "low_confidence" and reply["callback_created"] is None
    assert len(callbacks(client)) == before
    reply = low(call, "yes", reviewed=True)  # the caller checked it and pressed "Send this"
    assert reply["callback_created"] and len(callbacks(client)) == before + 1


@pytest.mark.parametrize("text", ["My face is swollen and the swelling is spreading to my eye.",
                                  "Can I speak to someone at reception?", "I want to book a consultation."])
def test_uncertain_speech_never_starts_a_workflow(client, text):
    call = Call(client, transfer="available")
    reply = low(call, text)
    assert reply["state"] == "listening" and reply["transfer"] is None
    assert all("112" not in m["text"] for m in reply["messages"])
    assert reply["timings"]["handled_by"] == "rule"


def test_uncertain_speech_never_reaches_the_language_model(client):
    calls = []
    provider = SimpleNamespace(name="fake", model="fake-1",
                               complete_json=lambda *a, **k: calls.append(a) or {"intent": "greeting", "answer_ids": []})
    client.app.state.voice_agent_router = llm.Router(provider)
    call = Call(client)
    low(call, "what are your timings")
    assert calls == []


def test_high_confidence_speech_proceeds_normally(client):
    call = Call(client)
    response = client.post(f"{API}/{call.id}/message", json={
        "text": "What are your opening hours?", "speech_confidence": "high", "heard": "What are your opening hours?"}).json()
    assert response["decision"]["topic"] == "hours" and response["timings"]["handled_by"] == "rule"


# --- Timings: this turn only, never stored ---------------------------------------------------

def test_turn_timings_are_returned_but_never_stored(client):
    call = Call(client)
    call.say("I want to book a consultation.")
    timings = call.last["timings"]
    assert set(timings) == {"intent_ms", "handled_by"} and timings["handled_by"] == "rule"
    give_details(call, reason="Cleaning")
    call.say("yes")
    call.end()
    assert not hasattr(CallLog, "timings") and not hasattr(CallLog, "intent_ms")
    task = next(t for t in callbacks(client) if t["id"] == call.last["callback_created"]["id"])
    assert "ms" not in task["notes"] and "intent" not in task["notes"]
    logged = client.get("/api/calls").json()[0]
    assert set(logged) == {"id", "channel", "caller_name", "caller_mobile", "started_at", "completed_at", "outcome",
                           "appointment_id", "callback_task_id", "language", "is_demo"}


# --- Language model: quick, minimal, and labelled ----------------------------------------------

def test_llm_timeout_is_strict_and_failures_are_labelled_fallback(monkeypatch):
    assert config.VOICE_AGENT_LLM_TIMEOUT_SECONDS == 1.5
    seen = {}

    def slow(system, user, schema, timeout):
        seen["timeout"] = timeout
        raise llm.LLMUnavailable("Ollama: ReadTimeout")

    conversation = Conversation(build_runtime_context(MONDAY), router=llm.Router(SimpleNamespace(
        name="ollama", model="qwen3:8b", complete_json=slow)))
    turn = conversation.handle("how is the weather near the clinic", "en", lambda d, i: 1)
    assert seen["timeout"] == 1.5 and turn.handled_by == "fallback" and "don't want to guess" in turn.messages[0].text


def test_llm_payload_is_minimal(monkeypatch):
    sent = {}
    provider = SimpleNamespace(name="fake", model="m", complete_json=lambda system, user, schema, timeout: sent.update(
        user=user) or {"intent": "answer", "answer_ids": ["hours"], "preferred_doctor": "not_mentioned", "preferred_time": ""})
    conversation = Conversation(build_runtime_context(MONDAY), router=llm.Router(provider))
    conversation.handle("hi there, what time do you shut?", "en", lambda d, i: 1)
    turn = conversation.handle("and on saturdays when do you shut", "en", lambda d, i: 1)
    assert turn.handled_by == "llm"
    assert "recent_conversation" not in sent["user"] and "callback" not in sent["user"]
    assert sent["user"] == '{"caller_said": "and on saturdays when do you shut", "selected_language": "en"}'


@pytest.mark.parametrize("text", ["My face is swollen and the swelling is spreading to my eye", "Which medicine should I take?",
                                  "Do you accept CGHS?", "Can I talk to the receptionist?", "Is my appointment confirmed?",
                                  "I want to reschedule my appointment", "Please cancel my appointment"])
def test_deterministic_intents_never_wait_for_the_model(text):
    calls = []
    provider = SimpleNamespace(name="fake", model="m", complete_json=lambda *a: calls.append(a))
    conversation = Conversation(build_runtime_context(MONDAY), router=llm.Router(provider))
    turn = conversation.handle(text, "en", lambda d, i: 1)
    assert calls == [] and turn.handled_by == "rule"


# --- Regression phrases (deterministic, as transcribed) ---------------------------------------

REGRESSION = [
    ("en", "What are your opening hours on Saturday?", "hours"),
    ("en", "I need an appointment for a root canal consultation.", "appointment_request"),
    ("hi", "मुझे रूट कैनाल के लिए अपॉइंटमेंट चाहिए।", "appointment_request"),
    ("hi", "क्या रविवार को क्लिनिक खुला है?", "hours"),
    ("hinglish", "Mujhe implant consultation ke liye appointment chahiye.", "appointment_request"),
    ("hinglish", "Sunday ko clinic khula hai kya?", "hours"),
    ("hinglish", "Mujhe reception se callback chahiye.", "callback_request"),
]


@pytest.mark.parametrize("language, heard, topic", REGRESSION)
def test_regression_phrases_route_correctly(client, language, heard, topic):
    call = Call(client, language=language)
    response = client.post(f"{API}/{call.id}/message", json={
        "text": heard, "language": language, "speech_confidence": "high", "heard": heard}).json()
    assert response["decision"]["topic"] == topic and response["language"] == language


# The same phrases spoken by the local Piper voices and transcribed by the real model (when installed).
SPOKEN = {
    "What are your opening hours on Saturday?": ("en", "What are your opening hours on Saturday?"),
    "I need an appointment for a root canal consultation.": ("en", "I need an appointment for a root canal consultation."),
    "मुझे रूट कैनाल के लिए अपॉइंटमेंट चाहिए।": ("hi", "मुझे रूट कैनाल के लिए अपॉइंटमेंट चाहिए।"),
    "क्या रविवार को क्लिनिक खुला है?": ("hi", "क्या रविवार को क्लिनिक खुला है?"),
    "Mujhe implant consultation ke liye appointment chahiye.": ("hi", "मुझे इम्प्लांट कंसल्टेशन के लिए अपॉइंटमेंट चाहिए।"),
    "Sunday ko clinic khula hai kya?": ("hi", "संडे को क्लिनिक खुला है क्या?"),
    "Mujhe reception se callback chahiye.": ("hi", "मुझे रिसेप्शन से कॉलबैक चाहिए।"),
}


@pytest.mark.real_stt
@pytest.mark.real_voice
@pytest.mark.parametrize("language, heard, topic", REGRESSION)
def test_real_model_transcribes_regression_phrases(language, heard, topic):
    voice, spoken = SPOKEN[heard]
    if not (stt.model_installed() and stt.package_installed() and tts.available(voice)):
        pytest.skip("needs the local speech-to-text model and the Piper voice packs")
    whisper = _shared_whisper()
    result = whisper.transcribe(tts.synthesize(spoken, voice), language, "audio/wav")
    assert policy.classify(result.text).topic == topic, result
    assert not result.low_confidence, result


_WHISPER = None


def _shared_whisper():
    global _WHISPER
    if _WHISPER is None:
        _WHISPER = stt.LocalWhisper()
    return _WHISPER


def test_page_phrases_use_the_cached_sentence_parts(client):
    import json
    import re

    html = client.get("/voice-agent-demo").text
    config_json = json.loads(re.search(r'<script type="application/json" id="va-config">(.*?)</script>', html, re.S).group(1))
    retry = config_json["phrases"]["low_confidence_retry"]
    assert retry["en"]["parts"] == tts.speech_parts(wording.line("low_confidence_retry", "en"))
    assert retry["hinglish"]["text"] == wording.line("low_confidence_retry", "hinglish")
    assert retry["hinglish"]["parts"] == tts.speech_parts(wording.line("low_confidence_retry", "hi"))
