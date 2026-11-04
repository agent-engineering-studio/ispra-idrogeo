"""What IdroGEO's public map service says about a point.

IdroGEO's GeoServer publishes its layers over WMS to anyone (the WFS asks
for a login). A ``GetFeatureInfo`` request asks what is under a pixel, and
with a tiny bounding box around a point that pixel is the point: one call
answers the PAI landslide hazard class, the flood scenarios, the
municipality, the lithology and the slope there. With a box of a few
hundred metres and a wide ``buffer``, the same request lists the IFFI
landslides around the point, with their geometry.

Pure functions: :func:`point_params` / :func:`area_params` build the
request, :func:`parse_hazard` and :func:`nearby` read the answer.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ispra_idrogeo.sources import BASE_URL

WMS_URL = f"{BASE_URL}/geoserver/wms"

#: The layers :func:`point_params` asks about, one answer each.
HAZARD_LAYERS = (
    "idrogeo:pericolosita_frane",
    "idrogeo:pericolosita_alluvioni",
    "idrogeo:comuni_2019",
    "idrogeo:slope10",
)
#: The 1:100,000 lithology: asked only on request, it takes ~16 s to answer
#: where the other layers take under one.
LITHOLOGY_LAYER = "idrogeo:idrogeo_litologia_100k"

#: The IFFI layers :func:`area_params` searches, and what each one holds.
LANDSLIDE_SHAPES = {
    "idrogeo:frane_poly_opendata": "polygon",
    "idrogeo:frane_line_opendata": "line",
    "idrogeo:frane_piff_opendata": "point",
    "idrogeo:aree_poly_opendata": "diffuse area",
    "idrogeo:dgpv_poly_opendata": "deep-seated deformation",
}

#: PAI landslide hazard classes by ``cod_per_it``, as the layer's legend says.
LANDSLIDE_CLASSES = {4: "P4", 3: "P3", 2: "P2", 1: "P1", 0: "AA"}
_LANDSLIDE_RANK = ("AA", "P1", "P2", "P3", "P4")
_EARTH_M = 6_371_008.8
_HALF_PIXEL_DEG = 0.00001  # ~1 m: the box whose middle pixel is the point


@dataclass(frozen=True, slots=True)
class PointHazard:
    """The hazard and context of one point; ``None`` where a layer has nothing.

    ``landslide`` is the highest PAI class there (``"P4"`` very high to
    ``"P1"`` moderate, ``"AA"`` attention area). ``flood`` is the most
    frequent flood scenario that reaches the point (``"P3"`` high
    probability, ``"P2"`` medium, ``"P1"`` low); ``flood_scenarios`` all of
    them. ``slope_deg`` is the slope in degrees. ``lithology`` is filled
    only when asked for.
    """

    lat: float
    lon: float
    landslide: str | None
    flood: str | None
    flood_scenarios: tuple[str, ...]
    municipality: int | None
    municipality_name: str | None
    province: int | None
    region: int | None
    lithology: str | None
    lithology_code: str | None
    slope_deg: float | None


def _check(lat: float, lon: float) -> None:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"({lat}, {lon}) is not a latitude and longitude in degrees")


def point_params(lat: float, lon: float, *, lithology: bool = False) -> dict[str, str]:
    """The ``GetFeatureInfo`` query asking :data:`HAZARD_LAYERS` about a point.

    ``lithology`` adds :data:`LITHOLOGY_LAYER`, much slower to answer.
    """
    _check(lat, lon)
    d = _HALF_PIXEL_DEG
    layers = (*HAZARD_LAYERS, LITHOLOGY_LAYER) if lithology else HAZARD_LAYERS
    return _feature_info(layers, (lat - d, lon - d, lat + d, lon + d), 20, 0)


def area_params(lat: float, lon: float, radius_m: float, limit: int) -> dict[str, str]:
    """The query listing the IFFI landslides within a square around a point."""
    _check(lat, lon)
    if not 0 < radius_m <= 5000:
        raise ValueError("radius_m must be more than 0 and at most 5,000 m")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    dlat = math.degrees(radius_m / _EARTH_M)
    dlon = dlat / max(math.cos(math.radians(lat)), 1e-6)
    box = (lat - dlat, lon - dlon, lat + dlat, lon + dlon)
    # The middle pixel of a 101-pixel image, widened by 50 pixels on each side,
    # covers the whole box.
    return _feature_info(tuple(LANDSLIDE_SHAPES), box, limit, 50)


def _feature_info(
    layers: Iterable[str], box: tuple[float, float, float, float], count: int, buffer: int
) -> dict[str, str]:
    names = ",".join(layers)
    params = {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetFeatureInfo",
        "layers": names,
        "query_layers": names,
        "crs": "EPSG:4326",  # WMS 1.3.0: the box is lat,lon
        "bbox": ",".join(f"{v:.7f}" for v in box),
        "width": "101",
        "height": "101",
        "i": "50",
        "j": "50",
        "info_format": "application/json",
        "feature_count": str(count),
    }
    if buffer:
        params["buffer"] = str(buffer)
    return params


def parse_hazard(lat: float, lon: float, features: Iterable[Mapping[str, Any]]) -> PointHazard:
    """Read the answer to :func:`point_params`.

    Each layer is told apart by its fields, not by the feature ids, which
    the slope layer leaves empty.
    """
    landslide: str | None = None
    scenarios: set[str] = set()
    area: Mapping[str, Any] = {}
    rock: Mapping[str, Any] = {}
    slope: float | None = None
    for feature in features:
        props = feature.get("properties") or {}
        if "cod_per_it" in props:
            code = _int(props["cod_per_it"])
            found = None if code is None else LANDSLIDE_CLASSES.get(code)
            if found and (landslide is None or _rank(found) > _rank(landslide)):
                landslide = found
        elif any(k.startswith("scenariop") for k in props):
            scenarios.update(f"P{k[-1]}" for k in props if k.startswith("scenariop"))
        elif "pro_com" in props:
            area = props
        elif "titolo_eng" in props:
            rock = props
        elif "acclivita" in props and props["acclivita"] is not None:
            value = float(props["acclivita"])
            slope = round(value, 1) if value >= 0 else None  # -9999: no data (sea)
    ordered = tuple(sorted(scenarios, reverse=True))
    return PointHazard(
        lat=lat,
        lon=lon,
        landslide=landslide,
        flood=ordered[0] if ordered else None,
        flood_scenarios=ordered,
        municipality=_int(area.get("pro_com")),
        municipality_name=area.get("comune"),
        province=_int(area.get("cod_prov")),
        region=_int(area.get("cod_reg")),
        lithology=rock.get("titolo_eng") or rock.get("titolo_ita"),
        lithology_code=rock.get("code"),
        slope_deg=slope,
    )


def nearby(
    lat: float, lon: float, features: Iterable[Mapping[str, Any]], radius_m: float
) -> list[dict[str, Any]]:
    """The landslides of an :func:`area_params` answer within ``radius_m``, nearest first.

    One row per ``id_frana``: its fields, ``distance_m`` (0 inside a polygon)
    and ``shapes``, the kinds of shape it is mapped as.
    """
    found: dict[str, dict[str, Any]] = {}
    for feature in features:
        props = dict(feature.get("properties") or {})
        geometry = feature.get("geometry")
        key = str(props.get("id_frana") or feature.get("id") or "")
        if not key or not geometry:
            continue
        distance = distance_m(lat, lon, geometry)
        if distance > radius_m:
            continue
        shape = LANDSLIDE_SHAPES.get(f"idrogeo:{str(feature.get('id', '')).split('.')[0]}")
        row = found.setdefault(key, {**props, "distance_m": distance, "shapes": []})
        row["distance_m"] = min(row["distance_m"], distance)
        if shape and shape not in row["shapes"]:
            row["shapes"].append(shape)
    for row in found.values():
        row["distance_m"] = round(row["distance_m"], 1)
    return sorted(found.values(), key=lambda r: r["distance_m"])


def distance_m(lat: float, lon: float, geometry: Mapping[str, Any]) -> float:
    """Metres from a point to a GeoJSON geometry in lon/lat; 0 inside a polygon.

    A local flat projection around the point: within a few kilometres the
    error is far below the precision of the maps.
    """
    scale = math.radians(1) * _EARTH_M
    cos = math.cos(math.radians(lat))

    def xy(position: Any) -> tuple[float, float]:
        return ((position[0] - lon) * scale * cos, (position[1] - lat) * scale)

    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "Point":
        return math.hypot(*xy(coords))
    if kind == "MultiPoint":
        return min((math.hypot(*xy(p)) for p in coords), default=math.inf)
    if kind == "LineString":
        return _to_line([xy(p) for p in coords])
    if kind == "MultiLineString":
        return min((_to_line([xy(p) for p in line]) for line in coords), default=math.inf)
    if kind == "Polygon":
        coords = [coords]
    elif kind != "MultiPolygon":
        return math.inf
    best = math.inf
    for polygon in coords:
        rings = [[xy(p) for p in ring] for ring in polygon]
        if rings and _inside(rings[0]) and not any(_inside(hole) for hole in rings[1:]):
            return 0.0
        best = min([best, *(_to_line(ring) for ring in rings)])
    return best


def _to_line(points: list[tuple[float, float]]) -> float:
    """Distance from the origin to a polyline."""
    if len(points) == 1:
        return math.hypot(*points[0])
    best = math.inf
    for (ax, ay), (bx, by) in itertools.pairwise(points):
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length))
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def _inside(ring: list[tuple[float, float]]) -> bool:
    """Whether the origin is inside a ring (even-odd rule)."""
    inside = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1], strict=True):
        if (ay > 0) != (by > 0) and ax + (0 - ay) * (bx - ax) / (by - ay) > 0:
            inside = not inside
    return inside


def _rank(code: str) -> int:
    return _LANDSLIDE_RANK.index(code)


def _int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None
