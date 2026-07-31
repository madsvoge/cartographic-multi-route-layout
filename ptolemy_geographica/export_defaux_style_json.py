#!/usr/bin/env python3
"""
Export the curated database as a Defaux-style structured JSON
==================================================================

Olivier Defaux's Xi/OmegaStructure.json files (published alongside his 2017
monograph on Iberia, see README.md's "Section type & multi-category tags"
section) group Ptolemy's catalogue as book -> chapters -> sections ->
sec_part, tag each locality with one or more categories (a locality can be
both e.g. "river mouth" and "boundary" at once), and tag each *section*
with its own narrative type (type_sec: "coast section", "inland", "island",
"mountain", ...).

This script writes the same shape from `db/ptolemy.db` (see README.md's
"The curated database" section) - the database, not the annotated CSV, is
this project's authoritative source from here on. It is a close structural
analogue, not a byte-for-byte replica of Defaux's own files - three real
differences, kept visible rather than papered over:

  - Names are the catalogue's own German locality names, not the original
    Greek toponyms (this project never digitized the Greek text itself).
  - Coordinates are plain decimal degrees, not Ptolemy's own degree-plus-
    unit-fraction notation (L/gamma/iota-beta/...) Defaux's files use.
  - There is no `people` field and no "text string"/"title"/"area
    presentation"/"borders description" sec_parts - this catalogue only
    ever carries locality rows with coordinates, never the connecting prose.

It also carries two things Defaux's own files don't: `note`/
`revision_notes` (why a section's or point's classification needed manual
review, migrated from this project's own working notes - see
`db/build_database.py`), and each locality's `next_point_id` per line it
belongs to (see `line_membership` in the schema) - the explicit connection
data this project's own map-drawing needs that Defaux's files have no
equivalent of, since his aren't used to draw constructed lines at all.

Usage
-----
    python3 export_defaux_style_json.py                    # -> ptolemy_geographica_defaux_style.json
    python3 export_defaux_style_json.py --db db/ptolemy.db --output out.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_DB = SCRIPT_DIR / "db" / "ptolemy.db"
DEFAULT_OUTPUT = SCRIPT_DIR / "ptolemy_geographica_defaux_style.json"


def _categories(category: str, extra_categories: str) -> list[str]:
    cats = [category] if category else []
    cats.extend(c for c in (extra_categories or "").split(";") if c)
    return cats


def build(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row

    memberships: dict[str, list[dict]] = {}
    for row in conn.execute(
        "SELECT point_id, feature_kind, feature_id, sequence_in_feature, next_point_id, closes_loop FROM line_membership"
    ):
        memberships.setdefault(row["point_id"], []).append(
            {
                "feature_kind": row["feature_kind"],
                "feature_id": row["feature_id"],
                "sequence_in_feature": row["sequence_in_feature"],
                "next_point_id": row["next_point_id"],
                "closes_loop": bool(row["closes_loop"]),
            }
        )

    points_by_section: dict[str, list[sqlite3.Row]] = {}
    for row in conn.execute("SELECT * FROM point ORDER BY section_id, sequence_in_section"):
        points_by_section.setdefault(row["section_id"], []).append(row)

    # book_ID -> chap_ID -> [section rows], in catalogue order.
    books: dict[str, dict[str, list[sqlite3.Row]]] = {}
    for row in conn.execute("SELECT * FROM section ORDER BY section_id"):
        books.setdefault(row["book"], {}).setdefault(row["map"], []).append(row)

    result = []
    for book_id, chapters in books.items():
        chapter_list = []
        for chap_id, section_rows in chapters.items():
            section_list = []
            for sec in section_rows:
                sec_parts = []
                for p in points_by_section.get(sec["section_id"], []):
                    sec_parts.append(
                        {
                            "ID": p["point_id"],
                            "type": "locality",
                            "category": _categories(p["category"], p["extra_categories"]),
                            "name": p["name_catalogue"],
                            "modern_location": p["modern_location"],
                            "coord": {
                                "long": round(p["lon_ptolemy"], 4) if p["lon_ptolemy"] is not None else None,
                                "lat": round(p["lat_ptolemy"], 4) if p["lat_ptolemy"] is not None else None,
                            },
                            "name_topos": p["name_topos"],
                            "match_score": p["match_score"],
                            "revision_notes": p["revision_notes"],
                            "line_memberships": memberships.get(p["point_id"], []),
                        }
                    )
                section_list.append(
                    {
                        "sec_ID": sec["section_id"],
                        "type_sec": sec["section_type"],
                        "short_title": sec["short_title"],
                        "description_catalogue": sec["description_catalogue"],
                        "description_topos": sec["description_topos"],
                        "note": sec["note"],
                        "sec_part": sec_parts,
                    }
                )
            chapter_list.append({"chap_ID": chap_id, "section": section_list})
        result.append({"book_ID": book_id, "chapters": chapter_list})
    return result


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
    data = build(conn)
    conn.close()
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    n_localities = sum(len(sec["sec_part"]) for book in data for chap in book["chapters"] for sec in chap["section"])
    n_sections = sum(len(chap["section"]) for book in data for chap in book["chapters"])
    print(f"wrote {args.output}: {len(data)} book(s), {n_sections} section(s), {n_localities} localities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
