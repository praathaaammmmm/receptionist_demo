"""Owner analytics page and API: aggregated sample-data figures only."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import analytics
from .pages import render

router = APIRouter()


@router.get("/analytics", include_in_schema=False)
def analytics_page(request: Request, range: str = "all", db: Session = Depends(get_db)):
    data = analytics.compute(db, range)
    return render(request, db, "analytics.html", active="analytics", data=data, ranges=analytics.RANGES)


@router.get("/api/analytics", tags=["analytics"])
def analytics_api(range: str = "all", db: Session = Depends(get_db)):
    """Aggregated counts for `today`, `week` or `all`. Contains no patient or doctor free-text data."""
    return analytics.compute(db, range)
