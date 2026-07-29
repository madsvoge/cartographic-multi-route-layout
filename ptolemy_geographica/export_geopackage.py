#!/usr/bin/env python3
"""
Export the annotated catalogue to a GeoPackage
=================================================

Writes `ptolemy_geographica.gpkg`, a single multi-layer GeoPackage for use
in QGIS/ArcGIS/any other GIS tool - the same categories and constructed
lines (coastlines, rivers, island outlines, mountain ranges) the two map
renderers (`ptolemy_map.py`, `static_map.py`) draw, but as real vector
layers instead of a picture.

Layer layout
------------
One point layer per category (the plain, unconnected reading of the
catalogue - every point, whether or not it's part of a constructed line):

    coast_points, harbor_points, river_mouth_points, city_points,
    river_points, mountain_points, island_points, lake_points, label_points

Plus, for the four point categories that get connected into a line
(coastlines walk the shore through coast/harbor/river_mouth points; rivers,
islands and mountain ranges connect same-named points elsewhere), a
LineString layer *and* a Point "nodes" layer - the nodes are the ordered
subset of the category points above that actually belong to a line, each
carrying its line's feature_id and its draw-order position, so the line and
its vertices can be related/joined in a GIS tool without recomputing
anything:

    coastlines          + coastline_nodes
    rivers               + river_nodes
    island_outlines      + island_outline_nodes
    mountain_ranges       + mountain_range_nodes

(A "nodes" layer's points are also present in the corresponding category
layer above - e.g. every coastline_nodes point is also in coast_points,
harbor_points or river_mouth_points - the nodes layer exists so a line's
vertices are available pre-filtered and pre-ordered, without a GIS-side
join.)

All geometry is in WGS84 (EPSG:4326), at the same Ferro-corrected modern
coordinates the map renderers use (see ptolemy_map.py's FERRO_OFFSET_DEG) -
Ptolemy's own claimed positions, not ground truth.

Usage
-----
    python3 export_geopackage.py                      # -> ptolemy_geographica.gpkg
    python3 export_geopackage.py --output out.gpkg
"""

from __future__ import annotations

import argparse
from pathlib import Path

import fiona

from ptolemy_map import (
    CATEGORIES,
    DEFAULT_INPUT,
    Reference,
    get_coastlines,
    get_island_lines,
    get_mountain_lines,
    get_river_lines,
    load_inputs,
)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "ptolemy_geographica.gpkg"
CRS = "EPSG:4326"

_POINT_PROPERTIES = {
    "ref_id": "str",
    "name": "str",
    "category": "str",
    "book": "str",
    "tabula": "str",
    "modern_location": "str",
    "recension": "str",
    "naming_observation": "str",
    "lon_ptolemy": "float",
    "lat_ptolemy": "float",
    "feature_id": "str",
    "sequence_in_feature": "int",
    "feature_closes_loop": "bool",
    "river_feature_id": "str",
    "river_sequence_in_feature": "int",
    "island_feature_id": "str",
    "island_sequence_in_feature": "int",
    "island_feature_closes_loop": "bool",
    "mountain_feature_id": "str",
    "mountain_sequence_in_feature": "int",
    "label_note": "str",
}

_LINE_PROPERTIES = {
    "feature_id": "str",
    "feature_type": "str",
    "name": "str",
    "point_count": "int",
    "closes_loop": "bool",
    "start_ref_id": "str",
    "end_ref_id": "str",
    "start_name": "str",
    "end_name": "str",
}


def _point_record(r: Reference) -> dict:
    return {
        "ref_id": r.ref_id,
        "name": r.name,
        "category": r.category,
        "book": r.book,
        "tabula": r.tabula,
        "modern_location": r.modern_location,
        "recension": r.recension,
        "naming_observation": r.naming_observation,
        "lon_ptolemy": r.lon_ptolemy,
        "lat_ptolemy": r.lat_ptolemy,
        "feature_id": r.feature_id,
        "sequence_in_feature": r.sequence_in_feature,
        "feature_closes_loop": r.feature_closes_loop,
        "river_feature_id": r.river_feature_id,
        "river_sequence_in_feature": r.river_sequence_in_feature,
        "island_feature_id": r.island_feature_id,
        "island_sequence_in_feature": r.island_sequence_in_feature,
        "island_feature_closes_loop": r.island_feature_closes_loop,
        "mountain_feature_id": r.mountain_feature_id,
        "mountain_sequence_in_feature": r.mountain_sequence_in_feature,
        "label_note": r.label_note,
    }


def _feature_name(feature_id: str) -> str:
    """feature_id is "<kind>_<index>_<name>" (coastline_000_EU01,
    river_003_Danuvius, island_002_Corfu, mountain_014_Pyrene-Gebirge) -
    the trailing part is already a readable name/tabula."""
    parts = feature_id.split("_", 2)
    return parts[2] if len(parts) > 2 else feature_id


def _write_points_layer(gpkg: Path, layer: str, refs: list[Reference]) -> int:
    if not refs:
        return 0
    schema = {"geometry": "Point", "properties": _POINT_PROPERTIES}
    with fiona.open(gpkg, "w", driver="GPKG", crs=CRS, schema=schema, layer=layer) as dst:
        for r in refs:
            dst.write(
                {
                    "geometry": {"type": "Point", "coordinates": (r.lon_modern, r.lat_modern)},
                    "properties": _point_record(r),
                }
            )
    return len(refs)


def _write_lines_layer(gpkg: Path, layer: str, feature_type: str, lines: list[list[Reference]]) -> int:
    lines = [line for line in lines if len(line) >= 2]
    if not lines:
        return 0
    schema = {"geometry": "LineString", "properties": _LINE_PROPERTIES}
    with fiona.open(gpkg, "w", driver="GPKG", crs=CRS, schema=schema, layer=layer) as dst:
        for line in lines:
            first, last = line[0], line[-1]
            feature_id = {
                "coastline": first.feature_id,
                "river": first.river_feature_id,
                "island_outline": first.island_feature_id,
                "mountain_range": first.mountain_feature_id,
            }[feature_type]
            closes_loop = {
                "coastline": first.feature_closes_loop,
                "island_outline": first.island_feature_closes_loop,
            }.get(feature_type, False)
            coords = [(r.lon_modern, r.lat_modern) for r in line]
            if closes_loop:
                coords = coords + [coords[0]]
            dst.write(
                {
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {
                        "feature_id": feature_id,
                        "feature_type": feature_type,
                        "name": _feature_name(feature_id),
                        "point_count": len(line),
                        "closes_loop": bool(closes_loop),
                        "start_ref_id": first.ref_id,
                        "end_ref_id": last.ref_id,
                        "start_name": first.name,
                        "end_name": last.name,
                    },
                }
            )
    return len(lines)


def export(refs: list[Reference], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    counts: dict[str, int] = {}

    for category in CATEGORIES:
        if category in ("", "label"):
            continue
        layer = f"{category}_points"
        counts[layer] = _write_points_layer(output, layer, [r for r in refs if r.category == category])
    counts["label_points"] = _write_points_layer(output, "label_points", [r for r in refs if r.category == "label"])
    unclassified = [r for r in refs if r.category not in CATEGORIES and r.category != "label"]
    if unclassified:
        counts["unclassified_points"] = _write_points_layer(output, "unclassified_points", unclassified)

    coastlines = get_coastlines(refs)
    rivers = get_river_lines(refs)
    islands = get_island_lines(refs)
    mountains = get_mountain_lines(refs)

    counts["coastlines"] = _write_lines_layer(output, "coastlines", "coastline", coastlines)
    counts["coastline_nodes"] = _write_points_layer(
        output, "coastline_nodes", sorted((r for line in coastlines for r in line), key=lambda r: (r.feature_id, r.sequence_in_feature))
    )
    counts["rivers"] = _write_lines_layer(output, "rivers", "river", rivers)
    counts["river_nodes"] = _write_points_layer(
        output, "river_nodes", sorted((r for line in rivers for r in line), key=lambda r: (r.river_feature_id, r.river_sequence_in_feature))
    )
    counts["island_outlines"] = _write_lines_layer(output, "island_outlines", "island_outline", islands)
    counts["island_outline_nodes"] = _write_points_layer(
        output,
        "island_outline_nodes",
        sorted((r for line in islands for r in line), key=lambda r: (r.island_feature_id, r.island_sequence_in_feature)),
    )
    counts["mountain_ranges"] = _write_lines_layer(output, "mountain_ranges", "mountain_range", mountains)
    counts["mountain_range_nodes"] = _write_points_layer(
        output,
        "mountain_range_nodes",
        sorted((r for line in mountains for r in line), key=lambda r: (r.mountain_feature_id, r.mountain_sequence_in_feature)),
    )

    print(f"wrote {output}")
    for layer, n in counts.items():
        if n:
            print(f"  {layer}: {n}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", nargs="*", type=Path, default=[DEFAULT_INPUT], help="CSV/XLSX file(s) or directories")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    refs = [r for r in load_inputs(args.input) if r.is_plausible()]
    if not refs:
        print("no geographical references loaded")
        return 1
    export(refs, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
