# Examples

Three notebooks, run on the live IdroGEO service on 3 November 2026: the
outputs and charts saved in them are real answers.

| Notebook | What it shows |
|---|---|
| [01 · A town and its landslides](01-a-town-and-its-landslides.ipynb) | Sarno, struck by debris flows in May 1998: exposure figures, hazard at three points, the IFFI landslides on a map, the landslides near a point, the monitoring sites around |
| [02 · Italy in numbers](02-italy-in-numbers.ipynb) | All 7,899 municipalities: who has the most residents in landslide and flood hazard areas, and a chart by region |
| [03 · What changed](03-what-changed.ipynb) | Events year by year, the records changed in the last week, and one round of `idrogeo watch` |

```bash
pip install "ispra-idrogeo[geo]" matplotlib jupyterlab
jupyter lab
```

Notebook 02 downloads the indicators of every municipality (about a minute
the first time, then from disk); notebook 01 downloads the Campania
landslide polygons (31 MB, once).

Data: ISPRA — IdroGEO, CC BY 4.0.
