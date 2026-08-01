#!/usr/bin/env python3
"""
Flag points whose topostext citation mentions a *different* named river
=========================================================================

Every category so far tracks a point's own coordinates and its own
category - nothing captures when topostext's prose ties one point to
*another* feature by name: "the Helveti along the River Rhine, with
cities Ganodurum" names a river a plain `city` point sits beside;
"Between the Indus and the Bidaspes...Ithagouros" places a city between
two rivers neither of which it's itself part of; "The sources of the
Dubis river, which flows below it [the Arar]" ties one river's own source
to a *different*-named river's course, a real tributary relationship the
same-name-based river-line grouping (`build_river_lines` in
`../ptolemy_map.py`) can't see, since "Dubis" and "Arar" never share a
base name to group by.

None of this changes any point's coordinates or category - it's a read-
only annotation, a `river_mentions` column listing which of the
catalogue's own river names (by base name - "Dubis", not "Dubis-Quellen")
turn up in this point's own `topostext_name` text, for a category other
than the river itself. Two filters keep it from being noise:

- **skip self-mentions**: a river point's own citation naming itself
  ("sources of the Dubis river") isn't new information.
- **skip bare-name coincidences**: a few catalogue river names collide
  with unrelated place names elsewhere (catalogue river "Arbis" vs.
  topostext's plain city citation "Arbis"; "Illiberis" vs. catalogue city
  "Iliberri") - genuinely nothing to do with each other, just homonyms.
  Requiring the citation to have at least `_MIN_CONTEXT_WORDS` words
  beyond the matched name filters these out without needing a manual
  exception list: a real relational mention ("the river Euenos flows
  around it") always carries surrounding prose; a coincidental name
  match is usually the bare name alone.

Re-run after `link_matches.py` (needs its `topostext_name` column) and
before `build_labels.py` (label rows have no `topostext_name` to scan and
would just noisily match nothing).

Usage
-----
    python3 river_mentions.py
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CATALOGUE = SCRIPT_DIR.parent / "data" / "ptolemy_catalogue_annotated.csv"

_RIVER_LINE_CATEGORIES = {"river", "river_mouth"}

# The same course/mouth-position suffix stripped by ptolemy_map.py's
# _river_base_name, duplicated here rather than imported so this script
# stays a self-contained CSV-in/CSV-out tool like the rest of topostext/.
_RIVER_SUFFIX_RE = re.compile(
    r"-mündung\b.*$|-quellen?\b.*$|"
    r"\s*\([^)]*(?:mitte|biegung|abzweigung|aufteilung|teilung|einmündung|"
    r"zusammenfluss|ursprung|mündungsarm|mündung|quell|oberlauf|unterlauf)[^)]*\)\s*$",
    re.IGNORECASE,
)
_GENERIC_RIVER_NAME_RE = re.compile(r"namenlos", re.IGNORECASE)

# Below this length a base name is too short to search for as a whole
# word without inviting noise (there's no river this short in the
# catalogue after the length filter below is applied, but kept explicit).
_MIN_NAME_LEN = 4

# A bare-name match ("Arbis", "Illiberis") with nothing else in the
# citation is a homonym coincidence, not a relational mention - real ones
# always come with surrounding prose ("the river Euenos flows around
# it"). Counted as words remaining in topostext_name once the matched
# name itself is removed.
_MIN_CONTEXT_WORDS = 2


def _river_base_name(name: str) -> str:
    return _RIVER_SUFFIX_RE.sub("", name).strip()


def load_rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fieldnames = [f for f in (reader.fieldnames or []) if f != "river_mentions"]
        return fieldnames, list(reader)


def write_rows(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_river_name_pattern(rows: list[dict]) -> re.Pattern | None:
    base_names: set[str] = set()
    for row in rows:
        if row.get("category") not in _RIVER_LINE_CATEGORIES:
            continue
        base = _river_base_name(row.get("name", ""))
        if len(base) >= _MIN_NAME_LEN and not _GENERIC_RIVER_NAME_RE.search(base):
            base_names.add(base)
    if not base_names:
        return None
    # Longest first, so e.g. "Kaystros" doesn't get pre-empted by a
    # coincidentally-contained shorter name earlier in the alternation.
    names_sorted = sorted(base_names, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(n) for n in names_sorted) + r")\b", re.IGNORECASE)


def find_mentions(text: str, own_name: str, pattern: re.Pattern) -> list[str]:
    own_name_lower = own_name.lower()
    found: list[str] = []
    seen: set[str] = set()
    for m in pattern.finditer(text):
        matched = m.group(1)
        key = matched.lower()
        if key in seen or key in own_name_lower:
            continue
        remainder = (text[: m.start()] + text[m.end() :]).split()
        if len(remainder) < _MIN_CONTEXT_WORDS:
            continue
        seen.add(key)
        found.append(matched)
    return found


def main() -> int:
    fieldnames, rows = load_rows(CATALOGUE)
    pattern = build_river_name_pattern(rows)

    matched_count = 0
    for row in rows:
        row["river_mentions"] = ""
        text = row.get("topostext_name") or ""
        if not text or pattern is None:
            continue
        mentions = find_mentions(text, row.get("name", ""), pattern)
        if mentions:
            row["river_mentions"] = "; ".join(mentions)
            matched_count += 1

    new_fieldnames = fieldnames + ["river_mentions"]
    write_rows(CATALOGUE, new_fieldnames, rows)
    print(f"{matched_count} of {len(rows)} rows mention a different named river in their topostext citation -> {CATALOGUE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
