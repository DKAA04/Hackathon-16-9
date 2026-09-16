from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.query_service import QueryInterpretationError, run_natural_language_query

router = APIRouter(prefix="/api", tags=["query"])


class NaturalLanguageQuery(BaseModel):
    query: str = Field(min_length=1, max_length=500)


@router.post("/query")
def natural_language_query(body: NaturalLanguageQuery, db: Session = Depends(get_db)):
    """Natural language (nl/en) → validated filters → normal business query.
    The model never generates SQL; only allowlisted filters reach the DB."""
    try:
        return run_natural_language_query(db, body.query)
    except QueryInterpretationError as exc:
        if exc.code == "AI_NOT_CONFIGURED":
            raise HTTPException(status_code=503, detail={"error": "AI_NOT_CONFIGURED"})
        raise HTTPException(status_code=422, detail={"error": exc.code, "message": exc.message})
