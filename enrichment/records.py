"""Turn register rows (VKBO API, starter-pack CSV/GeoJSON, or any JSON list) into EnrichTargets."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import httpx

from .models import EnrichTarget

VKBO_ITEMS_URL = "https://geo.api.vlaanderen.be/VKBO/ogc/features/v1/collections/Vkbo/items"
VKBO_ATTRIBUTION = "publieke KBO gegevens, verrijkt met adressen uit het Vlaamse Adressenregister"
UNSET_DATES = ("1900-01-01", "9999-12-31")


def load_file(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if path.suffix.lower() in (".csv", ".tsv", ".txt"):
        with path.open(encoding="utf-8-sig", newline="") as fh:
            sample = fh.read(8192)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            return list(csv.DictReader(fh, dialect=dialect))
    data = json.loads(path.read_text(encoding="utf-8"))
    return rows_from_json(data)


def rows_from_json(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        return [_feature_row(f) for f in data.get("features", [])]
    if isinstance(data, dict):
        data = data.get("records") or data.get("data") or data.get("results") or [data]
    return [r for r in data if isinstance(r, dict)]


def _feature_row(feature: dict) -> dict[str, Any]:
    row = dict(feature.get("properties") or {})
    coords = (feature.get("geometry") or {}).get("coordinates") or [None, None]
    row.setdefault("longitude", coords[0])
    row.setdefault("latitude", coords[1])
    return row


def fetch_vkbo(gemeente: str, straat: str | None = None, limit: int | None = None,
               timeout: float = 60.0) -> list[dict[str, Any]]:
    """Live rows from Digitaal Vlaanderen's VKBO service (records with KBO status 'actief')."""
    def quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    cql = f"KBO_Gemeente={quote(gemeente)}"
    if straat:
        cql += f" AND KBO_Straat={quote(straat)}"
    page_size = min(limit or 1000, 1000)
    rows: list[dict[str, Any]] = []
    with httpx.Client(timeout=timeout) as client:
        while limit is None or len(rows) < limit:
            params = {
                "f": "application/geo+json",
                "limit": page_size,
                "startIndex": len(rows),
                "filter-lang": "cql-text",
                "filter": cql,
            }
            resp = client.get(VKBO_ITEMS_URL, params=params)
            resp.raise_for_status()
            features = resp.json().get("features", [])
            rows.extend(_feature_row(f) for f in features)
            if len(features) < page_size:
                break
    return rows[:limit] if limit else rows


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s and s.lower() not in ("nan", "none", "null") else None


def _number(value: Any) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return None
    return digits.zfill(10) if len(digits) < 10 else digits


def _float(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _real_date(value: Any) -> str | None:
    s = _clean(value)
    return s[:10] if s and s[:10] not in UNSET_DATES else None


def red_flags(row: dict[str, Any]) -> list[str]:
    """Register hints that a record marked 'actief' may no longer be active."""
    flags = []
    if _real_date(row.get("begindat_ambtsh_doorhaling")) and not _real_date(row.get("einddat_ambtsh_doorhaling")):
        flags.append("ambtshalve doorgehaald")
    if _real_date(row.get("datum_adresdoorhaling")):
        flags.append("adres doorgehaald")
    status = _clean(row.get("rechtstoestand"))
    if status and status.lower() != "normale toestand":
        flags.append(f"rechtstoestand: {status}")
    if _clean(row.get("kbo_straat")) and "ar_straat" in row and not _clean(row.get("ar_straat")):
        flags.append("adres niet gevonden in adressenregister")
    return flags


def target_from_row(row: dict[str, Any]) -> EnrichTarget | None:
    r = {str(k).strip().lower(): v for k, v in row.items()}

    def get(*keys: str) -> str | None:
        for key in keys:
            if (value := _clean(r.get(key))) is not None:
                return value
        return None

    record_id = _number(get("ondernemingsnr", "record_id", "enterprise_number", "ondernemingsnummer", "kbo"))
    parent = _number(get("ondernemingsnr_maatsch_zetel", "parent_enterprise_number"))
    name = get("maatschappelijke_naam", "name", "naam", "company_name")
    trade_name = get("commerciele_naam", "trade_name", "handelsnaam", "afgekorte_naam")
    if not (name or trade_name):
        return None
    is_establishment = bool(parent) or (record_id or "").startswith("2")
    return EnrichTarget(
        record_id=record_id or "",
        name=name or trade_name or "",
        trade_name=trade_name if trade_name and trade_name != name else None,
        enterprise_number=parent if is_establishment else record_id,
        is_establishment=is_establishment,
        street=get("kbo_straat", "ar_straat", "street", "straat"),
        house_number=get("kbo_huisnr", "ar_huisnr", "house_number", "huisnummer", "huisnr"),
        postcode=get("kbo_postcode", "ar_postcode", "postcode", "postal_code"),
        municipality=get("kbo_gemeente", "municipality", "gemeente", "city"),
        lat=_float(get("latitude", "lat")),
        lon=_float(get("longitude", "lon", "lng")),
        known_phone=get("telefoonnummer", "phone", "telefoon"),
        known_email=get("email", "e-mail", "mail"),
        known_website=get("website", "webadres", "url"),
        activity=get("omschrijving_hoofdact_rsz", "omschrijving_hoofdact_btw", "activity"),
        flags=red_flags(r),
    )
