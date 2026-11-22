"""Run every method on every known case, offline, from the cassettes.

    python -m benchmarks.run              # the table
    python -m benchmarks.run --markdown   # the same, for the README
    python -m benchmarks.run --record     # write results.json
    python -m benchmarks.run --check      # exit 1 if anything differs from results.json

``--check`` runs in CI: a new answer, a changed case or a changed method is
always a visible decision (re-record results.json), never an accident.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tomllib
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from benchmarks.cassettes import Replayer
from benchmarks.methods import METHODS, Method
from ispra_idrogeo import IdroGEO

HERE = Path(__file__).parent
RESULTS = HERE / "results.json"
Outcome = str  # "pass", "fail" or "error: …"


def load_cases(path: Path = HERE / "cases.toml") -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = tomllib.loads(path.read_text(encoding="utf-8"))["case"]
    return cases


async def answer(method: Method, idrogeo: IdroGEO, check: dict[str, Any]) -> Any:
    """What ``method`` answers to one check."""
    kind = check["kind"]
    if kind == "hazard":
        return list(await method.hazard(idrogeo, check["lat"], check["lon"]))
    if kind == "count":
        return await method.count(idrogeo, check["level"], check["code"])
    if kind == "events":
        start, end = check["start"], check["end"]
        assert isinstance(start, date) and isinstance(end, date)
        return await method.events(idrogeo, check["municipality"], start, end)
    if kind == "near":
        return await method.near(idrogeo, check["lat"], check["lon"], check["radius_m"])
    if kind == "search":
        return len(await method.search(idrogeo))
    if kind == "reliability":
        return method.reliability(check["level"], check["code"], check["field"])
    raise ValueError(f"unknown kind {kind!r}")


def judge(check: dict[str, Any], got: Any) -> bool:
    """Whether an answer is the one the case expects."""
    kind = check["kind"]
    if kind == "hazard":
        return bool(got == [check["landslide"], check["flood"]])
    if kind == "count":
        return bool(got == check["landslides"])
    if kind == "events":
        first = check.get("first")
        return len(got) == check["events"] and (first is None or bool(got and got[0] == first))
    if kind == "near":
        return bool(got >= check["at_least"])
    if kind == "search":
        return bool(got > 0) is bool(check["works"])
    if kind == "reliability":
        return got is not None and bool(check["min"] <= got <= check["max"])
    raise ValueError(f"unknown kind {kind!r}")


async def run_case(method: Method, case: dict[str, Any]) -> dict[str, Outcome]:
    """Every check of a case, with a fresh client replaying the case's cassette."""
    cassette = HERE / "cassettes" / f"{case['id']}.json"
    transport: httpx.AsyncBaseTransport = (
        Replayer(case["id"]) if cassette.exists() else httpx.MockTransport(_offline)
    )
    outcomes: dict[str, Outcome] = {}
    async with httpx.AsyncClient(transport=transport) as client:
        idrogeo = IdroGEO(client, retries=0)
        for check in case["check"]:
            try:
                got = await answer(method, idrogeo, check)
            except Exception as exc:  # an error is an outcome too
                outcomes[check["name"]] = f"error: {type(exc).__name__}"
                continue
            outcomes[check["name"]] = "pass" if judge(check, got) else "fail"
    return outcomes


def _offline(request: httpx.Request) -> httpx.Response:
    return httpx.Response(599, text="no cassette for this case", request=request)


async def run(cases: Sequence[dict[str, Any]]) -> dict[str, dict[str, Outcome]]:
    """``{method: {"case · check": outcome}}``."""
    results: dict[str, dict[str, Outcome]] = {}
    for method in METHODS:
        mine: dict[str, Outcome] = {}
        for case in cases:
            for name, outcome in (await run_case(method, case)).items():
                mine[f"{case['id']} · {name}"] = outcome
        results[method.name] = mine
    return results


def score(cases: Sequence[dict[str, Any]], outcomes: dict[str, Outcome]) -> str:
    """``confirmed: x/y · known-gap: x/y``."""
    parts = []
    for status in ("confirmed", "known-gap"):
        keys = [
            f"{c['id']} · {k['name']}" for c in cases if c["status"] == status for k in c["check"]
        ]
        if keys:
            passed = sum(outcomes.get(k) == "pass" for k in keys)
            parts.append(f"{status}: {passed}/{len(keys)}")
    return " · ".join(parts)


def table(cases: Sequence[dict[str, Any]], results: dict[str, dict[str, Outcome]]) -> str:
    """A Markdown table: one row per check, one column per method."""
    names = list(results)
    mark = {"pass": "✅", "fail": "❌"}
    lines = ["| case | check | " + " | ".join(names) + " |", "|---|---|" + "---|" * len(names)]
    for case in cases:
        for check in case["check"]:
            key = f"{case['id']} · {check['name']}"
            cells = [
                mark.get(results[n].get(key, ""), "⚠️ " + results[n].get(key, "")) for n in names
            ]
            lines.append(f"| {case['id']} | {check['name']} | " + " | ".join(cells) + " |")
    lines.append("| **score** | | " + " | ".join(score(cases, results[n]) for n in names) + " |")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    top = argparse.ArgumentParser(prog="python -m benchmarks.run", description=__doc__)
    top.add_argument("--markdown", action="store_true", help="print the Markdown table only")
    top.add_argument("--record", action="store_true", help="write results.json")
    top.add_argument("--check", action="store_true", help="exit 1 on any difference")
    args = top.parse_args(argv)
    cases = load_cases()
    results = asyncio.run(run(cases))
    if args.record:
        RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(table(cases, results))
    if args.check:
        known = json.loads(RESULTS.read_text(encoding="utf-8"))
        if known != results:
            for method in sorted(set(known) | set(results)):
                for key in sorted(set(known.get(method, {})) | set(results.get(method, {}))):
                    was, now = known.get(method, {}).get(key), results.get(method, {}).get(key)
                    if was != now:
                        print(f"changed: {method} · {key}: {was} -> {now}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
