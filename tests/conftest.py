"""Small but real IdroGEO shapefiles, zipped and served by a mocked transport."""

from __future__ import annotations

import io
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from ispra_idrogeo import IdroGEO, mosaic, opendata

#: A point in Trivento (Molise), and two municipalities around it.
LON, LAT = 14.55, 41.78
TRIVENTO, FORLI_DEL_SANNIO = 70081, 94020


def _shapefiles(folder: Path) -> dict[str, dict[str, bytes]]:
    """The members of each ZIP, drawn around (LON, LAT) with DuckDB spatial."""
    duckdb = pytest.importorskip("duckdb")
    db = duckdb.connect()
    try:
        db.execute("LOAD spatial")
    except duckdb.Error:  # pragma: no cover - first run on a new machine
        db.execute("INSTALL spatial")
        db.execute("LOAD spatial")
    db.execute("SET geometry_always_xy = true")
    db.execute(
        "CREATE TABLE here AS SELECT ST_Transform(ST_Point(?, ?), 'EPSG:4326', 'EPSG:32632') AS p",
        [LON, LAT],
    )

    def write(name: str, select: str, srs: str, options: str = "") -> None:
        db.execute(
            f"COPY ({select}) TO '{folder / name}.shp' WITH (FORMAT GDAL, "
            f"DRIVER 'ESRI Shapefile', SRS '{srs}'{options})"
        )

    shift = "ST_Point(ST_X(p) + {dx}, ST_Y(p))"
    points = " UNION ALL ".join(
        f"SELECT '{i:010d}' AS id_frana, {t} AS tipo_movim, '{n}' AS nome_tipo, "
        f"14.0 AS regione, {c // 1000}.0 AS provincia, {c}.0 AS comune, '{m}' AS nome_com, "
        f"{shift.format(dx=dx)} AS geom FROM here"
        for i, (t, n, c, m, dx) in enumerate(
            (
                (7, "Complesso", TRIVENTO, "Trivento", 100),
                (4, "Colamento lento", TRIVENTO, "Trivento", -40),
                (7, "Complesso", TRIVENTO, "Trivento", 900),
                (2, "Scivolamento", FORLI_DEL_SANNIO, "Forlì del Sannio", 20_000),
            )
        )
    )
    write(
        "frane_piff_opendataPoint",
        points,
        "EPSG:32632",
        ", LAYER_CREATION_OPTIONS 'ENCODING=ISO-8859-1'",
    )
    cpg = folder / "frane_piff_opendataPoint.cpg"
    cpg.rename(cpg.with_suffix(".cst"))  # as IdroGEO ships it

    write(
        "Mosaicatura_PAI",
        "SELECT ' Pericolosità molto elevata P4' AS per_fr_ita, ST_Buffer(p, 50) AS geom FROM here"
        " UNION ALL SELECT ' Pericolosità elevata P3', ST_Buffer(p, 200) FROM here"
        " UNION ALL SELECT ' Aree di Attenzione AA', ST_Buffer(ST_Point(0, 0), 10) FROM here",
        "EPSG:32632",
    )
    for prefix, metres in (("HPH", None), ("MPH", 300), ("LPH", 600)):
        area = (
            f"ST_Transform(ST_Buffer(p, {metres}), 'EPSG:32632', 'EPSG:3035')"
            if metres
            else "ST_Transform(ST_Buffer(ST_Point(0, 0), 10), 'EPSG:32632', 'EPSG:3035')"
        )
        write(
            f"{prefix}_Mosaicatura_idraulica",
            f"SELECT 'scenario {prefix}' AS scenario, {area} AS geom FROM here",
            "EPSG:3035",
        )
    db.close()

    def members(stem: str) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in folder.iterdir() if p.name.startswith(stem)}

    flood = {}
    for prefix in FLOOD_PREFIXES:
        flood.update(members(prefix))
    return {
        opendata("frane_piff", "molise").filename: members("frane_piff"),
        mosaic("pai_frane").filename: members("Mosaicatura_PAI"),
        mosaic("idraulica").filename: flood,
    }


FLOOD_PREFIXES = ("HPH", "MPH", "LPH")


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buffer.getvalue()


class Opendata:
    """Serves the ZIPs with an ETag; ``version`` changes it, ``asked`` counts."""

    def __init__(self, zips: dict[str, bytes]) -> None:
        self.zips = zips
        self.version = "1"
        self.sent: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        if name not in self.zips:
            return httpx.Response(404)
        etag = f'"{name}-{self.version}"'
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304)
        self.sent.append(name)
        return httpx.Response(200, content=self.zips[name], headers={"etag": etag})


@pytest.fixture(scope="session")
def zips(tmp_path_factory: pytest.TempPathFactory) -> dict[str, bytes]:
    folder = tmp_path_factory.mktemp("shapefiles")
    return {name: _zip(files) for name, files in _shapefiles(folder).items()}


@pytest.fixture
def opendata_server(zips: dict[str, bytes]) -> Opendata:
    return Opendata(zips)


@pytest.fixture
async def idrogeo(opendata_server: Opendata) -> AsyncIterator[IdroGEO]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(opendata_server))
    yield IdroGEO(client)
    await client.aclose()
