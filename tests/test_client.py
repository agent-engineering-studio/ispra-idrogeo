from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from ispra_idrogeo import IdroGEO, IdrogeoError, mosaic, opendata, sensor_data

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


async def test_own_client_is_closed() -> None:
    idrogeo = IdroGEO()
    await idrogeo.aclose()
    assert idrogeo._client.is_closed
