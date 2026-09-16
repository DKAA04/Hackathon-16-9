"""Website enrichment: fetch homepage (+ contact/about page), extract
structured contact facts. Narrow scope, no broad crawling, no guessed emails.
"""

import json
import logging
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = "CivicLensBot/0.1 (municipal business verification prototype)"
TIMEOUT = 8.0
MAX_EXTRA_PAGES = 2

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
SOCIAL_DOMAINS = ("facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com", "tiktok.com")
CONTACT_HINTS = ("contact", "over-ons", "over_ons", "overons", "about")


def _fetch(url: str) -> str | None:
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
            follow_redirects=True,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type and not response.text.lstrip().startswith("<"):
            return None
        return response.text
    except Exception as exc:
        logger.warning("Website fetch failed for %s: %s", url, exc)
        return None


def extract_from_html(html: str, page_url: str) -> dict:
    """Structured-first extraction: JSON-LD, mailto:, tel:, then visible text."""
    soup = BeautifulSoup(html, "html.parser")
    found: dict = {"emails": set(), "phones": set(), "social_links": set(),
                   "description": None, "opening_hours": None, "contact_urls": set()}

    # JSON-LD / schema.org
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                items.extend(x for x in graph if isinstance(x, dict))
                continue
            if item.get("email"):
                found["emails"].add(str(item["email"]).replace("mailto:", "").strip())
            if item.get("telephone"):
                found["phones"].add(str(item["telephone"]).strip())
            if item.get("description") and not found["description"]:
                found["description"] = str(item["description"])[:500]
            hours = item.get("openingHours") or item.get("openingHoursSpecification")
            if hours and not found["opening_hours"]:
                found["opening_hours"] = json.dumps(hours, ensure_ascii=False)[:500]

    # mailto: / tel: / social / contact links
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        lower = href.lower()
        if lower.startswith("mailto:"):
            email = href[7:].split("?")[0].strip()
            if EMAIL_RE.fullmatch(email):
                found["emails"].add(email)
        elif lower.startswith("tel:"):
            found["phones"].add(href[4:].strip())
        elif any(domain in lower for domain in SOCIAL_DOMAINS):
            found["social_links"].add(href)
        elif any(hint in lower for hint in CONTACT_HINTS):
            found["contact_urls"].add(urljoin(page_url, href))

    # Visible-text emails as fallback (never guessed patterns)
    for match in EMAIL_RE.findall(soup.get_text(" ", strip=True)):
        if not match.lower().endswith((".png", ".jpg", ".svg", ".webp")):
            found["emails"].add(match)

    if not found["description"]:
        meta = soup.find("meta", attrs={"name": "description"}) or soup.find(
            "meta", attrs={"property": "og:description"})
        if meta and meta.get("content"):
            found["description"] = meta["content"][:500]

    return found


def enrich_from_website(website_url: str) -> dict:
    """Fetch homepage + at most MAX_EXTRA_PAGES contact/about pages and merge
    extracted facts. Returns {"status": ..., "fields": {field: value}, ...}."""
    if not website_url.startswith(("http://", "https://")):
        website_url = "https://" + website_url

    parsed = urlparse(website_url)
    if not parsed.netloc:
        return {"status": "ERROR", "error": "invalid website URL"}

    html = _fetch(website_url)
    if html is None:
        return {"status": "ERROR", "error": f"could not fetch {website_url}"}

    merged = extract_from_html(html, website_url)

    same_host_contacts = [
        u for u in merged["contact_urls"]
        if urlparse(u).netloc in ("", parsed.netloc)
    ]
    for extra_url in same_host_contacts[:MAX_EXTRA_PAGES]:
        extra_html = _fetch(extra_url)
        if not extra_html:
            continue
        extra = extract_from_html(extra_html, extra_url)
        merged["emails"] |= extra["emails"]
        merged["phones"] |= extra["phones"]
        merged["social_links"] |= extra["social_links"]
        merged["description"] = merged["description"] or extra["description"]
        merged["opening_hours"] = merged["opening_hours"] or extra["opening_hours"]

    fields: dict[str, str] = {"website": website_url}
    if merged["emails"]:
        fields["email"] = sorted(merged["emails"])[0]
    if merged["phones"]:
        fields["phone"] = sorted(merged["phones"])[0]
    if merged["description"]:
        fields["description"] = merged["description"]
    if merged["opening_hours"]:
        fields["opening_hours"] = merged["opening_hours"]
    if merged["social_links"]:
        fields["social_links"] = json.dumps(sorted(merged["social_links"])[:5])
    if same_host_contacts:
        fields["contact_url"] = same_host_contacts[0]

    return {
        "status": "OK",
        "source_url": website_url,
        "fields": fields,
        "emails_found": sorted(merged["emails"]),
        "phones_found": sorted(merged["phones"]),
    }
