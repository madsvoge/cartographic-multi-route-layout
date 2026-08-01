#!/usr/bin/env python3
"""
Export the database as an annotated CSV, for the map renderers
====================================================================

`ptolemy_map.py`'s own interactive HTML map and `static_map.py`'s PNG
renderer both read `data/ptolemy_catalogue_annotated.csv` as a plain file,
with no database awareness - rewriting them to read `db/ptolemy.db`
directly was out of scope for the override-migration work (see README.md's
"Reading overrides from the database" section). Instead, this script
inverts the direction: `db/ptolemy.db` is upstream now, and this is a pure
`SELECT`-and-pivot back into exactly the shape `ptolemy_map.write_annotated_
csv()`/`load_annotated_csv()` already round-trip - the renderers keep
working completely unchanged, reading a CSV whose *content* now originates
from the database instead of a from-scratch xlsx pass.

Label rows (`category == "label"`, `topostext/build_labels.py`'s synthetic
province/island-group/mountain-range text labels) are never stored in the
database (see README.md - they don't reach the Defaux JSON export either)
and so aren't written here either. Run `topostext/build_labels.py` on this
script's output afterward if you want them back in the CSV for the map
renderers, the same as the documented full-refresh order.

Usage
-----
    python3 db/export_annotated_csv.py                # -> data/ptolemy_catalogue_annotated.csv
    python3 db/export_annotated_csv.py --output out.csv
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT_DIR))

from ptolemy_map import _CONTINENT_NAMES, Reference, write_annotated_csv  # noqa: E402

DEFAULT_DB = SCRIPT_DIR / "ptolemy.db"
DEFAULT_OUTPUT = ROOT_DIR / "data" / "ptolemy_catalogue_annotated.csv"

_FEATURE_ATTRS = {
    "coastline": ("feature_id", "sequence_in_feature", "feature_closes_loop"),
    "river": ("river_feature_id", "river_sequence_in_feature", None),
    "island": ("island_feature_id", "island_sequence_in_feature", "island_feature_closes_loop"),
    "mountain": ("mountain_feature_id", "mountain_sequence_in_feature", None),
}


def build_references(conn: sqlite3.Connection) -> list[Reference]:
    conn.row_factory = sqlite3.Row
    sections = {row["section_id"]: row for row in conn.execute("SELECT * FROM section")}

    memberships: dict[str, dict[str, sqlite3.Row]] = {}
    for row in conn.execute("SELECT * FROM line_membership"):
        memberships.setdefault(row["point_id"], {})[row["feature_kind"]] = row

    def ref_id_sort_key(row: sqlite3.Row) -> tuple:
        # A plain `ORDER BY point_id` sorts lexicographically ("3.04.16.10"
        # before "3.04.16.2"), not numerically - matches the numeric sort
        # key ptolemy_map.py's own build_coastlines()/load_xlsx() row
        # ordering already uses, so this export's row order matches a
        # from-scratch xlsx pass exactly, not just its data.
        return tuple(int(p) if p.isdigit() else p for p in row["point_id"].split("."))

    refs = []
    for p in sorted(conn.execute("SELECT * FROM point"), key=ref_id_sort_key):
        section = sections.get(p["section_id"])
        print_sheet = (section["print_sheet"] if section else "") or ""
        continent = _CONTINENT_NAMES.get(print_sheet[:2], print_sheet[:2])
        m = memberships.get(p["point_id"], {})

        ref = Reference(
            name=p["name_catalogue"] or "",
            book=continent,
            tabula=print_sheet or "?",
            lon_ptolemy=p["lon_ptolemy"],
            lat_ptolemy=p["lat_ptolemy"],
            source="db",
            modern_location=p["modern_location"] or "",
            recension=p["recension"] or "",
            category=p["category"] or "",
            extra_categories=p["extra_categories"] or "",
            section_type=(section["section_type"] if section else "") or "",
            ref_id=p["point_id"],
            naming_observation=p["naming_observation"] or "",
        )
        for feature_kind, (id_attr, seq_attr, closes_attr) in _FEATURE_ATTRS.items():
            row = m.get(feature_kind)
            if row is None:
                continue
            setattr(ref, id_attr, row["feature_id"])
            setattr(ref, seq_attr, row["sequence_in_feature"])
            if closes_attr:
                setattr(ref, closes_attr, bool(row["closes_loop"]))
        refs.append(ref)
    return refs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.db.exists():
        print(f"{args.db} not found - run db/build_database.py first")
        return 1
    conn = sqlite3.connect(args.db)
    refs = build_references(conn)
    conn.close()
    write_annotated_csv(refs, args.output)
    print(f"wrote {len(refs)} references -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
