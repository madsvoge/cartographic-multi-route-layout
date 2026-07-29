#!/usr/bin/env python3
"""
Sanity-check the "near-miss" thesis behind forward_unmatched.csv: for each
topostext citation with no catalogue point within the strict 0.02-degree
match tolerance, find the *nearest* catalogue point in the same book
regardless of distance, and compare names (after normalizing umlauts and
translating the catalogue's German descriptor vocabulary to English) to
see whether it's plausibly the same point cited slightly differently, or
something else entirely.

Usage
-----
    python3 verify_near_matches.py
"""

from __future__ import annotations

import csv
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CATALOGUE = SCRIPT_DIR.parent / "data" / "ptolemy_catalogue_annotated.csv"
FORWARD_UNMATCHED = SCRIPT_DIR / "forward_unmatched.csv"

_NEAR_TOL_DEG = 0.6  # generous - just "plausibly the same neighbourhood"

# The catalogue's German descriptor vocabulary (see _MOUTH_RE etc. in
# ptolemy_map.py) translated to the English words topostext actually uses,
# so e.g. "Südspitze" and "southern promontory" compare as similar instead
# of as unrelated strings. Order matters: longer/more specific keys first
# so e.g. "mündung" isn't partially shadowed by a shorter key.
_TRANSLATIONS = [
    ("mündungen", "mouths"),
    ("mündung", "mouth"),
    ("vorgebirge", "promontory"),
    ("spitze", "promontory point tip"),
    ("kap", "cape promontory"),
    ("hafen", "harbor harbour port"),
    ("portus", "harbor harbour port"),
    ("ästuar", "estuary"),
    ("inseln", "islands"),
    ("insel", "island"),
    ("quellen", "sources"),
    ("quelle", "source"),
    ("ursprung", "origin source"),
    ("zusammenfluss", "confluence"),
    ("gebirge", "mountain mountains range"),
    ("berg", "mount mountain"),
    ("palus", "lake marsh"),
    ("golf", "gulf bay"),
    ("meerbusen", "gulf bay"),
    ("bucht", "bay"),
    ("südlich", "southern south"),
    ("nördlich", "northern north"),
    ("östlich", "eastern east"),
    ("westlich", "western west"),
    ("süd", "south southern"),
    ("nord", "north northern"),
    ("ost", "east eastern"),
    ("west", "west western"),
    ("mitte", "middle"),
    ("ende", "end"),
]

_STRIP_RE = re.compile(r"[^a-z0-9\s]")
_WS_RE = re.compile(r"\s+")

# topostext's own boilerplate for a multi-city run - "X, among whom are the
# following towns: ACTUALNAME" / "with these inland cities: ACTUALNAME" -
# the real name is always what follows the *last* colon. Only the first
# point of such a run carries this (later points in the same run are
# already bare names), but it's enough to badly dilute a naive similarity
# score on that first point.
def _strip_leadin(text: str) -> str:
    if ":" in text:
        text = text.rsplit(":", 1)[1]
    return text


def _normalize(text: str) -> str:
    text = _strip_leadin(text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    for de, en in _TRANSLATIONS:
        text = text.replace(de, f" {en} ")
    text = _STRIP_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _name_similarity(a: str, b: str) -> float:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    # token-overlap (order-independent, handles "with city" / lead-in noise)
    ta, tb = set(na.split()), set(nb.split())
    token_score = len(ta & tb) / max(1, min(len(ta), len(tb)))
    # sequence-ratio as a fallback for single-token proper nouns that
    # differ only in transliteration ("Ebusus" vs "Ebussos")
    seq_score = SequenceMatcher(None, na, nb).ratio()
    return max(token_score, seq_score)


def load_catalogue(path: Path) -> dict[str, list[dict]]:
    by_book: dict[str, list[dict]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not row.get("ref_id") or not row.get("lon_ptolemy"):
                continue
            by_book.setdefault(row["ref_id"].split(".")[0], []).append(row)
    return by_book


def main() -> int:
    by_book = load_catalogue(CATALOGUE)
    with FORWARD_UNMATCHED.open(newline="", encoding="utf-8") as fh:
        fwd_rows = list(csv.DictReader(fh))

    buckets = {"near+similar": 0, "near+dissimilar": 0, "far": 0}
    dissimilar_examples: list[tuple] = []
    far_examples: list[tuple] = []

    for row in fwd_rows:
        lon, lat = float(row["lon_decimal"]), float(row["lat_decimal"])
        candidates = by_book.get(row["book"], [])
        in_window = [
            (cand, abs(float(cand["lon_ptolemy"]) - lon) + abs(float(cand["lat_ptolemy"]) - lat))
            for cand in candidates
        ]
        in_window = [(c, d) for c, d in in_window if d <= _NEAR_TOL_DEG]

        if not in_window:
            nearest = min(candidates, key=lambda c: abs(float(c["lon_ptolemy"]) - lon) + abs(float(c["lat_ptolemy"]) - lat), default=None)
            nearest_dist = (
                abs(float(nearest["lon_ptolemy"]) - lon) + abs(float(nearest["lat_ptolemy"]) - lat) if nearest else None
            )
            buckets["far"] += 1
            if len(far_examples) < 15:
                far_examples.append((row["book"], row["map"], row["section"], row["name_phrase"], round(nearest_dist, 2) if nearest_dist is not None else None))
            continue

        # Among everything within the distance window, pick the BEST NAME
        # MATCH rather than the geographically nearest - two different real
        # points (e.g. two river mouths along the same stretch of coast)
        # can sit closer to each other than either sits to its own
        # topostext citation, so nearest-by-distance alone picks wrong.
        best_cand, best_dist, best_sim = None, None, -1.0
        for cand, d in in_window:
            sim = _name_similarity(row["name_phrase"], cand["name"])
            if sim > best_sim:
                best_cand, best_dist, best_sim = cand, d, sim

        if best_sim >= 0.5:
            buckets["near+similar"] += 1
        else:
            buckets["near+dissimilar"] += 1
            if len(dissimilar_examples) < 25:
                dissimilar_examples.append(
                    (row["book"], row["map"], row["section"], row["name_phrase"], best_cand["ref_id"], best_cand["name"], round(best_dist, 3), round(best_sim, 2))
                )

    total = len(fwd_rows)
    print(f"{total} topostext citations with no coordinate match within 0.02 deg")
    print(f"  {buckets['near+similar']} near a catalogue point ({_NEAR_TOL_DEG} deg) AND name-similar -> confirms same-point, edition/rounding difference")
    print(f"  {buckets['near+dissimilar']} near a catalogue point but name doesn't obviously match -> needs a look")
    print(f"  {buckets['far']} no catalogue point within {_NEAR_TOL_DEG} deg at all -> candidate real gaps (or parser noise)")
    print()
    if dissimilar_examples:
        print(f"=== sample of 'near but dissimilar name' ({len(dissimilar_examples)} shown) ===")
        for b, m, s, phrase, ref_id, name, dist, sim in dissimilar_examples:
            print(f"  §{b}.{m}.{s} topostext=\"{phrase}\" ~ nearest cat={ref_id} \"{name}\" (dist={dist}, name_sim={sim})")
        print()
    if far_examples:
        print(f"=== sample of 'far' ({len(far_examples)} shown) ===")
        for b, m, s, phrase, dist in far_examples:
            print(f"  §{b}.{m}.{s} topostext=\"{phrase}\" (nearest cat point {dist} deg away)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
