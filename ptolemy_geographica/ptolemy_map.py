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
    "harbor": {"label": "Harbor town", "color": "#2ca02c"},
    "river_mouth": {"label": "River mouth", "color": "#6ec6ff"},
    "city": {"label": "City / inland settlement", "color": "#eb6834"},
    "river": {"label": "River source / confluence / bend", "color": "#6ec6ff"},
    "mountain": {"label": "Mountain", "color": "#eda100"},
    "island": {"label": "Island", "color": "#e87ba4"},
    "lake": {"label": "Lake / inland water", "color": "#6ec6ff"},
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
# substring and fell through to the default "city". "ausfluss" (outflow)
# is the same kind of river-origin point, just phrased for a river that
# starts by draining a lake rather than rising from a spring - "Padus
# (Ausfluss aus Lacus Larius)" (topostext: "the head of the river at
# Lario lake").
_RIVERFEAT_RE = re.compile(r"quell|einmündung|ursprung|zusammenfluss|ausfluss", re.IGNORECASE)
# Landmarks *along* a river's course - a bend, its midpoint, its upper/lower
# reach, or a delta fork/split - as opposed to "Mündung" (river mouth, i.e.
# actually on the coast). These are inland, but nothing in the word itself
# says so (unlike "Quelle"/"Ursprung" = source), so a river bend sitting in a
# sea-headed section (e.g. "Garumna (Mitte)", the Garonne's midpoint, in the
# same section as Aquitania's coastal capes) fell through to "coast" and got
# spliced into the middle of that coastal walk out of geographic order.
# One legitimate exception: a bend *in a gulf's own coastline* ("Elanitischer
# Golf (Biegung)") isn't a river feature, hence the golf/bay guard.
# "teilung" (bare, not just "-aufteilung") catches four more delta-fork
# citations along the Danube's own branching mouths ("Ister (Teilung des
# nördlichsten Armes)", "Ister (Teilung)" x2, "Ister (1. Teilung bei
# Noviodunum)") that had fallen through to the default `city` - checked
# against the whole catalogue first: every other "teilung" hit is already
# an "-aufteilung" delta-fork citation elsewhere (the Nile's own five
# delta divisions, four more river forks in India), so broadening to the
# bare word introduces no false positives.
_RIVER_COURSE_RE = re.compile(r"\(mitte\)|biegung|abzweigung|aufteilung|teilung|oberlauf|unterlauf", re.IGNORECASE)
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
# "-berg" suffix of its own. "Skardon" (confirmed by topostext: "the point
# at Skardon mountain", "Mt. Skardon") is the same case - a specific proper
# name with no generic suffix - and safe to match as a bare word since
# "Skardona" (a different, unrelated city and island in the same section)
# doesn't satisfy the trailing \b. "Namenlose(r) Berg(e)" ("unnamed
# mountain(s)") is the mountain-side counterpart of "Namenloser Fluss" -
# five citations across Illyria and Arabia of a peak with no proper name of
# its own - matched as a phrase rather than added to the bare-word tier,
# since a bare "\bberg\b" would also catch a river point that merely
# mentions a mountain as its location (the same problem _MOUNTAIN_LOCATION_REF_RE
# guards against below). "Karpaten" (the Carpathians, topostext: "the
# beginning of Mt. Karpatos", "Mt. Karpata") is the same specific-proper-
# name case again - three re-citations of the same boundary point (all at
# the identical coordinate, so no line to draw regardless of category).
_MOUNTAIN_NAME_RE = re.compile(
    r"gebirge|-berg\b|^berg\b|\bcalpe\b|\bskardon\b|\bkarpaten\b|namenlose[rs]?\s+berge?\b", re.IGNORECASE
)
_ALPS_BAREWORD_RE = re.compile(r"\balpes\b|\balpen\b", re.IGNORECASE)
# A third, more specific case of the same problem the two tiers above guard
# against: a river's source/mouth/confluence point routinely names the
# mountain range it rises from or passes as its *location*, not its own
# identity - "Namenloser Fluss (Quelle am Arbita-Gebirge)" ("unnamed river,
# source at the Arbita mountains"), "Narmades-Quellen im Vindion-Gebirge"
# ("...source in the Vindion mountains"). Unlike the bare "Alpes"/"Alpen"
# case, these carry a full "-Gebirge" suffix and would otherwise win even
# the strong, name-anchored tier above, mis-plotting 31 river points as
# mountains across Book 7 (India). Distinguished from a genuine range point
# like "Marianum-Gebirge (Mitte)" (which also matches a river-course keyword
# via "(Mitte)"/"(Biegung)" and must NOT be reclassified) by *where* the
# range name sits: as the object of "am"/"im"/"vom"/"von"/"zum" ("at/in/
# from/to the ... mountains") rather than as the point's own leading name.
_MOUNTAIN_LOCATION_REF_RE = re.compile(r"\b(?:am|im|vom|von|zum)\s+[\w\-\s]*?(?:gebirge|berg)\b", re.IGNORECASE)
# A fourth tier, weaker still: "Berg"/"Berge" as its own separate word
# ("Goldener Berg", "Sarmatische Berge (S-Ende)", "Rasende Berge") rather
# than hyphenated onto a proper name ("-Gebirge"/"-berg\b" above) or at the
# very start ("^berg\b"). Found via topostext explicitly calling these
# "Golden mountain"/"the Mainomena mountains" while the catalogue's own
# `city` fallback had them uncategorized. Guarded twice, both times to
# avoid disturbing a point that's *already* doing real work as a coastal
# landmark: never overrides a point whose section is itself sea-headed
# (Athos, cited only as "Athos, ein Berg" with no "-Gebirge"/"-berg" of its
# own, ends a real stretch of Aegean coastline) or that also matches a
# more specific coastal pattern (cape/gulf/harbor/estuary - "Akrokeraunische
# Berge (Spitze)", "Schwarze Berge (Endpunkt am Meer)" on the Red Sea, both
# genuine coastline points where a range happens to end at the sea, the
# same reasoning _KAP_WORD_RE already uses). And, like the two tiers
# above, never overrides a genuine river point merely naming a mountain as
# its location - the same _MOUNTAIN_LOCATION_REF_RE guard.
_MOUNTAIN_BAREWORD_BERG_RE = re.compile(r"\bberge?\b", re.IGNORECASE)
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
# "Lacus" (Latin for lake) is a separate naming convention from "See"/
# "Palus" used only for the four Cisalpine Gaul lakes along the Padus/Doria
# river system (Lacus Larius/Como, Lacus Poeninus, Lacus Benacus/Garda) -
# bare "Lacus Benacus" had no keyword to match at all and fell through to
# the default "city".
_LAKE_RE = re.compile(r"\bsee[n]?\b|\bpalus\b|\blacus\b", re.IGNORECASE)
# The lake-side counterpart of _MOUNTAIN_LOCATION_REF_RE - distinguishes a
# river point merely naming a lake as its *location* from a genuine lake
# citation. Load-bearing for "Nil (Vereinigung der Flüsse aus Nil-Seen)" -
# the Nile's own confluence point, naming the lakes its tributaries come
# from, not a lake itself - which the plural "Seen" broadening above would
# otherwise catch (the three Cisalpine Gaul river/lake pairs, e.g. "Padus
# (Ausfluss aus Lacus Larius...)", don't need the guard here: "Ausfluss"/
# "Einmündung" already send them to "river" via _RIVERFEAT_RE earlier).
_LAKE_LOCATION_REF_RE = re.compile(r"\b(?:am|im|vom|von|zum|aus|des)\s+[\w\-\s]*?(?:see|seen|palus|lacus)\b", re.IGNORECASE)

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
    # Found by the systematic topostext-disagreement review (2026-07-30):
    # the *other* Ionian islands, each cited once (not a coastal walk of
    # any single one, so no _ISLAND_LINE_GROUPS entry - just the "list of
    # several different islands" shape _ISLAND_APPENDIX_SECTIONS exists
    # for). Section "12": Kephallenia ("Kephallenia island, with a city of
    # the same name...its northernmost promontory" / "the southern
    # promontory" - both capes stay `island` too, the same as Corfu's own
    # capes above), Erikusa, Skopelos, Leukas ("Leukas island"). Section
    # "13": Echinaden ("the Echinades islands"), Ithake ("in which a city
    # of that name"), Lotoa ("Letoa island"), Zakynthos ("in which a city
    # of the same name"). All were sitting in `city`.
    ("3.14", "12"),
    ("3.14", "13"),
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
    ("2.11", "34"),  # Scandia W/O/N/S - the island Scandia's four extremity points (topostext: "This island is itself properly called Scandia"), the same shape as Thule's five points above
    ("2.16", "14"),  # Issa/Tragurium/Pharia/Korkyra Melaina/Melite - the Dalmatian islands off the Croatian coast (Vis/Trogir/Hvar/Korcula/Mljet), each a single citation merging the island with its city - topostext: "Off Dalmatia are the islands Issa with city...Tragourion with city...Pharia with city...Melite island" - the same shared-name shape as Iulia Caesarea/Tenedos, not the multi-city-per-island shape of neighbouring Liburnia (2.16.13, Apsorros/Kourikta/Skardona, each with *two* named cities and correctly staying `city`)
    ("3.03", "08"),  # Ilva/Nymphaea/Diabate/Ficaria/Hermaea + the already-"-Insel" points - the islands around Sardinia (topostext: "The islands around Sardinia are: Phintonos island...")
    ("3.04", "16"),  # Didyme/Hikesia/Erikodes/Phoinikodes/Euonymos/Lipara/Strongyle + Hephaistos-Insel - the islands around Sicily (topostext: "the islands located around Sicily...are: Didyme island...")
    ("3.04", "17"),  # Ustika/Osteodes/Phorbantia/Aigusa/Hiera/Pakonia + Aiolos-Insel - more islands around Sicily, continuing 3.04.16
    ("3.10", "17"),  # Borysthenis + Achilles-Insel - the two islands off Lower Moesia (topostext: "the so-called Borysthenes island...and Achilleos or Leuke island")
    ("3.16", "23"),  # Strophaden/Prote/Sphagia/Theganusa/Kythera/Aigila/Salamis/Aigine - the islands adjoining the Peloponnese (topostext: "Islands adjoining the Peloponnese: the Strophades...")
    ("3.17", "11"),  # Kaudos/Letoa/Dia/Kimolos/Melos - the islands adjacent to Crete (topostext: "Islands adjacent to Crete Klaudos island...")
    ("4.01", "16"),  # Paina/Erytheia - islands off Mauritania Tingitana in the Outer Ocean
    ("4.03", "44"),  # Hydras/Galata/Drakontios/Aigimoros/Larunesen/Anemussa/Lopadusa/Aithusa - islands along the coast of Africa (topostext: "Islands along the coast of Africa, which are near the coast: Hydras...")
    ("4.03", "46"),  # Misynos/Pontia/Gaia - three more islands off Africa
    ("4.04", "14"),  # Myrmex + Aphrodite-Insel bzw. Laia - the two islands off Cyrenaica (topostext: "The islands by this country are: Myrmex island...Laia or Aphrodite island")
    ("4.05", "77"),  # Saspeirene/Aphrodite-Insel/Agathon-Insel - the islands in the Arabian bay (topostext: "In the Arabian bay are these islands: Sappeirene...")
    ("4.06", "33"),  # Kerne + Hera-/Autolala-Insel - islands off Libya in the Western Ocean
    ("4.07", "36"),  # Astarte/Altar der Athene/Gypsites/Myron (+ already-island Gomadeon) - islands "near Ethiopia below Egypt in the Arabian Gulf". Four of these (33-36) had been wrongly strung onto the end of coastline_025_AF04 by the coastline graph, the same spurious-tail pattern as Paena/Erythia earlier - reclassifying correctly truncates that coastline back to its real endpoint, Kap Bazion (4.07.28.06)
    ("4.07", "37"),  # Thrisitides/Magon/Daphnine/Akanthine/Makaria/Orneon (+ already-island Kathathrai/Chelonitides) - more of the same Arabian Gulf island list, continuing 4.07.36
    ("4.07", "39"),  # Mondu - the island in the Bay of Avalites
    ("4.07", "40"),  # Amiku/Myrsiake (+ already-island Menan) - the islands next to Aromata
    ("5.01", "15"),  # Thynias bzw. Daphnusa/Klippen Erythinoi (+ already-island Kyaneen) - islands off Bithynia
    ("5.05", "10"),  # Krambusa/Attelebusa - the two islands lying off Pamphylia
    ("5.14", "07"),  # Kleiden/Karpasische Inseln - the two island groups off Cyprus's own coast (topostext: "The islands on its coast are those called Cleides..." then "the Karpasian islands") - "Karpasische Inseln" already matched `_ISLAND_RE` on its own name ("Inseln"), but "Kleiden" (Cleides), a bare proper name, fell through to `city`
    ("5.15", "27"),  # Arados/Tyros - the islands off Syria (topostext: "Islands off Syria: Arados...and Tyros just offshore") - this "Tyros" is the offshore islet citation, distinct from the mainland coastal city of the same name already catalogued at 5.15.05
    ("6.04", "08"),  # Tabiana/Sophtha + already-island "Insel des Alexander bzw. Arakia" - the islands adjacent to Persis (topostext: "Islands adjacent to Persis: Tabiana...Sophtha...Alexandrou or Arakia")
    ("6.08", "15"),  # Sagdana/Vorochtha - the islands lying off Karmania in the Persian Gulf (topostext: "The islands lying off Karmania are, in the Persian Gulf, Sagdana...Vorochtha") - both had been wrongly strung onto the *start* of coastline_045_AS06 by the coastline graph (the real coastal walk begins at the next section, 6.08.04's river mouths), the same spurious-tail pattern as Paena/Erythia earlier
    ("6.08", "16"),  # Polla/Karminna/Liba - "In the Indian sea Palla or Polla...Karminna...Liba island", three more islands off Karmania continuing 6.08.15's list - these three had been strung onto the *end* of that same coastline_045_AS06, after its real endpoint (the Gedrosia/Karmania boundary point, 6.08.10.01)
    ("7.02", "29"),  # Argyre*/Iabadiu (W-Ende and SO-Ende) - the island Iabadios (topostext: "The island of Iabadios...It lies in [W]...and the eastern limit lies in [E]"), its two extent points in the same shape as Thule/Scandia's W/O/N/S citations
    ("7.04", "11"),  # Vangana/Kanathra/Orneon/Aigidion/Monache/Ammine - the group of islands in front of Taprobane (topostext: "In front of Taprobane lies a group of islands...Ouangalia...Kanathra...Aigidion...Orneon...Monache...Ammine")
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
    "3.05.31.02",  # Alopekia bzw. Tanais - the island off the Tanais' mouth (topostext: "An island lies off the mouth of the Tanais river, Alopekia or Tanais island")
    "4.02.35.02",  # Iulia Caesarea - the island off Mauritania Caesariensis' capital, sharing its name (topostext: "An island lies off Iulia Caesarea, with the same name, with a city")
    "4.03.45.01",  # Cercina - an island in a section (4.03.45) that also names Gerra/Meninx, two cities *on* a different island (Lotophagitis) with no coordinate of its own - not safe to force-island the whole section
    "4.03.47.02",  # Kossura (Pantelleria) - one of three real islands in a section (4.03.47) that also names Melite's own peninsula/shrines, not islands themselves
    "4.03.47.03",  # Gaulos (Gozo)
    "4.03.47.05",  # Melite (Malta)
    "4.05.76.02",  # Pharos - the island of the Alexandria lighthouse; its section (4.05.76) also names "Argaiu", an unrelated point not confirmed as an island
    "5.02.28.03",  # Tenedos - a single citation covering both the island and "a city of the same name" (topostext), the same shared-name shape as Iulia Caesarea
    "6.09.08.02",  # Talka - "a sea island off it [Hyrkania] called Talka" (topostext), a lone island citation amid an otherwise mainland-coastal book.map
    "7.01.94.03",  # Barake - "Islands lying near the part of India which projects into the ocean in the Gulf of Kanthi: Barake" (topostext), a single-island section
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
    ("4.01", "10"),  # Pyrrhon-Ebene - an inland plain embedded in a tribal-boundary description (topostext: "...below whom are the Nectiberes; and next is the Pyrrhon Plain...Below these are the Zegrenses..."), not a coastal point
    # Found in the same edge-by-edge Black Sea sweep as the newest
    # _COASTAL_APPENDIX_SECTIONS entries, but the opposite problem: section
    # "5.09.11"'s own header happens to include "Hyrkanisches Meer" (the
    # Caspian) as the far end of a *boundary-line* description ("Thence it
    # extends along Iberia, with the Sarmatian Gates...thence along Albania
    # to the limit on the Hyrkanian sea" - topostext) - Sarmatia-in-Asia's
    # inland border with Iberia/Albania, not a continuation of its Black Sea
    # coast, which topostext explicitly ends one section earlier ("The limit
    # on the side of Kolchis is at", 5.09.10 - left alone, correctly coastal).
    # "Sarmatische Pforten" (the Sarmatian/Caucasian Gates, a mountain pass)
    # had been swept into `coast` by the header match and strung onto the
    # real coastline via catalogue-order adjacency, a spurious ~2 degree
    # detour east from the Kolchis boundary point that had nothing to do
    # with the shore.
    ("5.09", "11"),
    # Found by the systematic whole-catalogue self-intersection review
    # (2026-07-30): three sections in the Maritime Alps (book.map "3.01",
    # sections 41-43) are each headed "Meeralpen" ("Maritime Alps") -
    # matching `_COASTAL_HDR_RE`'s bare "meer" the same way "Hyrkanisches
    # Meer" did above, even though their content is inland Alpine tribal
    # cities (topostext: "Of the Nerusi in the Maritime Alps Vintium", "Of
    # the Suetri in the Maritime Alps Salinae", "Of the Vedianti in the
    # Maritime Alps Cemenelum"), not points on the actual coast - the real
    # Ligurian-sea coastal walk runs through the separate, correctly-headed
    # sections "3.01.01"/"3.01.02" (Varus-Mündung, Nicaea, Hercules-Hafen,
    # ...). Left as coastal, these four points' edges cut back across the
    # real coastline near Nicaea.
    ("3.01", "41"),
    ("3.01", "42"),
    ("3.01", "43"),
}

# The mountain-side counterpart of _ISLAND_APPENDIX_SECTIONS: a section
# that's purely a *list* of named mountains/peaks, each cited by its own
# proper name with no "-Gebirge"/"-berg" suffix of its own to catch by
# keyword ("Of the named mountains the center of Bertiskos lies at...Mt.
# Bermion...Mt. Olympos...", "Mountains in the Peloponnese Pholoe...and
# Stymphalos...") - the same "no shared pattern to regex on, so it has to
# be an explicit allow-list" reasoning as the island appendix. Confirmed by
# topostext's own section headers; more such sections likely exist
# elsewhere in the catalogue, not yet found because their books haven't
# been cross-referenced yet.
_MOUNTAIN_APPENDIX_SECTIONS = {
    ("3.13", "19"),  # Bertiskos/Bermion/Berketesios/Kitarion/Olympos/Ossa/Pelion/Othrys - Macedonia's named mountains, including Mt. Olympus itself
    ("3.16", "14"),  # Pholoe/Stymphalos/Minthe/Taygetos/Kronion/Zarex - the Peloponnese's named mountains
    ("4.01", "12"),  # Diur (+ the already-"-Gebirge" Durdon-Gebirge W/O-Ende) - Mauritania Tingitana's named mountains (topostext: "The noteworthy mountains in this land are the so-called Diur...")
    ("5.01", "10"),  # Orminios/Mysischer Olymp - Bithynia's named mountains
    ("5.02", "13"),  # Ida/Killaion/Temnon/Dindymos(W-Ende)/Sipylos/Tmolos/Mesogis/Mykale/Kadmos/Mimas/Phoinix - "the named mountains in Asia" (topostext: "These are the named mountains in Asia, of which the central points are: Mt. Ida...")
    ("5.03", "04"),  # Kragos - Lykia's named mountain
    ("5.04", "04"),  # Oligas(Gigas)/Dindymos(O-Ende)/Huegel von Kelainai - Galatia's named mountains, including Dindymos' other end (see 5.02.13 above - same range, re-cited across the book.map boundary)
    ("5.13", "05"),  # Paryardes(NW/SO-Ende)/Udakespes(Mitte)/Anti-Tauros in Gross-Armenien(Mitte)/Abos(Mitte)/Gordyaische Berge(Mitte) - Greater Armenia's named mountains (topostext: "The named mountains of Armenia are the Moschika...and Paryardes...and the Oudakespes mountain...and the part of Antitauros...and the so-called Abos mountain...and the Gordyaia mountains...")
    ("5.15", "08"),  # Pieria(Mitte)/Kassios(Mitte)/Libanos(W/O-Ende)/Antilibanos(W/O-Ende)/Alsadamos(Mitte)/Hippos(Mitte) - Syria's named mountains (topostext: "The noteworthy mountains in Syria are Pieria mountain, midpoint...and Kassios mountain...and Libanos...and Antilibanos...and beside Arabia Deserta Mt. Alsadamos...Near Judaia Mt. Hippos...")
    ("5.18", "02"),  # Masion(Mitte)/Singaras - Mesopotamia's named mountains (topostext: "The named mountains in Mesopotamia are Masion mountain, midpoint...and Singaras")
    ("6.02", "04"),  # Zagros(Mitte)/Orontes(Mitte)/Iasonion(Mitte) + already-"-Gebirge" Koronos(W/O-Ende) - Media's named mountains (topostext: "The most important mountains of Media are the Zagros, midpoint...the Orontes, midpoint...the Iasonion, midpoint...and the western part of Korono...")
}

# The coastal-walk counterpart of _NONCOASTAL_EXCEPTION_SECTIONS' mirror
# image: sections manually verified to be a genuine continuation of a
# coastal walk despite a section header that names a *tribe*, not a sea -
# so _COASTAL_HDR_RE never fires for them and every plain-named point falls
# through to the default "city". Found by inspection of a rendered map: the
# whole Arabian side of the Red Sea (book.map "6.07", Arabia Felix) was
# missing its coastline entirely, replaced by an unconnected scatter of
# "city" points, while the opposite African shore (book.map "4.07") was
# correctly traced - reported by the user as "as if one coastline is
# missing, full of little islands". Ptolemy's own catalogue narrates this
# coast tribe-by-tribe ("In the country of the Kinaidokolpitans...", "The
# Kassanite country...", "Country of the Elisarans...") rather than
# re-stating "Arabian Gulf"/"Red Sea" at every section, and only sections
# 02, 08 (and a few later ones already caught by _GULF_RE on their own
# points) happen to carry an explicit sea-name header - topostext's English
# translation confirms the whole span 02-19 is one continuous coastal
# enumeration ("border of the Arabian Gulf in the inmost part of the
# Elanite gulf, Onne" opens it; "Country of the Adramitans", "Sachalites",
# "In the narrows of the Persian Gulf" carry it on down the Arabian Sea
# coast and round into the Persian Gulf; section 20, the named-mountains
# appendix, is where it ends - already handled by _MOUNTAIN_APPENDIX_SECTIONS
# above). Forcing section_is_coastal here is safe even for the sections that
# also contain real river mouths/sources (05's "Baitios-Quellen", 10's
# "Prion-Mündung"/springs) since _RIVERFEAT_RE/_MOUTH_RE are checked before
# the section-level coastal fallback ever gets a turn - only the plain
# harbor-town citations that had nothing else to match on are affected
# (Kopar, Zabram, Thebai, Badeo, Mamala, Muza, Okelis and more - several of
# them well-attested real Red Sea ports).
_COASTAL_APPENDIX_SECTIONS = {
    ("6.07", "02"),
    ("6.07", "03"),
    ("6.07", "05"),
    ("6.07", "06"),
    ("6.07", "07"),
    ("6.07", "08"),
    ("6.07", "09"),
    ("6.07", "10"),
    ("6.07", "11"),
    ("6.07", "12"),
    ("6.07", "13"),
    ("6.07", "14"),
    ("6.07", "15"),
    ("6.07", "16"),
    ("6.07", "17"),
    ("6.07", "18"),
    ("6.07", "19"),
    # Same pattern, found the same way (user-reported gap in a rendered
    # map), on the Black Sea: Paphlagonia/Pontus's own coast (book.map
    # "5.04") is headed by "Pontos Euxeinos" (Greek for "Black Sea") only
    # once, at the very start of the book.map (section "01") - every
    # section actually enumerating the coast is headed by a place name
    # instead ("Kytoros", section "02"'s own header), so almost every
    # plain-named point fell through to `city`, including two of antiquity's
    # best-known Black Sea ports, Sinope and Amisos (Sinop/Samsun today).
    # The real cape "Kap Karambis" and the two river mouths already caught
    # via `_MOUTH_RE` were the only survivors.
    ("5.04", "02"),
    ("5.04", "03"),
    # Bithynia's own coast (book.map "5.01"): section "03" (Astakos, Olbia,
    # Nikomedeia, on the Gulf of Astakos/Izmit) sits directly between two
    # promontory citations (section "02"'s Akritas cape, section "04"'s
    # Posideion cape) with no sea-header of its own - a bay indentation in
    # the same shape as Arabia's Adulitic Bay detour, not the genuinely
    # inland cities of section "13" (which topostext itself introduces as
    # "The following are the inland cities" - correctly left as `city`,
    # not added here).
    ("5.01", "03"),
    # Sarmatia-in-Asia's own coast (book.map "5.09", the Sea of Azov/Kerch
    # strait/NE Black Sea shore down to the Colchis border) - previously
    # documented below (see the Coverage section of the README) as
    # "confirmed, not fixed" for lack of an override mechanism at the time;
    # fixed now that one exists. Real Bosporan-kingdom port towns
    # (Phanagoria, Hermonassa, Sindikos - topostext explicitly calls the
    # latter a "harbor") were sitting in `city` between coast/river_mouth
    # points precisely because most of this coastal walk's own points never
    # individually matched a keyword and the section headers are Greek
    # place/tribe names, not `_COASTAL_HDR_RE`'s German sea words.
    ("5.09", "02"),
    ("5.09", "03"),
    ("5.09", "04"),
    ("5.09", "05"),
    ("5.09", "06"),
    ("5.09", "08"),
    ("5.09", "09"),
    ("5.09", "10"),
    # The root cause behind all three Black Sea fixes above, generalized:
    # `_COASTAL_HDR_RE` only recognizes *German* sea words ("Meer"/"Golf"/
    # "Ozean"/...), but this catalogue routinely heads a Pontic-region
    # section with the *Greek* proper noun instead ("Pontos Euxeinos",
    # "Propontis", "Kimmerischer Bosporos") - which never matches. Reported
    # by the user as points "hopping and dancing" around the Black Sea,
    # Bosphorus and Thrace/Bithynia - not a classification problem exactly
    # (each point's own coordinate was always right), but a *connectivity*
    # one: with real waypoints along the shore sitting in `city` instead of
    # `coast`, the graph had nothing to connect but the few points that did
    # happen to match some other keyword, forcing long, geographically
    # senseless edges between them instead of the short, orderly hops a
    # complete coastal walk would draw. Checked every section headed by a
    # Greek Pontic sea-name across the whole catalogue (via a regex on the
    # header text) and triaged each one individually - most were already
    # fine (either already `coast`, or genuinely inland, like `5.06.09`-
    # `11`'s "Pontos" *province* name, Amaseia and neighbours, nowhere near
    # the shore) or too low-impact/uncertain to act on without further
    # verification (single boundary-point sections). These sections had a
    # real, topostext-confirmed gap:
    ("3.06", "02"),  # Crimea/Chersonesus Taurica's coast (topostext: "...in the Pontus: Dandake...Chersonesos...") - Eupatoria (Yevpatoria), Dandake etc.
    ("3.06", "04"),  # The Cimmerian Bosphorus/Kerch strait's own coast (topostext: "On the Cimmerian Bosphorus, Tyriktake...Pantikapaia...") - the Bosporan Kingdom's capital
    ("3.11", "03"),  # Thrace's own Black Sea coast, its boundary hand-off from Lower Moesia
    ("3.11", "05"),  # Byzantion itself - the missing hinge point between Thrace's Black Sea coast (section "04") and its Propontis coast (section "06")
    ("3.11", "06"),  # Thrace's Propontis coast (topostext: "Next, in Propontis...") - Selymbria, Herakleia, Bisanthe, the Long Wall, Paktye
    ("5.01", "02"),  # Bithynia's Bosphorus-mouth coast - Chalkedon (Kadıköy) and Trarion
    ("5.01", "04"),  # Bithynia's coast continuing past the Gulf of Astakos - Prusias (Modern_location: Gemlik) and Apameia (Modern_location: Mudanya), both real Marmara Sea ports; Askania-See stays `lake` regardless (matched by _LAKE_RE before the section-level fallback ever gets a turn)
    ("5.01", "05"),  # Bithynia's own coast continuing east - Artake (topostext: "Artake kome")
    ("5.02", "02"),  # Mysia/Troad's Propontis coast (topostext: "In the Propontis...Kyzikos...Parion...") - two more well-attested ancient ports
    ("5.06", "03"),  # Pontus Galaticus' coast (topostext: "...the plain by Phanagoria: Themiskyra...") - legendary home of the Amazons, a real coastal city
    ("5.06", "04"),  # Pontus Polemoniacus' coast (topostext: "Of Polemonian Pontos...") - Polemonion and neighbours
    ("5.06", "05"),  # Pontus Cappadocicus' coast (topostext: "...near Sidene: Ischopolis...") - Kerasous/Giresun, Pharnakia, on the way to Trapezous/Trebizond
    # A fourth round, from a systematic edge-by-edge sweep of every coastline
    # in the wider Black Sea/Sea of Azov region (every consecutive-point gap
    # over ~1.8 degrees, checked one at a time against topostext and the raw
    # section headers, per the user's request after the third round still
    # left some "non-neighbour" connections) - the same header-language gap
    # as the fixes above, just two sections these earlier passes hadn't
    # reached yet:
    ("3.06", "03"),  # Crimea's coast continues past Kap Korax/Istrianos-Mündung with no header of its own - Theodosia (Feodosia) and Nymphaion were sitting in `city`, missing from the traced coastline entirely (topostext: "...Istrianos river mouth, Theodosia, Nymphaion" - directly between the two already-coastal sections either side)
    ("3.05", "11"),  # Sarmatia-in-Europe's coast opens with "Neue Festung" (topostext: "isthmus...toward the Karkinites river, Neon Teichos") - the walk's own starting point, sitting in `city`
    ("3.05", "12"),  # ...continuing (topostext, by name match - this book.map's own section numbering runs well ahead of topostext's: "Leianon city...Akra city...Gerros river mouth...Kremnoi city") - Leianon and Akra were `city`
    ("3.05", "13"),  # ...continuing to the Tanais/Don (topostext: "...Agaron promontory...Hygreis city...Karoia kome...western mouth of the Tanais") - Kneme, Hygreis, Karoia were `city`
    # The Thracian Chersonese's own coast (book.map "3.12", a self-contained
    # peninsula loop distinct from mainland Thrace's - see topostext,
    # book 3 map 11 section 9, oddly filed under Thrace's own map rather
    # than getting its own: "the part of Propontis on that side as far as
    # Kallipolis...on the west...Kardia city...Mastousia promontory...on
    # the south...the city Elaious...the protruding promontory...on the
    # East by the Hellespont, on which are the cities: Koila, Sestos, next
    # the above-mentioned Kallipolis" - a closed loop back to its own
    # start). Section "04"'s own header is "Hellespont" (Greek proper
    # noun, not `_COASTAL_HDR_RE`'s German sea words) - Koila and Sestos
    # were sitting in `city`, the two points the user spotted "floating in
    # the water" north of Kap gleich daneben, unconnected to the rest of
    # the peninsula's own coastline.
    ("3.12", "04"),
    # Lower Moesia's own coast resuming past the Danube delta (book.map
    # "3.10" section "14", no header of its own) - topostext confirms the
    # real sequence is a clean coastal run: "7.1 northernmost mouth of the
    # Istros until the mouth of the Borysthenes...7.2 Axiakos river
    # mouth / 7.3 Physke city / 7.4 Tyras river mouth / 7.5 Hermonaktos
    # village / 7.6 Arpis city" - matching our own item order exactly
    # (`.02` Axiakes-Mündung, `.03` Physke, `.04` Tyras-Mündung, `.05`
    # Dorf des Hermonax, `.06` Harpis). Found by the user pointing at
    # Axiakes-Mündung looking disconnected in a rendered map - it was
    # technically connected already (to Panysus-Mündung, a real but large
    # jump across an inland digression - see _COASTLINE_HARD_BREAKS'
    # sibling comments), but the walk continuing *past* it dead-ended at
    # Tyras-Mündung because Physke/Hermonax/Harpis, the points that should
    # carry it onward, were sitting in `city`.
    ("3.10", "14"),
    # Found by the systematic catalogue-wide header scan (2026-07-30): the
    # Troad's own Hellespont shore (book.map "5.02" section "03") is the
    # same "Hellespont" (Greek, not `_COASTAL_HDR_RE`'s German sea words)
    # gap as the Thracian Chersonese case above, just on the opposite
    # shore of the strait - topostext confirms a clean coastal run: "on the
    # Hellespont: Abydos / mouth of the Simoeis river / Dardanon / mouth of
    # the Skamander river / Sigeion promontory". Abydos and Dardanon were
    # sitting in `city`; the two river mouths and Kap Sigeion were already
    # correctly `river_mouth`/`coast` via their own name keywords.
    ("5.02", "03"),
    # Found by the systematic topostext-disagreement review (2026-07-30):
    # Marmarica/Cyrenaica's own Mediterranean coast (book.map "4.05",
    # sections "03" through "07") continues directly from section "02"'s
    # own coastal declaration ("on the north by the Egyptian sea. This
    # seacoast is thus described: In the nomes of Marmarike are: Aziris
    # village...") without repeating a sea-word header of its own -
    # topostext confirms one continuous run of harbor/promontory/village
    # citations straight through ("Antipyrgos harbor...Big Petras
    # harbor...Panormos harbor...Ainesisphyra harbor...Selinous
    # harbor...Graias Gony, harbor...Gyzis or Zygis harbor...Phoinikos
    # harbor...Leukaspis harbor..."), matching the catalogue's own item
    # order. The "Kap"-named capes in this stretch were already correctly
    # `coast`; the plain-named harbor towns between them (Antipyrgos,
    # Skythranios, Petra Megale, Panormos, Ainesisphyra, Zygris, Chettaia,
    # Zagylis, Selinus, Graias Gony, Zygis, Leuke Akte, Antiphrai,
    # Leukaspis) fell through to `city` for lack of a keyword of their own.
    ("4.05", "03"),
    ("4.05", "04"),
    ("4.05", "05"),
    ("4.05", "06"),
    ("4.05", "07"),
    # The same gap recurs on Egypt's Red Sea coast: section "13" is headed
    # "Arabischer Golf" ("Arabian Gulf", the Red Sea) and correctly
    # coastal, but sections "14" and "15" continue the same walk south
    # without repeating that header - topostext confirms an unbroken run
    # ("above-mentioned inmost point of the gulf...Arsinoe, Klysma
    # castle, Drepanon promontory, Myos hormos, Philoteras harbor, Mt.
    # Aias" straight into "Leukos harbor, Mt. Akabe, Nechesia, Mt.
    # Samaragdos, Lepte akra, Berenike, Mt. Pentadaktylon, Bazion
    # promontory" - the same mountains-ending-at-the-shore shape already
    # established for Mt. Athos/Akrokeraunia, correctly staying coastal
    # here too rather than being reclassified). Arsinoe, Klysma, Myos
    # Hormos and Philoteras (section 14) were sitting in `city`.
    ("4.05", "14"),
    ("4.05", "15"),
    # Epirus's own Ionian coast (book.map "3.14"): section "01" is headed
    # "Ionisches Meer" and correctly coastal, but sections "02" and "04"
    # continue the same walk without repeating that header - topostext
    # confirms an unbroken run ("Chaonia Orikon" straight into "Panormos
    # harbor...Onchesmos harbor...Kassiope harbor", then "Bouthroton
    # gulf...Pelodes harbor" between the two already-coastal capes Kap
    # Poseidion/Kap Thyamis). Orikon, Panormos, Onchesmos, Kassiope
    # (section 02) and Buthroton, Schlammhafen (section 04) were sitting
    # in `city`.
    ("3.14", "02"),
    ("3.14", "04"),
    # A wide batch found by the same systematic topostext-disagreement
    # review, each independently confirmed the same way: a plain-named
    # harbor town or headland sitting in `city`, whose section has no
    # sea-word header of its own but whose topostext citation both names
    # it a harbor/port *and* sits in an unbroken run of coastal citations
    # (river mouths, capes, other harbors) either side of it in the same
    # section - the same "province/tribe name instead of sea name" header
    # gap already fixed many times this session, just not yet swept
    # outside the regions checked so far:
    ("4.03", "04"),  # Africa: "Holcachites gulf...Tacatye...Lesser Collops...Siur port"
    ("3.03", "02"),  # Sardinia, explicitly "Description of the coast...west side": Nymphaeum/Korakodes harbors among capes and river mouths
    ("3.03", "03"),  # Sardinia, "Description of the southern side": Sulci/Bithia harbors among capes
    ("3.03", "04"),  # Sardinia, "Description of the eastern side": Sulpicius/Olbian harbors among capes and river mouths
    ("3.04", "07"),  # Sicily: river mouths and promontories either side of Kaukana harbor
    ("3.15", "07"),  # Attica: "Peiraieus...Ilissos river outlet...Mounychias harbor...Hyphormos harbor...Sounion promontory..."
    ("3.16", "03"),  # Korinthia: "Sanctuary of Hera of Corinth...Lechaion port...Asopos river outlet..."
    ("3.16", "05"),  # Achaia proper: "Aigeira...Erineos harbor...Rhion promontory..."
    ("3.16", "06"),  # Elis: "Kyllene port...Peneios river outlet...Chelonitis headland..."
    ("3.16", "11"),  # Argolis: "Astron...Inachos river outlet...Nauplia port...Skyllaion promontory..."
    ("3.16", "13"),  # Argolis/Korinthia continuation: "...Speiraion promontory...Kenchreai port...Schoinous harbor"
    ("3.17", "02"),  # Crete, "Description of the western side": Korykos headland/city into Rhamnous harbor
    ("3.17", "05"),  # Crete, "Description of the east side": Sammonion promontory into Minoa harbor
    ("4.01", "02"),  # Mauretania Tingitana: a run of river mouths ending at Rusibis harbor
    ("4.01", "03"),  # Mauretania Tingitana continuation: river mouths and capes around Mysokaras harbor
    ("4.02", "02"),  # Mauretania Caesariensis: "Malva river mouth, Great promontory...Gypsaria harbor..."
    ("4.03", "12"),  # Africa: a city-at-the-limit/promontory run including Pisidon and Garapha harbors
    ("4.04", "03"),  # Cyrenaica (Syrtis): "Automalax fort...Drepanon promontory...Diarroia harbor...Tower of Herakles..."
    ("4.04", "05"),  # Cyrenaica: "Phykous promontory...Apollonia [naval station]...Naustathmon harbor...Zephyrion promontory..."
    ("5.06", "06"),  # Pontus (Kissian coast): "Opious...Rizous harbor...Athenon promontory..."
    ("6.08", "09"),  # India: "Gulf of Paragon...Derane Billa...Kophanta harbor...river mouth..."
    # Found by an independent second pass: building a standalone category
    # guess purely from topostext's own wording (category_check.py, no
    # access to the catalogue's category, name, or any exception list)
    # and comparing it to the catalogue's category surfaced a few more
    # instances of the same gap the batch above missed:
    ("3.01", "21"),  # Picenum's own Adriatic coast: "Castrum...Cupra Maritima...mouth of the Truentini river...Potentia...Numana...Ancona"
    ("3.13", "03"),  # Illyria: "west by the Ionian Sea from Dyrrachion...per the following description"..."Panyasos river outlet...Apollonia...Aoos river outlet...Aulon city and port"
    ("4.07", "05"),  # Barbaria/Cape Guardafui coast: "Bazion promontory...Chersonesos...Deep harbor...Dioskoroi harbor...Lookout of Demeter promontory"
    ("5.02", "10"),  # Doris/Caria: "Skopia promontory...Halikarnassos...Keramos...Knidos city and promontory"
    ("3.04", "09"),  # Sicily's own east coast: "Syrakousai...Tauros promontory...Katane...Symaithos river mouth...Tauromenion...Argennon promontory...Messene in the strait"
    ("4.03", "05"),  # Numidia/Africa coast at Cape Bon: "Hippo promontory...Stoborrum promontory...Aphrodisium...Hippo Regius...Rubricatus river mouth...Thabraca"
    ("5.02", "06"),  # Aiolis' own coast: "Kaine promontory...Elaia...Myrina...Hydra promontory...Kyme...Phokaia...mouth of the Hermos river"
    ("7.04", "05"),  # Taprobane's own coast: "Dagana...Cape of Dionysos...Ketaion Cape...Mouth of the river Barakes...the haven of Mardos"
    # The Levant's own coast (book.map "5.15", Syria/Phoenicia/Palestine):
    # found by the user noticing Sidon, Tyros and Byblos plotting inland
    # in a rendered map ("real coastal cities... doesn't topostext give
    # context that these sit along the water?"). Section "02" is headed
    # "Syrisches Meer" and correctly coastal (Alexandreia bei Issos,
    # Myriandros, Rhosos...), but sections "03" through "05" continue the
    # same walk without repeating that header - topostext confirms one
    # unbroken run: "mouth of the Orontes river...Poseidion...Herakleia...
    # Laodikeia...Gabala...Paltos...Balaneai" straight into "Phoinike:
    # mouth of Eleutheros river...Simyra...Orthosia...Tripolis...Theou
    # prosopon promontory...Botrys...Byblos...mouth of the Adonis river"
    # straight into "Berytos...mouth of the Leon river...Sidon...Tyros...
    # Ekdippa...Ptolemais...Sykaminon...Karmelos mountain...Dora...mouth
    # of the Chorseos river" - matching the catalogue's own item order
    # exactly. Section "06" resumes with Judaea's own inland boundary
    # description (Grenzpunkt entries, correctly `city`) - the gap is
    # cleanly bounded to these three sections.
    ("5.15", "03"),
    ("5.15", "04"),
    ("5.15", "05"),
}

# The mountain-side counterpart of _ISLAND_POINT_OVERRIDES: a lone mountain
# reference embedded in an otherwise-coastal section, where force-mountaining
# the whole section (as above) would wrongly pull its genuine coastal points
# out of their coastline. Book.map "3.13" section "11" is Chalkidike's coast
# (Panormos harbor, "Athos, ein Berg"/"Athos, Kap und Berg" ending the
# Athos peninsula, Nymphaion promontory...) except for one entry - "Athos
# (Mitte)", the *midpoint* of the mountain rather than a coastal point on
# it - that the "(Mitte)" river-course pattern was catching first, with
# nothing in the bare name "Athos" itself to redirect it. Keyed by ref_id.
_MOUNTAIN_POINT_OVERRIDES = {
    "3.13.11.05",  # Athos (Mitte) - the mountain's own midpoint, not a coastal point
    "5.06.08.02",  # Argaios (NW-Ende) - Kappadokia's named mountains, section 5.06.08, force-mountain unsafe there since the same section also has 5.06.08.04, a genuine Euphrat/Melas river confluence point mentioned as an aside during the range's own boundary description
    "5.06.08.03",  # Argaios (SO-Ende)
    "5.06.08.08",  # Anti-Tauros W (W-Ende)
    "5.06.08.09",  # Anti-Tauros W (O-Ende)
    "5.06.08.10",  # Anti-Tauros O (W-Ende)
    "5.06.08.11",  # Anti-Tauros O (O-Ende)
    "6.07.20.01",  # Zames (Mitte) - one of Arabia Felix's named mountains (topostext: "the so-called Zames, midpoint..."), section 6.07.20 unsafe to force whole since it also has "Wasser der Styx (Quelle)", a genuine spring/river-source point mentioned as an aside during the range's own description
    "6.07.20.03",  # Klimax - a bare-name mountain in the same list, confirmed repeatedly elsewhere in the same chunk ("beyond Klimax mountain", "extending as far as Klimax mountain") rather than by a marker on this citation itself
}

# The river-side counterpart of _ISLAND_POINT_OVERRIDES/_MOUNTAIN_POINT_OVERRIDES:
# a lone river-boundary reference embedded in an otherwise-coastal section
# (book.map "2.04" section "03" is headed "Baliarisches Meer"), where
# nothing in the bare name itself ("Anas", the river's own proper name -
# no "Mündung"/"Quelle"/course-keyword) tells the classifier it's a river
# point rather than a plain coastal one. Found by the user spotting it as
# one of two odd-looking dots sitting inland in Spain on a rendered map.
_RIVER_POINT_OVERRIDES = {
    "2.04.03.04",  # Anas (Grenzpunkt Baetica, Lusitania, Tarraconensis) - a boundary marker up the river Anas/Guadiana itself (topostext: "Where the river touches the border of Lusitania", Modern_location "Guadiana"), not a coastal point - already excluded from the coastline's own edges (_COASTLINE_SKIP_REF_IDS) but still carried the wrong point category/color
    # Found by the user auditing the GeoPackage export directly in QGIS
    # (2026-07-30) - the same shape, a different river: "Durius (Grenzpunkt
    # Lusitania, Tarraconensis)" (Modern_location "Douro", topostext: "The
    # part of the river where Lusitania begins") is a boundary marker up
    # the Durius/Douro, not a point on the coast - prompted a full sweep
    # of every "Grenzpunkt"/"Endpunkt" name still categorized `coast`
    # (see `_NONCOASTAL_POINT_OVERRIDES` below for the rest of that sweep).
    "2.05.01.06",
}

# The second of the two odd-looking Spain dots the user flagged is not
# river- or lake-related at all: "Baetica (Ostende am Baliarischen Meer)"
# ("Baetica's own eastern end at the Balearic sea", topostext: "there
# along the border of Tarraconensis to where the Balearic sea ends") is a
# province-to-sea boundary *endpoint*, the same "Grenzpunkt" shape as the
# many already-non-coastal boundary markers elsewhere (5.03.01.06 etc.,
# all `city`) - just sitting in a section whose header happens to be
# coastal, with nothing in its own name to redirect it. Cited twice,
# verbatim (2.04.03.07, then again as 2.06.12.05 orienting the next
# province's own section) - both listed. The point-level counterpart of
# `_NONCOASTAL_EXCEPTION_SECTIONS` (which operates on a whole section).
_NONCOASTAL_POINT_OVERRIDES = {
    "2.04.03.07",
    "2.06.12.05",
    # The rest of the "every remaining Grenzpunkt/Endpunkt still marked
    # `coast`" sweep prompted by the Durius find above: of 27 such points,
    # 23 are genuinely coastal (topostext explicitly names a sea/gulf as
    # the boundary's own endpoint - "the other on the Adriatic at",
    # "termination at the sea", "the inner recess of the...Maisanites
    # Gulf" - or, for the Arabia Felix "Endpunkt am Meer" mountain cases,
    # sit smoothly in-line with their coastal neighbours' own coordinates,
    # the same Athos/Akrokeraunia shape already confirmed this session)
    # and left untouched. These three are pure land-boundary descriptions
    # with no sea/gulf mentioned anywhere in their citation, or explicitly
    # contrasted with a *different*, genuinely coastal sibling point:
    "2.16.01.04",  # Grenzpunkt (Illyricum, Pannonia Superior) - topostext: "Illyria is bounded on the north by the two Pannonias...whose midpoint toward the limit point of Upper Pannonia at" - the *inland* end of a line whose text explicitly names a second, different end "on the Adriatic" (2.16.01.05, correctly left coastal) - this one is the land end, not the sea end
    "6.14.01.06",  # Grenzpunkt (beide Skythien, unbekanntes Land) - topostext: "Scythia within Imaos is bounded on the west by Sarmatia...on the north by an unknown land...on the east by Mount Imaos" - a pure Central-Asian land-boundary description, no sea mentioned at all
    "5.19.01.04",  # Grenzpunkt (Arabia Deserta, Babylonien, Mesopotamien) - topostext's own fuller citation (5.18.1.2): "On the south by the remaining part of the Euphrates river, along Arabia Deserta to the limit point at" - a river-following boundary marker (the same Anas/Durius shape, just without a clean single-river attachment to force `river` instead), well inland of the same walk's own two genuinely coastal points a few steps later (5.19.01.11/.13, both explicitly "the Persian Gulf")
}


# "Kap" (cape) as a bare word anywhere in the name, not just as a leading
# prefix - the catalogue names a cape many ways ("Nördliches Kap", "Heiliges
# Kap", "Grosses Kap am Anfang des Golfes", "X, ein Kap", "Athos, Kap und
# Berg"), and only a minority happen to lead with the word. Checked the
# whole catalogue before broadening past the prefix-only match: every one
# of the ~30 non-leading "Kap" mentions found this way is the point's own
# identity, not an incidental aside (unlike "Alpen"/"-Gebirge" mentioned as
# a river point's mere location) - so no location-reference guard is needed
# here the way _MOUNTAIN_LOCATION_REF_RE guards the mountain tiers.
_KAP_WORD_RE = re.compile(r"\bkap\b", re.IGNORECASE)


def _classify_locality(
    name: str,
    section_is_coastal: bool,
    force_island: bool = False,
    force_island_point: bool = False,
    force_noncoastal: bool = False,
    force_mountain: bool = False,
    force_mountain_point: bool = False,
    force_coastal: bool = False,
    force_river_point: bool = False,
) -> tuple[str, str]:
    """Return (category, naming_observation) - the observation is the audit
    trail for *why* this category was picked, for the "naming_observation"
    column of the annotated dataset (see annotate_dataset.py)."""
    if force_coastal:
        # A manually-verified coastal-appendix section (see
        # _COASTAL_APPENDIX_SECTIONS) - the header-based section_is_coastal
        # guess missed it because the header names a tribe, not a sea.
        # Applied this early so it participates like any other
        # section_is_coastal=True in every check below (river/mountain/lake
        # keywords still win first - only the plain-city fallback changes).
        section_is_coastal = True
    # A manually-verified island override - whole section or single point -
    # wins over everything else, including a name that otherwise reads as an
    # unambiguous cape ("Kap Leukimma" *is* a real cape - it's just a cape on
    # Corfu, not on the mainland coastline its section would otherwise be
    # spliced into).
    if force_island:
        return "island", "manually verified island-appendix section (_ISLAND_APPENDIX_SECTIONS)"
    if force_island_point:
        return "island", "manually verified individual island point amid an otherwise mainland section (_ISLAND_POINT_OVERRIDES)"
    if force_mountain:
        return "mountain", "manually verified mountain-appendix section (_MOUNTAIN_APPENDIX_SECTIONS)"
    if force_mountain_point:
        return "mountain", "manually verified individual mountain point amid an otherwise coastal section (_MOUNTAIN_POINT_OVERRIDES)"
    if force_river_point:
        return "river", "manually verified individual river-boundary point amid an otherwise coastal section (_RIVER_POINT_OVERRIDES)"
    if _KAP_WORD_RE.search(name):
        # A name containing "Kap" is unambiguously a cape - even when it
        # also carries a mountain-range aside, e.g. "Kap Oiarso,
        # Pyrene-Gebirge (NW-Ende)" (Cabo Higuer, right at the Spain/France
        # border - also happens to be where the Pyrenees end). Classifying
        # it "mountain" dropped it from the coastline entirely, leaving a
        # gap between Spain's Biscay coast and France's Atlantic coast that
        # this cape would otherwise have bridged.
        return "coast", "contains 'Kap' (cape) - coastal regardless of any mountain-range aside"
    is_river_like = _RIVERFEAT_RE.search(name) or _RIVER_COURSE_RE.search(name) or _MOUTH_RE.search(name)
    if _MOUNTAIN_NAME_RE.search(name) and not (is_river_like and _MOUNTAIN_LOCATION_REF_RE.search(name)):
        return "mountain", "matches mountain-range name pattern (Gebirge/-berg/Calpe), not a river point naming it as a location"
    if _ALPS_BAREWORD_RE.search(name) and not is_river_like:
        return "mountain", "matches 'Alpes'/'Alpen' (bare, not also a river-course/source/mouth pattern)"
    if (
        _MOUNTAIN_BAREWORD_BERG_RE.search(name)
        and not (is_river_like and _MOUNTAIN_LOCATION_REF_RE.search(name))
        and not section_is_coastal
        and not _CAPE_RE.search(name)
        and not _GULF_RE.search(name)
        and not _HARBOR_RE.search(name)
        and not _ESTUARY_RE.search(name)
    ):
        return "mountain", "matches 'Berg'/'Berge' as its own word (bare, not a coastal landmark or river location)"
    if force_noncoastal:
        section_is_coastal = False
    if _LAKE_RE.search(name) and _RIVER_COURSE_RE.search(name) and not _LAKE_LOCATION_REF_RE.search(name):
        # Same collision as the mountain "(Mitte)" fix above, one category
        # over: a lake's own midpoint/end citation ("Asphaltites-See
        # (Mitte)", "Lychnitis-See (Mitte)", "Chelonidai-Seen (Mitte)")
        # matches _RIVER_COURSE_RE's "(mitte)" before the lake check further
        # below ever gets a turn. Guarded the same way, against a river
        # point that merely names a lake as its *location* rather than its
        # own identity ("Padus (Einmündung des aus Lacus Benacus
        # entspringenden Flusses)" - the Po's confluence, not the lake).
        return "lake", "matches 'See'/'Seen'/'Palus'/'Lacus' with a river-course position marker (Mitte/Ende), not a river point naming a lake as a location"
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
    if _LAKE_RE.search(name) and not _LAKE_LOCATION_REF_RE.search(name):
        return "lake", "matches 'See'/'Seen'/'Palus'/'Lacus' (lake/marsh), not a river point naming a lake as a location"
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
    mountain_feature_id: str = ""  # which drawn mountain-range line this point belongs to, once resolved (see build_mountain_lines)
    mountain_sequence_in_feature: int = -1  # draw order within mountain_feature_id, once resolved
    label_note: str = ""  # supplementary text for category=="label" rows (e.g. a people/tribe name) - see topostext/build_labels.py

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
    "mountain_feature_id",
    "mountain_sequence_in_feature",
    "label_note",
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
                    "mountain_feature_id": ref.mountain_feature_id,
                    "mountain_sequence_in_feature": ref.mountain_sequence_in_feature if ref.mountain_feature_id else "",
                    "label_note": ref.label_note,
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
                    mountain_feature_id=row.get("mountain_feature_id", ""),
                    mountain_sequence_in_feature=int(row["mountain_sequence_in_feature"])
                    if row.get("mountain_sequence_in_feature")
                    else -1,
                    label_note=row.get("label_note", ""),
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
        section_force_noncoastal = book_map_section in _NONCOASTAL_EXCEPTION_SECTIONS
        force_mountain = book_map_section in _MOUNTAIN_APPENDIX_SECTIONS
        force_coastal = book_map_section in _COASTAL_APPENDIX_SECTIONS

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
                force_noncoastal=section_force_noncoastal or str(_id) in _NONCOASTAL_POINT_OVERRIDES,
                force_mountain=force_mountain,
                force_mountain_point=str(_id) in _MOUNTAIN_POINT_OVERRIDES,
                force_coastal=force_coastal,
                force_river_point=str(_id) in _RIVER_POINT_OVERRIDES,
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
    "3.10.14.01",  # Borysthenes-Mündung - the same pattern the other way round: Lower Moesia's own coastal
    # walk resumes at book.map "3.10" section "14" (Dniester-area river mouths, a genuinely new stretch)
    # by re-stating the Dnieper's mouth as an orientation point first - the exact same coordinate already
    # given, correctly, as Sarmatia-in-Europe's own citation (3.05.07.01). Left in as an edge, this
    # duplicate coordinate became a node with edges to *both* its own real neighbour (3.10.14.02) and,
    # via catalogue-order adjacency within its own book.map, the far end of a >4.5-degree jump back across
    # section "08"'s last coastal point (an intervening digression into inland Danube-bank legionary
    # camps, sections "09"-"13", correctly left `city`) - a zigzag with no geographic basis, reported by
    # the user as "two strange lines...as if it's trying to connect the wrong features". Skipping this one
    # re-citation lets 3.10's own walk connect directly to its real next point instead.
    #
    # The four entries below were found a different way: a real coastline
    # never crosses itself (the same "a road doesn't cross itself" argument
    # the user made, prompting this check) - so any drawn coastline whose
    # own line self-intersects has a real ordering bug somewhere, findable
    # without eyeballing a render or hand-picking a distance threshold.
    # Checked every coastline/river/island/mountain line in the catalogue
    # with shapely's line-segment intersection test; all four hits below
    # turned out to be the *introductory boundary point* pattern above,
    # just not yet found because a false self-crossing edge is a different
    # symptom than a straight-line "jump" is.
    "3.13.06.05",  # Malischer Golf - Macedonia's own southern border marker (topostext, by name match: cited alongside "Pindos mountain midpoint"/"Oite mountain midpoint" as boundary landmarks with Achaia/Epirus), stated *before* the region's coastal walk actually begins at Neapolis (3.13.09.03) - left in, its first edge (straight to Neapolis, far north) crossed twelve later segments of the walk it correctly closes back near its own start (Malischer Golf and Spercheios-Mündung are both near Thermopylae - see the existing 3.13.09.03/3.13.17.10 _NO_CLOSE_LOOP_TRAILS entry, which this restores)
    "5.03.01.06",  # Grenzpunkt (Lykien, Pamphylien) - Lykia's own eastern border marker (topostext: "limit of Asia through the Masikytos mountain, as far as the sea at..." - its own separate introductory section, before "the following" starts the coastal walk at Kaunos/Xanthos)
    "5.05.01.09",  # Grenzpunkt (Kilikien, Pamphylien) - Pamphylia's, the same shape (topostext: "limit point near Galatia to the Pamphylian sea, the limit point of this line at..." then "the shores of Pamphylia: Olbia, Attaleia...")
    "5.08.01.09",  # Grenzpunkt (Kilikien, Syrien) - Cilicia's, the same shape again (topostext: "limit at Kappadokia extending to the Issian Gulf and Amanikian Gates, which limit..." then "In Selinitis of Kilikia Tracheia Iotape...")
    "5.01.05.04",  # Kap Bithynia - an undermarked re-citation of the same headland as "Spitze Bithyniens mit Artemis-Heiligtum" (5.01.02.02): same latitude exactly, topostext re-describing it verbatim ("mouth of the Pontos and the sanctuary of Artemis Bithynian promontory") to reorient the reader before continuing west past Artake/Psyllis/Kalpas - the same shape as the Borysthenes-Mündung case, just without an explicit arrow marker this time. Left in, its edge from Rhyndakos-Mündung (the Gulf of Astakos digression's own inner end) cut straight back across the gulf, crossing three of the digression's own segments.
    "3.12.04.05",  # Kallipolis - the Thracian Chersonese's own loop closing back to its start (topostext, book 3 map 11 section 9: "...Sestos, next the above-mentioned Kallipolis"), a bit-identical coordinate duplicate of 3.12.01.05. Left in as a fresh point, it would just re-close the loop a second time at the same node - the ordinary close-loop mechanism (feature_closes_loop) already does this correctly once 3.12's own points are traced.
    #
    # Found by the systematic whole-catalogue self-intersection review
    # (2026-07-30), same "Grenzpunkt" boundary-marker pattern as the five
    # entries above, this time in Iberia rather than the Aegean/Black Sea:
    "2.04.03.04",  # Anas (Grenzpunkt Baetica, Lusitania, Tarraconensis) - a border marker *up the river Anas/Guadiana itself* (topostext: "Where the river touches the border of Lusitania", right after "Before the river turns towards the east") at -8.67,39.0 - over 4 degrees inland/east of either of the river's own two mouths. Left in as coastal, its edge from the eastern mouth cut straight back across the walk's own western end (Onoba/Baetis-Mündung, the same estuary as the western Anas mouth that closes this loop).
    "2.04.03.07",  # Baetica (Ostende am Baliarischen Meer) - the very next citation, Baetica's own *eastern* border marker where the province line meets "the Balearic sea" (topostext: "there along the border of Tarraconensis to where the Balearic sea ends") - a second inland/administrative boundary point in the same short digression as the one above, not a coastal step either.
    #
    # Found indirectly, by fixing the Durius Grenzpunkt (_RIVER_POINT_OVERRIDES,
    # 2026-07-30): removing that inland point from the coastline exposed a
    # second, previously-hidden bug in the same book.map - the exact
    # Acheloos-/Borysthenes-Mündung shape above, just not visible before
    # because the wrong two-hop path (via the now-removed Grenzpunkt)
    # happened not to cross anything, by coincidence, while the shorter
    # direct edge does. Durius-Mündung (topostext: "The southern side of
    # Lusitania is the common boundary with...Baetica. The northern side
    # links to Tarraconensis along the western part of the Dourius
    # river...The mouth of the river, which flows into the Outer Sea") is
    # Lusitania's own *northern* boundary marker, stated first as an
    # orientation point - the walk proper starts at Balsa (the *southern*,
    # Baetica-border end) and runs the whole Algarve-then-west-coast loop
    # back up to Vacua-Mündung, a few hundredths of a degree from Durius-
    # Mündung's own coordinate, closing the loop on its own without this
    # edge. Left in, the direct Durius-Mündung -> Balsa edge (skipping
    # straight from Porto to the Algarve) cut across the walk's own real
    # west-coast return leg three times.
    "2.05.01.04",
}

# A narrower tool than _COASTLINE_SKIP_REF_IDS: that one drops a point from
# every edge it would touch, incoming or outgoing. Sometimes only *one*
# specific edge is wrong and the point itself is a real, correctly-placed
# step that should stay connected to what comes *before* it - just not to
# what catalogue order happens to put right after it. Found by the user
# pointing at two exact edges directly in a rendered map ("the line from
# this point onward is wrong"):
#
# - `3.11.02.10` ("Grenzpunkt der Thrakischen Chersones an der Propontis")
#   correctly ends Thrace's Aegean-coast-and-Chersonese-boundary walk, but
#   catalogue order puts `3.11.03.05` ("Grenze bei Moesia Inferior") right
#   after it - and topostext shows that's not a continuation at all: "3.1
#   On the east by the Propontis and the mouth of Pontos...and by the
#   onward shores of Pontos until the border with Lower Moesia" is a fresh
#   *restatement* of Thrace's whole eastern boundary line, whose own
#   enumeration ("3.2 which border the description is the following:
#   after Mesembria of Moesia, Anchialos...") starts a new, independent
#   coastal walk (already `_COASTAL_APPENDIX_SECTIONS`-fixed at
#   `5.04`/`3.11.04` etc.) that never comes back near the Chersonese.
#   Breaking just this edge lets that Black-Sea-and-Propontis walk stand
#   as its own trail instead of bridging 3.2 degrees across Thrace's
#   interior to a point it was never narratively connected to.
# - `5.01.04.07` (Rhyndakos-Mündung) correctly ends the Gulf of
#   Astakos/Marmara-south-shore digression (Astakos through Daskylion,
#   `5.01.04`), but catalogue order puts Artake (`5.01.05.05`, where the
#   main Propontis coast resumes past the Kap Bithynia re-citation) right
#   after it - an edge that cut back across the whole digression regardless
#   of which intermediate points were included (see check_self_intersections.py).
#   Unlike the Thrace case there's no boundary-line sentence marking this
#   one explicitly, but the same shape - a real digression's own end,
#   bridged by catalogue adjacency to an unrelated resumption point - fits
#   every other fact of the case.
_COASTLINE_HARD_BREAKS: set[tuple[str, str]] = {
    ("3.11.02.10", "3.11.03.05"),
    ("5.01.04.07", "5.01.05.05"),
    # Panysus-Mündung correctly ends the coast heading *south* from the
    # Danube delta toward Thrace (topostext, book 3 map 10 section 3: "The
    # eastern side of Moesia is bound by the coast following the mouths of
    # Pontos as far as [Kap Pteron]...Tomoi...Kallatis...Tiristis
    # promontory...Odessos...Panysos river mouth...Mesembria"). Axiakes-
    # Mündung starts an entirely different stretch heading *north* from the
    # delta toward the Dniester (topostext section 7: "northernmost mouth
    # of the Istros until the mouth of the Borysthenes river and the
    # hinterland...Axiakos river mouth..."). Catalogue order bridges them
    # directly only because an inland digression (Danube-bank Roman cities,
    # correctly `city`) sits between the two sections with nothing to mark
    # the hard turn - a ~4 degree jump the user pointed at as "completely
    # wrong" directly in a rendered map.
    ("3.10.08.10", "3.10.14.02"),
    # The delta's own six mouths reorder correctly south-to-north (see
    # _COASTLINE_EXPLICIT_ORDER_OVERRIDES), ending at the *northernmost*
    # one - but the coast heading south toward Thrace (Kap Pteron onward)
    # naturally continues from there in ref_id order regardless, cutting
    # straight back across the delta's own southward-opening branches
    # (confirmed by check_self_intersections.py - three real crossings).
    # Kap Pteron is topostext's own next-door neighbour to the *southern*
    # mouth, Hieron/Heilige Mündung ("Sacred mouth of the Istros river,
    # Pteron promontory" - one citation, not two), not the northern one.
    # Breaking this edge and letting the ordinary proximity stitch
    # reconnect Heilige Mündung to Kap Pteron instead (0.4 degrees apart,
    # well under the stitch tolerance, and the closest pairing available)
    # gives the delta a real branch shape: one open chain, walked
    # south-to-north through the six mouths, with the rest of the coast
    # rejoining at the south end where it geographically belongs.
    ("3.10.04.03", "3.10.08.03"),
}

# build_coastlines assumes catalogue order (ref_id order) is walking order
# - true for an ordinary coastal survey, but not for a river delta, which
# Ptolemy describes as a *branching tree*, not a line: "the first division
# of the mouths at Noviodunum...the southernmost part...flows out by the
# Sacred mouth...the northernmost divides again...divides again...flows
# out by Thiagola or Psilon...The more southerly of the second division
# also splits...flows out by Boreios...also divides...flows out by
# Narakion...also divides...flows out by Pseudostomon...the more
# southerly flows out by Kalon" (topostext, book 3 map 10 - the Danube
# delta). Reading that nested south/north branching in order (the
# catalogue's own division points confirm every split: "Ister (1. Teilung
# bei Noviodunum)", "...Teilung des nördlichsten Armes", two more bare
# "Ister (Teilung)" citations - see _RIVER_COURSE_RE's "teilung" addition)
# gives a real geographic south-to-north walk along the coast, confirmed
# by every one of the six mouths' own latitude increasing monotonically
# in this order - catalogue/ref_id order does not (it interleaves them
# with the division points in a different sequence entirely). Found by
# the user comparing the rendered result against old maps that draw this
# delta as a single point fanning into several branches, and asking for
# the branches to be worked through step by step rather than left to
# ref_id order. `sort_key` below checks this override before falling back
# to natural (book, tabula, section, item) order; unlisted ref_ids are
# unaffected, and the six overrides are placed as extra tuple elements
# immediately after the first mouth's own natural key so they sort
# between it and the next unrelated point without disturbing anything
# else in book.map "3.10".
_COASTLINE_EXPLICIT_ORDER_OVERRIDES: dict[str, tuple] = {
    "3.10.05.05": (3, 10, 2, 5, 1),  # Narakion-Mündung
    "3.10.06.03": (3, 10, 2, 5, 2),  # Schöne Mündung (Kalon)
    "3.10.06.02": (3, 10, 2, 5, 3),  # Pseudostomon (Mündung)
    "3.10.05.03": (3, 10, 2, 5, 4),  # Nördliche Mündung (Boreios)
    "3.10.04.03": (3, 10, 2, 5, 5),  # Psilon bzw. Thiagola (Mündung)
}

# A different, self-marking version of the same "same point re-cited"
# problem above, found from a user-reported zigzag in the Arabia
# Felix/Persian Gulf area: book.map "6.07" sections "12" and "13" are each
# a *summary recap* - "[Coastal mountains of Eudaimon Arabia:] Hippos
# Mountain...Kaboubathra Mountain...Didyma Mountains..." (topostext) and
# "Coastal rivers: Baitios river...Prionos river mouth..." - re-listing
# points already cited earlier in the same book.map, each one explicitly
# marked in the catalogue's own Locality text with a back-reference arrow
# ("Didyma-Berge –> 6.7.11", "Lar-Mündung < 6,7,14"). Unlike the
# Acheloos-Mündung case, these recap citations land at (essentially) the
# *exact same coordinate* as their original, so node-collapsing doesn't
# just merge two ends of one walk - it turns the original point into a
# junction with extra edges to whatever precedes/follows it in the recap
# list, which has no geographic relationship to the original's real
# neighbours at all. The result was a coastline graph walk that left its
# real path to detour through the recap list and back, a zigzag with no
# geographic basis (checked across the whole catalogue via this same
# regex - all 15 matches are these two sections, nowhere else). Matched by
# pattern rather than a hand-picked ref_id list since the arrow itself
# *is* the "this is a duplicate, not a new point" signal - skipped from
# coastline edges, river-line and mountain-line grouping alike (a mountain
# name recap would create the exact same kind of junction if one ever
# shows up elsewhere).
_RECAP_BACKREF_RE = re.compile(r"–>|->|<\s*\d")

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
    # Three more of the same shape, found by the user on Turkey's own
    # Black Sea coast (book.maps 5.01/5.04/5.06/5.10, each a different
    # Roman-administrative sub-province - Bithynia, Paphlagonia+Pontus,
    # then the three "Pontus" sub-provinces, then Colchis - covering the
    # same continuous real shore end to end, split only by where one
    # province's own book.map hands off to the next).
    ("5.01.07.07", "5.04.02.02"),  # Parthenios-Mündung/Bartın Su - Bithynia -> Paphlagonia, the real Bithynia/Paphlagonia border river
    ("5.04.03.07", "5.06.02.03"),  # Amisos/Samsun -> Iris-Mündung/Yeşilırmak - Paphlagonia+Pontus -> Pontus Galaticus, the coast right at Samsun
    ("5.06.07.02", "5.10.02.09"),  # Apsorros-Mündung/Çoruh -> Phasis-Mündung/Rioni - Pontus Cappadocicus -> Colchis, the real Turkey/Georgia border river to the Golden Fleece's own river
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
    # Both found via the self-intersection sweep (see _COASTLINE_SKIP_REF_IDS
    # above): a small enough closing gap relative to path length to pass
    # _CLOSE_LOOP_MAX_GAP_RATIO, but the resulting closing edge cut straight
    # across the middle of the trail's own real path - the geometric
    # signature of a mainland coast's two ends happening to land near each
    # other, not an island's coastline genuinely returning to its start.
    # ("3.10.02.05", "3.10.14.06") - Heilige Mündung -> Harpis - was here,
    # covering Lower Moesia's Danube-delta-to-Dniester coast. No longer
    # needed: reordering the delta's own six mouths and rejoining the rest
    # of the coast at the correct (southern) end instead
    # (_COASTLINE_EXPLICIT_ORDER_OVERRIDES, _COASTLINE_HARD_BREAKS) changed
    # this trail's own endpoints to Panysus-Mündung/Axiakes-Mündung, over
    # 2.5 degrees apart - well outside a false closure's reach, so nothing
    # replaces this entry.
    ("3.11.02.01", "3.11.06.09"),  # Nessos-Mündung -> Paktye: Thrace's Aegean-to-Propontis coast, not an island
    # Once Thrace (3.11) and Macedonia/Thessaly (3.13) stopped each falsely
    # closing on their own, the real Nessos-Mündung/Neapolis boundary stitch
    # (_BOUNDARY_STITCH_REF_ID_PAIRS, below) correctly merged them into one
    # much longer trail - whose own two new loose ends, Paktye and
    # Spercheios-Mündung, then happened to satisfy the same ratio check
    # themselves, closing a ~58-point trail across the whole Aegean and
    # self-crossing the same way. Same fix, one level up.
    ("3.11.06.09", "3.13.17.10"),  # Paktye -> Spercheios-Mündung: the merged Thrace+Macedonia+Thessaly coast, not an island
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
        if ref.ref_id in _COASTLINE_EXPLICIT_ORDER_OVERRIDES:
            return _COASTLINE_EXPLICIT_ORDER_OVERRIDES[ref.ref_id]
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
            if (
                ref.category not in _COASTLINE_CATEGORIES
                or ref.ref_id in _COASTLINE_SKIP_REF_IDS
                or _RECAP_BACKREF_RE.search(ref.name)
            ):
                continue
            if (
                prev is not None
                and _dist((prev.lat_modern, prev.lon_modern), (ref.lat_modern, ref.lon_modern)) <= _MAX_COASTAL_GAP_DEG
                and (prev.ref_id, ref.ref_id) not in _COASTLINE_HARD_BREAKS
                and (ref.ref_id, prev.ref_id) not in _COASTLINE_HARD_BREAKS
            ):
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

# The only category that can be a step along a drawn mountain-range line.
_MOUNTAIN_LINE_CATEGORIES = ("mountain",)

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


# The river-line counterpart of _COASTLINE_SKIP_REF_IDS: a point excluded
# from a river's node set entirely, rather than left to the ordinary
# distance-based dedup below to sort out. Needed when the dedup's "keep
# whichever duplicate sorts first by ref_id" rule picks the *wrong* one of
# two identical-coordinate re-citations - an earlier-numbered boundary-line
# citation of a bend/confluence (stated as an orientation point for an
# unrelated province's border) instead of the same bend's later, correctly-
# sequenced appearance within the river's own continuous course narrative.
# Found by the systematic self-intersection review (2026-07-30), re-
# examining the three Danuvius crossings this session had previously
# accepted as "genuine Ptolemaic distortion" without checking this
# possibility first - the same premature call already corrected once this
# session for the Danube delta.
_RIVER_LINE_SKIP_REF_IDS = {
    "2.15.01.06",  # Danuvius (Einmündung des Savus) - topostext (2.15.1.1): "...on the south by Illyria which extends from the indicated terminus as far as the bend in the Danube near which the Savos river empties into it" - Pannonia Inferior's own boundary description, citing the Savus confluence purely as its terminus. The dedup (exact coordinate match, distance 0.0) kept this one because "2.15.01" sorts before "2.15.02", pulling it in front of Cirpi's *later* bend (2.15.02.04/2.11.05.16) and out of the real downstream order (Cirpi -> Dravus confluence -> Cornacum -> Acumincum -> Rittium -> Savus confluence) that Moesia Superior's own section 2.15.02 narrates as one continuous run - the same physical point is re-cited there too, correctly placed at the end, as "Danuvius (Biegung bei der Einmündung des Savus)" (2.15.02.18, also distance 0.0 from this one). Skipping this citation here lets that correctly-sequenced duplicate survive the dedup instead.
}

# Ptolemy reuses common river names for entirely unrelated rivers within
# the *same* book, not just across books - Britain alone has two rivers
# each called "Deva" and two each called "Alaunus" (topostext confirms:
# `2.03.02.06` "mouth of the Devas river" sits on the west coast between
# Iena and Novius estuaries, while `2.03.05.12` "mouth of the Deva river"
# sits on the opposite, northeast coast between Taezalon promontory and
# Tina estuary, nowhere near the first one's narrative context;
# `2.03.04.06` "mouth of the Alaunus river" is on the south coast between
# Isca and Magnus Portus, while `2.03.06.01` "mouth of the Alaunus river"
# is far north on the east coast between Boderia estuary/the Firth of
# Forth and Vedra/the Wear - modern Dee-side Chester vs. Dee-side
# Aberdeen, and the Hampshire Aln vs. the Northumberland Aln, two
# same-named-river coincidences, not one river each). Found by the user
# asking for a north-south river crossing Britain's own coastline as a
# review target: both pairs sit close enough (~6-8 degrees) to fall under
# `_RIVER_LINE_MAX_GAP_DEG` and get merged into one two-point "river"
# cutting straight across the island - short enough (2 points, 1 segment)
# to never trip `check_self_intersections.py`'s `len(trail) >= 4` floor,
# and a *coastline* crossing rather than a self-crossing, which that
# checker never tests for at all. Lowering the general gap threshold
# would risk splitting genuinely long, distorted rivers elsewhere
# (Nile/Ganges/Indus already have confirmed-genuine internal jumps closer
# to 20 degrees) - so this is a narrow, evidence-specific pairing
# exclusion instead, the same shape as `_COASTLINE_HARD_BREAKS`.
_RIVER_LINE_NO_MERGE_REF_ID_PAIRS: set[tuple[str, str]] = {
    ("2.03.02.06", "2.03.05.12"),  # Deva (Chester) vs. Deva (Aberdeen)
    ("2.03.04.06", "2.03.06.01"),  # Alaunus (Hampshire) vs. Alaunus (Northumberland)
    #
    # Found by generalizing the Deva/Alaunus check catalogue-wide (a new
    # river-vs-coastline crossing check, since a same-name-merged river is
    # usually only 2 points - too short for check_self_intersections.py's
    # own len>=4 floor to ever catch as a self-crossing): the same reused-
    # name coincidence, confirmed each time by two different `Modern_location`
    # values and/or non-adjacent book.maps, not one continuous course:
    ("4.01.02.06", "4.01.04.06"),  # Sala (Bou Regreg, Rabat) vs. Sala (Oued Tamrakt, ~7 degrees south) - both in book.map 4.01 (Mauretania Tingitana) but different modern rivers
    ("3.02.05.01", "3.03.02.10"),  # Heiliger Fluss/"Sacred river" (Corsica's Fium'Orbo, book.map 3.02) vs. Heiliger Fluss (Sardinia, book.map 3.03) - a descriptive name ("Hieros Potamos"), not a proper name, reused independently on each island
    ("3.13.18.11", "3.16.06.03"),  # Peneios-Quelle, Thessaly (book.map 3.13, near Mt. Pindos) vs. Peneios-Mündung, the Peloponnese (book.map 3.16) - two real, still-named rivers (Pineios of Thessaly and Pineios of Elis), not one course; the Thessalian mouth+source pair (3.13.15.07/3.13.18.11) stays merged as one line
    ("3.15.13.09", "3.16.03.04"),  # Asopos (confluence with Kephisos/Ismenos - Boiotian rivers, book.map 3.15) vs. Asopos-Mündung, the Peloponnese (book.map 3.16) - the Boiotian Asopos (of the Battle of Plataia) and the Peloponnesian Asopos near Sikyon are two different rivers sharing a name
    ("5.06.07.05", "5.14.02.06"),  # Lykos-Quellen (Kelkit Çayı, Pontus, book.map 5.06) vs. Lykos-Mündung (Kuris, book.map 5.14, far south) - different modern rivers entirely
}


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
        if (
            ref.category not in _RIVER_LINE_CATEGORIES
            or not ref.ref_id
            or ref.ref_id in _RIVER_LINE_SKIP_REF_IDS
            or not ref.is_plausible()
            or _RECAP_BACKREF_RE.search(ref.name)
        ):
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
            no_merge = (prev.ref_id, cur.ref_id) in _RIVER_LINE_NO_MERGE_REF_ID_PAIRS or (
                cur.ref_id,
                prev.ref_id,
            ) in _RIVER_LINE_NO_MERGE_REF_ID_PAIRS
            if no_merge or _ref_dist(prev, cur) > _RIVER_LINE_MAX_GAP_DEG:
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


# A mountain range is catalogued the same way a river's course is: its own
# named ends ("(W-Ende)"/"(O-Ende)", or "(N-Ende)"/"(S-Ende)" etc.) and
# sometimes a midpoint ("(Mitte)"/"(Mittelpunkt)"), each its own entry -
# never a continuous walk the way a shoreline is. Grouped by book as well
# as name for the same reason a river line is (see _RIVER_LINE_MAX_GAP_DEG)
# - but unlike rivers, no case of two *different* ranges sharing a base
# name within one book was found in this catalogue (every W-Ende/O-Ende
# pair checked, even the widest at 18.4 degrees for Anniba-Gebirge in
# India, is a real range's own extent), so the gap cap here only needs to
# rule out a wildly implausible jump, not a genuine name collision.
_MOUNTAIN_LINE_MAX_GAP_DEG = 20.0
_MOUNTAIN_LINE_COLOR = "#6b4226"

# The two largest ranges in the catalogue (Kasia, spanning Book 6 maps
# 6.15/6.16) are each cited as two separately-numbered halves - "(westl.
# Teil, ...)" and "(östl. Teil, ...)" - rather than one continuous range.
# Recognized and kept (not stripped like a plain position marker) so the
# two halves stay in their own groups instead of merging into one line
# that would jump across the gap between them.
_MOUNTAIN_PART_RE = re.compile(r"\((westl\.|östl\.)\s*teil\s*,\s*[^)]*\)", re.IGNORECASE)
_MOUNTAIN_TOKEN_RE = re.compile(r"-gebirge|-berg\b|\bgebirge\b", re.IGNORECASE)


def _mountain_base_name(name: str) -> str:
    """The name shared by every point along one mountain range's extent,
    with its position marker and any trailing alias stripped - the range
    counterpart of _river_base_name. Rather than enumerate every position
    phrasing the catalogue uses ("(Mitte)", "(W-Ende)", "(nördliches
    Grenzzeichen)", "(W-Ende am Euphrat)", "(O-Ende) bzw. Serisches
    Gebirge", ...), cut at the *first* parenthesis/alias marker after the
    range's own name - whatever position or alternate-name detail follows
    carries no grouping identity of its own. A leading descriptive aside
    naming something else first ("Heiligtum der Venus, Pyrene-Gebirge
    (SO-Ende)") is reduced to just the comma-segment that actually names a
    range, first."""
    name = _MOUNTAIN_PART_RE.sub(lambda m: f" [{m.group(1)} Teil]", name)
    head = name.split("(", 1)[0]
    if "," in head:
        parts = [p.strip() for p in name.split(",", 1)]
        if _MOUNTAIN_TOKEN_RE.search(parts[-1]):
            name = parts[-1].strip()
    cut_at = [i for i in (name.find(" bzw."), name.find(" / "), name.find("(")) if i != -1]
    if cut_at:
        name = name[: min(cut_at)]
    return name.strip().replace("[", "(").replace("]", ")")


def build_mountain_lines(refs: list[Reference]) -> list[list[Reference]]:
    """Connect a mountain range's own points (ends, midpoint) into a line
    tracing its extent, in catalogue order - build_river_lines()'s approach
    applied to mountains instead of rivers, including the same re-citation
    dedup (Ptolemy re-cites an end already given once a range reappears as
    a boundary marker between two later book.map sections, e.g. Buzara-
    Gebirge's O-Ende, Koronos-Gebirge's O-Ende, Emoda-Gebirge's O-Ende) and
    the same book-scoped, gap-capped grouping to avoid trusting a bare
    range name across unrelated continents."""

    def sort_key(ref: Reference) -> tuple:
        return tuple(int(p) if p.isdigit() else p for p in ref.ref_id.split("."))

    groups: dict[tuple[str, str, str], list[Reference]] = {}
    for ref in refs:
        if (
            ref.category not in _MOUNTAIN_LINE_CATEGORIES
            or not ref.ref_id
            or not ref.is_plausible()
            or _RECAP_BACKREF_RE.search(ref.name)
        ):
            continue
        base = _mountain_base_name(ref.name)
        # Same guard as build_river_lines: "Namenlose(r) Berg(e)" ("unnamed
        # mountain(s)") is a placeholder, not a shared identity - five
        # separate, unrelated peaks scattered from Illyria to Arabia all
        # reduce to this same base name, and connecting them would draw a
        # nonsense line across two continents.
        if not base or _GENERIC_RIVER_NAME_RE.search(base):
            continue
        groups.setdefault((ref.source, ref.book, base), []).append(ref)

    lines: list[list[Reference]] = []
    for items in groups.values():
        items.sort(key=sort_key)
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
            if _ref_dist(prev, cur) > _MOUNTAIN_LINE_MAX_GAP_DEG:
                if len(run) >= 2:
                    lines.append(run)
                run = [cur]
            else:
                run.append(cur)
        if len(run) >= 2:
            lines.append(run)
    return lines


def assign_mountain_features(refs: list[Reference]) -> None:
    """Materialize build_mountain_lines()'s output as data, the same way
    assign_river_features() does."""
    lines = build_mountain_lines(refs)
    for line_idx, points in enumerate(lines):
        feature_id = f"mountain_{line_idx:03d}_{_mountain_base_name(points[0].name)}"
        for position, ref in enumerate(points):
            ref.mountain_feature_id = feature_id
            ref.mountain_sequence_in_feature = position


def build_mountain_lines_from_features(refs: list[Reference]) -> list[list[Reference]]:
    """The trivial counterpart to build_mountain_lines(): group by
    mountain_feature_id, sort by mountain_sequence_in_feature."""
    groups: dict[str, list[Reference]] = {}
    for ref in refs:
        if not ref.mountain_feature_id:
            continue
        groups.setdefault(ref.mountain_feature_id, []).append(ref)

    lines: list[list[Reference]] = []
    for points in groups.values():
        points.sort(key=lambda r: r.mountain_sequence_in_feature)
        lines.append(points)
    return lines


def get_mountain_lines(refs: list[Reference]) -> list[list[Reference]]:
    """Trivial reconstruction if the dataset already carries resolved
    mountain_feature_id/mountain_sequence_in_feature, falling back to
    build_mountain_lines() otherwise - mirrors get_river_lines()."""
    if any(r.mountain_feature_id for r in refs):
        return build_mountain_lines_from_features(refs)
    return build_mountain_lines(refs)


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
        if ref.category != "island" or not ref.ref_id or not ref.is_plausible() or _RECAP_BACKREF_RE.search(ref.name):
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

    # Synthetic region/island-group/mountain-range labels (build_labels.py)
    # aren't real catalogue points - keep them out of the marker-cluster
    # loop, the coastline/river/island/mountain line builders, and the
    # center-of-mass calculation, and draw them separately as plain text.
    label_refs = [r for r in plausible if r.category == "label"]
    plausible = [r for r in plausible if r.category != "label"]

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

    mountain_lines = get_mountain_lines(plausible)
    mountain_position: dict[str, tuple[int, int]] = {}
    for line_idx, line in enumerate(mountain_lines):
        for i, ref in enumerate(line):
            mountain_position.setdefault(ref.ref_id, (line_idx, i))

    if mountain_lines:
        mountain_layer = folium.FeatureGroup(name=f"Mountain ranges ({len(mountain_lines)} lines)").add_to(fmap)
        for line in mountain_lines:
            coords = [(r.lat_modern, r.lon_modern) for r in line]
            folium.PolyLine(coords, color=_MOUNTAIN_LINE_COLOR, weight=4, opacity=0.85).add_to(mountain_layer)

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
        mountain_line_info = ""
        if ref.ref_id in mountain_position:
            mountain_idx, mountain_pos = mountain_position[ref.ref_id]
            mountain_line_info = f"Mountain-range line #{mountain_idx}, position #{mountain_pos}<br>"
        popup_html = (
            f"<b>{html.escape(ref.name)}</b><br>"
            f"{modern_line}"
            f"{category_line}"
            f"{seq_line}"
            f"{river_line_info}"
            f"{island_line_info}"
            f"{mountain_line_info}"
            f"Map ID: {html.escape(ref.ref_id) or '?'} "
            f"&mdash; Book {html.escape(ref.book) or '?'}, {html.escape(ref.tabula) or 'unlabelled table'}<br>"
            f"Ptolemy coords: {ref.lon_ptolemy:.2f}° (Ferro), {ref.lat_ptolemy:.2f}°{recension_line}<br>"
            f"Modern approx.: {ref.lat_modern:.3f}, {ref.lon_modern:.3f}<br>"
            f"<i>source: {html.escape(ref.source)}</i>"
        )
        color = CATEGORIES[ref.category]["color"]
        is_coast_family = ref.category in _COASTLINE_CATEGORIES or ref.ref_id in island_position
        # Lakes share the rivers' light-blue color now (both are "inland
        # water" to a reader at a glance) - sized up instead, so a lake is
        # still visually distinct from an ordinary river bend/confluence
        # rather than just blending into the same-colored dots around it.
        radius = 11 if ref.category == "lake" else (8 if is_coast_family else 5)
        marker = folium.CircleMarker(
            location=[ref.lat_modern, ref.lon_modern],
            radius=radius,
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

    if label_refs:
        label_layer = folium.FeatureGroup(name=f"Region/feature labels ({len(label_refs)})").add_to(fmap)
        for ref in label_refs:
            note_line = f"<br>{html.escape(ref.label_note)}" if ref.label_note else ""
            popup_html = f"<b>{html.escape(ref.name)}</b>{note_line}<br><i>{html.escape(ref.ref_id)}</i>"
            folium.Marker(
                location=[ref.lat_modern, ref.lon_modern],
                icon=folium.DivIcon(
                    html=(
                        f'<div style="font-size:15px;font-style:italic;font-weight:600;color:#2b2b2b;'
                        f'text-shadow:0 0 3px #fff,0 0 3px #fff,0 0 3px #fff,0 0 3px #fff;'
                        f'white-space:nowrap;transform:translate(-50%,-50%);pointer-events:none;">{html.escape(ref.name)}</div>'
                    )
                ),
                popup=folium.Popup(popup_html, max_width=280),
            ).add_to(label_layer)

    _add_legend(fmap, plausible)
    folium.LayerControl(collapsed=False).add_to(fmap)
    output.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(output))
    print(
        f"plotted {len(plausible)} geographical reference(s) "
        f"({len(coastlines)} coastline segments, {len(river_lines)} river lines, "
        f"{len(island_lines)} island outlines, {len(mountain_lines)} mountain-range lines, "
        f"{len(label_refs)} region/feature labels) -> {output}"
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
