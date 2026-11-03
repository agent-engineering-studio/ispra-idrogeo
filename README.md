# ispra-idrogeo

<p>
  <a href="https://github.com/agent-engineering-studio/ispra-idrogeo/actions/workflows/ci.yml"><img src="https://github.com/agent-engineering-studio/ispra-idrogeo/actions/workflows/ci.yml/badge.svg" alt="ci"></a>
  <a href="https://pypi.org/project/ispra-idrogeo/"><img src="https://img.shields.io/pypi/v/ispra-idrogeo" alt="PyPI"></a>
  <img src="https://img.shields.io/badge/python-3.12%20%7C%203.13-blue" alt="Python 3.12 | 3.13">
  <img src="https://img.shields.io/badge/typing-mypy%20strict-informational" alt="mypy strict">
  <img src="https://img.shields.io/badge/coverage-100%25-brightgreen" alt="coverage 100%">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-green" alt="Apache-2.0"></a>
</p>

**ispra-idrogeo** is a small, typed, async Python library for
[IdroGEO](https://idrogeo.isprambiente.it/), the ISPRA platform for
landslides and floods in Italy. It downloads the **IFFI landslide inventory**
(721,365 landslides in November 2026), the **dated landslide events** and the
national **PAI landslide and flood hazard mosaics** into a **persistent
folder**, and asks again only for what changed. It also reads the public
**REST API**: summaries and risk indicators per region, province and
municipality, code lists, paged searches.

```python
async with IdroGEO() as idrogeo:
    folder = await idrogeo.fetch(opendata("frane_poly"))  # ~570 MB the first time, a 304 after
```

No account, no key. One dependency: `httpx`.

## Install

```bash
pip install ispra-idrogeo
```

## Quick start

```python
import asyncio

from ispra_idrogeo import IdroGEO, mosaic, opendata


async def main() -> None:
    async with IdroGEO() as idrogeo:
        # IFFI points (one per landslide), for the whole of Italy.
        points = await idrogeo.fetch(opendata("frane_piff"))
        # The same layer as GeoJSON, for one region.
        puglia = await idrogeo.fetch(opendata("frane_piff", "puglia", "geojson"))
        # The national flood hazard mosaic (~750 MB).
        floods = await idrogeo.fetch(mosaic("idraulica"))
        # API: IFFI counts for Puglia (ISTAT region 16).
        summary = await idrogeo.summary("iffi", "regioni", 16)
        print(points, puglia, floods, summary["nome"])


asyncio.run(main())
```

`fetch` returns the folder the ZIP unpacks to (`<dir>/frane_piff_ispra_opendata/`);
`download` returns the file and whether this call changed it.

## What there is

| Layer | What | Italy, zipped |
|---|---|---|
| `frane_piff` | IFFI landslide identification points, one per landslide | 38 MB |
| `frane_poly` | IFFI landslide polygons | 573 MB |
| `frane_line` | IFFI landslides too narrow for a polygon | 18 MB |
| `aree_poly` | areas of diffuse landslides | 236 MB |
| `dgpv_poly` | deep-seated gravitational slope deformations | 4 MB |
| `eventi` | dated landslide events (points) | 1 MB |
| `segnalazioni` | reports | small |
| `mosaic("pai_frane")` | PAI landslide hazard mosaic 2020-2021 | 1.2 GB |
| `mosaic("idraulica")` | flood hazard mosaic 2020 | 0.75 GB |
| `sensor_data()` | monitoring network readings, CSV (bzip2) | |

Every `opendata` layer comes as a shapefile (default) or GeoJSON
(`fmt="geojson"`), for Italy (`area="ispra"`, the default) or for one area:
the 19 region file names in `REGIONS` (by ISTAT code), and the provinces
that publish separately in `PROVINCES` (Bolzano, Trento, the Sicilian ones).
Coordinates are in **EPSG:32632** (WGS 84 / UTM 32N).

## Where downloads are saved

In a folder that should survive restarts, because the national files weigh
hundreds of MB:

1. the `directory` you pass;
2. else `IDROGEO_DATA_DIR`;
3. else `~/.cache/ispra-idrogeo` (or `$XDG_CACHE_HOME/ispra-idrogeo`).

Next to each file, `<file>.meta.json` keeps the `ETag` and `Last-Modified`
the server sent. ISPRA regenerates the inventory files **every day**, so
they become a conditional GET: an unchanged file costs one `304 Not
Modified`, a changed one is downloaded and unpacked again.

Downloads stream to `<file>.part` and are renamed when complete; unpacking
goes to `<folder>.part` and is swapped in whole. A reader never finds half a
file or half a shapefile, and a ZIP member that would land outside its
folder is refused.

## The API

```python
async with IdroGEO() as idrogeo:
    italy = await idrogeo.summary("pir", "italia")  # hazard and risk indicators
    bari = await idrogeo.summary("pir", "comuni", 72006)  # one municipality
    regions = await idrogeo.summary("iffi", "regioni")  # the list of a level
    names = await idrogeo.dictionaries()  # the code lists
    causes = await idrogeo.dictionary("cause")
    page = await idrogeo.search_landslides(limit=100, offset=0, select=["id_frana"])
```

Reading needs no account. Search filters are a JSON object whose syntax is
in ISPRA's technical manual; an empty one matches everything, so page with
`limit` and `offset`. Some detail endpoints (`/frana/{id}`) answer 401
without a login, whatever the OpenAPI document says.

## Errors and retries

- A dataset that does not exist (404), an API refusal, or a JSON that is
  not what was asked for raise `IdrogeoError`.
- Network errors and 429/5xx are retried `retries` times (default 3) with
  exponential backoff, then propagate as `httpx` exceptions. Pass
  `retries=0` to wrap the calls in your own retry policy.
- Give it your `httpx.AsyncClient` and timeouts, proxies and pooling stay
  yours.

## The traps we already fell into

- **The old paths are gone.** `/opendata/iffi/<region>/iffi_<region>_<layer>.zip`
  and `/opendata/iffi/dizionari/*.json` answer 404 in 2026. The files moved
  to `/opendata/frane/`, the dictionaries to the API.
- **The WFS is not public.** `geoserver/idrogeo/frane/ows` answers 401, and
  the global GeoServer lists no layer to an anonymous user. The downloads
  and the API are the open way in.
- **Not every IdroGEO area is a region.** Trentino-Alto Adige publishes per
  province (`bolzano`, `trento`), and Sicily also per province, besides its
  regional file.

## Data licence

Unless stated otherwise, ISPRA publishes its data under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/legalcode)
([note legali](https://www.isprambiente.gov.it/it/note-legali)): credit
*ISPRA — IdroGEO* when you publish anything derived from them. This library
only downloads them.

## Development

```bash
uv sync
make check
```

Extracted from [Limen](https://github.com/agent-engineering-studio/limen),
a multi-hazard risk monitor for Italy.

## License

[Apache-2.0](./LICENSE).
