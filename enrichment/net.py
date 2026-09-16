"""Polite HTTP access: robots.txt, per-host throttling, public-URL guard, size cap, disk cache."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import httpx

USER_AGENT = "DuckDuckGov-enrichment/0.1 (PROV-AI hackathon prototype; not affiliated with DuckDuckGo)"
CACHE_DIR = Path(__file__).resolve().parent / ".cache"
MAX_BYTES = 2_000_000
PAGE_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


class FetchError(Exception):
    pass


@dataclass
class Page:
    url: str
    status: int
    text: str
    from_cache: bool = False


def is_public_url(url: str) -> bool:
    """Only fetch http(s) URLs that resolve to public addresses (no localhost / LAN)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443)
    except (UnicodeError, OSError, ValueError):
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return bool(infos)


class _DisallowAll:
    def can_fetch(self, *_args) -> bool:
        return False


class Fetcher:
    def __init__(self, use_cache: bool = True, cache_ttl_hours: float = 72, host_delay: float = 1.0,
                 timeout: float = 12.0):
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "nl-BE,nl;q=0.9,en;q=0.6"},
            timeout=timeout,
            follow_redirects=False,
        )
        self.use_cache = use_cache
        self.cache_ttl = cache_ttl_hours * 3600
        self.host_delay = host_delay
        self._robots: dict[str, Any] = {}
        self._last_hit: dict[str, float] = {}
        self._host_locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        self.client.close()

    # ----- cache -----

    def _cache_path(self, key: str) -> Path:
        return CACHE_DIR / f"{hashlib.sha256(key.encode()).hexdigest()[:32]}.json"

    def cache_get(self, key: str, ttl: float | None = None) -> Any | None:
        if not self.use_cache:
            return None
        path = self._cache_path(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if time.time() - payload.get("stored_at", 0) > (ttl or self.cache_ttl):
            return None
        return payload.get("data")

    def cache_put(self, key: str, data: Any) -> None:
        if not self.use_cache:
            return
        payload = {"key": key, "stored_at": time.time(), "data": data}
        self._cache_path(key).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    # ----- politeness -----

    def throttle(self, host: str) -> None:
        with self._lock:
            lock = self._host_locks.setdefault(host, threading.Lock())
        with lock:
            wait = self._last_hit.get(host, 0.0) + self.host_delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_hit[host] = time.monotonic()

    def robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            known = base in self._robots
            parser = self._robots.get(base)
        if not known:
            parser = self._load_robots(base)
            with self._lock:
                self._robots[base] = parser
        return True if parser is None else parser.can_fetch(USER_AGENT, url)

    def _load_robots(self, base: str):
        try:
            self.throttle(urlsplit(base).hostname or base)
            r = self.client.get(base + "/robots.txt", timeout=6.0, follow_redirects=True)
        except httpx.HTTPError:
            return None  # the page request itself will fail and be reported
        if r.status_code >= 500:
            return _DisallowAll()
        if r.status_code >= 400:
            return None
        parser = robotparser.RobotFileParser()
        parser.parse(r.text.splitlines())
        return parser

    # ----- requests -----

    def get(self, url: str, max_redirects: int = 5) -> Page:
        key = "GET " + url
        if (cached := self.cache_get(key)) is not None:
            return Page(**cached, from_cache=True)
        current = url
        for _ in range(max_redirects + 1):
            if not is_public_url(current):
                raise FetchError(f"niet bereikbaar of geen publiek adres: {current}")
            if not self.robots_allows(current):
                raise FetchError(f"robots.txt staat dit niet toe: {current}")
            self.throttle(urlsplit(current).hostname or "")
            try:
                with self.client.stream("GET", current) as r:
                    if r.is_redirect:
                        location = r.headers.get("location")
                        if not location:
                            raise FetchError(f"redirect zonder doel: {current}")
                        current = urljoin(current, location)
                        continue
                    if r.status_code >= 400:
                        raise FetchError(f"HTTP {r.status_code}: {current}")
                    ctype = r.headers.get("content-type", "").lower()
                    if ctype and not ctype.startswith(PAGE_TYPES):
                        raise FetchError(f"geen webpagina ({ctype.split(';')[0]}): {current}")
                    body = bytearray()
                    for chunk in r.iter_bytes():
                        body.extend(chunk)
                        if len(body) >= MAX_BYTES:
                            break
                    text = bytes(body[:MAX_BYTES]).decode(r.charset_encoding or "utf-8", errors="replace")
                    page = Page(url=str(r.url), status=r.status_code, text=text)
            except httpx.HTTPError as exc:
                raise FetchError(f"{type(exc).__name__}: {current}") from exc
            self.cache_put(key, {"url": page.url, "status": page.status, "text": page.text})
            return page
        raise FetchError(f"te veel redirects: {url}")

    def post(self, url: str, **kwargs) -> httpx.Response:
        self.throttle(urlsplit(url).hostname or "")
        return self.client.post(url, **kwargs)
