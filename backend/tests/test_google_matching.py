"""Google matches must be about this business, not a neighbour on the same street."""
from app.db.models import Business, Enrichment
from app.services import google_places, website_enrichment
from app.services.enrichment_service import revalidate_google_matches

BUSINESS_ID = "2285533695"  # SDG-consultancy, Gelmelenstraat 204 (parent 0719273014)


def _business(db) -> Business:
    return db.query(Business).filter(Business.business_number == BUSINESS_ID).first()


def _place(business, name, address, website="https://ander-bedrijf.be"):
    return {
        "id": "place-other",
        "displayName": {"text": name},
        "formattedAddress": address,
        "businessStatus": "OPERATIONAL",
        "googleMapsUri": "https://maps.google.com/?cid=999",
        "websiteUri": website,
        "internationalPhoneNumber": "+32 3 999 99 99",
        "location": {"latitude": business.latitude, "longitude": business.longitude},
    }


def _use(monkeypatch, places, pages=None):
    monkeypatch.setattr(google_places.settings, "google_maps_api_key", "test-key")
    monkeypatch.setattr(google_places, "_search_text", lambda query, api_key: places)
    monkeypatch.setattr(website_enrichment, "_fetch", lambda url: (pages or {}).get(url.rstrip("/")))


def test_scores():
    b = Business(business_number="0740562732", record_type="ENTERPRISE", legal_name="BROODJESBAR BO",
                 kbo_street="Paalstraat", kbo_house_number="205")
    assert google_places.name_score(b, "Los Smos") < google_places.NAME_MATCH
    assert google_places.same_address(b, "Paalstraat 205, 2900 Schoten, België")
    assert not google_places.same_address(b, "Paalstraat 213, 2900 Schoten, België")
    peeters = Business(business_number="1", record_type="ENTERPRISE", legal_name="Bakkerij Peeters BV")
    assert google_places.name_score(peeters, "Bakkerij Peeters") >= google_places.NAME_MATCH
    assert google_places.name_score(peeters, "Bakkerij Janssens") < google_places.NAME_MATCH
    assert google_places.name_score(peeters, "Bakkerij") < google_places.NAME_MATCH


def test_neighbour_is_rejected_and_its_contacts_not_used(client, db, monkeypatch):
    business = _business(db)
    neighbour = _place(business, "Los Smos", f"{business.kbo_street} 999, 2900 Schoten, België")
    _use(monkeypatch, [neighbour])
    body = client.post(f"/api/businesses/{BUSINESS_ID}/enrich/google").json()
    assert body["google_status"] == "UNKNOWN" and body["other_business"] == "Los Smos"

    detail = client.get(f"/api/businesses/{BUSINESS_ID}").json()
    assert detail["effective"]["phone"] != "+32 3 999 99 99"
    assert detail["effective"]["website"] != "https://ander-bedrijf.be"
    codes = {e["code"] for e in detail["evidence"]}
    assert "GOOGLE_OTHER_BUSINESS_NEARBY" in codes
    assert "GOOGLE_MATCH_OPERATIONAL" not in codes


def test_same_address_other_name_needs_website_proof(client, db, monkeypatch):
    business = _business(db)
    here = _place(business, "Iets Heel Anders", f"{business.kbo_street} {business.kbo_house_number}, 2900 Schoten, België")
    _use(monkeypatch, [here], pages={"https://ander-bedrijf.be": "<html><body>Welkom!</body></html>"})
    body = client.post(f"/api/businesses/{BUSINESS_ID}/enrich/google").json()
    assert body["google_status"] == "UNKNOWN"
    codes = {e["code"] for e in client.get(f"/api/businesses/{BUSINESS_ID}").json()["evidence"]}
    assert "GOOGLE_OTHER_BUSINESS_AT_ADDRESS" in codes


def test_same_address_confirmed_by_enterprise_number_on_site(client, db, monkeypatch):
    business = _business(db)
    parent = business.parent_enterprise_number
    here = _place(business, "Iets Heel Anders", f"{business.kbo_street} {business.kbo_house_number}, 2900 Schoten, België")
    html = f"<html><body>BTW BE {parent[:4]}.{parent[4:7]}.{parent[7:]}</body></html>"
    _use(monkeypatch, [here], pages={"https://ander-bedrijf.be": html})
    body = client.post(f"/api/businesses/{BUSINESS_ID}/enrich/google").json()
    assert body["google_status"] == "OPERATIONAL"
    google = client.get(f"/api/businesses/{BUSINESS_ID}").json()["sources"]["google_places"]
    assert "ondernemingsnummer" in google["business_status"]["metadata"]["reason"]


def test_revalidate_rejects_old_neighbour_match(client, db, monkeypatch):
    business = _business(db)
    db.query(Enrichment).filter(Enrichment.business_id == business.id, Enrichment.status == "active").update(
        {"status": "superseded"})
    for field, value in {
        "business_status": "OPERATIONAL", "matched_name": "Los Smos", "phone": "+32 3 999 99 99",
        "formatted_address": f"{business.kbo_street} 999, 2900 Schoten", "website": "https://ander-bedrijf.be",
    }.items():
        db.add(Enrichment(business_id=business.id, provider="google_places", field_name=field, value=value,
                          confidence=0.61, status="active"))
    db.add(Enrichment(business_id=business.id, provider="website", field_name="email",
                      value="info@ander-bedrijf.be", status="active"))
    db.commit()
    monkeypatch.setattr(website_enrichment, "_fetch", lambda url: None)

    result = revalidate_google_matches(db)
    assert result["rejected"] >= 1
    detail = client.get(f"/api/businesses/{BUSINESS_ID}").json()
    assert detail["effective"]["phone"] != "+32 3 999 99 99"
    assert detail["effective"]["email"] != "info@ander-bedrijf.be"
    assert detail["sources"]["google_places"]["business_status"]["value"] == "UNKNOWN"
