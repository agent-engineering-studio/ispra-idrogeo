from __future__ import annotations

import io
import json
import os
import time
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from ispra_idrogeo import IdroGEO, cli, init
from ispra_idrogeo.offline import CORINE_FOLDER, IFFI_AREAS

ETAG = '"v1"'


def _zip(name: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr(f"{name}.shp", b"shape")
    return buffer.getvalue()


class _Server:
    """IdroGEO, ISTAT and SINAnet: ZIPs and plain files with an ETag, 304 to the right one."""

    def __init__(self) -> None:
        self.requests: list[str] = []
        self.missing: set[str] = set()
        self.broken: set[str] = set()
        self.down: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        self.requests.append(name)
        if name in self.down:
            raise httpx.ConnectError("down", request=request)
        if name in self.missing:
            return httpx.Response(404)
        if request.headers.get("if-none-match") == ETAG:
            return httpx.Response(304)
        if name in self.broken:
            body = b"not a zip"
        elif name.endswith(".zip"):
            body = _zip(name.removesuffix(".zip"))
        else:
            body = b"corine"
        return httpx.Response(200, content=body, headers={"ETag": ETAG})


def _client(server: _Server) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(server))


async def test_downloads_what_limen_uses_then_only_what_changed(tmp_path: Path) -> None:
    server = _Server()
    async with _client(server) as client:
        first = await init(tmp_path, client=client, retries=0)
        assert not client.is_closed  # the caller's client stays open
        assert not first.failed and not first.skipped
        assert len(first.downloaded) == 5 * len(IFFI_AREAS) + 2 + 1 + 5 == 113
        assert first.downloaded_bytes > 0
        assert (tmp_path / "frane_piff_puglia_opendata" / "frane_piff_puglia_opendata.shp").exists()
        assert (tmp_path / "Mosaicatura_ISPRA_2020_aree_pericolosita_idraulica").is_dir()
        assert (tmp_path / "Limiti01012023_g").is_dir()
        assert (tmp_path / CORINE_FOLDER / "CLC18_IT.shp").read_bytes() == b"corine"
        assert not list(tmp_path.rglob("*.part"))

        server.requests.clear()
        again = await init(tmp_path, client=client, retries=0)
    assert not again.downloaded and len(again.skipped) == 113 and again.downloaded_bytes == 0
    # ISTAT and CORINE never change: not even asked for again.
    assert len(server.requests) == 107
    assert "Limiti01012023_g.zip" not in server.requests


async def test_chosen_areas_and_mosaics(tmp_path: Path) -> None:
    server = _Server()
    async with _client(server) as client:
        found = await init(
            tmp_path,
            areas=["puglia"],
            mosaics=["pai_frane_2024", "pai_frane_2024"],
            boundaries=False,
            land_cover=False,
            unpack=False,
            client=client,
        )
    assert found.downloaded == sorted(
        [f"{layer}_puglia_opendata.zip" for layer in ("frane_piff", "frane_poly", "frane_line")]
        + ["aree_poly_puglia_opendata.zip", "dgpv_poly_puglia_opendata.zip"]
        + ["Mosaicatura_ISPRA_2024_pericolosita_frana_PAI.zip"]
    )
    assert not [p for p in tmp_path.iterdir() if p.is_dir()]  # nothing unpacked

    with pytest.raises(ValueError, match="unknown area"):
        await init(tmp_path, areas=["atlantide"], client=_client(server))
    with pytest.raises(ValueError, match="concurrency"):
        await init(tmp_path, concurrency=0, client=_client(server))


async def test_a_file_that_fails_does_not_stop_the_others(tmp_path: Path) -> None:
    server = _Server()
    server.missing.add("frane_piff_molise_opendata.zip")
    server.down.add("CLC18_IT.dbf")
    server.broken.add("dgpv_poly_molise_opendata.zip")
    async with _client(server) as client:
        found = await init(
            tmp_path, areas=["molise"], mosaics=(), boundaries=False, client=client, retries=0
        )
    assert set(found.failed) == {
        "frane_piff_molise_opendata.zip",
        f"{CORINE_FOLDER}/CLC18_IT.dbf",
        "dgpv_poly_molise_opendata.zip",
    }
    assert "404" in found.failed["frane_piff_molise_opendata.zip"]
    assert found.failed["dgpv_poly_molise_opendata.zip"].startswith("cannot unpack")
    # The broken ZIP is gone with its ETag, so the next run downloads it in full.
    assert not (tmp_path / "dgpv_poly_molise_opendata.zip").exists()
    assert not (tmp_path / "dgpv_poly_molise_opendata.zip.meta.json").exists()
    assert len(found.downloaded) == 3 + 4


async def test_max_age_skips_recent_files_without_asking(tmp_path: Path) -> None:
    server = _Server()
    kw: dict[str, Any] = {"areas": ["molise"], "mosaics": (), "boundaries": False}
    kw["land_cover"] = False
    async with _client(server) as client:
        await init(tmp_path, client=client, **kw)
        server.requests.clear()
        await init(tmp_path, client=client, max_age=timedelta(days=1), **kw)
        assert server.requests == []
        old = time.time() - 2 * 86_400
        zip_path = tmp_path / "frane_piff_molise_opendata.zip"
        os.utime(zip_path, (old, old))
        found = await init(tmp_path, client=client, max_age=timedelta(days=1), **kw)
    assert server.requests == ["frane_piff_molise_opendata.zip"]
    assert found.skipped == sorted(found.skipped) and len(found.skipped) == 5


async def test_a_disk_error_is_raised(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("")
    async with _client(_Server()) as client:
        with pytest.raises(OSError):
            await init(blocker / "sub", areas=["molise"], client=client)


async def test_own_client_and_default_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("IDROGEO_DATA_DIR", raising=False)
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    server = _Server()
    real = httpx.AsyncClient
    monkeypatch.setattr(
        "ispra_idrogeo.client.httpx.AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(server), **kw),
    )
    found = await init(areas=(), mosaics=(), land_cover=False)
    assert found.directory == tmp_path / "ispra-idrogeo"
    assert found.downloaded == ["Limiti01012023_g.zip"]
    assert (tmp_path / "ispra-idrogeo" / "Limiti01012023_g").is_dir()


async def _cli(*argv: str, server: _Server) -> tuple[list[Any], BaseException | None]:
    out = io.StringIO()
    error: BaseException | None = None
    async with IdroGEO(_client(server), retries=0) as idrogeo:
        try:
            await cli.run(cli.parser().parse_args(argv), idrogeo, out)
        except Exception as exc:
            error = exc
    return [json.loads(line) for line in out.getvalue().splitlines()], error


async def test_cli_init(tmp_path: Path) -> None:
    server = _Server()
    rows, error = await _cli(
        "--dir",
        str(tmp_path),
        "init",
        "--area",
        "molise",
        "--mosaic",
        "idraulica",
        "--no-boundaries",
        "--no-land-cover",
        "--max-age-days",
        "1",
        server=server,
    )
    assert error is None
    assert rows[0]["directory"] == str(tmp_path)
    assert len(rows[0]["downloaded"]) == 6 and rows[0]["failed"] == {}

    server.missing.add("CLC18_IT.prj")
    rows, error = await _cli(
        "--dir", str(tmp_path), "init", "--no-iffi", "--no-mosaics", "--no-unpack", server=server
    )
    corine = [f"{CORINE_FOLDER}/CLC18_IT.{ext}" for ext in ("cpg", "dbf", "shp", "shx")]
    assert rows[0]["downloaded"] == sorted(["Limiti01012023_g.zip", *corine])
    assert str(error) == f"did not arrive: {CORINE_FOLDER}/CLC18_IT.prj"
