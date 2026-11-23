import math

import pytest

from ispra_idrogeo.grounding import SOURCES, Rule, check_claims, check_text, grounded, numbers

# What area_risk and area_landslides answered for Bari, and hazard_at for a
# point above Sarno: the facts the answers below were written from.
FACTS = {
    "bari": {
        "nome": "Bari",
        "uid": 72006,
        "pop_res021": 315948,
        "pop_idr_p2": 4038,
        "popidp2_p": 1.278,
        "ar_kmq": 117.39,
    },
    "italy": {"pop_idr_p2": 6818375, "popidp2_p": 11.5, "pop_fr_p3p4": 1278455},
    "sarno": {"landslide": "P4", "municipality": 65135, "slope_deg": 12.3, "frane_totali": 53},
    "event": {"uid": "EIT202500009", "data_certa": "2025-01-21T00:00"},
}

# (answer, numbers check_text must report): faithful answers report nothing.
FAITHFUL = [
    "Bari ha 315.948 residenti; l'1,3 % (4.038 persone) vive in pericolo alluvione P2.",
    "Bari has 315,948 residents: 1.28% of them, 4,038 people, in flood hazard P2.",
    "In Italy about 6.8 million people live in flood hazard P2, 11.5% of residents.",
    "In Italia circa 1,3 milioni di persone vivono in pericolo frana P3+P4.",
    "Sopra Sarno il pericolo è P4, con una pendenza di 12.3°; il Comune ha 53 frane IFFI.",
    "Bari (ISTAT 72006) covers 117.4 km².",
    "The event EIT202500009 is dated 2025-01-21, that is 21/01/2025.",
    "1. Bari\n2. Sarno\n(EPSG:32632, classes P3 and P4)",
]
FAULTY = [
    ("Bari has 315,949 residents.", ["315,949"]),  # off by one
    ("Sarno has 54 landslides, slope 12.4°.", ["54", "12.4"]),  # invented
    ("In Italy 7.4 million people live in flood hazard P2.", ["7.4 million"]),
    ("Bari: 1.5% in flood hazard P2.", ["1.5"]),  # rounded the wrong way
    ("The event happened on 2025-01-22.", ["2025-01-22"]),  # a date not in the facts
    ("About 2 mila people.", ["2 mila"]),
]


@pytest.mark.parametrize("text", FAITHFUL)
def test_faithful_answers_pass(text: str) -> None:
    assert check_text(text, FACTS) == []


@pytest.mark.parametrize(("text", "wrong"), FAULTY)
def test_faults_are_found(text: str, wrong: list[str]) -> None:
    assert check_text(text, FACTS) == wrong


def test_numbers_of_the_question_are_allowed() -> None:
    text = "Within 500 m of the point there are 3 landslides."
    assert check_text(text, {"count": 3}) == ["500"]
    assert check_text(text, {"count": 3}, question="Landslides within 500 m?") == []


def test_how_numbers_are_read() -> None:
    def read(text: str) -> list[tuple[float, float]]:
        [found] = numbers(text)
        return list(found.readings)

    assert read("1,278") == [(1.278, 0.001), (1278.0, 1.0)]  # Italian or English
    assert read("1.234,5") == [(1234.5, 0.1)]
    assert read("1,234.5") == [(1234.5, 0.1)]
    assert read("12\u00a0345") == [(12345.0, 1.0)]  # a space is never a decimal point
    assert read("1,300") == [(1.3, 0.001), (1300.0, 100.0)]  # a round number
    assert read("-3.5") == [(-3.5, 0.1)]
    assert read("\u22122") == [(-2.0, 1.0)]
    assert read("0") == [(0.0, 1.0)]
    assert read("2.5 milioni") == [(2_500_000.0, 100_000.0)]
    assert numbers("1.2.3") == []  # not a number
    assert [n.text for n in numbers("P4, CUM3, 10:30, 2026-11-22, x2")] == []


def test_facts_of_every_shape() -> None:
    facts = {"5": "rapid debris flow", "n": "42", "flags": [True, None], "x": math.nan}
    assert check_text("Code 5, 42 of them.", facts) == []
    assert check_text("1 or 0", {"flag": True, "none": None}) == ["1", "0"]


def test_grounded_answers() -> None:
    rows = grounded([{"a": 1}], "iffi")
    assert rows["results"] == [{"a": 1}] and rows["count"] == 1
    assert rows["source"] == SOURCES["iffi"] and rows["retrieved_at"].endswith("Z")
    one = grounded({"a": 1, "source": "theirs"}, "indicators")
    assert one["source"] == "theirs" and "CC BY 4.0" in one["idrogeo_source"]
    text = grounded("a path", "idrogeo")
    assert text["results"] == "a path" and "count" not in text
    assert "CC BY-SA 4.0" in SOURCES["iffi"] and "CC BY-SA 4.0" in SOURCES["events"]


# (answer, numbers check_claims must report): said of the right thing, or not.
CLAIMS = [
    ("Bari ha 315.948 residenti, l'1,3% in pericolo alluvione P2 (4.038 persone).", []),
    ("Bari has 315,948 residents: 1.28% of them, 4,038 people, live in flood hazard P2.", []),
    ("4,038 residents live in flood hazard P2; the town has 315,948 residents.", []),
    ("In pericolo alluvione ci sono 4.038 persone.", []),
    ("In Italy about 6.8 million people live in flood hazard P2.", []),  # Italy, not Bari
    ("Bari ha 4.038 residenti.", ["4.038"]),
    ("A Bari 315.948 persone vivono in pericolo alluvione P2.", ["315.948"]),
]


@pytest.mark.parametrize(("text", "wrong"), CLAIMS)
def test_claims_said_of_the_right_thing(text: str, wrong: list[str]) -> None:
    assert [m.said for m in check_claims(text, FACTS)] == wrong


def test_shares_and_counts_are_told_apart() -> None:
    facts = {"popidp2_p": 1.278, "aridp2_p": 2.1, "frane_totali": 9, "ed_idr_p2": 500}
    assert check_claims("Il 2,1% del territorio è in pericolo alluvione.", facts) == []
    [wrong] = check_claims("Il 2,1% dei residenti è in pericolo alluvione.", facts)
    assert (wrong.said, wrong.key, wrong.fact) == ("2,1", "popidp2_p", 1.278)
    assert check_claims("In pericolo alluvione ci sono 500 edifici.", facts) == []
    assert [m.said for m in check_claims("Il Comune ha 53 frane.", facts)] == ["53"]
    assert check_claims("Il Comune ha 53 frane datate.", facts) == []  # not all of them


def test_claims_leave_unknown_things_alone() -> None:
    assert check_claims("Bari ha 12 ponti e 3 fiumi.", FACTS) == []
    assert check_claims("Bari ha 4.038 residenti.", {"other": 1}) == []  # no figure to compare
    assert check_claims("Bari ha 4.038 residenti.", {"pop_res021": -1}) == []  # not available
    own = (Rule("ar_kmq", (("km",),), share=False),)
    assert [m.said for m in check_claims("Bari covers 131 km².", FACTS, own)] == ["131"]
