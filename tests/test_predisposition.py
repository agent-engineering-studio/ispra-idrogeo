import pytest

from ispra_idrogeo.predisposition import ITALIAN, NOTE, predisposition, rule, step_of


@pytest.mark.parametrize(
    ("share", "step"),
    [
        (None, None),
        (-1, None),
        (0, "none"),
        (0.01, "low"),
        (4.99, "low"),
        (5, "medium"),
        (15, "high"),
        (29.9, "high"),
        (30, "very high"),
        (98.6, "very high"),
    ],
)
def test_steps(share: float | None, step: str | None) -> None:
    assert step_of(share) == step


def test_predisposition_of_an_area() -> None:
    found = predisposition({"ar_frp3p4p": 31.2, "aridp2_p": -1})
    assert found["landslide"].step == "very high" and found["landslide"].share == 31.2
    assert found["flood"].step is None and found["flood"].share is None
    assert "not an alert" in found["landslide"].note and found["flood"].note == NOTE
    assert found["landslide"].rule == rule() and "15-30%" in rule()
    assert found["landslide"].as_dict()["kind"] == "landslide"
    assert predisposition({})["flood"].step is None
    assert ITALIAN["very high"] == "molto alta"
