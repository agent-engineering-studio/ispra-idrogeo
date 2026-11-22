from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from ispra_idrogeo import FileState, IdroGEO, IdrogeoError, opendata
from ispra_idrogeo.freshness import compare, freshness, published, summary

DATE = "Sun, 22 Nov 2026 08:36:52 GMT"


def _server(etag: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "HEAD"
        if "segnalazioni" in request.url.path:
            return httpx.Response(200, headers={"etag": etag})  # no date, no size
        if "nope" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(
            200, headers={"etag": etag, "last-modified": DATE, "content-length": "38161680"}
        )

    return httpx.MockTransport(handler)


async def test_head_and_freshness(tmp_path: Path) -> None:
    state = tmp_path / "freshness.json"
    async with IdroGEO(httpx.AsyncClient(transport=_server('"a"'))) as idrogeo:
        piff = await idrogeo.head(opendata("frane_piff"))
        assert piff == FileState(
            "frane_piff_ispra_opendata.zip", opendata("frane_piff").url, '"a"', DATE, 38161680
        )
        first = await freshness(idrogeo, state=state)
        assert len(first) == len(published()) == 10
        assert {f.changed for f in first} == {None}  # nothing saved yet
        assert first[0].modified == "2026-11-22T08:36:52Z"
        reports = next(f for f in first if f.filename.startswith("segnalazioni"))
        assert (reports.modified, reports.age_days, reports.size) == (None, None, None)
        again = await freshness(idrogeo, state=state)
        assert {f.changed for f in again} == {False}
        from ispra_idrogeo.sources import Dataset

        with pytest.raises(IdrogeoError):
            await idrogeo.head(Dataset(url="https://x/nope.zip", filename="nope.zip"))
    async with IdroGEO(httpx.AsyncClient(transport=_server('"b"'))) as idrogeo:
        changed = await freshness(idrogeo, [opendata("frane_piff")], state=state)
        assert changed[0].changed is True
        counts = summary(changed)
        assert counts["changed"] == ["frane_piff_ispra_opendata.zip"]
        assert counts["newest"] == counts["oldest"] == "frane_piff_ispra_opendata.zip"
    state.write_text("[1]")  # not a dict: treated as nothing saved
    async with IdroGEO(httpx.AsyncClient(transport=_server('"b"'))) as idrogeo:
        assert (await freshness(idrogeo, [opendata("frane_piff")], state=state))[0].changed is None
    assert summary([])["newest"] is None


def test_compare_reads_bad_dates_as_unknown() -> None:
    found = FileState("f", "u", None, "not a date", None)
    one = compare(found, {"etag": None, "last_modified": "not a date"}, datetime.now(UTC))
    assert (one.modified, one.age_days, one.changed) == (None, None, False)
    assert one.as_dict()["filename"] == "f"
