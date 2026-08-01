#!/usr/bin/env python3
"""
Export the curated database back to CSV
===========================================

The database (`ptolemy.db`) is the authoritative store from here on (see
README.md's "The curated database" section), but a binary SQLite file
diffs badly in git - this writes plain, git-diffable CSV snapshots of it
on every commit, purely for human-readable history, never read back in as
a source themselves.

Writes six files: sections.csv, points.csv, line_membership.csv,
connection_overrides.csv, point_overrides.csv, section_overrides.csv - the
last two are the git-diffable record of the override *rules* themselves
(see README.md's "The curated database" section): editing one of those
tables and re-running this script turns the correction into a readable
git diff, the same way editing a Python exception list used to.

Usage
-----
    python3 db/export_csv_from_db.py
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DB = SCRIPT_DIR / "ptolemy.db"
DEFAULT_OUTDIR = SCRIPT_DIR.parent / "data"


def _dump_table(conn: sqlite3.Connection, table: str, order_by: str, out_path: Path) -> int:
    cur = conn.execute(f"SELECT * FROM {table} ORDER BY {order_by}")
    columns = [d[0] for d in cur.description]
    rows = cur.fetchall()
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        writer.writerows(rows)
    return len(rows)


def export(db_path: Path, outdir: Path) -> None:
    conn = sqlite3.connect(db_path)
    n_sections = _dump_table(conn, "section", "section_id", outdir / "sections.csv")
    n_points = _dump_table(conn, "point", "point_id", outdir / "points.csv")
    n_membership = _dump_table(conn, "line_membership", "feature_id, sequence_in_feature", outdir / "line_membership.csv")
    n_overrides = _dump_table(conn, "connection_override", "feature_kind, id", outdir / "connection_overrides.csv")
    n_point_overrides = _dump_table(conn, "point_override", "point_id, override_type", outdir / "point_overrides.csv")
    n_section_overrides = _dump_table(conn, "section_override", "section_id, override_type", outdir / "section_overrides.csv")
    conn.close()
    print(f"wrote {outdir}/sections.csv ({n_sections} rows)")
    print(f"wrote {outdir}/points.csv ({n_points} rows)")
    print(f"wrote {outdir}/line_membership.csv ({n_membership} rows)")
    print(f"wrote {outdir}/connection_overrides.csv ({n_overrides} rows)")
    print(f"wrote {outdir}/point_overrides.csv ({n_point_overrides} rows)")
    print(f"wrote {outdir}/section_overrides.csv ({n_section_overrides} rows)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    export(args.db, args.outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
