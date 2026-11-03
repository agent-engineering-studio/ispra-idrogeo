from __future__ import annotations

from datetime import date

import pytest

from ispra_idrogeo import event_filter, landslide_filter, site_filter


def test_landslide_filter() -> None:
    assert landslide_filter() == {}
    assert landslide_filter(movement=6, activity=100, district=[5, 6]) == {
        "tipo_movimento": 6,  # plain: the landslide search refuses "eq.6"
        "stato_attivita_1liv": "eq.100",
        "autorita_distretto": "in.(5,6)",
    }
    assert landslide_filter(activity=(100,)) == {"stato_attivita_1liv": "eq.100"}
    with pytest.raises(ValueError, match="at least one"):
        landslide_filter(activity=[])


def test_event_filter() -> None:
    assert event_filter(region=16, movement=[1, 2]) == {
        "regione": "eq.16",
        "tipo_movimento": "in.(1,2)",
    }
    assert event_filter(province=70, municipality=70077) == {
        "provincia": "eq.70",
        "comune": "eq.70077",
    }
    year = event_filter(start=date(2023, 1, 1), end=date(2024, 1, 1))
    assert year == {"and": "(computed_date.gte.2023-01-01,computed_date.lt.2024-01-01)"}
    assert event_filter(start=date(2025, 1, 1)) == {"computed_date": "gte.2025-01-01"}
    assert event_filter(end=date(2018, 1, 1)) == {"computed_date": "lt.2018-01-01"}
    with pytest.raises(ValueError, match="after start"):
        event_filter(start=date(2024, 1, 1), end=date(2024, 1, 1))


def test_site_filter() -> None:
    assert site_filter(region=1, active=True) == {"regione": "eq.1", "stato_monitoraggio": "eq.1"}
    assert site_filter(province=6, active=False) == {
        "provincia": "eq.6",
        "stato_monitoraggio": "neq.1",
    }
    assert site_filter(municipality=[6001, 6002]) == {"comune": "in.(6001,6002)"}
