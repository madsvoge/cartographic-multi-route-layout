#!/usr/bin/env python3
"""
Static Ptolemy's Geographica map (no tile server required)
============================================================

`ptolemy_map.py` renders an interactive Leaflet/OpenStreetMap page, which
needs a browser with network access to fetch map tiles. This script instead
renders a static PNG using an offline basemap (Natural Earth, public domain,
bundled with geopandas<1.0's `naturalearth_lowres` dataset) - useful for
environments without tile-server access, or for embedding a plain image in
a document.

Usage
-----
    pip install -r requirements-static.txt
    python3 static_map.py                                  # world, all references
    python3 static_map.py --region europe                  # built-in region
    python3 static_map.py --bbox -15 33 45 63 --output out.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ptolemy_map import DEFAULT_INPUT, load_inputs

SCRIPT_DIR = Path(__file__).resolve().parent

# lon_min, lat_min, lon_max, lat_max
REGIONS = {
    "world": (-180, -60, 180, 75),
    "europe": (-15, 33, 45, 63),
    "mediterranean": (-10, 28, 40, 47),
    "asia": (25, -10, 135, 55),
    "africa": (-20, -35, 55, 38),
}

SERIES_BLUE = "#2a78d6"
LAND = "#eceae4"
OCEAN = "#dbe6ee"
BORDER = "#c3c2b7"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"


def render(refs, bbox, output: Path, title: str) -> int:
    import geopandas
    import matplotlib.pyplot as plt

    lon_min, lat_min, lon_max, lat_max = bbox
    points = [
        (r.lon_modern, r.lat_modern)
        for r in refs
        if r.is_plausible() and lon_min <= r.lon_modern <= lon_max and lat_min <= r.lat_modern <= lat_max
    ]

    world = geopandas.read_file(geopandas.datasets.get_path("naturalearth_lowres"))
    pad = max((lon_max - lon_min), (lat_max - lat_min)) * 0.1
    world = world.cx[lon_min - pad : lon_max + pad, lat_min - pad : lat_max + pad]

    fig, ax = plt.subplots(figsize=(14, 11), dpi=150)
    fig.patch.set_facecolor("#f9f9f7")
    ax.set_facecolor(OCEAN)

    world.plot(ax=ax, color=LAND, edgecolor=BORDER, linewidth=0.6)

    if points:
        xs, ys = zip(*points)
        ax.scatter(xs, ys, s=14, color=SERIES_BLUE, alpha=0.65, linewidths=0.4, edgecolors="white", zorder=5)

    ax.set_xlim(lon_min, lon_max)
    ax.set_ylim(lat_min, lat_max)
    ax.set_aspect(1.4)
    ax.grid(True, color="#ffffff", linewidth=0.6, alpha=0.6, zorder=1)
    ax.set_xlabel("Longitude", color=TEXT_SECONDARY, fontsize=10)
    ax.set_ylabel("Latitude", color=TEXT_SECONDARY, fontsize=10)
    ax.tick_params(colors=TEXT_SECONDARY, labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(BORDER)

    fig.subplots_adjust(top=0.88, bottom=0.09, left=0.06, right=0.98)
    fig.text(0.06, 0.965, title, fontsize=18, color=TEXT_PRIMARY, fontweight="bold", ha="left")
    fig.text(
        0.06,
        0.925,
        f"{len(points)} of {len(refs)} catalogue references shown at modernized (Ferro-offset) coordinates",
        fontsize=11.5,
        color=TEXT_SECONDARY,
        ha="left",
    )
    fig.text(
        0.06,
        0.02,
        "Basemap: Natural Earth (public domain). Coordinates are Ptolemy's own claimed positions, "
        "converted from his Ferro meridian to Greenwich - not modern surveyed locations.",
        fontsize=8.5,
        color=TEXT_SECONDARY,
        ha="left",
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, facecolor=fig.get_facecolor())
    print(f"plotted {len(points)} reference(s) -> {output}")
    return len(points)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", nargs="*", type=Path, default=[DEFAULT_INPUT], help="CSV/XLSX file(s) or directories")
    parser.add_argument("--region", choices=sorted(REGIONS), default="world", help="Built-in region bounding box")
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"),
        default=None,
        help="Custom bounding box, overrides --region",
    )
    parser.add_argument("--output", type=Path, default=SCRIPT_DIR / "ptolemy_map_static.png")
    parser.add_argument("--title", default=None, help="Custom map title")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    refs = [r for r in load_inputs(args.input) if r.is_plausible()]
    if not refs:
        print("no geographical references loaded")
        return 1

    bbox = tuple(args.bbox) if args.bbox else REGIONS[args.region]
    region_label = "custom region" if args.bbox else args.region.title()
    title = args.title or f"Ptolemy's Geographica - geographical references ({region_label})"
    render(refs, bbox, args.output, title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
