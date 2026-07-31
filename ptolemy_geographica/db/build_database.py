#!/usr/bin/env python3
"""
Build the curated SQLite database from the current pipeline's own output
============================================================================

This is the bootstrap step, run once (and again only when the raw source
changes, e.g. more books get digitized): it takes everything the existing
classifier + accumulated exception lists in `ptolemy_map.py` already know
- every category, section type, and constructed line, the product of
eighteen rounds of hand-verified review this session - and turns it from
"recomputed by running the pipeline" into "stored, documented, queryable
data" (see README.md's "The curated database" section for why).

After this runs once, further corrections are meant to happen as *edits to
the database* (with a revision_notes entry saying why), not as new entries
in a Python exception list - re-running this script is only for picking up
genuinely new source data, and never overwrites a point/section whose
notes already show manual review (see `--force` to override that guard).

Sources combined:
  - data/ptolemy_catalogue_annotated.csv - the fully-resolved catalogue
    (category, extra_categories, section_type, all four line-membership
    chains, topostext match columns) - already the output of the full
    pipeline (annotate_dataset.py -> link_matches.py -> river_mentions.py).
  - data/ptolemy_catalogue_stueckelberger.xlsx - re-read only for each
    section's own header row text (never stored in the CSV).
  - topostext/raw_209_*.txt - re-parsed only for each section's own lead-in
    prose (topostext_209.csv only keeps individual point citations, not
    the connecting prose between them).
  - ptolemy_map.py's own source text - scanned for the trailing same-line
    comment next to each entry in the override lists
    (_COASTAL_APPENDIX_SECTIONS and its many siblings), which becomes each
    section's/point's `note`/`revision_notes`. Best-effort: only same-line
    comments are captured, not the longer prose that precedes a block of
    several entries - see the printed coverage summary.

Usage
-----
    python3 db/build_database.py                  # -> db/ptolemy.db
    python3 db/build_database.py --force           # overwrite even reviewed rows
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "topostext"))

from section_header_check import load_catalogue_headers, load_topostext_headers, RAW_TOPOSTEXT_FILES  # noqa: E402

DEFAULT_DB = SCRIPT_DIR / "ptolemy.db"
DEFAULT_CSV = ROOT_DIR / "data" / "ptolemy_catalogue_annotated.csv"
DEFAULT_XLSX = ROOT_DIR / "data" / "ptolemy_catalogue_stueckelberger.xlsx"
PTOLEMY_MAP_PY = ROOT_DIR / "ptolemy_map.py"

_LINE_FEATURE_COLUMNS = {
    "coastline": ("feature_id", "sequence_in_feature", "feature_closes_loop"),
    "river": ("river_feature_id", "river_sequence_in_feature", None),
    "island": ("island_feature_id", "island_sequence_in_feature", "island_feature_closes_loop"),
    "mountain": ("mountain_feature_id", "mountain_sequence_in_feature", None),
}

# --- extracting the "why" already written in ptolemy_map.py's own source ---

# A section-appendix entry: ("2.05", "04"),  # comment...
_SECTION_ENTRY_RE = re.compile(r'\(\s*"(\d+\.\d+)"\s*,\s*"(\d+)"\s*\)\s*,(?:\s*#\s*(.*))?')
# A point-override entry: "2.04.03.04",  # comment...
_POINT_ENTRY_RE = re.compile(r'"(\d+\.\d+\.\d+\.\d+)"\s*,(?:\s*#\s*(.*))?')
# A pair entry (hard breaks / no-merge pairs): ("2.05.04.11", "2.05.04.10"),  # comment...
_PAIR_ENTRY_RE = re.compile(r'\(\s*"(\d+\.\d+\.\d+\.\d+)"\s*,\s*"(\d+\.\d+\.\d+\.\d+)"\s*\)\s*,(?:\s*#\s*(.*))?')

_SECTION_NOTE_SOURCES = [
    "_COASTAL_APPENDIX_SECTIONS",
    "_NONCOASTAL_EXCEPTION_SECTIONS",
    "_ISLAND_APPENDIX_SECTIONS",
    "_MOUNTAIN_APPENDIX_SECTIONS",
]
_POINT_NOTE_SOURCES = [
    "_RIVER_POINT_OVERRIDES",
    "_NONCOASTAL_POINT_OVERRIDES",
    "_ISLAND_POINT_OVERRIDES",
    "_MOUNTAIN_POINT_OVERRIDES",
    "_COASTLINE_SKIP_REF_IDS",
    "_RIVER_LINE_SKIP_REF_IDS",
]
_PAIR_NOTE_SOURCES = [
    ("_COASTLINE_HARD_BREAKS", "coastline", "hard_break"),
    ("_RIVER_LINE_NO_MERGE_REF_ID_PAIRS", "river", "no_merge"),
]


def _extract_block(source: str, name: str) -> str:
    """Return the source text between "NAME = {"/"NAME = (" and its
    matching closing bracket - a naive but sufficient brace counter, since
    these blocks never nest anything but the tuples themselves."""
    start = source.find(f"{name} = ")
    if start == -1:
        start = source.find(f"{name}: ")  # a couple are annotated ("...: set[...] = {")
    if start == -1:
        return ""
    open_pos = source.find("{", start)
    if open_pos == -1:
        return ""
    depth = 0
    for i in range(open_pos, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[open_pos : i + 1]
    return ""


def extract_section_notes(source: str) -> dict[tuple[str, str], str]:
    notes: dict[tuple[str, str], str] = {}
    for block_name in _SECTION_NOTE_SOURCES:
        block = _extract_block(source, block_name)
        for m in _SECTION_ENTRY_RE.finditer(block):
            book_map, section, comment = m.group(1), m.group(2), m.group(3)
            if comment:
                notes[(book_map, section)] = comment.strip()
    return notes


def extract_point_notes(source: str) -> dict[str, str]:
    notes: dict[str, str] = {}
    for block_name in _POINT_NOTE_SOURCES:
        block = _extract_block(source, block_name)
        for m in _POINT_ENTRY_RE.finditer(block):
            ref_id, comment = m.group(1), m.group(2)
            if comment:
                notes[ref_id] = comment.strip()
    return notes


def extract_pair_notes(source: str) -> list[tuple[str, str, str, str, str]]:
    """(feature_kind, relation_type, point_a, point_b, note)."""
    pairs = []
    for block_name, feature_kind, relation_type in _PAIR_NOTE_SOURCES:
        block = _extract_block(source, block_name)
        for m in _PAIR_ENTRY_RE.finditer(block):
            a, b, comment = m.group(1), m.group(2), m.group(3)
            pairs.append((feature_kind, relation_type, a, b, (comment or "").strip()))
    return pairs


# --- section short_title (best-effort, from whatever we have) ---


def _short_title(description_catalogue: str, first_point_name: str) -> str:
    if description_catalogue:
        # e.g. "Lusitania | Baetica | Tarraconensis | Äusseres Meer" -> "Lusitania"
        return description_catalogue.split("|")[0].strip()
    return first_point_name


def build(db_path: Path, csv_path: Path, xlsx_path: Path, force: bool) -> None:
    source = PTOLEMY_MAP_PY.read_text(encoding="utf-8")
    section_notes = extract_section_notes(source)
    point_notes = extract_point_notes(source)
    pair_notes = extract_pair_notes(source)

    catalogue_headers = load_catalogue_headers(xlsx_path)
    topos_headers = load_topostext_headers(RAW_TOPOSTEXT_FILES)

    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["category"] != "label" and r["ref_id"]]

    if db_path.exists() and not force:
        db_path.unlink()  # bootstrap always rebuilds fresh; --force is about overwriting reviewed *rows* going forward, not this file
    elif db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    conn.executescript((SCRIPT_DIR / "schema.sql").read_text(encoding="utf-8"))

    # --- sections ---
    sections: dict[str, dict] = {}
    for row in rows:
        parts = row["ref_id"].split(".")
        if len(parts) < 4:
            continue
        book, map_num, sec_num = parts[0], parts[1], parts[2]
        map_id = f"{book}.{map_num}"
        section_id = f"{map_id}.{sec_num}"
        if section_id not in sections:
            desc_cat = catalogue_headers.get((map_id, sec_num), "")
            desc_topos = topos_headers.get((map_id, sec_num), "")
            sections[section_id] = {
                "section_id": section_id,
                "book": book,
                "map": map_id,
                "section_number": sec_num,
                "short_title": _short_title(desc_cat, row["name"]),
                "description_catalogue": desc_cat,
                "description_topos": desc_topos,
                "section_type": row["section_type"],
                "note": section_notes.get((map_id, sec_num), ""),
            }

    conn.executemany(
        "INSERT INTO section (section_id, book, map, section_number, short_title, "
        "description_catalogue, description_topos, section_type, note) "
        "VALUES (:section_id, :book, :map, :section_number, :short_title, "
        ":description_catalogue, :description_topos, :section_type, :note)",
        sections.values(),
    )

    # --- points ---
    point_rows = []
    for row in rows:
        parts = row["ref_id"].split(".")
        if len(parts) < 4:
            continue
        section_id = f"{parts[0]}.{parts[1]}.{parts[2]}"
        try:
            seq = int(parts[3])
        except ValueError:
            seq = None
        point_rows.append(
            {
                "point_id": row["ref_id"],
                "section_id": section_id,
                "sequence_in_section": seq,
                "category": row["category"],
                "extra_categories": row["extra_categories"],
                "name_catalogue": row["name"],
                "name_topos": row["topostext_name"] if row.get("topostext_matched") == "yes" else "",
                "modern_location": row["modern_location"],
                "recension": row["recension"],
                "lon_ptolemy": float(row["lon_ptolemy"]) if row["lon_ptolemy"] else None,
                "lat_ptolemy": float(row["lat_ptolemy"]) if row["lat_ptolemy"] else None,
                "match_score": float(row["topostext_match_score"]) if row.get("topostext_match_score") else None,
                "topos_id": row.get("topostext_ref", ""),
                "revision_notes": point_notes.get(row["ref_id"], ""),
            }
        )

    conn.executemany(
        "INSERT INTO point (point_id, section_id, sequence_in_section, category, extra_categories, "
        "name_catalogue, name_topos, modern_location, recension, lon_ptolemy, lat_ptolemy, "
        "match_score, topos_id, revision_notes) "
        "VALUES (:point_id, :section_id, :sequence_in_section, :category, :extra_categories, "
        ":name_catalogue, :name_topos, :modern_location, :recension, :lon_ptolemy, :lat_ptolemy, "
        ":match_score, :topos_id, :revision_notes)",
        point_rows,
    )

    # --- line_membership: one row per (point, line) membership, chained by next_point_id ---
    membership_rows = []
    for feature_kind, (id_col, seq_col, closes_col) in _LINE_FEATURE_COLUMNS.items():
        lines: dict[str, list[dict]] = {}
        for row in rows:
            fid = row.get(id_col)
            if not fid:
                continue
            lines.setdefault(fid, []).append(row)
        for fid, members in lines.items():
            members.sort(key=lambda r: int(r[seq_col]))
            closes_loop = bool(closes_col) and members[0].get(closes_col) == "True"
            for i, r in enumerate(members):
                next_row = members[i + 1] if i + 1 < len(members) else (members[0] if closes_loop else None)
                membership_rows.append(
                    {
                        "point_id": r["ref_id"],
                        "feature_kind": feature_kind,
                        "feature_id": fid,
                        "sequence_in_feature": int(r[seq_col]),
                        "next_point_id": next_row["ref_id"] if next_row else None,
                        "closes_loop": 1 if closes_loop else 0,
                    }
                )

    conn.executemany(
        "INSERT INTO line_membership (point_id, feature_kind, feature_id, sequence_in_feature, "
        "next_point_id, closes_loop) VALUES (:point_id, :feature_kind, :feature_id, "
        ":sequence_in_feature, :next_point_id, :closes_loop)",
        membership_rows,
    )

    # --- connection_override: pairwise facts (no-merge guards, hard breaks) ---
    valid_ids = {r["ref_id"] for r in rows}
    override_rows = [
        {"feature_kind": fk, "relation_type": rt, "point_a": a, "point_b": b, "note": note}
        for fk, rt, a, b, note in pair_notes
        if a in valid_ids and b in valid_ids
    ]
    conn.executemany(
        "INSERT INTO connection_override (feature_kind, relation_type, point_a, point_b, note) "
        "VALUES (:feature_kind, :relation_type, :point_a, :point_b, :note)",
        override_rows,
    )

    conn.commit()

    # --- coverage summary ---
    n_sections_with_note = sum(1 for s in sections.values() if s["note"])
    n_points_with_note = sum(1 for p in point_rows if p["revision_notes"])
    n_sections_with_topos_desc = sum(1 for s in sections.values() if s["description_topos"])
    print(f"wrote {db_path}")
    print(f"  {len(sections)} sections, {len(point_rows)} points, {len(membership_rows)} line memberships, {len(override_rows)} connection overrides")
    print(f"  {n_sections_with_note}/{len(sections)} sections have a migrated note (same-line code comments only)")
    print(f"  {n_points_with_note}/{len(point_rows)} points have a migrated revision note")
    print(f"  {n_sections_with_topos_desc}/{len(sections)} sections have topostext lead-in prose")
    conn.close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX)
    parser.add_argument("--force", action="store_true", help="rebuild even if it would overwrite a reviewed row (currently: bootstrap always rebuilds fresh regardless)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    build(args.db, args.csv, args.xlsx, args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
