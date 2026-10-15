"""Editable demo configuration and seed values.

Everything here is sample data for a demo. Change the values below (or edit
them later on the Settings page) and delete the database file to re-seed.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# SQLite for the demo; point DATABASE_URL at PostgreSQL to migrate later.
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'clinic_demo.db'}")

# Clinic-wide closed weekdays (0 = Monday ... 6 = Sunday). No slots are created or bookable on
# these days, whatever an individual doctor's working days say. Keep in step with CLINIC_HOURS
# in knowledge.py.
CLINIC_CLOSED_WEEKDAYS = (6,)

# Consultation slots are kept seeded for this many days, starting today.
SLOT_WINDOW_DAYS = 7

# Public assistant endpoint: at most this many messages per client address per window.
ASSISTANT_RATE_LIMIT = 40
ASSISTANT_RATE_WINDOW_SECONDS = 60
# Spoken replies in the call demo are limited separately (one audio request per reply).
SPEECH_RATE_LIMIT = 60

# Optional natural voice for the call demo (Piper, runs locally, no internet once downloaded).
# Install with:  pip install -r requirements-voice.txt  &&  python scripts/download_voice.py
# Without it the call demo falls back to the browser's own voice or to text simulation mode.
VOICE_DIR = BASE_DIR / "voices"
VOICE_NAME = os.getenv("CALL_DEMO_VOICE", "en_GB-cori-medium")
# Speaker within a multi-speaker voice, by name or number (for example "SVBI" in
# en_US-l2arctic-medium). Leave empty for single-speaker voices.
VOICE_SPEAKER = os.getenv("CALL_DEMO_VOICE_SPEAKER", "")

# Procedures a doctor may select for a draft treatment recommendation in the doctor workspace.
# Demo list only; the clinic owner must approve the real one.
DEMO_PROCEDURES = [
    "Implant consultation",
    "Root canal treatment assessment",
    "Aligner assessment",
    "Crown/bridge assessment",
]

# QR check-in window around the appointment start, on the appointment's own date.
# None for "minutes before" means from the start of that day, so the demo can be shown at any hour;
# a real clinic would use something like 120.
CHECKIN_OPENS_MINUTES_BEFORE = None
CHECKIN_CLOSES_MINUTES_AFTER = 60

# Which existing service a procedure follow-up is booked under. The follow-up is a discussion
# appointment in a normal consultation slot, not delivery of the procedure.
PROCEDURE_SERVICES = {
    "Implant consultation": "Dental Implants",
    "Root canal treatment assessment": "Root Canal Treatment",
    "Aligner assessment": "Aligners",
    "Crown/bridge assessment": "General Consultation",
}
FOLLOWUP_DEFAULT_SERVICE = "General Consultation"

SLOT_TAKEN_MESSAGE = "This slot has just been booked. Please choose another available time."

# Only the clinic name is real. Address, phone, email, doctors, hours and fees below are
# placeholders that the clinic owner must supply or approve before any public use.
SEED_CLINIC = {
    "name": "Smriti Raj Dentistry",
    "address": "12 Sample Street, Demo City 000000",
    "phone": "+00 00000 00000",
    "email": "frontdesk@example.com",
    "currency_symbol": "₹",
}

# working_days: 0 = Monday ... 6 = Sunday
# The demo clinic is closed on Sunday (see CLINIC_HOURS in knowledge.py), so no doctor lists day 6.
SEED_DOCTORS = [
    {
        "name": "Dr. Anika Rao",
        "speciality": "General Dentistry",
        "work_start": "09:00",
        "work_end": "17:00",
        "consultation_minutes": 30,
        "working_days": [0, 1, 2, 3, 4, 5],
    },
    {
        "name": "Dr. Vikram Shah",
        "speciality": "Implantology & Oral Surgery",
        "work_start": "10:00",
        "work_end": "18:00",
        "consultation_minutes": 45,
        "working_days": [0, 1, 2, 3, 4],
    },
    {
        "name": "Dr. Meera Iyer",
        "speciality": "Endodontics & Orthodontics",
        "work_start": "12:00",
        "work_end": "20:00",
        "consultation_minutes": 30,
        "working_days": [1, 2, 3, 4, 5],
    },
]

# fee = demo consultation fee in whole currency units (not the clinic's real prices)
SEED_SERVICES = [
    {"name": "General Consultation", "fee": 500},
    {"name": "Dental Implants", "fee": 1500},
    {"name": "Root Canal Treatment", "fee": 1000},
    {"name": "Aligners", "fee": 1200},
]

SEED_PATIENTS = [
    {"name": "Demo Patient One", "mobile": "5550100001", "email": "patient.one@example.com", "notes": "Sample record"},
    {"name": "Demo Patient Two", "mobile": "5550100002", "email": None, "notes": "Sample record"},
    {"name": "Demo Patient Three", "mobile": "5550100003", "email": "patient.three@example.com", "notes": None},
    {"name": "Demo Patient Four", "mobile": "5550100004", "email": None, "notes": None},
]
