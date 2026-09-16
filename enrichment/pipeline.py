"""Run all sources for a record, merge what they found, and score it."""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from . import google_maps, matching as m, web_search
from .extract import phone_from_string, clean_email
from .models import EnrichmentResult, EnrichTarget, Finding, Observation, SourceRun, confidence_level
from .net import Fetcher, is_public_url
from .osm import OsmIndex
from .website import SiteReport, contact_confidence, crawl

MIN_CONFIDENCE = 30  # anything weaker is noise, not a proposal
ALIAS_MIN_SCORE = 85  # map listings this certain lend their name to the target


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = Path(__file__).resolve().parent
    for path in (here / ".env", here.parent / "backend" / ".env"):
        if path.exists():
            load_dotenv(path, override=False)


@dataclass
class Options:
    use_osm: bool = True
    use_google: bool = True  # only runs when GOOGLE_MAPS_API_KEY is set
    use_web_search: bool = True  # only runs when OPENAI_API_KEY is set and nothing else found a site
    guess_domains: bool = True
    use_cache: bool = True
    max_sites: int = 3
    max_pages_per_site: int = 5


class _Collector:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], Finding] = {}

    def add(self, kind: str, value: str, display: str, obs: Observation, scope: str = "onbekend") -> None:
        finding = self.items.setdefault((kind, value), Finding(kind=kind, value=value, display=display))
        finding.observations.append(obs)
        if finding.scope == "onbekend":
            finding.scope = scope

    def finish(self, kind: str) -> list[Finding]:
        out = []
        for finding in (f for (k, _), f in self.items.items() if k == kind):
            best = max(o.confidence for o in finding.observations)
            finding.confidence = min(99, best + 5 * (len(finding.sources) - 1))  # independent sources agree
            finding.level = confidence_level(finding.confidence)
            finding.observations.sort(key=lambda o: -o.confidence)
            if kind == "signal" or finding.confidence >= MIN_CONFIDENCE:
                out.append(finding)
        return sorted(out, key=lambda f: -f.confidence)


class Enricher:
    def __init__(self, options: Options | None = None, fetcher: Fetcher | None = None):
        load_env()
        self.options = options or Options()
        self.fetcher = fetcher or Fetcher(use_cache=self.options.use_cache)
        self.osm = OsmIndex(self.fetcher)
        self.google_key = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_PLACES_API_KEY")
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.openai_model = os.getenv("ENRICH_OPENAI_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5-mini"

    def close(self) -> None:
        self.fetcher.close()

    # ------------------------------------------------------------------

    def enrich(self, target: EnrichTarget) -> EnrichmentResult:
        found = _Collector()
        runs: list[SourceRun] = []
        proofs: list[str] = []
        site_candidates: list[tuple[str, str, int]] = []  # (url, origin, origin confidence)

        self._from_register(target, found, site_candidates)
        if self.options.use_osm:
            self._timed(runs, lambda: self._from_osm(target, found, site_candidates))
        else:
            runs.append(SourceRun("osm", "overgeslagen", "uitgeschakeld"))
        if self.options.use_google and self.google_key:
            self._timed(runs, lambda: self._from_google(target, found, site_candidates))
        else:
            detail = "geen GOOGLE_MAPS_API_KEY" if self.options.use_google else "uitgeschakeld"
            runs.append(SourceRun("google_maps", "overgeslagen", detail))
        self._timed(runs, lambda: self._from_websites(target, found, site_candidates, proofs, runs))

        return EnrichmentResult(
            target=target,
            phones=found.finish("phone"),
            emails=found.finish("email"),
            websites=found.finish("website"),
            signals=found.finish("signal"),
            identity_proof=proofs,
            sources=runs,
        )

    def enrich_many(self, targets: Iterable[EnrichTarget], workers: int = 4,
                    progress: Callable[[int, int, EnrichmentResult], None] | None = None) -> list[EnrichmentResult]:
        targets = list(targets)
        if self.options.use_osm:  # download each municipality once before the threads start
            for town in {t.municipality for t in targets if t.municipality}:
                try:
                    self.osm.pois(town)
                except Exception:
                    pass  # reported per record by OsmIndex.lookup
        results: list[EnrichmentResult | None] = [None] * len(targets)

        def run(index: int) -> None:
            target = targets[index]
            try:
                result = self.enrich(target)
            except Exception as exc:  # one bad record must not stop the batch
                result = EnrichmentResult(target, [], [], [], [], [], [SourceRun("pipeline", "fout", repr(exc)[:200])])
            results[index] = result
            if progress:
                progress(index, len(targets), result)

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            list(pool.map(run, range(len(targets))))
        return [r for r in results if r is not None]

    # ------------------------------------------------------------------

    @staticmethod
    def _timed(runs: list[SourceRun], step: Callable[[], SourceRun | None]) -> None:
        started = time.perf_counter()
        run = step()
        if run is not None:
            run.elapsed_ms = int((time.perf_counter() - started) * 1000)
            runs.append(run)

    def _from_register(self, target: EnrichTarget, found: _Collector, sites: list) -> None:
        url = target.register_url
        if phone := phone_from_string(target.known_phone):
            found.add("phone", *phone, Observation("kbo", url, f"Telefoonnummer: {target.known_phone}", 80,
                                                   "opgegeven in de KBO (datum onbekend)"), "onderneming")
        if email := clean_email(target.known_email):
            found.add("email", email, email, Observation("kbo", url, f"Email: {target.known_email}", 80,
                                                         "opgegeven in de KBO (datum onbekend)"), "onderneming")
        if target.known_website:
            sites.append((_as_url(target.known_website), "website uit het record", 80))
        if site := m.email_domain_site(target.known_email):
            sites.append((site, "domein van het KBO-e-mailadres", 60))

    def _from_osm(self, target: EnrichTarget, found: _Collector, sites: list) -> SourceRun:
        match, run = self.osm.lookup(target)
        if not match:
            return run
        if match.score >= ALIAS_MIN_SCORE:
            target.add_alias(match.name)
        reason = f"OpenStreetMap: {match.reason}"
        scope = "vestiging" if match.score >= 75 else "onbekend"
        for e164, display, tag in match.phones:
            found.add("phone", e164, display, Observation("osm", match.url, tag, match.score, reason), scope)
        for email, tag in match.emails:
            found.add("email", email, email, Observation("osm", match.url, tag, match.score, reason), scope)
        for site in match.websites:
            sites.append((site, "OpenStreetMap", match.score))
        if match.disused:
            found.add("signal", "osm_disused", "OpenStreetMap: zaak gemarkeerd als niet meer in gebruik",
                      Observation("osm", match.url, match.name, match.score, reason))
        elif match.opening_hours:
            checked = f", gecontroleerd {match.check_date}" if match.check_date else ""
            found.add("signal", "osm_opening_hours", f"Openingsuren op OpenStreetMap{checked}: {match.opening_hours}",
                      Observation("osm", match.url, f"opening_hours={match.opening_hours}", match.score, reason))
        return run

    def _from_google(self, target: EnrichTarget, found: _Collector, sites: list) -> SourceRun:
        place, run = google_maps.lookup(target, self.fetcher, self.google_key or "")
        if not place:
            return run
        if place.score >= ALIAS_MIN_SCORE:
            target.add_alias(place.name)
        reason = f"Google Maps: {place.reason}"
        snippet = f"{place.name}, {place.address}"
        scope = "vestiging" if place.score >= 75 else "onbekend"
        for e164, display in place.phones:
            found.add("phone", e164, display, Observation("google_maps", place.url, snippet, place.score, reason), scope)
        if place.website:
            sites.append((place.website, "Google Maps", place.score))
        if place.status:
            code, text = place.status
            found.add("signal", code, text, Observation("google_maps", place.url, snippet, place.score, reason))
        return run

    def _from_websites(self, target: EnrichTarget, found: _Collector, candidates: list[tuple[str, str, int]],
                       proofs: list[str], runs: list[SourceRun]) -> SourceRun:
        reports: list[SiteReport] = []
        tried: set[str] = set()

        def visit(url: str, origin: str, origin_confidence: int, max_pages: int) -> SiteReport | None:
            host = m.host_of(url)
            if not host or host in tried or not web_search.is_own_site_candidate(url):
                return None
            tried.add(host)
            report = crawl(self.fetcher, url, target, origin, origin_confidence, max_pages)
            reports.append(report)
            return report

        for url, origin, confidence in sorted(candidates, key=lambda c: -c[2]):
            if len(reports) >= self.options.max_sites:
                break
            visit(url, origin, confidence, self.options.max_pages_per_site)

        def good_site() -> bool:
            return any(r.confirmed for r in reports)

        if not good_site() and self.options.guess_domains:
            for domain in m.domain_guesses(target.names):
                if good_site():
                    break
                if m.host_of("https://" + domain) in tried or not is_public_url("https://" + domain):
                    continue
                visit("https://" + domain + "/", "domeinnaam afgeleid van de bedrijfsnaam", 0, 3)

        if not good_site() and self.options.use_web_search:
            if not self.openai_key:
                runs.append(SourceRun("web_search", "overgeslagen", "geen OPENAI_API_KEY"))
            else:
                started = time.perf_counter()
                urls, run = web_search.find_websites(target, self.openai_key, self.openai_model)
                run.elapsed_ms = int((time.perf_counter() - started) * 1000)
                runs.append(run)
                for url in urls:
                    visit(url, "webzoekopdracht", 0, self.options.max_pages_per_site)

        for report in reports:
            self._use_site(report, found, proofs)

        if not reports:
            return SourceRun("website", "geen_resultaat", "geen website gevonden")
        good = [r for r in reports if r.confirmed]
        detail = "; ".join(
            f"{r.site_url} ({r.origin}): {r.proof if r.reachable else 'onbereikbaar'}" for r in reports
        )
        return SourceRun("website", "ok" if good else "geen_resultaat", detail[:600])

    @staticmethod
    def _use_site(report: SiteReport, found: _Collector, proofs: list[str]) -> None:
        vouched = report.origin_confidence > 0
        if not report.reachable:
            if vouched:  # a site that the map sources know about is down: worth a look
                found.add("signal", "website_unreachable", f"Website onbereikbaar: {report.start_url}",
                          Observation("website", report.start_url, "; ".join(report.errors)[:200],
                                      report.origin_confidence, f"gevonden via {report.origin}, maar onbereikbaar"))
            return
        confidence = report.confidence
        if not vouched and not report.confirmed:
            return  # guessed/searched domain that does not prove it is this business
        reason = f"{report.proof} (gevonden via {report.origin})"
        found.add("website", report.site_url.rstrip("/"), report.site_url.rstrip("/"),
                  Observation("website", report.proof_url or report.site_url, report.proof, confidence, reason))
        if report.confirmed:
            proofs.append(f"{report.site_url}: {report.proof}" + (f" ({report.proof_url})" if report.proof_url else ""))
        if confidence < 45:
            return
        scope = "vestiging" if report.address_found else "onbekend"
        distinct_phones = len({c.value for c in report.phones})
        for contact in report.phones:
            score = contact_confidence(report, contact, "phone", distinct_phones)
            local = contact.near_address or (report.address_found and distinct_phones < 3)
            found.add("phone", contact.value, contact.display,
                      Observation("website", contact.page_url, contact.snippet, score, reason),
                      "vestiging" if local else "onbekend")
        for contact in report.emails:
            score = contact_confidence(report, contact, "email", distinct_phones)
            found.add("email", contact.value, contact.display,
                      Observation("website", contact.page_url, contact.snippet, score, reason), scope)


def _as_url(value: str) -> str:
    value = value.strip()
    return value if "://" in value else "https://" + value
