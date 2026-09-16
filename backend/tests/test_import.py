from app.db.database import SessionLocal
from app.db.models import Business
from app.services.kbo_import import clean, parse_date, run_import


def test_import_loads_exactly_1000(imported, db):
    assert imported["source_features"] == 1000
    assert db.query(Business).count() == 1000


def test_import_is_idempotent(imported, db):
    stats = run_import(db)
    assert db.query(Business).count() == 1000
    assert stats["inserted"] == 0


def test_csv_sanity_check_matches(imported):
    check = imported["csv_check"]
    assert check["csv_available"] is True
    assert check["match"] is True
    assert check["csv_unique_numbers"] == 1000


def test_registry_numbers_remain_strings_with_leading_zero(db):
    row = db.query(Business).filter(Business.business_number == "0415708742").first()
    assert row is not None
    assert isinstance(row.business_number, str)
    assert row.business_number.startswith("0")


def test_whitespace_only_becomes_none(db):
    assert clean("  ") is None
    assert clean("") is None
    assert clean(None) is None
    assert clean(" x ") == "x"
    # Real record: FOOTBALL CLUB KONINGSHOF has whitespace-only Commerciele_naam
    row = db.query(Business).filter(Business.business_number == "0415708742").first()
    assert row.commercial_name is None


def test_sentinel_dates_become_none():
    assert parse_date("1900-01-01T00:00:00Z") is None
    assert parse_date("9999-12-31T00:00:00Z") is None
    assert parse_date(" ") is None
    assert str(parse_date("2019-02-25T00:00:00Z")) == "2019-02-25"


def test_establishment_classification_matches_metadata(db):
    # source-metadata.json: 457 legal entity rows, 543 establishment rows
    enterprises = db.query(Business).filter(Business.record_type == "ENTERPRISE").count()
    establishments = db.query(Business).filter(Business.record_type == "ESTABLISHMENT").count()
    assert enterprises == 457
    assert establishments == 543


def test_establishment_exposes_parent_number(db):
    row = db.query(Business).filter(Business.business_number == "2285533695").first()
    assert row is not None
    assert row.record_type == "ESTABLISHMENT"
    assert row.parent_enterprise_number == "0719273014"


def test_enterprise_has_no_parent(db):
    row = db.query(Business).filter(Business.business_number == "0415708742").first()
    assert row.record_type == "ENTERPRISE"
    assert row.parent_enterprise_number is None
