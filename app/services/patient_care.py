"""Doctor patient controls: the patient overview inside a consultation, doctor-managed flags,
private doctor notes and operational care actions (callback and follow-up requests).

Every action goes through one of the doctor's own appointments, so a doctor can act only on
patients they are seeing. Nothing here edits patient identity or contact details, deletes a
record, or books a slot: callbacks and follow-ups are requests that reception handles.

Private notes are read only by `overview()` for the same doctor. No reception page, timeline,
API, notification, call screen or assistant imports DoctorPatientNote.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import utils
from ..models import (
    CALLBACK_COMPLETED,
    CLOSE_REASONS,
    DOCTOR_CALLBACK_REASONS,
    FOLLOWUP_OPEN_STATES,
    RECOMMENDATION_DRAFT,
    FOLLOWUP_CLOSED,
    PATIENT_FLAGS,
    RECOMMENDATION_READY,
    SOURCE_DOCTOR,
    STATUS_ARRIVED,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_CONFIRMED,
    STATUS_NO_SHOW,
    STATUS_PENDING,
    Appointment,
    CallbackTask,
    ConsultationFollowup,
    DoctorPatientNote,
    PatientFlag,
    TimelineEvent,
    WaitlistEntry,
)
from . import callbacks, consultations
from .errors import NotFoundError, NotPermittedError, ValidationError

NOTE_LIMIT = 2000
REQUEST_STATES = {
    RECOMMENDATION_DRAFT: "Draft", RECOMMENDATION_READY: "Waiting", "CONTACT_PATIENT": "Waiting · contacting patient",
    "AWAITING_RESPONSE": "Waiting · awaiting patient", "SCHEDULED": "Scheduled", "COMPLETED": "Completed", FOLLOWUP_CLOSED: "Closed",
}


def overview(db: Session, doctor_id: int, appointment: Appointment) -> dict:
    """Everything the patient overview shows, scoped to this doctor. `appointment` must already be
    one of this doctor's (see consultations.appointment_for_doctor)."""
    patient = appointment.patient
    with_doctor = list(db.scalars(
        select(Appointment)
        .options(joinedload(Appointment.service))
        .where(Appointment.patient_id == patient.id, Appointment.doctor_id == doctor_id)
        .order_by(Appointment.start_time.desc())
    ))
    now = utils.now()
    upcoming = sorted(
        (a for a in with_doctor
         if a.start_time > now and a.id != appointment.id and a.status in (STATUS_PENDING, STATUS_CONFIRMED)),
        key=lambda a: a.start_time,
    )
    flags = {f.kind: f for f in db.scalars(select(PatientFlag).where(
        PatientFlag.patient_id == patient.id, PatientFlag.doctor_id == doctor_id
    ))}
    note = db.scalar(select(DoctorPatientNote).where(
        DoctorPatientNote.patient_id == patient.id, DoctorPatientNote.doctor_id == doctor_id
    ))
    requests = list(db.scalars(
        select(ConsultationFollowup)
        .where(ConsultationFollowup.patient_id == patient.id, ConsultationFollowup.doctor_id == doctor_id)
        .order_by(ConsultationFollowup.created_at.desc())
    ))
    open_callbacks = [
        t for t in db.scalars(select(CallbackTask).where(
            CallbackTask.mobile == patient.mobile, CallbackTask.status != CALLBACK_COMPLETED
        ))
    ]
    from_waitlist = db.scalar(select(WaitlistEntry.id).where(WaitlistEntry.appointment_id == appointment.id)) is not None
    return {
        "patient": patient,
        "history": with_doctor[:6],
        "history_total": len(with_doctor),
        "upcoming": upcoming[0] if upcoming else None,
        "completed": sum(a.status == STATUS_COMPLETED for a in with_doctor),
        "cancelled": sum(a.status == STATUS_CANCELLED for a in with_doctor),
        "no_shows": sum(a.status == STATUS_NO_SHOW for a in with_doctor),
        "from_waitlist": from_waitlist,
        "flags": {kind: (flags[kind].active if kind in flags else False) for kind in PATIENT_FLAGS},
        "note": note,
        "requests": requests,
        "request_states": REQUEST_STATES,
        "open_callbacks": len(open_callbacks),
        "can_request_followup": appointment.status in (STATUS_ARRIVED, STATUS_COMPLETED)
        and (appointment.followup_request is None or appointment.followup_request.status == FOLLOWUP_CLOSED),
    }


def set_flags(db: Session, doctor_id: int, appointment_id: int, kinds: list[str]) -> list[str]:
    """Set exactly these flags for this doctor and patient; the others are cleared. Every change is
    logged on the patient timeline with the flag name only. Returns the changes made."""
    appointment = consultations.appointment_for_doctor(db, doctor_id, appointment_id)
    wanted = set(kinds)
    if wanted - set(PATIENT_FLAGS):
        raise ValidationError("Please choose flags from the list.")
    existing = {f.kind: f for f in db.scalars(select(PatientFlag).where(
        PatientFlag.patient_id == appointment.patient_id, PatientFlag.doctor_id == doctor_id
    ))}
    now = utils.now()
    changes = []
    for kind, (label, _meaning) in PATIENT_FLAGS.items():
        flag = existing.get(kind)
        active_now = bool(flag and flag.active)
        if (kind in wanted) == active_now:
            continue
        if flag is None:
            flag = PatientFlag(patient_id=appointment.patient_id, doctor_id=doctor_id, kind=kind)
            db.add(flag)
        flag.active = kind in wanted
        flag.updated_at = now
        event = "PATIENT_FLAG_SET" if flag.active else "PATIENT_FLAG_CLEARED"
        db.add(TimelineEvent(
            kind=event, source=SOURCE_DOCTOR, occurred_at=now, patient_id=appointment.patient_id,
            detail=f"{label} · {appointment.doctor.name}",
        ))
        changes.append(f"{'Set' if flag.active else 'Cleared'}: {label}")
    db.commit()
    return changes


def save_note(db: Session, doctor_id: int, appointment_id: int, body: str) -> DoctorPatientNote:
    """Create or update this doctor's private note about the patient. Never shared."""
    appointment = consultations.appointment_for_doctor(db, doctor_id, appointment_id)
    text = "\n".join(line.rstrip() for line in (body or "").strip().splitlines())
    if len(text) > NOTE_LIMIT:
        raise ValidationError(f"Doctor notes can be up to {NOTE_LIMIT} characters.")
    note = db.scalar(select(DoctorPatientNote).where(
        DoctorPatientNote.patient_id == appointment.patient_id, DoctorPatientNote.doctor_id == doctor_id
    ))
    if note is None:
        note = DoctorPatientNote(patient_id=appointment.patient_id, doctor_id=doctor_id)
        db.add(note)
    note.body = text or None
    note.updated_at = utils.now()
    db.commit()
    return note


def request_callback(db: Session, doctor_id: int, appointment_id: int, reason_code: str) -> CallbackTask:
    """A callback task for reception with one of the fixed operational reasons. There is no free-text
    field, so nothing clinical can reach the reception-visible reason."""
    appointment = consultations.appointment_for_doctor(db, doctor_id, appointment_id)
    if reason_code not in DOCTOR_CALLBACK_REASONS:
        raise ValidationError("Please choose a reason from the list.")
    patient = appointment.patient
    reason = f"{DOCTOR_CALLBACK_REASONS[reason_code]} (requested by {appointment.doctor.name})"
    task = callbacks.create_callback(
        db, name=patient.name, mobile=patient.mobile, email=patient.email, reason=reason, source="STAFF", acknowledge=False
    )
    db.add(TimelineEvent(
        kind="DOCTOR_CALLBACK_REQUESTED", source=SOURCE_DOCTOR, occurred_at=utils.now(), patient_id=patient.id,
        callback_task_id=task.id, detail=DOCTOR_CALLBACK_REASONS[reason_code],
    ))
    db.commit()
    return task


def request_followup(
    db: Session, doctor_id: int, appointment_id: int, *, duration=None, timeframe=None, by_date=None,
    priority=None, followup_type=None, draft=False,
):
    """Follow-up request straight from the patient overview: no procedure and no particular next step
    needed, only a patient the doctor has seen. Reception books it through the normal flow."""
    appointment = consultations.appointment_for_doctor(db, doctor_id, appointment_id)
    if appointment.status not in (STATUS_ARRIVED, STATUS_COMPLETED):
        raise ValidationError("A follow-up can be requested once the patient has arrived.")
    preference = consultations.followup_preference(duration, timeframe, by_date)
    return consultations.create_followup_request(
        db, appointment, doctor_id, preference, "Consultation follow-up · requested by the doctor for scheduling",
        draft=draft, followup_type=followup_type, priority=priority,
    )


def close_followup(db: Session, doctor_id: int, request_id: int, reason: str | None = None) -> ConsultationFollowup:
    """The requesting doctor marks a follow-up as no longer required, with an operational reason from a
    fixed list. A booked one is left alone: the appointment is reception's to cancel."""
    request = db.get(ConsultationFollowup, request_id)
    if request is None:
        raise NotFoundError("We could not find that follow-up request.")
    if request.doctor_id != doctor_id:
        raise NotPermittedError("Only the doctor who asked for this follow-up can close it.")
    if request.followup_appointment_id is not None:
        raise ValidationError("Reception has already booked this follow-up. Ask reception to cancel the appointment if it is not needed.")
    if request.status not in (RECOMMENDATION_DRAFT, *FOLLOWUP_OPEN_STATES):
        raise ValidationError("This follow-up request is already closed.")
    if reason not in CLOSE_REASONS:
        raise ValidationError("Please choose why the follow-up is no longer required.")
    request.status = FOLLOWUP_CLOSED
    request.close_reason = reason
    db.add(TimelineEvent(
        kind="FOLLOWUP_CLOSED", source=SOURCE_DOCTOR, occurred_at=utils.now(), patient_id=request.patient_id,
        appointment_id=request.appointment_id, detail=f"{request.type_label} · not required: {CLOSE_REASONS[reason]}",
    ))
    db.commit()
    return request
