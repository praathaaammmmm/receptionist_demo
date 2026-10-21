"""Call-demo audio stops instantly on End call or leaving, and late audio never plays.

The playback rules live in app/static/js/call-audio.js (no DOM), checked here in Node with a fake
audio element, speech endpoint and speech engine. Skipped if Node is not installed.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from .test_multilingual import Call, logged

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests/js/call_audio_harness.js"
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js is needed to run the audio scenarios")
@pytest.mark.parametrize("scenario", [
    "end_call_stops_playing_audio_immediately",
    "end_call_aborts_in_flight_speech_request",
    "late_speech_response_never_plays_after_end",
    "end_while_audio_downloads_or_starts_discards_it",
    "leaving_for_dashboard_stops_audio_instantly",
    "new_call_cannot_play_audio_from_previous_call",
    "mute_and_replacement_discard_pending_audio",
    "browser_speech_fallback_is_cancelled_on_end",
    "voice_tests_play_outside_a_call",
])
def test_audio_scenario(scenario):
    result = subprocess.run([NODE, str(HARNESS), scenario], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and result.stdout.strip() == "ok", result.stderr or result.stdout


def test_call_page_routes_all_audio_through_the_controller(client):
    page = client.get("/call-demo").text
    assert page.index("js/call-audio.js") < page.index("js/call.js")
    script = (ROOT / "app/static/js/call.js").read_text()
    assert "new Audio()" in script and "window.CallAudio.create(" in script
    assert "player" not in script and "speechSeq" not in script  # no second, uncancellable player
    assert "AbortController: window.AbortController" in script
    end = script.split("async function endCall(quiet) {")[1].split("try {")[0]
    # On End call: silence first, then the "Call ended" state with input disabled.
    assert end.index("audio.endCall()") < end.index('showIdle("Call ended")')
    assert "callToken = null" in end
    assert "speak(" not in script.split("async function endCall(quiet) {")[1].split("async function resetCall")[0]
    leave = script.split("window.LeaveGuard({")[1].split("});")[0]
    assert leave.index("audio.leave()") < leave.index("endCall(true)")
    assert "audio.leave();" in script.split('addEventListener("pagehide"')[1]
    # Each call gets its own client-side audio session, and replies are checked against it.
    assert re.search(r"callToken = `call-\$\{callId\}-\$\{\+\+callSeq\}`;[^\n]*\s+audio\.beginCall\(callToken\);", script)
    assert "if (token !== callToken) return; // the call ended while waiting" in script
    assert "if (token !== callToken) return; // the call ended while this reply was on its way" in script
    assert 'ended: "Call ended · audio stopped"' in script and 'speaking: "AI is speaking"' in script
    assert "if (ended) return \"ended\";" in script  # never "AI is speaking" after the end


def test_controller_uses_every_required_stop_step():
    module = (ROOT / "app/static/js/call-audio.js").read_text()
    for step in ("audio.pause()", "audio.currentTime = 0", 'audio.removeAttribute("src")', "audio.load()",
                 "env.revokeObjectURL(url)", "request.abort()", "env.synth.cancel()", "env.clearTimeout(id)",
                 "signal: controller.signal"):
        assert step in module, step


def test_ending_and_leaving_keep_one_call_log_with_its_outcome(client):
    call = Call(client, "hinglish")
    call.shortcut("What are your opening hours?")
    first = call.end()["call"]
    # The page may end the same call twice (End call, then the pagehide beacon); the log is unchanged.
    again = client.post(f"/api/call-demo/{call.id}/end", content=b'{"language":"hinglish"}',
                        headers={"content-type": "application/json"}).json()["call"]
    assert again == first and first["outcome"] == "FAQ_ANSWERED"
    assert len(client.get("/api/calls").json()) == 1
    # A reply requested after the end is refused, so no audio text exists for it.
    late = client.post(f"/api/call-demo/{call.id}/message", json={"text": "hello", "language": "hinglish"})
    assert late.status_code == 400
    assert logged(client, call.id)["outcome"] == "FAQ_ANSWERED"
