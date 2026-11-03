"""Search filters without the technical manual.

Each IdroGEO search reads its JSON filter its own way, and the differences
fail with cryptic messages. These builders know them (checked on the live
service, November 2026):

- **landslides**: most fields take operators (``"eq.100"``, ``"in.(5,6)"``),
  but ``tipo_movimento`` takes a plain number and no list. There is no
  reliable area filter: ``regione`` is a relation the search refuses, and
  ``regione_2019`` is empty for 18% of the landslides (most of Campania).
  For an area, download ``opendata(layer, area)``.
- **events** and **sites**: operators on every field, areas included; a
  range of dates is an ``"and"`` of two conditions.

Every builder returns a plain ``dict`` for the ``filters`` argument of
``iter_landslides``, ``iter_events``, ``sites`` and ``webcams``; combine it
with ``modified_since`` there.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

Codes = int | Iterable[int]


def landslide_filter(
    *,
    movement: int | None = None,
    activity: Codes | None = None,
    district: Codes | None = None,
) -> dict[str, Any]:
    """Landslides by type of movement, state of activity, river basin district.

    ``movement`` is one ``tipo_movimento`` code (the search takes no list);
    ``activity`` the ``stato_attivita_1liv`` codes (100 active, reactivated
    or suspended; 200 dormant; 300 stabilised; 400 relict); ``district`` the
    ``autorita_distretto`` codes.
    """
    out: dict[str, Any] = {}
    if movement is not None:
        out["tipo_movimento"] = int(movement)
    _add(out, "stato_attivita_1liv", activity)
    _add(out, "autorita_distretto", district)
    return out


def event_filter(
    *,
    region: Codes | None = None,
    province: Codes | None = None,
    municipality: Codes | None = None,
    movement: Codes | None = None,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    """Landslide events by area (ISTAT codes), type of movement, date.

    ``start`` is included and ``end`` excluded, like a Python range:
    ``start=date(2023, 1, 1), end=date(2024, 1, 1)`` is the year 2023.
    """
    out: dict[str, Any] = {}
    _add(out, "regione", region)
    _add(out, "provincia", province)
    _add(out, "comune", municipality)
    _add(out, "tipo_movimento", movement)
    if start is not None and end is not None:
        if end <= start:
            raise ValueError(f"end {end} must come after start {start}")
        out["and"] = f"(computed_date.gte.{start.isoformat()},computed_date.lt.{end.isoformat()})"
    elif start is not None:
        out["computed_date"] = f"gte.{start.isoformat()}"
    elif end is not None:
        out["computed_date"] = f"lt.{end.isoformat()}"
    return out


def site_filter(
    *,
    region: Codes | None = None,
    province: Codes | None = None,
    municipality: Codes | None = None,
    active: bool | None = None,
) -> dict[str, Any]:
    """Monitoring sites by area (ISTAT codes) and whether active.

    Webcams take the area part too; they have no ``active``.
    """
    out: dict[str, Any] = {}
    _add(out, "regione", region)
    _add(out, "provincia", province)
    _add(out, "comune", municipality)
    if active is not None:
        out["stato_monitoraggio"] = "eq.1" if active else "neq.1"
    return out


def _add(out: dict[str, Any], field: str, codes: Codes | None) -> None:
    """``eq.16`` for one code, ``in.(14,16)`` for several."""
    if codes is None:
        return
    if isinstance(codes, int):
        out[field] = f"eq.{codes}"
        return
    found = [int(c) for c in codes]
    if not found:
        raise ValueError(f"{field}: give at least one code")
    out[field] = f"eq.{found[0]}" if len(found) == 1 else f"in.({','.join(map(str, found))})"
