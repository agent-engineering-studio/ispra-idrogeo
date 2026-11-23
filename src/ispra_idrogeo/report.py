"""The report of one municipality, in Italian: figures from a template, no model.

``idrogeo report 65135`` writes, for Sarno, the residents, land and buildings
in landslide and flood hazard, the predisposition classes, the IFFI
landslides, how far to trust them, what nobody measured, and the sources.
Every number of the text is checked against the figures it was written from
(:func:`~ispra_idrogeo.grounding.check_text` and
:func:`~ispra_idrogeo.grounding.check_claims`) before it is returned.

**Not an alert.** It uses no rain. For warnings, the bulletins of the Civil
Protection Department and of the region.

With an Anthropic key, :func:`summarize` asks a model for a short summary in
plain words. The model writes only the words: a summary with a number that
the figures do not back is refused, never saved.
"""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ispra_idrogeo.grounding import SOURCES, check_claims, check_text
from ispra_idrogeo.predisposition import ITALIAN, predisposition
from ispra_idrogeo.reliability import reliability

if TYPE_CHECKING:
    from ispra_idrogeo.client import IdroGEO

#: What each predisposition class measures, in Italian.
MEASURES_IT = {
    "landslide": "quota di territorio in pericolo frana P3+P4 (mappa PAI 2024)",
    "flood": "quota di territorio nello scenario di alluvione P2 (tempo di ritorno 100-200 anni)",
}
RULE_IT = "nessuna 0% · bassa <5% · media 5-15% · alta 15-30% · molto alta ≥30%"
NOTE_IT = (
    "È una classe di predisposizione calcolata sulle mappe ufficiali di pericolo, non "
    "un'allerta: non usa la pioggia. Per le allerte valgono i bollettini della Protezione "
    "Civile e della Regione."
)
NOT_MEASURED_IT = (
    "la precisione delle posizioni IFFI: ogni record dice «esatta»",
    "quanto è completo l'inventario: non c'è un riferimento con cui confrontarlo",
    "se un evento e una frana IFFI sono la stessa frana",
    "l'anno in cui ogni Regione ha rilevato le sue frane: ISPRA non lo pubblica",
)
#: The numbers the template itself writes (thresholds, census year, the 1 km of the events).
TEMPLATE_FIGURES = {"census": 2021, "since": 2018, "within_km": 1, "steps": [0, 5, 15, 30]}
#: The model :func:`summarize` asks by default.
MODEL = "claude-sonnet-5-5"
NOT_AVAILABLE = "non disponibile"


def number_it(value: int) -> str:
    """A whole number with the Italian thousands separator: 1.234."""
    return f"{value:,}".replace(",", ".")


def share_it(share: float | None) -> str:
    """A share from 0 to 1 as an Italian percentage: 0.039 is "3,9%"."""
    if share is None:
        return NOT_AVAILABLE
    value = share * 100
    return "meno dello 0,1%" if 0 < value < 0.1 else f"{value:.1f}%".replace(".", ",")


def notes_it(found: dict[str, Any]) -> list[str]:
    """The notes of :func:`~ispra_idrogeo.reliability.reliability`, in Italian."""
    landslides = found["landslides"]
    if not landslides:
        notes = ["In questo Comune IFFI non censisce nessuna frana."]
    else:
        day = round((found["day_share"] or 0) * landslides)
        edited = share_it(found["edited_since_2021_share"])
        notes = [
            f"{number_it(day)} frane IFFI su {number_it(landslides)} "
            f"({share_it(found['day_share'])}) hanno una data al giorno.",
            f"Record IFFI modificati dal 2021: {edited}.",
        ]
    if found["dated_since_2018"]:
        notes.append(
            f"Dal 2018: {found['iffi_day_since_2018']} frane IFFI datate al giorno e "
            f"{found['events_since_2018']} eventi, {found['events_within_1km']} con il punto "
            "noto entro 1 km."
        )
    else:
        notes.append(
            "Nessuna frana datata al giorno dal 2018: qui nessun dato può verificare una soglia "
            "di pioggia."
        )
    return notes


def _value(value: Any) -> float | None:
    """A figure, or ``None`` for missing and IdroGEO's "not available" (-1)."""
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        return None
    return float(value)


def _count(value: Any) -> str:
    found = _value(value)
    return NOT_AVAILABLE if found is None else number_it(round(found))


def _percent(value: Any) -> str:
    """A share already in percent (IdroGEO's ``*_p`` keys): 1.278 is "1,3%"."""
    found = _value(value)
    return NOT_AVAILABLE if found is None else f"{found:.1f}%".replace(".", ",")


class UngroundedError(ValueError):
    """A text with numbers the figures do not back."""

    def __init__(self, unmatched: list[str], misquoted: list[str]) -> None:
        self.unmatched, self.misquoted = unmatched, misquoted
        wrong = ", ".join([*unmatched, *misquoted])
        super().__init__(f"numbers not backed by the figures: {wrong}")


def check(text: str, facts: dict[str, Any]) -> None:
    """Raise :class:`UngroundedError` if a number of ``text`` is not backed by ``facts``."""
    unmatched = check_text(text, facts)
    misquoted = [m.said for m in check_claims(text, facts)]
    if unmatched or misquoted:
        raise UngroundedError(unmatched, misquoted)


@dataclass(frozen=True)
class AreaReport:
    """The text of a report and the figures it was written from."""

    code: int
    name: str
    text: str
    facts: dict[str, Any]
    retrieved_at: str
    summary: str | None = field(default=None)

    def markdown(self) -> str:
        if not self.summary:
            return self.text
        title, _, body = self.text.partition("\n\n")
        return f"{title}\n\n**In breve.** {self.summary}\n\n{body}"


def render(
    code: int,
    pir: dict[str, Any],
    iffi: dict[str, Any],
    trust: dict[str, Any] | None,
    retrieved_at: str,
) -> AreaReport:
    """The report from the summaries ``pir`` and ``iffi`` and the reliability ``trust``."""
    name = str(pir.get("nome") or iffi.get("nome") or code)
    classes = predisposition(pir)

    def step(kind: str) -> str:
        found = classes[kind]  # type: ignore[index]
        return ITALIAN[found.step] if found.step else NOT_AVAILABLE

    lines = [
        f"# {name}: i dati di IdroGEO",
        "",
        f"Comune {name}, codice ISTAT {code}. Dati letti da ISPRA IdroGEO il "
        f"{retrieved_at[:10]}. Questo testo non è un'allerta: non usa la pioggia. Per le "
        "allerte valgono i bollettini della Protezione Civile e della Regione.",
        "",
        "## Pericolo ed esposizione",
        "",
        f"- Residenti: {_count(pir.get('pop_res021'))} (censimento 2021).",
        f"- Pericolo frana P3+P4: territorio {_percent(pir.get('ar_frp3p4p'))}; residenti "
        f"{_count(pir.get('popfr_p3p4'))} ({_percent(pir.get('popfrp3p4p'))} del totale); "
        f"edifici {_count(pir.get('ed_fr_p3p4'))}.",
        f"- Pericolo alluvione P2: territorio {_percent(pir.get('aridp2_p'))}; residenti "
        f"{_count(pir.get('pop_idr_p2'))} ({_percent(pir.get('popidp2_p'))} del totale); "
        f"edifici {_count(pir.get('ed_idr_p2'))}.",
        f"- Classe di predisposizione: frana {step('landslide')}, alluvione {step('flood')}. "
        f"Regola: {RULE_IT}. {NOTE_IT}",
        "",
        "## Frane censite (IFFI)",
        "",
        f"- Frane censite: {_count(iffi.get('frane_totali'))}.",
        f"- Eventi di frana registrati: {_count(iffi.get('eventi_totali'))}.",
        "",
        "## Quanto fidarsi",
        "",
    ]
    derived: dict[str, Any] = {}
    if trust is None:
        lines.append(f"- Affidabilità: {NOT_AVAILABLE} per questo Comune.")
    else:
        lines += [f"- {note}" for note in notes_it(trust)]
        derived = {
            "day": round((trust["day_share"] or 0) * trust["landslides"]),
            "day_pct": (trust["day_share"] or 0) * 100,
            "edited_pct": (trust["edited_since_2021_share"] or 0) * 100,
        }
    lines += ["", "Non misurato:", *[f"- {item}" for item in NOT_MEASURED_IT]]
    body = "\n".join(lines)
    facts = {
        "pir": pir,
        "iffi": iffi,
        "reliability": trust,
        "derived": derived,
        "template": TEMPLATE_FIGURES,
        "code": code,
        "retrieved_at": retrieved_at,
    }
    check(body, facts)  # the template's numbers, before the sources (which have versions)
    sources = [
        "",
        "## Fonti",
        "",
        f"- Pericolo ed esposizione: {SOURCES['indicators']}",
        f"- Frane: {SOURCES['iffi']}",
        f"- Eventi: {SOURCES['events']}",
        "",
        "Testo generato da ispra-idrogeo, non affiliato a ISPRA.",
    ]
    text = body + "\n" + "\n".join(sources) + "\n"
    return AreaReport(code, name, text, facts, retrieved_at)


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return plain.casefold().strip()


async def find_municipality(idrogeo: IdroGEO, name_or_code: str) -> int:
    """The ISTAT code of a municipality from its code or its exact name."""
    if name_or_code.strip().isdigit():
        return int(name_or_code)
    wanted = _fold(name_or_code)
    rows = await idrogeo.summary("iffi", "comuni")
    found = [r for r in rows if _fold(str(r.get("nome", ""))) == wanted]
    if len(found) != 1:
        close = sorted(str(r["nome"]) for r in rows if wanted in _fold(str(r.get("nome", ""))))
        hint = f"; did you mean {', '.join(close[:5])}?" if close else ""
        many = "more than one" if found else "no"
        raise ValueError(f"{many} municipality named {name_or_code!r}{hint}")
    return int(found[0]["uid"])


async def area_report(idrogeo: IdroGEO, code: int) -> AreaReport:
    """The report of the municipality ``code``: two requests, no model."""
    pir = await idrogeo.summary("pir", "comuni", code)
    iffi = await idrogeo.summary("iffi", "comuni", code)
    try:
        trust: dict[str, Any] | None = reliability("comuni", code).as_dict()
    except ValueError:  # a municipality the shipped table does not know
        trust = None
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return render(code, dict(pir), dict(iffi), trust, now)


PROMPT = """\
Scrivi un riassunto in italiano semplice, al massimo cinque frasi brevi, del
rapporto qui sotto, per i cittadini di {name}. Usa solo i numeri che sono nel
rapporto, scritti come lì; non calcolare, non stimare, non aggiungere numeri.
Non scrivere che una frana o un'alluvione arriverà: non è un'allerta. Scrivi
solo il riassunto, senza titolo.

{text}"""


def summarize(report: AreaReport, client: Any = None, model: str = MODEL) -> AreaReport:
    """``report`` with a short summary by a model, checked before it is returned.

    ``client`` is an ``anthropic.Anthropic`` (made from ``ANTHROPIC_API_KEY`` if
    omitted). Each call is paid. Raises :class:`UngroundedError` if the summary
    has a number the figures do not back: then nothing is saved.
    """
    if client is None:  # pragma: no cover - needs the package, a key and money
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError("a summary needs: pip install 'ispra-idrogeo[ai]'") from exc
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    prompt = PROMPT.format(name=report.name, text=report.text)
    response = client.messages.create(
        model=model, max_tokens=1000, messages=[{"role": "user", "content": prompt}]
    )
    summary = " ".join(b.text for b in response.content if b.type == "text").strip()
    check(summary, report.facts)
    return AreaReport(
        report.code, report.name, report.text, report.facts, report.retrieved_at, summary
    )
