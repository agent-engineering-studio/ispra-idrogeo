---
hide:
  - navigation
---

# ispra-idrogeo

![ispra-idrogeo: Italy's landslides and flood hazard, from ISPRA IdroGEO, in a few lines of Python](images/banner.svg)

**ispra-idrogeo** is a small, typed, async Python library for
[IdroGEO](https://idrogeo.isprambiente.it/), the platform where ISPRA (Italy's
national environmental agency) publishes what it knows about **landslides and
floods** in Italy. A script can download the national landslide inventory and
the hazard maps, keep them up to date, and ask the IdroGEO API for risk figures
about any region, province or town. No browser, no copy-pasted links, no account.

```python
async with IdroGEO() as idrogeo:
    folder = await idrogeo.fetch(opendata("frane_piff"))  # 721,365 landslides, one point each
```

<div class="grid cards" markdown>

-   :material-rocket-launch: **[Getting started](getting-started.md)**

    Install, download your first layer, look at it, ask the API.

-   :material-database: **[Datasets](datasets.md)**

    Every open-data layer and mosaic, for Italy, a region or a province.

-   :material-robot: **[AI agents](ai-agents.md)**

    `idrogeo-mcp`: the same data as ten MCP tools for Claude and other agents.

-   :material-map-marker-path: **[Roadmap & AI](roadmap.md)**

    Where the project goes next: improvements and AI features, prioritised.

</div>

```bash
pip install ispra-idrogeo            # downloads, API, the idrogeo command
pip install "ispra-idrogeo[geo]"     # + GeoDataFrames and GeoParquet
pip install "ispra-idrogeo[mcp]"     # + the MCP server for AI agents
```

## What is IdroGEO, in 30 seconds

--8<-- "README.md:intro"

## What this library does

--8<-- "README.md:features"

## Who is it for

--8<-- "README.md:audience"

## Data licence and credits

--8<-- "README.md:licence"
