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
Leaflet/OpenStreetMap page with a marker (and popup: name, modern
identification, book/tabula, ancient and modernized coordinates) for each of
the ~6,400 plottable references — clustered so the browser stays responsive.

## Point classification & coastlines

Ptolemy didn't just list coordinates - within each region his catalogue is
organized into rubricated sections: a running sequence of coastal points
(capes, river mouths, bays - going around the shore in order), the peoples
inhabiting the area (named but given no coordinates of their own), and the
inland cities. The xlsx loader (`load_xlsx` in `ptolemy_map.py`) recovers
this structure well enough to classify every plotted point into one of:

| Category | Color | How it's detected |
|---|---|---|
| Coastal point | blue | the point's catalogue section is headed by a sea/ocean/gulf name, or its own name matches a cape/river-mouth pattern |
| City / inland settlement | orange | default, for points not in a coastal section and not matching another pattern |
| River source / confluence | teal | name matches "Quelle" (source), "Einmündung" (confluence), etc. |
| Mountain | amber | name matches "Gebirge" (mountain range) |
| Island | pink | name matches "Insel" (island) |

**Coastlines** are then reconstructed by connecting consecutive
coastal-category points *in the catalogue's own listing order*, grouped by
the catalogue's "book.map" prefix (e.g. "2.02") rather than by the printed
tabula (e.g. "EU01") - a tabula routinely bundles several distinct
book.map sub-regions onto one sheet (EU01 = Ireland "2.02" *and* Britain
"2.03"), and grouping by tabula alone drew a spurious line straight across
the sea between the two. A run breaks at a non-coastal point or an
implausibly large jump; broken-off segments are then re-stitched
(`_stitch_segments`) if their loose ends land within ~2.5° of each other,
since that's usually catalogue order being interrupted by an inland aside
rather than a genuine gap in the coast.

This is a heuristic (regex over the German `Locality` text plus section
structure), not a verified ground truth - expect the occasional
misclassified point, or a coastline that runs oddly straight in a region
where Ptolemy's own coordinates were badly distorted (Sarmatia/Scythia are
the worst-known cases - compared against a 15th-century Nicolaus Germanus
redrawing of the same catalogue, the straight-line distortion there turned
out to already be present in Ptolemy's original data, not a bug in this
reconstruction). Use `--dry-run` to inspect the `category` assigned to any
point.

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
