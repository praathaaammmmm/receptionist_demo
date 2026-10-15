import re

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import Patient
from .errors import DuplicatePatientError, NotFoundError, ValidationError

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_mobile(raw: str | None) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if not 7 <= len(digits) <= 15:
        raise ValidationError("Please enter a valid mobile number (7 to 15 digits).")
    return digits


def get_patient(db: Session, patient_id: int) -> Patient:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise NotFoundError("We could not find that patient.")
    return patient


def find_by_mobile(db: Session, mobile: str) -> Patient | None:
    return db.scalar(select(Patient).where(Patient.mobile == mobile))


def create_patient(
    db: Session,
    *,
    name: str,
    mobile: str,
    email: str | None = None,
    notes: str | None = None,
    is_demo: bool = False,
) -> Patient:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Please enter the patient's name.")
    mobile = normalize_mobile(mobile)
    email = (email or "").strip() or None
    if email and not _EMAIL_RE.match(email):
        raise ValidationError("Please enter a valid email address, or leave it blank.")
    notes = (notes or "").strip() or None

    existing = find_by_mobile(db, mobile)
    if existing:
        raise DuplicatePatientError(existing)

    patient = Patient(name=name, mobile=mobile, email=email, notes=notes, is_demo=is_demo)
    db.add(patient)
    try:
        db.commit()
    except IntegrityError:
        # Someone registered the same mobile number at the same moment.
        db.rollback()
        raise DuplicatePatientError(find_by_mobile(db, mobile)) from None
    return patient


def search_patients(db: Session, query: str | None = None, limit: int = 25) -> list[Patient]:
    """Search by name or mobile number. An empty query returns the newest patients."""
    term = (query or "").strip()
    stmt = select(Patient)
    if term:
        conditions = [Patient.name.icontains(term, autoescape=True)]
        digits = re.sub(r"\D", "", term)
        if digits:
            conditions.append(Patient.mobile.contains(digits))
        stmt = stmt.where(or_(*conditions)).order_by(Patient.name)
    else:
        stmt = stmt.order_by(Patient.created_at.desc(), Patient.id.desc())
    return list(db.scalars(stmt.limit(limit)))
