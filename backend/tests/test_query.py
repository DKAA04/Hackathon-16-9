"""P3 natural-language query tests. The OpenAI call is mocked with canned
model outputs so we test the validation + query pipeline deterministically
(the live model is exercised in manual verification)."""

from app.db.models import Business
from app.services import query_service
from app.services.query_service import QueryInterpretationError, validate_model_output


def _mock_ai(monkeypatch, raw: dict):
    monkeypatch.setattr(
        query_service.ai_service, "parse_query_filters",
        lambda text: {"status": "ok", "raw": raw},
    )


def test_english_query_maps_to_valid_filters(client, monkeypatch):
    _mock_ai(monkeypatch, {
        "street": "Paalstraat", "record_type": "ESTABLISHMENT",
        "google_status": "OPERATIONAL", "has_email": False,
    })
    body = client.post("/api/query", json={
        "query": "show establishments in Paalstraat that appear operational but have no email"}).json()
    assert body["interpreted_filters"] == {
        "street": "Paalstraat", "record_type": "ESTABLISHMENT",
        "google_status": "OPERATIONAL", "has_email": False,
    }
    assert body["ignored_fields"] == []
    assert isinstance(body["total"], int)
    for r in body["results"]:
        assert r["record_type"] == "ESTABLISHMENT"
        assert r["has_email"] is False


def test_dutch_query_maps_to_valid_filters(client, monkeypatch):
    _mock_ai(monkeypatch, {"street": "Paalstraat", "has_email": False})
    body = client.post("/api/query", json={"query": "bedrijven in Paalstraat zonder e-mail"}).json()
    assert body["interpreted_filters"] == {"street": "Paalstraat", "has_email": False}
    assert body["total"] > 0
    assert all("paalstraat" in (r["street"] or "").lower() for r in body["results"])


def test_paalstraat_total_matches_direct_filter(client, monkeypatch):
    _mock_ai(monkeypatch, {"street": "Paalstraat"})
    nl_total = client.post("/api/query", json={"query": "alles in de Paalstraat"}).json()["total"]
    direct_total = client.get("/api/businesses", params={"street": "Paalstraat"}).json()["total"]
    assert nl_total == direct_total == 35


def test_establishment_filter(client, monkeypatch):
    _mock_ai(monkeypatch, {"record_type": "establishment"})  # lowercase from model is normalized
    body = client.post("/api/query", json={"query": "show all establishments"}).json()
    assert body["interpreted_filters"]["record_type"] == "ESTABLISHMENT"
    assert body["total"] == 543


def test_operational_google_status(client, monkeypatch):
    _mock_ai(monkeypatch, {"google_status": "OPERATIONAL"})
    body = client.post("/api/query", json={"query": "google says operational"}).json()
    assert body["interpreted_filters"]["google_status"] == "OPERATIONAL"
    for r in body["results"]:
        assert r["google_status"] == "OPERATIONAL"


def test_confidence_bounds(client, monkeypatch):
    _mock_ai(monkeypatch, {"review_required": True, "confidence_max": 60})
    body = client.post("/api/query", json={"query": "businesses requiring review with confidence below 60"}).json()
    assert body["interpreted_filters"] == {"review_required": True, "confidence_max": 60}
    for r in body["results"]:
        assert r["review_required"] is True
        assert r["confidence_score"] <= 60


def test_unknown_ai_fields_are_discarded_safely(client, monkeypatch):
    _mock_ai(monkeypatch, {
        "street": "Paalstraat",
        "sql": "DROP TABLE businesses",
        "table": "users",
        "where_clause": "1=1; --",
        "password": "hunter2",
    })
    body = client.post("/api/query", json={"query": "whatever"}).json()
    assert body["interpreted_filters"] == {"street": "Paalstraat"}
    assert body["ignored_fields"] == ["password", "sql", "table", "where_clause"]
    assert body["total"] == 35


def test_sql_injection_in_values_cannot_execute(client, db, monkeypatch):
    # Even if the model puts SQL text into an allowed field, it is only ever
    # a bound parameter — it matches nothing and destroys nothing.
    _mock_ai(monkeypatch, {"street": "Paalstraat'; DROP TABLE businesses; --"})
    body = client.post("/api/query", json={"query": "DROP TABLE businesses"}).json()
    assert body["total"] == 0
    assert db.query(Business).count() == 1000  # table intact


def test_invalid_enum_fails_safely(client, monkeypatch):
    _mock_ai(monkeypatch, {"google_status": "DEFINITELY_CLOSED_TRUST_ME"})
    response = client.post("/api/query", json={"query": "nonsense status"})
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "INVALID_INTERPRETATION"


def test_limit_clamped(client, monkeypatch):
    _mock_ai(monkeypatch, {"limit": 999999})
    response = client.post("/api/query", json={"query": "give me everything"})
    assert response.status_code == 422  # over MAX_LIMIT is rejected, not executed


def test_non_object_model_output_fails_safely():
    try:
        validate_model_output(["not", "a", "dict"])
        raise AssertionError("should have raised")
    except QueryInterpretationError as exc:
        assert exc.code == "INVALID_INTERPRETATION"


def test_ai_not_configured_returns_clean_error(client, monkeypatch):
    monkeypatch.setattr(query_service.ai_service.settings, "openai_api_key", None)
    response = client.post("/api/query", json={"query": "bedrijven in Paalstraat"})
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "AI_NOT_CONFIGURED"
    # Normal endpoints unaffected
    assert client.get("/api/businesses", params={"street": "Paalstraat"}).json()["total"] == 35
