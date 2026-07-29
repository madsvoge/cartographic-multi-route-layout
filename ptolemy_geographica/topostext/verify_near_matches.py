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
    ("grenzpunkt", "boundary point border limit"),
    ("quellgebiet", "headwaters source region"),
    ("klippe", "cliff rock reef"),
    ("halbinsel", "peninsula"),
    ("meerenge", "strait"),
    ("ebene", "plain"),
    ("hügel", "hill"),
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
    text = text.lower()
    # Translate BEFORE folding umlauts away - the dict's keys ("mündung",
    # "ästuar", "südlich", ...) are themselves umlauted, so translating
    # after an ASCII fold (the original bug here) silently never matched
    # any of them, which is most of the catalogue's descriptor vocabulary.
    for de, en in _TRANSLATIONS:
        text = text.replace(de, f" {en} ")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = _STRIP_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


_TOKEN_RATIO_FLOOR = 0.6  # see _token_sim - separates real variant spelling from coincidence

def _token_sim(t1: str, t2: str) -> float:
    """Graduated token similarity (0..1), not a yes/no match - so a shared
    stem or a variant spelling earns partial credit instead of nothing just
    because it falls short of being identical. The better of two signals:
    (a) the shared *leading* run of characters, scaled by the longer
    token's length ("taurische"/"taurianus" -> 5/9, "sipontum"/"sipus" ->
    3/8 - a 4-letter stem shared by two 9-letter words counts for less than
    the same stem shared by two 5-letter words); (b) a whole-token edit-
    distance ratio, but only above a floor - catches drift the prefix
    check misses because it isn't at the very start of the word
    ("ilipa"/"illipa" -> 0.91, "orospeda"/"ortospeda" -> 0.94,
    "messalias"/"messalia" -> 0.94), gated at 0.6 because below that the
    ratio stops meaning anything: "tyana"/"kydnos" - two words with
    nothing in common - still scores 0.36 from scattered shared letters,
    the same coincidental-overlap failure the phrase-level seq_score
    fallback below has to guard against too."""
    if t1 == t2:
        return 1.0
    if len(t1) < 3 or len(t2) < 3:
        return 0.0
    common_prefix = 0
    for c1, c2 in zip(t1, t2):
        if c1 != c2:
            break
        common_prefix += 1
    prefix_score = common_prefix / max(len(t1), len(t2)) if common_prefix >= 3 else 0.0
    ratio = SequenceMatcher(None, t1, t2).ratio()
    ratio_score = ratio if ratio >= _TOKEN_RATIO_FLOOR else 0.0
    return max(prefix_score, ratio_score)


def _name_similarity(a: str, b: str) -> float:
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    # For each token on the *shorter* side (order-independent, handles
    # "with city" / lead-in noise), its best graduated similarity to any
    # token on the other side - averaged, not counted as a hit/miss, so a
    # partial stem match nudges the score up without needing to clear a
    # hard bar the way the old boolean version did.
    ta, tb = na.split(), nb.split()
    shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if not shorter:
        return 0.0
    per_token = [max((_token_sim(t, o) for o in longer), default=0.0) for t in shorter]
    token_score = sum(per_token) / len(per_token)
    # sequence-ratio as a fallback, but *only* for single-token proper
    # nouns that differ purely by transliteration ("Ebusus" vs "Ebussos")
    # - applied to longer phrases it stops being a name check at all and
    # starts rewarding coincidental character overlap between otherwise
    # unrelated text (e.g. "Kydnos sources" vs "Tyana" scored 0.21 this
    # way despite sharing no real word, just scattered letters).
    seq_score = SequenceMatcher(None, na, nb).ratio() if len(ta) == 1 and len(tb) == 1 else 0.0
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
