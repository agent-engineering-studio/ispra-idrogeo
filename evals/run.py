"""Run the agent eval: Claude, connected to ``idrogeo-mcp``, on ``cases.CASES``.

    uv run --group evals python -m evals.run --limit 5           # a pilot
    uv run --group evals python -m evals.run                     # every case
    uv run --group evals python -m evals.run --model claude-opus-5-5 --variant v1

The Anthropic key comes from ``--api-key``, else from ``ANTHROPIC_API_KEY``,
else from the SDK's own chain (``ANTHROPIC_AUTH_TOKEN``, an ``ant auth login``
profile). Prefer the environment: a key on the command line stays in the
shell history and is visible to other users in ``ps``.

Each (case, rep) starts its own ``idrogeo-mcp`` over stdio, exactly as an
MCP client would, hands its tools (and its instructions) to Claude, and adds
one tool of the harness, ``submit_answer``, which ends the case. The ground
truth is computed from the live API at the same time. Results go to
``.claude/hillclimb/agent-mcp/<variant>/``: ``results.jsonl`` (one row per
case and rep, written as each finishes, so a rerun resumes), ``traces/``
(every turn) and ``errors.jsonl`` (attempts that never produced an answer to
grade: API errors, timeouts, a model other than the one asked for).

Server-side refusal fallbacks are deliberately off: a fallback would answer
with another model, and the eval would no longer measure the one named.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from evals.cases import CASES, Case
from evals.grade import grade
from ispra_idrogeo import IdroGEO

FLOW = Path(".claude/hillclimb/agent-mcp")
DEFAULT_MODEL = "claude-sonnet-5-5"
#: The harness's own tool: the only way to end a case with an answer.
SUBMIT = {
    "name": "submit_answer",
    "description": (
        "Give your final answer to the user's question and end. Call it exactly once, "
        "after using the IdroGEO tools. answer: the value only (a number, a hazard class "
        "such as P4, 'none', a name or a code). status: 'answered', or 'not_available' "
        "when the data cannot answer the question. source: where the data comes from. "
        "notes: what you would tell the user, in one or two sentences."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "status": {"type": "string", "enum": ["answered", "not_available"]},
            "unit": {"type": "string"},
            "source": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["answer", "status", "unit", "source", "notes"],
        "additionalProperties": False,
    },
}
HARNESS = (
    "You answer questions about landslides and floods in Italy with the IdroGEO tools. "
    "When you have the answer, call submit_answer once; do not answer in plain text."
)
#: Tools of the server the eval leaves out: downloads of up to 1.2 GB, and a
#: warehouse the eval machine has not synced.
EXCLUDED = frozenset({"download_dataset", "warehouse_schema", "warehouse_sql"})
NUDGE = "Please call submit_answer with your final answer."


class Tools(Protocol):
    """What the runner needs from an MCP session (a fake one in the tests)."""

    instructions: str

    async def list(self) -> list[dict[str, Any]]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]: ...


Connect = Callable[[], AbstractAsyncContextManager[Tools]]


class AttemptError(Exception):
    """An attempt with nothing to grade; ``kind`` goes to errors.jsonl."""

    def __init__(self, kind: str, message: str, usage: dict[str, int] | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.usage = usage or {}


@dataclass
class Options:
    model: str = DEFAULT_MODEL
    effort: str = "medium"
    reps: int = 1
    max_turns: int = 16
    timeout_s: float = 300
    concurrency: int = 4
    variant: str = "baseline"
    api_key: str | None = None
    flow: Path = FLOW
    cases: Sequence[Case] = field(default_factory=lambda: CASES)


# The MCP side


@dataclass
class _Session:
    session: Any
    instructions: str

    async def list(self) -> list[dict[str, Any]]:
        listed = await self.session.list_tools()
        return [
            {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
            for t in listed.tools
            if t.name not in EXCLUDED
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        result = await self.session.call_tool(name, arguments, read_timeout_seconds=120)
        text = "\n".join(getattr(c, "text", "") for c in result.content) or json.dumps(
            result.structured_content
        )
        return text, bool(result.is_error)


@asynccontextmanager
async def stdio_tools(data_dir: Path) -> AsyncIterator[Tools]:  # pragma: no cover - a subprocess
    """A fresh ``idrogeo-mcp`` over stdio, with its downloads in ``data_dir``."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from ispra_idrogeo.mcp_server import main; main()"],  # = idrogeo-mcp
        env={**os.environ, "IDROGEO_DATA_DIR": str(data_dir)},
    )
    with Path(os.devnull).open("w") as quiet:
        async with (
            stdio_client(params, errlog=quiet) as (read, write),
            ClientSession(read, write) as session,
        ):
            started = await session.initialize()
            yield _Session(session, started.instructions or "")


# One case


async def run_case(
    client: Any, connect: Connect, case: Case, truth: Any, options: Options
) -> dict[str, Any]:
    """Claude on one case: the row for results.jsonl, and the trace."""
    async with connect() as tools:
        definitions = [*await tools.list(), SUBMIT]
        system = f"{tools.instructions}\n\n{HARNESS}".strip()
        messages: list[dict[str, Any]] = [{"role": "user", "content": case.question}]
        trace: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": case.question},
        ]
        usage = dict.fromkeys(
            (
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            ),
            0,
        )
        calls: list[dict[str, Any]] = []
        submission: dict[str, Any] | None = None
        nudged, tool_calls, stop_reason, model = False, 0, None, None
        for _turn in range(options.max_turns):
            started = time.monotonic()
            response = await client.messages.create(
                model=options.model,
                max_tokens=16000,
                system=system,
                tools=definitions,
                messages=messages,
                output_config={"effort": options.effort},
                cache_control={"type": "ephemeral"},
            )
            took = time.monotonic() - started
            model, stop_reason = response.model, response.stop_reason
            spent = _usage(response.usage)
            for key in usage:
                usage[key] += spent[key]
            calls.append({"latency_s": round(took, 2), "stop_reason": stop_reason, "usage": spent})
            if not str(model).startswith(options.model):
                raise AttemptError(
                    "model_mismatch", f"asked {options.model}, served {model}", usage
                )
            messages.append({"role": "assistant", "content": response.content})
            text = " ".join(b.text for b in response.content if b.type == "text").strip()
            uses = [b for b in response.content if b.type == "tool_use"]
            if text and not uses:
                trace.append({"role": "assistant", "content": text})
            if stop_reason in ("refusal", "max_tokens"):
                break
            if stop_reason == "pause_turn":
                continue
            if not uses:
                if nudged:
                    break
                nudged = True
                messages.append({"role": "user", "content": NUDGE})
                trace.append({"role": "user", "content": NUDGE})
                continue
            results = []
            for use in uses:
                trace.append(
                    {
                        "role": "tool_call",
                        "name": use.name,
                        "content": json.dumps(use.input, indent=2),
                    }
                )
                if use.name == SUBMIT["name"]:
                    submission = dict(use.input)
                    output, failed = "Answer recorded.", False
                else:
                    tool_calls += 1
                    try:
                        output, failed = await tools.call(use.name, dict(use.input))
                    except Exception as exc:  # a broken tool reaches the model as an error
                        output, failed = f"{type(exc).__name__}: {exc}", True
                trace.append({"role": "tool_result", "content": output})
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": use.id,
                        "content": output,
                        "is_error": failed,
                    }
                )
            messages.append({"role": "user", "content": results})
            if submission is not None:
                break
    status = {"max_tokens": "truncated", "refusal": "refusal"}.get(str(stop_reason), "ok")
    scores, why = grade(case, truth, submission)
    return {
        "prompt_id": case.id,
        "prompt": case.question,
        "tags": list(case.tags),
        "expected": _jsonable(truth),
        "submission": submission,
        "stop_reason": stop_reason,
        "status": status,
        "grade": scores,
        "explanation": why,
        "model": model,
        "usage": usage,
        "latency_s": round(sum(c["latency_s"] for c in calls), 2),
        "tool_calls": tool_calls,
        "turns": len(calls),
        "meta": {"calls": calls, "nudged": nudged, "effort": options.effort, "trace": trace},
    }


def _usage(usage: Any) -> dict[str, int]:
    return {
        key: int(getattr(usage, key, 0) or 0)
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
    }


def _jsonable(value: Any) -> Any:
    return list(value) if isinstance(value, tuple) else value


# The whole run


async def run(
    client: Any,
    connect: Connect,
    idrogeo: IdroGEO,
    options: Options,
    log: Callable[[str], None] = print,
) -> Path:
    """Every (case, rep) not already in results.jsonl; the variant's folder."""
    folder = options.flow / options.variant
    (folder / "traces").mkdir(parents=True, exist_ok=True)
    _write_state(options.flow)
    results, errors = folder / "results.jsonl", folder / "errors.jsonl"
    done = {(r["prompt_id"], r.get("rep", 0)) for r in _rows(results)}
    todo = [(c, k) for c in options.cases for k in range(options.reps) if (c.id, k) not in done]
    gate = asyncio.Semaphore(options.concurrency)
    lock = asyncio.Lock()

    async def one(case: Case, rep: int) -> None:
        async with gate:
            started = time.monotonic()
            try:
                truth = await case.truth(idrogeo)
                row = await asyncio.wait_for(
                    run_case(client, connect, case, truth, options), options.timeout_s
                )
            except Exception as exc:
                failure = _failure(_cause(exc), options)
            else:
                trace = row["meta"].pop("trace")
                row["rep"] = rep
                row["wall_s"] = round(time.monotonic() - started, 2)
                (folder / "traces" / f"{case.id}_rep{rep}.json").write_text(
                    json.dumps(trace, ensure_ascii=False, indent=1, default=str)
                )
                async with lock:
                    with results.open("a") as out:
                        out.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                mark = "✓" if row["grade"]["correct"] else "✗"
                log(f"{mark} {case.id} rep{rep}: {row['explanation']['correct']}")
                return
            async with lock:
                with errors.open("a") as out:
                    error = {"prompt_id": case.id, "rep": rep, "kind": failure.kind}
                    error |= {
                        "message": str(failure),
                        "usage": failure.usage,
                        "model": options.model,
                    }
                    out.write(json.dumps(error, ensure_ascii=False) + "\n")
            log(f"! {case.id} rep{rep}: {failure.kind}: {failure}")

    await asyncio.gather(*(one(c, k) for c, k in todo))
    return folder


def _cause(exc: BaseException) -> BaseException:
    """The error inside the ExceptionGroups that anyio (the MCP client) wraps it in."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _failure(exc: BaseException, options: Options) -> AttemptError:
    """What an exception means for the eval: the failure class of errors.jsonl."""
    if isinstance(exc, AttemptError):
        return exc
    if isinstance(exc, TimeoutError):
        return AttemptError("timeout", f"over {options.timeout_s:g} s")
    name = type(exc).__name__
    if name in ("AuthenticationError", "PermissionDeniedError"):
        return AttemptError("credentials", f"{name}: check --api-key or ANTHROPIC_API_KEY")
    return AttemptError("harness_or_serving", f"{name}: {exc}")


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write_state(flow: Path) -> None:
    state = flow / "_state.json"
    if state.exists():
        return
    flow.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps(
            {
                "metrics": [
                    {"id": "correct", "label": "correct", "kind": "binary"},
                    {"id": "cited_source", "label": "cites ISPRA", "kind": "binary"},
                ],
                "perf_fields": ["latency_s", "tool_calls", "usage"],
            },
            indent=2,
        )
    )


def options(argv: Sequence[str] | None = None) -> Options:
    top = argparse.ArgumentParser(prog="evals.run", description=__doc__.splitlines()[0])
    top.add_argument("--model", default=DEFAULT_MODEL)
    top.add_argument(
        "--effort", default="medium", choices=("low", "medium", "high", "xhigh", "max")
    )
    top.add_argument("--reps", type=int, default=1)
    top.add_argument("--limit", type=int, help="only the first N cases (a pilot)")
    top.add_argument("--case", action="append", default=[], help="only this case id (repeatable)")
    top.add_argument("--variant", default="baseline", help="baseline, v1, v2…")
    top.add_argument("--concurrency", type=int, default=4)
    top.add_argument("--timeout-s", type=float, default=300)
    top.add_argument("--max-turns", type=int, default=16)
    top.add_argument(
        "--api-key",
        default=os.environ.get("ANTHROPIC_API_KEY"),
        help="Anthropic API key (default: $ANTHROPIC_API_KEY, then the SDK's credential chain)",
    )
    args = top.parse_args(argv)
    cases: Sequence[Case] = [c for c in CASES if c.id in args.case] if args.case else CASES
    if args.limit:
        cases = _pilot(cases, args.limit)
    return Options(
        model=args.model,
        effort=args.effort,
        reps=args.reps,
        max_turns=args.max_turns,
        timeout_s=args.timeout_s,
        concurrency=args.concurrency,
        variant=args.variant,
        api_key=args.api_key or None,
        cases=cases,
    )


def _pilot(cases: Sequence[Case], n: int) -> list[Case]:
    """``n`` cases spread over the kinds of question (round robin on tags[0])."""
    groups: dict[str, list[Case]] = {}
    for case in cases:
        groups.setdefault(case.tags[0], []).append(case)
    picked: list[Case] = []
    while len(picked) < min(n, len(cases)):
        for group in groups.values():
            if group and len(picked) < n:
                picked.append(group.pop(0))
    return picked


async def _main(opts: Options) -> None:  # pragma: no cover - needs the API and the network
    from anthropic import AsyncAnthropic

    from evals.report import write_report

    data = opts.flow / "data"
    started = time.monotonic()
    # api_key=None lets the SDK find the credentials itself (env, ant profile).
    anthropic = AsyncAnthropic(api_key=opts.api_key, max_retries=4)
    async with anthropic as client, IdroGEO() as idrogeo:
        folder = await run(client, lambda: stdio_tools(data), idrogeo, opts)
    print(f"wall clock: {time.monotonic() - started:.0f} s")
    print(write_report(opts.flow))
    _ = folder


def main(argv: Sequence[str] | None = None) -> None:  # pragma: no cover
    asyncio.run(_main(options(argv)))


if __name__ == "__main__":  # pragma: no cover
    main()
