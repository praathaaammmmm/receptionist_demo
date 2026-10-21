"""Browser voice-call simulation: a demo page plus a thin wrapper around the assistant.

Local simulation only. Nothing here connects to a phone network, records audio
or calls an AI provider. Each turn goes through app/services/assistant.py, so a
simulated call behaves exactly like the website assistant.
"""
import re

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from .. import knowledge, schemas
from .. import knowledge_translations as wording
from ..database import get_db
from ..ratelimit import assistant_rate_limit, speech_rate_limit
from ..services import assistant, call_language, calls, clinic, tts
from .pages import templates

router = APIRouter()
limited = [Depends(assistant_rate_limit)]

# Browser speech is optional. Where it is unreliable the page runs as a text simulation.
TEXT_MODE_MESSAGE = "Text simulation mode — the conversation transcript remains fully functional."
TEXT_MODE_REASONS = {
    "firefox": "Voice is switched off in Firefox, where browser speech is unreliable. The demo runs as a text simulation here.",
    "no-voice": "This browser has no speech voice, so the demo runs as a text simulation.",
    "failed": "Speech did not start in this browser, so this call continues as a text simulation. Reset the demo call to try again.",
}


def is_firefox(user_agent: str | None) -> bool:
    return bool(re.search(r"firefox|fxios", user_agent or "", re.I))


def _languages() -> list[dict]:
    """Language choices for the page, with each language's local voice and its approved screen text."""
    return [
        {
            "code": code,
            "label": wording.LANGUAGES[code]["label"],
            "html_lang": wording.LANGUAGES[code]["html_lang"],
            "voice": tts.status(code),
            "ui": wording.UI[code],
        }
        for code in wording.LANGUAGE_CODES
    ]


@router.get("/call-demo", include_in_schema=False)
def call_demo_page(request: Request, db: Session = Depends(get_db)):
    english_voice = tts.available("en")
    return templates.TemplateResponse(
        request,
        "call_demo.html",
        {
            "clinic": clinic.get_clinic(db),
            "shortcuts": [
                {"value": phrase, "labels": {code: call_language.localize_label(phrase, code) for code in wording.LANGUAGE_CODES}}
                for phrase in knowledge.VOICE_DEMO_SHORTCUTS
            ],
            "hours": knowledge.CLINIC_HOURS,
            "languages": _languages(),
            "voice_missing_message": wording.VOICE_MISSING_MESSAGE,
            # With the local English voice pack every browser can play audio. Without it, Firefox starts in
            # text mode from the first paint and the page script decides for other browsers.
            "server_voice": english_voice,
            "text_mode": "firefox" if is_firefox(request.headers.get("user-agent")) and not english_voice else None,
            "text_mode_message": TEXT_MODE_MESSAGE,
            "text_mode_reasons": TEXT_MODE_REASONS,
        },
    )


@router.post("/api/call-demo/start", status_code=201, tags=["call demo"], dependencies=limited)
def start_call(body: schemas.CallStart | None = None, db: Session = Depends(get_db)):
    language = body.language if body else wording.DEFAULT_LANGUAGE
    call = calls.start_call(db, language=language)
    reply = assistant.respond(db, action="start")
    name = clinic.get_clinic(db).name
    reply["messages"] = [
        {"text": line.format(clinic=name), "key": key, "params": {"clinic": name}}
        for key, line in zip(("voice_greeting", "voice_greeting_help"), knowledge.VOICE_GREETING)
    ]
    reply["options"] = []  # the page offers its own caller phrases
    return {"call": schemas.call_out(call), "reply": call_language.localize_reply(reply, language)}


@router.post("/api/call-demo/{call_id}/message", tags=["call demo"], dependencies=limited)
def call_message(call_id: int, body: schemas.CallMessage, db: Session = Depends(get_db)):
    call = calls.get_active_call(db, call_id)
    reply = assistant.respond(db, text=body.text, action=body.action, value=body.value, state=body.state)
    call.language = body.language
    return {
        "call": schemas.call_out(calls.record_turn(db, call, reply)),
        "reply": call_language.localize_reply(reply, body.language),
    }


@router.post("/api/call-demo/{call_id}/end", tags=["call demo"])
def end_call(call_id: int, body: schemas.CallEnd | None = None, db: Session = Depends(get_db)):
    call = calls.end_call(db, call_id, language=body.language if body else None)
    goodbye = call_language.message("goodbye", call_language.normalize(call.language), clinic=clinic.get_clinic(db).name)
    return {"call": schemas.call_out(call), "goodbye": goodbye}


@router.get("/api/call-demo/voice", tags=["call demo"])
def voice_status():
    """Which local voice packs are installed. English is reported at the top level for older clients."""
    english = tts.status("en")
    return {
        "available": english["available"],
        "engine": "piper",
        "voice": english["voice"],
        "speaker": english["speaker"],
        "runs": "locally",
        "languages": {code: tts.status(code) for code in wording.LANGUAGE_CODES},
    }


@router.post("/api/call-demo/speech", tags=["call demo"], dependencies=[Depends(speech_rate_limit)])
def speech(body: schemas.SpeechRequest):
    """Audio for one assistant reply in the chosen language, generated on this machine. Nothing is stored."""
    audio = tts.synthesize(body.text, body.language)
    voice, speaker = tts.voice_for(body.language)
    headers = {"Cache-Control": "no-store", "X-Voice": voice + (f"; speaker={speaker}" if speaker else "")}
    return Response(content=audio, media_type="audio/wav", headers=headers)


@router.get("/api/calls", tags=["call demo"])
def list_calls(db: Session = Depends(get_db)):
    return [schemas.call_out(c) for c in calls.list_recent(db, limit=50)]
