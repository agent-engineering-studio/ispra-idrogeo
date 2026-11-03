from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point

from ispra_idrogeo.geo import add_labels, frame, read

WORDS = {"4": "slow earth flow", "15": "inclinometer", "22": "topographic monitoring"}


def _shapefile(folder: Path) -> Path:
    folder.mkdir()
    data = gpd.GeoDataFrame(
        {"id_frana": ["0017680500"], "tipo_movim": [4]},
        geometry=[Point(688001.7, 5152545.2)],
        crs="EPSG:32632",
    )
    data.to_file(folder / "frane_piff_opendataPoint.shp")
    return folder


def test_read_a_folder_or_a_file(tmp_path: Path) -> None:
    folder = _shapefile(tmp_path / "frane_piff_molise_opendata")
    landslides = read(folder)
    assert landslides.crs.to_epsg() == 32632
    assert landslides["id_frana"].tolist() == ["0017680500"]
    assert len(read(folder / "frane_piff_opendataPoint.shp", columns=["id_frana"])) == 1
    (folder / "second.geojson").write_text('{"type": "FeatureCollection", "features": []}')
    with pytest.raises(ValueError, match="one shapefile or GeoJSON"):
        read(folder)
    (tmp_path / "empty").mkdir()
    with pytest.raises(ValueError, match="none"):
        read(tmp_path / "empty")


def test_frame_from_points() -> None:
    sites = frame([{"uid": "SIABR001", "point": [14.03, 42.24]}, {"uid": "SIX", "point": None}])
    assert sites.crs.to_epsg() == 4326
    assert sites.geometry.iloc[0].x == 14.03
    assert sites.geometry.iloc[1] is None  # kept, without a geometry
    assert "point" not in sites.columns


def test_frame_from_geojson_keeps_its_crs() -> None:
    geom = {
        "type": "Point",
        "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
        "coordinates": [1016342.8, 5794446.8],
    }
    cams = frame([{"id_sensore": "SW00000001", "geom": geom}], geometry="geom")
    assert cams.crs.to_epsg() == 3857
    assert cams.geometry.iloc[0].x == 1016342.8
    assert frame([], geometry="geom").crs is None


def test_add_labels() -> None:
    rows = frame(
        [
            {"tipo_movim": 4.0, "strumentazione": [15, 22]},
            {"tipo_movim": None, "strumentazione": []},
            {"tipo_movim": 99, "strumentazione": None},
        ]
    )
    out = add_labels(rows, {"tipo_movim": WORDS, "strumentazione": WORDS, "assente": WORDS})
    assert out["tipo_movim_label"].tolist() == ["slow earth flow", None, None]
    assert out["strumentazione_label"].tolist() == [
        ["inclinometer", "topographic monitoring"],
        [],
        None,
    ]
    assert "assente_label" not in out.columns
    assert "tipo_movim_label" not in rows.columns  # a copy
