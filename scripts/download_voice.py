"""Download Piper voice packs for the call demo into ./voices (about 60-80 MB each, one time).

Usage:
  python scripts/download_voice.py --all-demo-languages   # every pack the demo languages need
  python scripts/download_voice.py [voice-name]           # one pack (default: the English voice)

The demo languages use CALL_DEMO_VOICE_ENGLISH (English) and CALL_DEMO_VOICE_HINDI (Hindi, and
Hinglish, which is spoken from Devanagari speech text); see app/config.py. Packs already present are
kept, never downloaded again. Voice names look like en_GB-cori-medium or hi_IN-priyamvada-medium;
the full list is at
https://huggingface.co/rhasspy/piper-voices. ./voices is ignored by Git.
"""
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402

BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
SUFFIXES = (".onnx.json", ".onnx")


def voice_url(name: str) -> str:
    locale, speaker, quality = name.split("-")  # en_GB-cori-medium
    return f"{BASE_URL}/{locale.split('_')[0]}/{locale}/{speaker}/{quality}/{name}.onnx"


def demo_voices() -> list[str]:
    """Packs the call-demo languages use, without duplicates."""
    return list(dict.fromkeys([config.VOICE_ENGLISH, config.VOICE_HINDI]))


def download(name: str) -> None:
    config.VOICE_DIR.mkdir(exist_ok=True)
    for suffix in SUFFIXES:
        target = config.VOICE_DIR / f"{name}{suffix}"
        if target.exists() and target.stat().st_size > 0:
            print(f"already present: {target.name}")
            continue
        url = voice_url(name) + suffix.removeprefix(".onnx")
        print(f"downloading {url}")
        partial = target.with_suffix(target.suffix + ".part")
        urllib.request.urlretrieve(url, partial)
        partial.rename(target)
        print(f"saved {target.name} ({target.stat().st_size / 1_000_000:.1f} MB)")


def verify(name: str) -> bool:
    """Both files are present and non-empty, and the .onnx.json is a Piper voice config."""
    import json

    model, settings = (config.VOICE_DIR / f"{name}{suffix}" for suffix in (".onnx", ".onnx.json"))
    try:
        ok = model.stat().st_size > 1_000_000 and "phoneme_id_map" in json.loads(settings.read_text())
    except (OSError, ValueError):
        ok = False
    print(f"{'verified' if ok else 'MISSING OR INCOMPLETE'}: {name}")
    return ok


def list_installed() -> None:
    print(f"\nInstalled voice packs in {config.VOICE_DIR}:")
    for model in sorted(config.VOICE_DIR.glob("*.onnx")):
        used = [label for label, voice in (("English", config.VOICE_ENGLISH), ("Hindi, Hinglish", config.VOICE_HINDI)) if voice == model.stem]
        note = f"  <- call demo: {', '.join(used)}" if used else ""
        print(f"  {model.stem:<28} {model.stat().st_size / 1_000_000:6.1f} MB{note}")


def main() -> None:
    args = sys.argv[1:]
    names = demo_voices() if args[:1] == ["--all-demo-languages"] else [args[0] if args else config.VOICE_ENGLISH]
    for name in names:
        download(name)
    ok = all([verify(name) for name in names])
    list_installed()
    if not ok:
        sys.exit("Some voice packs are incomplete. Delete them from ./voices and run this again.")


if __name__ == "__main__":
    main()
