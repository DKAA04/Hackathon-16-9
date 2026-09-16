"""Website crawl + scoring end to end, with canned pages instead of the internet."""
from enrichment.models import EnrichTarget
from enrichment.net import FetchError, Page
from enrichment.pipeline import Enricher, Options
from enrichment.website import crawl

from .test_extract import KBO, PAGE

CONTACT = """<html><head><title>Contact - Bakkerij Peeters</title></head><body>
<h1>Contact</h1><p>Kerkplein 5, 2650 Edegem</p><p>Tel: 03 440 12 34</p>
<p>Bestellingen: bestel [at] bakkerijpeeters [dot] be</p></body></html>"""


class StubFetcher:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.calls: list[str] = []

    def get(self, url: str) -> Page:
        self.calls.append(url)
        key = url.rstrip("/")
        if key in self.pages:
            return Page(url=url, status=200, text=self.pages[key])
        raise FetchError(f"HTTP 404: {url}")

    def cache_get(self, *_args, **_kwargs):
        return None

    def close(self):
        pass


SITE = {"https://www.bakkerijpeeters.be": PAGE, "https://www.bakkerijpeeters.be/contact": CONTACT}


def make_target(**extra) -> EnrichTarget:
    data = dict(record_id="2123456789", name="Peeters Jan", trade_name="Bakkerij Peeters",
                enterprise_number=KBO, is_establishment=True, street="Kerkplein", house_number="5",
                postcode="2650", municipality="Edegem")
    data.update(extra)
    return EnrichTarget(**data)


def test_crawl_proves_identity_with_enterprise_number():
    fetcher = StubFetcher(SITE)
    report = crawl(fetcher, "https://www.bakkerijpeeters.be/", make_target(), "test")
    assert report.identity == 95 and report.kbo_found and report.address_found
    assert "https://www.bakkerijpeeters.be/contact" in report.pages
    assert "https://www.bakkerijpeeters.be/over-ons" in fetcher.calls  # tried, 404 is fine
    assert not any("facebook" in c for c in fetcher.calls)


def test_crawl_other_enterprise_number_caps_confidence():
    report = crawl(StubFetcher(SITE), "https://www.bakkerijpeeters.be/",
                   make_target(enterprise_number="0403170701"), "test")
    assert not report.kbo_found
    assert report.identity == 50
    assert "ander ondernemingsnummer" in report.proof


def test_enricher_merges_and_scores():
    options = Options(use_osm=False, use_google=False, use_web_search=False, guess_domains=False)
    enricher = Enricher(options, fetcher=StubFetcher(SITE))
    result = enricher.enrich(make_target(known_website="www.bakkerijpeeters.be", known_email="info@bakkerijpeeters.be"))

    phones = {f.value: f for f in result.phones}
    assert set(phones) == {"+3234401234", "+32470123456"}
    assert phones["+3234401234"].level == "hoog"
    assert phones["+3234401234"].scope == "vestiging"
    assert result.best("phone").value == "+3234401234"  # tel-link + contact page beat plain text

    emails = {f.value: f for f in result.emails}
    assert emails["info@bakkerijpeeters.be"].sources == ["kbo", "website"]
    assert emails["info@bakkerijpeeters.be"].confidence == 99
    assert emails["studio@webbureau.be"].confidence < emails["bestel@bakkerijpeeters.be"].confidence

    assert result.best("website").value == "https://www.bakkerijpeeters.be"
    assert any("ondernemingsnummer" in p for p in result.identity_proof)
    assert {r.source: r.status for r in result.sources} == {
        "osm": "overgeslagen", "google_maps": "overgeslagen", "website": "ok",
    }
    data = result.to_dict()
    assert data["best"]["phone"]["display"] == "03 440 12 34"
    assert data["ui_evidence"][0]["label"] == "Telefoon"


BRAND_PAGE = """<html><head><title>Grote Bank - Kantoren</title></head><body>
<p>Bel ons: 03 440 55 66</p><p>Klantendienst: info@grotebank.be</p></body></html>"""


def test_linked_site_that_never_names_the_business_stays_low():
    options = Options(use_osm=False, use_google=False, use_web_search=False, guess_domains=False)
    enricher = Enricher(options, fetcher=StubFetcher({"https://www.grotebank.be/kantoren": BRAND_PAGE}))
    result = enricher.enrich(make_target(known_website="https://www.grotebank.be/kantoren"))
    assert result.best("website").confidence == 65
    assert result.best("phone").level == "laag"
    assert result.best("email").level == "laag"
    assert result.identity_proof == []


MULTI_OFFICE = f"""<html><head><title>Kantoren - Bakkerij Peeters</title></head><body>
<div><h2>Edegem</h2><p>Kerkplein 5, 2650 Edegem</p><p>Tel 03 440 12 34</p></div>
<div><h2>Mortsel</h2><p>Statiestraat 1, 2640 Mortsel</p><p>Tel 03 455 11 22</p></div>
<div><h2>Kontich</h2><p>Mechelsesteenweg 10, 2550 Kontich</p><p>Tel 03 457 33 44</p></div>
<footer>BTW BE {KBO[:4]}.{KBO[4:7]}.{KBO[7:]}</footer></body></html>"""


def test_multi_office_site_prefers_the_local_number():
    options = Options(use_osm=False, use_google=False, use_web_search=False, guess_domains=False)
    enricher = Enricher(options, fetcher=StubFetcher({"https://peeters.example.be": MULTI_OFFICE}))
    result = enricher.enrich(make_target(known_website="https://peeters.example.be"))
    phones = {f.display: f for f in result.phones}
    assert result.best("phone").display == "03 440 12 34"
    assert (phones["03 440 12 34"].level, phones["03 440 12 34"].scope) == ("hoog", "vestiging")
    assert (phones["03 455 11 22"].level, phones["03 455 11 22"].scope) == ("middel", "onbekend")


def test_aliases_extend_names():
    target = make_target()
    target.add_alias("Voorbeeldbakker")
    target.add_alias("bakkerij peeters")
    assert target.names == ["Bakkerij Peeters", "Peeters Jan", "Voorbeeldbakker"]


def test_unreachable_known_site_becomes_signal():
    options = Options(use_osm=False, use_google=False, use_web_search=False, guess_domains=False)
    enricher = Enricher(options, fetcher=StubFetcher({}))
    result = enricher.enrich(make_target(known_website="https://gone.example.be"))
    assert [s.value for s in result.signals] == ["website_unreachable"]
    assert result.websites == [] and result.phones == []
