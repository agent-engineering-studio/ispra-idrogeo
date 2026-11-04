from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FORLI_DEL_SANNIO, LAT, LON, TRIVENTO, Opendata

from ispra_idrogeo import IdroGEO, IdrogeoError

duckdb = pytest.importorskip("duckdb")
from ispra_idrogeo import warehouse as wh  # noqa: E402
from ispra_idrogeo.warehouse import Warehouse  # noqa: E402

ALL = ["frane_piff", "pai_frane", "idraulica"]


async def _synced(tmp_path: Path, idrogeo: IdroGEO, layers: list[str] = ALL) -> Warehouse:
    warehouse = Warehouse(tmp_path / "w.duckdb")
    await warehouse.sync(idrogeo, layers, "molise", tmp_path)
    return warehouse


async def test_sync_loads_only_what_changed(
    tmp_path: Path, idrogeo: IdroGEO, opendata_server: Opendata
) -> None:
    with Warehouse(tmp_path / "w.duckdb") as warehouse:
        assert await warehouse.sync(idrogeo, ALL, "molise", tmp_path) == dict.fromkeys(ALL, True)
        layers = {layer["name"]: layer for layer in warehouse.layers()}
        assert {n: (layer["area"], layer["rows"]) for n, layer in layers.items()} == {
            "frane_piff": ("molise", 4),
            "pai_frane": ("ispra", 3),  # the mosaics are national
            "idraulica": ("ispra", 3),  # three scenario files, one table
        }
        assert layers["frane_piff"]["version"].startswith('"frane_piff_molise')
        again = await warehouse.sync(idrogeo, ALL, "molise", tmp_path)
        assert again == dict.fromkeys(ALL, False)  # three 304s, nothing reloaded
        opendata_server.version = "2"
        assert await warehouse.sync(idrogeo, ["pai_frane"], directory=tmp_path) == {
            "pai_frane": True
        }


async def test_hazard_at_a_point(tmp_path: Path, idrogeo: IdroGEO) -> None:
    with await _synced(tmp_path, idrogeo) as warehouse:
        here = warehouse.hazard_at(LAT, LON)
        assert (here["landslide"], here["landslide_classes"]) == ("P4", ["P4", "P3"])
        assert (here["flood"], here["flood_classes"]) == ("P2", ["P2", "P1"])  # no P3 here
        assert here["missing"] == [] and len(here["sources"]) == 2
        assert all("CC BY-SA 4.0" in s for s in here["sources"])
        assert "legal value" in here["note"]
        far = warehouse.hazard_at(LAT, LON + 0.5)
        assert (far["landslide"], far["flood"]) == (None, None)
        with pytest.raises(ValueError, match="degrees"):
            warehouse.hazard_at(4600000, 500000)  # metres, not degrees


async def test_hazard_says_what_is_missing(tmp_path: Path, idrogeo: IdroGEO) -> None:
    with await _synced(tmp_path, idrogeo, ["frane_piff"]) as warehouse:
        answer = warehouse.hazard_at(LAT, LON)
        assert answer["missing"] == ["pai_frane", "idraulica"] and answer["sources"] == []
    empty = tmp_path / "empty.duckdb"
    duckdb.connect(str(empty)).close()  # a file nothing was ever synced into
    with Warehouse(empty, read_only=True) as warehouse:
        assert warehouse.hazard_at(LAT, LON)["missing"] == ["pai_frane", "idraulica"]


async def test_landslides_near_and_in(tmp_path: Path, idrogeo: IdroGEO) -> None:
    with await _synced(tmp_path, idrogeo, ["frane_piff"]) as warehouse:
        near = warehouse.landslides_near(LAT, LON, 500)
        assert [(r["id_frana"], r["distance_m"]) for r in near] == [
            ("0000000001", 40.0),
            ("0000000000", 100.0),
        ]
        assert near[0]["lon"] == pytest.approx(LON, abs=0.001)
        assert near[0]["comune"] == TRIVENTO  # whole numbers, not 70081.0
        assert len(warehouse.landslides_near(LAT, LON, 1000, limit=1)) == 1
        for radius, limit in ((0, 10), (60_000, 10), (100, 0)):
            with pytest.raises(ValueError):
                warehouse.landslides_near(LAT, LON, radius, limit=limit)
        trivento = warehouse.landslides_in(municipality=TRIVENTO)
        assert trivento["landslides"] == 3
        assert trivento["by_type"][0] == {
            "tipo_movim": 7,
            "nome_tipo": "Complesso",
            "landslides": 2,
        }
        assert "CC BY 4.0" in trivento["source"]
        assert warehouse.landslides_in(region=14)["landslides"] == 4
        forli = warehouse.landslides_in(province=94)["by_type"]
        assert forli == [{"tipo_movim": 2, "nome_tipo": "Scivolamento", "landslides": 1}]
        for layer in ("frane_poly", "x; DROP TABLE frane_piff"):
            with pytest.raises(IdrogeoError, match="idrogeo sync"):
                warehouse.landslides_in(layer=layer)


async def test_query_reads_and_only_reads(tmp_path: Path, idrogeo: IdroGEO) -> None:
    with await _synced(tmp_path, idrogeo, ["frane_piff"]) as warehouse:
        rows = warehouse.query(
            "SELECT nome_com, count(*) AS n FROM frane_piff WHERE comune = ? GROUP BY 1",
            [FORLI_DEL_SANNIO],
        )
        assert rows == [{"nome_com": "Forlì del Sannio", "n": 1}]  # ISO-8859-1, read right
        with_cte = "WITH t AS (SELECT * FROM frane_piff) SELECT id_frana FROM t ORDER BY 1"
        assert len(warehouse.query(with_cte, limit=2)) == 2
        for sql in ("DROP TABLE frane_piff", "SELECT 1; SELECT 2", "COPY frane_piff TO 'x.csv'"):
            with pytest.raises(ValueError, match="one SELECT"):
                warehouse.query(sql)
        with pytest.raises(ValueError, match="nothing_here"):
            warehouse.query("SELECT nothing_here FROM frane_piff")
        with pytest.raises(ValueError, match="limit"):
            warehouse.query("SELECT 1", limit=0)
        [shape] = warehouse.query('SELECT geom AS "the point" FROM frane_piff LIMIT 1')
        assert shape["the point"].startswith("POINT (")  # WKT, not WKB bytes
        columns = {c["column"] for c in warehouse.schema()["frane_piff"]}
        assert {"id_frana", "tipo_movim", "comune", "geom"} <= columns


async def test_opening_and_loading_errors(tmp_path: Path, idrogeo: IdroGEO) -> None:
    with pytest.raises(IdrogeoError, match="run `idrogeo sync` first"):
        Warehouse(tmp_path / "missing.duckdb", read_only=True)
    with Warehouse(tmp_path / "w.duckdb") as warehouse:
        with pytest.raises(IdrogeoError, match="busy"):
            Warehouse(tmp_path / "w.duckdb", read_only=True)  # held open for writing
        with pytest.raises(ValueError, match="unknown layer"):
            await warehouse.sync(idrogeo, ["nothing"])
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(IdrogeoError, match="no shapefile"):
            warehouse._load("eventi", empty, "ispra", "v")
        odd = tmp_path / "odd"
        odd.mkdir()
        await warehouse.sync(idrogeo, ["idraulica"], directory=tmp_path)
        unpacked = next(tmp_path.glob("Mosaicatura*idraulica"))
        for member in unpacked.glob("HPH_*"):
            member.rename(odd / member.name.replace("HPH_", "XXX_"))
        with pytest.raises(IdrogeoError, match="unexpected flood scenario"):
            warehouse._load("idraulica", odd, "ispra", "v")


async def test_read_only_shuts_every_door(tmp_path: Path, idrogeo: IdroGEO) -> None:
    (await _synced(tmp_path, idrogeo, ["frane_piff"])).close()
    secret = tmp_path / "secret.txt"
    secret.write_text("password")
    with Warehouse(tmp_path / "w.duckdb", read_only=True) as warehouse:
        assert warehouse.query("SELECT count(*) AS n FROM frane_piff") == [{"n": 4}]
        for sql in (
            f"SELECT * FROM read_text('{secret}')",
            f"SELECT * FROM ST_Read('{secret}')",
            "SELECT * FROM read_csv('https://example.com/x.csv')",
        ):
            with pytest.raises(ValueError):
                warehouse.query(sql)


async def test_a_failed_load_keeps_the_old_table(
    tmp_path: Path, idrogeo: IdroGEO, monkeypatch: pytest.MonkeyPatch
) -> None:
    with await _synced(tmp_path, idrogeo, ["frane_piff"]) as warehouse:
        before = warehouse.layers()
        monkeypatch.setattr(warehouse, "_select", lambda name, shp: "SELECT no_such_column")
        folder = next(tmp_path.glob("frane_piff_molise*/"))
        with pytest.raises(duckdb.Error):
            warehouse._load("frane_piff", folder, "molise", "new")
        assert warehouse.layers() == before  # rolled back, still 4 rows
        assert warehouse.landslides_in()["landslides"] == 4


def test_encoding(tmp_path: Path) -> None:
    shp = tmp_path / "layer.shp"
    assert wh._encoding(shp) == ""
    shp.with_suffix(".cst").write_text("ISO-8859-1\n")
    assert wh._encoding(shp) == ", open_options = ['ENCODING=ISO-8859-1']"
    shp.with_suffix(".cpg").write_text("UTF-8")
    assert "UTF-8" in wh._encoding(shp)  # .cpg first
    shp.with_suffix(".cpg").write_text("x'); DROP TABLE t; --")
    shp.with_suffix(".cst").unlink()
    assert wh._encoding(shp) == ""
    assert wh._quote(Path("/a/b'c")) == "/a/b''c"
