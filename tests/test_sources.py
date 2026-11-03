from __future__ import annotations

import pytest

from ispra_idrogeo import (
    ITALY,
    LANDSLIDE_LAYERS,
    PROVINCES,
    REGIONS,
    mosaic,
    opendata,
    region_area,
    sensor_data,
)


def test_national_shapefile_url() -> None:
    d = opendata("frane_poly")
    assert d.url == ("https://idrogeo.isprambiente.it/opendata/frane/frane_poly_ispra_opendata.zip")
    assert d.filename == "frane_poly_ispra_opendata.zip"
    assert d.stem == "frane_poly_ispra_opendata"


def test_regional_geojson_and_events() -> None:
    d = opendata("frane_piff", "puglia", "geojson")
    assert d.url.endswith("/opendata/frane/frane_piff_puglia_opendata.json.zip")
    assert d.stem == "frane_piff_puglia_opendata"
    assert opendata("eventi").url.endswith("/opendata/eventi/eventi_ispra_opendata.zip")
    assert "/opendata/segnalazioni/" in opendata("segnalazioni", "bolzano").url


def test_unknown_layer_or_area() -> None:
    with pytest.raises(ValueError, match="unknown layer"):
        opendata("iffi")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown area"):
        opendata("frane_piff", "trentino-alto-adige")


def test_mosaics_and_sensor_data() -> None:
    d = mosaic("pai_frane")
    assert d.url.endswith(
        "/opendata/wms/Mosaicatura_ISPRA_2020_2021_aree_pericolosita_frana_PAI.zip"
    )
    assert d.stem == "Mosaicatura_ISPRA_2020_2021_aree_pericolosita_frana_PAI"
    with pytest.raises(ValueError, match="unknown mosaic"):
        mosaic("valanghe")  # type: ignore[arg-type]
    s = sensor_data()
    assert s.url.endswith("/opendata/monitoraggio/idrogeo_sensor_data.csv.bz2")
    assert s.stem == "idrogeo_sensor_data"


def test_areas() -> None:
    assert region_area(16) == "puglia"
    with pytest.raises(KeyError):
        region_area(4)  # Trentino-Alto Adige publishes per province
    assert {"bolzano", "trento"} <= set(PROVINCES.values())
    assert len(REGIONS) == 19
    assert ITALY == "ispra"
    assert len(LANDSLIDE_LAYERS) == 5


def test_stem_of_a_plain_file() -> None:
    from ispra_idrogeo import Dataset

    assert Dataset(url="u", filename="readme.txt").stem == "readme.txt"
