from app.db.models import Business

BUSINESS_ID = "0415708742"  # FOOTBALL CLUB KONINGSHOF


def test_manual_override_wins_in_effective_view(client, db):
    before = db.query(Business).filter(Business.business_number == BUSINESS_ID).first()
    original_email = before.email
    original_name = before.legal_name

    response = client.patch(
        f"/api/businesses/{BUSINESS_ID}",
        json={"email": "corrected@club.be", "note": "verified by phone call"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["overrides_created"][0]["field_name"] == "email"
    assert body["overrides_created"][0]["new_value"] == "corrected@club.be"

    detail = client.get(f"/api/businesses/{BUSINESS_ID}").json()
    assert detail["effective"]["email"] == "corrected@club.be"
    assert detail["effective"]["email_source"] == "manual_override"
    assert detail["sources"]["manual_override"]["email"]["note"] == "verified by phone call"

    # Source KBO values untouched
    db.expire_all()
    after = db.query(Business).filter(Business.business_number == BUSINESS_ID).first()
    assert after.email == original_email
    assert after.legal_name == original_name
    assert detail["business"]["email"] == original_email


def test_override_history_and_precedence_chain(client):
    client.patch(f"/api/businesses/{BUSINESS_ID}", json={"email": "second@club.be", "note": "updated"})
    detail = client.get(f"/api/businesses/{BUSINESS_ID}").json()
    assert detail["effective"]["email"] == "second@club.be"

    history = client.get(f"/api/businesses/{BUSINESS_ID}/history").json()
    email_overrides = [o for o in history["overrides"] if o["field_name"] == "email"]
    assert len(email_overrides) >= 2
    # old_effective_value preserved on the second correction
    assert email_overrides[0]["old_effective_value"] == "corrected@club.be"


def test_override_requires_fields(client):
    response = client.patch(f"/api/businesses/{BUSINESS_ID}", json={"note": "nothing"})
    assert response.status_code == 400


def test_manual_activity_status_flag(client):
    client.patch(f"/api/businesses/{BUSINESS_ID}", json={"activity_status": "inactive", "note": "site visit"})
    detail = client.get(f"/api/businesses/{BUSINESS_ID}").json()
    assert detail["effective"]["activity_status"] == "INACTIVE"
    codes = [e["code"] for e in detail["evidence"]]
    assert "MANUAL_MARKED_INACTIVE" in codes
    assert detail["review_required"] is True
