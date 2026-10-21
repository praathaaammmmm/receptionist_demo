import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import sessionmaker

from . import config, utils
from .database import Base, add_missing_columns, make_engine, upgrade_data
from .ratelimit import RateLimiter
from .routes import (
    analytics, api, assistant, calls, checkin, doctor, followups, notifications, pages, voice_agent, waitlist,
)
from .seed import seed_if_empty
from .services import availability, stt, voice_agent_demo
from .voice_agent import llm
from .services.errors import ClinicError

APP_DIR = Path(__file__).resolve().parent


def create_app(database_url: str | None = None) -> FastAPI:
    engine = make_engine(database_url)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    Base.metadata.create_all(engine)
    add_missing_columns(engine)
    upgrade_data(engine)
    with session_factory() as db:
        seed_if_empty(db)
        availability.ensure_slots(db)

    app = FastAPI(title="Dental Front Desk Demo", version="0.1.0")
    app.state.session_factory = session_factory
    app.state.slots_seeded_for = utils.now().date()
    app.state.assistant_limiter = RateLimiter(config.ASSISTANT_RATE_LIMIT, config.ASSISTANT_RATE_WINDOW_SECONDS)
    app.state.speech_limiter = RateLimiter(config.SPEECH_RATE_LIMIT, config.ASSISTANT_RATE_WINDOW_SECONDS)
    app.state.voice_agent_sessions = voice_agent_demo.SessionStore()
    # Both are lazy: nothing is loaded or contacted until a call needs it.
    app.state.transcriber = stt.LocalWhisper()
    app.state.voice_agent_router = llm.router_from_config()
    # Warm the installed speech models in the background so the first call is quick (never downloads).
    threading.Thread(target=voice_agent_demo.warm_up, args=(app,), daemon=True).start()

    @app.exception_handler(ClinicError)
    def clinic_error_handler(_request: Request, exc: ClinicError):
        body = {"error": exc.code, "message": exc.message}
        patient = getattr(exc, "patient", None)
        if patient is not None:
            from .schemas import patient_out

            body["patient"] = patient_out(patient)
        return JSONResponse(body, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    def request_validation_handler(_request: Request, _exc: RequestValidationError):
        return JSONResponse(
            {"error": "invalid_request", "message": ClinicError.default_message}, status_code=422
        )

    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    app.include_router(api.router)
    app.include_router(assistant.router)
    app.include_router(calls.router)
    app.include_router(voice_agent.router)
    app.include_router(doctor.router)
    app.include_router(checkin.router)
    app.include_router(waitlist.router)
    app.include_router(notifications.router)
    app.include_router(analytics.router)
    app.include_router(followups.router)
    app.include_router(pages.router)
    return app


app = create_app()
