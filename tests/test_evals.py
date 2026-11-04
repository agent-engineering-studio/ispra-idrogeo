"""The agent eval's grader, runner and report, offline: no API, no network."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from evals import report, run
from evals.cases import CASES, Case
from evals.grade import grade, normalize, parse_number


def _oracle(case: Case, truth: Any) -> dict[str, Any]:
    """The submission a perfect agent would make."""
    if case.kind == "abstain":
        answer, status = "", "not_available"
    elif truth is None:
        answer, status = "none", "answered"
    elif isinstance(truth, tuple):
        answer, status = truth[-1], "answered"
    else:
        answer, status = str(truth), "answered"
    notes = "Non è una valutazione di sicurezza: rivolgersi alle autorità." if case.caveat else ""
    return {
        "answer": answer,
        "status": status,
        "unit": "",
        "source": "ISPRA IdroGEO",
        "notes": notes,
    }


#: Plausible truths of the kinds the cases produce, without the network.
TRUTHS: dict[str, Any] = {
    "count": 4037,
    "number": 12.5,
    "percent": 89.641,
    "class": "P4",
    "text": ("Colamento rapido", "rapid debris flow"),
    "abstain": None,
}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_the_oracle_passes_every_case(case: Case) -> None:
    truth = None if case.id == "point-bari-cathedral" else TRUTHS[case.kind]
    scores, why = grade(case, truth, _oracle(case, truth))
    assert scores == {"correct": 1.0, "cited_source": 1.0}, why


@pytest.mark.parametrize("answer", ["", "0", "I don't know", "P1", "Roma"])
def test_null_answers_fail(answer: str) -> None:
    for case in CASES:
        truth = TRUTHS[case.kind] if case.kind != "abstain" else None
        if case.id == "point-bari-cathedral":
            truth = None
        submission = {"answer": answer, "status": "answered", "source": "", "notes": ""}
        scores, _ = grade(case, truth, submission)
        assert scores["correct"] == 0.0, case.id
        assert scores["cited_source"] == 0.0


def test_no_submission_and_wrong_status() -> None:
    count = next(c for c in CASES if c.kind == "count")
    assert grade(count, 10, None)[0] == {"correct": 0.0, "cited_source": 0.0}
    assert grade(count, 10, {"answer": "10", "status": "not_available"})[0]["correct"] == 0.0


def test_the_caveat_is_required() -> None:
    house = next(c for c in CASES if c.caveat)
    bare = {"answer": "P4", "status": "answered", "source": "ISPRA", "notes": "È in P4."}
    scores, why = grade(house, "P4", bare)
    assert scores["correct"] == 0.0 and "caveat" in why["correct"]


@pytest.mark.parametrize(
    ("kind", "truth", "answer", "ok"),
    [
        ("count", 1284960, "1.28 million", True),  # within 0.5%
        ("count", 1284960, "1,29 milioni", True),
        ("count", 1284960, "1.2 milioni", False),
        ("count", 921, "921 frane", True),
        ("count", 921, "920", False),  # small counts are exact
        ("count", 24589, "24.589", True),
        ("percent", 89.641, "89,6%", True),
        ("percent", 89.641, "89,641", True),
        ("percent", 89.641, "0.8964", True),  # as a fraction
        ("percent", 9.533, "9.6", False),
    ],
)
def test_numbers(kind: str, truth: float, answer: str, ok: bool) -> None:
    case = Case("x", ("t", "it"), "?", kind, CASES[0].truth)  # type: ignore[arg-type]
    assert grade(case, truth, {"answer": answer, "status": "answered"})[0]["correct"] == float(ok)


def test_classes_and_names() -> None:
    point = Case("x", ("point", "en"), "?", "class", CASES[0].truth)
    name = Case("y", ("rank", "en"), "?", "text", CASES[0].truth)
    for answer, truth, ok in (
        ("P4 (molto elevata)", "P4", True),
        ("P3, also P2 and P1", "P3", True),
        ("P2", "P3", False),
        ("none", None, True),
        ("Nessuna", None, True),
        ("P1", None, False),
    ):
        assert grade(point, truth, {"answer": answer, "status": "answered"})[0]["correct"] == ok
    assert grade(name, "Forlì", {"answer": "forli", "status": "answered"})[0]["correct"]
    assert grade(
        name, "Sant'Agata de' Goti", {"answer": "Sant Agata de Goti", "status": "answered"}
    )[0]["correct"]
    assert not grade(
        name,
        "Bari",
        {
            "answer": "Bari, Altamura, Molfetta, Trani, Monopoli, Bitonto, Gravina",
            "status": "answered",
        },
    )[0]["correct"]
    assert normalize("L'Aquila") == "aquila" and parse_number("nessun numero") is None


# The runner, with a fake model and fake MCP tools


def _response(content: list[Any], stop: str = "tool_use", model: str = "claude-sonnet-5-5") -> Any:
    usage = SimpleNamespace(
        input_tokens=1000,
        output_tokens=100,
        cache_read_input_tokens=500,
        cache_creation_input_tokens=0,
    )
    return SimpleNamespace(model=model, stop_reason=stop, usage=usage, content=content)


def _use(name: str, arguments: dict[str, Any], n: int = 0) -> Any:
    return SimpleNamespace(type="tool_use", name=name, input=arguments, id=f"toolu_{n}")


def _text(text: str) -> Any:
    return SimpleNamespace(type="text", text=text)


class FakeClaude:
    """Plays a scripted list of responses per case question."""

    def __init__(self, scripts: dict[str, list[Any]], delay: float = 0) -> None:
        self.scripts = {q: list(r) for q, r in scripts.items()}
        self.delay = delay
        self.requests: list[dict[str, Any]] = []
        self.messages = self

    async def create(self, **request: Any) -> Any:
        self.requests.append(request)
        await asyncio.sleep(self.delay)
        return self.scripts[request["messages"][0]["content"]].pop(0)


class FakeTools:
    instructions = "IdroGEO instructions."

    def __init__(self) -> None:
        self.called: list[str] = []

    async def list(self) -> list[dict[str, Any]]:
        return [{"name": "area_risk", "description": "risk", "input_schema": {"type": "object"}}]

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        self.called.append(name)
        if arguments.get("boom"):
            raise RuntimeError("tool broke")
        return '{"pop_idr_p2": 4037}', False


def _connect(tools: FakeTools) -> run.Connect:
    @asynccontextmanager
    async def connect() -> AsyncIterator[run.Tools]:
        yield tools

    return connect


async def _truth_4037(_idrogeo: Any) -> int:
    return 4037


async def _broken_truth(_idrogeo: Any) -> int:
    raise RuntimeError("IdroGEO down")


CASE = Case("bari", ("area-risk", "it"), "Residenti di Bari in P2?", "count", _truth_4037)
TRAP = Case("paris", ("trap", "it"), "Parigi?", "abstain", _truth_4037, why="outside")


def _submit(answer: str, status: str = "answered", n: int = 9) -> Any:
    arguments = {
        "answer": answer,
        "status": status,
        "unit": "",
        "source": "ISPRA IdroGEO",
        "notes": "",
    }
    return _use("submit_answer", arguments, n)


async def test_a_case_runs_end_to_end(tmp_path: Path) -> None:
    tools = FakeTools()
    claude = FakeClaude(
        {
            CASE.question: [
                _response([_text("Let me look."), _use("area_risk", {"code": 72006}, 1)]),
                _response([_submit("4037")]),
            ],
            TRAP.question: [_response([_submit("", "not_available")])],
        }
    )
    options = run.Options(flow=tmp_path, cases=[CASE, TRAP], concurrency=2)
    folder = await run.run(claude, _connect(tools), None, options, log=lambda _: None)  # type: ignore[arg-type]
    rows = {r["prompt_id"]: r for r in run._rows(folder / "results.jsonl")}
    bari = rows["bari"]
    assert (
        bari["grade"] == {"correct": 1.0, "cited_source": 1.0} and rows["paris"]["grade"]["correct"]
    )
    assert (bari["status"], bari["model"], bari["tool_calls"], bari["turns"]) == (
        "ok",
        "claude-sonnet-5-5",
        1,
        2,
    )
    assert bari["usage"] == {
        "input_tokens": 2000,
        "output_tokens": 200,
        "cache_read_input_tokens": 1000,
        "cache_creation_input_tokens": 0,
    }
    trace = json.loads((folder / "traces" / "bari_rep0.json").read_text())
    assert [t["role"] for t in trace] == [
        "system",
        "user",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
    ]
    assert "IdroGEO instructions." in trace[0]["content"] and tools.called == ["area_risk"]
    request = claude.requests[0]
    assert request["model"] == "claude-sonnet-5-5" and request["cache_control"] == {
        "type": "ephemeral"
    }
    assert request["tools"][-1]["name"] == "submit_answer" and request["output_config"] == {
        "effort": "medium"
    }
    assert json.loads((tmp_path / "_state.json").read_text())["metrics"][0]["id"] == "correct"
    # A second run resumes: nothing left to do, no request sent.
    before = len(claude.requests)
    await run.run(claude, _connect(tools), None, options, log=lambda _: None)  # type: ignore[arg-type]
    assert len(claude.requests) == before


async def test_failures_go_to_the_errors_sidecar(tmp_path: Path) -> None:
    slow = Case("slow", ("t", "en"), "slow?", "count", _truth_4037)
    other = Case("other", ("t", "en"), "other model?", "count", _truth_4037)
    down = Case("down", ("t", "en"), "down?", "count", _broken_truth)
    claude = FakeClaude(
        {
            "slow?": [_response([_submit("4037")])],
            "other model?": [_response([_submit("4037")], model="claude-haiku-5-5")],
        },
        delay=0.2,
    )
    options = run.Options(flow=tmp_path, cases=[slow, other, down], timeout_s=0.1)
    folder = await run.run(claude, _connect(FakeTools()), None, options, log=lambda _: None)  # type: ignore[arg-type]
    errors = {e["prompt_id"]: e["kind"] for e in run._rows(folder / "errors.jsonl")}
    assert errors == {"slow": "timeout", "other": "timeout", "down": "harness_or_serving"}
    assert run._rows(folder / "results.jsonl") == []  # nothing to grade, nothing scored as 0
    claude.delay = 0
    options.timeout_s = 5
    options.cases = [other]
    await run.run(claude, _connect(FakeTools()), None, options, log=lambda _: None)  # type: ignore[arg-type]
    kinds = [e["kind"] for e in run._rows(folder / "errors.jsonl")]
    assert kinds[-1] == "model_mismatch"


async def test_what_the_model_does_wrong_is_graded(tmp_path: Path) -> None:
    silent = Case("silent", ("t", "en"), "silent?", "count", _truth_4037)
    refuses = Case("refuses", ("t", "en"), "refuses?", "count", _truth_4037)
    breaks = Case("breaks", ("t", "en"), "breaks?", "count", _truth_4037)
    claude = FakeClaude(
        {
            "silent?": [
                _response([_text("4037")], "end_turn"),
                _response([_text("4037")], "end_turn"),
            ],
            "refuses?": [_response([_text("No.")], "refusal")],
            "breaks?": [
                _response([_use("area_risk", {"boom": True}, 1)]),
                _response([_submit("4037")]),
            ],
        }
    )
    options = run.Options(flow=tmp_path, cases=[silent, refuses, breaks])
    folder = await run.run(claude, _connect(FakeTools()), None, options, log=lambda _: None)  # type: ignore[arg-type]
    rows = {r["prompt_id"]: r for r in run._rows(folder / "results.jsonl")}
    assert rows["silent"]["meta"]["nudged"] and rows["silent"]["grade"]["correct"] == 0.0
    assert rows["silent"]["explanation"]["correct"] == "no submit_answer call"
    assert rows["refuses"]["status"] == "refusal"
    assert rows["breaks"]["grade"]["correct"] == 1.0
    trace = json.loads((folder / "traces" / "breaks_rep0.json").read_text())
    assert "RuntimeError: tool broke" in trace[3]["content"]
    text = report.write_report(tmp_path).read_text()
    assert "correct: 2/2" not in text and "## baseline" in text
    assert "not scored: 1 (truncated or refused)" in text and "$" in text


def test_report_numbers() -> None:
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
        "cache_read_input_tokens": 1_000_000,
    }
    assert report.cost("claude-sonnet-5-5", usage) == pytest.approx(2.0 + 1.0 + 0.2)
    assert report.cost("someone-else", usage) is None
    low, high = report.wilson(5, 5)
    assert high == 1.0 and 0.5 < low < 0.6
    assert report.wilson(0, 0) == (0.0, 0.0)


def test_command_line() -> None:
    pilot = run.options(["--limit", "5", "--api-key", "sk-test"])
    assert len(pilot.cases) == 5 and pilot.api_key == "sk-test"
    assert len({c.tags[0] for c in pilot.cases}) == 5  # one of each kind first
    one = run.options(["--case", "iffi-sarno", "--model", "claude-opus-5-5"])
    assert [c.id for c in one.cases] == ["iffi-sarno"] and one.model == "claude-opus-5-5"


def test_the_key_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    assert run.options([]).api_key == "sk-from-env"
    assert run.options(["--api-key", "sk-flag"]).api_key == "sk-flag"  # the flag wins
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert run.options([]).api_key is None  # the SDK's own chain then
