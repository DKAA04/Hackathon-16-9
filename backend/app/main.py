import logging

# Use the OS certificate store for outbound TLS (verification stays ON).
# Needed on machines where antivirus/proxy (e.g. AVG Web Shield) re-signs
# HTTPS traffic with a CA that is trusted by Windows but absent from certifi.
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:  # optional dependency — fall back to certifi bundle
    pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, businesses, calls, email, enrichment, legacy, map as map_api, query
from app.config import settings
from app.db.database import SessionLocal, init_db
from app.db.models import Business, Enrichment
from app.services.kbo_import import load_metadata, run_import
from app.services.nightly_job import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="CivicLens",
    version="0.2.0",
    description=(
        "CivicLens backend — normalized KBO/VKBO snapshot with persistent "
        "enrichment, manual overrides and an explainable review signal. "
        "Confidence scoring is a prototype heuristic, not official municipal scoring."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

app.include_router(businesses.router)
app.include_router(map_api.router)
app.include_router(enrichment.router)
app.include_router(email.router)
app.include_router(query.router)
app.include_router(admin.router)
app.include_router(calls.router)
app.include_router(legacy.router)


@app.on_event("startup")
def startup() -> None:
    init_db()
    # First-run convenience: import the snapshot once if the DB is empty.
    # Never re-imports on every startup/request.
    db = SessionLocal()
    try:
        if db.query(Business).count() == 0:
            logger.info("Empty database — running initial KBO snapshot import")
            run_import(db)
    except Exception as exc:
        logger.error("Initial import failed: %s", exc)
    finally:
        db.close()
    start_scheduler()


@app.on_event("shutdown")
def shutdown() -> None:
    stop_scheduler()


@app.get("/api/health")
def health():
    db = SessionLocal()
    try:
        business_count = db.query(Business).count()
        enrichment_count = db.query(Enrichment).count()
        database = "connected"
    except Exception:
        business_count = enrichment_count = 0
        database = "error"
    finally:
        db.close()

    metadata = load_metadata()
    return {
        "status": "ok",
        "ok": True,  # legacy frontend compatibility
        "database": database,
        "business_count": business_count,
        "records_loaded": business_count,  # legacy frontend compatibility
        "enrichment_count": enrichment_count,
        "dataset": {
            "name": metadata.get("dataset"),
            "snapshot_date": metadata.get("retrieved_on"),
            "source": metadata.get("source_url"),
            "publisher": metadata.get("publisher"),
        },
        "google_places_configured": settings.google_places_configured,
        "smtp_configured": settings.smtp_configured,
        "openai_configured": bool(settings.openai_api_key),
        "calls_configured": settings.calls_configured,
    }
