"""An async client for the IdroGEO downloads and API.

Give it your ``httpx.AsyncClient`` and timeouts, proxies and pooling stay
yours; give it none and it opens (and closes) its own.

Downloads are streamed to a ``.part`` file and renamed when complete, so a
file that exists is whole and memory stays flat (the national landslide
polygons are ~570 MB). Each is revalidated with a conditional GET: an
unchanged file costs one 304.

Network errors and 429/5xx are retried ``retries`` times with exponential
backoff, then propagate as ``httpx`` exceptions (``HTTPStatusError`` for a
status). Pass ``retries=0`` to put your own retry policy around the calls.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from ispra_idrogeo import api
from ispra_idrogeo.cache import (
    Validators,
    default_directory,
    extract,
    read_json,
    read_validators,
    write_json,
    write_validators,
)
from ispra_idrogeo.errors import IdrogeoError
from ispra_idrogeo.sources import Dataset

_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_CHUNK = 1 << 20


def _code(uid: str) -> str:
    """A site or station ``uid`` as a path segment: letters and digits only."""
    if not uid.isalnum():
        raise ValueError(f"a site uid is letters and digits only, like 'SIPIE001' (got {uid!r})")
    return uid


@dataclass(frozen=True, slots=True)
class Download:
    """A file on disk, and whether this call changed it."""

    path: Path
    changed: bool


class IdroGEO:
    """Open-data downloads into a persistent folder, and the read-only API."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        api_url: str = api.API_URL,
        retries: int = 3,
        backoff_s: float = 2.0,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self._own = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(60, read=300), follow_redirects=True
        )
        self._api = api_url.rstrip("/")
        self._retries = retries
        self._backoff_s = backoff_s
        self._sleep = sleep

    async def __aenter__(self) -> IdroGEO:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the HTTP client if this instance opened it."""
        if self._own:
            await self._client.aclose()

    async def download(self, dataset: Dataset, directory: Path | None = None) -> Download:
        """The file in ``directory``, downloaded only if missing or changed upstream.

        ``directory`` defaults to :func:`~ispra_idrogeo.cache.default_directory`.
        A 404 raises :class:`IdrogeoError`: the layer or area does not exist.
        """
        directory = directory or default_directory()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / dataset.filename
        known = read_validators(path, dataset.url)
        headers = known.headers() if known is not None else {}
        partial = path.with_name(f"{path.name}.part")
        for attempt in range(self._retries + 1):
            try:
                async with self._client.stream("GET", dataset.url, headers=headers) as response:
                    status = response.status_code
                    if status == 304 and known is not None:
                        return Download(path, changed=False)
                    if status == 200:
                        with partial.open("wb") as out:
                            async for chunk in response.aiter_bytes(_CHUNK):
                                out.write(chunk)
                        partial.replace(path)
                        write_validators(
                            path,
                            Validators(
                                url=dataset.url,
                                etag=response.headers.get("etag"),
                                last_modified=response.headers.get("last-modified"),
                            ),
                        )
                        return Download(path, changed=True)
                    if status == 404:
                        raise IdrogeoError(f"{dataset.url} does not exist (HTTP 404)")
                    if status not in _RETRY_STATUS or attempt == self._retries:
                        await response.aread()
                        response.raise_for_status()
                        raise IdrogeoError(f"{dataset.url}: unexpected HTTP {status}")
            except httpx.TransportError:
                partial.unlink(missing_ok=True)
                if attempt == self._retries:
                    raise
            await self._sleep(self._backoff_s * 2**attempt)
        raise AssertionError("unreachable")  # pragma: no cover

    async def fetch(
        self, dataset: Dataset, directory: Path | None = None, *, unpack: bool = True
    ) -> Path:
        """The dataset ready to read: the folder its ZIP unpacks to, or the file.

        The folder is ``<directory>/<dataset.stem>`` and is unpacked again
        only when the download changed (or the folder is missing).
        """
        directory = directory or default_directory()
        got = await self.download(dataset, directory)
        if not unpack or not dataset.filename.endswith(".zip"):
            return got.path
        folder = directory / dataset.stem
        if got.changed or not folder.is_dir():
            await asyncio.to_thread(extract, got.path, folder)
        return folder

    async def summary(self, summary: api.Summary, level: api.Level, code: int | None = None) -> Any:
        """IFFI counts (``"iffi"``) or hazard indicators (``"pir"``), or a level's list."""
        return await self._get(api.summary_path(summary, level, code))

    async def summaries(
        self,
        summary: api.Summary,
        level: api.Level,
        directory: Path | None = None,
        *,
        concurrency: int = 8,
        max_age: timedelta | None = None,
    ) -> list[dict[str, Any]]:
        """The summary of every region, province or municipality, kept on disk.

        One call lists the level, then one call per area (7,899 for
        ``"comuni"``, ~17 MB) asks for its summary, ``concurrency`` at a
        time. Each answer is saved in ``<directory>/<summary>_<level>/<code>.json``
        and read back instead of asked again until it is older than
        ``max_age`` (never, by default), so an interrupted run resumes where
        it stopped. The result follows the order of the API's list.
        """
        if level not in api.CODE_FIELDS:
            raise ValueError(f"{level!r} has no list: one of {tuple(api.CODE_FIELDS)}")
        if concurrency < 1:
            raise ValueError("concurrency must be ≥ 1")
        folder = (directory or default_directory()) / f"{summary}_{level}"
        folder.mkdir(parents=True, exist_ok=True)
        codes = api.level_codes(level, await self._get(api.summary_path(summary, level)))
        found: dict[int, dict[str, Any]] = {}
        gate = asyncio.Semaphore(concurrency)

        async def one(code: int) -> None:
            path = folder / f"{code}.json"
            saved = read_json(path, max_age)
            if saved is None:
                async with gate:
                    saved = await self._get(api.summary_path(summary, level, code))
                write_json(path, saved)
            found[code] = saved

        try:
            async with asyncio.TaskGroup() as group:
                for code in codes:
                    group.create_task(one(code))
        except BaseExceptionGroup as failed:
            raise failed.exceptions[0] from None
        return [found[code] for code in codes]

    async def municipalities(
        self,
        summary: api.Summary = "pir",
        directory: Path | None = None,
        *,
        concurrency: int = 8,
        max_age: timedelta | None = None,
    ) -> list[dict[str, Any]]:
        """Hazard and risk indicators (or IFFI counts) of every municipality.

        :meth:`summaries` for ``"comuni"``: see there for the folder and
        ``max_age``.
        """
        return await self.summaries(
            summary, "comuni", directory, concurrency=concurrency, max_age=max_age
        )

    async def dictionaries(self) -> list[str]:
        """The names of the code lists."""
        return [str(n) for n in await self._get("dizionari")]

    async def dictionary(self, name: str) -> Any:
        """One code list (``IdrogeoError`` if it does not exist)."""
        return await self._get(f"dizionari/{name}")

    async def landslide(self, id_frana: str) -> dict[str, Any]:
        """The full record of one validated IFFI landslide (~140 fields).

        Causes, activations, state and velocity, damage, interventions,
        precursors: many fields are often empty. ``IdrogeoError`` if the id
        is unknown or the landslide is not public (IdroGEO answers 401, not
        404, to both).
        """
        if not id_frana.isdigit():
            raise ValueError(f"an IFFI id is digits only, like '0017680500' (got {id_frana!r})")
        response = await self._send("GET", f"{self._api}/frana/{id_frana}")
        if response.status_code == 401:
            raise IdrogeoError(f"landslide {id_frana} is unknown or not public (HTTP 401)")
        data = api.parse(response.status_code, response.content)
        if not isinstance(data, dict):
            raise IdrogeoError(f"IdroGEO returned {type(data).__name__} for landslide {id_frana}")
        return data

    def iter_landslides(
        self,
        filters: dict[str, Any] | None = None,
        *,
        modified_since: datetime | None = None,
        page_size: int = 1000,
        select: list[str] | None = None,
        order: str = "id_frana",
    ) -> AsyncIterator[dict[str, Any]]:
        """Every IFFI landslide matching ``filters``, page after page.

        Filters take plain values (``{"tipo_movimento": 6}``). With
        ``modified_since`` only the landslides changed since then: the
        incremental update of a local copy (``select=["*"]`` brings the
        geometry too). A landslide that is removed does not show up as
        changed, it just stops being listed.

        Pages are ordered by ``order`` so that they do not overlap; IdroGEO
        changes daily, so a record edited while you iterate may be seen
        twice or missed.
        """
        found = api.since_filter(filters, modified_since)
        return self._pages("frana/searchfilter", found, page_size, select, order)

    def iter_events(
        self,
        filters: dict[str, Any] | None = None,
        *,
        modified_since: datetime | None = None,
        page_size: int = 1000,
        select: list[str] | None = None,
        order: str = "uid",
    ) -> AsyncIterator[dict[str, Any]]:
        """Every validated landslide event matching ``filters``, page after page.

        Filters take operators (``{"regione": "eq.16"}``); see
        :meth:`iter_landslides` for ``modified_since`` and the order.
        """
        found = api.since_filter(filters, modified_since)
        return self._pages("evento/main/filter", found, page_size, select, order)

    async def sites(
        self,
        filters: dict[str, Any] | None = None,
        *,
        modified_since: datetime | None = None,
        select: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """The landslide monitoring sites matching ``filters`` (1,063 in all).

        Filters take operators (``{"stato_monitoraggio": "eq.1"}`` for the
        active ones); ``modified_since`` keeps the sites changed since then.
        ``point`` is longitude and latitude (WGS 84); ``id_frane_correlati``
        links a site to its IFFI landslides.
        """
        found = api.since_filter(filters, modified_since)
        return [s async for s in self._pages("sito/filter", found, 1000, select, "uid")]

    async def site(self, uid: str) -> dict[str, Any]:
        """One monitoring site by its ``uid`` (``"SIPIE001"``), not by its ``id``."""
        data = await self._get(f"sito/{_code(uid)}")
        if not isinstance(data, dict):
            raise IdrogeoError(f"IdroGEO returned {type(data).__name__} for site {uid}")
        return data

    async def stations(self, uid: str) -> list[dict[str, Any]]:
        """The stations of a monitoring site, with their instruments and sensors."""
        data = await self._get(f"sito/{_code(uid)}/listing")
        if not isinstance(data, dict) or not isinstance(data.get("stazioni"), list):
            raise IdrogeoError(f"site {uid} is unknown (IdroGEO answered {data!r})")
        return list(data["stazioni"])

    async def webcams(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """The webcams pointed at landslides (14, all in Lombardy in 2026).

        Filters take operators (``{"regione": "eq.3"}``). Mind ``geom``: its
        coordinates are EPSG:3857 metres, not longitude and latitude.
        """
        return [w async for w in self._pages("webcam/filter", filters, 1000, None, None)]

    async def _pages(
        self,
        path: str,
        filters: dict[str, Any] | None,
        page_size: int,
        select: list[str] | None,
        order: str | None,
    ) -> AsyncIterator[dict[str, Any]]:
        offset = 0
        while True:
            page = await self._search(path, filters, page_size, offset, select, order)
            for row in page:
                yield row
            if len(page) < page_size:
                return
            offset += page_size

    async def search_landslides(
        self,
        filters: dict[str, Any] | None = None,
        *,
        limit: int = 100,
        offset: int = 0,
        select: list[str] | None = None,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """One page of IFFI landslides matching ``filters``."""
        return await self._search("frana/searchfilter", filters, limit, offset, select, order)

    async def search_events(
        self,
        filters: dict[str, Any] | None = None,
        *,
        limit: int = 100,
        offset: int = 0,
        select: list[str] | None = None,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """One page of validated landslide events matching ``filters``."""
        return await self._search("evento/main/filter", filters, limit, offset, select, order)

    async def _search(
        self,
        path: str,
        filters: dict[str, Any] | None,
        limit: int,
        offset: int,
        select: list[str] | None,
        order: str | None,
    ) -> list[dict[str, Any]]:
        params = api.search_params(limit=limit, offset=offset, select=select, order=order)
        response = await self._send(
            "POST", f"{self._api}/{path}", params=params, json=filters or {}
        )
        return api.parse_list(response.status_code, response.content)

    async def _get(self, path: str) -> Any:
        response = await self._send("GET", f"{self._api}/{path}")
        return api.parse(response.status_code, response.content)

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(self._retries + 1):
            try:
                response = await self._client.request(method, url, **kwargs)
            except httpx.TransportError:
                if attempt == self._retries:
                    raise
            else:
                if response.status_code not in _RETRY_STATUS:
                    return response
                if attempt == self._retries:
                    response.raise_for_status()
            await self._sleep(self._backoff_s * 2**attempt)
        raise AssertionError("unreachable")  # pragma: no cover
