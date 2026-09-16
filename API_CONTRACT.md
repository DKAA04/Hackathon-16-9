# CivicLens Backend API Contract

Base URL (local dev): `http://localhost:8000`
Interactive docs: `http://localhost:8000/docs`

The frontend only consumes these normalized endpoints. It never needs to parse
the KBO GeoJSON/CSV, the Google Places API, or database internals.

**Key concepts**

- `id` of a business = its **business/registry number as a string** (leading
  zeros matter), e.g. `"0415708742"`.
- `record_type`: `ENTERPRISE` (legal entity) or `ESTABLISHMENT` (physical
  location). An establishment has `parent_enterprise_number` pointing to its
  parent enterprise (which may or may not be inside the Schoten snapshot).
- **Effective values** merge: manual override > enrichment > KBO source.
  Provenance is always included (`*_source` fields and the `sources` block).
- `confidence_score` (0–100), `confidence_level` (`HIGH`/`MEDIUM`/`LOW`) and
  `review_required` come from a **prototype heuristic** — explainable review
  priority, not an official activity probability.
- `google_status`: `OPERATIONAL`, `CLOSED_TEMPORARILY`, `CLOSED_PERMANENTLY`,
  `FUTURE_OPENING`, `UNKNOWN` (checked but no confident match), or `null`
  (never checked). **No Google result ≠ closed.**

---

## GET /api/health

```json
{
  "status": "ok",
  "database": "connected",
  "business_count": 1000,
  "enrichment_count": 0,
  "dataset": {
    "name": "VKBO ondernemingen en vestigingseenheden V3",
    "snapshot_date": "2026-09-07 Europe/Brussels",
    "source": "https://geo.api.vlaanderen.be/...",
    "publisher": "agentschap Digitaal Vlaanderen"
  },
  "google_places_configured": false,
  "smtp_configured": false,
  "openai_configured": false
}
```
(also contains legacy keys `ok` and `records_loaded`)

---

## GET /api/businesses

List/search businesses.

Query parameters (all optional):

| param | type | notes |
|---|---|---|
| `query` | string | searches name(s), business number, street, municipality |
| `sector` | `bakkerij` \| `horeca` \| `zorg` \| `kapper` \| `bouw` \| `auto` \| `winkel` \| `advies` | occupation, see below (422 for unknown keys) |
| `street` | string | substring match on KBO street |
| `postcode` | string | exact |
| `municipality` | string | case-insensitive exact |
| `record_type` | `ENTERPRISE` \| `ESTABLISHMENT` | |
| `legal_status` | string | substring match (e.g. `Normale`) |
| `has_email` / `has_phone` / `has_website` | bool | based on **effective** values |
| `google_status` | string | see above; `NOT_CHECKED` = never enriched |
| `review_required` | bool | |
| `confidence_min` / `confidence_max` | int 0–100 | |
| `limit` | int, default 50, max 500 | |
| `offset` | int, default 0 | |

Response:

```json
{
  "results": [
    {
      "id": "2296242396",
      "business_number": "2296242396",
      "record_type": "ESTABLISHMENT",
      "parent_enterprise_number": "0448824436",
      "display_name": "AMPLIFON Hoorcentrum Schoten",
      "legal_name": "...",
      "legal_form": null,
      "legal_status": null,
      "address": "Paalstraat 38, 2900 Schoten",
      "street": "Paalstraat",
      "postcode": "2900",
      "municipality": "Schoten",
      "longitude": 4.4964,
      "latitude": 51.2529,
      "effective": {
        "display_name": "AMPLIFON Hoorcentrum Schoten",
        "display_name_source": "kbo",
        "email": null, "email_source": null,
        "phone": null, "phone_source": null,
        "website": null, "website_source": null,
        "activity_status": "UNKNOWN",
        "notes": null
      },
      "google_status": null,
      "has_email": false,
      "has_phone": false,
      "has_website": false,
      "confidence_score": 75,
      "confidence_level": "HIGH",
      "review_required": false,
      "sectors": ["zorg"]
    }
  ],
  "total": 35,
  "limit": 50,
  "offset": 0
}
```

`effective.activity_status`: `ACTIVE` | `REVIEW` | `INACTIVE` | `UNKNOWN`
(manual override wins; otherwise derived from Google + KBO legal status).

---

## GET /api/businesses/{id}

Full detail with provenance. 404 `{"detail": "Business not found"}` if unknown.

```json
{
  "business": { ...normalized KBO source record (see fields below)... },
  "parent_enterprise": { ...same shape... } | null,
  "sources": {
    "kbo": { ...original raw source properties... },
    "google_places": { "business_status": {enrichment row}, ... } | null,
    "website": { "email": {enrichment row}, ... } | null,
    "manual_override": { "email": {override row}, ... } | null
  },
  "effective": { ...same shape as in list... },
  "sectors": [
    {"value": "zorg", "label": "Zorg & welzijn",
     "reason": "activiteitscode 86230 (Activiteiten van tandartspraktijken)"}
  ],
  "evidence": [
    {"code": "ADDRESS_MATCH", "effect": 15,
     "label_nl": "KBO-adres komt overeen met het Adressenregister",
     "label_en": "KBO address agrees with the Flemish Address Register"}
  ],
  "confidence_score": 85,
  "confidence_level": "HIGH",
  "review_required": false
}
```

`business` fields: `id`, `business_number`, `parent_enterprise_number`,
`record_type`, `legal_name`, `commercial_name`, `short_name`, `display_name`,
`business_type`, `legal_form`, `legal_status`,
`address {street, house_number, bus_number, postcode, municipality, formatted}`,
`address_register {street, house_number, bus_number, postcode}`,
`phone`, `email`, `nace {vat_code, vat_description, rsz_code, rsz_description}`,
`employee_class`, `registration_date`, `start_date`, `cessation_date`,
`cessation_reason`, `address_deregistration_date`,
`address_deregistration_reason`, `annual_accounts_url`, `longitude`,
`latitude`, `source_dataset`, `source_snapshot_date`.

Enrichment row shape: `{id, provider, field_name, value, source_url,
provider_external_id, confidence, metadata, retrieved_at, status}`.
Override row shape: `{id, field_name, old_effective_value, new_value, note,
created_at}`.

---

## GET /api/businesses/{id}/history

```json
{
  "business_id": "2288075392",
  "enrichments": [ ...all enrichment rows, newest first, incl. superseded... ],
  "overrides": [ ...all override rows, newest first... ]
}
```

---

## PATCH /api/businesses/{id}

Manual officer correction. Stored as override rows; **never mutates KBO
source**. Overrides win in the effective view.

Body (all fields optional, at least one required — otherwise 400):

```json
{
  "display_name": "...",
  "email": "info@example.be",
  "phone": "+32 ...",
  "website": "https://example.be",
  "activity_status": "active" | "inactive" | "review",
  "notes": "free text",
  "note": "why this correction was made (audit note)"
}
```

Response: `{"business_id": "...", "overrides_created": [...], "detail": {full detail response}}`

---

## GET /api/filters

Filter values + counts for building UI dropdowns:

```json
{
  "streets": [{"value": "Paalstraat", "count": 35}, ...],
  "municipalities": [...],
  "postcodes": [...],
  "record_types": [{"value": "ESTABLISHMENT", "count": 543}, {"value": "ENTERPRISE", "count": 457}],
  "legal_statuses": [...],
  "legal_forms": [...],
  "google_statuses": [...],
  "sectors": [{"value": "bakkerij", "label": "Bakkerijen & banket", "count": 1}, ...],
  "total_businesses": 1000
}
```

---

## GET /api/map

Normalized GeoJSON FeatureCollection. Same filters as `/api/businesses`
(minus pagination): `query`, `sector`, `street`, `postcode`, `municipality`,
`record_type`, `legal_status`, `google_status`, `review_required`,
`has_email`, `has_phone`, `has_website`.

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {"type": "Point", "coordinates": [4.52738857, 51.2662707]},
      "properties": {
        "id": "0415708742",
        "display_name": "FOOTBALL CLUB KONINGSHOF",
        "business_number": "0415708742",
        "record_type": "ENTERPRISE",
        "address": "Zilverstraat 53, 2900 Schoten",
        "confidence_score": 75,
        "confidence_level": "HIGH",
        "review_required": false,
        "google_status": null,
        "has_email": false,
        "has_phone": false,
        "has_website": false,
        "sectors": []
      }
    }
  ],
  "total_matching": 1000,
  "skipped_invalid_coordinates": 0
}
```

Records with missing/invalid coordinates are skipped and counted, never crash.

---

## Enrichment (on demand, never bulk-automatic)

### POST /api/businesses/{id}/enrich/google
Runs Google Places lookup and stores results persistently.

Responses:
- not configured: `{"provider": "google_places", "status": "skipped", "reason": "GOOGLE_NOT_CONFIGURED"}`
- upstream failure: `{"provider": "google_places", "status": "error", "error": "..."}` (HTTP 200 — degrades gracefully)
- success: `{"provider": "google_places", "status": "ok", "google_status": "OPERATIONAL", "match_confidence": 0.87, "fields_stored": 8}`

### POST /api/businesses/{id}/enrich/website
Fetches known website (from override/Google enrichment — never guessed) and
extracts structured contact data.
- no known website: `{"provider": "website", "status": "skipped", "reason": "NO_KNOWN_WEBSITE"}`
- success: `{"provider": "website", "status": "ok", "source_url": "...", "fields_stored": 4, "emails_found": [...]}`

### POST /api/businesses/{id}/enrich
Runs all configured enrichers: `{"business_id": "...", "results": [ ...per-provider results... ]}`

### POST /api/enrich
Batch, **max 20 ids** (422 above that):

```json
{"business_ids": ["2288075392", "0415708742"]}
```

---

## POST /api/admin/import

Idempotent re-import of the KBO snapshot (safe to repeat; never duplicates):

```json
{
  "source_features": 1000, "inserted": 0, "updated": 0, "skipped": 1000,
  "errors": [], "business_count": 1000,
  "csv_check": {"csv_available": true, "csv_rows": 1000, "csv_unique_numbers": 1000, "missing_in_db": [], "match": true},
  "dataset": {"name": "...", "snapshot_date": "...", "source": "..."}
}
```

---

### Sectors (occupation filter)

The KBO snapshot barely records activities, so a sector matches on a NACE code prefix
**or** a whole-word keyword in the business name (`services/sectors.py`). Every match
carries a `reason`. Co-ownership associations (VME) never get a sector. Keys:
`bakkerij`, `horeca`, `zorg`, `kapper`, `bouw`, `auto`, `winkel`, `advies`.

## Nightly job (admin)

Runs inside the backend every night at `NIGHTLY_TIME` (Europe/Brussels): re-import the
snapshot → cleaning/quality summary → register signals → sector counts → enrich up to
`NIGHTLY_ENRICH_LIMIT` records that were never checked (sector businesses without
contact data first). Every run and its log lines are stored in `job_runs`.

### GET /api/admin/jobs?limit=10

```json
{
  "schedule": {"job_name": "nightly", "enabled": true, "time": "02:15", "timezone": "Europe/Brussels",
               "next_run_at": "2026-09-17T02:15+02:00", "enrich_limit": 20,
               "steps": ["import", "opschoning", "registersignalen", "sectoren", "verrijking"]},
  "running": false,
  "runs": [{"id": 1, "job_name": "nightly", "trigger": "manual", "status": "success",
            "started_at": "2026-09-16T12:25:01+00:00", "finished_at": "2026-09-16T12:25:09+00:00",
            "stats": {"import": {...}, "quality": {...}, "review_required": 127, "enrichment": {...}},
            "log": [{"at": "2026-09-16T12:25:02+00:00", "level": "info", "message": "KBO-momentopname ingelezen: ..."}]}]
}
```

### POST /api/admin/jobs/nightly/run?enrich_limit=5

Starts a run in the background → 202 `{"started": true}`; follow it with
`GET /api/admin/jobs`. 409 `{"detail": {"error": "JOB_ALREADY_RUNNING"}}` if a run is active.

Settings (`backend/.env`): `NIGHTLY_ENABLED` (default `true`), `NIGHTLY_TIME` (`02:15`),
`NIGHTLY_ENRICH_LIMIT` (`20`). The job only runs while the backend is running.

## Legacy endpoints (existing frontend starter keeps working)

- `POST /api/search` — body `{"query": "...", "demo_mode": false}`; now backed
  by the real database, returns the original `Result` shape.
- `POST /api/ingest` — alias for `/api/admin/import`.

---

## Error states

- 404: `{"detail": "Business not found"}`
- 400: `{"detail": "No override fields provided"}`
- 422: FastAPI validation errors (bad params/body)
- External provider failures never break business lookups; enrichment
  endpoints return `status: "error"`/`"skipped"` payloads instead of 5xx.

## Email workflow

Human-in-the-loop: AI (or an officer) drafts, a human edits/approves, only
approved drafts can be sent. Drafting always works without SMTP/OpenAI.

Draft shape (everywhere below):

```json
{
  "id": 1,
  "business_id": "2296242396",
  "recipient": "info@example.be",
  "subject": "...",
  "ai_generated_body": "... original AI text or null (manual mode) ...",
  "final_body": "... human-editable body actually sent ...",
  "language": "nl",
  "purpose": "verify_business_activity",
  "status": "draft" | "approved" | "sent",
  "created_at": "...", "approved_at": "... | null", "sent_at": "... | null",
  "events": [{"event_type": "created|updated|approved|sent|send_failed",
              "provider_message": "...", "created_at": "..."}]
}
```

### POST /api/emails/draft

```json
{
  "business_ids": ["2296242396"],            // max 20
  "mode": "ai" | "manual",                   // default "ai"
  "language": "nl" | "en",                   // default "nl"
  "purpose": "verify_business_activity" | "verify_contact_details" |
             "request_correction" | "general_contact",
  "instructions": "officer guidance (ai mode, optional)",
  "subject": "required in manual mode",
  "body": "required in manual mode",
  "recipient": "optional — defaults to the business's effective email"
}
```

Response: `{"drafts": [draft...], "errors": [{"business_id": "...", "error": "AI_NOT_CONFIGURED" | "BUSINESS_NOT_FOUND"}]}`

AI mode uses only factual business data from the database (never invents
contact details or status). Without `OPENAI_API_KEY`, AI mode returns
`AI_NOT_CONFIGURED` per business; manual mode always works.

### POST /api/emails/{id}/update
Body: `{"recipient"?, "subject"?, "body"?}` — editing an approved draft
resets it to `draft` (approval must be redone). 409 if already sent.

### POST /api/emails/{id}/approve
Marks the draft human-approved (`approved_at` set). 409 if already sent.

### POST /api/emails/{id}/send
Refuses anything not approved. Returns `{"status": ..., "error"?: ..., "draft": {...}}`:
- not approved → `"error": "DRAFT_NOT_APPROVED"`
- already sent → `"error": "DRAFT_ALREADY_SENT"`
- no recipient → `"error": "NO_RECIPIENT"`
- SMTP not configured → `"error": "EMAIL_PROVIDER_NOT_CONFIGURED"` (draft stays approved)
- SMTP failure → `"error": "SMTP_SEND_FAILED: <type>"` (no credentials ever exposed)
- success → `"status": "sent"`, draft locked (no edit/resend)

### GET /api/emails
Query params: `status`, `business_id`, `limit`, `offset` →
`{"results": [draft...], "total", "limit", "offset"}`

### GET /api/emails/{id}
Single draft with full event history.

## POST /api/query — natural-language search

Converts an officer's sentence (Dutch or English) into **validated filters**
and runs the normal business query. The model never generates SQL; only
allowlisted filter fields reach the database, unknown fields are discarded
(reported in `ignored_fields`), enum values are strictly validated and
`limit` is clamped.

Request: `{"query": "show establishments in Paalstraat that appear operational but have no email"}`

Response:

```json
{
  "original_query": "...",
  "interpreted_filters": {
    "street": "Paalstraat",
    "record_type": "ESTABLISHMENT",
    "google_status": "OPERATIONAL",
    "has_email": false
  },
  "ignored_fields": [],
  "results": [ ...same summary objects as /api/businesses... ],
  "total": 1, "limit": 50, "offset": 0
}
```

Allowed filter fields: `query`, `street`, `postcode`, `municipality`,
`record_type`, `legal_status`, `has_email`, `has_phone`, `has_website`,
`google_status`, `review_required`, `confidence_min`, `confidence_max`,
`limit` (max 100), `offset`.

Errors:
- 503 `{"detail": {"error": "AI_NOT_CONFIGURED"}}` — no OpenAI key (normal
  `/api/businesses` filtering keeps working)
- 422 `{"detail": {"error": "INVALID_INTERPRETATION" | "AI_INTERPRETATION_FAILED", "message": "..."}}`
