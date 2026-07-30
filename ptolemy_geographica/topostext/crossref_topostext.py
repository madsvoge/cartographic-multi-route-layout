#!/usr/bin/env python3
"""
Flag category disagreements against topostext's own already-computed matches
==============================================================================

For every catalogue point `link_matches.py` already matched to a topostext
citation (`topostext_matched == "yes"`), does our `category` look
consistent with what topostext's own English phrasing says the point is
("mouth of the X river" -> river_mouth/coast/harbor, "island" -> island,
"promontory"/cape wording -> coast/mountain, etc)? This is an independent
check against topostext's own narrative, not a guess from Modern_location
or a section-header keyword - the same kind of audit signal that found
the Corfu/Euboea/Egypt bugs earlier in this project's history.

Originally this script re-matched topostext_209.csv against the catalogue
by coordinate with its own strict 0.02deg tolerance, duplicating work
`link_matches.py` already does better (a graduated distance+name score,
covering ~6000 matches instead of ~5000). It now just reads the
annotated catalogue's own `topostext_matched`/`topostext_name` columns -
run `link_matches.py` first.

Two refinements over a naive "does topostext's wording match our
category" check, both found by actually running this and reading the
first batch of results:

- A settlement topostext describes as a "city"/"town" that our own
  category has as `coast`/`harbor`/`river_mouth` is not a disagreement -
  it's how this project's schema works on purpose: a city sitting right
  on the shore is still walked as part of the coastline (see "Point
  classification & coastlines" in the README). Only a *plain settlement
  word* with no coastal-family category at all is worth a look.
- A "lake" mention against a `river` category is not a disagreement when
  the catalogue's own name already marks it as a *location* reference
  ("Padus (Ausfluss aus Lacus Larius)" - the Po's own point describing
  where it exits Lake Como) rather than the lake's own identity - the
  same distinction `_LAKE_LOCATION_REF_RE` in `ptolemy_map.py` draws for
  classification itself, duplicated here as a filter rather than imported
  to keep this script self-contained like the rest of `topostext/`.

Sorted shortest topostext phrase first: a short citation ("Populonium
city") is almost always about the matched point itself, while a long
one is often a multi-clause boundary/region description that happens to
mention several features in passing - only one of which is the actual
matched point - so those are more likely to be noise and worth reviewing
last.

Usage
-----
    python3 crossref_topostext.py
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CATALOGUE = SCRIPT_DIR.parent / "data" / "ptolemy_catalogue_annotated.csv"

_COASTAL_FAMILY = {"coast", "harbor", "river_mouth"}

_TYPE_HINTS: list[tuple[re.Pattern, set[str]]] = [
    (re.compile(r"\bmouth of\b|\bestuary\b", re.IGNORECASE), {"river_mouth", "coast", "harbor"}),
    (re.compile(r"\bisland[s]?\b", re.IGNORECASE), {"island"}),
    (re.compile(r"\bpromontory\b|\bcape\b", re.IGNORECASE), {"coast", "mountain"}),
    (re.compile(r"\bharbor\b|\bharbour\b|\bport\b", re.IGNORECASE), {"harbor", "coast"}),
    (re.compile(r"\bbay\b", re.IGNORECASE), {"coast"}),
    (re.compile(r"\bcity\b|\btown\b", re.IGNORECASE), {"city"} | _COASTAL_FAMILY),
    (re.compile(r"\bsource[s]?\b|\bquelle\b", re.IGNORECASE), {"river"}),
    (re.compile(r"\blake\b", re.IGNORECASE), {"lake"}),
    (re.compile(r"\bmountain[s]?\b|\bmount\b", re.IGNORECASE), {"mountain"}),
]

# Same distinction ptolemy_map.py's _LAKE_LOCATION_REF_RE draws when
# classifying a point in the first place: a river/city point that merely
# *names* a lake as its location ("(Ausfluss aus Lacus Larius)", "(Einmündung
# des aus Lacus Benacus entspringenden Flusses)") isn't lying about being a
# lake - topostext's own "lake" wording is describing the same location
# reference, not a disagreement.
_LAKE_LOCATION_REF_RE = re.compile(r"\b(?:am|im|vom|von|zum|aus|des)\s+[\w\-\s]*?(?:see|seen|palus|lacus)\b", re.IGNORECASE)


def _guess_expected_categories(name_phrase: str) -> set[str] | None:
    for pattern, expected in _TYPE_HINTS:
        if pattern.search(name_phrase):
            return expected
    return None


def load_matched_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [row for row in csv.DictReader(fh) if row.get("topostext_matched") == "yes"]


def find_disagreements(rows: list[dict]) -> list[tuple[dict, set[str]]]:
    disagreements: list[tuple[dict, set[str]]] = []
    for row in rows:
        phrase = row.get("topostext_name") or ""
        expected = _guess_expected_categories(phrase)
        if expected is None or row["category"] in expected:
            continue
        if "lake" in expected and row["category"] == "river" and _LAKE_LOCATION_REF_RE.search(row["name"]):
            continue
        disagreements.append((row, expected))
    disagreements.sort(key=lambda pair: len(pair[0].get("topostext_name") or ""))
    return disagreements


def main() -> int:
    rows = load_matched_rows(DEFAULT_CATALOGUE)
    disagreements = find_disagreements(rows)

    print(f"{len(rows)} catalogue points matched to a topostext citation (topostext_matched == 'yes')")
    print()
    if disagreements:
        print(f"=== {len(disagreements)} possible category disagreements (shortest topostext phrase first) ===")
        for row, expected in disagreements:
            print(
                f"ref_id={row['ref_id']} name={row['name']!r} our_category={row['category']!r} "
                f"expected~{sorted(expected)} topostext=\"{row['topostext_name']}\" "
                f"(topostext_ref={row['topostext_ref']}, score={row['topostext_match_score']})"
            )
    else:
        print("no category disagreements found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
