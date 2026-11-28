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

- **landslides per km² of land in landslide hazard P3+P4**, and how that
  compares with Italy (:attr:`Reliability.vs_italy`). The hazard maps say
  where landslides are expected; where they expect many and IFFI holds few,
  a low density more likely means that little was surveyed than that the
  ground is stable. Counted on 28 November 2026: for the same hazard the
  provinces differ up to 300 times (Sardegna and Puglia have under a
  twentieth of Italy's figure). The hazard maps differ between basin
  authorities too (Valle d'Aosta maps 84% of its land), so this is a hint to
  read a density with care, not a measure of how complete IFFI is. Inside
  one municipality the ratio follows the shape of its hazard map more than
  the survey (Sarno, mapped widely after 1998, has an eighth of Italy's
  figure), so the note of a municipality speaks of its province
  (:attr:`Reliability.province_vs_italy`).

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
    "hazard_land_km2",
)
#: Under this much land in hazard a ratio says nothing: a few records move it.
MIN_HAZARD_KM2 = 1.0
#: Under this share of Italy's landslides per km² of hazard land, the note says so.
THIN = 0.2
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
    #: Land in landslide hazard P3+P4, km² (PAI mosaic, IdroGEO's indicators).
    hazard_land_km2: float | None
    #: IFFI landslides per km² of that land; ``None`` under :data:`MIN_HAZARD_KM2`.
    landslides_per_hazard_km2: float | None
    #: The same figure for the whole of Italy, and this area's as a share of it
    #: (0.05 is a twentieth); ``None`` when either is missing.
    italy_per_hazard_km2: float | None
    vs_italy: float | None
    #: Municipalities only: the two figures of the province around it.
    province_per_hazard_km2: float | None
    province_vs_italy: float | None
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
        found = dict(zip(FIELDS, row, strict=True))
        around = (
            self.levels.get("province", {}).get(str(code // 1000)) if level == "comuni" else None
        )
        province = dict(zip(FIELDS, around, strict=True)) if around else None
        return _reliability(level, code, found, self.built_on, self.italy_per_hazard_km2, province)

    @property
    def italy_per_hazard_km2(self) -> float | None:
        """IFFI landslides per km² of land in hazard P3+P4, all regions together."""
        regions = [
            dict(zip(FIELDS, row, strict=True)) for row in self.levels.get("regioni", {}).values()
        ]
        land = sum(r["hazard_land_km2"] or 0.0 for r in regions)
        return round(sum(r["landslides"] for r in regions) / land, 1) if land else None

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


def _per_hazard(row: dict[str, Any], italy: float | None) -> tuple[float | None, float | None]:
    """Landslides per km² of land in hazard P3+P4, and that as a share of Italy's."""
    land = row["hazard_land_km2"]
    ratio = round(row["landslides"] / land, 1) if land and land >= MIN_HAZARD_KM2 else None
    return ratio, round(ratio / italy, 2) if ratio is not None and italy else None


def _reliability(
    level: Level,
    code: int,
    row: dict[str, Any],
    built_on: str,
    italy: float | None = None,
    province: dict[str, Any] | None = None,
) -> Reliability:
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
    per_hazard, vs_italy = _per_hazard(row, italy)
    around, around_vs_italy = _per_hazard(province, italy) if province else (None, None)
    # a municipality is judged by its province: its own ratio follows the shape of its map
    said, where = (around, around_vs_italy), "in this province"
    if level != "comuni":
        said, where = (per_hazard, vs_italy), "here"
    if said[1] is not None and said[1] < THIN:
        notes.append(
            f"Few IFFI landslides for the hazard mapped {where}: {said[0]} per km² of land in "
            f"landslide hazard P3+P4, against {italy} in Italy. A low density here may mean "
            "that little was surveyed, not that few landslides happen."
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
        hazard_land_km2=row["hazard_land_km2"],
        landslides_per_hazard_km2=per_hazard,
        italy_per_hazard_km2=italy,
        vs_italy=vs_italy,
        province_per_hazard_km2=around,
        province_vs_italy=around_vs_italy,
        notes=tuple(notes),
        built_on=built_on,
    )
