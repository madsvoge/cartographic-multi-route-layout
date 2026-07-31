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
islands and mountain ranges connect same-named points elsewhere), a single
*combined* layer holding both the line itself and its own ordered vertices
- one GeoPackage feature table with a generic geometry column
(`MultiLineString` for the line row, `Point` for each node row), rather
than a separate line layer plus a separate "nodes" point layer requiring a
GIS-side join to relate them:

    coastlines, rivers, island_outlines, mountain_ranges

A `record_type` property (`"line"` or `"node"`) tells the two kinds of
row apart within the layer; `feature_id` is shared between a line row and
its own node rows, so grouping/filtering by `feature_id` in a GIS tool
recovers "this one line plus its N vertices" without any join. A node
row also carries its own `sequence_in_feature` (draw order along the
line) and every attribute the corresponding `..._points` layer above has
for that point (category, Modern_location, Ptolemy coordinates, ...) -
it's the same point, just pre-filtered and pre-ordered to the subset
that's actually part of a line.

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
import sqlite3
from pathlib import Path

import fiona

from overrides import OverrideBundle, load_overrides_from_db
from ptolemy_map import (
    CATEGORIES,
    DEFAULT_INPUT,
    Reference,
    get_coastlines,
    get_island_lines,
    get_manual_junctions,
    get_mountain_lines,
    get_river_lines,
    load_inputs,
)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "ptolemy_geographica.gpkg"
DEFAULT_OVERRIDES_DB = SCRIPT_DIR / "db" / "ptolemy.db"
CRS = "EPSG:4326"

_POINT_PROPERTIES = {
    "ref_id": "str",
    "name": "str",
    "category": "str",
    "extra_categories": "str",
    "section_type": "str",
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

# One combined layer per line-building feature type: a "line" row (the
# whole constructed line, as a MultiLineString) and its own "node" rows
# (each vertex, as a Point, in draw order) share this same property
# schema - record_type tells them apart, and the columns each kind
# doesn't use are left blank rather than needing two separate schemas.
_COMBINED_PROPERTIES = {
    "record_type": "str",  # "line" or "node"
    "feature_id": "str",  # shared key between a line row and its own node rows
    "feature_type": "str",
    "name": "str",
    # line-only:
    "point_count": "int",
    "closes_loop": "bool",
    "start_ref_id": "str",
    "end_ref_id": "str",
    "start_name": "str",
    "end_name": "str",
    # node-only - the underlying point's own attributes, plus its position
    # along this particular line:
    "ref_id": "str",
    "sequence_in_feature": "int",
    "category": "str",
    "extra_categories": "str",
    "section_type": "str",
    "book": "str",
    "tabula": "str",
    "modern_location": "str",
    "recension": "str",
    "lon_ptolemy": "float",
    "lat_ptolemy": "float",
}


def _point_record(r: Reference) -> dict:
    return {
        "ref_id": r.ref_id,
        "name": r.name,
        "category": r.category,
        "extra_categories": r.extra_categories,
        "section_type": r.section_type,
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


# (feature_id attr, sequence attr, closes-loop attr or None) per feature
# type - the four different Reference attribute names build_coastlines()/
# build_river_lines()/build_island_lines()/build_mountain_lines() each
# write their own line membership into.
_FEATURE_ATTRS: dict[str, tuple[str, str, str | None]] = {
    "coastline": ("feature_id", "sequence_in_feature", "feature_closes_loop"),
    "river": ("river_feature_id", "river_sequence_in_feature", None),
    "island_outline": ("island_feature_id", "island_sequence_in_feature", "island_feature_closes_loop"),
    "mountain_range": ("mountain_feature_id", "mountain_sequence_in_feature", None),
}


def _write_combined_layer(gpkg: Path, layer: str, feature_type: str, lines: list[list[Reference]]) -> int:
    """One layer per feature type holding both the constructed line (as a
    MultiLineString, `record_type="line"`) and its own ordered vertices
    (as Points, `record_type="node"`) - see the module docstring."""
    lines = [line for line in lines if len(line) >= 2]
    if not lines:
        return 0
    feature_id_attr, sequence_attr, closes_loop_attr = _FEATURE_ATTRS[feature_type]
    schema = {"geometry": "Unknown", "properties": _COMBINED_PROPERTIES}
    written = 0
    with fiona.open(gpkg, "w", driver="GPKG", crs=CRS, schema=schema, layer=layer) as dst:
        for line in lines:
            first, last = line[0], line[-1]
            feature_id = getattr(first, feature_id_attr)
            closes_loop = bool(getattr(first, closes_loop_attr)) if closes_loop_attr else False
            coords = [(r.lon_modern, r.lat_modern) for r in line]
            if closes_loop:
                coords = coords + [coords[0]]
            line_properties = dict.fromkeys(_COMBINED_PROPERTIES)
            line_properties.update(
                {
                    "record_type": "line",
                    "feature_id": feature_id,
                    "feature_type": feature_type,
                    "name": _feature_name(feature_id),
                    "point_count": len(line),
                    "closes_loop": closes_loop,
                    "start_ref_id": first.ref_id,
                    "end_ref_id": last.ref_id,
                    "start_name": first.name,
                    "end_name": last.name,
                }
            )
            dst.write({"geometry": {"type": "MultiLineString", "coordinates": [coords]}, "properties": line_properties})
            written += 1
            for r in line:
                node_properties = dict.fromkeys(_COMBINED_PROPERTIES)
                node_properties.update(
                    {
                        "record_type": "node",
                        "feature_id": feature_id,
                        "feature_type": feature_type,
                        "name": r.name,
                        "ref_id": r.ref_id,
                        "sequence_in_feature": getattr(r, sequence_attr),
                        "category": r.category,
                        "extra_categories": r.extra_categories,
                        "section_type": r.section_type,
                        "book": r.book,
                        "tabula": r.tabula,
                        "modern_location": r.modern_location,
                        "recension": r.recension,
                        "lon_ptolemy": r.lon_ptolemy,
                        "lat_ptolemy": r.lat_ptolemy,
                    }
                )
                dst.write({"geometry": {"type": "Point", "coordinates": (r.lon_modern, r.lat_modern)}, "properties": node_properties})
                written += 1
    return written


_BRIDGE_PROPERTIES = {
    "ref_id_a": "str",
    "name_a": "str",
    "ref_id_b": "str",
    "name_b": "str",
    "note": "str",
}


def _write_manual_bridges_layer(gpkg: Path, layer: str, refs: list[Reference], overrides: OverrideBundle | None) -> int:
    """A point where two or more separately catalogued coastal
    descriptions meet, but that get_coastlines()'s trail-stitching can't
    fold into a single line (a manual_junction connection_override row,
    see db/schema.sql) - exported as its own short 2-point LineString per
    pair, so the connection is directly checkable in QGIS even though it
    never shows up as part of the `coastlines` layer's own line geometry."""
    junctions = get_manual_junctions(refs, overrides)
    if not junctions:
        return 0
    schema = {"geometry": "LineString", "properties": _BRIDGE_PROPERTIES}
    with fiona.open(gpkg, "w", driver="GPKG", crs=CRS, schema=schema, layer=layer) as dst:
        for ref_a, ref_b, note in junctions:
            dst.write(
                {
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [(ref_a.lon_modern, ref_a.lat_modern), (ref_b.lon_modern, ref_b.lat_modern)],
                    },
                    "properties": {
                        "ref_id_a": ref_a.ref_id,
                        "name_a": ref_a.name,
                        "ref_id_b": ref_b.ref_id,
                        "name_b": ref_b.name,
                        "note": note,
                    },
                }
            )
    return len(junctions)


def export(refs: list[Reference], output: Path, overrides: OverrideBundle | None = None) -> None:
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

    counts["coastlines"] = _write_combined_layer(output, "coastlines", "coastline", get_coastlines(refs))
    counts["rivers"] = _write_combined_layer(output, "rivers", "river", get_river_lines(refs))
    counts["island_outlines"] = _write_combined_layer(output, "island_outlines", "island_outline", get_island_lines(refs))
    counts["mountain_ranges"] = _write_combined_layer(output, "mountain_ranges", "mountain_range", get_mountain_lines(refs))
    counts["manual_bridges"] = _write_manual_bridges_layer(output, "manual_bridges", refs, overrides)

    print(f"wrote {output}")
    for layer, n in counts.items():
        if n:
            print(f"  {layer}: {n}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", nargs="*", type=Path, default=[DEFAULT_INPUT], help="CSV/XLSX file(s) or directories")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--overrides-db",
        type=Path,
        default=DEFAULT_OVERRIDES_DB,
        help="db/ptolemy.db to read the manual_bridges layer's connections from (falls back to ptolemy_map.py's own constants if missing)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    refs = [r for r in load_inputs(args.input) if r.is_plausible()]
    if not refs:
        print("no geographical references loaded")
        return 1
    overrides = None
    if args.overrides_db.exists():
        conn = sqlite3.connect(args.overrides_db)
        overrides = load_overrides_from_db(conn)
        conn.close()
    export(refs, args.output, overrides)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
