"""Public, patient-facing assistant: one page and one rate-limited message endpoint.

Nothing here returns patient lists, staff notes or other patients' details.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import knowledge, schemas
from ..database import get_db
from ..ratelimit import assistant_rate_limit
from ..services import assistant, clinic
from .pages import templates

router = APIRouter()


@router.get("/assistant", include_in_schema=False)
def assistant_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "assistant.html",
        {
            "clinic": clinic.get_clinic(db),
            "website": knowledge.CLINIC_WEBSITE,
            "prompts": knowledge.SUGGESTED_PROMPTS,
            "callback_promise": knowledge.CALLBACK_PROMISE,
        },
    )


@router.post("/api/assistant/message", tags=["assistant"], dependencies=[Depends(assistant_rate_limit)])
def assistant_message(body: schemas.AssistantMessage, db: Session = Depends(get_db)):
    return assistant.respond(db, text=body.text, action=body.action, value=body.value, state=body.state)
