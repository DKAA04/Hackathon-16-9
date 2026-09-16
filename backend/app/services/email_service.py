"""Email draft/approve/send workflow.

- Drafting always works, with or without AI or SMTP.
- Sending is provider-neutral SMTP, refuses unapproved drafts, and fails
  cleanly with EMAIL_PROVIDER_NOT_CONFIGURED when SMTP is absent.
- Credentials never appear in responses, events or logs.
"""

import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Business, EmailDraft, EmailEvent

logger = logging.getLogger(__name__)

SENDABLE_STATUS = "approved"


def add_event(db: Session, draft: EmailDraft, event_type: str, message: str | None = None) -> None:
    db.add(EmailEvent(draft_id=draft.id, event_type=event_type, provider_message=message))


def create_draft(
    db: Session,
    business: Business,
    *,
    recipient: str | None,
    subject: str | None,
    body: str | None,
    ai_generated_body: str | None,
    language: str,
    purpose: str,
    mode: str,
) -> EmailDraft:
    draft = EmailDraft(
        business_id=business.id,
        recipient=recipient,
        subject=subject,
        ai_generated_body=ai_generated_body,
        final_body=body,
        language=language,
        purpose=purpose,
        status="draft",
    )
    db.add(draft)
    db.commit()
    add_event(db, draft, "created", f"mode={mode}")
    db.commit()
    return draft


def update_draft(db: Session, draft: EmailDraft, *, recipient: str | None,
                 subject: str | None, body: str | None) -> EmailDraft:
    changed = []
    if recipient is not None:
        draft.recipient = recipient
        changed.append("recipient")
    if subject is not None:
        draft.subject = subject
        changed.append("subject")
    if body is not None:
        draft.final_body = body  # original AI draft stays in ai_generated_body
        changed.append("body")
    if changed and draft.status == "approved":
        # Any edit invalidates a previous approval.
        draft.status = "draft"
        draft.approved_at = None
        changed.append("approval_reset")
    add_event(db, draft, "updated", ",".join(changed) or "no-op")
    db.commit()
    return draft


def approve_draft(db: Session, draft: EmailDraft) -> EmailDraft:
    draft.status = "approved"
    draft.approved_at = datetime.utcnow()
    add_event(db, draft, "approved")
    db.commit()
    return draft


def _smtp_send(recipient: str, subject: str, body: str) -> None:
    """Provider-neutral SMTP send. Isolated for test mocking. Raises on failure."""
    message = EmailMessage()
    message["From"] = formataddr((settings.smtp_from_name, settings.smtp_from_email))
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    # 30s: AV/proxy interceptors (e.g. AVG Mail Shield) can take >15s to
    # deliver their real error response; a shorter timeout masks it as a
    # generic disconnect.
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        server.ehlo()
        try:
            server.starttls()
            server.ehlo()
        except smtplib.SMTPNotSupportedError:
            pass  # plain connection (e.g. local dev relay)
        if settings.smtp_username and settings.smtp_password:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


def send_draft(db: Session, draft: EmailDraft) -> dict:
    """Send an APPROVED draft. Returns a structured result, never crashes."""
    if draft.status == "sent":
        return {"status": "error", "error": "DRAFT_ALREADY_SENT"}
    if draft.status != SENDABLE_STATUS:
        return {"status": "error", "error": "DRAFT_NOT_APPROVED"}
    if not draft.recipient:
        return {"status": "error", "error": "NO_RECIPIENT"}
    if not (draft.subject and draft.final_body):
        return {"status": "error", "error": "DRAFT_INCOMPLETE"}

    if not settings.smtp_configured:
        add_event(db, draft, "send_failed", "EMAIL_PROVIDER_NOT_CONFIGURED")
        db.commit()
        return {"status": "error", "error": "EMAIL_PROVIDER_NOT_CONFIGURED"}

    try:
        _smtp_send(draft.recipient, draft.subject, draft.final_body)
    except Exception as exc:
        # Never leak credentials: log/store the exception type only.
        reason = f"SMTP_SEND_FAILED: {type(exc).__name__}"
        logger.warning("Email send failed for draft %s: %s", draft.id, reason)
        add_event(db, draft, "send_failed", reason)
        db.commit()
        return {"status": "error", "error": reason}

    draft.status = "sent"
    draft.sent_at = datetime.utcnow()
    add_event(db, draft, "sent", "smtp:ok")
    db.commit()
    return {"status": "sent", "sent_at": draft.sent_at.isoformat()}


def serialize_draft(db: Session, draft: EmailDraft, business_number: str | None = None) -> dict:
    events = (
        db.query(EmailEvent)
        .filter(EmailEvent.draft_id == draft.id)
        .order_by(EmailEvent.created_at, EmailEvent.id)
        .all()
    )
    return {
        "id": draft.id,
        "business_id": business_number,
        "recipient": draft.recipient,
        "subject": draft.subject,
        "ai_generated_body": draft.ai_generated_body,
        "final_body": draft.final_body,
        "language": draft.language,
        "purpose": draft.purpose,
        "status": draft.status,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "approved_at": draft.approved_at.isoformat() if draft.approved_at else None,
        "sent_at": draft.sent_at.isoformat() if draft.sent_at else None,
        "events": [
            {
                "event_type": e.event_type,
                "provider_message": e.provider_message,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }
