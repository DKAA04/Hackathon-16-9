"""Persist enrichment results. Old rows are superseded (kept for history),
never deleted; KBO source columns are never touched."""

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import Business, Enrichment
from app.services import google_places, website_enrichment
from app.services.business_service import build_effective, load_enrichment_map, load_override_map


def _store_rows(
    db: Session,
    business: Business,
    provider: str,
    fields: dict[str, str | None],
    *,
    source_url: str | None = None,
    external_id: str | None = None,
    confidence: float | None = None,
    metadata: dict | None = None,
) -> list[Enrichment]:
    # Supersede previous active rows for this provider (history preserved).
    db.query(Enrichment).filter(
        Enrichment.business_id == business.id,
        Enrichment.provider == provider,
        Enrichment.status == "active",
    ).update({"status": "superseded"})

    rows = []
    for field, value in fields.items():
        if value is None:
            continue
        row = Enrichment(
            business_id=business.id,
            provider=provider,
            field_name=field,
            value=str(value),
            source_url=source_url,
            provider_external_id=external_id,
            confidence=confidence,
            metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
            retrieved_at=datetime.utcnow(),
            status="active",
        )
        db.add(row)
        rows.append(row)
    db.commit()
    return rows


def enrich_google(db: Session, business: Business) -> dict:
    result = google_places.lookup(business)
    status = result.get("status")

    if status == "NOT_CONFIGURED":
        return {"provider": "google_places", "status": "skipped", "reason": "GOOGLE_NOT_CONFIGURED"}
    if status == "ERROR":
        # Record the failure, keep the record usable.
        _store_rows(db, business, "google_places", {"business_status": "UNKNOWN"},
                    metadata={"error": result.get("error")})
        return {"provider": "google_places", "status": "error", "error": result.get("error")}

    fields = {
        "business_status": status,  # UNKNOWN when no confident match — never CLOSED
        "matched_name": result.get("matched_name"),
        "formatted_address": result.get("formatted_address"),
        "google_maps_url": result.get("google_maps_url"),
        "website": result.get("website"),
        "phone": result.get("phone"),
        "latitude": result.get("latitude"),
        "longitude": result.get("longitude"),
    }
    metadata = {
        "match_confidence": result.get("match_confidence"),
        "reason": result.get("reason"),
        "checked_at": result.get("checked_at"),
    }
    rows = _store_rows(
        db, business, "google_places", fields,
        source_url=result.get("google_maps_url"),
        external_id=result.get("place_id"),
        confidence=result.get("match_confidence"),
        metadata=metadata,
    )
    return {
        "provider": "google_places",
        "status": "ok",
        "google_status": status,
        "match_confidence": result.get("match_confidence"),
        "fields_stored": len(rows),
    }


def enrich_website(db: Session, business: Business) -> dict:
    # Website candidates: manual override > website/google enrichment. We do
    # not guess URLs from names.
    enrichment_map = load_enrichment_map(db, [business.id]).get(business.id, {})
    override_map = load_override_map(db, [business.id]).get(business.id, {})
    effective = build_effective(business, enrichment_map, override_map)
    website_url = effective.get("website")

    if not website_url:
        return {"provider": "website", "status": "skipped", "reason": "NO_KNOWN_WEBSITE"}

    result = website_enrichment.enrich_from_website(website_url)
    if result["status"] != "OK":
        return {"provider": "website", "status": "error", "error": result.get("error")}

    rows = _store_rows(
        db, business, "website", result["fields"],
        source_url=result["source_url"],
        confidence=0.8,  # authoritative for its own site, still below manual override
    )
    return {
        "provider": "website",
        "status": "ok",
        "source_url": result["source_url"],
        "fields_stored": len(rows),
        "emails_found": result["emails_found"],
    }


def enrich_business(db: Session, business: Business) -> dict:
    """Run all safe configured enrichers; failures degrade gracefully."""
    results = [enrich_google(db, business)]
    results.append(enrich_website(db, business))
    return {"business_id": business.business_number, "results": results}
