"""Backward-compatible endpoints for the existing frontend starter:
POST /api/search (Result shape) and POST /api/ingest (now runs the DB import).
New frontend work should use /api/businesses and /api/map instead."""

import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.business_service import query_businesses
from app.services.kbo_import import run_import

router = APIRouter(prefix="/api", tags=["legacy"])


class Evidence(BaseModel):
    label: str
    value: str
    source: str
    status: str = "support"


class Result(BaseModel):
    id: str
    title: str
    subtitle: str | None = None
    status: str
    confidence: str
    confidence_score: int = Field(ge=0, le=100)
    source_count: int
    summary: str
    tags: list[str]
    evidence: list[Evidence]


class SearchRequest(BaseModel):
    query: str = ""
    demo_mode: bool = True


def _summary_to_result(item: dict) -> Result:
    level = item["confidence_level"].lower()
    evidence = [
        Evidence(label="Business number", value=item["business_number"], source="KBO/VKBO snapshot"),
    ]
    if item["address"]:
        evidence.append(Evidence(label="Address", value=item["address"], source="KBO/VKBO snapshot"))
    if item["parent_enterprise_number"]:
        evidence.append(Evidence(
            label="Parent enterprise", value=item["parent_enterprise_number"], source="KBO/VKBO snapshot"))
    if item["google_status"]:
        evidence.append(Evidence(label="Google status", value=item["google_status"], source="Google Places"))

    tags = [t for t in [item["record_type"], item["municipality"], item["street"]] if t]
    return Result(
        id=item["id"],
        title=item["display_name"] or item["business_number"],
        subtitle=item["address"],
        status=item["effective"]["activity_status"],
        confidence=level,
        confidence_score=item["confidence_score"],
        source_count=1 + bool(item["google_status"]) + bool(item["has_website"]),
        summary="Normalized KBO snapshot record with evidence-based review signal.",
        tags=tags,
        evidence=evidence,
    )


@router.post("/search")
def search(request: SearchRequest, db: Session = Depends(get_db)):
    started = time.perf_counter()
    q = request.query.strip()
    result = query_businesses(db, {"query": q or None, "limit": 30, "offset": 0})
    results = [_summary_to_result(item) for item in result["results"]]
    return {
        "query": q,
        "interpreted_as": "Search normalized CivicLens business records",
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "total": result["total"],
        "results": results,
        "system_notes": [f"{result['total']} matching records in local database"],
    }


@router.post("/ingest")
def ingest(db: Session = Depends(get_db)):
    """Legacy alias: now performs the idempotent KBO snapshot import."""
    return run_import(db)
