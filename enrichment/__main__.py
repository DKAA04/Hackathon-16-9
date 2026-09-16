"""Command line: python -m enrichment --help"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from .export import write_csv, write_json
from .models import EnrichmentResult, EnrichTarget
from .pipeline import Enricher, Options
from .records import fetch_vkbo, load_file, target_from_row

OUT_DIR = Path(__file__).resolve().parent / "out"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m enrichment",
        description="DuckDuckGov: find phone numbers, e-mail addresses and websites for register records, with evidence.",
    )
    src = p.add_argument_group("input (choose one)")
    src.add_argument("--input", help="CSV / GeoJSON / JSON file with register rows (VKBO columns or name/street/...)")
    src.add_argument("--gemeente", help="municipality: fetch live VKBO rows, or the town of --name")
    src.add_argument("--straat", help="with --gemeente: only this street (exact KBO spelling)")
    src.add_argument("--name", help="enrich one business given on the command line")
    one = p.add_argument_group("single business (with --name)")
    one.add_argument("--trade-name")
    one.add_argument("--street")
    one.add_argument("--number")
    one.add_argument("--postcode")
    one.add_argument("--kbo", help="enterprise number, digits only")
    one.add_argument("--website")
    one.add_argument("--lat", type=float)
    one.add_argument("--lon", type=float)

    flt = p.add_argument_group("filters")
    flt.add_argument("--limit", type=int, help="max records to enrich")
    flt.add_argument("--only-flagged", action="store_true", help="only records with register red flags")
    flt.add_argument("--only-missing", action="store_true", help="only records without a phone number in the register")
    flt.add_argument("--ids", help="comma-separated record numbers to keep")

    run = p.add_argument_group("sources")
    run.add_argument("--no-osm", action="store_true")
    run.add_argument("--no-google", action="store_true")
    run.add_argument("--no-web-search", action="store_true")
    run.add_argument("--no-guess", action="store_true", help="do not try domain names derived from the business name")
    run.add_argument("--no-cache", action="store_true")
    run.add_argument("--workers", type=int, default=4)

    out = p.add_argument_group("output")
    out.add_argument("--out", help="output path without extension (default: enrichment/out/<timestamp>)")
    out.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)
    if not (args.input or args.name or args.gemeente):
        p.error("give --input FILE, --gemeente NAME, or --name NAME")
    return args


def load_targets(args: argparse.Namespace) -> list[EnrichTarget]:
    if args.name:
        return [EnrichTarget(
            record_id=args.kbo or "", name=args.name, trade_name=args.trade_name, enterprise_number=args.kbo,
            street=args.street, house_number=args.number, postcode=args.postcode, municipality=args.gemeente,
            lat=args.lat, lon=args.lon, known_website=args.website,
        )]
    if args.input:
        rows = load_file(args.input)
    else:
        print(f"VKBO ophalen voor {args.gemeente}{' / ' + args.straat if args.straat else ''} ...", file=sys.stderr)
        # fetch everything when filtering, otherwise only what is needed
        needs_all = args.only_flagged or args.only_missing or args.ids
        rows = fetch_vkbo(args.gemeente, args.straat, None if needs_all else args.limit)
    targets = [t for t in (target_from_row(r) for r in rows) if t]
    if args.ids:
        wanted = {"".join(ch for ch in i if ch.isdigit()).zfill(10) for i in args.ids.split(",")}
        targets = [t for t in targets if t.record_id in wanted]
    if args.only_flagged:
        targets = [t for t in targets if t.flags]
    if args.only_missing:
        targets = [t for t in targets if not t.known_phone]
    return targets[: args.limit] if args.limit else targets


def line(result: EnrichmentResult) -> str:
    parts = []
    for kind, label in (("phone", "tel"), ("email", "mail"), ("website", "web")):
        if f := result.best(kind):
            parts.append(f"{label} {f.display} [{f.level} {f.confidence}]")
    for s in result.signals:
        if s.value != "osm_opening_hours":
            parts.append(f"! {s.display}")
    t = result.target
    return f"{t.display_name[:40]:<40} | " + (" | ".join(parts) or "niets gevonden")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = parse_args(argv)
    targets = load_targets(args)
    if not targets:
        print("Geen records om te verrijken.", file=sys.stderr)
        return 1

    options = Options(
        use_osm=not args.no_osm,
        use_google=not args.no_google,
        use_web_search=not args.no_web_search,
        guess_domains=not args.no_guess,
        use_cache=not args.no_cache,
    )
    enricher = Enricher(options)
    active = ["website"] + (["osm"] if options.use_osm else [])
    active += ["google_maps"] if options.use_google and enricher.google_key else []
    active += ["web_search"] if options.use_web_search and enricher.openai_key else []
    print(f"{len(targets)} records, bronnen: {', '.join(active)}", file=sys.stderr)

    started = time.perf_counter()

    def progress(index: int, total: int, result: EnrichmentResult) -> None:
        if not args.quiet:
            print(f"[{index + 1:>3}/{total}] {line(result)}", flush=True)

    try:
        results = enricher.enrich_many(targets, workers=args.workers, progress=progress)
    finally:
        enricher.close()

    stem = Path(args.out) if args.out else OUT_DIR / datetime.now().strftime("enrichment-%Y%m%d-%H%M%S")
    json_path = write_json(results, stem.with_suffix(".json"), used_google="google_maps" in active)
    csv_path = write_csv(results, stem.with_suffix(".csv"))
    with_phone = sum(1 for r in results if r.phones)
    with_email = sum(1 for r in results if r.emails)
    print(
        f"\n{len(results)} records in {time.perf_counter() - started:.0f}s: "
        f"{with_phone} met telefoon, {with_email} met e-mail.\n"
        f"JSON: {json_path}\nCSV:  {csv_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
