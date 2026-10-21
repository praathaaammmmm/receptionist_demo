"""Typed shapes for the voice agent: policy results, callback details and tool contracts.

The tool contracts describe what a later LLM integration may call. Nothing executes them
in this phase: there is no tool-calling, telephony or database write here.
"""
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import phone


class Language(StrEnum):
    EN = "en"
    HI = "hi"  # Hindi in Devanagari
    HINGLISH = "hinglish"  # Hindi in Roman script, English words where callers use them


class CallbackCategory(StrEnum):
    APPOINTMENT = "appointment"
    ENQUIRY = "enquiry"
    PANEL = "panel"
    HUMAN_REQUEST = "human_request"
    URGENT = "urgent"
    OTHER = "other"


class PolicyPath(StrEnum):
    ANSWER = "answer"  # an approved fact
    UNKNOWN = "unknown"  # not in approved knowledge: never guess, offer a callback
    PANEL = "panel"  # CGHS / ECHS / CISF / DU / Air India: panel callback only
    CLINICAL = "clinical"  # no diagnosis, medicines, remedies or reassurance
    TOOTH_PAIN = "tooth_pain"  # ordinary pain or sensitivity: appointment callback
    EMERGENCY = "emergency"  # urgent symptoms: 112 first
    HUMAN_REQUEST = "human_request"
    CALLBACK_REQUEST = "callback_request"  # "please call me back": take details, then ask the reason


class NextAction(StrEnum):
    CONTINUE = "continue"
    OFFER_CALLBACK = "offer_callback"  # ask whether the caller wants a callback
    CAPTURE_CALLBACK = "capture_callback"  # start taking name and number now
    TRANSFER = "transfer"  # call transfer_to_reception


class PolicyResponse(BaseModel):
    """What the policy decided, with the words to say. `text` is spoken: no bullets, emojis or URLs."""

    model_config = ConfigDict(frozen=True)

    path: PolicyPath
    language: Language
    text: str
    next_action: NextAction
    topic: str | None = None
    callback_category: CallbackCategory | None = None
    urgent: bool = False
    matched_rules: tuple[str, ...] = ()


class UnknownInformation(PolicyResponse):
    """The information is not approved. No answer is given; a callback is offered."""

    path: Literal[PolicyPath.UNKNOWN, PolicyPath.PANEL] = PolicyPath.UNKNOWN
    topic: str
    answered: Literal[False] = False
    next_action: Literal[NextAction.OFFER_CALLBACK] = NextAction.OFFER_CALLBACK
    callback_category: CallbackCategory = CallbackCategory.ENQUIRY


class CallbackDetails(BaseModel):
    """A validated callback request. Created only after the caller confirms name and number."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(description="10-digit Indian mobile number")
    language: Language
    reason: str = Field(min_length=1, max_length=500)
    category: CallbackCategory
    urgent: bool = False
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("phone")
    @classmethod
    def _phone(cls, value: str) -> str:
        return phone.normalize_indian_mobile(value)

    @model_validator(mode="after")
    def _urgent_matches_category(self):
        if self.urgent != (self.category == CallbackCategory.URGENT):
            raise ValueError("Only an urgent-category callback is marked urgent, and it must be.")
        return self


# The phone value meaning "the number this call is coming from". The runtime fills in the
# digits, so the model never sees or reads out the caller's number.
CALLER_NUMBER = "caller_number"


class CreateCallbackArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Caller's name exactly as they confirmed it")
    phone: str = Field(
        description=f"The confirmed 10-digit Indian mobile number, or '{CALLER_NUMBER}' if the caller agreed "
        "to be called back on the number they are calling from"
    )
    language: Language = Field(description="Language the caller is using")
    reason: str = Field(description="One short sentence: why the caller wants a callback")
    category: CallbackCategory
    urgent: bool = Field(description="True only for an urgent escalation (category 'urgent')")
    notes: str | None = Field(default=None, description="Anything staff need; never a diagnosis")


class TransferToReceptionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EndCallArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolContract:
    name: str
    description: str
    args: type[BaseModel]
    rules: tuple[str, ...]

    def parameters_schema(self) -> dict:
        return self.args.model_json_schema()


TOOLS = (
    ToolContract(
        name="create_callback",
        description="Record a request for clinic staff to phone the caller back. Places no call itself.",
        args=CreateCallbackArgs,
        rules=(
            "Call only after reading back the name and number and the caller saying yes.",
            "At most one callback per call; a separate urgent escalation is the only exception.",
            "phone must be a 10-digit Indian mobile starting with 6, 7, 8 or 9 (a leading +91 or 0 is ignored).",
        ),
    ),
    ToolContract(
        name="transfer_to_reception",
        description="Try to connect the caller to a person at reception.",
        args=TransferToReceptionArgs,
        rules=(
            "Call only when transfer_available is yes.",
            "If it fails, apologise and start taking callback details straight away.",
        ),
    ),
    ToolContract(
        name="end_call",
        description="End the call politely.",
        args=EndCallArgs,
        rules=(
            "Never end a call where the caller asked for a person until they were transferred "
            "or offered a callback.",
            "Say a short goodbye first.",
        ),
    ),
)
