from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from ispra_idrogeo import IdroGEO, cli
from ispra_idrogeo.digest import FILES, MARKS, build, digest
from ispra_idrogeo.freshness import Freshness

NOW = datetime(2026, 11, 23, 8, 0, tzinfo=UTC)
SINCE = datetime(2026, 11, 16, tzinfo=UTC)


def _file(name: str, changed: bool | None) -> Freshness:
    return Freshness(name, f"https://x/{name}", None, None, None, None, changed)


def test_build_and_markdown() -> None:
    rows: dict[str, list[dict[str, Any]]] = {
        "landslides": [{"regione": 5}, {"regione": 5}, {"regione": 6}, {}],
        "events": [
            {"uid": "E1", "computed_date": "2026-10-10T00:00", "comune_nome": "Melito"},
            {"uid": "E2", "computed_date": None, "regione_nome": "Veneto"},
        ],
        "sites": [],
    }
    since = {"landslides": SINCE, "events": SINCE, "sites": SINCE}
    found = build([_file("a.zip", True), _file("b.zip", False)], rows, since, NOW)  # type: ignore[arg-type]
    assert found.files_changed == ["a.zip"] and found.counts == {
        "landslides": 4,
        "events": 2,
        "sites": 0,
    }
    assert found.by_region["landslides"] == {"5": 2, "6": 1, "region not given": 1}
    assert [e["uid"] for e in found.events] == ["E1", "E2"]  # newest first, undated last
    text = found.markdown()
    assert text.startswith("# IdroGEO changes, 2026-11-16 to 2026-11-23")
    assert "Published files changed: 1 of 2 (a.zip)." in text
    assert "IFFI landslide records changed: 4 (5 2, 6 1, region not given 1)." in text
    assert "event E1: 2026-10-10, Melito" in text and "event E2: date not given" in text
    assert "Monitoring sites changed: 0." in text and "Not an alert" in text
    first = build([_file("a.zip", None)], {}, {}, NOW)
    assert first.files_changed is None and "first look" in first.markdown()
    none = build([_file("a.zip", False)], {}, {}, NOW)
    assert "changed: none of 1" in none.markdown()


def _server(request: httpx.Request) -> httpx.Response:
    if request.method == "HEAD":
        return httpx.Response(200, headers={"etag": '"1"'})
    path = request.url.path.removeprefix("/api/")
    if path == "frana/searchfilter":
        since = json.loads(request.content)["modified"].removeprefix("gte.")
        row = {"id_frana": "A", "modified": "2026-11-20T10:00:00+00:00", "regione": 5}
        return httpx.Response(200, json=[row] if since <= row["modified"] else [])
    return httpx.Response(200, json=[])


def _idrogeo() -> IdroGEO:
    return IdroGEO(httpx.AsyncClient(transport=httpx.MockTransport(_server)))


async def test_each_digest_starts_where_the_last_ended(tmp_path: Path) -> None:
    async with _idrogeo() as idrogeo:
        first = await digest(idrogeo, tmp_path, ["landslides"], SINCE)
        assert first.counts == {"landslides": 1} and first.files_changed is None
        assert (tmp_path / MARKS).is_file() and (tmp_path / FILES).is_file()
        again = await digest(idrogeo, tmp_path, ["landslides"])
        assert again.counts == {"landslides": 0} and again.files_changed == []


def test_digest_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "IdroGEO", _idrogeo)
    folder = ["--dir", str(tmp_path)]
    assert (
        cli.main([*folder, "digest", "--kind", "landslides", "--since", "2026-11-16T00:00Z"]) == 0
    )
    assert "IFFI landslide records changed: 1 (5 1)." in capsys.readouterr().out
    assert cli.main([*folder, "digest", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["landslides"] == 0
