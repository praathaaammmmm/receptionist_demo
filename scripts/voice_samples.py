"""Write short audio samples of call-demo voices to ./voices/samples for comparison.

Usage:  python scripts/voice_samples.py     then open voices/samples/index.html
"""
import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config, knowledge_translations  # noqa: E402
from app.services import tts  # noqa: E402

TEXT = {
    "en": (
        "Thank you for calling Smriti Raj Dentistry. The clinic is closed at the moment, so you have reached "
        "our automated assistant. I can help you book a consultation, or ask our front desk to call you."
    ),
    "hi": (
        "Smriti Raj Dentistry में कॉल करने के लिए धन्यवाद। इस समय क्लिनिक बंद है, इसलिए आप हमारे स्वचालित "
        "असिस्टेंट से बात कर रहे हैं। रविवार को क्लिनिक बंद रहता है।"
    ),
    # Hinglish is shown in Roman Hindi; this is its reviewed Devanagari speech text.
    "hinglish": (
        "स्मृति राज डेंटिस्ट्री को कॉल करने के लिए धन्यवाद। अभी क्लिनिक बंद है, इसलिए आप हमारे ऑटोमेटेड "
        "असिस्टेंट से बात कर रहे हैं। रविवार को क्लिनिक बंद रहता है।"
    ),
}
# (language, voice pack, speaker, description). Indian-accent English speakers come from two research
# recordings of Indian English speakers that Piper's multi-speaker voices were trained on.
CANDIDATES = [
    ("en", "en_US-l2arctic-medium", "SVBI", "Indian accent, female (L2-ARCTIC speaker SVBI)"),
    ("en", "en_US-l2arctic-medium", "TNI", "Indian accent, female (L2-ARCTIC speaker TNI)"),
    ("en", "en_US-l2arctic-medium", "ASI", "Indian accent, male (L2-ARCTIC speaker ASI)"),
    ("en", "en_US-l2arctic-medium", "RRBI", "Indian accent, male (L2-ARCTIC speaker RRBI)"),
    ("en", "en_GB-vctk-medium", "p248", "Indian accent, female (VCTK speaker p248)"),
    ("en", "en_GB-vctk-medium", "p251", "Indian accent, male (VCTK speaker p251)"),
    ("en", "en_GB-cori-medium", "", "British, female (demo default)"),
    ("hi", "hi_IN-priyamvada-medium", "", "Hindi, female (single speaker, demo default)"),
    ("hinglish", "hi_IN-priyamvada-medium", "", "Hinglish conversation · Hindi local voice (demo default)"),
]


def main() -> None:
    out = config.VOICE_DIR / "samples"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for language, voice, speaker, label in CANDIDATES:
        if language in ("hi", "hinglish"):
            config.VOICE_HINDI, config.VOICE_HINDI_SPEAKER = voice, speaker
        else:
            config.VOICE_ENGLISH, config.VOICE_ENGLISH_SPEAKER = voice, speaker
        if not tts.available(language):
            print(f"skipped (not downloaded): {voice}")
            continue
        name = f"{language}-{voice}{'-' + speaker if speaker else ''}.wav"
        (out / name).write_bytes(tts.synthesize(TEXT[language], language))
        heading = f"{knowledge_translations.LANGUAGES[language]['label']} · {voice}" + (f" · speaker {speaker}" if speaker else "")
        rows.append(f"<li><p><strong>{html.escape(heading)}</strong><br>{html.escape(label)}</p>"
                    f"<p lang=\"{knowledge_translations.LANGUAGES[language]['html_lang']}\">“{html.escape(TEXT[language])}”</p>"
                    f'<audio controls preload="none" src="{name}"></audio></li>')
        print(f"wrote {name}  [{language} | {voice} | {speaker or 'single speaker'}]")
    page = ("<!doctype html><meta charset='utf-8'><title>Call demo voice samples</title>"
            "<style>body{font:16px/1.5 system-ui;max-width:720px;margin:40px auto;padding:0 16px;background:#FCF8F2;color:#191919}"
            "li{margin:0 0 26px;list-style:none}ul{padding:0}p{margin:0 0 6px}audio{width:100%}</style>"
            f"<h1>Call demo voice samples</h1><ul>{''.join(rows)}</ul>")
    (out / "index.html").write_text(page, encoding="utf-8")
    print(f"open {out / 'index.html'}")


if __name__ == "__main__":
    main()
