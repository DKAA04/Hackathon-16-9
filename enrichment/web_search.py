"""Website discovery through OpenAI's web search tool (optional, needs OPENAI_API_KEY).

The model only proposes candidate URLs. A candidate counts as evidence only after
website.py has fetched it and found the enterprise number or address on the site.
"""
from __future__ import annotations

import re

from . import matching as m
from .extract import format_kbo
from .models import EnrichTarget, SourceRun

# Directories, social media and platforms: useful for people, but not the business's own site.
NOT_OWN_SITE = (
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com", "youtube.com", "tiktok.com",
    "pinterest.com", "goudengids.be", "pagesdor.be", "infobel.com", "companyweb.be", "trendstop.knack.be",
    "trends.knack.be", "openthebox.be", "kbopub.economie.fgov.be", "economie.fgov.be", "bizzy.org", "dnb.com",
    "cylex.be", "cylex-belgie.be", "yelp.be", "yelp.com", "tripadvisor.be", "tripadvisor.com", "google.com",
    "goo.gl", "booking.com", "takeaway.com", "ubereats.com", "deliveroo.be", "resengo.com", "zenchef.com",
    "treatwell.be", "salonkee.be", "planity.com", "doctoranytime.be", "doctena.be", "staatsbladmonitor.be",
    "creditsafe.com", "northdata.com", "opencorporates.com", "wikipedia.org", "openstreetmap.org",
    "vlaanderen.be", "edegem.be", "schoten.be", "2dehands.be", "immoweb.be", "zimmo.be", "yellowpages.com",
    "openingsurengids.be", "bedrijvengids.be", "bsearch.be",
)
URL_RE = re.compile(r"https?://[^\s)\]>\"'<]+")


def is_own_site_candidate(url: str) -> bool:
    host = m.host_of(url)
    return bool(host) and not any(host == d or host.endswith("." + d) for d in NOT_OWN_SITE)


def _prompt(target: EnrichTarget) -> str:
    lines = [
        "Find the official website of this Belgian business.",
        f"Registered name: {target.name}",
    ]
    if target.trade_name:
        lines.append(f"Trade name: {target.trade_name}")
    if target.address:
        lines.append(f"Address: {target.address}, Belgium")
    if target.enterprise_number:
        lines.append(f"Enterprise number (KBO/VAT): BE {format_kbo(target.enterprise_number)}")
    if target.activity:
        lines.append(f"Activity: {target.activity}")
    lines.append(
        "Answer with only the URL of the business's own website, or NONE if you cannot find it. "
        "Never answer with a directory, register, review, booking or social-media page."
    )
    return "\n".join(lines)


def find_websites(target: EnrichTarget, api_key: str, model: str) -> tuple[list[str], SourceRun]:
    try:
        import openai
    except ImportError:
        return [], SourceRun("web_search", "overgeslagen", "openai-pakket niet geïnstalleerd")

    client = openai.OpenAI(api_key=api_key, timeout=90)
    attempts = [
        {"tools": [{"type": "web_search"}], "reasoning": {"effort": "low"}},
        {"tools": [{"type": "web_search"}]},
        {"tools": [{"type": "web_search_preview"}]},
    ]
    response, error = None, "geen antwoord"
    for extra in attempts:
        try:
            response = client.responses.create(model=model, input=_prompt(target), **extra)
            break
        except openai.BadRequestError as exc:  # older model/tool combination: try the next variant
            error = str(exc)[:200]
        except openai.OpenAIError as exc:
            return [], SourceRun("web_search", "fout", f"{type(exc).__name__}: {str(exc)[:160]}")
    if response is None:
        return [], SourceRun("web_search", "fout", error)

    urls = URL_RE.findall(response.output_text or "")
    for item in response.output or []:
        for content in getattr(item, "content", None) or []:
            for note in getattr(content, "annotations", None) or []:
                if getattr(note, "type", "") == "url_citation" and getattr(note, "url", None):
                    urls.append(note.url)

    candidates: list[str] = []
    for url in urls:
        url = url.split("?")[0].rstrip(".,;")
        if is_own_site_candidate(url) and m.host_of(url) not in {m.host_of(c) for c in candidates}:
            candidates.append(url)
    if not candidates:
        return [], SourceRun("web_search", "geen_resultaat", f"model {model}: geen eigen website voorgesteld")
    return candidates[:3], SourceRun("web_search", "ok", f"model {model} stelde voor: {', '.join(candidates[:3])}")
