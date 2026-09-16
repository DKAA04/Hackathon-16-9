"""Crawl a candidate website, check that it belongs to the business, and collect contact details."""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from . import matching as m
from .extract import ParsedPage, format_kbo, parse_page
from .models import EnrichTarget
from .net import FetchError, Fetcher

CONTACT_HINTS = (
    ("contact", 10), ("impressum", 9), ("colofon", 8), ("juridisch", 8), ("wettelijke", 8), ("disclaimer", 7),
    ("privacy", 6), ("voorwaarden", 6), ("bereikbaar", 5), ("vind-ons", 5), ("over-ons", 5), ("over ons", 5),
    ("about", 4), ("openingsuren", 4), ("praktisch", 4), ("route", 3), ("locatie", 3),
)
SKIP_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip", ".doc", ".docx", ".mp4")
CONFIRMED = 70  # identity score from which the site itself proves it belongs to the business
UNCONFIRMED_CONTACT_CAP = 55  # contacts from a site that does not prove that stay "laag"


@dataclass
class SiteContact:
    value: str
    display: str
    page_url: str
    snippet: str
    via: str
    on_contact_page: bool
    near_address: bool = False  # the establishment's street is the one written next to it


@dataclass
class SiteReport:
    start_url: str
    origin: str  # how the URL was found (Dutch)
    origin_confidence: int = 0  # how sure that source is that the URL belongs to the business
    pages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    identity: int = 0  # how sure the site itself makes us
    proof: str = "identiteit niet bevestigd"
    proof_url: str | None = None
    kbo_found: bool = False
    other_kbo: list[str] = field(default_factory=list)
    address_found: bool = False
    phones: list[SiteContact] = field(default_factory=list)
    emails: list[SiteContact] = field(default_factory=list)

    @property
    def reachable(self) -> bool:
        return bool(self.pages)

    @property
    def site_url(self) -> str:
        return self.pages[0] if self.pages else self.start_url

    @property
    def confirmed(self) -> bool:
        return self.reachable and self.identity >= CONFIRMED

    @property
    def confidence(self) -> int:
        """Confidence that this site is the business's site."""
        if not self.reachable:
            return 0
        vouched = self.origin_confidence - 10 if self.origin_confidence else 0
        if self.confirmed:
            return max(self.identity, vouched)
        # a map source links to it, but the site itself never names the business (e.g. a brand's office locator)
        return min(max(self.identity, vouched), 65)


def contact_rank(url: str, label: str) -> int:
    haystack = (urlsplit(url).path + " " + label).lower()
    return max((weight for hint, weight in CONTACT_HINTS if hint in haystack), default=0)


def _contact_links(page: ParsedPage, site_domain: str, limit: int) -> list[str]:
    ranked: dict[str, int] = {}
    for url, label in page.links:
        clean = url.split("#")[0]
        if m.registrable_domain(clean) != site_domain or clean.lower().endswith(SKIP_EXTENSIONS):
            continue
        if (rank := contact_rank(clean, label)) and rank > ranked.get(clean, 0):
            ranked[clean] = rank
    return [u for u, _ in sorted(ranked.items(), key=lambda kv: -kv[1])][:limit]


def crawl(fetcher: Fetcher, start_url: str, target: EnrichTarget, origin: str,
          origin_confidence: int = 0, max_pages: int = 5) -> SiteReport:
    report = SiteReport(start_url=start_url, origin=origin, origin_confidence=origin_confidence)
    exclude = [n for n in (target.enterprise_number, target.record_id) if n]
    root = f"{urlsplit(start_url).scheme}://{urlsplit(start_url).netloc}/"
    queue = [start_url] + ([root] if root.rstrip("/") != start_url.rstrip("/") else [])
    seen: set[str] = set()
    parsed: list[tuple[ParsedPage, bool]] = []
    site_domain = m.registrable_domain(start_url)

    while queue and len(parsed) < max_pages:
        url = queue.pop(0)
        key = url.split("#")[0].rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            page = fetcher.get(url)
        except FetchError as exc:
            report.errors.append(str(exc))
            continue
        if not parsed:  # follow the domain the site actually lives on after redirects
            site_domain = m.registrable_domain(page.url)
        elif m.registrable_domain(page.url) != site_domain:
            continue
        page_data = parse_page(page.text, page.url, exclude)
        parsed.append((page_data, contact_rank(page.url, "") > 0))
        report.pages.append(page.url)
        for link in _contact_links(page_data, site_domain, max_pages):
            if link.rstrip("/").lower() not in seen and link not in queue:
                queue.append(link)

    _judge_identity(report, parsed, target)
    _collect_contacts(report, parsed, target)
    return report


def _judge_identity(report: SiteReport, parsed: list[tuple[ParsedPage, bool]], target: EnrichTarget) -> None:
    kbo = target.enterprise_number
    name_found = False
    town_found = False
    other: set[str] = set()
    for page, _ in parsed:
        if kbo and kbo in page.enterprise_numbers and not report.kbo_found:
            report.kbo_found = True
            report.proof = f"ondernemingsnummer {format_kbo(kbo)} staat op de website"
            report.proof_url = page.url
        other.update(n for n in page.enterprise_numbers if n != kbo)
        text_norm = m.normalize_text(page.title + " " + page.text)
        name_found = name_found or m.name_on_page(target.names, text_norm, page.title)
        full, town = m.address_on_page(text_norm, target.street, target.house_number,
                                       target.postcode, target.municipality)
        if full and not report.address_found:
            report.address_found = True
            if not report.kbo_found:
                report.proof_url = page.url
        town_found = town_found or town

    report.other_kbo = sorted(other)
    if report.kbo_found:
        report.identity = 95
        return
    if report.address_found and name_found:
        report.identity, report.proof = 88, "naam en adres staan op de website"
    elif report.address_found:
        report.identity, report.proof = 80, "het KBO-adres staat op de website"
    elif town_found and name_found:
        report.identity, report.proof = 70, "naam en gemeente/postcode staan op de website"
    elif name_found:
        report.identity, report.proof = 45, "enkel de naam staat op de website"
    elif parsed:
        report.identity, report.proof = 20, "naam en adres niet teruggevonden op de website"
    if report.other_kbo and kbo:
        report.identity = min(report.identity, 50)
        numbers = ", ".join(format_kbo(n) for n in report.other_kbo[:3])
        report.proof += f"; let op: ander ondernemingsnummer op de site ({numbers})"


def _collect_contacts(report: SiteReport, parsed: list[tuple[ParsedPage, bool]], target: EnrichTarget) -> None:
    seen_phone: set[tuple[str, str]] = set()
    seen_email: set[tuple[str, str]] = set()
    for page, is_contact in parsed:
        for hit in page.phones:
            if (hit.value, page.url) not in seen_phone:
                seen_phone.add((hit.value, page.url))
                near = m.is_same_street(m.nearest_street(hit.before, hit.after), target.street)
                report.phones.append(SiteContact(hit.value, hit.display, page.url, hit.snippet, hit.via,
                                                 is_contact, near))
        for hit in page.emails:
            if (hit.value, page.url) not in seen_email:
                seen_email.add((hit.value, page.url))
                report.emails.append(SiteContact(hit.value, hit.display, page.url, hit.snippet, hit.via, is_contact))


def contact_confidence(report: SiteReport, contact: SiteContact, kind: str, distinct_phones: int) -> int:
    score = report.confidence if report.confirmed else min(report.confidence, UNCONFIRMED_CONTACT_CAP)
    if kind == "phone":
        score += 3 if contact.via in ("tel-link", "json-ld") else 0
        score += 2 if contact.on_contact_page else 0
        if distinct_phones > 6:  # a page full of numbers is a listing, not one business
            score -= 20
        elif distinct_phones >= 3:  # several offices: prefer the number written next to this address
            score += 2 if contact.near_address else -20
    else:
        domain = contact.value.rsplit("@", 1)[1]
        if m.registrable_domain(domain) == m.registrable_domain(report.site_url):
            score += 3
        elif domain in m.FREE_MAIL_DOMAINS:
            score -= 5
        else:  # e.g. the web designer's address in the footer
            score -= 10 if contact.on_contact_page else 20
    return max(0, min(97, score))
