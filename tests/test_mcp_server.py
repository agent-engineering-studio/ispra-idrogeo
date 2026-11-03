from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from ispra_idrogeo import IdroGEO, mcp_server
from ispra_idrogeo.mcp_server import server


def _zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("eventi_opendata.shp", b"SHP")
    return buffer.getvalue()


_ZIP = _zip()


async def _sleep(_s: float) -> None:
    return None


def _labels(name: str) -> list[dict[str, str]]:
    words = {
        "tipo_movimento": ("5", "rapid debris flow"),
        "strumento_monitoraggio": ("15", "inclinometer"),
    }
    code, label = words.get(name, ("1", f"{name} 1"))
    return [{"codice": code, "descrizione_en": label}]


def _api(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.startswith("/opendata/"):
        return httpx.Response(200, content=_ZIP)
    path = path.removeprefix("/api/")
    body = json.loads(request.content) if request.content else None
    rows: Any
    if path == "iffi/comuni":
        rows = [
            {"uid": 72006, "nome": "Bari"},
            {"uid": 72004, "nome": "Altamura"},
            {"uid": 1, "nome": "Sbari"},
        ]
    elif path == "iffi/comuni/72006":
        rows = {"nome": "Bari", "frane_stats": [{"cod": 5, "nr_frane": 3}], "frane_totali": 3}
    elif path == "pir/italia":
        rows = {"nome": "Italia", "pop_idr_p2": 6818375}
    elif path.startswith("dizionari/"):
        rows = _labels(path.removeprefix("dizionari/"))
    elif path == "frana/0017680500":
        rows = {"id_frana": "0017680500", "tipo_movimento": 5, "geom_polygon": {}, "point": [1, 2]}
    elif path == "frana/0000000000":
        return httpx.Response(401, json={"message": "Missing authorization header"})
    elif path in ("frana/searchfilter", "evento/main/filter"):
        limit = int(request.url.params["limit"])
        rows = [{"n": n, "body": body} for n in range(min(limit, 250))]
    elif path == "sito/filter":
        rows = [{"uid": f"SI{n}", "strumentazione": [15], "body": body} for n in range(3)]
    elif path == "webcam/filter":
        rows = [{"id_sensore": "SW00000001", "body": body}]
    else:
        raise AssertionError(path)
    return httpx.Response(200, json=rows)


def _server() -> Any:
    client = httpx.AsyncClient(transport=httpx.MockTransport(_api))
    return server(IdroGEO(client, sleep=_sleep))


async def _call(mcp: Any, tool: str, **arguments: Any) -> Any:
    result = await mcp.call_tool(tool, arguments)
    assert not result.is_error, result.content
    structured = result.structured_content
    if structured is None:  # a tool typed Any answers with JSON text only
        return json.loads(result.content[0].text)
    return structured.get("result", structured)


async def test_tools_are_listed_and_read_only() -> None:
    tools = {t.name: t for t in await _server().list_tools()}
    assert set(tools) == {
        "find_area",
        "area_risk",
        "area_landslides",
        "landslide",
        "search_landslides",
        "search_events",
        "monitoring_sites",
        "webcams",
        "code_list",
        "download_dataset",
    }
    assert tools["area_risk"].annotations.read_only_hint
    assert not tools["download_dataset"].annotations.read_only_hint


async def test_areas_and_risk() -> None:
    mcp = _server()
    found = await _call(mcp, "find_area", name="BARI")
    assert found[0] == {"code": 72006, "name": "Bari", "level": "comuni"}  # exact name first
    assert [a["name"] for a in found] == ["Bari", "Sbari"]
    assert (await _call(mcp, "area_risk", level="italia"))["pop_idr_p2"] == 6818375
    counts = await _call(mcp, "area_landslides", level="comuni", code=72006)
    assert counts["frane_stats"] == [{"cod": 5, "nr_frane": 3, "type": "rapid debris flow"}]


async def test_landslides_events_sites() -> None:
    mcp = _server()
    record = await _call(mcp, "landslide", id_frana="0017680500")
    assert record["tipo_movimento_label"] == "rapid debris flow"
    assert "geom_polygon" not in record and record["point"] == [1, 2]
    found = await _call(mcp, "search_landslides", movement=6, activity=[100], limit=5)
    assert len(found) == 5 and found[0]["body"] == {
        "tipo_movimento": 6,
        "stato_attivita_1liv": "eq.100",
    }
    events = await _call(mcp, "search_events", region=16, start="2023-01-01", end="2024-01-01")
    assert len(events) == 100  # the default limit
    assert events[0]["body"]["regione"] == "eq.16" and "and" in events[0]["body"]
    sites = await _call(mcp, "monitoring_sites", region=1, active=True, limit=2)
    assert [s["strumentazione_label"] for s in sites] == [["inclinometer"], ["inclinometer"]]
    assert sites[0]["body"] == {"regione": "eq.1", "stato_monitoraggio": "eq.1"}
    assert (await _call(mcp, "webcams", region=3))[0]["body"] == {"regione": "eq.3"}
    assert (await _call(mcp, "code_list", name="cause")) == {"1": "cause 1"}


async def test_download(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IDROGEO_DATA_DIR", str(tmp_path))
    mcp = _server()
    path = await _call(mcp, "download_dataset", dataset="eventi", area="puglia", geojson=True)
    assert Path(path["path"]).parent == tmp_path
    mosaic_path = await _call(mcp, "download_dataset", dataset="idraulica")
    assert "Mosaicatura" in mosaic_path["path"]


async def test_errors_reach_the_agent() -> None:
    mcp = _server()
    for tool, arguments in (
        ("landslide", {"id_frana": "0000000000"}),
        ("search_events", {"limit": 0}),
        ("download_dataset", {"dataset": "nothing"}),
    ):
        with pytest.raises(ToolError):
            await mcp.call_tool(tool, arguments)


async def test_the_client_is_closed_only_if_ours() -> None:
    ours, theirs = IdroGEO(), IdroGEO()
    async with mcp_server._closing(ours, own=True):
        pass
    async with mcp_server._closing(theirs, own=False):
        pass
    assert ours._client.is_closed and not theirs._client.is_closed
    await theirs.aclose()
    assert mcp_server.server() is not None  # builds with its own client
