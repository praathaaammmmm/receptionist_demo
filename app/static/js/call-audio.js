// Audio for the call demo: plays local Piper replies (or the browser-speech fallback) and stops
// them instantly. Every reply is tied to the call it belongs to; audio that arrives after that
// call has ended, been muted, been replaced or left behind is discarded and never played.
// No DOM access here, so the rules can be tested in Node with fakes (tests/js/call_audio_harness.js).
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.CallAudio = factory();
})(typeof self !== "undefined" ? self : this, function () {
  function create(env) {
    const hooks = env.hooks || {};
    let seq = 0; // increases whenever audio is stopped or replaced; old work checks it before playing
    let session = null; // token of the active call, or null when no call is active
    let muted = false;
    let leaving = false; // the page is navigating away
    let current = null; // { audio, url } of the reply being played
    let request = null; // AbortController of the in-flight speech request
    let queueRequests = []; // AbortControllers of a sentence queue's speech requests (playQueue)
    let finishCurrent = null; // resolves the sentence that playQueue is waiting on when it is stopped
    let timers = [];
    let utterances = []; // keep references so the browser does not drop queued speech

    function later(fn, ms) {
      const id = env.setTimeout(fn, ms);
      timers.push(id);
      return id;
    }

    function silence(audio) {
      audio.onended = null;
      audio.pause();
      try {
        audio.currentTime = 0;
      } catch (_) {
        /* not seekable yet */
      }
      if (audio.removeAttribute) audio.removeAttribute("src");
      else audio.src = "";
      if (audio.load) audio.load(); // drops any buffered sound
    }

    function releaseAudio() {
      if (finishCurrent) {
        const finish = finishCurrent;
        finishCurrent = null;
        finish("stopped");
      }
      if (!current) return;
      const { audio, url } = current;
      current = null;
      silence(audio);
      if (url) env.revokeObjectURL(url);
    }

    // Stop everything now: playing audio, the in-flight request, queued browser speech and timers.
    function stop() {
      seq += 1;
      if (request) {
        request.abort();
        request = null;
      }
      for (const controller of queueRequests) controller.abort();
      queueRequests = [];
      for (const id of timers) env.clearTimeout(id);
      timers = [];
      releaseAudio();
      utterances = [];
      if (env.synth) env.synth.cancel();
      if (hooks.onStopped) hooks.onStopped();
    }

    // May audio queued under this ticket still play?
    function allowed(ticket) {
      if (ticket.seq !== seq || muted || leaving) return false;
      return ticket.token === null || (session !== null && ticket.token === session);
    }

    function ticket(token) {
      return { seq, token: token === undefined ? session : token };
    }

    async function playLocal(text, language, token) {
      stop(); // a new reply replaces anything still playing or loading
      const mine = ticket(token);
      if (!allowed(mine)) return "discarded";
      const controller = new env.AbortController();
      request = controller;
      try {
        const response = await env.fetch(env.speechUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, language }),
          signal: controller.signal,
        });
        if (!allowed(mine)) return "discarded";
        if (response.status === 503) {
          if (hooks.onUnavailable) hooks.onUnavailable(language);
          return "unavailable";
        }
        if (!response.ok) {
          if (hooks.onFailed) hooks.onFailed();
          return "failed";
        }
        const blob = await response.blob();
        if (!allowed(mine)) return "discarded"; // ended while the audio was downloading
        if (request === controller) request = null;
        const url = env.createObjectURL(blob);
        const audio = env.makeAudio();
        audio.src = url;
        current = { audio, url };
        audio.onended = () => {
          if (current && current.audio === audio) {
            releaseAudio();
            if (hooks.onDone) hooks.onDone();
          }
        };
        await audio.play();
        if (!allowed(mine)) {
          // Stopped while the browser was starting playback: silence this exact element again.
          if (current && current.audio === audio) releaseAudio();
          else silence(audio);
          return "discarded";
        }
        if (hooks.onPlaying) hooks.onPlaying();
        return "played";
      } catch (error) {
        if (!allowed(mine) || error.name === "AbortError") return "discarded";
        if (error.name === "NotAllowedError") {
          if (hooks.onNotAllowed) hooks.onNotAllowed();
          return "not-allowed";
        }
        if (hooks.onFailed) hooks.onFailed();
        return "failed";
      } finally {
        if (request === controller) request = null;
      }
    }

    // Browser speech fallback (English only). Chrome can drop speak() calls made in the same
    // tick as cancel(), so the parts are queued just after it.
    function speakBrowser(parts, voice, token) {
      stop();
      const mine = ticket(token);
      if (!allowed(mine) || !env.synth || !parts.length) return;
      later(() => {
        if (!allowed(mine)) return;
        let started = false;
        env.synth.resume();
        for (const part of parts) {
          const utterance = env.makeUtterance(part);
          if (voice) {
            utterance.voice = voice;
            utterance.lang = voice.lang;
          } else {
            utterance.lang = "en-IN";
          }
          utterance.onstart = () => {
            if (!allowed(mine)) return env.synth.cancel();
            started = true;
            if (hooks.onPlaying) hooks.onPlaying();
          };
          utterance.onend = () => {
            if (allowed(mine) && utterance === utterances[utterances.length - 1] && hooks.onDone) hooks.onDone();
          };
          utterance.onerror = (event) => {
            if (!allowed(mine) || event.error === "interrupted" || event.error === "canceled") return;
            if (event.error === "not-allowed") return hooks.onNotAllowed && hooks.onNotAllowed();
            if (hooks.onFailed) hooks.onFailed();
          };
          utterances.push(utterance);
          env.synth.speak(utterance);
        }
        later(() => {
          if (!started && allowed(mine) && hooks.onFailed) hooks.onFailed();
        }, 4000);
      }, 80);
    }

    // Voice agent: a reply as sentences. Only the next sentence is requested ahead, so the server makes the
    // first one first; each plays as soon as it is ready. Everything belongs to `token` (one caller turn):
    // a newer turn, mute, End call or leaving stops it, aborts its requests and drops anything late.
    async function playQueue(parts, language, token, url, extra) {
      stop();
      const mine = ticket(token);
      if (!allowed(mine) || !parts.length) return "discarded";
      const fetchPart = (text) => {
        const controller = new env.AbortController();
        queueRequests.push(controller);
        const started = env.now ? env.now() : 0;
        return env.fetch(url || env.speechUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, language, ...(extra || {}) }),
          signal: controller.signal,
        }).then(async (response) => {
          if (response.status === 503) return { unavailable: true };
          if (response.status === 204 || !response.ok) return { failed: true };
          const blob = await response.blob();
          const headers = response.headers;
          return {
            blob,
            ms: env.now ? env.now() - started : null,
            serverMs: headers && headers.get ? Number(headers.get("X-Synthesis-Ms")) : null,
            cache: headers && headers.get ? headers.get("X-Phrase-Cache") : null,
            voiceMode: headers && headers.get ? headers.get("X-Voice-Mode") : null,
            fallbackReason: headers && headers.get ? headers.get("X-Voice-Fallback-Reason") : null,
          };
        }).catch((error) => ({ error }));
      };
      if (hooks.onPreparing) hooks.onPreparing();
      let next = fetchPart(parts[0]);
      for (let i = 0; i < parts.length; i += 1) {
        const result = await next;
        if (!allowed(mine)) return "discarded";
        next = i + 1 < parts.length ? fetchPart(parts[i + 1]) : null;
        if (result.error) {
          if (result.error.name === "AbortError") return "discarded";
          if (hooks.onFailed) hooks.onFailed();
          return "failed";
        }
        if (result.unavailable) {
          if (hooks.onUnavailable) hooks.onUnavailable(language);
          return "unavailable";
        }
        if (result.failed) {
          if (hooks.onFailed) hooks.onFailed();
          return "failed";
        }
        if (hooks.onPartReady) hooks.onPartReady(i, result);
        const outcome = await playBlob(result.blob, mine, i === 0);
        if (outcome !== "ended") return outcome;
      }
      if (allowed(mine) && hooks.onDone) hooks.onDone();
      return "played";
    }

    function playBlob(blob, mine, first) {
      return new Promise((resolve) => {
        const url = env.createObjectURL(blob);
        const audio = env.makeAudio();
        audio.src = url;
        current = { audio, url };
        finishCurrent = resolve;
        audio.onended = () => {
          if (current && current.audio === audio) {
            finishCurrent = null;
            current = null;
            silence(audio);
            env.revokeObjectURL(url);
            resolve("ended");
          }
        };
        Promise.resolve(audio.play()).then(() => {
          if (!allowed(mine)) {
            if (current && current.audio === audio) releaseAudio();
            else silence(audio);
            return resolve("discarded");
          }
          if (first && hooks.onPlaying) hooks.onPlaying();
        }).catch((error) => {
          if (current && current.audio === audio) releaseAudio();
          if (!allowed(mine)) return resolve("discarded");
          if (error && error.name === "NotAllowedError" && hooks.onNotAllowed) hooks.onNotAllowed();
          else if (hooks.onFailed) hooks.onFailed();
          resolve("failed");
        });
      });
    }

    // Resolves when nothing is playing any more, or after timeoutMs.
    function idle(timeoutMs) {
      return new Promise((resolve) => {
        const started = Date.now();
        const check = () => {
          if (!current || Date.now() - started >= timeoutMs) return resolve();
          env.setTimeout(check, 40);
        };
        check();
      });
    }

    return {
      idle,
      playQueue,
      playLocal,
      speakBrowser,
      stop,
      // A new call: a clean audio session that nothing from earlier calls can play into.
      beginCall(token) {
        stop();
        session = token;
        leaving = false;
      },
      endCall() {
        session = null;
        stop();
      },
      leave() {
        leaving = true;
        session = null;
        stop();
      },
      setMuted(value) {
        muted = value;
        if (value) stop();
      },
      get playing() {
        return current !== null;
      },
      get session() {
        return session;
      },
    };
  }

  return { create };
});
