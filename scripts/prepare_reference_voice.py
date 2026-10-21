"""Cut reference clips for the voice agent's optional reference voice from an authorised recording.

Use only a recording whose speaker has explicitly agreed to have their voice cloned for this local demo.

Usage (the segment times are in seconds, from the speaker's own lines only):
  python scripts/prepare_reference_voice.py --source "/path/to/recording.mp4" \\
      --clip hi_1=10.46-14.42,18.98-23.74,28.55-30.87 --clip mix_1=1.20-5.50,40.22-42.48,99.92-105.66

Each clip is that speaker's segments joined with 0.25 s gaps, converted to mono 24 kHz WAV and
level-normalised, and written to VOICE_AGENT_REFERENCE_DIR (default ./voices/reference, ignored by Git).
Nothing is uploaded anywhere, and the clips are never served by the app.
"""
import argparse
import io
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402

RATE = 24000
GAP_SECONDS = 0.25
TARGET_RMS_DB = -20.0
PAD_SECONDS = 0.05


def load(source: Path) -> np.ndarray:
    """The whole recording as mono 24 kHz float32 (decoded by ffmpeg, in memory)."""
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(source), "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def build(audio: np.ndarray, spans: list[tuple[float, float]]) -> np.ndarray:
    gap = np.zeros(int(GAP_SECONDS * RATE), np.float32)
    parts = []
    for start, end in spans:
        piece = audio[max(0, int((start - PAD_SECONDS) * RATE)):int((end + PAD_SECONDS) * RATE)]
        fade = min(len(piece) // 2, int(0.01 * RATE))  # 10 ms fades: no clicks at the joins
        if fade:
            ramp = np.linspace(0, 1, fade, dtype=np.float32)
            piece = piece.copy()
            piece[:fade] *= ramp
            piece[-fade:] *= ramp[::-1]
        parts += [piece, gap]
    clip = np.concatenate(parts[:-1])
    rms = np.sqrt(np.mean(clip ** 2)) + 1e-9
    clip *= 10 ** (TARGET_RMS_DB / 20) / rms
    peak = np.max(np.abs(clip))
    if peak > 0.95:
        clip *= 0.95 / peak
    return clip


def write(path: Path, clip: np.ndarray) -> None:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes((clip * 32767).astype(np.int16).tobytes())
    path.write_bytes(buffer.getvalue())


def parse(value: str) -> tuple[str, list[tuple[float, float]]]:
    name, _, spans = value.partition("=")
    pairs = [tuple(float(x) for x in span.split("-")) for span in spans.split(",") if span]
    if not name or not pairs or any(end <= start for start, end in pairs):
        raise argparse.ArgumentTypeError(f"bad clip: {value}")
    return name, pairs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--clip", required=True, action="append", type=parse, help="name=start-end,start-end,...")
    args = parser.parse_args()
    folder = config.VOICE_AGENT_REFERENCE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    audio = load(args.source)
    for name, spans in args.clip:
        clip = build(audio, spans)
        path = folder / f"{name}.wav"
        write(path, clip)
        print(f"{path}: {len(clip) / RATE:.1f} s from {len(spans)} segments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
