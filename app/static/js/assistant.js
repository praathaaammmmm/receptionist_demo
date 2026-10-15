// Public appointment assistant. All logic lives on the server; this file only
// sends each turn to /api/assistant/message and renders the reply.
(function () {
  const log = document.getElementById("chat-log");
  const optionsBox = document.getElementById("chat-options");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const label = document.getElementById("chat-label");
  const sendButton = form.querySelector("button");
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const QUIET = new Set(["reset", "skip", "more", "change_date", "change_time", "waitlist"]);

  let state = null;
  let lastOptions = [];
  let busy = false;

  function el(tag, props, ...children) {
    const node = Object.assign(document.createElement(tag), props || {});
    node.append(...children);
    return node;
  }

  function scrollDown() {
    log.scrollTop = log.scrollHeight;
  }

  function addMessage(text, who, tone) {
    log.append(el("div", { className: `msg msg-${who}` + (tone ? ` msg-${tone}` : ""), textContent: text }));
    scrollDown();
  }

  function addReceipt(title, rows, status) {
    const list = el("dl");
    for (const [term, detail] of rows) list.append(el("dt", { textContent: term }), el("dd", { textContent: detail }));
    list.append(
      el("dt", { textContent: "Status" }),
      el("dd", null, el("span", { className: "pill pill-" + status.toLowerCase(), textContent: status.replace("_", " ") }))
    );
    log.append(el("div", { className: "receipt" }, el("h3", { textContent: title }), list));
    scrollDown();
  }

  function setBusy(value) {
    busy = value;
    sendButton.disabled = value;
    for (const button of optionsBox.querySelectorAll("button")) button.disabled = value;
  }

  function renderOptions(options) {
    lastOptions = options;
    optionsBox.replaceChildren();
    for (const option of options) {
      const quiet = QUIET.has(option.action) || option.label === "No thanks" || option.label === "Speak to a person";
      const button = el("button", {
        type: "button",
        className: "chat-option" + (quiet ? " is-quiet" : ""),
        textContent: option.label,
      });
      button.addEventListener("click", () => send({ action: option.action, value: option.value }, option.label));
      optionsBox.append(button);
    }
  }

  function configureInput(spec) {
    input.type = spec.type || "text";
    input.placeholder = spec.placeholder || "";
    input.autocomplete = spec.autocomplete || "off";
    input.inputMode = spec.type === "tel" ? "tel" : spec.type === "email" ? "email" : "text";
    label.textContent = spec.label || "Your message";
  }

  const pause = (ms) => new Promise((resolve) => setTimeout(resolve, calm ? 0 : ms));

  async function render(reply) {
    state = reply.state;
    for (const message of reply.messages) {
      addMessage(message.text, "bot", message.tone);
      await pause(220);
    }
    if (reply.booking) {
      const b = reply.booking;
      addReceipt(
        "Booking request",
        [
          ["Reference", "#" + b.reference],
          ["Visit", b.service],
          ["Doctor", b.doctor],
          ["When", `${b.date} at ${b.time} (${b.duration_minutes} min)`],
        ],
        b.status
      );
    }
    if (reply.callback) {
      addReceipt("Callback request", [["Reference", reply.callback.reference], ["We will call", reply.callback.mobile]], reply.callback.status);
    }
    renderOptions(reply.options);
    configureInput(reply.input || {});
  }

  async function send(payload, echo) {
    if (busy) return;
    setBusy(true);
    if (echo) addMessage(echo, "user");
    const typing = el("div", { className: "typing", ariaLabel: "Assistant is replying" }, el("i"), el("i"), el("i"));
    log.append(typing);
    scrollDown();
    try {
      const [response] = await Promise.all([
        fetch("/api/assistant/message", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: "", action: null, value: null, ...payload, state }),
        }),
        pause(380),
      ]);
      const data = await response.json().catch(() => ({}));
      typing.remove();
      if (!response.ok) throw new Error(data.message || "Something went wrong. Please try again.");
      await render(data);
    } catch (error) {
      typing.remove();
      const offline = error instanceof TypeError;
      addMessage(offline ? "I could not reach the clinic system. Please check your connection and try again." : error.message, "bot", "notice");
      renderOptions(lastOptions);
    } finally {
      setBusy(false);
      if (!echo || payload.text !== undefined) input.focus({ preventScroll: true });
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text || busy) return;
    input.value = "";
    send({ text }, text);
  });

  send({ action: "start" });
})();
