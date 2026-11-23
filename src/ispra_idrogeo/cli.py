"""The ``idrogeo`` command: the library from a shell, no Python needed.

Downloads print the path they wrote; everything else prints JSON, one
object per line for lists (JSON Lines), so it pipes into ``jq``, a file or
a database loader.

    idrogeo fetch frane_piff --area puglia
    idrogeo summary pir comuni 72006
    idrogeo municipalities --max-age-days 30 > comuni.jsonl
    idrogeo municipalities --region 16 > puglia.jsonl
    idrogeo landslides --since 2026-11-01T00:00:00Z --select '*'
    idrogeo sites --filter stato_monitoraggio=eq.1
    idrogeo lookup formazioni argille
    idrogeo sync frane_piff pai_frane idraulica    # a local DuckDB copy, extra [warehouse]
    idrogeo sql "SELECT nome_reg, count(*) AS n FROM frane_piff GROUP BY 1"
    idrogeo hazard 40.829 14.617
    idrogeo near 40.838 14.630 --radius 500
    idrogeo watch --once >> changes.jsonl      # from cron
    idrogeo check facts.json < answer.txt      # numbers of a text not in the facts
    idrogeo dated --since 2018-01-01 --max-interval-days 1 --max-position-m 1000
    idrogeo reliability comuni 65135               # how far to trust IFFI in Sarno
    idrogeo freshness                              # when ISPRA last changed each file
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable, Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

from ispra_idrogeo.api import LOOKUPS
from ispra_idrogeo.cache import default_directory
from ispra_idrogeo.client import IdroGEO
from ispra_idrogeo.errors import IdrogeoError
from ispra_idrogeo.sources import (
    EVENT_LAYERS,
    LANDSLIDE_LAYERS,
    MOSAICS,
    Dataset,
    mosaic,
    opendata,
    sensor_data,
)
from ispra_idrogeo.watch import WATCHED, Kind, Mark, changes, load_marks, save_marks

_DATASETS = (*LANDSLIDE_LAYERS, *EVENT_LAYERS, *MOSAICS, "sensor_data")


def parser() -> argparse.ArgumentParser:
    """The command line, one sub-command per kind of data."""
    top = argparse.ArgumentParser(
        prog="idrogeo", description="ISPRA IdroGEO open data and API, from the shell."
    )
    top.add_argument("--dir", type=Path, help="download folder (default: IDROGEO_DATA_DIR)")
    commands = top.add_subparsers(dest="command", required=True, metavar="command")

    fetch = commands.add_parser("fetch", help="download (if changed) and unpack a dataset")
    fetch.add_argument("dataset", choices=_DATASETS)
    fetch.add_argument("--area", default="ispra", help="region or province (default: Italy)")
    fetch.add_argument("--geojson", action="store_true", help="GeoJSON instead of shapefile")
    fetch.add_argument("--no-unpack", action="store_true", help="keep the ZIP as it is")
    fetch.add_argument(
        "--progress",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="show a progress bar on stderr (default: when stderr is a terminal)",
    )

    summary = commands.add_parser("summary", help="IFFI counts or risk indicators of an area")
    summary.add_argument("summary", choices=("iffi", "pir"))
    summary.add_argument(
        "level", choices=("italia", "macroregioni", "regioni", "province", "comuni")
    )
    summary.add_argument("code", type=int, nargs="?", help="ISTAT code (none: the list)")

    every = commands.add_parser("municipalities", help="the summary of every municipality")
    every.add_argument("--summary", choices=("iffi", "pir"), default="pir")
    every.add_argument("--max-age-days", type=float, help="ask again answers older than this")
    every.add_argument("--concurrency", type=int, default=8)
    every.add_argument("--region", type=int, help="only those of this region (ISTAT code)")
    every.add_argument("--province", type=int, help="only those of this province (ISTAT code)")

    for name, what in (
        ("landslides", "IFFI landslides"),
        ("events", "dated landslide events"),
        ("sites", "monitoring sites"),
    ):
        search = commands.add_parser(name, help=f"every matching record: {what}")
        _search_options(search)
        if name == "landslides":
            area = search.add_argument_group("area (ISTAT codes; reads the whole inventory)")
            area.add_argument("--region", type=int)
            area.add_argument("--province", type=int)
            area.add_argument("--municipality", type=int)

    webcams = commands.add_parser("webcams", help="the webcams pointed at landslides")
    webcams.add_argument("--filter", action="append", default=[], metavar="FIELD=VALUE")

    one = commands.add_parser("landslide", help="the full record of one landslide")
    one.add_argument("id_frana")

    labels = commands.add_parser("labels", help="one code list as {code: label}")
    labels.add_argument("name", help="e.g. tipo_movimento, cause (see: idrogeo dictionaries)")
    labels.add_argument("--lang", choices=("it", "en", "fr", "de"), default="en")

    commands.add_parser("dictionaries", help="the names of the code lists")

    hazard = commands.add_parser("hazard", help="landslide and flood hazard of a point")
    hazard.add_argument("lat", type=float)
    hazard.add_argument("lon", type=float)
    hazard.add_argument("--lithology", action="store_true", help="add the rock type (~16 s)")

    near = commands.add_parser("near", help="the IFFI landslides around a point")
    near.add_argument("lat", type=float)
    near.add_argument("lon", type=float)
    near.add_argument("--radius", type=float, default=500, help="metres (default 500)")
    near.add_argument("--limit", type=int, default=200)

    watch = commands.add_parser(
        "watch", help="print the landslides, events and sites that change, as they change"
    )
    watch.add_argument(
        "--kind", action="append", choices=tuple(WATCHED), help="repeatable (default: all)"
    )
    watch.add_argument("--state", type=Path, help="marks file (default: <dir>/watch.json)")
    watch.add_argument("--since", type=_since, help="first run: start here (default: now)")
    watch.add_argument("--once", action="store_true", help="one round, then exit (for cron)")
    watch.add_argument("--interval", type=float, default=3600, help="seconds between rounds")

    lookup = commands.add_parser("lookup", help="search a reference list by text")
    lookup.add_argument("kind", choices=LOOKUPS)
    lookup.add_argument("text")
    lookup.add_argument("--limit", type=int, default=10)

    sync = commands.add_parser("sync", help="load layers into the local warehouse (DuckDB)")
    sync.add_argument("layers", nargs="+", choices=(*LANDSLIDE_LAYERS, *EVENT_LAYERS, *MOSAICS))
    sync.add_argument("--area", default="ispra", help="region or province (default: Italy)")

    sql = commands.add_parser("sql", help="one read-only SELECT on the local warehouse")
    sql.add_argument("query", nargs="?", help="SELECT …; without it, the tables and columns")
    sql.add_argument("--limit", type=int, default=1000)

    dated = commands.add_parser(
        "dated", help="dated landslides (IFFI and events) with the precision of date and place"
    )
    dated.add_argument("--since", type=date.fromisoformat, help="from this day (YYYY-MM-DD)")
    dated.add_argument("--until", type=date.fromisoformat, help="before this day (YYYY-MM-DD)")
    dated.add_argument("--region", type=int, help="ISTAT region code")
    dated.add_argument("--source", action="append", choices=("iffi", "eventi"), help="repeatable")
    dated.add_argument("--max-interval-days", type=int, help="1 keeps dates known to the day")
    dated.add_argument("--max-position-m", type=int, help="keeps points known to these metres")
    dated.add_argument("--summary", action="store_true", help="counts instead of the list")

    fresh = commands.add_parser(
        "freshness", help="date, size and changes of every published file (HEAD, no download)"
    )
    fresh.add_argument("--state", type=Path, help="where to keep the last answers")
    fresh.add_argument("--summary", action="store_true", help="counts instead of the list")

    trust = commands.add_parser(
        "reliability", help="how far to trust IFFI and the events in an area (no network)"
    )
    trust.add_argument("level", choices=("regioni", "province", "comuni"))
    trust.add_argument("code", type=int, nargs="?", help="ISTAT code; without it, every area")

    report = commands.add_parser(
        "report", help="the report of a municipality, in Italian, from a template (no model)"
    )
    report.add_argument("municipality", help="ISTAT code or exact name, e.g. 65135 or Sarno")
    report.add_argument("--out", type=Path, help="write the Markdown here (default: print it)")
    report.add_argument("--facts", type=Path, help="also write the figures it used, as JSON")
    report.add_argument(
        "--summary",
        action="store_true",
        help="add a short summary by a model (needs ANTHROPIC_API_KEY; paid), checked first",
    )
    report.add_argument("--model", default="claude-sonnet-5-5", help="for --summary")

    digest = commands.add_parser(
        "digest", help="what changed since the last digest: files, records, events"
    )
    digest.add_argument(
        "--kind", action="append", choices=tuple(WATCHED), help="repeatable (default: all)"
    )
    digest.add_argument("--since", type=_since, help="first digest: start here (default: 7 days)")
    digest.add_argument("--json", action="store_true", help="JSON instead of Markdown")

    check = commands.add_parser(
        "check", help="the numbers of a text that match no figure of a JSON file (no network)"
    )
    check.add_argument("facts", type=Path, help="JSON file the text was written from")
    check.add_argument("--text", type=Path, help="the text (default: standard input)")
    check.add_argument("--question", default="", help="numbers in it are allowed")
    return top


def _search_options(search: argparse.ArgumentParser) -> None:
    search.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help="repeatable; landslides take plain values (tipo_movimento=6), "
        "events and sites operators (regione=eq.16)",
    )
    search.add_argument("--since", type=_since, help="only records changed since (ISO, with zone)")
    search.add_argument("--select", help="comma-separated fields, or '*' for all and geometry")


def _since(text: str) -> datetime:
    when = datetime.fromisoformat(text)
    if when.tzinfo is None:
        raise argparse.ArgumentTypeError(f"{text!r} needs a time zone, e.g. {text}Z")
    return when


def filters(pairs: Iterable[str]) -> dict[str, Any]:
    """``["tipo_movimento=6", "stato=validato_ispra"]`` as a filter object.

    Whole numbers become numbers, as landslide filters need; anything else
    stays text.
    """
    out: dict[str, Any] = {}
    for pair in pairs:
        field, sep, value = pair.partition("=")
        if not sep or not field:
            raise ValueError(f"filter {pair!r} is not FIELD=VALUE")
        out[field] = int(value) if value.lstrip("-").isdigit() else value
    return out


def _dataset(name: str, area: str, geojson: bool) -> Dataset:
    if name == "sensor_data":
        return sensor_data()
    if name in MOSAICS:
        return mosaic(name)
    return opendata(name, area, "geojson" if geojson else "shapefile")  # type: ignore[arg-type]


async def run(
    args: argparse.Namespace,
    idrogeo: IdroGEO,
    out: TextIO,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
) -> None:
    """Carry out one parsed command, writing its result to ``out``."""
    write: Callable[[Any], None] = lambda value: print(  # noqa: E731
        json.dumps(value, ensure_ascii=False, default=str), file=out
    )
    command = args.command
    if command == "fetch":
        dataset = _dataset(args.dataset, args.area, args.geojson)
        show = sys.stderr.isatty() if args.progress is None else args.progress
        bar = _bar(dataset.filename, sys.stderr) if show else None
        print(
            await idrogeo.fetch(dataset, args.dir, unpack=not args.no_unpack, progress=bar),
            file=out,
        )
        if bar is not None:
            print(file=sys.stderr)
    elif command == "summary":
        write(await idrogeo.summary(args.summary, args.level, args.code))
    elif command == "municipalities":
        age = None if args.max_age_days is None else timedelta(days=args.max_age_days)
        rows = await idrogeo.municipalities(
            args.summary,
            args.dir,
            concurrency=args.concurrency,
            max_age=age,
            region=args.region,
            province=args.province,
        )
        for row in rows:
            write(row)
    elif command == "landslides" and (args.region or args.province or args.municipality):
        found = idrogeo.iter_landslides_in(
            region=args.region,
            province=args.province,
            municipality=args.municipality,
            filters=filters(args.filter),
            modified_since=args.since,
            select=_select(args),
        )
        await _lines(found, write)
    elif command in ("landslides", "events"):
        search = idrogeo.iter_landslides if command == "landslides" else idrogeo.iter_events
        found = search(filters(args.filter), modified_since=args.since, select=_select(args))
        await _lines(found, write)
    elif command == "sites":
        for row in await idrogeo.sites(
            filters(args.filter), modified_since=args.since, select=_select(args)
        ):
            write(row)
    elif command == "webcams":
        for row in await idrogeo.webcams(filters(args.filter)):
            write(row)
    elif command == "landslide":
        write(await idrogeo.landslide(args.id_frana))
    elif command == "labels":
        write(await idrogeo.labels(args.name, args.lang))
    elif command == "hazard":
        write(asdict(await idrogeo.hazard_at(args.lat, args.lon, lithology=args.lithology)))
    elif command == "near":
        for row in await idrogeo.landslides_near(args.lat, args.lon, args.radius, limit=args.limit):
            write(row)
    elif command == "watch":
        await _watch(args, idrogeo, write, sleep)
    elif command == "freshness":
        from ispra_idrogeo import freshness as fresh

        state = args.state or (args.dir or default_directory()) / fresh.STATE
        files = await fresh.freshness(idrogeo, state=state)
        if args.summary:
            write(fresh.summary(files))
        else:
            for item in files:
                write(item.as_dict())
    elif command == "dated":
        from ispra_idrogeo.dated import dated_landslides, summary

        landslides = await dated_landslides(
            idrogeo,
            sources=args.source or ("iffi", "eventi"),
            since=args.since,
            until=args.until,
            region=args.region,
            max_interval_days=args.max_interval_days,
            max_position_m=args.max_position_m,
            directory=args.dir,
        )
        if args.summary:
            write(summary(landslides))
        else:
            for one in landslides:
                write(one.as_dict())
    elif command == "lookup":
        for row in await idrogeo.lookup(args.kind, args.text, limit=args.limit):
            write(row)
    elif command in ("sync", "sql"):
        await _warehouse(args, idrogeo, write)
    elif command == "report":
        await _report(args, idrogeo, out)
    elif command == "digest":
        from ispra_idrogeo.digest import digest

        folder = args.dir or default_directory()
        folder.mkdir(parents=True, exist_ok=True)
        changed = await digest(idrogeo, folder, args.kind, args.since)
        if args.json:
            write(changed.as_dict())
        else:
            out.write(changed.markdown())
    else:  # dictionaries
        write(await idrogeo.dictionaries())


def _bar(name: str, stream: TextIO) -> Callable[[int, int | None], None]:
    """A one-line progress bar: ``name  12.3 / 573.0 MB  2%``, rewritten in place."""

    def show(done: int, total: int | None) -> None:
        mb = done / 1e6
        if total:
            line = f"{name}  {mb:,.1f} / {total / 1e6:,.1f} MB  {100 * done // total}%"
        else:
            line = f"{name}  {mb:,.1f} MB"
        print(f"\r{line}", end="", file=stream, flush=True)

    return show


async def _watch(
    args: argparse.Namespace,
    idrogeo: IdroGEO,
    write: Callable[[Any], None],
    sleep: Callable[[float], Awaitable[Any]],
) -> None:
    kinds: list[Kind] = args.kind or list(WATCHED)
    state: Path = args.state or (args.dir or default_directory()) / "watch.json"
    marks = load_marks(state)
    start = args.since or datetime.now(UTC)
    for kind in kinds:
        if kind not in marks:
            marks[kind] = Mark(start)
    save_marks(state, marks)
    while True:
        for kind in kinds:
            rows, marks[kind] = await changes(idrogeo, kind, marks[kind])
            for row in rows:
                write({"kind": kind, **row})
            save_marks(state, marks)
        if args.once:
            return
        await sleep(args.interval)


async def _report(args: argparse.Namespace, idrogeo: IdroGEO, out: TextIO) -> None:
    from ispra_idrogeo.report import area_report, find_municipality, summarize

    code = await find_municipality(idrogeo, args.municipality)
    found = await area_report(idrogeo, code)
    if args.summary:  # paid; raises before anything is written if a number is not backed
        found = await asyncio.to_thread(summarize, found, None, args.model)
    if args.facts:
        args.facts.write_text(json.dumps(found.facts, ensure_ascii=False, indent=2) + "\n")
    if args.out:
        args.out.write_text(found.markdown(), encoding="utf-8")
    else:
        out.write(found.markdown())


async def _warehouse(
    args: argparse.Namespace, idrogeo: IdroGEO, write: Callable[[Any], None]
) -> None:
    from ispra_idrogeo.cache import default_directory
    from ispra_idrogeo.warehouse import FILENAME, Warehouse

    path = (args.dir or default_directory()) / FILENAME
    with Warehouse(path, read_only=args.command == "sql") as warehouse:
        if args.command == "sync":
            write(await warehouse.sync(idrogeo, args.layers, args.area, args.dir))
        elif not args.query:
            write(warehouse.schema())
        else:
            for row in warehouse.query(args.query, limit=args.limit):
                write(row)


def _select(args: argparse.Namespace) -> list[str] | None:
    return [f.strip() for f in args.select.split(",")] if args.select else None


async def _lines(rows: AsyncIterable[Any], write: Callable[[Any], None]) -> None:
    async for row in rows:
        write(row)


async def _main(args: argparse.Namespace, out: TextIO) -> None:
    async with IdroGEO() as idrogeo:
        await run(args, idrogeo, out)


def _reliability(args: argparse.Namespace, out: TextIO) -> int:
    """``idrogeo reliability``: one area, or every area of a level, as JSON lines."""
    from ispra_idrogeo.reliability import reliability_map

    found = reliability_map()
    try:
        areas = [found.at(args.level, args.code)] if args.code else found.all(args.level)
    except ValueError as exc:
        print(f"idrogeo: {exc}", file=sys.stderr)
        return 1
    for area in areas:
        out.write(json.dumps(area.as_dict(), ensure_ascii=False) + "\n")
    return 0


def _check(args: argparse.Namespace, out: TextIO) -> int:
    """``idrogeo check``: 0 when every number is backed by the facts, else 1."""
    from ispra_idrogeo.grounding import check_claims, check_text

    facts = json.loads(args.facts.read_text(encoding="utf-8"))
    text = args.text.read_text(encoding="utf-8") if args.text else sys.stdin.read()
    missing = check_text(text, facts, args.question)
    wrong = [asdict(m) for m in check_claims(text, facts)]
    ok = not missing and not wrong
    out.write(
        json.dumps({"unmatched": missing, "misquoted": wrong, "ok": ok}, ensure_ascii=False) + "\n"
    )
    return 0 if ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of the ``idrogeo`` command; the exit status."""
    args = parser().parse_args(argv)
    if args.command == "reliability":
        return _reliability(args, sys.stdout)
    if args.command == "check":
        try:
            return _check(args, sys.stdout)
        except (OSError, ValueError) as exc:
            print(f"idrogeo: {exc}", file=sys.stderr)
            return 1
    try:
        asyncio.run(_main(args, sys.stdout))
    except (IdrogeoError, ValueError, ImportError) as exc:
        print(f"idrogeo: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:  # `idrogeo landslides | head`
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
