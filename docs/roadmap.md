# Roadmap & AI

Where ispra-idrogeo stands at **0.10.0** (22 November 2026), and what would
make it more useful. These are directions, not promises: open an issue to
discuss one before starting. The roadmap that brought it here is
[#11](https://github.com/agent-engineering-studio/ispra-idrogeo/issues/11)
(closed); the AI layer still to do is
[#23](https://github.com/agent-engineering-studio/ispra-idrogeo/issues/23).

## Where we are

| Area | Today | Gap |
|---|---|---|
| **Data** | Every open-data layer and mosaic (PAI 2024 too), conditional downloads, a local DuckDB warehouse | – |
| **Places** | `hazard_at`, `landslides_near`, `iter_landslides_in`; risk figures of all 7,899 towns | PAI polygons clipped to a box, not to the town's outline, on the map |
| **Trust** | `dated_landslides` with their precision, `reliability` per town, `freshness` of every file | No reference to measure how complete IFFI is |
| **People** | The *Mappa dei dati* for public bodies, in Docker, with `publiccode.yml` | Italian only; no WCAG audit |
| **AI agents** | `idrogeo-mcp`: 19 tools with source, licence and time in every answer; `check_answer`; `SKILL.md`, `llms-full.txt`; an eval (pilot 5/5) | `check_answer` not yet used by agents; no check of who-said-what |
| **Quality** | 100% coverage, `mypy --strict`, known cases replayed in CI, live contract tests every day | – |

## Status

| # | Feature | Kind | Status |
|---|---|---|---|
| 1 | Point queries: `hazard_at`, `landslides_near` (WMS) | Core | ✅ 0.6.0 |
| 2 | Landslides of an area: `iter_landslides_in` | Core | ✅ 0.6.0 |
| 3 | `idrogeo watch`, progress bar, example notebooks | DX | ✅ 0.6.0 |
| 4 | MCP over streamable HTTP, `/health`, env configuration | AI | ✅ 0.6.0 |
| 5 | `llms.txt` for coding assistants | AI | ✅ 0.7.0 |
| 6 | MCP `rank_areas`, `compare_areas`, resources, prompts | AI | ✅ 0.7.0 |
| 7 | Local DuckDB warehouse with read-only SQL for agents | Core · AI | ✅ 0.7.0 |
| 8 | Live contract tests, every day since 0.10.0, opening an issue on drift | Quality | ✅ 0.7.0 |
| 9 | Agent evaluation suite (`make eval`, needs an Anthropic key) | AI | ✅ 0.8.0, pilot 5/5 correct |
| 10 | Source, licence and time in every MCP answer; `check_text` / `check_answer` | AI | ✅ 0.8.0 |
| 11 | PAI landslide mosaic 2024 (`pai_frane_2024`), File Geodatabases in the warehouse | Data | ✅ 0.9.0 |
| 12 | Dated landslides with their precision (`dated_landslides`) | Data | ✅ 0.9.0 |
| 13 | How far to trust IFFI, town by town (`reliability`) | Data | ✅ 0.9.0 |
| 14 | Benchmark of known cases, replayed offline in CI | Quality | ✅ 0.10.0 |
| 15 | Freshness of every published file (`freshness`) | Data | ✅ 0.10.0 |
| 16 | Agent skill (`SKILL.md`) and `llms-full.txt` | AI | ✅ 0.10.0 |
| 17 | *Mappa dei dati* for public bodies, predisposition classes | People | ✅ 0.10.0 |
| 18 | `check_claims`, faithfulness benchmark, typed tool outputs, area reports, change digests | AI | ✅ next release ([#23](https://github.com/agent-engineering-studio/ispra-idrogeo/issues/23)) |
| 19 | Map: polygons clipped to the town, EN switch, screenshot | People | ⏳ |
| 20 | Landslide susceptibility baseline (notebook) | Research | 💡 |
| 21 | News → candidate events, for review | Research | 💡 |

```mermaid
flowchart LR
    subgraph D["Done (0.6 → 0.10)"]
        direction TB
        P["Places and risk figures"]
        T["Dates and trust<br/>dated_landslides · reliability · freshness"]
        M["Mappa dei dati"]
        Q["Known cases · daily live tests"]
        C["check_claims · faithfulness<br/>typed outputs · reports · digests"]
    end
    subgraph N["Next"]
        direction TB
        Y["Map: clipped polygons · EN switch"]
    end
    subgraph L["Later"]
        direction TB
        S["Research"]
    end
    D --> N --> L
```

---

## Done, not yet released

### Rank and compare, explain the indicators ([#1](https://github.com/agent-engineering-studio/ispra-idrogeo/pull/1))

`rank_areas` (top or bottom areas by any indicator, inside a region or
province) and `compare_areas` (up to 20 side by side) so the agent quotes
numbers instead of computing them. The resource `idrogeo://indicators`
explains keys such as `popfrp3p4p`; two prompts, `area_profile` and
`recent_events`, show clients how to chain the tools. `find_area` ignores
accents and suggests close names.

## In review

### A local warehouse, offline and in SQL ([#4](https://github.com/agent-engineering-studio/ispra-idrogeo/pull/4))

`idrogeo sync` keeps the layers in one DuckDB file, R-tree indexed, in
EPSG:32632. It is for what one WMS request per point cannot do: thousands of
points, work offline, joins. `warehouse_sql` lets an agent write its own
query. The file is opened read-only with DuckDB's access to files and URLs
switched off, so a prompt-injected `read_text('~/.ssh/…')` fails.

Building it turned up four facts now in [Known traps](traps.md):

- the hazard mosaics are **CC BY-SA 4.0**;
- the flood mosaic is in **EPSG:3035**;
- the IFFI shapefiles are **ISO-8859-1**;
- the API's landslide hazard areas add up to ~15% more than the mosaic you can download.

---

### Live contract tests ([#5](https://github.com/agent-engineering-studio/ispra-idrogeo/pull/5))

51 tests against the live service, weekly, outside `make check`. They cover
every layer and area, the `304`, the fields the tools read, and the traps
still being traps. On failure the workflow opens an issue labelled
`live-contract`.

## Next

### Agent evaluation suite

!!! tip "Tool descriptions are prompts: test them like code"
    A set of 50–100 questions (*"residents in flood hazard P2 in Bari"*,
    *"is piazza San Marco in a flood zone?"*, *"the five municipalities of
    Campania with the most residents in landslide hazard P3+P4"*) whose
    answers are computed from the API, run against an agent connected to
    `idrogeo-mcp`. It measures whether the agent picks the right tools, with
    the right codes, and reports the right numbers. Run on demand (it costs
    model calls), not in every CI build.

### The AI layer, phase 5 (#23)

- **`check_claims`**: a real number said of the wrong indicator ("Bari ha
  4.038 residenti", where 4,038 are the people in flood hazard) is flagged.
  `check_answer` and `idrogeo check` run it with `check_text`.
- **A faithfulness benchmark**, free and offline in CI: 18 answers labeled
  by hand. Swaps caught: 0/6 by `check_text`, 5/6 with `check_claims`; no
  false alarm on the 8 good answers.
- **`check_answer` before every number**: stronger instructions, and the
  eval reports "checks its answer: x/y".
- **Typed outputs**: every MCP tool publishes an output schema.
- **`idrogeo report <comune>`**: a page in Italian from a template, every
  number checked; `--summary` adds a model's summary, checked before it is
  written.
- **`idrogeo digest`**: files, records and events changed since the last
  digest.

---

## Later: AI features

!!! tip "The design rule for every AI feature here"
    **Numbers come from the data, words from the model.** The library
    assembles the figures deterministically; the model only writes prose
    around them, and a checker verifies that every number in the text appears
    in the data. Every output cites ISPRA — IdroGEO and says it is not an
    official hazard assessment.

### Next

- An English version of `idrogeo report`, and HTML output.
- A digest by region or province (`--region`), for a newsletter or a
  council briefing.

---

## Research directions

### A landslide susceptibility baseline

A notebook that trains a simple model (gradient boosting) for one region.
IFFI landslides are the positives; slope, lithology (both already returned by
`hazard_at`), land cover and rainfall are the features. It serves as teaching
material and as a baseline for
[Limen](https://github.com/agent-engineering-studio/limen). Two honest
caveats, written into the notebook: IFFI is incomplete where surveys were
fewer (sampling bias), and a model is **not** a substitute for the official
PAI hazard maps.

### News → candidate events

A pipeline that reads local news feeds, has a model extract *when, where,
what type*, geocodes it, and matches it to IFFI and IdroGEO events. Output:
**candidates** for review, clearly separated from official data, never
written back as if they were ISPRA records.

---

## Not AI, still important

- 🧩 **GeoServer bootstrap** for [mcp-geo-server](https://github.com/agent-engineering-studio/mcp-geo-server).
- 🗺️ **A static explorer on this site**: a nightly workflow writes the 7,899
  municipalities' indicators to JSON, and a page shows them on a map with
  search. No server, no API key.
- 🏷️ **A clear User-Agent** with the library's version, so ISPRA can see and
  reach its users.
- ❓ **Ask ISPRA** which edition the API's landslide hazard indicators use, and
  whether it will be published for download.

## How to help

Pick a row, open an issue saying which one, and read
[Contributing](contributing.md). The English report and the digest by region are
good first contributions.
