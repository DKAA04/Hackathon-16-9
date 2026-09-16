"""Turn enrichment results into rows for the backend's `enrichments` table.

    from enrichment import Enricher
    from enrichment.backend_adapter import enrichment_rows, target_from_business

    enricher = Enricher()                                  # create once, reuse
    target = target_from_business(business)                # ORM object or dict with backend field names
    result = enricher.enrich(target)
    for row in enrichment_rows(result, business_id=business.id):
        session.add(Enrichment(**row))                     # provider, field_name, value, source_url, ...

KBO observations are skipped: that data is already the source record. `metadata_json` is a JSON
string (display value, combined confidence, level, scope, reason, snippet).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .models import EnrichmentResult, EnrichTarget, Finding, Observation
from .records import target_from_row

PROVIDER = {"website": "website", "web_search": "website", "osm": "osm", "google_maps": "google_places"}

# signal code -> (field_name, value)
SIGNAL_FIELD = {
    "google_operational": ("business_status", "OPERATIONAL"),
    "google_closed_temporarily": ("business_status", "CLOSED_TEMPORARILY"),
    "google_closed_permanently": ("business_status", "CLOSED_PERMANENTLY"),
    "osm_disused": ("activity_signal", "DISUSED"),
    "osm_opening_hours": ("opening_hours", None),
    "website_unreachable": ("website_status", "UNREACHABLE"),
}

BUSINESS_FIELDS = (
    "business_number", "parent_enterprise_number", "record_type", "legal_name", "commercial_name", "short_name",
    "kbo_street", "kbo_house_number", "kbo_postcode", "kbo_municipality", "address_register_street",
    "address_register_house_number", "address_register_postcode", "phone", "email", "website",
    "latitude", "longitude", "legal_status", "nace_rsz_description", "nace_vat_description",
)


def target_from_business(business: Any) -> EnrichTarget | None:
    """Accepts a dict or an object (e.g. a SQLAlchemy model) with the backend's field names."""
    if isinstance(business, dict):
        row = dict(business)
    else:
        row = {name: getattr(business, name) for name in BUSINESS_FIELDS if hasattr(business, name)}
    return target_from_row(row)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _row(business_id: Any, provider: str, field_name: str, value: str, obs: Observation,
         finding: Finding | None, external_id: str | None = None) -> dict[str, Any]:
    meta = {"reason": obs.reason, "snippet": obs.snippet}
    if finding is not None:
        meta.update(display=finding.display, combined_confidence=finding.confidence, level=finding.level,
                    scope=finding.scope, sources=finding.sources)
    return {
        "business_id": business_id,
        "provider": provider,
        "field_name": field_name,
        "value": value,
        "source_url": obs.url,
        "provider_external_id": external_id,
        "confidence": obs.confidence,
        "metadata_json": json.dumps(meta, ensure_ascii=False),
        "retrieved_at": _parse_time(obs.retrieved_at),
        "status": "proposed",
    }


def _external_id(obs: Observation) -> str | None:
    if obs.source == "osm" and obs.url and "openstreetmap.org/" in obs.url:
        return obs.url.split("openstreetmap.org/", 1)[1]  # e.g. node/11537721122
    return None


def enrichment_rows(result: EnrichmentResult, business_id: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field_name, findings in (("phone", result.phones), ("email", result.emails), ("website", result.websites)):
        for finding in findings:
            best_per_source: dict[str, Observation] = {}
            for obs in finding.observations:
                if obs.source == "kbo":
                    continue
                current = best_per_source.get(obs.source)
                if current is None or obs.confidence > current.confidence:
                    best_per_source[obs.source] = obs
            for source, obs in best_per_source.items():
                rows.append(_row(business_id, PROVIDER.get(source, source), field_name, finding.value, obs,
                                 finding, _external_id(obs)))
    for signal in result.signals:
        field_name, value = SIGNAL_FIELD.get(signal.value, ("signal", signal.value))
        obs = signal.observations[0]
        rows.append(_row(business_id, PROVIDER.get(obs.source, obs.source), field_name,
                         value if value is not None else signal.display, obs, None, _external_id(obs)))
    return rows
