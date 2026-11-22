"""After the site build, write site/llms-full.txt and copy the agent skill.

    uv run zensical build --strict && uv run python tools/build_llms.py

llms.txt (docs/llms.txt) is the short guide; llms-full.txt is the whole
README in plain Markdown (images and HTML left out) after it, so a model can
read the full documentation in one file. skills/ispra-idrogeo/SKILL.md is
published next to them as SKILL.md.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def plain(markdown: str) -> str:
    """The README without HTML tags, image lines and the include markers."""
    text = re.sub(r"<!--.*?-->", "", markdown, flags=re.S)
    text = re.sub(r"<p[^>]*>.*?</p>", "", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def main(site: Path = ROOT / "site") -> int:
    if not site.is_dir():
        print(f"{site} does not exist: build the site first", file=sys.stderr)
        return 1
    short = (ROOT / "docs" / "llms.txt").read_text(encoding="utf-8").strip()
    readme = plain((ROOT / "README.md").read_text(encoding="utf-8"))
    (site / "llms-full.txt").write_text(f"{short}\n\n---\n\n{readme}", encoding="utf-8")
    shutil.copy(ROOT / "skills" / "ispra-idrogeo" / "SKILL.md", site / "SKILL.md")
    print(f"{site / 'llms-full.txt'}, {site / 'SKILL.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
