from __future__ import annotations

import math
from typing import Any

import pytest

from ispra_idrogeo.wms import (
    LITHOLOGY_LAYER,
    PointHazard,
    area_params,
    distance_m,
    nearby,
    parse_hazard,
    point_params,
)

# A ~111 m square around (0, 0): 0.001 degrees on each side.
SQUARE = [
    [[-0.0005, -0.0005], [0.0005, -0.0005], [0.0005, 0.0005], [-0.0005, 0.0005], [-0.0005, -0.0005]]
]


def _feature(layer: str, geometry: object = None, **props: object) -> dict[str, Any]:
    return {"id": f"{layer}.1", "geometry": geometry, "properties": props}


def test_point_params() -> None:
    params = point_params(40.829, 14.617)
    assert params["request"] == "GetFeatureInfo" and params["crs"] == "EPSG:4326"
    assert params["i"] == params["j"] == "50" and "buffer" not in params
    south, west, north, east = map(float, params["bbox"].split(","))
    assert south < 40.829 < north and west < 14.617 < east  # lat,lon order in WMS 1.3.0
    assert LITHOLOGY_LAYER not in params["layers"]
    assert LITHOLOGY_LAYER in point_params(40.829, 14.617, lithology=True)["layers"]
    with pytest.raises(ValueError, match="latitude and longitude"):
        point_params(14.617, 200)


def test_area_params() -> None:
    params = area_params(45.0, 9.0, 1000, 50)
    south, west, north, east = map(float, params["bbox"].split(","))
    assert math.isclose((north - south) / 2, 1000 / 111_195, rel_tol=1e-3)
    assert (east - west) > (north - south)  # a degree of longitude is shorter at 45°N
    assert params["buffer"] == "50" and params["feature_count"] == "50"
    for bad in ((0, 50), (6000, 50), (500, 0), (500, 1001)):
        with pytest.raises(ValueError):
            area_params(45.0, 9.0, *bad)


def test_parse_hazard() -> None:
    features: list[dict[str, Any]] = [
        _feature("pericolosita_frane", cod_per_it=1),
        _feature("pericolosita_frane", cod_per_it="4"),
        _feature("pericolosita_frane", cod_per_it=0),
        _feature("pericolosita_idraulica_p1", scenariop1="bassa P1"),
        _feature("pericolosita_idraulica_p3", scenariop3="elevata P3"),
        _feature("comuni_2019", pro_com=65135, comune="Sarno", cod_prov=65, cod_reg=15),
        _feature("idrogeo_litologia_100k", code="Cr", titolo_eng="Carbonate rocks"),
        {"id": "", "properties": {"acclivita": 12.3014}},
    ]
    assert parse_hazard(40.8, 14.6, features) == PointHazard(
        lat=40.8,
        lon=14.6,
        landslide="P4",  # the highest of the polygons there
        flood="P3",
        flood_scenarios=("P3", "P1"),
        municipality=65135,
        municipality_name="Sarno",
        province=65,
        region=15,
        lithology="Carbonate rocks",
        lithology_code="Cr",
        slope_deg=12.3,
    )
    only_attention = parse_hazard(0, 0, [_feature("pericolosita_frane", cod_per_it=0)])
    assert only_attention.landslide == "AA"
    sea = parse_hazard(
        0, 0, [{"properties": {"acclivita": -9999.0}}, _feature("x", cod_per_it="?")]
    )
    assert sea.slope_deg is None and sea.landslide is None and sea.municipality is None


def test_distance_m() -> None:
    assert distance_m(0, 0, {"type": "Point", "coordinates": [0.001, 0]}) == pytest.approx(
        111.2, abs=0.1
    )
    assert distance_m(
        0, 0, {"type": "MultiPoint", "coordinates": [[0.01, 0], [0, 0.001]]}
    ) == pytest.approx(111.2, abs=0.1)
    line = {"type": "LineString", "coordinates": [[-1, 0.001], [1, 0.001]]}
    assert distance_m(0, 0, line) == pytest.approx(111.2, abs=0.1)  # to the segment, not its ends
    assert distance_m(
        0, 0, {"type": "MultiLineString", "coordinates": [[[0.002, 0]], [[0, 0.003], [0, 0.004]]]}
    ) == pytest.approx(222.4, abs=0.1)
    assert distance_m(0, 0, {"type": "Polygon", "coordinates": SQUARE}) == 0.0
    outside = [[[x + 0.002, y] for x, y in SQUARE[0]]]
    assert distance_m(0, 0, {"type": "MultiPolygon", "coordinates": [outside]}) == pytest.approx(
        166.8, abs=0.2
    )
    holed = [
        SQUARE[0],
        [
            [-0.0001, -0.0001],
            [0.0001, -0.0001],
            [0.0001, 0.0001],
            [-0.0001, 0.0001],
            [-0.0001, -0.0001],
        ],
    ]
    assert distance_m(0, 0, {"type": "Polygon", "coordinates": holed}) == pytest.approx(
        11.1, abs=0.1
    )
    assert distance_m(0, 0, {"type": "Point", "coordinates": [0, 0]}) == 0.0
    assert distance_m(0, 0, {"type": "GeometryCollection"}) == math.inf
    assert distance_m(
        0, 0, {"type": "LineString", "coordinates": [[0.001, 0], [0.001, 0]]}
    ) == pytest.approx(111.2, abs=0.1)


def test_nearby() -> None:
    point = {"type": "Point", "coordinates": [0.001, 0]}
    features: list[dict[str, Any]] = [
        _feature("frane_piff_opendata", point, id_frana="A", nome_tipo="Complesso"),
        _feature("frane_poly_opendata", {"type": "Polygon", "coordinates": SQUARE}, id_frana="A"),
        _feature("frane_piff_opendata", {"type": "Point", "coordinates": [0.004, 0]}, id_frana="B"),
        _feature("frane_piff_opendata", {"type": "Point", "coordinates": [0.1, 0]}, id_frana="far"),
        _feature("frane_piff_opendata", None, id_frana="no geometry"),
        {"id": "", "geometry": point, "properties": {}},
        {"id": "unknown_layer.1", "geometry": point, "properties": {"id_frana": "C"}},
    ]
    rows = nearby(0, 0, features, radius_m=500)
    assert [r["id_frana"] for r in rows] == ["A", "C", "B"]
    assert rows[0]["distance_m"] == 0.0 and rows[0]["shapes"] == ["point", "polygon"]
    assert rows[0]["nome_tipo"] == "Complesso"
    assert rows[1]["shapes"] == [] and rows[2]["distance_m"] == pytest.approx(444.8, abs=0.1)
