from enrichment.extract import (
    clean_email,
    decode_cfemail,
    emails_in_text,
    enterprise_numbers_in_text,
    kbo_checksum_ok,
    parse_page,
    phone_from_string,
    phones_in_text,
)


def valid_kbo(base8: str) -> str:
    return base8 + f"{97 - int(base8) % 97:02d}"


def cf_encode(email: str, key: int = 0x42) -> str:
    return f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in email)


KBO = valid_kbo("04287559")  # 0428755935


def test_kbo_checksum():
    assert KBO == "0428755935"
    assert kbo_checksum_ok(KBO)
    assert not kbo_checksum_ok("0428755949")
    assert not kbo_checksum_ok("2428755935")


def test_enterprise_numbers_in_text_formats():
    text = f"BTW BE {KBO[:4]}.{KBO[4:7]}.{KBO[7:]} en ook BE{KBO} en BE 428.755.935"
    assert list(enterprise_numbers_in_text(text)) == [KBO]


def test_phone_normalisation():
    assert phone_from_string("03 440 12 34") == ("+3234401234", "03 440 12 34")
    assert phone_from_string("+32 (0)470 12 34 56")[0] == "+32470123456"
    assert phone_from_string("12345") is None


def test_phones_skip_vat_iban_fax_and_own_number():
    text = (
        "Tel. 03 440 12 34 - GSM 0470/12.34.56 - Fax 03 440 99 99 - "
        "BTW BE 0471.234.567 - ondernemingsnummer 0471 234 567 - IBAN BE68 5390 0754 7034 - "
        "www.zaak.be 03 440 55 66"
    )
    values = {h.value for h in phones_in_text(text, exclude_digits=["0471234567"])}
    assert values == {"+3234401234", "+32470123456", "+3234405566"}


def test_tel_fax_combined_line_is_kept():
    assert {h.value for h in phones_in_text("Tel/Fax: 03 440 12 34")} == {"+3234401234"}


def test_emails_plain_obfuscated_and_filtered():
    text = "Mail info@zaak.be of bestel [at] zaak [dot] be. Niet: logo@2x.png, naam@voorbeeld.be, jan@example.com"
    assert [h.value for h in emails_in_text(text)] == ["info@zaak.be", "bestel@zaak.be"]
    assert clean_email("mailto:Info@Zaak.be?subject=Hallo") == "info@zaak.be"


def test_cloudflare_email():
    assert decode_cfemail(cf_encode("hallo@zaak.be")) == "hallo@zaak.be"


PAGE = f"""<html><head><title>Bakkerij Peeters | Edegem</title>
<script type="application/ld+json">{{"@context": "https://schema.org", "@type": "Bakery",
 "name": "Bakkerij Peeters", "telephone": "+32 3 440 12 34",
 "address": {{"@type": "PostalAddress", "streetAddress": "Kerkplein 5", "postalCode": "2650"}}}}</script>
<style>.x{{color:red}}</style></head><body>
<nav><a href="/contact">Contact</a> <a href="/over-ons">Over ons</a> <a href="https://facebook.com/x">FB</a></nav>
<p>Bel ons: <a href="tel:+3234401234">03 440 12 34</a> of GSM 0470 12 34 56</p>
<p>Fax 03 440 99 99</p>
<footer>Bakkerij Peeters BV, Kerkplein 5, 2650 Edegem, BTW BE {KBO[:4]}.{KBO[4:7]}.{KBO[7:]}
<a href="mailto:info@bakkerijpeeters.be?subject=Vraag">Mail ons</a>
<a href="/cdn-cgi/l/email-protection#{cf_encode('hallo@bakkerijpeeters.be')}">[email&#160;protected]</a>
Webdesign: studio@webbureau.be <img src="logo@2x.png"></footer>
</body></html>"""


def test_parse_page():
    page = parse_page(PAGE, "https://www.bakkerijpeeters.be/", exclude_digits=[KBO])
    assert page.title == "Bakkerij Peeters | Edegem"
    assert {h.value for h in page.phones} == {"+3234401234", "+32470123456"}
    assert {h.via for h in page.phones} >= {"json-ld", "tel-link", "tekst"}
    assert {h.value for h in page.emails} == {
        "info@bakkerijpeeters.be", "hallo@bakkerijpeeters.be", "studio@webbureau.be",
    }
    assert KBO in page.enterprise_numbers
    assert ("https://www.bakkerijpeeters.be/contact", "Contact") in page.links
    assert "color:red" not in page.text
