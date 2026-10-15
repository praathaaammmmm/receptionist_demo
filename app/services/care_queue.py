"""Reception's follow-up work queue: one list for consultation follow-ups (and reviews), procedure
discussions (doctor recommendations) and procedure plans, with planning fields, due dates and the
contact steps reception owns.

Who does what:
- the doctor creates a request, recommendation or plan and explicitly hands it to reception;
- reception contacts the patient, records the response and books through the normal booking engine;
- the booked appointment then drives the item: completed → Completed; cancelled or missed → back to
  "Awaiting patient response" (procedure plans: "Discussing with patient"), never silently closed.

Staff-safe by construction: nothing here reads a consultation summary, follow-up note, recommendation
note or a plan's private note. Messages are simulated outbox entries only.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .. import utils
from ..models import (
    FOLLOWUP_AWAITING,
    FOLLOWUP_COMPLETED,
    FOLLOWUP_CONTACT,
    FOLLOWUP_STATES,
    FOLLOWUP_TYPES,
    NEXT_STEPS,
    PLAN_ACCEPTED,
    PLAN_COMPLETED,
    PLAN_DISCUSSING,
    PLAN_DRAFT,
    PLAN_READY,
    PRIORITIES,
    RECOMMENDATION_DRAFT,
    RECOMMENDATION_READY,
    SOURCE_STAFF,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_NO_SHOW,
    Appointment,
    ConsultationFollowup,
    Doctor,
    ProcedurePlan,
    TimelineEvent,
    TreatmentRecommendation,
)
from . import notifications
from .errors import NotFoundError, ValidationError

KINDS = ("consultation", "procedure", "plan")
# One status vocabulary for filtering across all three kinds.
STAGES = {
    "READY": "Ready for reception",
    FOLLOWUP_CONTACT: "Contact patient",
    FOLLOWUP_AWAITING: "Awaiting patient response",
    PLAN_DISCUSSING: "Discussing with patient",
    PLAN_ACCEPTED: "Accepted",
    "DEFERRED": "Deferred",
    "SCHEDULED": "Scheduled",
    "COMPLETED": "Completed",
    "CLOSED": "Closed / not required",
}
OPEN_STAGES = ("READY", FOLLOWUP_CONTACT, FOLLOWUP_AWAITING, PLAN_DISCUSSING, PLAN_ACCEPTED, "DEFERRED")
STATUS_FILTERS = {"open": "Needs reception action", **STAGES, "all": "Everything"}
SORTS = {"due": "Due date", "priority": "Priority", "newest": "Newest first"}
_PRIORITY_RANK = {"PRIORITY": 0, "SOON": 1, "ROUTINE": 2}


def _stage(kind: str, status: str) -> str:
    if status in (RECOMMENDATION_READY, PLAN_READY):
        return "READY"
    if status in ("CLOSED", "DECLINED", "CANCELLED"):
        return "CLOSED"
    return status


@dataclass
class QueueItem:
    """One row of reception's work queue. Operational fields only."""

    kind: str
    id: int
    type_code: str
    procedure: str | None
    patient: object
    doctor: Doctor  # the doctor the appointment is with (a plan's preferred doctor)
    requested_by: Doctor
    origin: Appointment
    status: str
    status_label: str
    priority: str
    by_date: date | None
    timeframe_label: str | None
    duration_minutes: int | None
    next_step: str | None
    reception_note: str | None
    booked: Appointment | None
    created_at: datetime
    resources: list[str] = field(default_factory=list)
    overdue: bool = False

    @property
    def key(self) -> str:
        return f"{self.kind}-{self.id}"

    @property
    def type_label(self) -> str:
        return FOLLOWUP_TYPES[self.type_code]

    @property
    def stage(self) -> str:
        return _stage(self.kind, self.status)

    @property
    def priority_label(self) -> str:
        return PRIORITIES[self.priority]

    @property
    def actions(self) -> list[tuple[str, str]]:
        """What reception can do next, as (action, button label)."""
        if self.kind == "plan":
            return {
                PLAN_READY: [(PLAN_DISCUSSING, "Discussing with patient"), (PLAN_ACCEPTED, "Patient accepted"), ("DECLINED", "Patient declined"), ("DEFERRED", "Defer")],
                PLAN_DISCUSSING: [(PLAN_ACCEPTED, "Patient accepted"), ("DECLINED", "Patient declined"), ("DEFERRED", "Defer")],
                PLAN_ACCEPTED: [("schedule", "Schedule procedure"), ("DEFERRED", "Defer"), ("DECLINED", "Patient declined")],
                "DEFERRED": [(PLAN_DISCUSSING, "Resume discussion")],
            }.get(self.status, [])
        return {
            RECOMMENDATION_READY: [("contact", "Contact patient"), ("schedule", "Schedule follow-up")],
            FOLLOWUP_CONTACT: [("awaiting", "Awaiting patient response"), ("schedule", "Schedule follow-up")],
            FOLLOWUP_AWAITING: [("contact", "Contact again"), ("schedule", "Schedule follow-up")],
        }.get(self.status, [])

    @property
    def workspace_href(self) -> str:
        return f"/doctor?doctor_id={self.requested_by.id}&appointment_id={self.origin.id}#consultation"


def _next_step(origin: Appointment) -> str | None:
    """The doctor's saved next step (the same marker reception already sees on the dashboard)."""
    return NEXT_STEPS.get(origin.outcome.next_step) if origin.outcome else None


def _from_followup(r: ConsultationFollowup, today: date) -> QueueItem:
    return QueueItem(
        "consultation", r.id, r.type_code, None, r.patient, r.doctor, r.doctor, r.appointment, r.status,
        FOLLOWUP_STATES.get(r.status, r.status), r.priority_code, r.by_date, r.timeframe_label, r.duration_minutes,
        _next_step(r.appointment), r.staff_note, r.followup_appointment, r.created_at, overdue=r.is_overdue(today),
    )


def _from_recommendation(r: TreatmentRecommendation, today: date) -> QueueItem:
    booked = r.followup.appointment if r.followup else None
    return QueueItem(
        "procedure", r.id, "PROCEDURE_DISCUSSION", r.procedure, r.patient, r.doctor, r.doctor, r.appointment, r.status,
        FOLLOWUP_STATES.get(r.status, r.status), r.priority_code, r.by_date, r.timeframe_label, None,
        _next_step(r.appointment), r.followup.staff_note if r.followup else None, booked, r.created_at,
        overdue=r.is_overdue(today),
    )


def _from_plan(p: ProcedurePlan, today: date) -> QueueItem:
    return QueueItem(
        "plan", p.id, "PROCEDURE_APPOINTMENT", p.service.name, p.patient, p.preferred_doctor, p.doctor, p.appointment,
        p.status, p.state_label, p.priority_code, p.by_date, p.timeframe_label, p.duration_minutes,
        _next_step(p.appointment), p.reception_instruction, p.scheduled_appointment, p.created_at,
        resources=p.resource_labels, overdue=p.is_overdue(today),
    )


def all_items(db: Session) -> list[QueueItem]:
    """Everything a doctor has handed to reception (drafts stay with the doctor)."""
    today = utils.now().date()
    followups = db.scalars(
        select(ConsultationFollowup)
        .options(joinedload(ConsultationFollowup.patient), joinedload(ConsultationFollowup.doctor))
        .where(ConsultationFollowup.status != RECOMMENDATION_DRAFT)
    ).all()
    recommendations = db.scalars(
        select(TreatmentRecommendation)
        .options(joinedload(TreatmentRecommendation.patient), joinedload(TreatmentRecommendation.doctor))
        .where(TreatmentRecommendation.status != RECOMMENDATION_DRAFT)
    ).all()
    plans = db.scalars(select(ProcedurePlan).where(ProcedurePlan.status != PLAN_DRAFT)).all()
    return (
        [_from_followup(r, today) for r in followups]
        + [_from_recommendation(r, today) for r in recommendations]
        + [_from_plan(p, today) for p in plans]
    )


def queue(
    db: Session, *, status: str = "open", doctor_id: int | None = None, type_code: str = "", priority: str = "",
    overdue: bool = False, sort: str = "due",
) -> list[QueueItem]:
    items = all_items(db)
    if status == "open":
        items = [i for i in items if i.stage in OPEN_STAGES]
    elif status in STAGES:
        items = [i for i in items if i.stage == status]
    if doctor_id:
        items = [i for i in items if doctor_id in (i.doctor.id, i.requested_by.id)]
    if type_code in FOLLOWUP_TYPES:
        items = [i for i in items if i.type_code == type_code]
    if priority in PRIORITIES:
        items = [i for i in items if i.priority == priority]
    if overdue:
        items = [i for i in items if i.overdue]
    if sort == "priority":
        items.sort(key=lambda i: (_PRIORITY_RANK[i.priority], i.by_date or date.max, i.created_at))
    elif sort == "newest":
        items.sort(key=lambda i: i.created_at, reverse=True)
    else:  # due date first (overdue at the top), then priority, then oldest
        items.sort(key=lambda i: (i.by_date or date.max, _PRIORITY_RANK[i.priority], i.created_at))
    return items


def summary(db: Session) -> dict:
    """Dashboard counts. "This week" is today and the next six days."""
    items = all_items(db)
    today = utils.now().date()
    week_end = today + timedelta(days=7)

    def booked_this_week(i: QueueItem) -> bool:
        return i.stage == "SCHEDULED" and i.booked is not None and today <= i.booked.start_time.date() < week_end

    followups = [i for i in items if i.kind != "plan"]
    plans = [i for i in items if i.kind == "plan"]
    by_doctor: dict[str, dict] = {}
    for i in items:
        if i.stage in OPEN_STAGES:
            row = by_doctor.setdefault(i.doctor.name, {"followups": 0, "procedures": 0})
            row["procedures" if i.kind == "plan" else "followups"] += 1
    return {
        "ready_to_schedule": sum(i.stage == "READY" for i in followups),
        "contact_patient": sum(i.stage == FOLLOWUP_CONTACT for i in followups),
        "awaiting_response": sum(i.stage == FOLLOWUP_AWAITING for i in followups),
        "overdue": sum(i.overdue for i in items),
        "scheduled_this_week": sum(booked_this_week(i) for i in followups),
        "plans_awaiting_reception": sum(i.status in (PLAN_READY, PLAN_DISCUSSING, PLAN_ACCEPTED) for i in plans),
        "procedures_this_week": sum(booked_this_week(i) for i in plans),
        "by_doctor": dict(sorted(by_doctor.items())),
    }


def item_out(i: QueueItem) -> dict:
    """Staff-safe JSON for one queue item."""
    return {
        "kind": i.kind,
        "id": i.id,
        "type": i.type_code,
        "type_label": i.type_label,
        "procedure": i.procedure,
        "patient": {"id": i.patient.id, "name": i.patient.name},
        "doctor": {"id": i.doctor.id, "name": i.doctor.name},
        "requested_by": {"id": i.requested_by.id, "name": i.requested_by.name},
        "original_appointment": {"id": i.origin.id, "start_time": i.origin.start_time.isoformat()},
        "status": i.status,
        "status_label": i.status_label,
        "stage": i.stage,
        "priority": i.priority,
        "due_date": i.by_date.isoformat() if i.by_date else None,
        "timeframe": i.timeframe_label,
        "duration_minutes": i.duration_minutes,
        "overdue": i.overdue,
        "next_step": i.next_step,
        "reception_note": i.reception_note,
        "resources": i.resources,
        "booked_appointment_id": i.booked.id if i.booked else None,
        "booked_start_time": i.booked.start_time.isoformat() if i.booked else None,
    }


# ---- Reception's contact steps for follow-ups (consultation follow-ups and procedure discussions) -----------
def _followup_record(db: Session, kind: str, item_id: int):
    model = {"consultation": ConsultationFollowup, "procedure": TreatmentRecommendation}.get(kind)
    record = db.get(model, item_id) if model else None
    if record is None:
        raise NotFoundError("We could not find that follow-up.")
    return record


def _label(kind: str, record) -> str:
    return record.type_label if kind == "consultation" else f"Procedure discussion: {record.procedure}"


def contact_patient(db: Session, kind: str, item_id: int):
    """Reception is contacting the patient to arrange the follow-up. Queues a simulated message."""
    record = _followup_record(db, kind, item_id)
    if record.status not in (RECOMMENDATION_READY, FOLLOWUP_AWAITING):
        raise ValidationError("This follow-up is not waiting for reception to contact the patient.")
    record.status = FOLLOWUP_CONTACT
    now = utils.now()
    db.add(TimelineEvent(
        kind="FOLLOWUP_CONTACTED", source=SOURCE_STAFF, occurred_at=now, patient_id=record.patient_id,
        appointment_id=record.appointment_id, detail=f"{_label(kind, record)} · reception is contacting the patient",
    ))
    patient = record.patient
    notifications.queue(
        db, "FOLLOWUP_SCHEDULING", key=f"{kind}:{record.id}:{now.isoformat()}", name=patient.name, mobile=patient.mobile,
        email=patient.email, patient_id=patient.id, doctor=record.doctor.name,
    )
    db.commit()
    return record


def mark_awaiting(db: Session, kind: str, item_id: int):
    """Reception has reached out and is waiting for the patient to reply."""
    record = _followup_record(db, kind, item_id)
    if record.status != FOLLOWUP_CONTACT:
        raise ValidationError("Mark the patient as contacted first.")
    record.status = FOLLOWUP_AWAITING
    db.add(TimelineEvent(
        kind="FOLLOWUP_AWAITING", source=SOURCE_STAFF, occurred_at=utils.now(), patient_id=record.patient_id,
        appointment_id=record.appointment_id, detail=f"{_label(kind, record)} · awaiting patient response",
    ))
    db.commit()
    return record


# ---- The booked appointment drives the item afterwards -------------------------------------------------------
def on_appointment_status(db: Session, appointment: Appointment, new_status: str) -> None:
    """Called inside appointments.set_status, before its commit."""
    if new_status not in (STATUS_COMPLETED, STATUS_CANCELLED, STATUS_NO_SHOW):
        return
    missed = "cancelled" if new_status == STATUS_CANCELLED else "missed (no-show)"
    now = utils.now()

    def event(kind, detail):
        db.add(TimelineEvent(kind=kind, source=SOURCE_STAFF, occurred_at=now, patient_id=appointment.patient_id,
                             appointment_id=appointment.id, detail=detail))

    request = appointment.consultation_followup
    if request is not None:
        if new_status == STATUS_COMPLETED:
            request.status = FOLLOWUP_COMPLETED
            event("FOLLOWUP_COMPLETED", f"{request.type_label} · completed")
        else:
            request.status = FOLLOWUP_AWAITING
            request.followup_appointment_id = None
            event("FOLLOWUP_REOPENED", f"{request.type_label} · booking {missed}, awaiting patient response")

    link = appointment.followup  # a procedure discussion booked from a recommendation
    if link is not None:
        recommendation = link.recommendation
        if new_status == STATUS_COMPLETED:
            recommendation.status = FOLLOWUP_COMPLETED
            event("FOLLOWUP_COMPLETED", f"Procedure discussion: {recommendation.procedure} · completed")
        else:
            recommendation.status = FOLLOWUP_AWAITING
            db.delete(link)  # free the recommendation for a new booking; the appointment and timeline remain
            event("FOLLOWUP_REOPENED", f"Procedure discussion: {recommendation.procedure} · booking {missed}, awaiting patient response")

    plan = appointment.procedure_plan
    if plan is not None:
        if new_status == STATUS_COMPLETED:
            plan.status = PLAN_COMPLETED
            event("PLAN_COMPLETED", f"{plan.service.name} · procedure appointment completed")
        else:
            plan.status = PLAN_DISCUSSING
            plan.scheduled_appointment_id = None
            event("PLAN_REOPENED", f"{plan.service.name} · procedure booking {missed}, discussing with patient again")
        plan.updated_at = now

