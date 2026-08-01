#!/usr/bin/env python3
"""
How much does a section's own header text predict its points' category?
==========================================================================

Three questions this answers, all at *section* granularity (book.map.section
- the first three dotted components of ref_id) rather than per-point:

1. Are catalogue sections actually category-homogeneous, the way this
   project's whole classification design assumes ("a coastal run OR an
   inland list", never both)? Measured directly from the final, fully
   corrected `category` column - not a guess, the verified answer.

2. How much of that can be read off *just the section header* - the data
   catalogue's own un-coordinated header row(s) (German: "Baliarisches
   Meer", "Ionisches Meer", ...) versus topostext's own lead-in sentence
   for the same section ("A description of the north coast...", "The
   following are the inland towns:", ...)? Each source's header is
   classified independently (reusing category_check.py's ordered English
   keyword patterns for topostext; a parallel German pattern set for the
   catalogue) and checked against the section's actual dominant category.

3. How often do the two sources' headers *agree with each other*, on the
   subset of sections where both have a recognizable header at all?

This is the section-level counterpart of category_check.py's point-level
question - same spirit (an independent guess from wording alone, checked
against the verified answer), one level up the hierarchy.

Usage
-----
    python3 section_header_check.py
"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from itertools import groupby
from pathlib import Path

from category_check import topostext_category

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CATALOGUE = SCRIPT_DIR.parent / "data" / "ptolemy_catalogue_annotated.csv"
DEFAULT_XLSX = SCRIPT_DIR.parent / "data" / "ptolemy_catalogue_stueckelberger.xlsx"
RAW_TOPOSTEXT_FILES = sorted(SCRIPT_DIR.glob("raw_209_*.txt"))

# category -> the coarser "family" sections are actually homogeneous in.
# coast/harbor/river_mouth are one narrative family (a coastal walk); every
# other category is its own family.
_FAMILY = {
    "coast": "coastal",
    "harbor": "coastal",
    "river_mouth": "coastal",
    "city": "city",
    "river": "river",
    "mountain": "mountain",
    "island": "island",
    "lake": "lake",
}

# German section-header keyword families - the header-row counterpart of
# category_check.py's English _CATEGORY_PATTERNS. Ordered, first match
# wins. Coastal reuses ptolemy_map.py's own _COASTAL_HDR_RE word list
# (ozean/meer/golf/meerbusen/kanal/bucht) rather than importing it, so this
# script stays a genuinely independent check, same principle as
# category_check.py not importing _classify_locality.
_DE_HEADER_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\binseln?\b", re.IGNORECASE), "island"),
    (re.compile(r"gebirge|gebirg(?:e|s)|\bberge\b", re.IGNORECASE), "mountain"),
    (re.compile(r"\bsee\b", re.IGNORECASE), "lake"),
    (re.compile(r"ozean|meer(?!wärts)|golf|meerbusen|kanal|bucht", re.IGNORECASE), "coastal"),
]


def catalogue_header_guess(text: str) -> str | None:
    for pattern, family in _DE_HEADER_PATTERNS:
        if pattern.search(text):
            return family
    return None


def topostext_header_guess(text: str) -> str | None:
    guess = topostext_category(text)
    if guess is None:
        return None
    return _FAMILY.get(guess, guess)


# --- data catalogue section headers (raw xlsx, un-coordinated header rows) ---


def load_catalogue_headers(path: Path) -> dict[tuple[str, str], str]:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = [
        tuple(row) + (None,) * (8 - len(row))
        for row in ws.iter_rows(min_row=2, max_col=8, values_only=True)
        if row[0] and row[2]
    ]
    wb.close()

    def has_coord(row: tuple) -> bool:
        return isinstance(row[4], (int, float)) and isinstance(row[5], (int, float)) or (
            isinstance(row[6], (int, float)) and isinstance(row[7], (int, float))
        )

    def section_key(row: tuple) -> tuple:
        parts = str(row[0]).split(".")
        return (row[1], parts[2] if len(parts) > 2 else None)

    headers: dict[tuple[str, str], str] = {}
    for _key, section_rows in groupby(rows, key=section_key):
        section_rows = list(section_rows)
        header_rows = [r for r in section_rows if not has_coord(r)]
        if not header_rows:
            continue
        id_parts = str(section_rows[0][0]).split(".")
        book_map = ".".join(id_parts[:2])
        section = id_parts[2] if len(id_parts) > 2 else ""
        text = " | ".join(str(h[2]) for h in header_rows if h[2])
        if text:
            headers[(book_map, section)] = text
    return headers


def load_catalogue_print_sheets(path: Path) -> dict[tuple[str, str], str]:
    """(book.map, section) -> the xlsx's own ID_map/tabula code ("EU09") -
    every row in a section shares the same ID_map, so this is just the
    first row's value per section. Used by db/build_database.py to
    populate `section.print_sheet`, which feature_id strings are built
    from (see ptolemy_map.py's build_coastlines) - kept out of
    load_catalogue_headers() above since that function's existing callers
    don't need it and its return shape is already relied on elsewhere."""
    import openpyxl

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = [
        tuple(row) + (None,) * (8 - len(row))
        for row in ws.iter_rows(min_row=2, max_col=8, values_only=True)
        if row[0] and row[2]
    ]
    wb.close()

    def section_key(row: tuple) -> tuple:
        parts = str(row[0]).split(".")
        return (row[1], parts[2] if len(parts) > 2 else None)

    sheets: dict[tuple[str, str], str] = {}
    for _key, section_rows in groupby(rows, key=section_key):
        section_rows = list(section_rows)
        id_parts = str(section_rows[0][0]).split(".")
        book_map = ".".join(id_parts[:2])
        section = id_parts[2] if len(id_parts) > 2 else ""
        id_map = (section_rows[0][1] or "").strip()
        if id_map:
            sheets[(book_map, section)] = id_map
    return sheets


# --- topostext section headers (raw pasted text, prose before the first coordinate) ---

_SECTION_RE = re.compile(r"§\s*(\d+)\.(\d+)\.(\d+)\.?\s+")
_COORD_RE = re.compile(
    r"(\d{1,3})°(\d{1,2})?'?\s*[.,]?\s*[a-z]?\s*(\d{1,3})°(\d{1,2})?'?(?:\s+(S)\.?(?![a-z]))?",
    re.IGNORECASE,
)


def load_topostext_headers(paths: list[Path]) -> dict[tuple[str, str], str]:
    headers: dict[tuple[str, str], str] = {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        markers = list(_SECTION_RE.finditer(text))
        for i, m in enumerate(markers):
            book, map_, section = m.group(1), m.group(2), m.group(3)
            body_start = m.end()
            body_end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
            body = text[body_start:body_end]
            coord_matches = list(_COORD_RE.finditer(body))
            header_text = body[: coord_matches[0].start()] if coord_matches else body
            header_text = header_text.strip()
            if header_text:
                headers[(f"{book}.{int(map_):02d}", section)] = header_text
    return headers


# --- catalogue points, grouped into sections ---


def load_section_categories(path: Path) -> dict[tuple[str, str], list[str]]:
    sections: dict[tuple[str, str], list[str]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            category = row.get("category")
            if category not in _FAMILY:
                continue
            ref_id = row["ref_id"]
            parts = ref_id.split(".")
            if len(parts) < 3:
                continue
            book_map = ".".join(parts[:2])
            section = parts[2]
            sections[(book_map, section)].append(_FAMILY[category])
    return sections


def dominant_family(families: list[str]) -> tuple[str, float]:
    counts = Counter(families)
    family, n = counts.most_common(1)[0]
    return family, n / len(families)


def main() -> int:
    section_categories = load_section_categories(DEFAULT_CATALOGUE)
    catalogue_headers = load_catalogue_headers(DEFAULT_XLSX)
    topostext_headers = load_topostext_headers(RAW_TOPOSTEXT_FILES)

    print(f"{len(section_categories)} sections with at least one categorized point")
    print(f"{len(catalogue_headers)} sections have their own catalogue header row")
    print(f"{len(topostext_headers)} sections have topostext prose before their first coordinate")
    print()

    # --- Q1: are sections actually category-homogeneous? ---
    print("=== Q1: section homogeneity of the final (verified) category ===")
    pure = dominant_80 = mixed = 0
    dominance_ratios = []
    for key, families in section_categories.items():
        if len(families) < 2:
            continue
        fam, ratio = dominant_family(families)
        dominance_ratios.append(ratio)
        if ratio == 1.0:
            pure += 1
        elif ratio >= 0.8:
            dominant_80 += 1
        else:
            mixed += 1
    total = pure + dominant_80 + mixed
    print(f"{total} multi-point sections")
    print(f"  pure (single family)              {pure:4d} ({pure/total*100:5.1f}%)")
    print(f"  dominant (>=80% one family)        {dominant_80:4d} ({dominant_80/total*100:5.1f}%)")
    print(f"  mixed (no family >=80%)            {mixed:4d} ({mixed/total*100:5.1f}%)")
    print()

    print("  sections with no dominant family (worth a manual look):")
    for key, families in sorted(section_categories.items()):
        if len(families) < 2:
            continue
        fam, ratio = dominant_family(families)
        if ratio < 0.8:
            counts = Counter(families)
            print(f"    {key[0]}.{key[1]:<3s} {dict(counts)}")
    print()

    # --- Q2: how predictive is each source's own header, alone? ---
    def evaluate_header_source(headers: dict, guess_fn) -> None:
        checked = 0
        correct = 0
        no_guess = 0
        for key, families in section_categories.items():
            header_text = headers.get(key)
            if not header_text:
                continue
            fam, ratio = dominant_family(families) if len(families) > 1 else (families[0], 1.0)
            guess = guess_fn(header_text)
            if guess is None:
                no_guess += 1
                continue
            checked += 1
            if guess == fam:
                correct += 1
        print(f"    {checked + no_guess} sections have both a header and a known dominant category")
        print(f"    {no_guess} of those headers have no recognizable keyword")
        if checked:
            print(f"    {correct}/{checked} header guesses match the dominant category ({correct/checked*100:.1f}%)")

    print("=== Q2: how much can you read off the header alone? ===")
    print("  -- catalogue's own header row (German) --")
    evaluate_header_source(catalogue_headers, catalogue_header_guess)
    print("  -- topostext's own lead-in prose (English) --")
    evaluate_header_source(topostext_headers, topostext_header_guess)
    print()

    # --- Q4: do the two header sources agree with each other? ---
    print("=== Q4: catalogue header vs topostext header, do they agree? ===")
    both_keys = set(catalogue_headers) & set(topostext_headers)
    both_guessed = 0
    agree = 0
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    for key in both_keys:
        g1 = catalogue_header_guess(catalogue_headers[key])
        g2 = topostext_header_guess(topostext_headers[key])
        if g1 is None or g2 is None:
            continue
        both_guessed += 1
        confusion[g1][g2] += 1
        if g1 == g2:
            agree += 1
    print(f"  {len(both_keys)} sections have a header from both sources")
    print(f"  {both_guessed} of those get a keyword guess from both sources")
    if both_guessed:
        print(f"  {agree}/{both_guessed} agree ({agree/both_guessed*100:.1f}%)")
    print()
    print("  confusion matrix (catalogue guess -> topostext guess):")
    all_fams = sorted({f for f in confusion} | {f for c in confusion.values() for f in c})
    header = "".ljust(10) + "".join(f[:8].rjust(9) for f in all_fams)
    print("    " + header)
    for fam in all_fams:
        line = fam.ljust(10) + "".join(str(confusion[fam].get(f, 0)).rjust(9) for f in all_fams)
        print("    " + line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
