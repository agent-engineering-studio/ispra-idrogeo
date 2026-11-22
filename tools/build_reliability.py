"""Build src/ispra_idrogeo/data/reliability.json from the live IdroGEO service.

    uv run python tools/build_reliability.py           # about two minutes

For every region, province and municipality it measures how far the IFFI
inventory and the dated events can be trusted for a study that needs dates
(rainfall thresholds) or a complete count: see ispra_idrogeo.reliability.
It reads the whole inventory once (about 50 s), the events file (100 kB) and
the area of every municipality (cached on disk for 30 days).
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from ispra_idrogeo import IdroGEO
from ispra_idrogeo.dated import from_event, from_iffi
from ispra_idrogeo.reliability import FIELDS, LEVELS
from ispra_idrogeo.sources import opendata

OUT = Path(__file__).parent.parent / "src" / "ispra_idrogeo" / "data" / "reliability.json"
SINCE = date(2018, 1, 1)
EDITED_SINCE = "2021"
SELECT = [
    "id_frana",
    "regione",
    "provincia",
    "comune",
    "data_certa",
    "data_incerta_min",
    "data_incerta_max",
    "modified",
]
CODE = {"regioni": "regione", "province": "provincia", "comuni": "comune"}


def _new() -> dict[str, Any]:
    return defaultdict(int)


async def main() -> None:
    today = datetime.now(UTC).date()
    counts: dict[str, dict[int, dict[str, Any]]] = {lv: defaultdict(_new) for lv in LEVELS}
    async with IdroGEO() as idrogeo:
        rows = idrogeo.iter_landslides(select=SELECT, page_size=1_000_000)
        async for row in rows:
            dated = from_iffi(row, today)
            for level in LEVELS:
                code = row.get(CODE[level])
                if code is None:
                    continue
                c = counts[level][int(code)]
                c["landslides"] += 1
                c["edited_recently"] += str(row.get("modified") or "")[:4] >= EDITED_SINCE
                if dated:
                    c["dated"] += 1
                    if dated.interval_days == 1:
                        c["dated_to_the_day"] += 1
                        c["iffi_day_since_2018"] += dated.start >= SINCE
        folder = await idrogeo.fetch(opendata("eventi", fmt="geojson"))
        for path in folder.glob("*.json"):
            for feature in json.loads(path.read_text(encoding="utf-8"))["features"]:
                event = from_event(feature, today)
                if not event or event.start < SINCE:
                    continue
                for level, code in (
                    ("regioni", event.region),
                    ("province", event.province),
                    ("comuni", event.municipality),
                ):
                    if code is None:
                        continue
                    c = counts[level][code]
                    c["events_since_2018"] += 1
                    known = event.position_m is not None and event.position_m <= 1000
                    c["events_within_1km"] += known
        names: dict[str, dict[int, str]] = {}
        areas: dict[str, dict[int, float]] = {}
        for level in LEVELS:
            summaries = await idrogeo.summaries("pir", level, max_age=timedelta(days=30))
            names[level] = {int(s["uid"]): str(s["nome"]) for s in summaries}
            areas[level] = {
                int(s["uid"]): float(s["ar_kmq"])
                for s in summaries
                if isinstance(s.get("ar_kmq"), int | float)
            }
        iffi_regions = {
            int(r["uid"]): int(r["frane_totali"])
            for r in await idrogeo.summaries("iffi", "regioni")
        }

    out: dict[str, Any] = {
        "built_on": today.isoformat(),
        "since": SINCE.isoformat(),
        "edited_since": EDITED_SINCE,
        "fields": list(FIELDS),
        "levels": {},
    }
    for level in LEVELS:
        table: dict[str, list[Any]] = {}
        for code in sorted(set(names[level]) | set(counts[level])):
            c = counts[level].get(code, {})
            area = areas[level].get(code)
            table[str(code)] = [
                names[level].get(code),
                round(area, 2) if area else None,
                c.get("landslides", 0),
                c.get("dated", 0),
                c.get("dated_to_the_day", 0),
                c.get("iffi_day_since_2018", 0),
                c.get("events_since_2018", 0),
                c.get("events_within_1km", 0),
                c.get("edited_recently", 0),
            ]
        out["levels"][level] = table
    # check: the inventory counted per region is the API's own count
    for code, total in iffi_regions.items():
        mine = counts["regioni"].get(code, {}).get("landslides", 0)
        if mine != total:
            print(f"region {code}: {mine} counted, the API says {total}", file=sys.stderr)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    total = sum(c["landslides"] for c in counts["regioni"].values())
    print(f"{OUT}: {OUT.stat().st_size // 1024} kB, {total:,} landslides")


if __name__ == "__main__":
    asyncio.run(main())
