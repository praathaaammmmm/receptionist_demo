"""Voice agent demo in real headless Chromium: typed input, push-to-talk transcription, End call, late
replies, 390px layout.

Runs tests/js/voice_agent_browser.js against a live server on a fresh demo database. Microphone tests use
Chromium's fake microphone and, unless marked real_stt, a fake transcriber on the server. Skipped when
Node.js or Chromium is not installed.
"""
import json
import math
import shutil
import struct
import wave
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from app.main import create_app
from app.services import stt, tts

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests/js/voice_agent_browser.js"
NODE = shutil.which("node")
CHROMIUM = next((shutil.which(b) for b in ("chromium", "chromium-browser", "google-chrome") if shutil.which(b)), None)

pytestmark = pytest.mark.skipif(not (NODE and CHROMIUM), reason="Node.js and Chromium are needed for browser checks")


class FakeTranscriber:
    """Stands in for faster-whisper: returns fixed text and records what reached the server."""

    def __init__(self, text="what are you open", low_confidence=False, delay=0.0):
        self.text, self.low_confidence, self.delay = text, low_confidence, delay
        self.calls = []

    def status(self):
        return {"available": True, "engine": "fake", "model": "test", "installed": True, "package": True,
                "loaded": True, "device": "cpu", "runs": "in this test", "modes": stt.MODES}

    def transcribe(self, audio, language, content_type=None):
        self.calls.append({"bytes": len(audio), "type": content_type, "language": language, "is_bytes": isinstance(audio, bytes)})
        time.sleep(self.delay)
        return stt.Transcript(self.text, language, 1.2, 0.05, "test", "cpu", 0.4 if self.low_confidence else 0.92,
                              self.low_confidence)


def serve(tmp_path, transcriber=None):
    app = create_app(f"sqlite:///{tmp_path / 'browser.db'}")
    if transcriber is not None:
        app.state.transcriber = transcriber
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        assert time.monotonic() < deadline, "server did not start"
        time.sleep(0.05)
    return app, f"http://127.0.0.1:{port}", server, thread


@pytest.fixture
def live_server(tmp_path, request):
    marker = request.node.get_closest_marker("transcriber")
    transcriber = FakeTranscriber(**marker.kwargs) if marker else None
    app, base, server, thread = serve(tmp_path, transcriber)
    yield app, base
    server.should_exit = True
    thread.join(timeout=10)


def run(scenario, base, *extra, env=None):
    result = subprocess.run([NODE, str(HARNESS), scenario, base, *extra], capture_output=True, text=True, timeout=180,
                            env={"CHROMIUM": CHROMIUM, "PATH": "/usr/bin:/bin", **(env or {})})
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout.strip().splitlines()[-1])["result"]


def logs(app):
    from app.services import calls

    with app.state.session_factory() as db:
        return calls.list_recent(db, limit=50)


def stored_files(folder: Path) -> set[Path]:
    return {p for p in folder.rglob("*") if p.is_file()}


def test_no_horizontal_overflow_at_390px(live_server):
    app, base = live_server
    assert run("layout_390", base)["overflow"] <= 0


def test_typed_flow_works_without_a_transcription_model(live_server):
    app, base = live_server
    assert "Monday to Saturday" in run("typed_flow_without_transcription_model", base)["log"]


def speech_like_wav(path: Path, speech_seconds=1.2, lead=0.6, tail=4.0) -> Path:
    """A fake microphone recording: quiet, a voice-like tone, then silence (Chromium loops it)."""
    rate = 16000
    frames = bytearray()
    for i in range(int((lead + speech_seconds + tail) * rate)):
        t = i / rate
        on = lead <= t < lead + speech_seconds
        value = int(9000 * math.sin(2 * math.pi * 180 * t) * (0.6 + 0.4 * math.sin(2 * math.pi * 3 * t))) if on else 0
        frames += struct.pack("<h", value)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(bytes(frames))
    return path


def silent_wav(path: Path, seconds=9.0) -> Path:
    return speech_like_wav(path, speech_seconds=0, lead=0, tail=seconds)


@pytest.mark.transcriber(text="What are your opening hours?")
def test_high_confidence_speech_ends_on_silence_and_is_sent_automatically(live_server, tmp_path):
    app, base = live_server
    microphone = speech_like_wav(tmp_path / "speech.wav")
    before = stored_files(tmp_path)
    result = run("high_confidence_speech_is_sent_automatically", base, str(microphone))
    assert result["user"] == ["What are your opening hours?"] and result["messages"] == 1
    call = app.state.transcriber.calls[0]
    assert call["is_bytes"] and call["bytes"] > 200 and call["type"].startswith("audio/") and call["language"] == "en"
    # Nothing new on disk except the demo database and the test's own fake-microphone file: no audio was written.
    new = {p.name for p in stored_files(tmp_path) - before}
    assert new <= {"browser.db", "browser.db-journal", "browser.db-wal"}, new


@pytest.mark.transcriber(text="umm what", low_confidence=True)
def test_low_confidence_speech_is_held_for_review_and_sent_only_when_confirmed(live_server, tmp_path):
    app, base = live_server
    result = run("low_confidence_speech_is_held_for_review", base, str(speech_like_wav(tmp_path / "speech.wav")))
    assert result["warning"].startswith("I may not have caught that clearly") and result["messages"] == 1


@pytest.mark.transcriber(text="umm what", low_confidence=True)
def test_type_instead_keeps_the_transcript_without_sending(live_server, tmp_path):
    app, base = live_server
    result = run("type_instead_moves_the_transcript_to_the_input", base, str(speech_like_wav(tmp_path / "speech.wav")))
    assert result == {"value": "umm what", "messages": 0}


@pytest.mark.transcriber()
def test_near_silent_recordings_are_never_uploaded(live_server, tmp_path):
    app, base = live_server
    result = run("silence_is_never_uploaded", base, str(silent_wav(tmp_path / "silence.wav")))
    assert result["transcribes"] == 0 and app.state.transcriber.calls == []


@pytest.mark.transcriber()
def test_microphone_permission_error_keeps_typed_input(live_server):
    app, base = live_server
    assert "permission was denied" in run("microphone_permission_denied_keeps_typing", base)["note"]
    assert app.state.transcriber.calls == []


@pytest.mark.transcriber(text="What are your opening hours?", delay=1.5)
def test_ending_while_transcribing_drops_the_transcript(live_server, tmp_path):
    app, base = live_server
    run("end_while_transcribing_drops_the_transcript", base, str(speech_like_wav(tmp_path / "speech.wav")))
    logged = logs(app)
    assert len(logged) == 1 and logged[0].outcome == "ENDED"


@pytest.mark.real_voice
@pytest.mark.skipif(not tts.available("en"), reason="the local English voice pack is not installed")
def test_a_new_turn_cancels_the_previous_turns_audio(live_server):
    app, base = live_server
    result = run("new_turn_cancels_older_audio", base)  # the harness asserts no greeting audio after the new turn
    assert result["speech"] and result["speech"][0].startswith("We're open Monday to Saturday")


@pytest.mark.real_voice
@pytest.mark.skipif(not tts.available("en"), reason="the local English voice pack is not installed")
def test_end_call_while_speaking_is_silent_at_once(live_server):
    app, base = live_server
    result = run("end_call_while_speaking_is_silent_at_once", base)
    assert result == {"playsAfter": 0, "ends": 1}


def test_late_reply_never_appears_or_plays_after_end(live_server):
    app, base = live_server
    run("late_reply_never_appears_after_end", base)
    logged = logs(app)
    assert len(logged) == 1 and logged[0].completed_at is not None


def test_language_choice_persists_in_local_storage(live_server):
    app, base = live_server
    assert run("language_choice_persists", base)["checked"] == "hi"


@pytest.mark.real_voice
@pytest.mark.skipif(not tts.available("en"), reason="the local English voice pack is not installed")
def test_end_call_stops_audio_immediately_and_logs_once(live_server):
    app, base = live_server
    result = run("end_call_silences_audio_immediately", base)
    assert result["later"]["playsAfter"] == 0 and result["later"]["ends"] == 1
    logged = logs(app)
    assert len(logged) == 1 and logged[0].outcome == "ENDED" and logged[0].channel == "VOICE_AGENT"


@pytest.mark.real_stt
@pytest.mark.real_voice
@pytest.mark.parametrize("language, voice, spoken, intent", [
    ("en", "en", "What are your opening hours on Saturday?", "hours"),
    ("hi", "hi", "क्या रविवार को क्लिनिक खुला रहता है?", "hours"),
    ("hinglish", "hi", "मुझे रूट कैनाल के लिए अपॉइंटमेंट चाहिए।", "appointment_request"),
])
def test_real_microphone_transcription_in_chromium(tmp_path, language, voice, spoken, intent):
    """End to end: Chromium's fake microphone plays a Piper recording, MediaRecorder captures it, and the
    local faster-whisper model transcribes it on the server."""
    if not (stt.model_installed() and stt.package_installed() and tts.available(voice)):
        pytest.skip("needs the local speech-to-text model and the Piper voice packs")
    clip = tmp_path / "phrase.wav"
    import io
    import wave

    speech = tts.synthesize(spoken, voice)
    with wave.open(io.BytesIO(speech)) as source, wave.open(str(clip), "wb") as padded:
        padded.setparams(source.getparams())
        frames = source.readframes(source.getnframes())
        silence = b"\0" * (source.getsampwidth() * source.getframerate())  # a second either side
        padded.writeframes(silence + frames + silence)
        seconds = source.getnframes() / source.getframerate() + 2
    app, base, server, thread = serve(tmp_path)
    try:
        result = run("real_transcription", base, str(clip), env={"VA_LANGUAGE": language})
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    # Exact spelling can vary with the recording; what matters is that the words reach the right intent.
    from app.voice_agent import policy

    assert policy.classify(result["heard"]).topic == intent, result
    assert "real_transcription" and result["timing"]["marks"].get("stt_completed")
    print(language, result)


def test_page_states_where_microphone_audio_goes(client):
    html = client.get("/voice-agent-demo").text
    assert "Microphone transcription is processed by this demo server and is not stored." in html
    assert "SpeechRecognition" not in (ROOT / "app/static/js/voice-agent.js").read_text()
    assert "webkitSpeechRecognition" not in html


@pytest.mark.real_voice
@pytest.mark.skipif(not tts.available("en"), reason="the local English voice pack is not installed")
def test_reference_voice_fallback_is_announced_and_never_claimed(tmp_path, monkeypatch):
    """The page offered the reference voice, but it cannot speak (no clips, no worker): the standard voice
    speaks and the page says so."""
    from app.services import reference_voice

    monkeypatch.setattr(reference_voice, "status", lambda timeout=0.4: {"available": True, "languages": ["en", "hi", "hinglish"]})
    app, base, server, thread = serve(tmp_path)
    try:
        result = run("reference_voice_fallback_is_announced", base)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    assert result["status"] == "Speaking (standard voice)"
