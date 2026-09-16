"""AI-assisted email drafting.

The model ONLY writes language around factual business context supplied from
the CivicLens database. It must never invent business facts (status, email,
phone, opening hours, addresses). If OpenAI is not configured, callers get a
clean AI_NOT_CONFIGURED result and manual drafting still works.

No "humanizer" tool exists in this environment, so none is used or simulated.
"""

import json
import logging

from app.config import settings
from app.db.models import Business

logger = logging.getLogger(__name__)

PURPOSES = {
    "verify_business_activity",
    "verify_contact_details",
    "request_correction",
    "general_contact",
}

LANGUAGE_NAMES = {"nl": "Dutch", "en": "English"}


def ai_configured() -> bool:
    return bool(settings.openai_api_key)


def build_business_facts(business: Business, effective: dict) -> dict:
    """Only facts that actually exist in the database. Absent facts are
    omitted so the model cannot echo invented values."""
    facts = {
        "business_number": business.business_number,
        "record_type": business.record_type,
        "name": effective.get("display_name"),
        "legal_name": business.legal_name,
        "address": ", ".join(x for x in [
            " ".join(y for y in [business.kbo_street, business.kbo_house_number] if y),
            " ".join(y for y in [business.kbo_postcode, business.kbo_municipality] if y),
        ] if x) or None,
        "known_email": effective.get("email"),
        "known_phone": effective.get("phone"),
        "known_website": effective.get("website"),
        "legal_form": business.legal_form,
        "legal_status": business.legal_status,
    }
    return {k: v for k, v in facts.items() if v}


SYSTEM_PROMPT = """You draft emails for a Belgian municipal local-economy officer (CivicLens).
Rules — non-negotiable:
- Use ONLY the facts in the provided JSON. Never invent or assume business facts:
  no invented email addresses, phone numbers, opening hours, activity status, or addresses.
- If a fact is absent from the JSON, do not mention it or ask the business to provide it.
- Tone: professional, official, natural, concise. No robotic boilerplate, no exaggeration.
- Do not claim the business is active or closed; the purpose of the email is verification.
- Sign as the municipal local economy office (no personal names).
Return strict JSON: {"subject": "...", "body": "..."}"""

PURPOSE_INSTRUCTIONS = {
    "verify_business_activity": "Politely ask whether the business is still operating at the listed address and request confirmation.",
    "verify_contact_details": "Politely ask the business to confirm or correct the contact details the municipality has on file.",
    "request_correction": "Ask the business to review the listed information and reply with any corrections.",
    "general_contact": "Write a general first-contact message from the local economy office.",
}


def generate_draft(business: Business, effective: dict, language: str, purpose: str,
                   instructions: str | None) -> dict:
    """Return {"status": "ok", "subject": ..., "body": ...} or
    {"status": "error", "error": "AI_NOT_CONFIGURED" | message}."""
    if not ai_configured():
        return {"status": "error", "error": "AI_NOT_CONFIGURED"}

    facts = build_business_facts(business, effective)
    user_prompt = (
        f"Language: {LANGUAGE_NAMES.get(language, language)}\n"
        f"Purpose: {PURPOSE_INSTRUCTIONS.get(purpose, purpose)}\n"
        + (f"Officer instructions: {instructions}\n" if instructions else "")
        + f"Business facts (the ONLY facts you may use):\n{json.dumps(facts, ensure_ascii=False)}"
    )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key, timeout=30.0)
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content)
        subject = str(payload.get("subject") or "").strip()
        body = str(payload.get("body") or "").strip()
        if not subject or not body:
            return {"status": "error", "error": "AI returned an empty draft"}
        return {"status": "ok", "subject": subject, "body": body}
    except Exception as exc:
        logger.warning("AI drafting failed for %s: %s", business.business_number, exc)
        return {"status": "error", "error": f"AI drafting failed: {exc}"}
