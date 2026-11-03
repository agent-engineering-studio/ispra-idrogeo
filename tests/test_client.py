from __future__ import annotations

import asyncio
import io
import json
import os
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from ispra_idrogeo import CODE_DICTIONARIES, IdroGEO, IdrogeoError, mosaic, opendata, sensor_data

Handler = Callable[[httpx.Request], httpx.Response]
ETAG = '"6ae99507-416c44"'


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buffer.getvalue()


class _Server:
    """A fake IdroGEO: one ZIP with an ETag, answering 304 to the right one."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.etag = ETAG
        self.requests: list[httpx.Request] = []
        self.failures: list[int] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failures:
            return httpx.Response(self.failures.pop(0), text="busy")
        if request.headers.get("if-none-match") == self.etag:
            return httpx.Response(304)
        return httpx.Response(
            200,
            content=self.body,
            headers={"ETag": self.etag, "Last-Modified": "Tue, 03 Nov 2026 08:02:15 GMT"},
        )


async def _sleep(_s: float) -> None:
    return None


def _idrogeo(handler: Handler, **kw: Any) -> IdroGEO:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return IdroGEO(client, sleep=_sleep, **kw)


async def test_download_is_conditional(tmp_path: Path) -> None:
    server = _Server(_zip({"dgpv_poly_opendataPolygon.shp": b"SHP"}))
    async with _idrogeo(server) as idrogeo:
        first = await idrogeo.download(opendata("dgpv_poly"), tmp_path)
        assert first.changed and first.path == tmp_path / "dgpv_poly_ispra_opendata.zip"
        assert "if-none-match" not in server.requests[0].headers
        again = await idrogeo.download(opendata("dgpv_poly"), tmp_path)
        assert not again.changed
        assert server.requests[1].headers["if-none-match"] == ETAG
        assert server.requests[1].headers["if-modified-since"].startswith("Tue")
        server.etag = '"new"'
        server.body = _zip({"dgpv_poly_opendataPolygon.shp": b"SHP2"})
        third = await idrogeo.download(opendata("dgpv_poly"), tmp_path)
        assert third.changed
        meta = json.loads((tmp_path / "dgpv_poly_ispra_opendata.zip.meta.json").read_text())
        assert meta["etag"] == '"new"'
    assert not list(tmp_path.glob("*.part"))


async def test_fetch_unpacks_only_when_changed(tmp_path: Path) -> None:
    server = _Server(_zip({"frane_piff_opendataPoint.shp": b"SHP"}))
    async with _idrogeo(server) as idrogeo:
        folder = await idrogeo.fetch(opendata("frane_piff"), tmp_path)
        assert folder == tmp_path / "frane_piff_ispra_opendata"
        assert (folder / "frane_piff_opendataPoint.shp").read_bytes() == b"SHP"
        (folder / "marker").write_bytes(b"")
        assert await idrogeo.fetch(opendata("frane_piff"), tmp_path) == folder
        assert (folder / "marker").exists()  # 304: not unpacked again
        (folder / "marker").unlink()
        folder.rename(tmp_path / "gone")
        await idrogeo.fetch(opendata("frane_piff"), tmp_path)  # 304, but folder missing
        assert (folder / "frane_piff_opendataPoint.shp").exists()
        zipped = await idrogeo.fetch(opendata("frane_piff"), tmp_path, unpack=False)
        assert zipped.suffix == ".zip"


async def test_fetch_keeps_a_non_zip_file(tmp_path: Path) -> None:
    server = _Server(b"BZ2")
    async with _idrogeo(server) as idrogeo:
        path = await idrogeo.fetch(sensor_data(), tmp_path)
    assert path == tmp_path / "idrogeo_sensor_data.csv.bz2"


async def test_busy_server_is_retried(tmp_path: Path) -> None:
    server = _Server(_zip({"a.shp": b"1"}))
    server.failures = [503, 429]
    async with _idrogeo(server) as idrogeo:
        got = await idrogeo.download(mosaic("idraulica"), tmp_path)
    assert got.changed and len(server.requests) == 3


async def test_retries_exhausted_raise_the_status(tmp_path: Path) -> None:
    server = _Server(b"")
    server.failures = [503, 503]
    async with _idrogeo(server, retries=1) as idrogeo:
        with pytest.raises(httpx.HTTPStatusError):
            await idrogeo.download(opendata("eventi"), tmp_path)
    server.failures = [503]
    async with _idrogeo(server, retries=0) as idrogeo:
        with pytest.raises(httpx.HTTPStatusError):
            await idrogeo.download(opendata("eventi"), tmp_path)
    assert len(server.requests) == 3


async def test_missing_dataset_and_odd_statuses(tmp_path: Path) -> None:
    async with _idrogeo(lambda _r: httpx.Response(404)) as idrogeo:
        with pytest.raises(IdrogeoError, match="does not exist"):
            await idrogeo.download(opendata("eventi", "puglia"), tmp_path)
    async with _idrogeo(lambda _r: httpx.Response(403)) as idrogeo:
        with pytest.raises(httpx.HTTPStatusError):
            await idrogeo.download(opendata("eventi"), tmp_path)
    async with _idrogeo(lambda _r: httpx.Response(304)) as idrogeo:
        # A 304 to a request that was not conditional is not a file.
        with pytest.raises(httpx.HTTPStatusError):
            await idrogeo.download(opendata("eventi"), tmp_path)
    async with _idrogeo(lambda _r: httpx.Response(204)) as idrogeo:
        with pytest.raises(IdrogeoError, match="unexpected HTTP 204"):
            await idrogeo.download(opendata("eventi"), tmp_path)


async def test_network_errors_are_retried_then_raised(tmp_path: Path) -> None:
    calls: list[int] = []

    def flaky(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(200, content=b"ok")

    async with _idrogeo(flaky) as idrogeo:
        assert (await idrogeo.download(opendata("eventi"), tmp_path)).changed

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with _idrogeo(down, retries=1) as idrogeo:
        with pytest.raises(httpx.ConnectError):
            await idrogeo.download(opendata("frane_line"), tmp_path)
    assert not list(tmp_path.glob("*.part"))


async def test_default_directory_is_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IDROGEO_DATA_DIR", str(tmp_path / "cache"))
    server = _Server(_zip({"a.shp": b"1"}))
    async with _idrogeo(server) as idrogeo:
        folder = await idrogeo.fetch(opendata("aree_poly"))
    assert folder == tmp_path / "cache" / "aree_poly_ispra_opendata"


def _api(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api/")
    if path == "iffi/regioni/16":
        return httpx.Response(200, json={"nome": "Puglia", "frane_stats": []})
    if path == "dizionari":
        return httpx.Response(200, json=["cause", "movimento_frana"])
    if path == "dizionari/cause":
        return httpx.Response(200, json=[{"cod": 1, "nome": "Pioggia"}])
    if path == "dizionari/nessuno":
        return httpx.Response(404, json={"message": "Dizionario 'nessuno' non trovato"})
    if path in ("frana/searchfilter", "evento/main/filter"):
        assert request.method == "POST"
        assert json.loads(request.content) == {"regione": "eq.16"}
        assert request.url.params["limit"] == "2"
        assert request.url.params["select"] == "id_frana"
        return httpx.Response(200, json=[{"id_frana": "1"}, {"id_frana": "2"}])
    raise AssertionError(path)


async def test_api() -> None:
    async with _idrogeo(_api, api_url="https://x/api/") as idrogeo:
        assert (await idrogeo.summary("iffi", "regioni", 16))["nome"] == "Puglia"
        assert await idrogeo.dictionaries() == ["cause", "movimento_frana"]
        assert await idrogeo.dictionary("cause") == [{"cod": 1, "nome": "Pioggia"}]
        with pytest.raises(IdrogeoError, match="non trovato"):
            await idrogeo.dictionary("nessuno")
        kw: dict[str, Any] = {"limit": 2, "select": ["id_frana"]}
        assert len(await idrogeo.search_landslides({"regione": "eq.16"}, **kw)) == 2
        assert len(await idrogeo.search_events({"regione": "eq.16"}, **kw)) == 2


def _dictionaries(request: httpx.Request) -> httpx.Response:
    name = request.url.path.removeprefix("/api/dizionari/")
    assert name in ("tipo_movimento", "stato_monitoraggio")
    return httpx.Response(
        200, json=[{"codice": "1", "descrizione": f"{name} it", "descrizione_en": f"{name} en"}]
    )


async def test_code_labels() -> None:
    calls: list[str] = []

    def counting(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return _dictionaries(request)

    async with _idrogeo(counting) as idrogeo:
        assert await idrogeo.labels("tipo_movimento", "it") == {"1": "tipo_movimento it"}
        calls.clear()
        labels = await idrogeo.code_labels(["tipo_movim", "tipo_movimento", "stato_monitoraggio"])
        assert labels["tipo_movim"] == labels["tipo_movimento"] == {"1": "tipo_movimento en"}
        assert labels["stato_monitoraggio"] == {"1": "stato_monitoraggio en"}
        assert len(calls) == 2  # one call per dictionary, not per field
        with pytest.raises(ValueError, match="no dictionary known"):
            await idrogeo.code_labels(["nome_tipo"])

    def every(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    async with _idrogeo(every) as idrogeo:
        assert set(await idrogeo.code_labels()) == set(CODE_DICTIONARIES)


async def test_lookup() -> None:
    def lists(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/voli"
        assert request.url.params["q"] == "1954" and request.url.params["limit"] == "2"
        return httpx.Response(200, json=[{"id": "0001", "nome": "Volo GAI", "data": "1954"}])

    async with _idrogeo(lists) as idrogeo:
        assert (await idrogeo.lookup("voli", "1954", limit=2))[0]["nome"] == "Volo GAI"


def _wms(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/geoserver/wms"
    params = request.url.params
    if "buffer" in params:
        point = {"type": "Point", "coordinates": [14.6301, 40.8380]}
        return httpx.Response(
            200,
            json={
                "features": [
                    {
                        "id": "frane_piff_opendata.9",
                        "geometry": point,
                        "properties": {"id_frana": "0640689600"},
                    }
                ]
            },
        )
    if params["bbox"].startswith("0."):
        return httpx.Response(200, json={"error": "nothing"})
    return httpx.Response(
        200,
        json={
            "features": [
                {"id": "pericolosita_frane.1", "properties": {"cod_per_it": 4}},
                {"id": "comuni_2019.1", "properties": {"pro_com": 65135, "comune": "Sarno"}},
            ]
        },
    )


async def test_hazard_at_and_landslides_near() -> None:
    async with _idrogeo(_wms) as idrogeo:
        hazard = await idrogeo.hazard_at(40.829, 14.617)
        assert hazard.landslide == "P4" and hazard.municipality_name == "Sarno"
        near = await idrogeo.landslides_near(40.838, 14.630, 100)
        assert near[0]["id_frana"] == "0640689600" and near[0]["distance_m"] < 20
        with pytest.raises(IdrogeoError, match="map service"):
            await idrogeo.hazard_at(0.0001, 0.0001)


async def test_api_retries_then_raises() -> None:
    calls: list[int] = []

    def busy(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(503)

    async with _idrogeo(busy, retries=2) as idrogeo:
        with pytest.raises(httpx.HTTPStatusError):
            await idrogeo.summary("pir", "italia")
    assert len(calls) == 3

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with _idrogeo(down, retries=0) as idrogeo:
        with pytest.raises(httpx.ConnectError):
            await idrogeo.dictionaries()


class _Paged:
    """A search endpoint holding ``rows`` records, honouring limit and offset."""

    def __init__(self, rows: int) -> None:
        self.rows = rows
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        params = request.url.params
        assert params["order"] in ("id_frana", "uid")  # stable pages
        start, size = int(params["offset"]), int(params["limit"])
        return httpx.Response(
            200, json=[{"n": n} for n in range(start, min(start + size, self.rows))]
        )


async def test_iterators_walk_every_page() -> None:
    for rows, pages in ((5, 3), (4, 3), (0, 1)):  # 2+2+1, 2+2+0, one empty page
        server = _Paged(rows)
        async with _idrogeo(server) as idrogeo:
            found = idrogeo.iter_landslides({"tipo_movimento": 6}, page_size=2)
            assert [r["n"] async for r in found] == list(range(rows))
        assert len(server.calls) == pages
        assert json.loads(server.calls[0].content) == {"tipo_movimento": 6}
    async with _idrogeo(_Paged(3)) as idrogeo:
        events = [r async for r in idrogeo.iter_events({"regione": "eq.16"}, select=["uid"])]
        assert len(events) == 3
        with pytest.raises(ValueError):
            [r async for r in idrogeo.iter_events(page_size=0)]


async def test_modified_since_reaches_every_search() -> None:
    since = datetime(2026, 11, 1, tzinfo=UTC)
    changed = {"modified": "gte.2026-11-01T00:00:00+00:00"}
    server = _Paged(1)
    async with _idrogeo(server) as idrogeo:
        assert len([r async for r in idrogeo.iter_landslides(modified_since=since)]) == 1
        assert (
            len([r async for r in idrogeo.iter_events({"regione": "eq.16"}, modified_since=since)])
            == 1
        )
        assert [r["n"] for r in await idrogeo.sites(modified_since=since)] == [0]
    assert json.loads(server.calls[0].content) == changed
    assert json.loads(server.calls[1].content) == {"regione": "eq.16", **changed}
    assert json.loads(server.calls[2].content) == changed
    assert [c.url.path for c in server.calls] == [
        "/api/frana/searchfilter",
        "/api/evento/main/filter",
        "/api/sito/filter",
    ]


def _frana(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api/frana/")
    if path == "0017680500":
        return httpx.Response(200, json={"id_frana": path, "tipo_movimento": 5})
    if path == "0000000000":
        return httpx.Response(401, json={"message": "Missing authorization header"})
    return httpx.Response(200, json=[])


async def test_landslide() -> None:
    async with _idrogeo(_frana) as idrogeo:
        assert (await idrogeo.landslide("0017680500"))["tipo_movimento"] == 5
        with pytest.raises(IdrogeoError, match="unknown or not public"):
            await idrogeo.landslide("0000000000")
        with pytest.raises(IdrogeoError, match="returned list"):
            await idrogeo.landslide("1")
        with pytest.raises(ValueError, match="digits"):
            await idrogeo.landslide("../evento")


def _monitoring(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api/")
    params = request.url.params
    if path == "sito/filter":
        assert params["order"] == "uid" and params["limit"] == "1000"
        assert json.loads(request.content) == {"stato_monitoraggio": "eq.1"}
        return httpx.Response(200, json=[{"uid": "SIPIE001", "point": [8.47, 44.66]}])
    if path == "webcam/filter":
        assert "order" not in params and "select" not in params
        return httpx.Response(200, json=[{"id_sensore": "SW00000001"}])
    if path == "sito/SIPIE001":
        return httpx.Response(200, json={"uid": "SIPIE001"})
    if path == "sito/SIPIE001/listing":
        return httpx.Response(200, json={"uid": "SIPIE001", "stazioni": [{"uid": "SIPIE001ST001"}]})
    if path == "sito/SIXXX999":
        return httpx.Response(404, json={"message": "Not found"})
    if path == "sito/SIXXX999/listing":
        return httpx.Response(200, content=b"null")
    if path == "sito/LIST":
        return httpx.Response(200, json=[])
    raise AssertionError(path)


async def test_monitoring_sites_and_webcams() -> None:
    async with _idrogeo(_monitoring) as idrogeo:
        active = await idrogeo.sites({"stato_monitoraggio": "eq.1"})
        assert active == [{"uid": "SIPIE001", "point": [8.47, 44.66]}]
        assert await idrogeo.webcams() == [{"id_sensore": "SW00000001"}]
        assert (await idrogeo.site("SIPIE001"))["uid"] == "SIPIE001"
        assert await idrogeo.stations("SIPIE001") == [{"uid": "SIPIE001ST001"}]
        with pytest.raises(IdrogeoError, match="Not found"):
            await idrogeo.site("SIXXX999")
        with pytest.raises(IdrogeoError, match="unknown"):
            await idrogeo.stations("SIXXX999")
        with pytest.raises(IdrogeoError, match="returned list"):
            await idrogeo.site("LIST")
        with pytest.raises(ValueError, match="letters and digits"):
            await idrogeo.site("../frana")


class _Comuni:
    """A fake list of three municipalities, counting the detail calls."""

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.missing: set[str] = set()
        self.running = 0
        self.peak = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/")
        if path == "pir/comuni":
            return httpx.Response(200, json=[{"pro_com": c} for c in (1001, 72006, 99001)])
        code = path.removeprefix("pir/comuni/")
        self.asked.append(code)
        self.running += 1
        self.peak = max(self.peak, self.running)
        await asyncio.sleep(0)
        self.running -= 1
        if code in self.missing:
            return httpx.Response(404, json={"message": "Comune non trovato"})
        return httpx.Response(200, json={"pro_com": int(code), "popfrp3p4p": 1.5})


def _async_idrogeo(handler: _Comuni) -> IdroGEO:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return IdroGEO(client, api_url="https://x/api", sleep=_sleep)


async def test_municipalities_are_kept_on_disk(tmp_path: Path) -> None:
    server = _Comuni()
    async with _async_idrogeo(server) as idrogeo:
        rows = await idrogeo.municipalities(directory=tmp_path, concurrency=2)
        assert [r["pro_com"] for r in rows] == [1001, 72006, 99001]  # the list's order
        assert sorted(server.asked) == ["1001", "72006", "99001"]
        assert server.peak <= 2
        assert sorted(p.name for p in (tmp_path / "pir_comuni").iterdir()) == [
            "1001.json",
            "72006.json",
            "99001.json",
        ]
        server.asked.clear()
        assert await idrogeo.municipalities(directory=tmp_path) == rows
        assert server.asked == []  # read back, only the list asked again
        bari = tmp_path / "pir_comuni" / "72006.json"
        old = bari.stat().st_mtime - 3 * 86400
        os.utime(bari, (old, old))
        await idrogeo.municipalities(directory=tmp_path, max_age=timedelta(days=1))
        assert server.asked == ["72006"]  # only the stale one


async def test_municipalities_resume_after_a_failure(tmp_path: Path) -> None:
    server = _Comuni()
    server.missing = {"99001"}
    async with _async_idrogeo(server) as idrogeo:
        with pytest.raises(IdrogeoError, match="non trovato"):
            await idrogeo.municipalities(directory=tmp_path, concurrency=1)
        assert (tmp_path / "pir_comuni" / "1001.json").exists()
        server.missing.clear()
        server.asked.clear()
        assert len(await idrogeo.municipalities(directory=tmp_path)) == 3
        assert server.asked == ["99001"]


async def test_summaries_check_their_arguments(tmp_path: Path) -> None:
    async with _async_idrogeo(_Comuni()) as idrogeo:
        with pytest.raises(ValueError, match="no list"):
            await idrogeo.summaries("pir", "italia", tmp_path)
        with pytest.raises(ValueError, match="concurrency"):
            await idrogeo.summaries("pir", "comuni", tmp_path, concurrency=0)


async def test_own_client_is_closed() -> None:
    idrogeo = IdroGEO()
    await idrogeo.aclose()
    assert idrogeo._client.is_closed
