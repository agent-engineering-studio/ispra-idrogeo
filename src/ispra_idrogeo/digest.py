"""What changed in IdroGEO since the last digest, in a few lines.

``idrogeo digest`` runs one round of :func:`~ispra_idrogeo.freshness.freshness`
(which published files changed) and of :func:`~ispra_idrogeo.watch.changes`
(which landslide records, events and monitoring sites changed), and says it
in a few lines with the counts by region and the newest events. Run it
every day or every week: it keeps its own state (``digest.json`` and
``digest-files.json`` in the download folder), apart from ``idrogeo watch``
and ``idrogeo freshness``, so the three never steal each other's changes.

The figures come from IdroGEO, the words from a template; no model. Not an
alert: a changed record is a correction or an addition to an archive, not a
landslide happening now.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ispra_idrogeo.freshness import Freshness, freshness
from ispra_idrogeo.grounding import SOURCES
from ispra_idrogeo.watch import WATCHED, Kind, Mark, changes, load_marks, save_marks

if TYPE_CHECKING:
    from ispra_idrogeo.client import IdroGEO

#: The files the digest keeps its state in, in the download folder.
MARKS = "digest.json"
FILES = "digest-files.json"
#: How far back the first digest looks.
FIRST_LOOK = timedelta(days=7)
#: Events listed one by one (the newest first); the rest are only counted.
LISTED = 10
NOTE = (
    "Not an alert: a changed record is a correction or an addition to an archive, not a "
    "landslide happening now. For warnings, follow the bulletins of the Civil Protection "
    "Department and of the region."
)
_SAID = {
    "landslides": "IFFI landslide records",
    "events": "Landslide events",
    "sites": "Monitoring sites",
}
#: The field that names the region of a record, for each kind.
_REGION: dict[Kind, str] = {"landslides": "regione", "events": "regione_nome", "sites": "regione"}


@dataclass(frozen=True)
class Digest:
    """One digest: the files and records changed since the last one."""

    since: dict[str, str]
    checked_at: str
    #: ``None`` on the first digest: nothing saved to compare with.
    files_changed: list[str] | None
    files: int
    counts: dict[str, int]
    by_region: dict[str, dict[str, int]]
    events: list[dict[str, Any]]
    sources: dict[str, str] = field(default_factory=dict)
    note: str = NOTE

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def markdown(self) -> str:
        """The digest in a few lines."""
        start = min(self.since.values(), default=self.checked_at)[:10]
        lines = [f"# IdroGEO changes, {start} to {self.checked_at[:10]}", ""]
        if self.files_changed is None:
            lines.append(f"- Published files: {self.files} checked; first look, no comparison.")
        elif self.files_changed:
            names = ", ".join(self.files_changed)
            changed = len(self.files_changed)
            lines.append(f"- Published files changed: {changed} of {self.files} ({names}).")
        else:
            lines.append(f"- Published files changed: none of {self.files}.")
        for kind, count in self.counts.items():
            top = sorted(self.by_region.get(kind, {}).items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            where = f" ({', '.join(f'{r} {n}' for r, n in top)})" if top else ""
            lines.append(f"- {_SAID[kind]} changed: {count}{where}.")
            if kind == "events":
                for event in self.events:
                    day = event.get("computed_date")
                    date = str(day)[:10] if day else "date not given"
                    place = event.get("comune_nome") or "place not given"
                    lines.append(f"  - event {event.get('uid')}: {date}, {place}")
        lines += ["", f"Source: {SOURCES['iffi']}.", "", self.note]
        return "\n".join(lines) + "\n"


def _iso(when: datetime) -> str:
    return when.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build(
    files: list[Freshness],
    rows: dict[Kind, list[dict[str, Any]]],
    since: dict[Kind, datetime],
    now: datetime,
) -> Digest:
    """The digest of one round: the files' states and the changed rows of each kind."""
    first = all(f.changed is None for f in files)
    by_region: dict[str, dict[str, int]] = {}
    for kind, found in rows.items():
        counted = Counter(str(r.get(_REGION[kind]) or "region not given") for r in found)
        by_region[kind] = dict(counted)
    events = sorted(
        rows.get("events", []), key=lambda r: str(r.get("computed_date") or ""), reverse=True
    )
    fields = ("uid", "computed_date", "comune_nome", "provincia_nome", "regione_nome")
    return Digest(
        since={k: _iso(v) for k, v in since.items()},
        checked_at=_iso(now),
        files_changed=None if first else [f.filename for f in files if f.changed],
        files=len(files),
        counts={k: len(v) for k, v in rows.items()},
        by_region=by_region,
        events=[{k: e.get(k) for k in fields} for e in events[:LISTED]],
        sources={"records": SOURCES["iffi"], "events": SOURCES["events"]},
    )


async def digest(
    idrogeo: IdroGEO,
    folder: Path,
    kinds: list[Kind] | None = None,
    first_since: datetime | None = None,
) -> Digest:
    """One digest, with its state in ``folder``; the next one starts where this ends."""
    wanted: list[Kind] = kinds or list(WATCHED)
    now = datetime.now(UTC)
    files = await freshness(idrogeo, state=folder / FILES)
    marks = load_marks(folder / MARKS)
    start = first_since or now - FIRST_LOOK
    since: dict[Kind, datetime] = {}
    rows: dict[Kind, list[dict[str, Any]]] = {}
    for kind in wanted:
        mark = marks.get(kind) or Mark(start)
        since[kind] = mark.since
        rows[kind], marks[kind] = await changes(idrogeo, kind, mark)
    save_marks(folder / MARKS, marks)
    return build(files, rows, since, now)
