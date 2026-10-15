"""Read-only views for the doctor workspace: the day board, the next patient and operational
patient context.

Nothing here writes. Everything is scoped to one doctor's own appointments, and the patient
context is operational only (dates, statuses, markers): it never reads a consultation summary,
follow-up note or recommendation note.

"In consultation" is a workspace stage, not an appointment status. The appointment stays
ARRIVED (see ConsultationStart), so reception, check-in and analytics are unchanged.
"""
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..models import (
    CALLBACK_COMPLETED,
    FOLLOWUP_CLOSED,
    RECOMMENDATION_READY,
    FOLLOWUP_STATES,
    STATUS_ARRIVED,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_CONFIRMED,
    STATUS_NO_SHOW,
    Appointment,
    CallbackTask,
    ConsultationFollowup,
    TreatmentRecommendation,
    WaitlistEntry,
)
from . import consultations

STAGE_UPCOMING = "UPCOMING"
STAGE_WAITING = "WAITING"
STAGE_IN_CONSULTATION = "IN_CONSULTATION"
STAGE_COMPLETED = "COMPLETED"
STAGE_NO_SHOW = "NO_SHOW"
STAGE_LABELS = {
    STAGE_UPCOMING: "Upcoming",
    STAGE_WAITING: "Arrived · waiting",
    STAGE_IN_CONSULTATION: "In consultation",
    STAGE_COMPLETED: "Completed",
    STAGE_NO_SHOW: "No-show",
}
# Queue filters, in display order. The key is what appears in the address (?show=...).
FILTERS = {
    "all": ("All today", None),
    "upcoming": ("Upcoming", STAGE_UPCOMING),
    "waiting": ("Waiting / arrived", STAGE_WAITING),
    "in_consultation": ("In consultation", STAGE_IN_CONSULTATION),
    "completed": ("Completed", STAGE_COMPLETED),
    "no_show": ("No-show", STAGE_NO_SHOW),
}
# Consultation follow-up handoff, as the doctor sees it.
HANDOFF_NOT_SENT, HANDOFF_READY, HANDOFF_SCHEDULED, HANDOFF_CLOSED = "NOT_SENT", "READY", "SCHEDULED", "CLOSED"
HANDOFF_STEPS = ((HANDOFF_NOT_SENT, "Not sent"), (HANDOFF_READY, "Ready for reception"), (HANDOFF_SCHEDULED, "Scheduled"))
# Procedure recommendation, as the doctor sees it (stored states keep their existing names).
RECOMMENDATION_STEPS = (("DRAFT", "Draft"), (RECOMMENDATION_READY, "Ready for reception"), ("SCHEDULED", "Scheduled"))


def stage(appointment: Appointment) -> str | None:
    if appointment.status == STATUS_CONFIRMED:
        return STAGE_UPCOMING
    if appointment.status == STATUS_ARRIVED:
        return STAGE_IN_CONSULTATION if appointment.consultation_start else STAGE_WAITING
    if appointment.status == STATUS_COMPLETED:
        return STAGE_COMPLETED
    if appointment.status == STATUS_NO_SHOW:
        return STAGE_NO_SHOW
    return None


def mask_mobile(mobile: str) -> str:
    """Everything but the last four digits hidden, for the at-a-glance card."""
    digits = re.sub(r"\D", "", mobile or "")
    return "•" * max(len(digits) - 4, 0) + digits[-4:]


def handoff_state(appointment: Appointment) -> str:
    request = appointment.followup_request
    if request is None:
        return HANDOFF_NOT_SENT
    if request.status == FOLLOWUP_CLOSED:
        return HANDOFF_CLOSED
    return HANDOFF_SCHEDULED if request.followup_appointment_id else HANDOFF_READY


def arrival(appointment: Appointment) -> dict:
    """Arrival / check-in indicator: how and when the patient was recorded as arrived."""
    token = appointment.checkin_token
    if token is not None and token.used_at is not None:
        return {"state": "qr", "label": f"QR check-in {token.used_at.strftime('%I:%M %p').lstrip('0')}"}
    if appointment.status in (STATUS_ARRIVED, STATUS_COMPLETED):
        return {"state": "arrived", "label": "Arrived"}
    if appointment.status == STATUS_NO_SHOW:
        return {"state": "absent", "label": "Did not arrive"}
    return {"state": "expected", "label": "Not arrived yet"}


@dataclass
class Visit:
    appointment: Appointment
    stage: str
    flags: list[str] = field(default_factory=list)

    @property
    def stage_label(self) -> str:
        return STAGE_LABELS[self.stage]

    @property
    def arrival(self) -> dict:
        return arrival(self.appointment)


@dataclass
class Board:
    visits: list[Visit]
    shown: list[Visit]
    counts: dict[str, int]
    next_visit: Visit | None
    filter: str


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def operational_flags(db: Session, appointments: list[Appointment]) -> dict[int, list[str]]:
    """Front-desk flags per appointment. Operational only: no clinical text is read."""
    flags: dict[int, list[str]] = {a.id: [] for a in appointments}
    if not appointments:
        return flags
    patient_ids = {a.patient_id for a in appointments}
    mobiles = {_digits(a.patient.mobile) for a in appointments}

    open_callback_mobiles = {
        _digits(t.mobile)
        for t in db.scalars(select(CallbackTask).where(CallbackTask.status != CALLBACK_COMPLETED))
        if _digits(t.mobile) in mobiles
    }
    followup_due = set(
        db.scalars(select(ConsultationFollowup.patient_id).where(
            ConsultationFollowup.patient_id.in_(patient_ids), ConsultationFollowup.status == RECOMMENDATION_READY
        ))
    ) | set(
        db.scalars(select(TreatmentRecommendation.patient_id).where(
            TreatmentRecommendation.patient_id.in_(patient_ids), TreatmentRecommendation.status == RECOMMENDATION_READY
        ))
    )
    from_waitlist = set(db.scalars(select(WaitlistEntry.appointment_id).where(
        WaitlistEntry.appointment_id.in_([a.id for a in appointments])
    )))
    no_shows = list(db.execute(select(Appointment.patient_id, Appointment.start_time).where(
        Appointment.patient_id.in_(patient_ids), Appointment.status == STATUS_NO_SHOW
    )))

    for a in appointments:
        if _digits(a.patient.mobile) in open_callback_mobiles:
            flags[a.id].append("Open callback")
        if a.followup is not None or a.consultation_followup is not None:
            flags[a.id].append("Follow-up visit")
        if a.patient_id in followup_due:
            flags[a.id].append("Follow-up due")
        if a.id in from_waitlist:
            flags[a.id].append("From waitlist")
        if any(pid == a.patient_id and start < a.start_time for pid, start in no_shows):
            flags[a.id].append("Previous no-show")
    return flags


def day_board(db: Session, doctor_id: int, show: str = "all") -> Board:
    """Today's list for one doctor, with stages, counts, the next patient and a filtered view."""
    show = show if show in FILTERS else "all"
    todays = consultations.todays_list(db, doctor_id)
    flags = operational_flags(db, todays)
    visits = [Visit(a, stage(a), flags[a.id]) for a in todays]
    counts = {key: sum(v.stage == key for v in visits) for key in STAGE_LABELS}
    # The doctor's next patient: whoever is already with them, else the first one waiting, else the next expected.
    next_visit = next(
        (v for wanted in (STAGE_IN_CONSULTATION, STAGE_WAITING, STAGE_UPCOMING) for v in visits if v.stage == wanted), None
    )
    wanted = FILTERS[show][1]
    shown = [v for v in visits if wanted is None or v.stage == wanted]
    return Board(visits=visits, shown=shown, counts=counts, next_visit=next_visit, filter=show)


def neighbours(board: Board, appointment: Appointment) -> tuple[Appointment | None, Appointment | None]:
    """Previous and next patient in this doctor's same-day list (only when the open one is in it)."""
    ids = [v.appointment.id for v in board.visits]
    if appointment.id not in ids:
        return None, None
    i = ids.index(appointment.id)
    previous = board.visits[i - 1].appointment if i > 0 else None
    following = board.visits[i + 1].appointment if i + 1 < len(ids) else None
    return previous, following


def patient_context(db: Session, appointment: Appointment) -> dict:
    """Operational history for the open consultation: dates, statuses and markers only."""
    patient = appointment.patient
    history = list(db.scalars(
        select(Appointment)
        .options(joinedload(Appointment.doctor), joinedload(Appointment.service))
        .where(Appointment.patient_id == patient.id, Appointment.id != appointment.id)
        .order_by(Appointment.start_time.desc())
    ))
    callbacks = [
        t for t in db.scalars(select(CallbackTask).order_by(CallbackTask.created_at.desc()))
        if _digits(t.mobile) == _digits(patient.mobile)
    ]
    waitlist = list(db.scalars(
        select(WaitlistEntry).where(WaitlistEntry.patient_id == patient.id).order_by(WaitlistEntry.created_at.desc())
    ))
    recommendations = list(db.scalars(
        select(TreatmentRecommendation)
        .options(joinedload(TreatmentRecommendation.doctor))
        .where(TreatmentRecommendation.patient_id == patient.id, TreatmentRecommendation.appointment_id != appointment.id)
        .order_by(TreatmentRecommendation.created_at.desc())
    ))
    return {
        "history": history[:8],
        "history_total": len(history),
        "no_shows": sum(a.status == STATUS_NO_SHOW for a in history),
        "cancellations": sum(a.status == STATUS_CANCELLED for a in history),
        # Status and date only: the reason and staff notes stay on the reception dashboard.
        "callbacks": [{"status": t.status, "created_at": t.created_at} for t in callbacks[:5]],
        "open_callbacks": sum(t.status != CALLBACK_COMPLETED for t in callbacks),
        "waitlist": waitlist[:5],
        "from_waitlist": any(w.appointment_id == appointment.id for w in waitlist),
        # Procedure name, state, doctor and date only: never the doctor's note.
        "recommendations": [
            {"procedure": r.procedure, "state": FOLLOWUP_STATES.get(r.status, r.status), "doctor": r.doctor.name, "created_at": r.created_at}
            for r in recommendations[:5]
        ],
        "checkin": arrival(appointment),
    }
