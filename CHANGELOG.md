# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
