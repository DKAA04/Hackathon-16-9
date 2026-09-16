"""Google Places API (New) enrichment adapter.

External evidence only — never overwrites KBO source data.
CRITICAL: no Google result != closed. No confident match => status UNKNOWN.
"""

import logging
import math
from datetime import datetime

import httpx
from rapidfuzz import fuzz

from app.config import settings
from app.db.models import Business

logger = logging.getLogger(__name__)

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.businessStatus",
    "places.googleMapsUri",
    "places.websiteUri",
    "places.internationalPhoneNumber",
    "places.location",
    "places.postalAddress",
])

MATCH_THRESHOLD = 0.55  # conservative: below this we report UNKNOWN, not the candidate


def _search_text(query: str, api_key: str) -> list[dict]:
    """Raw Places text search. Isolated so tests can monkeypatch it."""
    response = httpx.post(
        PLACES_SEARCH_URL,
        json={"textQuery": query, "maxResultCount": 5, "languageCode": "nl", "regionCode": "BE"},
        headers={
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json().get("places", [])


def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _score_candidate(business: Business, place: dict) -> float:
    """Conservative similarity 0..1 from name, address parts and distance."""
    target_names = [n for n in (business.commercial_name, business.legal_name, business.search_name) if n]
    place_name = (place.get("displayName") or {}).get("text") or ""
    name_score = max((fuzz.WRatio(n.lower(), place_name.lower()) for n in target_names), default=0) / 100.0

    address = (place.get("formattedAddress") or "").lower()
    street_ok = bool(business.kbo_street and business.kbo_street.lower() in address)
    number_ok = bool(business.kbo_house_number and business.kbo_house_number.lower() in address)
    postcode_ok = bool(business.kbo_postcode and business.kbo_postcode in address)
    municipality_ok = bool(business.kbo_municipality and business.kbo_municipality.lower() in address)
    address_score = (
        0.4 * street_ok + 0.2 * number_ok + 0.2 * postcode_ok + 0.2 * municipality_ok
    )

    distance_score = 0.0
    location = place.get("location") or {}
    if business.latitude and business.longitude and location.get("latitude"):
        meters = _haversine_m(
            business.latitude, business.longitude,
            location["latitude"], location["longitude"],
        )
        distance_score = 1.0 if meters <= 150 else 0.5 if meters <= 500 else 0.0

    return round(0.5 * name_score + 0.35 * address_score + 0.15 * distance_score, 3)


def lookup(business: Business) -> dict:
    """Return a normalized Google Places result for one business.

    Shapes:
      {"status": "NOT_CONFIGURED"}
      {"status": "ERROR", "error": "..."}
      {"status": "UNKNOWN", ...}                    # no confident match
      {"status": "OPERATIONAL"|"CLOSED_*"|..., ...} # confident match
    """
    if not settings.google_places_configured:
        return {"status": "NOT_CONFIGURED"}

    name = business.commercial_name or business.legal_name or business.search_name
    if not name:
        return {"status": "UNKNOWN", "reason": "no usable name in source record"}

    parts = [name, business.kbo_street, business.kbo_house_number,
             business.kbo_postcode, business.kbo_municipality, "Belgium"]
    query = " ".join(p for p in parts if p)

    try:
        places = _search_text(query, settings.google_maps_api_key)
    except Exception as exc:
        logger.warning("Google Places lookup failed for %s: %s", business.business_number, exc)
        return {"status": "ERROR", "error": str(exc)}

    if not places:
        return {"status": "UNKNOWN", "reason": "no Google Places result", "checked_at": datetime.utcnow().isoformat()}

    scored = sorted(((_score_candidate(business, p), p) for p in places), key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]

    if best_score < MATCH_THRESHOLD:
        return {
            "status": "UNKNOWN",
            "reason": f"best candidate below match threshold ({best_score} < {MATCH_THRESHOLD})",
            "checked_at": datetime.utcnow().isoformat(),
        }

    location = best.get("location") or {}
    return {
        "status": (best.get("businessStatus") or "UNKNOWN").upper(),
        "place_id": best.get("id"),
        "matched_name": (best.get("displayName") or {}).get("text"),
        "formatted_address": best.get("formattedAddress"),
        "google_maps_url": best.get("googleMapsUri"),
        "website": best.get("websiteUri"),
        "phone": best.get("internationalPhoneNumber"),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "match_confidence": best_score,
        "checked_at": datetime.utcnow().isoformat(),
    }
