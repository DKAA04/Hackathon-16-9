# DuckDuckGov

**[Try the synthetic browser demo](https://dkaa04.github.io/DKAA04/duck.html)** · [Demo provenance](https://github.com/DKAA04/DKAA04/blob/main/SOURCE_NOTES.md)

[![DuckDuckGov demonstration](https://raw.githubusercontent.com/DKAA04/DKAA04/main/duck-preview.png)](https://dkaa04.github.io/DKAA04/duck.html)

**A municipal business-data exploration and enrichment prototype.**

DuckDuckGov brings a KBO/VKBO business snapshot into a searchable map and review interface. It connects registry records, source evidence, enrichment results and manual corrections so a reviewer can inspect why a business record needs attention.

The frontend uses the DuckDuckGov name; backend modules retain the earlier CivicLens name. This is a hackathon prototype, not an official municipal service.

## What is implemented

- React interface for business search, filtering, map exploration and record details.
- FastAPI backend with SQLite persistence, snapshot import and manual overrides.
- Enrichment services for Google Places and business websites, with matching and provenance information.
- Email drafting/sending and a configured test-call integration.
- A frontend fallback that can explore the bundled snapshot without backend API credentials.
- Tests for import, matching, enrichment, queries, overrides and email behavior.

## Architecture

```text
KBO/VKBO snapshot → import and normalization → SQLite → FastAPI → React map and review UI
                                              ↑
                              enrichment + evidence + manual overrides
```

**Stack:** Python, FastAPI, SQLAlchemy, SQLite, React, TypeScript, Vite and Leaflet. OpenAI, Google Places, SMTP and ElevenLabs integrations are optional.

## Run locally

Use Python 3.11+ and a Node.js version compatible with Vite 7 (22.12+ is a suitable baseline).

```bash
git clone https://github.com/DKAA04/Hackathon-16-9.git
cd Hackathon-16-9
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

Start the backend from the repository root:

```bash
NIGHTLY_ENABLED=false python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

PowerShell equivalent:

```powershell
$env:NIGHTLY_ENABLED="false"
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Open http://localhost:5173. API documentation is at http://localhost:8000/docs. The backend imports the bundled snapshot into a local database on first startup. Set `VITE_DATA_MODE=demo` in `frontend/.env.local` to force the frontend fallback.

## Configuration and data

See [backend configuration](backend/.env.example) and [frontend configuration](frontend/.env.example). Keep credentials in ignored local environment files. For a local review, leave external-service credentials empty and disable the nightly job as above.

The bundled snapshot is **a limited Schoten sample, not a complete municipal register**. Its [source metadata](backend/data/reference/source-metadata.json) records the publisher, retrieval date, attribution, licence link and pagination limit. Source attribution: publieke KBO gegevens, verrijkt met adressen uit het Vlaamse Adressenregister.

Review data reuse terms before redistribution, and use synthetic records for screenshots or demos that do not require real registry data. Do not add private contact lists, SMTP credentials, call recordings or client exports.

## Checks

From the repository root, with the Python environment active:

```bash
python -m pytest backend/tests
```

From `frontend/`:

```bash
npm run build
```

The optional standalone [enrichment package](enrichment/README.md) has its own dependencies and tests.

## Prototype boundaries

Confidence scores are review heuristics, not verified ground truth or official ratings. External enrichment may be incomplete or stale. Email and call actions can contact external services when configured; use controlled test recipients only. Authentication, authorization and deployment hardening need review before exposing the backend publicly.

## Explore the implementation

- [API contract](API_CONTRACT.md)
- [Backend services](backend/app/services/)
- [Frontend data-source adapter](frontend/src/api/index.ts)
- [Backend tests](backend/tests/)
