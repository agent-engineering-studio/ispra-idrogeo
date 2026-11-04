# Agent eval: Claude on idrogeo-mcp

Does an agent connected to `idrogeo-mcp` answer people's questions right?
31 questions ([CASES.md](CASES.md)), in Italian and English: hazard and
exposure of an area, rankings, IFFI counts, a point, monitoring and events,
code meanings, and three traps (a place outside Italy, a town that does not
exist, "is my house safe?").

- **Ground truth** is computed from the live API by the library at run time
  (`cases.py`), never written by hand or taken from a model.
- **The agent** is Claude through the Messages API, connected to a fresh
  `idrogeo-mcp` over stdio per case, with the server's own tools and
  instructions. It ends with `submit_answer`.
- **Grading** is programmatic (`grade.py`): counts exact below 1,000, else
  within 0.5%; percentages within 0.05 points; PAI classes exact; names after
  normalising case, accents and articles; traps passed only by
  `not_available`; "is my house safe?" also needs the caveat. A second metric
  says whether the answer cites ISPRA.

```bash
export ANTHROPIC_API_KEY=…          # or --api-key, or an `ant auth login` profile
make eval ARGS="--limit 5"          # a pilot: 5 questions, one of each kind
make eval                           # all 31 (claude-sonnet-5-5, effort medium)
make eval ARGS="--model claude-opus-5-5 --variant v1"
```

Results go to `.claude/hillclimb/agent-mcp/<variant>/` (`results.jsonl`,
`traces/`, `errors.jsonl`) and `report.md` summarises them: pass rate with a
95% interval, by kind of question, tool calls, latency and cost from the
recorded `usage`. A rerun resumes where the last one stopped.

Running it costs API calls; `make check` runs only the offline tests of the
grader and the runner (`tests/test_evals.py`, with a fake model).
