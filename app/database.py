from pathlib import Path

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase

from . import config, utils


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None) -> Engine:
    url = url or config.DATABASE_URL
    if not url.startswith("sqlite"):
        return create_engine(url)

    db_path = make_url(url).database
    if db_path and db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def get_db(request: Request):
    """Request-scoped session. Also tops up the rolling slot window once a day."""
    from .services import availability

    state = request.app.state
    db = state.session_factory()
    try:
        today = utils.now().date()
        if state.slots_seeded_for != today:
            availability.ensure_slots(db, today)
            state.slots_seeded_for = today
        yield db
    finally:
        db.close()
