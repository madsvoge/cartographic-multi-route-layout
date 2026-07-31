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

from ptolemy_map import CATEGORIES, DEFAULT_INPUT, get_coastlines, get_island_lines, get_mountain_lines, get_river_lines, load_inputs

SCRIPT_DIR = Path(__file__).resolve().parent

# lon_min, lat_min, lon_max, lat_max
REGIONS = {
    "world": (-180, -60, 180, 75),
    "europe": (-15, 33, 45, 63),
    "mediterranean": (-10, 28, 40, 47),
    "asia": (25, -10, 135, 55),
    "africa": (-20, -35, 55, 38),
}

LAND = "#eceae4"
OCEAN = "#dbe6ee"
BORDER = "#c3c2b7"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
MOUNTAIN_LINE_COLOR = "#6b4226"

# --fill-ptolemy-land's world-edge closure: the same bounding box
# --region world already renders with. Two of this catalogue's confirmed
# world-edge points (see README.md's "Filling Ptolemy's own coastline")
# close against its southern edge specifically, not just "nearest edge" -
# Ptolemy's own claimed cosmology has an unknown southern landmass below
# the known world, enclosing the Indian Ocean, which is exactly what
# projecting straight down represents. A third pair, Kap Rhapton and
# Kattigara, closes directly against *each other* instead of the box -
# the one closure with actual textual backing (Ptolemy explicitly
# believed and stated the Indian Ocean was landlocked), the same "Terra
# Incognita" land bridge the 1482/1486 Ulm editions themselves drew.
_WORLD_EDGE_BBOX = REGIONS["world"]
_HYPODROMOS_AITHIOPIAS = "4.06.07.08"  # Africa's own Atlantic-coast world edge
_KAP_RHAPTON = "4.07.12.04"  # Africa's own Indian-Ocean-side world edge
_KUTIARIS_MUENDUNG = "7.03.03.03"  # start of the small fragment leading to Kattigara
_KATTIGARA = "7.03.03.07"  # Asia's own far-eastern world edge, the "Land of the Sinai"


def _in_bbox(lon: float, lat: float, bbox: tuple[float, float, float, float]) -> bool:
    lon_min, lat_min, lon_max, lat_max = bbox
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def _find_trail_by_endpoint(trails: list, ref_id: str):
    """Return (trail, index_within_trail) for the trail whose first or last
    point has this ref_id, or (None, None)."""
    for trail in trails:
        if trail and trail[0].ref_id == ref_id:
            return trail, 0
        if trail and trail[-1].ref_id == ref_id:
            return trail, -1
    return None, None


def _build_world_edge_polygon(refs) -> list[tuple[float, float]] | None:
    """The one combined, fillable shape this catalogue's own world-edge
    points support today: Africa's own coast (Hypodromos Aithiopias ->
    Kap Rhapton), a schematic land-bridge to the small Kattigara fragment
    (Kutiaris-Mündung -> Kattigara), and both loose ends closed against
    the southern edge of the world bounding box - see the module-level
    comment above _WORLD_EDGE_BBOX. Returns None if the expected trails
    aren't found (e.g. a future round merges or renames them)."""
    coastlines = get_coastlines(refs)
    africa, africa_end = _find_trail_by_endpoint(coastlines, _KAP_RHAPTON)
    kattigara_frag, _ = _find_trail_by_endpoint(coastlines, _KUTIARIS_MUENDUNG)
    if africa is None or kattigara_frag is None:
        return None
    if africa[0].ref_id != _HYPODROMOS_AITHIOPIAS:
        africa = list(reversed(africa))
    if kattigara_frag[0].ref_id != _KUTIARIS_MUENDUNG:
        kattigara_frag = list(reversed(kattigara_frag))
    if kattigara_frag[-1].ref_id != _KATTIGARA:
        return None  # shape assumption no longer holds - skip rather than draw something wrong

    lon_min, lat_min, lon_max, lat_max = _WORLD_EDGE_BBOX
    hypodromos = africa[0]
    kattigara = kattigara_frag[-1]
    south_under_hypodromos = (hypodromos.lon_modern, lat_min)
    south_under_kattigara = (kattigara.lon_modern, lat_min)

    coords = [(r.lon_modern, r.lat_modern) for r in africa]
    coords += [(r.lon_modern, r.lat_modern) for r in kattigara_frag]
    coords += [south_under_kattigara, south_under_hypodromos]
    return coords


def render(
    refs,
    bbox,
    output: Path,
    title: str,
    label_coastlines: bool = False,
    show_feature_labels: bool = True,
    fill_ptolemy_land: bool = False,
) -> int:
    import geopandas
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle, Polygon
    from matplotlib.patheffects import withStroke

    lon_min, lat_min, lon_max, lat_max = bbox
    in_view = [r for r in refs if r.is_plausible() and _in_bbox(r.lon_modern, r.lat_modern, bbox)]

    fig, ax = plt.subplots(figsize=(14, 11), dpi=150)
    fig.patch.set_facecolor("#f9f9f7")
    ax.set_facecolor(OCEAN)

    if not fill_ptolemy_land:
        world = geopandas.read_file(geopandas.datasets.get_path("naturalearth_lowres"))
        pad = max((lon_max - lon_min), (lat_max - lat_min)) * 0.1
        world = world.cx[lon_min - pad : lon_max + pad, lat_min - pad : lat_max + pad]
        world.plot(ax=ax, color=LAND, edgecolor=BORDER, linewidth=0.6)

    coastlines = get_coastlines(refs)

    # --fill-ptolemy-land: fill *Ptolemy's own* closed loops as land, not
    # the modern Natural Earth ones above - only the trails that already
    # close back on their own starting point (an island, or the handful of
    # mainland peninsulas whose whole loop happens to be described end to
    # end) can be filled this way. Most of this catalogue's coastline
    # trails are open arcs - one province's described stretch of a much
    # larger, still-connected landmass - and stay outline-only until
    # they're stitched together into a full ring across book/map
    # boundaries, the same kind of work this project has done at a
    # regional scale all session, just not yet attempted at continental
    # scale. See README.md's "Filling Ptolemy's own coastline" section.
    n_filled = 0
    if fill_ptolemy_land:
        for trail in coastlines + get_island_lines(refs):
            if not trail or not (trail[0].feature_closes_loop or trail[0].island_feature_closes_loop):
                continue
            coords = [(r.lon_modern, r.lat_modern) for r in trail]
            ax.add_patch(Polygon(coords, closed=True, facecolor=LAND, edgecolor=BORDER, linewidth=0.6, zorder=2))
            n_filled += 1

        world_edge_coords = _build_world_edge_polygon(refs)
        if world_edge_coords is not None:
            ax.add_patch(Polygon(world_edge_coords, closed=True, facecolor=LAND, edgecolor=BORDER, linewidth=0.6, zorder=2))
            n_filled += 1

    coastline_segments_drawn = 0
    for trail_idx, trail in enumerate(coastlines):
        line_in_view = [(r.lon_modern, r.lat_modern, i, r) for i, r in enumerate(trail) if _in_bbox(r.lon_modern, r.lat_modern, bbox)]
        if len(line_in_view) < 2:
            continue
        coords = [(r.lon_modern, r.lat_modern) for r in trail]
        xs, ys = zip(*coords)
        ax.plot(xs, ys, color=CATEGORIES["coast"]["color"], linewidth=2.2, alpha=0.9, zorder=4)
        coastline_segments_drawn += 1
        if label_coastlines:
            for lon, lat, i, r in line_in_view:
                ax.annotate(
                    r.ref_id,
                    (lon, lat),
                    fontsize=6.5,
                    color="#0b0b0b",
                    xytext=(4, 4),
                    textcoords="offset points",
                    zorder=6,
                )

    river_lines = get_river_lines(refs)
    river_lines_drawn = 0
    for line in river_lines:
        line_in_view = [r for r in line if _in_bbox(r.lon_modern, r.lat_modern, bbox)]
        if len(line_in_view) < 2:
            continue
        coords = [(r.lon_modern, r.lat_modern) for r in line]
        xs, ys = zip(*coords)
        ax.plot(xs, ys, color=CATEGORIES["river_mouth"]["color"], linewidth=1.1, alpha=0.8, zorder=3)
        river_lines_drawn += 1

    island_lines = get_island_lines(refs)
    island_lines_drawn = 0
    island_line_ref_ids: set[str] = set()
    for line in island_lines:
        island_line_ref_ids.update(r.ref_id for r in line)
        line_in_view = [r for r in line if _in_bbox(r.lon_modern, r.lat_modern, bbox)]
        if len(line_in_view) < 2:
            continue
        coords = [(r.lon_modern, r.lat_modern) for r in line]
        xs, ys = zip(*coords)
        ax.plot(xs, ys, color=CATEGORIES["island"]["color"], linewidth=1.8, alpha=0.9, zorder=4)
        island_lines_drawn += 1

    mountain_lines = get_mountain_lines(refs)
    mountain_lines_drawn = 0
    for line in mountain_lines:
        line_in_view = [r for r in line if _in_bbox(r.lon_modern, r.lat_modern, bbox)]
        if len(line_in_view) < 2:
            continue
        coords = [(r.lon_modern, r.lat_modern) for r in line]
        xs, ys = zip(*coords)
        ax.plot(xs, ys, color=MOUNTAIN_LINE_COLOR, linewidth=3.0, alpha=0.85, zorder=3, solid_capstyle="round")
        mountain_lines_drawn += 1

    # No known coastal walk for these - a single citation, or one entry in
    # a list of several different islands (see _ISLAND_LINE_GROUPS). A real
    # cartographer working from just one reported position wouldn't have
    # left a bare point either - they'd still sketch a small schematic
    # island there. This circle is exactly that: a stylistic placeholder,
    # not a real coastline (its size carries no geographic meaning).
    for r in in_view:
        if r.category == "island" and r.ref_id not in island_line_ref_ids:
            ax.add_patch(
                Circle(
                    (r.lon_modern, r.lat_modern),
                    radius=0.09,
                    facecolor=CATEGORIES["island"]["color"],
                    edgecolor=CATEGORIES["island"]["color"],
                    alpha=0.3,
                    linewidth=1.0,
                    zorder=4,
                )
            )

    # Synthetic region/island-group/mountain-range labels (build_labels.py,
    # category "label") aren't real catalogue points - not in CATEGORIES,
    # so the scatter loop below already skips them; draw plain italic text
    # for them instead of a colored dot.
    label_refs_drawn = 0
    if show_feature_labels:
        for r in in_view:
            if r.category != "label":
                continue
            ax.annotate(
                r.name,
                (r.lon_modern, r.lat_modern),
                fontsize=12,
                fontstyle="italic",
                fontweight="bold",
                color="#2b2b2b",
                ha="center",
                va="center",
                zorder=6,
                path_effects=[withStroke(linewidth=3, foreground="white")],
            )
            label_refs_drawn += 1

    present_categories = [cat for cat in CATEGORIES if any(r.category == cat for r in in_view)]
    for cat in present_categories:
        pts = [(r.lon_modern, r.lat_modern) for r in in_view if r.category == cat]
        xs, ys = zip(*pts)
        is_coast_family = cat in ("coast", "harbor", "river_mouth")
        # Lakes share the rivers' light-blue color now - sized up instead,
        # so a lake still reads as visually distinct rather than blending
        # into the same-colored river points around it.
        size = 70 if cat == "lake" else (42 if is_coast_family else 16)
        ax.scatter(
            xs,
            ys,
            s=size,
            color=CATEGORIES[cat]["color"],
            alpha=0.85 if is_coast_family or cat == "lake" else 0.75,
            linewidths=0.6 if cat in ("coast", "lake") else 0.3,
            edgecolors="white",
            zorder=5,
            label=f"{CATEGORIES[cat]['label']} ({len(pts)})",
        )

    if present_categories:
        legend = ax.legend(loc="upper right", fontsize=8.5, framealpha=0.9, facecolor="#fcfcfb", edgecolor=BORDER)
        for text in legend.get_texts():
            text.set_color(TEXT_PRIMARY)

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
        f"{len(in_view)} of {len(refs)} catalogue references shown "
        f"({coastline_segments_drawn} coastline segments, {river_lines_drawn} river lines, "
        f"{island_lines_drawn} island outlines, {mountain_lines_drawn} mountain-range lines, "
        f"{label_refs_drawn} feature labels) "
        "at modernized (Ferro-offset) coordinates",
        fontsize=11.5,
        color=TEXT_SECONDARY,
        ha="left",
    )
    basemap_note = (
        f"Land fill: {n_filled} of Ptolemy's own closed coastline/island loops - open coastal arcs "
        "are outline-only, not yet stitched into closed regions."
        if fill_ptolemy_land
        else "Basemap: Natural Earth (public domain)."
    )
    fig.text(
        0.06,
        0.02,
        f"{basemap_note} Coordinates are Ptolemy's own claimed positions, "
        "converted from his Ferro meridian to Greenwich - not modern surveyed locations.",
        fontsize=8.5,
        color=TEXT_SECONDARY,
        ha="left",
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, facecolor=fig.get_facecolor())
    print(
        f"plotted {len(in_view)} reference(s), {coastline_segments_drawn} coastline segments, "
        f"{river_lines_drawn} river lines, {island_lines_drawn} island outlines, "
        f"{mountain_lines_drawn} mountain-range lines, {label_refs_drawn} feature labels -> {output}"
    )
    return len(in_view)


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
    parser.add_argument(
        "--label-coastlines",
        action="store_true",
        help="Annotate each coastal point with its ref_id - "
        "for auditing a specific --bbox, not for wide views (gets unreadable fast)",
    )
    parser.add_argument(
        "--hide-feature-labels",
        action="store_true",
        help="Suppress the italic region/island-group/mountain-range text labels",
    )
    parser.add_argument(
        "--fill-ptolemy-land",
        action="store_true",
        help="Fill Ptolemy's own closed coastline/island loops as land, blue ocean everywhere else, "
        "instead of the modern Natural Earth land fill - only trails that already close back on "
        "their own start (islands, a few self-contained peninsulas) can be filled this way; open "
        "coastal arcs stay outline-only. See README.md's 'Filling Ptolemy's own coastline' section.",
    )
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
    render(
        refs,
        bbox,
        args.output,
        title,
        label_coastlines=args.label_coastlines,
        show_feature_labels=not args.hide_feature_labels,
        fill_ptolemy_land=args.fill_ptolemy_land,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
