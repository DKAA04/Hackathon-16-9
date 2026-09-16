from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services import call_service
from app.services.business_service import get_business_by_public_id

router = APIRouter(prefix="/api", tags=["calls"])


class CallRequest(BaseModel):
    note: str | None = None


@router.post("/businesses/{business_id}/call")
def call_business(business_id: str, body: CallRequest, db: Session = Depends(get_db)):
    """Start an AI phone call about this business (always to CALL_TEST_NUMBER)."""
    business = get_business_by_public_id(db, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    result = call_service.start_call(business, body.note)
    if result["status"] == "error":
        code = 503 if result["error"] == "CALLS_NOT_CONFIGURED" else 502
        raise HTTPException(status_code=code, detail={"error": result["error"]})
    return result


@router.get("/calls/{conversation_id}")
def get_call(conversation_id: str):
    result = call_service.call_status(conversation_id)
    if result["status"] == "error":
        raise HTTPException(status_code=502, detail={"error": result["error"]})
    return result
