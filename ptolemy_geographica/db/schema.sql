-- Ptolemy Geographica - curated database schema
-- ================================================
--
-- Four tables, replacing the flat one-row-per-point annotated CSV as the
-- *authoritative* dataset (see README.md's "The curated database" section
-- for the reasoning). Two entities the CSV always flattened onto every
-- point row (section metadata, line-connection facts) get their own
-- tables; a fourth holds the pairwise facts that were never really a
-- single point's own property (no-merge guards).
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
-- simple next-point link - currently just "these two ref_ids, despite
-- matching heuristics (same river name, close coordinates), are NOT the
-- same physical point and must not be merged into one node".
CREATE TABLE connection_override (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    feature_kind             TEXT NOT NULL,       -- "coastline" | "river" | "island" | "mountain"
    relation_type            TEXT NOT NULL,       -- "no_merge" (more types can be added later without a schema change)
    point_a                  TEXT NOT NULL REFERENCES point(point_id),
    point_b                  TEXT NOT NULL REFERENCES point(point_id),
    note                     TEXT
);

CREATE INDEX idx_point_section ON point(section_id);
CREATE INDEX idx_line_membership_point ON line_membership(point_id);
CREATE INDEX idx_line_membership_feature ON line_membership(feature_id);
