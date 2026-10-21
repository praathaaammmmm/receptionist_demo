"""Internal comparison of the standard Piper voice and the consented reference voice. Not part of the app.

Step 1 (main environment): generate the same approved sentences with both voices, time the first audio,
and check intelligibility by transcribing every output with the local Whisper model:
  .venv/bin/python scripts/evaluate_reference_voice.py generate
Step 2 (reference-voice environment): speaker similarity to the reference clips, pitch and pace:
  .venv-refvoice/bin/python scripts/evaluate_reference_voice.py compare

Outputs go to voices/reference/eval/ (ignored by Git) so a person can listen to them, plus results.json.
Delete that folder when the comparison is done. Needs the reference-voice worker running for step 1.
"""
import argparse
import asyncio
import io
import json
import re
import sys
import time
import unicodedata
import uuid
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "voices" / "reference" / "eval"

HINGLISH_ROMAN = ("Namaste, main Smriti Raj Dentistry ki virtual assistant hoon. Main appointment, callback aur "
                  "consultation enquiry mein help kar sakti hoon.")
HINGLISH_DEVANAGARI = ("नमस्ते, मैं स्मृति राज डेंटिस्ट्री की वर्चुअल असिस्टेंट हूँ। मैं अपॉइंटमेंट, कॉलबैक और "
                       "कंसल्टेशन एनक्वायरी में हेल्प कर सकती हूँ।")


def cases():
    from app.voice_agent import wording

    promise_en = wording.PROMISE["open"]["en"]
    promise_hi = wording.PROMISE["open"]["hi"]
    # (case, demo language, text for Piper, text for the reference voice, target text for intelligibility, STT mode)
    return [
        ("greeting_en", "en", "Namaste, you've reached Smriti Raj Dentistry. How may I help you today?", None, None, "en"),
        ("greeting_hi", "hi", "नमस्ते, आपने स्मृति राज डेंटिस्ट्री को कॉल किया है। मैं आपकी कैसे मदद कर सकती हूँ?", None, None, "hi"),
        # Hinglish: the app speaks the Devanagari version with the Hindi voice; also try the Roman text directly.
        ("greeting_hinglish", "hinglish", HINGLISH_DEVANAGARI, HINGLISH_DEVANAGARI, HINGLISH_ROMAN, "hinglish"),
        ("greeting_hinglish_roman_hi", "hinglish", None, HINGLISH_ROMAN, HINGLISH_ROMAN, "hinglish"),
        ("greeting_hinglish_roman_en", "en", None, HINGLISH_ROMAN, HINGLISH_ROMAN, "hinglish"),
        ("callback_name_en", "en", wording.line("callback_created", "en", name="Asha Verma", promise=promise_en), None, None, "en"),
        ("callback_name_hi", "hi", wording.line("callback_created", "hi", name="आशा वर्मा", promise=promise_hi), None, None, "hi"),
        ("hours_en", "en", wording.line("hours", "en"), None, None, "en"),
        ("hours_hi", "hi", wording.line("hours", "hi"), None, None, "hi"),
        ("emergency_en", "en", wording.line("emergency", "en"), None, None, "en"),
        ("emergency_hi", "hi", wording.line("emergency", "hi"), None, None, "hi"),
    ]


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text.lower())
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def cer(reference: str, hypothesis: str) -> float:
    a, b = normalise(reference).replace(" ", ""), normalise(hypothesis).replace(" ", "")
    if not a:
        return 0.0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return round(previous[-1] / len(a), 3)


def seconds(audio: bytes) -> float:
    with wave.open(io.BytesIO(audio)) as w:
        return w.getnframes() / w.getframerate()


def resample(audio: bytes, rate: int) -> bytes:
    """A Piper sentence at the reference voice's sample rate, so a mixed reply can be joined into one file."""
    import numpy as np

    with wave.open(io.BytesIO(audio)) as w:
        source_rate, frames = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), np.int16)
    positions = np.linspace(0, len(frames) - 1, int(len(frames) * rate / source_rate))
    out = np.interp(positions, np.arange(len(frames)), frames).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(out.tobytes())
    return buffer.getvalue()


def join_wavs(parts: list[bytes]) -> bytes:
    frames, params = [], None
    for part in parts:
        with wave.open(io.BytesIO(part)) as w:
            params = params or w.getparams()
            frames.append(w.readframes(w.getnframes()))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setparams(params)
        out.writeframes(b"".join(frames))
    return buffer.getvalue()


def generate() -> None:
    from app import config
    from app.services import reference_voice, stt, tts

    config.VOICE_AGENT_STT_DEVICE = "cpu"  # the checker stays off the GPU, which the voice models need
    OUT.mkdir(parents=True, exist_ok=True)
    whisper = stt.LocalWhisper()
    results = []
    for case, language, piper_text, reference_text, target, stt_mode in cases():
        reference_text = reference_text or piper_text
        target = target or piper_text or reference_text
        row = {"case": case, "language": language, "target": target}
        for voice, text in (("piper", piper_text), ("reference", reference_text)):
            if text is None:
                continue
            parts, first_ms, outputs, reasons = tts.speech_parts(text), None, [], []
            started = time.perf_counter()
            for index, part in enumerate(parts):
                t = time.perf_counter()
                if voice == "piper":
                    tts._fixed_audio.clear()
                    audio, _ = tts.synthesize_turn(part, "hi" if language == "hinglish" else language)
                else:
                    result = asyncio.run(reference_voice.synthesize_reference_voice(part, language, uuid.uuid4().hex))
                    audio = result.audio
                    if audio is None:  # as the app does: this sentence is spoken by the standard voice
                        reasons.append(result.fallback_reason)
                        audio, _ = tts.synthesize_turn(part, "hi" if language == "hinglish" else language)
                        audio = resample(audio, 24000)
                if index == 0:
                    first_ms = round((time.perf_counter() - t) * 1000)
                outputs.append(audio)
            if not outputs:
                row[voice] = {"failed": reasons}
                continue
            audio = join_wavs(outputs)
            path = OUT / f"{case}__{voice}.wav"
            path.write_bytes(audio)
            heard = whisper.transcribe(audio, stt_mode, "audio/wav")
            row[voice] = {"file": path.name, "fallback_parts": reasons, "first_audio_ms": first_ms, "total_ms": round((time.perf_counter() - started) * 1000),
                          "audio_seconds": round(seconds(audio), 2), "heard": heard.text, "cer": cer(target, heard.text)}
        results.append(row)
        print(json.dumps(row, ensure_ascii=False))
    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))


def compare() -> None:
    import librosa
    import numpy as np
    import torch
    from chatterbox.models.voice_encoder import VoiceEncoder
    from huggingface_hub import hf_hub_download

    encoder = VoiceEncoder()
    encoder.load_state_dict(torch.load(hf_hub_download("ResembleAI/chatterbox", "ve.pt"), weights_only=True))
    encoder.eval()

    def embed(path):
        x, _ = librosa.load(str(path), sr=16000)
        return encoder.embeds_from_wavs([x], sample_rate=16000)[0], x

    def pitch(x):
        f0, voiced, _ = librosa.pyin(x, fmin=70, fmax=400, sr=16000)
        return round(float(np.nanmedian(f0[voiced])), 1) if voiced.any() else None

    references = sorted((ROOT / "voices" / "reference").glob("*.wav"))
    ref_embeds = [embed(p) for p in references]
    centroid = np.mean([e for e, _ in ref_embeds], axis=0)
    cos = lambda a, b: round(float(a @ b / np.linalg.norm(a) / np.linalg.norm(b)), 3)  # noqa: E731
    summary = {"reference_pitch_hz": [pitch(x) for _, x in ref_embeds]}
    results = json.loads((OUT / "results.json").read_text())
    for row in results:
        for voice in ("piper", "reference"):
            info = row.get(voice)
            if not info or "file" not in info:
                continue
            e, x = embed(OUT / info["file"])
            info["similarity_to_reference"] = cos(e, centroid)
            info["pitch_hz"] = pitch(x)
            info["chars_per_second"] = round(len(normalise(row["target"]).replace(" ", "")) / info["audio_seconds"], 1)
        print(row["case"], {v: {k: row[v].get(k) for k in ("similarity_to_reference", "pitch_hz", "chars_per_second", "cer",
                                                            "first_audio_ms")} for v in ("piper", "reference") if v in row})
    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    print(summary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["generate", "compare"])
    {"generate": generate, "compare": compare}[parser.parse_args().step]()
