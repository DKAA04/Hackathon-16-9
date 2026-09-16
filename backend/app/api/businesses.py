from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.services.sectors import SECTORS, sector_keys
from app.db.database import get_db
from app.db.models import Business, BusinessOverride, Enrichment
from app.services.business_service import (
    apply_overrides,
    build_detail,
    get_business_by_public_id,
    query_businesses,
    serialize_enrichment,
    serialize_override,
)

router = APIRouter(prefix="/api", tags=["businesses"])


class OverrideRequest(BaseModel):
    display_name: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    activity_status: str | None = None
    notes: str | None = None
    note: str | None = None  # why the correction was made


@router.get("/businesses")
def list_businesses(
    query: str | None = None,
    sector: str | None = Query(default=None, pattern="^(bakkerij|horeca|zorg|kapper|bouw|auto|winkel|advies)$"),
    street: str | None = None,
    postcode: str | None = None,
    municipality: str | None = None,
    record_type: str | None = Query(default=None, pattern="(?i)^(ENTERPRISE|ESTABLISHMENT)$"),
    legal_status: str | None = None,
    has_email: bool | None = None,
    has_phone: bool | None = None,
    has_website: bool | None = None,
    google_status: str | None = None,
    review_required: bool | None = None,
    confidence_min: int | None = Query(default=None, ge=0, le=100),
    confidence_max: int | None = Query(default=None, ge=0, le=100),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return query_businesses(db, {
        "query": query,
        "sector": sector,
        "street": street,
        "postcode": postcode,
        "municipality": municipality,
        "record_type": record_type,
        "legal_status": legal_status,
        "has_email": has_email,
        "has_phone": has_phone,
        "has_website": has_website,
        "google_status": google_status,
        "review_required": review_required,
        "confidence_min": confidence_min,
        "confidence_max": confidence_max,
        "limit": limit,
        "offset": offset,
    })


@router.get("/businesses/{business_id}")
def business_detail(business_id: str, db: Session = Depends(get_db)):
    business = get_business_by_public_id(db, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return build_detail(db, business)


@router.get("/businesses/{business_id}/history")
def business_history(business_id: str, db: Session = Depends(get_db)):
    business = get_business_by_public_id(db, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    enrichments = (
        db.query(Enrichment)
        .filter(Enrichment.business_id == business.id)
        .order_by(Enrichment.retrieved_at.desc(), Enrichment.id.desc())
        .all()
    )
    overrides = (
        db.query(BusinessOverride)
        .filter(BusinessOverride.business_id == business.id)
        .order_by(BusinessOverride.created_at.desc(), BusinessOverride.id.desc())
        .all()
    )
    return {
        "business_id": business.business_number,
        "enrichments": [serialize_enrichment(e) for e in enrichments],
        "overrides": [serialize_override(o) for o in overrides],
    }


@router.patch("/businesses/{business_id}")
def override_business(business_id: str, body: OverrideRequest, db: Session = Depends(get_db)):
    business = get_business_by_public_id(db, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    changes = {
        field: value
        for field, value in body.model_dump(exclude={"note"}).items()
        if value is not None
    }
    if not changes:
        raise HTTPException(status_code=400, detail="No override fields provided")

    created = apply_overrides(db, business, changes, body.note)
    return {
        "business_id": business.business_number,
        "overrides_created": [serialize_override(o) for o in created],
        "detail": build_detail(db, business),
    }


@router.get("/filters")
def filter_values(db: Session = Depends(get_db)):
    def counts(column):
        rows = (
            db.query(column, func.count(Business.id))
            .filter(column.isnot(None))
            .group_by(column)
            .order_by(func.count(Business.id).desc())
            .all()
        )
        return [{"value": value, "count": count} for value, count in rows]

    google_rows = (
        db.query(Enrichment.value, func.count(Enrichment.id))
        .filter(Enrichment.provider == "google_places",
                Enrichment.field_name == "business_status",
                Enrichment.status == "active")
        .group_by(Enrichment.value)
        .all()
    )

    return {
        "streets": counts(Business.kbo_street),
        "municipalities": counts(Business.kbo_municipality),
        "postcodes": counts(Business.kbo_postcode),
        "record_types": counts(Business.record_type),
        "legal_statuses": counts(Business.legal_status),
        "legal_forms": counts(Business.legal_form),
        "google_statuses": [{"value": v, "count": c} for v, c in google_rows],
        "sectors": sector_counts(db.query(Business).all()),
        "total_businesses": db.query(Business).count(),
    }


def sector_counts(businesses) -> list[dict]:
    counts = {sector.key: 0 for sector in SECTORS}
    for business in businesses:
        for key in sector_keys(business):
            counts[key] += 1
    return [{"value": s.key, "label": s.label, "count": counts[s.key]} for s in SECTORS]
