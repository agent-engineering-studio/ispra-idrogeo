"""How well the number checks catch unfaithful answers, offline and free.

    python -m benchmarks.faithful            # the table
    python -m benchmarks.faithful --record   # write faithful.json
    python -m benchmarks.faithful --check    # exit 1 if anything differs from faithful.json

Every answer in ``faithful.toml`` is labeled by hand with the numbers a
careful reader would flag. An answer is caught when a check flags exactly
those numbers (nothing, for a faithful one). ``check_text`` alone asks
"does this number exist?"; with ``check_claims`` it also asks "is it said
of the right thing?". No model and no network: it runs in CI.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ispra_idrogeo.grounding import check_claims, check_text

HERE = Path(__file__).parent
CASES = HERE / "faithful.toml"
RESULTS = HERE / "faithful.json"
CLASSES = ("faithful", "approximate", "question", "rounded", "invented", "swapped")


def flagged(answer: dict[str, Any], facts: dict[str, Any], claims: bool) -> list[str]:
    """The numbers a check flags in one answer, in order, without repeats."""
    found = check_text(answer["text"], facts, question=answer.get("question", ""))
    if claims:
        found += [m.said for m in check_claims(answer["text"], facts)]
    return list(dict.fromkeys(found))


def score(path: Path = CASES) -> dict[str, dict[str, str]]:
    """For each check and class: answers caught out of answers, as ``"x/y"``."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    facts, answers = data["facts"], data["answer"]
    out: dict[str, dict[str, str]] = {}
    for name, claims in (("check_text", False), ("check_text + check_claims", True)):
        right: Counter[str] = Counter()
        total: Counter[str] = Counter()
        for answer in answers:
            total[answer["class"]] += 1
            right[answer["class"]] += flagged(answer, facts, claims) == answer.get("flag", [])
        out[name] = {c: f"{right[c]}/{total[c]}" for c in CLASSES if total[c]}
    return out


def table(results: dict[str, dict[str, str]]) -> str:
    rows = [f"{'class':<12} " + " ".join(f"{n:>26}" for n in results)]
    for c in CLASSES:
        rows.append(f"{c:<12} " + " ".join(f"{r.get(c, '-'):>26}" for r in results.values()))
    return "\n".join(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.faithful")
    parser.add_argument("--record", action="store_true", help="write faithful.json")
    parser.add_argument("--check", action="store_true", help="compare with faithful.json")
    args = parser.parse_args(argv)
    results = score()
    print(table(results))
    if args.record:
        RESULTS.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    if args.check:
        recorded = json.loads(RESULTS.read_text(encoding="utf-8"))
        if recorded != results:
            print("differs from faithful.json: re-record it if the change is wanted")
            return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
