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
from typing import Any, Literal

from ispra_idrogeo.errors import IdrogeoError
from ispra_idrogeo.sources import BASE_URL

API_URL = f"{BASE_URL}/api"

#: Which summary: the IFFI inventory counts, or hazard and risk indicators.
Summary = Literal["iffi", "pir"]
Level = Literal["italia", "macroregioni", "regioni", "province", "comuni"]


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


def parse(status_code: int, body: bytes | str) -> Any:
    """The decoded JSON of a 200; :class:`IdrogeoError` with the API's message otherwise."""
    try:
        data: Any = json.loads(body)
    except ValueError:
        data = None
    if status_code != 200:
        detail = data.get("message") if isinstance(data, dict) else str(body)[:200]
        raise IdrogeoError(f"IdroGEO API refused (HTTP {status_code}): {detail}")
    if data is None:
        raise IdrogeoError(f"IdroGEO API did not return JSON: {str(body)[:200]!r}")
    return data


def parse_list(status_code: int, body: bytes | str) -> list[dict[str, Any]]:
    """A JSON list of objects (searches, level lists)."""
    data = parse(status_code, body)
    if not isinstance(data, list):
        raise IdrogeoError(f"IdroGEO API returned {type(data).__name__}, expected a list")
    return data
