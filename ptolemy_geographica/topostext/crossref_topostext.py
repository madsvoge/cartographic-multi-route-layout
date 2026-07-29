#!/usr/bin/env python3
"""
Cross-reference parsed topostext.org citations against our annotated
catalogue, matching by *coordinate* (both sources encode the same
Ferro-relative degrees-minutes values) rather than by section position -
robust to topostext folding a paragraph's opening "shared boundary" point
into prose instead of listing it as its own line (see parse_topostext.py).

For each match, flags a naming_observation-vs-topostext-name disagreement:
does our `category` look consistent with what topostext's own phrasing
says the point is ("mouth of the X river" -> river_mouth/river, "island"
-> island, "promontory"/cape wording -> coast, etc)? This is the same kind
of audit signal that found the Corfu/Euboea/Egypt bugs earlier, but from
an independent source instead of guessing from Modern_location.

Usage
-----
    python3 crossref_topostext.py topostext_209.csv \
        --catalogue ../data/ptolemy_catalogue_annotated.csv
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CATALOGUE = SCRIPT_DIR.parent / "data" / "ptolemy_catalogue_annotated.csv"

_MATCH_TOL_DEG = 0.02  # both sources round DMS the same way; a real match should be near-exact

_TYPE_HINTS: list[tuple[re.Pattern, set[str]]] = [
    (re.compile(r"\bmouth of\b|\bestuary\b", re.IGNORECASE), {"river_mouth", "coast", "harbor"}),
    (re.compile(r"\bisland[s]?\b", re.IGNORECASE), {"island"}),
    (re.compile(r"\bpromontory\b|\bcape\b", re.IGNORECASE), {"coast", "mountain"}),
    (re.compile(r"\bharbor\b|\bharbour\b|\bport\b", re.IGNORECASE), {"harbor", "coast"}),
    (re.compile(r"\bbay\b", re.IGNORECASE), {"coast"}),
    (re.compile(r"\bcity\b|\btown\b", re.IGNORECASE), {"city"}),
    (re.compile(r"\bsource[s]?\b|\bquelle\b", re.IGNORECASE), {"river"}),
    (re.compile(r"\blake\b", re.IGNORECASE), {"lake"}),
    (re.compile(r"\bmountain[s]?\b|\bmount\b", re.IGNORECASE), {"mountain"}),
]


def _guess_expected_categories(name_phrase: str) -> set[str] | None:
    for pattern, expected in _TYPE_HINTS:
        if pattern.search(name_phrase):
            return expected
    return None


def load_catalogue(path: Path) -> dict[str, list[dict]]:
    """Index catalogue rows by their ref_id's book component for a fast,
    scoped search (topostext's own book number == our ref_id's book)."""
    by_book: dict[str, list[dict]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not row.get("ref_id") or not row.get("lon_ptolemy"):
                continue
            book = row["ref_id"].split(".")[0]
            by_book[book].append(row)
    return by_book


def find_match(topo_row: dict, candidates: list[dict]) -> dict | None:
    best, best_dist = None, None
    lon, lat = float(topo_row["lon_decimal"]), float(topo_row["lat_decimal"])
    for cand in candidates:
        d = abs(float(cand["lon_ptolemy"]) - lon) + abs(float(cand["lat_ptolemy"]) - lat)
        if d <= _MATCH_TOL_DEG and (best_dist is None or d < best_dist):
            best, best_dist = cand, d
    return best


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("topostext_csv", type=Path)
    parser.add_argument("--catalogue", type=Path, default=DEFAULT_CATALOGUE)
    args = parser.parse_args(argv)

    by_book = load_catalogue(args.catalogue)

    with args.topostext_csv.open(newline="", encoding="utf-8") as fh:
        topo_rows = list(csv.DictReader(fh))

    unmatched: list[dict] = []
    matched = 0
    disagreements: list[tuple[dict, dict, set[str]]] = []
    for topo_row in topo_rows:
        candidates = by_book.get(topo_row["book"], [])
        match = find_match(topo_row, candidates)
        if match is None:
            unmatched.append(topo_row)
            continue
        matched += 1
        expected = _guess_expected_categories(topo_row["name_phrase"])
        if expected is not None and match["category"] not in expected:
            disagreements.append((topo_row, match, expected))

    print(f"{len(topo_rows)} topostext citations, {matched} matched by coordinate, {len(unmatched)} unmatched")
    print()
    if disagreements:
        print(f"=== {len(disagreements)} possible category disagreements ===")
        for topo_row, match, expected in disagreements:
            print(
                f"§{topo_row['book']}.{topo_row['map']}.{topo_row['section']} "
                f"topostext=\"{topo_row['name_phrase']}\" ({topo_row['lon_dms']} . {topo_row['lat_dms']}) "
                f"-> ref_id={match['ref_id']} name=\"{match['name']}\" our_category={match['category']!r} "
                f"expected~{sorted(expected)}"
            )
        print()
    if unmatched:
        print(f"=== {len(unmatched)} unmatched topostext citations (no catalogue point within {_MATCH_TOL_DEG} deg) ===")
        for topo_row in unmatched:
            print(
                f"§{topo_row['book']}.{topo_row['map']}.{topo_row['section']}.{topo_row['position']} "
                f"\"{topo_row['name_phrase']}\" ({topo_row['lon_dms']} . {topo_row['lat_dms']})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
