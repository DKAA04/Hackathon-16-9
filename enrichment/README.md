# DuckDuckGov · contact enrichment

Finds phone numbers, e-mail addresses and websites for business-register records, and records **where** each value was found and **how sure** we are. Every value is a proposal (`review_status: "voorstel"`) for an officer to confirm or reject.

Standalone on purpose: it does not touch `backend/app` or `frontend/`.

## Run

From the repo root (any Python 3.11+ works; the backend venv is handy):

```powershell
backend\.venv\Scripts\pip install -r enrichment\requirements.txt

# a data file (VKBO CSV / GeoJSON from the starter pack, or a JSON list)
# e.g. the Schoten sample: 1,000 records, 123 with register red flags
backend\.venv\Scripts\python -m enrichment --input backend\data\reference\schoten-kbo-1000-2026-09-07.geojson --only-flagged

# live from the Flemish VKBO service
backend\.venv\Scripts\python -m enrichment --gemeente Edegem --straat Hovestraat --limit 15

# one business
backend\.venv\Scripts\python -m enrichment --name "Bakkerij Voorbeeld" --street Kerkplein --number 5 --postcode 2650 --gemeente Edegem
```

Writes `enrichment/out/<timestamp>.json` (for the app) and `.csv` (Excel nl-BE: `;`, UTF-8 BOM, enterprise numbers as `0123.456.789` so leading zeros survive). Use `--out path/name` to choose the name.

| Flag | Effect |
| --- | --- |
| `--only-flagged` | only records with register red flags (struck off, address struck off, liquidation/bankruptcy, address not in the address register) |
| `--only-missing` | only records without a phone number in the register |
| `--ids 0428755935,2123456789` | only these record numbers |
| `--limit N`, `--workers 4` | batch size and parallelism |
| `--no-osm`, `--no-google`, `--no-web-search`, `--no-guess`, `--no-cache` | switch sources off |

Input columns: VKBO names (`Ondernemingsnr`, `Ondernemingsnr_maatsch_zetel`, `Maatschappelijke_naam`, `Commerciele_naam`, `KBO_Straat`, `KBO_Huisnr`, `KBO_Postcode`, `KBO_Gemeente`, `Telefoonnummer`, `Email`, `longitude`, `latitude`, …, any case) or generic ones (`name`, `trade_name`, `street`, `house_number`, `postcode`, `municipality`, `phone`, `email`, `website`, `lat`, `lon`).

## Sources

| Order | Source | Needs | Gives |
| --- | --- | --- | --- |
| 1 | KBO record | – | phone/e-mail the enterprise registered, red flags |
| 2 | OpenStreetMap (Overpass) | – | name/address match, phone, e-mail, website, opening hours, "disused" |
| 3 | Google Maps (Places API New) | `GOOGLE_MAPS_API_KEY` | phone, website, open / temporarily / permanently closed, Maps link |
| 4 | Website crawl | – | home + contact/legal pages: `tel:`/`mailto:` links, schema.org, page text, Cloudflare-protected addresses, enterprise number |
| 5 | Domain guess | – | tries e.g. `bakkerijpeeters.be`; kept only if the site proves it is this business |
| 6 | Web search (OpenAI) | `OPENAI_API_KEY` | candidate URLs when nothing above gave a confirmed site; the crawler still has to confirm them |

Keys come from the environment, `enrichment/.env` or `backend/.env`. Model: `ENRICH_OPENAI_MODEL`, else `OPENAI_MODEL`, else `gpt-5-mini`.

Google Search and Google Maps web pages are **not** scraped: Google's terms forbid it and it runs into CAPTCHAs. The Places API is the official route (a Google Cloud project with billing and "Places API (New)" enabled; phone/website fields are billed at a higher tier, so check pricing and the free monthly quota).

## Confidence (0–100)

- **Is this site theirs?** enterprise number on the site 95 · name + street/number 88 · street/number 80 · name + postcode/town 70 · name only 45. Another valid enterprise number on the site (and not theirs) caps it at 50.
- **Is this map listing theirs?** name + address 92 · name + within 60 m 88 · address + similar name 82 · name + same street/within 250 m 75 · name only 55.
- **Register values:** 80 (the date they were entered is unknown).
- **Agreement:** +5 for each extra independent source.
- **Linked but unproven site** (e.g. a brand's office locator): site max 65, its contacts max 55.
- **Several phone numbers on one site:** the number written next to this street +2 and scope `vestiging`; the others −20.
- **Levels:** `hoog` ≥ 85 · `middel` ≥ 65 · `laag` below that; values under 30 are dropped.

## Output

```jsonc
{
  "target": { "record_id", "name", "trade_name", "enterprise_number", "is_establishment", "address",
              "register_url", "flags": ["ambtshalve doorgehaald"], "aliases": ["Voorbeeldbakker"], ... },
  "phones":   [{ "value": "+3234401234", "display": "03 440 12 34", "confidence": 97, "level": "hoog",
                 "scope": "vestiging", "review_status": "voorstel",
                 "observations": [{ "source": "osm", "url": "...", "snippet": "phone=...", "confidence": 92,
                                    "reason": "OpenStreetMap: naam en adres komen overeen", "retrieved_at": "..." }] }],
  "emails": [...], "websites": [...],
  "signals":  [{ "value": "google_closed_permanently | osm_disused | website_unreachable | osm_opening_hours", ... }],
  "best": { "phone": {...}, "email": {...}, "website": {...} },
  "identity_proof": ["https://...: ondernemingsnummer 0428.755.935 staat op de website"],
  "ui_evidence": [{ "label": "Telefoon", "value": "03 440 12 34 (zekerheid hoog)", "source": "Website · https://...", "status": "support" }],
  "sources": [{ "source": "osm", "status": "ok | geen_resultaat | overgeslagen | fout", "detail": "...", "elapsed_ms": 6 }],
  "summary": "telefoon: 03 440 12 34 (hoog); ..."
}
```

`ui_evidence` already matches the frontend's `Evidence` type.

## Use from the backend

```python
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))  # repo root, from backend/app/main.py

from enrichment import Enricher, target_from_row

enricher = Enricher()  # reuse it: it holds the HTTP client, caches and the OSM index
result = enricher.enrich(target_from_row(record))  # record: one VKBO row as a dict
payload = result.to_dict()
```

A record takes a few seconds (up to ~15 s on a new site). Run batches ahead of the demo and serve the JSON; the page cache makes re-runs fast.

## Politeness and privacy

- Follows robots.txt; at most 1 request per second per site, 5 pages per site, 2 MB per page; public addresses only.
- Pages are cached for 72 h in `enrichment/.cache` (Overpass 24 h). Google results are never written to disk.
- User agent: `DuckDuckGov-enrichment/0.1 (PROV-AI hackathon prototype; not affiliated with DuckDuckGo)`.
- A sole trader's phone number is personal data. `enrichment/out/` is git-ignored; keep real numbers out of public videos.
- Attribution: *publieke KBO gegevens, verrijkt met adressen uit het Vlaamse Adressenregister* · © OpenStreetMap-bijdragers (ODbL) · Google Maps (when used).

## Tests

```powershell
backend\.venv\Scripts\python -m pytest enrichment\tests -q
```
