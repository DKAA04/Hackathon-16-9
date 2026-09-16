"""Natural-language → validated CivicLens filters.

The LLM's ONLY job is to translate an officer's sentence into a structured
filter object. The output is Pydantic-validated against a strict allowlist
and then fed into the existing query_businesses() service, which uses bound
SQLAlchemy parameters. The model can never produce SQL, table names or raw
expressions that reach the database: unknown keys are discarded, enum values
are allowlisted, and free-text values are only ever used as bound parameters.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from app.services import ai_service
from app.services.business_service import query_businesses

MAX_LIMIT = 100


class QueryFilters(BaseModel):
    """Strict allowlist of filters the model may produce. Anything else is
    dropped before validation; invalid enum values raise a structured error."""

    model_config = ConfigDict(extra="forbid")

    query: str | None = None
    street: str | None = None
    postcode: str | None = None
    municipality: str | None = None
    record_type: Literal["ENTERPRISE", "ESTABLISHMENT"] | None = None
    legal_status: str | None = None
    has_email: bool | None = None
    has_phone: bool | None = None
    has_website: bool | None = None
    google_status: Literal[
        "OPERATIONAL", "CLOSED_TEMPORARILY", "CLOSED_PERMANENTLY",
        "FUTURE_OPENING", "UNKNOWN", "NOT_CHECKED",
    ] | None = None
    review_required: bool | None = None
    confidence_min: int | None = Field(default=None, ge=0, le=100)
    confidence_max: int | None = Field(default=None, ge=0, le=100)
    limit: int | None = Field(default=None, ge=1, le=MAX_LIMIT)
    offset: int | None = Field(default=None, ge=0)

    @field_validator("record_type", "google_status", mode="before")
    @classmethod
    def _uppercase_enums(cls, value):
        return value.upper() if isinstance(value, str) else value

    @field_validator("query", "street", "postcode", "municipality", "legal_status", mode="before")
    @classmethod
    def _strip_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


ALLOWED_FIELDS = set(QueryFilters.model_fields)


class QueryInterpretationError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def validate_model_output(raw: dict) -> tuple[QueryFilters, list[str]]:
    """Drop unknown keys (reported back as ignored_fields), then strictly
    validate the remainder."""
    if not isinstance(raw, dict):
        raise QueryInterpretationError("INVALID_INTERPRETATION", "model output was not an object")

    ignored = sorted(k for k in raw if k not in ALLOWED_FIELDS)
    candidate = {k: v for k, v in raw.items() if k in ALLOWED_FIELDS}

    try:
        filters = QueryFilters(**candidate)
    except ValidationError as exc:
        raise QueryInterpretationError(
            "INVALID_INTERPRETATION",
            "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()),
        ) from exc
    return filters, ignored


def run_natural_language_query(db: Session, text: str) -> dict:
    """Interpret the officer's sentence and run the normal business query.
    Raises QueryInterpretationError with codes AI_NOT_CONFIGURED /
    AI_INTERPRETATION_FAILED / INVALID_INTERPRETATION."""
    parsed = ai_service.parse_query_filters(text)
    if parsed["status"] != "ok":
        code = parsed["error"] if parsed["error"] == "AI_NOT_CONFIGURED" else "AI_INTERPRETATION_FAILED"
        raise QueryInterpretationError(code, parsed["error"])

    filters, ignored = validate_model_output(parsed["raw"])
    filter_dict = filters.model_dump(exclude_none=True)

    query_filters = dict(filter_dict)
    query_filters.setdefault("limit", 50)
    query_filters.setdefault("offset", 0)

    result = query_businesses(db, query_filters)
    return {
        "original_query": text,
        "interpreted_filters": filter_dict,
        "ignored_fields": ignored,
        "results": result["results"],
        "total": result["total"],
        "limit": result["limit"],
        "offset": result["offset"],
    }
