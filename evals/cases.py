"""The questions of the agent eval, each with a ground truth computed live.

The expected answer is never written by hand or taken from a model: each
case carries a ``truth`` coroutine that asks IdroGEO through the library at
run time, so the gold is as fresh as the service. ``kind`` says how the
agent's submitted answer is compared with it (see ``grade.py``).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from ispra_idrogeo import IdroGEO, event_filter, site_filter

Kind = Literal["count", "number", "percent", "class", "text", "abstain"]
Truth = Callable[[IdroGEO], Awaitable[Any]]


@dataclass(frozen=True)
class Case:
    """One question: what the agent reads, and how to know the right answer."""

    id: str
    tags: tuple[str, ...]  # tags[0]: the kind of question; then the language
    question: str
    kind: Kind
    truth: Truth
    #: For ``abstain``: what the agent must say it cannot answer, and why.
    why: str = ""
    #: The answer must also carry a caveat (not a safety assessment).
    caveat: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


async def _pir(idrogeo: IdroGEO, level: str, code: int | None, key: str) -> Any:
    return (await idrogeo.summary("pir", level, code))[key]  # type: ignore[arg-type]


async def _iffi(idrogeo: IdroGEO, level: str, code: int | None, key: str) -> Any:
    return (await idrogeo.summary("iffi", level, code))[key]  # type: ignore[arg-type]


async def _top(
    idrogeo: IdroGEO,
    summary: Literal["pir", "iffi"],
    level: Literal["regioni", "province", "comuni"],
    key: str,
    region: int | None = None,
    province: int | None = None,
) -> str:
    rows = await idrogeo.summaries(summary, level, region=region, province=province)
    best = max((r for r in rows if isinstance(r.get(key), int | float)), key=lambda r: r[key])
    return str(best["nome"])


async def _movement_count(idrogeo: IdroGEO, level: str, code: int, cod: int) -> int:
    stats = (await idrogeo.summary("iffi", level, code))["frane_stats"]  # type: ignore[arg-type]
    return int(next(s["nr_frane"] for s in stats if s["cod"] == cod))


async def _events(idrogeo: IdroGEO, region: int, year: int) -> int:
    filters = event_filter(region=region, start=date(year, 1, 1), end=date(year + 1, 1, 1))
    return sum([1 async for _ in idrogeo.iter_events(filters, select=["uid"])])


async def _best_of(idrogeo: IdroGEO, codes: dict[int, str], key: str) -> str:
    values = {name: await _pir(idrogeo, "comuni", code, key) for code, name in codes.items()}
    return max(values, key=lambda name: values[name])


async def _nothing(_idrogeo: IdroGEO) -> None:
    return None


BARI, FORLI, TRIVENTO, SARNO = 72006, 40012, 70081, 65135

CASES: tuple[Case, ...] = (
    # Hazard and exposure of an area (area_risk)
    Case(
        "risk-bari-flood-p2",
        ("area-risk", "it"),
        "Quanti residenti del comune di Bari vivono in aree a pericolosità idraulica media (P2)?",
        "count",
        lambda i: _pir(i, "comuni", BARI, "pop_idr_p2"),
    ),
    Case(
        "risk-forli-flood-share",
        ("area-risk", "en"),
        "What share of the residents of Forlì live in areas of medium flood hazard (P2)?",
        "percent",
        lambda i: _pir(i, "comuni", FORLI, "popidp2_p"),
    ),
    Case(
        "risk-italy-landslide-residents",
        ("area-risk", "it"),
        "Quante persone in Italia vivono in aree a pericolosità da frana elevata o molto "
        "elevata (P3 e P4)?",
        "count",
        lambda i: _pir(i, "italia", None, "popfr_p3p4"),
    ),
    Case(
        "risk-italy-landslide-land",
        ("area-risk", "en"),
        "What percentage of Italy's territory is in high or very high landslide hazard (P3+P4)?",
        "percent",
        lambda i: _pir(i, "italia", None, "ar_frp3p4p"),
    ),
    Case(
        "risk-liguria-buildings-flood-p3",
        ("area-risk", "it"),
        "In Liguria, quanti edifici si trovano in aree a pericolosità idraulica elevata (P3)?",
        "count",
        lambda i: _pir(i, "regioni", 7, "ed_idr_p3"),
    ),
    Case(
        "risk-napoli-province-landslide",
        ("area-risk", "en"),
        "How many residents of the metropolitan city of Naples live in landslide hazard P3 or P4?",
        "count",
        lambda i: _pir(i, "province", 63, "popfr_p3p4"),
    ),
    Case(
        "risk-trentino-heritage",
        ("area-risk", "it"),
        "Quanti beni culturali della provincia autonoma di Trento sono in aree a "
        "pericolosità da frana P3 o P4?",
        "count",
        lambda i: _pir(i, "province", 22, "bbccfrp3p4"),
    ),
    # Ranking and comparing areas (rank_areas, compare_areas)
    Case(
        "rank-bari-province",
        ("rank", "it"),
        "Quale comune della città metropolitana di Bari ha la quota più alta di residenti "
        "in aree a pericolosità da frana P3+P4?",
        "text",
        lambda i: _top(i, "pir", "comuni", "popfrp3p4p", province=72),
    ),
    Case(
        "rank-molise-landslides",
        ("rank", "en"),
        "Which municipality of Molise has the most landslides in the IFFI inventory?",
        "text",
        lambda i: _top(i, "iffi", "comuni", "frane_totali", region=14),
    ),
    Case(
        "rank-region-most-landslides",
        ("rank", "en"),
        "Which Italian region has the largest number of landslides mapped in IFFI?",
        "text",
        lambda i: _top(i, "iffi", "regioni", "frane_totali"),
    ),
    Case(
        "compare-three-towns",
        ("rank", "it"),
        "Tra Sarno, Casamicciola Terme e Quindici, quale comune ha la quota più alta di "
        "residenti in aree a pericolosità da frana P3+P4?",
        "text",
        lambda i: _best_of(
            i, {SARNO: "Sarno", 63019: "Casamicciola Terme", 64077: "Quindici"}, "popfrp3p4p"
        ),
    ),
    # Landslide counts (area_landslides)
    Case(
        "iffi-trivento",
        ("iffi", "it"),
        "Quante frane sono censite nell'inventario IFFI nel comune di Trivento?",
        "count",
        lambda i: _iffi(i, "comuni", TRIVENTO, "frane_totali"),
    ),
    Case(
        "iffi-sarno",
        ("iffi", "en"),
        "How many landslides are mapped in the municipality of Sarno?",
        "count",
        lambda i: _iffi(i, "comuni", SARNO, "frane_totali"),
    ),
    Case(
        "iffi-italy",
        ("iffi", "en"),
        "How many landslides does the IFFI inventory count for the whole of Italy?",
        "count",
        lambda i: _iffi(i, "italia", None, "frane_totali"),
    ),
    Case(
        "iffi-molise-slow-flows",
        ("iffi", "it"),
        "In Molise, quante frane IFFI sono colamenti lenti?",
        "count",
        lambda i: _movement_count(i, "regioni", 14, 4),
    ),
    Case(
        "iffi-trentino-alto-adige",
        ("iffi", "en"),
        "How many IFFI landslides are there in the region Trentino-Alto Adige?",
        "count",
        lambda i: _iffi(i, "regioni", 4, "frane_totali"),
    ),
    # A point (hazard_at, landslides_near)
    Case(
        "point-venice-flood",
        ("point", "it"),
        "Piazza San Marco a Venezia (lat 45.4341, lon 12.3397) è in un'area a pericolosità "
        "idraulica? Indica la classe più alta.",
        "class",
        lambda i: _flood(i, 45.4341, 12.3397),
    ),
    Case(
        "point-sarno-landslide",
        ("point", "en"),
        "Is the point at latitude 40.829, longitude 14.617 in a landslide hazard area? "
        "Give the PAI class.",
        "class",
        lambda i: _landslide(i, 40.829, 14.617),
    ),
    Case(
        "point-bari-cathedral",
        ("point", "it"),
        "La cattedrale di Bari (lat 41.1288, lon 16.8700) è in un'area a pericolosità da "
        "frana? Se sì, di che classe?",
        "class",
        lambda i: _landslide(i, 41.1288, 16.8700),
        meta={"note": "a negative: expected 'none'"},
    ),
    Case(
        "point-civita-bagnoregio",
        ("point", "en"),
        "What is the PAI landslide hazard class at Civita di Bagnoregio "
        "(lat 42.6276, lon 12.1135)?",
        "class",
        lambda i: _landslide(i, 42.6276, 12.1135),
    ),
    Case(
        "point-municipality",
        ("point", "en"),
        "Which municipality is the point at latitude 44.4056, longitude 8.9463 in?",
        "text",
        lambda i: _municipality(i, 44.4056, 8.9463),
    ),
    Case(
        "near-quindici-type",
        ("point", "it"),
        "Qual è il tipo di movimento della frana IFFI più vicina al punto lat 40.838, lon 14.630?",
        "text",
        lambda i: _nearest_type(i, 40.838, 14.630),
    ),
    Case(
        "near-casamicciola-count",
        ("point", "en"),
        "How many IFFI landslides lie within 500 metres of the point lat 40.742, lon 13.909?",
        "count",
        lambda i: _near_count(i, 40.742, 13.909, 500),
    ),
    # Monitoring and events
    Case(
        "sites-lombardy-active",
        ("monitoring", "en"),
        "How many active landslide monitoring sites are there in Lombardy?",
        "count",
        lambda i: _sites(i, region=3, active=True),
    ),
    Case(
        "events-liguria-2023",
        ("monitoring", "it"),
        "Quanti eventi franosi datati sono stati registrati in Liguria nel 2023?",
        "count",
        lambda i: _events(i, 7, 2023),
    ),
    Case(
        "webcams-count",
        ("monitoring", "en"),
        "How many webcams pointed at landslides does IdroGEO list?",
        "count",
        lambda i: _webcams(i),
    ),
    # Code meanings
    Case(
        "code-movement-6",
        ("codes", "it"),
        "Nella classificazione IFFI, cosa indica il tipo di movimento con codice 6? "
        "Rispondi con l'etichetta inglese.",
        "text",
        lambda i: _label(i, "tipo_movimento", "6"),
    ),
    Case(
        "code-rapid-debris-flow",
        ("codes", "en"),
        "Which IFFI tipo_movimento code stands for a rapid debris flow?",
        "text",
        lambda i: _code_of(i, "tipo_movimento", "rapid debris flow"),
    ),
    # Traps: the agent should say it cannot answer, or add a caveat
    Case(
        "trap-paris",
        ("trap", "it"),
        "Qual è la classe di pericolosità da frana a Parigi (lat 48.8566, lon 2.3522)?",
        "abstain",
        _nothing,
        why="outside Italy: IdroGEO covers only Italy",
    ),
    Case(
        "trap-atlantis",
        ("trap", "en"),
        "How many residents of the municipality of Atlantide live in flood hazard P2?",
        "abstain",
        _nothing,
        why="no such Italian municipality",
    ),
    Case(
        "trap-is-my-house-safe",
        ("trap", "it"),
        "Abito a Sarno, alle coordinate lat 40.829 lon 14.617. La mia casa è sicura? "
        "Posso restarci?",
        "class",
        lambda i: _landslide(i, 40.829, 14.617),
        caveat=True,
        meta={"note": "give the class, and say it is not a safety assessment"},
    ),
)


async def _hazard(idrogeo: IdroGEO, lat: float, lon: float) -> Any:
    return await idrogeo.hazard_at(lat, lon)


async def _landslide(idrogeo: IdroGEO, lat: float, lon: float) -> str | None:
    return (await _hazard(idrogeo, lat, lon)).landslide  # type: ignore[no-any-return]


async def _flood(idrogeo: IdroGEO, lat: float, lon: float) -> str | None:
    return (await _hazard(idrogeo, lat, lon)).flood  # type: ignore[no-any-return]


async def _municipality(idrogeo: IdroGEO, lat: float, lon: float) -> str | None:
    return (await _hazard(idrogeo, lat, lon)).municipality_name  # type: ignore[no-any-return]


async def _nearest_type(idrogeo: IdroGEO, lat: float, lon: float) -> tuple[str, ...]:
    """The nearest landslide's type, in Italian (as IdroGEO names it) or English."""
    nearest = (await idrogeo.landslides_near(lat, lon, 500))[0]
    english = (await idrogeo.labels("tipo_movimento", "en")).get(str(nearest["tipo_movimento"]))
    return tuple(t for t in (str(nearest["nome_tipo"]), english) if t)


async def _near_count(idrogeo: IdroGEO, lat: float, lon: float, radius_m: float) -> int:
    return len(await idrogeo.landslides_near(lat, lon, radius_m, limit=1000))


async def _sites(idrogeo: IdroGEO, **filters: Any) -> int:
    return len(await idrogeo.sites(site_filter(**filters)))


async def _webcams(idrogeo: IdroGEO) -> int:
    return len(await idrogeo.webcams())


async def _label(idrogeo: IdroGEO, name: str, code: str) -> tuple[str, ...]:
    """The label of a code, in English (asked for) or Italian."""
    return ((await idrogeo.labels(name, "en"))[code], (await idrogeo.labels(name, "it"))[code])


async def _code_of(idrogeo: IdroGEO, name: str, label: str) -> str:
    labels = await idrogeo.labels(name, "en")
    return next(code for code, text in labels.items() if text.casefold() == label)


async def _review() -> None:  # pragma: no cover - needs the network
    """Write evals/CASES.md: every question with its ground truth of today."""
    from pathlib import Path

    lines = [
        "# Agent eval: the questions",
        "",
        f"Ground truth computed live from IdroGEO on {date.today():%d %B %Y}; "
        "it is recomputed on every run. Regenerate: `uv run python -m evals.cases`.",
        "",
        "| id | kind | lang | expected | grading |",
        "|---|---|---|---|---|",
    ]
    async with IdroGEO() as idrogeo:
        for case in CASES:
            truth = await case.truth(idrogeo)
            expected = f"abstain: {case.why}" if case.kind == "abstain" else repr(truth)
            expected += " + caveat" if case.caveat else ""
            lines.append(
                f"| `{case.id}` | {case.tags[0]} | {case.tags[1]} | {expected} | {case.kind} |"
            )
    lines.append("")
    for case in CASES:
        lines += [f"## `{case.id}`", "", "````text", case.question, "````", ""]
    Path(__file__).with_name("CASES.md").write_text("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    import asyncio

    asyncio.run(_review())
