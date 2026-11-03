"""Where IdroGEO publishes its open data, as pure URL builders.

The open-data downloads are the ones the IdroGEO web app links to under
"Download massivo": ``/opendata/<group>/<layer>_<area>_opendata.zip``, a
shapefile, or ``….json.zip`` for GeoJSON. ``<area>`` is ``ispra`` for the
whole of Italy, or the file name of a region or province (:data:`REGIONS`,
:data:`PROVINCES`). ISPRA regenerates them every day, with an ``ETag`` and a
``Last-Modified``, so a conditional GET tells whether anything changed.

The older paths ``/opendata/iffi/<region>/iffi_<region>_<layer>.zip`` and
``/opendata/iffi/dizionari/*.json`` answer 404 since 2026: the dictionaries
are now served by the API (:mod:`ispra_idrogeo.api`).

Coordinates in the files are in EPSG:32632 (WGS 84 / UTM zone 32N).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BASE_URL = "https://idrogeo.isprambiente.it"

#: The whole of Italy, in the file names.
ITALY = "ispra"

#: IFFI landslide inventory layers: PIFF points (one per landslide), landslide
#: polygons and lines, areas with diffuse landslides, and DGPV (deep-seated
#: gravitational slope deformations).
LandslideLayer = Literal["frane_piff", "frane_poly", "frane_line", "aree_poly", "dgpv_poly"]
LANDSLIDE_LAYERS: tuple[LandslideLayer, ...] = (
    "frane_piff",
    "frane_poly",
    "frane_line",
    "aree_poly",
    "dgpv_poly",
)

#: Point layers outside the inventory: dated landslide events, and reports.
EventLayer = Literal["eventi", "segnalazioni"]
EVENT_LAYERS: tuple[EventLayer, ...] = ("eventi", "segnalazioni")

Layer = LandslideLayer | EventLayer
Format = Literal["shapefile", "geojson"]

#: Region file names by ISTAT region code, as the web app builds them.
#: Trentino-Alto Adige (4) has none: its two provinces publish separately.
REGIONS: dict[int, str] = {
    1: "piemonte",
    2: "valle-d-aosta",
    3: "lombardia",
    5: "veneto",
    6: "friuli-venezia-giulia",
    7: "liguria",
    8: "emilia-romagna",
    9: "toscana",
    10: "umbria",
    11: "marche",
    12: "lazio",
    13: "abruzzo",
    14: "molise",
    15: "campania",
    16: "puglia",
    17: "basilicata",
    18: "calabria",
    19: "sicilia",
    20: "sardegna",
}

#: Province file names by ISTAT province code: the two autonomous provinces,
#: and the Sicilian ones, which publish their own files too.
PROVINCES: dict[int, str] = {
    21: "bolzano",
    22: "trento",
    81: "trapani",
    82: "palermo",
    83: "messina",
    84: "agrigento",
    85: "caltanissetta",
    86: "enna",
    87: "catania",
    88: "ragusa",
    89: "siracusa",
}

#: National hazard mosaics (PAI landslide hazard, flood hazard). Large (about
#: 1.2 and 0.75 GB) and rarely updated.
Mosaic = Literal["pai_frane", "idraulica"]
MOSAICS: dict[Mosaic, str] = {
    "pai_frane": "Mosaicatura_ISPRA_2020_2021_aree_pericolosita_frana_PAI",
    "idraulica": "Mosaicatura_ISPRA_2020_aree_pericolosita_idraulica",
}

_AREAS = frozenset({ITALY, *REGIONS.values(), *PROVINCES.values()})


@dataclass(frozen=True, slots=True)
class Dataset:
    """One downloadable file: its URL and the name it is saved under."""

    url: str
    filename: str

    @property
    def stem(self) -> str:
        """The file name without its archive suffix: also the extraction folder."""
        for suffix in (".json.zip", ".zip", ".csv.bz2"):
            if self.filename.endswith(suffix):
                return self.filename.removesuffix(suffix)
        return self.filename


def opendata(layer: Layer, area: str = ITALY, fmt: Format = "shapefile") -> Dataset:
    """An open-data download: a layer, for Italy (default) or one area.

    ``ValueError`` for an unknown layer or area.
    """
    if layer in LANDSLIDE_LAYERS:
        group = "frane"
    elif layer in EVENT_LAYERS:
        group = layer
    else:
        raise ValueError(f"unknown layer {layer!r}: one of {LANDSLIDE_LAYERS + EVENT_LAYERS}")
    if area not in _AREAS:
        raise ValueError(f"unknown area {area!r}: {ITALY!r}, a region or a province file name")
    suffix = ".json.zip" if fmt == "geojson" else ".zip"
    filename = f"{layer}_{area}_opendata{suffix}"
    return Dataset(url=f"{BASE_URL}/opendata/{group}/{filename}", filename=filename)


def mosaic(name: Mosaic) -> Dataset:
    """A national hazard mosaic (shapefile in a ZIP)."""
    try:
        stem = MOSAICS[name]
    except KeyError:
        raise ValueError(f"unknown mosaic {name!r}: one of {tuple(MOSAICS)}") from None
    filename = f"{stem}.zip"
    return Dataset(url=f"{BASE_URL}/opendata/wms/{filename}", filename=filename)


def sensor_data() -> Dataset:
    """The monitoring network's readings, one bzip2-compressed CSV."""
    filename = "idrogeo_sensor_data.csv.bz2"
    return Dataset(url=f"{BASE_URL}/opendata/monitoraggio/{filename}", filename=filename)


def region_area(cod_reg: int) -> str:
    """The file name of a region from its ISTAT code; ``KeyError`` for 4 or unknown."""
    return REGIONS[cod_reg]
