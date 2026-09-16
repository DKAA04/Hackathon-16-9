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

    proof = None
    if result.get("match") == "address_only":
        # Same address, different name: only accept it when the website shows this business.
        numbers = [n for n in (business.parent_enterprise_number, business.business_number) if n]
        proof = (website_enrichment.identity_proof(result["website"], numbers, business.kbo_street,
                                                   business.kbo_house_number)
                 if result.get("website") else None)
        if proof is None:
            result = {
                "status": "UNKNOWN",
                "reason": f"andere naam ({result.get('matched_name')}) op hetzelfde adres, niet bevestigd",
                "other_business": {
                    "name": result.get("matched_name"),
                    "address": result.get("formatted_address"),
                    "google_maps_url": result.get("google_maps_url"),
                    "same_address": True,
                },
                "checked_at": result.get("checked_at"),
            }
            status = "UNKNOWN"
    if status == "UNKNOWN":
        return _store_rejected(db, business, result)

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
        "name_score": result.get("name_score"),
        "reason": proof or result.get("reason") or "naam komt overeen",
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


def _store_rejected(db: Session, business: Business, result: dict) -> dict:
    """No reliable Google match: store UNKNOWN (never closed) plus what Google does show there.
    Website rows derived from an earlier, rejected Google website are superseded too."""
    other = result.get("other_business") or {}
    fields = {"business_status": "UNKNOWN"}
    if other.get("name"):
        key = "other_business_at_address" if other.get("same_address") else "other_business_nearby"
        fields[key] = " · ".join(x for x in (other.get("name"), other.get("address")) if x)
    _store_rows(db, business, "google_places", fields, source_url=other.get("google_maps_url"),
                metadata={"reason": result.get("reason"), "checked_at": result.get("checked_at")})
    override_map = load_override_map(db, [business.id]).get(business.id, {})
    if "website" not in override_map:
        db.query(Enrichment).filter(
            Enrichment.business_id == business.id,
            Enrichment.provider == "website",
            Enrichment.status == "active",
        ).update({"status": "superseded"})
        db.commit()
    return {
        "provider": "google_places",
        "status": "ok",
        "google_status": "UNKNOWN",
        "match_confidence": None,
        "reason": result.get("reason"),
        "other_business": other.get("name"),
    }


def revalidate_google_matches(db: Session) -> dict:
    """Re-check stored Google matches with the current (stricter) rules, without new API calls."""
    rows = db.query(Enrichment).filter(
        Enrichment.provider == "google_places",
        Enrichment.field_name == "matched_name",
        Enrichment.status == "active",
    ).all()
    checked = rejected = confirmed = 0
    for row in rows:
        business = row.business
        checked += 1
        if google_places.name_score(business, row.value) >= google_places.NAME_MATCH:
            continue
        active = {
            r.field_name: r.value
            for r in db.query(Enrichment).filter(
                Enrichment.business_id == business.id,
                Enrichment.provider == "google_places",
                Enrichment.status == "active",
            )
        }
        at_address = google_places.same_address(business, active.get("formatted_address"))
        if at_address and active.get("website"):
            numbers = [n for n in (business.parent_enterprise_number, business.business_number) if n]
            if website_enrichment.identity_proof(active["website"], numbers, business.kbo_street,
                                                 business.kbo_house_number):
                confirmed += 1
                continue
        _store_rejected(db, business, {
            "reason": f"herbekeken: andere naam ({row.value})",
            "other_business": {
                "name": row.value,
                "address": active.get("formatted_address"),
                "google_maps_url": active.get("google_maps_url"),
                "same_address": at_address,
            },
            "checked_at": datetime.utcnow().isoformat(),
        })
        rejected += 1
    return {"checked": checked, "rejected": rejected, "confirmed_by_website": confirmed}


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
