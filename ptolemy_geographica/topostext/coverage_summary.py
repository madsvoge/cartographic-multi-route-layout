#!/usr/bin/env python3
"""
Two-way coverage summary between topostext_209.csv and our catalogue, scoped
to the book.map range topostext chunks have actually covered so far.

Reads the match columns link_matches.py already wrote (topostext_matched
on the catalogue, catalogue_matched on topostext_209.csv) rather than
recomputing its own - single source of truth for what counts as "matched"
(see link_matches.py's docstring for the fuzzy distance+name score behind
it). Run link_matches.py first; this is just a summary/report layer on
top of its output.

Forward (topostext -> catalogue): how many topostext citations have no
catalogue point matched.

Reverse (catalogue -> topostext): restricted to catalogue rows whose
book.map falls inside the range topostext has actually pasted (book 2
maps 02-16 fully; book 3 maps 01-15 of 01-17; book 4 maps 01-08, i.e. all
of it - topostext's own "§4.9.N" labels are a source quirk for the tail
of map 8, not a real map 9; book 5 maps 01-06 of 01-20) - how many of OUR
points in that range have no topostext citation matched.
"""

from __future__ import annotations

import csv
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CATALOGUE = SCRIPT_DIR.parent / "data" / "ptolemy_catalogue_annotated.csv"
TOPOSTEXT = SCRIPT_DIR / "topostext_209.csv"

# book -> set of covered map numbers, based on what topostext_209.csv
# actually contains (see link_matches.py's docstring re: book 4's "map 9"
# quirk).
_COVERED_MAPS = {
    "2": set(range(2, 17)),
    "3": set(range(1, 16)),
    "4": set(range(1, 9)),
    "5": set(range(1, 20)),
}


def load_catalogue(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [
            row
            for row in csv.DictReader(fh)
            if row.get("ref_id") and row.get("lon_ptolemy") and row["ref_id"].split(".")[0].isdigit()
        ]


def load_topostext(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    cat_rows = load_catalogue(CATALOGUE)
    topo_rows = load_topostext(TOPOSTEXT)

    if not topo_rows or "catalogue_matched" not in topo_rows[0]:
        raise SystemExit("run link_matches.py first - no catalogue_matched column found in topostext_209.csv")
    if cat_rows and "topostext_matched" not in cat_rows[0]:
        raise SystemExit("run link_matches.py first - no topostext_matched column found in the catalogue")

    fwd_unmatched = [r for r in topo_rows if r["catalogue_matched"] != "yes"]

    scoped_cat = [
        r
        for r in cat_rows
        if int(r["ref_id"].split(".")[1]) in _COVERED_MAPS.get(r["ref_id"].split(".")[0], set())
    ]
    rev_unmatched = [r for r in scoped_cat if r["topostext_matched"] != "yes"]

    print("TOPOSTEXT -> CATALOGUE")
    print(f"  {len(topo_rows)} topostext citations parsed so far")
    print(f"  {len(topo_rows) - len(fwd_unmatched)} matched a catalogue point")
    print(f"  {len(fwd_unmatched)} unmatched")
    print()
    print("CATALOGUE -> TOPOSTEXT (scoped to covered book.map range)")
    print(f"  {len(scoped_cat)} catalogue points fall inside the range topostext has covered so far")
    print(f"  {len(scoped_cat) - len(rev_unmatched)} matched a topostext citation")
    print(f"  {len(rev_unmatched)} unmatched")
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

    rev_path = SCRIPT_DIR / "reverse_unmatched.csv"
    with rev_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["ref_id", "name", "category", "lon_ptolemy", "lat_ptolemy"])
        writer.writeheader()
        for row in rev_unmatched:
            writer.writerow({k: row.get(k, "") for k in writer.fieldnames})

    fwd_path = SCRIPT_DIR / "forward_unmatched.csv"
    fwd_fields = ["book", "map", "section", "position", "name_phrase", "lon_dms", "lat_dms", "lon_decimal", "lat_decimal"]
    with fwd_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fwd_fields)
        writer.writeheader()
        for row in fwd_unmatched:
            writer.writerow({k: row.get(k, "") for k in fwd_fields})

    print()
    print(f"  (full list of the {len(rev_unmatched)} unmatched catalogue points written to {rev_path.name})")
    print(f"  (full list of the {len(fwd_unmatched)} unmatched topostext citations written to {fwd_path.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
