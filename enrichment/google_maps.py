"""Google Maps lookup through the official Places API (New) Text Search.

Needs GOOGLE_MAPS_API_KEY (a Google Cloud project with billing and "Places API (New)" enabled).
Requesting phone/website fields is billed at a higher tier; check current pricing and free quota.
Google's terms restrict storing Places content, so results are only kept in memory for this run;
show "Google Maps" plus the googleMapsUri link wherever the data is displayed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from . import matching as m
from .extract import phone_from_string
from .models import EnrichTarget, SourceRun
from .net import Fetcher

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.addressComponents",
    "places.location",
    "places.businessStatus",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.websiteUri",
    "places.googleMapsUri",
])
STATUS_TEXT = {
    "OPERATIONAL": ("google_operational", "Actief volgens Google Maps"),
    "CLOSED_TEMPORARILY": ("google_closed_temporarily", "Tijdelijk gesloten volgens Google Maps"),
    "CLOSED_PERMANENTLY": ("google_closed_permanently", "Definitief gesloten volgens Google Maps"),
}


@dataclass
class PlaceMatch:
    place_id: str
    name: str
    address: str
    url: str
    score: int
    reason: str
    phones: list[tuple[str, str]] = field(default_factory=list)
    website: str | None = None
    status: tuple[str, str] | None = None


def _component(place: dict, kind: str) -> str | None:
    for comp in place.get("addressComponents", []):
        if kind in comp.get("types", []):
            return comp.get("longText") or comp.get("shortText")
    return None


def lookup(target: EnrichTarget, fetcher: Fetcher, api_key: str) -> tuple[PlaceMatch | None, SourceRun]:
    query = f"{target.display_name}, {target.address}".strip(", ")
    body: dict = {"textQuery": query, "languageCode": "nl", "regionCode": "BE"}
    if target.lat is not None and target.lon is not None:
        body["locationBias"] = {
            "circle": {"center": {"latitude": target.lat, "longitude": target.lon}, "radius": 500.0}
        }
    headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELD_MASK}
    try:
        resp = fetcher.post(PLACES_URL, json=body, headers=headers, timeout=20)
    except httpx.HTTPError as exc:
        return None, SourceRun("google_maps", "fout", type(exc).__name__)
    if resp.status_code != 200:
        try:
            message = resp.json().get("error", {}).get("message", "")
        except ValueError:
            message = resp.text[:200]
        return None, SourceRun("google_maps", "fout", f"HTTP {resp.status_code}: {message[:200]}")

    places = resp.json().get("places", [])
    best: PlaceMatch | None = None
    for place in places:
        name = (place.get("displayName") or {}).get("text", "")
        location = place.get("location") or {}
        similarity = m.best_similarity(target.names, [name])
        distance = m.haversine_m(target.lat, target.lon, location.get("latitude"), location.get("longitude"))
        same_street = m.street_similarity(_component(place, "route"), target.street) >= 90
        same_number = m.house_match(_component(place, "street_number"), target.house_number)
        score, reason = m.place_match_score(similarity, distance, same_street, same_number)
        if not score or (best and score <= best.score):
            continue
        best = PlaceMatch(
            place_id=place.get("id", ""),
            name=name,
            address=place.get("formattedAddress", ""),
            url=place.get("googleMapsUri") or f"https://www.google.com/maps/place/?q=place_id:{place.get('id', '')}",
            score=score,
            reason=reason,
            website=place.get("websiteUri"),
            status=STATUS_TEXT.get(place.get("businessStatus", "")),
        )
        for key in ("internationalPhoneNumber", "nationalPhoneNumber"):
            if (phone := phone_from_string(place.get(key))) and phone not in best.phones:
                best.phones.append(phone)

    if best is None:
        return None, SourceRun("google_maps", "geen_resultaat", f"{len(places)} resultaten, geen match voor '{query}'")
    return best, SourceRun("google_maps", "ok", f"{best.name}, {best.address}: {best.reason}")
