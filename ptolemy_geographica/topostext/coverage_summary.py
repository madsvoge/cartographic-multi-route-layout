#!/usr/bin/env python3
"""
Two-way coverage summary between topostext_209.csv and our catalogue, scoped
to the book.map range topostext chunks have actually covered so far.

Forward (topostext -> catalogue): reuses crossref_topostext.py's own
coordinate-match/tolerance logic - "how many topostext citations have no
catalogue point nearby".

Reverse (catalogue -> topostext): the new direction - restricted to catalogue
rows whose book.map falls inside the range topostext has actually pasted
(book 2 maps 02-16 fully; book 3 maps 01-15 of 01-17; book 4 maps 01-08,
i.e. all of it - topostext's own "§4.9.N" labels are a source quirk for the
tail of map 8, not a real map 9; book 5 maps 01-06 of 01-20) - "how many of
OUR points in that range have no topostext citation anywhere nearby".
"""

from __future__ import annotations

import csv
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CATALOGUE = SCRIPT_DIR.parent / "data" / "ptolemy_catalogue_annotated.csv"
TOPOSTEXT = SCRIPT_DIR / "topostext_209.csv"

_MATCH_TOL_DEG = 0.02

# book -> set of covered map numbers, based on what topostext_209.csv
# actually contains (see module docstring re: book 4's "map 9" quirk).
_COVERED_MAPS = {
    "2": set(range(2, 17)),
    "3": set(range(1, 16)),
    "4": set(range(1, 9)),
    "5": set(range(1, 7)),
}


def load_catalogue(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [row for row in csv.DictReader(fh) if row.get("ref_id") and row.get("lon_ptolemy")]


def load_topostext(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    cat_rows = load_catalogue(CATALOGUE)
    topo_rows = load_topostext(TOPOSTEXT)

    cat_by_book: dict[str, list[dict]] = {}
    for row in cat_rows:
        cat_by_book.setdefault(row["ref_id"].split(".")[0], []).append(row)

    topo_by_book: dict[str, list[dict]] = {}
    for row in topo_rows:
        topo_by_book.setdefault(row["book"], []).append(row)

    # --- forward: topostext -> catalogue --------------------------------
    fwd_unmatched = []
    for topo_row in topo_rows:
        lon, lat = float(topo_row["lon_decimal"]), float(topo_row["lat_decimal"])
        candidates = cat_by_book.get(topo_row["book"], [])
        hit = any(
            abs(float(c["lon_ptolemy"]) - lon) + abs(float(c["lat_ptolemy"]) - lat) <= _MATCH_TOL_DEG
            for c in candidates
        )
        if not hit:
            fwd_unmatched.append(topo_row)

    # --- reverse: catalogue (in covered range) -> topostext -------------
    scoped_cat = []
    for row in cat_rows:
        parts = row["ref_id"].split(".")
        book, map_ = parts[0], int(parts[1])
        if map_ in _COVERED_MAPS.get(book, set()):
            scoped_cat.append(row)

    rev_unmatched = []
    for cat_row in scoped_cat:
        book = cat_row["ref_id"].split(".")[0]
        lon, lat = float(cat_row["lon_ptolemy"]), float(cat_row["lat_ptolemy"])
        candidates = topo_by_book.get(book, [])
        hit = any(
            abs(float(t["lon_decimal"]) - lon) + abs(float(t["lat_decimal"]) - lat) <= _MATCH_TOL_DEG
            for t in candidates
        )
        if not hit:
            rev_unmatched.append(cat_row)

    print(f"TOPOSTEXT -> CATALOGUE")
    print(f"  {len(topo_rows)} topostext citations parsed so far")
    print(f"  {len(topo_rows) - len(fwd_unmatched)} matched a catalogue point by coordinate")
    print(f"  {len(fwd_unmatched)} unmatched (no catalogue point within {_MATCH_TOL_DEG} deg)")
    print()
    print(f"CATALOGUE -> TOPOSTEXT (scoped to covered book.map range)")
    print(f"  {len(scoped_cat)} catalogue points fall inside the range topostext has covered so far")
    print(f"  {len(scoped_cat) - len(rev_unmatched)} matched a topostext citation by coordinate")
    print(f"  {len(rev_unmatched)} unmatched (no topostext citation within {_MATCH_TOL_DEG} deg)")
    print()
    print("  breakdown by book:")
    by_book_totals: dict[str, list[int]] = {}
    for row in scoped_cat:
        book = row["ref_id"].split(".")[0]
        by_book_totals.setdefault(book, [0, 0])[0] += 1
    for row in rev_unmatched:
        book = row["ref_id"].split(".")[0]
        by_book_totals.setdefault(book, [0, 0])[1] += 1
    for book in sorted(by_book_totals, key=int):
        total, missing = by_book_totals[book]
        print(f"    book {book}: {total} scoped points, {missing} unmatched ({total - missing} matched)")

    out_path = SCRIPT_DIR / "reverse_unmatched.csv"
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["ref_id", "name", "category", "lon_ptolemy", "lat_ptolemy"])
        writer.writeheader()
        for row in rev_unmatched:
            writer.writerow({k: row.get(k, "") for k in writer.fieldnames})
    print()
    print(f"  (full list of the {len(rev_unmatched)} unmatched catalogue points written to {out_path.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
