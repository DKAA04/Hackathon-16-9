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
      "review_required": false
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
  "total_businesses": 1000
}
```

---

## GET /api/map

Normalized GeoJSON FeatureCollection. Same filters as `/api/businesses`
(minus pagination): `query`, `street`, `postcode`, `municipality`,
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
        "has_website": false
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

## Planned (P3 — not implemented yet)

Optional `POST /api/query` natural-language filter parsing.
