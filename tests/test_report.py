from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from ispra_idrogeo import IdroGEO, cli
from ispra_idrogeo.report import (
    UngroundedError,
    area_report,
    find_municipality,
    render,
    share_it,
    summarize,
)

PIR = {
    "nome": "Sarno",
    "pop_res021": 30652,
    "ar_frp3p4p": 43.04,
    "popfr_p3p4": 2345,
    "popfrp3p4p": 7.65,
    "ed_fr_p3p4": 612,
    "aridp2_p": 3.2,
    "pop_idr_p2": 1500,
    "popidp2_p": 4.89,
    "ed_idr_p2": -1,  # not available
}
IFFI = {"nome": "Sarno", "frane_totali": 53, "eventi_totali": 2}
NOW = "2026-11-23T10:00:00Z"


def _server(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api/")
    if path == "pir/comuni/65135":
        return httpx.Response(200, json=PIR)
    if path == "pir/comuni/99999":
        return httpx.Response(200, json={"nome": "Nuovo"})
    if path == "iffi/comuni/99999":
        return httpx.Response(200, json={})
    if path == "iffi/comuni/65135":
        return httpx.Response(200, json=IFFI)
    if path == "iffi/comuni":
        names = [(65135, "Sarno"), (1, "Sarnano"), (2, "Sàrnico"), (3, "Sarnico")]
        return httpx.Response(200, json=[{"uid": u, "nome": n} for u, n in names])
    return httpx.Response(404)


def _idrogeo() -> IdroGEO:
    return IdroGEO(httpx.AsyncClient(transport=httpx.MockTransport(_server)))


def test_the_report_says_the_figures_and_what_it_is_not() -> None:
    from ispra_idrogeo.reliability import reliability

    report = render(65135, PIR, IFFI, reliability("comuni", 65135).as_dict(), NOW)
    text = report.text
    assert text.startswith("# Sarno: i dati di IdroGEO")
    assert "Residenti: 30.652 (censimento 2021)." in text
    assert "territorio 43,0%; residenti 2.345 (7,7% del totale); edifici 612." in text
    assert "edifici non disponibile." in text  # -1 is never zero
    assert "frana molto alta, alluvione bassa" in text
    assert "non è un'allerta" in text and "Protezione Civile" in text
    assert "Non misurato:" in text and "CC BY-SA 4.0" in text and "CC BY 4.0" in text
    assert report.markdown() == text  # no summary


def test_the_report_says_where_the_inventory_is_thin() -> None:
    from ispra_idrogeo.reliability import THIN, reliability_map

    table = reliability_map()
    thin = next(
        r
        for r in table.all("comuni")
        if r.province_vs_italy is not None and r.province_vs_italy < THIN
    )
    text = render(thin.code, PIR, IFFI, thin.as_dict(), NOW).text  # every number is checked
    said = f"{thin.province_per_hazard_km2:.1f}".replace(".", ",")
    assert (
        f"In questa provincia poche frane censite per il pericolo mappato: {said} per km²" in text
    )
    assert "non che le frane sono poche" in text
    # Sarno has few records for its wide hazard map, in a province that has many: no note
    sarno = table.at("comuni", 65135)
    assert sarno.vs_italy is not None and sarno.vs_italy < THIN
    assert "poche frane censite" not in render(65135, PIR, IFFI, sarno.as_dict(), NOW).text


def test_a_municipality_without_reliability() -> None:
    text = render(1, {"nome": "X"}, {}, None, NOW).text
    assert "Affidabilità: non disponibile" in text
    assert "Residenti: non disponibile" in text


def test_a_template_number_not_in_the_facts_is_refused() -> None:
    with pytest.raises(UngroundedError) as found:
        render(65135, {**PIR, "nome": "Sarno 99"}, IFFI, None, NOW)  # a number in the name
    assert found.value.unmatched == ["99"]


def test_shares() -> None:
    assert (share_it(None), share_it(0.0004), share_it(0.039)) == (
        "non disponibile",
        "meno dello 0,1%",
        "3,9%",
    )


async def test_area_report_and_names() -> None:
    async with _idrogeo() as idrogeo:
        assert await find_municipality(idrogeo, "65135") == 65135
        assert await find_municipality(idrogeo, " sarno ") == 65135
        with pytest.raises(ValueError, match="did you mean Sarnico, Sàrnico"):
            await find_municipality(idrogeo, "Sarnico")  # two, once folded
        with pytest.raises(ValueError, match="no municipality named 'Roma'"):
            await find_municipality(idrogeo, "Roma")
        report = await area_report(idrogeo, 65135)
        assert report.name == "Sarno" and report.facts["pir"]["pop_res021"] == 30652
        new = await area_report(idrogeo, 99999)  # not in the shipped reliability table
        assert new.facts["reliability"] is None and "Affidabilità: non disponibile" in new.text


class _Claude:
    def __init__(self, text: str) -> None:
        self.text, self.asked = text, ""
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw: Any) -> Any:
        self.asked = kw["messages"][0]["content"]
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


def test_the_summary_is_checked_before_it_is_kept() -> None:
    report = render(65135, PIR, IFFI, None, NOW)
    good = _Claude("A Sarno il 43% del territorio è in pericolo frana P3+P4.")
    kept = summarize(report, good)
    assert kept.summary and "non è un'allerta" in good.asked
    assert "**In breve.** A Sarno il 43%" in kept.markdown()
    with pytest.raises(UngroundedError, match=r"12\.000"):
        summarize(report, _Claude("A Sarno 12.000 persone vivono in pericolo frana."))
    with pytest.raises(UngroundedError):  # real number, wrong thing
        summarize(report, _Claude("Sarno ha 2.345 residenti."))


def test_report_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "IdroGEO", _idrogeo)
    out, facts = tmp_path / "sarno.md", tmp_path / "sarno.json"
    assert cli.main(["report", "Sarno", "--out", str(out), "--facts", str(facts)]) == 0
    assert out.read_text().startswith("# Sarno")
    assert json.loads(facts.read_text())["iffi"]["frane_totali"] == 53
    assert cli.main(["report", "65135"]) == 0
    assert "## Fonti" in capsys.readouterr().out
    monkeypatch.setattr(
        "ispra_idrogeo.report.summarize",
        lambda *_: (_ for _ in ()).throw(UngroundedError(["9"], [])),
    )
    assert cli.main(["report", "65135", "--summary", "--out", str(tmp_path / "x.md")]) == 1
    assert not (tmp_path / "x.md").exists()  # nothing written
    assert "numbers not backed by the figures: 9" in capsys.readouterr().err
