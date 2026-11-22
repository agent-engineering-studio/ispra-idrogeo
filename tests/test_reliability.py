import pytest

from ispra_idrogeo.reliability import (
    FIELDS,
    LEVELS,
    NOT_MEASURED,
    ReliabilityMap,
    reliability,
    reliability_map,
)


def test_the_shipped_map_covers_every_area() -> None:
    found = reliability_map()
    assert found.built_on >= "2026-11-22"
    assert {level: len(found.levels[level]) for level in LEVELS} == {
        "regioni": 20,
        "province": 107,
        "comuni": 7899,
    }
    regions = found.all("regioni")
    # the inventory counted per region adds up to the whole of IFFI
    assert sum(r.landslides for r in regions) > 700_000
    assert all(len(row) == len(FIELDS) for row in found.levels["comuni"].values())


def test_one_area() -> None:
    sarno = reliability("comuni", 65135)
    assert sarno.name == "Sarno" and sarno.landslides > 0 and sarno.area_km2
    assert sarno.density_per_km2 == round(sarno.landslides / sarno.area_km2, 3)
    assert sarno.day_share is not None and 0 <= sarno.day_share <= 1
    assert sarno.not_measured == NOT_MEASURED and "CC BY-SA 4.0" in sarno.source
    as_json = sarno.as_dict()
    assert as_json["dated_since_2018"] == sarno.iffi_day_since_2018 + sarno.events_since_2018
    assert isinstance(as_json["notes"], list) and isinstance(as_json["not_measured"], list)
    with pytest.raises(ValueError, match="no comuni with ISTAT code 1"):
        reliability("comuni", 1)
    with pytest.raises(ValueError, match="unknown level"):
        reliability("nazione", 1)  # type: ignore[arg-type]


def test_the_notes_say_the_numbers() -> None:
    row = ["Somewhere", 10.0, 2000, 30, 1, 0, 0, 0, 0]
    empty = ["Nowhere", None, 0, 0, 0, 0, 0, 0, 0]
    dated = ["Dated", 5.0, 100, 50, 40, 12, 3, 2, 100]
    found = ReliabilityMap(
        built_on="2026-11-22", levels={"comuni": {"1": row, "2": empty, "3": dated}}
    )
    some = found.at("comuni", 1)
    assert some.notes == (
        "1 of 2,000 IFFI landslides (<0.1%) have a date to the day.",
        "0.0% of the IFFI records were edited since 2021.",
        "No landslide dated to the day since 2018: nothing here can check a threshold.",
    )
    none = found.at("comuni", 2)
    assert none.notes[0] == "No IFFI landslide is mapped here."
    assert (none.density_per_km2, none.dated_share, none.edited_since_2021_share) == (None,) * 3
    assert found.at("comuni", 3).notes[-1] == (
        "Since 2018: 12 IFFI landslides dated to the day and 3 events, 2 of them with a "
        "point known to 1 km."
    )


def test_a_map_with_other_fields_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from ispra_idrogeo import reliability as module

    class Fake:
        def joinpath(self, _name: str) -> "Fake":
            return self

        def read_text(self, _encoding: str) -> str:
            return '{"built_on": "x", "fields": ["name"], "levels": {}}'

    module.reliability_map.cache_clear()
    monkeypatch.setattr("importlib.resources.files", lambda _package: Fake())
    with pytest.raises(ValueError, match="rebuild it"):
        module.reliability_map()
    monkeypatch.undo()
    module.reliability_map.cache_clear()
