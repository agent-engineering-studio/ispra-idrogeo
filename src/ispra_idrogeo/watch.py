"""What changed in IdroGEO since last time: the engine of ``idrogeo watch``.

For each kind of record (landslides, events, monitoring sites) a
:class:`Mark` remembers the latest ``modified`` seen and the records
modified at that very instant. The next :func:`changes` asks for
``modified >= since`` and drops those records, which the "at or after"
filter would send again: every change comes out once.

The marks live in a small JSON file (:func:`load_marks`, :func:`save_marks`),
written atomically, so a cron job or a loop can stop and resume anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from ispra_idrogeo.cache import read_json, write_json
from ispra_idrogeo.client import IdroGEO

Kind = Literal["landslides", "events", "sites"]

#: For each kind: the field that names a record, and the fields printed.
WATCHED: dict[Kind, tuple[str, tuple[str, ...]]] = {
    "landslides": (
        "id_frana",
        (
            "id_frana",
            "modified",
            "tipo_movimento",
            "stato",
            "regione",
            "provincia",
            "comune",
            "point",
        ),
    ),
    "events": (
        "uid",
        (
            "uid",
            "modified",
            "computed_date",
            "tipo_movimento",
            "regione_nome",
            "provincia_nome",
            "comune_nome",
            "extent",
        ),
    ),
    "sites": (
        "uid",
        (
            "uid",
            "modified",
            "stato_monitoraggio",
            "regione",
            "comune",
            "localita",
            "point",
            "id_frane_correlati",
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class Mark:
    """Where one kind's watch stands: the latest ``modified`` and who had it."""

    since: datetime
    ids: tuple[str, ...] = ()


def load_marks(path: Path) -> dict[str, Mark]:
    """The marks saved in ``path``; none if the file is missing or unreadable."""
    data = read_json(path)
    if not isinstance(data, dict):
        return {}
    marks = {}
    for kind, saved in data.items():
        try:
            since = datetime.fromisoformat(saved["since"])
            marks[kind] = Mark(since, tuple(str(i) for i in saved.get("ids", ())))
        except (KeyError, TypeError, ValueError):
            continue
    return marks


def save_marks(path: Path, marks: dict[str, Mark]) -> None:
    """Write the marks to ``path``, atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(
        path, {k: {"since": m.since.isoformat(), "ids": list(m.ids)} for k, m in marks.items()}
    )


async def changes(idrogeo: IdroGEO, kind: Kind, mark: Mark) -> tuple[list[dict[str, Any]], Mark]:
    """The records of ``kind`` changed since ``mark``, oldest first, and the next mark."""
    key, fields = WATCHED[kind]
    select = list(fields)
    if kind == "landslides":
        rows = [r async for r in idrogeo.iter_landslides(modified_since=mark.since, select=select)]
    elif kind == "events":
        rows = [r async for r in idrogeo.iter_events(modified_since=mark.since, select=select)]
    else:
        rows = await idrogeo.sites(modified_since=mark.since, select=select)
    seen = set(mark.ids)
    fresh = [
        r
        for r in rows
        if not (_modified(r) == mark.since and str(r.get(key)) in seen) and _modified(r) is not None
    ]
    fresh.sort(key=lambda r: (_modified(r), str(r.get(key))))
    if not fresh:
        return [], mark
    latest = max(m for r in fresh if (m := _modified(r)) is not None)
    at_latest = {str(r.get(key)) for r in fresh if _modified(r) == latest}
    if latest == mark.since:
        at_latest |= seen
    return fresh, Mark(latest, tuple(sorted(at_latest)))


def _modified(row: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(row["modified"]))
    except (KeyError, ValueError):
        return None
