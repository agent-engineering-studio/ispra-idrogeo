"""The IdroGEO REST API (``/api``), as pure request builders and parsers.

Reading needs no account; only writes and a few detail endpoints ask for a
login. Summaries and hazard indicators exist for Italy, macro-regions,
regions, provinces and municipalities (ISTAT codes); the dictionaries are the
code lists the files use (movement types, causes, damage, …).

Searches take a JSON object of filters whose syntax is described in ISPRA's
technical manual; an empty object matches everything, so always page with
``limit`` and ``offset``.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from ispra_idrogeo.errors import IdrogeoError
from ispra_idrogeo.sources import BASE_URL

API_URL = f"{BASE_URL}/api"

#: Which summary: the IFFI inventory counts, or hazard and risk indicators.
Summary = Literal["iffi", "pir"]
Level = Literal["italia", "macroregioni", "regioni", "province", "comuni"]

#: The reference lists you search by text, and what the text is matched on:
#: geological units (sigla, nome_unita), aerial survey flights (id, nome,
#: data), bibliography (authors, title, journal), institutions and
#: professional bodies (name), funding sources.
Lookup = Literal["formazioni", "voli", "bibliografie", "istituzioni", "ordini", "finanziamenti"]
LOOKUPS: tuple[Lookup, ...] = (
    "formazioni",
    "voli",
    "bibliografie",
    "istituzioni",
    "ordini",
    "finanziamenti",
)

#: The levels that have a list, and the field of each item that is its code.
CODE_FIELDS: dict[Level, str] = {"regioni": "cod_reg", "province": "cod_prov", "comuni": "pro_com"}


def summary_path(summary: Summary, level: Level, code: int | None = None) -> str:
    """``iffi/regioni/16``; without ``code``, the list of that level (``italia`` takes none)."""
    if level == "italia":
        if code is not None:
            raise ValueError("'italia' takes no code")
        return f"{summary}/italia"
    if code is None:
        if level == "macroregioni":
            raise ValueError("'macroregioni' has no list: give a code")
        return f"{summary}/{level}"
    return f"{summary}/{level}/{int(code)}"


def level_codes(level: Level, items: list[dict[str, Any]]) -> list[int]:
    """The ISTAT codes in the list of a level, in the order the API gives them."""
    try:
        field = CODE_FIELDS[level]
    except KeyError:
        raise ValueError(f"{level!r} has no list: one of {tuple(CODE_FIELDS)}") from None
    try:
        return [int(item[field]) for item in items]
    except (KeyError, TypeError, ValueError):
        raise IdrogeoError(f"IdroGEO list of {level!r} without {field!r} codes") from None


def since_filter(filters: dict[str, Any] | None, since: datetime | None) -> dict[str, Any]:
    """``filters`` plus "modified at or after ``since``", for incremental updates.

    ``since`` must carry a time zone (``datetime.now(UTC)``): IdroGEO stores
    ``modified`` in UTC, and a naive time would be read in the server's.
    """
    out = dict(filters or {})
    if since is None:
        return out
    if since.tzinfo is None:
        raise ValueError("since needs a time zone, e.g. datetime(2026, 11, 1, tzinfo=UTC)")
    if "modified" in out:
        raise ValueError("give since or a 'modified' filter, not both")
    out["modified"] = f"gte.{since.isoformat()}"
    return out


def lookup_params(kind: str, text: str, limit: int) -> dict[str, str]:
    """The query string of a text search in a reference list."""
    if kind not in LOOKUPS:
        raise ValueError(f"unknown list {kind!r}: one of {LOOKUPS}")
    if not text.strip():
        raise ValueError("give some text to search for")
    if limit < 1:
        raise ValueError("limit must be ≥ 1")
    return {"q": text.strip(), "limit": str(limit)}


def search_params(
    *, limit: int, offset: int = 0, select: list[str] | None = None, order: str | None = None
) -> dict[str, str]:
    """The query string of a search."""
    if limit < 1 or offset < 0:
        raise ValueError("limit must be ≥ 1 and offset ≥ 0")
    params = {"limit": str(limit), "offset": str(offset)}
    if select:
        params["select"] = ",".join(select)
    if order:
        params["order"] = order
    return params


_NOT_JSON = object()


def parse(status_code: int, body: bytes | str) -> Any:
    """The decoded JSON of a 200; :class:`IdrogeoError` with the API's message otherwise."""
    try:
        data: Any = json.loads(body)
    except ValueError:
        data = _NOT_JSON
    if status_code != 200:
        detail = data.get("message") if isinstance(data, dict) else str(body)[:200]
        raise IdrogeoError(f"IdroGEO API refused (HTTP {status_code}): {detail}")
    if data is _NOT_JSON:
        raise IdrogeoError(f"IdroGEO API did not return JSON: {str(body)[:200]!r}")
    return data


def parse_list(status_code: int, body: bytes | str) -> list[dict[str, Any]]:
    """A JSON list of objects (searches, level lists)."""
    data = parse(status_code, body)
    if not isinstance(data, list):
        raise IdrogeoError(f"IdroGEO API returned {type(data).__name__}, expected a list")
    return data
