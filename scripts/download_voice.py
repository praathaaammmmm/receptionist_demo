"""Download the Piper voice used by the call demo into ./voices (about 60 MB, one time).

Usage:  python scripts/download_voice.py [voice-name]
Voice names look like en_GB-cori-medium or en_US-lessac-medium; the full list is at
https://huggingface.co/rhasspy/piper-voices. Set CALL_DEMO_VOICE to use a non-default voice.
"""
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402

BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


def voice_url(name: str) -> str:
    locale, speaker, quality = name.split("-")  # en_GB-cori-medium
    return f"{BASE_URL}/{locale.split('_')[0]}/{locale}/{speaker}/{quality}/{name}.onnx"


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else config.VOICE_NAME
    config.VOICE_DIR.mkdir(exist_ok=True)
    for suffix in (".onnx.json", ".onnx"):
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
    print(f"Voice '{name}' is ready in {config.VOICE_DIR}")


if __name__ == "__main__":
    main()
