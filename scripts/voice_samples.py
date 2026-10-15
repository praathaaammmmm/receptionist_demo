"""Write short audio samples of candidate call-demo voices to ./voices/samples for comparison.

Usage:  python scripts/voice_samples.py     then open voices/samples/index.html
"""
import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402
from app.services import tts  # noqa: E402

TEXT = (
    "Thank you for calling Smriti Raj Dentistry. The clinic is closed at the moment, so you have reached "
    "our automated assistant. I can help you book a consultation, or ask our front desk to call you."
)
# (voice pack, speaker, description). Indian-accent speakers come from two research
# recordings of Indian English speakers that Piper's multi-speaker voices were trained on.
CANDIDATES = [
    ("en_US-l2arctic-medium", "SVBI", "Indian accent, female (L2-ARCTIC speaker SVBI)"),
    ("en_US-l2arctic-medium", "TNI", "Indian accent, female (L2-ARCTIC speaker TNI)"),
    ("en_US-l2arctic-medium", "ASI", "Indian accent, male (L2-ARCTIC speaker ASI)"),
    ("en_US-l2arctic-medium", "RRBI", "Indian accent, male (L2-ARCTIC speaker RRBI)"),
    ("en_GB-vctk-medium", "p248", "Indian accent, female (VCTK speaker p248)"),
    ("en_GB-vctk-medium", "p251", "Indian accent, male (VCTK speaker p251)"),
    ("en_GB-vctk-medium", "p376", "Indian accent, male (VCTK speaker p376)"),
    ("en_GB-cori-medium", "", "British, female (current default, for comparison)"),
]


def main() -> None:
    out = config.VOICE_DIR / "samples"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for voice, speaker, label in CANDIDATES:
        config.VOICE_NAME, config.VOICE_SPEAKER = voice, speaker
        if not tts.available():
            print(f"skipped (not downloaded): {voice}")
            continue
        name = f"{voice}{'-' + speaker if speaker else ''}.wav"
        (out / name).write_bytes(tts.synthesize(TEXT))
        setting = f"CALL_DEMO_VOICE={voice}" + (f" CALL_DEMO_VOICE_SPEAKER={speaker}" if speaker else "")
        rows.append(f"<li><p><strong>{html.escape(label)}</strong><br><code>{html.escape(setting)}</code></p>"
                    f'<audio controls preload="none" src="{name}"></audio></li>')
        print(f"wrote {name}")
    page = ("<!doctype html><meta charset='utf-8'><title>Call demo voice samples</title>"
            "<style>body{font:16px/1.5 system-ui;max-width:720px;margin:40px auto;padding:0 16px;background:#FCF8F2;color:#191919}"
            "li{margin:0 0 22px;list-style:none}ul{padding:0}code{background:#EBE2D4;padding:2px 6px;border-radius:4px;font-size:.85em}"
            "audio{width:100%}</style><h1>Call demo voice samples</h1>"
            f"<p>Each sample says: “{html.escape(TEXT)}”</p><ul>{''.join(rows)}</ul>")
    (out / "index.html").write_text(page, encoding="utf-8")
    print(f"open {out / 'index.html'}")


if __name__ == "__main__":
    main()
