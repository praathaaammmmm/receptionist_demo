from pathlib import Path

from fastapi import Request
from sqlalchemy import create_engine, event, inspect, text
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


def add_missing_columns(engine: Engine) -> list[str]:
    """Additive schema upgrade for an existing database.

    `create_all` creates new tables but never adds columns to tables that already exist, so a demo
    database from an earlier version would fail on a newer model. This adds any missing *nullable*
    column (new columns are always declared nullable for this reason). It never drops, renames or
    rewrites anything. Returns the columns it added.
    """
    added = []
    existing_tables = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            present = {c["name"] for c in inspect(connection).get_columns(table.name)}
            for column in table.columns:
                if column.name in present or not column.nullable:
                    continue
                kind = column.type.compile(dialect=engine.dialect)
                connection.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {kind}'))
                added.append(f"{table.name}.{column.name}")
    return added


def upgrade_data(engine: Engine) -> None:
    """One-off data moves between versions. Safe to run on every start.

    Follow-up preferences briefly lived in their own table (`followup_preferences`); they are now
    columns on `consultation_followups`. Copy any that exist across, then drop the old table.
    """
    if "followup_preferences" not in inspect(engine).get_table_names():
        return
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE consultation_followups SET "
            "duration_minutes = (SELECT duration_minutes FROM followup_preferences p WHERE p.request_id = consultation_followups.id), "
            "timeframe = (SELECT timeframe FROM followup_preferences p WHERE p.request_id = consultation_followups.id), "
            "by_date = (SELECT by_date FROM followup_preferences p WHERE p.request_id = consultation_followups.id) "
            "WHERE id IN (SELECT request_id FROM followup_preferences)"
        ))
        connection.execute(text("DROP TABLE followup_preferences"))


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
