"""JSON booking API. Thin wrappers over app.services; Phase 2 can call these directly."""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..models import BOOKING_SOURCES
from ..services import appointments, availability, callbacks, clinic, patients, timeline

router = APIRouter(prefix="/api", tags=["booking"])


@router.get("/clinic")
def get_clinic(db: Session = Depends(get_db)):
    c = clinic.get_clinic(db)
    return {
        "name": c.name,
        "address": c.address,
        "phone": c.phone,
        "email": c.email,
        "currency_symbol": c.currency_symbol,
        "is_demo": c.is_demo,
        "booking_sources": list(BOOKING_SOURCES),
    }


@router.get("/doctors")
def list_doctors(db: Session = Depends(get_db)):
    return [schemas.doctor_out(d) for d in availability.list_doctors(db)]


@router.get("/services")
def list_services(db: Session = Depends(get_db)):
    return [schemas.service_out(s) for s in appointments.list_services(db)]


@router.get("/doctors/{doctor_id}/slots")
def doctor_slots(doctor_id: int, day: date = Query(alias="date"), db: Session = Depends(get_db)):
    return [schemas.slot_out(v) for v in availability.slots_for_day(db, doctor_id, day)]


@router.get("/patients")
def search_patients(q: str = "", db: Session = Depends(get_db)):
    return [schemas.patient_out(p) for p in patients.search_patients(db, q)]


@router.post("/patients", status_code=201)
def create_patient(body: schemas.PatientCreate, db: Session = Depends(get_db)):
    return schemas.patient_out(patients.create_patient(db, **body.model_dump()))


@router.get("/appointments")
def list_appointments(scope: str = "upcoming", db: Session = Depends(get_db)):
    rows = appointments.list_today(db) if scope == "today" else appointments.list_upcoming(db)
    return [schemas.appointment_out(a) for a in rows]


@router.post("/appointments", status_code=201)
def create_appointment(body: schemas.AppointmentCreate, db: Session = Depends(get_db)):
    return schemas.appointment_out(appointments.create_appointment(db, **body.model_dump()))


@router.post("/appointments/{appointment_id}/status")
def update_status(appointment_id: int, body: schemas.StatusUpdate, db: Session = Depends(get_db)):
    return schemas.appointment_out(appointments.set_status(db, appointment_id, body.status))


@router.get("/dashboard/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    return appointments.dashboard_summary(db)


@router.get("/callbacks")
def list_callbacks(status: str | None = None, db: Session = Depends(get_db)):
    return [schemas.callback_out(t) for t in callbacks.list_all(db, status)]


@router.post("/callbacks", status_code=201)
def create_callback(body: schemas.CallbackCreate, db: Session = Depends(get_db)):
    return schemas.callback_out(callbacks.create_callback(db, **body.model_dump()))


@router.post("/callbacks/{task_id}/status")
def update_callback_status(task_id: int, body: schemas.CallbackStatusUpdate, db: Session = Depends(get_db)):
    return schemas.callback_out(callbacks.set_status(db, task_id, body.status, body.notes))


@router.get("/callbacks/summary")
def callbacks_summary(db: Session = Depends(get_db)):
    return callbacks.counts(db)


@router.get("/patients/{patient_id}/timeline")
def patient_timeline(patient_id: int, db: Session = Depends(get_db)):
    """Read-only, staff-safe history for one patient, newest first."""
    patient = patients.get_patient(db, patient_id)
    events = [{**e, "at": e["at"].isoformat()} for e in timeline.build(db, patient)]
    return {"patient": schemas.patient_out(patient), "read_only": True, "events": events}
