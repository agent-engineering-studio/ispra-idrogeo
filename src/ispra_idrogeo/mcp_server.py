"""An MCP server over IdroGEO, for AI agents: ``pip install "ispra-idrogeo[mcp]"``.

    idrogeo-mcp                                     # stdio: Claude Desktop, IDEs
    idrogeo-mcp --transport streamable-http --host 0.0.0.0 --port 8767

Over HTTP the MCP endpoint is ``/mcp`` and ``GET /health`` answers
``{"status": "ok"}`` for container healthchecks. Every option also reads
an environment variable (``IDROGEO_MCP_TRANSPORT``, ``IDROGEO_MCP_HOST``,
``IDROGEO_MCP_PORT``, ``IDROGEO_MCP_ALLOWED_HOSTS``), so a compose file
needs no command line.

Every tool reads the public API (no account), except ``download_dataset``,
which writes the file to the local download folder and returns its path.
Codes come back with their English labels, and long answers are cut at
``limit`` rows, so an agent never receives 700,000 landslides at once.
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date, datetime
from functools import wraps
from typing import Any, Literal, cast

from ispra_idrogeo import __version__
from ispra_idrogeo.client import IdroGEO
from ispra_idrogeo.codes import decode
from ispra_idrogeo.errors import IdrogeoError
from ispra_idrogeo.filters import event_filter, landslide_filter, site_filter
from ispra_idrogeo.sources import EVENT_LAYERS, LANDSLIDE_LAYERS, MOSAICS, mosaic, opendata

try:
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.server.transport_security import TransportSecuritySettings
    from mcp.types import ToolAnnotations
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        'ispra_idrogeo.mcp_server needs the mcp extra: pip install "ispra-idrogeo[mcp]"'
    ) from exc

AreaLevel = Literal["regioni", "province", "comuni"]
INSTRUCTIONS = """\
Italian landslide and flood data from ISPRA IdroGEO (CC BY 4.0: credit
"ISPRA — IdroGEO"). For a place or an address, use its coordinates with
hazard_at and landslides_near. Areas use ISTAT codes: call find_area first
to turn a name into a code. area_risk gives hazard and exposure (residents, buildings,
cultural heritage in each landslide class P1-P4/AA and flood class P1-P3);
area_landslides the IFFI inventory counts. Search tools return at most
`limit` rows; the totals are in area_landslides.
"""

#: The heavy geometry fields a landslide record carries; the point stays.
_GEOMETRY = ("geom", "geom_polygon", "geom_linestring", "extent")
_READ = ToolAnnotations(read_only_hint=True, open_world_hint=True)


@asynccontextmanager
async def _closing(client: IdroGEO, *, own: bool) -> AsyncIterator[None]:
    """The server's lifespan: close the HTTP client at shutdown if it is ours."""
    try:
        yield
    finally:
        if own:
            await client.aclose()


def _tool_errors[**P, T](call: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
    """IdroGEO refusals and bad arguments as a ToolError the agent can read."""

    @wraps(call)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return await call(*args, **kwargs)
        except (IdrogeoError, ValueError) as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


def server(idrogeo: IdroGEO | None = None) -> MCPServer[Any]:
    """The MCP server; ``idrogeo`` defaults to a client it opens and closes itself."""
    client = idrogeo or IdroGEO()
    areas: dict[str, list[dict[str, Any]]] = {}

    mcp: MCPServer[Any] = MCPServer(
        "ispra-idrogeo",
        instructions=INSTRUCTIONS,
        lifespan=lambda _server: _closing(client, own=idrogeo is None),
    )

    @mcp.tool(annotations=_READ)
    @_tool_errors
    async def find_area(name: str, level: AreaLevel = "comuni") -> list[dict[str, Any]]:
        """ISTAT code of a region, province or municipality from (part of) its name."""
        if level not in areas:
            areas[level] = await client.summary("iffi", level)
        wanted = name.strip().casefold()
        found = [a for a in areas[level] if wanted in str(a.get("nome", "")).casefold()]
        found.sort(key=lambda a: (str(a["nome"]).casefold() != wanted, str(a["nome"])))
        return [{"code": a["uid"], "name": a["nome"], "level": level} for a in found[:20]]

    @mcp.tool(annotations=_READ)
    @_tool_errors
    async def area_risk(level: Literal["italia", AreaLevel], code: int | None = None) -> Any:
        """Hazard and exposure indicators of Italy or one area (ISTAT code).

        Keys: ar_* areas (km², *_p in %), pop_* residents, fam_* families,
        ed_* buildings, im_* businesses, bbcc_* cultural heritage; *_fr_*
        landslide hazard P1-P4/AA, *_idr_* flood hazard P1-P3.
        """
        return await client.summary("pir", level, code)

    @mcp.tool(annotations=_READ)
    @_tool_errors
    async def area_landslides(
        level: Literal["italia", AreaLevel], code: int | None = None
    ) -> dict[str, Any]:
        """IFFI counts of Italy or one area: landslides by type, events, monitoring."""
        found = await client.summary("iffi", level, code)
        types = await client.labels("tipo_movimento")
        found["frane_stats"] = [
            {**s, "type": types.get(str(s.get("cod")))} for s in found.get("frane_stats") or []
        ]
        return dict(found)

    @mcp.tool(annotations=_READ)
    @_tool_errors
    async def landslide(id_frana: str) -> dict[str, Any]:
        """The full record of one IFFI landslide, codes decoded, geometry left out."""
        record = await client.landslide(id_frana)
        labels = await client.code_labels([f for f in _CODED if f in record])
        return {k: v for k, v in decode(record, labels).items() if k not in _GEOMETRY}

    @mcp.tool(annotations=_READ)
    @_tool_errors
    async def search_landslides(
        movement: int | None = None,
        activity: list[int] | None = None,
        region: int | None = None,
        province: int | None = None,
        municipality: int | None = None,
        modified_since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """IFFI landslides by movement code, activity codes (100 active, 200
        dormant, 300 stabilised, 400 relict), area (ISTAT codes) or changed
        since a time. An area reads the whole inventory first (~20 s); for an
        area's totals area_landslides is instant."""
        wanted = landslide_filter(movement=movement, activity=activity)
        if region or province or municipality:
            found = client.iter_landslides_in(
                region=region,
                province=province,
                municipality=municipality,
                filters=wanted,
                modified_since=modified_since,
            )
        else:
            found = client.iter_landslides(
                wanted, modified_since=modified_since, page_size=_page(limit)
            )
        return await _take(found, _page(limit))

    @mcp.tool(annotations=_READ)
    @_tool_errors
    async def search_events(
        region: int | None = None,
        province: int | None = None,
        municipality: int | None = None,
        movement: int | None = None,
        start: date | None = None,
        end: date | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Dated landslide events by area (ISTAT codes), movement, and dates
        (start included, end excluded)."""
        found = client.iter_events(
            event_filter(
                region=region,
                province=province,
                municipality=municipality,
                movement=movement,
                start=start,
                end=end,
            ),
            page_size=_page(limit),
        )
        return await _take(found, limit)

    @mcp.tool(annotations=_READ)
    @_tool_errors
    async def monitoring_sites(
        region: int | None = None,
        province: int | None = None,
        municipality: int | None = None,
        active: bool | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Landslide monitoring sites by area (ISTAT codes) and whether active,
        with their instruments and the IFFI landslides they watch."""
        sites = await client.sites(
            site_filter(region=region, province=province, municipality=municipality, active=active)
        )
        labels = await client.code_labels(_SITE_CODES)
        return [decode(s, labels) for s in sites[: _page(limit)]]

    @mcp.tool(annotations=_READ)
    @_tool_errors
    async def webcams(region: int | None = None) -> list[dict[str, Any]]:
        """Webcams pointed at landslides (geom in EPSG:3857 metres)."""
        return await client.webcams(site_filter(region=region))

    @mcp.tool(annotations=_READ)
    @_tool_errors
    async def hazard_at(lat: float, lon: float, lithology: bool = False) -> dict[str, Any]:
        """Landslide and flood hazard of a point (WGS 84 degrees), with its
        municipality (ISTAT code) and slope in degrees.

        landslide: PAI class P4 very high, P3 high, P2 medium, P1 moderate,
        AA attention area, null outside. flood: the most frequent scenario
        reaching the point, P3 high probability (frequent floods), P2 medium,
        P1 low (rare, extreme). lithology=true adds the rock type but takes
        ~16 s longer.
        """
        return asdict(await client.hazard_at(lat, lon, lithology=lithology))

    @mcp.tool(annotations=_READ)
    @_tool_errors
    async def landslides_near(
        lat: float, lon: float, radius_m: float = 500, limit: int = 50
    ) -> list[dict[str, Any]]:
        """IFFI landslides within radius_m (at most 5,000) of a point, nearest
        first, with distance_m (0 when the point is on the landslide) and the
        type of movement."""
        found = await client.landslides_near(lat, lon, radius_m, limit=1000)
        return found[: _page(limit)]

    @mcp.tool(annotations=_READ)
    @_tool_errors
    async def code_list(name: str, lang: Literal["it", "en", "fr", "de"] = "en") -> dict[str, str]:
        """One IdroGEO code list as {code: label}, e.g. tipo_movimento, cause."""
        return await client.labels(name, lang)

    @mcp.tool(annotations=ToolAnnotations(idempotent_hint=True, open_world_hint=True))
    @_tool_errors
    async def download_dataset(
        dataset: str, area: str = "ispra", geojson: bool = False
    ) -> dict[str, str]:
        """Download (only if changed) and unpack an open-data layer; its local path.

        Datasets: IFFI layers (frane_piff, frane_poly, frane_line, aree_poly,
        dgpv_poly), eventi, segnalazioni, or the mosaics pai_frane and
        idraulica. area: "ispra" (Italy) or a region or province file name.
        """
        if dataset in MOSAICS:
            found = mosaic(dataset)
        elif dataset in (*LANDSLIDE_LAYERS, *EVENT_LAYERS):
            found = opendata(dataset, area, "geojson" if geojson else "shapefile")
        else:
            raise ValueError(f"unknown dataset {dataset!r}")
        return {"path": str(await client.fetch(found))}

    async def health(_request: Request) -> Response:
        """``GET /health`` over HTTP, for container healthchecks."""
        return JSONResponse({"status": "ok", "server": "ispra-idrogeo", "version": __version__})

    # custom_route is untyped in the SDK: register the typed handler through a cast.
    route = cast(Callable[[Any], Any], mcp.custom_route("/health", methods=["GET"]))
    route(health)

    return mcp


_CODED = (
    "tipo_movimento",
    "stato_attivita_1liv",
    "stato_attivita_2liv",
    "velocita_1ord",
    "movimento_1ord",
    "materiale_1ord",
    "cause",
    "metodo",
    "uso_suolo",
    "posizione_punto",
)
_SITE_CODES = ("stato_monitoraggio", "finalita_monitoraggio", "tipo_acquisizione", "strumentazione")


def _page(limit: int) -> int:
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    return limit


async def _take(rows: AsyncIterator[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    out = []
    async for row in rows:
        out.append(row)
        if len(out) == limit:
            break
    return out


def options(
    argv: Sequence[str] | None = None, environ: Mapping[str, str] = os.environ
) -> argparse.Namespace:
    """The command line of ``idrogeo-mcp``, each default from its environment variable."""
    top = argparse.ArgumentParser(prog="idrogeo-mcp", description="IdroGEO as an MCP server.")
    top.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=environ.get("IDROGEO_MCP_TRANSPORT", "stdio"),
        help="stdio (default) or streamable-http, served at /mcp",
    )
    top.add_argument(
        "--host",
        default=environ.get("IDROGEO_MCP_HOST", "127.0.0.1"),
        help="HTTP address (default 127.0.0.1; 0.0.0.0 in a container)",
    )
    top.add_argument("--port", type=int, default=int(environ.get("IDROGEO_MCP_PORT", "8767")))
    top.add_argument(
        "--allowed-host",
        action="append",
        default=[h for h in environ.get("IDROGEO_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()],
        metavar="HOST[:PORT]",
        help="accept only these Host headers (DNS rebinding protection); repeatable",
    )
    args = top.parse_args(argv)
    if args.transport not in ("stdio", "streamable-http"):
        top.error(f"unknown transport {args.transport!r}")
    return args


def http_options(args: argparse.Namespace) -> dict[str, Any]:
    """The keyword arguments of ``MCPServer.run`` for the HTTP transport."""
    found: dict[str, Any] = {"host": args.host, "port": args.port, "streamable_http_path": "/mcp"}
    if args.allowed_host:
        found["transport_security"] = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[h.strip() for h in args.allowed_host],
        )
    return found


def main(argv: Sequence[str] | None = None) -> None:  # pragma: no cover - runs a server
    """Entry point of ``idrogeo-mcp``."""
    logging.getLogger("httpx").setLevel(logging.WARNING)  # not one line per request
    args = options(argv)
    if args.transport == "stdio":
        server().run("stdio")
    else:
        server().run("streamable-http", **http_options(args))
