from __future__ import annotations

import ispra_idrogeo


def test_version_is_exposed() -> None:
    assert ispra_idrogeo.__version__
