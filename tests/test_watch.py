from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from ispra_idrogeo import IdroGEO
from ispra_idrogeo.watch import Mark, changes, load_marks, save_marks

T0 = datetime(2026, 11, 3, 16, 0, tzinfo=UTC)


async def _sleep(_s: float) -> None:
    return None


class _Changing:
    """A search answering every row modified at or after the filter's time."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def __call__(self, request: httpx.Request) -> httpx.Response:
        since = datetime.fromisoformat(json.loads(request.content)["modified"].removeprefix("gte."))
        found = [
            r
            for r in self.rows
            if "modified" not in r or datetime.fromisoformat(r["modified"]) >= since
        ]
        return httpx.Response(200, json=found)


def _idrogeo(handler: Any) -> IdroGEO:
    return IdroGEO(httpx.AsyncClient(transport=httpx.MockTransport(handler)), sleep=_sleep)


async def test_every_change_comes_out_once() -> None:
    server = _Changing(
        [
            {"id_frana": "B", "modified": "2026-11-03T16:30:00+00:00"},
            {"id_frana": "A", "modified": "2026-11-03T16:30:00+00:00"},
            {"id_frana": "C", "modified": "2026-11-03T15:00:00+00:00"},  # before the mark
            {"id_frana": "X"},  # no modified: skipped
        ]
    )
    async with _idrogeo(server) as idrogeo:
        rows, mark = await changes(idrogeo, "landslides", Mark(T0))
        assert [r["id_frana"] for r in rows] == ["A", "B"]
        assert mark == Mark(datetime(2026, 11, 3, 16, 30, tzinfo=UTC), ("A", "B"))
        again, same = await changes(idrogeo, "landslides", mark)
        assert again == [] and same == mark  # the boundary rows are not sent twice
        server.rows.append({"id_frana": "D", "modified": "2026-11-03T16:30:00+00:00"})
        late, after = await changes(idrogeo, "landslides", mark)
        assert [r["id_frana"] for r in late] == ["D"]  # same instant, new id
        assert after.ids == ("A", "B", "D")
        server.rows.append({"id_frana": "A", "modified": "2026-11-03T17:00:00+00:00"})
        edited, last = await changes(idrogeo, "landslides", after)
        assert [r["id_frana"] for r in edited] == ["A"] and last.ids == ("A",)


async def test_events_and_sites() -> None:
    server = _Changing([{"uid": "E1", "modified": "2026-11-03T16:10:00+00:00"}])
    async with _idrogeo(server) as idrogeo:
        events, _ = await changes(idrogeo, "events", Mark(T0))
        sites, _ = await changes(idrogeo, "sites", Mark(T0))
    assert [r["uid"] for r in events] == [r["uid"] for r in sites] == ["E1"]


def test_marks_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state" / "watch.json"
    assert load_marks(path) == {}
    marks = {"landslides": Mark(T0, ("A",)), "events": Mark(T0)}
    save_marks(path, marks)
    assert load_marks(path) == marks
    path.write_text(json.dumps({"landslides": {"since": "nope"}, "events": {}, "sites": 3}))
    assert load_marks(path) == {}
    path.write_text("[]")
    assert load_marks(path) == {}
