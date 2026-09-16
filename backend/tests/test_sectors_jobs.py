import time

from app.db.models import Business
from app.services import nightly_job
from app.services.sectors import classify


def make(**fields) -> Business:
    return Business(business_number="0000000000", record_type="ENTERPRISE", **fields)


def keys(business: Business) -> set[str]:
    return {m["value"] for m in classify(business)}


def test_bakery_by_activity_code():
    matches = classify(make(display_name="Loewie Biskwie", nace_rsz_code="10720",
                            nace_rsz_description="Vervaardiging van beschuit"))
    assert [m["value"] for m in matches] == ["bakkerij"]
    assert "10720" in matches[0]["reason"]


def test_sandwich_bar_is_horeca_not_bakery():
    assert keys(make(display_name="Broodjes Tasty")) == {"horeca"}
    assert keys(make(display_name="Bakkerij Peeters")) == {"bakkerij"}


def test_whole_words_only():
    assert keys(make(display_name="Kerkfabriek Sint-Jozef te Bloemendaal")) == set()
    assert keys(make(display_name="Bloemen Van Hoof")) == {"winkel"}


def test_co_ownership_is_never_a_sector():
    vme = make(display_name="Residentie Eethuis", legal_form="Vereniging van Mede-eigenaars",
               legal_name="Vereniging van Mede-eigenaars Residentie Eethuis")
    assert classify(vme) == []


def test_sector_filter_list_map_and_counts(client):
    body = client.get("/api/businesses", params={"sector": "zorg", "limit": 500}).json()
    assert body["total"] > 0
    assert all("zorg" in r["sectors"] for r in body["results"])
    counts = {s["value"]: s["count"] for s in client.get("/api/filters").json()["sectors"]}
    assert counts["zorg"] == body["total"]
    assert client.get("/api/map", params={"sector": "zorg"}).json()["total_matching"] == body["total"]


def test_unknown_sector_rejected(client):
    assert client.get("/api/businesses", params={"sector": "nope"}).status_code == 422


def test_detail_explains_sector(client):
    item = client.get("/api/businesses", params={"sector": "zorg", "limit": 1}).json()["results"][0]
    detail = client.get(f"/api/businesses/{item['id']}").json()
    assert detail["sectors"][0]["value"] == "zorg"
    assert detail["sectors"][0]["reason"]


def test_nightly_job_runs_and_logs(client):
    assert client.post("/api/admin/jobs/nightly/run", params={"enrich_limit": 0}).status_code == 202
    body = {}
    for _ in range(200):
        body = client.get("/api/admin/jobs").json()
        if not body["running"] and body["runs"] and body["runs"][0]["status"] != "running":
            break
        time.sleep(0.05)
    run = body["runs"][0]
    assert (run["status"], run["trigger"]) == ("success", "manual")
    messages = " | ".join(line["message"] for line in run["log"])
    assert "KBO-momentopname ingelezen: 1000 records" in messages
    assert "Sectoren herkend" in messages
    assert run["stats"]["enrichment"]["checked"] == 0
    assert run["stats"]["quality"]["enterprises"] + run["stats"]["quality"]["establishments"] == 1000
    assert body["schedule"]["enabled"] is False  # disabled in tests (conftest)


def test_second_run_refused_while_running(client):
    assert nightly_job._run_lock.acquire(blocking=False)
    try:
        response = client.post("/api/admin/jobs/nightly/run")
        assert response.status_code == 409
        assert response.json()["detail"]["error"] == "JOB_ALREADY_RUNNING"
    finally:
        nightly_job._run_lock.release()
