"""Write results as JSON (for the app) and as an Excel-friendly CSV (for officers)."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .models import SOURCE_LABELS, EnrichmentResult, Finding, now_iso
from .osm import ATTRIBUTION as OSM_ATTRIBUTION
from .records import VKBO_ATTRIBUTION

TOOL = "DuckDuckGov enrichment 0.1"
REVIEW_NOTE = "Alle waarden zijn voorstellen: een medewerker bevestigt of verwerpt ze voordat ze gebruikt worden."


def format_record_number(number: str) -> str:
    """0123.456.789 / 2.123.456.789: keeps leading zeros when Excel opens the CSV."""
    if len(number) != 10 or not number.isdigit():
        return number
    if number.startswith("2"):
        return f"{number[0]}.{number[1:4]}.{number[4:7]}.{number[7:]}"
    return f"{number[:4]}.{number[4:7]}.{number[7:]}"


def write_json(results: list[EnrichmentResult], path: Path, used_google: bool = False) -> Path:
    attribution = [VKBO_ATTRIBUTION, OSM_ATTRIBUTION] + (["Google Maps"] if used_google else [])
    payload = {
        "tool": TOOL,
        "generated_at": now_iso(),
        "note": REVIEW_NOTE,
        "attribution": attribution,
        "count": len(results),
        "results": [r.to_dict() for r in results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text  # no formula injection in Excel


def _describe(finding: Finding | None) -> tuple[str, str, str, str]:
    if not finding:
        return "", "", "", ""
    sources = " + ".join(SOURCE_LABELS.get(s, s) for s in finding.sources)
    return finding.display, f"{finding.level} ({finding.confidence})", sources, finding.observations[0].url or ""


def result_row(result: EnrichmentResult) -> dict[str, str]:
    t = result.target
    phone = _describe(result.best("phone"))
    email = _describe(result.best("email"))
    site = result.best("website")
    row = {
        "ondernemingsnr": format_record_number(t.record_id),
        "onderneming_zetel": format_record_number(t.enterprise_number or ""),
        "type": "vestiging" if t.is_establishment else "onderneming",
        "naam": t.name,
        "handelsnaam": t.trade_name or "",
        "adres": t.address,
        "kbo_signalen": "; ".join(t.flags),
        "telefoon": phone[0],
        "telefoon_zekerheid": phone[1],
        "telefoon_bronnen": phone[2],
        "telefoon_bewijs": phone[3],
        "andere_telefoons": ", ".join(f.display for f in result.phones[1:4]),
        "email": email[0],
        "email_zekerheid": email[1],
        "email_bronnen": email[2],
        "email_bewijs": email[3],
        "website": site.display if site else "",
        "website_zekerheid": f"{site.level} ({site.confidence})" if site else "",
        "website_bewijs": site.observations[0].snippet if site else "",
        "signalen": "; ".join(s.display for s in result.signals),
        "samenvatting": result.summary,
        "bronnen": "; ".join(f"{r.source}: {r.status}" for r in result.sources),
        "verrijkt_op": result.enriched_at,
    }
    return {k: _cell(v) for k, v in row.items()}


def write_csv(results: list[EnrichmentResult], path: Path) -> Path:
    rows = [result_row(r) for r in results]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:  # BOM + ';' so Excel (nl-BE) opens it cleanly
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["ondernemingsnr"], delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    return path
