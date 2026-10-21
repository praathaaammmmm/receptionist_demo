"""Download the local speech-to-text model for the voice agent demo (one time, explicit).

Usage:
  python scripts/download_stt_model.py            # the model in VOICE_AGENT_STT_MODEL (default large-v3-turbo)
  python scripts/download_stt_model.py small      # another faster-whisper model, e.g. small or medium

The app never downloads a model by itself. Models go to VOICE_AGENT_STT_DIR (default ./models/stt,
ignored by Git). Sizes: small about 0.5 GB, large-v3-turbo about 1.6 GB. Needs:
pip install -r requirements-voice.txt
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402
from app.services import stt  # noqa: E402


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else config.VOICE_AGENT_STT_MODEL
    try:
        from faster_whisper import download_model
    except ImportError:
        print("faster-whisper is not installed. Run: pip install -r requirements-voice.txt")
        return 1
    target = stt.model_dir(name)
    if stt.model_installed(name):
        print(f"already present: {target}")
        return 0
    target.mkdir(parents=True, exist_ok=True)
    print(f"downloading faster-whisper model '{name}' to {target} ...")
    download_model(name, output_dir=str(target))
    print("done" if stt.model_installed(name) else "download incomplete: please run again")
    return 0 if stt.model_installed(name) else 1


if __name__ == "__main__":
    raise SystemExit(main())
