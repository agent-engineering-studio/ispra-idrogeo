"""``report.md`` for the agent eval, from the rows on disk: pure, offline.

    uv run python -m evals.report        # rewrites .claude/hillclimb/agent-mcp/report.md

Scores are recomputed from each row's ``grade``; cost from each row's
``model`` and ``usage`` at first-party prices (cache writes 1.25x input,
cache reads 0.1x input).
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

#: $ per million tokens (input, output), first-party API, November 2026.
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.00, 50.00),
}


def cost(model: str | None, usage: dict[str, int]) -> float | None:
    """Dollars for one row; ``None`` for a model without a price here."""
    prices = next((p for m, p in PRICES.items() if str(model).startswith(m)), None)
    if prices is None:
        return None
    rate_in, rate_out = (p / 1e6 for p in prices)
    return (
        usage.get("input_tokens", 0) * rate_in
        + usage.get("cache_creation_input_tokens", 0) * rate_in * 1.25
        + usage.get("cache_read_input_tokens", 0) * rate_in * 0.1
        + usage.get("output_tokens", 0) * rate_out
    )


def wilson(passed: int, n: int) -> tuple[float, float]:
    """The 95% Wilson interval of a pass rate."""
    if n == 0:
        return 0.0, 0.0
    z, p = 1.96, passed / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def summarize(folder: Path) -> list[str]:
    """The markdown of one variant."""
    rows, errors = _rows(folder / "results.jsonl"), _rows(folder / "errors.jsonl")
    scored = [r for r in rows if r.get("status") == "ok"]
    passed = sum(int(r["grade"]["correct"]) for r in scored)
    low, high = wilson(passed, len(scored))
    costs = [c for r in rows if (c := cost(r.get("model"), r.get("usage", {}))) is not None]
    cited = sum(int(r["grade"]["cited_source"]) for r in scored)
    lines = [
        f"## {folder.name}",
        "",
        f"- **correct: {passed}/{len(scored)} = {passed / max(len(scored), 1):.0%}** "
        f"(95% CI {low:.0%}-{high:.0%})",
        f"- cites ISPRA: {cited}/{len(scored)}",
        f"- not scored: {len(rows) - len(scored)} (truncated or refused), errors: {len(errors)}",
        f"- models: {', '.join(sorted({str(r.get('model')) for r in rows})) or '-'}",
    ]
    if scored:
        latency = [r["latency_s"] for r in scored]
        tools = [r["tool_calls"] for r in scored]
        lines += [
            f"- latency per case: median {statistics.median(latency):.1f} s, "
            f"max {max(latency):.1f} s",
            f"- tool calls per case: mean {statistics.mean(tools):.1f}, max {max(tools)}",
        ]
    if costs:
        lines.append(
            f"- cost: ${sum(costs):.2f} in all, ${statistics.median(costs):.3f} median per case "
            f"(range ${min(costs):.3f}-${max(costs):.3f})"
        )
    by_tag: dict[str, list[float]] = defaultdict(list)
    for r in scored:
        by_tag[r["tags"][0]].append(r["grade"]["correct"])
    lines += ["", "| kind | correct |", "|---|---|"]
    lines += [f"| {t} | {int(sum(v))}/{len(v)} |" for t, v in sorted(by_tag.items())]
    lines += ["", "| case | rep | ok | why | tools | trace |", "|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["tags"][0], r["prompt_id"], r.get("rep", 0))):
        mark = "✓" if r["grade"]["correct"] else ("-" if r["status"] != "ok" else "✗")
        why = str(r["explanation"].get("correct", "")).replace("|", "\\|")[:90]
        trace = f"{folder.name}/traces/{r['prompt_id']}_rep{r.get('rep', 0)}.json"
        lines.append(
            f"| `{r['prompt_id']}` | {r.get('rep', 0)} | {mark} | {why} | {r['tool_calls']} "
            f"| [{trace}]({trace}) |"
        )
    for e in errors:
        lines.append(
            f"| `{e['prompt_id']}` | {e['rep']} | error | {e['kind']}: {e['message'][:80]} | | |"
        )
    return lines


def write_report(flow: Path) -> Path:
    """``<flow>/report.md`` for the baseline and every ``v<N>`` variant."""
    variants = sorted(
        (
            d
            for d in flow.iterdir()
            if d.is_dir() and (d.name == "baseline" or d.name[1:].isdigit())
        ),
        key=lambda d: (d.name != "baseline", d.name),
    )
    lines = ["# Agent eval: Claude on idrogeo-mcp", ""]
    for folder in variants:
        lines += [*summarize(folder), ""]
    report = flow / "report.md"
    report.write_text("\n".join(lines))
    return report


if __name__ == "__main__":  # pragma: no cover
    print(
        write_report(
            Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".claude/hillclimb/agent-mcp")
        )
    )
