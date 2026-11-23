---
hide:
  - navigation
---

# ispra-idrogeo

![ispra-idrogeo: Italy's landslides and flood hazard, from ISPRA IdroGEO, in a few lines of Python](images/banner.svg)

**ispra-idrogeo** brings Italy's official data on **landslides and floods**
into your code, and tells you **how far you can trust it**. The data comes
from [IdroGEO](https://idrogeo.isprambiente.it/), the platform of ISPRA,
Italy's national environmental agency. No browser, no account, no API key.

```python
async with IdroGEO() as idrogeo:
    folder = await idrogeo.fetch(opendata("frane_piff"))  # 721,457 landslides, one point each
```

<div class="grid cards" markdown>

-   :material-rocket-launch: **[Getting started](getting-started.md)**

    Install, download your first layer, look at it, ask the API, or start everything in Docker.

-   :material-database: **[Datasets](datasets.md)**

    Every layer and hazard map, and how far the data can be trusted town by town.

-   :material-calendar-check: **[Dated landslides](recipes.md#dated-landslides-when-and-how-precisely)**

    The landslides with a date, and how precise that date and point are.

-   :material-map: **[Mappa per gli enti](riuso.md)**

    A page for a town's site: hazard, landslides, exposure and trust. No rain, no alert.

-   :material-robot: **[AI agents](ai-agents.md)**

    `idrogeo-mcp`: the data as tools, with sources and a check of every number. Reports and digests too.

-   :material-check-decagram: **[How it works](how-it-works.md)**

    Downloads that never break, known cases replayed in CI, daily live tests.

</div>

```bash
pip install ispra-idrogeo            # downloads, API, the idrogeo command
pip install "ispra-idrogeo[geo]"     # + GeoDataFrames and GeoParquet
pip install "ispra-idrogeo[mcp]"     # + the MCP server for AI agents
make start                           # or everything in Docker: MCP, map, Jupyter
```

## What is IdroGEO, in 30 seconds

--8<-- "README.md:intro"

## What this library does

--8<-- "README.md:features"

## Who is it for

--8<-- "README.md:audience"

## A map for public bodies

--8<-- "README.md:app"

## Data licence and credits

--8<-- "README.md:licence"
