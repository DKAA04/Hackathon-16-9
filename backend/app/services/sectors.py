"""Occupation (sector) classification for the officer's filter.

The KBO snapshot barely records activities (the VAT activity code is empty for every
row, the RSZ code for most), so a sector match combines NACE code prefixes with
whole-word name keywords, and every match carries a human-readable reason.
Co-ownership associations (VME) are never classified as a business sector.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.db.models import Business


@dataclass(frozen=True)
class Sector:
    key: str
    label: str
    nace_prefixes: tuple[str, ...]
    pattern: re.Pattern


def _words(*alternatives: str) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(alternatives) + r")\b")


SECTORS: tuple[Sector, ...] = (
    Sector("bakkerij", "Bakkerijen & banket", ("1071", "1072", "4724"),
           _words(r"bakker\w*", r"boulanger\w*", r"patisserie\w*", r"patissier\w*", r"banket\w*",
                  r"brood(?!je)\w*", r"viennoiserie\w*", r"chocolat\w*")),
    Sector("horeca", "Horeca", ("55", "56"),
           _words(r"restaurant\w*", r"frituur\w*", r"friture\w*", r"cafe\w*", r"brasserie\w*", r"bistro\w*",
                  r"pizzeria\w*", r"pizza\w*", r"snack\w*", r"broodje\w*", r"eethuis", r"taverne", r"traiteur\w*",
                  r"sushi", r"kebab\w*", r"grill\w*", r"hotel\w*", r"catering\w*", r"bar")),
    Sector("zorg", "Zorg & welzijn", ("86", "87", "88", "4773", "4774"),
           _words(r"apothe\w*", r"kinesi\w*", r"tandarts\w*", r"dental\w*", r"dokter\w*", r"huisarts\w*",
                  r"medisch\w*", r"medical\w*", r"verpleeg\w*", r"thuiszorg\w*", r"zorg\w*", r"hoorcentrum\w*",
                  r"optiek\w*", r"opticien\w*", r"psycholo\w*", r"logopedi\w*", r"fysio\w*", r"moveo")),
    Sector("kapper", "Kappers & schoonheid", ("9602", "9604"),
           _words(r"kapper\w*", r"kapsalon\w*", r"coiff\w*", r"hair\w*", r"kapsel\w*", r"schoonheid\w*",
                  r"beauty\w*", r"nagel\w*", r"nails?", r"barber\w*", r"wellness\w*")),
    Sector("bouw", "Bouw & installatie", ("41", "42", "43"),
           _words(r"bouw\w*", r"renovat\w*", r"dakwerk\w*", r"schilder\w*", r"elektri\w*", r"loodgiet\w*",
                  r"sanitair\w*", r"installat\w*", r"tegel\w*", r"aannem\w*", r"schrijnwerk\w*", r"verwarming\w*")),
    Sector("auto", "Auto & mobiliteit", ("45", "4932", "8553"),
           _words(r"garage\w*", r"autobedrijf\w*", r"autohandel\w*", r"autoservice\w*", r"car", r"carrosser\w*",
                  r"banden\w*", r"rijschool\w*", r"taxi\w*", r"fiets\w*")),
    Sector("winkel", "Winkels & detailhandel", ("47",),
           _words(r"winkel\w*", r"shop\w*", r"boetiek\w*", r"boutique\w*", r"bloem(?:en|ist|isterij|enwinkel|enzaak|enhandel)", r"slager\w*",
                  r"beenhouwer\w*", r"juwel\w*", r"mode", r"supermarkt\w*", r"kruidenier\w*", r"store")),
    Sector("advies", "Advies & vrije beroepen", ("69", "70", "71", "6622"),
           _words(r"boekhoud\w*", r"accountan\w*", r"advocat\w*", r"notaris\w*", r"fiscal\w*", r"consult\w*",
                  r"verzekering\w*", r"architect\w*", r"taxcal\w*", r"tax")),
)
BY_KEY = {s.key: s for s in SECTORS}


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def is_co_ownership(business: Business) -> bool:
    text = _normalize(f"{business.legal_form or ''} {business.legal_name or ''}")
    return "mede-eigenaars" in text or "mede eigenaars" in text


def classify(business: Business) -> list[dict]:
    """[{value, label, reason}] for every sector this record matches."""
    if is_co_ownership(business):
        return []
    names = " | ".join(n for n in (business.display_name, business.commercial_name, business.legal_name,
                                   business.short_name) if n)
    names_norm = _normalize(names)
    codes = [(c, d) for c, d in ((business.nace_rsz_code, business.nace_rsz_description),
                                 (business.nace_vat_code, business.nace_vat_description)) if c]
    matches = []
    for sector in SECTORS:
        reason = None
        for code, description in codes:
            digits = re.sub(r"\D", "", code)
            if digits.startswith(sector.nace_prefixes):
                reason = f"activiteitscode {code}" + (f" ({description})" if description else "")
                break
        if reason is None:
            hit = sector.pattern.search(names_norm)
            if hit:
                reason = f'naam bevat "{hit.group(0)}"'
        if reason:
            matches.append({"value": sector.key, "label": sector.label, "reason": reason})
    return matches


def sector_keys(business: Business) -> set[str]:
    return {m["value"] for m in classify(business)}
