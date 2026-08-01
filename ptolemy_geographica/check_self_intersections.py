#!/usr/bin/env python3
"""
Check every drawn line for self-intersection
==============================================

A real coastline, river, island outline or mountain-range line never
crosses itself - the same reasoning as a road on a map. If a *drawn* line
does cross itself, that's not a coincidence of Ptolemy's distorted
coordinates (distortion stretches and skews a line, it doesn't fold it
back through itself) - it's a real ordering bug: some point is being
visited out of its true sequence, almost always because an introductory
boundary citation or an undermarked re-citation of an earlier point (see
`_COASTLINE_SKIP_REF_IDS`/`_NO_CLOSE_LOOP_TRAILS` in ptolemy_map.py) was
left in as a graph edge instead of excluded.

This is a diagnostic, not part of the regular pipeline - run it after any
change to the classification/line-building rules in ptolemy_map.py (or
periodically as an audit) to catch this class of bug directly, instead of
eyeballing a rendered map region by region. It found four real bugs this
way in one pass: two false "close the loop" calls whose closing edge cut
straight across the rest of the trail (book.maps 3.10 and 3.11, and a
follow-on case once fixing those let two trails stitch together into a
bigger one that then falsely closed too), and three introductory boundary
citations left in as edges (3.13.06.05, 5.03.01.06, 5.05.01.09,
5.08.01.09) that each crossed several of the walk's own real segments.

Usage
-----
    python3 check_self_intersections.py                # every line type
    python3 check_self_intersections.py --kind coastline
"""

from __future__ import annotations

import argparse
from pathlib import Path

from shapely.geometry import LineString

from ptolemy_map import (
    DEFAULT_INPUT,
    Reference,
    get_coastlines,
    get_island_lines,
    get_mountain_lines,
    get_river_lines,
    load_inputs,
)


def _segments_cross(a1: tuple, a2: tuple, b1: tuple, b2: tuple) -> tuple[float, float] | None:
    """The point where segments (a1,a2) and (b1,b2) cross, or None if they
    don't cross at all, or only touch at a shared endpoint (adjacent
    segments always share one - that's not a self-intersection)."""
    seg_a, seg_b = LineString([a1, a2]), LineString([b1, b2])
    if not seg_a.intersects(seg_b):
        return None
    inter = seg_a.intersection(seg_b)
    if inter.geom_type != "Point":
        return None  # overlapping/collinear segments - a different, rarer problem, not handled here
    for pt in (a1, a2, b1, b2):
        if abs(inter.x - pt[0]) < 1e-6 and abs(inter.y - pt[1]) < 1e-6:
            return None
    return (inter.x, inter.y)


def find_self_intersections(trail: list[Reference], closes_loop: bool = False) -> list[tuple[int, int, tuple[float, float]]]:
    """Every pair of non-adjacent segments in `trail` that cross each
    other, as (segment_i_index, segment_j_index, crossing_point). Adjacent
    segments (sharing a vertex) are never compared - that's a bend, not a
    crossing. If `closes_loop`, the wraparound segment (last point back to
    first) is real and included; the pair (first segment, wraparound
    segment) is skipped since they share the start point."""
    coords = [(r.lon_modern, r.lat_modern) for r in trail]
    if closes_loop and coords[0] != coords[-1]:
        coords = coords + [coords[0]]
    seg_count = len(coords) - 1
    hits = []
    for i in range(seg_count):
        for j in range(i + 2, seg_count):
            if closes_loop and i == 0 and j == seg_count - 1:
                continue  # wraparound segment shares its start with segment 0's start
            pt = _segments_cross(coords[i], coords[i + 1], coords[j], coords[j + 1])
            if pt:
                hits.append((i, j, pt))
    return hits


def _report(kind: str, feature_id: str, trail: list[Reference], closes_loop: bool = False) -> int:
    hits = find_self_intersections(trail, closes_loop)
    for i, j, pt in hits:
        a, b = trail[i], trail[i + 1]
        c, d = trail[j % len(trail)], trail[(j + 1) % len(trail)]
        print(
            f"[{kind}] {feature_id}: segment {a.ref_id}({a.name}) -> {b.ref_id}({b.name})  "
            f"X  segment {c.ref_id}({c.name}) -> {d.ref_id}({d.name})  at ({pt[0]:.2f},{pt[1]:.2f})"
        )
    return len(hits)


def check(refs: list[Reference], kinds: list[str]) -> int:
    total = 0
    if "coastline" in kinds:
        for trail in get_coastlines(refs):
            if len(trail) >= 4:
                total += _report("coastline", trail[0].feature_id or "?", trail, trail[0].feature_closes_loop)
    if "river" in kinds:
        for trail in get_river_lines(refs):
            if len(trail) >= 4:
                total += _report("river", trail[0].river_feature_id or "?", trail)
    if "island" in kinds:
        for trail in get_island_lines(refs):
            if len(trail) >= 4:
                total += _report("island", trail[0].island_feature_id or "?", trail, trail[0].island_feature_closes_loop)
    if "mountain" in kinds:
        for trail in get_mountain_lines(refs):
            if len(trail) >= 4:
                total += _report("mountain", trail[0].mountain_feature_id or "?", trail)
    return total


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", nargs="*", type=Path, default=[DEFAULT_INPUT], help="CSV/XLSX file(s) or directories")
    parser.add_argument(
        "--kind",
        choices=["coastline", "river", "island", "mountain"],
        action="append",
        help="Restrict to one line type (repeatable) - default: all four",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    refs = [r for r in load_inputs(args.input) if r.is_plausible()]
    kinds = args.kind or ["coastline", "river", "island", "mountain"]
    total = check(refs, kinds)
    print(f"\n{total} self-intersection(s) found" if total else "\nno self-intersections found")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
