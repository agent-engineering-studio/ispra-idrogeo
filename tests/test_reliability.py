import pytest

from ispra_idrogeo.reliability import (
    FIELDS,
    LEVELS,
    NOT_MEASURED,
    THIN,
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
    row = ["Somewhere", 10.0, 2000, 30, 1, 0, 0, 0, 0, None]
    empty = ["Nowhere", None, 0, 0, 0, 0, 0, 0, 0, None]
    dated = ["Dated", 5.0, 100, 50, 40, 12, 3, 2, 100, None]
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


def test_few_records_for_the_hazard() -> None:
    def row(name: str, landslides: int, hazard: float | None) -> list[object]:
        return [name, 1000.0, landslides, 0, 0, 0, 0, 0, 0, hazard]

    found = ReliabilityMap(
        built_on="2026-11-28",
        levels={
            # Italy: 1,000 landslides on 100 km² of land in hazard P3+P4, 10 per km²
            "regioni": {"1": row("Full", 990, 50.0), "2": row("Thin", 10, 50.0)},
            "province": {"1": row("Thin province", 10, 20.0), "2": row("Full province", 500, 20.0)},
            "comuni": {
                "1001": row("Thin town", 5, 10.0),
                "1002": row("Small", 3, 0.5),  # under 1 km² of hazard land: too little to say
                "1003": row("Flat", 3, 0.0),
                "1004": row("Unknown", 3, None),
                "2001": row("Wide map", 5, 10.0),  # few for its own map, in a province with many
                "9001": row("Lost", 5, 10.0),  # its province is not in the table
            },
        },
    )
    assert found.italy_per_hazard_km2 == 10.0
    full, thin = found.at("regioni", 1), found.at("regioni", 2)
    assert (full.hazard_land_km2, full.landslides_per_hazard_km2, full.vs_italy) == (
        50.0,
        19.8,
        1.98,
    )
    assert not any("Few IFFI landslides" in note for note in full.notes)
    assert (thin.landslides_per_hazard_km2, thin.vs_italy) == (0.2, 0.02) and THIN > 0.02
    assert thin.notes[-1] == (
        "Few IFFI landslides for the hazard mapped here: 0.2 per km² of land in landslide "
        "hazard P3+P4, against 10.0 in Italy. A low density here may mean that little was "
        "surveyed, not that few landslides happen."
    )
    town = found.at("comuni", 1001)
    assert (town.landslides_per_hazard_km2, town.vs_italy) == (0.5, 0.05)
    assert (town.province_per_hazard_km2, town.province_vs_italy) == (0.5, 0.05)
    assert town.notes[-1].startswith(
        "Few IFFI landslides for the hazard mapped in this province: 0.5"
    )
    assert town.as_dict()["italy_per_hazard_km2"] == 10.0
    for code in (1002, 1003, 1004):
        other = found.at("comuni", code)
        assert (other.landslides_per_hazard_km2, other.vs_italy) == (None, None)
        assert "in this province" in other.notes[-1]  # the province says it, whatever the town
    wide = found.at("comuni", 2001)  # judged by its province, not by its own map
    assert (wide.vs_italy, wide.province_vs_italy) == (0.05, 2.5)
    assert not any("Few IFFI landslides" in note for note in wide.notes)
    lost = found.at("comuni", 9001)
    assert (lost.province_per_hazard_km2, lost.province_vs_italy) == (None, None)
    assert not any("Few IFFI landslides" in note for note in lost.notes)
    province = found.at("province", 1)
    assert province.province_vs_italy is None and "mapped here: 0.5" in province.notes[-1]
    # a map without the regions has no figure for Italy: the ratio, not the comparison
    alone = ReliabilityMap(built_on="x", levels={"comuni": {"1": row("Town", 5, 10.0)}})
    assert alone.italy_per_hazard_km2 is None
    town = alone.at("comuni", 1)
    assert (town.landslides_per_hazard_km2, town.vs_italy) == (0.5, None)


def test_the_shipped_map_knows_where_the_inventory_is_thin() -> None:
    found = reliability_map()
    assert found.italy_per_hazard_km2 is not None and 20 < found.italy_per_hazard_km2 < 40
    thin = {r.name for r in found.all("regioni") if r.vs_italy is not None and r.vs_italy < THIN}
    assert {"Sardegna", "Puglia"} <= thin and "Lombardia" not in thin


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
