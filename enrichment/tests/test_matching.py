from enrichment import matching as m
from enrichment.records import target_from_row


def test_normalize_name_drops_legal_forms():
    assert m.normalize_name("Bakkerij Peeters B.V.B.A.") == "bakkerij peeters"
    assert m.normalize_name("Café Ré & Zonen NV") == "cafe re en zonen"


def test_name_similarity():
    assert m.name_similarity("Bakkerij Peeters BV", "Bakkerij Peeters") == 100
    assert m.name_similarity("Apotheek", "Apotheek Peeters") <= 50
    assert m.name_similarity("Peeters", "Janssens") < 60


def test_house_and_street():
    assert m.house_match("12A", "12")
    assert not m.house_match("12", "13")
    assert m.street_similarity("Mechelse Stwg", "Mechelsesteenweg") >= 90


def test_place_match_score():
    assert m.place_match_score(95, 20, False, False)[0] == 88
    assert m.place_match_score(95, 900, False, False)[0] == 0
    assert m.place_match_score(72, None, True, True)[0] == 82


def test_address_on_page():
    text = m.normalize_text("Bezoek ons: Kerkplein 5, 2650 Edegem")
    assert m.address_on_page(text, "Kerkplein", "5", "2650", "Edegem") == (True, True)
    assert m.address_on_page(text, "Kerkplein", "7", None, None) == (False, False)


def test_domains():
    assert m.domain_guesses(["Bakkerij Peeters BV"])[:2] == ["bakkerijpeeters.be", "bakkerijpeeters.com"]
    assert m.domain_guesses(["Apotheek"]) == []
    assert m.email_domain_site("info@zaak.be") == "https://zaak.be/"
    assert m.email_domain_site("jan@telenet.be") is None
    assert m.registrable_domain("https://www.shop.zaak.be/contact") == "zaak.be"


def test_target_from_vkbo_establishment_row():
    row = {
        "Ondernemingsnr": "2123456789",
        "Ondernemingsnr_maatsch_zetel": "428755935",  # leading zero lost in a spreadsheet
        "Maatschappelijke_naam": "Peeters Jan",
        "Commerciele_naam": "Bakkerij Peeters",
        "KBO_Straat": "Kerkplein", "KBO_Huisnr": "5", "KBO_Postcode": "2650", "KBO_Gemeente": "Edegem",
        "AR_straat": " ",
        "Telefoonnummer": " ", "Email": "info@bakkerijpeeters.be",
        "Begindat_ambtsh_doorhaling": "2021-03-01T00:00:00Z", "Einddat_ambtsh_doorhaling": "9999-12-31T00:00:00Z",
        "Datum_adresdoorhaling": "1900-01-01T00:00:00Z",
        "longitude": 4.44, "latitude": 51.15,
    }
    t = target_from_row(row)
    assert t.is_establishment and t.enterprise_number == "0428755935"
    assert t.names == ["Bakkerij Peeters", "Peeters Jan"]
    assert t.known_phone is None and t.known_email == "info@bakkerijpeeters.be"
    assert t.flags == ["ambtshalve doorgehaald", "adres niet gevonden in adressenregister"]
    assert t.address == "Kerkplein 5, 2650 Edegem"
