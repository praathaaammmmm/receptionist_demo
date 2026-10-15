"""Seeds demo data on first run. All seeded rows are flagged is_demo."""
from datetime import time

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import config, utils
from .models import (
    STATUS_CONFIRMED,
    Appointment,
    CallbackTask,
    CallLog,
    CheckinToken,
    Clinic,
    ConsultationFollowup,
    ConsultationOutcome,
    ConsultationStart,
    Doctor,
    DoctorPatientNote,
    PatientFlag,
    ProcedurePlan,
    DoctorBlock,
    Notification,
    ProcedureFollowup,
    Patient,
    Service,
    Slot,
    TimelineEvent,
    TreatmentRecommendation,
    WaitlistEntry,
)
from .services import appointments, availability, patients


def seed_if_empty(db: Session) -> bool:
    if db.scalar(select(Clinic.id).limit(1)) is not None:
        return False

    db.add(Clinic(**config.SEED_CLINIC, is_demo=True))
    for doctor in config.SEED_DOCTORS:
        db.add(
            Doctor(
                name=doctor["name"],
                speciality=doctor["speciality"],
                work_start=time.fromisoformat(doctor["work_start"]),
                work_end=time.fromisoformat(doctor["work_end"]),
                consultation_minutes=doctor["consultation_minutes"],
                working_days=",".join(str(d) for d in doctor["working_days"]),
                is_demo=True,
            )
        )
    for service in config.SEED_SERVICES:
        db.add(Service(**service, is_demo=True))
    db.commit()

    availability.ensure_slots(db)
    _seed_sample_bookings(db)
    return True


def reset_demo_data(db: Session) -> dict:
    """Wipe everything and restore the seeded demo state.

    DEMO DATA ONLY: never run against real patient data. This deletes every
    patient, booking, callback task and call log. It is deliberately not
    reachable from any page or API route; use scripts/reset_demo.py.
    """
    # Children first, so foreign keys are satisfied on any database.
    for model in (
        ProcedurePlan, PatientFlag, DoctorPatientNote, ConsultationFollowup, ProcedureFollowup, Notification, WaitlistEntry, CheckinToken, TimelineEvent, TreatmentRecommendation, ConsultationOutcome, ConsultationStart, CallLog, CallbackTask, DoctorBlock, Appointment, Slot, Patient,
        Service, Doctor, Clinic,
    ):
        db.execute(delete(model))
    db.commit()
    seed_if_empty(db)
    return {
        "doctors": len(db.scalars(select(Doctor.id)).all()),
        "services": len(db.scalars(select(Service.id)).all()),
        "patients": len(db.scalars(select(Patient.id)).all()),
        "appointments": len(db.scalars(select(Appointment.id)).all()),
        "slots": len(db.scalars(select(Slot.id)).all()),
        "callback_tasks": len(db.scalars(select(CallbackTask.id)).all()),
        "call_logs": len(db.scalars(select(CallLog.id)).all()),
    }


def _seed_sample_bookings(db: Session) -> None:
    """A few sample patients and bookings so the dashboard is not empty."""
    now = utils.now()
    doctors = availability.list_doctors(db)
    services = appointments.list_services(db)
    sources = ("STAFF", "WEBSITE", "AI_DEMO")
    days = availability.window_days(now.date())

    for i, data in enumerate(config.SEED_PATIENTS):
        patient = patients.create_patient(db, **data, is_demo=True)
        doctor = doctors[i % len(doctors)]
        # Spread the samples across the doctor's free slots so they land on different times/days.
        free = [
            view.slot
            for day in days
            for view in availability.slots_for_day(db, doctor.id, day, now)
            if view.available
        ]
        if not free:
            continue
        slot = free[min(1 + i * 4, len(free) - 1)]
        appointment = appointments.create_appointment(
            db,
            patient_id=patient.id,
            slot_id=slot.id,
            service_id=services[i % len(services)].id,
            reason="Sample booking",
            source=sources[i % len(sources)],
            is_demo=True,
            now=now,
        )
        if i == 0:
            appointments.set_status(db, appointment.id, STATUS_CONFIRMED)
