"""How far to trust IFFI here: a map of the inventory's dates, events and upkeep.

IFFI is the best map of Italy's landslides, but it is not the same
everywhere. Some regions date many of their landslides and others none; some
were edited last year and others twenty years ago. A study that needs dates
(a rainfall threshold) or a fair count (a comparison between towns) should
know which, place by place, before it starts.

:func:`reliability` answers for a region, province or municipality (ISTAT
code), from a table shipped with the package (``data/reliability.json``,
built by ``tools/build_reliability.py`` from the live service, date in
:attr:`ReliabilityMap.built_on`):

- **landslides** and their **density** per km²;
- **dated**: the share of IFFI landslides with any date, and **to the day**;
- **since 2018**: IFFI landslides dated to the day, and events (each with a
  stated accuracy of its point, ``events_within_1km`` known to 1 km);
- **edited since 2021**: the share of records changed in IdroGEO's database
  since 2021. Bulk loads count too (117,282 records carry the placeholder
  date 2000-12-31, 79,772 the migration of 18 July 2017), so this is how
  recently the inventory was *touched*, not when the landslides were
  surveyed.

It is an estimate made from outside: ISPRA publishes no quality map of IFFI,
nor the year each region last updated it (the open-data page says it differs
by region, without the years). What cannot be measured is in
:data:`NOT_MEASURED`, and every answer carries it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import cache
from importlib import resources
from typing import Any, Literal

from ispra_idrogeo.grounding import SOURCES

Level = Literal["regioni", "province", "comuni"]
LEVELS: tuple[Level, ...] = ("regioni", "province", "comuni")
#: The columns of each row of the table, in order.
FIELDS = (
    "name",
    "area_km2",
    "landslides",
    "dated",
    "dated_to_the_day",
    "iffi_day_since_2018",
    "events_since_2018",
    "events_within_1km",
    "edited_recently",
)
#: What this map cannot say, said with every answer.
NOT_MEASURED = (
    "the accuracy of IFFI positions: every record says 'esatta'",
    "how complete the inventory is: there is no reference to compare it with",
    "whether an event and an IFFI record are the same landslide",
    "the year each region last surveyed its landslides: ISPRA does not publish it",
)


@dataclass(frozen=True, slots=True)
class Reliability:
    """How far IFFI and the events can be trusted in one area."""

    level: Level
    code: int
    name: str | None
    area_km2: float | None
    landslides: int
    #: Landslides per km², ``None`` without an area.
    density_per_km2: float | None
    #: Shares (0 to 1) of the IFFI landslides here; ``None`` when there are none.
    dated_share: float | None
    day_share: float | None
    iffi_day_since_2018: int
    events_since_2018: int
    events_within_1km: int
    edited_since_2021_share: float | None
    #: The numbers above in plain words.
    notes: tuple[str, ...]
    built_on: str
    not_measured: tuple[str, ...] = NOT_MEASURED
    source: str = SOURCES["iffi"]

    @property
    def dated_since_2018(self) -> int:
        """Landslides dated to the day since 2018, IFFI and events (may overlap)."""
        return self.iffi_day_since_2018 + self.events_since_2018

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready, with ``dated_since_2018``."""
        out = asdict(self)
        out["notes"], out["not_measured"] = list(self.notes), list(self.not_measured)
        out["dated_since_2018"] = self.dated_since_2018
        return out


@dataclass(frozen=True)
class ReliabilityMap:
    """The table of every area, as built on :attr:`built_on`."""

    built_on: str
    levels: dict[str, dict[str, list[Any]]]

    def at(self, level: Level, code: int) -> Reliability:
        """One area; ``ValueError`` for an unknown level or code."""
        if level not in LEVELS:
            raise ValueError(f"unknown level {level!r}: one of {LEVELS}")
        row = self.levels[level].get(str(code))
        if row is None:
            raise ValueError(f"no {level} with ISTAT code {code} in the map of {self.built_on}")
        return _reliability(level, code, dict(zip(FIELDS, row, strict=True)), self.built_on)

    def all(self, level: Level) -> list[Reliability]:
        """Every area of a level, by ISTAT code."""
        return [self.at(level, int(code)) for code in self.levels[level]]


@cache
def reliability_map() -> ReliabilityMap:
    """The map shipped with the package, read once."""
    text = resources.files("ispra_idrogeo").joinpath("data/reliability.json").read_text("utf-8")
    data = json.loads(text)
    if tuple(data["fields"]) != FIELDS:
        raise ValueError("data/reliability.json has other fields: rebuild it")
    return ReliabilityMap(built_on=data["built_on"], levels=data["levels"])


def reliability(level: Level, code: int) -> Reliability:
    """How far IFFI and the events can be trusted in a region, province or municipality."""
    return reliability_map().at(level, code)


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _pct(share: float) -> str:
    return f"{share * 100:.1f}%" if share >= 0.001 or share == 0 else "<0.1%"


def _reliability(level: Level, code: int, row: dict[str, Any], built_on: str) -> Reliability:
    landslides = int(row["landslides"])
    area = row["area_km2"]
    found = {
        "dated_share": _share(row["dated"], landslides),
        "day_share": _share(row["dated_to_the_day"], landslides),
        "edited": _share(row["edited_recently"], landslides),
    }
    notes: list[str] = []
    since = row["iffi_day_since_2018"] + row["events_since_2018"]
    if not landslides:
        notes.append("No IFFI landslide is mapped here.")
    else:
        day = found["day_share"] or 0.0
        notes.append(
            f"{row['dated_to_the_day']:,} of {landslides:,} IFFI landslides "
            f"({_pct(day)}) have a date to the day."
        )
        edited = found["edited"] or 0.0
        notes.append(f"{_pct(edited)} of the IFFI records were edited since 2021.")
    if since:
        notes.append(
            f"Since 2018: {row['iffi_day_since_2018']:,} IFFI landslides dated to the day "
            f"and {row['events_since_2018']:,} events, {row['events_within_1km']:,} of "
            "them with a point known to 1 km."
        )
    else:
        notes.append(
            "No landslide dated to the day since 2018: nothing here can check a threshold."
        )
    return Reliability(
        level=level,
        code=code,
        name=row["name"],
        area_km2=area,
        landslides=landslides,
        density_per_km2=round(landslides / area, 3) if area else None,
        dated_share=found["dated_share"],
        day_share=found["day_share"],
        iffi_day_since_2018=int(row["iffi_day_since_2018"]),
        events_since_2018=int(row["events_since_2018"]),
        events_within_1km=int(row["events_within_1km"]),
        edited_since_2021_share=found["edited"],
        notes=tuple(notes),
        built_on=built_on,
    )
