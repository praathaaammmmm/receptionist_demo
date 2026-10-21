// Real-browser checks for /voice-agent-demo in headless Chromium, run by tests/test_voice_agent_browser.py.
// Usage: node tests/js/voice_agent_browser.js <scenario> <base-url> [extra]  -> prints JSON, exits non-zero on failure.
// [extra] is a screenshot path for layout_390, or the audio file the fake microphone plays for real_transcription.
const assert = require("node:assert/strict");
const path = require("node:path");
const { launch } = require(path.join(__dirname, "cdp.js"));

const [scenario, base, extra] = process.argv.slice(2);
const screenshot = scenario === "layout_390" ? extra : null;
const PAGE = `${base}/voice-agent-demo`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Counts every audio play, End request and message reply; can hold message replies back.
const INSTRUMENT = `(() => {
  const va = window.__va = { plays: [], ends: 0, messages: 0, delay: 0, transcribes: 0, speech: [], speechAborted: 0 };
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function () { va.plays.push({ at: performance.now(), el: this }); return play.call(this); };
  const realFetch = window.fetch.bind(window);
  window.fetch = async (url, options) => {
    const u = String(url);
    if (u.includes("/api/voice-agent-demo/") && u.endsWith("/end")) va.ends += 1;
    if (u.includes("/transcribe")) va.transcribes += 1;
    if (u.endsWith("/api/voice-agent-demo/speech")) {
      const entry = { at: performance.now(), text: JSON.parse(options.body).text };
      va.speech.push(entry);
      if (options.signal) options.signal.addEventListener("abort", () => (va.speechAborted += 1));
    }
    const response = await realFetch(url, options);
    if (u.includes("/message")) { va.messages += 1; if (va.delay) await new Promise((r) => setTimeout(r, va.delay)); }
    return response;
  };
  const beacon = navigator.sendBeacon && navigator.sendBeacon.bind(navigator);
  if (beacon) navigator.sendBeacon = (url, data) => { if (String(url).endsWith("/end")) va.ends += 1; return beacon(url, data); };
})();`;
const DENY_MICROPHONE = `navigator.mediaDevices.getUserMedia = () =>
  Promise.reject(Object.assign(new Error("denied"), { name: "NotAllowedError" }));`;

const logText = "document.getElementById('va-log').innerText";
const botCount = "document.querySelectorAll('#va-log .msg-bot').length";
const state = "window.VoiceAgentDemo.state";

async function open(c, scripts = []) {
  for (const source of [INSTRUMENT, ...scripts]) await c.send("Page.addScriptToEvaluateOnNewDocument", { source });
  await c.goto(PAGE);
}

async function startCall(c) {
  await c.eval("document.getElementById('va-start-btn').click()");
  await c.waitFor(`${state}.active && !${state}.busy`);
}

async function say(c, text) {
  await c.eval(`(() => { const i = document.getElementById('va-input'); i.value = ${JSON.stringify(text)};
    document.getElementById('va-form').requestSubmit(); })()`);
}

const overflow = "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth";

const scenarios = {
  async layout_390(c) {
    await c.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
    await open(c, []);
    assert.equal(await c.eval("window.innerWidth"), 390);
    assert.ok((await c.eval(overflow)) <= 0, "horizontal overflow on load");
    await c.eval("document.querySelector('[data-scenario=urgent]').click()");
    await c.waitFor(`${logText}.includes('112')`);
    await c.eval("document.getElementById('va-settings').open = true");
    assert.ok((await c.eval(overflow)) <= 0, "horizontal overflow during a call");
    const controls = await c.eval(`['va-mic', 'va-end', 'va-input'].map((id) => {
      const r = document.getElementById(id).getBoundingClientRect(); return { id, left: r.left, right: r.right, height: r.height };
    })`);
    for (const box of controls) {
      assert.ok(box.left >= 0 && box.right <= 390, `${box.id} is off screen`);
      assert.ok(box.height >= 40, `${box.id} is too small to tap`);
    }
    if (screenshot) await c.screenshot(screenshot);
    return { overflow: await c.eval(overflow), controls };
  },

  async typed_flow_without_transcription_model(c) {
    await open(c);
    const before = await c.eval(state);
    assert.ok(before.micProblem && before.micProblem.includes("Typed input works fully"));
    assert.ok(await c.eval("document.getElementById('va-mic-note').innerText.includes('not set up')"));
    await startCall(c);
    assert.equal(await c.eval("document.getElementById('va-mic').disabled"), true);
    assert.equal(await c.eval("document.getElementById('va-input').disabled"), false);
    await say(c, "What are your opening hours?");
    await c.waitFor(`${logText}.includes('Monday to Saturday')`);
    return { log: await c.eval(logText) };
  },

  async high_confidence_speech_is_sent_automatically(c) {
    await open(c);
    assert.equal(await c.eval(`${state}.micProblem`), null);
    await startCall(c);
    await c.eval("document.getElementById('va-mic').click()");
    await c.waitFor(`${state}.listening`);
    assert.equal(await c.eval("document.getElementById('va-mic-label').innerText"), "Stop listening");
    assert.equal(await c.eval("document.getElementById('va-audio-status-text').innerText"), "Listening…");
    // No second tap: the turn ends by itself when the speech stops.
    await c.waitFor(`!${state}.listening`, 8000);
    await c.waitFor(`${logText}.includes('Monday to Saturday')`, 10000);
    const user = await c.eval("[...document.querySelectorAll('#va-log .msg-user')].map((m) => m.innerText)");
    const timing = await c.eval("window.VoiceAgentDemo.timing");
    for (const name of ["recording_started", "speech_last_voice", "speech_end_detected", "stt_completed", "intent_started", "intent_completed"]) {
      assert.ok(timing.marks[name] !== undefined, `missing timing mark ${name}`);
    }
    const silenceWait = timing.marks.speech_end_detected - timing.marks.speech_last_voice;
    assert.ok(silenceWait >= 700 && silenceWait <= 1100, `silence detection took ${silenceWait} ms`);
    assert.equal(timing.notes.intent.handled_by, "rule");
    assert.equal(await c.eval("document.getElementById('va-heard').hidden"), true); // no review step
    const panel = await c.eval("document.getElementById('va-timing-list').textContent");
    assert.ok(panel.includes("Speech ended → transcript") && panel.includes("Transcript → answer"));
    return { user, silenceWait, messages: await c.eval("window.__va.messages"), panel };
  },

  async low_confidence_speech_is_held_for_review(c) {
    await open(c);
    await startCall(c);
    await c.eval("document.getElementById('va-mic').click()");
    await c.waitFor(`${state}.listening`);
    await c.waitFor("!document.getElementById('va-heard').hidden", 10000);
    const warning = await c.eval("document.getElementById('va-heard-warning').innerText");
    assert.equal(warning, "I may not have caught that clearly. Please say that again, or type your message.");
    await sleep(500);
    assert.equal(await c.eval("window.__va.messages"), 0, "uncertain speech was sent without review");
    const buttons = await c.eval("['va-heard-send','va-heard-retry','va-heard-typed'].map((id) => document.getElementById(id).innerText)");
    assert.deepEqual(buttons, ["Send this", "Try again", "Type instead"]);
    await c.eval(`(() => { document.getElementById('va-heard-text').value = 'What are your opening hours?';
      document.getElementById('va-heard-send').click(); })()`);
    await c.waitFor(`${logText}.includes('Monday to Saturday')`);
    return { warning, buttons, messages: await c.eval("window.__va.messages") };
  },

  async type_instead_moves_the_transcript_to_the_input(c) {
    await open(c);
    await startCall(c);
    await c.eval("document.getElementById('va-mic').click()");
    await c.waitFor("!document.getElementById('va-heard').hidden", 10000);
    await c.eval("document.getElementById('va-heard-typed').click()");
    assert.equal(await c.eval("document.getElementById('va-heard').hidden"), true);
    assert.equal(await c.eval("document.activeElement.id"), "va-input");
    return { value: await c.eval("document.getElementById('va-input').value"), messages: await c.eval("window.__va.messages") };
  },

  async silence_is_never_uploaded(c) {
    await open(c);
    await startCall(c);
    await c.eval("document.getElementById('va-mic').click()");
    await c.waitFor(`${state}.listening`);
    await c.waitFor(`!${state}.listening`, 9000);
    const note = await c.eval("document.getElementById('va-mic-note').innerText");
    assert.ok(note.startsWith("I didn't hear anything"), note);
    return { note, transcribes: await c.eval("window.__va.transcribes") };
  },

  async microphone_permission_denied_keeps_typing(c) {
    await open(c, [DENY_MICROPHONE]);
    await startCall(c);
    await c.eval("document.getElementById('va-mic').click()");
    await c.waitFor("document.getElementById('va-mic-note').innerText.includes('permission was denied')");
    const note = await c.eval("document.getElementById('va-mic-note').innerText");
    assert.equal(await c.eval(`${state}.listening`), false);
    await say(c, "Where are you located?");
    await c.waitFor(`${logText}.includes('Pragati Public School')`);
    return { note };
  },

  async end_while_transcribing_drops_the_transcript(c) {
    await open(c);
    await startCall(c);
    await c.eval("document.getElementById('va-mic').click()");
    await c.waitFor(`${state}.understanding`, 8000);
    assert.equal(await c.eval("document.getElementById('va-audio-status-text').innerText"), "I heard you. Understanding…");
    await c.eval("document.getElementById('va-end').click()");
    await sleep(2000); // the server's transcription finishes after the end
    const after = await c.eval(`({ heardHidden: document.getElementById('va-heard').hidden, messages: window.__va.messages,
      state: ${state}, ends: window.__va.ends, users: document.querySelectorAll('#va-log .msg-user').length })`);
    assert.ok(after.heardHidden, "a transcript appeared after End");
    assert.equal(after.messages, 0);
    assert.equal(after.users, 0);
    assert.ok(after.state.ended && !after.state.understanding && !after.state.listening);
    assert.equal(after.ends, 1);
    return after;
  },

  async new_turn_cancels_older_audio(c) {
    await open(c);
    await startCall(c);
    await c.waitFor(`${state}.speaking`, 20000); // the greeting is playing
    const t = await c.eval(`(() => { const i = document.getElementById('va-input'); i.value = 'What are your opening hours?';
      document.getElementById('va-form').requestSubmit(); return performance.now(); })()`);
    const atSend = await c.eval("window.__va.plays.every((p) => p.el.paused)");
    await c.waitFor(`${logText}.includes('Monday to Saturday')`);
    await sleep(2500);
    const speech = await c.eval(`window.__va.speech.filter((r) => r.at > ${t}).map((r) => r.text)`);
    const greetingAfter = speech.filter((text) => /calling|automated assistant|recording|logged|help you today/i.test(text));
    assert.ok(atSend, "the greeting kept playing after a new turn");
    assert.deepEqual(greetingAfter, [], "greeting audio was requested after the new turn");
    return { speech, aborted: await c.eval("window.__va.speechAborted") };
  },

  async end_call_while_speaking_is_silent_at_once(c) {
    await open(c);
    await startCall(c);
    await c.waitFor(`${state}.speaking`, 20000);
    const result = await c.eval(`(() => { const t = performance.now(); document.getElementById('va-end').click();
      return { t, paused: window.__va.plays.every((p) => p.el.paused && !p.el.getAttribute('src')) }; })()`);
    await sleep(1500);
    const playsAfter = await c.eval(`window.__va.plays.filter((p) => p.at > ${result.t}).length`);
    assert.ok(result.paused && playsAfter === 0);
    return { playsAfter, ends: await c.eval("window.__va.ends") };
  },

  async real_transcription(c) {
    const language = process.env.VA_LANGUAGE || "en";
    await open(c);
    await c.eval(`document.querySelector('input[name=va-language][value=${language}]').click()`);
    await startCall(c);
    await c.eval("document.getElementById('va-mic').click()");
    await c.waitFor(`${state}.listening`);
    // The turn ends by itself after the speech; then either the reply arrives, or (low confidence) the review.
    await c.waitFor(`window.VoiceAgentDemo.timing.marks.stt_completed !== undefined`, 30000);
    await c.waitFor(`window.VoiceAgentDemo.timing.marks.intent_completed !== undefined || !document.getElementById('va-heard').hidden`, 30000);
    await c.waitFor(`window.VoiceAgentDemo.timing.marks.audio_first_played !== undefined || !document.getElementById('va-heard').hidden`, 30000);
    const users = await c.eval("[...document.querySelectorAll('#va-log .msg-user')].map((m) => m.innerText)");
    const heard = users.length ? users[users.length - 1] : await c.eval("document.getElementById('va-heard-text').value");
    return { heard, review: await c.eval("!document.getElementById('va-heard').hidden"),
             transcript: await c.eval("document.getElementById('va-f-transcript').textContent"),
             timing: await c.eval("window.VoiceAgentDemo.timing"),
             reply: await c.eval("[...document.querySelectorAll('#va-log .msg-bot')].slice(-2).map((m) => m.innerText).join(' / ')") };
  },

  async reference_voice_fallback_is_announced(c) {
    await open(c);
    assert.equal(await c.eval("document.querySelector('input[name=va-voice]:checked').value"), "standard");
    await c.eval("document.querySelector('input[name=va-voice][value=reference]').click()");
    await startCall(c);
    await c.waitFor(`${state}.speaking`, 20000);
    const notice = await c.eval("document.getElementById('va-voice-notice').hidden ? null : document.getElementById('va-voice-notice').innerText");
    const status = await c.eval("document.getElementById('va-audio-status-text').innerText");
    assert.equal(notice, "Reference voice is unavailable for this reply. Using the standard local voice.");
    assert.equal(status, "Speaking (standard voice)"); // never claimed as the reference voice
    assert.equal(await c.eval(`${state}.spokenBy`), "fallback");
    await c.eval("document.getElementById('va-end').click()");
    return { notice, status };
  },

  async end_call_silences_audio_immediately(c) {
    await open(c, []);
    await startCall(c);
    await c.waitFor(`${state}.playing && ${state}.speaking`, 20000); // the greeting is being heard
    const atEnd = await c.eval(`(() => {
      const t = performance.now();
      document.getElementById('va-end').click();
      const audios = window.__va.plays.map((p) => p.el);
      return { t, paused: audios.every((a) => a.paused), sources: audios.map((a) => a.getAttribute('src')),
               status: document.getElementById('va-audio-status-text').innerText, playing: ${state}.playing };
    })()`);
    assert.ok(atEnd.paused, "audio still playing right after End");
    assert.ok(atEnd.sources.every((s) => !s), "audio source not released");
    assert.equal(atEnd.playing, false);
    assert.equal(atEnd.status, "Call ended");
    await sleep(1500);
    const later = await c.eval(`({ playsAfter: window.__va.plays.filter((p) => p.at > ${atEnd.t}).length,
      ends: window.__va.ends, inputDisabled: document.getElementById('va-input').disabled,
      micDisabled: document.getElementById('va-mic').disabled, endDisabled: document.getElementById('va-end').disabled })`);
    assert.equal(later.playsAfter, 0, "audio played after End");
    assert.equal(later.ends, 1);
    assert.ok(later.inputDisabled && later.micDisabled && later.endDisabled);
    return { atEnd, later };
  },

  async late_reply_never_appears_after_end(c) {
    await open(c, []);
    await startCall(c);
    const bots = await c.eval(botCount);
    await c.eval("window.__va.delay = 1500");
    const t = await c.eval(`(() => {
      const i = document.getElementById('va-input'); i.value = 'What are your opening hours?';
      document.getElementById('va-form').requestSubmit();
      const t = performance.now();
      document.getElementById('va-end').click();
      return t;
    })()`);
    await sleep(2500);
    const after = await c.eval(`({ bots: ${botCount}, log: ${logText}, plays: window.__va.plays.filter((p) => p.at > ${t}).length,
      messages: window.__va.messages, ends: window.__va.ends, state: ${state} })`);
    assert.ok(after.messages <= 1); // End now aborts the request; either way nothing may appear
    assert.equal(after.bots, bots, "a reply appeared after End");
    assert.ok(!after.log.includes("Monday to Saturday"));
    assert.equal(after.plays, 0);
    assert.equal(after.ends, 1);
    assert.ok(after.state.ended && !after.state.active);
    return after;
  },

  async language_choice_persists(c) {
    await open(c, []);
    await c.eval("document.querySelector('input[name=va-language][value=hi]').click()");
    await c.goto(PAGE);
    const checked = await c.eval("document.querySelector('input[name=va-language]:checked').value");
    assert.equal(checked, "hi");
    await startCall(c);
    await c.waitFor(`${logText}.includes('धन्यवाद')`);
    return { checked };
  },
};

// Microphone scenarios get Chromium's fake microphone playing the given audio file (speech, then silence).
const fakeMicrophone = () => ["--use-fake-device-for-media-stream", ...(extra ? [`--use-file-for-fake-audio-capture=${extra}`] : [])];
const MICROPHONE_SCENARIOS = new Set(["high_confidence_speech_is_sent_automatically", "low_confidence_speech_is_held_for_review",
  "type_instead_moves_the_transcript_to_the_input", "silence_is_never_uploaded", "end_while_transcribing_drops_the_transcript",
  "microphone_permission_denied_keeps_typing", "real_transcription"]);

(async () => {
  const args = MICROPHONE_SCENARIOS.has(scenario) ? fakeMicrophone() : [];
  const c = await launch({ args });
  try {
    if (!scenarios[scenario]) throw new Error("Unknown scenario " + scenario);
    const result = await scenarios[scenario](c);
    console.log(JSON.stringify({ ok: true, result }));
  } catch (error) {
    console.error(error.stack || String(error));
    process.exitCode = 1;
  } finally {
    c.close();
  }
})();
