from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from ispra_idrogeo import IdroGEO, cli


async def _sleep(_s: float) -> None:
    return None


def _server(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/geoserver/wms":
        if "buffer" in request.url.params:
            point = {"type": "Point", "coordinates": [14.63, 40.838]}
            feature = {
                "id": "frane_piff_opendata.1",
                "geometry": point,
                "properties": {"id_frana": "1"},
            }
            return httpx.Response(200, json={"features": [feature]})
        layers = request.url.params["layers"]
        return httpx.Response(
            200, json={"features": [{"properties": {"cod_per_it": 4}}], "layers": layers}
        )
    body = json.loads(request.content) if request.content else None
    if path.startswith("/opendata/"):
        return httpx.Response(200, content=b"BZ2", headers={"ETag": '"1"'})
    path = path.removeprefix("/api/")
    if path == "pir/comuni/72006":
        return httpx.Response(200, json={"nome": "Bari"})
    if path == "pir/comuni":
        return httpx.Response(200, json=[{"pro_com": 72006}])
    if path in ("frana/searchfilter", "evento/main/filter", "sito/filter", "webcam/filter"):
        return httpx.Response(200, json=[{"path": path, "body": body, **request.url.params}])
    if path == "frana/0017680500":
        return httpx.Response(200, json={"id_frana": "0017680500"})
    if path == "frana/0000000000":
        return httpx.Response(401, json={"message": "Missing authorization header"})
    if path == "dizionari/cause":
        return httpx.Response(200, json=[{"codice": "1", "descrizione_en": "weak material"}])
    if path == "dizionari":
        return httpx.Response(200, json=["cause"])
    if path == "ordini":
        return httpx.Response(200, json=["Ordine dei Geologi Abruzzo", request.url.params["limit"]])
    raise AssertionError(path)


def _idrogeo() -> IdroGEO:
    client = httpx.AsyncClient(transport=httpx.MockTransport(_server))
    return IdroGEO(client, sleep=_sleep)


async def _run(*argv: str) -> list[Any]:
    out = io.StringIO()
    async with _idrogeo() as idrogeo:
        await cli.run(cli.parser().parse_args(argv), idrogeo, out)
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_filters() -> None:
    assert cli.filters(["tipo_movimento=6", "regione=eq.16", "x=-1", "y=a=b"]) == {
        "tipo_movimento": 6,
        "regione": "eq.16",
        "x": -1,
        "y": "a=b",
    }
    with pytest.raises(ValueError, match="FIELD=VALUE"):
        cli.filters(["regione"])


async def test_searches_print_json_lines() -> None:
    [row] = await _run(
        "landslides",
        "--filter",
        "tipo_movimento=6",
        "--since",
        "2026-11-01T00:00:00Z",
        "--select",
        "id_frana, modified",
    )
    assert row["path"] == "frana/searchfilter"
    assert row["body"] == {"tipo_movimento": 6, "modified": "gte.2026-11-01T00:00:00+00:00"}
    assert row["select"] == "id_frana,modified"
    [event] = await _run("events", "--filter", "regione=eq.16")
    assert event["path"] == "evento/main/filter" and event["body"] == {"regione": "eq.16"}
    [site] = await _run("sites")
    assert site["path"] == "sito/filter" and site["body"] == {}
    [cam] = await _run("webcams", "--filter", "regione=eq.3")
    assert cam["body"] == {"regione": "eq.3"}


async def test_api_commands() -> None:
    assert await _run("summary", "pir", "comuni", "72006") == [{"nome": "Bari"}]
    assert await _run("landslide", "0017680500") == [{"id_frana": "0017680500"}]
    assert await _run("labels", "cause") == [{"1": "weak material"}]
    assert await _run("dictionaries") == [["cause"]]
    [hazard] = await _run("hazard", "40.829", "14.617")
    assert hazard["landslide"] == "P4" and hazard["lat"] == 40.829
    assert (await _run("hazard", "40.829", "14.617", "--lithology"))[0]["landslide"] == "P4"
    [near] = await _run("near", "40.838", "14.630", "--radius", "100")
    assert near["id_frana"] == "1" and near["distance_m"] == 0.0
    assert await _run("lookup", "ordini", "geologi", "--limit", "3") == [
        "Ordine dei Geologi Abruzzo",
        "3",
    ]


async def test_fetch_and_municipalities(tmp_path: Path) -> None:
    out = io.StringIO()
    async with _idrogeo() as idrogeo:
        await cli.run(
            cli.parser().parse_args(["--dir", str(tmp_path), "fetch", "sensor_data"]), idrogeo, out
        )
        assert out.getvalue().strip() == str(tmp_path / "idrogeo_sensor_data.csv.bz2")
        for argv in (
            ["fetch", "eventi", "--area", "puglia", "--geojson", "--no-unpack"],
            ["fetch", "idraulica", "--no-unpack"],
        ):
            out = io.StringIO()
            await cli.run(cli.parser().parse_args(["--dir", str(tmp_path), *argv]), idrogeo, out)
            assert Path(out.getvalue().strip()).suffix == ".zip"
    rows = await _run("--dir", str(tmp_path), "municipalities", "--max-age-days", "30")
    assert rows == [{"nome": "Bari"}]
    assert await _run("--dir", str(tmp_path), "municipalities") == rows


def test_since_needs_a_time_zone(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["landslides", "--since", "2026-11-01"])
    assert "time zone" in capsys.readouterr().err


def test_main_exit_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "IdroGEO", _idrogeo)
    assert cli.main(["landslide", "0017680500"]) == 0
    assert json.loads(capsys.readouterr().out) == {"id_frana": "0017680500"}
    assert cli.main(["landslide", "0000000000"]) == 1
    assert "unknown or not public" in capsys.readouterr().err
    assert cli.main(["landslides", "--filter", "nope"]) == 1

    async def interrupted(*_a: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "_main", interrupted)
    assert cli.main(["dictionaries"]) == 130

    async def closed(*_a: Any) -> None:
        raise BrokenPipeError

    monkeypatch.setattr(cli, "_main", closed)
    assert cli.main(["dictionaries"]) == 0
