#!/usr/bin/env python3
"""
Cross-reference topostext_209.csv and the annotated catalogue by
coordinate (same strict tolerance as crossref_topostext.py), then write
the match status back into *both* source files, and produce a two-sheet
workbook of everything left unmapped for manual review.

Unlike coverage_summary.py (which only prints/dumps a snapshot), this
script mutates the two CSVs in place - re-run it any time either file
changes (a fresh annotate_dataset.py run, or a newly-pasted topostext
chunk) to refresh the match columns.

NOTE: annotate_dataset.py's write_annotated_csv() only knows its own fixed
column list and will overwrite these two extra columns' *values* (not
remove the columns, since DictReader/DictWriter elsewhere just ignore
unknown columns) whenever it regenerates the catalogue - re-run this
script afterwards to refresh them.

Usage
-----
    python3 link_matches.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

SCRIPT_DIR = Path(__file__).resolve().parent
CATALOGUE = SCRIPT_DIR.parent / "data" / "ptolemy_catalogue_annotated.csv"
TOPOSTEXT = SCRIPT_DIR / "topostext_209.csv"
REVIEW_XLSX = SCRIPT_DIR / "unmapped_review.xlsx"

_MATCH_TOL_DEG = 0.02  # same strict tolerance as crossref_topostext.py/coverage_summary.py

# Which book.map pairs topostext has actually covered so far (see
# coverage_summary.py's docstring re: book 4's "map 9" source quirk being
# the tail of map 8, not a real map 9) - scopes the catalogue side of the
# unmapped review to the range topostext could plausibly have cited.
_COVERED_MAPS = {
    "2": set(range(2, 17)),
    "3": set(range(1, 16)),
    "4": set(range(1, 9)),
    "5": set(range(1, 7)),
}


def load_rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def write_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def topo_ref(row: dict) -> str:
    return f"{row['book']}.{row['map']}.{row['section']}.{row['position']}"


def main() -> int:
    cat_fields, cat_rows = load_rows(CATALOGUE)
    topo_fields, topo_rows = load_rows(TOPOSTEXT)

    cat_by_book: dict[str, list[dict]] = {}
    for row in cat_rows:
        if row.get("ref_id") and row.get("lon_ptolemy"):
            cat_by_book.setdefault(row["ref_id"].split(".")[0], []).append(row)

    topo_by_book: dict[str, list[dict]] = {}
    for row in topo_rows:
        topo_by_book.setdefault(row["book"], []).append(row)

    # --- catalogue -> topostext (nearest topostext row within tolerance) ---
    for row in cat_rows:
        row["topostext_matched"] = "no"
        row["topostext_ref"] = ""
        if not (row.get("ref_id") and row.get("lon_ptolemy")):
            continue
        book = row["ref_id"].split(".")[0]
        lon, lat = float(row["lon_ptolemy"]), float(row["lat_ptolemy"])
        best, best_d = None, None
        for cand in topo_by_book.get(book, []):
            d = abs(float(cand["lon_decimal"]) - lon) + abs(float(cand["lat_decimal"]) - lat)
            if d <= _MATCH_TOL_DEG and (best_d is None or d < best_d):
                best, best_d = cand, d
        if best is not None:
            row["topostext_matched"] = "yes"
            row["topostext_ref"] = topo_ref(best)

    # --- topostext -> catalogue (nearest catalogue row within tolerance) ---
    for row in topo_rows:
        row["catalogue_matched"] = "no"
        row["catalogue_ref_id"] = ""
        lon, lat = float(row["lon_decimal"]), float(row["lat_decimal"])
        best, best_d = None, None
        for cand in cat_by_book.get(row["book"], []):
            d = abs(float(cand["lon_ptolemy"]) - lon) + abs(float(cand["lat_ptolemy"]) - lat)
            if d <= _MATCH_TOL_DEG and (best_d is None or d < best_d):
                best, best_d = cand, d
        if best is not None:
            row["catalogue_matched"] = "yes"
            row["catalogue_ref_id"] = best["ref_id"]

    new_cat_fields = cat_fields + ["topostext_matched", "topostext_ref"]
    new_topo_fields = topo_fields + ["catalogue_matched", "catalogue_ref_id"]
    write_rows(CATALOGUE, new_cat_fields, cat_rows)
    write_rows(TOPOSTEXT, new_topo_fields, topo_rows)

    cat_matched = sum(1 for r in cat_rows if r["topostext_matched"] == "yes")
    topo_matched = sum(1 for r in topo_rows if r["catalogue_matched"] == "yes")
    print(f"catalogue: {len(cat_rows)} rows, {cat_matched} marked topostext_matched=yes -> {CATALOGUE.name}")
    print(f"topostext: {len(topo_rows)} rows, {topo_matched} marked catalogue_matched=yes -> {TOPOSTEXT.name}")

    unmapped_cat = [
        r
        for r in cat_rows
        if r["topostext_matched"] == "no"
        and r.get("ref_id")
        and int(r["ref_id"].split(".")[1]) in _COVERED_MAPS.get(r["ref_id"].split(".")[0], set())
    ]
    unmapped_topo = [r for r in topo_rows if r["catalogue_matched"] == "no"]

    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "unmapped_catalogue"
    cat_cols = ["ref_id", "name", "category", "book", "tabula", "modern_location", "lon_ptolemy", "lat_ptolemy"]
    ws1.append(cat_cols)
    for r in unmapped_cat:
        ws1.append([r.get(c, "") for c in cat_cols])
    for i, c in enumerate(cat_cols, start=1):
        ws1.column_dimensions[get_column_letter(i)].width = max(12, len(c) + 2)

    ws2 = wb.create_sheet("unmapped_topostext")
    topo_cols = ["book", "map", "section", "position", "name_phrase", "lon_dms", "lat_dms", "lon_decimal", "lat_decimal"]
    ws2.append(topo_cols)
    for r in unmapped_topo:
        ws2.append([r.get(c, "") for c in topo_cols])
    for i, c in enumerate(topo_cols, start=1):
        ws2.column_dimensions[get_column_letter(i)].width = max(12, len(c) + 2)

    wb.save(REVIEW_XLSX)
    print(f"{len(unmapped_cat)} unmapped catalogue points (scoped to topostext's covered range) -> sheet 'unmapped_catalogue'")
    print(f"{len(unmapped_topo)} unmapped topostext citations -> sheet 'unmapped_topostext'")
    print(f"-> {REVIEW_XLSX}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
