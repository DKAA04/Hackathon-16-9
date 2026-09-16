"""Small local HTTP API around the enricher, used by the frontend when the main backend
has no enrichment endpoint. Standard library only.

    python -m enrichment.server            # http://127.0.0.1:8765

GET  /health
POST /enrich          one register row (VKBO or backend field names)  -> EnrichmentResult.to_dict()
POST /enrich/batch    {"records": [...]} (max 20)                     -> {"results": [...]}
"""
from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .pipeline import Enricher, Options
from .records import target_from_row

MAX_BATCH = 20
MAX_BODY = 1_000_000


def make_handler(enricher: Enricher, allow_origin: str = "*"):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DuckDuckGovEnrichment/0.1"

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", allow_origin)
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def _send(self, status: int, payload: object) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # CORS preflight
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            if self.path.split("?")[0].rstrip("/") in ("", "/health"):
                self._send(HTTPStatus.OK, {
                    "ok": True,
                    "sources": ["kbo", "osm" if enricher.options.use_osm else None, "website",
                                "google_maps" if enricher.options.use_google and enricher.google_key else None,
                                "web_search" if enricher.options.use_web_search and enricher.openai_key else None],
                    "max_batch": MAX_BATCH,
                })
                return
            self._send(HTTPStatus.NOT_FOUND, {"detail": "not found"})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"detail": "request too large"})
                return
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send(HTTPStatus.BAD_REQUEST, {"detail": "invalid JSON"})
                return
            path = self.path.split("?")[0].rstrip("/")
            try:
                if path == "/enrich":
                    row = data.get("record", data) if isinstance(data, dict) else None
                    target = target_from_row(row) if isinstance(row, dict) else None
                    if target is None:
                        self._send(HTTPStatus.UNPROCESSABLE_ENTITY, {"detail": "record needs at least a name"})
                        return
                    self._send(HTTPStatus.OK, enricher.enrich(target).to_dict())
                elif path == "/enrich/batch":
                    rows = data.get("records") if isinstance(data, dict) else None
                    if not isinstance(rows, list) or not rows:
                        self._send(HTTPStatus.UNPROCESSABLE_ENTITY, {"detail": "give a non-empty 'records' list"})
                        return
                    if len(rows) > MAX_BATCH:
                        self._send(HTTPStatus.UNPROCESSABLE_ENTITY, {"detail": f"max {MAX_BATCH} records per call"})
                        return
                    targets = [t for t in (target_from_row(r) for r in rows if isinstance(r, dict)) if t]
                    results = enricher.enrich_many(targets, workers=4)
                    self._send(HTTPStatus.OK, {"results": [r.to_dict() for r in results]})
                else:
                    self._send(HTTPStatus.NOT_FOUND, {"detail": "not found"})
            except Exception as exc:  # keep the server alive for the next request
                self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"detail": f"enrichment failed: {type(exc).__name__}"})

        def log_message(self, fmt: str, *args) -> None:
            print(f"[enrichment] {fmt % args}", flush=True)

    return Handler


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m enrichment.server", description="DuckDuckGov local enrichment API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--allow-origin", default="*")
    p.add_argument("--no-google", action="store_true")
    p.add_argument("--no-web-search", action="store_true")
    args = p.parse_args(argv)

    enricher = Enricher(Options(use_google=not args.no_google, use_web_search=not args.no_web_search))
    server = ThreadingHTTPServer((args.host, args.port), make_handler(enricher, args.allow_origin))
    print(f"DuckDuckGov enrichment API on http://{args.host}:{args.port} (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        enricher.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
