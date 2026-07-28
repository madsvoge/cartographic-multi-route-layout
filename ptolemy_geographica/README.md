# Ptolemy's Geographica -> OpenStreetMap

`ptolemy_map.py` extracts the geographical references (place names and
coordinates) recorded in Claudius Ptolemy's 2nd-century *Geographica* and
plots them as an interactive map on OpenStreetMap tiles.

## Quick start

```bash
pip install -r requirements.txt
python3 ptolemy_map.py --open
```

This reads the full catalogue and writes `ptolemy_map.html`, an interactive
Leaflet/OpenStreetMap page with a marker for each of the ~6,400 plottable
references, clustered so the browser stays responsive. Coastal points are
drawn larger than other categories; click one for its name, category, map
ID, its position within its reconstructed coastline (segment #, position
#), and both its ancient and modernized coordinates - useful for auditing
why two particular points ended up connected.

## Point classification & coastlines

Ptolemy didn't just list coordinates - within each region his catalogue is
organized into rubricated sections: a running sequence of coastal points
(capes, river mouths, bays - going around the shore in order), the peoples
inhabiting the area (named but given no coordinates of their own), and the
inland cities. The xlsx loader (`load_xlsx` in `ptolemy_map.py`) recovers
this structure well enough to classify every plotted point into one of:

| Category | Color | How it's detected |
|---|---|---|
| Coastal point | blue | the point's catalogue section is headed by a sea/ocean/gulf name, or its own name matches a cape/harbor/estuary pattern |
| River mouth | light blue | name matches "Mündung" - a distinct shade from "Coastal point" for visual identification, but otherwise treated identically: still sized like a coastal point and still a full participant in coastline reconstruction (see below) |
| City / inland settlement | orange | default, for points not in a coastal section and not matching another pattern |
| River source / confluence / bend | teal | name matches "Quelle" (source), "Einmündung" (confluence), "Zusammenfluss" (two rivers joining), "(Mitte)"/"Biegung" (a river's midpoint/bend), "Abzweigung"/"Aufteilung" (a delta fork) - checked *before* the coastal mouth pattern, since e.g. "Einmündung" contains the substring "mündung" and would otherwise be misread as a coastal river mouth |
| Mountain | amber | name matches "Gebirge" (mountain range) |
| Island | pink | name matches "Insel" (island), or the name ends in "(N)" - e.g. "Kassiteriden (10)" - the catalogue's convention for a scattered island group given as one count-labelled entry |
| Lake / inland water | green | name matches "See" (lake) or "Palus" (marsh/lake) |

Harbors ("Hafen"/"Portus") and estuaries ("Ästuar") are always coastal
regardless of their section, the same as capes and river mouths - they used
to only get classified as coastal when their section happened to be headed
by a sea name, which missed a real chunk of them (most catalogue sections
are headed by the local tribe's name even for points sitting right on the
shore).

Landmarks *along* a river's course - a bend ("Biegung"), its midpoint
("(Mitte)"), or a delta fork ("Abzweigung"/"Aufteilung") - are river
points too, not coastal, even though (unlike "Quelle"/source) nothing in
the word says so on its own. "Garumna (Mitte)" (the Garonne's midpoint)
sitting in the same sea-headed section as Aquitania's coastal capes used
to get pulled into the France Atlantic coastline out of geographic order,
splicing an inland river point into the middle of an otherwise-clean
coastal walk. One exception is carved out for a bend *in a gulf's own
shoreline* ("Elanitischer Golf (Biegung)"), which is genuinely coastal.

**Coastlines** are reconstructed from catalogue-order neighbours, but not
by naive end-to-end concatenation. Ptolemy regularly walks a coastline out
from a corner point and back to a *different* stretch starting at that
same corner again (Ireland's north coast and west coast both start at
"Nordspitze") - concatenating catalogue order literally would draw a
spurious straight line from the end of one walk back across to the start
of the next (this is what caused Britain's stray diagonal line, and why
Ireland's line never closed back to its own start). Instead, each
catalogue-order neighbour pair becomes an edge in an undirected graph,
points that (nearly) coincide are collapsed into one shared node, and the
graph is decomposed into trails that together cover every edge - a naive
single walk per connected component silently drops whichever branches it
doesn't happen to walk down at a junction (3+ coastal stretches sharing
one corner), so trails are re-started from any still-unused edge until
none remain. Non-coastal rows (a city, a river feature) are skipped over
rather than breaking the run outright - some books (Africa, for one)
interleave a tribal aside between *every* coastal point instead of
grouping them the way Ireland's entry does, and hard-breaking on each one
dropped those points entirely. Trails still separated afterwards (a
genuine gap, or a non-coastal detour too long to bridge) are stitched back
together if their loose ends land within ~2.5° of each other, and a
trail whose two remaining ends land within ~6° *and within 30% of the
trail's own total length* is closed into a loop - this is what closes an
island's coastline back to its own start. The length check matters:
distance alone isn't enough to tell "this path wrapped back around to
where it started" (Ireland: a 1.3° gap closing a 23°-long path, 6%) from
"these are just two points on an open stretch that happen to be
somewhat close" (France's Atlantic coast, Aturus-Mündung to
Liger-Mündung, is a real 6.9°-long walk whose ends sit 3.9° apart, 56% -
closing that drew a diagonal straight back down through the country).
Runs are
grouped by the catalogue's "book.map" prefix (e.g. "2.02"), not the
printed tabula (e.g. "EU01") - a tabula routinely bundles several distinct
book.map sub-regions onto one sheet (EU01 = Ireland "2.02" *and* Britain
"2.03"), which used to draw a line straight across the sea between the
two. A run also breaks at an implausibly large jump between points (5°) -
picked empirically: the largest verified-legitimate cross-section gap
found (Africa's book.map "4.03", capes strung along the coast each in
their own one-point section) is 3.7°, while jumps that need rejecting
(e.g. Kent straight to the north tip of Scotland, or the Biscay coast
straight to Baetica's Mediterranean side - both catalogue-adjacent but
nowhere near each other) start around 7-9°.

A second, harder-to-generalize problem: some sea-headed sections aren't a
coastal walk at all but a list of scattered islands (Elba/Capraia/Pianosa;
the Balearics; the Sporades; Red Sea and Persian Gulf islands...), and nothing
in the text reliably tells them apart from a real coastal-city section
headed the same way (Ptolemy's Gulf-of-Taranto cities - Croto, Thurii,
Tarentum - are headed by "Golf von Tarent" exactly like the island lists
are headed by "Tyrrhenisches Meer"). A blanket rule would misclassify one
or the other, so `_ISLAND_APPENDIX_SECTIONS` is a small, manually verified
exception list (checked against the `Modern_location` column and known
ancient geography) of the specific `(book.map, section)` pairs confirmed to
be island enumerations - not a general heuristic. If you spot another
sea-crossing line, check the two points' `Modern_location` in the
spreadsheet (or click them in the interactive map) - if they're islands,
tell me their section (`book.section` prefix of the `ref_id`, e.g. "6.08")
and I can add it.

This is all heuristic (regex over the German `Locality` text plus section
structure and graph reconstruction), not a verified ground truth - expect
the occasional misclassified point, or a coastline that runs oddly
straight in a region where Ptolemy's own coordinates were badly distorted
(Sarmatia/Scythia are the worst-known cases - compared against a
15th-century Nicolaus Germanus redrawing of the same catalogue, the
straight-line distortion there turned out to already be present in
Ptolemy's original data, not a bug in this reconstruction). Use `--dry-run`
to inspect the `category` assigned to any point.

## Data

- `data/ptolemy_catalogue_stueckelberger.xlsx` (default, full catalogue) —
  10,049 rows covering all 27 regional maps of the Geographica (10 Europe, 12
  Asia, 4 Africa + Ireland), columns:
  `ID, ID_map, Locality, Modern_location, Longitude_Omega, Latitude_Omega, Longitude_Xi, Latitude_Xi`.
  Omega and Xi are the Geographica's two main manuscript recensions; the
  loader plots Omega where available, Xi otherwise. ~6,400 rows carry a
  coordinate pair — the remaining rows are region/people/river names in the
  catalogue that Ptolemy didn't assign coordinates of their own.
- `data/petri-munster-1540-hibernia.csv` — a small CSV-schema sample (the
  "Hiberniae Insulae" table of the 1540 Petri/Münster edition), in the
  open-data schema published by the
  [Ptolemy-Geography project](https://github.com/Lorp/Ptolemy-Geography):
  `book,map,subheading,placename,longitude,longitude-min,latitude,latitude-min`.
- Point `--input` at a directory (or specific CSV/XLSX files) to combine
  multiple sources, e.g.:

  ```bash
  python3 ptolemy_map.py --input data/ more_tables/ --output map.html
  ```

- `--text some_edition.txt` will additionally regex-scan a freeform/plain
  text file for `name  lon-deg lon-min  lat-deg lat-min` style lines. This
  is a best-effort heuristic — use `--dry-run` first to review what it
  extracted before trusting it.

## Coordinate conversion

Ptolemy's latitude is measured from the equator, same as today, so it's
used as-is. His longitude is measured east of a prime meridian at the
"Fortunate Isles" (roughly El Hierro / Ferro in the Canaries), so it's
converted to a Greenwich-relative longitude by subtracting the meridian's
offset (`--ferro-offset`, default 17.6667°).

This is only an approximate modernization. Ptolemy underestimated the
Earth's circumference, so his coordinates are systematically stretched and
skewed relative to reality — worse the further from the Mediterranean.
Treat the plotted points as "where Ptolemy claimed the place was", not
ground truth.

## CLI options

```
--input PATH [PATH ...]   CSV file(s)/directories to load (default: bundled sample)
--text PATH [PATH ...]    Plain-text file(s) to regex-extract references from
--output PATH             Output HTML map path (default: ptolemy_map.html)
--ferro-offset DEGREES    Ferro-to-Greenwich meridian offset (default: 17.6667)
--center LAT LON          Initial map center (default: mean of all plotted points)
--zoom-start N            Initial zoom level (default: 5)
--open                    Open the resulting map in a browser
--dry-run                 Print extracted references instead of building a map
```

## Static image (no tile server needed)

`static_map.py` renders a static PNG using an offline basemap (public-domain
Natural Earth country outlines) instead of live OpenStreetMap tiles - useful
when there's no network access to a tile server, or for a plain image to
drop into a document:

```bash
pip install -r requirements-static.txt
python3 static_map.py --region europe --output europe.png
```

Built-in `--region` choices: `world` (default), `europe`, `mediterranean`,
`asia`, `africa`. Or pass a custom `--bbox LON_MIN LAT_MIN LON_MAX LAT_MAX`.
