# Examples

Four notebooks, run on the live IdroGEO service: the outputs and charts
saved in them are real answers (00 on 22 November 2026, the others on 3
November 2026).

| Notebook | What it shows |
|---|---|
| [00 · Test the library](00-test-the-library.ipynb) | Every feature once, each with a check: 23 checks, a table of ✅ and ❌ at the end. `make test-notebooks` runs it (or `make docker-test-notebooks` in a container) and fails if a check fails |
| [01 · A town and its landslides](01-a-town-and-its-landslides.ipynb) | Sarno, struck by debris flows in May 1998: exposure figures, hazard at three points, the IFFI landslides on a map, the landslides near a point, the monitoring sites around |
| [02 · Italy in numbers](02-italy-in-numbers.ipynb) | All 7,899 municipalities: who has the most residents in landslide and flood hazard areas, and a chart by region |
| [03 · What changed](03-what-changed.ipynb) | Events year by year, the records changed in the last week, and one round of `idrogeo watch` |

```bash
make notebooks                       # Jupyter in a container: http://localhost:8888/lab?token=idrogeo
# or, without Docker:
uv run --group notebooks jupyter lab
```

Notebook 02 downloads the indicators of every municipality (about a minute
the first time, then from disk); notebook 01 downloads the Campania
landslide polygons (31 MB, once).

Data: ISPRA — IdroGEO. IFFI landslides and events CC BY-SA 4.0, risk indicators CC BY 4.0.
