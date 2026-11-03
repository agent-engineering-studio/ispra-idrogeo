from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from ispra_idrogeo import (
    IdrogeoError,
    level_codes,
    lookup_params,
    parse,
    parse_list,
    search_params,
    since_filter,
    summary_path,
)


def test_summary_paths() -> None:
    assert summary_path("iffi", "italia") == "iffi/italia"
    assert summary_path("pir", "regioni", 16) == "pir/regioni/16"
    assert summary_path("iffi", "comuni") == "iffi/comuni"
    assert summary_path("iffi", "macroregioni", 4) == "iffi/macroregioni/4"
    with pytest.raises(ValueError, match="no code"):
        summary_path("iffi", "italia", 1)
    with pytest.raises(ValueError, match="no list"):
        summary_path("pir", "macroregioni")


def test_level_codes() -> None:
    assert level_codes("comuni", [{"pro_com": 72006}, {"pro_com": "1001"}]) == [72006, 1001]
    assert level_codes("regioni", [{"cod_reg": 16}]) == [16]
    assert level_codes("province", []) == []
    with pytest.raises(ValueError, match="no list"):
        level_codes("italia", [])
    with pytest.raises(IdrogeoError, match="pro_com"):
        level_codes("comuni", [{"nome": "Bari"}])


def test_since_filter() -> None:
    since = datetime(2026, 11, 1, tzinfo=UTC)
    assert since_filter(None, None) == {}
    assert since_filter({"regione": "eq.16"}, None) == {"regione": "eq.16"}
    assert since_filter({"regione": "eq.16"}, since) == {
        "regione": "eq.16",
        "modified": "gte.2026-11-01T00:00:00+00:00",
    }
    rome = timezone(timedelta(hours=1))
    assert since_filter(None, datetime(2026, 11, 1, 1, tzinfo=rome)) == {
        "modified": "gte.2026-11-01T01:00:00+01:00"
    }
    filters = {"tipo_movimento": 6}
    since_filter(filters, since)
    assert filters == {"tipo_movimento": 6}  # not changed in place
    with pytest.raises(ValueError, match="time zone"):
        since_filter(None, datetime(2026, 11, 1))
    with pytest.raises(ValueError, match="not both"):
        since_filter({"modified": "gte.2026-01-01"}, since)


def test_lookup_params() -> None:
    assert lookup_params("formazioni", " argille ", 5) == {"q": "argille", "limit": "5"}
    with pytest.raises(ValueError, match="unknown list"):
        lookup_params("frane", "x", 5)
    with pytest.raises(ValueError, match="some text"):
        lookup_params("voli", "  ", 5)
    with pytest.raises(ValueError, match="limit"):
        lookup_params("voli", "1954", 0)


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
    assert parse(200, b"null") is None  # a JSON null is an answer, not an error


def test_parse_list() -> None:
    assert parse_list(200, b'[{"id_frana": "1"}]') == [{"id_frana": "1"}]
    with pytest.raises(IdrogeoError, match="expected a list"):
        parse_list(200, b"{}")
