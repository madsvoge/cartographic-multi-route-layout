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
import json
import re
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "topostext"))

sys.path.insert(0, str(SCRIPT_DIR))

import ptolemy_map as pm  # noqa: E402 - the override collections' own live values (see _POINT_OVERRIDE_TYPES etc. below), not just their comments
from recompute import recompute  # noqa: E402 - the one place category/section_type/line_membership get computed, see the point_rows comment below
from section_header_check import (  # noqa: E402
    load_catalogue_headers,
    load_catalogue_print_sheets,
    load_topostext_headers,
    RAW_TOPOSTEXT_FILES,
)

DEFAULT_DB = SCRIPT_DIR / "ptolemy.db"
DEFAULT_CSV = ROOT_DIR / "data" / "ptolemy_catalogue_annotated.csv"
DEFAULT_XLSX = ROOT_DIR / "data" / "ptolemy_catalogue_stueckelberger.xlsx"
PTOLEMY_MAP_PY = ROOT_DIR / "ptolemy_map.py"

# --- extracting the "why" already written in ptolemy_map.py's own source ---
#
# Three real comment shapes coexist in this file, and a first version of
# this extractor (which matched "entry ,(?:\s*#\s*(.*))?" as one regex
# across the whole block) got this wrong: `\s*` before `#` happily crosses
# a newline, so it was capturing the *next* entry's leading comment block
# as if it trailed the *previous* entry, truncated at that comment's own
# first line break. Fixed by walking line by line instead:
#
#   1. A same-line trailing comment ("2.04.03.04",  # Anas (Grenzpunkt...))
#      belongs to that entry alone.
#   2. A comment block sitting directly above an entry, with no blank line
#      between them, explains *that* entry (`_COASTLINE_HARD_BREAKS`'s own
#      style: a paragraph, then the one tuple it justifies).
#   3. A comment block above a whole *run* of otherwise bare entries (the
#      109-section round-17 batch) is a shared rationale - propagated to
#      every consecutive bare entry until a blank line or a new comment
#      block breaks the run.
#
# A block's own preceding intro comment (right above "NAME = {", still
# outside the brace) is folded in too, so a mechanism explained once at
# the top (`_COASTLINE_EXPLICIT_ORDER_OVERRIDES`'s Danube-delta paragraph)
# reaches every entry under it rather than none.

# Trailing separator is `[,:]`, not just `,` - a plain set entry ("x",) and
# a dict entry ("x": value) both need to match here. _POINT_ENTRY_RE already
# needed this for _COASTLINE_EXPLICIT_ORDER_OVERRIDES's "ref_id": (...)
# shape; _SECTION_ENTRY_RE/_PAIR_ENTRY_RE didn't until _ISLAND_LINE_GROUPS/
# _MANUAL_JUNCTION_REF_ID_PAIRS (both dict-valued) needed the same widening
# to have their own reasoning reach the database (see point_override.py's
# and connection_override's `value` column).
_SECTION_ENTRY_RE = re.compile(r'\(\s*"(\d+\.\d+)"\s*,\s*"(\d+)"\s*\)\s*[,:]')
_POINT_ENTRY_RE = re.compile(r'"(\d+\.\d+\.\d+\.\d+)"\s*[,:]')
_PAIR_ENTRY_RE = re.compile(r'\(\s*"(\d+\.\d+\.\d+\.\d+)"\s*,\s*"(\d+\.\d+\.\d+\.\d+)"\s*\)\s*[,:]')

_SECTION_NOTE_SOURCES = [
    "_COASTAL_APPENDIX_SECTIONS",
    "_NONCOASTAL_EXCEPTION_SECTIONS",
    "_ISLAND_APPENDIX_SECTIONS",
    "_MOUNTAIN_APPENDIX_SECTIONS",
    "_ISLAND_LINE_GROUPS",
]
_POINT_NOTE_SOURCES = [
    "_RIVER_POINT_OVERRIDES",
    "_NONCOASTAL_POINT_OVERRIDES",
    "_ISLAND_POINT_OVERRIDES",
    "_MOUNTAIN_POINT_OVERRIDES",
    "_COASTLINE_SKIP_REF_IDS",
    "_RIVER_LINE_SKIP_REF_IDS",
    "_COASTLINE_EXPLICIT_ORDER_OVERRIDES",
]
# The pair-scoped collections' own note sources are declared as part of
# _CONNECTION_OVERRIDE_TYPES further below (it needs the same five names
# anyway, to pull each collection's *value* straight off `pm`, so there's
# no separate list here the way _SECTION_NOTE_SOURCES/_POINT_NOTE_SOURCES
# stand apart from their *_OVERRIDE_TYPES counterparts).
# _MANUAL_JUNCTION_REF_ID_PAIRS is handled separately, in
# build_connection_override_rows() below: its one entry's value is itself
# a multi-line parenthesized string (its own justification prose, not a
# short label with a separate trailing/preceding comment), a shape
# _iter_entries_with_notes' line-by-line walk isn't built for - with
# exactly one entry, not worth generalizing the walker for.


def _extract_block(source: str, name: str) -> str:
    """Return the source text of NAME's own preceding intro comment (if
    directly adjacent, no blank line) plus everything between "NAME = {"/
    "NAME: ... = {" and its matching closing bracket - a naive but
    sufficient brace counter, since these blocks never nest anything but
    the tuples themselves."""
    start = source.find(f"{name} = ")
    if start == -1:
        start = source.find(f"{name}: ")  # a couple are annotated ("...: set[...] = {")
    if start == -1:
        return ""
    open_pos = source.find("{", start)
    if open_pos == -1:
        return ""
    depth = 0
    end = None
    for i in range(open_pos, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        return ""

    # Walk backwards from the "NAME = " line, collecting a contiguous
    # preceding comment block (stopping at the first blank or non-comment
    # line), then prepend it in forward order.
    preceding_lines = source[:start].splitlines()
    intro: list[str] = []
    for line in reversed(preceding_lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            intro.append(line)
        else:
            break
    intro.reverse()

    return "\n".join(intro) + "\n" + source[open_pos:end]


def _iter_entries_with_notes(block: str, entry_re: re.Pattern) -> list[tuple[re.Match, str]]:
    """Walk `block` line by line, pairing each regex match with its note -
    see the module-level comment above for the three shapes handled."""
    results: list[tuple[re.Match, str]] = []
    pending: list[str] = []
    shared: str | None = None
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            pending = []
            shared = None
            continue
        if stripped.startswith("#"):
            pending.append(stripped.lstrip("#").strip())
            continue
        matches = list(entry_re.finditer(line))
        if not matches:
            continue  # the "NAME = {" line itself, a closing "}", etc.
        block_note = " ".join(pending) if pending else None
        for i, m in enumerate(matches):
            is_last = i == len(matches) - 1
            same_line = None
            if is_last:
                hash_pos = line.find("#", m.end())
                if hash_pos != -1:
                    same_line = line[hash_pos + 1 :].strip()
            if i == 0 and block_note:
                shared = block_note  # a fresh comment block establishes (or replaces) the running shared context
            # `shared`, once established, keeps applying to every entry until a
            # blank line resets it - even one with its own extra same-line
            # label (the Danube-delta explicit-order overrides: one shared
            # paragraph, then five entries each *also* carrying its own
            # river-mouth name) - losing the shared context there just
            # because an entry has one more word of its own would mean only
            # the first of the five ever kept the actual explanation.
            if shared and same_line:
                note = f"{shared} [{same_line}]"
            elif shared:
                note = shared
            elif same_line:
                note = same_line
            else:
                note = ""
            results.append((m, note))
        pending = []
    return results


def _notes_by_block(source: str, block_names: list[str], entry_re: re.Pattern, key_fn) -> dict[str, dict]:
    """Walk each of `block_names`'s own source block and collect its
    entries' notes, kept separate *per block* rather than merged into one
    dict - so a point_override/section_override/connection_override row
    can be given the note that actually came from *its own* collection,
    even where the same key happens to also appear (with a different note)
    in a different collection covered by the same walk. `extract_section_
    notes()`/`extract_point_notes()` below merge these per-block dicts
    into one (last-block-wins) for the general-purpose `section.note`/
    `point.revision_notes` catch-all columns; the
    `build_*_override_rows()` functions use the per-block version instead,
    since a row's `note` must trace back to the specific override it
    documents, not whichever collection happened to be walked last."""
    result: dict[str, dict] = {}
    for block_name in block_names:
        block = _extract_block(source, block_name)
        notes = {}
        for m, note in _iter_entries_with_notes(block, entry_re):
            if note:
                notes[key_fn(m)] = note
        result[block_name] = notes
    return result


def extract_section_notes(source: str) -> dict[tuple[str, str], str]:
    merged: dict[tuple[str, str], str] = {}
    per_block = _notes_by_block(source, _SECTION_NOTE_SOURCES, _SECTION_ENTRY_RE, lambda m: (m.group(1), m.group(2)))
    for notes in per_block.values():
        merged.update(notes)
    return merged


def extract_point_notes(source: str) -> dict[str, str]:
    merged: dict[str, str] = {}
    per_block = _notes_by_block(source, _POINT_NOTE_SOURCES, _POINT_ENTRY_RE, lambda m: m.group(1))
    for notes in per_block.values():
        merged.update(notes)
    return merged


# --- override rules themselves, not just their notes ---
#
# Each collection's *value* (which ref_ids it contains, or what value it
# maps a key to) is read straight off the live `ptolemy_map` module
# (imported as `pm` above), not re-parsed out of source text: simpler and
# safer than teaching the regex walker above to also `ast.literal_eval`
# arbitrary values, and immune to shapes it was never built for (see
# _MANUAL_JUNCTION_REF_ID_PAIRS's multi-line string, handled separately
# below). The regex walker's job stays exactly what it's already good at:
# pairing a key with its human-written justification - `_notes_by_block()`
# above supplies that half.

_POINT_OVERRIDE_TYPES = {
    "_ISLAND_POINT_OVERRIDES": "force_island_point",
    "_MOUNTAIN_POINT_OVERRIDES": "force_mountain_point",
    "_RIVER_POINT_OVERRIDES": "force_river_point",
    "_NONCOASTAL_POINT_OVERRIDES": "force_noncoastal_point",
    "_COASTLINE_SKIP_REF_IDS": "coastline_skip",
    "_RIVER_LINE_SKIP_REF_IDS": "river_line_skip",
}
_POINT_OVERRIDE_VALUE_TYPES = {
    "_COASTLINE_EXPLICIT_ORDER_OVERRIDES": "coastline_explicit_order",
}
_SECTION_OVERRIDE_TYPES = {
    "_ISLAND_APPENDIX_SECTIONS": "force_island_section",
    "_NONCOASTAL_EXCEPTION_SECTIONS": "force_noncoastal_section",
    "_MOUNTAIN_APPENDIX_SECTIONS": "force_mountain_section",
    "_COASTAL_APPENDIX_SECTIONS": "force_coastal_section",
}
_SECTION_OVERRIDE_VALUE_TYPES = {
    "_ISLAND_LINE_GROUPS": "island_line_group",
}
_CONNECTION_OVERRIDE_TYPES = {
    "_COASTLINE_HARD_BREAKS": ("coastline", "hard_break"),
    "_RIVER_LINE_NO_MERGE_REF_ID_PAIRS": ("river", "no_merge"),
    "_BOUNDARY_STITCH_REF_ID_PAIRS": ("coastline", "force_stitch"),
    "_NO_CLOSE_LOOP_TRAILS": ("coastline", "no_close_loop"),
    "_FORCE_CLOSE_LOOP_TRAILS": ("coastline", "force_close_loop"),
}


def build_point_override_rows(source: str, valid_ids: set[str]) -> list[dict]:
    membership_notes = _notes_by_block(source, list(_POINT_OVERRIDE_TYPES), _POINT_ENTRY_RE, lambda m: m.group(1))
    value_notes = _notes_by_block(source, list(_POINT_OVERRIDE_VALUE_TYPES), _POINT_ENTRY_RE, lambda m: m.group(1))
    rows = []
    for block_name, override_type in _POINT_OVERRIDE_TYPES.items():
        notes = membership_notes[block_name]
        # sorted(): a plain `set`'s iteration order depends on Python's
        # per-process string hash randomization, not insertion order - left
        # unsorted, re-running this script with no actual data change would
        # still reshuffle every row's `id` and the CSV export's row order,
        # producing a spurious multi-hundred-line git diff each time.
        for point_id in sorted(getattr(pm, block_name)):
            if point_id in valid_ids:
                rows.append({"point_id": point_id, "override_type": override_type, "value": None, "note": notes.get(point_id, "")})
    for block_name, override_type in _POINT_OVERRIDE_VALUE_TYPES.items():
        notes = value_notes[block_name]
        for point_id, value in sorted(getattr(pm, block_name).items()):
            if point_id in valid_ids:
                rows.append(
                    {
                        "point_id": point_id,
                        "override_type": override_type,
                        "value": json.dumps(list(value)),
                        "note": notes.get(point_id, ""),
                    }
                )
    return rows


def build_section_override_rows(source: str, valid_sections: set[str]) -> list[dict]:
    key_fn = lambda m: (m.group(1), m.group(2))  # noqa: E731
    membership_notes = _notes_by_block(source, list(_SECTION_OVERRIDE_TYPES), _SECTION_ENTRY_RE, key_fn)
    value_notes = _notes_by_block(source, list(_SECTION_OVERRIDE_VALUE_TYPES), _SECTION_ENTRY_RE, key_fn)
    rows = []
    for block_name, override_type in _SECTION_OVERRIDE_TYPES.items():
        notes = membership_notes[block_name]
        for book_map, section_num in sorted(getattr(pm, block_name)):
            section_id = f"{book_map}.{section_num}"
            if section_id in valid_sections:
                rows.append(
                    {
                        "section_id": section_id,
                        "override_type": override_type,
                        "value": None,
                        "note": notes.get((book_map, section_num), ""),
                    }
                )
    for block_name, override_type in _SECTION_OVERRIDE_VALUE_TYPES.items():
        notes = value_notes[block_name]
        for (book_map, section_num), value in sorted(getattr(pm, block_name).items()):
            section_id = f"{book_map}.{section_num}"
            if section_id in valid_sections:
                rows.append(
                    {
                        "section_id": section_id,
                        "override_type": override_type,
                        "value": value,
                        "note": notes.get((book_map, section_num), ""),
                    }
                )
    return rows


def build_connection_override_rows(source: str, valid_ids: set[str]) -> list[dict]:
    key_fn = lambda m: (m.group(1), m.group(2))  # noqa: E731
    pair_note_blocks = _notes_by_block(source, list(_CONNECTION_OVERRIDE_TYPES), _PAIR_ENTRY_RE, key_fn)
    rows = []
    for block_name, (feature_kind, relation_type) in _CONNECTION_OVERRIDE_TYPES.items():
        notes = pair_note_blocks[block_name]
        for point_a, point_b in sorted(getattr(pm, block_name)):
            if point_a in valid_ids and point_b in valid_ids:
                rows.append(
                    {
                        "feature_kind": feature_kind,
                        "relation_type": relation_type,
                        "point_a": point_a,
                        "point_b": point_b,
                        "value": None,
                        "note": notes.get((point_a, point_b), ""),
                    }
                )
    # _MANUAL_JUNCTION_REF_ID_PAIRS - see the comment on _PAIR_NOTE_SOURCES
    # above: its dict value *is* its own justification prose, so it doubles
    # as both `value` and `note` here rather than needing a scraped comment.
    for (point_a, point_b), value in sorted(pm._MANUAL_JUNCTION_REF_ID_PAIRS.items()):
        if point_a in valid_ids and point_b in valid_ids:
            rows.append(
                {
                    "feature_kind": "coastline",
                    "relation_type": "manual_junction",
                    "point_a": point_a,
                    "point_b": point_b,
                    "value": value,
                    "note": value,
                }
            )
    return rows


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

    catalogue_headers = load_catalogue_headers(xlsx_path)
    print_sheets = load_catalogue_print_sheets(xlsx_path)
    topos_headers = load_topostext_headers(RAW_TOPOSTEXT_FILES)

    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["category"] != "label" and r["ref_id"]]

    # Sorted by the same numeric ref_id key ptolemy_map.py's own row
    # ordering uses (not a plain string sort - "3.04.16.10" would
    # otherwise land before "3.04.16.2"), rather than trusting whatever
    # physical row order the CSV happens to be in: the "first row seen for
    # this section_id wins" logic below (short_title's fallback to a
    # point's own name, when the section has no catalogue header text of
    # its own) needs a row order that doesn't silently depend on which
    # tool last wrote the CSV - `db/export_annotated_csv.py`'s own
    # database-sourced row order isn't guaranteed to match a from-scratch
    # xlsx pass's, and previously didn't need to.
    rows.sort(key=lambda r: tuple(int(p) if p.isdigit() else p for p in r["ref_id"].split(".")))

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
                "print_sheet": print_sheets.get((map_id, sec_num), ""),
                "short_title": _short_title(desc_cat, row["name"]),
                "description_catalogue": desc_cat,
                "description_topos": desc_topos,
                "note": section_notes.get((map_id, sec_num), ""),
            }

    conn.executemany(
        "INSERT INTO section (section_id, book, map, section_number, print_sheet, short_title, "
        "description_catalogue, description_topos, note) "
        "VALUES (:section_id, :book, :map, :section_number, :print_sheet, :short_title, "
        ":description_catalogue, :description_topos, :note)",
        sections.values(),
    )

    # --- points ---
    # category/extra_categories/naming_observation are deliberately NOT
    # populated here, even though the CSV already carries them - they, and
    # section.section_type and every line_membership row below, are always
    # computed by exactly one code path (db/recompute.py's recompute(),
    # called at the end of this function), never duplicated between a
    # CSV-derived value here and a database-derived one there. Two
    # independent computations of the same classify+build-lines logic
    # would only ever be *coincidentally* in sync, not guaranteed to be -
    # recompute() is the one source of truth for these fields, both here
    # (the bootstrap) and after a routine point_override/section_override/
    # connection_override edit.
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
        "INSERT INTO point (point_id, section_id, sequence_in_section, "
        "name_catalogue, name_topos, modern_location, recension, lon_ptolemy, lat_ptolemy, "
        "match_score, topos_id, revision_notes) "
        "VALUES (:point_id, :section_id, :sequence_in_section, "
        ":name_catalogue, :name_topos, :modern_location, :recension, :lon_ptolemy, :lat_ptolemy, "
        ":match_score, :topos_id, :revision_notes)",
        point_rows,
    )

    # --- point_override / section_override / connection_override: the
    # override RULES themselves, not just their scraped comment text - see
    # the module comment above build_point_override_rows(). From here on,
    # correcting a point/section/connection is an edit to one of these
    # three tables (with a `note` explaining why), not a new entry in one
    # of ptolemy_map.py's 18 Python collections.
    valid_ids = {r["ref_id"] for r in rows}
    valid_sections = set(sections)
    point_override_rows = build_point_override_rows(source, valid_ids)
    section_override_rows = build_section_override_rows(source, valid_sections)
    connection_override_rows = build_connection_override_rows(source, valid_ids)

    conn.executemany(
        "INSERT INTO point_override (point_id, override_type, value, note) "
        "VALUES (:point_id, :override_type, :value, :note)",
        point_override_rows,
    )
    conn.executemany(
        "INSERT INTO section_override (section_id, override_type, value, note) "
        "VALUES (:section_id, :override_type, :value, :note)",
        section_override_rows,
    )
    conn.executemany(
        "INSERT INTO connection_override (feature_kind, relation_type, point_a, point_b, value, note) "
        "VALUES (:feature_kind, :relation_type, :point_a, :point_b, :value, :note)",
        connection_override_rows,
    )

    conn.commit()

    # category/extra_categories/naming_observation, section_type, and
    # line_membership are computed here, by the one code path that ever
    # computes them (see the comment above the point_rows loop).
    recompute_stats = recompute(conn)

    # --- coverage summary ---
    n_sections_with_note = sum(1 for s in sections.values() if s["note"])
    n_points_with_note = sum(1 for p in point_rows if p["revision_notes"])
    n_sections_with_topos_desc = sum(1 for s in sections.values() if s["description_topos"])
    n_point_overrides_with_note = sum(1 for r in point_override_rows if r["note"])
    n_section_overrides_with_note = sum(1 for r in section_override_rows if r["note"])
    n_connection_overrides_with_note = sum(1 for r in connection_override_rows if r["note"])
    print(f"wrote {db_path}")
    print(f"  {len(sections)} sections, {len(point_rows)} points, {recompute_stats['line_memberships']} line memberships")
    print(f"  categories: {recompute_stats['categories']}")
    print(
        f"  {len(point_override_rows)} point overrides ({n_point_overrides_with_note} with a note), "
        f"{len(section_override_rows)} section overrides ({n_section_overrides_with_note} with a note), "
        f"{len(connection_override_rows)} connection overrides ({n_connection_overrides_with_note} with a note)"
    )
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
