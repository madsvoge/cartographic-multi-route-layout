#!/usr/bin/env python3
"""
How well would category-from-topostext agree with category-from-catalogue?
=============================================================================

`crossref_topostext.py` asks a narrow question: for a given catalogue
point, is its category *consistent* with topostext's wording (a set of
acceptable categories, deliberately generous - a coastal city is allowed
to read as either `city` or `coast`)? This script asks a blunter,
independent question instead: if you classified *purely from topostext's
own English phrasing*, with no access to the catalogue's category, its
German name, or any of this project's hand-tuned exception lists, how
often would that single best guess land on the same category the
catalogue/keyword pipeline (`annotate_dataset.py`) produced?

This is not a better classifier - it is deliberately cruder than
`_classify_locality` (one ordered keyword list, first match wins, no
section-header context, no location-reference guards, no manually
verified exception sets) - but it is a genuinely *independent* second
opinion, built from a different language and a different set of clues
(a citation's own narrated role: "harbor", "island", "mouth of") than
the catalogue side ever sees (a section's header word, a German course/
feature suffix). Comparing the two, category by category, shows where
the two sources agree strongly (high confidence either way) and where
they don't (worth a closer, manual look - not automatically "topostext
is right", since this script has no location-reference/shared-name/
mountain-ends-at-the-shore reasoning at all, the same false-positive
classes `crossref_topostext.py`'s review worked through by hand).

Usage
-----
    python3 category_check.py
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CATALOGUE = SCRIPT_DIR.parent / "data" / "ptolemy_catalogue_annotated.csv"

# Ordered, first match wins - unlike _TYPE_HINTS's "set of acceptable
# categories" (crossref_topostext.py), this produces one single best
# guess per phrase, so two independent classifications can be compared
# category-for-category instead of just checked for membership.
# "island" goes first: a phrase naming both an island and its own city
# ("Chios city", short for the fuller "island of Chios, with a city of
# the same name") should read as `island` here, the same deliberate
# choice the catalogue side makes for these - if it instead read `city`,
# every one of those shared-name cases would show up as a disagreement
# that isn't really one.
_CATEGORY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bisland[s]?\b", re.IGNORECASE), "island"),
    (re.compile(r"\bmouth of\b|\briver outlet\b|\bestuary\b", re.IGNORECASE), "river_mouth"),
    (re.compile(r"\bharbor\b|\bharbour\b|\bport\b", re.IGNORECASE), "harbor"),
    (re.compile(r"\bpromontory\b|\bcape\b|\bheadland\b", re.IGNORECASE), "coast"),
    (re.compile(r"\bbay\b|\bgulf\b", re.IGNORECASE), "coast"),
    (re.compile(r"\blake\b", re.IGNORECASE), "lake"),
    (re.compile(r"\bsource[s]?\b|\bspring[s]?\b", re.IGNORECASE), "river"),
    (re.compile(r"\bmountain[s]?\b|\bmount\b", re.IGNORECASE), "mountain"),
    (re.compile(r"\bcity\b|\btown\b|\bvillage\b|\bkome\b", re.IGNORECASE), "city"),
]


def topostext_category(phrase: str) -> str | None:
    for pattern, category in _CATEGORY_PATTERNS:
        if pattern.search(phrase):
            return category
    return None


def load_matched_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [row for row in csv.DictReader(fh) if row.get("topostext_matched") == "yes"]


def main() -> int:
    rows = load_matched_rows(DEFAULT_CATALOGUE)

    classified = [(row, topostext_category(row.get("topostext_name") or "")) for row in rows]
    with_guess = [(row, guess) for row, guess in classified if guess is not None]
    no_guess = len(classified) - len(with_guess)

    agree = sum(1 for row, guess in with_guess if row["category"] == guess)
    total = len(with_guess)

    print(f"{len(rows)} catalogue points matched to a topostext citation")
    print(f"{no_guess} of those have no recognizable category keyword in their topostext phrase (no guess possible)")
    print(f"{total} points get an independent topostext-only category guess")
    print(f"{agree} of {total} agree with the catalogue's own category ({agree / total * 100:.1f}%)")
    print()

    # Per catalogue category: of the points the catalogue calls X, how
    # many does topostext's own wording agree are X (when it ventures a
    # guess at all)?
    print("=== Agreement by catalogue category (catalogue's own view) ===")
    by_cat_category: dict[str, list[bool]] = {}
    by_cat_no_guess: Counter[str] = Counter()
    for row, guess in classified:
        cat = row["category"]
        if guess is None:
            by_cat_no_guess[cat] += 1
            continue
        by_cat_category.setdefault(cat, []).append(cat == guess)
    for cat in sorted(by_cat_category, key=lambda c: -len(by_cat_category[c])):
        results = by_cat_category[cat]
        n_agree = sum(results)
        n = len(results)
        skipped = by_cat_no_guess.get(cat, 0)
        print(f"  {cat:12s} {n_agree:4d}/{n:4d} agree ({n_agree / n * 100:5.1f}%)  [{skipped} with no topostext keyword to compare]")
    print()

    # Per topostext category: of the points topostext's own wording
    # implies are X, how many does the catalogue also call X?
    print("=== Agreement by topostext-implied category (topostext's own view) ===")
    by_topos_category: dict[str, list[bool]] = {}
    for row, guess in with_guess:
        by_topos_category.setdefault(guess, []).append(row["category"] == guess)
    for guess in sorted(by_topos_category, key=lambda c: -len(by_topos_category[c])):
        results = by_topos_category[guess]
        n_agree = sum(results)
        n = len(results)
        print(f"  {guess:12s} {n_agree:4d}/{n:4d} agree ({n_agree / n * 100:5.1f}%)")
    print()

    # Full confusion matrix - catalogue category (rows) x topostext-implied
    # category (columns), for the points where topostext ventures a guess.
    all_cats = sorted({row["category"] for row, _ in with_guess} | {guess for _, guess in with_guess})
    confusion: dict[str, Counter[str]] = {cat: Counter() for cat in all_cats}
    for row, guess in with_guess:
        confusion[row["category"]][guess] += 1

    print("=== Confusion matrix: catalogue category (row) vs topostext-implied category (column) ===")
    header = "catalogue\\topos".ljust(16) + "".join(c[:8].rjust(9) for c in all_cats)
    print(header)
    for cat in all_cats:
        line = cat.ljust(16) + "".join(str(confusion[cat].get(c, 0)).rjust(9) for c in all_cats)
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
