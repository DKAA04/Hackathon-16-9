from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import get_db
from app.db.models import JobRun
from app.services import nightly_job
from app.services.kbo_import import run_import

router = APIRouter(prefix="/api", tags=["admin"])


@router.post("/admin/import")
def admin_import(db: Session = Depends(get_db)):
    """Idempotent import of the supplied KBO snapshot (GeoJSON canonical,
    CSV as sanity check). Safe to run repeatedly."""
    return run_import(db)


@router.get("/admin/jobs")
def list_jobs(limit: int = Query(default=10, ge=1, le=50), db: Session = Depends(get_db)):
    """Nightly job schedule and the most recent runs with their log lines."""
    runs = db.query(JobRun).order_by(JobRun.id.desc()).limit(limit).all()
    return {
        "schedule": {
            "job_name": nightly_job.JOB_NAME,
            "enabled": settings.nightly_enabled,
            "time": settings.nightly_time,
            "timezone": "Europe/Brussels",
            "next_run_at": nightly_job.next_run_at().isoformat(timespec="minutes") if settings.nightly_enabled else None,
            "enrich_limit": settings.nightly_enrich_limit,
            "steps": ["import", "opschoning", "registersignalen", "sectoren", "verrijking"],
        },
        "running": nightly_job.is_running(),
        "runs": [nightly_job.serialize_run(r) for r in runs],
    }


@router.post("/admin/jobs/nightly/run", status_code=202)
def run_nightly_now(enrich_limit: int | None = Query(default=None, ge=0, le=100)):
    """Start the nightly job now in the background; follow it via GET /api/admin/jobs."""
    if not nightly_job.start_in_background("manual", enrich_limit):
        raise HTTPException(status_code=409, detail={"error": "JOB_ALREADY_RUNNING"})
    return {"started": True}
