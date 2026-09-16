from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Business, EmailDraft
from app.services import ai_service, email_service
from app.services.ai_service import PURPOSES
from app.services.business_service import (
    build_effective,
    get_business_by_public_id,
    load_enrichment_map,
    load_override_map,
)

router = APIRouter(prefix="/api", tags=["emails"])

DRAFT_BATCH_CAP = 20


class DraftRequest(BaseModel):
    business_ids: list[str] = Field(min_length=1, max_length=DRAFT_BATCH_CAP)
    mode: str = Field(default="ai", pattern="^(ai|manual)$")
    language: str = Field(default="nl", pattern="^(nl|en)$")
    purpose: str = "verify_business_activity"
    instructions: str | None = None  # AI mode: officer guidance
    subject: str | None = None       # manual mode
    body: str | None = None          # manual mode
    recipient: str | None = None     # defaults to the effective email if known


class UpdateRequest(BaseModel):
    recipient: str | None = None
    subject: str | None = None
    body: str | None = None


def _effective_for(db: Session, business: Business) -> dict:
    enrichment_map = load_enrichment_map(db, [business.id]).get(business.id, {})
    override_map = load_override_map(db, [business.id]).get(business.id, {})
    return build_effective(business, enrichment_map, override_map)


def _get_draft(db: Session, draft_id: int) -> EmailDraft:
    draft = db.query(EmailDraft).filter(EmailDraft.id == draft_id).first()
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


def _business_number(db: Session, draft: EmailDraft) -> str | None:
    business = db.query(Business).filter(Business.id == draft.business_id).first()
    return business.business_number if business else None


@router.post("/emails/draft")
def create_drafts(body: DraftRequest, db: Session = Depends(get_db)):
    if body.purpose not in PURPOSES:
        raise HTTPException(status_code=422, detail=f"purpose must be one of {sorted(PURPOSES)}")
    if body.mode == "manual" and not (body.subject and body.body):
        raise HTTPException(status_code=422, detail="manual mode requires subject and body")

    drafts, errors = [], []
    for business_id in body.business_ids:
        business = get_business_by_public_id(db, business_id)
        if business is None:
            errors.append({"business_id": business_id, "error": "BUSINESS_NOT_FOUND"})
            continue

        effective = _effective_for(db, business)
        recipient = body.recipient or effective.get("email")

        if body.mode == "manual":
            subject, final_body, ai_body = body.subject, body.body, None
        else:
            result = ai_service.generate_draft(
                business, effective, body.language, body.purpose, body.instructions)
            if result["status"] != "ok":
                errors.append({"business_id": business_id, "error": result["error"]})
                continue
            subject, final_body, ai_body = result["subject"], result["body"], result["body"]

        draft = email_service.create_draft(
            db, business,
            recipient=recipient, subject=subject, body=final_body,
            ai_generated_body=ai_body, language=body.language,
            purpose=body.purpose, mode=body.mode,
        )
        drafts.append(email_service.serialize_draft(db, draft, business.business_number))

    return {"drafts": drafts, "errors": errors}


@router.post("/emails/{draft_id}/update")
def update_draft(draft_id: int, body: UpdateRequest, db: Session = Depends(get_db)):
    draft = _get_draft(db, draft_id)
    if draft.status == "sent":
        raise HTTPException(status_code=409, detail="Draft already sent")
    draft = email_service.update_draft(
        db, draft, recipient=body.recipient, subject=body.subject, body=body.body)
    return email_service.serialize_draft(db, draft, _business_number(db, draft))


@router.post("/emails/{draft_id}/approve")
def approve_draft(draft_id: int, db: Session = Depends(get_db)):
    draft = _get_draft(db, draft_id)
    if draft.status == "sent":
        raise HTTPException(status_code=409, detail="Draft already sent")
    draft = email_service.approve_draft(db, draft)
    return email_service.serialize_draft(db, draft, _business_number(db, draft))


@router.post("/emails/{draft_id}/send")
def send_draft(draft_id: int, db: Session = Depends(get_db)):
    draft = _get_draft(db, draft_id)
    result = email_service.send_draft(db, draft)
    return {
        **result,
        "draft": email_service.serialize_draft(db, draft, _business_number(db, draft)),
    }


@router.get("/emails")
def list_drafts(
    status: str | None = None,
    business_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    query = db.query(EmailDraft)
    if status:
        query = query.filter(EmailDraft.status == status)
    if business_id:
        business = get_business_by_public_id(db, business_id)
        query = query.filter(EmailDraft.business_id == (business.id if business else -1))
    total = query.count()
    rows = (
        query.order_by(EmailDraft.created_at.desc(), EmailDraft.id.desc())
        .offset(max(offset, 0)).limit(min(max(limit, 1), 200)).all()
    )
    return {
        "results": [email_service.serialize_draft(db, d, _business_number(db, d)) for d in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/emails/{draft_id}")
def get_draft(draft_id: int, db: Session = Depends(get_db)):
    draft = _get_draft(db, draft_id)
    return email_service.serialize_draft(db, draft, _business_number(db, draft))
