from __future__ import annotations

import pytest

from ispra_idrogeo import IdrogeoError, parse, parse_list, search_params, summary_path


def test_summary_paths() -> None:
    assert summary_path("iffi", "italia") == "iffi/italia"
    assert summary_path("pir", "regioni", 16) == "pir/regioni/16"
    assert summary_path("iffi", "comuni") == "iffi/comuni"
    assert summary_path("iffi", "macroregioni", 4) == "iffi/macroregioni/4"
    with pytest.raises(ValueError, match="no code"):
        summary_path("iffi", "italia", 1)
    with pytest.raises(ValueError, match="no list"):
        summary_path("pir", "macroregioni")


def test_search_params() -> None:
    assert search_params(limit=10) == {"limit": "10", "offset": "0"}
    assert search_params(limit=5, offset=10, select=["id_frana", "comune"], order="id_frana") == {
        "limit": "5",
        "offset": "10",
        "select": "id_frana,comune",
        "order": "id_frana",
    }
    with pytest.raises(ValueError):
        search_params(limit=0)
    with pytest.raises(ValueError):
        search_params(limit=1, offset=-1)


def test_parse() -> None:
    assert parse(200, b'{"nome": "Italia"}') == {"nome": "Italia"}
    with pytest.raises(IdrogeoError, match="non trovato"):
        parse(404, b'{"statusCode":404,"message":"Dizionario \'x\' non trovato"}')
    with pytest.raises(IdrogeoError, match="HTTP 502"):
        parse(502, b"<html>bad gateway</html>")
    with pytest.raises(IdrogeoError, match="not return JSON"):
        parse(200, b"<html></html>")


def test_parse_list() -> None:
    assert parse_list(200, b'[{"id_frana": "1"}]') == [{"id_frana": "1"}]
    with pytest.raises(IdrogeoError, match="expected a list"):
        parse_list(200, b"{}")
