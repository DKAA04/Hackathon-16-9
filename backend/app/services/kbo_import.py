"""Idempotent importer for the supplied KBO/VKBO snapshot.

The GeoJSON is the canonical source (full API response, incl. contact,
cessation and address-deregistration fields plus geometry). The CSV is only
used as a sanity check. Original files are never modified.
"""

import csv
import json
import logging
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import CSV_PATH, GEOJSON_PATH, METADATA_PATH
from app.db.models import Business

logger = logging.getLogger(__name__)

# VKBO uses sentinel dates for "not applicable".
SENTINEL_DATES = {"1900-01-01", "9999-12-31"}


def clean(value) -> str | None:
    """Trim whitespace; whitespace-only becomes None. Keeps strings as strings
    (registry numbers keep leading zeros)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_date(value) -> date | None:
    text = clean(value)
    if not text:
        return None
    day = text[:10]
    if day in SENTINEL_DATES:
        return None
    try:
        return date.fromisoformat(day)
    except ValueError:
        logger.warning("Unparseable date value: %r", value)
        return None


def load_metadata(metadata_path: Path | None = None) -> dict:
    path = metadata_path or METADATA_PATH
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def normalize_feature(feature: dict, source_dataset: str, snapshot_date: str | None) -> dict:
    props = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates") if geometry.get("type") == "Point" else None

    longitude = latitude = None
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        try:
            longitude = float(coords[0])
            latitude = float(coords[1])
        except (TypeError, ValueError):
            longitude = latitude = None

    business_number = clean(props.get("Ondernemingsnr"))
    parent_number = clean(props.get("Ondernemingsnr_maatsch_zetel"))

    # ESTABLISHMENT (vestigingseenheid) when it points to a parent enterprise,
    # otherwise the record is the enterprise / legal entity itself.
    record_type = "ESTABLISHMENT" if parent_number else "ENTERPRISE"

    legal_name = clean(props.get("Maatschappelijke_naam"))
    commercial_name = clean(props.get("Commerciele_naam"))
    short_name = clean(props.get("Afgekorte_naam"))
    search_name = clean(props.get("Zoeknaam"))
    display_name = commercial_name or legal_name or search_name or short_name or business_number

    return {
        "source_uid": clean(props.get("UIDN")),
        "business_number": business_number,
        "parent_enterprise_number": parent_number,
        "record_type": record_type,
        "legal_name": legal_name,
        "commercial_name": commercial_name,
        "short_name": short_name,
        "search_name": search_name,
        "display_name": display_name,
        "business_type": clean(props.get("Type_onderneming")),
        "legal_form": clean(props.get("Rechtsvorm")),
        "legal_status": clean(props.get("Rechtstoestand")),
        "kbo_street": clean(props.get("KBO_Straat")),
        "kbo_house_number": clean(props.get("KBO_Huisnr")),
        "kbo_bus_number": clean(props.get("KBO_Busnr")),
        "kbo_niscode": clean(props.get("KBO_NISCODE")),
        "kbo_postcode": clean(props.get("KBO_Postcode")),
        "kbo_municipality": clean(props.get("KBO_Gemeente")),
        "address_register_street": clean(props.get("AR_straat")),
        "address_register_house_number": clean(props.get("AR_huisnr")),
        "address_register_bus_number": clean(props.get("AR_busnr")),
        "address_register_postcode": clean(props.get("AR_postcode")),
        "phone": clean(props.get("Telefoonnummer")),
        "email": clean(props.get("Email")),
        "nace_vat_code": clean(props.get("NACE_hoofdact_BTW")),
        "nace_vat_version": clean(props.get("NACE_versie_BTW")),
        "nace_vat_description": clean(props.get("Omschrijving_hoofdact_BTW")),
        "nace_rsz_code": clean(props.get("NACE_hoofdact_RSZ")),
        "nace_rsz_version": clean(props.get("NACE_Versie_RSZ")),
        "nace_rsz_description": clean(props.get("Omschrijving_hoofdact_RSZ")),
        "employee_class": clean(props.get("Personeelsklasse")),
        "registration_date": parse_date(props.get("Datum_inschrijving")),
        "start_date": parse_date(props.get("Startdatum")),
        "cessation_date": parse_date(props.get("Datum_stopzetting")),
        "cessation_reason": clean(props.get("Reden_stopzetting")),
        "closure_date": parse_date(props.get("Datum_afsluiting")),
        "official_deregistration_reason": clean(props.get("Reden_ambtsh_doorhaling")),
        "official_deregistration_start": parse_date(props.get("Begindat_ambtsh_doorhaling")),
        "official_deregistration_end": parse_date(props.get("Einddat_ambtsh_doorhaling")),
        "address_deregistration_date": parse_date(props.get("Datum_adresdoorhaling")),
        "address_deregistration_reason": clean(props.get("Reden_adresdoorhaling")),
        "annual_accounts_url": clean(props.get("JAARREK_URL_NBB")),
        "longitude": longitude,
        "latitude": latitude,
        "raw_json": json.dumps(props, ensure_ascii=False),
        "source_dataset": source_dataset,
        "source_snapshot_date": snapshot_date,
    }


def sanity_check_csv(csv_path: Path, imported_numbers: set[str]) -> dict:
    """Compare imported business numbers against the flattened CSV reference."""
    check: dict = {"csv_available": csv_path.exists()}
    if not csv_path.exists():
        return check
    try:
        with open(csv_path, encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        csv_numbers = {clean(r.get("Ondernemingsnr")) for r in rows}
        csv_numbers.discard(None)
        check["csv_rows"] = len(rows)
        check["csv_unique_numbers"] = len(csv_numbers)
        check["missing_in_db"] = sorted(csv_numbers - imported_numbers)[:10]
        check["match"] = csv_numbers == imported_numbers
    except Exception as exc:  # sanity check must never break the import
        check["error"] = str(exc)
    return check


def run_import(
    db: Session,
    geojson_path: Path | None = None,
    csv_path: Path | None = None,
    metadata_path: Path | None = None,
) -> dict:
    """Insert/update source businesses from the GeoJSON snapshot.

    Idempotent: keyed on business_number, so re-running never duplicates rows.
    """
    geojson_path = geojson_path or GEOJSON_PATH
    csv_path = csv_path or CSV_PATH

    metadata = load_metadata(metadata_path)
    source_dataset = metadata.get("dataset") or geojson_path.name
    snapshot_date = metadata.get("retrieved_on")

    payload = json.loads(geojson_path.read_text(encoding="utf-8"))
    features = payload.get("features") or []

    existing = {b.business_number: b for b in db.query(Business).all()}

    inserted = updated = skipped = 0
    errors: list[str] = []
    seen: set[str] = set()

    for index, feature in enumerate(features):
        try:
            data = normalize_feature(feature, source_dataset, snapshot_date)
            number = data["business_number"]
            if not number or number in seen:
                skipped += 1
                continue
            seen.add(number)

            row = existing.get(number)
            if row is None:
                db.add(Business(**data, imported_at=datetime.utcnow()))
                inserted += 1
            else:
                changed = False
                for key, value in data.items():
                    if getattr(row, key) != value:
                        setattr(row, key, value)
                        changed = True
                if changed:
                    row.imported_at = datetime.utcnow()
                    updated += 1
                else:
                    skipped += 1
        except Exception as exc:  # flag the row, keep importing the rest
            errors.append(f"feature[{index}]: {exc}")

    db.commit()

    total = db.query(Business).count()
    stats = {
        "source_features": len(features),
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "business_count": total,
        "csv_check": sanity_check_csv(csv_path, seen),
        "dataset": {
            "name": source_dataset,
            "snapshot_date": snapshot_date,
            "source": metadata.get("source_url"),
        },
    }
    logger.info("KBO import finished: %s", {k: stats[k] for k in ("inserted", "updated", "skipped", "business_count")})
    return stats
