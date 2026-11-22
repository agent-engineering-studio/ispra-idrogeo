"""The predisposition class of an area: how much of its land is in official hazard.

**Not an alert, and no rain.** It says how much of a municipality (or a
province, a region) the official maps put in hazard, in five steps with
fixed thresholds, so two places can be compared at a glance. It never says
whether a landslide or a flood is coming: that depends on the rain, and the
official alert is the bulletin of the Civil Protection Department and of the
region.

- **landslide**: the share of land in PAI landslide hazard P3 + P4 of the
  2024 mosaic (``ar_frp3p4p`` of ``summary("pir", …)``);
- **flood**: the share of land in flood scenario P2, floods every 100 to 200
  years, the reference scenario of D.Lgs. 49/2010 (``aridp2_p``).

On 22 November 2026, of the 7,899 municipalities: landslide none 2,126, low
2,674, medium 1,519, high 926, very high 654; flood none 1,289, low 3,470,
medium 1,764, high 774, very high 602.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal

Kind = Literal["landslide", "flood"]
Step = Literal["none", "low", "medium", "high", "very high"]

#: The lower bound (share of land, %) of each step above "none".
THRESHOLDS: tuple[tuple[float, Step], ...] = (
    (30.0, "very high"),
    (15.0, "high"),
    (5.0, "medium"),
    (0.0, "low"),
)
#: Where each class reads its share, and what it measures.
SHARES: dict[Kind, tuple[str, str]] = {
    "landslide": ("ar_frp3p4p", "share of land in PAI landslide hazard P3+P4 (2024 mosaic)"),
    "flood": ("aridp2_p", "share of land in flood scenario P2 (100-200 years)"),
}
#: Said with every class.
NOTE = (
    "A predisposition class from the official hazard maps, not an alert: it uses no rain. "
    "For warnings, follow the bulletins of the Civil Protection Department and of the region."
)
#: The steps in Italian, for pages and texts for public bodies.
ITALIAN: dict[Step, str] = {
    "none": "nessuna",
    "low": "bassa",
    "medium": "media",
    "high": "alta",
    "very high": "molto alta",
}


@dataclass(frozen=True, slots=True)
class Predisposition:
    """One class: the step, the share it comes from, and the rule."""

    kind: Kind
    #: ``None`` when the share is not available (``-1`` or missing in the API).
    step: Step | None
    share: float | None
    measures: str
    rule: str
    note: str = NOTE

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def step_of(share: float | None) -> Step | None:
    """The step of a share of land in hazard (0 to 100); ``None`` when it is not known."""
    if share is None or share < 0:  # the API writes -1 for "not available"
        return None
    if share == 0:
        return "none"
    return next(step for bound, step in THRESHOLDS if share >= bound)


def rule() -> str:
    """The thresholds in words."""
    return "none 0% · low <5% · medium 5-15% · high 15-30% · very high >=30%"


def predisposition(summary: Mapping[str, Any]) -> dict[Kind, Predisposition]:
    """The landslide and flood classes of an area from its ``summary("pir", …)``."""
    out: dict[Kind, Predisposition] = {}
    for kind, (key, measures) in SHARES.items():
        value = summary.get(key)
        share = float(value) if isinstance(value, int | float) and value >= 0 else None
        out[kind] = Predisposition(kind, step_of(share), share, measures, rule())
    return out
