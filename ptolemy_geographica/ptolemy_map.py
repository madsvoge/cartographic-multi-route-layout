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


def load_xlsx(path: Path) -> list[Reference]:
    """Load the Stueckelberger/Grasshoff-schema catalogue workbook.

    Columns: ID, ID_map, Locality, Modern_location,
             Longitude_Omega, Latitude_Omega, Longitude_Xi, Latitude_Xi
    Uses the Omega recension's coordinates where present, falling back to
    Xi; rows with neither (region/people/river names without their own
    coordinate pair) are skipped.
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
    rows = ws.iter_rows(min_row=2, max_col=8, values_only=True)

    refs: list[Reference] = []
    for row in rows:
        row = tuple(row) + (None,) * (8 - len(row))
        _id, id_map, locality, modern_location, lon_o, lat_o, lon_x, lat_x = row
        if not locality:
            continue

        if isinstance(lon_o, (int, float)) and isinstance(lat_o, (int, float)):
            lon, lat, recension = float(lon_o), float(lat_o), "Omega"
        elif isinstance(lon_x, (int, float)) and isinstance(lat_x, (int, float)):
            lon, lat, recension = float(lon_x), float(lat_x), "Xi"
        else:
            continue  # no coordinate pair recorded for this catalogue entry

        id_map = (id_map or "").strip()
        continent = _CONTINENT_NAMES.get(id_map[:2], id_map[:2])
        refs.append(
            Reference(
                name=str(locality).strip(),
                book=continent,
                tabula=id_map or "?",
                lon_ptolemy=lon,
                lat_ptolemy=lat,
                source=path.name,
                modern_location=str(modern_location).strip() if modern_location else "",
                recension=recension,
            )
        )
    wb.close()
    return refs


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


def build_map(refs: list[Reference], output: Path) -> None:
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

    center_lat = sum(r.lat_modern for r in plausible) / len(plausible)
    center_lon = sum(r.lon_modern for r in plausible) / len(plausible)

    fmap = folium.Map(location=[center_lat, center_lon], zoom_start=5, tiles="OpenStreetMap")
    cluster = MarkerCluster(name="Ptolemy Geographica references").add_to(fmap)

    for ref in plausible:
        modern_line = f"Identified with: {html.escape(ref.modern_location)}<br>" if ref.modern_location else ""
        recension_line = f" ({html.escape(ref.recension)} recension)" if ref.recension else ""
        popup_html = (
            f"<b>{html.escape(ref.name)}</b><br>"
            f"{modern_line}"
            f"Book {html.escape(ref.book) or '?'} "
            f"&mdash; {html.escape(ref.tabula) or 'unlabelled table'}<br>"
            f"Ptolemy coords: {ref.lon_ptolemy:.2f}° (Ferro), {ref.lat_ptolemy:.2f}°{recension_line}<br>"
            f"Modern approx.: {ref.lat_modern:.3f}, {ref.lon_modern:.3f}<br>"
            f"<i>source: {html.escape(ref.source)}</i>"
        )
        folium.CircleMarker(
            location=[ref.lat_modern, ref.lon_modern],
            radius=5,
            color="#8b2e2e",
            fill=True,
            fill_color="#c0504d",
            fill_opacity=0.85,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=ref.name,
        ).add_to(cluster)

    folium.LayerControl().add_to(fmap)
    output.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(output))
    print(f"plotted {len(plausible)} geographical reference(s) -> {output}")


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
            print(
                f"[{status}] {ref.name!r} book={ref.book!r} tabula={ref.tabula!r} "
                f"ptolemy=({ref.lon_ptolemy:.2f},{ref.lat_ptolemy:.2f}) "
                f"modern=({ref.lat_modern:.3f},{ref.lon_modern:.3f}) source={ref.source}"
            )
        print(f"\n{len(refs)} reference(s) total")
        return 0

    build_map(refs, args.output)

    if args.open:
        webbrowser.open(args.output.resolve().as_uri())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
