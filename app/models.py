from datetime import date, datetime, time, timedelta

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, backref, mapped_column, relationship

from . import utils
from .database import Base

STATUS_PENDING = "PENDING"
STATUS_CONFIRMED = "CONFIRMED"
STATUS_CANCELLED = "CANCELLED"
# Consultation-day statuses, set from the doctor workspace.
STATUS_ARRIVED = "ARRIVED"
STATUS_COMPLETED = "COMPLETED"
STATUS_NO_SHOW = "NO_SHOW"
STATUSES = (STATUS_PENDING, STATUS_CONFIRMED, STATUS_CANCELLED, STATUS_ARRIVED, STATUS_COMPLETED, STATUS_NO_SHOW)

NEXT_STEPS = {
    "NO_FOLLOW_UP": "No follow-up needed",
    "FOLLOW_UP_CONSULTATION": "Follow-up consultation",
    "PROCEDURE_DISCUSSION": "Procedure discussion",
}
RECOMMENDATION_DRAFT = "DRAFT"
RECOMMENDATION_READY = "READY_FOR_SCHEDULING"
RECOMMENDATION_SCHEDULED = "SCHEDULED"
RECOMMENDATION_STATES = {
    RECOMMENDATION_DRAFT: "Draft",
    RECOMMENDATION_READY: "Ready for scheduling",
    RECOMMENDATION_SCHEDULED: "Scheduled",
}
# The follow-up lifecycle shared by consultation follow-ups and procedure-discussion recommendations.
# The doctor owns Draft → Ready; reception owns contact and scheduling; the booked appointment drives
# Completed (and a cancelled or missed booking goes back to Awaiting patient response).
FOLLOWUP_CONTACT = "CONTACT_PATIENT"
FOLLOWUP_AWAITING = "AWAITING_RESPONSE"
FOLLOWUP_COMPLETED = "COMPLETED"
FOLLOWUP_STATES = {
    **RECOMMENDATION_STATES,
    FOLLOWUP_CONTACT: "Contact patient",
    FOLLOWUP_AWAITING: "Awaiting patient response",
    FOLLOWUP_COMPLETED: "Completed",
    "CLOSED": "Closed · not required",
}
# States in which reception still has something to do (shown in "awaiting" lists).
FOLLOWUP_OPEN_STATES = (RECOMMENDATION_READY, FOLLOWUP_CONTACT, FOLLOWUP_AWAITING)
FOLLOWUP_TYPES = {
    "CONSULTATION": "Consultation follow-up",
    "REVIEW": "Review / check-up",
    "PROCEDURE_DISCUSSION": "Procedure discussion",
    "PROCEDURE_APPOINTMENT": "Procedure appointment",
}
PRIORITIES = {"ROUTINE": "Routine", "SOON": "Soon", "PRIORITY": "Priority"}
# Operational reasons for closing a request. Fixed, so no clinical reasoning can be attached.
CLOSE_REASONS = {
    "NOT_NEEDED": "No longer needed after review",
    "PATIENT_DECLINED": "Patient declined",
    "BOOKED_ELSEWHERE": "Already booked another way",
    "UNREACHABLE": "Patient could not be reached",
    "DUPLICATE": "Duplicate request",
}

# Procedure plans: an approved service the doctor plans to carry out, scheduled by reception.
PLAN_DRAFT = "DRAFT"
PLAN_READY = "READY_FOR_RECEPTION"
PLAN_DISCUSSING = "DISCUSSING"
PLAN_ACCEPTED = "ACCEPTED"
PLAN_SCHEDULED = "SCHEDULED"
PLAN_COMPLETED = "COMPLETED"
PLAN_DECLINED = "DECLINED"
PLAN_DEFERRED = "DEFERRED"
PLAN_CANCELLED = "CANCELLED"
PLAN_STATES = {
    PLAN_DRAFT: "Draft",
    PLAN_READY: "Ready for reception",
    PLAN_DISCUSSING: "Discussing with patient",
    PLAN_ACCEPTED: "Accepted",
    PLAN_SCHEDULED: "Scheduled",
    PLAN_COMPLETED: "Completed",
    PLAN_DECLINED: "Declined",
    PLAN_DEFERRED: "Deferred",
    PLAN_CANCELLED: "Cancelled",
}
PLAN_OPEN_STATES = (PLAN_READY, PLAN_DISCUSSING, PLAN_ACCEPTED, PLAN_DEFERRED)
PLAN_RESOURCES = {"CHAIR": "Treatment chair", "ROOM": "Procedure room", "EQUIPMENT": "Special equipment"}
PLAN_DURATIONS = (30, 45, 60, 90, 120)
PLAN_INSTRUCTION_LIMIT = 160
FOLLOWUP_LABEL = "Procedure discussion / follow-up"
CONSULTATION_FOLLOWUP_LABEL = "Consultation follow-up"
# A follow-up the doctor marked as no longer needed (before reception booked it).
FOLLOWUP_CLOSED = "CLOSED"

# Doctor-managed patient flags: (label, plain operational meaning for reception). No clinical reasoning.
PATIENT_FLAGS = {
    "NEEDS_FOLLOW_UP": ("Needs follow-up", "The doctor wants this patient seen again. Check Follow-ups for a booking request."),
    "PRIORITY_REVIEW": ("Priority review", "Give this patient priority: offer the earliest suitable time and let the doctor know when booked."),
    "DOCTOR_REVIEW_BEFORE_BOOKING": (
        "Do not schedule without doctor review", "Check with the doctor before booking any new appointment for this patient.",
    ),
}
# Fixed, operational reasons a doctor may give reception for a callback. Doctors cannot type free text here.
DOCTOR_CALLBACK_REASONS = {
    "ARRANGE_FOLLOW_UP": "Please call to arrange follow-up",
    "CONFIRM_APPOINTMENT": "Please confirm appointment",
    "ASK_TO_CONTACT": "Please ask patient to contact clinic",
}
# Preferred follow-up timing the doctor can attach to a request. Reception still books a normal slot.
FOLLOWUP_DURATIONS = (15, 30, 45)
FOLLOWUP_TIMEFRAMES = {"WEEK_1": ("Within 1 week", 7), "WEEK_2": ("Within 2 weeks", 14), "MONTH_1": ("Within 1 month", 30), "DATE": ("By a chosen date", None)}

BLOCK_REASONS = {"LEAVE": "Leave", "PERSONAL": "Personal", "TRAINING": "Training", "OTHER": "Other"}

BOOKING_SOURCES = ("STAFF", "WEBSITE", "AI_DEMO")

CALLBACK_OPEN = "OPEN"
CALLBACK_IN_PROGRESS = "IN_PROGRESS"
CALLBACK_COMPLETED = "COMPLETED"
CALLBACK_STATUSES = (CALLBACK_OPEN, CALLBACK_IN_PROGRESS, CALLBACK_COMPLETED)

CALL_CHANNEL_VOICE_DEMO = "VOICE_DEMO"
CALL_FAQ_ANSWERED = "FAQ_ANSWERED"
CALL_BOOKING_CREATED = "BOOKING_CREATED"
CALL_CALLBACK_CREATED = "CALLBACK_CREATED"
CALL_ENDED = "ENDED"
CALL_OUTCOMES = (CALL_FAQ_ANSWERED, CALL_BOOKING_CREATED, CALL_CALLBACK_CREATED, CALL_ENDED)


class Clinic(Base):
    __tablename__ = "clinics"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(120))
    currency_symbol: Mapped[str] = mapped_column(String(8), default="₹")
    is_demo: Mapped[bool] = mapped_column(default=False)


class Doctor(Base):
    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    speciality: Mapped[str] = mapped_column(String(120))
    work_start: Mapped[time]
    work_end: Mapped[time]
    consultation_minutes: Mapped[int] = mapped_column(default=30)
    # Comma-separated weekdays, 0 = Monday ... 6 = Sunday
    working_days: Mapped[str] = mapped_column(String(20), default="0,1,2,3,4,5")
    is_demo: Mapped[bool] = mapped_column(default=False)

    @property
    def working_day_set(self) -> set[int]:
        return {int(d) for d in self.working_days.split(",") if d != ""}


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    fee: Mapped[int] = mapped_column(default=0)
    is_demo: Mapped[bool] = mapped_column(default=False)


class Planning:
    """Reception-facing planning fields shared by follow-ups and procedure plans: priority, a suggested
    timeframe with its target date, and a preferred length. Operational only."""

    @property
    def priority_code(self) -> str:
        return self.priority or "ROUTINE"

    @property
    def priority_label(self) -> str:
        return PRIORITIES.get(self.priority_code, "Routine")

    @property
    def timeframe_label(self) -> str | None:
        if self.timeframe and self.timeframe != "DATE":
            return FOLLOWUP_TIMEFRAMES[self.timeframe][0]
        return f"By {utils.fmt_date(self.by_date)}" if self.by_date else None

    def is_overdue(self, today: date) -> bool:
        return bool(self.by_date and self.by_date < today and self.status in (*FOLLOWUP_OPEN_STATES, *PLAN_OPEN_STATES))

    @property
    def summary(self) -> str:
        parts = []
        if getattr(self, "duration_minutes", None):
            parts.append(f"{self.duration_minutes} min")
        if self.timeframe and self.timeframe != "DATE":
            parts.append(FOLLOWUP_TIMEFRAMES[self.timeframe][0].lower())
        if self.by_date:
            parts.append(f"by {utils.fmt_date(self.by_date)}")
        return " · ".join(parts)


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    # Digits only; unique so the same mobile number cannot be registered twice.
    mobile: Mapped[str] = mapped_column(String(20), unique=True)
    email: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())


class Slot(Base):
    """A bookable consultation slot. Whether it is free is derived from appointments."""

    __tablename__ = "slots"
    __table_args__ = (UniqueConstraint("doctor_id", "start_time", name="uq_slot_doctor_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    start_time: Mapped[datetime] = mapped_column(index=True)
    end_time: Mapped[datetime]

    doctor: Mapped[Doctor] = relationship()

    @property
    def duration_minutes(self) -> int:
        return int((self.end_time - self.start_time).total_seconds() // 60)


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        # Database-level guard: one active appointment per doctor and start time.
        Index(
            "uq_active_appointment_doctor_start",
            "doctor_id",
            "start_time",
            unique=True,
            sqlite_where=text("status != 'CANCELLED'"),
            postgresql_where=text("status != 'CANCELLED'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    start_time: Mapped[datetime] = mapped_column(index=True)
    end_time: Mapped[datetime]
    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDING, index=True)
    source: Mapped[str] = mapped_column(String(20), default="STAFF")
    is_demo: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())

    patient: Mapped[Patient] = relationship()
    doctor: Mapped[Doctor] = relationship()
    service: Mapped[Service] = relationship()

    @property
    def is_active(self) -> bool:
        return self.status != STATUS_CANCELLED

    @property
    def can_cancel(self) -> bool:
        """Reception can cancel only before the patient has arrived."""
        return self.status in (STATUS_PENDING, STATUS_CONFIRMED)


class CallbackTask(Base):
    """A request for the front desk to phone a patient or lead."""

    __tablename__ = "callback_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    mobile: Mapped[str] = mapped_column(String(20), index=True)
    email: Mapped[str | None] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="AI_DEMO")
    status: Mapped[str] = mapped_column(String(20), default=CALLBACK_OPEN, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())


class CallLog(Base):
    """One simulated voice call. Demo only: no real call is received or recorded."""

    __tablename__ = "call_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(20), default=CALL_CHANNEL_VOICE_DEMO)
    caller_name: Mapped[str | None] = mapped_column(String(120))
    caller_mobile: Mapped[str | None] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(default=lambda: utils.now(), index=True)
    completed_at: Mapped[datetime | None]
    # Empty while the call is in progress and nothing has happened yet.
    outcome: Mapped[str | None] = mapped_column(String(20))
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"))
    callback_task_id: Mapped[int | None] = mapped_column(ForeignKey("callback_tasks.id"))

    appointment: Mapped[Appointment | None] = relationship()
    callback_task: Mapped[CallbackTask | None] = relationship()

    @property
    def duration_seconds(self) -> int | None:
        if self.completed_at is None:
            return None
        return max(0, int((self.completed_at - self.started_at).total_seconds()))


class ConsultationOutcome(Base):
    """Doctor-entered consultation outcome for one appointment. Demo only: not a medical record."""

    __tablename__ = "consultation_outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    summary: Mapped[str] = mapped_column(Text)
    next_step: Mapped[str] = mapped_column(String(30))
    follow_up_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())
    updated_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())

    appointment: Mapped[Appointment] = relationship(backref=backref("outcome", uselist=False))
    doctor: Mapped[Doctor] = relationship()


class ConsultationStart(Base):
    """When the doctor started seeing an arrived patient ("In consultation").

    A workspace stage, not an appointment status: the appointment stays ARRIVED until
    it is completed, so reception, check-in, analytics and the calendar are unchanged.
    """

    __tablename__ = "consultation_starts"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    started_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())

    appointment: Mapped[Appointment] = relationship(backref=backref("consultation_start", uselist=False))


class PatientFlag(Base):
    """An operational flag a doctor sets on one of their patients. Reception sees the label and its
    plain meaning; there is no free text, so no clinical reasoning can be attached."""

    __tablename__ = "patient_flags"
    __table_args__ = (UniqueConstraint("patient_id", "doctor_id", "kind"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    kind: Mapped[str] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())

    patient: Mapped[Patient] = relationship(backref=backref("flags", order_by="PatientFlag.id"))
    doctor: Mapped[Doctor] = relationship()

    @property
    def label(self) -> str:
        return PATIENT_FLAGS[self.kind][0]

    @property
    def meaning(self) -> str:
        return PATIENT_FLAGS[self.kind][1]


class DoctorPatientNote(Base):
    """Private doctor notes about a patient. Read and written only in that doctor's own workspace:
    no reception page, timeline, API, notification, call screen or assistant reads this table."""

    __tablename__ = "doctor_patient_notes"
    __table_args__ = (UniqueConstraint("patient_id", "doctor_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))  # the author
    body: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())
    updated_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())


class TreatmentRecommendation(Planning, Base):
    """A doctor's draft treatment recommendation. Only the doctor workspace creates these;
    reception and the assistant can read them but never create, edit or approve them."""

    __tablename__ = "treatment_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    procedure: Mapped[str] = mapped_column(String(120))
    doctor_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=RECOMMENDATION_DRAFT)
    created_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())
    # Planning (added later, so nullable): set by the doctor when releasing it to reception.
    priority: Mapped[str | None] = mapped_column(String(20))
    timeframe: Mapped[str | None] = mapped_column(String(20))
    by_date: Mapped[date | None]
    close_reason: Mapped[str | None] = mapped_column(String(30))

    appointment: Mapped[Appointment] = relationship(backref=backref("recommendations", order_by="TreatmentRecommendation.id"))
    doctor: Mapped[Doctor] = relationship()
    patient: Mapped[Patient] = relationship()


class DoctorBlock(Base):
    """A period a doctor has blocked (leave, training...). Slots inside it are never offered."""

    __tablename__ = "doctor_blocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    start_time: Mapped[datetime] = mapped_column(index=True)
    end_time: Mapped[datetime]
    reason: Mapped[str] = mapped_column(String(20), default="LEAVE")
    created_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())

    doctor: Mapped[Doctor] = relationship()

    @property
    def all_day(self) -> bool:
        return self.start_time.time() == time.min and self.end_time - self.start_time == timedelta(days=1)


# Who or what caused a timeline event.
SOURCE_STAFF = "STAFF"
SOURCE_WEBSITE = "WEBSITE"
SOURCE_WEBSITE_AI = "WEBSITE_AI"
SOURCE_VOICE_DEMO = "VOICE_DEMO"
SOURCE_DOCTOR = "DOCTOR"
SOURCE_LABELS = {
    SOURCE_STAFF: "Staff",
    SOURCE_WEBSITE: "Website",
    SOURCE_WEBSITE_AI: "Website AI",
    SOURCE_VOICE_DEMO: "Voice Demo",
    SOURCE_DOCTOR: "Doctor",
}


class TimelineEvent(Base):
    """When something changed, for the patient timeline.

    Only records what no other table keeps: the moment and actor of a status
    change (confirmed, arrived, callback started...). Creation events are read
    from the records themselves. Later event kinds (QR check-in, notifications)
    can be added here without changing the timeline.
    """

    __tablename__ = "timeline_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(20))
    occurred_at: Mapped[datetime] = mapped_column(default=lambda: utils.now(), index=True)
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"), index=True)
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"), index=True)
    callback_task_id: Mapped[int | None] = mapped_column(ForeignKey("callback_tasks.id"), index=True)
    # Short, staff-safe text only. Never clinical notes.
    detail: Mapped[str | None] = mapped_column(String(255))


class CheckinToken(Base):
    """An opaque, random check-in token for one appointment (shown as a QR code).

    The token is the whole QR payload. It carries no patient or appointment
    information; everything is looked up here on the server.
    """

    __tablename__ = "checkin_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())
    used_at: Mapped[datetime | None]  # when the patient was checked in with it

    appointment: Mapped[Appointment] = relationship(backref=backref("checkin_token", uselist=False))


WAITLIST_WAITING = "WAITING"
WAITLIST_OFFERED = "OFFERED"
WAITLIST_BOOKED = "BOOKED"
WAITLIST_CLOSED = "CLOSED"
WAITLIST_STATUSES = (WAITLIST_WAITING, WAITLIST_OFFERED, WAITLIST_BOOKED, WAITLIST_CLOSED)
TIME_PREFERENCES = {"MORNING": "Morning (before 12 noon)", "AFTERNOON": "Afternoon (12 noon onwards)", "ANY": "Any time"}
CONTACT_PREFERENCES = {"PHONE": "Phone call", "MESSAGE": "Text message", "EMAIL": "Email"}


class WaitlistEntry(Base):
    """A patient waiting for a consultation time to become free.

    The waitlist never books, reserves or contacts anyone by itself: staff offer a
    freed slot and book it only after the patient has accepted.
    """

    __tablename__ = "waitlist_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctors.id"))  # empty = any doctor
    date_from: Mapped[date]
    date_to: Mapped[date]
    time_preference: Mapped[str] = mapped_column(String(20), default="ANY")
    contact_preference: Mapped[str] = mapped_column(String(20), default="PHONE")
    status: Mapped[str] = mapped_column(String(20), default=WAITLIST_WAITING, index=True)
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="STAFF")
    created_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())
    # The slot staff have offered (not reserved), and the booking made from it.
    offered_slot_id: Mapped[int | None] = mapped_column(ForeignKey("slots.id", ondelete="SET NULL"))
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"))

    patient: Mapped[Patient] = relationship()
    service: Mapped[Service] = relationship()
    doctor: Mapped[Doctor | None] = relationship()
    offered_slot: Mapped[Slot | None] = relationship()
    appointment: Mapped[Appointment | None] = relationship()


NOTIFICATION_QUEUED = "QUEUED"
NOTIFICATION_SENT = "SENT"
NOTIFICATION_DELIVERED = "DELIVERED"
NOTIFICATION_FAILED = "FAILED"
NOTIFICATION_STATUSES = (NOTIFICATION_QUEUED, NOTIFICATION_SENT, NOTIFICATION_DELIVERED, NOTIFICATION_FAILED)


class Notification(Base):
    """One simulated outbound message in the demo Notification Centre. Nothing is ever sent."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=NOTIFICATION_QUEUED, index=True)
    recipient_name: Mapped[str] = mapped_column(String(120))
    recipient_contact: Mapped[str] = mapped_column(String(120))  # sample mobile or email; masked in lists
    message: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(default=1)  # 1 = first attempt; each retry adds one
    # One notification per triggering event, e.g. "APPOINTMENT_CONFIRMATION:appointment:5".
    dedupe_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: utils.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id"), index=True)
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"))
    callback_task_id: Mapped[int | None] = mapped_column(ForeignKey("callback_tasks.id"))
    waitlist_entry_id: Mapped[int | None] = mapped_column(ForeignKey("waitlist_entries.id"))

    patient: Mapped[Patient | None] = relationship()


class ProcedureFollowup(Base):
    """Links a doctor's recommendation to the follow-up appointment reception booked for it.

    One recommendation can have one follow-up (unique), and the appointment is an
    ordinary consultation booking labelled as a procedure discussion: it is not
    treatment delivery, and no room, chair or equipment is scheduled.
    """

    __tablename__ = "procedure_followups"

    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("treatment_recommendations.id"), unique=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True)
    staff_note: Mapped[str | None] = mapped_column(Text)  # reception's scheduling note, not a clinical note
    created_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())

    recommendation: Mapped[TreatmentRecommendation] = relationship(backref=backref("followup", uselist=False))
    appointment: Mapped[Appointment] = relationship(backref=backref("followup", uselist=False))


class ConsultationFollowup(Planning, Base):
    """A doctor's request for reception to book a follow-up consultation (or a review / check-up).

    Created only by the doctor: as a draft, or sent straight to reception. It carries no clinical
    text: reception sees the patient, the doctor, the type, planning fields and the state.
    """

    __tablename__ = "consultation_followups"

    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), unique=True)  # the original consultation
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default=RECOMMENDATION_READY, index=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())
    followup_appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"), unique=True)
    staff_note: Mapped[str | None] = mapped_column(Text)  # reception's scheduling note
    # Planning (added later, so nullable). An empty type means a consultation follow-up.
    followup_type: Mapped[str | None] = mapped_column(String(20))
    priority: Mapped[str | None] = mapped_column(String(20))
    timeframe: Mapped[str | None] = mapped_column(String(20))
    by_date: Mapped[date | None]
    duration_minutes: Mapped[int | None]
    close_reason: Mapped[str | None] = mapped_column(String(30))

    appointment: Mapped[Appointment] = relationship(
        foreign_keys=[appointment_id], backref=backref("followup_request", uselist=False)
    )
    followup_appointment: Mapped[Appointment | None] = relationship(
        foreign_keys=[followup_appointment_id], backref=backref("consultation_followup", uselist=False)
    )
    doctor: Mapped[Doctor] = relationship()
    patient: Mapped[Patient] = relationship()

    @property
    def type_code(self) -> str:
        return self.followup_type or "CONSULTATION"

    @property
    def type_label(self) -> str:
        return FOLLOWUP_TYPES[self.type_code]


class ProcedurePlan(Planning, Base):
    """A doctor's plan for a procedure appointment, using an approved service from the clinic catalogue.

    Reception sees the service name, status, the short operational instruction, the preferred doctor,
    timeframe, duration and resources. The private note never leaves the doctor workspace.
    """

    __tablename__ = "procedure_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))  # the planning doctor, who owns it
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id"), index=True)  # the consultation it came from
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"))
    preferred_doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    duration_minutes: Mapped[int | None]
    timeframe: Mapped[str | None] = mapped_column(String(20))
    by_date: Mapped[date | None]
    priority: Mapped[str | None] = mapped_column(String(20))
    resources: Mapped[str | None] = mapped_column(String(80))  # comma-separated PLAN_RESOURCES codes
    reception_instruction: Mapped[str | None] = mapped_column(String(PLAN_INSTRUCTION_LIMIT))
    private_note: Mapped[str | None] = mapped_column(Text)  # doctor workspace only
    status: Mapped[str] = mapped_column(String(20), default=PLAN_DRAFT, index=True)
    close_reason: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())
    updated_at: Mapped[datetime] = mapped_column(default=lambda: utils.now())
    scheduled_appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"), unique=True)

    patient: Mapped[Patient] = relationship()
    doctor: Mapped[Doctor] = relationship(foreign_keys=[doctor_id])
    preferred_doctor: Mapped[Doctor] = relationship(foreign_keys=[preferred_doctor_id])
    service: Mapped[Service] = relationship()
    appointment: Mapped[Appointment] = relationship(
        foreign_keys=[appointment_id], backref=backref("procedure_plans", order_by="ProcedurePlan.id")
    )
    scheduled_appointment: Mapped[Appointment | None] = relationship(
        foreign_keys=[scheduled_appointment_id], backref=backref("procedure_plan", uselist=False)
    )

    @property
    def resource_codes(self) -> list[str]:
        return [r for r in (self.resources or "").split(",") if r in PLAN_RESOURCES]

    @property
    def resource_labels(self) -> list[str]:
        return [PLAN_RESOURCES[r] for r in self.resource_codes]

    @property
    def state_label(self) -> str:
        return PLAN_STATES.get(self.status, self.status)
