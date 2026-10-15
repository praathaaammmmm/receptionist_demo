"""QR appointment check-in: staff screens only (demo).

Generating a QR and checking a patient in are both reception actions. The
token is posted, never put in a URL, and a refused token shows only a message.
"""
from fastapi import APIRouter, Depends, Form, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import schemas
from ..database import get_db
from ..services import appointments, checkin
from ..services.errors import ClinicError, NotFoundError
from .pages import redirect, render

router = APIRouter()


class TokenBody(BaseModel):
    token: str = Field(default="", max_length=200)


def _result_out(result: dict) -> dict:
    appointment, record = result["appointment"], result["token"]
    return {
        "state": result["state"],
        "message": result["message"],
        # Present only for a usable or already-used token; refusals carry no patient data.
        "appointment": schemas.appointment_out(appointment) if appointment else None,
        "checked_in_at": record.used_at.isoformat() if record and record.used_at else None,
    }


@router.get("/check-in", include_in_schema=False)
def checkin_page(request: Request, arrived: int | None = None, db: Session = Depends(get_db)):
    done = None
    if arrived is not None:
        try:
            done = appointments.get_appointment(db, arrived)
        except ClinicError:
            done = None
    return render(request, db, "checkin.html", active="checkin", result=None, done=done)


@router.post("/check-in", include_in_schema=False)
def checkin_lookup(request: Request, token: str = Form(""), db: Session = Depends(get_db)):
    result = checkin.inspect(db, token)
    return render(request, db, "checkin.html", active="checkin", result=result, done=None,
                  entered=checkin.clean_token(token) if result["appointment"] else "")


@router.post("/check-in/arrive", include_in_schema=False)
def checkin_arrive(request: Request, token: str = Form(""), db: Session = Depends(get_db)):
    result = checkin.mark_arrived(db, token)
    if result["state"] == "CHECKED_IN":
        return redirect("/check-in", arrived=result["appointment"].id)
    return render(request, db, "checkin.html", active="checkin", result=result, done=None, entered="")


def _card(request: Request, db: Session, appointment_id: int, error: ClinicError | None = None):
    appointment = appointments.get_appointment(db, appointment_id)
    record = appointment.checkin_token
    context = {"active": "checkin", "appointment": appointment, "record": record,
               "qr_svg": checkin.qr_svg(record) if record else None, "window": checkin.window(appointment)}
    if error is not None:
        context["notice"] = ("error", error.message)
    response = render(request, db, "checkin_qr.html", **context)
    if error is not None:
        response.status_code = error.status_code
    return response


@router.post("/appointments/{appointment_id}/checkin-qr", include_in_schema=False)
def generate_qr(request: Request, appointment_id: int, db: Session = Depends(get_db)):
    try:
        checkin.generate(db, appointment_id)
    except NotFoundError as exc:
        return render(request, db, "checkin.html", active="checkin", result=None, done=None, notice=("error", exc.message))
    except ClinicError as exc:
        return _card(request, db, appointment_id, exc)
    return redirect(f"/appointments/{appointment_id}/checkin-qr")


@router.get("/appointments/{appointment_id}/checkin-qr", include_in_schema=False)
def qr_card(request: Request, appointment_id: int, db: Session = Depends(get_db)):
    """Printable demo QR card for one appointment (staff screen)."""
    try:
        return _card(request, db, appointment_id)
    except ClinicError as exc:
        response = render(request, db, "checkin.html", active="checkin", result=None, done=None, notice=("error", exc.message))
        response.status_code = exc.status_code
        return response


@router.get("/appointments/{appointment_id}/checkin-qr.svg", include_in_schema=False)
def qr_download(appointment_id: int, db: Session = Depends(get_db)):
    record = appointments.get_appointment(db, appointment_id).checkin_token
    if record is None:
        raise NotFoundError("No check-in QR has been generated for this booking.")
    svg = '<?xml version="1.0" encoding="UTF-8"?>\n' + checkin.qr_svg(record, scale=10).replace(
        "<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1
    )
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Content-Disposition": f'attachment; filename="demo-check-in-qr-{appointment_id}.svg"',
                 "Cache-Control": "no-store"},
    )


# --- Staff JSON API -----------------------------------------------------------------
@router.post("/api/appointments/{appointment_id}/checkin-token", status_code=201, tags=["check-in"])
def api_generate(appointment_id: int, db: Session = Depends(get_db)):
    record = checkin.generate(db, appointment_id)
    return {"appointment_id": appointment_id, "token": record.token, "qr_payload": checkin.qr_payload(record)}


@router.post("/api/check-in/lookup", tags=["check-in"])
def api_lookup(body: TokenBody, db: Session = Depends(get_db)):
    """What reception may do with this token. Changes nothing."""
    return _result_out(checkin.inspect(db, body.token))


@router.post("/api/check-in/arrive", tags=["check-in"])
def api_arrive(body: TokenBody, db: Session = Depends(get_db)):
    """Staff-confirmed check-in: CONFIRMED -> ARRIVED. Repeats change nothing."""
    return _result_out(checkin.mark_arrived(db, body.token))
