"""Pull phone numbers, e-mail addresses and enterprise numbers out of web pages."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable
from urllib.parse import unquote, urljoin

import phonenumbers
from bs4 import BeautifulSoup
from phonenumbers import NumberParseException, PhoneNumberFormat

EMAIL_FULL_RE = re.compile(r"[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,24}")
EMAIL_RE = re.compile(r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}(?![\w-])")
# info [at] zaak [dot] be, info(at)zaak.be, ...
OBFUSCATED_EMAIL_RE = re.compile(
    r"([A-Za-z0-9._%+-]+)\s*(?:\[\s*at\s*\]|\(\s*at\s*\)|\{\s*at\s*\}|\[\s*apenstaartje\s*\])\s*"
    r"([A-Za-z0-9-]+(?:(?:\.|\s*\[\s*(?:dot|punt)\s*\]\s*|\s*\(\s*(?:dot|punt)\s*\)\s*)[A-Za-z0-9-]+)+)",
    re.I,
)
OBFUSCATED_DOT_RE = re.compile(r"\s*(?:\[\s*(?:dot|punt)\s*\]|\(\s*(?:dot|punt)\s*\))\s*", re.I)

PLACEHOLDER_LOCALS = {
    "name", "naam", "email", "e-mail", "mail", "your", "yourname", "jouw", "jouwnaam", "uw", "uwnaam",
    "voorbeeld", "example", "user", "username", "test", "firstname.lastname", "voornaam.achternaam",
}
PLACEHOLDER_DOMAIN_PREFIXES = ("example.", "domain.", "yourdomain.", "voorbeeld.", "email.", "test.")
PLACEHOLDER_DOMAIN_PARTS = ("sentry", "wixpress.com", "localhost")
ASSET_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js", ".ico", ".avif")

# Numbers right after these words are enterprise/VAT/bank numbers (or faxes), not phones.
NOT_PHONE_WORDS = re.compile(r"btw|tva|vat|kbo|bce|rpr|rpm|ondernemings|enterprise|iban|bic|rekening|bank|reg\.?\s*nr", re.I)
FAX_WORDS = re.compile(r"fax", re.I)
PHONE_WORDS = re.compile(r"tel|gsm|phone|mobiel|bel\s", re.I)
BE_PREFIX = re.compile(r"(?<![A-Za-z.])BE[\s.:-]?$")
KBO_SHAPE = re.compile(r"^\s*(?:BE\s*)?[01]\d{3}\.\d{3}\.\d{3}\s*$", re.I)
KBO_RE = re.compile(r"(?<![\dA-Za-z])(?:BE[\s.:-]?)?([01]\d{3})[\s.]?(\d{3})[\s.]?(\d{3})(?!\d)", re.I)
OLD_VAT_RE = re.compile(r"(?<![A-Za-z])BE[\s.:-]?([1-9]\d{2})[\s.]?(\d{3})[\s.]?(\d{3})(?!\d)", re.I)
INTL_ZERO_RE = re.compile(r"(\+32\s*)\(0\)\s*")

CONTACT_KEYS = ("telephone", "phone", "email", "vatID", "taxID", "streetAddress", "postalCode", "addressLocality", "name")


@dataclass
class Hit:
    value: str  # normalised
    display: str
    snippet: str
    via: str  # tel-link | mailto | cloudflare | json-ld | tekst
    before: str = ""  # surrounding text, used to find the street a number belongs to
    after: str = ""


@dataclass
class ParsedPage:
    url: str
    title: str
    text: str
    phones: list[Hit] = field(default_factory=list)
    emails: list[Hit] = field(default_factory=list)
    enterprise_numbers: dict[str, str] = field(default_factory=dict)  # number -> snippet
    links: list[tuple[str, str]] = field(default_factory=list)  # (absolute url, anchor text)


def snippet(text: str, start: int, end: int, width: int = 60) -> str:
    left = max(0, start - width)
    right = min(len(text), end + width)
    s = text[left:right].strip()
    return ("…" if left else "") + s + ("…" if right < len(text) else "")


# ---------- phones ----------

def format_phone(number: phonenumbers.PhoneNumber) -> tuple[str, str]:
    e164 = phonenumbers.format_number(number, PhoneNumberFormat.E164)
    style = PhoneNumberFormat.NATIONAL if number.country_code == 32 else PhoneNumberFormat.INTERNATIONAL
    return e164, phonenumbers.format_number(number, style)


def phone_from_string(raw: str | None) -> tuple[str, str] | None:
    if not raw:
        return None
    try:
        number = phonenumbers.parse(INTL_ZERO_RE.sub(r"\1", str(raw)), "BE")
    except NumberParseException:
        return None
    if not phonenumbers.is_valid_number(number):
        return None
    return format_phone(number)


def _last_end(regex: re.Pattern, text: str) -> int:
    return max((m.end() for m in regex.finditer(text)), default=-1)


def phones_in_text(text: str, exclude_digits: Iterable[str] = ()) -> list[Hit]:
    text = INTL_ZERO_RE.sub(r"\1", text)
    excluded = {d.lstrip("0") for d in exclude_digits if d}
    hits = []
    for match in phonenumbers.PhoneNumberMatcher(text, "BE", leniency=phonenumbers.Leniency.VALID):
        raw = match.raw_string
        before = text[max(0, match.start - 28):match.start]
        phone_word = _last_end(PHONE_WORDS, before)
        if KBO_SHAPE.match(raw) or BE_PREFIX.search(before):
            continue
        # skip when the closest label says VAT/KBO/bank/fax rather than tel/gsm ("Tel/Fax" stays)
        if _last_end(NOT_PHONE_WORDS, before) > phone_word:
            continue
        fax_word = _last_end(FAX_WORDS, before)
        if fax_word > phone_word and not PHONE_WORDS.search(before[max(0, fax_word - 12):fax_word]):
            continue
        if re.sub(r"\D", "", raw).lstrip("0") in excluded:
            continue
        e164, display = format_phone(match.number)
        hits.append(Hit(e164, display, snippet(text, match.start, match.end), "tekst",
                        before=text[max(0, match.start - 150):match.start], after=text[match.end:match.end + 80]))
    return hits


# ---------- e-mail ----------

def clean_email(raw: str | None) -> str | None:
    if not raw:
        return None
    email = unquote(str(raw)).strip().lower()
    if email.startswith("mailto:"):
        email = email[7:]
    email = email.split("?")[0].strip().strip(".,;:()[]<>\"'")
    if not EMAIL_FULL_RE.fullmatch(email):
        return None
    local, _, domain = email.partition("@")
    if local in PLACEHOLDER_LOCALS or domain.endswith(ASSET_SUFFIXES):
        return None
    if domain.startswith(PLACEHOLDER_DOMAIN_PREFIXES) or any(p in domain for p in PLACEHOLDER_DOMAIN_PARTS):
        return None
    return email


def decode_cfemail(encoded: str) -> str | None:
    """Cloudflare 'email protection' stores the address XOR-ed with its first byte."""
    try:
        key = int(encoded[:2], 16)
        return "".join(chr(int(encoded[i:i + 2], 16) ^ key) for i in range(2, len(encoded), 2))
    except (ValueError, IndexError):
        return None


def emails_in_text(text: str) -> list[Hit]:
    hits = []
    for match in EMAIL_RE.finditer(text):
        if email := clean_email(match.group(0)):
            hits.append(Hit(email, email, snippet(text, match.start(), match.end()), "tekst"))
    for match in OBFUSCATED_EMAIL_RE.finditer(text):
        domain = OBFUSCATED_DOT_RE.sub(".", match.group(2))
        if email := clean_email(f"{match.group(1)}@{domain}"):
            hits.append(Hit(email, email, snippet(text, match.start(), match.end()), "tekst"))
    return hits


# ---------- enterprise numbers ----------

def kbo_checksum_ok(number: str) -> bool:
    if len(number) != 10 or not number.isdigit() or number[0] not in "01":
        return False
    return 97 - int(number[:8]) % 97 == int(number[8:])


def format_kbo(number: str) -> str:
    return f"{number[:4]}.{number[4:7]}.{number[7:]}"


def enterprise_numbers_in_text(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for regex, pad in ((KBO_RE, ""), (OLD_VAT_RE, "0")):
        for match in regex.finditer(text):
            number = pad + "".join(match.groups())
            if kbo_checksum_ok(number) and number not in found:
                found[number] = snippet(text, match.start(), match.end(), 40)
    return found


# ---------- pages ----------

def _walk_jsonld(node: Any) -> Iterable[dict]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_jsonld(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_jsonld(value)


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def parse_page(html: str, url: str, exclude_digits: Iterable[str] = ()) -> ParsedPage:
    soup = BeautifulSoup(html, "html.parser")
    phones: list[Hit] = []
    emails: list[Hit] = []
    structured_text: list[str] = []

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in _walk_jsonld(data):
            address = obj.get("address")
            if isinstance(address, dict):
                address = " ".join(str(v) for k, v in address.items() if not k.startswith("@") and isinstance(v, (str, int)))
            address = str(address) if isinstance(address, (str, int)) else ""
            for key in ("telephone", "phone"):
                for value in _as_list(obj.get(key)):
                    if phone := phone_from_string(str(value)):
                        label = f"schema.org {key}: {value}" + (f" ({address})" if address else "")
                        phones.append(Hit(*phone, label, "json-ld", before=address))
            for value in _as_list(obj.get("email")):
                if email := clean_email(str(value)):
                    emails.append(Hit(email, email, f"schema.org email: {value}", "json-ld"))
            structured_text.extend(str(obj[k]) for k in CONTACT_KEYS if isinstance(obj.get(k), (str, int)))

    links: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        label = a.get_text(" ", strip=True)
        low = href.lower()
        if low.startswith("tel:"):
            if phone := phone_from_string(unquote(href[4:])):
                around = a.parent.get_text(" ", strip=True)[:300] if a.parent else label
                phones.append(Hit(*phone, label or href, "tel-link", before=around))
        elif low.startswith("mailto:"):
            if email := clean_email(href):
                emails.append(Hit(email, email, label or email, "mailto"))
        elif "/cdn-cgi/l/email-protection#" in low:
            if email := clean_email(decode_cfemail(href.split("#", 1)[1])):
                emails.append(Hit(email, email, label or "beschermd e-mailadres", "cloudflare"))
        elif not low.startswith(("javascript:", "#")):
            links.append((urljoin(url, href), label))

    for tag in soup.select("[data-cfemail]"):
        if email := clean_email(decode_cfemail(tag.get("data-cfemail", ""))):
            emails.append(Hit(email, email, "beschermd e-mailadres", "cloudflare"))

    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    full_text = text + (" " + " ".join(structured_text) if structured_text else "")

    phones += phones_in_text(text, exclude_digits)
    emails += emails_in_text(text)
    return ParsedPage(
        url=url,
        title=title,
        text=full_text,
        phones=phones,
        emails=emails,
        enterprise_numbers=enterprise_numbers_in_text(full_text),
        links=links,
    )
