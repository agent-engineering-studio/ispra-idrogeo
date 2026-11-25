"""Everything a new server needs to work offline, in one call: :func:`init`.

    idrogeo init                                  # Italy: IFFI, PAI, flood, ISTAT, CORINE
    idrogeo init --area puglia --area basilicata  # IFFI of two regions only

By default it downloads what Limen uses: the IFFI inventory area by area (the
five layers of the 19 regions and of Bolzano and Trento, 105 files), the PAI
landslide mosaic 2020-2021 and the flood mosaic, the ISTAT administrative
boundaries 2023 and CORINE Land Cover 2018. All of it goes to the download
folder (:func:`~ispra_idrogeo.cache.default_directory`, that is
``$DATA_ROOT/ispra-idrogeo`` when ``DATA_ROOT`` is set), about 3.5 GB the
first time.

It can be run again: every file goes through :meth:`IdroGEO.download
<ispra_idrogeo.client.IdroGEO.download>`, so one that has not changed costs a
304, and the ISTAT and CORINE files, which carry their year in the name and
never change, are not asked for again once on disk. A file that does not
arrive is listed in :attr:`InitResult.failed` and does not stop the others;
an error writing to disk does.
"""

from __future__ import annotations

import asyncio
import time
import zipfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx

from ispra_idrogeo.cache import default_directory, extract, meta_path, read_validators
from ispra_idrogeo.client import Download, IdroGEO
from ispra_idrogeo.errors import IdrogeoError
from ispra_idrogeo.sources import (
    LANDSLIDE_LAYERS,
    PROVINCES,
    REGIONS,
    Dataset,
    Mosaic,
    mosaic,
    opendata,
)

#: The areas with IFFI files of their own: the 19 regions and the two
#: autonomous provinces (Trentino-Alto Adige has no regional file).
IFFI_AREAS: tuple[str, ...] = (*REGIONS.values(), PROVINCES[21], PROVINCES[22])

#: The mosaics :func:`init` downloads unless told otherwise.
DEFAULT_MOSAICS: tuple[Mosaic, ...] = ("pai_frane", "idraulica")

#: ISTAT administrative boundaries at 1 January 2023, generalised (municipalities,
#: provinces, regions): a ZIP whose shapefiles sit in a folder of the same name.
ISTAT_BOUNDARIES = Dataset(
    url=(
        "https://www.istat.it/storage/cartografia/confini_amministrativi/"
        "generalizzati/2023/Limiti01012023_g.zip"
    ),
    filename="Limiti01012023_g.zip",
)

_CORINE_URL = (
    "https://groupware.sinanet.isprambiente.it/uso-copertura-e-consumo-di-suolo/"
    "library/copertura-del-suolo/corine-land-cover/clc2018_shapefile"
)
#: CORINE Land Cover 2018 for Italy, the shapefile SINAnet (ISPRA) publishes
#: one file at a time. Saved in the folder :data:`CORINE_FOLDER`.
CORINE_LAND_COVER: tuple[Dataset, ...] = tuple(
    Dataset(url=f"{_CORINE_URL}/{item}/download/en/1/CLC18_IT.{ext}", filename=f"CLC18_IT.{ext}")
    for item, ext in (
        ("clc18_it-2", "shp"),
        ("clc18_it-4", "shx"),
        ("clc18_it-5", "dbf"),
        ("clc18_it-3", "prj"),
        ("clc18_it-1", "cpg"),
    )
)
CORINE_FOLDER = "CLC18_IT"


@dataclass(slots=True)
class InitResult:
    """What :func:`init` did, file by file (names relative to ``directory``)."""

    directory: Path
    #: Downloaded now: new, or changed upstream.
    downloaded: list[str] = field(default_factory=list)
    #: Already on disk and still valid: unchanged upstream, or not asked for.
    skipped: list[str] = field(default_factory=list)
    #: Not downloaded or not unpacked, with the reason.
    failed: dict[str, str] = field(default_factory=dict)
    #: The size of the files downloaded now.
    downloaded_bytes: int = 0

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["directory"] = str(self.directory)
        return out


@dataclass(frozen=True, slots=True)
class _File:
    dataset: Dataset
    folder: str = ""
    #: Never changes upstream: not asked for again once on disk.
    fixed: bool = False


def _plan(
    areas: Iterable[str] | None,
    mosaics: Iterable[Mosaic],
    boundaries: bool,
    land_cover: bool,
) -> list[_File]:
    chosen = IFFI_AREAS if areas is None else tuple(areas)
    files = [_File(opendata(layer, area)) for layer in LANDSLIDE_LAYERS for area in chosen]
    files += [_File(mosaic(name)) for name in dict.fromkeys(mosaics)]
    if boundaries:
        files.append(_File(ISTAT_BOUNDARIES, fixed=True))
    if land_cover:
        files += [_File(ds, CORINE_FOLDER, fixed=True) for ds in CORINE_LAND_COVER]
    return files


def _younger(path: Path, max_age: timedelta) -> bool:
    try:
        return time.time() - path.stat().st_mtime < max_age.total_seconds()
    except OSError:
        return False


async def init_with(
    idrogeo: IdroGEO,
    directory: Path | None = None,
    *,
    areas: Iterable[str] | None = None,
    mosaics: Iterable[Mosaic] = DEFAULT_MOSAICS,
    boundaries: bool = True,
    land_cover: bool = True,
    unpack: bool = True,
    max_age: timedelta | None = None,
    concurrency: int = 4,
) -> InitResult:
    """:func:`init` with a client you already have; see there."""
    if concurrency < 1:
        raise ValueError("concurrency must be ≥ 1")
    root = directory or default_directory()
    files = _plan(areas, mosaics, boundaries, land_cover)
    result = InitResult(root)
    gate = asyncio.Semaphore(concurrency)

    async def one(item: _File) -> None:
        ds = item.dataset
        folder = root / item.folder if item.folder else root
        name = f"{item.folder}/{ds.filename}" if item.folder else ds.filename
        path = folder / ds.filename
        on_disk = read_validators(path, ds.url) is not None
        if on_disk and (item.fixed or (max_age is not None and _younger(path, max_age))):
            got = Download(path, changed=False)
        else:
            try:
                async with gate:
                    got = await idrogeo.download(ds, folder)
            except (httpx.HTTPError, IdrogeoError) as exc:
                result.failed[name] = str(exc)[:300]
                return
        unpacked = folder / ds.stem
        if unpack and ds.filename.endswith(".zip") and (got.changed or not unpacked.is_dir()):
            try:
                await asyncio.to_thread(extract, got.path, unpacked)
            except (zipfile.BadZipFile, IdrogeoError) as exc:
                # A broken ZIP kept with its ETag would be answered 304 forever:
                # without it, the next run downloads it in full.
                got.path.unlink(missing_ok=True)
                meta_path(got.path).unlink(missing_ok=True)
                result.failed[name] = f"cannot unpack: {exc}"[:300]
                return
        if got.changed:
            result.downloaded.append(name)
            result.downloaded_bytes += got.path.stat().st_size
        else:
            result.skipped.append(name)

    try:
        async with asyncio.TaskGroup() as group:
            for item in files:
                group.create_task(one(item))
    except BaseExceptionGroup as failed:
        raise failed.exceptions[0] from None
    result.downloaded.sort()
    result.skipped.sort()
    return result


async def init(
    directory: Path | None = None,
    *,
    areas: Iterable[str] | None = None,
    mosaics: Iterable[Mosaic] = DEFAULT_MOSAICS,
    boundaries: bool = True,
    land_cover: bool = True,
    unpack: bool = True,
    max_age: timedelta | None = None,
    concurrency: int = 4,
    client: httpx.AsyncClient | None = None,
    retries: int = 3,
) -> InitResult:
    """Download the national data needed to work offline; what was done.

    ``directory`` defaults to :func:`~ispra_idrogeo.cache.default_directory`
    (``$DATA_ROOT/ispra-idrogeo`` when ``DATA_ROOT`` is set).

    ``areas`` are the IFFI areas (region or province file names, or
    ``"ispra"`` for the national files): all of :data:`IFFI_AREAS` when
    ``None``, none with ``()``. ``mosaics`` are the hazard mosaics (``()``
    for none); ``boundaries`` the ISTAT boundaries, ``land_cover`` CORINE
    2018. ZIPs are unpacked next to themselves unless ``unpack=False``.

    Each file is revalidated with a conditional GET; with ``max_age``, one
    downloaded more recently than that is not even asked for. A file that
    fails is listed in :attr:`InitResult.failed` and the others go on; an
    unknown area raises ``ValueError`` before anything is downloaded, and an
    error writing to disk (``OSError``) is raised.

    ``client`` is used and left open; ``retries`` is passed to
    :class:`~ispra_idrogeo.client.IdroGEO` (``0`` to put your own retry
    policy around the call).
    """
    async with IdroGEO(client, retries=retries) as idrogeo:
        return await init_with(
            idrogeo,
            directory,
            areas=areas,
            mosaics=mosaics,
            boundaries=boundaries,
            land_cover=land_cover,
            unpack=unpack,
            max_age=max_age,
            concurrency=concurrency,
        )
