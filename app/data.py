"""What the page shows, read through the library: no rain, no alert.

:class:`Data` answers the page's questions about one municipality: the
panel (predisposition classes, exposure, IFFI, how far to trust, sources),
the layers as GeoJSON (PAI 2024 polygons and IFFI points from the local
warehouse, dated landslides from the library), the state of the contract
with IdroGEO, and downloads. Answers are kept in memory for a while, so a
page opened by many people asks IdroGEO once.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ispra_idrogeo import LANDSLIDE_FIELDS, IdroGEO, mosaic
from ispra_idrogeo.dated import DatedLandslide, dated_landslides
from ispra_idrogeo.grounding import SOURCES
from ispra_idrogeo.predisposition import ITALIAN, predisposition
from ispra_idrogeo.reliability import reliability

#: The layers the page loads into its warehouse at start.
LAYERS = ("frane_piff", "pai_frane_2024")
#: Exposure figures shown in the panel: (key, label).
EXPOSURE = (
    ("pop_res021", "Residenti (censimento 2021)"),
    ("popfr_p3p4", "Residenti in pericolo frana P3+P4"),
    ("popfrp3p4p", "… in % dei residenti"),
    ("pop_idr_p2", "Residenti in pericolo alluvione P2"),
    ("popidp2_p", "… in % dei residenti"),
    ("ed_fr_p3p4", "Edifici in pericolo frana P3+P4"),
    ("ed_idr_p2", "Edifici in pericolo alluvione P2"),
    ("bbccfrp3p4", "Beni culturali in pericolo frana P3+P4"),
    ("bbcc_id_p2", "Beni culturali in pericolo alluvione P2"),
)
CITATIONS = {
    "pai_2024": (
        "ISPRA - Mosaicatura nazionale delle aree a pericolosità da frana PAI (v. 5.0 - 2024) - "
        "Piattaforma IdroGEO https://idrogeo.isprambiente.it, CC BY 4.0"
    ),
    "flood": SOURCES["hazard"],
    "iffi": SOURCES["iffi"],
    "events": SOURCES["events"],
    "indicators": SOURCES["indicators"],
    "boundaries": "ISTAT, confini comunali 2019, dal servizio WMS di IdroGEO",
}
SARNO = (40.829, 14.617)


class Cache:
    """Answers kept for ``ttl`` seconds, one computation at a time per key."""

    def __init__(self, ttl: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl, self._clock = ttl, clock
        self._kept: dict[Any, tuple[float, Any]] = {}
        self._locks: dict[Any, asyncio.Lock] = {}

    async def get(self, key: Any, make: Callable[[], Awaitable[Any]]) -> Any:
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            kept = self._kept.get(key)
            if kept and self._clock() - kept[0] < self.ttl:
                return kept[1]
            value = await make()
            self._kept[key] = (self._clock(), value)
            return value


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def region_of(summary: dict[str, Any]) -> int | None:
    """The ISTAT region code from a summary's breadcrumb."""
    for crumb in summary.get("breadcrumb") or []:
        if crumb.get("t") == "r":
            return int(crumb["id"])
    return None


#: The predisposition classes, said in Italian for the page.
MEASURES_IT = {
    "landslide": "quota di territorio in pericolo frana P3+P4 (mappa PAI 2024)",
    "flood": "quota di territorio nello scenario di alluvione P2 (tempo di ritorno 100-200 anni)",
}
RULE_IT = "nessuna 0% · bassa <5% · media 5-15% · alta 15-30% · molto alta ≥30%"
NOTE_IT = (
    "È una classe di predisposizione calcolata sulle mappe ufficiali di pericolo, non "
    "un'allerta: non usa la pioggia. Per le allerte valgono i bollettini della Protezione "
    "Civile e della Regione."
)


def panel(
    code: int, pir: dict[str, Any], iffi: dict[str, Any], types: dict[str, str]
) -> dict[str, Any]:
    """Everything the side panel shows for one municipality."""
    classes = predisposition(pir)
    return {
        "code": code,
        "name": pir.get("nome") or iffi.get("nome"),
        "extent": pir.get("extent") or iffi.get("extent"),
        "region": region_of(iffi) or region_of(pir),
        "breadcrumb": [c.get("name") for c in iffi.get("breadcrumb") or []],
        "predisposition": {
            kind: {
                **c.as_dict(),
                "label": ITALIAN[c.step] if c.step else "non disponibile",
                "measures": MEASURES_IT[kind],
                "rule": RULE_IT,
                "note": NOTE_IT,
            }
            for kind, c in classes.items()
        },
        "exposure": [
            {"key": key, "label": label, "value": _value(pir.get(key))} for key, label in EXPOSURE
        ],
        "iffi": {
            "landslides": iffi.get("frane_totali"),
            "by_type": sorted(
                (
                    {
                        "type": types.get(str(s.get("cod")), str(s.get("cod"))),
                        "n": s.get("nr_frane"),
                    }
                    for s in iffi.get("frane_stats") or []
                    if s.get("nr_frane")
                ),
                key=lambda t: -int(t["n"]),
            ),
            "events": iffi.get("eventi_totali"),
            "monitored": iffi.get("frane_monitorate"),
            "monitoring_sites": iffi.get("siti_monitoraggio_totali"),
        },
        "reliability": _reliability_it(code),
        "citations": CITATIONS,
        "retrieved_at": _now(),
    }


NOT_MEASURED_IT = (
    "la precisione delle posizioni IFFI: ogni record dice «esatta»",
    "quanto è completo l'inventario: non c'è un riferimento con cui confrontarlo",
    "se un evento e una frana IFFI sono la stessa frana",
    "l'anno in cui ogni Regione ha rilevato le sue frane: ISPRA non lo pubblica",
)


def _n(value: int) -> str:
    """A whole number with the Italian thousands separator: 1.234."""
    return f"{value:,}".replace(",", ".")


def _pct(share: float | None) -> str:
    if share is None:
        return "non disponibile"
    value = share * 100
    return "meno dello 0,1%" if 0 < value < 0.1 else f"{value:.1f}%".replace(".", ",")


def notes_it(found: dict[str, Any]) -> list[str]:
    """The notes of :func:`~ispra_idrogeo.reliability.reliability`, in Italian."""
    landslides = found["landslides"]
    if not landslides:
        notes = ["In questo Comune IFFI non censisce nessuna frana."]
    else:
        day = round((found["day_share"] or 0) * landslides)
        edited = _pct(found["edited_since_2021_share"])
        notes = [
            f"{_n(day)} frane IFFI su {_n(landslides)} ({_pct(found['day_share'])}) hanno una "
            "data al giorno.",
            f"Record IFFI modificati dal 2021: {edited}.",
        ]
    if found["dated_since_2018"]:
        notes.append(
            f"Dal 2018: {found['iffi_day_since_2018']} frane IFFI datate al giorno e "
            f"{found['events_since_2018']} eventi, {found['events_within_1km']} con il punto "
            "noto entro 1 km."
        )
    else:
        notes.append(
            "Nessuna frana datata al giorno dal 2018: qui nessun dato può verificare una soglia "
            "di pioggia."
        )
    return notes


def _value(value: Any) -> Any:
    """``None`` for IdroGEO's "not available" (-1)."""
    return None if isinstance(value, int | float) and value < 0 else value


def _reliability_it(code: int) -> dict[str, Any] | None:
    try:
        found = reliability("comuni", code).as_dict()
    except ValueError:  # a municipality the shipped table does not know
        return None
    return {**found, "notes": notes_it(found), "not_measured": list(NOT_MEASURED_IT)}


def feature(geometry: dict[str, Any], properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def dated_features(found: list[DatedLandslide], code: int) -> list[dict[str, Any]]:
    """The dated landslides of one municipality as GeoJSON features."""
    return [
        feature(
            {"type": "Point", "coordinates": [d.lon, d.lat]},
            {**d.as_dict(), "layer": "dated", "citation": d.citation},
        )
        for d in found
        if d.municipality == code and d.lon is not None and d.lat is not None
    ]


class UnavailableError(Exception):
    """A layer that is not ready (the warehouse is still loading, or failed)."""


class Data:
    """The page's questions, answered with the library and kept in memory."""

    def __init__(self, idrogeo: IdroGEO, warehouse: Path | None = None) -> None:
        self.idrogeo = idrogeo
        self.warehouse = warehouse
        self.state: dict[str, Any] = {"warehouse": "not started", "layers": {}}
        self._day = Cache(24 * 3600)
        self._hour = Cache(3600)
        self._reader: Any = None
        self._reading = threading.Lock()  # one DuckDB connection, one query at a time

    # the warehouse, loaded once in the background

    async def load_warehouse(self, layers: tuple[str, ...] = LAYERS) -> None:
        """Download (if changed) and load the layers; the page shows the state."""
        from ispra_idrogeo.warehouse import Warehouse

        self.state["warehouse"] = "loading"
        try:
            with Warehouse(self.warehouse) as opened:
                for name in layers:
                    self.state["layers"][name] = "loading"
                    await opened.sync(self.idrogeo, [name])
                    self.state["layers"][name] = "ready"
            self.state["warehouse"] = "ready"
        except Exception as exc:  # shown on the page, never fatal
            self.state["warehouse"] = f"failed: {exc}"

    def _query(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        from ispra_idrogeo.warehouse import Warehouse

        if self.state["warehouse"] != "ready":
            raise UnavailableError(f"warehouse {self.state['warehouse']}")
        with self._reading:
            if self._reader is None:
                self._reader = Warehouse(self.warehouse, read_only=True)
            rows: list[dict[str, Any]] = self._reader.query(sql, params, limit=10_000)
            return rows

    # the page's questions

    async def municipalities(self) -> list[dict[str, Any]]:
        async def make() -> list[dict[str, Any]]:
            rows = await self.idrogeo.summary("iffi", "comuni")
            return [{"code": int(r["uid"]), "name": str(r["nome"])} for r in rows]

        found: list[dict[str, Any]] = await self._day.get("municipalities", make)
        return found

    async def find(self, text: str, limit: int = 10) -> list[dict[str, Any]]:
        from ispra_idrogeo.mcp_server import _fold

        wanted = _fold(text)
        found = [m for m in await self.municipalities() if wanted in _fold(m["name"])]
        found.sort(
            key=lambda m: (
                _fold(m["name"]) != wanted,
                not _fold(m["name"]).startswith(wanted),
                m["name"],
            )
        )
        return found[:limit]

    async def panel(self, code: int) -> dict[str, Any]:
        async def make() -> dict[str, Any]:
            pir, iffi, types = await asyncio.gather(
                self.idrogeo.summary("pir", "comuni", code),
                self.idrogeo.summary("iffi", "comuni", code),
                self.idrogeo.labels("tipo_movimento", "it"),
            )
            return panel(code, pir, iffi, types)

        found: dict[str, Any] = await self._day.get(("panel", code), make)
        return found

    async def landslides(self, code: int) -> dict[str, Any]:
        """The IFFI points of a municipality, from the warehouse."""
        rows = await asyncio.to_thread(
            self._query,
            "SELECT id_frana, nome_tipo, ST_AsGeoJSON(ST_Transform(geom, 'EPSG:32632', "
            "'EPSG:4326')) AS shape FROM frane_piff WHERE comune = ?",
            [code],
        )
        features = [
            feature(
                json.loads(r["shape"]),
                {
                    "id_frana": r["id_frana"],
                    "type": r["nome_tipo"],
                    "layer": "iffi",
                    "citation": CITATIONS["iffi"],
                },
            )
            for r in rows
        ]
        return {"type": "FeatureCollection", "features": features, "truncated": len(rows) >= 10_000}

    async def hazard(self, code: int) -> dict[str, Any]:
        """The PAI 2024 polygons crossing the municipality's box, simplified to 5 m."""
        extent = (await self.panel(code))["extent"]
        if not extent:
            raise UnavailableError("no extent for this municipality")
        (west, south), (east, north) = extent
        rows = await asyncio.to_thread(
            self._query,
            "WITH box AS (SELECT ST_Transform(ST_MakeEnvelope(?, ?, ?, ?), 'EPSG:4326', "
            "'EPSG:32632') AS b) SELECT class, ST_AsGeoJSON(ST_Transform(ST_Simplify(geom, 5), "
            "'EPSG:32632', 'EPSG:4326')) AS shape FROM pai_frane_2024, box "
            "WHERE ST_Intersects(geom, b)",
            [west, south, east, north],
        )
        features = [
            feature(
                json.loads(r["shape"]),
                {
                    "class": r["class"],
                    "layer": "pai_2024",
                    "citation": CITATIONS["pai_2024"],
                },
            )
            for r in rows
        ]
        return {"type": "FeatureCollection", "features": features, "truncated": len(rows) >= 10_000}

    async def dated(self, code: int) -> dict[str, Any]:
        """The dated landslides of a municipality, with their precision."""
        region = (await self.panel(code))["region"]

        async def make() -> list[DatedLandslide]:
            return await dated_landslides(self.idrogeo, region=region)

        found: list[DatedLandslide] = await self._hour.get(("dated", region), make)
        return {"type": "FeatureCollection", "features": dated_features(found, code)}

    async def contract(self) -> dict[str, Any]:
        """A live check that the calls the page and Limen use still work (the lesson of #9)."""

        async def check(name: str, run: Callable[[], Awaitable[bool]]) -> dict[str, Any]:
            try:
                ok = await run()
                return {"name": name, "ok": ok, "detail": "" if ok else "risposta inattesa"}
            except Exception as exc:  # any failure is the answer
                return {"name": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"[:200]}

        async def search() -> bool:
            rows = await self.idrogeo.search_landslides(limit=1)
            return bool(rows) and set(LANDSLIDE_FIELDS) <= rows[0].keys()

        async def summary() -> bool:
            return int((await self.idrogeo.summary("iffi", "italia"))["frane_totali"]) > 700_000

        async def point() -> bool:
            return (await self.idrogeo.hazard_at(*SARNO)).landslide == "P4"

        async def files() -> bool:
            return (await self.idrogeo.head(mosaic("pai_frane_2024"))).size is not None

        async def make() -> dict[str, Any]:
            checks = await asyncio.gather(
                check("Ricerca delle frane (campi espliciti, #9)", search),
                check("Conteggi IFFI dell'Italia", summary),
                check("Pericolo in un punto (WMS): Sarno è P4", point),
                check("File della mappa PAI 2024", files),
            )
            return {"checked_at": _now(), "ok": all(c["ok"] for c in checks), "checks": checks}

        found: dict[str, Any] = await self._hour.get("contract", make)
        return found

    async def csv_of(self, code: int) -> str:
        """The panel's figures as CSV, with sources and licences."""
        found = await self.panel(code)
        out = io.StringIO()
        write = csv.writer(out)
        write.writerow(["voce", "valore", "fonte"])
        for kind, c in found["predisposition"].items():
            write.writerow(
                [f"predisposizione {kind} (non è un'allerta)", c["label"], c["measures"]]
            )
        for item in found["exposure"]:
            write.writerow([item["label"], item["value"], CITATIONS["indicators"]])
        write.writerow(["Frane IFFI", found["iffi"]["landslides"], CITATIONS["iffi"]])
        for item in found["iffi"]["by_type"]:
            write.writerow([f"Frane IFFI: {item['type']}", item["n"], CITATIONS["iffi"]])
        for note in found["reliability"]["notes"]:
            write.writerow(
                ["Quanto fidarsi", note, f"reliability {found['reliability']['built_on']}"]
            )
        write.writerow(["Letto il", found["retrieved_at"], "https://idrogeo.isprambiente.it"])
        return out.getvalue()
