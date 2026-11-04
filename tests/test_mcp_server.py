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


_COMUNI = (
    (72006, "Bari", 16),
    (72004, "Altamura", 16),
    (1001, "Sbari", 1),
    (40012, "Forlì", 8),
    (62070, "Sant'Agata de' Goti", 15),
)


def _api(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.startswith("/opendata/"):
        return httpx.Response(200, content=_ZIP)
    path = path.removeprefix("/api/")
    body = json.loads(request.content) if request.content else None
    rows: Any
    if path in ("iffi/comuni", "pir/comuni"):
        rows = [
            {"uid": c, "pro_com": c, "nome": n, "cod_reg": r, "cod_prov": c // 1000}
            for c, n, r in _COMUNI
        ]
    elif path.startswith("pir/comuni/"):
        code = int(path.removeprefix("pir/comuni/"))
        name = next(n for c, n, _ in _COMUNI if c == code)
        rows = {"uid": code, "nome": name, "popfrp3p4p": code / 1000, "pop_res021": 10}
        if code == 1001:
            rows["popfrp3p4p"] = None  # not every area has every value
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
        "rank_areas",
        "compare_areas",
        "hazard_at_point",
        "nearest_landslides",
        "area_landslide_types",
        "warehouse_schema",
        "warehouse_sql",
        "download_dataset",
    }
    assert not tools["hazard_at_point"].annotations.open_world_hint  # local, no network
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


async def test_names_are_matched_without_accents() -> None:
    mcp = _server()
    assert (await _call(mcp, "find_area", name="forli"))[0]["name"] == "Forlì"
    found = await _call(mcp, "find_area", name="sant agata de\u2019 goti")
    assert found[0]["code"] == 62070
    with pytest.raises(ToolError, match="did you mean Bari"):
        await mcp.call_tool("find_area", {"name": "Barii"})
    with pytest.raises(ToolError, match=r"no comuni named like 'Roma'$"):
        await mcp.call_tool("find_area", {"name": "Roma"})


async def test_rank_and_compare(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IDROGEO_DATA_DIR", str(tmp_path))
    mcp = _server()
    ranked = await _call(mcp, "rank_areas", indicator="popfrp3p4p", top=2)
    assert ranked["areas_compared"] == 4  # Sbari has no value
    assert [(r["rank"], r["name"]) for r in ranked["ranking"]] == [
        (1, "Bari"),
        (2, "Altamura"),
    ]
    assert "CC BY 4.0" in ranked["source"]
    lowest = await _call(mcp, "rank_areas", indicator="popfrp3p4p", region=16, lowest=True)
    assert [r["code"] for r in lowest["ranking"]] == [72004, 72006]
    assert lowest["order"] == "lowest first"
    assert (tmp_path / "pir_comuni" / "72006.json").exists()  # kept for next time
    compared = await _call(mcp, "compare_areas", level="comuni", codes=[72006, 40012])
    assert compared["indicators"][0] == "pop_res021"
    forli = compared["areas"][1]
    assert (forli["name"], forli["pop_res021"], forli["popfr_p3p4"]) == ("Forlì", 10, None)
    picked = await _call(
        mcp, "compare_areas", level="comuni", codes=[72006], indicators=["pop_res021"]
    )
    assert picked["areas"] == [{"code": 72006, "name": "Bari", "pop_res021": 10}]
    for tool, arguments, message in (
        ("rank_areas", {"indicator": "popfr_p34"}, "close: popfrp3p4p"),
        ("rank_areas", {"indicator": "zzz"}, "unknown indicator 'zzz' "),
        ("rank_areas", {"indicator": "popfrp3p4p", "top": 0}, "top must"),
        ("rank_areas", {"indicator": "popfrp3p4p", "region": 99}, "no area found"),
        ("compare_areas", {"level": "comuni", "codes": []}, "between 1 and 20"),
    ):
        with pytest.raises(ToolError, match=message):
            await mcp.call_tool(tool, arguments)


async def test_resources_and_prompts() -> None:
    mcp = _server()
    assert {str(r.uri) for r in await mcp.list_resources()} == {
        "idrogeo://indicators",
        "idrogeo://datasets",
    }
    glossary = (await mcp.read_resource("idrogeo://indicators"))[0].content
    assert "popfrp3p4p" in glossary
    catalogue = json.loads((await mcp.read_resource("idrogeo://datasets"))[0].content)
    assert "frane_piff" in catalogue["landslide_layers"] and "bolzano" in catalogue["areas"]
    codes = json.loads((await mcp.read_resource("idrogeo://codes/tipo_movimento"))[0].content)
    assert codes == {"5": "rapid debris flow"}
    assert {p.name for p in await mcp.list_prompts()} == {"area_profile", "recent_events"}
    profile = await mcp.get_prompt("area_profile", {"place": "Sarno"})
    assert "Sarno" in profile.messages[0].content.text
    events = await mcp.get_prompt("recent_events", {"place": "Liguria", "since": "2026-10-01"})
    assert "2026-10-01" in events.messages[0].content.text


async def test_spatial_tools_read_the_warehouse(tmp_path: Path, idrogeo: IdroGEO) -> None:
    from conftest import LAT, LON, TRIVENTO

    from ispra_idrogeo.warehouse import Warehouse

    path = tmp_path / "w.duckdb"
    mcp = server(idrogeo, warehouse=path)
    with pytest.raises(ToolError, match="idrogeo sync"):
        await mcp.call_tool("hazard_at_point", {"lon": LON, "lat": LAT})
    with Warehouse(path) as warehouse:
        await warehouse.sync(idrogeo, ["frane_piff", "pai_frane"], "molise", tmp_path)
    here = await _call(mcp, "hazard_at_point", lon=LON, lat=LAT)
    assert (here["landslide"], here["missing"]) == ("P4", ["idraulica"])
    near = await _call(mcp, "nearest_landslides", lon=LON, lat=LAT, radius_m=200)
    assert [r["distance_m"] for r in near] == [40.0, 100.0]
    counts = await _call(mcp, "area_landslide_types", municipality=TRIVENTO)
    assert counts["landslides"] == 3
    schema = await _call(mcp, "warehouse_schema")
    assert {layer["name"] for layer in schema["layers"]} == {"frane_piff", "pai_frane"}
    rows = await _call(mcp, "warehouse_sql", sql="SELECT count(*) AS n FROM pai_frane")
    assert rows == [{"n": 3}]
    with pytest.raises(ToolError, match="one SELECT"):
        await mcp.call_tool("warehouse_sql", {"sql": "DELETE FROM pai_frane"})


def test_command_line_arguments() -> None:
    assert mcp_server._arguments([]).transport == "stdio"
    http = mcp_server._arguments(["--transport", "streamable-http", "--port", "9000"])
    assert (http.transport, http.host, http.port) == ("streamable-http", "127.0.0.1", 9000)


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
