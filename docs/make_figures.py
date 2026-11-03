# ruff: noqa: E501  (SVG markup reads better on one line)
"""Draw the README figures in docs/images/ from live IdroGEO API answers.

    uv run python docs/make_figures.py

Needs the network (about 40 small API calls) and nothing but this package.
"""

from __future__ import annotations

import asyncio
import datetime
from pathlib import Path
from typing import Any

from ispra_idrogeo import IdroGEO

OUT = Path(__file__).parent / "images"
_today = datetime.date.today()
TODAY = f"{_today.day} {_today:%B %Y}"


async def load() -> tuple[dict[int, dict[str, Any]], dict[int, int], int]:
    """Per-region counts and areas, national counts by movement type, total."""
    async with IdroGEO() as idrogeo:
        regions = {}
        for region in await idrogeo.summary("iffi", "regioni"):
            cod = region["cod_reg"]
            counts = await idrogeo.summary("iffi", "regioni", cod)
            hazard = await idrogeo.summary("pir", "regioni", cod)
            regions[cod] = {
                "nome": region["nome"],
                "frane": counts["frane_totali"],
                "ar": hazard["ar_kmq"],
            }
        italy = await idrogeo.summary("iffi", "italia")
    types = {s["cod"]: s["nr_frane"] for s in italy["frane_stats"]}
    return regions, types, italy["frane_totali"]


regions, TYPE_COUNTS, TOTAL = asyncio.run(load())

FONT = 'text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}'
BASE_CSS = """
  .bg{fill:#fcfcfb} .h{fill:#0b0b0b} .t2{fill:#52514e} .ax{fill:#7a7974} .grid{stroke:#e6e5e0;stroke-width:1}
  .chip{fill:#f0efec} .val{fill:#0b0b0b} .edge{stroke:#fcfcfb}
  @media (prefers-color-scheme: dark){
    .bg{fill:#1a1a19} .h{fill:#f0efec} .t2{fill:#c3c2b7} .ax{fill:#8f8e88} .grid{stroke:#2e2e2b}
    .chip{fill:#2a2a28} .val{fill:#f0efec} .edge{stroke:#1a1a19}
  }
"""

# Tile map of Italy: (column, row) of each region, one square per region.
GRID = {
    4: (2, 0),
    6: (3, 0),
    2: (0, 1),
    3: (1, 1),
    5: (2, 1),
    1: (0, 2),
    8: (1, 2),
    7: (0, 3),
    9: (1, 3),
    10: (2, 3),
    11: (3, 3),
    12: (2, 4),
    13: (3, 4),
    14: (4, 4),
    20: (0, 5),
    15: (3, 5),
    16: (4, 5),
    17: (4, 6),
    18: (4, 7),
    19: (3, 8),
}
SHORT = {
    1: "PIE",
    2: "VDA",
    3: "LOM",
    4: "TAA",
    5: "VEN",
    6: "FVG",
    7: "LIG",
    8: "EMR",
    9: "TOS",
    10: "UMB",
    11: "MAR",
    12: "LAZ",
    13: "ABR",
    14: "MOL",
    15: "CAM",
    16: "PUG",
    17: "BAS",
    18: "CAL",
    19: "SIC",
    20: "SAR",
}
BY_PROVINCE = {4, 19}
BINS = [  # landslides per 100 km², upper bound, fill, text colour
    (50, "#fbe3d6", "#5a2a1a"),
    (150, "#f5b69a", "#5a2a1a"),
    (300, "#ec8665", "#3b1408"),
    (450, "#d9553b", "#ffffff"),
    (10**9, "#a8321f", "#ffffff"),
]
BIN_LABELS = ["under 50", "50 to 150", "150 to 300", "300 to 450", "over 450"]


def density(cod: int) -> float:
    r = regions[cod]
    return r["frane"] / r["ar"] * 100


def colour(cod: int) -> tuple[str, str]:
    d = density(cod)
    for top, fill, ink in BINS:
        if d < top:
            return fill, ink
    raise AssertionError


def tiles(x0: float, y0: float, size: float, gap: float, labels: bool) -> str:
    out = []
    for cod, (c, r) in GRID.items():
        x, y = x0 + c * (size + gap), y0 + r * (size + gap)
        fill, ink = colour(cod)
        reg = regions[cod]
        tip = f"{reg['nome']}: {reg['frane']:,} landslides, {density(cod):.0f} per 100 km²"
        out.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{size}" height="{size}" rx="{size * 0.12:.1f}" '
            f'fill="{fill}"><title>{tip}</title></rect>'
        )
        if cod in BY_PROVINCE and labels:
            out.append(
                f'<circle cx="{x + size - 11:.1f}" cy="{y + 11:.1f}" r="4.5" fill="{ink}" opacity=".85"/>'
            )
        if labels:
            out.append(
                f'<text x="{x + size / 2:.1f}" y="{y + size / 2 - 3:.1f}" text-anchor="middle" '
                f'font-size="15" font-weight="700" fill="{ink}">{SHORT[cod]}</text>'
            )
            out.append(
                f'<text x="{x + size / 2:.1f}" y="{y + size / 2 + 16:.1f}" text-anchor="middle" '
                f'font-size="12" fill="{ink}">{reg["frane"]:,}</text>'
            )
    return "\n".join(out)


def banner() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 260" role="img" aria-label="ispra-idrogeo: Italy's landslides and floods, from ISPRA IdroGEO, in a few lines of Python">
<style>{FONT}{BASE_CSS}</style>
<rect class="bg" width="1000" height="260" rx="14"/>
<text class="h" x="40" y="92" font-size="44" font-weight="700">ispra-idrogeo</text>
<text class="t2" x="40" y="128" font-size="18">Italy's landslides and flood hazard, from ISPRA IdroGEO,</text>
<text class="t2" x="40" y="152" font-size="18">in a few lines of Python.</text>
<g font-size="13">
  <rect class="chip" x="40" y="182" width="146" height="28" rx="14"/><text class="t2" x="113" y="201" text-anchor="middle">{TOTAL:,} landslides</text>
  <rect class="chip" x="194" y="182" width="60" height="28" rx="14"/><text class="t2" x="224" y="201" text-anchor="middle">IFFI</text>
  <rect class="chip" x="262" y="182" width="52" height="28" rx="14"/><text class="t2" x="288" y="201" text-anchor="middle">PAI</text>
  <rect class="chip" x="322" y="182" width="64" height="28" rx="14"/><text class="t2" x="354" y="201" text-anchor="middle">async</text>
  <rect class="chip" x="394" y="182" width="96" height="28" rx="14"/><text class="t2" x="442" y="201" text-anchor="middle">no API key</text>
</g>
<g transform="translate(760 14)">
{tiles(0, 0, 22, 4, labels=False)}
</g>
</svg>
"""


def tile_map() -> str:
    size, gap, x0, y0 = 70, 6, 40, 92
    lx = 470
    legend = []
    for i, ((_, fill, _), label) in enumerate(zip(BINS, BIN_LABELS, strict=True)):
        y = 170 + i * 34
        legend.append(f'<rect x="{lx}" y="{y}" width="26" height="26" rx="4" fill="{fill}"/>')
        legend.append(f'<text class="t2" x="{lx + 38}" y="{y + 18}" font-size="14">{label}</text>')
    top = sorted(regions, key=lambda c: -regions[c]["frane"])[:5]
    peak = regions[top[0]]["frane"]
    bars = []
    for i, cod in enumerate(top):
        y = 470 + i * 34
        w = regions[cod]["frane"] / peak * 250
        bars.append(
            f'<text class="t2" x="{lx + 130}" y="{y + 17}" font-size="14" text-anchor="end">{regions[cod]["nome"]}</text>'
        )
        bars.append(
            f'<rect x="{lx + 142}" y="{y + 2}" width="{w:.1f}" height="22" rx="3" fill="#d9553b"/>'
        )
        bars.append(
            f'<text class="val" x="{lx + 150 + w:.1f}" y="{y + 18}" font-size="13" font-weight="600">{regions[cod]["frane"]:,}</text>'
        )
    height = y0 + 9 * (size + gap) + 30
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 {height}" role="img" aria-label="Tile map of Italy's 20 regions coloured by IFFI landslides per 100 square km: Lombardia, Molise and Toscana are highest, Puglia and Sardegna lowest">
<style>{FONT}{BASE_CSS}</style>
<rect class="bg" width="980" height="{height}" rx="14"/>
<text class="h" x="40" y="44" font-size="20" font-weight="700">The IFFI inventory, region by region</text>
<text class="t2" x="40" y="68" font-size="14">One square per region (not to scale). The number is how many landslides are mapped there.</text>
{tiles(x0, y0, size, gap, labels=True)}
<text class="h" x="{lx}" y="150" font-size="15" font-weight="700">Landslides per 100 km²</text>
{chr(10).join(legend)}
<circle cx="{lx + 13}" cy="{352}" r="4.5" class="h"/>
<text class="t2" x="{lx + 38}" y="{357}" font-size="14">also published per province</text>
<text class="t2" x="{lx + 38}" y="{377}" font-size="14">(opendata(layer, "trento"), …)</text>
<text class="h" x="{lx}" y="450" font-size="15" font-weight="700">Most landslides mapped</text>
{chr(10).join(bars)}
<text class="ax" x="{lx}" y="672" font-size="12">Density shows mapping effort as well as terrain:</text>
<text class="ax" x="{lx}" y="690" font-size="12">regions surveyed in more detail list more landslides.</text>
<text class="ax" x="{lx}" y="{height - 30}" font-size="12">Source: ISPRA IdroGEO API, iffi/regioni, {TODAY}.</text>
</svg>
"""


TYPES = [  # code, English name from the tipo_movimento dictionary
    (2, "rotational/translational slide"),
    (4, "slow earth flow"),
    (5, "rapid debris flow"),
    (11, "areas of shallow landslides"),
    (9, "areas of rockfalls/topples"),
    (7, "complex"),
    (1, "fall/topple"),
    (0, "not determined"),
    (8, "deep-seated deformation (DGPV)"),
]


def types_chart() -> str:
    peak = max(TYPE_COUNTS.values())
    x0, scale = 300, 520 / peak
    rows, grid = [], []
    for v in range(0, 250_001, 50_000):
        x = x0 + v * scale
        grid.append(
            f'<line class="grid" x1="{x:.1f}" y1="62" x2="{x:.1f}" y2="{62 + len(TYPES) * 34}"/>'
        )
        grid.append(
            f'<text class="ax" x="{x:.1f}" y="{80 + len(TYPES) * 34}" text-anchor="middle" font-size="11">{v // 1000}k</text>'
        )
    for i, (cod, name) in enumerate(TYPES):
        y = 66 + i * 34
        n = TYPE_COUNTS[cod]
        fill = "#d9553b" if i < 3 else "#a3a29b"
        rows.append(
            f'<text class="t2" x="{x0 - 14}" y="{y + 18}" font-size="14" text-anchor="end">{name}</text>'
        )
        rows.append(
            f'<rect x="{x0}" y="{y}" width="{n * scale:.1f}" height="24" rx="4" fill="{fill}"><title>{name}: {n:,}</title></rect>'
        )
        rows.append(
            f'<text class="val" x="{x0 + n * scale + 8:.1f}" y="{y + 17}" font-size="13" font-weight="600">{n:,}</text>'
        )
    height = 120 + len(TYPES) * 34
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 {height}" role="img" aria-label="IFFI landslides in Italy by type of movement: slides {TYPE_COUNTS[2]:,}, slow earth flows {TYPE_COUNTS[4]:,}, rapid debris flows {TYPE_COUNTS[5]:,}">
<style>{FONT}{BASE_CSS}</style>
<rect class="bg" width="980" height="{height}" rx="14"/>
<text class="h" x="40" y="40" font-size="17" font-weight="700">How Italy's landslides move</text>
{chr(10).join(grid)}
{chr(10).join(rows)}
<text class="ax" x="40" y="{height - 14}" font-size="12">IFFI, whole of Italy, by tipo_movimento. Source: ISPRA IdroGEO API, iffi/italia, {TODAY}.</text>
</svg>
"""


SIZES = [  # label, MB (Italy, zipped)
    ('mosaic("pai_frane")  landslide hazard', 1200),
    ('mosaic("idraulica")  flood hazard', 750),
    ('"frane_poly"  landslide polygons', 573),
    ('"aree_poly"  diffuse landslide areas', 236),
    ('"frane_piff"  one point per landslide', 38),
    ('"frane_line"  narrow landslides', 18),
    ('"dgpv_poly"  deep-seated deformations', 4),
    ('"eventi"  dated events', 1),
]


def sizes_chart() -> str:
    x0, scale = 340, 470 / 1200
    rows, grid = [], []
    n = len(SIZES)
    for v in range(0, 1201, 300):
        x = x0 + v * scale
        grid.append(f'<line class="grid" x1="{x:.1f}" y1="62" x2="{x:.1f}" y2="{62 + n * 34}"/>')
        grid.append(
            f'<text class="ax" x="{x:.1f}" y="{80 + n * 34}" text-anchor="middle" font-size="11">{v}</text>'
        )
    for i, (label, mb) in enumerate(SIZES):
        y = 66 + i * 34
        w = max(mb * scale, 2)
        txt = f"{mb / 1000:.2g} GB" if mb >= 1000 else f"{mb} MB"
        rows.append(
            f'<text class="t2" x="{x0 - 14}" y="{y + 18}" font-size="13" text-anchor="end">{label}</text>'
        )
        rows.append(
            f'<rect x="{x0}" y="{y}" width="{w:.1f}" height="24" rx="4" fill="#a3a29b"><title>{label}: {txt}</title></rect>'
        )
        rows.append(
            f'<text class="val" x="{x0 + w + 8:.1f}" y="{y + 17}" font-size="13" font-weight="600">{txt}</text>'
        )
    y = 100 + n * 34
    height = y + 86
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 {height}" role="img" aria-label="Download sizes for the whole of Italy, from 1.2 GB for the landslide hazard mosaic to 1 MB for events; the next run of an unchanged file costs one 304 answer">
<style>{FONT}{BASE_CSS} .keep{{fill:#2a78d6}} @media (prefers-color-scheme: dark){{ .keep{{fill:#3987e5}} }}</style>
<rect class="bg" width="980" height="{height}" rx="14"/>
<text class="h" x="40" y="40" font-size="17" font-weight="700">First run: what each layer weighs for all of Italy (MB, zipped)</text>
{chr(10).join(grid)}
{chr(10).join(rows)}
<rect class="keep" x="40" y="{y + 10}" width="10" height="56" rx="3"/>
<text class="h" x="64" y="{y + 32}" font-size="15" font-weight="700">Every run after that: one "304 Not Modified" per file, a few hundred bytes.</text>
<text class="t2" x="64" y="{y + 56}" font-size="14">ISPRA rebuilds the inventory files daily; only a file that really changed is downloaded and unpacked again.</text>
</svg>
"""


OUT.mkdir(parents=True, exist_ok=True)
(OUT / "banner.svg").write_text(banner())
(OUT / "map.svg").write_text(tile_map())
(OUT / "types.svg").write_text(types_chart())
(OUT / "sizes.svg").write_text(sizes_chart())
