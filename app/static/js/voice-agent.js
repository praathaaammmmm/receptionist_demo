// Browser voice agent demo. The server decides everything a call says (app/voice_agent policy);
// this page only captures the caller's words, shows the reply and plays its local Piper audio.
// The microphone records one phrase per turn and stops by itself when the caller goes quiet; this
// demo server transcribes it in memory and never stores it. Clear transcripts are sent at once;
// uncertain ones are shown for review and never acted on until the caller confirms them.
// All playback and cancellation go through call-audio.js. Every turn has its own id, and nothing
// from an older turn or an ended call can appear or be heard.
(function () {
  const $ = (id) => document.getElementById(id);
  const config = JSON.parse($("va-config").textContent);
  const LANGS = Object.fromEntries(config.languages.map((l) => [l.code, l]));
  const SCENARIOS = Object.fromEntries(config.scenarios.map((s) => [s.id, s]));
  const LANGUAGE_KEY = "smriti.voiceAgent.language";
  const now = () => performance.now();
  // Voice activity detection (browser side, audio level only).
  const VAD = { frameMs: 30, calibrateMs: 240, minSpeechMs: 150, minVoicedMs: 250, silenceMs: 800, noSpeechMs: 6000 };
  const ACK_AFTER_MS = 1200; // "One moment, please." only if the reply is still being worked on by then
  const PATH_LABELS = {
    greeting: "Greeting",
    answer: "Approved answer",
    unknown: "Unknown information: no guess, callback offered",
    panel: "Panel enquiry: panel callback",
    clinical: "Clinical question: no advice, callback offered",
    tooth_pain: "Tooth pain: appointment callback offered",
    emergency: "URGENT: 112 instruction given",
    human_request: "Asked for a person",
    callback_request: "Asked for a callback",
    closing: "Closing the call",
    low_confidence: "Unclear speech: not acted on",
  };
  const TOPIC_LABELS = {
    appointment_request: "Appointment enquiry: appointment callback only (no live booking)",
    appointment_availability: "Appointment enquiry: appointment callback only (no live booking)",
    doctor_schedule: "Doctor schedule unknown: no guess, appointment callback offered",
    treatment_cost: "Treatment price: never quoted, callback offered",
  };
  const OUTCOME_LABELS = {
    CALLBACK_CREATED: "Callback created",
    FAQ_ANSWERED: "Question answered",
    ENDED: "Ended",
  };

  const log = $("va-log");
  const input = $("va-input");
  const form = $("va-form");
  const sendButton = $("va-send");
  const micButton = $("va-mic");
  const endButton = $("va-end");
  const startButton = $("va-start-btn");
  const muteButton = $("va-mute");
  const replayButton = $("va-replay");
  const radios = [...document.querySelectorAll('input[name="va-language"]')];
  const settings = { transfer: $("va-set-transfer"), caller_id: $("va-set-caller"), clinic: $("va-set-clinic") };

  let language = readLanguage();
  let sessionId = null;
  let callToken = null; // client-side id of the active call; replies for any other call are dropped
  let callSeq = 0;
  let turnId = null; // client-side id of the newest caller turn; anything for an older turn is dropped
  let turnSeq = 0;
  let active = false; // a call is in progress and accepts input
  let ended = false; // the last call has ended
  let busy = false; // waiting for the conversation's reply
  let speaking = false;
  let preparing = false; // fetching the first sentence of a reply's audio
  let listening = false;
  let understanding = false; // the recording is being transcribed
  let acknowledging = false; // "One moment, please." is showing
  let muted = false;
  let lastSpeech = null;
  let endPromise = null;
  let startedAt = 0;
  let ticker = null;
  let messageRequest = null; // AbortController of the in-flight message
  let ackTimer = null;
  let timing = null; // marks for the current turn only; shown on the page, never sent or stored
  // Demo-only: the consented reference voice, offered only when the server says it is ready. Default: standard.
  let voiceMode = "standard";
  let spokenBy = null; // the voice that actually spoke the latest sentence: "reference", "standard" or "fallback"
  const voiceOk = Object.fromEntries(config.languages.map((l) => [l.code, l.voice.available]));

  // --- Small helpers -------------------------------------------------------------------------
  function el(tag, props, ...children) {
    const node = Object.assign(document.createElement(tag), props || {});
    node.append(...children);
    return node;
  }

  function readLanguage() {
    try {
      const saved = window.localStorage.getItem(LANGUAGE_KEY);
      if (saved && LANGS[saved]) return saved;
    } catch (_) {
      /* storage blocked: default to English */
    }
    return "en";
  }

  function saveLanguage(code) {
    try {
      window.localStorage.setItem(LANGUAGE_KEY, code);
    } catch (_) {
      /* storage blocked: the choice still applies to this visit */
    }
  }

  async function post(path, body, signal) {
    let response;
    try {
      response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
        signal,
      });
    } catch (error) {
      if (error.name === "AbortError") throw error;
      throw new Error("Could not reach the demo server. Please check it is running.");
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.message || "Something went wrong. Please try again.");
      error.code = data.error;
      throw error;
    }
    return data;
  }

  function scrollDown() {
    log.scrollTop = log.scrollHeight;
  }

  function addMessage(kind, text, lang) {
    const empty = $("va-empty");
    if (empty) empty.remove();
    const node = el("p", { className: "msg " + kind, textContent: text });
    if (lang) node.lang = lang;
    log.append(node);
    scrollDown();
    return node;
  }

  // An approved fixed line ("One moment, please." and the low-confidence retry), as shown and as spoken.
  function phrase(key) {
    return config.phrases[key][language];
  }

  // --- Turn timing (developer panel, this turn only) -------------------------------------------
  function newTurn(kind) {
    turnId = `${callToken}:${++turnSeq}`;
    timing = { kind, marks: {}, notes: {} };
    return turnId;
  }

  function mark(name, value) {
    if (timing && timing.marks[name] === undefined) timing.marks[name] = value === undefined ? now() : value;
    renderTiming();
  }

  function note(name, value) {
    if (timing) timing.notes[name] = value;
    renderTiming();
  }

  function renderTiming() {
    const list = $("va-timing-list");
    if (!list || !timing) return;
    const m = timing.marks;
    const n = timing.notes;
    const ms = (a, b) => (m[a] !== undefined && m[b] !== undefined ? `${Math.round(m[b] - m[a])} ms` : "…");
    const rows = [];
    if (timing.kind === "voice") {
      rows.push(["Speech ended → silence detected", ms("speech_last_voice", "speech_end_detected")]);
      rows.push(["Speech ended → transcript", ms("speech_last_voice", "stt_completed")
        + (n.stt ? ` (server ${n.stt.server_ms} ms: decode ${n.stt.decode_ms}, model ${n.stt.stt_ms})` : "")]);
    }
    rows.push(["Transcript → answer", ms(timing.kind === "voice" ? "stt_completed" : "intent_started", "intent_completed")
      + (n.intent ? ` (${n.intent.handled_by}, server ${n.intent.intent_ms} ms)` : "")]);
    rows.push(["Answer → audio ready", ms("intent_completed", "tts_completed")
      + (n.tts ? ` (synthesis ${n.tts.serverMs} ms, ${n.tts.cache === "hit" ? "cached phrase" : "generated"})` : "")]);
    rows.push(["Answer → audio playing", ms("intent_completed", "audio_first_played")]);
    if (timing.kind === "voice") rows.push(["Speech ended → audio playing", ms("speech_last_voice", "audio_first_played")]);
    list.textContent = "";
    for (const [label, value] of rows) list.append(el("li", {}, el("span", { textContent: label }), el("strong", { textContent: value })));
  }

  // --- Audio ---------------------------------------------------------------------------------
  const audio = window.CallAudio.create({
    fetch: (...args) => window.fetch(...args),
    makeAudio: () => new Audio(),
    makeUtterance: () => null,
    synth: null, // local Piper voices only: a missing pack means text only, never another voice
    speechUrl: "/api/voice-agent-demo/speech",
    now,
    createObjectURL: (blob) => URL.createObjectURL(blob),
    revokeObjectURL: (url) => URL.revokeObjectURL(url),
    setTimeout: (fn, ms) => window.setTimeout(fn, ms),
    clearTimeout: (id) => window.clearTimeout(id),
    AbortController: window.AbortController,
    hooks: {
      onPreparing() {
        preparing = true;
        showStatus();
      },
      onPartReady(index, result) {
        if (index === 0 && !acknowledging) {
          mark("tts_completed");
          note("tts", result);
        }
        spokenBy = result.voiceMode || "standard";
        if (spokenBy === "fallback") {
          // Never presented as the reference voice: say plainly that the standard voice is speaking.
          const notice = $("va-voice-notice");
          notice.textContent = config.referenceVoice.fallbackMessage;
          notice.hidden = false;
        }
        showStatus();
      },
      onPlaying() {
        preparing = false;
        speaking = true;
        if (!acknowledging) mark("audio_first_played");
        showStatus();
      },
      onDone() {
        speaking = preparing = false;
        showStatus();
      },
      onStopped() {
        speaking = preparing = false;
      },
      onUnavailable(code) {
        preparing = speaking = false;
        voiceOk[code] = false;
        showStatus();
      },
      onNotAllowed() {
        preparing = speaking = false;
        showStatus("The browser blocked audio. Click Replay to hear the last response.");
      },
      onFailed() {
        preparing = speaking = false;
        showStatus("The voice could not play. The conversation continues as text.");
      },
    },
  });

  function speak(speech) {
    if (!speech || !speech.text || muted || !voiceOk[speech.language]) return Promise.resolve("skipped");
    mark("tts_started");
    $("va-voice-notice").hidden = true;
    return audio.playQueue(speech.parts && speech.parts.length ? speech.parts : [speech.text], speech.language, callToken,
                           undefined, { voice: voiceMode });
  }

  // --- Microphone: one phrase per turn, ended by silence, transcribed on this demo server ----------
  const canRecord = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  let micProblem = null;
  if (!config.microphone.available) {
    micProblem = "Microphone transcription is not set up on this demo server (the speech-to-text model is not installed). Typed input works fully.";
  } else if (!canRecord || !AudioContextClass) {
    micProblem = "This browser cannot record audio here. Typed input works fully.";
  }
  let capture = null; // { recorder, stream, context, timer, chunks, discard }
  let transcribeRequest = null;
  let heardOriginal = "";
  const DEFAULT_MIC_NOTE = $("va-mic-note").textContent;

  function showMicNote(text, warning) {
    const box = $("va-mic-note");
    box.textContent = text;
    box.classList.toggle("is-warning", !!warning);
  }

  function closeCapture() {
    if (!capture) return;
    const c = capture;
    capture = null;
    window.clearInterval(c.timer);
    if (c.recorder.state !== "inactive") c.recorder.stop();
    for (const track of c.stream.getTracks()) track.stop();
    if (c.context && c.context.state !== "closed") c.context.close().catch(() => {});
  }

  // Stop recording and transcribing at once; whatever was recorded is dropped unsent.
  function stopListening() {
    if (capture) capture.discard = true;
    closeCapture();
    if (transcribeRequest) transcribeRequest.abort();
    transcribeRequest = null;
    if (listening || understanding) {
      listening = understanding = false;
      showStatus();
    }
  }

  function clearHeard() {
    heardOriginal = "";
    $("va-heard").hidden = true;
    $("va-heard-warning").hidden = true;
    $("va-heard-text").value = "";
  }

  // Low confidence only: show the transcript for review. Nothing is sent until the caller chooses.
  function reviewHeard(data) {
    heardOriginal = data.text || "";
    $("va-heard").hidden = false;
    const box = $("va-heard-text");
    box.value = heardOriginal;
    box.lang = LANGS[language].html_lang;
    const warning = $("va-heard-warning");
    warning.hidden = false;
    warning.textContent = phrase("low_confidence_retry").text;
    box.focus({ preventScroll: true });
  }

  function describeTranscript(data) {
    $("va-heard-meta").textContent = `Transcribed in ${data.processing_seconds.toFixed(2)}s from ${data.audio_seconds.toFixed(1)}s of audio · ${data.model} on ${data.device} · not stored`;
    $("va-f-transcript").textContent = `"${data.text || "(nothing heard)"}" · confidence ${Math.round(data.confidence * 100)}%`
      + `${data.low_confidence ? " (low)" : ""} · ${data.detected_language || data.language}${data.script ? `, ${data.script} script` : ""}`
      + ` · ${data.processing_seconds.toFixed(2)}s`;
  }

  const PERMISSION_MESSAGES = {
    NotAllowedError: "Microphone permission was denied. Allow the microphone for this site in the address bar, then tap to speak again, or type instead.",
    SecurityError: "The browser blocked the microphone on this page. Open the demo on localhost, or type instead.",
    NotFoundError: "No microphone was found. Connect one and try again, or type instead.",
    NotReadableError: "The microphone is in use by another app. Close it and try again, or type instead.",
  };

  async function startListening() {
    if (micProblem || !active || busy || understanding) return;
    if (listening) return finishCapture("button");
    clearHeard();
    audio.stop(); // the caller is talking: the assistant stops
    const token = newTurn("voice");
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
    } catch (error) {
      showMicNote(PERMISSION_MESSAGES[error.name] || "The microphone could not start. Typed input works fully.", true);
      return;
    }
    if (token !== turnId || !active) {
      for (const track of stream.getTracks()) track.stop();
      return;
    }
    const type = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm", "audio/mp4"].find(
      (t) => window.MediaRecorder.isTypeSupported && window.MediaRecorder.isTypeSupported(t)) || "";
    let recorder;
    let context;
    try {
      recorder = new window.MediaRecorder(stream, type ? { mimeType: type } : undefined);
      context = new AudioContextClass();
      if (context.state === "suspended") await context.resume();
    } catch (_) {
      for (const track of stream.getTracks()) track.stop();
      showMicNote("The microphone could not start. Typed input works fully.", true);
      return;
    }
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    context.createMediaStreamSource(stream).connect(analyser);
    const samples = new Float32Array(analyser.fftSize);
    const c = { recorder, stream, context, chunks: [], discard: false, timer: null };
    const started = now();
    let floor = 0;
    let calibrationFrames = 0;
    let voicedMs = 0;
    let speechStarted = false;
    let lastVoice = 0;
    recorder.ondataavailable = (event) => {
      if (event.data && event.data.size) c.chunks.push(event.data);
    };
    recorder.onstop = () => {
      if (c.discard || token !== turnId) return;
      transcribe(token, new Blob(c.chunks, { type: recorder.mimeType || type || "audio/webm" }));
    };
    c.timer = window.setInterval(() => {
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (const v of samples) sum += v * v;
      const level = Math.sqrt(sum / samples.length);
      const t = now();
      if (t - started < VAD.calibrateMs) {
        floor = (floor * calibrationFrames + level) / (calibrationFrames + 1);
        calibrationFrames += 1;
        return;
      }
      const threshold = Math.max(0.012, floor * 3);
      if (level > threshold) {
        voicedMs += VAD.frameMs;
        lastVoice = t;
        if (!speechStarted && voicedMs >= VAD.minSpeechMs) {
          speechStarted = true;
          mark("speech_started", t);
        }
      } else if (speechStarted && t - lastVoice >= VAD.silenceMs) {
        finishCapture("silence", lastVoice, voicedMs);
      }
      if (!speechStarted && t - started >= VAD.noSpeechMs) finishCapture("no-speech", lastVoice, voicedMs);
      else if (t - started >= config.maxRecordSeconds * 1000) finishCapture("limit", lastVoice || t, voicedMs);
    }, VAD.frameMs);
    c.finish = { voiced: () => voicedMs, last: () => lastVoice };
    capture = c;
    recorder.start();
    listening = true;
    mark("recording_started", started);
    showMicNote("Listening… speak now. It stops by itself when you pause. Microphone transcription is processed by this demo server and is not stored.");
    showStatus();
  }

  // End the capture: by silence, the time limit, or "Stop listening". Near-silent recordings are never sent.
  function finishCapture(reason, lastVoice, voicedMs) {
    const c = capture;
    if (!c) return;
    const voiced = voicedMs !== undefined ? voicedMs : c.finish.voiced();
    const last = lastVoice !== undefined ? lastVoice : c.finish.last();
    if (voiced < VAD.minVoicedMs) {
      c.discard = true;
      closeCapture();
      listening = false;
      showMicNote(reason === "no-speech" ? "I didn't hear anything. Tap to speak and try again, or type instead."
        : "That was too quiet to send. Tap to speak and try again, or type instead.", true);
      showStatus();
      return;
    }
    mark("speech_last_voice", last || now());
    mark("speech_end_detected");
    closeCapture(); // the recorder's onstop sends the audio for transcription
    listening = false;
    understanding = true;
    showStatus();
  }

  async function transcribe(token, blob) {
    if (token !== turnId || ended) return;
    const controller = new AbortController();
    transcribeRequest = controller;
    mark("upload_started");
    let data;
    try {
      const response = await fetch(`/api/voice-agent-demo/transcribe?language=${encodeURIComponent(language)}`, {
        method: "POST",
        headers: { "Content-Type": blob.type || "application/octet-stream" },
        body: blob,
        signal: controller.signal,
      });
      data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.message || "The recording could not be transcribed. Please try again or type instead.");
    } catch (error) {
      if (token !== turnId || error.name === "AbortError") return;
      understanding = false;
      if (transcribeRequest === controller) transcribeRequest = null;
      showMicNote(error.message, true);
      showStatus();
      return;
    }
    if (transcribeRequest === controller) transcribeRequest = null;
    if (token !== turnId || ended) return; // a newer turn, or the call ended while transcribing
    understanding = false;
    mark("stt_completed");
    note("stt", data.timings || {});
    describeTranscript(data);
    if (data.low_confidence || !data.text) {
      // Never acted on automatically: the caller reviews it, tries again or types.
      reviewHeard(data);
      addMessage("msg-bot", phrase("low_confidence_retry").text, LANGS[language].html_lang);
      const retry = phrase("low_confidence_retry");
      speak({ text: retry.speech, parts: retry.parts, language: retry.voice_language });
      showStatus();
      return;
    }
    send(data.text, { heard: data.text, confidence: "high", turn: token });
  }

  // --- Status and controls -------------------------------------------------------------------
  function audioState() {
    if (ended) return ["ended", "Call ended"];
    if (!active) return ["idle", "Audio starts with the call"];
    if (listening) return ["listening", "Listening…"];
    if (understanding) return ["understanding", "I heard you. Understanding…"];
    if (busy) return ["thinking", acknowledging ? phrase("one_moment").text : "Thinking…"];
    if (preparing) return ["preparing", "Preparing voice…"];
    if (speaking) {
      return ["speaking", spokenBy === "reference" ? "Speaking (reference voice)"
        : voiceMode === "reference" ? "Speaking (standard voice)" : "Speaking"];
    }
    if (!voiceOk[language]) return ["text-only", "Voice unavailable, text only"];
    if (muted) return ["muted", "Muted"];
    return ["ready", "Waiting for the caller"];
  }

  function showStatus(notice) {
    const [state, text] = audioState();
    $("va-audio-status").dataset.state = state;
    $("va-audio-status-text").textContent = text;
    const callStatus = $("va-call-status");
    callStatus.dataset.state = active ? "live" : ended ? "ended" : "idle";
    $("va-call-status-text").textContent = active ? "Call in progress" : ended ? "Call ended" : "Not in a call";
    if (notice) showMicNote(notice, true);
    showControls();
  }

  function showControls() {
    const canTalk = active && !busy;
    input.disabled = sendButton.disabled = !canTalk;
    micButton.disabled = !canTalk || !!micProblem || understanding;
    micButton.setAttribute("aria-pressed", listening ? "true" : "false");
    micButton.dataset.stage = listening ? "listening" : understanding ? "transcribing" : "idle";
    $("va-mic-label").textContent = listening ? "Stop listening" : understanding ? "Understanding…" : "Tap to speak";
    for (const id of ["va-heard-send", "va-heard-retry"]) $(id).disabled = !canTalk;
    $("va-heard-retry").hidden = !!micProblem;
    endButton.disabled = !active;
    startButton.hidden = active;
    startButton.textContent = ended ? "Start another demo call" : "Start demo call";
    for (const select of Object.values(settings)) select.disabled = active;
    replayButton.disabled = !active || !lastSpeech || !voiceOk[language] || muted;
    for (const button of document.querySelectorAll("[data-scenario]")) button.disabled = busy;
    muteButton.setAttribute("aria-pressed", muted ? "true" : "false");
    $("va-mute-label").textContent = muted ? "Unmute voice" : "Mute voice";
    const voice = LANGS[language].voice;
    $("va-voice-name").textContent = voiceOk[language]
      ? `Local voice: ${voice.label} (${voice.voice}), generated on this computer`
      : config.voiceMissing;
    if (micProblem) showMicNote(micProblem, true);
  }

  function setLanguage(code) {
    if (!LANGS[code]) return;
    language = code;
    saveLanguage(code);
    for (const radio of radios) radio.checked = radio.value === code;
    $("va-f-language").textContent = { en: "English", hi: "Hindi", hinglish: "Hinglish" }[code];
    $("va-lang-now").textContent = { en: "English", hi: "हिंदी", hinglish: "Hinglish" }[code];
    if (listening || understanding) stopListening();
    showStatus();
  }

  function tick() {
    const seconds = Math.floor((Date.now() - startedAt) / 1000);
    $("va-timer").textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  }

  // --- Clinic team panel ---------------------------------------------------------------------
  function renderTeam(data) {
    const caller = data.caller || {};
    $("va-f-name").textContent = caller.name || "Not given yet";
    $("va-f-phone").textContent = caller.phone ? `${caller.phone} · ${caller.phone_status}` : `Not given yet · ${caller.phone_status || "caller ID unknown"}`;
    $("va-f-language").textContent = { en: "English", hi: "Hindi", hinglish: "Hinglish" }[data.language];
    $("va-f-reason").textContent = data.detected_reason || "None yet";
    $("va-f-state").textContent = data.state_label;
    const path = data.decision && data.decision.path;
    const pathNode = $("va-f-path");
    if (path) pathNode.textContent = TOPIC_LABELS[data.decision.topic] || PATH_LABELS[path] || path;
    pathNode.classList.toggle("is-urgent", path === "emergency");
    if (data.decision && data.decision.source_label) {
      $("va-f-source").textContent = data.decision.source_label;
      $("va-f-source").classList.toggle("is-urgent", data.decision.source === "emergency_escalation");
    }
    if (data.decision && data.decision.engine_note) $("va-f-engine").textContent = data.decision.engine_note;
    if (data.lead) {
      $("va-f-lead").textContent = [data.lead.patient_type, data.lead.doctor && `Preferred doctor: ${data.lead.doctor}`,
        data.lead.time && `Preferred time: ${data.lead.time}`].filter(Boolean).join(" · ");
    }
    const transfer = data.transfer;
    $("va-f-transfer").textContent = !transfer
      ? "Not requested"
      : transfer.attempted
        ? "Attempted · no answer (simulated) · switched to callback details"
        : "Not available · went straight to callback details";
    if (data.callbacks && data.callbacks.length) {
      const last = data.callback_created || data.callbacks[data.callbacks.length - 1];
      const node = $("va-f-callback");
      node.textContent = "";
      const link = el("a", { href: last.href, textContent: `${last.reference} · open in callback queue` });
      link.dataset.leaveGuard = "";
      node.append(link);
      node.append(` · ${last.category_label}`);
      node.classList.toggle("is-urgent", !!last.urgent);
    }
    $("va-f-outcome").textContent = data.call_log_id
      ? `${OUTCOME_LABELS[data.outcome] || data.outcome} · logged in call activity`
      : data.outcome ? `${OUTCOME_LABELS[data.outcome] || data.outcome} so far · logged when the call ends` : "Not logged yet";

    for (const link of data.links || []) {
      const node = document.querySelector(`[data-link="${link.id}"]`);
      if (node) {
        node.href = link.href;
        node.hidden = false;
      }
    }
    const result = $("va-result");
    if (data.callback_created) {
      result.hidden = false;
      $("va-result-text").textContent = `Callback task ${data.callback_created.reference} created for the front desk (${data.callback_created.category_label}).`;
      $("va-view-dashboard").href = data.callback_created.href;
    } else if (data.call_log_id) {
      result.hidden = false;
      $("va-result-text").textContent = `Call logged in the dashboard's call activity (${OUTCOME_LABELS[data.outcome] || data.outcome}).`;
      $("va-view-dashboard").href = data.callbacks && data.callbacks.length ? data.callbacks[0].href : "/#call-activity";
    }
  }

  function renderContext(context) {
    const sim = context.simulation;
    const parts = [
      context.now_ist,
      `clinic ${context.clinic_open_now ? "open" : "closed"}${sim.clinic !== "auto" ? " (simulated)" : ""}`,
      `transfer ${context.transfer_available ? "available" : "unavailable"}${sim.transfer !== "auto" || sim.clinic !== "auto" ? " (simulated)" : ""}`,
      `caller ID ${context.caller_number_available ? "present (sample, not read out)" : "unknown"}`,
    ];
    const box = $("va-context");
    box.textContent = "This call: " + parts.join(" · ");
    box.hidden = false;
  }

  function resetTeam() {
    for (const [id, text] of [["va-f-name", "Not given yet"], ["va-f-phone", "Not given yet"], ["va-f-reason", "None yet"],
      ["va-f-state", "No call in progress"], ["va-f-path", "None yet"], ["va-f-source", "None yet"],
      ["va-f-lead", "Not collected"], ["va-f-transfer", "Not requested"],
      ["va-f-callback", "None"], ["va-f-outcome", "Not logged yet"]]) {
      $(id).textContent = text;
      $(id).classList.remove("is-urgent");
    }
    $("va-result").hidden = true;
    document.querySelector('[data-link="timeline"]').hidden = true;
    document.querySelector('[data-link="callbacks"]').href = "/#callback-tasks";
  }

  // --- The call ------------------------------------------------------------------------------
  async function render(data, token) {
    if (token !== turnId) return; // an older turn, or the call ended while this reply was on its way
    const lang = LANGS[data.language].html_lang;
    for (const m of data.messages) {
      const kind = data.decision && data.decision.path === "emergency" && m.text.includes("112") ? "msg-bot msg-emergency" : "msg-bot";
      addMessage(kind, m.text, lang);
    }
    renderTeam(data);
    if (data.speech) lastSpeech = data.speech;
    if (data.ended) finishLocally(data, false);
    showStatus();
    speak(data.speech);
  }

  async function startCall() {
    if (active || busy) return;
    clearHeard();
    log.textContent = "";
    resetTeam();
    endPromise = null;
    lastSpeech = null;
    ended = false;
    busy = true;
    const call = `va-${++callSeq}`;
    callToken = call;
    audio.beginCall(call);
    const token = newTurn("start");
    mark("intent_started");
    showStatus();
    const body = { language };
    for (const [key, select] of Object.entries(settings)) body[key] = select.value;
    let data;
    try {
      data = await post("/api/voice-agent-demo/start", body);
    } catch (error) {
      if (call !== callToken) return;
      busy = false;
      callToken = null;
      addMessage("msg-notice", error.message);
      showStatus();
      return;
    }
    if (call !== callToken) {
      post(`/api/voice-agent-demo/${data.session_id}/end`).catch(() => {}); // ended before it began
      return;
    }
    mark("intent_completed");
    sessionId = data.session_id;
    busy = false;
    active = true;
    startedAt = Date.now();
    tick();
    ticker = window.setInterval(tick, 1000);
    $("va-settings").open = false; // settings are fixed for the call; keep the transcript in view
    renderContext(data.context);
    render(data, token);
    if (window.matchMedia("(max-width: 720px)").matches) $("va-log").scrollIntoView({ block: "start" });
    else input.focus({ preventScroll: true });
  }

  // One caller turn. Typed text, or a transcript: high confidence is sent as is; low confidence only
  // after the caller reviews it (reviewed: true), and the server refuses to act on it otherwise.
  async function send(text, options = {}) {
    text = (text || "").trim();
    if (!text || !active || busy) return;
    clearHeard();
    if (listening || understanding) stopListening();
    audio.stop(); // a new caller turn replaces anything still being said
    const token = options.turn && options.turn === turnId ? options.turn : newTurn("typed");
    if (!micProblem) showMicNote(DEFAULT_MIC_NOTE);
    addMessage("msg-user", text, LANGS[language].html_lang);
    input.value = "";
    busy = true;
    mark("intent_started");
    showStatus();
    const controller = new AbortController();
    messageRequest = controller;
    ackTimer = window.setTimeout(() => acknowledge(token), ACK_AFTER_MS);
    const body = { text, language, heard: options.heard || null, speech_confidence: options.confidence || null,
                   reviewed: !!options.reviewed };
    let data;
    try {
      data = await post(`/api/voice-agent-demo/${sessionId}/message`, body, controller.signal);
    } catch (error) {
      window.clearTimeout(ackTimer);
      if (token !== turnId || error.name === "AbortError") return;
      busy = acknowledging = false;
      addMessage("msg-system", error.message);
      if (error.code === "call_ended" || error.code === "not_found") finishLocally(null, true);
      showStatus();
      return;
    } finally {
      if (messageRequest === controller) messageRequest = null;
    }
    window.clearTimeout(ackTimer);
    if (token !== turnId) return; // a newer turn, or the call ended while waiting: never shown or spoken
    busy = false;
    mark("intent_completed");
    note("intent", data.timings || {});
    if (acknowledging) await audio.idle(1500); // let "One moment, please." finish rather than cut it off
    acknowledging = false;
    if (token !== turnId) return;
    render(data, token);
  }

  // Only if the reply is still being worked on: an approved, cached "One moment, please."
  function acknowledge(token) {
    if (token !== turnId || !busy) return;
    acknowledging = true;
    const line = phrase("one_moment");
    showStatus();
    if (!muted && voiceOk[language]) audio.playQueue(line.parts, line.voice_language, callToken, undefined, { voice: voiceMode });
  }

  // The call is over on the server (goodbye) or locally (End). Input stops either way.
  function finishLocally(data, silence) {
    if (silence) audio.endCall();
    window.clearTimeout(ackTimer);
    if (messageRequest) messageRequest.abort();
    messageRequest = null;
    active = false;
    ended = true;
    busy = acknowledging = false;
    stopListening();
    clearHeard();
    window.clearInterval(ticker);
    if (data) renderTeam(data);
    showStatus();
  }

  // End call: silence first, then the ended state with input disabled, then log it once.
  function endCall() {
    if (endPromise) return endPromise;
    const sid = sessionId;
    callToken = null;
    turnId = null;
    audio.endCall();
    finishLocally(null, false);
    addMessage("msg-system", "Call ended.");
    if (!sid) return (endPromise = Promise.resolve());
    endPromise = post(`/api/voice-agent-demo/${sid}/end`)
      .then((data) => renderTeam(data))
      .catch((error) => addMessage("msg-system", error.message));
    return endPromise;
  }

  async function runScenario(id) {
    const scenario = SCENARIOS[id];
    if (!scenario || busy) return;
    if (scenario.language && scenario.language !== language) setLanguage(scenario.language);
    if (!active) await startCall();
    if (active) await send(scenario.text);
  }

  // --- Wiring --------------------------------------------------------------------------------
  startButton.addEventListener("click", startCall);
  endButton.addEventListener("click", endCall);
  micButton.addEventListener("click", startListening);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    send(input.value);
  });
  $("va-heard-send").addEventListener("click", () => {
    const text = $("va-heard-text").value;
    const heard = heardOriginal;
    clearHeard();
    send(text, { heard, confidence: "low", reviewed: true, turn: turnId });
  });
  $("va-heard-retry").addEventListener("click", () => {
    clearHeard();
    startListening();
  });
  $("va-heard-typed").addEventListener("click", () => {
    const text = $("va-heard-text").value;
    clearHeard();
    input.value = text;
    input.focus();
  });
  muteButton.addEventListener("click", () => {
    muted = !muted;
    audio.setMuted(muted); // stops anything playing and cancels its pending audio
    showStatus();
  });
  replayButton.addEventListener("click", () => {
    if (active && lastSpeech) speak(lastSpeech);
  });
  for (const radio of radios) radio.addEventListener("change", () => setLanguage(radio.value));
  for (const radio of document.querySelectorAll('input[name="va-voice"]')) {
    radio.addEventListener("change", () => {
      voiceMode = radio.value === "reference" && config.referenceVoice.available ? "reference" : "standard";
      audio.stop(); // the next reply uses the chosen voice
      showStatus();
    });
  }
  for (const button of document.querySelectorAll("[data-scenario]")) {
    button.addEventListener("click", () => runScenario(button.dataset.scenario));
  }

  window.LeaveGuard({
    isActive: () => active,
    beforeLeave: () => {
      audio.leave();
      return endCall();
    },
  });
  window.addEventListener("pagehide", () => {
    audio.leave();
    if (active && sessionId && navigator.sendBeacon) {
      navigator.sendBeacon(`/api/voice-agent-demo/${sessionId}/end`, new Blob(["{}"], { type: "application/json" }));
    }
  });

  setLanguage(language);
  if (micProblem) showMicNote(micProblem, true);
  showStatus();

  // For the browser checks in tests/js: read-only view of the page state.
  window.VoiceAgentDemo = {
    get state() {
      return { active, ended, busy, speaking, preparing, listening, understanding, transcribing: understanding,
               acknowledging, muted, sessionId, language, turnId, playing: audio.playing, micProblem, voiceMode, spokenBy };
    },
    get timing() {
      return timing ? { kind: timing.kind, marks: { ...timing.marks }, notes: { ...timing.notes } } : null;
    },
  };
})();
