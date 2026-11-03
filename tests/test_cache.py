from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from ispra_idrogeo import (
    IdrogeoError,
    Validators,
    default_directory,
    extract,
    read_validators,
    write_validators,
)


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    path.write_bytes(buffer.getvalue())
    return path


def test_default_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IDROGEO_DATA_DIR", str(tmp_path / "dati"))
    assert default_directory() == tmp_path / "dati"
    monkeypatch.delenv("IDROGEO_DATA_DIR")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert default_directory() == tmp_path / "ispra-idrogeo"
    monkeypatch.delenv("XDG_CACHE_HOME")
    assert default_directory() == Path("~/.cache/ispra-idrogeo").expanduser()


def test_validators_round_trip(tmp_path: Path) -> None:
    f = tmp_path / "a.zip"
    assert read_validators(f, "u") is None  # no file
    f.write_bytes(b"x")
    assert read_validators(f, "u") is None  # no metadata
    write_validators(f, Validators(url="u", etag='"e"', last_modified="Tue"))
    v = read_validators(f, "u")
    assert v is not None
    assert v.headers() == {"If-None-Match": '"e"', "If-Modified-Since": "Tue"}
    assert read_validators(f, "other") is None  # another URL is not trusted
    (tmp_path / "a.zip.meta.json").write_text("[1]")
    assert read_validators(f, "u") is None
    (tmp_path / "a.zip.meta.json").write_text("{not json")
    assert read_validators(f, "u") is None
    assert Validators(url="u").headers() == {}


def test_extract_replaces_the_folder_whole(tmp_path: Path) -> None:
    first = _zip(tmp_path / "a.zip", {"x.shp": b"1", "sub/y.dbf": b"2", "sub/": b""})
    folder = extract(first, tmp_path / "a")
    assert (folder / "x.shp").read_bytes() == b"1"
    assert (folder / "sub" / "y.dbf").read_bytes() == b"2"
    second = _zip(tmp_path / "b.zip", {"z.shp": b"3"})
    extract(second, folder)
    assert sorted(p.name for p in folder.iterdir()) == ["z.shp"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a", "a.zip", "b.zip"]


@pytest.mark.parametrize("name", ["../evil.shp", "/etc/evil"])
def test_extract_refuses_members_outside_the_folder(tmp_path: Path, name: str) -> None:
    archive = _zip(tmp_path / "a.zip", {name: b"!"})
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "kept.shp").write_bytes(b"old")
    with pytest.raises(IdrogeoError, match="unsafe member"):
        extract(archive, tmp_path / "a")
    assert (tmp_path / "a" / "kept.shp").read_bytes() == b"old"
    assert not (tmp_path / "a.part").exists()
