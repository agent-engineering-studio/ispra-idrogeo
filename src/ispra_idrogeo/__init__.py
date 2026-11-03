"""ISPRA IdroGEO: IFFI landslide inventory, hazard mosaics and events.

Pure URL builders (:mod:`~ispra_idrogeo.sources`), API requests and parsers
(:mod:`~ispra_idrogeo.api`), a persistent download folder with conditional
GETs (:mod:`~ispra_idrogeo.cache`) and an async client over them.
"""

from importlib.metadata import version

from ispra_idrogeo.api import (
    API_URL,
    Level,
    Summary,
    parse,
    parse_list,
    search_params,
    summary_path,
)
from ispra_idrogeo.cache import (
    ENV_DATA_DIR,
    Validators,
    default_directory,
    extract,
    read_validators,
    write_validators,
)
from ispra_idrogeo.client import Download, IdroGEO
from ispra_idrogeo.errors import IdrogeoError
from ispra_idrogeo.sources import (
    BASE_URL,
    EVENT_LAYERS,
    ITALY,
    LANDSLIDE_LAYERS,
    MOSAICS,
    PROVINCES,
    REGIONS,
    Dataset,
    EventLayer,
    Format,
    LandslideLayer,
    Layer,
    Mosaic,
    mosaic,
    opendata,
    region_area,
    sensor_data,
)

__version__ = version("ispra-idrogeo")

__all__ = [
    "API_URL",
    "BASE_URL",
    "ENV_DATA_DIR",
    "EVENT_LAYERS",
    "ITALY",
    "LANDSLIDE_LAYERS",
    "MOSAICS",
    "PROVINCES",
    "REGIONS",
    "Dataset",
    "Download",
    "EventLayer",
    "Format",
    "IdroGEO",
    "IdrogeoError",
    "LandslideLayer",
    "Layer",
    "Level",
    "Mosaic",
    "Summary",
    "Validators",
    "__version__",
    "default_directory",
    "extract",
    "mosaic",
    "opendata",
    "parse",
    "parse_list",
    "read_validators",
    "region_area",
    "search_params",
    "sensor_data",
    "summary_path",
    "write_validators",
]
