-- Ptolemy Geographica - curated database schema
-- ================================================
--
-- Replaces the flat one-row-per-point annotated CSV as the *authoritative*
-- dataset (see README.md's "The curated database" section for the
-- reasoning). Two entities the CSV always flattened onto every point row
-- (section metadata, line-connection facts) get their own tables; three
-- more hold the *override rules themselves* - what used to live only as
-- Python set/dict literals in ptolemy_map.py (point_override,
-- section_override, and connection_override's widened relation_type
-- vocabulary). A correction is now a row edit in one of these three
-- tables plus a `db/recompute.py` run, not a Python code change.
--
-- Coordinates are never edited here - `point.lon_ptolemy`/`lat_ptolemy`
-- are always the data catalogue's own values, unchanged. Everything this
-- project has ever corrected is a *category*, a *section type*, or a
-- *connection* - never a coordinate.

CREATE TABLE section (
    section_id             TEXT PRIMARY KEY,   -- "2.04.03" (book.map.section)
    book                    TEXT NOT NULL,       -- Ptolemy's own book number, "2"
    map                     TEXT NOT NULL,       -- Ptolemy's own book.map, "2.04"
    section_number          TEXT NOT NULL,       -- the section's own number within its map, "03"
    print_sheet              TEXT,                -- the xlsx's own ID_map / tabula code, "EU09" - feeds feature_id strings ("coastline_003_EU09"), constant within a section
    short_title              TEXT,                -- derived label (catalogue header text, or a fallback)
    description_catalogue   TEXT,                -- the data catalogue's own header row text (German, usually short - a sea/province name, not prose)
    description_topos       TEXT,                -- topostext's own lead-in prose for this section, before its first coordinate
    section_type            TEXT,                -- "coast section" | "inland" | "island" | "mountain"
    note                     TEXT                 -- why this section's classification needed manual review, if it did - migrated from ptolemy_map.py's own code comments where one existed
);

CREATE TABLE point (
    point_id                TEXT PRIMARY KEY,   -- ref_id, "2.04.03.01" - this *is* the "Datakatalog ID"
    section_id               TEXT NOT NULL REFERENCES section(section_id),
    sequence_in_section      INTEGER,             -- position within the section (the ref_id's own 4th component, as an integer where parseable)
    category                 TEXT,                -- coast | harbor | river_mouth | city | river | mountain | island | lake
    extra_categories         TEXT,                -- semicolon-separated additional tags, e.g. "boundary"
    name_catalogue           TEXT,                -- the data catalogue's own (German) locality name
    name_topos               TEXT,                -- the matched topostext citation's own phrasing
    modern_location          TEXT,
    recension                TEXT,                -- "Omega" | "Xi"
    lon_ptolemy               REAL,                -- data catalogue's own longitude (Ferro-relative degrees) - never edited
    lat_ptolemy               REAL,                -- data catalogue's own latitude - never edited
    match_score               REAL,                -- topostext match score (0-100), see topostext/link_matches.py
    topos_id                  TEXT,                -- topostext's own citation reference (paragraph.position)
    revision_notes            TEXT                 -- why this point's category/connections needed manual review, if they did - migrated from ptolemy_map.py's own code comments where one existed
);

-- One row per (point, line) membership - a river-mouth point sits on both
-- a coastline *and* a river line at once, hence a separate table rather
-- than columns on `point` (which could only ever hold one such membership).
-- `next_point_id` makes every line-adjacency explicit data: rebuilding a
-- line is "start at the row with no other row's next_point_id pointing to
-- it, then follow next_point_id until NULL (or, if closes_loop, back to
-- the start)" - no separate exception-list mechanism needed for a
-- boundary-citation skip (the point simply has no membership row for that
-- feature_kind) or a hard break (next_point_id just names the real
-- neighbour, not whatever catalogue order would otherwise imply).
CREATE TABLE line_membership (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    point_id                TEXT NOT NULL REFERENCES point(point_id),
    feature_kind             TEXT NOT NULL,       -- "coastline" | "river" | "island" | "mountain"
    feature_id                TEXT NOT NULL,       -- e.g. "coastline_010_EU09"
    sequence_in_feature      INTEGER NOT NULL,
    next_point_id             TEXT REFERENCES point(point_id),  -- NULL if this is the line's last point (and it doesn't close a loop)
    closes_loop               INTEGER NOT NULL DEFAULT 0
);

-- The pairwise facts that were never a single point's own property or a
-- simple next-point link. `relation_type` covers what used to be six
-- separate Python pair-keyed dicts/sets in ptolemy_map.py:
--   no_merge          - these two ref_ids, despite matching heuristics
--                        (same river name, close coordinates), are NOT the
--                        same physical point (was _RIVER_LINE_NO_MERGE_REF_ID_PAIRS)
--   hard_break         - these two catalogue-adjacent points must NOT be
--                        read as a coastline edge (was _COASTLINE_HARD_BREAKS)
--   force_stitch        - force-join two trail endpoints regardless of the
--                        normal distance gap (was _BOUNDARY_STITCH_REF_ID_PAIRS)
--   no_close_loop        - this trail's two endpoints must NOT be closed into
--                        a loop despite passing the normal gap/ratio check
--                        (was _NO_CLOSE_LOOP_TRAILS)
--   force_close_loop      - the inverse: force-close a loop that wouldn't
--                        normally pass (was _FORCE_CLOSE_LOOP_TRAILS)
--   manual_junction       - a manually-confirmed bridge between two otherwise
--                        separate lines (was _MANUAL_JUNCTION_REF_ID_PAIRS);
--                        `value` carries the junction's own label/prose,
--                        the one relation_type where `value` and `note`
--                        legitimately hold the same text (there was never a
--                        separate code comment to distinguish them)
CREATE TABLE connection_override (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_kind             TEXT NOT NULL,       -- "coastline" | "river" | "island" | "mountain"
    relation_type            TEXT NOT NULL,       -- no_merge | hard_break | force_stitch | no_close_loop | force_close_loop | manual_junction
    point_a                  TEXT NOT NULL REFERENCES point(point_id),
    point_b                  TEXT NOT NULL REFERENCES point(point_id),
    value                    TEXT,                -- NULL for every relation_type except manual_junction (its label/prose)
    note                     TEXT
);

-- A single ref_id's own override: force its category, or exclude/reorder it
-- within a line. One row per (point_id, override_type) - a point can carry
-- more than one *kind* of override, never two of the same kind (enforced
-- by the unique index below, so a contradictory duplicate fails loudly at
-- write time instead of silently picking one, the way a Python dict's
-- last-write-wins would have).
--
--   override_type              value                    was
--   --------------------------  -----------------------  ------------------------------------
--   force_island_point          NULL                     _ISLAND_POINT_OVERRIDES
--   force_mountain_point        NULL                     _MOUNTAIN_POINT_OVERRIDES
--   force_river_point           NULL                     _RIVER_POINT_OVERRIDES
--   force_noncoastal_point      NULL                     _NONCOASTAL_POINT_OVERRIDES
--   coastline_skip              NULL                     _COASTLINE_SKIP_REF_IDS
--   river_line_skip             NULL                     _RIVER_LINE_SKIP_REF_IDS
--   coastline_explicit_order    JSON array of ref_ids    _COASTLINE_EXPLICIT_ORDER_OVERRIDES
CREATE TABLE point_override (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    point_id      TEXT NOT NULL REFERENCES point(point_id),
    override_type TEXT NOT NULL,
    value         TEXT,
    note          TEXT
);

-- A whole (book.map, section)'s own override - same shape as point_override,
-- one level up.
--
--   override_type              value           was
--   --------------------------  --------------  ---------------------------------
--   force_island_section        NULL            _ISLAND_APPENDIX_SECTIONS
--   force_mountain_section      NULL            _MOUNTAIN_APPENDIX_SECTIONS
--   force_coastal_section       NULL            _COASTAL_APPENDIX_SECTIONS
--   force_noncoastal_section    NULL            _NONCOASTAL_EXCEPTION_SECTIONS
--   island_line_group           island name     _ISLAND_LINE_GROUPS
CREATE TABLE section_override (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    section_id    TEXT NOT NULL REFERENCES section(section_id),
    override_type TEXT NOT NULL,
    value         TEXT,
    note          TEXT
);

-- Tracks whether each pipeline stage's inputs have changed since it last
-- ran, so `db/pipeline.py` can rerun only what a given edit actually
-- affects instead of the whole chain (see README.md's pipeline-order
-- section). `input_signature` is stage-specific: a sha256 of a raw source
-- file for the xlsx/topostext-import stages, or (for `recompute`)
-- `override_epoch.epoch` combined with a hash over base catalogue content.
CREATE TABLE pipeline_stage (
    stage           TEXT PRIMARY KEY,
    input_signature TEXT NOT NULL,
    ran_at          TEXT NOT NULL
);

-- A single counter, bumped by trigger on any write to point_override,
-- section_override, or connection_override - `recompute`'s cheap staleness
-- check against `pipeline_stage` is "has the epoch moved since I last ran",
-- not a full table re-hash.
CREATE TABLE override_epoch (
    id    INTEGER PRIMARY KEY CHECK (id = 1),
    epoch INTEGER NOT NULL DEFAULT 0
);
INSERT INTO override_epoch (id, epoch) VALUES (1, 0);

CREATE TRIGGER trg_point_override_epoch_ins AFTER INSERT ON point_override
BEGIN UPDATE override_epoch SET epoch = epoch + 1 WHERE id = 1; END;
CREATE TRIGGER trg_point_override_epoch_upd AFTER UPDATE ON point_override
BEGIN UPDATE override_epoch SET epoch = epoch + 1 WHERE id = 1; END;
CREATE TRIGGER trg_point_override_epoch_del AFTER DELETE ON point_override
BEGIN UPDATE override_epoch SET epoch = epoch + 1 WHERE id = 1; END;

CREATE TRIGGER trg_section_override_epoch_ins AFTER INSERT ON section_override
BEGIN UPDATE override_epoch SET epoch = epoch + 1 WHERE id = 1; END;
CREATE TRIGGER trg_section_override_epoch_upd AFTER UPDATE ON section_override
BEGIN UPDATE override_epoch SET epoch = epoch + 1 WHERE id = 1; END;
CREATE TRIGGER trg_section_override_epoch_del AFTER DELETE ON section_override
BEGIN UPDATE override_epoch SET epoch = epoch + 1 WHERE id = 1; END;

CREATE TRIGGER trg_connection_override_epoch_ins AFTER INSERT ON connection_override
BEGIN UPDATE override_epoch SET epoch = epoch + 1 WHERE id = 1; END;
CREATE TRIGGER trg_connection_override_epoch_upd AFTER UPDATE ON connection_override
BEGIN UPDATE override_epoch SET epoch = epoch + 1 WHERE id = 1; END;
CREATE TRIGGER trg_connection_override_epoch_del AFTER DELETE ON connection_override
BEGIN UPDATE override_epoch SET epoch = epoch + 1 WHERE id = 1; END;

CREATE INDEX idx_point_section ON point(section_id);
CREATE INDEX idx_line_membership_point ON line_membership(point_id);
CREATE INDEX idx_line_membership_feature ON line_membership(feature_id);
CREATE UNIQUE INDEX idx_point_override_unique ON point_override(point_id, override_type);
CREATE INDEX idx_point_override_point ON point_override(point_id);
CREATE UNIQUE INDEX idx_section_override_unique ON section_override(section_id, override_type);
CREATE INDEX idx_section_override_section ON section_override(section_id);
