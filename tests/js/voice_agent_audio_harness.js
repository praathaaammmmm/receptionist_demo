// Scenario checks for CallAudio.playQueue (app/static/js/call-audio.js), the voice agent's sentence-by-sentence
// playback. Run by tests/test_voice_agent_latency.py. Usage: node tests/js/voice_agent_audio_harness.js <scenario>
const assert = require("node:assert/strict");
const path = require("node:path");
const CallAudio = require(path.join(__dirname, "../../app/static/js/call-audio.js"));

const tick = (ms = 0) => new Promise((resolve) => setTimeout(resolve, ms));

function deferred() {
  let resolve;
  const promise = new Promise((res) => (resolve = res));
  return { promise, resolve };
}

class FakeAudio {
  constructor(log) {
    this.log = log;
    this.src = "";
    this.paused = true;
    this.currentTime = 0;
    log.audios.push(this);
  }
  play() {
    this.paused = false;
    this.log.plays.push(this.src);
    return Promise.resolve();
  }
  pause() {
    this.paused = true;
  }
  removeAttribute(name) {
    if (name === "src") this.src = "";
  }
  load() {}
  finish() {
    this.paused = true;
    if (this.onended) this.onended();
  }
}

// A speech endpoint whose replies the scenario releases by hand, one per requested sentence.
function setup() {
  const log = { audios: [], plays: [], fetches: [], revoked: [], events: [], parts: [] };
  const env = {
    speechUrl: "/api/voice-agent-demo/speech",
    now: () => Date.now(),
    fetch(url, options) {
      const reply = deferred();
      const entry = { body: JSON.parse(options.body), signal: options.signal, reply, aborted: false };
      log.fetches.push(entry);
      options.signal.addEventListener("abort", () => (entry.aborted = true));
      return new Promise((resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
        reply.promise.then(resolve);
      });
    },
    makeAudio: () => new FakeAudio(log),
    createObjectURL: (blob) => `blob:${blob.text}`,
    revokeObjectURL: (url) => log.revoked.push(url),
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id),
    AbortController,
    synth: null,
    hooks: {
      onPreparing: () => log.events.push("preparing"),
      onPlaying: () => log.events.push("playing"),
      onDone: () => log.events.push("done"),
      onPartReady: (i, result) => {
        log.events.push(`ready:${i}`);
        log.parts.push({ voiceMode: result.voiceMode, fallbackReason: result.fallbackReason });
      },
    },
  };
  const ok = (text, extra = {}) => ({ ok: true, status: 200,
    headers: { get: (h) => (h in extra ? extra[h] : h === "X-Phrase-Cache" ? "miss" : "12") },
    blob: async () => ({ text }) });
  return { log, audio: CallAudio.create(env), ok };
}

const lastAudio = (log) => log.audios[log.audios.length - 1];

const scenarios = {
  async sends_voice_choice_and_reports_fallback() {
    const { log, audio, ok } = setup();
    const reported = [];
    audio.beginCall("call-1");
    const env = audio; // the voice choice travels in the request body; the voice used comes back in a header
    const done = env.playQueue(["One."], "en", "call-1", undefined, { voice: "reference" });
    await tick();
    assert.deepEqual(log.fetches[0].body, { text: "One.", language: "en", voice: "reference" });
    log.events.length = 0;
    log.fetches[0].reply.resolve(ok("One.", { "X-Voice-Mode": "fallback", "X-Voice-Fallback-Reason": "too slow" }));
    await tick();
    lastAudio(log).finish();
    assert.equal(await done, "played");
    reported.push(...log.parts);
    assert.deepEqual(reported, [{ voiceMode: "fallback", fallbackReason: "too slow" }]);
  },


  async plays_parts_in_order_requesting_one_ahead() {
    const { log, audio, ok } = setup();
    audio.beginCall("call-1");
    const done = audio.playQueue(["One.", "Two.", "Three."], "en", "call-1");
    await tick();
    assert.equal(log.fetches.length, 1, "only the first sentence is requested at first");
    log.fetches[0].reply.resolve(ok("One."));
    await tick();
    assert.deepEqual(log.plays, ["blob:One."]);
    assert.equal(log.fetches.length, 2, "the next sentence is requested while the first plays");
    log.fetches[1].reply.resolve(ok("Two."));
    await tick();
    assert.deepEqual(log.plays, ["blob:One."], "the second waits for the first to finish");
    lastAudio(log).finish();
    await tick();
    assert.deepEqual(log.plays, ["blob:One.", "blob:Two."]);
    log.fetches[2].reply.resolve(ok("Three."));
    lastAudio(log).finish();
    await tick();
    lastAudio(log).finish();
    assert.equal(await done, "played");
    assert.deepEqual(log.plays, ["blob:One.", "blob:Two.", "blob:Three."]);
    assert.deepEqual(log.events.filter((e) => e === "playing" || e === "done"), ["playing", "done"]);
  },

  async a_newer_turn_cancels_the_older_queue() {
    const { log, audio, ok } = setup();
    audio.beginCall("call-1");
    const old = audio.playQueue(["Old one.", "Old two."], "en", "call-1");
    await tick();
    log.fetches[0].reply.resolve(ok("Old one."));
    await tick();
    const playing = lastAudio(log);
    const fresh = audio.playQueue(["New."], "en", "call-1");
    assert.ok(playing.paused && playing.src === "", "the old sentence is silenced at once");
    assert.ok(log.fetches[1].aborted, "the old turn's pending sentence request is aborted");
    assert.equal(await old, "stopped");
    await tick();
    log.fetches[2].reply.resolve(ok("New."));
    log.fetches[1].reply.resolve(ok("Old two.")); // a late reply for the old turn
    await tick(5);
    assert.deepEqual(log.plays, ["blob:Old one.", "blob:New."], "nothing from the old turn plays after the new one");
    lastAudio(log).finish();
    assert.equal(await fresh, "played");
  },

  async end_call_stops_and_discards_late_audio() {
    const { log, audio, ok } = setup();
    audio.beginCall("call-1");
    const queue = audio.playQueue(["One.", "Two."], "en", "call-1");
    await tick();
    audio.endCall();
    assert.ok(log.fetches[0].aborted);
    log.fetches[0].reply.resolve(ok("One."));
    await tick(5);
    assert.deepEqual(log.plays, []);
    assert.equal(await queue, "discarded");
  },

  async mute_cancels_pending_audio() {
    const { log, audio, ok } = setup();
    audio.beginCall("call-1");
    const queue = audio.playQueue(["One."], "en", "call-1");
    await tick();
    audio.setMuted(true);
    log.fetches[0].reply.resolve(ok("One."));
    await tick(5);
    assert.deepEqual(log.plays, []);
    assert.equal(await queue, "discarded");
  },

  async a_previous_calls_queue_never_plays_into_a_new_call() {
    const { log, audio, ok } = setup();
    audio.beginCall("call-1");
    audio.playQueue(["Old call."], "en", "call-1");
    await tick();
    audio.beginCall("call-2");
    log.fetches[0].reply.resolve(ok("Old call."));
    await tick(5);
    assert.deepEqual(log.plays, []);
  },

  async idle_waits_for_the_current_sentence() {
    const { log, audio, ok } = setup();
    audio.beginCall("call-1");
    audio.playQueue(["Short."], "en", "call-1");
    await tick();
    log.fetches[0].reply.resolve(ok("Short."));
    await tick();
    let idle = false;
    audio.idle(2000).then(() => (idle = true));
    await tick(60);
    assert.equal(idle, false);
    lastAudio(log).finish();
    await tick(60);
    assert.equal(idle, true);
  },
};

(async () => {
  const scenario = process.argv[2];
  if (!scenarios[scenario]) throw new Error("Unknown scenario " + scenario);
  await scenarios[scenario]();
  console.log("ok");
})().catch((error) => {
  console.error(error.stack || String(error));
  process.exitCode = 1;
});
