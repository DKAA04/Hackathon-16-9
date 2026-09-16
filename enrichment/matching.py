"""Name/address normalisation and fuzzy matching."""
from __future__ import annotations

import math
import re
import unicodedata
from urllib.parse import urlsplit

from rapidfuzz import fuzz

LEGAL_FORM_RE = re.compile(
    r"\b(?:bvba|bv|nv|vzw|ivzw|vof|commv|comm v|gcv|cvba|cv|ebvba|esv|lv|srl|sprl|scrl|sa|asbl|sc|scs|snc|gmbh|ltd)\b"
)
SINGLE_LETTERS_RE = re.compile(r"\b(?:[a-z] ){1,4}[a-z]\b")  # "b v b a" -> "bvba"
STREET_ABBREVIATIONS = {"stwg": "steenweg", "str": "straat", "ln": "laan", "pl": "plein", "stw": "steenweg"}

# Words that say what a business is, not which one it is.
GENERIC_WORDS = {
    "bakkerij", "apotheek", "kapsalon", "kapper", "frituur", "garage", "beenhouwerij", "slagerij", "restaurant",
    "cafe", "brasserie", "bistro", "immo", "immobilien", "consult", "consulting", "consultancy", "bouw",
    "services", "service", "solutions", "invest", "management", "holding", "group", "groep", "de", "het", "en",
    "the", "and", "van", "der", "den", "shop", "winkel", "praktijk", "dokter", "dr", "tandarts", "atelier",
    "studio", "center", "centrum", "company", "international", "belgium", "belgie", "antwerpen", "edegem",
}
FREE_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.be", "outlook.com", "outlook.be", "live.com", "live.be",
    "msn.com", "yahoo.com", "yahoo.fr", "icloud.com", "me.com", "telenet.be", "skynet.be", "proximus.be",
    "scarlet.be", "pandora.be", "belgacom.net", "edpnet.be", "gmx.com", "gmx.net", "protonmail.com", "proton.me",
    "mail.be", "online.be", "base.be", "voo.be",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_text(s: str | None) -> str:
    if not s:
        return ""
    s = strip_accents(str(s)).lower().replace("&", " en ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_name(s: str | None) -> str:
    s = normalize_text(s)
    s = SINGLE_LETTERS_RE.sub(lambda m: m.group(0).replace(" ", ""), s)
    s = LEGAL_FORM_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def significant_tokens(name: str) -> list[str]:
    return [t for t in normalize_name(name).split() if len(t) >= 3 and t not in GENERIC_WORDS]


def name_similarity(a: str | None, b: str | None) -> int:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0
    if min(len(na), len(nb)) <= 3:
        return 100 if na == nb else 0
    score = int(max(fuzz.token_set_ratio(na, nb), fuzz.ratio(na, nb)))
    shared = set(na.split()) & set(nb.split())
    if shared and not shared - GENERIC_WORDS and fuzz.ratio(na, nb) < 90:
        score = min(score, 50)  # "Apotheek" vs "Apotheek Peeters" is not a match
    return score


def best_similarity(names: list[str], candidates: list[str]) -> int:
    return max((name_similarity(a, b) for a in names for b in candidates if a and b), default=0)


def normalize_street(s: str | None) -> str:
    words = normalize_text(s).split()
    return " ".join(STREET_ABBREVIATIONS.get(w, w) for w in words)


def street_similarity(a: str | None, b: str | None) -> int:
    na, nb = normalize_street(a).replace(" ", ""), normalize_street(b).replace(" ", "")
    if not na or not nb:
        return 0
    return int(fuzz.ratio(na, nb))


def house_core(s: str | None) -> str:
    match = re.match(r"\s*(\d+)", str(s or ""))
    return match.group(1) if match else ""


def house_match(a: str | None, b: str | None) -> bool:
    ca, cb = house_core(a), house_core(b)
    return bool(ca) and ca == cb


def haversine_m(lat1, lon1, lat2, lon2) -> float | None:
    if None in (lat1, lon1, lat2, lon2):
        return None
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def place_match_score(similarity: int, distance: float | None, same_street: bool, same_number: bool) -> tuple[int, str]:
    """How sure we are that a map listing (OSM / Google) is this register record."""
    if similarity >= 85 and same_street and same_number:
        return 92, "naam en adres komen overeen"
    if similarity >= 85 and distance is not None and distance <= 60:
        return 88, f"naam komt overeen, {int(distance)} m van het KBO-adres"
    if similarity >= 70 and same_street and same_number:
        return 82, "adres komt overeen, naam lijkt sterk"
    if similarity >= 85 and (same_street or (distance is not None and distance <= 250)):
        return 75, "naam komt overeen, zelfde straat of buurt"
    if similarity >= 95 and distance is None and not same_street:
        return 55, "enkel de naam komt overeen"
    return 0, ""


# ---------- web pages ----------

def name_on_page(names: list[str], text_norm: str, title: str) -> bool:
    tokens = set(text_norm.split())
    padded = f" {text_norm} "
    title_norm = normalize_name(title)
    for name in names:
        nn = normalize_name(name)
        if not nn:
            continue
        sig = significant_tokens(name)
        if sig and all(t in tokens for t in sig):
            return True
        if len(nn) > 3 and f" {nn} " in padded and sig:
            return True
        if sig and title_norm and fuzz.token_set_ratio(nn, title_norm) >= 90:
            return True
    return False


STREET_WORD_RE = re.compile(
    r"[a-z]+(?:straat|laan|steenweg|plein|lei|dreef|weg|baan|kaai|markt|dijk|hof|pad|singel|vest|berg|veld|park)\b"
)


def nearest_street(before: str, after: str = "") -> str | None:
    """The street name written closest to a phone number: last one before it, else first one after."""
    words = STREET_WORD_RE.findall(normalize_street(before))
    if words:
        return words[-1]
    words = STREET_WORD_RE.findall(normalize_street(after))
    return words[0] if words else None


def is_same_street(word: str | None, street: str | None) -> bool:
    target = normalize_street(street).replace(" ", "")
    return bool(word and target and (target.endswith(word) or word.endswith(target)))


def address_on_page(text_norm: str, street: str | None, house_number: str | None,
                    postcode: str | None, municipality: str | None) -> tuple[bool, bool]:
    """(street + house number found, postcode or municipality found)."""
    text_s = normalize_street(text_norm)
    street_c = normalize_street(street).replace(" ", "")
    number = house_core(house_number)
    full = False
    if len(street_c) >= 4 and number:
        # "mechelsesteenweg" must also match "mechelse steenweg"
        pattern = r"\s?".join(map(re.escape, street_c)) + r"\s*(?:nr\s*|nummer\s*)?(\d+)"
        full = any(match.group(1) == number for match in re.finditer(pattern, text_s))
    town = bool(postcode and re.search(rf"\b{re.escape(postcode)}\b", text_norm))
    town = town or bool(municipality and f" {normalize_text(municipality)} " in f" {text_norm} ")
    return full, town


def host_of(url: str | None) -> str:
    host = (urlsplit(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def registrable_domain(host_or_url: str | None) -> str:
    host = host_of(host_or_url) if "/" in (host_or_url or "") else (host_or_url or "").lower()
    host = host[4:] if host.startswith("www.") else host
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def email_domain_site(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower()
    if domain in FREE_MAIL_DOMAINS or "." not in domain:
        return None
    return f"https://{domain}/"


def domain_guesses(names: list[str], limit: int = 4) -> list[str]:
    """Likely own-domain names, e.g. 'Bakkerij Peeters BV' -> bakkerijpeeters.be."""
    out: list[str] = []
    for name in names:
        tokens = normalize_name(name).split()
        if not tokens or all(t in GENERIC_WORDS for t in tokens):
            continue
        for base in ("".join(tokens), "-".join(tokens)):
            if not 4 <= len(base) <= 40:
                continue
            for tld in (".be", ".com"):
                domain = base + tld
                if domain not in out and not (tld == ".com" and "-" in base):
                    out.append(domain)
    return out[:limit]
