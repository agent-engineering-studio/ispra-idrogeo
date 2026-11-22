# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- A screenshot of the *Mappa dei dati* on Sarno (`docs/images/mappa-sarno.jpg`)
  in the README and in `publiccode.yml`.
- README in plainer words: what the library does in six lines, "In one
  picture", three schemes (where the data comes from, the libraries and
  Limen, how the map page works) and two new charts generated from the data
  (`dates.svg`: landslides dated to the day by region; `classes.svg`: the
  7,899 towns by predisposition step); the sizes chart lists the 2024 mosaic;
  updated figures. The site's home and roadmap (0.10.0) follow.
- `make start` builds every image and starts the MCP server, the map and
  Jupyter in one command, printing their addresses; `make stop` stops them.

### Changed

- README (traps), the `MOSAICS` comment and the 0.9.0 entry of this file say
  to name the mosaics one by one: since 0.9.0 `MOSAICS` holds
  `pai_frane_2024` too, and a loop over it downloads 790 MB more.

### Fixed

- The map: the PAI polygons covered the landslide points, so a click on a
  dated landslide opened the polygon underneath; the points now have a pane
  of their own above the polygons. The flood citation in "Fonti e licenze"
  is in Italian, like the rest of the page, and so are the precision labels
  of a dated landslide (ora, giorno, intervallo).
- The map's files are served with `Cache-Control: no-cache`: after an update
  a browser revalidates them and shows the new page at once, instead of a
  cached old one.

## [0.10.0] - 2026-11-22

### Added

- `app/`: the **Mappa dei dati su frane e pericolo** for public bodies (#22),
  a page in Italian with Bootstrap Italia and Leaflet served without CDN and
  a small Starlette API over the library. For one municipality: the PAI 2024
  landslide hazard polygons and the IFFI points from a local warehouse
  loaded at start, flood hazard and the boundary from IdroGEO's WMS, the
  dated landslides with their precision, a predisposition class (no rain,
  not an alert), exposure, landslides by type, how far to trust the data,
  the live state of the contract with IdroGEO, sources, licences and CSV or
  GeoJSON downloads. `make app`, `make app-up` (container `<NAME>-app`, port
  3002), `docs/riuso.md` and `publiccode.yml`, validated in CI.
- `ispra_idrogeo.predisposition`: the landslide and flood predisposition
  classes of an area from `summary("pir", …)`, five fixed steps on the
  official share of land in hazard (P3+P4 of the 2024 mosaic; flood
  scenario P2), with the counts of the 7,899 municipalities.

### Fixed

- Two `Warehouse(read_only=True)` on the same file in one process (two MCP
  calls at once, two requests of the page) failed: the second tried to set
  up and lock the configuration the first had already locked.
- `make help` printed "Makefile" instead of the command names when a `.env`
  file was there.

### Added

- `IdroGEO.head(dataset)` and `FileState`: a file's date, ETag and size
  without downloading it. `ispra_idrogeo.freshness`: `freshness()` asks
  about every published file (IFFI layers, events, reports, mosaics) and,
  with a saved `state`, says which changed since last time; `summary()`.
  `idrogeo freshness`, MCP tool `data_freshness`.
- `skills/ispra-idrogeo/SKILL.md`, an agent skill for coding assistants, and
  `tools/build_llms.py`, which publishes `llms-full.txt` (the whole README)
  and the skill on the site after the build.

### Changed

- The live contract tests run every day, not every Monday: #9 went unseen
  for a week.

### Added

- `benchmarks/`: known cases with known answers (Sarno P4, Venice P3, the
  plain of Foggia, Casamicciola 26/11/2022, Melito di Porto Salvo
  10/10/2026, Trivento, the #9 contract, the reliability map), 8 cases and
  14 checks. IdroGEO's real answers are recorded once
  (`python -m benchmarks.record`, 260 kB in `benchmarks/cassettes/`) and
  replayed offline by `python -m benchmarks.run --check`, which CI runs and
  which fails on any change against `benchmarks/results.json`. A constant
  method shows each check can fail. `make benchmark`, `make
  benchmark-record`.

## [0.9.0] - 2026-11-22

> **Note (added after the release):** `MOSAICS` gained `pai_frane_2024`. Code
> that loops over every entry of `MOSAICS` now downloads 790 MB more at each
> sync; name the mosaics you need instead (`mosaic("pai_frane")`,
> `mosaic("idraulica")`). Limen did so in limen#673.

### Added

- `mosaic("pai_frane_2024")`: the PAI landslide hazard mosaic v. 5.0 (2024),
  0.79 GB, a File Geodatabase, **CC BY 4.0** (its licence PDF). The
  warehouse loads it (`idrogeo sync pai_frane_2024`; File Geodatabases are
  read like shapefiles, the geometry found by type) and `hazard_at` prefers
  it to the 2020-2021 mosaic, naming the one used in `landslide_mosaic`.
  `warehouse.SOURCES` has its citation. Checked on the real file: 1,060,084
  polygons in 132 s, areas within 0.1% of the API's `ar_fr_*` per class. This
  explains the trap of the "10–20% more" areas: the API uses the 2024 mosaic.
- `ispra_idrogeo.dated`: `dated_landslides()` gathers the dated landslides
  of IFFI (API, one request) and of the events file, each with `start`/`end`,
  `time`, `precision` (hour, day, interval), `interval_days`, `position_m`
  (the stated accuracy of the point), `lon`/`lat` and its citation; filters
  by dates, region, `max_interval_days` and `max_position_m`; `summary()`
  counts them. `parse_period` reads partial dates (`"1979"`, `"1983-07"`) as
  intervals and leaves impossible ones out; `utm32n_to_lonlat` converts the
  events' EPSG:32632 points (Krüger series, under a millimetre from PROJ
  across Italy). `idrogeo dated` from the shell. Measured on 22 November
  2026: 28,076 of 721,457 IFFI records have a date (10,822 to the day), and
  every IFFI record says its position is "esatta"; README, traps, live test.

- `ispra_idrogeo.reliability`: how far IFFI and the events can be trusted in
  each region, province and municipality, from a table shipped with the
  package (`data/reliability.json`, 354 kB, built by
  `tools/build_reliability.py` from the live service): landslides and
  density, share dated and dated to the day, landslides dated since 2018
  (IFFI and events, points known to 1 km), share of records edited since
  2021, notes in plain words and what is not measured. `idrogeo
  reliability`, MCP tool `data_reliability`. Checked: per-region counts equal
  the API's, dated totals equal `dated_landslides`.

### Changed

- `.claude/hillclimb/` (eval results) is ignored by git.

### Fixed

- `dated_landslides` missed the IFFI records that have only
  `data_incerta_max` (1,475): the server filter now asks for any of the three
  date fields. IFFI records with a date: 28,076, not 26,601.

## [0.8.0] - 2026-11-22

### Added

- `ispra_idrogeo.grounding`: `check_text(text, facts, question)` lists the
  numbers and dates of a text that match no figure of the facts (rounded as
  written, Italian and English formats, scale words, dates); `SOURCES` and
  `grounded()` give each kind of data its citation and licence. `idrogeo
  check facts.json` and the MCP tool `check_answer` do the same.
- README "AI: where it helps": what is ready (`idrogeo-mcp`, `llms.txt`,
  `evals/`), who it helps and how, where AI must not be used, how to use an
  Anthropic key from `.env` with `make eval`, and what comes next. The
  Makefile exports `ANTHROPIC_API_KEY` from `.env`; only `make eval` uses it.
- `evals/`: an eval of Claude as an agent on `idrogeo-mcp`. 31 questions in
  Italian and English with their ground truth computed live, programmatic
  grading, a runner that starts the real server over stdio and resumes, and a
  `report.md`. `make eval` runs it (API key from `--api-key` or
  `ANTHROPIC_API_KEY`); `make check` tests the grader and runner offline.

### Changed

- Every `idrogeo-mcp` answer carries `source` (citation and licence: IFFI and
  events CC BY-SA 4.0, risk indicators CC BY 4.0) and `retrieved_at` (UTC).
  **Breaking for code that parses the MCP JSON:** tools that answered a list
  now answer `{"results": [...], "count": n, "source": ..., "retrieved_at":
  ...}`. The instructions ask the agent to take
  every number from a tool, cite the source, never read null as zero, say
  nothing is an alert, and call `check_answer` on its draft.

## [0.7.1] - 2026-11-22

### Added

- `examples/00-test-the-library.ipynb`: every feature once against the live
  service, 23 checks, a table of results; `make test-notebooks` runs it and
  fails when a check fails. Dependency group `notebooks`.
- Containers: `Dockerfile` (targets `app` and `notebooks`), `compose.yaml`,
  `.env.example`. `make up` starts `idrogeo-mcp` on port 8767, `make
  notebooks` Jupyter on 8888, `make cli ARGS=…` runs a command, `make
  docker-test-notebooks` the test notebook. Every container, image, volume
  and network starts with `NAME` (default `ispra-idrogeo`), so copies never
  clash. `make help` lists every command.
- README: a "Jump to what you need" table of every example, "Run it in
  containers", how precise the dates of the events are, and the licence of
  each dataset.

### Fixed

- The IFFI inventory and its events are **CC BY-SA 4.0**, not CC BY 4.0: the
  licence PDFs linked from IdroGEO's open-data page say so, region by region.
  `warehouse.SOURCES["iffi"]`, the MCP instructions, prompts and the
  `idrogeo://datasets` resource now say it; only the risk indicators are
  CC BY 4.0.

- Landslide searches (`search_landslides`, `iter_landslides`, the MCP tool
  `search_landslides` and `idrogeo landslides` without `--select`) answered
  HTTP 400 since November 2026: IdroGEO's default fields embed `regioni_2022`,
  a relation it removed. The library now always names the fields, by default
  `LANDSLIDE_FIELDS`, which adds the dates and the position accuracy (#9).

### Changed

- The documentation site is built with Zensical (`zensical.toml`) instead of
  MkDocs Material; same pages, theme and API reference.

## [0.7.0] - 2026-11-04

### Added

- Extra `[warehouse]` (DuckDB) and `ispra_idrogeo.warehouse.Warehouse`: the
  layers in one local DuckDB file, R-tree indexed, all in EPSG:32632, for
  work offline, many places at once and SQL of your own. `sync()` loads only
  the layers whose download changed, in one transaction; `query()` runs one
  read-only SELECT (geometries as WKT), with file and network access shut
  off when the warehouse is opened read-only; `hazard_at()`,
  `landslides_near()` and `landslides_in()` answer the client's questions
  offline. The flood mosaic is reprojected from EPSG:3035; IFFI text is read
  as the ISO-8859-1 its `.cst` file says.
- `idrogeo sync` and `idrogeo sql`; MCP tools `warehouse_schema` and
  `warehouse_sql`.
- MCP tools `rank_areas` (top or bottom areas by any indicator, inside a
  region or province, summaries kept on disk 30 days) and `compare_areas`
  (up to 20 areas side by side); both carry the source and licence.
- MCP resources `idrogeo://indicators` (what the indicator keys mean),
  `idrogeo://datasets` and `idrogeo://codes/{name}`; prompts `area_profile`
  and `recent_events`.
- `summaries()` and `municipalities()` take `region` and `province`, and
  `idrogeo municipalities` `--region` and `--province`, to ask only for the
  areas inside them; `within(items, region=, province=)` filters a list.
- Documentation site on GitHub Pages (MkDocs Material, API reference from the
  docstrings), built and deployed by the `docs` workflow; `make docs` and
  `make docs-serve`. Pages reuse the README sections, so there is one source.
- A Roadmap & AI page: improvements and AI features, prioritised.
- `llms.txt` on the site, for AI coding assistants.
- `tests/live/`: 51 contract tests against the live IdroGEO service (every
  layer and area published, the `304`, the fields the library reads, the
  traps of the README still being traps), excluded from `make check`;
  `make live` runs them. The `live` workflow runs them every Monday and opens
  (or updates) an issue labelled `live-contract` when one fails.

### Changed

- README: the two hazard mosaics are CC BY-SA 4.0 (their licence PDF), not
  CC BY 4.0; the flood mosaic is in EPSG:3035; the API's landslide hazard
  areas do not add up like the downloadable mosaic.
- `find_area` matches names without accents and apostrophes (`forli` finds
  Forlì) and answers an unknown name with "did you mean" suggestions instead
  of an empty list.

## [0.6.0] - 2026-11-03

### Added

- `IdroGEO.hazard_at(lat, lon)`: the PAI landslide hazard class, the flood
  scenarios, the municipality and the slope of a point, in one request to
  IdroGEO's public WMS (`GetFeatureInfo`); `lithology=True` adds the rock
  type (slower). `idrogeo hazard`, and the MCP tool `hazard_at`.
- `IdroGEO.landslides_near(lat, lon, radius_m)`: the IFFI landslides around a
  point, nearest first, with the distance to their real outline.
  `idrogeo near`, and the MCP tool `landslides_near`.
- `IdroGEO.iter_landslides_in(region=, province=, municipality=)`: every
  IFFI landslide of an area, checked on each record's own area fields since
  the search has no reliable area filter; exact counts (Campania 55,254).
  `idrogeo landslides --region/--province/--municipality`, and area
  arguments on the MCP tool `search_landslides`.
- `idrogeo watch`: prints the landslides, events and monitoring sites that
  change, once per change, resuming from `<dir>/watch.json`; `--once` for
  cron. `ispra_idrogeo.watch` (`changes`, `Mark`, `load_marks`,
  `save_marks`) is the engine.
- `progress=callback(done, total)` on `download` and `fetch`, and a progress
  bar in `idrogeo fetch` (on stderr, when it is a terminal).
- `idrogeo-mcp --transport streamable-http --host --port`: the MCP server
  over HTTP at `/mcp`, with `GET /health`; every option also reads
  `IDROGEO_MCP_TRANSPORT`, `IDROGEO_MCP_HOST`, `IDROGEO_MCP_PORT` and
  `IDROGEO_MCP_ALLOWED_HOSTS` (DNS rebinding protection). stdio stays the
  default.
- `ispra_idrogeo.wms`: the pure request builders and parsers behind them,
  and `distance_m` from a point to any GeoJSON geometry.

- `examples/`: three notebooks run on the live service (a town and its
  landslides, Italy in numbers, what changed).

### Fixed

- README: IdroGEO's GeoServer is public over WMS; only the WFS asks for a
  login.

## [0.5.0] - 2026-11-03

### Added

- `IdroGEO.labels(name, lang)` and `IdroGEO.code_labels(fields, lang)`: the
  API's code lists as `{code: label}`, in Italian, English, French or German.
- `decode(record, labels)`: a copy of a record (API, site or shapefile row)
  with `<field>_label` next to each coded field; `CODE_DICTIONARIES` says
  which code list decodes which field.
- Extra `[geo]` (geopandas, pyarrow) and `ispra_idrogeo.geo`: `read` opens a
  downloaded file or folder as a GeoDataFrame, `frame` turns API rows into
  one in their own CRS (EPSG:4326 points, EPSG:32632 landslides, EPSG:3857
  webcams), `add_labels` adds `<column>_label` columns; `.to_parquet` writes
  GeoParquet.
- `landslide_filter`, `event_filter`, `site_filter`: search filters by
  movement, activity, district, area (ISTAT codes) and dates, in the syntax
  each search wants.
- Extra `[mcp]` and the `idrogeo-mcp` server (MCP SDK 2.x, stdio): 10
  tools for AI agents (`find_area`, `area_risk`, `area_landslides`,
  `landslide`, `search_landslides`, `search_events`, `monitoring_sites`,
  `webcams`, `code_list`, `download_dataset`), codes decoded, answers capped
  at `limit` rows.
- `IdroGEO.lookup(kind, text, limit)` and `idrogeo lookup`: text search in
  the reference lists (geological units, aerial survey flights,
  bibliography, institutions, professional bodies, funding sources).
- The `idrogeo` command: `fetch`, `summary`, `municipalities`, `landslides`,
  `events`, `sites`, `webcams`, `landslide`, `labels`, `dictionaries`,
  `lookup`;
  downloads print their path, the rest prints JSON Lines.

### Fixed

- README: the code lists come in four languages, not five.

## [0.4.0] - 2026-11-03

### Added

- `modified_since` on `iter_landslides`, `iter_events` and `sites`: only the
  records changed since a time-zone-aware datetime, for incremental updates
  of a local copy (`select=["*"]` brings the geometry).
- `since_filter(filters, since)`: the pure filter behind it.

## [0.3.0] - 2026-11-03

### Added

- `IdroGEO.landslide(id_frana)`: the full record of a validated IFFI
  landslide; `IdrogeoError` for an unknown id (IdroGEO answers 401).
- `IdroGEO.iter_landslides` / `IdroGEO.iter_events`: async iterators over
  every matching record, page after page, in a stable order.
- `IdroGEO.sites`, `site(uid)`, `stations(uid)`: the 1,063 landslide
  monitoring sites, one site, and its stations with instruments and sensors.
- `IdroGEO.webcams`: the webcams pointed at landslides (coordinates in
  EPSG:3857).

### Fixed

- Search filters are typed `dict[str, Any]`: landslide filters take plain
  values (`{"tipo_movimento": 6}`), not only strings.
- `parse` returns `None` for a JSON `null` instead of raising "did not
  return JSON".

## [0.2.0] - 2026-11-03

### Added

- `IdroGEO.municipalities(summary="pir")` and `IdroGEO.summaries(summary,
  level)`: the summary of every municipality (7,899), province or region,
  `concurrency` calls at a time, saved one JSON per area under
  `<directory>/<summary>_<level>/` and asked again only when older than
  `max_age`; an interrupted run resumes.
- `level_codes`, `CODE_FIELDS`, `read_json`, `write_json`: the pure pieces
  behind it.

### Fixed

- README: `/api/frana/{id}` answers without a login; the detail endpoint
  that asks for one is `/api/evento/{id}`.

## [0.1.0] - 2026-11-03

### Added

- `opendata(layer, area, fmt)`, `mosaic(name)`, `sensor_data()`: the IdroGEO
  open-data downloads (IFFI layers, events, reports, PAI and flood hazard
  mosaics, monitoring CSV) for Italy or one region or province.
- `IdroGEO.download` / `IdroGEO.fetch`: streamed downloads into a persistent
  folder (`IDROGEO_DATA_DIR`), revalidated with ETag / Last-Modified, unpacked
  atomically.
- `IdroGEO.summary`, `dictionaries`, `dictionary`, `search_landslides`,
  `search_events`: the public REST API.
