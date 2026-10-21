"""Optional consented reference voice: adapter contract, fallback to Piper, privacy boundaries, page selector."""
import asyncio
import io
import json
import re
import subprocess
import shutil
import wave
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app import config
from app.services import reference_voice, tts

from .test_voice_agent_latency import fake_piper  # noqa: F401 - fixture

ROOT = Path(__file__).resolve().parent.parent
API = "/api/voice-agent-demo"
NODE = shutil.which("node")


def wav(seconds=0.2, rate=24000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"\0\0" * int(seconds * rate))
    return buffer.getvalue()


@pytest.fixture
def clips(monkeypatch, tmp_path):
    folder = tmp_path / "reference"
    folder.mkdir()
    for name in reference_voice.REQUIRED_CLIPS:
        (folder / f"{name}.wav").write_bytes(wav())
    monkeypatch.setattr(config, "VOICE_AGENT_REFERENCE_DIR", folder)
    return folder


class FakeWorker:
    """Stands in for scripts/reference_voice_worker.py through httpx's mock transport."""

    def __init__(self, status=200, delay=0.0, fail=False):
        self.status, self.delay, self.fail = status, delay, fail
        self.requests, self.cancelled = [], []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            raise httpx.ConnectError("refused")
        body = json.loads(request.content or b"{}")
        if request.url.path == "/cancel":
            self.cancelled.append(body["request_id"])
            return httpx.Response(200, json={"cancelled": True})
        self.requests.append(body)
        await asyncio.sleep(self.delay)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "unsupported"})
        return httpx.Response(200, content=wav(), headers={"content-type": "audio/wav", "X-Generation-Ms": "640"})


@pytest.fixture
def worker(monkeypatch):
    fake = FakeWorker()
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(fake.handle), **kw))
    return fake


def speak(text="Hello there.", language="en", **kw):
    return asyncio.run(reference_voice.synthesize_reference_voice(text, language, "req-1", **kw))


# --- Adapter --------------------------------------------------------------------------------

def test_result_carries_audio_backend_and_latency(clips, worker):
    result = speak("नमस्ते।", "hinglish")
    assert result.audio.startswith(b"RIFF") and result.backend == "chatterbox-multilingual"
    assert result.fallback_reason is None and result.generation_ms == 640 and result.latency_ms >= 0
    assert worker.requests == [{"text": "नमस्ते।", "language": "hi", "request_id": "req-1"}]  # Hinglish: Hindi profile


@pytest.mark.parametrize("language, model_language", [("en", "en"), ("hi", "hi"), ("hinglish", "hi")])
def test_language_mapping(clips, worker, language, model_language):
    speak("Text.", language)
    assert worker.requests[0]["language"] == model_language


def test_unsupported_language_falls_back_without_calling_the_worker(clips, worker):
    result = speak("வணக்கம்", "ta")
    assert result.audio is None and result.fallback_reason == "language not supported by the reference voice"
    assert worker.requests == []


def test_worker_refusing_a_language_falls_back(clips, worker):
    worker.status = 422
    assert speak().fallback_reason == "language not supported by the reference voice"


def test_missing_clips_fall_back(worker):
    result = speak()
    assert result.audio is None and result.fallback_reason == "no authorised reference clips installed"


def test_worker_not_running_falls_back(clips, worker):
    worker.fail = True
    assert speak().fallback_reason == "the local reference-voice worker is not running"


def test_too_slow_falls_back_and_cancels_the_queued_generation(clips, worker, monkeypatch):
    monkeypatch.setattr(config, "VOICE_AGENT_REFERENCE_TIMEOUT_SECONDS", 0.1)
    worker.delay = 1.0
    result = speak()
    assert result.audio is None and result.fallback_reason == "too slow"
    assert worker.cancelled == ["req-1"]


def test_cancellation_while_generating_stops_at_once(clips, worker):
    worker.delay = 2.0

    async def run():
        cancelled = asyncio.Event()
        asyncio.get_running_loop().call_later(0.1, cancelled.set)
        return await reference_voice.synthesize_reference_voice("Hello.", "en", "req-9", cancelled)

    result = asyncio.run(run())
    assert result.audio is None and result.fallback_reason == "cancelled" and result.latency_ms < 1000
    assert worker.cancelled == ["req-9"]


def test_status_requires_clips_and_a_ready_worker(clips, monkeypatch):
    assert reference_voice.status()["available"] is False  # tests point the worker at a closed port
    monkeypatch.setattr(httpx, "get", lambda url, timeout: SimpleNamespace(json=lambda: {
        "ready": True, "model": "m", "licence": "MIT", "device": "cuda", "languages": ["en", "hi"]}))
    status = reference_voice.status()
    assert status["available"] is True and status["languages"] == ["en", "hi", "hinglish"]


# --- Speech endpoint ------------------------------------------------------------------------

def test_reference_speech_is_labelled_and_never_cached(client, clips, worker):
    for _ in range(2):
        response = client.post(f"{API}/speech", json={"text": "One moment, please.", "language": "en", "voice": "reference"})
        assert response.status_code == 200 and response.headers["x-voice-mode"] == "reference"
        assert response.headers["x-voice"] == "chatterbox-multilingual" and response.headers["cache-control"] == "no-store"
    assert len(worker.requests) == 2  # generated each time: reference speech is never kept


def test_fallback_uses_piper_and_says_so(client, fake_piper):
    response = client.post(f"{API}/speech", json={"text": "Hello there.", "language": "en", "voice": "reference"})
    assert response.status_code == 200 and response.headers["x-voice-mode"] == "fallback"
    assert response.headers["x-voice-fallback-reason"] == "no authorised reference clips installed"
    assert response.headers["x-voice"] != "chatterbox-multilingual"


def test_standard_voice_is_unchanged(client, fake_piper):
    response = client.post(f"{API}/speech", json={"text": "Hello there.", "language": "en"})
    assert response.status_code == 200 and response.headers["x-voice-mode"] == "standard"
    assert "x-voice-fallback-reason" not in response.headers


def test_call_demo_speech_route_is_untouched(client):
    response = client.post("/api/call-demo/speech", json={"text": "Hello.", "language": "en", "voice": "reference"})
    assert response.status_code == 503  # no voice pack in tests; and no reference mode there
    assert "x-voice-mode" not in response.headers


# --- Page -----------------------------------------------------------------------------------

def page_config(client):
    html = client.get("/voice-agent-demo").text
    return html, json.loads(re.search(r'<script type="application/json" id="va-config">(.*?)</script>', html, re.S).group(1))


def test_selector_hidden_when_reference_voice_unavailable(client):
    html, cfg = page_config(client)
    assert "Reference voice (authorised demo)" not in html and cfg["referenceVoice"]["available"] is False


def test_selector_shown_with_standard_as_default_when_available(client, monkeypatch):
    monkeypatch.setattr(reference_voice, "status", lambda timeout=0.4: {"available": True, "languages": ["en", "hi", "hinglish"]})
    html, cfg = page_config(client)
    assert "Standard local voice" in html and "Reference voice (authorised demo)" in html
    assert re.search(r'value="standard" checked', html) and not re.search(r'value="reference" checked', html)
    assert cfg["referenceVoice"]["fallbackMessage"] == ("Reference voice is unavailable for this reply. "
                                                        "Using the standard local voice.")


# --- Privacy boundaries ---------------------------------------------------------------------

def test_reference_audio_is_never_served(client, clips):
    for path in ("/voices/reference/hi_1.wav", "/static/../voices/reference/hi_1.wav", "/reference/hi_1.wav",
                 "/api/voice-agent-demo/reference/hi_1.wav"):
        assert client.get(path).status_code in (404, 405)
    paths = {getattr(route, "path", "") for route in client.app.routes}
    assert not any("reference" in path for path in paths)


def test_reference_voice_has_no_database_or_external_access():
    source = (ROOT / "app/services/reference_voice.py").read_text()
    assert "sqlalchemy" not in source and "Session" not in source and ".db" not in source
    assert config.VOICE_AGENT_REFERENCE_WORKER_URL.startswith("http://127.0.0.1")
    worker = (ROOT / "scripts/reference_voice_worker.py").read_text()
    assert '("127.0.0.1", args.port)' in worker  # local only
    assert "/health" in worker and "reference_dir" in worker and "send_file" not in worker


def test_reference_clips_and_environment_are_ignored_by_git():
    ignored = subprocess.run(["git", "check-ignore", "voices/reference/hi_1.wav", ".venv-refvoice/bin/python",
                              "voices/reference/eval/x.wav"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert len(ignored) == 3


@pytest.mark.skipif(NODE is None, reason="Node.js is needed to run the audio scenarios")
def test_queue_sends_the_voice_choice_and_reports_the_voice_used():
    result = subprocess.run([NODE, str(ROOT / "tests/js/voice_agent_audio_harness.js"), "sends_voice_choice_and_reports_fallback"],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and result.stdout.strip() == "ok", result.stderr or result.stdout


# --- With the real worker (skipped unless it is running) -------------------------------------

@pytest.mark.real_reference
def test_real_worker_speaks_all_three_languages():
    if not reference_voice.status()["available"]:
        pytest.skip("the reference-voice worker is not running")
    for language, text in (("en", "How may I help you today?"), ("hi", "मैं आपकी कैसे मदद कर सकती हूँ?"),
                           ("hinglish", "मैं आपकी कैसे मदद कर सकती हूँ?")):
        result = asyncio.run(reference_voice.synthesize_reference_voice(text, language, f"t-{language}"))
        assert result.audio and result.audio.startswith(b"RIFF") and result.fallback_reason is None, result


@pytest.mark.parametrize("language", ["en", "hi", "hinglish"])
def test_emergency_number_is_always_spoken_by_the_standard_voice(clips, worker, language):
    from app.voice_agent import wording

    line = wording.line("emergency", "hi" if language == "hinglish" else language)
    sentence = next(part for part in tts.speech_parts(line) if "112" in part)
    result = speak(sentence, language)
    assert result.audio is None and result.fallback_reason == "emergency instructions always use the standard voice"
    assert worker.requests == []


def test_numbers_are_written_out_for_the_reference_voice_only(clips, worker):
    speak("We're open Monday to Saturday, from 9 AM to 8 PM.", "en")
    speak("सुबह 9 बजे से रात 8 बजे तक, प्लॉट नंबर 54", "hi")
    assert worker.requests[0]["text"] == "We're open Monday to Saturday, from nine AM to eight PM."
    assert worker.requests[1]["text"] == "सुबह नौ बजे से रात आठ बजे तक, प्लॉट नंबर चौवन"
    assert reference_voice.speakable("Call 98765", "en") == "Call nine eight seven six five"
