#!/usr/bin/env python3
"""
The override rules classification/line-building read at runtime
====================================================================

`ptolemy_map.py`'s classifier and coastline/river/island graph-building
algorithms need eighteen collections of manually-verified exceptions
(force a point/section's category, skip a point from a line, force-stitch
two trail endpoints, ...) - see `db/schema.sql`'s comments on
`point_override`/`section_override`/`connection_override` for the full
mapping. This module defines `OverrideBundle`, the in-memory shape those
algorithms actually consume, and two ways to build one:

  - `load_overrides_from_code()` - straight from `ptolemy_map.py`'s own
    eighteen module-level constants (today's behaviour, kept as a frozen
    fallback/reference point - see that module's own docstring).
  - `load_overrides_from_db(conn)` - from the `point_override`/
    `section_override`/`connection_override` tables in `db/ptolemy.db`,
    which is what a correction actually edits from here on.

Both return the identical shape, so nothing downstream needs to know or
care which one supplied it - see README.md's "Reading overrides from the
database" section.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field


@dataclass(frozen=True)
class OverrideBundle:
    # section-scoped (was _ISLAND_APPENDIX_SECTIONS and its three siblings,
    # plus _ISLAND_LINE_GROUPS)
    island_appendix_sections: frozenset[tuple[str, str]] = frozenset()
    noncoastal_exception_sections: frozenset[tuple[str, str]] = frozenset()
    mountain_appendix_sections: frozenset[tuple[str, str]] = frozenset()
    coastal_appendix_sections: frozenset[tuple[str, str]] = frozenset()
    island_line_groups: dict[tuple[str, str], str] = field(default_factory=dict)

    # point-scoped (was _ISLAND_POINT_OVERRIDES and its five siblings, plus
    # _COASTLINE_EXPLICIT_ORDER_OVERRIDES)
    island_point_overrides: frozenset[str] = frozenset()
    mountain_point_overrides: frozenset[str] = frozenset()
    river_point_overrides: frozenset[str] = frozenset()
    noncoastal_point_overrides: frozenset[str] = frozenset()
    coastline_skip_ref_ids: frozenset[str] = frozenset()
    river_line_skip_ref_ids: frozenset[str] = frozenset()
    coastline_explicit_order_overrides: dict[str, tuple] = field(default_factory=dict)

    # pair-scoped (was _COASTLINE_HARD_BREAKS and its four siblings, plus
    # _MANUAL_JUNCTION_REF_ID_PAIRS)
    coastline_hard_breaks: frozenset[tuple[str, str]] = frozenset()
    river_line_no_merge_ref_id_pairs: frozenset[tuple[str, str]] = frozenset()
    boundary_stitch_ref_id_pairs: frozenset[tuple[str, str]] = frozenset()
    no_close_loop_trails: frozenset[tuple[str, str]] = frozenset()
    force_close_loop_trails: frozenset[tuple[str, str]] = frozenset()
    manual_junction_ref_id_pairs: dict[tuple[str, str], str] = field(default_factory=dict)


def load_overrides_from_code() -> OverrideBundle:
    """The eighteen Python collections' own live values - deferred import
    (rather than a module-level `import ptolemy_map`) so this module has
    no import-time dependency on ptolemy_map.py, which is itself expected
    to import *this* module (to build its own `_DEFAULT_OVERRIDES`) -
    without the deferral, that would be a circular import at load time."""
    import ptolemy_map as pm

    return OverrideBundle(
        island_appendix_sections=frozenset(pm._ISLAND_APPENDIX_SECTIONS),
        noncoastal_exception_sections=frozenset(pm._NONCOASTAL_EXCEPTION_SECTIONS),
        mountain_appendix_sections=frozenset(pm._MOUNTAIN_APPENDIX_SECTIONS),
        coastal_appendix_sections=frozenset(pm._COASTAL_APPENDIX_SECTIONS),
        island_line_groups=dict(pm._ISLAND_LINE_GROUPS),
        island_point_overrides=frozenset(pm._ISLAND_POINT_OVERRIDES),
        mountain_point_overrides=frozenset(pm._MOUNTAIN_POINT_OVERRIDES),
        river_point_overrides=frozenset(pm._RIVER_POINT_OVERRIDES),
        noncoastal_point_overrides=frozenset(pm._NONCOASTAL_POINT_OVERRIDES),
        coastline_skip_ref_ids=frozenset(pm._COASTLINE_SKIP_REF_IDS),
        river_line_skip_ref_ids=frozenset(pm._RIVER_LINE_SKIP_REF_IDS),
        coastline_explicit_order_overrides=dict(pm._COASTLINE_EXPLICIT_ORDER_OVERRIDES),
        coastline_hard_breaks=frozenset(pm._COASTLINE_HARD_BREAKS),
        river_line_no_merge_ref_id_pairs=frozenset(pm._RIVER_LINE_NO_MERGE_REF_ID_PAIRS),
        boundary_stitch_ref_id_pairs=frozenset(pm._BOUNDARY_STITCH_REF_ID_PAIRS),
        no_close_loop_trails=frozenset(pm._NO_CLOSE_LOOP_TRAILS),
        force_close_loop_trails=frozenset(pm._FORCE_CLOSE_LOOP_TRAILS),
        manual_junction_ref_id_pairs=dict(pm._MANUAL_JUNCTION_REF_ID_PAIRS),
    )


# override_type/relation_type -> which OverrideBundle field it feeds, and
# whether that field is a plain membership set or a key->value dict (in
# which case the row's `value` column is the value - a JSON array for
# coastline_explicit_order, a plain string for the other two).
_SECTION_SET_FIELDS = {
    "force_island_section": "island_appendix_sections",
    "force_noncoastal_section": "noncoastal_exception_sections",
    "force_mountain_section": "mountain_appendix_sections",
    "force_coastal_section": "coastal_appendix_sections",
}
_SECTION_DICT_FIELDS = {"island_line_group": "island_line_groups"}
_POINT_SET_FIELDS = {
    "force_island_point": "island_point_overrides",
    "force_mountain_point": "mountain_point_overrides",
    "force_river_point": "river_point_overrides",
    "force_noncoastal_point": "noncoastal_point_overrides",
    "coastline_skip": "coastline_skip_ref_ids",
    "river_line_skip": "river_line_skip_ref_ids",
}
_POINT_DICT_FIELDS = {"coastline_explicit_order": "coastline_explicit_order_overrides"}
_PAIR_SET_FIELDS = {
    "no_merge": "river_line_no_merge_ref_id_pairs",
    "hard_break": "coastline_hard_breaks",
    "force_stitch": "boundary_stitch_ref_id_pairs",
    "no_close_loop": "no_close_loop_trails",
    "force_close_loop": "force_close_loop_trails",
}
_PAIR_DICT_FIELDS = {"manual_junction": "manual_junction_ref_id_pairs"}


def load_overrides_from_db(conn: sqlite3.Connection) -> OverrideBundle:
    """Rebuild the identical shape `load_overrides_from_code()` returns,
    from `point_override`/`section_override`/`connection_override` in
    `db/ptolemy.db` instead of ptolemy_map.py's Python literals - this is
    what a correction actually changes from here on."""
    section_sets: dict[str, set] = {f: set() for f in _SECTION_SET_FIELDS.values()}
    section_dicts: dict[str, dict] = {f: {} for f in _SECTION_DICT_FIELDS.values()}
    for section_id, override_type, value in conn.execute("SELECT section_id, override_type, value FROM section_override"):
        book_map, _, section_num = section_id.rpartition(".")
        key = (book_map, section_num)
        if override_type in _SECTION_SET_FIELDS:
            section_sets[_SECTION_SET_FIELDS[override_type]].add(key)
        elif override_type in _SECTION_DICT_FIELDS:
            section_dicts[_SECTION_DICT_FIELDS[override_type]][key] = value

    point_sets: dict[str, set] = {f: set() for f in _POINT_SET_FIELDS.values()}
    point_dicts: dict[str, dict] = {f: {} for f in _POINT_DICT_FIELDS.values()}
    for point_id, override_type, value in conn.execute("SELECT point_id, override_type, value FROM point_override"):
        if override_type in _POINT_SET_FIELDS:
            point_sets[_POINT_SET_FIELDS[override_type]].add(point_id)
        elif override_type in _POINT_DICT_FIELDS:
            point_dicts[_POINT_DICT_FIELDS[override_type]][point_id] = tuple(json.loads(value))

    pair_sets: dict[str, set] = {f: set() for f in _PAIR_SET_FIELDS.values()}
    pair_dicts: dict[str, dict] = {f: {} for f in _PAIR_DICT_FIELDS.values()}
    for point_a, point_b, relation_type, value in conn.execute(
        "SELECT point_a, point_b, relation_type, value FROM connection_override"
    ):
        key = (point_a, point_b)
        if relation_type in _PAIR_SET_FIELDS:
            pair_sets[_PAIR_SET_FIELDS[relation_type]].add(key)
        elif relation_type in _PAIR_DICT_FIELDS:
            pair_dicts[_PAIR_DICT_FIELDS[relation_type]][key] = value

    fields = {}
    for d in (section_sets, point_sets, pair_sets):
        fields.update({k: frozenset(v) for k, v in d.items()})
    for d in (section_dicts, point_dicts, pair_dicts):
        fields.update(d)
    return OverrideBundle(**fields)
