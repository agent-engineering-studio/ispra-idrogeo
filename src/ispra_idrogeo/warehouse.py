"""A local, indexed copy of IdroGEO layers: ``pip install "ispra-idrogeo[warehouse]"``.

    async with IdroGEO() as idrogeo:
        with Warehouse() as warehouse:
            await warehouse.sync(idrogeo, ["frane_piff", "pai_frane", "idraulica"])
            warehouse.query("SELECT nome_reg, count(*) AS n FROM frane_piff GROUP BY 1")
            warehouse.hazard_at(40.8205, 14.6297)        # Sarno: landslide P4
            warehouse.landslides_in(municipality=65135)  # Sarno: 53, by type

:meth:`Warehouse.sync` downloads each layer (only if changed, as
:meth:`~ispra_idrogeo.IdroGEO.fetch` does) and loads it into one DuckDB file,
``idrogeo.duckdb`` in the download folder, with an R-tree index on the
geometry. A layer is loaded again only when its download changed. Every table
is in EPSG:32632 (metres), whatever the source: the flood mosaic comes in
EPSG:3035 and is reprojected. Points in and out are latitude and longitude,
in that order, as in :meth:`~ispra_idrogeo.IdroGEO.hazard_at`.

For one point, :meth:`~ispra_idrogeo.IdroGEO.hazard_at` asks IdroGEO's map
service and needs no download; the warehouse is for working offline, for
many points or areas at once, and for SQL of your own.

The two hazard mosaics are CC BY-SA 4.0 (the rest of IdroGEO is CC BY 4.0):
:data:`SOURCES` holds the citation ISPRA asks for each one. Data derived from
them must be shared under the same licence. They are a national technical
mosaic, not the legally binding maps of the basin authorities.

Loading needs DuckDB's ``spatial`` extension, which DuckDB downloads once from
its extension repository the first time.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any

from ispra_idrogeo.cache import default_directory, read_validators
from ispra_idrogeo.client import IdroGEO
from ispra_idrogeo.errors import IdrogeoError
from ispra_idrogeo.sources import (
    EVENT_LAYERS,
    ITALY,
    LANDSLIDE_LAYERS,
    MOSAICS,
    Dataset,
    mosaic,
    opendata,
)

try:
    import duckdb
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        'ispra_idrogeo.warehouse needs the warehouse extra: pip install "ispra-idrogeo[warehouse]"'
    ) from exc

#: The coordinate system of every table.
CRS = "EPSG:32632"
#: The file name of the warehouse in the download folder.
FILENAME = "idrogeo.duckdb"
#: What every layer is published under, and how ISPRA asks to cite it.
SOURCES: dict[str, str] = {
    "pai_frane": (
        "ISPRA - Mosaicatura nazionale delle aree a pericolosità da frana PAI "
        "(v. 4.0 \u2013 2020-2021), https://idrogeo.isprambiente.it, CC BY-SA 4.0"
    ),
    "idraulica": (
        "ISPRA - Mosaicatura delle aree a pericolosità idraulica (v. 5.0 \u2013 2020), "
        "https://idrogeo.isprambiente.it, CC BY-SA 4.0"
    ),
    "iffi": (
        "ISPRA — IdroGEO, Inventario dei Fenomeni Franosi in Italia (IFFI), "
        "https://idrogeo.isprambiente.it, CC BY 4.0"
    ),
}
#: Said with every hazard answer.
DISCLAIMER = (
    "ISPRA's national mosaics are technical and scientific, updated every few "
    "years; the maps with legal value are those of the basin district "
    "authorities (and the provinces of Trento and Bolzano). Not a safety "
    "assessment of any site."
)
#: Landslide hazard classes, most severe first; AA are areas of attention.
LANDSLIDE_CLASSES = ("P4", "P3", "P2", "P1", "AA")
#: Flood hazard scenarios, most frequent first, by the prefix of their file.
FLOOD_CLASSES = {"HPH": "P3", "MPH": "P2", "LPH": "P1"}
#: Where each mosaic says its class.
_CLASS_FIELD = {"pai_frane": "per_fr_ita", "idraulica": "scenario"}
#: The coordinate system each layer is published in.
_SOURCE_CRS = {"idraulica": "EPSG:3035"}
#: Area codes come as decimals from the shapefiles; they are whole numbers.
_CODES = ("regione", "provincia", "comune")
_TABLE = re.compile(r"[a-z][a-z0-9_]*")


class Warehouse:
    """One DuckDB file with IdroGEO layers, indexed for spatial queries."""

    def __init__(self, path: Path | None = None, *, read_only: bool = False) -> None:
        """Open (or create) the warehouse; ``path`` defaults to the download folder.

        ``read_only`` lets several readers (an MCP server, notebooks) share
        the file while no one is syncing it, and shuts every door out of the
        database: no file, URL or other database can be read through it, so
        :meth:`query` is safe to hand to an agent.
        """
        self.path = path or default_directory() / FILENAME
        if read_only and not self.path.exists():
            raise IdrogeoError(f"no warehouse at {self.path}: run `idrogeo sync` first")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._db = duckdb.connect(str(self.path), read_only=read_only)
        except (duckdb.IOException, duckdb.ConnectionException) as exc:
            raise IdrogeoError(f"warehouse {self.path} is busy (a sync running?): {exc}") from exc
        if not _has_spatial(self._db):  # pragma: no cover - once per machine, needs the network
            self._db.execute("INSTALL spatial")
        self._db.execute("LOAD spatial")
        self._db.execute("SET geometry_always_xy = true")
        if read_only:  # no files, no URLs, no way back: queries see only these tables
            self._db.execute("SET enable_external_access = false")
            self._db.execute("SET lock_configuration = true")
        else:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS _layers ("
                "name VARCHAR PRIMARY KEY, area VARCHAR, version VARCHAR, rows BIGINT)"
            )

    def __enter__(self) -> Warehouse:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the DuckDB connection."""
        self._db.close()

    async def sync(
        self,
        idrogeo: IdroGEO,
        layers: Iterable[str] = ("frane_piff",),
        area: str = ITALY,
        directory: Path | None = None,
    ) -> dict[str, bool]:
        """Download ``layers`` (only if changed) and load the ones that changed.

        Layers: IFFI layers and events (``frane_piff``, ``frane_poly``, …,
        ``eventi``) for ``area``, or the mosaics ``pai_frane`` and
        ``idraulica`` (all of Italy). Each becomes a table of the same name; a
        layer synced for another area replaces it. Returns, for each layer,
        whether its table was (re)loaded.
        """
        loaded: dict[str, bool] = {}
        for name in layers:
            dataset = _dataset(name, area)
            folder = await idrogeo.fetch(dataset, directory)
            zipped = folder.parent / dataset.filename
            known = read_validators(zipped, dataset.url)
            version = f"{known.etag}|{known.last_modified}" if known else "unknown"
            table_area = ITALY if name in MOSAICS else area
            if self._layer(name) == (table_area, version):
                loaded[name] = False
                continue
            await asyncio.to_thread(self._load, name, folder, table_area, version)
            loaded[name] = True
        return loaded

    def layers(self) -> list[dict[str, Any]]:
        """The tables loaded: name, area, rows and the version of the download."""
        return self._rows("SELECT name, area, rows, version FROM _layers ORDER BY name")

    def hazard_at(self, lat: float, lon: float) -> dict[str, Any]:
        """Landslide (PAI) and flood hazard classes of a point (latitude, longitude).

        ``landslide`` is the most severe class found (P4 … P1, then AA),
        ``flood`` the most frequent scenario (P3 … P1); ``None`` means outside
        every mapped area. A mosaic not synced yet is listed in ``missing``.
        """
        x, y = self._project(lat, lon)
        answer: dict[str, Any] = {"lat": lat, "lon": lon, "missing": []}
        for name, order, key in (
            ("pai_frane", LANDSLIDE_CLASSES, "landslide"),
            ("idraulica", tuple(FLOOD_CLASSES.values()), "flood"),
        ):
            if not self._has(name):
                answer["missing"].append(name)
                continue
            found = {
                c
                for (c,) in self._db.execute(
                    f"SELECT DISTINCT class FROM {name} WHERE ST_Intersects(geom, ST_Point(?, ?))",
                    [x, y],
                ).fetchall()
            }
            classes = [c for c in order if c in found]
            answer[key] = classes[0] if classes else None
            answer[f"{key}_classes"] = classes
        answer["sources"] = [SOURCES[n] for n in ("pai_frane", "idraulica") if self._has(n)]
        answer["note"] = DISCLAIMER
        return answer

    def landslides_near(
        self,
        lat: float,
        lon: float,
        radius_m: float = 500,
        *,
        layer: str = "frane_piff",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """The landslides of ``layer`` within ``radius_m`` of a point, nearest first.

        Each row has the layer's fields, ``distance_m``, and the ``lon`` and
        ``lat`` of its point (or of the nearest point of a polygon).
        """
        if not 0 < radius_m <= 50_000:
            raise ValueError("radius_m must be more than 0 and at most 50,000")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        self._need(layer)
        x, y = self._project(lat, lon)
        box = ", ".join(
            str(float(v)) for v in (x - radius_m, y - radius_m, x + radius_m, y + radius_m)
        )
        point = f"ST_Point({float(x)}, {float(y)})"
        return self._rows(
            f"SELECT * EXCLUDE (geom, near), ST_X(near) AS lon, ST_Y(near) AS lat FROM ("
            f" SELECT *, round(ST_Distance(geom, {point}), 1) AS distance_m,"
            f" ST_Transform(ST_ClosestPoint(geom, {point}), '{CRS}', 'EPSG:4326') AS near"
            f" FROM {layer} WHERE ST_Intersects(geom, ST_MakeEnvelope({box}))"
            f") WHERE distance_m <= ? ORDER BY distance_m LIMIT ?",
            [radius_m, limit],
        )

    def landslides_in(
        self,
        *,
        region: int | None = None,
        province: int | None = None,
        municipality: int | None = None,
        layer: str = "frane_piff",
    ) -> dict[str, Any]:
        """The landslides of ``layer`` in an area (ISTAT codes), counted by type.

        The area comes from the fields IdroGEO puts on each landslide, so it
        works where the API's ``regione_2019`` is empty.
        """
        self._need(layer)
        where, params = [], []
        for field, code in (("regione", region), ("provincia", province), ("comune", municipality)):
            if code is not None:
                where.append(f"{field} = ?")
                params.append(code)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        by_type = self._rows(
            f"SELECT tipo_movim, nome_tipo, count(*) AS landslides FROM {layer} {clause}"
            " GROUP BY ALL ORDER BY landslides DESC, tipo_movim",
            params,
        )
        return {
            "landslides": sum(t["landslides"] for t in by_type),
            "by_type": by_type,
            "source": SOURCES["iffi"],
        }

    def query(
        self, sql: str, params: list[Any] | None = None, *, limit: int = 1000
    ) -> list[dict[str, Any]]:
        """The rows of one read-only ``SELECT`` (or ``WITH … SELECT``), at most ``limit``.

        Anything else (several statements, ``INSERT``, ``COPY``, ``ATTACH``…)
        raises ``ValueError``: this is the door for people and agents to ask
        their own questions, not to change the data. Open the warehouse with
        ``read_only=True`` before running SQL you did not write: only then are
        file and network functions (``read_csv``, ``ST_Read``…) shut off too.
        Geometry columns come back as WKT text, in the table's EPSG:32632.
        """
        statements = duckdb.extract_statements(sql)
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            raise ValueError("only one SELECT statement is allowed")
        if not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10,000")
        inner = f"SELECT * FROM ({statements[0].query})"
        try:
            columns = self._db.execute(f"{inner} LIMIT 0", params or []).description or []
            shapes = [_ident(c[0]) for c in columns if str(c[1]).startswith("GEOMETRY")]
            text = ", ".join(f"ST_AsText({c}) AS {c}" for c in shapes)
            replace = f" REPLACE ({text})" if shapes else ""
            return self._rows(f"SELECT *{replace} FROM ({inner}) LIMIT {int(limit)}", params)
        except duckdb.Error as exc:  # a typo, an unknown column, a door shut: say so
            raise ValueError(str(exc)) from exc

    def schema(self) -> dict[str, list[dict[str, str]]]:
        """Every loaded table and its columns, for whoever writes the SQL."""
        return {
            layer["name"]: [
                {"column": c, "type": t}
                for c, t, *_ in self._db.execute(f"DESCRIBE {layer['name']}").fetchall()
            ]
            for layer in self.layers()
        }

    # internals

    def _load(self, name: str, folder: Path, area: str, version: str) -> None:
        shapefiles = sorted(folder.rglob("*.shp"))
        if not shapefiles:
            raise IdrogeoError(f"no shapefile in {folder}")
        parts = [self._select(name, shp) for shp in shapefiles]
        with self._transaction():
            self._db.execute(
                f"CREATE OR REPLACE TABLE {name} AS {' UNION ALL BY NAME '.join(parts)}"
            )
            self._db.execute(f"CREATE INDEX {name}_geom ON {name} USING RTREE (geom)")
            (rows,) = self._db.execute(f"SELECT count(*) FROM {name}").fetchone() or (0,)
            self._db.execute(
                "INSERT OR REPLACE INTO _layers VALUES (?, ?, ?, ?)", [name, area, version, rows]
            )

    def _select(self, name: str, shp: Path) -> str:
        """The SELECT that reads one shapefile into the table's shape."""
        source = f"ST_Read('{_quote(shp)}'{_encoding(shp)})"
        columns = [c for c, *_ in self._db.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()]
        fields = [
            f"CAST({c} AS INTEGER) AS {c}" if c in _CODES else c
            for c in columns
            if c not in ("geom", "OGC_FID")
        ]
        crs = _SOURCE_CRS.get(name)
        geom = f"ST_Transform(geom, '{crs}', '{CRS}', always_xy := true)" if crs else "geom"
        fields.append(f"{geom}::GEOMETRY AS geom")
        if name == "idraulica":
            prefix = shp.name[:3].upper()
            if prefix not in FLOOD_CLASSES:
                raise IdrogeoError(f"unexpected flood scenario file {shp.name}")
            fields.append(f"'{FLOOD_CLASSES[prefix]}' AS class")
        elif name == "pai_frane":
            fields.append(f"regexp_extract(trim({_CLASS_FIELD[name]}), '(P[1-4]|AA)$', 1) AS class")
        return f"SELECT {', '.join(fields)} FROM {source}"

    def _project(self, lat: float, lon: float) -> tuple[float, float]:
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("give latitude and longitude in degrees (EPSG:4326)")
        row = self._db.execute(
            f"SELECT ST_X(p), ST_Y(p) FROM "
            f"(SELECT ST_Transform(ST_Point(?, ?), 'EPSG:4326', '{CRS}') AS p)",
            [lon, lat],
        ).fetchone()
        assert row is not None
        return float(row[0]), float(row[1])

    def _layer(self, name: str) -> tuple[str, str] | None:
        row = self._db.execute(
            "SELECT area, version FROM _layers WHERE name = ?", [name]
        ).fetchone()
        return (str(row[0]), str(row[1])) if row else None

    def _has(self, name: str) -> bool:
        try:
            return self._layer(name) is not None
        except duckdb.CatalogException:  # a read-only file nothing was synced into
            return False

    def _need(self, name: str) -> None:
        if not _TABLE.fullmatch(name) or not self._has(name):
            raise IdrogeoError(f"layer {name!r} is not in the warehouse: run `idrogeo sync {name}`")

    def _rows(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        cursor = self._db.execute(sql, params or [])
        names = [d[0] for d in cursor.description or []]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._db.execute("BEGIN TRANSACTION")
        try:
            yield
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        self._db.execute("COMMIT")


def _dataset(name: str, area: str) -> Dataset:
    if name in MOSAICS:
        return mosaic(name)
    if name in (*LANDSLIDE_LAYERS, *EVENT_LAYERS):
        return opendata(name, area)
    raise ValueError(
        f"unknown layer {name!r}: one of {(*LANDSLIDE_LAYERS, *EVENT_LAYERS, *MOSAICS)}"
    )


def _has_spatial(db: duckdb.DuckDBPyConnection) -> bool:
    row = db.execute(
        "SELECT installed FROM duckdb_extensions() WHERE extension_name = 'spatial'"
    ).fetchone()
    return bool(row and row[0])


def _encoding(shp: Path) -> str:
    """The ST_Read option for the text encoding the ``.cpg`` or ``.cst`` file names.

    IdroGEO ships ``.cst`` files (``ISO-8859-1``), which GDAL does not read.
    """
    for suffix in (".cpg", ".cst"):
        found = shp.with_suffix(suffix)
        if found.is_file():
            name = found.read_text(encoding="ascii", errors="ignore").strip()
            if re.fullmatch(r"[A-Za-z0-9_.:-]+", name):
                return f", open_options = ['ENCODING={name}']"
    return ""


def _ident(name: str) -> str:
    """A column name as a quoted SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def _quote(path: Path) -> str:
    return str(path).replace("'", "''")
