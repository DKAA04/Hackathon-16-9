"""JSON-friendly data shapes for contact enrichment.

Officer-facing strings (reasons, labels) are Dutch; code and docs are English.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

KBO_ENTERPRISE_URL = "https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html?lang=nl&ondernemingsnummer={}"
KBO_ESTABLISHMENT_URL = "https://kbopub.economie.fgov.be/kbopub/toonvestigingps.html?lang=nl&vestigingsnummer={}"

SOURCE_LABELS = {
    "kbo": "KBO",
    "website": "Website",
    "osm": "OpenStreetMap",
    "google_maps": "Google Maps",
    "web_search": "Webzoekopdracht",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def confidence_level(score: int) -> str:
    return "hoog" if score >= 85 else "middel" if score >= 65 else "laag"


@dataclass
class EnrichTarget:
    """One register record (VKBO enterprise or establishment unit) to enrich."""

    record_id: str
    name: str
    trade_name: str | None = None
    # Legal-entity number that a website would show: own number, or the parent's for establishments.
    enterprise_number: str | None = None
    is_establishment: bool = False
    street: str | None = None
    house_number: str | None = None
    postcode: str | None = None
    municipality: str | None = None
    lat: float | None = None
    lon: float | None = None
    known_phone: str | None = None
    known_email: str | None = None
    known_website: str | None = None
    activity: str | None = None
    flags: list[str] = field(default_factory=list)
    # names learned from confidently matched map listings (OSM / Google)
    aliases: list[str] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        out: list[str] = []
        for n in (self.trade_name, self.name, *self.aliases):
            if n and n.lower() not in (x.lower() for x in out):
                out.append(n)
        return out

    def add_alias(self, name: str | None) -> None:
        if name and name.lower() not in (x.lower() for x in self.names):
            self.aliases.append(name)

    @property
    def display_name(self) -> str:
        return self.trade_name or self.name

    @property
    def address(self) -> str:
        street = " ".join(x for x in (self.street, self.house_number) if x)
        town = " ".join(x for x in (self.postcode, self.municipality) if x)
        return ", ".join(x for x in (street, town) if x)

    @property
    def register_url(self) -> str | None:
        if self.is_establishment and self.record_id.startswith("2"):
            return KBO_ESTABLISHMENT_URL.format(self.record_id)
        if self.enterprise_number:
            return KBO_ENTERPRISE_URL.format(self.enterprise_number)
        return None


@dataclass
class Observation:
    """One place where a value was seen."""

    source: str  # kbo | website | osm | google_maps | web_search
    url: str | None  # where an officer can check it
    snippet: str | None  # text around the value, or the field it came from
    confidence: int  # 0-100: how sure we are that this value belongs to this business
    reason: str  # Dutch, officer-facing
    retrieved_at: str = field(default_factory=now_iso)


@dataclass
class Finding:
    """A proposed value (phone, e-mail, website or status signal) with all its evidence."""

    kind: str  # phone | email | website | signal
    value: str  # E.164 phone, lowercase e-mail, URL, or signal code
    display: str
    confidence: int = 0
    level: str = "laag"
    scope: str = "onbekend"  # vestiging | onderneming | onbekend
    observations: list[Observation] = field(default_factory=list)
    review_status: str = "voorstel"  # the officer turns this into bevestigd / afgewezen

    @property
    def sources(self) -> list[str]:
        return sorted({o.source for o in self.observations})


@dataclass
class SourceRun:
    source: str
    status: str  # ok | geen_resultaat | overgeslagen | fout
    detail: str
    elapsed_ms: int = 0


@dataclass
class EnrichmentResult:
    target: EnrichTarget
    phones: list[Finding]
    emails: list[Finding]
    websites: list[Finding]
    signals: list[Finding]
    identity_proof: list[str]
    sources: list[SourceRun]
    enriched_at: str = field(default_factory=now_iso)

    def best(self, kind: str) -> Finding | None:
        items = {"phone": self.phones, "email": self.emails, "website": self.websites}[kind]
        return items[0] if items else None

    @property
    def summary(self) -> str:
        parts = []
        for label, items in (("telefoon", self.phones), ("e-mail", self.emails), ("website", self.websites)):
            if items:
                parts.append(f"{label}: {items[0].display} ({items[0].level})")
        if not parts:
            return "Geen contactgegevens gevonden."
        return "; ".join(parts)

    def ui_evidence(self) -> list[dict[str, str]]:
        """Items in the frontend's Evidence shape: {label, value, source, status}."""
        out = []
        labels = {"phone": "Telefoon", "email": "E-mail", "website": "Website"}
        for kind, label in labels.items():
            f = self.best(kind)
            if not f:
                continue
            top = f.observations[0]
            source = " + ".join(SOURCE_LABELS.get(s, s) for s in f.sources)
            if top.url:
                source += f" · {top.url}"
            out.append({
                "label": label,
                "value": f"{f.display} (zekerheid {f.level})",
                "source": source,
                "status": "support" if f.level == "hoog" else "warning",
            })
        for s in self.signals:
            top = s.observations[0]
            out.append({
                "label": "Signaal",
                "value": s.display,
                "source": SOURCE_LABELS.get(top.source, top.source) + (f" · {top.url}" if top.url else ""),
                "status": "conflict" if s.value in NEGATIVE_SIGNALS else "support",
            })
        return out

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["target"].update(
            display_name=self.target.display_name,
            address=self.target.address,
            register_url=self.target.register_url,
        )
        data["summary"] = self.summary
        data["best"] = {k: (asdict(f) if (f := self.best(k)) else None) for k in ("phone", "email", "website")}
        data["ui_evidence"] = self.ui_evidence()
        return data


NEGATIVE_SIGNALS = {
    "google_closed_permanently",
    "google_closed_temporarily",
    "osm_disused",
    "website_unreachable",
}
