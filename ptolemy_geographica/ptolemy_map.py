#!/usr/bin/env python3
"""
Ptolemy's Geographica -> OpenStreetMap
=======================================

Extracts geographical references (place names + coordinates) recorded in
Claudius Ptolemy's 2nd-century "Geographike Hyphegesis" (Geographica) and
plots them as an interactive map on OpenStreetMap tiles.

Ptolemy's Geographica lists ~8,000 place names as pairs of coordinates
(longitude, latitude in degrees/minutes) measured from a prime meridian at
the "Fortunate Isles" (roughly the Canary Islands / El Hierro / "Ferro"),
not from Greenwich. Three input modes are supported:

1. XLSX mode (default, full catalogue): reads
   `data/ptolemy_catalogue_stueckelberger.xlsx`, a 10,049-row digitization of
   the complete Geographica catalogue covering all 27 regional maps (10
   Europe, 12 Asia, 4 Africa + Ireland), with columns:

       ID, ID_map, Locality, Modern_location,
       Longitude_Omega, Latitude_Omega, Longitude_Xi, Latitude_Xi

   Omega and Xi are the two main manuscript recensions of the Geographica;
   this loader plots the Omega coordinates where available, falling back to
   Xi. ~6,400 of the 10,049 rows carry coordinates - the rest are
   region/people/river names in the catalogue that Ptolemy didn't assign
   their own coordinate pair to.

2. CSV mode: reads structured digitizations of the Geographica's tables
   ("tabulae") using the open-data schema published by the Ptolemy-Geography
   project (github.com/Lorp/Ptolemy-Geography):

       book,map,subheading,placename,longitude,longitude-min,latitude,latitude-min

   A small bundled sample (`data/petri-munster-1540-hibernia.csv`, the
   "Hiberniae Insulae" table from the 1540 Petri/Munster edition) is
   included for reference. Point --input at a directory or specific CSV
   files (in the same schema) to include more.

3. Text mode (--text): a best-effort regex extractor for freeform/plain-text
   editions of the Geographica, for place-name + degree/minute coordinate
   pairs that don't already exist as structured data. Always review
   extracted points with --dry-run before trusting them; OCR'd or loosely
   formatted source text will produce false positives/negatives.

Coordinate conversion
----------------------
Ptolemy's latitude is measured from the equator, the same convention used
today, so it is plotted as-is. His longitude is measured eastward from the
Ferro meridian, so it is converted to a Greenwich-relative WGS84 longitude
by subtracting the meridian's offset (~17.67 deg W of Greenwich, override
with --ferro-offset). This is only an approximate modernization: Ptolemy's
underlying figure for the Earth's circumference was too small, so his
coordinates are systematically stretched/skewed relative to reality,
worse the further from the Mediterranean. Treat plotted positions as
"Ptolemy's claimed location", not ground truth.

Usage
-----
    pip install -r requirements.txt
    python3 ptolemy_map.py                        # full catalogue -> ptolemy_map.html
    python3 ptolemy_map.py --input data/           # every *.csv/*.xlsx in a directory
    python3 ptolemy_map.py --text geographica.txt --dry-run
    python3 ptolemy_map.py --output out.html --open
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import sys
import webbrowser
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path

# Longitude (degrees) of the Ferro/El Hierro meridian west of Greenwich.
# Ptolemy's longitudes count eastward from 0 there, so:
#   modern_longitude = ptolemy_longitude - FERRO_OFFSET_DEG
FERRO_OFFSET_DEG = 17.6667

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR / "data" / "ptolemy_catalogue_stueckelberger.xlsx"
DEFAULT_OUTPUT = SCRIPT_DIR / "ptolemy_map.html"

# Continent prefixes used by the ID_map column of the Stueckelberger/Grasshoff
# catalogue (EU/AS/AF + the map's 2-digit index within that continent).
_CONTINENT_NAMES = {"EU": "Europe", "AS": "Asia", "AF": "Africa"}


# Point categories the xlsx loader classifies each coordinate into, and the
# color each gets on the map (dataviz reference palette, fixed hue order).
CATEGORIES = {
    "coast": {"label": "Coastal point / coastline", "color": "#2a78d6"},
    "city": {"label": "City / inland settlement", "color": "#eb6834"},
    "river": {"label": "River source / confluence", "color": "#1baf7a"},
    "mountain": {"label": "Mountain", "color": "#eda100"},
    "island": {"label": "Island", "color": "#e87ba4"},
    "lake": {"label": "Lake / inland water", "color": "#008300"},
    "": {"label": "Unclassified", "color": "#898781"},
}

# Section-header keywords (German, this catalogue's Locality language) that
# mark a catalogue section as a run of coastal points.
_COASTAL_HDR_RE = re.compile(r"ozean|meer(?!wärts)|golf|meerbusen|kanal|bucht", re.IGNORECASE)
# Per-point name keywords used to refine/override the section-level guess.
# Mouths, capes, harbors and estuaries are coastal by definition regardless
# of what their catalogue section happens to be headed by (sections are
# often headed by the local tribe's name even for points right on the
# shore).
# Note: matched *before* _MOUTH_RE below - "Einmündung" (a tributary joining
# another river inland) contains the substring "mündung" and would
# otherwise be caught by the coastal mouth pattern first.
_RIVERFEAT_RE = re.compile(r"quelle|einmündung|ursprung|zusammenfluss", re.IGNORECASE)
_MOUTH_RE = re.compile(r"mündung", re.IGNORECASE)
_CAPE_RE = re.compile(r"^kap\b|spitze|vorgebirge|promont", re.IGNORECASE)
_HARBOR_RE = re.compile(r"\bhafen\b|portus", re.IGNORECASE)
_ESTUARY_RE = re.compile(r"ästuar", re.IGNORECASE)
_MOUNTAIN_RE = re.compile(r"gebirge|-berg\b|^berg\b", re.IGNORECASE)
_ISLAND_RE = re.compile(r"\binsel\b|inseln", re.IGNORECASE)
# A name ending in "(N)" - "Kassiteriden (10)", "Pityussae (2)" - denotes an
# island group given as a single count-labelled entry, a standard
# cataloguing convention for scattered islands sharing one name. These
# often sit in a section headed by a sea name (so section_is_coastal would
# otherwise call them "coast"), but they're not steps along a coastal
# walk - two island groups in the same sea can be catalogued back to back
# while sitting on opposite sides of it, and connecting them as if adjacent
# drew a line straight across open water between unrelated islands.
_ISLAND_GROUP_RE = re.compile(r"\(\d+\)\s*$")
_LAKE_RE = re.compile(r"\bsee\b|\bpalus\b", re.IGNORECASE)

# Sections manually verified (via the Modern_location column and known
# ancient geography) to be island enumerations rather than coastal walks,
# even though neither the section header nor the point names carry any
# island-specific keyword. A sea-headed section is structurally ambiguous
# between "coastal points along this sea's shore" (e.g. book.map "3.01"
# section "14": Hydruntum/Lupiae/Brundisium - real coastal cities, Otranto/
# Lecce/Brindisi) and "islands scattered across this sea" (section "79" of
# that same book.map: Planasia/Pontia/.../Capreae - Pianosa/Ponza/.../Capri)
# - both look identical from the text alone, so this can't be a general
# regex rule without also breaking the former. Keyed by (book.map, section).
_ISLAND_APPENDIX_SECTIONS = {
    ("2.06", "77"),  # Ophiussa/Ebusus - Formentera/Ibiza (Balearics)
    ("3.01", "78"),  # Aethalia/Capraria/Ilva - Elba/Capraia
    ("3.01", "79"),  # Planasia..Capreae - Pianosa/Ponza/Ischia/Capri
    ("3.11", "14"),  # Kyaneen/Proikonesos/Thasos/Samothrake
    ("3.13", "47"),  # Saso/Skiathos/Peparethos/Skopelos (Sporades)
    ("5.02", "31"),  # Arkesine/Kos/Astypalaia (Cyclades/Dodecanese)
    ("5.02", "32"),  # Syme/Kasos (Dodecanese)
    ("6.07", "43"),  # Red Sea islands
    ("6.07", "45"),  # Red Sea islands incl. Dioskorides (Socotra)
    ("6.07", "46"),  # Sachalitic Gulf islands
    ("6.07", "47"),  # Persian Gulf islands incl. Tylos (Bahrain)
    ("7.01", "95"),  # Ganges-delta islands ("Heptanesia" = "seven islands")
}


def _classify_locality(name: str, section_is_coastal: bool, force_island: bool = False) -> str:
    if _MOUNTAIN_RE.search(name):
        return "mountain"
    if force_island:
        return "island"
    if _RIVERFEAT_RE.search(name):
        return "river"
    if _MOUTH_RE.search(name) or _CAPE_RE.search(name) or _HARBOR_RE.search(name) or _ESTUARY_RE.search(name):
        return "coast"
    if _ISLAND_RE.search(name) or _ISLAND_GROUP_RE.search(name):
        return "island"
    if _LAKE_RE.search(name):
        return "lake"
    if section_is_coastal:
        return "coast"
    return "city"


@dataclass
class Reference:
    """One geographical reference extracted from the Geographica."""

    name: str
    book: str
    tabula: str
    lon_ptolemy: float  # decimal degrees, Ferro-relative
    lat_ptolemy: float  # decimal degrees, from equator
    source: str
    modern_location: str = ""
    recension: str = ""
    category: str = ""  # "coast" | "city" | "river" | "mountain" | "island" | "" (unclassified)
    ref_id: str = ""  # catalogue ID (book.map.section.item), used to reconstruct coastlines

    @property
    def lon_modern(self) -> float:
        return self.lon_ptolemy - FERRO_OFFSET_DEG

    @property
    def lat_modern(self) -> float:
        return self.lat_ptolemy

    def is_plausible(self) -> bool:
        return -180.0 <= self.lon_modern <= 180.0 and -90.0 <= self.lat_modern <= 90.0


def _dms_to_decimal(degrees: str, minutes: str) -> float | None:
    degrees = (degrees or "").strip()
    minutes = (minutes or "").strip()
    if not degrees:
        return None
    try:
        deg = float(degrees)
        mins = float(minutes) if minutes else 0.0
    except ValueError:
        return None
    return deg + mins / 60.0


def load_csv(path: Path) -> list[Reference]:
    """Load one Ptolemy-Geography-schema CSV file."""
    refs: list[Reference] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        counters: dict[str, int] = {}
        for row in reader:
            lon = _dms_to_decimal(row.get("longitude", ""), row.get("longitude-min", ""))
            lat = _dms_to_decimal(row.get("latitude", ""), row.get("latitude-min", ""))
            if lon is None or lat is None:
                continue
            subheading = (row.get("subheading") or "").strip()
            placename = (row.get("placename") or "").strip()
            if not placename:
                counters[subheading] = counters.get(subheading, 0) + 1
                placename = f"{subheading or 'Unnamed point'} #{counters[subheading]}"
            refs.append(
                Reference(
                    name=placename,
                    book=(row.get("book") or "").strip(),
                    tabula=(row.get("map") or subheading).strip(),
                    lon_ptolemy=lon,
                    lat_ptolemy=lat,
                    source=path.name,
                )
            )
    return refs


def _xlsx_section_key(row: tuple) -> tuple:
    """(ID_map, section-number) grouping key - row[0] is the dotted ID."""
    parts = str(row[0]).split(".")
    return (row[1], parts[2] if len(parts) > 2 else None)


def _xlsx_has_coord(row: tuple) -> bool:
    return isinstance(row[4], (int, float)) and isinstance(row[5], (int, float)) or (
        isinstance(row[6], (int, float)) and isinstance(row[7], (int, float))
    )


def load_xlsx(path: Path) -> list[Reference]:
    """Load the Stueckelberger/Grasshoff-schema catalogue workbook.

    Columns: ID, ID_map, Locality, Modern_location,
             Longitude_Omega, Latitude_Omega, Longitude_Xi, Latitude_Xi
    Uses the Omega recension's coordinates where present, falling back to
    Xi; rows with neither (region/people/river names without their own
    coordinate pair) are skipped.

    Each catalogue entry is also classified into a point category (coast /
    city / river / mountain / island) by combining two signals: whether the
    entry's *section* is headed by a coastline-type label (an ocean/sea/gulf
    name - Ptolemy lists coastal points as a running sequence along the
    shore), and keywords in the entry's own name (river mouth, cape,
    mountain range, island). See CATEGORIES and build_coastlines().
    """
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "openpyxl is required to read .xlsx catalogues. Install it with:\n"
            "    pip install -r requirements.txt"
        ) from exc

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = [
        tuple(row) + (None,) * (8 - len(row))
        for row in ws.iter_rows(min_row=2, max_col=8, values_only=True)
        if row[0] and row[2]  # needs an ID and a Locality name
    ]
    wb.close()

    refs: list[Reference] = []
    for _section_key, section_rows in groupby(rows, key=_xlsx_section_key):
        section_rows = list(section_rows)
        headers = [r for r in section_rows if not _xlsx_has_coord(r)]
        section_is_coastal = any(_COASTAL_HDR_RE.search(str(h[2])) for h in headers)
        id_parts = str(section_rows[0][0]).split(".")
        book_map_section = (".".join(id_parts[:2]), id_parts[2] if len(id_parts) > 2 else "")
        force_island = book_map_section in _ISLAND_APPENDIX_SECTIONS

        for row in section_rows:
            _id, id_map, locality, modern_location, lon_o, lat_o, lon_x, lat_x = row
            if isinstance(lon_o, (int, float)) and isinstance(lat_o, (int, float)):
                lon, lat, recension = float(lon_o), float(lat_o), "Omega"
            elif isinstance(lon_x, (int, float)) and isinstance(lat_x, (int, float)):
                lon, lat, recension = float(lon_x), float(lat_x), "Xi"
            else:
                continue  # header/label row - no coordinate pair recorded

            name = str(locality).strip()
            id_map = (id_map or "").strip()
            continent = _CONTINENT_NAMES.get(id_map[:2], id_map[:2])
            refs.append(
                Reference(
                    name=name,
                    book=continent,
                    tabula=id_map or "?",
                    lon_ptolemy=lon,
                    lat_ptolemy=lat,
                    source=path.name,
                    modern_location=str(modern_location).strip() if modern_location else "",
                    recension=recension,
                    category=_classify_locality(name, section_is_coastal, force_island=force_island),
                    ref_id=str(_id),
                )
            )
    return refs


# Coastal runs are broken if consecutive points (in catalogue order) are
# further apart than this (degrees, roughly) - a safety valve against
# wrongly bridging two disjoint landmasses/coastal stretches that happen to
# sit adjacent in the catalogue's row order despite not being geographically
# adjacent (e.g. a description jumping from Kent to the north tip of
# Scotland between two sections). 5 degrees was picked empirically: the
# largest *verified-legitimate* cross-section gap found (Africa's book.map
# "4.03", capes strung along the coast in separate one-point sections) is
# 3.7 degrees, while the jumps this cap needs to reject start around 7-9
# degrees.
_MAX_COASTAL_GAP_DEG = 5.0

# Two catalogue points are treated as "the same physical spot" (a shared
# corner where two separate coastal walks both start/end) if within this
# many degrees of each other.
_SAME_POINT_TOL_DEG = 0.05

# A traced coastline whose two loose ends land within this distance is
# assumed to be a real closed loop (an island, or a peninsula walk that
# just didn't re-state its own starting point) and gets closed.
_CLOSE_LOOP_MAX_GAP_DEG = 6.0

# Separate trails within the same book.map region are stitched together if
# their nearest endpoints are closer than this - a run breaks whenever a
# non-coastal point interrupts an otherwise-continuous coast (a city point
# wedged between two capes, say), and this reconnects those pieces. Tighter
# than the loop-closing gap above since this bridges two *different* trails
# rather than confirming one trail return to its own start.
_STITCH_MAX_GAP_DEG = 2.5


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _ref_dist(a: "Reference", b: "Reference") -> float:
    return _dist((a.lat_modern, a.lon_modern), (b.lat_modern, b.lon_modern))


def _stitch_trails(trails: list[list["Reference"]]) -> list[list["Reference"]]:
    """Greedily join trails whose nearest endpoints are within range."""
    trails = [list(t) for t in trails]
    merged = True
    while merged and len(trails) > 1:
        merged = False
        best = None  # (distance, i, j, orientation)
        for i in range(len(trails)):
            for j in range(i + 1, len(trails)):
                a, b = trails[i], trails[j]
                for orientation, (pa, pb) in {
                    "end-start": (a[-1], b[0]),
                    "end-end": (a[-1], b[-1]),
                    "start-start": (a[0], b[0]),
                    "start-end": (a[0], b[-1]),
                }.items():
                    d = _ref_dist(pa, pb)
                    if d <= _STITCH_MAX_GAP_DEG and (best is None or d < best[0]):
                        best = (d, i, j, orientation)
        if best is not None:
            _, i, j, orientation = best
            a, b = trails[i], trails[j]
            if orientation == "end-start":
                joined = a + b
            elif orientation == "end-end":
                joined = a + list(reversed(b))
            elif orientation == "start-start":
                joined = list(reversed(a)) + b
            else:  # start-end
                joined = b + a
            for idx in sorted((i, j), reverse=True):
                del trails[idx]
            trails.append(joined)
            merged = True
    return trails


def build_coastlines(refs: list[Reference]) -> list[list[Reference]]:
    """Reconstruct coastlines from category="coast" points.

    Returns a list of trails, each an ordered list of the Reference points
    along it (so callers can label points with their name/category/tabula
    and their sequence position within the trail, not just bare
    coordinates).

    Ptolemy lists coastal points as a running sequence along the shore, so
    consecutive "coast"-classified points *in catalogue order* are real
    geographic neighbours. But a region isn't always described as one
    single unbroken lap: Ptolemy often walks a coast out from a corner
    point and back to a *different* stretch starting at that same corner
    again (e.g. Ireland's north coast and west coast both start at
    "Nordspitze"). Naively concatenating catalogue order end-to-end draws
    a spurious straight line from the end of one walk back across to the
    start of the next.

    Instead, catalogue-order neighbours become edges in an undirected
    graph, with points that (nearly) coincide - like "Nordspitze" showing
    up twice - collapsed into one shared node. Tracing each connected
    component as a path (or a cycle, if it closes on itself) reconstructs
    the coastline without that spurious jump: shared corners naturally
    become junctions rather than the two arms getting stitched together
    end-to-end. A path whose two remaining loose ends land close together
    is closed into a loop (see _CLOSE_LOOP_MAX_GAP_DEG) - this is what
    closes an island's coastline back to its own starting point.

    Runs (and hence edges) are grouped by the catalogue's own "book.map"
    prefix (e.g. "2.02"), not by the printed tabula (e.g. "EU01") - a
    single tabula routinely bundles several distinct book.map sub-regions
    onto one sheet (EU01 = Ireland "2.02" *and* Britain "2.03"), and
    grouping by tabula alone drew a line straight across the sea between
    two unrelated landmasses. A run also breaks whenever a
    differently-classified point interrupts the sequence, or the gap
    between two points is implausibly large.
    """

    def sort_key(ref: Reference) -> tuple:
        return tuple(int(p) if p.isdigit() else p for p in ref.ref_id.split("."))

    def book_map(ref: Reference) -> str:
        parts = ref.ref_id.split(".")
        return ".".join(parts[:2]) if len(parts) >= 2 else ref.ref_id

    groups: dict[tuple[str, str], list[Reference]] = {}
    for ref in refs:
        if not ref.ref_id or not ref.is_plausible():
            continue
        groups.setdefault((ref.source, book_map(ref)), []).append(ref)

    polylines: list[list[Reference]] = []
    for items in groups.values():
        items.sort(key=sort_key)

        # Build the raw catalogue-order edge list, breaking at non-coastal
        # points or implausibly large jumps.
        # Non-coastal rows (a city, a river feature) are skipped over rather
        # than treated as a hard break: some books (e.g. Africa) interleave
        # a tribal/descriptive aside between *every* coastal point instead
        # of grouping them into one contiguous run the way e.g. Ireland's
        # entry does, and requiring strict adjacency dropped those capes
        # entirely. The distance cap below is what still guards against
        # bridging two genuinely unrelated stretches.
        edges: list[tuple[Reference, Reference]] = []
        prev: Reference | None = None
        for ref in items:
            if ref.category != "coast":
                continue
            if prev is not None and _dist((prev.lat_modern, prev.lon_modern), (ref.lat_modern, ref.lon_modern)) <= _MAX_COASTAL_GAP_DEG:
                edges.append((prev, ref))
            prev = ref

        if not edges:
            continue

        # Collapse near-identical points (shared corners) into one node,
        # keyed by rounded coordinates.
        def node_key(ref: Reference) -> tuple[float, float]:
            return (round(ref.lat_modern / _SAME_POINT_TOL_DEG), round(ref.lon_modern / _SAME_POINT_TOL_DEG))

        node_ref: dict[tuple[float, float], Reference] = {}
        adjacency: dict[tuple[float, float], list[tuple[float, float]]] = {}
        for a, b in edges:
            ka, kb = node_key(a), node_key(b)
            node_ref.setdefault(ka, a)
            node_ref.setdefault(kb, b)
            if ka == kb:
                continue
            adjacency.setdefault(ka, []).append(kb)
            adjacency.setdefault(kb, []).append(ka)

        # Decompose the graph into trails that together cover every edge -
        # not just one path per connected component. A node with 3+ edges
        # (three or more coastal walks sharing one corner) can't be
        # captured by a single walk: greedily walking from one endpoint
        # until "stuck" leaves the other branches at that junction
        # untouched, and since nothing revisits an already-walked node,
        # those branches would otherwise be silently dropped instead of
        # rendered as their own line. Repeatedly tracing a trail from
        # whatever unused edges remain - allowing a junction node to be
        # revisited by a later trail - guarantees every edge ends up in
        # some polyline.
        remaining: dict[tuple[float, float], list[tuple[float, float]]] = {n: list(nbs) for n, nbs in adjacency.items()}

        def remove_edge(u: tuple[float, float], v: tuple[float, float]) -> None:
            remaining[u].remove(v)
            remaining[v].remove(u)

        trails: list[list[Reference]] = []
        while any(remaining.values()):
            # Prefer starting a trail at an odd-degree node (a natural
            # trail endpoint); otherwise any node with unused edges works
            # (it's part of a not-yet-fully-consumed cycle or junction).
            start_node = next(
                (n for n, nbs in remaining.items() if nbs and len(nbs) % 2 == 1),
                next(n for n, nbs in remaining.items() if nbs),
            )
            path = [start_node]
            current = start_node
            while remaining[current]:
                nxt = remaining[current][0]
                remove_edge(current, nxt)
                path.append(nxt)
                current = nxt

            trail_refs = [node_ref[n] for n in path]
            if len(trail_refs) >= 2:
                trails.append(trail_refs)

        # Trails broken apart by an interrupting non-coastal point (rather
        # than a genuine gap in the graph) are rejoined if their loose ends
        # land close together, then closed into a loop if the final trail
        # returns near its own start.
        for trail_refs in _stitch_trails(trails):
            first, last = trail_refs[0], trail_refs[-1]
            if (
                len(trail_refs) >= 4
                and first is not last
                and _dist((first.lat_modern, first.lon_modern), (last.lat_modern, last.lon_modern)) <= _CLOSE_LOOP_MAX_GAP_DEG
            ):
                trail_refs = trail_refs + [first]
            polylines.append(trail_refs)

    return polylines


def load_inputs(paths: list[Path]) -> list[Reference]:
    refs: list[Reference] = []
    for p in paths:
        if p.is_dir():
            data_files = sorted(p.glob("*.csv")) + sorted(p.glob("*.xlsx"))
            if not data_files:
                print(f"warning: no *.csv/*.xlsx files found in directory {p}", file=sys.stderr)
            for data_file in data_files:
                refs.extend(load_xlsx(data_file) if data_file.suffix == ".xlsx" else load_csv(data_file))
        elif p.suffix == ".xlsx":
            refs.extend(load_xlsx(p))
        else:
            refs.extend(load_csv(p))
    return refs


# Best-effort extractor for freeform/plain-text editions of the Geographica.
# Matches a leading place name followed by two degree(-minute) coordinate
# pairs on the same line, e.g.:
#   "Massalia   Long. 24 20   Lat. 45 15"
#   "Rhegion — 40°15' 38°30'"
_TEXT_LINE_RE = re.compile(
    r"""
    ^\s*
    (?P<name>[A-Za-z][A-Za-z .,'\-]{1,60}?)     # place name
    [\s:.\-]{1,10}
    (?:long\.?\s*)?
    (?P<lon_deg>\d{1,3})\s*[°ºo,]?\s*(?P<lon_min>\d{1,2})?\s*['′]?
    [\s,;]{1,6}
    (?:lat\.?\s*)?
    (?P<lat_deg>\d{1,2})\s*[°ºo,]?\s*(?P<lat_min>\d{1,2})?\s*['′]?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_from_text(path: Path) -> list[Reference]:
    """Regex-based extraction of place/coordinate pairs from freeform text.

    Heuristic only - intended for scanning digitized plain-text editions of
    the Geographica that aren't yet available as structured CSV. Always
    sanity-check results (e.g. with --dry-run) before trusting them.
    """
    refs: list[Reference] = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        match = _TEXT_LINE_RE.match(line)
        if not match:
            continue
        lon = _dms_to_decimal(match.group("lon_deg"), match.group("lon_min"))
        lat = _dms_to_decimal(match.group("lat_deg"), match.group("lat_min"))
        if lon is None or lat is None:
            continue
        name = match.group("name").strip(" .,-")
        if not name:
            continue
        refs.append(
            Reference(
                name=name,
                book="",
                tabula="",
                lon_ptolemy=lon,
                lat_ptolemy=lat,
                source=path.name,
            )
        )
    return refs


def build_map(
    refs: list[Reference],
    output: Path,
    center: tuple[float, float] | None = None,
    zoom_start: int = 5,
) -> None:
    try:
        import folium
        from folium.plugins import MarkerCluster
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "folium is required to render the map. Install it with:\n"
            "    pip install -r requirements.txt"
        ) from exc

    plausible = [r for r in refs if r.is_plausible()]
    dropped = len(refs) - len(plausible)
    if dropped:
        print(f"warning: dropped {dropped} reference(s) with out-of-range coordinates", file=sys.stderr)
    if not plausible:
        raise SystemExit("no plottable geographical references found")

    if center is None:
        center_lat = sum(r.lat_modern for r in plausible) / len(plausible)
        center_lon = sum(r.lon_modern for r in plausible) / len(plausible)
    else:
        center_lat, center_lon = center

    fmap = folium.Map(location=[center_lat, center_lon], zoom_start=zoom_start, tiles="OpenStreetMap")

    coastlines = build_coastlines(plausible)
    # Position of each coastal point within its trail, so it can be labelled
    # "#N in coastline segment #M" - both in the map (see below) and for
    # anyone re-deriving the trails to audit a specific segment.
    trail_position: dict[str, tuple[int, int]] = {}
    for trail_idx, trail in enumerate(coastlines):
        for i, ref in enumerate(trail):
            trail_position.setdefault(ref.ref_id, (trail_idx, i))

    if coastlines:
        coast_layer = folium.FeatureGroup(name=f"Coastlines ({len(coastlines)} segments)").add_to(fmap)
        for line in coastlines:
            coords = [(r.lat_modern, r.lon_modern) for r in line]
            folium.PolyLine(coords, color=CATEGORIES["coast"]["color"], weight=2, opacity=0.75).add_to(coast_layer)

    clusters = {
        cat: MarkerCluster(name=f"{info['label']} ({sum(1 for r in plausible if r.category == cat)})").add_to(fmap)
        for cat, info in CATEGORIES.items()
        if any(r.category == cat for r in plausible)
    }

    for ref in plausible:
        modern_line = f"Identified with: {html.escape(ref.modern_location)}<br>" if ref.modern_location else ""
        recension_line = f" ({html.escape(ref.recension)} recension)" if ref.recension else ""
        category_line = f"Category: {html.escape(CATEGORIES[ref.category]['label'])}<br>" if ref.category else ""
        seq_line = ""
        seq_label = ""
        if ref.ref_id in trail_position:
            trail_idx, pos = trail_position[ref.ref_id]
            seq_line = f"Coastline segment #{trail_idx}, position #{pos}<br>"
            seq_label = str(pos)
        popup_html = (
            f"<b>{html.escape(ref.name)}</b><br>"
            f"{modern_line}"
            f"{category_line}"
            f"{seq_line}"
            f"Map ID: {html.escape(ref.ref_id) or '?'} "
            f"&mdash; Book {html.escape(ref.book) or '?'}, {html.escape(ref.tabula) or 'unlabelled table'}<br>"
            f"Ptolemy coords: {ref.lon_ptolemy:.2f}° (Ferro), {ref.lat_ptolemy:.2f}°{recension_line}<br>"
            f"Modern approx.: {ref.lat_modern:.3f}, {ref.lon_modern:.3f}<br>"
            f"<i>source: {html.escape(ref.source)}</i>"
        )
        color = CATEGORIES[ref.category]["color"]
        is_coast = ref.category == "coast"
        marker = folium.CircleMarker(
            location=[ref.lat_modern, ref.lon_modern],
            radius=8 if is_coast else 5,
            color=color,
            weight=2,
            fill=True,
            fill_color=color,
            fill_opacity=0.85,
            popup=folium.Popup(popup_html, max_width=320),
            tooltip=f"#{seq_label} {ref.name} ({ref.ref_id})" if is_coast else f"{ref.name} ({ref.ref_id})",
        )
        marker.add_to(clusters[ref.category])
        if is_coast and seq_label:
            folium.Marker(
                location=[ref.lat_modern, ref.lon_modern],
                icon=folium.DivIcon(
                    html=(
                        f'<div style="font-size:10px;font-weight:bold;color:#0b0b0b;'
                        f'text-shadow:0 0 2px #fff,0 0 2px #fff,0 0 2px #fff,0 0 2px #fff;'
                        f'transform:translate(8px,-8px);white-space:nowrap;">{seq_label}</div>'
                    )
                ),
            ).add_to(clusters["coast"])

    _add_legend(fmap, plausible)
    folium.LayerControl(collapsed=False).add_to(fmap)
    output.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(output))
    print(f"plotted {len(plausible)} geographical reference(s) ({len(coastlines)} coastline segments) -> {output}")


def _add_legend(fmap, refs: list[Reference]) -> None:
    import folium

    present = [cat for cat in CATEGORIES if any(r.category == cat for r in refs)]
    if not present:
        return
    rows = "".join(
        f'<div style="display:flex;align-items:center;margin:2px 0;">'
        f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;'
        f'background:{CATEGORIES[cat]["color"]};margin-right:6px;flex:none;"></span>'
        f'<span>{html.escape(CATEGORIES[cat]["label"])}</span></div>'
        for cat in present
    )
    legend_html = f"""
    <div style="position: fixed; bottom: 24px; left: 24px; z-index: 9999;
                background: #fcfcfb; padding: 10px 12px; border-radius: 6px;
                border: 1px solid #c3c2b7; font-size: 12px; color: #0b0b0b;
                font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
                box-shadow: 0 1px 4px rgba(0,0,0,0.2);">
      <div style="font-weight:bold;margin-bottom:4px;">Point category</div>
      {rows}
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(legend_html))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--input",
        nargs="*",
        type=Path,
        default=[DEFAULT_INPUT],
        help="CSV/XLSX file(s) and/or directories of them "
        "(default: full catalogue data/ptolemy_catalogue_stueckelberger.xlsx)",
    )
    parser.add_argument(
        "--text",
        nargs="*",
        type=Path,
        default=[],
        help="Plain-text file(s) to regex-extract place/coordinate references from",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output HTML map path")
    parser.add_argument(
        "--center",
        nargs=2,
        type=float,
        default=None,
        metavar=("LAT", "LON"),
        help="Initial map center (default: mean of all plotted points)",
    )
    parser.add_argument(
        "--zoom-start",
        type=int,
        default=5,
        help="Initial zoom level (default: 5)",
    )
    parser.add_argument(
        "--ferro-offset",
        type=float,
        default=FERRO_OFFSET_DEG,
        help=f"Degrees the Ferro meridian lies west of Greenwich (default {FERRO_OFFSET_DEG})",
    )
    parser.add_argument("--open", action="store_true", help="Open the resulting map in a browser")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print extracted references instead of building a map",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    global FERRO_OFFSET_DEG
    FERRO_OFFSET_DEG = args.ferro_offset

    refs: list[Reference] = []
    refs.extend(load_inputs(args.input))
    for text_path in args.text:
        refs.extend(extract_from_text(text_path))

    if not refs:
        print("no geographical references loaded (check --input/--text paths)", file=sys.stderr)
        return 1

    if args.dry_run:
        for ref in refs:
            status = "ok" if ref.is_plausible() else "OUT OF RANGE"
            category = f" category={ref.category!r}" if ref.category else ""
            print(
                f"[{status}] {ref.name!r} book={ref.book!r} tabula={ref.tabula!r}{category} "
                f"ptolemy=({ref.lon_ptolemy:.2f},{ref.lat_ptolemy:.2f}) "
                f"modern=({ref.lat_modern:.3f},{ref.lon_modern:.3f}) source={ref.source}"
            )
        print(f"\n{len(refs)} reference(s) total")
        return 0

    center = tuple(args.center) if args.center else None
    build_map(refs, args.output, center=center, zoom_start=args.zoom_start)

    if args.open:
        webbrowser.open(args.output.resolve().as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
