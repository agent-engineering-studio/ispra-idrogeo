---
name: ispra-idrogeo
description: Use the ispra-idrogeo Python library (or its idrogeo CLI and idrogeo-mcp server) for Italian landslide and flood data from ISPRA IdroGEO - the IFFI landslide inventory, PAI landslide and flood hazard mosaics, dated landslide events, hazard and exposure indicators of regions, provinces and municipalities. Trigger on IdroGEO, ISPRA, IFFI, frane, franosità, PAI, pericolosità frana/idraulica, mosaicatura, rischio idrogeologico, comuni a rischio, landslides in Italy.
---

# ispra-idrogeo

Use the library instead of raw HTTP to IdroGEO: several paths in old guides
answer 404 or 401, and the library already handles the traps below.

## Setup

```bash
pip install ispra-idrogeo                 # downloads, API, the idrogeo command
pip install "ispra-idrogeo[geo]"          # GeoDataFrames (geopandas)
pip install "ispra-idrogeo[warehouse]"    # a local DuckDB copy, SQL, offline
pip install "ispra-idrogeo[mcp]"          # idrogeo-mcp, the MCP server
```

Everything is async: `async with IdroGEO() as idrogeo: ...`. No account, no key.

## The data, in one paragraph

IFFI maps 721,457 landslides (points, outlines, lines). The PAI mosaics map
landslide hazard (P4 very high … P1, AA attention) and flood hazard (P3
frequent, P2 100–200 years, P1 rare); the 2024 landslide mosaic
(`mosaic("pai_frane_2024")`) is the one the API's indicators are computed
on. `summary("pir", level, code)` gives hazard and exposure (residents,
buildings, heritage per class) by ISTAT code; `summary("iffi", …)` the
landslide counts. `hazard_at(lat, lon)` and `landslides_near(lat, lon)` answer
for a point. `dated_landslides` gives the landslides with a date and how
precise it is; `reliability(level, code)` how far IFFI can be trusted in a
place; `freshness()` when ISPRA last changed each file.

## Traps a model gets wrong from memory

- Files are in **EPSG:32632**, the flood mosaic in **EPSG:3035**; IFFI text is
  ISO-8859-1. Old `/opendata/iffi/...` paths answer 404; the WFS answers 401.
- Filter landslides by area with `iter_landslides_in(region=…)`, not with
  `{"regione": …}` (error) or `regione_2019` (empty for 18%).
- `{"tipo_movimento": 6}` takes a plain number; other filters take operators
  (`"eq.16"`). Use `landslide_filter`, `event_filter`, `site_filter`.
- Only **3.9%** of IFFI landslides have a date (10,822 to the day); 16 regions
  date fewer than 1%. IFFI's `accuratezza_posizione` says "esatta" for every
  record: it tells nothing. Treat a date at 00:00 as "that day".
- Licences: IFFI and events **CC BY-SA 4.0** (cite per region), 2020-2021 and
  flood mosaics CC BY-SA 4.0, 2024 landslide mosaic and indicators CC BY 4.0.

## Rules for answers

- Every number from a tool or the library: no estimating, adding up or
  extrapolating. `null` means not available, never zero.
- Cite the `source` each MCP answer carries; check a draft with
  `check_answer` (or `ispra_idrogeo.grounding.check_text`).
- A hazard map is not an alert and not a safety assessment of a building:
  point to the Civil Protection bulletins for warnings.

Documentation: https://agentengineering.it/ispra-idrogeo/ · full text for
models: https://agentengineering.it/ispra-idrogeo/llms-full.txt
