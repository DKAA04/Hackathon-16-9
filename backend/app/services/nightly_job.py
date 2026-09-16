"""Nightly data job: re-import the KBO snapshot, summarise the cleaning and review
signals, and enrich a capped number of records that were never checked.

Runs inside the backend process at NIGHTLY_TIME (Europe/Brussels) and can be started
by hand from the admin panel. Every run is stored in `job_runs` with its log lines.
"""
from __future__ import annotations

import json
import logging
import math
import threading
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import SessionLocal
from app.db.models import Business, Enrichment, JobRun
from app.services.business_service import query_businesses
from app.services.enrichment_service import enrich_business, revalidate_google_matches
from app.services.kbo_import import run_import
from app.services.sectors import SECTORS, classify, is_co_ownership

logger = logging.getLogger(__name__)

JOB_NAME = "nightly"
TZ = ZoneInfo("Europe/Brussels")
OUT_OF_AREA_KM = 12  # further than this from the municipality centre is a suspect coordinate

_run_lock = threading.Lock()
_stop = threading.Event()
_scheduler_started = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat(timespec="seconds") if value else None


def schedule_time() -> time:
    hours, minutes = (int(x) for x in settings.nightly_time.split(":", 1))
    return time(hours, minutes)


def next_run_at(now: datetime | None = None) -> datetime:
    now = now or datetime.now(TZ)
    candidate = datetime.combine(now.date(), schedule_time(), tzinfo=TZ)
    return candidate if candidate > now else candidate + timedelta(days=1)


def serialize_run(run: JobRun) -> dict:
    return {
        "id": run.id,
        "job_name": run.job_name,
        "trigger": run.trigger,
        "status": run.status,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "stats": json.loads(run.stats_json) if run.stats_json else {},
        "log": json.loads(run.log_json) if run.log_json else [],
    }


def is_running() -> bool:
    return _run_lock.locked()


def _quality(db: Session) -> dict:
    rows = db.query(Business).all()
    numbers = {r.business_number for r in rows}

    located = [r for r in rows if r.longitude is not None and r.latitude is not None]
    center_lat = sorted(r.latitude for r in located)[len(located) // 2] if located else 0.0
    center_lon = sorted(r.longitude for r in located)[len(located) // 2] if located else 0.0

    def valid(r: Business) -> bool:
        if r.longitude is None or r.latitude is None:
            return False
        dlat = math.radians(r.latitude - center_lat)
        dlon = math.radians(r.longitude - center_lon) * math.cos(math.radians(center_lat))
        return 6371 * math.hypot(dlat, dlon) <= OUT_OF_AREA_KM

    sectors = Counter(m["value"] for r in rows for m in classify(r))
    return {
        "enterprises": sum(r.record_type == "ENTERPRISE" for r in rows),
        "establishments": sum(r.record_type == "ESTABLISHMENT" for r in rows),
        "parents_in_dataset": sum(bool(r.parent_enterprise_number) and r.parent_enterprise_number in numbers for r in rows),
        "invalid_coordinates": sum(not valid(r) for r in rows),
        "not_in_address_register": sum(bool(r.kbo_street) and not r.address_register_street for r in rows),
        "address_deregistered": sum(r.address_deregistration_date is not None for r in rows),
        "ex_officio_deregistered": sum(r.official_deregistration_start is not None and r.official_deregistration_end is None for r in rows),
        "abnormal_legal_status": sum(bool(r.legal_status) and r.legal_status.lower() != "normale toestand" for r in rows),
        "co_ownership": sum(is_co_ownership(r) for r in rows),
        "with_phone": sum(bool(r.phone) for r in rows),
        "with_email": sum(bool(r.email) for r in rows),
        "sectors": {s.key: sectors[s.key] for s in SECTORS},
    }


def _enrichment_candidates(db: Session, limit: int) -> list[Business]:
    checked = {row[0] for row in db.query(Enrichment.business_id).distinct()}
    rows = [r for r in db.query(Business).order_by(Business.display_name).all()
            if r.id not in checked and not is_co_ownership(r)]
    # sector businesses without contact details first: that is what officers mail
    rows.sort(key=lambda r: (not classify(r), bool(r.email or r.phone)))
    return rows[:limit]


def run_nightly(trigger: str = "schedule", enrich_limit: int | None = None) -> dict | None:
    """Run the job once. Returns None when a run is already in progress."""
    if not _run_lock.acquire(blocking=False):
        return None
    db = SessionLocal()
    run = JobRun(job_name=JOB_NAME, trigger=trigger, status="running", started_at=_utcnow())
    db.add(run)
    db.commit()
    log: list[dict] = []
    stats: dict = {}

    def note(message: str, level: str = "info") -> None:
        log.append({"at": _iso(_utcnow()), "level": level, "message": message})
        run.log_json = json.dumps(log, ensure_ascii=False)
        db.commit()

    try:
        limit = settings.nightly_enrich_limit if enrich_limit is None else enrich_limit
        note(f"Start ({'geplande taak' if trigger == 'schedule' else 'handmatig gestart'})")

        imported = run_import(db)
        stats["import"] = {k: imported[k] for k in ("source_features", "inserted", "updated", "skipped", "business_count")}
        stats["import"]["errors"] = len(imported["errors"])
        csv = imported.get("csv_check") or {}
        note(f"KBO-momentopname ingelezen: {imported['source_features']} records · {imported['inserted']} nieuw · "
             f"{imported['updated']} gewijzigd · {imported['skipped']} ongewijzigd · {len(imported['errors'])} fouten")
        if csv.get("csv_available"):
            note("CSV-controle: " + ("alle nummers aanwezig" if csv.get("match") else f"{len(csv.get('missing_in_db') or [])} ontbreken"),
                 "info" if csv.get("match") else "warning")

        quality = _quality(db)
        stats["quality"] = quality
        note(f"Opgeschoond: {quality['enterprises']} ondernemingen · {quality['establishments']} vestigingen · "
             f"{quality['parents_in_dataset']} vestigingen met hoofdzetel in de dataset")
        note(f"Registersignalen: {quality['ex_officio_deregistered']} ambtshalve doorgehaald · "
             f"{quality['abnormal_legal_status']} afwijkende rechtstoestand · {quality['address_deregistered']} adres doorgehaald · "
             f"{quality['not_in_address_register']} adres niet in Adressenregister",
             "warning" if quality["ex_officio_deregistered"] or quality["abnormal_legal_status"] else "info")
        note(f"Plausibiliteit: {quality['invalid_coordinates']} coördinaten buiten de gemeente (> {OUT_OF_AREA_KM} km) · "
             f"{quality['co_ownership']} verenigingen van mede-eigenaars (geen handelszaak)")
        labels = {s.key: s.label for s in SECTORS}
        note("Sectoren herkend: " + " · ".join(f"{labels[k]} {v}" for k, v in quality["sectors"].items()))

        review = query_businesses(db, {"review_required": True, "limit": 1})["total"]
        stats["review_required"] = review
        note(f"{review} records vragen controle door een medewerker")

        recheck = revalidate_google_matches(db)
        stats["google_recheck"] = recheck
        note(f"Google-matches herbekeken: {recheck['checked']} · {recheck['rejected']} afgewezen (andere zaak) · "
             f"{recheck['confirmed_by_website']} bevestigd via de website",
             "warning" if recheck["rejected"] else "info")
        candidates = _enrichment_candidates(db, limit)
        if not settings.google_places_configured:
            note("Google Maps niet geconfigureerd: verrijking beperkt tot bekende websites", "warning")
        outcome = Counter()
        found = Counter()
        for business in candidates:
            if _stop.is_set():
                note("Gestopt: backend sluit af", "warning")
                break
            result = enrich_business(db, business)
            parts = []
            for provider in result["results"]:
                key = f"{provider['provider']}:{provider['status']}"
                outcome[key] += 1
                if provider["provider"] == "google_places" and provider["status"] == "ok":
                    parts.append(f"Google {provider.get('google_status')}")
                if provider["provider"] == "website" and provider["status"] == "ok":
                    emails = provider.get("emails_found") or []
                    found["emails"] += len(emails)
                    parts.append(f"website: {len(emails)} e-mail")
            note(f"Verrijkt: {business.display_name} — {', '.join(parts) or 'geen nieuwe gegevens'}")
        stats["enrichment"] = {"checked": len(candidates), "outcomes": dict(outcome), "emails_found": found["emails"]}
        note(f"Verrijking klaar: {len(candidates)} records gecontroleerd (limiet {limit} per nacht) · "
             f"{outcome['google_places:ok']} Google-resultaten · {found['emails']} e-mailadressen gevonden")

        run.status = "success"
        note("Klaar")
    except Exception as exc:  # the job must never take the API down
        logger.exception("Nightly job failed")
        run.status = "failed"
        note(f"Mislukt: {type(exc).__name__}: {exc}", "error")
    finally:
        run.finished_at = _utcnow()
        run.stats_json = json.dumps(stats, ensure_ascii=False)
        db.commit()
        result = serialize_run(run)
        db.close()
        _run_lock.release()
    return result


def start_in_background(trigger: str = "manual", enrich_limit: int | None = None) -> bool:
    if is_running():
        return False
    threading.Thread(target=run_nightly, args=(trigger, enrich_limit), name="nightly-job", daemon=True).start()
    return True


def _scheduler_loop() -> None:
    while not _stop.is_set():
        wait = (next_run_at() - datetime.now(TZ)).total_seconds()
        if _stop.wait(timeout=max(1.0, wait)):
            return
        run_nightly("schedule")


def start_scheduler() -> None:
    global _scheduler_started
    if _scheduler_started:
        return
    if not settings.nightly_enabled:
        logger.info("Nightly job disabled (NIGHTLY_ENABLED=false)")
        return
    _scheduler_started = True
    threading.Thread(target=_scheduler_loop, name="nightly-scheduler", daemon=True).start()
    logger.info("Nightly job scheduled daily at %s Europe/Brussels (next: %s)", settings.nightly_time, next_run_at())


def stop_scheduler() -> None:
    _stop.set()
