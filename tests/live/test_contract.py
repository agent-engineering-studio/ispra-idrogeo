"""The contract with the live IdroGEO service: ``pytest -m live``.

Every test checks one thing the library or its README relies on: a path
that answers, a field that is read, a trap that is still a trap. They need
the network and run weekly in CI (``.github/workflows/live.yml``), never in
``make check``. When one fails, IdroGEO changed: fix the library, or the
README's "traps we already fell into", then the test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from ispra_idrogeo import (
    BASE_URL,
    EVENT_LAYERS,
    LANDSLIDE_LAYERS,
    MOSAICS,
    PROVINCES,
    REGIONS,
    IdroGEO,
    IdrogeoError,
    Level,
    landslide_filter,
    mosaic,
    opendata,
    sensor_data,
)

pytestmark = pytest.mark.live

#: Places whose answers are documented in the README.
SARNO = (40.829, 14.617)  # the hills above Sarno: landslide P4
VENICE = (45.438, 12.330)  # flood P3, P2 and P1
BARI = 72006


@pytest.fixture
async def idrogeo() -> AsyncIterator[IdroGEO]:
    async with IdroGEO(retries=2, backoff_s=5) as client:
        yield client


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        yield client


# Downloads


@pytest.mark.parametrize("layer", [*LANDSLIDE_LAYERS, *EVENT_LAYERS])
async def test_every_national_layer_is_published(http: httpx.AsyncClient, layer: str) -> None:
    response = await http.head(opendata(layer).url)  # type: ignore[arg-type]
    assert response.status_code == 200
    assert response.headers.get("etag") or response.headers.get("last-modified")


@pytest.mark.parametrize("area", [*REGIONS.values(), *PROVINCES.values()])
async def test_every_area_is_published(http: httpx.AsyncClient, area: str) -> None:
    assert (await http.head(opendata("frane_piff", area).url)).status_code == 200


@pytest.mark.parametrize("name", MOSAICS)
async def test_the_mosaics_and_the_sensor_data_are_published(
    http: httpx.AsyncClient, name: str
) -> None:
    for dataset in (mosaic(name), sensor_data()):  # type: ignore[arg-type]
        assert (await http.head(dataset.url)).status_code == 200


async def test_an_unchanged_download_costs_one_304(idrogeo: IdroGEO, tmp_path: Path) -> None:
    first = await idrogeo.download(opendata("eventi"), tmp_path)
    second = await idrogeo.download(opendata("eventi"), tmp_path)
    assert first.changed and not second.changed


async def test_the_old_paths_are_still_gone(http: httpx.AsyncClient) -> None:
    for path in (
        "/opendata/iffi/puglia/iffi_puglia_frane_piff.zip",
        "/opendata/iffi/dizionari/tipo_movimento.json",
    ):
        assert (await http.get(BASE_URL + path)).status_code == 404, path
    capabilities = {"service": "WFS", "request": "GetCapabilities"}
    workspace = await http.get(f"{BASE_URL}/geoserver/idrogeo/frane/ows", params=capabilities)
    assert workspace.status_code == 401  # the WFS asks for a login
    anywhere = await http.get(f"{BASE_URL}/geoserver/wfs", params=capabilities)
    assert "Service WFS is disabled" in anywhere.text  # with HTTP 200


# Summaries


async def test_the_indicators_the_tools_read(idrogeo: IdroGEO) -> None:
    italy = await idrogeo.summary("pir", "italia")
    for key in ("pop_res021", "pop_idr_p2", "popidp2_p", "ar_fr_p3p4", "popfrp3p4p", "ar_kmq"):
        assert isinstance(italy[key], int | float), key
    bari = await idrogeo.summary("pir", "comuni", BARI)
    assert bari["nome"] == "Bari" and bari["popidp2_p"] > 0


async def test_the_lists_carry_their_codes(idrogeo: IdroGEO) -> None:
    levels: tuple[tuple[Level, str, int], ...] = (
        ("regioni", "cod_reg", 20),
        ("province", "cod_prov", 100),
        ("comuni", "pro_com", 7800),
    )
    for level, field, at_least in levels:
        items = await idrogeo.summary("iffi", level)
        assert len(items) >= at_least, level
        assert all({"uid", "nome", field, "cod_reg"} <= item.keys() for item in items), level


async def test_iffi_counts(idrogeo: IdroGEO) -> None:
    bari = await idrogeo.summary("iffi", "comuni", BARI)
    assert isinstance(bari["frane_totali"], int)
    assert all({"cod", "nr_frane"} <= s.keys() for s in bari["frane_stats"])


# Code lists and lookups


async def test_code_lists(idrogeo: IdroGEO) -> None:
    assert "tipo_movimento" in await idrogeo.dictionaries()
    movements = await idrogeo.labels("tipo_movimento", "en")
    assert movements["6"] and movements["2"]
    assert await idrogeo.lookup("formazioni", "argille", limit=1)


# Records and searches


async def test_one_landslide_and_the_401_trap(idrogeo: IdroGEO) -> None:
    [found] = await idrogeo.search_landslides(landslide_filter(movement=6), limit=1)
    record = await idrogeo.landslide(found["id_frana"])
    assert record["tipo_movimento"] == 6
    with pytest.raises(IdrogeoError):  # 401 "Missing authorization header", not 404
        await idrogeo.landslide("0000000000")


async def test_the_movement_filter_wants_a_plain_number(idrogeo: IdroGEO) -> None:
    rows = await idrogeo.search_landslides({"tipo_movimento": 6}, limit=5)
    assert rows and all(r["tipo_movimento"] == 6 for r in rows)
    with pytest.raises(IdrogeoError, match="invalid input syntax for type integer"):
        await idrogeo.search_landslides({"tipo_movimento": "eq.6"}, limit=1)


async def test_events_and_their_dates(idrogeo: IdroGEO) -> None:
    rows = await idrogeo.search_events({"regione": "eq.7"}, limit=5)  # Liguria
    assert rows and all("uid" in r for r in rows)


async def test_monitoring_sites(idrogeo: IdroGEO) -> None:
    sites = await idrogeo.sites()
    assert len(sites) > 500
    assert any(s.get("id_frane_correlati") for s in sites)
    assert (await idrogeo.site("SIPIE001"))["uid"] == "SIPIE001"
    with pytest.raises(IdrogeoError):
        await idrogeo.site("SIXXX999")


# The map service


async def test_hazard_at_a_point(idrogeo: IdroGEO) -> None:
    sarno = await idrogeo.hazard_at(*SARNO)
    assert sarno.landslide == "P4" and sarno.municipality_name == "Sarno"
    venice = await idrogeo.hazard_at(*VENICE)
    assert venice.flood == "P3" and "P1" in venice.flood_scenarios


async def test_landslides_near_a_point(idrogeo: IdroGEO) -> None:
    near = await idrogeo.landslides_near(40.838, 14.630, radius_m=500)
    assert near and near == sorted(near, key=lambda f: f["distance_m"])
    assert {"id_frana", "nome_tipo", "distance_m"} <= near[0].keys()
