// Scenario checks for app/static/js/call-audio.js, run by tests/test_call_audio.py.
// Usage: node tests/js/call_audio_harness.js <scenario>   -> prints "ok" or exits non-zero.
const assert = require("node:assert/strict");
const path = require("node:path");
const CallAudio = require(path.join(__dirname, "../../app/static/js/call-audio.js"));

const tick = (ms = 0) => new Promise((resolve) => setTimeout(resolve, ms));

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => ((resolve = res), (reject = rej)));
  return { promise, resolve, reject };
}

class FakeAudio {
  constructor(log) {
    this.log = log;
    this.src = "";
    this.currentTime = 0;
    this.paused = true;
    this.loads = 0;
    this.playGate = null; // a deferred, to hold play() pending
    log.audios.push(this);
  }
  play() {
    this.log.plays.push(this.src);
    const start = () => {
      this.paused = false;
      this.currentTime = 1.5; // pretend some sound has been heard
    };
    if (this.playGate) return this.playGate.promise.then(start);
    start();
    return Promise.resolve();
  }
  pause() {
    this.paused = true;
  }
  removeAttribute(name) {
    if (name === "src") this.src = "";
  }
  load() {
    this.loads += 1;
  }
}

// A speech endpoint whose replies the scenario releases by hand. `honourAbort: false` imitates a
// server that finishes synthesis anyway and answers after the call has ended.
function setup({ honourAbort = true } = {}) {
  const log = { audios: [], plays: [], fetches: [], revoked: [], cancels: 0, spoken: [], hooks: [] };
  const fakeSynth = {
    cancel: () => (log.cancels += 1),
    resume: () => {},
    speak: (u) => log.spoken.push(u),
  };
  const env = {
    speechUrl: "/api/call-demo/speech",
    fetch(url, options) {
      const reply = deferred();
      const entry = { url, body: JSON.parse(options.body), signal: options.signal, reply };
      log.fetches.push(entry);
      if (honourAbort) {
        options.signal.addEventListener("abort", () => {
          const error = new Error("aborted");
          error.name = "AbortError";
          reply.reject(error);
        });
      }
      return reply.promise;
    },
    makeAudio: () => new FakeAudio(log),
    makeUtterance: (text) => ({ text }),
    synth: fakeSynth,
    createObjectURL: () => `blob:${log.fetches.length}`,
    revokeObjectURL: (url) => log.revoked.push(url),
    setTimeout,
    clearTimeout,
    AbortController,
    hooks: {
      onPlaying: () => log.hooks.push("playing"),
      onDone: () => log.hooks.push("done"),
      onStopped: () => log.hooks.push("stopped"),
      onFailed: () => log.hooks.push("failed"),
    },
  };
  return { audio: CallAudio.create(env), log };
}

const wav = () => ({ ok: true, status: 200, blob: async () => "RIFF-fake-wav" });

const scenarios = {
  async end_call_stops_playing_audio_immediately() {
    const { audio, log } = setup();
    audio.beginCall("call-1");
    const result = audio.playLocal("नमस्ते", "hi", "call-1");
    log.fetches[0].reply.resolve(wav());
    assert.equal(await result, "played");
    const playing = log.audios[0];
    assert.equal(playing.paused, false);
    audio.endCall();
    // Synchronous: by the time endCall() returns the sound has stopped.
    assert.equal(playing.paused, true);
    assert.equal(playing.currentTime, 0);
    assert.equal(playing.src, "");
    assert.equal(playing.loads, 1);
    assert.deepEqual(log.revoked, ["blob:1"]);
    assert.equal(audio.playing, false);
    assert.ok(log.cancels >= 1, "browser speech is cancelled too");
  },

  async end_call_aborts_in_flight_speech_request() {
    const { audio, log } = setup();
    audio.beginCall("call-1");
    const result = audio.playLocal("Hello", "en", "call-1");
    assert.equal(log.fetches[0].signal.aborted, false);
    audio.endCall();
    assert.equal(log.fetches[0].signal.aborted, true);
    assert.equal(await result, "discarded");
    assert.equal(log.audios.length, 0, "no audio element is ever created");
    assert.deepEqual(log.plays, []);
  },

  async late_speech_response_never_plays_after_end() {
    const { audio, log } = setup({ honourAbort: false }); // the server finishes synthesis anyway
    audio.beginCall("call-1");
    const result = audio.playLocal("Hello", "en", "call-1");
    audio.endCall();
    log.fetches[0].reply.resolve(wav()); // the audio arrives after the call ended
    assert.equal(await result, "discarded");
    assert.deepEqual(log.plays, []);
    assert.equal(log.audios.length, 0);
  },

  async end_while_audio_downloads_or_starts_discards_it() {
    // Ended between the response headers and the audio body.
    let { audio, log } = setup({ honourAbort: false });
    audio.beginCall("call-1");
    let gate = deferred();
    let result = audio.playLocal("Hello", "en", "call-1");
    log.fetches[0].reply.resolve({ ok: true, status: 200, blob: () => gate.promise });
    await tick();
    audio.endCall();
    gate.resolve("RIFF");
    assert.equal(await result, "discarded");
    assert.deepEqual(log.plays, []);

    // Ended while the browser was still starting playback.
    ({ audio, log } = setup());
    audio.beginCall("call-2");
    const realMake = log;
    result = audio.playLocal("Hello", "en", "call-2");
    const playGate = deferred();
    const originalPush = realMake.audios.push.bind(realMake.audios);
    realMake.audios.push = (a) => ((a.playGate = playGate), originalPush(a));
    log.fetches[0].reply.resolve(wav());
    await tick();
    audio.endCall();
    playGate.resolve();
    assert.equal(await result, "discarded");
    const element = log.audios[0];
    assert.equal(element.paused, true);
    assert.equal(element.src, "");
  },

  async leaving_for_dashboard_stops_audio_instantly() {
    const { audio, log } = setup();
    audio.beginCall("call-1");
    const result = audio.playLocal("Hello", "en", "call-1");
    log.fetches[0].reply.resolve(wav());
    await result;
    audio.leave();
    assert.equal(log.audios[0].paused, true);
    assert.equal(log.audios[0].currentTime, 0);
    // Nothing can start while the page is navigating away, not even a voice test.
    assert.equal(await audio.playLocal("Hello", "en", null), "discarded");
    assert.equal(log.fetches.length, 1);
  },

  async new_call_cannot_play_audio_from_previous_call() {
    const { audio, log } = setup({ honourAbort: false });
    audio.beginCall("call-1");
    const old = audio.playLocal("from call one", "en", "call-1");
    audio.endCall();
    audio.beginCall("call-2"); // "Start another demo call"
    log.fetches[0].reply.resolve(wav()); // call one's audio turns up late
    assert.equal(await old, "discarded");
    assert.deepEqual(log.plays, []);
    // A reply still addressed to call one is refused outright.
    assert.equal(await audio.playLocal("stale", "en", "call-1"), "discarded");
    // The new call's own reply plays normally.
    const fresh = audio.playLocal("from call two", "en", "call-2");
    log.fetches[log.fetches.length - 1].reply.resolve(wav());
    assert.equal(await fresh, "played");
    assert.equal(log.plays.length, 1);
    assert.equal(log.fetches[log.fetches.length - 1].body.text, "from call two");
  },

  async mute_and_replacement_discard_pending_audio() {
    const { audio, log } = setup({ honourAbort: false });
    audio.beginCall("call-1");
    const first = audio.playLocal("one", "en", "call-1");
    const second = audio.playLocal("two", "en", "call-1"); // a newer reply replaces the first
    log.fetches[0].reply.resolve(wav());
    assert.equal(await first, "discarded");
    audio.setMuted(true);
    log.fetches[1].reply.resolve(wav());
    assert.equal(await second, "discarded");
    assert.deepEqual(log.plays, []);
    assert.equal(await audio.playLocal("three", "en", "call-1"), "discarded");
  },

  async browser_speech_fallback_is_cancelled_on_end() {
    const { audio, log } = setup();
    audio.beginCall("call-1");
    audio.speakBrowser(["Hello there."], null, "call-1");
    audio.endCall(); // before the 80 ms queue delay
    await tick(120);
    assert.deepEqual(log.spoken, [], "queued speech never starts");

    audio.beginCall("call-2");
    audio.speakBrowser(["Hello again."], null, "call-2");
    await tick(120);
    assert.equal(log.spoken.length, 1);
    const cancelsBefore = log.cancels;
    audio.endCall();
    assert.equal(log.cancels, cancelsBefore + 1, "speechSynthesis.cancel() on end");
    log.spoken[0].onstart(); // a late start event after the end is shut down again
    assert.equal(log.cancels, cancelsBefore + 2);
    assert.ok(!log.hooks.slice(log.hooks.lastIndexOf("stopped")).includes("playing"));
  },

  async voice_tests_play_outside_a_call() {
    const { audio, log } = setup();
    const result = audio.playLocal("नमस्ते", "hinglish", null);
    log.fetches[0].reply.resolve(wav());
    assert.equal(await result, "played");
    assert.equal(log.fetches[0].body.language, "hinglish");
  },
};

const name = process.argv[2];
if (!scenarios[name]) {
  console.error(`unknown scenario: ${name}; known: ${Object.keys(scenarios).join(", ")}`);
  process.exit(2);
}
scenarios[name]().then(
  () => console.log("ok"),
  (error) => {
    console.error(error.stack || error);
    process.exit(1);
  }
);
