// Voice-call simulation. A local demo: no telephony, no microphone, no recording.
// Every caller turn is sent to the server, which runs the same guided assistant
// as the website and words the reply in the chosen language (English, Hindi or
// Hinglish). Replies are read aloud by a local Piper voice generated on this computer,
// from each message's speech_text (for Hinglish, reviewed Devanagari text).
(function () {
  const $ = (id) => document.getElementById(id);
  const config = JSON.parse($("call-config").textContent);
  const LANGS = Object.fromEntries(config.languages.map((language) => [language.code, language]));
  const phone = document.querySelector(".phone");
  const log = $("chat-log");
  const optionsBox = $("chat-options");
  const form = $("call-form");
  const input = $("call-input");
  const sayButton = form.querySelector("button");
  const startButton = $("call-start");
  const muteButton = $("call-mute");
  const endButton = $("call-end");
  const doneActions = $("done-actions");
  const shortcuts = [...document.querySelectorAll(".shortcut")];
  const radios = [...document.querySelectorAll('input[name="call-language"]')];
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const canSpeak = "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
  const QUIET = new Set(["reset", "skip", "more", "change_date", "change_time", "waitlist"]);
  const LANGUAGE_KEY = "smriti.callDemo.language";

  let callId = null;
  let state = null;
  let busy = false;
  let muted = false;
  let startedAt = 0;
  let ticker = null;
  let lastOptions = [];
  let language = "en";

  function el(tag, props, ...children) {
    const node = Object.assign(document.createElement(tag), props || {});
    node.append(...children);
    return node;
  }
  const pause = (ms) => new Promise((resolve) => setTimeout(resolve, calm ? 0 : ms));
  const scrollDown = () => (log.scrollTop = log.scrollHeight);
  const ui = () => LANGS[language].ui;

  async function api(path, body) {
    let response;
    try {
      response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      });
    } catch (_) {
      throw new Error("Could not reach the demo server. Please check it is running and try again.");
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || "Something went wrong. Please try again.");
    return data;
  }

  // --- Voice ------------------------------------------------------------------
  // Each language is spoken by its own local Piper voice pack, generated on this computer and
  // played as ordinary audio, so it works in every browser, Firefox included. English uses the
  // British English pack (Cori); Hindi and Hinglish use the Hindi pack (Hinglish is shown in Roman
  // Hindi but spoken from its Devanagari speech_text). If a language's pack is missing, that
  // language runs as text only: Hindi is never read by an English voice. Browser speech remains
  // only as a fallback for English when the local English pack is missing.
  // Nothing is spoken until the presenter has clicked or pressed a key.
  const panel = $("audio-panel");
  const STATUS_TEXT = {
    ended: "Call ended · audio stopped",
    speaking: "AI is speaking",
    ready: "Voice ready",
    muted: "Muted",
    "needs-click": "Audio requires a click to start",
    text: panel.dataset.textMessage,
  };
  const REASONS = {
    firefox: panel.dataset.reasonFirefox,
    "no-voice": panel.dataset.reasonNoVoice,
    failed: panel.dataset.reasonFailed,
    "missing-pack": config.voiceMissing,
  };
  // Firefox (notably on Linux) often has no usable speech engine, so it never uses browser speech.
  const isFirefox = document.body.dataset.textMode === "firefox" || /firefox|fxios/i.test(navigator.userAgent);
  const synth = canSpeak && !isFirefox ? window.speechSynthesis : null;

  const pack = (code) => (code === "en" ? "en" : "hi"); // Hinglish is spoken by the Hindi pack
  const localVoice = { en: LANGS.en.voice.available, hi: LANGS.hi.voice.available };

  let voices = [];
  let voicesChecked = false; // true once the browser has had a fair chance to list its voices
  let interacted = false; // browsers only allow speech after a user gesture
  let speechOffForCall = false; // speech failed to start once: stay in text mode until the next call
  let heard = false; // an utterance has actually started at least once
  let speaking = false; // a reply is being heard right now
  let ended = false; // the last call has ended and nothing new has been asked for since
  let callToken = null; // client-side id of the active call's audio session
  let callSeq = 0;

  // All playback and cancellation lives in call-audio.js. Anything queued for a call that has
  // ended (or been muted, replaced or left) is discarded there instead of being played.
  const audio = window.CallAudio.create({
    fetch: (...args) => window.fetch(...args),
    makeAudio: () => new Audio(),
    makeUtterance: (text) => new SpeechSynthesisUtterance(text),
    synth,
    speechUrl: "/api/call-demo/speech",
    createObjectURL: (blob) => URL.createObjectURL(blob),
    revokeObjectURL: (url) => URL.revokeObjectURL(url),
    setTimeout: (fn, ms) => window.setTimeout(fn, ms),
    clearTimeout: (id) => window.clearTimeout(id),
    AbortController: window.AbortController,
    hooks: {
      onPlaying() {
        heard = speaking = true;
        showAudio();
      },
      onDone() {
        speaking = false;
        showAudio();
      },
      onStopped() {
        speaking = false;
      },
      onUnavailable(code) {
        localVoice[pack(code)] = false; // the pack is gone: this language carries on as text
        showAudio();
      },
      onNotAllowed() {
        interacted = false; // the browser wants a fresh click first; not a failure
        showAudio();
      },
      onFailed: () => fallBackToText(),
    },
  });

  // Why a language is in text simulation mode, or null when it can be spoken.
  function textModeReason(code = language) {
    if (localVoice[pack(code)]) return speechOffForCall ? "failed" : null;
    if (pack(code) === "hi") return "missing-pack";
    if (isFirefox) return "firefox";
    if (!synth || (voicesChecked && !voices.length && !heard)) return "no-voice";
    if (speechOffForCall) return "failed";
    return null;
  }

  function audioState() {
    if (ended) return "ended";
    if (textModeReason()) return "text";
    if (speaking) return "speaking";
    if (muted) return "muted";
    if (!interacted) return "needs-click";
    return "ready";
  }

  function showVoice() {
    const voice = LANGS[language].voice;
    $("audio-voice-name").textContent = voice.label;
    const installed = localVoice[pack(language)];
    $("audio-voice-model").textContent = voice.voice + (voice.speaker ? " · " + voice.speaker : "") + (installed ? "" : " · not installed");
    $("audio-note").textContent =
      (installed
        ? "Audio is generated on this computer for the demo."
        : pack(language) === "en" && !textModeReason()
          ? "Audio is generated by this browser for the demo."
          : "No voice is playing for this language.") + " It is optional: the transcript is the record of the call.";
  }

  function showAudio(notice) {
    const current = audioState();
    const reason = textModeReason();
    $("audio-status").dataset.state = current;
    $("audio-status-text").textContent = reason === "missing-pack" ? REASONS[reason] : STATUS_TEXT[current];
    // In text mode the speaker tests and mute control stay visible but inactive, with the reason on hover.
    for (const button of document.querySelectorAll("[data-test-language]")) {
      const why = textModeReason(button.dataset.testLanguage);
      if (why) {
        button.setAttribute("aria-disabled", "true");
        button.title = REASONS[why];
      } else {
        button.removeAttribute("aria-disabled");
        button.removeAttribute("title");
      }
    }
    muteButton.disabled = !!reason;
    $("call-mute-label").textContent = reason ? "Voice off" : muted ? "Voice muted" : "Mute voice";
    showVoice();
    const box = $("audio-notice");
    box.textContent = notice || "";
    box.hidden = !notice;
  }

  function loadVoices() {
    if (!synth) return;
    const read = () => {
      const list = synth.getVoices();
      if (!list.length) return false;
      voices = list;
      voicesChecked = true;
      showAudio();
      return true;
    };
    if (read()) return;
    // Chrome-family browsers fill the list asynchronously and announce it with this event.
    synth.onvoiceschanged = read;
    setTimeout(() => {
      if (!read()) {
        voicesChecked = true;
        showAudio();
      }
    }, 2500);
  }

  // Browser fallback voice (English only). Prefer English (India); otherwise the
  // browser's default voice if it is English; otherwise another plain English voice. Some speech
  // engines list distorted "variant" voices (names like "English+whisper"), which sound garbled.
  function preferredVoice() {
    const lang = (v) => (v.lang || "").replace("_", "-").toLowerCase();
    const english = voices.filter((v) => lang(v) === "en" || lang(v).startsWith("en-"));
    const plain = english.filter((v) => !v.name.includes("+"));
    const pool = plain.length ? plain : english;
    return (
      pool.find((v) => lang(v) === "en-in") ||
      pool.find((v) => v.default) ||
      pool.find((v) => lang(v) === "en-gb") ||
      pool.find((v) => lang(v) === "en-us") ||
      pool[0] ||
      null
    );
  }

  function hush() {
    audio.stop();
  }

  // Speech did not start: finish this call as a text simulation rather than keep retrying.
  function fallBackToText() {
    speechOffForCall = true;
    hush();
    showAudio();
  }

  // `token` ties the reply to its call; null (the voice tests) plays outside any call.
  function speak(lines, code = language, token = callToken) {
    if (textModeReason(code)) return; // text simulation mode: never touch the speech engine
    hush(); // a new reply replaces anything still queued from the previous one
    if (muted || !interacted) return showAudio();
    if (localVoice[pack(code)]) return void audio.playLocal(lines.join("\n"), code, token);
    // Browser fallback. Short lines are spoken whole; long ones go sentence by sentence,
    // which some browsers need to avoid cutting off lengthy speech.
    const parts = lines
      .flatMap((line) => line.replace(/[•#·]/g, " ").split(line.length > 160 ? /(?<=[.?!])\s+|\n+/ : /\n+/))
      .map((part) => part.trim())
      .filter(Boolean);
    audio.speakBrowser(parts, preferredVoice(), token);
  }

  function setMuted(value) {
    muted = value;
    muteButton.setAttribute("aria-pressed", String(value));
    audio.setMuted(value);
    showAudio();
  }

  function testVoice(code) {
    interacted = true;
    const reason = textModeReason(code);
    if (reason) return showAudio(REASONS[reason]);
    if (muted) return showAudio("Voice is muted. Choose “Voice muted” to turn it back on, then test again.");
    ended = false;
    showAudio();
    speak([LANGS[code].ui.test_speech], code, null);
  }

  // The first click or key press anywhere on the page is what allows audio to start.
  for (const type of ["pointerdown", "keydown"]) {
    document.addEventListener(
      type,
      () => {
        if (interacted) return;
        interacted = true;
        showAudio();
      },
      { capture: true }
    );
  }

  // --- Language -------------------------------------------------------------------
  function storedLanguage() {
    try {
      const saved = window.localStorage.getItem(LANGUAGE_KEY);
      return saved in LANGS ? saved : "en";
    } catch (_) {
      return "en";
    }
  }

  function showLanguage() {
    const chosen = LANGS[language];
    for (const radio of radios) radio.checked = radio.value === language;
    $("lang-current-name").textContent = chosen.label;
    $("lang-current-name").lang = chosen.html_lang;
    $("call-lang-tag").textContent = chosen.label;
    $("call-lang-tag").lang = chosen.html_lang;
    for (const button of shortcuts) {
      const label = button.dataset["label" + language.charAt(0).toUpperCase() + language.slice(1)]; // data-label-hi etc.
      button.textContent = "“" + (label || button.dataset.phrase) + "”";
      button.lang = chosen.html_lang;
    }
    showAudio();
  }

  function setLanguage(code) {
    if (!(code in LANGS) || code === language) return;
    language = code;
    try {
      window.localStorage.setItem(LANGUAGE_KEY, code);
    } catch (_) {
      /* private mode: the choice lasts for this page only */
    }
    hush(); // never finish a reply in the previous language's voice
    showLanguage();
    if (callId) {
      // The choices stay open (arrow keys move through them); "Change language" closes them again.
      addMessage(ui().language_changed, "system", null, LANGS[code].html_lang);
    }
  }

  function toggleLanguageChoices(open, focus) {
    $("lang-choices").hidden = !open;
    $("lang-hint").hidden = !(open && callId);
    $("lang-change").setAttribute("aria-expanded", String(open));
    if (open && focus) (radios.find((radio) => radio.checked) || radios[0]).focus();
  }

  function showLanguageMode() {
    // Before a call the choices are always visible; during one they sit behind "Change language".
    $("lang-current").hidden = !callId;
    toggleLanguageChoices(!callId);
  }

  // --- Transcript ---------------------------------------------------------------
  function addMessage(text, who, tone, lang) {
    const names = { bot: "AI assistant", user: "Caller" };
    const node = el("div", { className: `msg msg-${who}` + (tone ? ` msg-${tone}` : ""), textContent: text });
    if (names[who]) node.dataset.who = names[who];
    if (lang) node.lang = lang;
    log.append(node);
    scrollDown();
  }

  function addReceipt(title, rows, status) {
    const list = el("dl");
    for (const [term, detail] of rows) list.append(el("dt", { textContent: term }), el("dd", { textContent: detail }));
    list.append(
      el("dt", { textContent: ui().status }),
      el("dd", null, el("span", { className: "pill pill-" + status.toLowerCase(), textContent: status.replace("_", " ") }))
    );
    log.append(el("div", { className: "receipt" }, el("h3", { textContent: title }), list));
    scrollDown();
  }

  function renderOptions(options, lang) {
    lastOptions = options;
    optionsBox.replaceChildren();
    for (const option of options) {
      const quiet = QUIET.has(option.action) || (option.action === "intent" && option.value === "human");
      const button = el("button", { type: "button", className: "chat-option" + (quiet ? " is-quiet" : ""), textContent: option.label });
      if (lang) button.lang = lang;
      button.addEventListener("click", () => say({ action: option.action, value: option.value }, option.label));
      optionsBox.append(button);
    }
  }

  function showCaller(call) {
    const name = call.caller_name;
    $("caller-name").textContent = name || "Unknown caller";
    $("caller-mobile").textContent = call.caller_mobile || "Number not given yet";
    $("caller-avatar").textContent = name ? name.trim().charAt(0).toUpperCase() : "?";
  }

  async function render(reply, token) {
    if (token !== callToken) return; // the call ended while this reply was on its way
    state = reply.state;
    const code = reply.language || language;
    const lang = LANGS[code].html_lang;
    const words = LANGS[code].ui;
    speak(reply.messages.map((message) => message.speech_text || message.text), code, token);
    for (const message of reply.messages) {
      if (token !== callToken) return; // ended part-way through: keep what is shown, add nothing more
      addMessage(message.text, "bot", message.tone, lang);
      await pause(220);
    }
    if (token !== callToken) return;
    if (reply.booking) {
      const b = reply.booking;
      addReceipt(
        words.receipt_booking,
        [[words.reference, "#" + b.reference], [words.visit, b.service], [words.doctor, b.doctor], [words.when, `${b.date} · ${b.time} (${b.duration_minutes} min)`]],
        b.status
      );
    }
    if (reply.callback) {
      addReceipt(words.receipt_callback, [[words.reference, reply.callback.reference], [words.we_will_call, reply.callback.mobile]], reply.callback.status);
    }
    doneActions.hidden = !(reply.booking || reply.callback || reply.waitlist);
    renderOptions(reply.options, lang);
    const spec = reply.input || {};
    input.type = spec.type || "text";
    input.inputMode = spec.type === "tel" ? "tel" : spec.type === "email" ? "email" : "text";
    input.placeholder = spec.type && spec.type !== "text" ? spec.placeholder : spec.label === "Your message" || !spec.label ? "Type what the caller says" : spec.placeholder;
    $("call-label").textContent = spec.label && spec.label !== "Your message" ? spec.label : "What the caller says";
  }

  // --- Call lifecycle -------------------------------------------------------------
  function setBusy(value) {
    busy = value;
    sayButton.disabled = value || !callId;
    startButton.disabled = value;
    for (const button of [...shortcuts, ...optionsBox.querySelectorAll("button")]) button.disabled = value;
  }

  function tick() {
    const seconds = Math.floor((Date.now() - startedAt) / 1000);
    $("call-timer").textContent = String(Math.floor(seconds / 60)).padStart(2, "0") + ":" + String(seconds % 60).padStart(2, "0");
  }

  function showIdle(message) {
    callId = null;
    state = null;
    clearInterval(ticker);
    phone.classList.remove("is-live");
    startButton.hidden = false;
    muteButton.hidden = true;
    endButton.hidden = true;
    input.disabled = true;
    sayButton.disabled = true;
    input.type = "text";
    input.placeholder = "Type what the caller says";
    $("call-state").textContent = message;
    renderOptions([]);
    showLanguageMode();
  }

  function clearScreen() {
    hush();
    log.replaceChildren(el("p", { className: "call-empty", id: "call-empty", textContent: "Press “Start demo call” or choose a caller phrase below to begin." }));
    $("call-timer").textContent = "00:00";
    $("call-outcome").textContent = "";
    doneActions.hidden = true;
    showCaller({});
  }

  async function startCall() {
    if (callId || busy) return;
    setBusy(true);
    clearScreen();
    try {
      const data = await api("/api/call-demo/start", { language });
      callId = data.call.id;
      callToken = `call-${callId}-${++callSeq}`; // a clean audio session for this call
      audio.beginCall(callToken);
      ended = false;
      log.replaceChildren();
      addMessage(`Call connected · simulated · ${LANGS[language].label}`, "system");
      phone.classList.add("is-live");
      startButton.hidden = true;
      muteButton.hidden = false;
      endButton.hidden = false;
      speechOffForCall = false; // every call gets a fresh chance at speech
      showLanguageMode();
      showAudio();
      input.disabled = false;
      $("call-state").textContent = "Connected";
      startedAt = Date.now();
      ticker = setInterval(tick, 500);
      await render(data.reply, callToken);
    } catch (error) {
      log.replaceChildren();
      addMessage(error.message, "bot", "notice");
      showIdle("Ready to start");
    } finally {
      setBusy(false);
    }
  }

  async function say(payload, echo) {
    if (busy) return;
    if (!callId) await startCall();
    if (!callId) return;
    const token = callToken;
    setBusy(true);
    hush();
    doneActions.hidden = true;
    addMessage(echo, "user");
    const typing = el("div", { className: "typing", ariaLabel: "Assistant is replying" }, el("i"), el("i"), el("i"));
    log.append(typing);
    scrollDown();
    try {
      const [data] = await Promise.all([
        api(`/api/call-demo/${callId}/message`, { text: "", action: null, value: null, ...payload, state, language }),
        pause(420),
      ]);
      typing.remove();
      if (token !== callToken) return; // the call ended while waiting: discard the reply and its audio
      showCaller(data.call);
      await render(data.reply, token);
    } catch (error) {
      typing.remove();
      if (token !== callToken) return;
      addMessage(error.message, "bot", "notice");
      renderOptions(lastOptions);
    } finally {
      setBusy(false);
      if (payload.text !== undefined) input.focus({ preventScroll: true });
    }
  }

  // Ends the call through the server, which records its outcome. `quiet` skips the transcript lines.
  // Audio stops first, before anything else: nothing from this call plays after this point.
  async function endCall(quiet) {
    if (!callId) return;
    const id = callId;
    callToken = null;
    audio.endCall();
    ended = true;
    showIdle("Call ended");
    setBusy(false);
    showAudio();
    try {
      const data = await api(`/api/call-demo/${id}/end`, { language });
      if (!quiet) {
        // The goodbye is shown, not spoken: ending a call is silent.
        addMessage(data.goodbye.text, "bot", null, LANGS[language].html_lang);
        addMessage("Call ended", "system");
        $("call-outcome").replaceChildren("Outcome recorded for this demo call: ", el("strong", { textContent: data.call.outcome }));
        doneActions.hidden = false;
      }
    } catch (error) {
      if (!quiet) addMessage(error.message, "bot", "notice");
    }
  }

  async function resetCall() {
    await endCall(true);
    clearScreen();
    showIdle("Ready to start");
    speechOffForCall = false;
    ended = false;
    setMuted(false);
    startButton.focus();
  }

  async function startAnother() {
    await endCall(true);
    clearScreen();
    showIdle("Ready to start");
    await startCall();
  }

  startButton.addEventListener("click", startCall);
  endButton.addEventListener("click", () => endCall(false));
  $("call-reset").addEventListener("click", resetCall);
  $("call-again").addEventListener("click", startAnother);
  muteButton.addEventListener("click", () => setMuted(!muted));
  $("lang-change").addEventListener("click", () => toggleLanguageChoices($("lang-choices").hidden, true));
  for (const radio of radios) radio.addEventListener("change", () => setLanguage(radio.value));
  for (const button of document.querySelectorAll("[data-test-language]")) {
    button.addEventListener("click", () => testVoice(button.dataset.testLanguage));
  }
  for (const button of shortcuts) {
    button.addEventListener("click", () => say({ action: "say", value: button.dataset.phrase }, button.textContent.replace(/^“|”$/g, "")));
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || busy || !callId) return;
    input.value = "";
    say({ text }, text);
  });
  // "Back to dashboard" during a call asks first, then ends the call properly before leaving.
  window.LeaveGuard({
    isActive: () => !!callId,
    beforeLeave: () => {
      audio.leave(); // silence first, then the normal end flow records the outcome
      return endCall(true);
    },
  });
  // Closing the tab or leaving any other way also closes the open demo call, so the dashboard
  // does not show it as in progress.
  // Coming back to this page from the browser's history restores it frozen after leaving: reload for a
  // clean call screen and audio session instead.
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) window.location.reload();
  });
  window.addEventListener("pagehide", () => {
    audio.leave();
    if (callId) navigator.sendBeacon(`/api/call-demo/${callId}/end`, new Blob([JSON.stringify({ language })], { type: "application/json" }));
  });

  language = storedLanguage();
  showIdle("Ready to start");
  loadVoices();
  showLanguage();
})();
