"""Clinic profile, doctor and service settings."""
from datetime import time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Clinic, Service
from . import availability
from .errors import NotFoundError, ValidationError


def get_clinic(db: Session) -> Clinic:
    return db.scalars(select(Clinic).order_by(Clinic.id)).first()


def closed_day_message(db: Session, day) -> str:
    """Staff- and patient-friendly sentence for a clinic-wide closed day."""
    return f"{get_clinic(db).name} is closed on {day:%A}."


def _required(value: str | None, label: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValidationError(f"Please enter the {label}.")
    return value


def update_clinic(db: Session, *, name, address, phone, email=None, currency_symbol="₹") -> Clinic:
    clinic = get_clinic(db)
    clinic.name = _required(name, "clinic name")
    clinic.address = _required(address, "clinic address")
    clinic.phone = _required(phone, "clinic phone number")
    clinic.email = (email or "").strip() or None
    clinic.currency_symbol = (currency_symbol or "").strip() or "₹"
    db.commit()
    return clinic


def update_doctor(
    db: Session,
    doctor_id: int,
    *,
    name: str,
    speciality: str,
    work_start: time,
    work_end: time,
    consultation_minutes: int,
    working_days: list[int],
):
    doctor = availability.get_doctor(db, doctor_id)
    if work_end <= work_start:
        raise ValidationError("Working hours must end after they start.")
    if not 5 <= consultation_minutes <= 240:
        raise ValidationError("Consultation duration must be between 5 and 240 minutes.")
    days = sorted({d for d in working_days if 0 <= d <= 6})
    if not days:
        raise ValidationError("Please choose at least one working day.")

    doctor.name = _required(name, "doctor's name")
    doctor.speciality = _required(speciality, "speciality")
    doctor.work_start = work_start
    doctor.work_end = work_end
    doctor.consultation_minutes = consultation_minutes
    doctor.working_days = ",".join(str(d) for d in days)
    db.commit()
    availability.regenerate_slots(db, doctor)
    return doctor


def update_service(db: Session, service_id: int, *, name: str, fee: int) -> Service:
    service = db.get(Service, service_id)
    if service is None:
        raise NotFoundError("We could not find that service.")
    if fee < 0:
        raise ValidationError("The fee cannot be negative.")
    service.name = _required(name, "service name")
    service.fee = fee
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ValidationError("Another service already uses that name.") from None
    return service
