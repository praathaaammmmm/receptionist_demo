"""Browser voice agent demo: /voice-agent-demo and its small session API.

Separate from /assistant and /call-demo. Every conversation decision is checked by the
app/voice_agent policy package; callbacks and the call log use the existing services.

Microphone: the page records one phrase with MediaRecorder and posts it to
/api/voice-agent-demo/transcribe, where the configured speech-to-text adapter (local
faster-whisper by default) turns it into text. The audio is processed in memory and dropped;
it is never stored. Replies are spoken by the existing local Piper endpoint
(/api/call-demo/speech). No telephony, recording or booking.
"""
import asyncio
import threading
import time
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from .. import knowledge_translations as call_wording
from ..database import get_db
from ..ratelimit import RateLimiter, assistant_rate_limit, speech_rate_limit
from ..services.errors import RateLimitedError
from ..schemas import VoiceAgentMessage, VoiceAgentSpeech, VoiceAgentStart
from ..services import reference_voice, stt, tts, voice_agent_demo
from ..services.errors import ValidationError
from ..voice_agent import wording
from .pages import templates

router = APIRouter()
limited = [Depends(assistant_rate_limit)]
# Replies are spoken sentence by sentence, so this endpoint gets more requests per turn than the call demo's.
_speech_limiter = RateLimiter(240, 60)


def sentence_rate_limit(request: Request) -> None:
    if not _speech_limiter.allow(request.client.host if request.client else "unknown"):
        raise RateLimitedError()

LANGUAGE_CHOICES = (
    {"code": "en", "label": "English", "html_lang": "en"},
    {"code": "hi", "label": "हिंदी", "html_lang": "hi"},
    {"code": "hinglish", "label": "Hinglish", "html_lang": "hi-Latn"},
)


def store(request: Request) -> voice_agent_demo.SessionStore:
    return request.app.state.voice_agent_sessions


def transcriber(request: Request) -> stt.SpeechToText:
    return request.app.state.transcriber


def language_router(request: Request):
    return request.app.state.voice_agent_router


def understanding_status(request: Request) -> dict:
    llm = language_router(request)
    if llm is None:
        return {"enabled": False, "label": "Rule-based policy (no language model configured)"}
    status = llm.status()
    return {**status, "label": f"Language model: {status['provider']} {status['model']}, with rule-based fallback"}


@router.get("/voice-agent-demo", include_in_schema=False)
def voice_agent_page(request: Request):
    """The page only. Loading it starts no call, loads no model and writes nothing."""
    languages = [{**choice, "voice": tts.status(choice["code"])} for choice in LANGUAGE_CHOICES]
    microphone = transcriber(request).status()
    reference = reference_voice.status()  # offered only when the authorised clips and the local worker are ready
    return templates.TemplateResponse(
        request,
        "voice_agent_demo.html",
        {
            "languages": languages,
            "scenarios": wording.DEMO_SCENARIOS,
            "microphone": microphone,
            "understanding": understanding_status(request),
            "reference": reference,
            "config": {
                "languages": languages,
                "scenarios": wording.DEMO_SCENARIOS,
                "voiceMissing": call_wording.VOICE_MISSING_MESSAGE,
                "microphone": microphone,
                "lowConfidence": stt.LOW_CONFIDENCE_MESSAGE,
                "referenceVoice": {"available": reference["available"], "languages": reference.get("languages", []),
                                   "fallbackMessage": reference_voice.FALLBACK_MESSAGE},
                # Approved fixed lines the page shows and speaks itself (both are pre-generated and cached).
                "phrases": {key: {lang: {"text": wording.line(key, lang),
                                         "speech": wording.line(key, "hi" if lang == "hinglish" else lang),
                                         # the same sentence parts the server pre-generates and caches
                                         "parts": tts.speech_parts(wording.line(key, "hi" if lang == "hinglish" else lang)),
                                         "voice_language": lang}
                                  for lang in ("en", "hi", "hinglish")}
                            for key in ("one_moment", "low_confidence_retry")},
                "maxRecordSeconds": min(15, int(stt.config.VOICE_AGENT_STT_MAX_SECONDS)),
            },
        },
    )


@router.post("/api/voice-agent-demo/start", status_code=201, tags=["voice agent demo"], dependencies=limited)
def start_call(request: Request, body: VoiceAgentStart | None = None, db: Session = Depends(get_db)):
    session, turn = voice_agent_demo.start(store(request), body or VoiceAgentStart(), router=language_router(request))
    return voice_agent_demo.snapshot(db, session, turn)


@router.post("/api/voice-agent-demo/{session_id}/message", tags=["voice agent demo"], dependencies=limited)
def call_message(request: Request, session_id: str, body: VoiceAgentMessage, db: Session = Depends(get_db)):
    uncertain = body.speech_confidence == "low" and not body.reviewed
    session, turn = voice_agent_demo.message(db, store(request), session_id, body.text, body.language, heard=body.heard,
                                             uncertain=uncertain)
    return voice_agent_demo.snapshot(db, session, turn)


@router.post("/api/voice-agent-demo/{session_id}/end", tags=["voice agent demo"])
def end_call(request: Request, session_id: str, db: Session = Depends(get_db)):
    session, already = voice_agent_demo.end(db, store(request), session_id)
    return {**voice_agent_demo.snapshot(db, session), "already_ended": already}


@router.get("/api/voice-agent-demo/transcription", tags=["voice agent demo"])
def transcription_status(request: Request):
    return transcriber(request).status()


@router.post("/api/voice-agent-demo/transcribe", tags=["voice agent demo"], dependencies=[Depends(speech_rate_limit)])
async def transcribe(request: Request, language: str = Query("en")):
    """Text for one recorded phrase (the request body is the audio). Nothing is stored: the audio is
    decoded and transcribed in memory, then dropped, and only the text is returned."""
    if language not in stt.LANGUAGES:
        raise ValidationError("That language is not available for transcription.")
    received = time.perf_counter()
    audio = await request.body()
    try:
        # In a worker thread, so the server stays responsive while the model runs.
        result = await asyncio.to_thread(transcriber(request).transcribe, audio, language,
                                         request.headers.get("content-type"))
    finally:
        del audio
    return {
        "text": result.text,
        "language": result.language,
        "mode": stt.MODES[result.language],
        "audio_seconds": result.audio_seconds,
        "processing_seconds": result.processing_seconds,
        "model": result.model,
        "device": result.device,
        "confidence": result.confidence,
        "low_confidence": result.low_confidence or not result.text,
        "message": stt.LOW_CONFIDENCE_MESSAGE if (result.low_confidence or not result.text) else None,
        "detected_language": result.detected_language,
        "script": result.script,
        # This request only, for the page's timing panel; never stored.
        "timings": {**(result.timings or {}), "server_ms": round((time.perf_counter() - received) * 1000)},
        "stored": False,
    }


@router.post("/api/voice-agent-demo/speech", tags=["voice agent demo"], dependencies=[Depends(sentence_rate_limit)])
async def speech(request: Request, body: VoiceAgentSpeech):
    """Audio for one sentence of a reply, from the local Piper voice, generated in a worker thread.
    If the page cancels (a newer turn, mute, End call), synthesis stops at the next audio chunk.
    Only approved fixed phrases are cached; nothing a caller said is kept.

    With voice="reference", the optional consented reference voice is tried first. If it cannot speak this
    sentence (unavailable, unsupported language, too slow, failed), the standard Piper voice speaks it instead
    and the headers say so: X-Voice-Mode is "reference" only when the reference voice really spoke."""
    started = time.perf_counter()
    fallback_reason = None
    if body.voice == "reference":
        disconnected = asyncio.Event()

        async def watch():
            while not disconnected.is_set():
                if await request.is_disconnected():
                    disconnected.set()
                    return
                await asyncio.sleep(0.05)

        watcher = asyncio.ensure_future(watch())
        try:
            result = await reference_voice.synthesize_reference_voice(body.text, body.language, uuid.uuid4().hex,
                                                                      disconnected)
        finally:
            watcher.cancel()
        if disconnected.is_set():
            return Response(status_code=204, headers={"Cache-Control": "no-store"})
        if result.audio is not None:  # not cached: generated reference speech is returned once and dropped
            return Response(content=result.audio, media_type="audio/wav", headers={
                "Cache-Control": "no-store",
                "X-Voice-Mode": "reference",
                "X-Voice": result.backend,
                "X-Synthesis-Ms": str(round((time.perf_counter() - started) * 1000)),
                "X-Phrase-Cache": "miss",
            })
        fallback_reason = result.fallback_reason
    cancel = threading.Event()
    task = asyncio.ensure_future(asyncio.to_thread(tts.synthesize_turn, body.text, body.language, cancel))
    while not task.done():
        await asyncio.wait({task}, timeout=0.05)
        if not task.done() and await request.is_disconnected():
            cancel.set()
    try:
        audio, cached = task.result()
    except tts.SynthesisCancelled:
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
    voice, speaker = tts.voice_for(body.language)
    headers = {
        "Cache-Control": "no-store",
        "X-Voice": voice + (f"; speaker={speaker}" if speaker else ""),
        "X-Synthesis-Ms": str(round((time.perf_counter() - started) * 1000)),
        "X-Phrase-Cache": "hit" if cached else "miss",
        "X-Voice-Mode": "fallback" if fallback_reason else "standard",
    }
    if fallback_reason:
        headers["X-Voice-Fallback-Reason"] = fallback_reason
    return Response(content=audio, media_type="audio/wav", headers=headers)
