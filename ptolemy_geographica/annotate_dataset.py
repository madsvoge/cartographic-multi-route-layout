#!/usr/bin/env python3
"""
Resolve the raw catalogue into a fully-annotated, self-contained dataset
==========================================================================

`ptolemy_map.py`'s xlsx loader has to *reason* about the raw catalogue at
runtime: is this point coastal, and if so, which points does it connect to,
in what order, does its line close into a loop? That reasoning (regex
matches, a graph reconstruction, distance thresholds, curated exception
lists for cases the text alone can't resolve) lives in code because nobody
had gone through and settled every one of those questions as data.

This script runs that reasoning once, over the whole catalogue, and writes
the answers into `data/ptolemy_catalogue_annotated.csv`:

  - `category` - already available from the xlsx loader.
  - `naming_observation` - *why* that category was picked (which keyword or
    manual exception matched), so a reviewer can audit or correct a call
    without reading the classifier's source.
  - `feature_id` / `sequence_in_feature` / `feature_closes_loop` - which
    drawn coastline (if any) this point belongs to, and where in the draw
    order.
  - `river_feature_id` / `river_sequence_in_feature` - the same, but for
    the river line (if any) this point belongs to. Separate columns
    because a river mouth sits on both a coastline and a river line at
    once, and each is its own line with its own draw order.
  - `island_feature_id` / `island_sequence_in_feature` /
    `island_feature_closes_loop` - the same, but for an island's own
    coastal outline (if any) - see _ISLAND_LINE_GROUPS.

Once generated, drawing the map from this file is exactly what a
15th-century cartographer working from the Geographica's text did: place
each point (its coordinates + category), and connect the dots along each
feature in sequence. See build_coastlines_from_features() and
build_river_lines_from_features() in ptolemy_map.py - no graph, no
distance thresholds, no stitching needed against this file.

Overrides (which point/section gets force-classified, which trails
force-stitch, ...) are read from `db/ptolemy.db`'s `point_override`/
`section_override`/`connection_override` tables by default - that's what
a correction actually edits now (see README.md's "The curated database"
section). Pass `--overrides code` to fall back to ptolemy_map.py's own
frozen Python constants instead (only meaningful before `db/ptolemy.db`
exists at all, i.e. the one-time bootstrap - see db/build_database.py).

Usage
-----
    python3 annotate_dataset.py
    python3 annotate_dataset.py --input data/ptolemy_catalogue_stueckelberger.xlsx --output data/ptolemy_catalogue_annotated.csv
    python3 annotate_dataset.py --overrides code   # bootstrap only, before db/ptolemy.db exists
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from pathlib import Path

from overrides import load_overrides_from_code, load_overrides_from_db
from ptolemy_map import (
    assign_coastline_features,
    assign_island_features,
    assign_mountain_features,
    assign_river_features,
    load_xlsx,
    write_annotated_csv,
)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE = SCRIPT_DIR / "data" / "ptolemy_catalogue_stueckelberger.xlsx"
DEFAULT_OUTPUT = SCRIPT_DIR / "data" / "ptolemy_catalogue_annotated.csv"
DEFAULT_OVERRIDES_DB = SCRIPT_DIR / "db" / "ptolemy.db"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_SOURCE, help="Raw xlsx catalogue to resolve")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Annotated CSV to write")
    parser.add_argument("--overrides-db", type=Path, default=DEFAULT_OVERRIDES_DB, help="Database to read overrides from (--overrides db)")
    parser.add_argument(
        "--overrides",
        choices=("db", "code"),
        default="db",
        help="Read override rules from db/ptolemy.db (default) or from ptolemy_map.py's own frozen Python constants",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.overrides == "db":
        if not args.overrides_db.exists():
            print(f"{args.overrides_db} not found - run db/build_database.py first, or pass --overrides code")
            return 1
        conn = sqlite3.connect(args.overrides_db)
        overrides = load_overrides_from_db(conn)
        conn.close()
    else:
        overrides = load_overrides_from_code()

    refs = load_xlsx(args.input, overrides)
    plausible = [r for r in refs if r.is_plausible()]
    dropped = len(refs) - len(plausible)
    if dropped:
        print(f"dropped {dropped} reference(s) with out-of-range coordinates")

    assign_coastline_features(plausible, overrides)
    assign_river_features(plausible, overrides)
    assign_island_features(plausible, overrides)
    assign_mountain_features(plausible)
    write_annotated_csv(plausible, args.output)

    categories = Counter(r.category for r in plausible)
    features = {r.feature_id for r in plausible if r.feature_id}
    in_feature = sum(1 for r in plausible if r.feature_id)
    river_features = {r.river_feature_id for r in plausible if r.river_feature_id}
    in_river_feature = sum(1 for r in plausible if r.river_feature_id)
    island_features = {r.island_feature_id for r in plausible if r.island_feature_id}
    in_island_feature = sum(1 for r in plausible if r.island_feature_id)
    mountain_features = {r.mountain_feature_id for r in plausible if r.mountain_feature_id}
    in_mountain_feature = sum(1 for r in plausible if r.mountain_feature_id)
    print(f"wrote {len(plausible)} references -> {args.output}")
    print(f"categories: {dict(categories)}")
    print(f"{len(features)} coastline features, {in_feature} points assigned to one")
    print(f"{len(river_features)} river lines, {in_river_feature} points assigned to one")
    print(f"{len(island_features)} island lines, {in_island_feature} points assigned to one")
    print(f"{len(mountain_features)} mountain-range lines, {in_mountain_feature} points assigned to one")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
