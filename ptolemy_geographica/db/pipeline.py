#!/usr/bin/env python3
"""
Run only what a change actually affects
============================================

The old advice was "run every stage, in order, for any tweak":

    annotate_dataset.py -> topostext/link_matches.py -> topostext/river_mentions.py ->
    topostext/build_labels.py -> db/build_database.py -> db/export_csv_from_db.py ->
    export_geopackage.py / export_defaux_style_json.py

That's only ever actually necessary when the *raw source* changes (a newly
digitized book in the xlsx, a newly pasted topostext chunk) - rare. A
correction (fixing a point's category, a coastline connection, ...) is now
an edit to `point_override`/`section_override`/`connection_override` in
`db/ptolemy.db`, and the only thing that needs to rerun for that is
`db/recompute.py` - no xlsx parsing, no topostext fuzzy matching. See
README.md's "Reading overrides from the database" and "Cutting the
pipeline down to what changed" sections.

This script is the everyday entry point for that fast path:

    python3 db/pipeline.py status    # is a recompute needed? are the exports stale?
    python3 db/pipeline.py run       # recompute if needed, then refresh the exports

For the rare full-source-changed case, run the documented full chain by
hand (`annotate_dataset.py --overrides code`, ..., `db/build_database.py`)
- this script deliberately doesn't try to automate that one, since knowing
*whether* the raw xlsx/topostext source changed is a judgment call about
new data having arrived, not something derivable from the database alone.

Usage
-----
    python3 db/pipeline.py status
    python3 db/pipeline.py run
    python3 db/pipeline.py run --skip-geopackage   # geopandas/shapely not installed
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT_DIR))

import export_defaux_style_json  # noqa: E402
from export_annotated_csv import build_references as build_annotated_csv_references  # noqa: E402
from export_csv_from_db import export as export_csvs  # noqa: E402
from ptolemy_map import write_annotated_csv  # noqa: E402
from recompute import is_stale, recompute  # noqa: E402

DEFAULT_DB = SCRIPT_DIR / "ptolemy.db"
DEFAULT_ANNOTATED_CSV = ROOT_DIR / "data" / "ptolemy_catalogue_annotated.csv"
DEFAULT_DEFAUX_JSON = ROOT_DIR / "ptolemy_geographica_defaux_style.json"
DEFAULT_GEOPACKAGE = ROOT_DIR / "ptolemy_geographica.gpkg"

# topostext/link_matches.py's own extra columns, appended onto the
# annotated CSV beyond write_annotated_csv()'s fixed schema (see that
# script's docstring) - matching is independent of point/section/
# connection overrides (see README.md's "Reading overrides from the
# database" section) and, unlike db/recompute.py, genuinely expensive
# (~50s: a fuzzy distance+name score over every catalogue point against
# every topostext citation) - not worth rerunning on every override edit.
# Carried over from whatever CSV already exists rather than recomputed,
# so a `db/pipeline.py run` doesn't silently drop them.
_TOPOSTEXT_COLUMNS = ("topostext_matched", "topostext_ref", "topostext_name", "topostext_match_score", "river_mentions")


def _merge_topostext_columns(new_csv: Path, old_csv_rows: dict[str, dict]) -> None:
    if not old_csv_rows:
        return
    with new_csv.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or []) + list(_TOPOSTEXT_COLUMNS)
        rows = list(reader)
    for row in rows:
        old = old_csv_rows.get(row["ref_id"], {})
        for col in _TOPOSTEXT_COLUMNS:
            row[col] = old.get(col, "")
    with new_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def status(conn: sqlite3.Connection) -> None:
    if is_stale(conn):
        print("recompute: STALE - an override was edited since the last recompute; run `db/pipeline.py run`")
    else:
        print("recompute: up to date")
    print("(if the raw xlsx or topostext source changed, this tool doesn't cover that - see the module docstring)")


def run(conn: sqlite3.Connection, skip_geopackage: bool) -> None:
    if is_stale(conn):
        stats = recompute(conn)
        print(f"recomputed {stats['points']} points, {stats['line_memberships']} line memberships")
        print(f"categories: {stats['categories']}")
    else:
        print("recompute: already up to date, skipping")

    # Read whatever topostext_matched/.../river_mentions columns the
    # *existing* annotated CSV already carries before overwriting it, so
    # they can be merged back in below rather than silently dropped - this
    # tool never reruns topostext/link_matches.py itself (see
    # _TOPOSTEXT_COLUMNS above).
    old_csv_rows: dict[str, dict] = {}
    if DEFAULT_ANNOTATED_CSV.exists():
        with DEFAULT_ANNOTATED_CSV.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("ref_id"):
                    old_csv_rows[row["ref_id"]] = row

    refs = build_annotated_csv_references(conn)
    write_annotated_csv(refs, DEFAULT_ANNOTATED_CSV)
    _merge_topostext_columns(DEFAULT_ANNOTATED_CSV, old_csv_rows)
    print(f"wrote {len(refs)} references -> {DEFAULT_ANNOTATED_CSV}")

    # topostext/build_labels.py is cheap (no fuzzy matching, just grouping
    # already-resolved rows) and its synthetic label rows would otherwise
    # be silently dropped by write_annotated_csv() above (see that
    # script's own docstring) - restore them every run. river_mentions.py
    # is comparably cheap but depends on topostext_name (only present if
    # link_matches.py has actually been run at some point, via the merge
    # above), so it's re-run here too rather than merged, to reflect this
    # run's own naming_observation column immediately rather than
    # a stale prior run's.
    subprocess.run([sys.executable, str(ROOT_DIR / "topostext" / "river_mentions.py")], check=True)
    subprocess.run([sys.executable, str(ROOT_DIR / "topostext" / "build_labels.py")], check=True)

    export_csvs(DEFAULT_DB, ROOT_DIR / "data")

    data = export_defaux_style_json.build(conn)
    DEFAULT_DEFAUX_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {DEFAULT_DEFAUX_JSON}")

    if not skip_geopackage:
        subprocess.run(
            [sys.executable, str(ROOT_DIR / "export_geopackage.py"), "--input", str(DEFAULT_ANNOTATED_CSV), "--output", str(DEFAULT_GEOPACKAGE)],
            check=True,
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("status", "run"))
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--skip-geopackage", action="store_true", help="skip export_geopackage.py (needs geopandas/shapely)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.db.exists():
        print(f"{args.db} not found - run db/build_database.py first")
        return 1
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    if args.command == "status":
        status(conn)
    else:
        run(conn, args.skip_geopackage)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
