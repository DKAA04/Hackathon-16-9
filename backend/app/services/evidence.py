"""Deterministic evidence / review-priority engine.

PROTOTYPE HEURISTIC, NOT OFFICIAL MUNICIPAL SCORING.
This is not a probability that a business is active. It is a transparent,
explainable review-priority signal: every applied rule is returned with its
effect so an officer can see exactly why a record scored the way it did.

Ambiguous signals (no Google result, missing contact data) never lower the
score: absence of evidence is not evidence of absence.
"""

from app.db.models import Business

BASE_SCORE = 50

# Keywords in Rechtstoestand that indicate a legal alert.
LEGAL_ALERT_KEYWORDS = (
    "faillissement",
    "ontbinding",
    "vereffening",
    "gerechtelijke reorganisatie",
    "sluiting",
    "stopzetting",
)

NORMAL_LEGAL_STATUS = "normale toestand"

# Signals that immediately warrant human review regardless of total score.
CRITICAL_CODES = {
    "CESSATION_SIGNAL",
    "LEGAL_STATUS_ALERT",
    "PARENT_LEGAL_STATUS_ALERT",
    "ADDRESS_DEREGISTRATION",
    "GOOGLE_CLOSED_PERMANENTLY",
    "MANUAL_REVIEW_FLAG",
    "MANUAL_MARKED_INACTIVE",
}


def _signal(code: str, effect: int, label_nl: str, label_en: str, detail: str | None = None) -> dict:
    item = {"code": code, "effect": effect, "label_nl": label_nl, "label_en": label_en}
    if detail:
        item["detail"] = detail
    return item


def _address_matches(business: Business) -> bool | None:
    """Compare KBO address with Flemish Address Register fields. None when the
    register side is absent (no evidence either way)."""
    if not (business.address_register_street or business.address_register_postcode):
        return None

    def norm(value):
        return (value or "").strip().lower()

    return (
        norm(business.kbo_street) == norm(business.address_register_street)
        and norm(business.kbo_house_number) == norm(business.address_register_house_number)
        and norm(business.kbo_postcode) == norm(business.address_register_postcode)
    )


def compute_evidence(
    business: Business,
    parent: Business | None,
    enrichment_map: dict[str, dict],
    override_map: dict[str, "object"],
) -> dict:
    """Return evidence list + confidence score/level + review flag.

    enrichment_map: {provider: {field_name: Enrichment}} (active rows only)
    override_map: {field_name: BusinessOverride} (latest per field)
    """
    evidence: list[dict] = []

    evidence.append(_signal(
        "KBO_RECORD", 10,
        "Record aanwezig in de KBO/VKBO-momentopname",
        "Record present in the KBO/VKBO snapshot",
    ))

    # --- Enterprise/establishment structure -------------------------------
    if business.record_type == "ESTABLISHMENT":
        if parent is not None:
            evidence.append(_signal(
                "PARENT_LINK_RESOLVED", 5,
                "Vestiging gekoppeld aan gekende onderneming",
                "Establishment linked to a known parent enterprise",
                f"parent {parent.business_number}",
            ))
            parent_status = (parent.legal_status or "").lower()
            if parent_status == NORMAL_LEGAL_STATUS:
                evidence.append(_signal(
                    "PARENT_STATUS_NORMAL", 5,
                    "Moederonderneming in normale toestand",
                    "Parent enterprise has normal legal status",
                ))
            elif any(k in parent_status for k in LEGAL_ALERT_KEYWORDS):
                evidence.append(_signal(
                    "PARENT_LEGAL_STATUS_ALERT", -30,
                    "Moederonderneming in ontbinding/vereffening/faillissement",
                    "Parent enterprise in dissolution/liquidation/bankruptcy",
                    parent.legal_status,
                ))

    # --- KBO vs Address Register ------------------------------------------
    address_match = _address_matches(business)
    if address_match is True:
        evidence.append(_signal(
            "ADDRESS_MATCH", 15,
            "KBO-adres komt overeen met het Adressenregister",
            "KBO address agrees with the Flemish Address Register",
        ))
    elif address_match is False:
        evidence.append(_signal(
            "ADDRESS_MISMATCH", -15,
            "KBO-adres wijkt af van het Adressenregister",
            "KBO address disagrees with the Flemish Address Register",
        ))

    # --- Own legal status / cessation -------------------------------------
    own_status = (business.legal_status or "").lower()
    if own_status and own_status != NORMAL_LEGAL_STATUS and any(k in own_status for k in LEGAL_ALERT_KEYWORDS):
        evidence.append(_signal(
            "LEGAL_STATUS_ALERT", -30,
            "Rechtstoestand wijst op stopzetting/ontbinding/faillissement",
            "Legal status indicates cessation/dissolution/bankruptcy",
            business.legal_status,
        ))

    if business.cessation_date or business.cessation_reason:
        evidence.append(_signal(
            "CESSATION_SIGNAL", -25,
            "Stopzettingsdatum of -reden aanwezig in de bron",
            "Cessation date or reason present in the source",
            str(business.cessation_date or business.cessation_reason),
        ))

    if business.address_deregistration_date or business.address_deregistration_reason:
        evidence.append(_signal(
            "ADDRESS_DEREGISTRATION", -15,
            "Adresdoorhaling geregistreerd",
            "Address deregistration recorded",
            str(business.address_deregistration_date or business.address_deregistration_reason),
        ))

    # --- Google Places evidence -------------------------------------------
    google = enrichment_map.get("google_places", {})
    google_status_row = google.get("business_status")
    if google_status_row is not None:
        status = (google_status_row.value or "UNKNOWN").upper()
        match_confidence = google_status_row.confidence or 0.0
        if status == "OPERATIONAL" and match_confidence >= 0.6:
            evidence.append(_signal(
                "GOOGLE_MATCH_OPERATIONAL", 15,
                "Sterke Google Places-match, status operationeel",
                "Strong Google Places match, status operational",
            ))
        elif status == "CLOSED_PERMANENTLY" and match_confidence >= 0.6:
            evidence.append(_signal(
                "GOOGLE_CLOSED_PERMANENTLY", -25,
                "Google Places meldt definitief gesloten (sterke match)",
                "Google Places reports permanently closed (strong match)",
            ))
        elif status == "UNKNOWN":
            # Ambiguous: no Google result must never mean inactive.
            evidence.append(_signal(
                "GOOGLE_NO_RESULT", 0,
                "Geen betrouwbaar Google Places-resultaat (geen bewijs van sluiting)",
                "No reliable Google Places result (not evidence of closure)",
            ))
        else:
            evidence.append(_signal(
                "GOOGLE_STATUS_OTHER", 0,
                f"Google Places status: {status}",
                f"Google Places status: {status}",
            ))

    other_here = google.get("other_business_at_address")
    if other_here is not None:
        evidence.append(_signal(
            "GOOGLE_OTHER_BUSINESS_AT_ADDRESS", -10,
            f"Google toont een andere zaak op dit adres: {other_here.value}",
            f"Google shows a different business at this address: {other_here.value}",
        ))
    other_near = google.get("other_business_nearby")
    if other_near is not None:
        evidence.append(_signal(
            "GOOGLE_OTHER_BUSINESS_NEARBY", 0,
            f"Geen eigen Google-vermelding; wel een andere zaak in de buurt: {other_near.value}",
            f"No own Google listing; a different business nearby: {other_near.value}",
        ))

    # --- Website evidence ---------------------------------------------------
    website = enrichment_map.get("website", {})
    if google.get("website") or website:
        evidence.append(_signal(
            "WEBSITE_FOUND", 5,
            "Website gevonden voor deze onderneming",
            "Website found for this business",
        ))
    if website.get("email") or website.get("phone"):
        evidence.append(_signal(
            "CONTACT_CONFIRMED_BY_WEBSITE", 5,
            "Contactgegevens bevestigd op de eigen website",
            "Contact details confirmed on the business website",
        ))

    # --- Manual officer signals --------------------------------------------
    activity_override = override_map.get("activity_status")
    if activity_override is not None:
        value = (activity_override.new_value or "").lower()
        if value in {"inactive", "closed", "stopgezet"}:
            evidence.append(_signal(
                "MANUAL_MARKED_INACTIVE", -40,
                "Handmatig gemarkeerd als niet actief",
                "Manually marked as not active",
            ))
        elif value in {"review", "needs_review"}:
            evidence.append(_signal(
                "MANUAL_REVIEW_FLAG", -20,
                "Handmatig gemarkeerd voor controle",
                "Manually flagged for review",
            ))
        elif value in {"active", "actief", "verified"}:
            evidence.append(_signal(
                "MANUAL_CONFIRMED_ACTIVE", 20,
                "Handmatig bevestigd als actief",
                "Manually confirmed active",
            ))

    score = max(0, min(100, BASE_SCORE + sum(item["effect"] for item in evidence)))
    level = "HIGH" if score >= 75 else "MEDIUM" if score >= 50 else "LOW"
    review_required = score < 50 or any(item["code"] in CRITICAL_CODES for item in evidence)

    return {
        "evidence": evidence,
        "confidence_score": score,
        "confidence_level": level,
        "review_required": review_required,
    }
