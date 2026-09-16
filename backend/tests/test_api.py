from app.db.models import Business


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"
    assert body["business_count"] == 1000
    assert "dataset" in body


def test_list_businesses_default(client):
    body = client.get("/api/businesses").json()
    assert body["total"] == 1000
    assert len(body["results"]) == 50
    first = body["results"][0]
    for key in ("id", "display_name", "record_type", "confidence_score", "effective"):
        assert key in first


def test_street_filter_paalstraat(client, db):
    body = client.get("/api/businesses", params={"street": "Paalstraat", "limit": 500}).json()
    assert body["total"] > 0
    assert all("paalstraat" in (r["street"] or "").lower() for r in body["results"])
    expected = db.query(Business).filter(Business.kbo_street.ilike("%Paalstraat%")).count()
    assert body["total"] == expected


def test_record_type_filter(client):
    body = client.get("/api/businesses", params={"record_type": "ESTABLISHMENT", "limit": 1}).json()
    assert body["total"] == 543
    assert body["results"][0]["record_type"] == "ESTABLISHMENT"


def test_query_search_by_name_and_number(client):
    body = client.get("/api/businesses", params={"query": "SDG-consultancy"}).json()
    assert body["total"] >= 1
    assert any(r["business_number"] == "2285533695" for r in body["results"])

    body = client.get("/api/businesses", params={"query": "0415708742"}).json()
    assert any(r["business_number"] == "0415708742" for r in body["results"])


def test_detail_includes_parent_and_provenance(client):
    body = client.get("/api/businesses/2285533695").json()
    assert body["business"]["record_type"] == "ESTABLISHMENT"
    assert body["business"]["parent_enterprise_number"] == "0719273014"
    assert "sources" in body and "kbo" in body["sources"]
    assert "effective" in body
    assert isinstance(body["evidence"], list)
    assert body["confidence_level"] in {"HIGH", "MEDIUM", "LOW"}
    # Parent may or may not be inside the Schoten snapshot; if present it must be an enterprise.
    if body["parent_enterprise"] is not None:
        assert body["parent_enterprise"]["record_type"] == "ENTERPRISE"


def test_parent_lookup_when_parent_in_dataset(client, db):
    # Find an establishment whose parent is inside the snapshot.
    parents = {b.business_number for b in db.query(Business).filter(Business.record_type == "ENTERPRISE")}
    establishment = (
        db.query(Business)
        .filter(Business.record_type == "ESTABLISHMENT",
                Business.parent_enterprise_number.in_(parents))
        .first()
    )
    if establishment is None:
        return  # dataset slice has no internal parent links; nothing to assert
    body = client.get(f"/api/businesses/{establishment.business_number}").json()
    assert body["parent_enterprise"] is not None
    assert body["parent_enterprise"]["business_number"] == establishment.parent_enterprise_number


def test_detail_404(client):
    assert client.get("/api/businesses/doesnotexist").status_code == 404


def test_filters_endpoint(client):
    body = client.get("/api/filters").json()
    assert body["total_businesses"] == 1000
    assert any(s["value"] == "Paalstraat" for s in body["streets"])
    assert {r["value"] for r in body["record_types"]} == {"ENTERPRISE", "ESTABLISHMENT"}


def test_map_returns_valid_geojson(client):
    body = client.get("/api/map").json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) > 0
    feature = body["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Point"
    lon, lat = feature["geometry"]["coordinates"]
    assert 2.0 <= lon <= 7.0 and 49.0 <= lat <= 52.0
    for key in ("id", "display_name", "record_type", "confidence_score", "review_required"):
        assert key in feature["properties"]


def test_map_handles_invalid_coordinates(client, db):
    # Inject a record with broken coordinates; it must be skipped, not crash.
    fake = Business(
        business_number="9999999999", record_type="ENTERPRISE",
        legal_name="Broken Coords BV", display_name="Broken Coords BV",
        longitude=None, latitude=None,
    )
    db.add(fake)
    db.commit()
    try:
        body = client.get("/api/map").json()
        assert body["skipped_invalid_coordinates"] >= 1
        assert all(f["properties"]["id"] != "9999999999" for f in body["features"])
    finally:
        db.delete(fake)
        db.commit()


def test_map_street_filter(client):
    body = client.get("/api/map", params={"street": "Paalstraat"}).json()
    assert body["type"] == "FeatureCollection"
    assert 0 < len(body["features"]) <= body["total_matching"]


def test_legacy_search_endpoint(client):
    body = client.post("/api/search", json={"query": "Paalstraat", "demo_mode": False}).json()
    assert body["total"] > 0
    assert body["results"][0]["confidence"] in {"high", "medium", "low"}
