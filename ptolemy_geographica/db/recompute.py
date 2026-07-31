#!/usr/bin/env python3
"""
Recompute category/section_type/line_membership from the database alone
============================================================================

The fast path for a correction: after editing a row in `point_override`/
`section_override`/`connection_override` (see README.md's "The curated
database" section), this is the only thing that needs to rerun - not
`annotate_dataset.py` (which re-reads the raw xlsx), not
`topostext/link_matches.py` or `topostext/river_mentions.py` (topostext
matching doesn't depend on overrides at all - see README.md's "Reading
overrides from the database" section for the one documented exception).

It reads `point`/`section` (already-resolved names, coordinates, and
header text - no xlsx or topostext file access at all) plus the three
override tables, rebuilds the same in-memory `Reference` objects
`ptolemy_map.load_xlsx()` would produce from the raw xlsx, and re-runs the
*same, unmodified* `_classify_locality()` and `assign_*_features()`
functions against them - writing the results (`point.category`/
`extra_categories`, `section.section_type`, `line_membership`) straight
back to the database. No CSV round-trip, no rebuild-from-scratch.

Usage
-----
    python3 db/recompute.py                # -> db/ptolemy.db, updated in place
    python3 db/recompute.py --status        # just report whether a recompute is needed
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT_DIR))

from overrides import load_overrides_from_db  # noqa: E402
from ptolemy_map import (  # noqa: E402
    _BOUNDARY_NAME_RE,
    _CONTINENT_NAMES,
    _COASTAL_HDR_RE,
    _classify_locality,
    Reference,
    assign_coastline_features,
    assign_island_features,
    assign_mountain_features,
    assign_river_features,
)

DEFAULT_DB = SCRIPT_DIR / "ptolemy.db"

_LINE_FEATURE_COLUMNS = {
    "coastline": ("feature_id", "sequence_in_feature", "feature_closes_loop"),
    "river": ("river_feature_id", "river_sequence_in_feature", None),
    "island": ("island_feature_id", "island_sequence_in_feature", "island_feature_closes_loop"),
    "mountain": ("mountain_feature_id", "mountain_sequence_in_feature", None),
}


def _input_signature(conn: sqlite3.Connection) -> str:
    """A cheap fingerprint of everything a recompute actually depends on:
    the override_epoch counter (bumped by trigger on any override-table
    write - see db/schema.sql) plus a hash over the base catalogue content
    (name/coordinates/section header text) that only changes when
    `db/build_database.py` re-imports from a genuinely new source. Two
    inputs, not one: an override edit alone must be enough to mark this
    stage stale, but so must new source data, and neither should require
    re-hashing the other."""
    epoch = conn.execute("SELECT epoch FROM override_epoch WHERE id = 1").fetchone()[0]
    h = hashlib.sha256()
    for row in conn.execute(
        "SELECT point_id, name_catalogue, lon_ptolemy, lat_ptolemy FROM point ORDER BY point_id"
    ):
        h.update("|".join(str(v) for v in row).encode("utf-8"))
    for row in conn.execute(
        "SELECT section_id, print_sheet, description_catalogue FROM section ORDER BY section_id"
    ):
        h.update("|".join(str(v) for v in row).encode("utf-8"))
    return f"{epoch}:{h.hexdigest()}"


def is_stale(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT input_signature FROM pipeline_stage WHERE stage = 'recompute'").fetchone()
    if row is None:
        return True
    return row[0] != _input_signature(conn)


def _build_references(conn: sqlite3.Connection, overrides) -> list[Reference]:
    """The database-sourced equivalent of ptolemy_map.load_xlsx() - same
    per-section force-flag resolution and per-point _classify_locality()
    call, just reading already-resolved `point`/`section` rows instead of
    re-parsing the xlsx. Grouped by `section_id` (book.map.section, the
    same key point_override/section_override/connection_override entries
    are already keyed by), not by the xlsx's own tabula-based row runs -
    the two happen to agree everywhere this catalogue's data actually
    needs them to (see the "Reading overrides from the database" section
    of README.md)."""
    sections = {row["section_id"]: row for row in conn.execute("SELECT * FROM section")}
    points_by_section: dict[str, list[sqlite3.Row]] = {}
    for row in conn.execute("SELECT * FROM point ORDER BY section_id, sequence_in_section"):
        points_by_section.setdefault(row["section_id"], []).append(row)

    refs: list[Reference] = []
    for section_id, section in sections.items():
        points = points_by_section.get(section_id, [])
        if not points:
            continue

        print_sheet = section["print_sheet"] or ""
        continent = _CONTINENT_NAMES.get(print_sheet[:2], print_sheet[:2])
        section_is_coastal = bool(_COASTAL_HDR_RE.search(section["description_catalogue"] or ""))
        book_map_section = (section["map"], section["section_number"])
        force_island = book_map_section in overrides.island_appendix_sections
        section_force_noncoastal = book_map_section in overrides.noncoastal_exception_sections
        force_mountain = book_map_section in overrides.mountain_appendix_sections
        force_coastal = book_map_section in overrides.coastal_appendix_sections

        if force_island:
            section_type = "island"
        elif force_mountain:
            section_type = "mountain"
        elif (section_is_coastal or force_coastal) and not section_force_noncoastal:
            section_type = "coast section"
        else:
            section_type = "inland"

        for p in points:
            name = p["name_catalogue"] or ""
            point_id = p["point_id"]
            category, observation = _classify_locality(
                name,
                section_is_coastal,
                force_island=force_island,
                force_island_point=point_id in overrides.island_point_overrides,
                force_noncoastal=section_force_noncoastal or point_id in overrides.noncoastal_point_overrides,
                force_mountain=force_mountain,
                force_mountain_point=point_id in overrides.mountain_point_overrides,
                force_coastal=force_coastal,
                force_river_point=point_id in overrides.river_point_overrides,
            )
            extra_categories = "boundary" if _BOUNDARY_NAME_RE.search(name) else ""
            refs.append(
                Reference(
                    name=name,
                    book=continent,
                    tabula=print_sheet or "?",
                    lon_ptolemy=p["lon_ptolemy"],
                    lat_ptolemy=p["lat_ptolemy"],
                    source="db",
                    modern_location=p["modern_location"] or "",
                    recension=p["recension"] or "",
                    category=category,
                    extra_categories=extra_categories,
                    section_type=section_type,
                    naming_observation=observation,
                    ref_id=point_id,
                )
            )
    return refs


def recompute(conn: sqlite3.Connection) -> dict:
    conn.row_factory = sqlite3.Row
    overrides = load_overrides_from_db(conn)
    refs = _build_references(conn, overrides)

    assign_coastline_features(refs, overrides)
    assign_river_features(refs, overrides)
    assign_island_features(refs, overrides)
    assign_mountain_features(refs)

    conn.executemany(
        "UPDATE point SET category = ?, extra_categories = ?, naming_observation = ? WHERE point_id = ?",
        [(r.category, r.extra_categories, r.naming_observation, r.ref_id) for r in refs],
    )
    section_types = {}
    for r in refs:
        section_id = ".".join(r.ref_id.split(".")[:3])
        section_types.setdefault(section_id, r.section_type)
    conn.executemany(
        "UPDATE section SET section_type = ? WHERE section_id = ?",
        [(st, sid) for sid, st in section_types.items()],
    )

    conn.execute("DELETE FROM line_membership")
    membership_rows = []
    for feature_kind, (id_attr, seq_attr, closes_attr) in _LINE_FEATURE_COLUMNS.items():
        lines: dict[str, list[Reference]] = {}
        for r in refs:
            fid = getattr(r, id_attr)
            if not fid:
                continue
            lines.setdefault(fid, []).append(r)
        for fid, members in lines.items():
            members.sort(key=lambda r: getattr(r, seq_attr))
            closes_loop = bool(closes_attr) and getattr(members[0], closes_attr)
            for i, r in enumerate(members):
                next_r = members[i + 1] if i + 1 < len(members) else (members[0] if closes_loop else None)
                membership_rows.append(
                    (r.ref_id, feature_kind, fid, getattr(r, seq_attr), next_r.ref_id if next_r else None, 1 if closes_loop else 0)
                )
    conn.executemany(
        "INSERT INTO line_membership (point_id, feature_kind, feature_id, sequence_in_feature, next_point_id, closes_loop) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        membership_rows,
    )

    signature = _input_signature(conn)
    conn.execute(
        "INSERT INTO pipeline_stage (stage, input_signature, ran_at) VALUES ('recompute', ?, ?) "
        "ON CONFLICT(stage) DO UPDATE SET input_signature = excluded.input_signature, ran_at = excluded.ran_at",
        (signature, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()

    categories: dict[str, int] = {}
    for r in refs:
        categories[r.category] = categories.get(r.category, 0) + 1
    return {
        "points": len(refs),
        "sections": len(section_types),
        "line_memberships": len(membership_rows),
        "categories": categories,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--status", action="store_true", help="report staleness only, don't recompute")
    parser.add_argument("--force", action="store_true", help="recompute even if already up to date")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.db.exists():
        print(f"{args.db} not found - run db/build_database.py first")
        return 1
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    stale = is_stale(conn)
    if args.status:
        print("stale - recompute needed" if stale else "up to date")
        conn.close()
        return 0

    if not stale and not args.force:
        print("up to date, nothing to do (pass --force to recompute anyway)")
        conn.close()
        return 0

    stats = recompute(conn)
    print(f"recomputed {stats['points']} points across {stats['sections']} sections, {stats['line_memberships']} line memberships")
    print(f"categories: {stats['categories']}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
