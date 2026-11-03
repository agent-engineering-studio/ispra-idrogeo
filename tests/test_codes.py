from __future__ import annotations

import pytest

from ispra_idrogeo import CODE_DICTIONARIES, IdrogeoError, decode, parse_labels

ENTRIES = [
    {"codice": "4", "descrizione": "Colamento lento", "descrizione_en": "slow earth flow"},
    {"codice": "6", "descrizione": "Sprofondamento ", "descrizione_en": ""},
    {"codice": 15, "descrizione": "Inclinometro", "descrizione_en": "inclinometer"},
]


def test_parse_labels() -> None:
    assert parse_labels(ENTRIES) == {
        "4": "slow earth flow",
        "6": "Sprofondamento",  # no English: the Italian, trimmed
        "15": "inclinometer",
    }
    assert parse_labels(ENTRIES, "it")["4"] == "Colamento lento"
    with pytest.raises(IdrogeoError, match="expected a list"):
        parse_labels({"codice": "1"})
    with pytest.raises(IdrogeoError, match="without a code"):
        parse_labels([{"descrizione": "x"}])


def test_decode() -> None:
    words = parse_labels(ENTRIES)
    labels = {"tipo_movim": words, "strumentazione": words, "cause": words, "stile": words}
    record = {"tipo_movim": 4.0, "strumentazione": [15, "99"], "cause": None, "stile": "", "x": 1}
    assert decode(record, labels) == {
        **record,
        "tipo_movim_label": "slow earth flow",  # a shapefile float is the same code
        "strumentazione_label": ["inclinometer", None],  # an unknown code is not guessed
        "cause_label": None,
        "stile_label": None,
    }
    assert decode({"x": 1}, labels) == {"x": 1}  # fields not in the record are skipped
    assert "tipo_movim_label" not in record  # the record itself is not changed


def test_every_field_has_a_dictionary_name() -> None:
    assert CODE_DICTIONARIES["tipo_movim"] == CODE_DICTIONARIES["tipo_movimento"]
    assert all(name and name.islower() for name in CODE_DICTIONARIES.values())
