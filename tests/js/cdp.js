// Minimal Chrome DevTools Protocol driver for headless Chromium, using only Node built-ins.
// Used by the voice agent browser checks (tests/js/voice_agent_browser.js).
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

async function launch({ width = 1280, height = 900, args = [] } = {}) {
  const binary = process.env.CHROMIUM || "chromium";
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "va-chromium-"));
  const proc = spawn(binary, [
    "--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--no-first-run",
    "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required", "--mute-audio",
    "--use-fake-ui-for-media-stream", `--window-size=${width},${height}`, ...args, "about:blank",
  ], { stdio: ["ignore", "ignore", "pipe"] });
  const wsUrl = await new Promise((resolve, reject) => {
    let buffer = "";
    const timer = setTimeout(() => reject(new Error("Chromium did not start")), 20000);
    proc.stderr.on("data", (chunk) => {
      buffer += chunk;
      const match = buffer.match(/DevTools listening on (ws:\/\/\S+)/);
      if (match) {
        clearTimeout(timer);
        resolve(match[1]);
      }
    });
    proc.on("exit", () => reject(new Error("Chromium exited: " + buffer.slice(-500))));
  });
  const port = new URL(wsUrl).port;
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = targets.find((t) => t.type === "page");
  const client = await connect(page.webSocketDebuggerUrl);
  client.close = () => {
    client.ws.close();
    proc.kill("SIGKILL");
    fs.rmSync(profile, { recursive: true, force: true });
  };
  await client.send("Page.enable");
  await client.send("Runtime.enable");
  return client;
}

function connect(url) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url);
    let id = 0;
    const pending = new Map();
    const listeners = new Map();
    const client = {
      ws,
      send(method, params = {}) {
        return new Promise((res, rej) => {
          const msgId = ++id;
          pending.set(msgId, { res, rej, method });
          ws.send(JSON.stringify({ id: msgId, method, params }));
        });
      },
      once(event) {
        return new Promise((res) => {
          const list = listeners.get(event) || [];
          list.push(res);
          listeners.set(event, list);
        });
      },
      async eval(expression) {
        const result = await client.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
        if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
        return result.result.value;
      },
      async goto(url) {
        const loaded = client.once("Page.loadEventFired");
        await client.send("Page.navigate", { url });
        await loaded;
      },
      async waitFor(expression, timeout = 10000) {
        const start = Date.now();
        while (Date.now() - start < timeout) {
          if (await client.eval(`Boolean(${expression})`)) return;
          await new Promise((r) => setTimeout(r, 50));
        }
        throw new Error("Timed out waiting for: " + expression);
      },
      async screenshot(file) {
        const { data } = await client.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
        fs.writeFileSync(file, Buffer.from(data, "base64"));
      },
    };
    ws.onopen = () => resolve(client);
    ws.onerror = (event) => reject(new Error("DevTools connection failed: " + event.message));
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.id && pending.has(message.id)) {
        const { res, rej, method } = pending.get(message.id);
        pending.delete(message.id);
        if (message.error) rej(new Error(`${method}: ${message.error.message}`));
        else res(message.result);
      } else if (message.method && listeners.has(message.method)) {
        const list = listeners.get(message.method);
        listeners.delete(message.method);
        for (const fn of list) fn(message.params);
      }
    };
  });
}

module.exports = { launch };
