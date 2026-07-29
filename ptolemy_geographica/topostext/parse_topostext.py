#!/usr/bin/env python3
"""
Parse pasted topostext.org/work/209 text (Ptolemy's Geography, English
translation) into a flat CSV of individual place citations.
==============================================================================

topostext's paragraph numbering ("§ 2.2.3") lines up with our catalogue's
book.map.section (the first three dotted components of ref_id) - confirmed
by hand against Ireland's north coast (§2.2.1) - but it does not expose a
per-point item number the way our ref_id's fourth component does, and a
paragraph's *first* point is often a restatement of the *previous*
paragraph's last point folded into the lead sentence ("from the Boreum
promontory which is in 11°00' . 61°00'...") rather than listed as its own
line - the same "shared boundary citation" pattern already found and fixed
directly in ptolemy_map.py (Kap Oiarso, Nordspitze, Acheloos-Mündung).

Rather than lean on a fragile position-in-section alignment, this script
extracts every (name phrase, longitude, latitude) triple in catalogue
order and lets crossref_topostext.py match them back to our dataset by
*coordinate*, which is robust to exactly that kind of restatement and to
any off-by-one in section boundaries between the two sources.

Usage
-----
    python3 parse_topostext.py raw_209_2.02-2.03.txt -o topostext_209.csv
    # append more as you paste more chunks:
    python3 parse_topostext.py raw_209_new_chunk.txt -o topostext_209.csv --append
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# "§ 2.2.3" - book, map, section (topostext's own paragraph numbering).
# A trailing "." before the whitespace ("§ 2.12.1.  RAETIA...") is rare
# (one occurrence in the whole corpus so far) but fatal when missed: the
# marker silently fails to match, so that section's whole body - including
# any of its own coordinates - gets absorbed into the *previous* section's
# body by the following section's successful match instead, mislabeling
# real points under the wrong book.map.section (found while building
# region labels, when book 2 map 12's opening boundary-description
# coordinates turned up misattributed to map 11 section 16).
_SECTION_RE = re.compile(r"§\s*(\d+)\.(\d+)\.(\d+)\.?\s+")

# "11°00' . 61°00'" (also tolerate a missing "'" or a stray footnote
# letter/space in place of the " . " separator, e.g. "14°00 d 51°45'").
# Minutes are optional on both components - book 4's Ethiopia/Agisymba
# chunk (below the equator, at the edge of Ptolemy's known world) gives
# several points in bare whole degrees ("80° . 15°20' S.", "45° . 6° S."),
# and a required-minutes group silently dropped every one of them instead
# of erroring, the kind of quiet data loss that's easy to miss unless a
# section's parsed-point count looks suspiciously low against how many
# coordinates its raw text actually has. A trailing "S" (or "S.") marks a
# southern-hemisphere latitude - this catalogue's only use of a hemisphere
# letter, since longitude is always east-of-Ferro and latitude north
# in every other book.
_COORD_RE = re.compile(
    r"(\d{1,3})°(\d{1,2})?'?\s*[.,]?\s*[a-z]?\s*(\d{1,3})°(\d{1,2})?'?(?:\s+(S)\.?(?![a-z]))?",
    re.IGNORECASE,
)

# Connector phrases that introduce a *restated* point from the previous
# paragraph rather than a fresh one - stripped from the left of a name
# phrase so what's left is closer to the actual place name. Not load-bearing
# for correctness (matching is by coordinate - see module docstring), just
# for readability of the name_phrase column.
_LEADIN_RE = re.compile(
    r"^.*?\b(?:from the|from|beginning at the|beginning at|after the|after)\s+",
    re.IGNORECASE | re.DOTALL,
)
_TRAILING_CONNECTOR_RE = re.compile(
    r"\s*\b(?:which is in|which is at|is in|is at|at)\s*$",
    re.IGNORECASE,
)
_LEADING_JUNK_RE = re.compile(r"^(?:and|then|next|,|;)\s+", re.IGNORECASE)


def _dms_to_decimal(deg: str, minutes: str | None) -> float:
    return float(deg) + (float(minutes) if minutes else 0.0) / 60.0


def _clean_name_phrase(raw: str) -> str:
    raw = raw.strip()
    raw = _LEADIN_RE.sub("", raw)
    raw = _TRAILING_CONNECTOR_RE.sub("", raw)
    raw = _LEADING_JUNK_RE.sub("", raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip(" ,;.")


def parse_text(text: str) -> list[dict]:
    """Split on "§ B.M.S" markers, then pull every (name, lon, lat) triple
    out of each section's body text in order of appearance."""
    markers = list(_SECTION_RE.finditer(text))
    rows: list[dict] = []
    for i, m in enumerate(markers):
        book, map_, section = m.group(1), m.group(2), m.group(3)
        body_start = m.end()
        body_end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        body = text[body_start:body_end]

        coord_matches = list(_COORD_RE.finditer(body))
        if not coord_matches:
            continue  # a pure tribe/prose paragraph - no point data to extract

        prev_end = 0
        for position, cm in enumerate(coord_matches, start=1):
            name_phrase = _clean_name_phrase(body[prev_end : cm.start()])
            prev_end = cm.end()
            lon = _dms_to_decimal(cm.group(1), cm.group(2))
            lat = _dms_to_decimal(cm.group(3), cm.group(4))
            if cm.group(5):  # trailing "S"/"S." - southern hemisphere
                lat = -lat
            lon_dms = f"{cm.group(1)}°{cm.group(2)}'" if cm.group(2) else f"{cm.group(1)}°"
            lat_dms = f"{cm.group(3)}°{cm.group(4)}'" if cm.group(4) else f"{cm.group(3)}°"
            if cm.group(5):
                lat_dms += " S"
            rows.append(
                {
                    "book": book,
                    "map": map_,
                    "section": section,
                    "position": position,
                    "name_phrase": name_phrase,
                    "lon_dms": lon_dms,
                    "lat_dms": lat_dms,
                    "lon_decimal": round(lon, 4),
                    "lat_decimal": round(lat, 4),
                }
            )
    return rows


_FIELDS = ["book", "map", "section", "position", "name_phrase", "lon_dms", "lat_dms", "lon_decimal", "lat_decimal"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path, nargs="+", help="Raw pasted-text file(s) to parse")
    parser.add_argument("-o", "--output", type=Path, default=SCRIPT_DIR / "topostext_209.csv")
    parser.add_argument("--append", action="store_true", help="Append to an existing output CSV instead of overwriting")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    rows: list[dict] = []
    for path in args.input:
        rows.extend(parse_text(path.read_text(encoding="utf-8")))

    mode = "a" if args.append and args.output.exists() else "w"
    write_header = mode == "w"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open(mode, newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    print(f"parsed {len(rows)} point citations from {len(args.input)} file(s) -> {args.output} ({'appended' if mode == 'a' else 'written'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
