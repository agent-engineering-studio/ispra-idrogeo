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
import asyncio
import difflib
import json
import logging
import os
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date, datetime, timedelta
from functools import wraps
from typing import Any, Literal, cast

from ispra_idrogeo import __version__
from ispra_idrogeo.client import IdroGEO
from ispra_idrogeo.codes import decode
from ispra_idrogeo.errors import IdrogeoError
from ispra_idrogeo.filters import event_filter, landslide_filter, site_filter
from ispra_idrogeo.sources import (
    EVENT_LAYERS,
    LANDSLIDE_LAYERS,
    MOSAICS,
    PROVINCES,
    REGIONS,
    mosaic,
    opendata,
)

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
area_landslides the IFFI inventory counts. To rank or compare areas use
rank_areas and compare_areas instead of doing arithmetic yourself; the
resource idrogeo://indicators explains every indicator key. Search tools
return at most `limit` rows; the totals are in area_landslides. These are
official hazard maps and inventories, not a safety assessment of a site.
"""

#: What the indicator keys of ``area_risk`` mean, for agents and people.
INDICATORS = """\
# IdroGEO hazard and exposure indicators (area_risk, rank_areas)

Prefixes (what is counted):
- ar_     area, km² (ar_kmq: the whole area)
- pop_    residents (pop_res021: 2021 census, pop_res011: 2011)
- fam_    families
- ed_     buildings
- im_     businesses (local units)
- bbcc_   cultural heritage items (n_vir: all items in the area)
- pop_gio / pop_adu / pop_anz: young / adult / elderly residents

Hazard (where):
- _fr_    landslide hazard, PAI mosaic: p4 very high, p3 high, p2 medium,
          p1 moderate, aa attention areas; p3p4 = p3 + p4
- _idr_ or _id_  flood hazard: p3 high (frequent floods, 20-50 years),
          p2 medium (100-200 years), p1 low (rare, extreme events)

Shares: a key with _p (popfrp3p4p, popidp2_p, ar_frp4_p...) is a percentage
of the area's total, 0-100. Example: popfr_p3p4 = residents in landslide
hazard P3+P4; popfrp3p4p = the same as % of residents; pop_idr_p2 =
residents in flood hazard P2; popidp2_p = the same as %.

Source: ISPRA — IdroGEO, CC BY 4.0.
"""

#: What compare_areas shows when no indicator is asked for.
DEFAULT_INDICATORS = (
    "pop_res021",
    "popfr_p3p4",
    "popfrp3p4p",
    "pop_idr_p2",
    "popidp2_p",
    "ar_fr_p3p4",
    "ar_frp3p4p",
    "ar_id_p2",
    "aridp2_p",
)
#: Summaries of all areas of a level are kept on disk this long.
_FRESH = timedelta(days=30)

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
        wanted = _fold(name)
        found = [a for a in areas[level] if wanted in _fold(str(a.get("nome", "")))]
        found.sort(key=lambda a: (_fold(str(a["nome"])) != wanted, str(a["nome"])))
        if not found:
            names = {_fold(str(a.get("nome", ""))): str(a.get("nome")) for a in areas[level]}
            close = difflib.get_close_matches(wanted, names, n=5, cutoff=0.75)
            hint = f"; did you mean {', '.join(names[c] for c in close)}?" if close else ""
            raise ValueError(f"no {level} named like {name!r}{hint}")
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

    @mcp.tool(annotations=_READ)
    @_tool_errors
    async def rank_areas(
        indicator: str,
        level: AreaLevel = "comuni",
        region: int | None = None,
        province: int | None = None,
        top: int = 10,
        lowest: bool = False,
        summary: Literal["pir", "iffi"] = "pir",
    ) -> dict[str, Any]:
        """The areas with the highest (or lowest) value of one indicator.

        indicator: a numeric key of area_risk (summary "pir", e.g. popfrp3p4p,
        pop_idr_p2; see idrogeo://indicators) or of area_landslides ("iffi",
        e.g. frane_totali). region / province (ISTAT codes) keep only the
        areas inside them. The first ranking of all 7,899 municipalities asks
        IdroGEO once per municipality (a few minutes); the answers are kept
        on disk for 30 days, and a region's ranking is much faster.
        """
        if not 1 <= top <= 100:
            raise ValueError("top must be between 1 and 100")
        rows = await client.summaries(
            summary, level, max_age=_FRESH, region=region, province=province
        )
        _check_indicators(rows, [indicator])
        valued = [r for r in rows if isinstance(r.get(indicator), int | float)]
        valued.sort(key=lambda r: r[indicator], reverse=not lowest)
        return {
            "indicator": indicator,
            "order": "lowest first" if lowest else "highest first",
            "areas_compared": len(valued),
            "ranking": [
                {"rank": n, "code": r.get("uid"), "name": r.get("nome"), "value": r[indicator]}
                for n, r in enumerate(valued[:top], 1)
            ],
            "source": SOURCE,
        }

    @mcp.tool(annotations=_READ)
    @_tool_errors
    async def compare_areas(
        level: Literal["italia", "macroregioni", AreaLevel],
        codes: list[int],
        indicators: list[str] | None = None,
    ) -> dict[str, Any]:
        """Hazard and exposure indicators of up to 20 areas, side by side.

        codes: ISTAT codes of the same level (from find_area). indicators:
        keys of area_risk; by default residents, area and their shares in
        landslide hazard P3+P4 and flood hazard P2.
        """
        if not 1 <= len(codes) <= 20:
            raise ValueError("give between 1 and 20 codes")
        wanted = list(indicators or DEFAULT_INDICATORS)
        rows = await asyncio.gather(*(client.summary("pir", level, c) for c in codes))
        if indicators:  # the defaults are left empty where an area has none
            _check_indicators(rows, wanted)
        return {
            "indicators": wanted,
            "areas": [
                {"code": c, "name": r.get("nome"), **{k: r.get(k) for k in wanted}}
                for c, r in zip(codes, rows, strict=True)
            ],
            "source": SOURCE,
        }

    @mcp.resource(
        "idrogeo://indicators",
        title="Indicator keys",
        description="What the hazard and exposure keys of area_risk mean.",
        mime_type="text/markdown",
    )
    def indicators() -> str:
        return INDICATORS

    @mcp.resource(
        "idrogeo://datasets",
        title="Open-data catalogue",
        description="The layers, mosaics and area names download_dataset accepts.",
        mime_type="application/json",
    )
    def datasets() -> str:
        return json.dumps(
            {
                "landslide_layers": list(LANDSLIDE_LAYERS),
                "event_layers": list(EVENT_LAYERS),
                "mosaics": list(MOSAICS),
                "areas": ["ispra", *sorted(REGIONS.values()), *sorted(PROVINCES.values())],
                "crs": "EPSG:32632",
                "source": SOURCE,
            }
        )

    @mcp.resource(
        "idrogeo://codes/{name}",
        title="Code list",
        description="One IdroGEO code list as {code: English label}, e.g. tipo_movimento.",
        mime_type="application/json",
    )
    async def codes(name: str) -> str:
        return json.dumps(await client.labels(name, "en"))

    @mcp.prompt(title="Risk profile of a place")
    def area_profile(place: str, level: AreaLevel = "comuni") -> str:
        """Hazard, exposure, landslides and monitoring of one region, province or town."""
        return (
            f"Write a short, plain-language risk profile of {place} ({level}) from "
            "ISPRA IdroGEO data. Use find_area to get its ISTAT code, then "
            "area_risk, area_landslides and monitoring_sites. Put it in context "
            "with area_risk of its province or region (find_area with that level). "
            "Report residents, buildings "
            "and cultural heritage in landslide hazard P3+P4 and flood hazard P2, "
            "the landslides by type, and who monitors them. Quote only numbers the "
            'tools returned, credit "Source: ISPRA — IdroGEO (CC BY 4.0)", and say '
            "that this is not a safety assessment of any site."
        )

    @mcp.prompt(title="Recent landslide events")
    def recent_events(place: str, since: str) -> str:
        """The dated landslide events of a place since a date (YYYY-MM-DD)."""
        return (
            f"List the landslide events recorded by ISPRA IdroGEO in {place} since "
            f"{since}. Use find_area for the ISTAT code (region, province or "
            "municipality), then search_events with start set to that date. Group "
            "them by month and type of movement, give the total, and credit "
            '"Source: ISPRA — IdroGEO (CC BY 4.0)".'
        )

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


SOURCE = "ISPRA — IdroGEO (https://idrogeo.isprambiente.it), CC BY 4.0"


def _fold(text: str) -> str:
    """Lower case, no accents, apostrophes and dashes as spaces: Forlì ~ forli."""
    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    for mark in "'\u2019`-":
        plain = plain.replace(mark, " ")
    return " ".join(plain.split())


def _check_indicators(rows: list[dict[str, Any]], keys: list[str]) -> None:
    """A readable error, with the closest keys, for an indicator no row has."""
    known = {k for r in rows for k, v in r.items() if isinstance(v, int | float)}
    if not known:
        raise ValueError("no area found")
    for key in keys:
        if key not in known:
            close = difflib.get_close_matches(key, known, n=5, cutoff=0.6)
            hint = f"; close: {', '.join(close)}" if close else ""
            raise ValueError(f"unknown indicator {key!r}{hint} (see idrogeo://indicators)")


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
