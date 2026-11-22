import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from benchmarks import cassettes, run
from benchmarks.methods import METHODS


def test_the_known_cases_still_give_the_recorded_results() -> None:
    assert run.main(["--check"]) == 0  # offline, from the cassettes


def test_every_check_tells_right_from_wrong() -> None:
    results = json.loads(run.RESULTS.read_text(encoding="utf-8"))
    library, constant = (results[m.name] for m in METHODS)
    assert set(library.values()) == {"pass"}
    assert sum(v == "pass" for v in constant.values()) <= 1  # only "no event yet" at Melito


async def test_a_case_without_a_cassette_is_an_error() -> None:
    case = {
        "id": "nowhere",
        "status": "confirmed",
        "check": [{"kind": "count", "name": "n", "level": "comuni", "code": 1, "landslides": 1}],
    }
    assert await run.run_case(METHODS[0], case) == {"n": "error: IdrogeoError"}


async def test_unknown_kinds_and_unseen_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        await run.answer(METHODS[0], None, {"kind": "nope"})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unknown kind"):
        run.judge({"kind": "nope"}, None)
    monkeypatch.setattr(cassettes, "FOLDER", tmp_path)
    (tmp_path / "x.json").write_text(
        json.dumps(
            {
                "recorded_on": "d",
                "entries": [
                    {"request": "GET a/b?", "status": 200, "content_type": "", "base64": "aGk="}
                ],
            }
        )
    )
    replayer = cassettes.Replayer("x")
    async with httpx.AsyncClient(transport=replayer) as client:
        assert (await client.get("http://a/b")).content == b"hi"
        assert (await client.get("http://a/c")).status_code == 599
    assert replayer.unseen == ["GET a/c?"]


def test_the_table_has_a_score_row() -> None:
    cases: list[dict[str, Any]] = [
        {"id": "c", "status": "known-gap", "check": [{"name": "n"}]},
    ]
    text = run.table(cases, {"m": {"c · n": "error: X"}})
    assert "⚠️ error: X" in text and "known-gap: 0/1" in text
