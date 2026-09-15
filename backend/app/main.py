from pathlib import Path
import json
import time
from typing import Any

import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pypdf import PdfReader
from rapidfuzz import fuzz


class Settings(BaseSettings):
    frontend_origin: str = "http://localhost:5173"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    elevenlabs_api_key: str | None = None
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

app = FastAPI(title="CivicLens", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

RECORDS: list[dict[str, Any]] = []
DOCUMENTS: list[dict[str, Any]] = []


class Evidence(BaseModel):
    label: str
    value: str
    source: str
    status: str = "support"


class Result(BaseModel):
    id: str
    title: str
    subtitle: str | None = None
    status: str
    confidence: str
    confidence_score: int = Field(ge=0, le=100)
    source_count: int
    summary: str
    tags: list[str]
    evidence: list[Evidence]


class SearchRequest(BaseModel):
    query: str = ""
    demo_mode: bool = True


DEMO = [
    Result(
        id="demo-1",
        title="Noord Atelier BV",
        subtitle="Italiëlei 124, 2000 Antwerpen",
        status="ACTIVE",
        confidence="high",
        confidence_score=97,
        source_count=3,
        summary="Identity, address and local activity records agree.",
        tags=["Retail", "Antwerpen", "Verified"],
        evidence=[
            Evidence(label="Enterprise number", value="0428.755.949", source="Business registry"),
            Evidence(label="Registered address", value="Exact address match", source="Address dataset"),
            Evidence(label="Local activity", value="Present in 2026 local dataset", source="Municipal source"),
        ],
    ),
    Result(
        id="demo-2",
        title="Studio Schelde CommV",
        subtitle="Sint-Paulusstraat 18, 2000 Antwerpen",
        status="ACTIVE",
        confidence="medium",
        confidence_score=78,
        source_count=2,
        summary="Registry and address agree, but local confirmation is older.",
        tags=["Services", "Antwerpen", "Needs review"],
        evidence=[
            Evidence(label="Enterprise number", value="0762.913.181", source="Business registry"),
            Evidence(label="Address", value="Exact street + postcode match", source="Address dataset"),
            Evidence(label="Freshness", value="Last local confirmation: 2024", source="Municipal source", status="warning"),
        ],
    ),
    Result(
        id="demo-3",
        title="Rivierenhof Foods BV",
        subtitle="Turnhoutsebaan 402, 2140 Borgerhout",
        status="REVIEW",
        confidence="low",
        confidence_score=51,
        source_count=3,
        summary="Possible identity conflict: trading name maps to two records.",
        tags=["Food", "Borgerhout", "Conflict"],
        evidence=[
            Evidence(label="Trading name", value="Rivierenhof Foods", source="Municipal source"),
            Evidence(label="Entity match", value="Two candidate enterprise numbers", source="Resolver", status="conflict"),
            Evidence(label="Address", value="One candidate differs by house number", source="Address dataset", status="warning"),
        ],
    ),
]


def norm(record: dict[str, Any], source: str) -> dict[str, Any]:
    out = {}
    for k, v in record.items():
        key = str(k).strip().lower().replace(" ", "_")
        if pd.isna(v):
            v = None
        out[key] = v
    out["_source"] = source
    return out


def pick(record: dict[str, Any], keys: list[str], default="") -> str:
    for k in keys:
        if record.get(k):
            return str(record[k])
    return default


def ingest_file(path: Path):
    suffix = path.suffix.lower()

    if suffix == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        RECORDS.extend(norm(x, path.name) for x in df.to_dict("records"))

    elif suffix in {".xlsx", ".xls"}:
        sheets = pd.read_excel(path, sheet_name=None, dtype=str)
        for sheet, df in sheets.items():
            RECORDS.extend(
                norm({**x, "_sheet": sheet}, path.name)
                for x in df.fillna("").to_dict("records")
            )

    elif suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = payload.get("data") or payload.get("records") or [payload]
        if not isinstance(payload, list):
            payload = [payload]
        RECORDS.extend(norm(x, path.name) for x in payload if isinstance(x, dict))

    elif suffix == ".pdf":
        reader = PdfReader(str(path))
        for n, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            if text:
                DOCUMENTS.append({
                    "id": f"{path.stem}-{n}",
                    "title": path.name,
                    "page": n,
                    "content": text,
                    "_source": path.name,
                })


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "records_loaded": len(RECORDS),
        "documents_loaded": len(DOCUMENTS),
        "openai_configured": bool(settings.openai_api_key),
        "elevenlabs_configured": bool(settings.elevenlabs_api_key),
    }


@app.post("/api/ingest")
def ingest():
    RECORDS.clear()
    DOCUMENTS.clear()

    directory = Path("data/incoming")
    directory.mkdir(parents=True, exist_ok=True)

    errors = []
    files = [
        p for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in {".csv", ".xlsx", ".xls", ".json", ".pdf"}
    ]

    for path in files:
        try:
            ingest_file(path)
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")

    return {
        "files_seen": len(files),
        "records_loaded": len(RECORDS),
        "documents_loaded": len(DOCUMENTS),
        "errors": errors,
    }


def record_to_result(i: int, record: dict[str, Any], score: int) -> Result:
    name = pick(record, ["name", "naam", "company_name", "enterprise_name", "trading_name"], f"Record {i+1}")
    municipality = pick(record, ["municipality", "gemeente", "city", "stad"])
    street = pick(record, ["street", "straat", "address", "adres"])
    postcode = pick(record, ["postcode", "postal_code"])
    subtitle = " ".join(x for x in [street, postcode, municipality] if x) or None
    enterprise = pick(record, ["enterprise_number", "ondernemingsnummer", "kbo", "company_number"], "Unknown")

    confidence_score = max(45, min(99, score))
    confidence = "high" if confidence_score >= 85 else "medium" if confidence_score >= 65 else "low"

    evidence = [
        Evidence(label="Source", value=record.get("_source", "Imported data"), source="Imported dataset")
    ]
    if enterprise != "Unknown":
        evidence.append(Evidence(label="Enterprise number", value=enterprise, source=record.get("_source", "Imported data")))
    if subtitle:
        evidence.append(Evidence(label="Address", value=subtitle, source=record.get("_source", "Imported data")))

    return Result(
        id=f"imported-{i}",
        title=name,
        subtitle=subtitle,
        status=pick(record, ["status", "state", "toestand"], "IMPORTED"),
        confidence=confidence,
        confidence_score=confidence_score,
        source_count=1,
        summary="Imported-record match with visible provenance.",
        tags=[x for x in [municipality or "Imported", record.get("_source", "Dataset")] if x],
        evidence=evidence,
    )


@app.post("/api/search")
def search(request: SearchRequest):
    started = time.perf_counter()
    q = request.query.strip()

    if request.demo_mode or not RECORDS:
        results = DEMO
        if q:
            ranked = []
            for item in results:
                text = f"{item.title} {item.subtitle or ''} {' '.join(item.tags)}"
                ranked.append((fuzz.WRatio(q.lower(), text.lower()), item))
            ranked.sort(key=lambda x: x[0], reverse=True)
            results = [x[1] for x in ranked]
        return {
            "query": q,
            "interpreted_as": "Find relevant businesses and expose evidence",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "total": len(results),
            "results": results,
            "system_notes": ["Demo mode active"],
        }

    ranked = []
    for i, record in enumerate(RECORDS):
        text = " ".join(str(v) for v in record.values() if v is not None)
        score = 90 if not q else fuzz.WRatio(q.lower(), text.lower())
        if score >= 28:
            ranked.append((score, i, record))

    ranked.sort(reverse=True, key=lambda x: x[0])
    results = [record_to_result(i, record, int(score)) for score, i, record in ranked[:30]]

    return {
        "query": q,
        "interpreted_as": "Search imported structured records",
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "total": len(results),
        "results": results,
        "system_notes": [f"{len(RECORDS)} records loaded"],
    }
