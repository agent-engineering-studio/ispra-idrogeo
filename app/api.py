"""The page's small API, over the library: ``uvicorn --factory app.api:create_app``.

Settings come from the environment (see ``app/README.md``): the body's name,
the municipality the map opens on, the map tiles, the warehouse file and
whether to load it at start.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app.data import CITATIONS, LAYERS, NOTE_IT, RULE_IT, Data, UnavailableError
from ispra_idrogeo import WMS_URL, IdroGEO, IdrogeoError
from ispra_idrogeo.predisposition import NOTE, THRESHOLDS, rule

STATIC = Path(__file__).parent / "static"


class FreshStaticFiles(StaticFiles):
    """Static files the browser revalidates every time (ETag), so an update shows at once."""

    def file_response(self, *args: Any, **kwargs: Any) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["cache-control"] = "no-cache"
        return response


BULLETIN = "https://mappe.protezionecivile.gov.it/it/mappe-rischi/bollettino-di-criticita"
LIMEN = "https://github.com/agent-engineering-studio/limen"


def settings(environ: Mapping[str, str] = os.environ) -> dict[str, Any]:
    """The page's settings, each from its environment variable."""
    code = environ.get("IDROGEO_COMUNE", "65135")
    return {
        "ente": environ.get("IDROGEO_ENTE") or "Mappa dei dati su frane e pericolo",
        "comune": int(code) if code.isdigit() else 65135,
        "tiles": environ.get("IDROGEO_TILES") or "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "tiles_credit": environ.get("IDROGEO_TILES_CREDIT")
        or '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        "warehouse": environ.get("IDROGEO_APP_WAREHOUSE") or None,
        "load": environ.get("IDROGEO_APP_LOAD", "1") != "0",
    }


def create_app(data: Data | None = None, config: dict[str, Any] | None = None) -> Starlette:
    """The application; ``data`` and ``config`` can be given for tests."""
    config = config or settings()
    found = data or Data(IdroGEO(), Path(config["warehouse"]) if config["warehouse"] else None)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        task = asyncio.create_task(found.load_warehouse(LAYERS)) if config["load"] else None
        yield
        if task is not None:
            task.cancel()
        await found.idrogeo.aclose()

    async def health(_request: Request) -> Response:
        return JSONResponse({"status": "ok", "warehouse": found.state})

    async def config_route(_request: Request) -> Response:
        return JSONResponse(
            {
                "ente": config["ente"],
                "comune": config["comune"],
                "tiles": config["tiles"],
                "tiles_credit": config["tiles_credit"],
                "wms": WMS_URL,
                "bulletin": BULLETIN,
                "limen": LIMEN,
                "rule": RULE_IT,
                "rule_en": rule(),
                "thresholds": [[bound, step] for bound, step in THRESHOLDS],
                "note": NOTE_IT,
                "note_en": NOTE,
                "citations": CITATIONS,
            }
        )

    async def find(request: Request) -> Response:
        text = request.query_params.get("q", "").strip()
        return JSONResponse(await found.find(text) if len(text) >= 2 else [])

    def code_of(request: Request) -> int:
        return int(request.path_params["code"])

    async def guarded(request: Request, call: Callable[[Request], Awaitable[Response]]) -> Response:
        try:
            return await call(request)
        except UnavailableError as exc:
            return JSONResponse({"error": "non ancora disponibile", "detail": str(exc)}, 503)
        except (IdrogeoError, ValueError) as exc:
            return JSONResponse({"error": "IdroGEO", "detail": str(exc)}, 502)

    async def panel(request: Request) -> Response:
        async def run(r: Request) -> Response:
            return JSONResponse(await found.panel(code_of(r)))

        return await guarded(request, run)

    def layer(name: str) -> Any:
        async def route(request: Request) -> Response:
            async def run(r: Request) -> Response:
                return JSONResponse(await getattr(found, name)(code_of(r)))

            return await guarded(request, run)

        return route

    async def contract(_request: Request) -> Response:
        return JSONResponse(await found.contract())

    async def csv_route(request: Request) -> Response:
        async def run(r: Request) -> Response:
            code = code_of(r)
            return PlainTextResponse(
                await found.csv_of(code),
                media_type="text/csv; charset=utf-8",
                headers={"content-disposition": f'attachment; filename="comune-{code}.csv"'},
            )

        return await guarded(request, run)

    routes = [
        Route("/api/health", health),
        Route("/api/config", config_route),
        Route("/api/find", find),
        Route("/api/comune/{code:int}", panel),
        Route("/api/comune/{code:int}/iffi.geojson", layer("landslides")),
        Route("/api/comune/{code:int}/pai.geojson", layer("hazard")),
        Route("/api/comune/{code:int}/dated.geojson", layer("dated")),
        Route("/api/comune/{code:int}/dati.csv", csv_route),
        Route("/api/contract", contract),
        Mount("/", FreshStaticFiles(directory=STATIC, html=True), name="static"),
    ]
    return Starlette(routes=routes, lifespan=lifespan)
