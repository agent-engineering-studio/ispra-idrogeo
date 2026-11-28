"""Dated landslides: the IFFI records and events that say *when*, and how precisely.

A rainfall threshold can only be checked on landslides with a date. IdroGEO
has two kinds:

- **IFFI records** (``iter_landslides``): 721,457 landslides, of which 28,076
  have a date: a certain one (``data_certa``, 6,144) or an interval
  (``data_incerta_min`` / ``data_incerta_max``). The other 96% have none.
  Their ``accuratezza_posizione`` says ``esatta`` for every record, so it
  tells nothing: :attr:`DatedLandslide.position_m` is ``None`` for them.
- **Events** (``opendata("eventi")``): about 1,800 dated events, most since
  2018, each with a stated accuracy of its point (exact, 100 m, 1 km, 10 km).
  Most dates give only the day.

:func:`dated_landslides` reads both and gives one list, each landslide with
the precision of its date and of its place, so a study can keep only what it
can trust: ``max_interval_days=1`` keeps dates known to the day,
``max_position_m=1000`` keeps points known to 1 km. Counted on 22 November
2026; the figures above change as ISPRA updates the data.

The open-data events do not carry the IFFI id, so nothing says that an event
and an IFFI record are the same landslide. :func:`twins` pairs the ones that
probably are, by a rule: both dated to the day, at most one day and one
kilometre apart. On 28 November 2026 it found 120 pairs, 115 of them since
2018, among 1,621 IFFI records dated to the day and 1,710 events: the two
sources mostly hold different landslides, and ``drop_twins=True`` keeps a
study from counting those twice.
It is a rule, not a fact: two landslides of the same storm on the same slope
pair too.

Not here: any date for the 96% that have none. Both sources are CC BY-SA 4.0.
"""

from __future__ import annotations

import calendar
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from ispra_idrogeo.client import IdroGEO
from ispra_idrogeo.grounding import SOURCES
from ispra_idrogeo.sources import opendata

Source = Literal["iffi", "eventi"]
Precision = Literal["hour", "day", "interval"]

#: The fields read from each IFFI record.
IFFI_FIELDS = (
    "id_frana",
    "data_certa",
    "data_incerta_min",
    "data_incerta_max",
    "point",
    "tipo_movimento",
    "regione",
    "provincia",
    "comune",
)
#: IFFI records with a certain date or an interval, filtered on the server.
_DATED = {
    "or": "(data_certa.not.is.null,data_incerta_min.not.is.null,data_incerta_max.not.is.null)"
}
#: The accuracy classes of the events, in metres (``Esatta`` is 0).
_EVENT_ACCURACY = {"esatta": 0, "100": 100, "1000": 1_000, "10000": 10_000}
_DATE = re.compile(r"(\d{4})(?:-(\d{2})(?:-(\d{2})(?:[T ](\d{2}):(\d{2}))?)?)?")


@dataclass(frozen=True, slots=True)
class DatedLandslide:
    """One landslide with a date, and how far its date and place can be trusted."""

    source: Source
    id: str
    lon: float | None
    lat: float | None
    #: The day, or the first day of the interval.
    start: date
    #: The same day, or the last day of the interval.
    end: date
    #: ``"HH:MM"`` when a time other than 00:00 is written, else ``None``.
    time: str | None
    precision: Precision
    #: Days covered by the date: 1 for a day or an hour.
    interval_days: int
    #: Accuracy of the point in metres (0 = exact) when the source states it.
    position_m: int | None
    movement: int | None
    region: int | None
    province: int | None
    municipality: int | None
    #: Events only: ``True`` for the main event of a series.
    main_event: bool | None
    citation: str

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready: dates as ISO strings."""
        out = asdict(self)
        out["start"], out["end"] = self.start.isoformat(), self.end.isoformat()
        return out


def parse_period(text: Any, today: date | None = None) -> tuple[date, date, str | None] | None:
    """The first and last day a date stands for, and its time if one is written.

    ``"2019-05-12"`` is that day; ``"1983-07"`` the whole month; ``"1979"``
    the whole year. The time is ``"HH:MM"``, or ``None`` at 00:00 or when
    absent; the day is the one written, whatever the time zone. ``None`` for
    an empty or impossible date (before 1000, or starting after ``today``).
    """
    if not isinstance(text, str):
        return None
    match = _DATE.fullmatch(text.strip()) or _DATE.match(text.strip())
    if not match:
        return None
    year, month, day, hour, minute = match.groups()
    try:
        y = int(year)
        if day:
            start = end = date(y, int(month), int(day))
        elif month:
            start = date(y, int(month), 1)
            end = date(y, int(month), calendar.monthrange(y, int(month))[1])
        else:
            start, end = date(y, 1, 1), date(y, 12, 31)
    except ValueError:
        return None
    if y < 1000 or start > (today or date.today()):
        return None
    clock = f"{hour}:{minute}" if hour and (hour, minute) != ("00", "00") else None
    return start, end, clock


def from_iffi(row: Mapping[str, Any], today: date | None = None) -> DatedLandslide | None:
    """An IFFI record with a date as a :class:`DatedLandslide`; ``None`` without one."""
    certain = parse_period(row.get("data_certa"), today)
    low = parse_period(row.get("data_incerta_min"), today)
    high = parse_period(row.get("data_incerta_max"), today)
    if certain:
        start, end, clock = certain
    elif low or high:
        first, last = low or high, high or low
        assert first is not None and last is not None
        start, end, clock = min(first[0], last[1]), max(first[0], last[1]), None
    else:
        return None
    precision: Precision = "interval" if start != end else "hour" if clock else "day"
    lon, lat = _xy(row.get("point")) or (None, None)
    return DatedLandslide(
        source="iffi",
        id=str(row.get("id_frana")),
        lon=lon,
        lat=lat,
        start=start,
        end=end,
        time=clock,
        precision=precision,
        interval_days=(end - start).days + 1,
        position_m=None,  # IFFI says "esatta" for every record
        movement=_int(row.get("tipo_movimento")),
        region=_int(row.get("regione")),
        province=_int(row.get("provincia")),
        municipality=_int(row.get("comune")),
        main_event=None,
        citation=SOURCES["iffi"],
    )


def from_event(feature: Mapping[str, Any], today: date | None = None) -> DatedLandslide | None:
    """A GeoJSON feature of ``opendata("eventi")`` as a :class:`DatedLandslide`."""
    props = feature.get("properties") or {}
    dated = parse_period(props.get("data_certa"), today)
    if not dated:
        return None
    start, end, clock = dated
    xy = _xy((feature.get("geometry") or {}).get("coordinates"))
    lon, lat = utm32n_to_lonlat(*xy) if xy else (None, None)
    accuracy = str(props.get("accuratezza_posizione") or "").strip().lower()
    main = props.get("evento_principale")
    return DatedLandslide(
        source="eventi",
        id=str(props.get("uid")),
        lon=lon,
        lat=lat,
        start=start,
        end=end,
        time=clock,
        precision="interval" if start != end else "hour" if clock else "day",
        interval_days=(end - start).days + 1,
        position_m=_EVENT_ACCURACY.get(accuracy),
        movement=_int(props.get("tipo_movimento")),
        region=_int(props.get("regione")),
        province=_int(props.get("provincia")),
        municipality=_int(props.get("comune")),
        main_event=None if main is None else str(main).upper() == "SI",
        citation=SOURCES["events"],
    )


def select(
    found: Iterable[DatedLandslide],
    *,
    since: date | None = None,
    until: date | None = None,
    region: int | None = None,
    max_interval_days: int | None = None,
    max_position_m: int | None = None,
) -> list[DatedLandslide]:
    """The landslides inside the dates (``since`` included, ``until`` excluded),
    the region (ISTAT code) and the precision asked for.

    ``max_position_m`` keeps only landslides whose source states an accuracy
    at least that good, so it leaves out every IFFI record.
    """
    return [
        d
        for d in found
        if (since is None or d.end >= since)
        and (until is None or d.start < until)
        and (region is None or d.region == region)
        and (max_interval_days is None or d.interval_days <= max_interval_days)
        and (
            max_position_m is None or (d.position_m is not None and d.position_m <= max_position_m)
        )
    ]


async def dated_landslides(
    idrogeo: IdroGEO,
    *,
    sources: Sequence[Source] = ("iffi", "eventi"),
    since: date | None = None,
    until: date | None = None,
    region: int | None = None,
    max_interval_days: int | None = None,
    max_position_m: int | None = None,
    directory: Path | None = None,
    drop_twins: bool = False,
) -> list[DatedLandslide]:
    """Every dated landslide of IFFI and of the events, with its precision, oldest first.

    IFFI is read from the API (one request, a few seconds); the events from
    the open-data file (100 kB, downloaded only if changed, into
    ``directory``). See :func:`select` for the filters. ``drop_twins`` leaves
    out the IFFI record of each pair of :func:`twins`, before the filters: the
    event stays, because it states how accurate its point is.
    """
    found: list[DatedLandslide] = []
    if "iffi" in sources:
        rows = idrogeo.iter_landslides(dict(_DATED), select=list(IFFI_FIELDS), page_size=100_000)
        found += [d async for r in rows if (d := from_iffi(r))]
    if "eventi" in sources:
        folder = await idrogeo.fetch(opendata("eventi", fmt="geojson"), directory)
        for path in sorted(folder.glob("*.json")):
            features = json.loads(path.read_text(encoding="utf-8")).get("features") or []
            found += [d for f in features if (d := from_event(f))]
    if drop_twins:
        same = {id(record) for record, _event in twins(found)}
        found = [d for d in found if id(d) not in same]
    chosen = select(
        found,
        since=since,
        until=until,
        region=region,
        max_interval_days=max_interval_days,
        max_position_m=max_position_m,
    )
    return sorted(chosen, key=lambda d: (d.start, d.source, d.id))


def distance_m(a: DatedLandslide, b: DatedLandslide) -> float | None:
    """Metres between two landslides, ``None`` when one has no point.

    On a plane tangent at their latitude: good to a few metres over the few
    kilometres :func:`twins` looks at, not for points far apart.
    """
    if a.lon is None or a.lat is None or b.lon is None or b.lat is None:
        return None
    east = (a.lon - b.lon) * 111_320.0 * math.cos(math.radians((a.lat + b.lat) / 2))
    return math.hypot(east, (a.lat - b.lat) * 110_574.0)


def twins(
    found: Iterable[DatedLandslide], *, max_distance_m: float = 1000, max_days: int = 1
) -> list[tuple[DatedLandslide, DatedLandslide]]:
    """The pairs (IFFI record, event) that are probably the same landslide, nearest first.

    Both must be dated to the day or the hour, at most ``max_days`` apart, with
    points at most ``max_distance_m`` apart. A record and an event are in one
    pair at most: the nearest wins. A record dated by an interval is never
    paired: a year that contains the day of an event says too little.
    """
    if max_distance_m < 0 or max_days < 0:
        raise ValueError("max_distance_m and max_days must be 0 or more")
    by_day: dict[date, list[DatedLandslide]] = {}
    records = []
    for d in found:
        if d.interval_days != 1 or d.lon is None or d.lat is None:
            continue
        if d.source == "eventi":
            by_day.setdefault(d.start, []).append(d)
        else:
            records.append(d)
    close = []
    for record in records:
        for offset in range(-max_days, max_days + 1):
            for event in by_day.get(record.start + timedelta(days=offset), ()):
                apart = distance_m(record, event)
                if apart is not None and apart <= max_distance_m:
                    close.append((apart, record, event))
    taken: set[int] = set()
    pairs = []
    for _apart, record, event in sorted(close, key=lambda c: (c[0], c[1].id, c[2].id)):
        if id(record) not in taken and id(event) not in taken:
            taken |= {id(record), id(event)}
            pairs.append((record, event))
    return pairs


def summary(found: Iterable[DatedLandslide]) -> dict[str, Any]:
    """Counts: by source, by precision of the date and of the place, by year and region."""
    items = list(found)

    def count(key: Any) -> dict[str, int]:
        return {str(k): v for k, v in sorted(Counter(key(d) for d in items).items(), key=str)}

    return {
        "total": len(items),
        "by_source": count(lambda d: d.source),
        "by_precision": count(lambda d: d.precision),
        "by_position_m": count(lambda d: "not stated" if d.position_m is None else d.position_m),
        "by_year": count(lambda d: d.start.year),
        "by_region": count(lambda d: d.region),
    }


# UTM zone 32N (EPSG:32632) to longitude and latitude, WGS 84: the events file
# is in UTM, and a study crossing it with rainfall wants degrees. Krüger's
# series to n³ (as on the UTM page of Wikipedia); checked against PROJ in the
# tests to under a metre across Italy.
_A = 6378137.0
_F = 1 / 298.257223563
_K0 = 0.9996
_N = _F / (2 - _F)
_AA = _A / (1 + _N) * (1 + _N**2 / 4 + _N**4 / 64)
_BETA = (
    _N / 2 - 2 * _N**2 / 3 + 37 * _N**3 / 96,
    _N**2 / 48 + _N**3 / 15,
    17 * _N**3 / 480,
)
_DELTA = (
    2 * _N - 2 * _N**2 / 3 - 2 * _N**3,
    7 * _N**2 / 3 - 8 * _N**3 / 5,
    56 * _N**3 / 15,
)


def utm32n_to_lonlat(x: float, y: float) -> tuple[float, float]:
    """Longitude and latitude (degrees) of a point in EPSG:32632 (metres)."""
    xi = y / (_K0 * _AA)
    eta = (x - 500_000.0) / (_K0 * _AA)
    xi1 = xi - sum(
        b * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j, b in enumerate(_BETA, 1)
    )
    eta1 = eta - sum(
        b * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j, b in enumerate(_BETA, 1)
    )
    chi = math.asin(math.sin(xi1) / math.cosh(eta1))
    lat = chi + sum(d * math.sin(2 * j * chi) for j, d in enumerate(_DELTA, 1))
    lon = math.radians(9.0) + math.atan2(math.sinh(eta1), math.cos(xi1))
    return math.degrees(lon), math.degrees(lat)


def _xy(value: Any) -> tuple[float, float] | None:
    """The first two numbers of a coordinate list, or ``None``."""
    if (
        isinstance(value, list | tuple)
        and len(value) >= 2
        and all(isinstance(v, int | float) for v in value[:2])
    ):
        return float(value[0]), float(value[1])
    return None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
