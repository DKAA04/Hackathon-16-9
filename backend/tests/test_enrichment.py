import json

from app.db.models import Business, Enrichment
from app.services import google_places
from app.services.website_enrichment import extract_from_html

BUSINESS_ID = "2285533695"  # SDG-consultancy, Gelmelenstraat 204


def _configure_google(monkeypatch, places):
    monkeypatch.setattr(google_places.settings, "google_maps_api_key", "test-key")
    monkeypatch.setattr(google_places, "_search_text", lambda query, api_key: places)


def _strong_place(business, status="OPERATIONAL", **extra):
    return {
        "id": "place-123",
        "displayName": {"text": business.commercial_name or business.legal_name},
        "formattedAddress": f"{business.kbo_street} {business.kbo_house_number}, "
                            f"{business.kbo_postcode} {business.kbo_municipality}, Belgium",
        "businessStatus": status,
        "googleMapsUri": "https://maps.google.com/?cid=123",
        "websiteUri": "https://example.be",
        "internationalPhoneNumber": "+32 3 123 45 67",
        "location": {"latitude": business.latitude, "longitude": business.longitude},
        **extra,
    }


def test_google_not_configured_skips_cleanly(client, monkeypatch):
    monkeypatch.setattr(google_places.settings, "google_maps_api_key", None)
    body = client.post(f"/api/businesses/{BUSINESS_ID}/enrich/google").json()
    assert body["status"] == "skipped"
    assert body["reason"] == "GOOGLE_NOT_CONFIGURED"


def test_google_no_result_is_unknown_not_closed(client, db, monkeypatch):
    _configure_google(monkeypatch, [])
    body = client.post(f"/api/businesses/{BUSINESS_ID}/enrich/google").json()
    assert body["status"] == "ok"
    assert body["google_status"] == "UNKNOWN"

    row = (
        db.query(Enrichment)
        .join(Business)
        .filter(Business.business_number == BUSINESS_ID,
                Enrichment.field_name == "business_status",
                Enrichment.status == "active")
        .first()
    )
    assert row.value == "UNKNOWN"


def test_google_strong_operational_match_enriches(client, db, monkeypatch):
    business = db.query(Business).filter(Business.business_number == BUSINESS_ID).first()
    _configure_google(monkeypatch, [_strong_place(business, "OPERATIONAL")])

    body = client.post(f"/api/businesses/{BUSINESS_ID}/enrich/google").json()
    assert body["status"] == "ok"
    assert body["google_status"] == "OPERATIONAL"
    assert body["match_confidence"] >= 0.55

    # Persistent + visible in effective view / evidence
    detail = client.get(f"/api/businesses/{BUSINESS_ID}").json()
    assert detail["sources"]["google_places"]["business_status"]["value"] == "OPERATIONAL"
    assert detail["effective"]["website"] == "https://example.be"
    codes = [e["code"] for e in detail["evidence"]]
    assert "GOOGLE_MATCH_OPERATIONAL" in codes


def test_weak_match_is_unknown(client, db, monkeypatch):
    business = db.query(Business).filter(Business.business_number == BUSINESS_ID).first()
    weak = _strong_place(business, "OPERATIONAL")
    weak["displayName"] = {"text": "Compleet Ander Bedrijf"}
    weak["formattedAddress"] = "Onbekende straat 1, 9999 Elders, Belgium"
    weak["location"] = {"latitude": 50.0, "longitude": 3.0}
    _configure_google(monkeypatch, [weak])

    body = client.post(f"/api/businesses/{BUSINESS_ID}/enrich/google").json()
    assert body["google_status"] == "UNKNOWN"


def test_google_closed_permanently_produces_review_evidence(client, db, monkeypatch):
    business = db.query(Business).filter(Business.business_number == BUSINESS_ID).first()
    _configure_google(monkeypatch, [_strong_place(business, "CLOSED_PERMANENTLY")])

    client.post(f"/api/businesses/{BUSINESS_ID}/enrich/google")
    detail = client.get(f"/api/businesses/{BUSINESS_ID}").json()
    codes = [e["code"] for e in detail["evidence"]]
    assert "GOOGLE_CLOSED_PERMANENTLY" in codes
    assert detail["review_required"] is True


def test_enrichment_does_not_overwrite_kbo_source(client, db, monkeypatch):
    before = db.query(Business).filter(Business.business_number == BUSINESS_ID).first()
    original = (before.legal_name, before.phone, before.email, before.kbo_street, before.raw_json)

    business = before
    _configure_google(monkeypatch, [_strong_place(business, "OPERATIONAL")])
    client.post(f"/api/businesses/{BUSINESS_ID}/enrich/google")

    db.expire_all()
    after = db.query(Business).filter(Business.business_number == BUSINESS_ID).first()
    assert (after.legal_name, after.phone, after.email, after.kbo_street, after.raw_json) == original


def test_google_provider_failure_does_not_crash_api(client, monkeypatch):
    monkeypatch.setattr(google_places.settings, "google_maps_api_key", "test-key")

    def boom(query, api_key):
        raise RuntimeError("google is down")

    monkeypatch.setattr(google_places, "_search_text", boom)
    response = client.post(f"/api/businesses/{BUSINESS_ID}/enrich/google")
    assert response.status_code == 200
    assert response.json()["status"] == "error"

    # Normal lookup still works afterwards.
    assert client.get(f"/api/businesses/{BUSINESS_ID}").status_code == 200


MOCK_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"LocalBusiness",
 "email":"info@voorbeeld.be","telephone":"+32 3 555 66 77",
 "description":"Familiebedrijf in Schoten."}
</script>
<meta name="description" content="fallback description">
</head><body>
<a href="mailto:contact@voorbeeld.be">mail ons</a>
<a href="tel:+3235556677">bel ons</a>
<a href="https://www.facebook.com/voorbeeld">fb</a>
<a href="/contact">Contactpagina</a>
</body></html>
"""


def test_website_structured_extraction_from_mock_html():
    found = extract_from_html(MOCK_HTML, "https://voorbeeld.be")
    assert "info@voorbeeld.be" in found["emails"]
    assert "contact@voorbeeld.be" in found["emails"]
    assert "+32 3 555 66 77" in found["phones"]
    assert any("facebook.com" in link for link in found["social_links"])
    assert found["description"].startswith("Familiebedrijf")
    assert "https://voorbeeld.be/contact" in found["contact_urls"]


def test_website_enrich_endpoint_skips_without_known_website(client, db):
    # Business without any known website URL — must skip cleanly, not guess.
    row = (
        db.query(Business)
        .outerjoin(Enrichment)
        .filter(Business.record_type == "ENTERPRISE", Enrichment.id.is_(None))
        .first()
    )
    body = client.post(f"/api/businesses/{row.business_number}/enrich/website").json()
    assert body["status"] == "skipped"
    assert body["reason"] == "NO_KNOWN_WEBSITE"


def test_batch_enrich_capped(client):
    response = client.post("/api/enrich", json={"business_ids": ["x"] * 50})
    assert response.status_code == 422  # over the batch cap
