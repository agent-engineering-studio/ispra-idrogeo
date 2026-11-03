"""IdroGEO data as GeoDataFrames: ``pip install "ispra-idrogeo[geo]"``.

:func:`read` opens what :meth:`~ispra_idrogeo.IdroGEO.fetch` unpacked;
:func:`frame` turns API rows (landslides, events, sites, webcams) into a
frame in the right coordinate system; :func:`add_labels` adds the words of
the coded columns. ``frame.to_parquet(path)`` writes GeoParquet.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

from ispra_idrogeo.codes import _key

try:
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import Point, shape
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        'ispra_idrogeo.geo needs the geo extra: pip install "ispra-idrogeo[geo]"'
    ) from exc

#: The coordinate system of each geometry field in the API rows.
#: ``point`` is longitude and latitude everywhere; ``geom`` says its own,
#: and :func:`frame` reads it from the first row.
Geometry = Literal["point", "geom", "geom_polygon", "geom_linestring"]

_SUFFIXES = (".shp", ".geojson", ".json")


def read(path: Path, **kwargs: Any) -> Any:
    """A file or an unpacked folder (from ``fetch``) as a GeoDataFrame.

    A folder must hold exactly one shapefile or GeoJSON. ``kwargs`` go to
    :func:`geopandas.read_file` (``bbox=``, ``columns=``, ``rows=``…).
    """
    if path.is_dir():
        found = sorted(p for p in path.rglob("*") if p.suffix.lower() in _SUFFIXES)
        if len(found) != 1:
            names = [p.name for p in found] or "none"
            raise ValueError(f"{path} must hold one shapefile or GeoJSON, found {names}")
        path = found[0]
    return gpd.read_file(path, **kwargs)


def frame(rows: Iterable[Mapping[str, Any]], geometry: Geometry = "point") -> Any:
    """API rows as a GeoDataFrame, geometry from ``geometry``.

    ``"point"`` is ``[lon, lat]`` (EPSG:4326): landslides, sites. The
    GeoJSON fields (``"geom"``, ``"geom_polygon"``, ``"geom_linestring"``)
    carry their own CRS: EPSG:32632 for landslides, EPSG:3857 for webcams.
    Rows without that geometry get an empty one rather than being dropped.
    """
    records = [dict(r) for r in rows]
    crs: str | None = "EPSG:4326" if geometry == "point" else None
    shapes: list[Any] = []
    for row in records:
        value = row.pop(geometry, None)
        if not value:
            shapes.append(None)
        elif geometry == "point":
            shapes.append(Point(value[0], value[1]))
        else:
            crs = crs or value.get("crs", {}).get("properties", {}).get("name")
            shapes.append(shape(value))
    return gpd.GeoDataFrame(records, geometry=shapes, crs=crs)


def add_labels(data: Any, labels: Mapping[str, Mapping[str, str]]) -> Any:
    """``data`` with a ``<column>_label`` next to each coded column in ``labels``.

    ``labels`` comes from :meth:`~ispra_idrogeo.IdroGEO.code_labels`; lists of
    codes become lists of labels, unknown codes ``None``.
    """
    out = data.copy()
    for column, words in labels.items():
        if column in out.columns:
            # dtype=object: pandas 3 would store text as `str` and None as NaN.
            found = [_label(v, words) for v in out[column]]
            out[f"{column}_label"] = pd.Series(found, index=out.index, dtype=object)
    return out


def _label(value: Any, words: Mapping[str, str]) -> Any:
    if isinstance(value, list):
        return [words.get(_key(v)) for v in value]
    if value is None or value == "" or value != value:  # None, empty, NaN
        return None
    return words.get(_key(value))
