from datetime import datetime, date

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Business(Base):
    """Normalized KBO/VKBO source record. Source values are immutable after
    import: enrichment and human corrections live in separate tables."""

    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_uid: Mapped[str | None] = mapped_column(String, index=True)
    # Registry numbers stay strings: leading zeros are significant.
    business_number: Mapped[str] = mapped_column(String, unique=True, index=True)
    parent_enterprise_number: Mapped[str | None] = mapped_column(String, index=True)
    record_type: Mapped[str] = mapped_column(String, index=True)  # ENTERPRISE | ESTABLISHMENT

    legal_name: Mapped[str | None] = mapped_column(String)
    commercial_name: Mapped[str | None] = mapped_column(String)
    short_name: Mapped[str | None] = mapped_column(String)
    search_name: Mapped[str | None] = mapped_column(String)
    display_name: Mapped[str | None] = mapped_column(String, index=True)

    business_type: Mapped[str | None] = mapped_column(String)
    legal_form: Mapped[str | None] = mapped_column(String)
    legal_status: Mapped[str | None] = mapped_column(String, index=True)

    kbo_street: Mapped[str | None] = mapped_column(String, index=True)
    kbo_house_number: Mapped[str | None] = mapped_column(String)
    kbo_bus_number: Mapped[str | None] = mapped_column(String)
    kbo_niscode: Mapped[str | None] = mapped_column(String)
    kbo_postcode: Mapped[str | None] = mapped_column(String, index=True)
    kbo_municipality: Mapped[str | None] = mapped_column(String, index=True)

    address_register_street: Mapped[str | None] = mapped_column(String)
    address_register_house_number: Mapped[str | None] = mapped_column(String)
    address_register_bus_number: Mapped[str | None] = mapped_column(String)
    address_register_postcode: Mapped[str | None] = mapped_column(String)

    phone: Mapped[str | None] = mapped_column(String)
    email: Mapped[str | None] = mapped_column(String)

    nace_vat_code: Mapped[str | None] = mapped_column(String)
    nace_vat_version: Mapped[str | None] = mapped_column(String)
    nace_vat_description: Mapped[str | None] = mapped_column(String)
    nace_rsz_code: Mapped[str | None] = mapped_column(String)
    nace_rsz_version: Mapped[str | None] = mapped_column(String)
    nace_rsz_description: Mapped[str | None] = mapped_column(String)
    employee_class: Mapped[str | None] = mapped_column(String)

    registration_date: Mapped[date | None] = mapped_column(Date)
    start_date: Mapped[date | None] = mapped_column(Date)
    cessation_date: Mapped[date | None] = mapped_column(Date)
    cessation_reason: Mapped[str | None] = mapped_column(String)
    closure_date: Mapped[date | None] = mapped_column(Date)

    official_deregistration_reason: Mapped[str | None] = mapped_column(String)
    official_deregistration_start: Mapped[date | None] = mapped_column(Date)
    official_deregistration_end: Mapped[date | None] = mapped_column(Date)

    address_deregistration_date: Mapped[date | None] = mapped_column(Date)
    address_deregistration_reason: Mapped[str | None] = mapped_column(String)

    annual_accounts_url: Mapped[str | None] = mapped_column(String)

    longitude: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)

    raw_json: Mapped[str | None] = mapped_column(Text)  # original GeoJSON feature properties

    source_dataset: Mapped[str | None] = mapped_column(String)
    source_snapshot_date: Mapped[str | None] = mapped_column(String)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    enrichments: Mapped[list["Enrichment"]] = relationship(back_populates="business")
    overrides: Mapped[list["BusinessOverride"]] = relationship(back_populates="business")


class Enrichment(Base):
    """External evidence (Google Places, business website, derived signals).
    Never merged destructively into the source record."""

    __tablename__ = "enrichments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    provider: Mapped[str] = mapped_column(String, index=True)  # google_places | website | derived
    field_name: Mapped[str] = mapped_column(String, index=True)
    value: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String)
    provider_external_id: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String, default="active", index=True)  # active | superseded | error

    business: Mapped[Business] = relationship(back_populates="enrichments")


class BusinessOverride(Base):
    """Manual officer correction. Wins over enrichment and source in the
    effective view; original KBO values are never mutated."""

    __tablename__ = "business_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    field_name: Mapped[str] = mapped_column(String, index=True)
    old_effective_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    business: Mapped[Business] = relationship(back_populates="overrides")


class EmailDraft(Base):
    __tablename__ = "email_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    recipient: Mapped[str | None] = mapped_column(String)
    subject: Mapped[str | None] = mapped_column(String)
    ai_generated_body: Mapped[str | None] = mapped_column(Text)
    final_body: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String, default="nl")
    purpose: Mapped[str] = mapped_column(String, default="general_contact")
    status: Mapped[str] = mapped_column(String, default="draft", index=True)  # draft | approved | sent | failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class EmailEvent(Base):
    __tablename__ = "email_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("email_drafts.id"), index=True)
    event_type: Mapped[str] = mapped_column(String)
    provider_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
