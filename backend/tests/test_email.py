import json

from app.services import ai_service, email_service

BUSINESS_ID = "2288075392"  # COJA (establishment with parent in dataset)


def _manual_draft(client, **kwargs):
    payload = {
        "business_ids": [BUSINESS_ID],
        "mode": "manual",
        "language": "nl",
        "purpose": "verify_business_activity",
        "subject": "Controle activiteit COJA",
        "body": "Geachte, is deze vestiging nog actief? Met vriendelijke groeten, dienst lokale economie.",
        "recipient": "test@example.be",
    }
    payload.update(kwargs)
    return client.post("/api/emails/draft", json=payload)


def test_manual_draft_creation_persists(client):
    response = _manual_draft(client)
    assert response.status_code == 200
    body = response.json()
    assert body["errors"] == []
    draft = body["drafts"][0]
    assert draft["status"] == "draft"
    assert draft["business_id"] == BUSINESS_ID
    assert draft["ai_generated_body"] is None  # manual mode

    fetched = client.get(f"/api/emails/{draft['id']}").json()
    assert fetched["subject"] == "Controle activiteit COJA"
    assert fetched["recipient"] == "test@example.be"
    assert fetched["events"][0]["event_type"] == "created"


def test_ai_draft_fails_cleanly_without_openai(client, monkeypatch):
    monkeypatch.setattr(ai_service.settings, "openai_api_key", None)
    response = client.post("/api/emails/draft", json={
        "business_ids": [BUSINESS_ID], "mode": "ai", "language": "nl",
        "purpose": "verify_business_activity",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["drafts"] == []
    assert body["errors"][0]["error"] == "AI_NOT_CONFIGURED"


def test_ai_draft_works_with_mocked_openai(client, monkeypatch):
    monkeypatch.setattr(ai_service.settings, "openai_api_key", "test-key")

    captured = {}

    def fake_generate(business, effective, language, purpose, instructions):
        captured["facts"] = ai_service.build_business_facts(business, effective)
        return {"status": "ok", "subject": "Vraag over uw vestiging",
                "body": "Geachte, kunt u bevestigen dat uw vestiging nog actief is?"}

    monkeypatch.setattr(ai_service, "generate_draft", fake_generate)
    response = client.post("/api/emails/draft", json={
        "business_ids": [BUSINESS_ID], "mode": "ai", "language": "nl",
        "purpose": "verify_business_activity",
        "instructions": "Ask about current activity.",
    })
    draft = response.json()["drafts"][0]
    assert draft["ai_generated_body"].startswith("Geachte")
    assert draft["final_body"] == draft["ai_generated_body"]
    # Facts fed to AI contain only real DB values — nothing invented.
    assert captured["facts"]["business_number"] == BUSINESS_ID
    assert "known_email" not in captured["facts"] or captured["facts"]["known_email"]


def test_manual_mode_requires_subject_and_body(client):
    response = client.post("/api/emails/draft", json={
        "business_ids": [BUSINESS_ID], "mode": "manual",
    })
    assert response.status_code == 422


def test_draft_edits_persist_and_reset_approval(client):
    draft_id = _manual_draft(client).json()["drafts"][0]["id"]
    client.post(f"/api/emails/{draft_id}/approve")

    updated = client.post(f"/api/emails/{draft_id}/update", json={
        "subject": "Aangepast onderwerp", "body": "Aangepaste inhoud.",
    }).json()
    assert updated["subject"] == "Aangepast onderwerp"
    assert updated["final_body"] == "Aangepaste inhoud."
    assert updated["status"] == "draft"  # edit invalidates approval
    assert updated["approved_at"] is None

    fetched = client.get(f"/api/emails/{draft_id}").json()
    assert fetched["subject"] == "Aangepast onderwerp"
    assert any(e["event_type"] == "updated" for e in fetched["events"])


def test_unapproved_send_is_refused(client):
    draft_id = _manual_draft(client).json()["drafts"][0]["id"]
    body = client.post(f"/api/emails/{draft_id}/send").json()
    assert body["status"] == "error"
    assert body["error"] == "DRAFT_NOT_APPROVED"
    assert body["draft"]["status"] == "draft"
    assert body["draft"]["sent_at"] is None


def test_send_without_smtp_returns_provider_not_configured(client, monkeypatch):
    monkeypatch.setattr(email_service.settings, "smtp_host", None)
    monkeypatch.setattr(email_service.settings, "smtp_from_email", None)

    draft_id = _manual_draft(client).json()["drafts"][0]["id"]
    approved = client.post(f"/api/emails/{draft_id}/approve").json()
    assert approved["status"] == "approved"
    assert approved["approved_at"] is not None

    body = client.post(f"/api/emails/{draft_id}/send").json()
    assert body["status"] == "error"
    assert body["error"] == "EMAIL_PROVIDER_NOT_CONFIGURED"
    # Draft survives, still approved, failure recorded in history.
    fetched = client.get(f"/api/emails/{draft_id}").json()
    assert fetched["status"] == "approved"
    assert any(e["event_type"] == "send_failed" and
               e["provider_message"] == "EMAIL_PROVIDER_NOT_CONFIGURED"
               for e in fetched["events"])


def _configure_smtp(monkeypatch):
    monkeypatch.setattr(email_service.settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(email_service.settings, "smtp_port", 587)
    monkeypatch.setattr(email_service.settings, "smtp_username", "civic-user")
    monkeypatch.setattr(email_service.settings, "smtp_password", "SUPER-SECRET-PW")
    monkeypatch.setattr(email_service.settings, "smtp_from_email", "lokale.economie@schoten.be")


def test_approved_draft_sends_via_mocked_smtp_and_history_persists(client, monkeypatch):
    _configure_smtp(monkeypatch)
    sent = {}

    def fake_smtp_send(recipient, subject, body):
        sent.update(recipient=recipient, subject=subject, body=body)

    monkeypatch.setattr(email_service, "_smtp_send", fake_smtp_send)

    draft_id = _manual_draft(client).json()["drafts"][0]["id"]
    client.post(f"/api/emails/{draft_id}/approve")
    body = client.post(f"/api/emails/{draft_id}/send").json()

    assert body["status"] == "sent"
    assert sent["recipient"] == "test@example.be"

    fetched = client.get(f"/api/emails/{draft_id}").json()
    assert fetched["status"] == "sent"
    assert fetched["sent_at"] is not None
    events = [e["event_type"] for e in fetched["events"]]
    assert events[-1] == "sent"

    # Sent draft is locked: no resend, no edit, no re-approve.
    assert client.post(f"/api/emails/{draft_id}/send").json()["error"] == "DRAFT_ALREADY_SENT"
    assert client.post(f"/api/emails/{draft_id}/update", json={"subject": "x"}).status_code == 409
    assert client.post(f"/api/emails/{draft_id}/approve").status_code == 409

    # Appears in list endpoint with sent status.
    listed = client.get("/api/emails", params={"status": "sent"}).json()
    assert any(d["id"] == draft_id for d in listed["results"])


def test_smtp_failure_is_clean_and_credential_free(client, monkeypatch):
    _configure_smtp(monkeypatch)

    def boom(recipient, subject, body):
        raise ConnectionRefusedError("connect to smtp.example.org failed for civic-user/SUPER-SECRET-PW")

    monkeypatch.setattr(email_service, "_smtp_send", boom)
    draft_id = _manual_draft(client).json()["drafts"][0]["id"]
    client.post(f"/api/emails/{draft_id}/approve")
    body = client.post(f"/api/emails/{draft_id}/send").json()

    assert body["status"] == "error"
    assert body["error"].startswith("SMTP_SEND_FAILED")
    # Only the exception type is exposed — never the message/credentials.
    assert "SUPER-SECRET-PW" not in json.dumps(body)
    fetched = client.get(f"/api/emails/{draft_id}").json()
    assert "SUPER-SECRET-PW" not in json.dumps(fetched)


def test_no_credentials_in_any_email_response(client, monkeypatch):
    _configure_smtp(monkeypatch)
    monkeypatch.setattr(email_service, "_smtp_send", lambda r, s, b: None)

    draft_id = _manual_draft(client).json()["drafts"][0]["id"]
    client.post(f"/api/emails/{draft_id}/approve")
    client.post(f"/api/emails/{draft_id}/send")

    for payload in (
        client.get("/api/emails").json(),
        client.get(f"/api/emails/{draft_id}").json(),
        client.get("/api/health").json(),
    ):
        dumped = json.dumps(payload)
        assert "SUPER-SECRET-PW" not in dumped
        assert "civic-user" not in dumped


def test_draft_missing_business_reported(client):
    response = client.post("/api/emails/draft", json={
        "business_ids": ["0000000000"], "mode": "manual",
        "subject": "x", "body": "y",
    })
    assert response.json()["errors"][0]["error"] == "BUSINESS_NOT_FOUND"


def test_invalid_purpose_rejected(client):
    response = _manual_draft(client, purpose="spam_everyone")
    assert response.status_code == 422
