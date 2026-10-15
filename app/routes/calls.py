"""Browser voice-call simulation: a demo page plus a thin wrapper around the assistant.

Local simulation only. Nothing here connects to a phone network, records audio
or calls an AI provider. Each turn goes through app/services/assistant.py, so a
simulated call behaves exactly like the website assistant.
"""
import re

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from .. import config, knowledge, schemas
from ..database import get_db
from ..ratelimit import assistant_rate_limit, speech_rate_limit
from ..services import assistant, calls, clinic, tts
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


@router.get("/call-demo", include_in_schema=False)
def call_demo_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "call_demo.html",
        {
            "clinic": clinic.get_clinic(db),
            "shortcuts": knowledge.VOICE_DEMO_SHORTCUTS,
            "hours": knowledge.CLINIC_HOURS,
            # With the local voice pack every browser can play audio. Without it, Firefox starts in
            # text mode from the first paint and the page script decides for other browsers.
            "server_voice": tts.available(),
            "text_mode": "firefox" if is_firefox(request.headers.get("user-agent")) and not tts.available() else None,
            "text_mode_message": TEXT_MODE_MESSAGE,
            "text_mode_reasons": TEXT_MODE_REASONS,
        },
    )


@router.post("/api/call-demo/start", status_code=201, tags=["call demo"], dependencies=limited)
def start_call(db: Session = Depends(get_db)):
    call = calls.start_call(db)
    reply = assistant.respond(db, action="start")
    name = clinic.get_clinic(db).name
    reply["messages"] = [{"text": line.format(clinic=name)} for line in knowledge.VOICE_GREETING]
    reply["options"] = []  # the page offers its own caller phrases
    return {"call": schemas.call_out(call), "reply": reply}


@router.post("/api/call-demo/{call_id}/message", tags=["call demo"], dependencies=limited)
def call_message(call_id: int, body: schemas.AssistantMessage, db: Session = Depends(get_db)):
    call = calls.get_active_call(db, call_id)
    reply = assistant.respond(db, text=body.text, action=body.action, value=body.value, state=body.state)
    return {"call": schemas.call_out(calls.record_turn(db, call, reply)), "reply": reply}


@router.post("/api/call-demo/{call_id}/end", tags=["call demo"])
def end_call(call_id: int, db: Session = Depends(get_db)):
    return {"call": schemas.call_out(calls.end_call(db, call_id))}


@router.get("/api/call-demo/voice", tags=["call demo"])
def voice_status():
    """Whether the optional local voice pack is installed."""
    return {
        "available": tts.available(),
        "engine": "piper",
        "voice": config.VOICE_NAME,
        "speaker": config.VOICE_SPEAKER or None,
        "runs": "locally",
    }


@router.post("/api/call-demo/speech", tags=["call demo"], dependencies=[Depends(speech_rate_limit)])
def speech(body: schemas.SpeechRequest):
    """Audio for one assistant reply, generated on this machine. Nothing is stored."""
    return Response(content=tts.synthesize(body.text), media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.get("/api/calls", tags=["call demo"])
def list_calls(db: Session = Depends(get_db)):
    return [schemas.call_out(c) for c in calls.list_recent(db, limit=50)]
