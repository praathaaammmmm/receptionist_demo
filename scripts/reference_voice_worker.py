"""Local worker for the voice agent's optional reference voice (consented demo experiment).

Runs Chatterbox Multilingual (Resemble AI, MIT licence; every output carries Resemble's PerTh watermark)
in its own environment, so the main app never imports PyTorch. Listens on 127.0.0.1 only. It reads the
reference clips once at start, keeps the model on the GPU, and returns generated speech as WAV bytes;
it stores nothing and never serves the reference audio.

Setup (separate environment, Python 3.11):
  uv venv .venv-refvoice --python 3.11
  uv pip install --python .venv-refvoice/bin/python chatterbox-tts
  # RTX 50-series GPUs need a CUDA 12.8 build of PyTorch:
  uv pip install --python .venv-refvoice/bin/python --reinstall torch==2.7.1 torchaudio==2.7.1 \\
      --index-url https://download.pytorch.org/whl/cu128
Run:
  .venv-refvoice/bin/python scripts/reference_voice_worker.py            # port 8765
"""
import argparse
import io
import json
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import torch
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

ROOT = Path(__file__).resolve().parent.parent
MODEL = "Chatterbox Multilingual (ResembleAI/chatterbox, t3_mtl23ls_v2)"
LICENCE = "MIT (code and weights, per the model card); PerTh watermark on every output"
# Which reference clip conditions each language. The clips are the authorised speaker's own Hindi/Hinglish
# and mixed-language lines; see README, "Reference voice".
PROFILES = {"en": "mix_1", "hi": "hi_1"}
MAX_CHARS = 400


class Worker:
    def __init__(self, reference_dir: Path, device: str):
        started = time.perf_counter()
        self.model = ChatterboxMultilingualTTS.from_pretrained(device=device)
        self.device = device
        self.conds = {}
        for language, clip in PROFILES.items():
            path = reference_dir / f"{clip}.wav"
            if path.is_file():
                self.model.prepare_conditionals(str(path), exaggeration=0.5)
                self.conds[language] = self.model.conds
        self.lock = threading.Lock()
        self.cancelled: set[str] = set()
        self.load_seconds = round(time.perf_counter() - started, 1)

    def health(self) -> dict:
        return {"ready": bool(self.conds), "model": MODEL, "licence": LICENCE, "device": self.device,
                "languages": sorted(self.conds), "load_seconds": self.load_seconds}

    def synthesize(self, text: str, language: str, request_id: str) -> tuple[bytes | None, float]:
        if language not in self.conds:
            raise ValueError("language not supported by the reference voice")
        text = " ".join(text.split())[:MAX_CHARS]
        if not text:
            raise ValueError("nothing to say")
        with self.lock:  # one generation at a time on the GPU
            if request_id in self.cancelled:  # cancelled while waiting: skip it
                self.cancelled.discard(request_id)
                return None, 0.0
            started = time.perf_counter()
            self.model.conds = self.conds[language]
            torch.manual_seed(0)
            wav = self.model.generate(text, language_id=language, exaggeration=0.5, cfg_weight=0.5)
            seconds = time.perf_counter() - started
        self.cancelled.discard(request_id)
        samples = np.clip(wav.squeeze(0).numpy(), -1, 1)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(self.model.sr)
            out.writeframes((samples * 32767).astype(np.int16).tobytes())
        return buffer.getvalue(), seconds


def handler_for(worker: Worker):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # nothing about requests or text is logged
            pass

        def _json(self, status: int, body: dict):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                return self._json(200, worker.health())
            self._json(404, {"error": "not_found"})

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            except ValueError:
                return self._json(400, {"error": "bad_json"})
            if self.path == "/cancel":
                worker.cancelled.add(str(body.get("request_id", "")))
                return self._json(200, {"cancelled": True})
            if self.path != "/synthesize":
                return self._json(404, {"error": "not_found"})
            try:
                audio, seconds = worker.synthesize(str(body.get("text", "")), str(body.get("language", "")),
                                                   str(body.get("request_id", "")))
            except ValueError as exc:
                return self._json(422, {"error": "unsupported", "message": str(exc)})
            except Exception as exc:  # noqa: BLE001
                return self._json(500, {"error": "generation_failed", "message": type(exc).__name__})
            if audio is None:
                return self._json(409, {"error": "cancelled"})
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(audio)))
            self.send_header("X-Generation-Ms", str(round(seconds * 1000)))
            self.end_headers()
            self.wfile.write(audio)

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reference-dir", type=Path, default=ROOT / "voices" / "reference")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = parser.parse_args()
    worker = Worker(args.reference_dir, args.device)
    print(json.dumps(worker.health()), flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(worker)).serve_forever()  # local only
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
