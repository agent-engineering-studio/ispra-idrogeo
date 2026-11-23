from typing import Any

import pytest
from starlette.testclient import TestClient

from app import api
from app.data import (
    Cache,
    Data,
    UnavailableError,
    dated_features,
    panel,
    region_of,
)
from ispra_idrogeo import IdroGEO, IdrogeoError
from ispra_idrogeo.dated import from_iffi
from ispra_idrogeo.report import notes_it

PIR = {
    "nome": "Sarno",
    "extent": [[14.5, 40.7], [14.7, 40.9]],
    "ar_frp3p4p": 43.4,
    "aridp2_p": 6.0,
    "pop_res021": 30652,
    "ed_idr_p2": -1,
}
IFFI = {
    "nome": "Sarno",
    "frane_totali": 53,
    "eventi_totali": 2,
    "frane_monitorate": 1,
    "breadcrumb": [{"id": 4, "name": "Sud", "t": "m"}, {"id": 15, "name": "Campania", "t": "r"}],
    "frane_stats": [
        {"cod": 5, "nr_frane": 39},
        {"cod": 2, "nr_frane": 14},
        {"cod": 1, "nr_frane": 0},
    ],
}


def test_panel() -> None:
    found = panel(65135, PIR, IFFI, {"5": "Colamento rapido", "2": "Scivolamento"})
    assert found["name"] == "Sarno" and found["region"] == 15
    assert found["predisposition"]["landslide"]["label"] == "molto alta"
    assert found["predisposition"]["flood"]["label"] == "media"
    exposure = {e["key"]: e["value"] for e in found["exposure"]}
    assert exposure["pop_res021"] == 30652 and exposure["ed_idr_p2"] is None  # -1: not available
    assert [t["type"] for t in found["iffi"]["by_type"]] == ["Colamento rapido", "Scivolamento"]
    assert found["reliability"]["notes"][0].endswith("hanno una data al giorno.")
    assert "CC BY-SA 4.0" in found["citations"]["iffi"]
    none = panel(1, {}, {}, {})
    assert none["region"] is None and none["predisposition"]["flood"]["label"] == "non disponibile"
    assert none["reliability"] is None


def test_notes_in_italian() -> None:
    base = {
        "landslides": 1234,
        "day_share": 0.0004,
        "edited_since_2021_share": 0.5,
        "dated_since_2018": 0,
        "iffi_day_since_2018": 0,
        "events_since_2018": 0,
        "events_within_1km": 0,
    }
    notes = notes_it(base)
    assert notes[0] == "0 frane IFFI su 1.234 (meno dello 0,1%) hanno una data al giorno."
    assert notes[1] == "Record IFFI modificati dal 2021: 50,0%."
    assert "nessun dato può verificare" in notes[2]
    empty = notes_it(
        {
            **base,
            "landslides": 0,
            "dated_since_2018": 3,
            "events_since_2018": 3,
            "edited_since_2021_share": None,
        }
    )
    assert empty[0].startswith("In questo Comune IFFI non censisce") and empty[1].startswith(
        "Dal 2018"
    )
    assert region_of({"breadcrumb": [{"id": 9, "t": "p"}]}) is None


def test_dated_features_keep_the_municipality() -> None:
    here = from_iffi(
        {"id_frana": "1", "data_certa": "2019-11-12", "comune": 7, "point": [14.6, 40.8]}
    )
    elsewhere = from_iffi(
        {"id_frana": "2", "data_certa": "2019-11-12", "comune": 8, "point": [1, 2]}
    )
    nowhere = from_iffi({"id_frana": "3", "data_certa": "2019-11-12", "comune": 7})
    found = dated_features([d for d in (here, elsewhere, nowhere) if d], 7)
    assert [f["properties"]["id"] for f in found] == ["1"]
    assert found[0]["geometry"]["coordinates"] == [14.6, 40.8]


async def test_cache_keeps_answers_for_a_while() -> None:
    now = [0.0]
    calls = []

    async def make() -> int:
        calls.append(1)
        return len(calls)

    cache = Cache(10, clock=lambda: now[0])
    assert await cache.get("k", make) == 1 and await cache.get("k", make) == 1
    now[0] = 11
    assert await cache.get("k", make) == 2


def test_settings() -> None:
    found = api.settings(
        {"IDROGEO_COMUNE": "72006", "IDROGEO_ENTE": "Comune di Bari", "IDROGEO_APP_LOAD": "0"}
    )
    assert (found["comune"], found["ente"], found["load"]) == (72006, "Comune di Bari", False)
    assert api.settings({"IDROGEO_COMUNE": "x"})["comune"] == 65135
    assert "openstreetmap" in api.settings({"IDROGEO_TILES": ""})["tiles"]  # empty from compose


class FakeData(Data):
    def __init__(self) -> None:
        super().__init__(IdroGEO())
        self.state = {"warehouse": "loading", "layers": {}}

    async def find(self, text: str, limit: int = 10) -> list[dict[str, Any]]:
        return [{"code": 65135, "name": "Sarno"}]

    async def panel(self, code: int) -> dict[str, Any]:
        if code == 1:
            raise IdrogeoError("unknown")
        return panel(code, PIR, IFFI, {})

    async def landslides(self, code: int) -> dict[str, Any]:
        raise UnavailableError("warehouse loading")

    async def dated(self, code: int) -> dict[str, Any]:
        return {"type": "FeatureCollection", "features": []}

    async def contract(self) -> dict[str, Any]:
        return {"ok": True, "checks": [], "checked_at": "now"}


def test_routes() -> None:
    config = {**api.settings({}), "load": False}
    with TestClient(api.create_app(FakeData(), config)) as client:
        assert client.get("/api/health").json()["warehouse"]["warehouse"] == "loading"
        found = client.get("/api/config").json()
        assert found["comune"] == 65135 and "bollettino" in found["bulletin"]
        assert "non è un'allerta" not in found["note"] and "non usa la pioggia" in found["note"]
        assert "not an alert" in found["note_en"] and found["thresholds"][0] == [30.0, "very high"]
        assert client.get("/api/find?q=s").json() == []  # too short
        assert client.get("/api/find?q=sarno").json()[0]["code"] == 65135
        assert client.get("/api/comune/65135").json()["name"] == "Sarno"
        assert client.get("/api/comune/1").status_code == 502
        assert client.get("/api/comune/65135/iffi.geojson").status_code == 503
        assert client.get("/api/comune/65135/dated.geojson").json()["features"] == []
        assert client.get("/api/contract").json()["ok"] is True
        csv = client.get("/api/comune/65135/dati.csv")
        assert csv.headers["content-type"].startswith("text/csv") and "non è un'allerta" in csv.text
        assert "comune-65135.csv" in csv.headers["content-disposition"]
        assert client.get("/api/comune/1/dati.csv").status_code == 502
        page = client.get("/")
        assert "<html" in page.text and page.headers["cache-control"] == "no-cache"
        assert client.get("/app.js").headers["cache-control"] == "no-cache"  # updates show at once


async def test_layers_wait_for_the_warehouse() -> None:
    data = Data(IdroGEO())
    with pytest.raises(UnavailableError, match="not started"):
        await data.landslides(65135)
    await data.idrogeo.aclose()
