"""The methods the benchmark compares: the library, and a trivial one that must fail.

A method answers each kind of check. ``ispra-idrogeo`` uses the library as a
user would; ``constant`` gives the same answer everywhere (P4, P3, nothing
counted, a search with IdroGEO's default fields), so every check is shown to
tell a right answer from a wrong one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ispra_idrogeo import LANDSLIDE_FIELDS, IdroGEO, event_filter
from ispra_idrogeo.api import API_URL
from ispra_idrogeo.reliability import reliability


@dataclass(frozen=True)
class Method:
    name: str

    async def hazard(self, idrogeo: IdroGEO, lat: float, lon: float) -> tuple[str, str]:
        found = await idrogeo.hazard_at(lat, lon)
        return found.landslide or "", found.flood or ""

    async def count(self, idrogeo: IdroGEO, level: str, code: int) -> int:
        return int((await idrogeo.summary("iffi", level, code))["frane_totali"])  # type: ignore[arg-type]

    async def events(
        self, idrogeo: IdroGEO, municipality: int, start: date, end: date
    ) -> list[str]:
        found = event_filter(municipality=municipality, start=start, end=end)
        return [str(e["uid"]) async for e in idrogeo.iter_events(found, select=["uid"])]

    async def near(self, idrogeo: IdroGEO, lat: float, lon: float, radius_m: float) -> int:
        return len(await idrogeo.landslides_near(lat, lon, radius_m))

    async def search(self, idrogeo: IdroGEO) -> list[dict[str, Any]]:
        rows = await idrogeo.search_landslides(limit=2)
        return [r for r in rows if set(LANDSLIDE_FIELDS) <= r.keys()]

    def reliability(self, level: str, code: int, field: str) -> float | None:
        value = getattr(reliability(level, code), field)  # type: ignore[arg-type]
        return None if value is None else float(value)


class Constant(Method):
    async def hazard(self, idrogeo: IdroGEO, lat: float, lon: float) -> tuple[str, str]:
        return "P4", "P3"

    async def count(self, idrogeo: IdroGEO, level: str, code: int) -> int:
        return 0

    async def events(
        self, idrogeo: IdroGEO, municipality: int, start: date, end: date
    ) -> list[str]:
        return []

    async def near(self, idrogeo: IdroGEO, lat: float, lon: float, radius_m: float) -> int:
        return 0

    async def search(self, idrogeo: IdroGEO) -> list[dict[str, Any]]:
        # what a client did before #9: IdroGEO's own default fields
        response = await idrogeo._client.post(
            f"{API_URL.rstrip('/')}/frana/searchfilter",
            params={"limit": "2", "offset": "0"},
            json={},
        )
        response.raise_for_status()
        rows: list[dict[str, Any]] = response.json()
        return rows

    def reliability(self, level: str, code: int, field: str) -> float | None:
        return 1.0


METHODS: tuple[Method, ...] = (Method("ispra-idrogeo"), Constant("constant"))
