"""Reset the demo to its seeded state.

    DEMO DATA ONLY — never run against real patient data.

Deletes every patient, booking, callback task and call log in the demo database,
then restores the seeded clinic, doctors, services, sample patients, sample
bookings and consultation slots from app/config.py. Settings-page edits are lost.

Developer-only: this is not available from any page or API route.

Usage:
    python scripts/reset_demo.py          # asks for confirmation
    python scripts/reset_demo.py --yes    # no prompt (for a pre-demo checklist)

Safe to run while the app is running; reload the browser afterwards.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import config  # noqa: E402
from app.database import Base, make_engine  # noqa: E402
from app.seed import reset_demo_data  # noqa: E402

WARNING = "Demo data only — never run against real patient data."


def main() -> int:
    args = set(sys.argv[1:])
    url = config.DATABASE_URL
    print(WARNING)
    print(f"Database: {url}")
    if not url.startswith("sqlite") and "--allow-non-sqlite" not in args:
        print("Refusing to reset: this is not the local SQLite demo database.")
        print("If this really is a disposable demo database, add --allow-non-sqlite.")
        return 2
    if "--yes" not in args:
        answer = input("This deletes ALL patients, bookings, callbacks and call logs. Type 'reset' to continue: ")
        if answer.strip().lower() != "reset":
            print("Cancelled. Nothing was changed.")
            return 1

    engine = make_engine(url)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        counts = reset_demo_data(db)
    print("Demo reset complete:")
    for name, count in counts.items():
        print(f"  {name.replace('_', ' ')}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
