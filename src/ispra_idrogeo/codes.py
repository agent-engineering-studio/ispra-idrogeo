"""Codes in the data, and the words they stand for.

IFFI records, the open-data files and the monitoring sites store codes
(``tipo_movimento = 4``); the API's dictionaries (``/api/dizionari``) say
what each code means, in Italian, English, French and German.
:data:`CODE_DICTIONARIES` says which dictionary decodes which field, and
:func:`decode` adds a ``<field>_label`` next to each coded field.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from ispra_idrogeo.errors import IdrogeoError

Language = Literal["it", "en", "fr", "de"]

#: Which dictionary decodes which field, in the API records and in the files
#: (``tipo_movim`` is the shapefile's 10-character name for ``tipo_movimento``).
CODE_DICTIONARIES: dict[str, str] = {
    "tipo_movimento": "tipo_movimento",
    "tipo_movim": "tipo_movimento",
    "stato_attivita_1liv": "stati",
    "stato_attivita_2liv": "stati",
    "velocita_1ord": "velocita",
    "velocita_2ord": "velocita",
    "movimento_1ord": "movimenti",
    "movimento_2ord": "movimenti",
    "materiale_1ord": "materiali",
    "materiale_2ord": "materiali",
    "cause": "cause",
    "metodo": "metodo",
    "uso_suolo": "usi_suolo",
    "distribuzione": "distribuzioni",
    "stile": "stile",
    "posizione_punto": "posizione_punto",
    "stato_monitoraggio": "stato_monitoraggio",
    "finalita_monitoraggio": "finalita_monitoraggio",
    "tipo_acquisizione": "tipo_acquisizione",
    "strumentazione": "strumento_monitoraggio",
}


def parse_labels(entries: Any, lang: Language = "en") -> dict[str, str]:
    """A dictionary's entries as ``{code: label}``; Italian where a translation is missing."""
    if not isinstance(entries, list):
        raise IdrogeoError(f"IdroGEO dictionary is {type(entries).__name__}, expected a list")
    out = {}
    for entry in entries:
        try:
            code = str(entry["codice"])
        except (KeyError, TypeError):
            raise IdrogeoError(f"IdroGEO dictionary entry without a code: {entry!r}") from None
        label = entry.get(f"descrizione_{lang}") or entry.get("descrizione") or ""
        out[code] = str(label).strip()
    return out


def decode(
    record: Mapping[str, Any],
    labels: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    """A copy of ``record`` with ``<field>_label`` next to each field in ``labels``.

    ``labels`` maps a field to its ``{code: label}`` (see
    :meth:`~ispra_idrogeo.IdroGEO.code_labels`). A list of codes becomes a
    list of labels; an empty value stays ``None``, and a code missing from
    the dictionary becomes ``None`` too rather than a guess.
    """
    out = dict(record)
    for field, words in labels.items():
        if field not in record:
            continue
        value = record[field]
        if value is None or value == "":
            out[f"{field}_label"] = None
        elif isinstance(value, list):
            out[f"{field}_label"] = [words.get(_key(v)) for v in value]
        else:
            out[f"{field}_label"] = words.get(_key(value))
    return out


def _key(code: Any) -> str:
    """``4``, ``4.0`` and ``"4"`` are the same code (shapefiles store floats)."""
    if isinstance(code, float) and code.is_integer():
        return str(int(code))
    return str(code)
