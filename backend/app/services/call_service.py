"""Outbound AI phone call via ElevenLabs Agents + Twilio.

Safety: every call goes to CALL_TEST_NUMBER, never to the business's own number.
"""
import httpx

from app.config import settings
from app.db.models import Business
from app.services.business_service import format_address

API = "https://api.elevenlabs.io/v1/convai"


def _headers() -> dict:
    return {"xi-api-key": settings.elevenlabs_api_key or ""}


def _error(response: httpx.Response, data: dict) -> str:
    detail = data.get("detail") or data.get("message") or f"HTTP {response.status_code}"
    return str(detail)[:300]


def start_call(business: Business, note: str | None) -> dict:
    if not settings.calls_configured:
        return {"status": "error", "error": "CALLS_NOT_CONFIGURED"}
    body = {
        "agent_id": settings.elevenlabs_agent_id,
        "agent_phone_number_id": settings.elevenlabs_phone_number_id,
        "to_number": settings.call_test_number,
        "conversation_initiation_client_data": {
            "dynamic_variables": {
                "business_name": business.display_name or business.legal_name or "uw onderneming",
                "address": format_address(business) or "onbekend adres",
                "officer_note": note or "geen extra vraag",
            }
        },
    }
    try:
        response = httpx.post(f"{API}/twilio/outbound-call", json=body, headers=_headers(), timeout=30)
        data = response.json()
    except Exception as exc:
        return {"status": "error", "error": f"ELEVENLABS_UNREACHABLE: {type(exc).__name__}"}
    if response.status_code >= 400 or data.get("success") is False:
        return {"status": "error", "error": _error(response, data)}
    return {
        "status": "started",
        "conversation_id": data.get("conversation_id"),
        "call_sid": data.get("callSid"),
        "to_number": settings.call_test_number,
    }


def call_status(conversation_id: str) -> dict:
    try:
        response = httpx.get(f"{API}/conversations/{conversation_id}", headers=_headers(), timeout=20)
        data = response.json()
    except Exception as exc:
        return {"status": "error", "error": f"ELEVENLABS_UNREACHABLE: {type(exc).__name__}"}
    if response.status_code >= 400:
        return {"status": "error", "error": _error(response, data)}
    analysis = data.get("analysis") or {}
    results = analysis.get("data_collection_results") or {}
    return {
        "status": data.get("status"),  # initiated | in-progress | processing | done | failed
        "summary": analysis.get("transcript_summary"),
        "call_successful": analysis.get("call_successful"),
        "collected": {key: (value or {}).get("value") for key, value in results.items()},
        "transcript": [
            {"role": turn.get("role"), "message": turn.get("message")}
            for turn in data.get("transcript") or [] if turn.get("message")
        ],
    }
