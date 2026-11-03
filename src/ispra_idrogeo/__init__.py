"""ISPRA IdroGEO: IFFI landslide inventory, hazard mosaics and events.

Pure URL builders (:mod:`~ispra_idrogeo.sources`), API requests and parsers
(:mod:`~ispra_idrogeo.api`), a persistent download folder with conditional
GETs (:mod:`~ispra_idrogeo.cache`) and an async client over them.
"""

from importlib.metadata import version

from ispra_idrogeo.api import (
    API_URL,
    CODE_FIELDS,
    Level,
    Summary,
    level_codes,
    parse,
    parse_list,
    search_params,
    since_filter,
    summary_path,
)
from ispra_idrogeo.cache import (
    ENV_DATA_DIR,
    Validators,
    default_directory,
    extract,
    read_json,
    read_validators,
    write_json,
    write_validators,
)
from ispra_idrogeo.client import Download, IdroGEO
from ispra_idrogeo.codes import CODE_DICTIONARIES, Language, decode, parse_labels
from ispra_idrogeo.errors import IdrogeoError
from ispra_idrogeo.filters import event_filter, landslide_filter, site_filter
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
    "CODE_DICTIONARIES",
    "CODE_FIELDS",
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
    "Language",
    "Layer",
    "Level",
    "Mosaic",
    "Summary",
    "Validators",
    "__version__",
    "decode",
    "default_directory",
    "event_filter",
    "extract",
    "landslide_filter",
    "level_codes",
    "mosaic",
    "opendata",
    "parse",
    "parse_labels",
    "parse_list",
    "read_json",
    "read_validators",
    "region_area",
    "search_params",
    "sensor_data",
    "since_filter",
    "site_filter",
    "summary_path",
    "write_json",
    "write_validators",
]
