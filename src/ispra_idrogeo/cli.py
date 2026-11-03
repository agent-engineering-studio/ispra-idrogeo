"""The ``idrogeo`` command: the library from a shell, no Python needed.

Downloads print the path they wrote; everything else prints JSON, one
object per line for lists (JSON Lines), so it pipes into ``jq``, a file or
a database loader.

    idrogeo fetch frane_piff --area puglia
    idrogeo summary pir comuni 72006
    idrogeo municipalities --max-age-days 30 > comuni.jsonl
    idrogeo landslides --since 2026-11-01T00:00:00Z --select '*'
    idrogeo sites --filter stato_monitoraggio=eq.1
    idrogeo lookup formazioni argille
    idrogeo hazard 40.829 14.617
    idrogeo near 40.838 14.630 --radius 500
    idrogeo watch --once >> changes.jsonl      # from cron
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
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

    for name, what in (
        ("landslides", "IFFI landslides"),
        ("events", "dated landslide events"),
        ("sites", "monitoring sites"),
    ):
        search = commands.add_parser(name, help=f"every matching record: {what}")
        _search_options(search)

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
        json.dumps(value, ensure_ascii=False), file=out
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
            args.summary, args.dir, concurrency=args.concurrency, max_age=age
        )
        for row in rows:
            write(row)
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
    elif command == "lookup":
        for row in await idrogeo.lookup(args.kind, args.text, limit=args.limit):
            write(row)
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


def _select(args: argparse.Namespace) -> list[str] | None:
    return [f.strip() for f in args.select.split(",")] if args.select else None


async def _lines(rows: AsyncIterable[Any], write: Callable[[Any], None]) -> None:
    async for row in rows:
        write(row)


async def _main(args: argparse.Namespace, out: TextIO) -> None:
    async with IdroGEO() as idrogeo:
        await run(args, idrogeo, out)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of the ``idrogeo`` command; the exit status."""
    args = parser().parse_args(argv)
    try:
        asyncio.run(_main(args, sys.stdout))
    except (IdrogeoError, ValueError) as exc:
        print(f"idrogeo: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:  # `idrogeo landslides | head`
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
