"""Grounded answers: where each figure comes from, and numbers nobody can back.

The rule for every AI use of this library is *numbers come from the data,
words from the model*. Two pieces make it checkable:

- :data:`SOURCES` and :func:`grounded`: every answer of ``idrogeo-mcp``
  carries the source, the licence and the time it was read, so the credit
  ISPRA asks for reaches the final answer.
- :func:`check_text`: the numbers of a text (a model's answer, a report)
  that match no figure of the facts it was written from. An empty list means
  every number was found.

A number matches a figure when the figure, rounded the way the number is
written, equals it: ``12.3`` matches 12.27, ``1.3 million`` matches
1,278,455, ``1,300`` matches 1,283 (a round number is read as rounded to its
zeros). ``1,278`` is read both ways, English (1278) and Italian (1.278).
Digits inside words (``P4``, ``EPSG:32632``) and list markers (``1.`` at the
start of a line) are not numbers. Dates (``2026-11-22``, ``22/11/2026``)
must appear among the dates of the facts.

This checks that a number exists in the facts, not that it is said of the
right thing: "Bari has 53 landslides" passes if 53 is any figure of the
facts. Pass only the facts the text was written from.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

Kind = Literal["indicators", "iffi", "events", "hazard", "monitoring", "idrogeo", "warehouse"]

#: The citation and licence of each kind of answer.
SOURCES: dict[Kind, str] = {
    "indicators": (
        "ISPRA (2024) Pericolosità e indicatori di rischio frane; ISPRA (2020) Pericolosità e "
        "indicatori di rischio alluvioni \u2013 Piattaforma IdroGEO, https://idrogeo.isprambiente.it,"
        " CC BY 4.0"
    ),
    "iffi": (
        "ISPRA \u2013 Regioni e Province Autonome. Inventario dei Fenomeni Franosi in Italia - "
        "IFFI. idrogeo.isprambiente.it, CC BY-SA 4.0"
    ),
    "events": (
        "ISPRA \u2013 Regioni e Province Autonome. Inventario dei Fenomeni Franosi in Italia - "
        "IFFI, eventi franosi. idrogeo.isprambiente.it, CC BY-SA 4.0"
    ),
    "hazard": (
        "ISPRA \u2014 IdroGEO map service: PAI landslide and flood hazard mosaics, "
        "https://idrogeo.isprambiente.it (landslide mosaic v. 5.0 2024 CC BY 4.0, v. 4.0 "
        "2020-2021 CC BY-SA 4.0; flood mosaic v. 5.0 2020 CC BY-SA 4.0; the service does not "
        "say which edition it shows)"
    ),
    "monitoring": (
        "ISPRA \u2014 IdroGEO, monitoring sites, https://idrogeo.isprambiente.it, CC BY 4.0"
    ),
    "idrogeo": "ISPRA \u2014 IdroGEO, https://idrogeo.isprambiente.it, CC BY 4.0",
    "warehouse": (
        "ISPRA \u2014 IdroGEO open data, local copy (idrogeo sync): IFFI and the hazard mosaics "
        "CC BY-SA 4.0, citations in ispra_idrogeo.warehouse.SOURCES"
    ),
}


def retrieved_at() -> str:
    """Now, in UTC, to the second: when an answer was read from IdroGEO."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def grounded(answer: Any, kind: Kind) -> dict[str, Any]:
    """``answer`` with its ``source`` and ``retrieved_at``.

    A dict gains the two keys (a key it already has is kept, and the source
    goes under ``idrogeo_source``); anything else becomes
    ``{"results": answer, "count": …, "source": …, "retrieved_at": …}``.
    """
    meta = {"source": SOURCES[kind], "retrieved_at": retrieved_at()}
    if isinstance(answer, dict):
        out = dict(answer)
        for key, value in meta.items():
            out["idrogeo_" + key if key in out else key] = value
        return out
    out = {"results": answer}
    if isinstance(answer, list):
        out["count"] = len(answer)
    return {**out, **meta}


# Numbers in text


@dataclass(frozen=True)
class Number:
    """A number as written, and the values it can mean with their precision."""

    text: str
    readings: tuple[tuple[float, float], ...]  # (value, unit of the last digit written)


_SCALES = {
    "thousand": 1e3,
    "thousands": 1e3,
    "mila": 1e3,
    "million": 1e6,
    "millions": 1e6,
    "milione": 1e6,
    "milioni": 1e6,
    "mln": 1e6,
    "billion": 1e9,
    "miliardo": 1e9,
    "miliardi": 1e9,
}
_NUMBER = re.compile(
    r"(?<![\w.,:/\-])"  # not inside a word, a code, a decimal, a time or a date
    r"[-\u2212]?\d+(?:[.,\u00a0\u202f']\d+)*"
    r"(?![\w:/]|[.,]\d|-\d)"
    r"(?:\s*(" + "|".join(sorted(_SCALES, key=len, reverse=True)) + r")\b)?",
    re.IGNORECASE,
)
_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)|(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")
_LIST_MARKER = re.compile(r"^\s*\d{1,2}[.)]\s", re.MULTILINE)


def _readings(digits: str) -> list[tuple[float, float]]:
    """Every value ``digits`` can mean (``1,278`` is 1278 or 1.278), with its unit."""
    digits = digits.replace("\u2212", "-")
    negative = digits.startswith("-")
    digits = digits.lstrip("-")
    groups = re.split(r"[.,\u00a0\u202f']", digits)
    seps = re.findall(r"[.,\u00a0\u202f']", digits)
    found: list[tuple[float, float]] = []
    if not seps:
        value = float(digits)
        zeros = len(digits) - len(digits.rstrip("0")) if value else 0
        found.append((value, 10.0**zeros))
    else:
        # the last separator as a decimal point (only . or ,), the others as thousands
        decimal_ok = seps[-1] in ".," and len(set(seps[:-1])) <= 1
        if decimal_ok and (not seps[:-1] or seps[-1] not in seps[:-1]):
            whole, frac = "".join(groups[:-1]), groups[-1]
            if all(len(g) == 3 for g in groups[1:-1]):
                found.append((float(f"{whole}.{frac}"), 10.0 ** -len(frac)))
        # every separator as thousands: groups of three after the first
        if len(set(seps)) == 1 and all(len(g) == 3 for g in groups[1:]):
            whole = "".join(groups)
            zeros = len(whole) - len(whole.rstrip("0")) if int(whole) else 0
            found.append((float(whole), 10.0**zeros))
    return [(-v if negative else v, u) for v, u in found]


def numbers(text: str) -> list[Number]:
    """The numbers of ``text``, in order, skipping dates, list markers and codes."""
    blanked = _DATE.sub(lambda m: " " * len(m.group(0)), text)
    blanked = _LIST_MARKER.sub(lambda m: " " * len(m.group(0)), blanked)
    found = []
    for match in _NUMBER.finditer(blanked):
        digits, scale = match.group(0), match.group(1)
        if scale:
            digits = digits[: match.start(1) - match.start(0)].strip()
        factor = _SCALES[scale.lower()] if scale else 1.0
        readings = tuple((v * factor, u * factor) for v, u in _readings(digits))
        if readings:
            found.append(Number(match.group(0).strip(), readings))
    return found


def _dates(text: str) -> Iterator[str]:
    for m in _DATE.finditer(text):
        if m.group(1):
            yield f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        else:
            yield f"{m.group(6)}-{int(m.group(5)):02d}-{int(m.group(4)):02d}"


def _figures(facts: Any) -> Iterator[float | str]:
    """Every number of ``facts`` (dict keys included) and every string in it."""
    if isinstance(facts, dict):
        for key, value in facts.items():
            yield from _figures(key)
            yield from _figures(value)
    elif isinstance(facts, list | tuple):
        for value in facts:
            yield from _figures(value)
    elif isinstance(facts, bool) or facts is None:
        return
    elif isinstance(facts, int | float):
        if math.isfinite(facts):
            yield float(facts)
    elif isinstance(facts, str):
        yield facts
        if re.fullmatch(r"-?\d+(\.\d+)?", facts.strip()):
            yield float(facts)


def check_text(text: str, facts: Any, question: str = "") -> list[str]:
    """The numbers and dates of ``text`` that match no figure of ``facts``.

    ``facts`` is what the text was written from: tool results, a dict, a list.
    Numbers that appear in ``question`` are allowed too.
    """
    figures = list(_figures(facts))
    values = [f for f in figures if isinstance(f, float)]
    strings = [f for f in figures if isinstance(f, str)]
    asked = [r for n in numbers(question) for r in n.readings]
    known_dates = {d for s in [*strings, question] for d in _dates(s)}

    def backed(number: Number) -> bool:
        for value, unit in number.readings:
            tolerance = unit / 2 + 1e-9 * max(1.0, abs(value))
            if any(abs(f - value) <= tolerance for f in values):
                return True
            if any(abs(v - value) <= 1e-9 * max(1.0, abs(v)) for v, _ in asked):
                return True
        return False

    missing = [n.text for n in numbers(text) if not backed(n)]
    missing += [d for d in _dates(text) if d not in known_dates]
    return missing
