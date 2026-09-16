"""OpenStreetMap lookup through the Overpass API: free, no key (data licence ODbL)."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

from . import matching as m
from .extract import clean_email, phone_from_string
from .models import EnrichTarget, SourceRun
from .net import Fetcher

OVERPASS_URL = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
ATTRIBUTION = "© OpenStreetMap-bijdragers (ODbL)"
POI_KEYS = ("shop", "amenity", "craft", "office", "healthcare", "tourism", "leisure", "club", "disused:shop", "was:shop")
NAME_TAGS = ("name", "brand", "operator", "official_name", "alt_name", "old_name")
PHONE_TAGS = ("phone", "contact:phone", "mobile", "contact:mobile")
EMAIL_TAGS = ("email", "contact:email")
WEBSITE_TAGS = ("website", "contact:website", "url")
CHECK_DATE_TAGS = ("check_date", "survey:date", "check_date:opening_hours")


@dataclass
class OsmMatch:
    url: str
    name: str
    score: int
    reason: str
    phones: list[tuple[str, str, str]] = field(default_factory=list)  # (e164, display, tag=value)
    emails: list[tuple[str, str]] = field(default_factory=list)  # (email, tag=value)
    websites: list[str] = field(default_factory=list)
    disused: bool = False
    opening_hours: str | None = None
    check_date: str | None = None


def build_query(municipality: str) -> str:
    name = municipality.replace("\\", "").replace('"', '\\"')
    selectors = "".join(f'nwr(area.a)["name"]["{key}"];' for key in POI_KEYS)
    return (
        '[out:json][timeout:90];'
        f'area["boundary"="administrative"]["admin_level"="8"]["name"="{name}"]->.a;'
        f'({selectors});out center tags;'
    )


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.replace(",", ";").split(";") if v.strip()]


def _normalize_url(value: str) -> str:
    value = value.strip()
    return value if "://" in value else "https://" + value


class OsmIndex:
    def __init__(self, fetcher: Fetcher, ttl_hours: float = 24):
        self.fetcher = fetcher
        self.ttl = ttl_hours * 3600
        self._pois: dict[str, list[dict]] = {}
        self._lock = threading.Lock()

    def pois(self, municipality: str) -> list[dict]:
        key = municipality.strip().lower()
        with self._lock:  # one Overpass download per municipality, also with worker threads
            if key not in self._pois:
                cache_key = f"OVERPASS {key}"
                data = self.fetcher.cache_get(cache_key, ttl=self.ttl)
                if data is None:
                    resp = self.fetcher.post(OVERPASS_URL, data={"data": build_query(municipality)}, timeout=120)
                    resp.raise_for_status()
                    data = resp.json()
                    self.fetcher.cache_put(cache_key, data)
                self._pois[key] = data.get("elements", [])
            return self._pois[key]

    def lookup(self, target: EnrichTarget) -> tuple[OsmMatch | None, SourceRun]:
        if not target.municipality:
            return None, SourceRun("osm", "overgeslagen", "geen gemeente in het record")
        try:
            pois = self.pois(target.municipality)
        except Exception as exc:  # network/Overpass trouble must not stop the batch
            return None, SourceRun("osm", "fout", f"Overpass: {type(exc).__name__}")
        if not pois:
            return None, SourceRun("osm", "geen_resultaat", f"geen OSM-zaken gevonden voor {target.municipality}")

        best: OsmMatch | None = None
        for element in pois:
            tags = element.get("tags", {})
            similarity = m.best_similarity(target.names, [tags[t] for t in NAME_TAGS if tags.get(t)])
            if similarity < 60:
                continue
            center = element.get("center") or element
            distance = m.haversine_m(target.lat, target.lon, center.get("lat"), center.get("lon"))
            same_street = m.street_similarity(tags.get("addr:street"), target.street) >= 90
            same_number = m.house_match(tags.get("addr:housenumber"), target.house_number)
            score, reason = m.place_match_score(similarity, distance, same_street, same_number)
            if score and (best is None or score > best.score):
                best = self._to_match(element, score, reason)

        if best is None:
            return None, SourceRun("osm", "geen_resultaat", f"{len(pois)} OSM-zaken bekeken, geen match")
        return best, SourceRun("osm", "ok", f"{best.name}: {best.reason} ({best.url})")

    @staticmethod
    def _to_match(element: dict, score: int, reason: str) -> OsmMatch:
        tags = element.get("tags", {})
        match = OsmMatch(
            url=f"https://www.openstreetmap.org/{element.get('type')}/{element.get('id')}",
            name=tags.get("name", ""),
            score=score,
            reason=reason,
            disused=any(k in tags for k in ("disused:shop", "was:shop")) or tags.get("shop") == "vacant",
            opening_hours=tags.get("opening_hours"),
            check_date=next((tags[t] for t in CHECK_DATE_TAGS if tags.get(t)), None),
        )
        for tag in PHONE_TAGS:
            for raw in _split(tags.get(tag, "")):
                if phone := phone_from_string(raw):
                    match.phones.append((*phone, f"{tag}={raw}"))
        for tag in EMAIL_TAGS:
            for raw in _split(tags.get(tag, "")):
                if email := clean_email(raw):
                    match.emails.append((email, f"{tag}={raw}"))
        for tag in WEBSITE_TAGS:
            if tags.get(tag):
                match.websites.append(_normalize_url(tags[tag]))
        return match
