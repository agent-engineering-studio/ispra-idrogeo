"""The persistent download folder, and what it remembers about each file.

Next to every downloaded file sits ``<file>.meta.json`` with the URL and the
``ETag`` / ``Last-Modified`` the server sent. They become the
``If-None-Match`` / ``If-Modified-Since`` of the next request, so a file
that has not changed is answered 304 and costs no download.
"""

from __future__ import annotations

import json
import os
import shutil
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from ispra_idrogeo.errors import IdrogeoError

#: The environment variable :func:`default_directory` reads.
ENV_DATA_DIR = "IDROGEO_DATA_DIR"

_CHUNK = 1 << 20


def default_directory() -> Path:
    """Where downloads go when no directory is given.

    ``IDROGEO_DATA_DIR`` if set, else ``ispra-idrogeo`` in the user cache
    (``$XDG_CACHE_HOME``, or ``~/.cache``). Use a folder that survives
    restarts: the national files weigh hundreds of MB.
    """
    if configured := os.environ.get(ENV_DATA_DIR, "").strip():
        return Path(configured).expanduser()
    cache = os.environ.get("XDG_CACHE_HOME", "").strip() or "~/.cache"
    return Path(cache).expanduser() / "ispra-idrogeo"


@dataclass(frozen=True, slots=True)
class Validators:
    """What the server said about the copy on disk."""

    url: str
    etag: str | None = None
    last_modified: str | None = None

    def headers(self) -> dict[str, str]:
        """The conditional-request headers for the next download."""
        out = {}
        if self.etag:
            out["If-None-Match"] = self.etag
        if self.last_modified:
            out["If-Modified-Since"] = self.last_modified
        return out


def meta_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.meta.json")


def read_validators(path: Path, url: str) -> Validators | None:
    """The validators of a file on disk, or ``None`` if it cannot be revalidated.

    A file without metadata, with unreadable metadata, or downloaded from
    another URL is downloaded again rather than trusted.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(meta_path(path).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("url") != url:
        return None
    return Validators(url=url, etag=data.get("etag"), last_modified=data.get("last_modified"))


def write_validators(path: Path, validators: Validators) -> None:
    target = meta_path(path)
    partial = target.with_name(f"{target.name}.part")
    partial.write_text(json.dumps(asdict(validators)))
    partial.replace(target)


def extract(archive: Path, folder: Path) -> Path:
    """Unpack a ZIP into ``folder``, replacing what was there; ``folder``.

    The new content is unpacked beside the old one and swapped in only when
    complete, so a reader never finds half a shapefile. Members that would
    land outside ``folder`` raise :class:`IdrogeoError`.
    """
    partial = folder.with_name(f"{folder.name}.part")
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                name = PurePosixPath(info.filename)
                if name.is_absolute() or ".." in name.parts:
                    raise IdrogeoError(f"{archive.name}: unsafe member {info.filename!r}")
                if info.is_dir():
                    continue
                target = partial.joinpath(*name.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst, _CHUNK)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    old = folder.with_name(f"{folder.name}.old")
    shutil.rmtree(old, ignore_errors=True)
    if folder.exists():
        folder.rename(old)
    partial.rename(folder)
    shutil.rmtree(old, ignore_errors=True)
    return folder
