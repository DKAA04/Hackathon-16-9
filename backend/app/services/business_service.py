"""Query + merged "effective view" logic.

Effective value priority: manual override > trusted enrichment > KBO source.
Provenance is always preserved; nothing overwrites the source record.
"""

import json

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import Business, BusinessOverride, Enrichment
from app.services.evidence import compute_evidence

OVERRIDABLE_FIELDS = {"display_name", "email", "phone", "website", "activity_status", "notes"}


# ---------------------------------------------------------------------------
# Bundles: business + active enrichments + latest overrides, batch-loaded.
# ---------------------------------------------------------------------------

def load_enrichment_map(db: Session, business_ids: list[int]) -> dict[int, dict[str, dict[str, Enrichment]]]:
    result: dict[int, dict[str, dict[str, Enrichment]]] = {bid: {} for bid in business_ids}
    if not business_ids:
        return result
    rows = (
        db.query(Enrichment)
        .filter(Enrichment.business_id.in_(business_ids), Enrichment.status == "active")
        .order_by(Enrichment.retrieved_at)
        .all()
    )
    for row in rows:
        result.setdefault(row.business_id, {}).setdefault(row.provider, {})[row.field_name] = row
    return result


def load_override_map(db: Session, business_ids: list[int]) -> dict[int, dict[str, BusinessOverride]]:
    result: dict[int, dict[str, BusinessOverride]] = {bid: {} for bid in business_ids}
    if not business_ids:
        return result
    rows = (
        db.query(BusinessOverride)
        .filter(BusinessOverride.business_id.in_(business_ids))
        .order_by(BusinessOverride.created_at, BusinessOverride.id)
        .all()
    )
    for row in rows:  # later rows win => latest override per field
        result.setdefault(row.business_id, {})[row.field_name] = row
    return result


def load_parents(db: Session, businesses: list[Business]) -> dict[str, Business]:
    numbers = {b.parent_enterprise_number for b in businesses if b.parent_enterprise_number}
    if not numbers:
        return {}
    rows = db.query(Business).filter(Business.business_number.in_(numbers)).all()
    return {r.business_number: r for r in rows}


# ---------------------------------------------------------------------------
# Effective view
# ---------------------------------------------------------------------------

def _enrichment_value(enrichment_map: dict, provider: str, field: str) -> str | None:
    row = enrichment_map.get(provider, {}).get(field)
    return row.value if row is not None else None


def derive_activity_status(business: Business, enrichment_map: dict, override_map: dict) -> str:
    """ACTIVE / REVIEW / INACTIVE / UNKNOWN — prototype signal, not official."""
    override = override_map.get("activity_status")
    if override is not None and override.new_value:
        return override.new_value.upper()

    google_status = (_enrichment_value(enrichment_map, "google_places", "business_status") or "").upper()
    if google_status == "CLOSED_PERMANENTLY":
        return "REVIEW"

    if business.cessation_date or business.cessation_reason:
        return "REVIEW"
    status = (business.legal_status or "").lower()
    if status == "normale toestand":
        return "ACTIVE"
    if status:
        return "REVIEW"
    return "UNKNOWN"


def build_effective(business: Business, enrichment_map: dict, override_map: dict) -> dict:
    def effective(field: str, enrichment_candidates: list[tuple[str, str]], source_value):
        override = override_map.get(field)
        if override is not None:
            return override.new_value, "manual_override"
        for provider, enr_field in enrichment_candidates:
            value = _enrichment_value(enrichment_map, provider, enr_field)
            if value:
                return value, provider
        return source_value, "kbo" if source_value else None

    display_name, display_src = effective("display_name", [], business.display_name)
    email, email_src = effective("email", [("website", "email")], business.email)
    phone, phone_src = effective("phone", [("website", "phone"), ("google_places", "phone")], business.phone)
    website, website_src = effective(
        "website", [("website", "website"), ("google_places", "website")], None
    )
    activity_status = derive_activity_status(business, enrichment_map, override_map)

    notes_override = override_map.get("notes")

    return {
        "display_name": display_name,
        "display_name_source": display_src,
        "email": email,
        "email_source": email_src if email else None,
        "phone": phone,
        "phone_source": phone_src if phone else None,
        "website": website,
        "website_source": website_src if website else None,
        "activity_status": activity_status,
        "notes": notes_override.new_value if notes_override else None,
    }


def google_status_of(enrichment_map: dict) -> str | None:
    value = _enrichment_value(enrichment_map, "google_places", "business_status")
    return value.upper() if value else None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def format_address(business: Business) -> str | None:
    line = " ".join(x for x in [business.kbo_street, business.kbo_house_number] if x)
    if business.kbo_bus_number:
        line = f"{line} bus {business.kbo_bus_number}"
    city = " ".join(x for x in [business.kbo_postcode, business.kbo_municipality] if x)
    full = ", ".join(x for x in [line, city] if x)
    return full or None


def serialize_business(business: Business) -> dict:
    return {
        "id": business.business_number,
        "business_number": business.business_number,
        "parent_enterprise_number": business.parent_enterprise_number,
        "record_type": business.record_type,
        "legal_name": business.legal_name,
        "commercial_name": business.commercial_name,
        "short_name": business.short_name,
        "display_name": business.display_name,
        "business_type": business.business_type,
        "legal_form": business.legal_form,
        "legal_status": business.legal_status,
        "address": {
            "street": business.kbo_street,
            "house_number": business.kbo_house_number,
            "bus_number": business.kbo_bus_number,
            "postcode": business.kbo_postcode,
            "municipality": business.kbo_municipality,
            "formatted": format_address(business),
        },
        "address_register": {
            "street": business.address_register_street,
            "house_number": business.address_register_house_number,
            "bus_number": business.address_register_bus_number,
            "postcode": business.address_register_postcode,
        },
        "phone": business.phone,
        "email": business.email,
        "nace": {
            "vat_code": business.nace_vat_code,
            "vat_description": business.nace_vat_description,
            "rsz_code": business.nace_rsz_code,
            "rsz_description": business.nace_rsz_description,
        },
        "employee_class": business.employee_class,
        "registration_date": business.registration_date.isoformat() if business.registration_date else None,
        "start_date": business.start_date.isoformat() if business.start_date else None,
        "cessation_date": business.cessation_date.isoformat() if business.cessation_date else None,
        "cessation_reason": business.cessation_reason,
        "address_deregistration_date": (
            business.address_deregistration_date.isoformat() if business.address_deregistration_date else None
        ),
        "address_deregistration_reason": business.address_deregistration_reason,
        "annual_accounts_url": business.annual_accounts_url,
        "longitude": business.longitude,
        "latitude": business.latitude,
        "source_dataset": business.source_dataset,
        "source_snapshot_date": business.source_snapshot_date,
    }


def serialize_enrichment(row: Enrichment) -> dict:
    return {
        "id": row.id,
        "provider": row.provider,
        "field_name": row.field_name,
        "value": row.value,
        "source_url": row.source_url,
        "provider_external_id": row.provider_external_id,
        "confidence": row.confidence,
        "metadata": json.loads(row.metadata_json) if row.metadata_json else None,
        "retrieved_at": row.retrieved_at.isoformat() if row.retrieved_at else None,
        "status": row.status,
    }


def serialize_override(row: BusinessOverride) -> dict:
    return {
        "id": row.id,
        "field_name": row.field_name,
        "old_effective_value": row.old_effective_value,
        "new_value": row.new_value,
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def build_summary(business: Business, parent: Business | None, enrichment_map: dict, override_map: dict) -> dict:
    verdict = compute_evidence(business, parent, enrichment_map, override_map)
    effective = build_effective(business, enrichment_map, override_map)
    return {
        "id": business.business_number,
        "business_number": business.business_number,
        "record_type": business.record_type,
        "parent_enterprise_number": business.parent_enterprise_number,
        "display_name": effective["display_name"],
        "legal_name": business.legal_name,
        "legal_form": business.legal_form,
        "legal_status": business.legal_status,
        "address": format_address(business),
        "street": business.kbo_street,
        "postcode": business.kbo_postcode,
        "municipality": business.kbo_municipality,
        "longitude": business.longitude,
        "latitude": business.latitude,
        "effective": effective,
        "google_status": google_status_of(enrichment_map),
        "has_email": bool(effective["email"]),
        "has_phone": bool(effective["phone"]),
        "has_website": bool(effective["website"]),
        "confidence_score": verdict["confidence_score"],
        "confidence_level": verdict["confidence_level"],
        "review_required": verdict["review_required"],
    }


def build_detail(db: Session, business: Business) -> dict:
    enrichment_map = load_enrichment_map(db, [business.id]).get(business.id, {})
    override_map = load_override_map(db, [business.id]).get(business.id, {})
    parent = None
    if business.parent_enterprise_number:
        parent = (
            db.query(Business)
            .filter(Business.business_number == business.parent_enterprise_number)
            .first()
        )

    verdict = compute_evidence(business, parent, enrichment_map, override_map)
    effective = build_effective(business, enrichment_map, override_map)

    google_rows = enrichment_map.get("google_places", {})
    website_rows = enrichment_map.get("website", {})

    return {
        "business": serialize_business(business),
        "parent_enterprise": serialize_business(parent) if parent else None,
        "sources": {
            "kbo": json.loads(business.raw_json) if business.raw_json else None,
            "google_places": {f: serialize_enrichment(r) for f, r in google_rows.items()} or None,
            "website": {f: serialize_enrichment(r) for f, r in website_rows.items()} or None,
            "manual_override": {f: serialize_override(r) for f, r in override_map.items()} or None,
        },
        "effective": effective,
        "evidence": verdict["evidence"],
        "confidence_score": verdict["confidence_score"],
        "confidence_level": verdict["confidence_level"],
        "review_required": verdict["review_required"],
    }


# ---------------------------------------------------------------------------
# Query with filters
# ---------------------------------------------------------------------------

def query_businesses(db: Session, filters: dict) -> dict:
    """SQL filters on source columns first, then computed filters (effective
    contact data, google status, confidence) in Python — fine at this scale."""
    query = db.query(Business)

    text = filters.get("query")
    if text:
        like = f"%{text}%"
        query = query.filter(or_(
            Business.display_name.ilike(like),
            Business.legal_name.ilike(like),
            Business.commercial_name.ilike(like),
            Business.search_name.ilike(like),
            Business.business_number.like(f"%{text.replace('.', '').replace(' ', '')}%"),
            Business.kbo_street.ilike(like),
            Business.kbo_municipality.ilike(like),
        ))
    if filters.get("street"):
        query = query.filter(Business.kbo_street.ilike(f"%{filters['street']}%"))
    if filters.get("postcode"):
        query = query.filter(Business.kbo_postcode == filters["postcode"])
    if filters.get("municipality"):
        query = query.filter(Business.kbo_municipality.ilike(filters["municipality"]))
    if filters.get("record_type"):
        query = query.filter(Business.record_type == filters["record_type"].upper())
    if filters.get("legal_status"):
        query = query.filter(Business.legal_status.ilike(f"%{filters['legal_status']}%"))

    rows = query.order_by(Business.display_name).all()

    ids = [r.id for r in rows]
    enrichment_maps = load_enrichment_map(db, ids)
    override_maps = load_override_map(db, ids)
    parents = load_parents(db, rows)

    summaries = []
    for row in rows:
        parent = parents.get(row.parent_enterprise_number) if row.parent_enterprise_number else None
        summaries.append(build_summary(row, parent, enrichment_maps.get(row.id, {}), override_maps.get(row.id, {})))

    def keep(item: dict) -> bool:
        for flag in ("has_email", "has_phone", "has_website", "review_required"):
            wanted = filters.get(flag)
            if wanted is not None and item[flag] != wanted:
                return False
        wanted_status = filters.get("google_status")
        if wanted_status:
            wanted_status = wanted_status.upper()
            actual = item["google_status"]
            if wanted_status == "NOT_CHECKED":
                if actual is not None:
                    return False
            elif actual != wanted_status:
                return False
        cmin = filters.get("confidence_min")
        if cmin is not None and item["confidence_score"] < cmin:
            return False
        cmax = filters.get("confidence_max")
        if cmax is not None and item["confidence_score"] > cmax:
            return False
        return True

    filtered = [s for s in summaries if keep(s)]

    limit = min(int(filters.get("limit") or 50), 500)
    offset = max(int(filters.get("offset") or 0), 0)

    return {
        "results": filtered[offset:offset + limit],
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
    }


def get_business_by_public_id(db: Session, public_id: str) -> Business | None:
    return db.query(Business).filter(Business.business_number == public_id.strip()).first()


def apply_overrides(db: Session, business: Business, changes: dict, note: str | None) -> list[BusinessOverride]:
    """Record manual corrections as override rows. Source columns untouched."""
    enrichment_map = load_enrichment_map(db, [business.id]).get(business.id, {})
    override_map = load_override_map(db, [business.id]).get(business.id, {})
    current = build_effective(business, enrichment_map, override_map)

    created = []
    for field, new_value in changes.items():
        if field not in OVERRIDABLE_FIELDS:
            continue
        row = BusinessOverride(
            business_id=business.id,
            field_name=field,
            old_effective_value=current.get(field),
            new_value=new_value,
            note=note,
        )
        db.add(row)
        created.append(row)
    db.commit()
    return created
