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
DEFAULT_INPUT = SCRIPT_DIR / "data" / "ptolemy_catalogue_annotated.csv"
DEFAULT_OUTPUT = SCRIPT_DIR / "ptolemy_map.html"

# Continent prefixes used by the ID_map column of the Stueckelberger/Grasshoff
# catalogue (EU/AS/AF + the map's 2-digit index within that continent).
_CONTINENT_NAMES = {"EU": "Europe", "AS": "Asia", "AF": "Africa"}


# Point categories the xlsx loader classifies each coordinate into, and the
# color each gets on the map (dataviz reference palette, fixed hue order).
CATEGORIES = {
    "coast": {"label": "Coastal point / coastline", "color": "#123f7a"},
    "harbor": {"label": "Harbor town", "color": "#86b6ef"},
    "river_mouth": {"label": "River mouth", "color": "#98df8a"},
    "city": {"label": "City / inland settlement", "color": "#eb6834"},
    "river": {"label": "River source / confluence / bend", "color": "#2ca02c"},
    "mountain": {"label": "Mountain", "color": "#eda100"},
    "island": {"label": "Island", "color": "#e87ba4"},
    "lake": {"label": "Lake / inland water", "color": "#008300"},
    "": {"label": "Unclassified", "color": "#898781"},
}

# Categories that participate in coastline reconstruction (build_coastlines)
# as if they were "coast" - river mouths and harbor towns are each a
# distinct color for display, but they're still real points on the shore
# and stay part of the traced coastline, same as a plain cape.
_COASTLINE_CATEGORIES = ("coast", "river_mouth", "harbor")

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
# otherwise be caught by the coastal mouth pattern first. "quell" (not just
# "quelle") also catches "Quellgebiet" (source region/catchment) - "Rhenus
# (Quellgebiet)" and five more river-source entries had no exact "Quelle"
# substring and fell through to the default "city".
_RIVERFEAT_RE = re.compile(r"quell|einmündung|ursprung|zusammenfluss", re.IGNORECASE)
# Landmarks *along* a river's course - a bend, its midpoint, its upper/lower
# reach, or a delta fork/split - as opposed to "Mündung" (river mouth, i.e.
# actually on the coast). These are inland, but nothing in the word itself
# says so (unlike "Quelle"/"Ursprung" = source), so a river bend sitting in a
# sea-headed section (e.g. "Garumna (Mitte)", the Garonne's midpoint, in the
# same section as Aquitania's coastal capes) fell through to "coast" and got
# spliced into the middle of that coastal walk out of geographic order.
# One legitimate exception: a bend *in a gulf's own coastline* ("Elanitischer
# Golf (Biegung)") isn't a river feature, hence the golf/bay guard.
_RIVER_COURSE_RE = re.compile(r"\(mitte\)|biegung|abzweigung|aufteilung|oberlauf|unterlauf", re.IGNORECASE)
_GULF_RE = re.compile(r"golf|meerbusen|bucht", re.IGNORECASE)
_MOUTH_RE = re.compile(r"mündung", re.IGNORECASE)
_CAPE_RE = re.compile(r"^kap\b|spitze|vorgebirge|promont", re.IGNORECASE)
_HARBOR_RE = re.compile(r"\bhafen\b|portus", re.IGNORECASE)
_ESTUARY_RE = re.compile(r"ästuar", re.IGNORECASE)
# Note: matched *before* _CAPE_RE below - "Alpes (S-Spitzen)"/"(N-Spitzen)"
# ("Alps, southern/northern peaks") contains "Spitzen", the plural of
# "Spitze" (cape/headland - "Nordspitze" etc.), and was caught by the cape
# pattern before this check ran, connecting the Alps' two ends straight
# across Bavaria/Austria as if they were coastal points. Other ranges in
# the same catalogue section ("Abnoba-Gebirge (S-Spitzen)", "Sudeta-Gebirge
# (...)") already say "Gebirge" and were unaffected - only "Alpes" lacks a
# mountain-range word of its own.
#
# Split into two tiers because "Alpes"/"Alpen" alone is a weaker signal than
# a name actually suffixed "-Gebirge"/"-berg": ~50 catalogue entries like
# "Marianum-Gebirge (Mitte)" are genuinely a named mountain range's own
# midpoint citation and must always win. But "Rhodanus (Biegung südlich von
# Lugdunum, zu den Alpen hin)" ("...bend south of Lyon, toward the Alps")
# and "Licius (Oberlauf), Alpes Poeninae" ("...upper course, Pennine Alps")
# are river-course points that merely mention the Alps as a *location* -
# "Alpen"/"Alpes" here is incidental, not the entity's own name, and both
# were wrongly drawn as mountains instead of connected as river points. The
# bare "Alpes"/"Alpen" tier is therefore only trusted when the name isn't
# already a recognized river-course/source/mouth pattern. "Calpe" (Mons
# Calpe, the Rock of Gibraltar - topostext: "Calpe mountain and pillar of
# the Inner sea") is folded into the name-anchored tier too: a specific,
# unambiguous proper name for one mountain with no generic "-Gebirge"/
# "-berg" suffix of its own.
_MOUNTAIN_NAME_RE = re.compile(r"gebirge|-berg\b|^berg\b|\bcalpe\b", re.IGNORECASE)
_ALPS_BAREWORD_RE = re.compile(r"\balpes\b|\balpen\b", re.IGNORECASE)
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
    ("3.14", "11"),  # Kassiope/Ptychia/Korkyra + Kap Leukimma/Amphipagos/Phalakron - Corfu
    ("3.15", "23"),  # Kap Kenaion/Atalante/Aidepsos - Euboea (NW coast)
    ("3.15", "24"),  # Chalkis/Eretria/Amarynthos/Karystos/Geraistos - Euboea (cities)
    ("3.15", "25"),  # Kap Kaphereus/Budoros-Mündung/Kerinthos/Kap Phalassia/Kap Dion - Euboea (S/E coast)
    ("3.15", "27"),  # Koressos/Iulis/Karthaia - Kea (Cyclades)
    ("3.15", "28"),  # Ios/Polyaigos/Therasia/Delos/Oliaros/Kythnos/Rhene (Cyclades)
    ("3.15", "29"),  # Kap Phorbia + Stadt auf Mykonos (Cyclades)
    ("3.15", "30"),  # Andros/Tenos/Syros/Naxos/Paros/Siphnos + a 2nd "Kap Sunion" citation (Cyclades)
    ("3.15", "31"),  # Seriphos/Pholegandros/Sikinos (Cyclades)
    ("5.02", "29"),  # Kap Sigrion/Pyrra/Eresos/Mytilene/Methymna/Antissa - Lesbos
    ("5.02", "30"),  # Ikaria + Kap Histoi/Chios/Kap Phanaia/Samos/Kap Ampelos - Ikaria/Chios/Samos (+ a 2nd "Myndos" citation)
    ("5.02", "31"),  # Arkesine/Kos/Astypalaia (Cyclades/Dodecanese)
    ("5.02", "32"),  # Syme/Kasos (Dodecanese)
    ("5.02", "33"),  # Kap Thoanteion/Kap Ephialtion/Potidaion - Karpathos
    ("5.02", "34"),  # Kap des Pan/Kameiros/Lindos/Rhodos/Ielyssos - Rhodes
    ("6.07", "43"),  # Red Sea islands
    ("6.07", "45"),  # Red Sea islands incl. Dioskorides (Socotra)
    ("6.07", "46"),  # Sachalitic Gulf islands
    ("6.07", "47"),  # Persian Gulf islands incl. Tylos (Bahrain)
    ("7.01", "95"),  # Ganges-delta islands ("Heptanesia" = "seven islands")
    ("4.05", "75"),  # Aedonis/Tyndarische Klippen/Ainesippa/Phokussai/Pedonia - small islands/reefs off the Marmarica coast, Egypt
    # The following five were confirmed against topostext.org/work/209's
    # English translation, which states outright "the Ebuda islands...",
    # "the islands which are near Albion island...", etc. - independent of
    # our own Modern_location-based guessing.
    ("2.02", "11"),  # Ebuda (x2)/Ricina/Maleus/Epidium - the Hebrides, off Ireland's Ptolemaic coast
    ("2.02", "12"),  # Monaoeda/Mona/Edrus/Limnus - Isle of Man, Anglesey, and neighbours
    ("2.03", "31"),  # Scitis/Dumna/Orkaden - Skye, Lewis, Orkney
    ("2.03", "32"),  # Thule W/O/N/S/Mitte - the island Thule's five extremity points
    ("2.03", "33"),  # Tanatis/Counnus/Vectis - Thanet, and the Isle of Wight
    ("2.05", "10"),  # Londobris - the Berlengas, off Lusitania ("An island lying off Lusitania, Londobris")
    ("2.10", "21"),  # Agatha/Blasco/Stoechades/Lero - islands off Narbonensis (Agde island, Ile de Brescou, Iles d'Hyeres, Ile Ste-Marguerite)
}

# The same problem at single-point granularity: a lone island reference
# embedded in an otherwise-mainland section, where force-islanding the
# *whole* section (as above) would wrongly reclassify real mainland points
# alongside it. Book.map "3.14" section "06" is Akarnania's mainland coast
# (Ambrakia/Arta, Aktion/Actium, Alyzeia, the Acheloos' mouth) except for
# one entry - "Kap Leukas" (Cape Doukato, the southern tip of the island of
# Lefkada) - sitting in the middle of that mainland run and pulling the
# Epirus/Akarnania coastline out onto the island and back. Keyed by ref_id.
_ISLAND_POINT_OVERRIDES = {
    "3.14.06.05",  # Kap Leukas - Cape Doukato, island of Lefkada
}

# _ISLAND_APPENDIX_SECTIONS covers two structurally different things: a
# section that's one island's own detailed coastal walk (Corfu's section
# "11" - Kassiope, Ptychia, Korkyra, then three capes in catalogue order
# around the shore), and a section that's a *list* of several different
# islands (the Cyclades' section "28" - Ios, Polyaigos, Therasia, Delos...
# are seven different islands, not seven points on one island's coast).
# Connecting every point in an island-appendix section into one line would
# be right for the former and draw a nonsensical inter-island line for the
# latter - and gap size alone can't tell them apart, the same way it
# couldn't for loop-closing (see _NO_CLOSE_LOOP_TRAILS): Corfu's own
# capes sit 0.3-0.8 degrees apart, but so do plenty of *different*
# Cycladic islands in Ptolemy's own compressed coordinates. So island
# lines are opt-in, not automatic: only sections manually confirmed to be
# one island's own coastal walk are listed here, mapped to that island's
# name so sections describing the *same* island (Euboea's coast is told
# across three consecutive sections) merge into a single line. Everything
# else stays plotted as individual, unconnected island points.
_ISLAND_LINE_GROUPS: dict[tuple[str, str], str] = {
    ("3.14", "11"): "Corfu",
    ("3.15", "23"): "Euboea",
    ("3.15", "24"): "Euboea",
    ("3.15", "25"): "Euboea",
    ("5.02", "29"): "Lesbos",
    ("5.02", "33"): "Karpathos",
    ("5.02", "34"): "Rhodes",
}

# The mirror-image problem: sections manually verified to be inland cities
# despite a coastal-sounding section header, so the section-level fallback
# must NOT apply to them. "2.03" section "17" is headed "Hafenreicher Golf"
# ("harbor-rich gulf") but its actual points - Eboracum (York), Camulodunum
# (Colchester), Petuaria (Brough-on-Humber) - are inland Roman-Britain
# towns/legion camps, not capes or mouths. Spliced into the England
# coastline as "coastal" points, they connected East Anglia straight to
# Kent via a detour up to York and back.
_NONCOASTAL_EXCEPTION_SECTIONS = {
    ("2.03", "17"),  # Eboracum/Camulodunum/Petuaria - York/Colchester/Brough
}


_KAP_PREFIX_RE = re.compile(r"^kap\b", re.IGNORECASE)


def _classify_locality(
    name: str,
    section_is_coastal: bool,
    force_island: bool = False,
    force_island_point: bool = False,
    force_noncoastal: bool = False,
) -> tuple[str, str]:
    """Return (category, naming_observation) - the observation is the audit
    trail for *why* this category was picked, for the "naming_observation"
    column of the annotated dataset (see annotate_dataset.py)."""
    # A manually-verified island override - whole section or single point -
    # wins over everything else, including a name that otherwise reads as an
    # unambiguous cape ("Kap Leukimma" *is* a real cape - it's just a cape on
    # Corfu, not on the mainland coastline its section would otherwise be
    # spliced into).
    if force_island:
        return "island", "manually verified island-appendix section (_ISLAND_APPENDIX_SECTIONS)"
    if force_island_point:
        return "island", "manually verified individual island point amid an otherwise mainland section (_ISLAND_POINT_OVERRIDES)"
    if _KAP_PREFIX_RE.search(name):
        # A name that leads with "Kap" is unambiguously a cape - even when
        # it also carries a mountain-range aside, e.g. "Kap Oiarso,
        # Pyrene-Gebirge (NW-Ende)" (Cabo Higuer, right at the Spain/France
        # border - also happens to be where the Pyrenees end). Classifying
        # it "mountain" dropped it from the coastline entirely, leaving a
        # gap between Spain's Biscay coast and France's Atlantic coast that
        # this cape would otherwise have bridged.
        return "coast", "starts with 'Kap' (cape) - coastal regardless of any mountain-range aside"
    if _MOUNTAIN_NAME_RE.search(name):
        return "mountain", "matches mountain-range name pattern (Gebirge/-berg/Calpe)"
    is_river_like = _RIVERFEAT_RE.search(name) or _RIVER_COURSE_RE.search(name) or _MOUTH_RE.search(name)
    if _ALPS_BAREWORD_RE.search(name) and not is_river_like:
        return "mountain", "matches 'Alpes'/'Alpen' (bare, not also a river-course/source/mouth pattern)"
    if force_noncoastal:
        section_is_coastal = False
    if _RIVERFEAT_RE.search(name):
        return "river", "matches river-feature pattern (Quelle/Quellgebiet/Einmündung/Ursprung/Zusammenfluss)"
    if _RIVER_COURSE_RE.search(name) and not _GULF_RE.search(name):
        return "river", "matches river-course pattern (Mitte/Biegung/Abzweigung/Aufteilung/Oberlauf/Unterlauf), not a gulf bend"
    if _MOUTH_RE.search(name):
        return "river_mouth", "matches 'Mündung' (river mouth) - coastal, colored separately"
    if _CAPE_RE.search(name):
        return "coast", "matches cape pattern (Spitze/Vorgebirge/Promont)"
    if _HARBOR_RE.search(name):
        return "harbor", "matches harbor pattern (Hafen/Portus) - coastal, colored separately"
    if _ESTUARY_RE.search(name):
        return "coast", "matches estuary pattern (Ästuar)"
    if _GULF_RE.search(name):
        # A point literally named "Golf von X"/"X-Bucht"/"X-Meerbusen" is a
        # gulf/bay by definition - coastal regardless of whether its own
        # catalogue section's header happens to carry a recognized sea word
        # (found via topostext.org's English translation explicitly calling
        # "Dunum bay"/"Gabrantuicorum bay" a bay while our section-header
        # fallback missed both and defaulted them to "city" - 25 more points
        # across the whole catalogue had the same bug once checked).
        return "coast", "matches gulf/bay pattern (Golf/Bucht/Meerbusen)"
    if _ISLAND_RE.search(name):
        return "island", "matches 'Insel'/'Inseln' (island)"
    if _ISLAND_GROUP_RE.search(name):
        return "island", "name ends in '(N)' - a count-labelled island group"
    if _LAKE_RE.search(name):
        return "lake", "matches 'See'/'Palus' (lake/marsh)"
    if force_noncoastal:
        return "city", "manually verified non-coastal exception despite sea-headed section (_NONCOASTAL_EXCEPTION_SECTIONS)"
    if section_is_coastal:
        return "coast", "no specific keyword match; section header names a sea/ocean/gulf"
    return "city", "no specific keyword match; section not sea-headed (default)"


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
    category: str = ""  # "coast" | "harbor" | "river_mouth" | "city" | "river" | "mountain" | "island" | "lake" | "" (unclassified)
    ref_id: str = ""  # catalogue ID (book.map.section.item), used to reconstruct coastlines
    naming_observation: str = ""  # why _classify_locality picked this category (audit trail)
    feature_id: str = ""  # which drawn coastline this point belongs to, once resolved (see annotate_dataset.py)
    sequence_in_feature: int = -1  # draw order within feature_id, once resolved
    feature_closes_loop: bool = False  # if true, after the last point re-connect to the first (an island etc.)
    river_feature_id: str = ""  # which drawn river line this point belongs to, once resolved (separate from feature_id: a river mouth is on both a coastline and a river line)
    river_sequence_in_feature: int = -1  # draw order within river_feature_id, once resolved
    island_feature_id: str = ""  # which drawn island outline this point belongs to, once resolved (see _ISLAND_LINE_GROUPS)
    island_sequence_in_feature: int = -1  # draw order within island_feature_id, once resolved
    island_feature_closes_loop: bool = False  # if true, after the last point re-connect to the first

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


_ANNOTATED_CSV_FIELDS = [
    "ref_id",
    "name",
    "category",
    "book",
    "tabula",
    "modern_location",
    "recension",
    "lon_ptolemy",
    "lat_ptolemy",
    "naming_observation",
    "feature_id",
    "sequence_in_feature",
    "feature_closes_loop",
    "river_feature_id",
    "river_sequence_in_feature",
    "island_feature_id",
    "island_sequence_in_feature",
    "island_feature_closes_loop",
]


def write_annotated_csv(refs: list[Reference], path: Path) -> None:
    """Write the fully-resolved dataset: every point's category plus (for
    coastline points) its feature_id/sequence_in_feature/feature_closes_loop
    - drawing the map from this file needs no algorithm beyond "group by
    feature_id, sort by sequence_in_feature, connect the dots"."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_ANNOTATED_CSV_FIELDS)
        writer.writeheader()
        for ref in refs:
            writer.writerow(
                {
                    "ref_id": ref.ref_id,
                    "name": ref.name,
                    "category": ref.category,
                    "book": ref.book,
                    "tabula": ref.tabula,
                    "modern_location": ref.modern_location,
                    "recension": ref.recension,
                    "lon_ptolemy": ref.lon_ptolemy,
                    "lat_ptolemy": ref.lat_ptolemy,
                    "naming_observation": ref.naming_observation,
                    "feature_id": ref.feature_id,
                    "sequence_in_feature": ref.sequence_in_feature if ref.feature_id else "",
                    "feature_closes_loop": "1" if ref.feature_closes_loop else "",
                    "river_feature_id": ref.river_feature_id,
                    "river_sequence_in_feature": ref.river_sequence_in_feature if ref.river_feature_id else "",
                    "island_feature_id": ref.island_feature_id,
                    "island_sequence_in_feature": ref.island_sequence_in_feature if ref.island_feature_id else "",
                    "island_feature_closes_loop": "1" if ref.island_feature_closes_loop else "",
                }
            )


def load_annotated_csv(path: Path) -> list[Reference]:
    """Load a dataset already annotated by annotate_dataset.py - category
    and (for coastline points) feature_id/sequence_in_feature are read
    directly, not re-derived."""
    refs: list[Reference] = []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            refs.append(
                Reference(
                    name=row["name"],
                    book=row["book"],
                    tabula=row["tabula"],
                    lon_ptolemy=float(row["lon_ptolemy"]),
                    lat_ptolemy=float(row["lat_ptolemy"]),
                    source=path.name,
                    modern_location=row.get("modern_location", ""),
                    recension=row.get("recension", ""),
                    category=row.get("category", ""),
                    ref_id=row.get("ref_id", ""),
                    naming_observation=row.get("naming_observation", ""),
                    feature_id=row.get("feature_id", ""),
                    sequence_in_feature=int(row["sequence_in_feature"]) if row.get("sequence_in_feature") else -1,
                    feature_closes_loop=row.get("feature_closes_loop") == "1",
                    river_feature_id=row.get("river_feature_id", ""),
                    river_sequence_in_feature=int(row["river_sequence_in_feature"])
                    if row.get("river_sequence_in_feature")
                    else -1,
                    island_feature_id=row.get("island_feature_id", ""),
                    island_sequence_in_feature=int(row["island_sequence_in_feature"])
                    if row.get("island_sequence_in_feature")
                    else -1,
                    island_feature_closes_loop=row.get("island_feature_closes_loop") == "1",
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
        force_noncoastal = book_map_section in _NONCOASTAL_EXCEPTION_SECTIONS

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
            category, observation = _classify_locality(
                name,
                section_is_coastal,
                force_island=force_island,
                force_island_point=str(_id) in _ISLAND_POINT_OVERRIDES,
                force_noncoastal=force_noncoastal,
            )
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
                    category=category,
                    naming_observation=observation,
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

# Ptolemy sometimes opens a region's description with a boundary point
# ("this region extends south to the mouth of the Acheloos") *before* the
# region's own coastal enumeration begins - then cites that same point
# again, correctly, at the point in the walk where it's actually reached.
# Book.map "3.14" (Epirus/Akarnania) section "01" is a single-row section -
# "Acheloos-Mündung" - sitting alone right before the walk proper starts at
# "Akrokeraunische Berge" in section "02"; the same "Acheloos-Mündung" (same
# name, same coordinates) shows up again, correctly, as the walk's actual
# last point in section "06". Both citations are real edges under the
# ordinary catalogue-adjacency rule (the intro one sits within the 5-degree
# gap cap of Akrokeraunia), so node-collapsing merges the two "Acheloos"
# rows into one graph node with edges to *both* ends of the walk - turning
# an 11-point open coastal walk into a closed loop and drawing its very
# first line as a jump from the Akarnanian coast straight to the Albanian
# border. A general rule ("a single-row section right before the walk
# starts is always introductory") risks discarding real single-point
# coastal sections elsewhere, so this is a small, manually-verified
# exclusion instead: these ref_ids keep their normal category (they still
# plot as an ordinary river-mouth marker) but are skipped when building
# coastline edges, the same way a non-coastal row already is.
_COASTLINE_SKIP_REF_IDS = {
    "3.14.01.04",  # Acheloos-Mündung - introductory boundary citation, duplicated (correctly) at 3.14.06.07
}

# The final global stitching pass below (see _SAME_POINT_TOL_DEG * 2)
# reconnects two book.map trails only when their endpoints land within a
# tight tolerance - deliberately tight, so it only catches a genuine shared
# citation and doesn't reopen the cross-region guessing that grouping by
# book.map exists to prevent. That tolerance is occasionally *just* too
# tight for a real one: Epirus/Akarnania's coast (book.map "3.14") ends at
# the Acheloos' mouth, and Aetolia's (book.map "3.15") starts at "Kap einer
# Halbinsel" barely 0.12 degrees away - the same stretch of coast, split
# only because Ptolemy describes it under two different regional headings,
# but just outside the 0.1-degree window that would auto-stitch it. Rather
# than loosening that tolerance everywhere (and risking a false stitch
# elsewhere), specific endpoint pairs manually verified to be the same
# real-world hand-off are force-stitched regardless of the exact distance.
# Keyed by the two ref_ids, order doesn't matter.
_BOUNDARY_STITCH_REF_ID_PAIRS = {
    ("3.14.06.07", "3.15.02.05"),  # Acheloos-Mündung (end of Epirus/Akarnania) -> Kap einer Halbinsel (start of Aetolia)
    ("3.11.02.01", "3.13.09.03"),  # Nessos-Mündung (end of Thrace) -> Neapolis/Kavala (start of Macedonia) - the Nestos, a real Thrace/Macedonia border river
    ("3.13.05.03", "3.14.02.03"),  # Kelydnos-Mündung/Dukati (end of the Illyria fragment) -> Akrokeraunische Berge/Karaburun (start of Epirus) - the Ceraunian mountains, the real Illyria/Epirus border
    ("2.06.20.04", "2.10.02.07"),  # Clodianus-Mündung/Fluvià (end of Iberia's Mediterranean coast) -> Heiligtum der Venus/Cap Béar (start of Gaul's) - the real Spain/France Mediterranean border, a second Kap-Oiarso-style hand-off on the Mediterranean side
    ("4.01.07.06", "4.02.02.05"),  # Malua-Mündung/Moulouya (end of Mauretania Tingitana) -> Siga-Mündung/Tafna (start of Mauretania Caesariensis) - the real Morocco/Algeria border river
    ("4.02.11.06", "4.03.03.05"),  # Ampsaga-Mündung/Oued el-Kebir (end of Mauretania Caesariensis) -> Kap Treton/Bougaroun (start of Africa Proconsularis) - the real Algeria/Tunisia border river
}

# Two catalogue points are treated as "the same physical spot" (a shared
# corner where two separate coastal walks both start/end) if within this
# many degrees of each other.
_SAME_POINT_TOL_DEG = 0.05

# A traced coastline whose two loose ends land within this distance is a
# candidate closed loop (an island, or a peninsula walk that just didn't
# re-state its own starting point) - but distance alone isn't enough: an
# open coastal stretch's two ends can easily land within a few degrees of
# each other purely by chance (France's Atlantic coast, Aturus-Mündung to
# Liger-Mündung, is a real 6.9-degree-long walk whose ends happen to sit
# 3.9 degrees apart - closing it drew a diagonal straight back down through
# the country). What actually distinguishes a real loop is that a closing
# edge that short relative to how far the path travelled is closing a
# genuine loop; the same absolute distance relative to a *short* path is
# just two nearby-but-unconnected points. So the gap must also be a small
# fraction of the trail's own total length - Ireland's real loop closes a
# 1.3-degree gap over a 23-degree path (6%); France's false one would have
# closed a 3.9-degree gap over a 6.9-degree path (56%).
_CLOSE_LOOP_MAX_GAP_DEG = 6.0
_CLOSE_LOOP_MAX_GAP_RATIO = 0.3

# The ratio check above isn't perfectly separable: a genuine island closure
# and a false one can land at essentially the same ratio. Sardinia's real
# closure (Kap Hermaeum round to Kap Errebantium, book.map "3.03") sits at
# a 24.3% ratio - and Macedonia's mainland coast (Neapolis/Kavala down to
# the Spercheios river mouth near Thessaly, book.map "3.13") happens to
# close at the same 24.3%, even though it's a continuous mainland walk,
# not an island - "closing" it drew a diagonal line straight back up the
# country from Thessaly to Kavala. No ratio threshold can separate these
# two - one has to be excluded by hand. Keyed by (first ref_id, last
# ref_id) of the trail build_coastlines would otherwise close, verified
# against Modern_location/known ancient geography the same way as
# _ISLAND_APPENDIX_SECTIONS and _NONCOASTAL_EXCEPTION_SECTIONS.
_NO_CLOSE_LOOP_TRAILS = {
    ("3.13.09.03", "3.13.17.10"),  # Neapolis (Kavala) -> Spercheios-Mündung: mainland Macedonia/Thessaly coast, not an island
}

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


def _stitch_trails(
    trails: list[list["Reference"]],
    max_gap_deg: float = _STITCH_MAX_GAP_DEG,
    force_pairs: set[tuple[str, str]] | None = None,
) -> list[list["Reference"]]:
    """Greedily join trails whose nearest endpoints are within range - or,
    for an endpoint ref_id pair manually verified to be the same real-world
    hand-off (see _BOUNDARY_STITCH_REF_ID_PAIRS), regardless of the actual
    distance between them."""
    trails = [list(t) for t in trails]
    force_pairs = force_pairs or set()
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
                    forced = (pa.ref_id, pb.ref_id) in force_pairs or (pb.ref_id, pa.ref_id) in force_pairs
                    d = 0.0 if forced else _ref_dist(pa, pb)
                    if (forced or d <= max_gap_deg) and (best is None or d < best[0]):
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
            if ref.category not in _COASTLINE_CATEGORIES or ref.ref_id in _COASTLINE_SKIP_REF_IDS:
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
            polylines.append(trail_refs)

    # Adjacent book.map regions often re-cite the same boundary point in
    # both their catalogue entries (Kap Oiarso/Cabo Higuer, right at the
    # Spain/France border, closes both Iberia's "2.06" and Aquitania's
    # "2.07"). Grouping by book.map is what fixed Ireland/Britain wrongly
    # merging, but as a side effect it also stops two *genuinely* adjacent
    # regions' trails from ever being stitched, since each group is only
    # stitched against itself. A final global pass reconnects trails whose
    # endpoints are essentially the same point (not just nearby) - tight
    # enough to only catch real shared citations, not reintroduce
    # cross-region guessing - plus any pair manually verified to be a real
    # hand-off despite falling just outside that tolerance (see
    # _BOUNDARY_STITCH_REF_ID_PAIRS).
    polylines = _stitch_trails(polylines, max_gap_deg=_SAME_POINT_TOL_DEG * 2, force_pairs=_BOUNDARY_STITCH_REF_ID_PAIRS)

    final: list[list[Reference]] = []
    for trail_refs in polylines:
        first, last = trail_refs[0], trail_refs[-1]
        no_close = (first.ref_id, last.ref_id) in _NO_CLOSE_LOOP_TRAILS or (last.ref_id, first.ref_id) in _NO_CLOSE_LOOP_TRAILS
        if len(trail_refs) >= 4 and first is not last and not no_close:
            closing_gap = _ref_dist(first, last)
            path_length = sum(_ref_dist(trail_refs[i], trail_refs[i + 1]) for i in range(len(trail_refs) - 1))
            if closing_gap <= _CLOSE_LOOP_MAX_GAP_DEG and closing_gap <= _CLOSE_LOOP_MAX_GAP_RATIO * path_length:
                trail_refs = trail_refs + [first]
        final.append(trail_refs)

    return final


def assign_coastline_features(refs: list[Reference]) -> None:
    """Resolve every ambiguity build_coastlines has to reason about at
    runtime (which points connect, in what order, where a trail closes)
    into two plain data columns: `feature_id` and `sequence_in_feature`.

    Mutates the Reference objects in place. Once assigned and saved (see
    annotate_dataset.py), drawing a coastline is just "group by feature_id,
    sort by sequence_in_feature, connect the dots" - no graph, no distance
    thresholds, no stitching. The graph reconstruction in build_coastlines()
    still does the actual reasoning; this just records its answer as data
    instead of re-deriving it on every run.
    """
    trails = build_coastlines(refs)
    for trail_idx, trail in enumerate(trails):
        # A closed-loop trail repeats its first Reference as its last
        # (same object, so it can't hold two different sequence numbers).
        # Record the loop-closure as its own flag instead and number only
        # the trail's distinct points.
        closes_loop = len(trail) > 1 and trail[0] is trail[-1]
        points = trail[:-1] if closes_loop else trail
        feature_id = f"coastline_{trail_idx:03d}_{points[0].tabula}"
        for position, ref in enumerate(points):
            ref.feature_id = feature_id
            ref.sequence_in_feature = position
            ref.feature_closes_loop = closes_loop


def build_coastlines_from_features(refs: list[Reference]) -> list[list[Reference]]:
    """The trivial counterpart to build_coastlines(): once every point
    carries a resolved `feature_id`/`sequence_in_feature` (see
    assign_coastline_features and annotate_dataset.py), drawing coastlines
    needs no graph, no distance thresholds, and no stitching - just group
    by feature_id, sort by sequence_in_feature, and connect the dots in
    order. This is what map-drawing "should" be, per the catalogue's own
    category+sequence structure - all the ambiguity-resolution now lives in
    the annotated dataset as data, not in this function.
    """
    groups: dict[str, list[Reference]] = {}
    for ref in refs:
        if not ref.feature_id:
            continue
        groups.setdefault(ref.feature_id, []).append(ref)

    trails: list[list[Reference]] = []
    for points in groups.values():
        points.sort(key=lambda r: r.sequence_in_feature)
        if points[0].feature_closes_loop and len(points) >= 2:
            points = points + [points[0]]
        trails.append(points)
    return trails


def get_coastlines(refs: list[Reference]) -> list[list[Reference]]:
    """Trivial reconstruction (build_coastlines_from_features) if the
    dataset already carries resolved feature_id/sequence_in_feature - e.g.
    loaded from annotate_dataset.py's output - falling back to the
    from-scratch graph reconstruction (build_coastlines) for datasets that
    don't (the raw xlsx, or a plain CSV)."""
    if any(r.feature_id for r in refs):
        return build_coastlines_from_features(refs)
    return build_coastlines(refs)


# Categories that can be a step along a drawn river line.
_RIVER_LINE_CATEGORIES = ("river", "river_mouth")

# Strips a river-course/mouth suffix off a name to get the name shared by
# every point along one river's course - "Danuvius (Einmündung des Savus)"
# and "Danuvius-Quellen" both reduce to "Danuvius". Matched as a suffix
# (anchored to the end of the string) so an alternate name folded into the
# same parenthetical ("Vidua-Mündung (Udia-Mündung)") is stripped along
# with it rather than mistaken for part of the base name.
_RIVER_SUFFIX_RE = re.compile(
    r"-mündung\b.*$|-quellen?\b.*$|"
    r"\s*\([^)]*(?:mitte|biegung|abzweigung|aufteilung|teilung|einmündung|"
    r"zusammenfluss|ursprung|mündungsarm|mündung|quell|oberlauf|unterlauf)[^)]*\)\s*$",
    re.IGNORECASE,
)
# A generic placeholder ("Namenloser Fluss" - "unnamed river") reused for
# many unrelated rivers throughout the catalogue - never a real shared name,
# so never a safe grouping key.
_GENERIC_RIVER_NAME_RE = re.compile(r"namenlos", re.IGNORECASE)

# A river line breaks wherever consecutive points (in catalogue order) are
# further apart than this. Needed because the catalogue reuses common river
# names for entirely unrelated rivers - three separate catalogue entries are
# each named "Deva" (two in Roman Britain, one in Iberia, ~19 degrees apart)
# - and book-level grouping alone doesn't catch it, since a single real
# river can legitimately span several book.map entries (the Danube's course
# is told across three). There's no gap size that cleanly separates "long
# real jump" from "different river, same name": Asia's worst-distorted
# rivers (Indus, Ganges) have genuine internal jumps of ~18-22 degrees,
# overlapping the ~13-19 degree gaps seen between different same-named
# rivers (Deva, Rha, Lykos, Hippos). Given that overlap, the cap is set
# below it - erring toward splitting a genuine long-distance river into
# several shorter, individually-trustworthy lines rather than ever drawing
# a confident-looking connection between two unrelated rivers.
_RIVER_LINE_MAX_GAP_DEG = 10.0


def _river_base_name(name: str) -> str:
    """The name shared by every point along one river's course, with any
    course/mouth-position suffix stripped. Rows that name no river at all
    ("Biegung gegen Osten", contextually understood from a preceding row)
    or use the generic "Namenloser Fluss" placeholder reduce to something
    that never repeats, so they end up in their own single-point group and
    never get drawn as a line - there's nothing in the text alone to safely
    connect them to."""
    return _RIVER_SUFFIX_RE.sub("", name).strip()


def build_river_lines(refs: list[Reference]) -> list[list[Reference]]:
    """Connect river/river-mouth points that share a base name into a line
    tracing that river's course, in catalogue order - the same
    "categorization + sequence" approach as build_coastlines, just grouped
    by name instead of by graph edges (a river's points aren't laid out as
    one continuous coastal walk the way a shoreline is, but the catalogue
    does return to the same named river - mouth, bends, source - across its
    entries). Grouped by `book` (continent) as well as name, since a bare
    name isn't a safe key on its own (see _RIVER_LINE_MAX_GAP_DEG); split
    further wherever a gap is too large to be the same river.
    """

    def sort_key(ref: Reference) -> tuple:
        return tuple(int(p) if p.isdigit() else p for p in ref.ref_id.split("."))

    groups: dict[tuple[str, str, str], list[Reference]] = {}
    for ref in refs:
        if ref.category not in _RIVER_LINE_CATEGORIES or not ref.ref_id or not ref.is_plausible():
            continue
        base = _river_base_name(ref.name)
        if not base or _GENERIC_RIVER_NAME_RE.search(base):
            continue
        groups.setdefault((ref.source, ref.book, base), []).append(ref)

    lines: list[list[Reference]] = []
    for items in groups.values():
        items.sort(key=sort_key)
        # Ptolemy routinely re-cites a point already given earlier in a
        # river's course - a bend, confluence or mouth carried over as the
        # opening reference of the next book.map's continuation - the same
        # "shared boundary citation" pattern already handled for coastlines
        # (see _COASTLINE_SKIP_REF_IDS / _BOUNDARY_STITCH_REF_ID_PAIRS), just
        # showing up here as an in-sequence revisit instead of a bookend.
        # Drop any point that lands within _SAME_POINT_TOL_DEG of a point
        # already kept earlier in this river's sequence, before segmenting
        # by gap: a river's course never legitimately loops back on itself
        # the way a coastline can, so any revisit is safe to collapse. This
        # also covers genuine delta forks cited under two different
        # downstream names (e.g. Nanagunas "(Aufteilung zur Bindas-Mündung)"
        # / "(...Goaris-Mündung)") - both name the same physical split point,
        # so keeping it once loses no line geometry.
        deduped: list[Reference] = []
        for item in items:
            if any(_ref_dist(item, kept) <= _SAME_POINT_TOL_DEG for kept in deduped):
                continue
            deduped.append(item)
        items = deduped
        if len(items) < 2:
            continue
        run = [items[0]]
        for prev, cur in zip(items, items[1:]):
            if _ref_dist(prev, cur) > _RIVER_LINE_MAX_GAP_DEG:
                if len(run) >= 2:
                    lines.append(run)
                run = [cur]
            else:
                run.append(cur)
        if len(run) >= 2:
            lines.append(run)
    return lines


def assign_river_features(refs: list[Reference]) -> None:
    """Materialize build_river_lines()'s output as data, the same way
    assign_coastline_features() does for coastlines - into river_feature_id/
    river_sequence_in_feature rather than feature_id/sequence_in_feature, so
    a river-mouth point (part of both a coastline and a river line) can
    carry both memberships at once."""
    lines = build_river_lines(refs)
    for line_idx, points in enumerate(lines):
        feature_id = f"river_{line_idx:03d}_{_river_base_name(points[0].name)}"
        for position, ref in enumerate(points):
            ref.river_feature_id = feature_id
            ref.river_sequence_in_feature = position


def build_river_lines_from_features(refs: list[Reference]) -> list[list[Reference]]:
    """The trivial counterpart to build_river_lines(): group by
    river_feature_id, sort by river_sequence_in_feature."""
    groups: dict[str, list[Reference]] = {}
    for ref in refs:
        if not ref.river_feature_id:
            continue
        groups.setdefault(ref.river_feature_id, []).append(ref)

    lines: list[list[Reference]] = []
    for points in groups.values():
        points.sort(key=lambda r: r.river_sequence_in_feature)
        lines.append(points)
    return lines


def get_river_lines(refs: list[Reference]) -> list[list[Reference]]:
    """Trivial reconstruction if the dataset already carries resolved
    river_feature_id/river_sequence_in_feature, falling back to
    build_river_lines() otherwise - mirrors get_coastlines()."""
    if any(r.river_feature_id for r in refs):
        return build_river_lines_from_features(refs)
    return build_river_lines(refs)


def _island_line_group(ref: Reference) -> str | None:
    """Which _ISLAND_LINE_GROUPS island (if any) a point belongs to, by its
    (book.map, section) - or None if its section isn't one of the
    manually-verified single-island coastal walks."""
    parts = ref.ref_id.split(".")
    if len(parts) < 3:
        return None
    return _ISLAND_LINE_GROUPS.get((".".join(parts[:2]), parts[2]))


def build_island_lines(refs: list[Reference]) -> list[list[Reference]]:
    """Connect an island's own points into a line tracing its shore, in
    catalogue order - grouped by _ISLAND_LINE_GROUPS rather than a graph,
    since (unlike coastlines) there's no reliable distance-based way to
    tell one island's own coastal walk apart from a list of several
    different islands (see _ISLAND_LINE_GROUPS). Closes into a loop if the
    trail's two ends land close enough relative to its own length - the
    same check build_coastlines uses (_CLOSE_LOOP_MAX_GAP_DEG/_RATIO)."""

    def sort_key(ref: Reference) -> tuple:
        return tuple(int(p) if p.isdigit() else p for p in ref.ref_id.split("."))

    groups: dict[tuple[str, str], list[Reference]] = {}
    for ref in refs:
        if ref.category != "island" or not ref.ref_id or not ref.is_plausible():
            continue
        island = _island_line_group(ref)
        if island is None:
            continue
        groups.setdefault((ref.source, island), []).append(ref)

    lines: list[list[Reference]] = []
    for items in groups.values():
        if len(items) < 2:
            continue
        items.sort(key=sort_key)
        first, last = items[0], items[-1]
        closing_gap = _ref_dist(first, last)
        path_length = sum(_ref_dist(items[i], items[i + 1]) for i in range(len(items) - 1))
        if closing_gap <= _CLOSE_LOOP_MAX_GAP_DEG and closing_gap <= _CLOSE_LOOP_MAX_GAP_RATIO * path_length:
            items = items + [first]
        lines.append(items)
    return lines


def assign_island_features(refs: list[Reference]) -> None:
    """Materialize build_island_lines()'s output as data, the same way
    assign_coastline_features()/assign_river_features() do."""
    lines = build_island_lines(refs)
    for line_idx, trail in enumerate(lines):
        closes_loop = len(trail) > 1 and trail[0] is trail[-1]
        points = trail[:-1] if closes_loop else trail
        feature_id = f"island_{line_idx:03d}_{_island_line_group(points[0])}"
        for position, ref in enumerate(points):
            ref.island_feature_id = feature_id
            ref.island_sequence_in_feature = position
            ref.island_feature_closes_loop = closes_loop


def build_island_lines_from_features(refs: list[Reference]) -> list[list[Reference]]:
    """The trivial counterpart to build_island_lines(): group by
    island_feature_id, sort by island_sequence_in_feature."""
    groups: dict[str, list[Reference]] = {}
    for ref in refs:
        if not ref.island_feature_id:
            continue
        groups.setdefault(ref.island_feature_id, []).append(ref)

    lines: list[list[Reference]] = []
    for points in groups.values():
        points.sort(key=lambda r: r.island_sequence_in_feature)
        if points[0].island_feature_closes_loop and len(points) >= 2:
            points = points + [points[0]]
        lines.append(points)
    return lines


def get_island_lines(refs: list[Reference]) -> list[list[Reference]]:
    """Trivial reconstruction if the dataset already carries resolved
    island_feature_id/island_sequence_in_feature, falling back to
    build_island_lines() otherwise - mirrors get_coastlines()."""
    if any(r.island_feature_id for r in refs):
        return build_island_lines_from_features(refs)
    return build_island_lines(refs)


def _is_annotated_csv(path: Path) -> bool:
    """Distinguish an annotate_dataset.py output from a plain
    Ptolemy-Geography-schema CSV by its header - the former carries
    "feature_id", the latter never does."""
    with path.open(newline="", encoding="utf-8") as fh:
        header = fh.readline()
    return "feature_id" in header


def _load_csv_auto(path: Path) -> list[Reference]:
    return load_annotated_csv(path) if _is_annotated_csv(path) else load_csv(path)


def load_inputs(paths: list[Path]) -> list[Reference]:
    refs: list[Reference] = []
    for p in paths:
        if p.is_dir():
            data_files = sorted(p.glob("*.csv")) + sorted(p.glob("*.xlsx"))
            if not data_files:
                print(f"warning: no *.csv/*.xlsx files found in directory {p}", file=sys.stderr)
            for data_file in data_files:
                refs.extend(load_xlsx(data_file) if data_file.suffix == ".xlsx" else _load_csv_auto(data_file))
        elif p.suffix == ".xlsx":
            refs.extend(load_xlsx(p))
        else:
            refs.extend(_load_csv_auto(p))
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

    coastlines = get_coastlines(plausible)
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
            folium.PolyLine(coords, color=CATEGORIES["coast"]["color"], weight=4, opacity=0.85).add_to(coast_layer)

    river_lines = get_river_lines(plausible)
    river_position: dict[str, tuple[int, int]] = {}
    for line_idx, line in enumerate(river_lines):
        for i, ref in enumerate(line):
            river_position.setdefault(ref.ref_id, (line_idx, i))

    if river_lines:
        river_layer = folium.FeatureGroup(name=f"Rivers ({len(river_lines)} lines)").add_to(fmap)
        for line in river_lines:
            coords = [(r.lat_modern, r.lon_modern) for r in line]
            folium.PolyLine(coords, color=CATEGORIES["river_mouth"]["color"], weight=2, opacity=0.8).add_to(river_layer)

    island_lines = get_island_lines(plausible)
    island_position: dict[str, tuple[int, int]] = {}
    for line_idx, line in enumerate(island_lines):
        for i, ref in enumerate(line):
            island_position.setdefault(ref.ref_id, (line_idx, i))

    if island_lines:
        island_layer = folium.FeatureGroup(name=f"Island outlines ({len(island_lines)})").add_to(fmap)
        for line in island_lines:
            coords = [(r.lat_modern, r.lon_modern) for r in line]
            folium.PolyLine(coords, color=CATEGORIES["island"]["color"], weight=3, opacity=0.85).add_to(island_layer)

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
        river_line_info = ""
        if ref.ref_id in river_position:
            river_idx, river_pos = river_position[ref.ref_id]
            river_line_info = f"River line #{river_idx}, position #{river_pos}<br>"
        island_line_info = ""
        if ref.ref_id in island_position:
            island_idx, island_pos = island_position[ref.ref_id]
            island_line_info = f"Island outline #{island_idx}, position #{island_pos}<br>"
            seq_label = seq_label or str(island_pos)
        popup_html = (
            f"<b>{html.escape(ref.name)}</b><br>"
            f"{modern_line}"
            f"{category_line}"
            f"{seq_line}"
            f"{river_line_info}"
            f"{island_line_info}"
            f"Map ID: {html.escape(ref.ref_id) or '?'} "
            f"&mdash; Book {html.escape(ref.book) or '?'}, {html.escape(ref.tabula) or 'unlabelled table'}<br>"
            f"Ptolemy coords: {ref.lon_ptolemy:.2f}° (Ferro), {ref.lat_ptolemy:.2f}°{recension_line}<br>"
            f"Modern approx.: {ref.lat_modern:.3f}, {ref.lon_modern:.3f}<br>"
            f"<i>source: {html.escape(ref.source)}</i>"
        )
        color = CATEGORIES[ref.category]["color"]
        is_coast_family = ref.category in _COASTLINE_CATEGORIES or ref.ref_id in island_position
        marker = folium.CircleMarker(
            location=[ref.lat_modern, ref.lon_modern],
            radius=8 if is_coast_family else 5,
            color=color,
            weight=2,
            fill=True,
            fill_color=color,
            fill_opacity=0.85,
            popup=folium.Popup(popup_html, max_width=320),
            tooltip=f"#{seq_label} {ref.name} ({ref.ref_id})" if is_coast_family else f"{ref.name} ({ref.ref_id})",
        )
        marker.add_to(clusters[ref.category])
        if is_coast_family and seq_label:
            folium.Marker(
                location=[ref.lat_modern, ref.lon_modern],
                icon=folium.DivIcon(
                    html=(
                        f'<div style="font-size:10px;font-weight:bold;color:#0b0b0b;'
                        f'text-shadow:0 0 2px #fff,0 0 2px #fff,0 0 2px #fff,0 0 2px #fff;'
                        f'transform:translate(8px,-8px);white-space:nowrap;">{seq_label}</div>'
                    )
                ),
            ).add_to(clusters[ref.category])
        if ref.category == "island" and ref.ref_id not in island_position:
            # No known coastal walk for this island - a single citation, or
            # one entry in a list of several different islands (see
            # _ISLAND_LINE_GROUPS). A real cartographer working from just
            # one reported position wouldn't have left a bare point either -
            # they'd still sketch a small schematic island there. This
            # circle is exactly that: a stylistic placeholder, not a real
            # coastline (its size carries no geographic meaning).
            folium.Circle(
                location=[ref.lat_modern, ref.lon_modern],
                radius=7000,
                color=CATEGORIES["island"]["color"],
                weight=1.5,
                fill=True,
                fill_color=CATEGORIES["island"]["color"],
                fill_opacity=0.25,
            ).add_to(clusters[ref.category])

    _add_legend(fmap, plausible)
    folium.LayerControl(collapsed=False).add_to(fmap)
    output.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(output))
    print(
        f"plotted {len(plausible)} geographical reference(s) "
        f"({len(coastlines)} coastline segments, {len(river_lines)} river lines, "
        f"{len(island_lines)} island outlines) -> {output}"
    )


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
