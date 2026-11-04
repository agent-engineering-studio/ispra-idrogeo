"""How a submitted answer is compared with the live ground truth: pure, offline.

The agent ends every case with ``submit_answer(answer, status, unit, source,
notes)``. ``grade`` turns that and the case's truth into two binary metrics:

- ``correct`` (the headline): the answer matches the truth, with the
  tolerances of ``Kind`` below; a trap is passed only by
  ``status="not_available"``, and a case with ``caveat`` also needs the notes
  to say it is not a safety assessment or to point to the authorities.
- ``cited_source``: the source names ISPRA or IdroGEO, as CC BY asks.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

from evals.cases import Case

#: Answers that mean "no class here".
NONE_WORDS = frozenset(
    {"none", "no", "nessuna", "nessuno", "null", "n/a", "na", "nothing", "not in", "non"}
)
#: Words that show the caveat on a "is my house safe?" question.
CAVEAT_WORDS = (
    "not a safety",
    "non e una valutazione",
    "non costituisce",
    "autorita",
    "authorit",
    "protezione civile",
    "civil protection",
    "valore legale",
    "legal value",
)
_ARTICLES = frozenset({"il", "lo", "la", "i", "gli", "le", "l", "the", "a", "an", "di", "of"})
_CLASS = re.compile(r"\b(p[1-4]|aa)\b")
_MULTIPLIERS = {
    "million": 1e6,
    "milioni": 1e6,
    "milione": 1e6,
    "mln": 1e6,
    "thousand": 1e3,
    "mila": 1e3,
}


def grade(
    case: Case, truth: Any, submission: Mapping[str, Any] | None
) -> tuple[dict[str, float], dict[str, str]]:
    """``({"correct": 0|1, "cited_source": 0|1}, {"correct": why})``."""
    if submission is None:
        return {"correct": 0.0, "cited_source": 0.0}, {"correct": "no submit_answer call"}
    answer = str(submission.get("answer", ""))
    status = submission.get("status")
    cited = float(bool(re.search(r"ispra|idrogeo", str(submission.get("source", "")), re.I)))
    if case.kind == "abstain":
        ok = status == "not_available"
        why = "abstained" if ok else f"answered {answer!r} instead of not_available"
    elif status == "not_available":
        ok, why = False, f"said not available; expected {truth!r}"
    else:
        ok, why = _matches(case, truth, answer)
        if ok and case.caveat and not has_caveat(str(submission.get("notes", ""))):
            ok, why = False, "right class but no caveat (not a safety assessment)"
    return {"correct": float(ok), "cited_source": cited}, {"correct": why}


def _matches(case: Case, truth: Any, answer: str) -> tuple[bool, str]:
    if case.kind in ("count", "number", "percent"):
        value = parse_number(answer, decimal=case.kind == "percent")
        if value is None:
            return False, f"no number in {answer!r}"
        ok = number_ok(case.kind, float(truth), value)
        return ok, f"{value:g} vs {truth!r}"
    if case.kind == "class":
        return class_ok(truth, answer), f"{answer!r} vs {truth!r}"
    alternatives = truth if isinstance(truth, Sequence) and not isinstance(truth, str) else [truth]
    ok = any(text_ok(str(t), answer) for t in alternatives)
    return ok, f"{answer!r} vs {list(alternatives)!r}"


def number_ok(kind: str, truth: float, value: float) -> bool:
    """Counts: exact below 1,000, else within 0.5%. Percents: within 0.05 points."""
    if kind == "percent":
        return abs(value - truth) <= 0.05 or abs(value * 100 - truth) <= 0.05
    if kind == "count" and abs(truth) < 1000:
        return round(value) == round(truth)
    return abs(value - truth) <= 0.005 * abs(truth)


def class_ok(truth: str | None, answer: str) -> bool:
    """The first class named in the answer is the truth; ``None`` wants a 'none'."""
    plain = normalize(answer)
    found = _CLASS.findall(plain)
    if truth is None:
        return not found and (plain in NONE_WORDS or plain.split(" ")[0] in NONE_WORDS)
    return bool(found) and found[0] == truth.casefold()


def text_ok(truth: str, answer: str) -> bool:
    """Same words after normalising, or the truth inside a short answer."""
    want, got = normalize(truth), normalize(answer)
    if not want:
        return False
    if want == got:
        return True
    return f" {want} " in f" {got} " and len(got) <= len(want) + 30


def has_caveat(notes: str) -> bool:
    plain = normalize(notes)
    return any(normalize(word) in plain for word in CAVEAT_WORDS)


def normalize(text: str) -> str:
    """Lower case, no accents, no punctuation or articles: "l'Aquila" ~ "aquila"."""
    plain = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    plain = re.sub(r"[^\w/]+", " ", plain)
    return " ".join(w for w in plain.split() if w not in _ARTICLES)


def parse_number(text: str, *, decimal: bool = False) -> float | None:
    """The first number in ``text``, with Italian or English separators and
    "million"/"milioni": "1.284.960", "1,284,960", "1.28 million", "89,6%".

    ``decimal`` reads a lone separator as the decimal one even before three
    digits ("89,641" is 89.641), as a percentage needs.
    """
    match = re.search(r"-?\d[\d.,\s]*\d|-?\d", text.replace("\u00a0", " "))
    if not match:
        return None
    raw = re.sub(r"\s", "", match.group())
    if "," in raw and "." in raw:  # the last separator is the decimal one
        point = "," if raw.rfind(",") > raw.rfind(".") else "."
        raw = raw.replace("." if point == "," else ",", "").replace(",", ".")
    elif raw.count(",") == 1 and (decimal or len(raw.split(",")[1]) != 3):
        raw = raw.replace(",", ".")
    elif raw.count(".") == 1 and (decimal or len(raw.split(".")[1]) != 3):
        pass  # 89.6
    else:
        raw = raw.replace(",", "").replace(".", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    tail = text[match.end() :].strip().casefold()
    for word, factor in _MULTIPLIERS.items():
        if tail.startswith(word):
            return value * factor
    return value
