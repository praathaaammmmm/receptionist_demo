"""Waitlist and cancellation fill: staff screens and staff API (demo).

Nothing here contacts a patient or books automatically. Offers and bookings
are explicit staff actions.
"""
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..models import CONTACT_PREFERENCES, TIME_PREFERENCES, WAITLIST_BOOKED, WAITLIST_CLOSED
from ..services import appointments, availability, patients, waitlist
from ..services.errors import ClinicError
from .pages import redirect, render

router = APIRouter()


class EntryBody(BaseModel):
    patient_id: int
    service_id: int
    doctor_id: int | None = None
    date_from: date
    date_to: date
    time_preference: str = "ANY"
    contact_preference: str = "PHONE"
    note: str | None = None


class OfferBody(BaseModel):
    slot_id: int


class BookBody(BaseModel):
    accepted: bool = False


def entry_out(e) -> dict:
    return {
        "id": e.id,
        "patient": {"id": e.patient.id, "name": e.patient.name, "mobile": e.patient.mobile},
        "service": e.service.name,
        "doctor": e.doctor.name if e.doctor else None,
        "date_from": e.date_from.isoformat(),
        "date_to": e.date_to.isoformat(),
        "time_preference": e.time_preference,
        "contact_preference": e.contact_preference,
        "status": e.status,
        "note": e.note,
        "source": e.source,
        "offered_slot_id": e.offered_slot_id,
        "appointment_id": e.appointment_id,
        "created_at": e.created_at.isoformat(),
    }


def page(request: Request, db: Session, error: ClinicError | None = None, form: dict | None = None):
    entries = waitlist.list_entries(db)
    context = {
        "active": "waitlist",
        "opportunities": waitlist.newly_available(db),
        "active_entries": [e for e in entries if e.status in waitlist.ACTIVE],
        "past_entries": [e for e in entries if e.status in (WAITLIST_BOOKED, WAITLIST_CLOSED)][-8:][::-1],
        "counts": waitlist.counts(db),
        "all_patients": patients.search_patients(db, "", limit=200),
        "doctors": availability.list_doctors(db),
        "services": appointments.list_services(db),
        "days": availability.window_days(),
        "time_preferences": TIME_PREFERENCES,
        "contact_preferences": CONTACT_PREFERENCES,
        "form": form or {},
    }
    if error is not None:
        context["notice"] = ("error", error.message)
    response = render(request, db, "waitlist.html", **context)
    if error is not None:
        response.status_code = error.status_code
    return response


@router.get("/waitlist", include_in_schema=False)
def waitlist_page(request: Request, db: Session = Depends(get_db)):
    return page(request, db)


@router.post("/waitlist", include_in_schema=False)
def waitlist_add(
    request: Request,
    patient_id: str = Form(""),
    new_name: str = Form(""),
    new_mobile: str = Form(""),
    service_id: int = Form(0),
    doctor_id: str = Form(""),
    date_from: str = Form(""),
    date_to: str = Form(""),
    time_preference: str = Form("ANY"),
    contact_preference: str = Form("PHONE"),
    note: str = Form(""),
    db: Session = Depends(get_db),
):
    form = {"patient_id": patient_id, "new_name": new_name, "new_mobile": new_mobile, "service_id": service_id,
            "doctor_id": doctor_id, "date_from": date_from, "date_to": date_to, "time_preference": time_preference,
            "contact_preference": contact_preference, "note": note}
    try:
        try:
            first, last = date.fromisoformat(date_from), date.fromisoformat(date_to)
        except ValueError:
            raise ClinicError("Please enter the preferred dates.") from None
        if patient_id.isdigit():
            patient = patients.get_patient(db, int(patient_id))
        elif new_name.strip() or new_mobile.strip():
            # A new patient, or the existing record if that mobile number is already registered.
            mobile = patients.normalize_mobile(new_mobile)
            patient = patients.find_by_mobile(db, mobile) or patients.create_patient(db, name=new_name, mobile=mobile)
        else:
            raise ClinicError("Please choose an existing patient or enter a new patient's name and mobile number.")
        waitlist.create_entry(
            db, patient_id=patient.id, service_id=service_id, doctor_id=int(doctor_id) if doctor_id.isdigit() else None,
            date_from=first, date_to=last, time_preference=time_preference, contact_preference=contact_preference, note=note,
        )
    except ClinicError as exc:
        return page(request, db, exc, form)
    return redirect("/waitlist", notice="waitlist_added")


@router.post("/waitlist/{entry_id}/offer", include_in_schema=False)
def waitlist_offer(request: Request, entry_id: int, slot_id: int = Form(0), db: Session = Depends(get_db)):
    try:
        waitlist.offer(db, entry_id, slot_id)
    except ClinicError as exc:
        return page(request, db, exc)
    return redirect("/waitlist", notice="waitlist_offered")


@router.post("/waitlist/{entry_id}/book", include_in_schema=False)
def waitlist_book(request: Request, entry_id: int, accepted: str = Form(""), db: Session = Depends(get_db)):
    try:
        appointment = waitlist.book(db, entry_id, accepted=accepted == "yes")
    except ClinicError as exc:
        return page(request, db, exc)
    return redirect("/", booked=appointment.id)


@router.post("/waitlist/{entry_id}/status", include_in_schema=False)
def waitlist_status(request: Request, entry_id: int, status: str = Form(""), db: Session = Depends(get_db)):
    try:
        if status == "WAITING":
            waitlist.return_to_waiting(db, entry_id)
        elif status == "CLOSED":
            waitlist.close(db, entry_id)
        else:
            raise ClinicError("That change is not available here.")
    except ClinicError as exc:
        return page(request, db, exc)
    return redirect("/waitlist", notice="waitlist_updated")


# --- Staff JSON API -----------------------------------------------------------------
@router.get("/api/waitlist", tags=["waitlist"])
def api_list(status: str | None = None, db: Session = Depends(get_db)):
    return [entry_out(e) for e in waitlist.list_entries(db, (status,) if status else None)]


@router.post("/api/waitlist", status_code=201, tags=["waitlist"])
def api_create(body: EntryBody, db: Session = Depends(get_db)):
    return entry_out(waitlist.create_entry(db, **body.model_dump()))


@router.get("/api/waitlist/opportunities", tags=["waitlist"])
def api_opportunities(db: Session = Depends(get_db)):
    """Slots freed by a cancellation and still free, with the waiting patients they suit."""
    return [
        {
            "slot": {"id": o["slot"].id, "doctor_id": o["slot"].doctor_id, "doctor": o["slot"].doctor.name,
                     "start_time": o["slot"].start_time.isoformat(), "end_time": o["slot"].end_time.isoformat()},
            "candidates": [entry_out(e) for e in o["candidates"]],
        }
        for o in waitlist.newly_available(db)
    ]


@router.get("/api/waitlist/summary", tags=["waitlist"])
def api_summary(db: Session = Depends(get_db)):
    return waitlist.counts(db)


@router.post("/api/waitlist/{entry_id}/offer", tags=["waitlist"])
def api_offer(entry_id: int, body: OfferBody, db: Session = Depends(get_db)):
    return entry_out(waitlist.offer(db, entry_id, body.slot_id))


@router.post("/api/waitlist/{entry_id}/status", tags=["waitlist"])
def api_status(entry_id: int, body: schemas.StatusUpdate, db: Session = Depends(get_db)):
    if body.status == "WAITING":
        return entry_out(waitlist.return_to_waiting(db, entry_id))
    if body.status == "CLOSED":
        return entry_out(waitlist.close(db, entry_id))
    raise ClinicError("Use the offer and book actions to move an entry to offered or booked.")


@router.post("/api/waitlist/{entry_id}/book", status_code=201, tags=["waitlist"])
def api_book(entry_id: int, body: BookBody, db: Session = Depends(get_db)):
    return schemas.appointment_out(waitlist.book(db, entry_id, accepted=body.accepted))
