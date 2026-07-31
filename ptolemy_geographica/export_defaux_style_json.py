#!/usr/bin/env python3
"""
Export the annotated catalogue as a Defaux-style structured JSON
==================================================================

Olivier Defaux's Xi/OmegaStructure.json files (published alongside his 2017
monograph on Iberia, see README.md's "Section type & multi-category tags"
section) group Ptolemy's catalogue as book -> chapters -> sections ->
sec_part, tag each locality with one or more categories (a locality can be
both e.g. "river mouth" and "boundary" at once), and tag each *section*
with its own narrative type (type_sec: "coast section", "inland", "island",
"mountain", ...).

This script writes the same shape from our own annotated catalogue, using
the `category`/`extra_categories`/`section_type` columns `ptolemy_map.py`'s
classifier now computes (see the module docstring there). It is a close
structural analogue, not a byte-for-byte replica - three real differences,
kept visible rather than papered over:

  - Names are the catalogue's own German locality names, not the original
    Greek toponyms (this project never digitized the Greek text itself).
  - Coordinates are plain decimal degrees, not Ptolemy's own degree-plus-
    unit-fraction notation (L/gamma/iota-beta/...) Defaux's files use.
  - There is no `people` field and no "text string"/"title"/"area
    presentation"/"borders description" sec_parts - our own catalogue only
    ever carries locality rows with coordinates, never the connecting prose
    (see ptolemy_map.py's own note on this next to `section_type`).

Usage
-----
    python3 export_defaux_style_json.py                   # -> ptolemy_geographica.json
    python3 export_defaux_style_json.py --output out.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ptolemy_map import DEFAULT_INPUT, Reference, load_inputs

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SCRIPT_DIR / "ptolemy_geographica_defaux_style.json"


def _categories(r: Reference) -> list[str]:
    cats = [r.category] if r.category else []
    cats.extend(c for c in r.extra_categories.split(";") if c)
    return cats


def _locality_part(r: Reference) -> dict:
    parts = r.ref_id.split(".")
    return {
        "ID": r.ref_id,
        "type": "locality",
        "category": _categories(r),
        "name": r.name,
        "modern_location": r.modern_location,
        "coord": {
            "long": round(r.lon_ptolemy, 4),
            "lat": round(r.lat_ptolemy, 4),
        },
    }


def build(refs: list[Reference]) -> list[dict]:
    # book_ID -> chap_ID -> sec_ID -> [Reference], in catalogue order -
    # dict insertion order does the grouping/ordering work, same principle
    # as annotate_dataset.py's own groupby-in-catalogue-order.
    books: dict[str, dict[str, dict[str, list[Reference]]]] = {}
    for r in refs:
        parts = r.ref_id.split(".")
        if len(parts) < 3:
            continue  # not a "book.map.section.point" catalogue row (e.g. a label row)
        book_id, chap_id, sec_num = parts[0], f"{parts[0]}.{parts[1]}", parts[2]
        sec_id = f"{chap_id}.{sec_num}"
        books.setdefault(book_id, {}).setdefault(chap_id, {}).setdefault(sec_id, []).append(r)

    result = []
    for book_id, chapters in books.items():
        chapter_list = []
        for chap_id, sections in chapters.items():
            section_list = []
            for sec_id, section_refs in sections.items():
                section_list.append(
                    {
                        "sec_ID": sec_id,
                        "type_sec": section_refs[0].section_type,
                        "sec_part": [_locality_part(r) for r in section_refs],
                    }
                )
            chapter_list.append({"chap_ID": chap_id, "section": section_list})
        result.append({"book_ID": book_id, "chapters": chapter_list})
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", nargs="*", type=Path, default=[DEFAULT_INPUT], help="CSV/XLSX file(s) or directories")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    refs = [r for r in load_inputs(args.input) if r.is_plausible() and r.category != "label"]
    if not refs:
        print("no geographical references loaded")
        return 1
    data = build(refs)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    n_localities = sum(
        len(sec["sec_part"]) for book in data for chap in book["chapters"] for sec in chap["section"]
    )
    n_sections = sum(len(chap["section"]) for book in data for chap in book["chapters"])
    print(f"wrote {args.output}: {len(data)} book(s), {n_sections} section(s), {n_localities} localities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
