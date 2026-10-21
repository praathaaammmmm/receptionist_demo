"""Server-rendered reception screens. No business rules live here."""
from datetime import date, time
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .. import config, knowledge, schemas, utils
from ..database import get_db
from ..models import (
    BOOKING_SOURCES,
    CALLBACK_COMPLETED,
    CALLBACK_IN_PROGRESS,
    NEXT_STEPS,
    FOLLOWUP_OPEN_STATES,
    FOLLOWUP_STATES,
    RECOMMENDATION_STATES,
    STATUS_CANCELLED,
    STATUS_CONFIRMED,
)
from ..services import (
    appointments,
    availability,
    callbacks,
    calls,
    checkin,
    clinic,
    consultations,
    followups,
    notifications,
    patients,
    timeline,
    waitlist,
)
from ..services.errors import ClinicError, DuplicatePatientError

router = APIRouter(include_in_schema=False)

templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")
templates.env.filters["fmt_time"] = utils.fmt_time
templates.env.filters["fmt_date"] = utils.fmt_date

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def asset(path: str) -> str:
    """Static URL that changes whenever the file does, so browsers never run a stale script or stylesheet."""
    try:
        version = int((STATIC_DIR / path).stat().st_mtime)
    except OSError:
        version = 0
    return f"/static/{path}?v={version}"


templates.env.globals["asset"] = asset
templates.env.globals["can_generate_qr"] = lambda appointment: checkin.can_generate(appointment)
templates.env.globals["next_step_label"] = lambda code: NEXT_STEPS.get(code, code)
templates.env.globals["recommendation_state"] = lambda code: FOLLOWUP_STATES.get(code, code)

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

NOTICES = {
    "confirmed": ("success", "Booking confirmed."),
    "cancelled": ("success", "Booking cancelled. The slot is available again."),
    "saved": ("success", "Changes saved."),
    "patient_created": ("success", "Patient registered."),
    "callback_in_progress": ("success", "Callback task marked in progress."),
    "callback_completed": ("success", "Callback task completed."),
    "arrived": ("success", "Patient marked as arrived."),
    "completed": ("success", "Consultation marked as completed."),
    "doctor_confirmed": ("success", "Appointment confirmed. Reception, the calendar and the patient timeline now show it as confirmed."),
    "already_confirmed": ("success", "This appointment was already confirmed. Nothing was changed or sent again."),
    "arrived_by_doctor": ("success", "Patient marked arrived. You can now start the consultation, save an outcome or send a follow-up to reception."),
    "consultation_started": ("success", "Consultation started. Write the outcome below; it can be saved now or after completing."),
    "no_show": ("success", "Booking marked as no-show."),
    "outcome_saved": ("success", "Consultation outcome saved. The summary, next step and note below are what is stored."),
    "recommendation_saved": ("success", "Draft treatment recommendation saved."),
    "recommendation_ready": ("success", "Marked ready. Reception can now schedule a follow-up."),
    "followup_sent": ("success", "Follow-up sent to reception. It is now on their Follow-ups list to be booked."),
    "care_flags": ("success", "Patient flags saved. Reception sees the flag names and what they mean, nothing else."),
    "care_flags_unchanged": ("success", "No flag changes to save."),
    "care_note": ("success", "Private doctor notes saved. Only you can see them, here in the doctor workspace."),
    "care_callback": ("success", "Callback request sent to reception with the reason you chose."),
    "care_followup": ("success", "Follow-up sent to reception. It is ready for scheduling."),
    "care_followup_closed": ("success", "Follow-up request closed. It is no longer on reception’s list."),
    "notification_sent": ("success", "Marked as sent (simulated). No message left this app."),
    "notification_delivered": ("success", "Marked as delivered (simulated)."),
    "notification_failed": ("success", "Marked as failed (simulated). It can be retried."),
    "notification_retried": ("success", "Queued again for another attempt (simulated)."),
    "waitlist_added": ("success", "Patient added to the waitlist."),
    "waitlist_offered": ("success", "Marked as offered. The slot is not reserved until it is booked."),
    "waitlist_updated": ("success", "Waitlist entry updated."),
    "block_saved": ("success", "Time blocked. It will not be offered for booking."),
    "block_removed": ("success", "Blocked time removed. Those slots can be booked again."),
}


def render(request: Request, db: Session, template: str, **context):
    context.setdefault("notice", NOTICES.get(request.query_params.get("notice", "")))
    today = utils.now().date()
    closed_days = {d for d in availability.window_days(today) if availability.is_closed(d)}
    context.update(clinic=clinic.get_clinic(db), today=today, closed_days=closed_days)
    return templates.TemplateResponse(request, template, context)


def redirect(path: str, fragment: str = "", **params) -> RedirectResponse:
    """303 to `path`. `fragment` keeps the reader at the part of the page they were working in."""
    query = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    target = f"{path}?{query}" if query else path
    return RedirectResponse(f"{target}#{fragment}" if fragment else target, status_code=303)


def parse_day(value: str | None, default: date) -> date:
    try:
        return date.fromisoformat(value or "")
    except ValueError:
        return default


@router.get("/")
def dashboard(request: Request, booked: int | None = None, db: Session = Depends(get_db)):
    context = {}
    if booked is not None:
        try:
            context["booked"] = appointments.get_appointment(db, booked)
        except ClinicError:
            pass
    return render(request, db, "dashboard.html", **dashboard_context(db), **context)


def dashboard_context(db: Session) -> dict:
    now = utils.now()
    notifications.queue_due_reminders(db, now)  # no scheduler in the demo: reminders are queued when staff look
    tasks = callbacks.list_active(db) + callbacks.list_recently_completed(db)
    known = {t.mobile: patients.find_by_mobile(db, t.mobile) for t in tasks}
    return {
        "active": "dashboard",
        # Callback tasks belong to a mobile number; link to the patient's timeline when one is registered.
        "callback_patients": {t.id: known[t.mobile].id for t in tasks if known[t.mobile]},
        "summary": appointments.dashboard_summary(db, now),
        "todays": appointments.list_today(db, now),
        "upcoming": appointments.list_upcoming(db, now),
        "callback_counts": callbacks.counts(db),
        "callback_tasks": tasks,
        "call_logs": calls.list_recent(db),
        "recent_activity": timeline.recent_activity(db),
        "notification_counts": notifications.counts(db),
        "followups_awaiting": followups.awaiting_count(db),
        "consultation_followups_awaiting": followups.consultation_awaiting_count(db),
        "waitlist_counts": waitlist.counts(db, now),
        "opportunities": waitlist.newly_available(db, now),
    }


@router.post("/callbacks/{task_id}/status")
def change_callback_status(
    request: Request,
    task_id: int,
    status: str = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        callbacks.set_status(db, task_id, status, notes)
    except ClinicError as exc:
        return dashboard_with_error(request, db, exc.message)
    notice = {CALLBACK_IN_PROGRESS: "callback_in_progress", CALLBACK_COMPLETED: "callback_completed"}.get(status, "saved")
    return redirect("/", notice=notice)


@router.post("/appointments/{appointment_id}/status")
def change_status(
    request: Request, appointment_id: int, status: str = Form(...), db: Session = Depends(get_db)
):
    try:
        appointments.set_status(db, appointment_id, status)
    except ClinicError as exc:
        return dashboard_with_error(request, db, exc.message)
    notice = {STATUS_CONFIRMED: "confirmed", STATUS_CANCELLED: "cancelled"}.get(status, "saved")
    return redirect("/", notice=notice)


def dashboard_with_error(request: Request, db: Session, message: str):
    return render(request, db, "dashboard.html", notice=("error", message), **dashboard_context(db))


@router.get("/patients")
def patients_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    results = patients.search_patients(db, q)
    return render(
        request,
        db,
        "patients.html",
        active="patients",
        q=q,
        results=results,
        form={},
        recommendations=consultations.recommendations_by_patient(db, [p.id for p in results]),
    )


@router.post("/patients")
def patients_create(
    request: Request,
    name: str = Form(""),
    mobile: str = Form(""),
    email: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    form = {"name": name, "mobile": mobile, "email": email, "notes": notes}
    try:
        patient = patients.create_patient(db, **form)
    except ClinicError as exc:
        return render(
            request,
            db,
            "patients.html",
            active="patients",
            q="",
            results=patients.search_patients(db),
            recommendations={},
            form=form,
            form_error=exc.message,
            duplicate=exc.patient if isinstance(exc, DuplicatePatientError) else None,
        )
    return redirect("/patients", q=patient.mobile, notice="patient_created")


@router.get("/patients/{patient_id}")
@router.get("/patients/{patient_id}/timeline")
def patient_timeline(request: Request, patient_id: int, db: Session = Depends(get_db)):
    """Patient detail page with its read-only Timeline section. Both addresses show the same
    page; doctor summaries and notes are never included."""
    try:
        patient = patients.get_patient(db, patient_id)
    except ClinicError as exc:
        response = render(request, db, "patient_timeline.html", active="patients", patient=None, events=[], notice=("error", exc.message))
        response.status_code = exc.status_code
        return response
    events = timeline.build(db, patient)
    sent = followups.sent_for_patient(db, patient.id)
    now = utils.now()
    upcoming = [
        a for a in appointments.list_today(db, now) + appointments.list_upcoming(db, now)
        if a.patient_id == patient.id and a.is_active and a.start_time >= now
    ]
    return render(
        request,
        db,
        "patient_timeline.html",
        active="patients",
        patient=patient,
        events=events,
        has_activity=timeline.has_activity(events),
        next_appointment=min(upcoming, key=lambda a: a.start_time, default=None),
        qr_bookings=sorted((a for a in upcoming if checkin.can_generate(a, now)), key=lambda a: a.start_time),
        open_callbacks=[t for t in callbacks.list_active(db) if t.mobile == patient.mobile],
        recommendations=consultations.recommendations_by_patient(db, [patient.id]).get(patient.id, []),
        followup_requests=sent,
        followup_doctor_ids={r.doctor_id for r in sent},
        followup_states=followups.PATIENT_PAGE_STATES,
        followup_open=FOLLOWUP_OPEN_STATES,
    )


@router.get("/availability")
def availability_page(
    request: Request, doctor_id: int | None = None, date: str | None = None, db: Session = Depends(get_db)
):
    doctors = availability.list_doctors(db)
    days = availability.window_days()
    day = parse_day(date, days[0])
    if day not in days:
        day = days[0]
    doctor = next((d for d in doctors if d.id == doctor_id), doctors[0])
    return render(
        request,
        db,
        "availability.html",
        active="availability",
        doctors=doctors,
        days=days,
        doctor=doctor,
        day=day,
        slots=availability.slots_for_day(db, doctor.id, day),
        weekdays=WEEKDAYS,
        clinic_closed=availability.is_closed(day),
        closed_message=clinic.closed_day_message(db, day),
        next_open=next((d for d in days if d > day and not availability.is_closed(d)), None),
    )


@router.get("/bookings/new")
def booking_new(
    request: Request,
    patient_id: int | None = None,
    doctor_id: int | None = None,
    date: str | None = None,
    slot_id: int | None = None,
    db: Session = Depends(get_db),
):
    doctors = availability.list_doctors(db)
    days = availability.window_days()
    day = parse_day(date, days[0])
    if day not in days:
        day = days[0]
    if availability.is_closed(day):
        # Bookings cannot be started on a closed day: fall back to the first open day.
        day = next((d for d in days if not availability.is_closed(d)), day)
    patient = None
    if patient_id is not None:
        try:
            patient = schemas.patient_out(patients.get_patient(db, patient_id))
        except ClinicError:
            pass
    init = {
        "patient": patient,
        "doctorId": doctor_id if any(d.id == doctor_id for d in doctors) else doctors[0].id,
        "date": day.isoformat(),
        "slotId": slot_id,
    }
    return render(
        request,
        db,
        "booking_new.html",
        active="booking",
        doctors=doctors,
        days=days,
        services=appointments.list_services(db),
        sources=BOOKING_SOURCES,
        init=init,
    )


def settings_page(request: Request, db: Session, **context):
    clinic_row = clinic.get_clinic(db)
    return render(
        request,
        db,
        "settings.html",
        active="settings",
        doctors=availability.list_doctors(db),
        services=appointments.list_services(db),
        weekdays=WEEKDAYS,
        # Read-only facts for the "Clinic schedule" section; they come from app/config.py.
        clinic_hours=knowledge.CLINIC_HOURS,
        closed_weekdays=config.CLINIC_CLOSED_WEEKDAYS,
        closed_weekday_names=[WEEKDAY_NAMES[d] for d in config.CLINIC_CLOSED_WEEKDAYS],
        slot_window_days=config.SLOT_WINDOW_DAYS,
        checkin_closes_after=config.CHECKIN_CLOSES_MINUTES_AFTER,
        # Profile fields still holding the seeded sample value: shown as awaiting the owner's details.
        placeholder_fields={k for k, v in config.SEED_CLINIC.items() if k in ("address", "phone", "email") and getattr(clinic_row, k, None) == v},
        **context,
    )


@router.get("/settings")
def settings(request: Request, db: Session = Depends(get_db)):
    return settings_page(request, db)


@router.post("/settings/clinic")
def settings_clinic(
    request: Request,
    name: str = Form(""),
    address: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    currency_symbol: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        clinic.update_clinic(
            db, name=name, address=address, phone=phone, email=email, currency_symbol=currency_symbol
        )
    except ClinicError as exc:
        return settings_page(request, db, notice=("error", exc.message))
    return redirect("/settings", notice="saved")


@router.post("/settings/doctors/{doctor_id}")
def settings_doctor(
    request: Request,
    doctor_id: int,
    name: str = Form(""),
    speciality: str = Form(""),
    work_start: str = Form(""),
    work_end: str = Form(""),
    consultation_minutes: int = Form(0),
    working_days: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
):
    try:
        try:
            start, end = time.fromisoformat(work_start), time.fromisoformat(work_end)
        except ValueError:
            raise ClinicError("Please enter valid working hours.") from None
        clinic.update_doctor(
            db,
            doctor_id,
            name=name,
            speciality=speciality,
            work_start=start,
            work_end=end,
            consultation_minutes=consultation_minutes,
            working_days=working_days,
        )
    except ClinicError as exc:
        return settings_page(request, db, notice=("error", exc.message))
    return redirect("/settings", notice="saved")


@router.post("/settings/services/{service_id}")
def settings_service(
    request: Request,
    service_id: int,
    name: str = Form(""),
    fee: int = Form(0),
    db: Session = Depends(get_db),
):
    try:
        clinic.update_service(db, service_id, name=name, fee=fee)
    except ClinicError as exc:
        return settings_page(request, db, notice=("error", exc.message))
    return redirect("/settings", notice="saved")
