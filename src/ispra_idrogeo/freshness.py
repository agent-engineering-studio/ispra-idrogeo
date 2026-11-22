"""How fresh IdroGEO's files are, and which changed since the last look.

ISPRA regenerates the IFFI files every day and the hazard mosaics every few
years. :func:`freshness` asks IdroGEO about each published file with one
``HEAD`` request (nothing is downloaded): its date, its ETag, its size, how
many days old it is, and, when a previous answer was saved in ``state``,
whether it changed since then. A system that depends on the data (Limen, a
nightly job) can run it on a schedule and act only on what changed.

    idrogeo freshness            # every file, and what changed since last time
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from ispra_idrogeo.cache import read_json, write_json
from ispra_idrogeo.client import FileState, IdroGEO
from ispra_idrogeo.sources import EVENT_LAYERS, LANDSLIDE_LAYERS, MOSAICS, Dataset, mosaic, opendata

#: The file the previous answers are kept in, in the download folder.
STATE = "freshness.json"


@dataclass(frozen=True, slots=True)
class Freshness:
    """One published file: when ISPRA last changed it, and whether it changed since last time."""

    filename: str
    url: str
    #: ``Last-Modified`` as an ISO date-time (UTC), ``None`` when not sent.
    modified: str | None
    #: Whole days between ``modified`` and now.
    age_days: int | None
    etag: str | None
    size: int | None
    #: ``True``/``False`` against the saved state; ``None`` the first time.
    changed: bool | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def published() -> list[Dataset]:
    """Every file for the whole of Italy: the IFFI layers, events, reports and mosaics."""
    return [opendata(layer) for layer in (*LANDSLIDE_LAYERS, *EVENT_LAYERS)] + [
        mosaic(name) for name in MOSAICS
    ]


def _iso(http_date: str | None) -> datetime | None:
    if not http_date:
        return None
    try:
        return parsedate_to_datetime(http_date).astimezone(UTC)
    except (TypeError, ValueError):
        return None


def compare(found: FileState, before: dict[str, Any] | None, now: datetime) -> Freshness:
    """A file's state against what was saved for it (``None``: nothing saved)."""
    modified = _iso(found.last_modified)
    changed = None
    if before is not None:
        changed = (before.get("etag"), before.get("last_modified")) != (
            found.etag,
            found.last_modified,
        )
    return Freshness(
        filename=found.filename,
        url=found.url,
        modified=modified.isoformat().replace("+00:00", "Z") if modified else None,
        age_days=(now - modified).days if modified else None,
        etag=found.etag,
        size=found.size,
        changed=changed,
    )


async def freshness(
    idrogeo: IdroGEO,
    datasets: Iterable[Dataset] | None = None,
    state: Path | None = None,
) -> list[Freshness]:
    """Every file's date, size and whether it changed since the answers saved in ``state``.

    ``datasets`` defaults to :func:`published`. With ``state`` (a JSON file),
    the previous answers are read from it and the new ones written back.
    """
    wanted = list(datasets) if datasets is not None else published()
    states = await asyncio.gather(*(idrogeo.head(d) for d in wanted))
    saved: dict[str, Any] = {}
    if state is not None and state.is_file():
        loaded = read_json(state)
        saved = loaded if isinstance(loaded, dict) else {}
    now = datetime.now(UTC)
    found = [compare(s, saved.get(s.filename) if saved else None, now) for s in states]
    if state is not None:
        write_json(
            state,
            {
                s.filename: {"etag": s.etag, "last_modified": s.last_modified, "size": s.size}
                for s in states
            },
        )
    return found


def summary(found: Iterable[Freshness]) -> dict[str, Any]:
    """The newest and oldest file, and which changed."""
    items = list(found)
    dated = [f for f in items if f.age_days is not None]
    return {
        "files": len(items),
        "changed": [f.filename for f in items if f.changed],
        "newest": min(dated, key=lambda f: f.age_days or 0).filename if dated else None,
        "oldest": max(dated, key=lambda f: f.age_days or 0).filename if dated else None,
        "checked_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
