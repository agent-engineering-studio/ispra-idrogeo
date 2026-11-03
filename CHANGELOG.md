# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `IdroGEO.hazard_at(lat, lon)`: the PAI landslide hazard class, the flood
  scenarios, the municipality and the slope of a point, in one request to
  IdroGEO's public WMS (`GetFeatureInfo`); `lithology=True` adds the rock
  type (slower). `idrogeo hazard`, and the MCP tool `hazard_at`.
- `IdroGEO.landslides_near(lat, lon, radius_m)`: the IFFI landslides around a
  point, nearest first, with the distance to their real outline.
  `idrogeo near`, and the MCP tool `landslides_near`.
- `ispra_idrogeo.wms`: the pure request builders and parsers behind them,
  and `distance_m` from a point to any GeoJSON geometry.

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
