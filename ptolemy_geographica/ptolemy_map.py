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
    "": {"label": "Unclassified", "color": "#898781"},
}

# Section-header keywords (German, this catalogue's Locality language) that
# mark a catalogue section as a run of coastal points.
_COASTAL_HDR_RE = re.compile(r"ozean|meer(?!wärts)|golf|meerbusen|kanal|bucht", re.IGNORECASE)
# Per-point name keywords used to refine/override the section-level guess.
_MOUTH_RE = re.compile(r"mündung", re.IGNORECASE)
_CAPE_RE = re.compile(r"^kap\b|spitze|vorgebirge|promont", re.IGNORECASE)
_MOUNTAIN_RE = re.compile(r"gebirge|-berg\b|^berg\b", re.IGNORECASE)
_ISLAND_RE = re.compile(r"\binsel\b|inseln", re.IGNORECASE)
_RIVERFEAT_RE = re.compile(r"quelle|einmündung|ursprung|zusammenfluss", re.IGNORECASE)


def _classify_locality(name: str, section_is_coastal: bool) -> str:
    if _MOUTH_RE.search(name) or _CAPE_RE.search(name):
        return "coast"
    if _MOUNTAIN_RE.search(name):
        return "mountain"
    if _ISLAND_RE.search(name):
        return "island"
    if _RIVERFEAT_RE.search(name):
        return "river"
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
                    category=_classify_locality(name, section_is_coastal),
                    ref_id=str(_id),
                )
            )
    return refs


# Coastal runs are broken if consecutive points (in catalogue order) are
# further apart than this (degrees, roughly) - a safety valve against
# wrongly bridging two disjoint landmasses that happen to sit adjacent in
# the catalogue's row order.
_MAX_COASTAL_GAP_DEG = 15.0

# After building runs, dangling segment *endpoints* within the same
# book.map region are stitched together if they're closer than this - much
# tighter than the gap valve above, and restricted to endpoints (not every
# point pair) so it only bridges runs that catalogue order itself split
# (e.g. a city/mountain point interrupting an otherwise continuous coast),
# rather than free-form nearest-neighbour routing across the whole point
# cloud, which tends to cut straight across bays and peninsulas.
_STITCH_MAX_GAP_DEG = 2.5


def _stitch_segments(segments: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    """Greedily join segments whose nearest endpoints are within range."""

    def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    segments = [list(s) for s in segments]
    merged = True
    while merged and len(segments) > 1:
        merged = False
        best = None  # (distance, i, j, orientation)
        for i in range(len(segments)):
            for j in range(i + 1, len(segments)):
                a, b = segments[i], segments[j]
                for orientation, (pa, pb) in {
                    "end-start": (a[-1], b[0]),
                    "end-end": (a[-1], b[-1]),
                    "start-start": (a[0], b[0]),
                    "start-end": (a[0], b[-1]),
                }.items():
                    d = dist(pa, pb)
                    if d <= _STITCH_MAX_GAP_DEG and (best is None or d < best[0]):
                        best = (d, i, j, orientation)
        if best is not None:
            _, i, j, orientation = best
            a, b = segments[i], segments[j]
            if orientation == "end-start":
                joined = a + b
            elif orientation == "end-end":
                joined = a + list(reversed(b))
            elif orientation == "start-start":
                joined = list(reversed(a)) + b
            else:  # start-end
                joined = b + a
            for idx in sorted((i, j), reverse=True):
                del segments[idx]
            segments.append(joined)
            merged = True
    return segments


def build_coastlines(refs: list[Reference]) -> list[list[tuple[float, float]]]:
    """Reconstruct coastlines from category="coast" points.

    Ptolemy lists coastal points as a running sequence along the shore, so
    connecting consecutive "coast"-classified points *in catalogue order*
    retraces the coastline he described. Runs are grouped by the
    catalogue's own "book.map" prefix (e.g. "2.02"), not by the printed
    tabula (e.g. "EU01") - a single tabula routinely bundles several
    distinct book.map sub-regions (EU01 = Ireland "2.02" *and* Britain
    "2.03" on one sheet), and grouping by tabula alone drew a spurious
    line straight across the sea between two unrelated landmasses. A run
    also breaks whenever a differently-classified point interrupts the
    sequence, or the gap between two points is implausibly large - such
    breaks are then re-stitched (see _stitch_segments) if the two loose
    ends land close together, since that's usually catalogue order being
    interrupted by an inland aside rather than a real coastline gap.
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

    polylines: list[list[tuple[float, float]]] = []
    for items in groups.values():
        items.sort(key=sort_key)
        segments: list[list[tuple[float, float]]] = []
        current: list[tuple[float, float]] = []
        for ref in items:
            point = (ref.lat_modern, ref.lon_modern)
            if ref.category != "coast":
                if current:
                    segments.append(current)
                current = []
                continue
            if current and (abs(point[0] - current[-1][0]) > _MAX_COASTAL_GAP_DEG or abs(point[1] - current[-1][1]) > _MAX_COASTAL_GAP_DEG):
                segments.append(current)
                current = []
            current.append(point)
        if current:
            segments.append(current)
        polylines.extend(s for s in _stitch_segments(segments) if len(s) >= 2)
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
    if coastlines:
        coast_layer = folium.FeatureGroup(name=f"Coastlines ({len(coastlines)} segments)").add_to(fmap)
        for line in coastlines:
            folium.PolyLine(line, color=CATEGORIES["coast"]["color"], weight=2, opacity=0.75).add_to(coast_layer)

    clusters = {
        cat: MarkerCluster(name=f"{info['label']} ({sum(1 for r in plausible if r.category == cat)})").add_to(fmap)
        for cat, info in CATEGORIES.items()
        if any(r.category == cat for r in plausible)
    }

    for ref in plausible:
        modern_line = f"Identified with: {html.escape(ref.modern_location)}<br>" if ref.modern_location else ""
        recension_line = f" ({html.escape(ref.recension)} recension)" if ref.recension else ""
        category_line = f"Category: {html.escape(CATEGORIES[ref.category]['label'])}<br>" if ref.category else ""
        popup_html = (
            f"<b>{html.escape(ref.name)}</b><br>"
            f"{modern_line}"
            f"{category_line}"
            f"Book {html.escape(ref.book) or '?'} "
            f"&mdash; {html.escape(ref.tabula) or 'unlabelled table'}<br>"
            f"Ptolemy coords: {ref.lon_ptolemy:.2f}° (Ferro), {ref.lat_ptolemy:.2f}°{recension_line}<br>"
            f"Modern approx.: {ref.lat_modern:.3f}, {ref.lon_modern:.3f}<br>"
            f"<i>source: {html.escape(ref.source)}</i>"
        )
        color = CATEGORIES[ref.category]["color"]
        folium.CircleMarker(
            location=[ref.lat_modern, ref.lon_modern],
            radius=4 if ref.category == "coast" else 5,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.85,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=ref.name,
        ).add_to(clusters[ref.category])

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
