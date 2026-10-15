"""Request bodies and JSON shapes for the booking API."""
from pydantic import BaseModel, Field

from . import utils
from .models import (
    NEXT_STEPS,
    Appointment,
    CallbackTask,
    CallLog,
    ConsultationOutcome,
    Doctor,
    Patient,
    Service,
    TreatmentRecommendation,
)
from .services.availability import SlotView


class PatientCreate(BaseModel):
    name: str
    mobile: str
    email: str | None = None
    notes: str | None = None


class AppointmentCreate(BaseModel):
    patient_id: int
    slot_id: int
    service_id: int
    reason: str | None = None
    source: str = "STAFF"


class StatusUpdate(BaseModel):
    status: str


class CallbackCreate(BaseModel):
    name: str
    mobile: str
    reason: str
    email: str | None = None
    source: str = "STAFF"
    notes: str | None = None


class CallbackStatusUpdate(BaseModel):
    status: str
    notes: str | None = None


class SpeechRequest(BaseModel):
    text: str = Field(default="", max_length=2000)


class AssistantMessage(BaseModel):
    text: str = Field(default="", max_length=1000)
    action: str | None = Field(default=None, max_length=40)
    value: str | int | None = None
    state: dict | None = None


def patient_out(p: Patient) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "mobile": p.mobile,
        "email": p.email,
        "notes": p.notes,
        "is_demo": p.is_demo,
        "created_at": p.created_at.isoformat(),
    }


def doctor_out(d: Doctor) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "speciality": d.speciality,
        "work_start": d.work_start.strftime("%H:%M"),
        "work_end": d.work_end.strftime("%H:%M"),
        "consultation_minutes": d.consultation_minutes,
        "working_days": sorted(d.working_day_set),
        "is_demo": d.is_demo,
    }


def service_out(s: Service) -> dict:
    return {"id": s.id, "name": s.name, "fee": s.fee, "is_demo": s.is_demo}


def slot_out(view: SlotView) -> dict:
    slot = view.slot
    return {
        "id": slot.id,
        "doctor_id": slot.doctor_id,
        "start_time": slot.start_time.isoformat(),
        "end_time": slot.end_time.isoformat(),
        "start_label": utils.fmt_time(slot.start_time),
        "duration_minutes": slot.duration_minutes,
        "status": view.status,
        "available": view.available,
    }


def appointment_out(a: Appointment) -> dict:
    return {
        "id": a.id,
        "patient": patient_out(a.patient),
        "doctor": {"id": a.doctor.id, "name": a.doctor.name, "speciality": a.doctor.speciality},
        "service": service_out(a.service),
        "reason": a.reason,
        "start_time": a.start_time.isoformat(),
        "end_time": a.end_time.isoformat(),
        "status": a.status,
        "source": a.source,
        "is_demo": a.is_demo,
        "created_at": a.created_at.isoformat(),
    }


def callback_out(t: CallbackTask) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "mobile": t.mobile,
        "email": t.email,
        "reason": t.reason,
        "source": t.source,
        "status": t.status,
        "notes": t.notes,
        "created_at": t.created_at.isoformat(),
    }


def call_out(c: CallLog) -> dict:
    return {
        "id": c.id,
        "channel": c.channel,
        "caller_name": c.caller_name,
        "caller_mobile": c.caller_mobile,
        "started_at": c.started_at.isoformat(),
        "completed_at": c.completed_at.isoformat() if c.completed_at else None,
        "outcome": c.outcome,
        "appointment_id": c.appointment_id,
        "callback_task_id": c.callback_task_id,
        "is_demo": True,
    }


def block_out(b) -> dict:
    return {
        "id": b.id,
        "doctor_id": b.doctor_id,
        "start_time": b.start_time.isoformat(),
        "end_time": b.end_time.isoformat(),
        "all_day": b.all_day,
        "reason": b.reason,
    }


def schedule_day_out(day: dict) -> dict:
    entries = []
    for e in day["entries"]:
        item = {"kind": e["kind"], "start_time": e["start"].isoformat(), "end_time": e["end"].isoformat()}
        if e["kind"] == "appointment":
            a = e["appointment"]
            item.update(appointment_id=a.id, status=a.status, patient=a.patient.name, service=a.service.name, source=a.source)
        elif e["kind"] == "slot":
            item.update(slot_id=e["slot"].id)
        else:
            item.update(block_id=e["block"].id, reason=e["block"].reason, all_day=e["block"].all_day)
        entries.append(item)
    return {
        "date": day["date"].isoformat(),
        "closed": day["closed"],
        "working": day["working"],
        "bookable": day["bookable"],
        "available": day["available"],
        "booked": day["booked"],
        "entries": entries,
    }


def outcome_out(o: ConsultationOutcome) -> dict:
    return {
        "appointment_id": o.appointment_id,
        "doctor_id": o.doctor_id,
        "summary": o.summary,
        "next_step": o.next_step,
        "next_step_label": NEXT_STEPS.get(o.next_step, o.next_step),
        "follow_up_note": o.follow_up_note,
        "entered_by": "doctor",
        "updated_at": o.updated_at.isoformat(),
    }


def recommendation_out(r: TreatmentRecommendation) -> dict:
    return {
        "id": r.id,
        "appointment_id": r.appointment_id,
        "doctor": {"id": r.doctor.id, "name": r.doctor.name},
        "patient_id": r.patient_id,
        "procedure": r.procedure,
        "doctor_note": r.doctor_note,
        "status": r.status,
        "followup_appointment_id": r.followup.appointment_id if r.followup else None,
        "entered_by": "doctor",
        "created_at": r.created_at.isoformat(),
    }
