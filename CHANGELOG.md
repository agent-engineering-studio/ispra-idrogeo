# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
