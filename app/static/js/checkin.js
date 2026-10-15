// QR check-in helpers. Typing or pasting a code always works; camera scanning is a
// progressive extra, offered only where the browser can decode QR codes itself.
(function () {
  const printButton = document.getElementById("print-card");
  if (printButton) printButton.addEventListener("click", () => window.print());

  const form = document.getElementById("checkin-form");
  if (!form) return;
  const input = document.getElementById("checkin-token");
  const startButton = document.getElementById("scan-start");
  const stopButton = document.getElementById("scan-stop");
  const scanner = document.getElementById("scanner");
  const video = document.getElementById("scan-video");
  const note = document.getElementById("scan-note");

  const supported = "BarcodeDetector" in window && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  if (!supported) {
    note.textContent = "Camera scanning is not available in this browser. Type or paste the code printed under the QR.";
    return;
  }
  startButton.hidden = false;

  let stream = null;
  let timer = null;

  function stop() {
    clearInterval(timer);
    if (stream) for (const track of stream.getTracks()) track.stop();
    stream = null;
    video.srcObject = null;
    scanner.hidden = true;
    startButton.disabled = false;
  }

  async function start() {
    startButton.disabled = true;
    try {
      const detector = new window.BarcodeDetector({ formats: ["qr_code"] });
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      video.srcObject = stream;
      scanner.hidden = false;
      await video.play();
      timer = setInterval(async () => {
        try {
          const codes = await detector.detect(video);
          if (!codes.length) return;
          input.value = codes[0].rawValue.trim();
          stop();
          form.requestSubmit();
        } catch (_) {
          /* a frame that cannot be read is not an error; keep looking */
        }
      }, 350);
    } catch (_) {
      stop();
      note.textContent = "The camera could not be used. Type or paste the code printed under the QR.";
    }
  }

  startButton.addEventListener("click", start);
  stopButton.addEventListener("click", stop);
  window.addEventListener("pagehide", stop);
})();
