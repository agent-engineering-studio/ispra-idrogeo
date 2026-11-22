import io
import json
import math
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from ispra_idrogeo import IdroGEO, opendata
from ispra_idrogeo.dated import (
    IFFI_FIELDS,
    DatedLandslide,
    dated_landslides,
    from_event,
    from_iffi,
    parse_period,
    select,
    summary,
    utm32n_to_lonlat,
)

TODAY = date(2026, 11, 22)


def test_parse_period() -> None:
    assert parse_period("2019-05-12", TODAY) == (date(2019, 5, 12), date(2019, 5, 12), None)
    assert parse_period("1996-01-15T17:00:00", TODAY) == (
        date(1996, 1, 15),
        date(1996, 1, 15),
        "17:00",
    )
    # the day as written, whatever the zone; midnight is no time
    assert parse_period("2021-03-01T00:00:00+01:00", TODAY) == (
        date(2021, 3, 1),
        date(2021, 3, 1),
        None,
    )
    assert parse_period("1983-07", TODAY) == (date(1983, 7, 1), date(1983, 7, 31), None)
    assert parse_period("2024-02", TODAY) == (date(2024, 2, 1), date(2024, 2, 29), None)
    assert parse_period("1979", TODAY) == (date(1979, 1, 1), date(1979, 12, 31), None)
    for impossible in ("", "n.d.", "0999-01-01", "7970-01-01", "2026-11-23", "2023-13-01", None):
        assert parse_period(impossible, TODAY) is None, impossible


def test_from_iffi() -> None:
    row = {
        "id_frana": "0017680500",
        "data_certa": "1998-05-05T16:00:00",
        "point": [14.6, 40.8],
        "tipo_movimento": 5,
        "regione": 15,
        "provincia": 65,
        "comune": 65135,
    }
    sarno = from_iffi(row, TODAY)
    assert sarno is not None
    assert (sarno.precision, sarno.time, sarno.interval_days) == ("hour", "16:00", 1)
    assert (sarno.lon, sarno.lat, sarno.position_m) == (14.6, 40.8, None)
    assert (sarno.region, sarno.municipality, sarno.movement) == (15, 65135, 5)
    assert "CC BY-SA 4.0" in sarno.citation and sarno.main_event is None

    interval = from_iffi({"data_incerta_min": "1977-05", "data_incerta_max": "1977-06"}, TODAY)
    assert interval is not None
    assert (interval.start, interval.end, interval.precision) == (
        date(1977, 5, 1),
        date(1977, 6, 30),
        "interval",
    )
    assert interval.interval_days == 61 and interval.lon is None
    only_max = from_iffi({"data_incerta_max": "2000-10-16", "regione": "x"}, TODAY)
    assert only_max is not None and only_max.precision == "day" and only_max.region is None
    assert from_iffi({"data_certa": None, "data_incerta_min": "n.d."}, TODAY) is None


def _event(**props: Any) -> dict[str, Any]:
    geometry = props.pop("geometry", {"type": "Point", "coordinates": [500000.0, 4500000.0]})
    return {"type": "Feature", "geometry": geometry, "properties": props}


def test_from_event() -> None:
    event = from_event(
        _event(
            uid="EIT202500009",
            data_certa="2025-01-21T00:00",
            accuratezza_posizione="100",
            evento_principale="SI",
            tipo_movimento=1,
            regione=19,
        ),
        TODAY,
    )
    assert event is not None
    assert (event.source, event.precision, event.position_m, event.main_event) == (
        "eventi",
        "day",
        100,
        True,
    )
    assert event.lon == pytest.approx(9.0) and event.lat == pytest.approx(40.65, abs=0.01)
    assert "eventi" in event.citation
    other = from_event(_event(data_certa="2020-12-27T10:50:00+01:00", geometry=None), TODAY)
    assert other is not None
    assert (other.time, other.lon, other.position_m, other.main_event) == (
        "10:50",
        None,
        None,
        None,
    )
    assert from_event(_event(data_certa=None), TODAY) is None
    assert from_event({"properties": None}, TODAY) is None


def _dated(**kw: Any) -> DatedLandslide:
    base: dict[str, Any] = {
        "source": "eventi",
        "id": "x",
        "lon": None,
        "lat": None,
        "start": date(2020, 1, 1),
        "end": date(2020, 1, 1),
        "time": None,
        "precision": "day",
        "interval_days": 1,
        "position_m": 0,
        "movement": None,
        "region": 7,
        "province": None,
        "municipality": None,
        "main_event": None,
        "citation": "c",
    }
    return DatedLandslide(**{**base, **kw})


def test_select_and_summary() -> None:
    found = [
        _dated(id="a"),
        _dated(
            id="b",
            start=date(2017, 1, 1),
            end=date(2017, 12, 31),
            interval_days=365,
            precision="interval",
            source="iffi",
            position_m=None,
            region=9,
        ),
        _dated(id="c", start=date(2023, 5, 1), end=date(2023, 5, 1), position_m=10_000),
    ]

    def ids(rows: list[DatedLandslide]) -> list[str]:
        return [d.id for d in rows]

    assert ids(select(found, since=date(2018, 1, 1))) == ["a", "c"]
    assert ids(select(found, until=date(2020, 1, 1))) == ["b"]
    assert ids(select(found, region=9)) == ["b"]
    assert ids(select(found, max_interval_days=1)) == ["a", "c"]
    assert ids(select(found, max_position_m=1000)) == ["a"]  # IFFI states no accuracy
    counts = summary(found)
    assert counts["total"] == 3 and counts["by_source"] == {"eventi": 2, "iffi": 1}
    assert counts["by_position_m"] == {"0": 1, "10000": 1, "not stated": 1}
    assert counts["by_year"] == {"2017": 1, "2020": 1, "2023": 1}
    assert found[0].as_dict()["start"] == "2020-01-01"


def test_utm_matches_proj_across_italy() -> None:
    duckdb = pytest.importorskip("duckdb")
    db = duckdb.connect()
    try:
        db.execute("LOAD spatial")
    except duckdb.Error:  # pragma: no cover - first run on a new machine
        db.execute("INSTALL spatial")
        db.execute("LOAD spatial")
    db.execute("SET geometry_always_xy = true")
    for lon, lat in ((7.3, 45.7), (12.33, 45.44), (14.63, 40.82), (18.17, 40.35), (12.6, 35.5)):
        x, y = db.execute(
            "SELECT ST_X(p), ST_Y(p) FROM "
            "(SELECT ST_Transform(ST_Point(?, ?), 'EPSG:4326', 'EPSG:32632') AS p)",
            [lon, lat],
        ).fetchone()
        back_lon, back_lat = utm32n_to_lonlat(x, y)
        metres = math.hypot(
            (back_lon - lon) * 111_320 * math.cos(math.radians(lat)), (back_lat - lat) * 110_540
        )
        assert metres < 0.01, (lon, lat, metres)


def _geojson_zip(features: list[dict[str, Any]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("eventi_ispra_opendata.json", json.dumps({"features": features}))
    return buffer.getvalue()


async def test_dated_landslides_reads_both_sources(tmp_path: Path) -> None:
    events = [
        _event(uid="E1", data_certa="2024-10-10", accuratezza_posizione="Esatta", regione=18),
        _event(uid="E2", data_certa=None),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/frana/searchfilter":
            dated = ["data_certa", "data_incerta_min", "data_incerta_max"]
            wanted = "(" + ",".join(f"{f}.not.is.null" for f in dated) + ")"
            assert json.loads(request.content) == {"or": wanted}
            assert request.url.params["select"] == ",".join(IFFI_FIELDS)
            return httpx.Response(
                200,
                json=[
                    {"id_frana": "1", "data_certa": "2019-11-12", "regione": 18},
                    {"id_frana": "2", "data_incerta_min": "1979", "regione": 18},
                    {"id_frana": "3", "data_certa": "7970-01-01"},  # impossible, left out
                ],
            )
        assert request.url.path == "/opendata/eventi/" + opendata("eventi", fmt="geojson").filename
        return httpx.Response(200, content=_geojson_zip(events))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with IdroGEO(client, api_url="https://idrogeo.isprambiente.it/api/") as idrogeo:
        found = await dated_landslides(idrogeo, directory=tmp_path)
        assert [(d.source, d.id) for d in found] == [("iffi", "2"), ("iffi", "1"), ("eventi", "E1")]
        assert found[-1].position_m == 0
        recent = await dated_landslides(
            idrogeo, sources=["eventi"], since=date(2020, 1, 1), directory=tmp_path
        )
        assert [d.id for d in recent] == ["E1"]
    await client.aclose()
