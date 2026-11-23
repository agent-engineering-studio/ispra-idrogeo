"""The shapes of the MCP tools' answers, published as output schemas.

Every answer carries ``source`` (citation and licence) and ``retrieved_at``
(UTC). A list comes wrapped as ``results`` with its ``count``. The keys named
here are stable; an answer may carry more (the API's own fields), and the
schemas allow them, so nothing is dropped from the structured content.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

#: Read by pydantic (and so by the MCP server): keep the keys not named here.
_OPEN = {"extra": "allow"}


class Grounded(TypedDict):
    """Any answer: its source and when it was read."""

    source: str
    retrieved_at: str


class Results(Grounded):
    """A list of rows, with how many there are."""

    results: list[Any]
    count: int


class Area(Grounded):
    """The figures of one area (a municipality, a province, a region, Italy)."""

    nome: NotRequired[str]


class Ranking(Grounded):
    """Areas ordered by one indicator."""

    indicator: str
    order: str
    areas_compared: int
    ranking: list[dict[str, Any]]


class Comparison(Grounded):
    """Areas side by side."""

    indicators: list[str]
    areas: list[dict[str, Any]]


class HazardAt(Grounded):
    """What the official maps say at a point. Not an alert."""

    lat: float
    lon: float
    landslide: str | None
    flood: str | None
    flood_scenarios: list[str]
    municipality: int | None
    municipality_name: str | None


class Reliability(Grounded):
    """How far IFFI and the events can be trusted in one area."""

    level: str
    code: int
    name: str | None
    landslides: int
    dated_share: float | None
    day_share: float | None
    notes: list[str]
    not_measured: list[str]


class Misquoted(TypedDict):
    """A number said of an indicator it does not match."""

    said: str
    key: str
    fact: float


class Checked(TypedDict):
    """The result of check_answer."""

    unmatched: list[str]
    misquoted: list[Misquoted]
    ok: bool


for _shape in (Grounded, Results, Area, Ranking, Comparison, HazardAt, Reliability):
    setattr(_shape, "__pydantic_config__", _OPEN)  # noqa: B010 - TypedDict bodies take no values
