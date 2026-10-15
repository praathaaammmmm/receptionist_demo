"""Business-rule errors. Messages are written for reception staff, not developers."""
from .. import config


class ClinicError(Exception):
    status_code = 400
    code = "invalid_request"
    default_message = "Please check the details and try again."

    def __init__(self, message: str | None = None):
        self.message = message or self.default_message
        super().__init__(self.message)


class ValidationError(ClinicError):
    pass


class NotFoundError(ClinicError):
    status_code = 404
    code = "not_found"
    default_message = "We could not find that record."


class SlotTakenError(ClinicError):
    status_code = 409
    code = "slot_taken"
    default_message = config.SLOT_TAKEN_MESSAGE


class NotPermittedError(ClinicError):
    status_code = 403
    code = "not_permitted"
    default_message = "That is not available from this screen."


class RateLimitedError(ClinicError):
    status_code = 429
    code = "rate_limited"
    default_message = "You are sending messages very quickly. Please wait a moment and try again."


class DuplicatePatientError(ClinicError):
    status_code = 409
    code = "duplicate_patient"

    def __init__(self, patient):
        self.patient = patient
        super().__init__(f"A patient with this mobile number is already registered: {patient.name}.")
