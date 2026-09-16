from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.business_service import get_business_by_public_id
from app.services.enrichment_service import enrich_business, enrich_google, enrich_website

router = APIRouter(prefix="/api", tags=["enrichment"])

BATCH_CAP = 20


class BatchEnrichRequest(BaseModel):
    business_ids: list[str] = Field(min_length=1, max_length=BATCH_CAP)


def _require_business(db: Session, business_id: str):
    business = get_business_by_public_id(db, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return business


@router.post("/businesses/{business_id}/enrich/google")
def enrich_business_google(business_id: str, db: Session = Depends(get_db)):
    business = _require_business(db, business_id)
    return enrich_google(db, business)


@router.post("/businesses/{business_id}/enrich/website")
def enrich_business_website(business_id: str, db: Session = Depends(get_db)):
    business = _require_business(db, business_id)
    return enrich_website(db, business)


@router.post("/businesses/{business_id}/enrich")
def enrich_business_all(business_id: str, db: Session = Depends(get_db)):
    business = _require_business(db, business_id)
    return enrich_business(db, business)


@router.post("/enrich")
def enrich_batch(body: BatchEnrichRequest, db: Session = Depends(get_db)):
    """Batch enrichment, capped — never sweeps the whole dataset."""
    results = []
    for business_id in body.business_ids[:BATCH_CAP]:
        business = get_business_by_public_id(db, business_id)
        if business is None:
            results.append({"business_id": business_id, "error": "not found"})
            continue
        results.append(enrich_business(db, business))
    return {"count": len(results), "results": results}
