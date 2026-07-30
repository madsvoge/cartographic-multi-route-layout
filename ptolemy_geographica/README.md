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
#) and/or river line and/or mountain-range line, and both its ancient and
modernized coordinates - useful for auditing why two particular points
ended up connected.

## Point classification & coastlines

Ptolemy didn't just list coordinates - within each region his catalogue is
organized into rubricated sections: a running sequence of coastal points
(capes, river mouths, bays - going around the shore in order), the peoples
inhabiting the area (named but given no coordinates of their own), and the
inland cities. The xlsx loader (`load_xlsx` in `ptolemy_map.py`) recovers
this structure well enough to classify every plotted point into one of:

| Category | Color | How it's detected |
|---|---|---|
| Coastal point | dark blue | the point's catalogue section is headed by a sea/ocean/gulf name, or its own name matches a cape/estuary pattern |
| Harbor town | green | name matches "Hafen"/"Portus" - a distinct color from "Coastal point" so a harbor's own commercial/settlement role stands out, but otherwise treated identically: still sized like a coastal point and still a full participant in coastline reconstruction (see below) |
| River mouth | light blue | name matches "Mündung" - a distinct color from "Coastal point" for visual identification, but otherwise treated identically: still sized like a coastal point and still a full participant in coastline reconstruction (see below) |
| City / inland settlement | orange | default, for points not in a coastal section and not matching another pattern |
| River source / confluence / bend | light blue | name matches "Quelle" (source), "Einmündung" (confluence), "Zusammenfluss" (two rivers joining), "(Mitte)"/"Biegung" (a river's midpoint/bend), "Abzweigung"/"Aufteilung" (a delta fork) - checked *before* the coastal mouth pattern, since e.g. "Einmündung" contains the substring "mündung" and would otherwise be misread as a coastal river mouth |
| Mountain | amber | name matches "Gebirge" (mountain range) |
| Island | pink | name matches "Insel" (island), or the name ends in "(N)" - e.g. "Kassiteriden (10)" - the catalogue's convention for a scattered island group given as one count-labelled entry |
| Lake / inland water | light blue (larger marker) | name matches "See" (lake) or "Palus" (marsh/lake) - same color as river points (both read as "inland water" at a glance), sized up instead so a lake still stands out rather than blending in |

Harbors ("Hafen"/"Portus") and estuaries ("Ästuar") are always coastal
regardless of their section, the same as capes and river mouths - they used
to only get classified as coastal when their section happened to be headed
by a sea name, which missed a real chunk of them (most catalogue sections
are headed by the local tribe's name even for points sitting right on the
shore). Harbor towns get their own color rather than folding into "Coastal
point" because a harbor is also a settlement - the same distinction river
mouths already got.

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

Grouping by book.map fixes wrong cross-region connections, but as a side
effect it also stops two *genuinely* adjacent regions from connecting:
Ptolemy's regional maps re-cite their shared boundary point in both
catalogue entries (Kap Oiarso/Cabo Higuer, right at the Spain/France
border, appears once at the end of Iberia's "2.06" and once at the start
of Aquitania's "2.07"), but since each book.map group is only stitched
against itself, those two citations never met - leaving Spain's Biscay
coast and France's Atlantic coast as two disconnected trails. A final
global pass reconnects trails across *any* book.map whose endpoints are
essentially the same point (within 0.1°, tight enough to only catch a
real shared citation, not reopen the cross-region guessing that grouping
by book.map was added to prevent).

Also, "Kap X" (a name that leads with "cape") is now always coastal even
when it also names a mountain range in passing - "Kap Oiarso, Pyrene-
Gebirge (NW-Ende)" ("cape Oiarso, Pyrenees' NW end") was losing to the
mountain check and getting dropped from the coastline entirely, which was
the other half of that same Spain/France gap.

A second, harder-to-generalize problem: some sea-headed sections aren't a
coastal walk at all but a list of scattered islands (Elba/Capraia/Pianosa;
the Balearics; the Sporades; Red Sea and Persian Gulf islands; Corfu;
Euboea; the Cyclades; Lesbos, Chios, Samos and Ikaria; Karpathos; Rhodes;
a handful of small reefs/islets off Egypt's Marmarica coast...), and
nothing in the text reliably tells them apart
from a real coastal-city section headed the same way (Ptolemy's
Gulf-of-Taranto cities - Croto, Thurii, Tarentum - are headed by "Golf von
Tarent" exactly like the island lists are headed by "Tyrrhenisches Meer").
Worse, a name like "Kap Leukimma" (a real cape, on Corfu) or "Kap Sunion"
(the real Attica cape - cited *again*, in the middle of the Cyclades list,
apparently as a reference point rather than the same physical cape) reads
as an unambiguous mainland coastal point from the name alone, with nothing
to say it isn't. A blanket rule would misclassify some section or other, so
`_ISLAND_APPENDIX_SECTIONS` is a small, manually verified exception list
(checked against the `Modern_location` column and known ancient geography)
of the specific `(book.map, section)` pairs confirmed to be island
enumerations - not a general heuristic - and it wins over even an
unambiguous "Kap"-prefixed name. A companion list,
`_ISLAND_POINT_OVERRIDES`, handles the same problem at single-point
granularity for the rare case where only *one* entry in an otherwise
all-mainland section is actually on an island - book.map "3.14" section
"06" is Akarnania's mainland coast except for "Kap Leukas" (Cape Doukato,
on the island of Lefkada), where force-islanding the whole section would
have wrongly reclassified the real mainland points sitting right next to
it.

A section can also mix island points and coastal points and only get
*partly* caught: book.map "4.05" section "75" (a handful of reefs/islets
just off Egypt's Marmarica coast, `Modern_location` names like "Geziret
el-Maracheb" - Arabic for "island") had 2 of its 5 entries already
correctly tagged `island` (their names end in a count, "(3)"/"(2)", the
count-labelled-group pattern), but the other 3 didn't match any
island-specific keyword and fell through to `coast` - which spliced them
into the *main* coastal walk as if they were more mainland capes, drawing
a visible second line doubling back over the same stretch of coast this
section's points were already scattered along. Adding the whole section to
`_ISLAND_APPENDIX_SECTIONS` (rather than patching the 3 stray entries
individually) fixed all 5 at once and removed the double line. If you spot
another sea-crossing line, check the two points'
`Modern_location` in the spreadsheet (or click them in the interactive
map) - if they're islands, tell me their section (`book.section` prefix of
the `ref_id`, e.g. "6.08") or the individual `ref_id` and I can add it.

This is all heuristic (regex over the German `Locality` text plus section
structure and graph reconstruction), not a verified ground truth - expect
the occasional misclassified point, or a coastline that runs oddly
straight in a region where Ptolemy's own coordinates were badly distorted
(Sarmatia/Scythia are the worst-known cases, and central-eastern Spain is
another - compared against a 15th-century Nicolaus Germanus redrawing of
the same catalogue, that kind of straight-line distortion turned out to
already be present in Ptolemy's original data, not a bug in this
reconstruction). Use `--dry-run` to inspect the `category` assigned to any
point.

Several exception lists handle cases neither the header nor the point-name
regexes can resolve on their own, all manually verified against
`Modern_location` plus known ancient geography: `_ISLAND_APPENDIX_SECTIONS`
(keyed by `(book.map, section)`) for sea-headed sections that are actually
a scattered island list (see above); `_ISLAND_POINT_OVERRIDES` (keyed by
individual `ref_id`) for the same problem at single-point granularity; and
`_NONCOASTAL_EXCEPTION_SECTIONS` (keyed by `(book.map, section)`) for the
mirror-image problem - a coastal-*sounding* header whose points are really
inland. E.g. book.map "2.03" section "17" is headed "Hafenreicher Golf"
("harbor-rich gulf") but its points are Eboracum (York), Camulodunum
(Colchester), and Petuaria (Brough-on-Humber) - inland Roman-Britain towns,
not capes or mouths - which had spliced a detour up to York into the
middle of the England coastline between East Anglia and Kent.

A third, similarly narrow exception list handles the loop-closing ratio
check (see `_CLOSE_LOOP_MAX_GAP_RATIO` above) getting it wrong: Sardinia's
real closure (Kap Hermaeum round to Kap Errebantium, book.map "3.03") and
Macedonia's mainland coast (Neapolis/Kavala down to the Spercheios river
mouth near Thessaly, book.map "3.13") close at the *same* ratio - 24.3% -
even though only one of them is an island. No ratio threshold can tell
those two apart, so `_NO_CLOSE_LOOP_TRAILS` excludes the Macedonia one by
its trail's start/end `ref_id` pair, verified the same way as the other
two lists.

A fourth handles a different structural quirk: Ptolemy sometimes opens a
region's description with a boundary point ("this region extends south to
the mouth of the Acheloos") before the region's own coastal enumeration
begins, then cites that same point again, correctly, where the walk
actually reaches it. Book.map "3.14" (Epirus/Akarnania) section "01" is a
single-row section - "Acheloos-Mündung" - sitting alone right before the
walk starts at "Akrokeraunische Berge" in section "02"; the same point (same
name, same coordinates) shows up again, correctly, as the walk's actual
last point in section "06". Both citations are real edges under ordinary
catalogue adjacency, so node-collapsing merged the two "Acheloos" rows
into one graph node connected to *both* ends of the walk - turning an
open coastal walk into a closed loop and drawing its first line as a jump
straight across the region. `_COASTLINE_SKIP_REF_IDS` excludes the
introductory citation from coastline-edge-building by its `ref_id` (it
still plots normally as a river-mouth marker - it just doesn't get
treated as a step in the coastal walk). Checked the rest of the catalogue
for the same signature (a book.map's first coastal-category citation
exactly duplicating a later one's coordinates) - most either exceed the
gap cap on both sides (so they never form a spurious edge to begin with)
or are genuine cases the graph reconstruction already handles correctly
(Ireland's "Nordspitze", cited at the start of both its north and west
coast walks; the Oxos' mouth, genuinely re-cited to close a small real
loop in Central Asia) - only the Acheloos case produced this failure mode.

A fifth handles the opposite failure: two trails that *should* connect but
don't. The final global stitching pass (`_SAME_POINT_TOL_DEG * 2` =
0.1 degrees) reconnects book.map trails whose endpoints are essentially
the same point - deliberately tight, so it only catches a genuine shared
citation and doesn't reopen the cross-region guessing that grouping by
book.map exists to prevent. That tightness occasionally excludes a real
one: Epirus/Akarnania's coast (book.map "3.14") ends at the Acheloos'
mouth, and Aetolia's (book.map "3.15") starts at "Kap einer Halbinsel"
0.12 degrees away - the same stretch of coast, split only because Ptolemy
describes it under two regional headings, but just outside the
auto-stitch window. Rather than loosen that window everywhere (and risk a
false stitch elsewhere), `_BOUNDARY_STITCH_REF_ID_PAIRS` force-joins
specific endpoint `ref_id` pairs manually verified to be the same
hand-off, regardless of the exact distance between them. The same pattern
recurs at real political/geographic borders throughout the catalogue, each
its own book.map hand-off just outside the auto-stitch window: Thrace into
Macedonia at the Nestos' mouth, Illyria into Epirus at the Ceraunian
mountains, Spain into Gaul at the Mediterranean border (a second,
independent gap from the Atlantic-side Kap Oiarso case above), and
Mauretania Tingitana into Mauretania Caesariensis into Africa
Proconsularis (Morocco - Algeria - Tunisia) at the Moulouya and
Oued-el-Kebir rivers - five pairs in total so far.

Not every gap between adjacent book.map trails is this kind of bug,
though - some are genuinely sparse source material, not a missed
same-point citation. Libya's coast has a real ~4-degree jump between Kap
Misurata (end of book.map "4.03") and the start of "4.04" - Ptolemy simply
named few points along the vast, sweeping Gulf of Sidra (Syrtis Major),
matching its real geography. Forcing a stitch there would draw a line
based on nothing; left alone, the visible gap honestly reflects a real gap
in the source. Only stitch a pair once you can identify what real place
sits at both ends.

If a coastline still visibly closes into a loop across open water or
straight across a mainland, jumps in a way that looks like the
introductory-citation pattern, or looks like it should continue into a
neighbouring book.map's trail but doesn't, tell me the relevant `ref_id`s
(hover the line's ends in the interactive map, or read them off
`--label-coastlines` in the static one) and I'll add it to the
appropriate list.

## River lines

**Rivers** are drawn as their own light-blue lines (`build_river_lines` in
`ptolemy_map.py`), separate from the coastline reconstruction above. A
river's points aren't laid out as one continuous walk the way a shoreline
is - Ptolemy's catalogue instead returns to the same named river at
different points in its regional entry (a mouth in the coastal run,
a bend or confluence, a source), so a river line is built by grouping
`river`/`river_mouth` points that share a base name - stripping the
course/mouth suffix ("-Mündung", "(Quelle)", "(Biegung ...)", etc.) - and
connecting them in catalogue order, the same categorization-plus-sequence
approach as coastlines, just grouped by name instead of by graph edges.

Grouped by `book` (continent) as well as name, since a bare name isn't a
safe key on its own: the catalogue reuses common river names for entirely
unrelated rivers - three separate entries are each named "Deva" (two in
Roman Britain, one in Iberia) - and a single real river can legitimately
span several book.map entries within the same book (the Danube's course is
told across three, "2.11" through "3.09"). A run also breaks wherever
consecutive points are more than ~10° apart - there's no gap size that
cleanly separates "a genuine long-distance jump" from "different river,
same name": the worst-distorted Asian rivers (Indus, Ganges) have real
internal jumps of ~18-22°, which overlaps the ~13-19° gaps seen between
different rivers that merely share a name (Deva, Rha, Lykos). Given that
overlap, the cap errs toward splitting a real river into several shorter,
individually-trustworthy lines rather than ever drawing a confident-looking
connection between two unrelated ones - so a badly-distorted river like the
Indus may end up as two or three disconnected line segments instead of
one continuous course.

This covers a bit under half of all `river`/`river_mouth` points (some
names never repeat - a mouth cited once with no matching source/bend
elsewhere - and a handful of rows name no river at all, e.g. "Biegung gegen
Osten", relying on context from a neighbouring row that this heuristic
doesn't reconstruct). Those points still plot individually; they just
don't get a connecting line.

The "Deva" case named above turned out to need more than the book-level
grouping and 10° gap cap once actually checked (river review round,
below): both Britain-internal "Deva"s (not the Iberian one, which is
already a different book) and four more same-name-different-river pairs
elsewhere sat close enough under that cap to still merge wrongly.
`_RIVER_LINE_NO_MERGE_REF_ID_PAIRS` forces a split for those specific,
individually-confirmed pairs; `_RIVER_LINE_SKIP_REF_IDS` drops a specific
duplicate re-citation from consideration entirely (the Danube's own
Savus-confluence case). Separately, `topostext/river_mentions.py` scans
every point's topostext citation for a *different* river's name and
records it in a `river_mentions` column - not a connecting line, just a
read-only note ("this city's citation also names this river") for
relationships (a tributary confluence, a settlement's own text placing
it beside a river) the same-name line-building above has no way to draw.
See the river review round further down for the full evidence.

## Island outlines

**Islands** are drawn as their own pink lines (`build_island_lines` in
`ptolemy_map.py`), the same color as the `island` category's points.
Unlike coastlines and rivers, this isn't automatic: it's an explicit,
manually-verified allow-list (`_ISLAND_LINE_GROUPS`), because gap size
can't tell "these points trace one island's own shore" apart from "these
points are a *list* of several different islands" - Corfu's own capes sit
0.3-0.8° apart in catalogue order, but so do plenty of different Cycladic
islands cited back to back. Only sections confirmed to be one island's own
detailed coastal walk are connected: Corfu, Euboea (told across three
consecutive sections, merged into one line), Lesbos, Karpathos, and Rhodes
so far. Everything else classified `island` - the Cyclades, the Sporades,
the Balearics, Elba/Capraia, the Dodecanese, Red Sea and Persian Gulf
islands, the Ganges delta - is a *list* of separate islands with no
reliable way to tell where one ends and the next begins from the text
alone, so those still plot as individual, unconnected points. If you know
a section is actually one island's own coastal walk, tell me its
`(book.map, section)` and which island, and I'll add it to
`_ISLAND_LINE_GROUPS`.

Those remaining unconnected `island` points still get a small pink
schematic circle drawn around them (`folium.Circle` in `ptolemy_map.py`,
a `matplotlib.patches.Circle` in `static_map.py`), rather than sitting as
a bare dot - the way a cartographer working from just one reported
position for an island would still have sketched a small round island
there, not left it off the map. The circle's size carries no geographic
meaning (all of them are drawn the same size) - it's a stylistic
placeholder for "this is an island we don't have a shape for," not a
claim about the island's real extent.

## Mountain-range lines

**Mountain ranges** are drawn as thick brown lines (`build_mountain_lines`
in `ptolemy_map.py`), the same "categorization + sequence" approach as
river lines. A range in the catalogue is never a continuous walk either -
Ptolemy cites its own named ends ("(W-Ende)"/"(O-Ende)", or "(N-Ende)"/
"(S-Ende)", "(SW-Ende)"/"(NO-Ende)", etc.) and sometimes a midpoint
("(Mitte)"/"(Mittelpunkt)"), each its own catalogue entry - so
`_mountain_base_name()` groups points by the range's own name with its
position marker cut off (everything from the first `(`, ` bzw.`, or ` / `
onward - there's too much free-form variety in how a position is phrased
to enumerate, unlike a river's fixed set of course words), the same shape
as `_river_base_name()`. The two largest ranges (Kasia, Emoda's
neighbour in Book 6) are each cited as two separately-numbered halves,
"(westl. Teil, ...)"/"(östl. Teil, ...)" ("western part"/"eastern part") -
recognized and kept rather than stripped, so the two halves stay in their
own groups instead of merging into one line that jumps across the gap
between them.

Grouped by `book` as well as name (mirroring `_RIVER_LINE_MAX_GAP_DEG`),
but with a looser 20° gap cap and no evidence it's needed for name-collision
safety the way the river cap is: every mountain base name checked, even the
widest real span (18.4° for Anniba-Gebirge in India), turned out to be one
range's own genuine end-to-end extent - unlike rivers, no case of two
*different* ranges sharing a bare name inside one book turned up in this
catalogue. The same re-citation dedup as river lines applies too: a range's
end is sometimes re-cited verbatim where it's later reused as a boundary
marker between two book.map sections (Buzara-Gebirge, Koronos-Gebirge, and
Mondgebirge's - the classical "Mountains of the Moon," Ptolemy's legendary
source of the Nile - O-Ende/W-Ende all reappear this way), collapsed the
same way a river's revisited point is.

Building this surfaced a real classification bug, independent of the
mountain-line feature itself: 31 river source/mouth/confluence points
across Book 7 (India) - "Namenloser Fluss (Quelle am Arbita-Gebirge)"
("unnamed river, source at the Arbita mountains"), "Narmades-Quellen im
Vindion-Gebirge" ("...source in the Vindion mountains") - were sitting in
`mountain` instead of `river`, because the classifier's name-anchored
`_MOUNTAIN_NAME_RE` tier ("-Gebirge"/"-berg", meant to always win - see the
Alps false-positive fix above) matched the mountain's name wherever it
appeared, even as a river point's *location* rather than its own identity.
Distinguishing this case from a genuine range point that also happens to
match a river-course keyword (~50 "X-Gebirge (Mitte)" entries match
`_RIVER_COURSE_RE`'s "(mitte)" too, and must *not* flip) needed a more
specific signal than "is this also river-like": a new `_MOUNTAIN_LOCATION_REF_RE`
checks whether the range name sits as the object of "am"/"im"/"vom"/"von"/
"zum" ("at/in/from/to the ... mountains") rather than as the point's own
leading name, and only then does a river keyword win over `_MOUNTAIN_NAME_RE`.
Fixing this also *repaired* several river lines that these points should
have belonged to (Narmades, Nanagunas, Pseudostomos, Baris, Solen, Tynas,
and others' source points) but couldn't reach while miscategorized as
mountains: 103 → 111 river lines, 263 → 281 points-in-a-line.

This covers 135 of 293 `mountain` points, grouped into 66 lines (a
single-citation range - most of the catalogue's ~150 named peaks/ranges
only ever appear once, with no second point to connect to - still plots as
an individual point, no line).

## Feature labels

Beyond individual points, the map carries **text labels** for three kinds
of named feature - a province ("Thrace", "Britannia"), a named island
group ("Corfu", "Rhodes"), a named mountain range ("Pyrene-Gebirge") -
each drawn as plain italic text rather than a colored marker (a dedicated
"Region/feature labels" layer in `ptolemy_map.py`'s folium output;
`ax.annotate` with a white outline in `static_map.py`). These are
synthetic rows, `category == "label"`, added on top of the regular
xlsx-derived dataset by `topostext/build_labels.py` - they carry no
`ref_id` from the catalogue and don't participate in coastline/river/
island/mountain-line reconstruction.

- **Province labels** are positioned at the centroid of every catalogue
  point in that book.map, and named from topostext's own opening sentence
  for the province's first section ("Setting of Hivernia British island",
  "Position of Macedonia", "Sarmatia is bounded on the north..." - see
  `_PROVINCE_LABELS` in `build_labels.py`). This pattern is near-universal
  across the whole range topostext has covered so far, but isn't a safe
  find-and-extract job: topostext's own book.map numbering runs one map
  ahead of ours for a stretch of book 3 (their §3.12 "Position of
  Macedonia" is actually our catalogue's book.map 3.13 - our catalogue
  gives the Thracian Chersonese its own separate map 3.12, headed
  "Thrakische Chersones" directly in the xlsx, that topostext doesn't
  number separately), so every entry was verified against a sample of its
  book.map's own `Modern_location` values, not assumed from the section
  number alone. 85 provinces are labelled this way, covering every book
  topostext has been cross-checked against - all of books 2 through 7.
- **Island-group labels** reuse the five confirmed one-island coastal
  walks already in `_ISLAND_LINE_GROUPS` (Corfu, Euboea, Lesbos, Karpathos,
  Rhodes) - no new lookup needed, just the centroid of that built island
  line's own points under its already-verified name.
- **Mountain-range labels** likewise reuse every `build_mountain_lines()`
  feature (63 of them) - the shared base name is already encoded in its
  `mountain_feature_id`.

A supplementary note - a people/tribe name, an alternate name, a caveat
about how the label was derived - goes in the `label_note` column, shown
in the popup/tooltip alongside the name; most labels have none.

Run order matters: `build_labels.py` reads the already-annotated,
already-linked catalogue and appends label rows on top, so it must run
*after* `annotate_dataset.py` and `link_matches.py`, not before - and
since `annotate_dataset.py`'s `write_annotated_csv()` only knows the
regular schema, re-running it wipes the label rows out entirely (not just
the two match-status columns, as with `link_matches.py`), so the full
refresh order is:

```bash
python3 annotate_dataset.py
python3 topostext/link_matches.py
python3 topostext/river_mentions.py
python3 topostext/build_labels.py
```

`build_labels.py` strips any label rows already present before adding
fresh ones, so it's safe to re-run any number of times. `river_mentions.py`
(see the "River review" section below) needs `link_matches.py`'s
`topostext_name` column and must run *before* `build_labels.py`, so its
synthetic label rows pick up a (blank) `river_mentions` column instead of
the CSV ending up with mismatched columns across row types.

## Cross-checking against topostext.org (`topostext/`)

Every classification and stitching decision so far has been verified
against the `Modern_location` column and outside knowledge of ancient
geography - useful, but it's still one person reading German place names
and guessing. `topostext.org/work/209` publishes an *English* translation
of the Geographica itself, paragraph-numbered `§ book.map.section` - the
same book.map.section our `ref_id` uses, confirmed by hand against
Ireland's north coast (`§2.2.1`'s Boreum/Vennicnium/Vidua/Argita/Rhobogdium
lines up point-for-point with our `2.02.02.01-05`). Crucially, its prose
states outright what a point *is* ("A description of the north coast...",
"the following are the inland towns...", "the islands which are near
Albion island...") instead of us inferring it from a keyword regex - an
independent check, not just a second opinion from the same method.

That prose has ended up doing more than confirming individual coordinate
matches - it's been the actual *source of understanding* behind most of
the structural features on the map, not just an afterthought check on
them:

- **Island lists** (`_ISLAND_APPENDIX_SECTIONS`/`_ISLAND_POINT_OVERRIDES`
  in `ptolemy_map.py`) exist almost entirely because topostext says so in
  plain English - "the islands which are near Albion island...", "The
  islands around Sardinia are...", "An island lies off Iulia Caesarea,
  with the same name" - sentences a German place name alone never states
  outright. Same for the mountain-name lists in `_MOUNTAIN_APPENDIX_SECTIONS`
  ("These are the named mountains in Asia, of which the central points
  are...").
- **Coastline bugs** - a spurious phantom coastline, a spurious tail
  stitched onto a real one - were caught by first confirming, from
  topostext's own wording, that a point was genuinely an island or an
  inland plain rather than a coastal point, *then* seeing the coastline
  graph's point count move in a way a pure category swap couldn't explain
  (see the pilot-run notes below for the specific cases).
- **River-mouth phrasing** ("mouth of the X river", "X river outlet")
  and **category words generally** ("promontory", "estuary", "harbor")
  are what `crossref_topostext.py`'s `_TYPE_HINTS` reads to flag when our
  own category disagrees with what the English text plainly says a point
  is - the audit signal that found the Corfu/Euboea/Egypt bugs.
- **Feature labels'** names (see above) are lifted directly from
  topostext's own opening sentence for a province, not invented or
  translated from the German locality name.
- Two real **parser bugs** in `parse_topostext.py` itself (a required-
  minutes coordinate regex silently dropping Book 4's bare-degree
  southern-hemisphere points; a section marker regex missing one book.map
  because of a stray trailing period) were only found because reading the
  actual pasted text made a suspiciously low point count, or a
  suspiciously merged section, visible - errors that stayed invisible
  from the catalogue side alone.

The tool can't fetch topostext.org itself (blocked by this environment's
network policy), so the workflow is: paste a chunk of the site's text into
the conversation, save it under `topostext/raw_209_<range>.txt`, then:

```bash
cd topostext
python3 parse_topostext.py raw_209_<range>.txt -o topostext_209.csv --append
python3 link_matches.py
python3 crossref_topostext.py
```

`parse_topostext.py` splits the pasted text on `§ B.M.S` markers and pulls
every `(name phrase, longitude, latitude)` triple out of each paragraph in
catalogue order. It does *not* try to align by position within a
paragraph - topostext often folds a paragraph's opening point into its
lead sentence as a restatement of the *previous* paragraph's last point
("from the Boreum promontory which is in 11°00' . 61°00'..."), the exact
same "shared boundary citation" pattern already found directly in our own
data (Kap Oiarso, Nordspitze, Acheloos-Mündung) - so position-in-paragraph
isn't a reliable join key. `link_matches.py` instead matches by a blended
distance+name score (see "Coverage" below) and writes the result back
into the annotated catalogue; `crossref_topostext.py` reads those columns
and flags cases where our `category` looks inconsistent with topostext's
own wording (originally it re-matched by coordinate itself, with a
strict tolerance and no fuzzy fallback - see the "closing the validation
loop" round further down for why and how that changed).

The first pilot run (Ireland and Britain, `§2.2`-`§2.3`) found two real,
previously-undetected bugs this way:

- Five whole sections - the Hebrides (`2.02.11`), Isle of Man/Anglesey
  (`2.02.12`), Skye/Lewis/Orkney (`2.03.31`), Thule's five extremity
  points (`2.03.32`), and Thanet/Isle of Wight (`2.03.33`) - were sitting
  in `city` because none of their point names matched an island keyword
  and their sections weren't sea-headed, even though topostext says
  outright "the Ebuda islands five in number...", "the islands which are
  near Albion island...". Added to `_ISLAND_APPENDIX_SECTIONS`.
- 25 points across the *entire* catalogue, not just Britain, were named
  "Golf von X"/"X-Bucht"/"X-Meerbusen" (gulf/bay) but had fallen to `city`
  because their own section's header didn't independently carry a
  recognized sea word - caught because topostext plainly called two of
  them ("Dunum bay", "Gabrantuicorum bay") a bay. A point named after a
  gulf is coastal by definition, the same reasoning already applied to
  "Kap"/"Hafen"/"Ästuar" - so this became a new keyword rule in
  `_classify_locality` (`_GULF_RE`) rather than five one-off exceptions.

Not every flagged mismatch is a bug - "Petuaria" (already a manually
verified inland exception, `_NONCOASTAL_EXCEPTION_SECTIONS`) gets flagged
too, because topostext mentions a nearby bay in the same sentence without
the matched point itself being on it. The tool's job is to surface
candidates for a human to look at, not to auto-correct - review the
`possible category disagreements` list before changing anything.

A second pilot run (Iberia and Gaul, `§2.4`-`§2.11`) found three more real
bugs of the same kind:

- "Rhodanus (Biegung südlich von Lugdunum, zu den Alpen hin)" ("...bend
  south of Lyon, *toward* the Alps") and "Licius (Oberlauf), Alpes
  Poeninae" ("...upper course, Pennine Alps") were both classified
  `mountain`, because the bare word "Alpen"/"Alpes" matched the same
  keyword rule as ~50 genuine "X-Gebirge (Mitte)" mountain-range midpoint
  citations elsewhere - but in these two, "Alpen"/"Alpes" only names the
  Rhône/Ticino's *location*, not what the point itself is: both are river
  points. Fixed by splitting the mountain check into two tiers -
  `_MOUNTAIN_NAME_RE` ("-Gebirge"/"-berg", always wins) and a weaker bare
  "Alpes"/"Alpen" tier that only applies when the name isn't *also* a
  recognized river-course/source/mouth pattern (the same reasoning
  already used to keep a gulf's own bend out of the river-course rule).
  "Calpe" (Mons Calpe, the Rock of Gibraltar - "Calpe mountain and pillar
  of the Inner sea") had the opposite problem, a real mountain with no
  "-Gebirge"/"-berg"/"Alpen" of its own, sitting in `city` - added to the
  name-anchored tier as a specific, unambiguous proper name.
- Six "X (Quellgebiet)" entries (a river's source *region* - the Rhine,
  Loire, Durance, Vistula ×2, Danube) were in `city`; `_RIVERFEAT_RE`
  matched "Quelle" but not "Quellgebiet", which doesn't contain that exact
  substring. Broadened the pattern from "quelle" to "quell".
- Two more island sections: Londobris (the Berlengas, off Lusitania -
  "An island lying off Lusitania, Londobris") and a set of four islands
  off Narbonensis (Agde island, Île de Brescou, the Îles d'Hyères, Île
  Sainte-Marguerite - "Islands lying off Narbonenses are Agathe...").

Cross-referencing the Iberia/Gaul chunk also fixed a river-line-*connection*
bug distinct from the classification bugs above: "Druentia (Quellgebiet)"
and "Druentia (Einmündung in den Rhodanus)" should have formed a two-point
river line but didn't, because `_river_base_name`'s own suffix-stripping
regex (`_RIVER_SUFFIX_RE`, separate from the classifier's `_RIVERFEAT_RE`
and missed by that same-named fix above) also matched "quelle" but not
"Quellgebiet" - so the two points reduced to different base names
("Druentia (Quellgebiet)" unstripped vs. "Druentia") and never landed in
the same group. Broadened it the same way, plus added "oberlauf"/"unterlauf"
for consistency; Druentia now forms its own line and the other five
Quellgebiet points correctly rejoined their rivers.

Checking topostext's confluence descriptions against ours (per the request
to verify branch/fork points, which the source text often states only
implicitly) surfaced a second, more pervasive river bug, this time entirely
within our own data: `build_river_lines()` grouped points by name and
catalogue order but never deduplicated them, so wherever Ptolemy re-cites a
point already given earlier in a river's course - the same "shared boundary
citation" pattern already fixed for coastlines (Kap Oiarso, Nordspitze,
Acheloos-Mündung via `_COASTLINE_SKIP_REF_IDS`/`_BOUNDARY_STITCH_REF_ID_PAIRS`),
just showing up mid-sequence here instead of at a bookend - the line jumped
forward to the new point, backtracked to redraw the old one, then jumped
forward again. About 20 rivers were affected, from a mild "there-and-back"
on short rivers to a serious zigzag on the 17-point Danube (three separate
re-citations: "Einmündung des Arabon", "Krümmung bei Curta", and "Biegung
bei Cirpi" each cited twice, once per book.map continuation) and an almost
entirely duplicate 5-point Tigris (really only two physical points - its
eastern and western mouths - cited repeatedly across `§5.20`/`§6.03`).

Fixed generally rather than as one-off exceptions: `build_river_lines()`
now drops any point that lands within `_SAME_POINT_TOL_DEG` of a point
already kept earlier in that river's sequence, before segmenting by the
gap cap. A river's course never legitimately loops back the way a
coastline can, so any revisit is always safe to collapse. One case needed
checking before applying this blindly: `Nanagunas (Aufteilung zur
Bindas-Mündung)` and `Nanagunas (Aufteilung zur Goaris-Mündung)` looked
like they might be a genuine fork - two different delta branches - rather
than an erroneous re-citation, since "forgreninger" (branchings) can be
described implicitly. They turned out to share the *exact same* coordinate
(114.0 . 16.0): Ptolemy cites the single physical split point twice, once
under each downstream branch's name, but doesn't give the two branches'
own separate coordinates in this stretch of the catalogue (those live
elsewhere, as standalone `Bindas-Mündung`/`Goaris-Mündung` river-mouth
points that aren't connected to this line at all). Collapsing the pair
loses no line geometry - both citations already draw through the same
spot - so the general coordinate-based dedup was safe to apply as-is.
Rerunning `annotate_dataset.py` afterward: 111 → 103 river lines, 304 → 263
points-in-a-line (the removed points are exactly the re-citations; a
handful of rivers that were *entirely* re-citations of the same one or two
points, per the Tigris case above, dropped from a false 3+-point line to
the correct 2-point one, and none fell below the 2-point minimum needed to
draw a line at all).

A third pilot run (Germania's mountains/Raetia/Noricum/both Pannonias/
Illyria and Dalmatia, `§2.11.4`-`§2.16`, plus the start of Italy, `§3.1`)
found three more real bugs, this time mostly surfaced by the mountain-line
work above rather than a fresh keyword sweep:

- Scandia - the large island opposite the Vistula's mouth, Ptolemy's
  Scandinavia - has four extremity points (`Scandia W/O/N/S`) the same
  shape as Thule's five, but was sitting in `city`: topostext states
  outright "This island is itself properly called Scandia, and its
  western parts are inhabited by..." Added `(2.11, 34)` to
  `_ISLAND_APPENDIX_SECTIONS`, the same fix as Thule got.
- "Skardon" (a boundary marker on Illyria's eastern border, "the point at
  Skardon mountain" per topostext, cited again in the very next section as
  the source of the river Drilon, "Mt. Skardon") was in `coast`, picked up
  by the section-header sea-fallback since it sits amid Illyria's overall
  bounded-by-the-Adriatic description. A specific, unambiguous proper name
  with no generic "-Gebirge"/"-berg" suffix of its own - the same shape as
  "Calpe" - so added to that same name-anchored tier as a bare word
  (`skardon` doesn't collide with "Skardona", an unrelated city/island
  cited in the same chunk, since the word boundary after "n" excludes it).
- "Namenlose(r) Berg(e)" ("unnamed mountain(s)") - the mountain-side
  counterpart of "Namenloser Fluss" - names a peak with no proper name of
  its own, and wasn't recognized by `_MOUNTAIN_NAME_RE` at all (its
  "-berg"/"^berg" checks require a hyphen or match at the very start,
  neither of which "Namenloser Berg" satisfies). Five citations across the
  whole catalogue - one in Illyria (topostext: "Mt. Skardon and from *that
  other mountain*..."), four scattered from Arabia to Persia - were sitting
  in `city`. Matched as a phrase rather than folded into a bare `\bberg\b`
  rule, to avoid the same "location, not identity" trap `_MOUNTAIN_LOCATION_REF_RE`
  already guards against for `-Gebirge`. Since all five reduce to the exact
  same base name with nothing else to distinguish them, `build_mountain_lines`
  needed the same "generic placeholder name" guard `build_river_lines`
  already has for "Namenloser Fluss" (`_GENERIC_RIVER_NAME_RE`, reused here
  rather than duplicated) - without it, fixing the classification would have
  drawn a nonsense line connecting five unrelated peaks from the Balkans to
  the Persian Gulf.

A fourth pilot run (Cisalpine Gaul's rivers and lakes, the Alpine peoples,
Corsica, Sardinia, Sicily, and the start of Sarmatia, `§3.1.24`-`§3.5.6`)
found the largest batch yet, all variations on "a word our keyword rules
never learned to recognize":

- Four points along the Padus/Doria (Po) river system named after a lake
  they source from or drain into - "Padus (Ausfluss aus Lacus Larius)"
  ("Po, outflow from Lake Como"), "Doria (Ausfluss aus Lacus Poeninus)",
  bare "Lacus Benacus" (Lake Garda) - were in `city`. "Ausfluss" (outflow)
  is the same kind of river-origin point as "Quelle"/"Ursprung", just for a
  river starting at a lake instead of a spring, so added to
  `_RIVERFEAT_RE`; "Lacus" (Latin for lake, used only for these four points
  - everywhere else in the catalogue uses German "See"/"Palus") added to
  `_LAKE_RE`. Checked before adding either: the river check runs first in
  `_classify_locality`, so the two dual-named "Ausfluss...Lacus..." points
  correctly land on `river` (their primary identity) while bare "Lacus
  Benacus", with no river keyword of its own, correctly falls through to
  `lake`.
- The biggest gap: "Berg"/"Berge" ("mountain(s)") as its own separate word
  - "Goldener Berg" ("Golden mountain"), "Rasende Berge" ("the Mainomena
    mountains", literally "raging mountains"), "Sarmatische Berge
    (S-Ende)/(N-Ende)", "Heiliger Berg", "Weisse Berge", "Libysche Berge",
    "Äthiopische Berge", "Mareitha-Berge" - wasn't recognized by
    `_MOUNTAIN_NAME_RE` at all: its "-berg\b"/"^berg\b" checks require a
    hyphen immediately before the word or a match at the very start, and
    none of these satisfy either (an adjective, not a hyphen, precedes
    "Berg"/"Berge"). 13 points across the whole catalogue were sitting in
    `city`, and three more - "Gordyaische Berge (Mitte)", "Berge aus denen
    die Flüsse...fliessen (Mitte)", "Strongylon (Mitte) bzw. Berg der
    Semiramis" - were in `river`, caught by the river-course pattern's
    "(Mitte)" before ever reaching a mountain check that didn't fire.
    Fixed with a fourth, weaker classification tier: a bare `\bberge?\b`
    match, guarded three ways so it never overrides a point already doing
    real work elsewhere - not river-like via a location reference (the
    same `_MOUNTAIN_LOCATION_REF_RE` check as the `-Gebirge` tier), not in
    a sea-headed section, and not also matching a cape/gulf/harbor/estuary
    pattern. That last pair of guards matters: Mount Athos ("Athos, ein
    Berg") and "Akrokeraunische Berge (Spitze)" are real, working coastline
    points (a range that happens to end at the sea, the same reasoning
    `_KAP_WORD_RE` already uses for "Kap Oiarso, Pyrene-Gebirge") and
    stayed exactly where they were - confirmed unchanged (61 coastline
    features before and after).
- "Karpaten" (the Carpathians - topostext: "the beginning of Mt. Karpatos",
  "Mt. Karpata") was in `city`, three re-citations of the same boundary
  point (all at the identical coordinate, so no line either way regardless
  of category) - added to the specific-proper-name tier alongside "Calpe"/
  "Skardon".
- Three more island-list sections, the same shape as the Cyclades/Dodecanese
  (several different islands enumerated together, only some of which happen
  to carry an explicit "-Insel" suffix of their own): the islands around
  Sardinia (`3.03.08` - Ilva, Nymphaea, Diabate, Ficaria, Hermaea sat in
  `city` alongside their already-`island` neighbours) and two sections of
  islands around Sicily (`3.04.16`/`3.04.17` - Didyme, Hikesia, Erikodes,
  Phoinikodes, Euonymos, Lipara, Strongyle, Ustica, Osteodes, Phorbantia,
  Aigusa, Hiera, Pakonia), confirmed by topostext's own headers ("The
  islands around Sardinia are...", "the islands located around Sicily...").

Not every flagged mismatch was a bug even this time round - "Rhoetius
mountains" at topostext's `30°00' . 40°20'` lands exactly on our own
"Rhoetium (Rhytium)" city point in Corsica's coastal-city list, with no
independent "Rhoetius-Gebirge" entry anywhere in the source catalogue to
back up a separate mountain citation - most likely a quirk of the English
translation itself rather than something to "fix" by inventing a mountain
our primary source doesn't have.

A fifth pilot run (the rest of Sarmatia, the Tauric Chersonese, the
Migratory Iazyges, Dacia, both Moesias, Thrace, the Thracian Chersonesos,
Macedonia, Epiros, Achaia/the Peloponnese, and Crete, `§3.5.7`-`§3.15.11`)
found a new *shape* of missing-keyword bug and four more island-list
sections:

- Whole sections that are purely a *list of named mountains*, each its own
  classical proper name with no "-Gebirge"/"-berg" suffix at all to catch
  by any keyword - "Of the named mountains the center of Bertiskos lies
  at...Mt. Bermion...Mt. Olympos..." (Macedonia, including Mount Olympus
  itself) and "Mountains in the Peloponnese Pholoe...and Stymphalos..."
  were both sitting entirely in `city`, 14 points between them. The
  mountain-side counterpart of the island-list sections: no shared pattern
  to regex on, so it needs an explicit allow-list the same way. Added
  `_MOUNTAIN_APPENDIX_SECTIONS` (`(3.13, 19)`, `(3.16, 14)`) and the
  matching `force_mountain`/`force_mountain_point` parameters to
  `_classify_locality`, mirroring `_ISLAND_APPENDIX_SECTIONS`'s own
  two-tier design exactly (whole-section allow-list plus a single-point
  override, `_MOUNTAIN_POINT_OVERRIDES`, for "Athos (Mitte)" - the
  mountain's own midpoint sitting inside Chalkidike's *coastal* section
  alongside the two genuine coastline points "Athos, ein Berg"/"Athos,
  Kap und Berg", which forcing the whole section would have wrongly pulled
  out of their coastline). More such mountain-list sections likely exist
  elsewhere in the catalogue, not yet found because their books haven't
  been cross-referenced yet.
- Four more island-list sections, the same shape as Sardinia/Sicily's
  above: a single island reference off the Tanais' mouth ("Alopekia bzw.
  Tanaïs", confirmed by topostext: "An island lies off the mouth of the
  Tanais river, Alopekia or Tanais island" - added to
  `_ISLAND_POINT_OVERRIDES`), the two islands off Lower Moesia
  (`3.10.17` - Borysthenis sat in `city` right next to its already-`island`
  neighbour Achilles-Insel), the islands adjoining the Peloponnese
  (`3.16.23` - Strophaden, Prote, Sphagia, Theganusa, Kythera, Aigila,
  Salamis, Aigine, all in `city`, no "-Insel" keyword present anywhere in
  the list), and the islands adjacent to Crete (`3.17.11` - Kaudos, Letoa,
  Dia, Kimolos, Melos, same pattern).

A sixth pilot run (Mauritania Tingitana, Mauritania Caesariensis, and
Africa proper, `§4.1.1`-`§4.3.47`) found a genuine coastline-building bug
underneath a category fix, plus more of the same mountain/island-list
shapes:

- Two islands "offshore to the west in the Outer ocean" (Paena/Erythia,
  `4.01.16`) were sitting in `coast`, not `city` - because a *third* point,
  "Pyrrhon-Ebene" ("Pyrrhon Plain", `4.01.10.16`), was *also* wrongly
  `coast` via the section-header sea-fallback despite being an inland
  landmark embedded in a tribal-boundary description (topostext: "...below
  whom are the Nectiberes; and next is the Pyrrhon Plain...Below these are
  the Zegrenses..."), and the coastline-reconstruction graph had strung
  all three together into a spurious 3-point "coastline" purely because
  they happened to sit within stitching distance of each other - Africa's
  real mainland coast, two offshore islands, and an inland plain, none of
  which trace a real shore. Fixing the islands' category first actually
  *revealed* this - `annotate_dataset.py`'s coastline count dropped by one
  when the fix landed, which is exactly backwards for a category-only
  change and was the tell to go looking. Fixed both: Paena/Erythia added
  to `_ISLAND_APPENDIX_SECTIONS`, Pyrrhon-Ebene's section added to
  `_NONCOASTAL_EXCEPTION_SECTIONS` (the same mechanism as York/Colchester/
  Brough) - the phantom coastline disappears entirely once neither endpoint
  is coastal any more, rather than becoming a real 2-point or 1-point one.
- "Diur" (`4.01.12`, Mauritania Tingitana's own named-mountains list,
  alongside the already-`-Gebirge`-suffixed Durdon-Gebirge W/O-Ende) was
  the same missing-keyword mountain-list shape as Macedonia/the
  Peloponnese - added to `_MOUNTAIN_APPENDIX_SECTIONS`.
- Two more island-list sections safe to force whole-section (`4.03.44`,
  eight islands "along the coast of Africa"; `4.03.46`, three more) and
  four islands needing a point-level fix instead, because their sections
  *also* contain a city sitting on a different island with no coordinate
  of its own for the island itself - "Iulia Caesarea" (an island sharing
  its name with the mainland capital it lies off), "Cercina" (its section
  also names Gerra/Meninx, two cities on the separate island Lotophagitis),
  and "Kossura"/"Gaulos"/"Melite" (Pantelleria/Gozo/Malta - their section
  also names Melite's own peninsula and two shrines, not islands
  themselves) - all four added to `_ISLAND_POINT_OVERRIDES` rather than
  their whole sections, to avoid mis-islanding those city-on-an-island
  siblings the same way `_ISLAND_POINT_OVERRIDES` was designed to avoid in
  the first place.

A seventh pilot run (Cyrenaica and Marmarike/Libya/Egypt including the Nile
Delta, `§4.4.1`-`§4.5.77`) found the biggest single fix of any pilot so
far, this time in the *coastline* classifier rather than mountains or
islands:

- "Kap" (cape) was only ever recognized as a *leading* word
  (`_KAP_PREFIX_RE`, `^kap\b`), but the catalogue names a cape just as
  often with "Kap" elsewhere in the name - "Nördliches Kap" ("Northern
  Cape"), "Heiliges Kap" ("Sacred Cape"), "Grosses Kap am Anfang des
  Golfes" ("Great cape at the start of the gulf"), "X, ein Kap" ("X, a
  cape"), "Athos, Kap und Berg". Checked the whole catalogue before
  broadening past the prefix anchor to a bare `\bkap\b` word match: of the
  ~30 non-leading "Kap" mentions found this way, every single one is the
  point's own identity as a cape, not an incidental aside the way
  "Alpen"/"-Gebirge" can be a river point's mere location - so, unlike the
  mountain tiers, no location-reference guard was needed. Renamed
  `_KAP_PREFIX_RE` to `_KAP_WORD_RE` to match. 18 points flipped from
  `city` to `coast`, and one - "Nördliches Kap" ending the Gulf of Sidra in
  Cyrenaica (`4.04.03.08`) - had been sitting in an entire coastal-walk
  section that never got recognized as coastal at all (its own header row
  is just a place name, "Dorf des Philainos", with no sea/gulf keyword for
  `_COASTAL_HDR_RE` to match), so fixing just this one cape reconnected it
  to "Kap Drepanon" into a real 2-point coastline segment that hadn't
  existed before: coastline count rose from 60 to 61.
- Three more island-list sections: the two islands off Cyrenaica
  (`4.04.14`, Myrmex + the already-`island` Aphrodite-Insel/Laia) and the
  three islands "in the Arabian bay" off the Red Sea coast (`4.05.77`,
  Saspeirene/Aphrodite-Insel/Agathon-Insel - Saspeirene itself was sitting
  in `coast` via the section-header fallback, confirmed not part of any
  existing coastline before reclassifying it, avoiding a repeat of the
  Paena/Erythia mistake above) - both safe to force whole-section. Plus one
  more point-level fix: "Pharos" (`4.05.76.02`) - the island of the
  Alexandria lighthouse - sitting in `city`, in a section that also names
  an unrelated, unconfirmed point ("Argaiu") not safe to force alongside it.
- Confirmed, not fixed: the string of Nile-delta points topostext describes
  as being "on the island" formed where the river forks around the
  Heracleopolites nome (`Nilupolis`, `Arsinoe`, `Aphroditopolis`,
  `Ankyronpolis`, `Kynonpolis` - `4.05.56`-`4.05.59`) are cities *on* that
  river-formed island, not the island itself (which has no coordinate of
  its own beyond the fork points already correctly categorized `river`) -
  the same "city on an island stays `city`" pattern as Ebusus/Melite's
  peninsula, not a bug.

An eighth pilot run (Interior Libya, Ethiopia below Egypt, and Interior
Aethiopia/Agisymba - the far southern edge of Ptolemy's known world,
`§4.6.1`-`§4.9.7`) found a bug in `parse_topostext.py` itself, silently
dropping real data, plus another spurious coastline tail of the
Paena/Erythia kind:

- `_COORD_RE` required a minutes group on *both* the longitude and
  latitude of every coordinate pair. Every other chunk so far had minutes
  given throughout ("11°00' . 61°00'"), but this one - the catalogue's
  southernmost reach, several degrees below the equator - gives a number
  of points in bare whole degrees ("80° . 15°20' S.", "45° . 6° S."), and
  the required-minutes match simply skipped every one of them without
  error: book 4 map 9 (Interior Aethiopia) parsed to a single point
  instead of the dozen-plus its raw text actually has - the tell that
  something was silently wrong, not a crossref disagreement (nothing to
  disagree with if the point was never extracted at all). Made minutes
  optional on both components, and added recognition of a trailing "S."/"S"
  hemisphere marker (this chunk's only use of one - the catalogue is
  otherwise all-northern) that negates the latitude. Broadening the match
  is exactly the kind of change that risks new false positives, so it was
  checked directly: added a word-boundary negative lookahead
  (`S(?![a-z])`) after the "S" so it can't swallow the leading letter of an
  unrelated word directly after a coordinate ("...58°20' **S**etantiorum
  harbor..." was initially mismatched into "58°20' S" before this guard,
  corrupting both the latitude *and* the next point's name) - confirmed by
  re-parsing an earlier, already-verified chunk (`§2.2`-`§2.3`) byte-for-
  byte identical before and after the regex change. Rather than risk drift
  from patching just the one chunk, every one of the eight raw chunks
  pasted so far was re-run through the fixed parser and concatenated fresh
  into `topostext_209.csv` (3525 rows total), the simplest way to guarantee
  the whole file reflects one consistent parser version.
- A second spurious coastline tail, the same shape as Paena/Erythia in the
  sixth pilot run: four islands "near Ethiopia below Egypt in the Arabian
  Gulf" (`4.07.36`: Astarte, Altar der Athene, Gypsites, Myron) had been
  strung onto the end of a long Red Sea coastal-walk segment
  (`coastline_025_AF04`, otherwise a real ~30-point trace of the Horn of
  Africa coast) purely because their coordinates landed within stitching
  distance of its last mainland point, "Kap Bazion" - exactly where
  topostext's own text pivots from coastal description to an island list
  ("After the Bazion promontory referred to above:... [coast]... The
  following islands are near Ethiopia below Egypt in the Arabian Gulf:...
  Astarta island..."). Reclassifying them correctly truncates the
  coastline back to Kap Bazion rather than breaking it. Five more
  island-list sections in the same stretch, all safe to force whole-
  section: Libya's Western Ocean islands (`4.06.33`), the rest of the
  Arabian Gulf island list (`4.07.37`), the lone island in the Bay of
  Avalites (`4.07.39`), and the islands next to Aromata (`4.07.40`).

A ninth pilot run - the start of Book 5 (Pontos/Bithynia, Asia proper,
Lykia, Galatia, Pamphylia, the start of Kappadokia, `§5.1.1`-`§5.6.17`) -
found the same "named-mountains list, no `-Gebirge`/`-berg` suffix to
catch" shape as the third/sixth pilot runs, but at a much larger scale:
Book 5's Anatolian provinces name almost every mountain by a bare
classical proper name ("Mt. Ida", "Mykale mountain", "the Argaion") rather
than the "X-Gebirge" convention common elsewhere, and several of those
bare names also carry a `"(Mitte)"` position marker that the river-course
pattern was claiming first, since nothing in the name itself said
"mountain":

- Four more sections safe to force whole: Bithynia's named mountains
  (`5.01.10` - Orminios, the Mysian Olympos), "the named mountains in
  Asia" (`5.02.13` - Ida, Killaion, Temnon, Sipylos, Tmolos, Mesogis,
  Mykale, Kadmos, Mimas, Phoinix, and one end of Dindymos - eleven points,
  the largest single named-mountains list found so far), Lykia's
  (`5.03.04` - Kragos), and Galatia's (`5.04.04` - Oligas/Gigas, "the hill
  of Kelainon", and Dindymos' *other* end - the same range re-cited across
  the book.map boundary the way Buzara-Gebirge/Koronos-Gebirge were,
  correctly reconnecting into its own two-point line once both ends share
  a category).
- One section needing point-level fixes instead: Kappadokia's named
  mountains (`5.06.08` - Argaion's two ends, and two separately-numbered
  segments of the Antitauros range, "Anti-Tauros W" and "Anti-Tauros O",
  each with its own W/O-Ende) sits in the same section as a genuine river
  confluence point (the Euphrates meeting the Melas, cited as an aside
  during the range's own boundary description) that a whole-section force
  would have wrongly swept up - six points added individually to
  `_MOUNTAIN_POINT_OVERRIDES` instead.
- Two more island-list sections (Bithynia's, `5.01.15`; Pamphylia's,
  `5.05.10`) and one single-point fix, "Tenedos" (`5.02.28.03`) - a lone
  citation covering both the island and, per topostext, "a city of the
  same name", the same shared-name shape as Iulia Caesarea earlier.

A tenth pass, prompted by spotting it directly on a rendered static map
rather than a fresh topostext chunk, checked two things the Mediterranean
overview map made visually obvious: a row of `city`-colored dots sitting
out in the Adriatic off the Croatian coast, and the Balearic Islands
showing as plain city dots with no island shape at all.

- The Adriatic row was real: `2.16.14` (Dalmatia's islands - Issa,
  Tragurium, Pharia, Korkyra Nigra, Melite - Vis, Trogir, Hvar, Korcula,
  Mljet) has no `"Insel"`/sea-header keyword for any regex to catch, so
  every point fell through to the default `city` classification. topostext
  confirms each is a single citation merging an island with its city
  ("Off Dalmatia are the islands Issa with city...Tragourion with
  city...Pharia with city...Melite island") - the same shared-name shape as
  Iulia Caesarea/Tenedos, now `_ISLAND_APPENDIX_SECTIONS`. Category counts:
  `island` 283 -> 288, `city` 4332 -> 4327, coastline count unchanged at 61
  (none of the five had ever been part of a coastline - `section_is_coastal`
  was false here, so they were never miscategorized as coastal in the
  first place, just as inland-default `city`).
- The Balearics, checked against the same neighbouring section (`2.16.13`,
  Liburnia's islands) and topostext, turned out *not* to be a bug: Ptolemy
  gives Mallorca and Menorca ("Grössere Insel"/"Kleinere Insel") no
  coordinate of their own, only two named cities each (Palma/Pollentia,
  Iamo/Mago - topostext: "The larger (Majorca) has two cities:
  Palma...Pollentia. ...the smaller (Minorca) with the two old cities,
  Iamna...Mago"), exactly like Liburnia's Apsorros/Kourikta/Skardona
  (Krepsa+Apsorus, Fulfinium+Curicum, Arba+Colentum) two sections earlier -
  the established "multiple cities on an island with no coordinate of its
  own stay `city`" pattern (see the Nile-delta note above), not the
  single-merged-citation shape that Dalmatia turned out to be. Left as is.

An eleventh pilot run - the rest of Book 5 (Lesser Armenia, Kilikia,
Sarmatia in Asia, Kolchis, Iberia, Albania, Greater Armenia, Cyprus,
Syria, Ioudaia, Arabia Petraia, Mesopotamia, Eremos Arabia -
`§5.7.1`-`§5.19.7`, completing Book 5) found three more named-mountains
lists in the by-now-familiar shape, one more island-list section, and a
genuinely new bug class: a lake sharing the mountain-name lists'
`"(Mitte)"` river-course collision.

- Three more named-mountains sections safe to force whole: Greater
  Armenia's (`5.13.05` - Paryardes' two ends, Udakespes, Antitauros'
  Armenian segment, Abos, and the already-`-Gebirge` Gordyaia), Syria's
  (`5.15.08` - Pieria, Kassios, Libanos' two ends, Antilibanos' two ends,
  Alsadamos, Hippos - topostext: "The noteworthy mountains in Syria are
  Pieria mountain, midpoint...and Kassios..."), and Mesopotamia's
  (`5.18.02` - Masion and Singaras, topostext: "The named mountains in
  Mesopotamia are Masion mountain, midpoint...and Singaras"). Two of
  these ranges each got their own two-point line for the first time
  (Paryardes' NW/SO ends, Libanos' and Antilibanos' W/O ends) - 63 → 66
  mountain lines, 129 → 135 points.
- One more island-list section: `5.15.27`, "Islands off Syria: Arados...
  and Tyros just offshore" - Arados (Arwad) and a second, *offshore*
  "Tyros" citation distinct from the mainland coastal city of the same
  name already catalogued a few sections earlier at `5.15.5` (ancient
  Tyre's small islet, before Alexander's siege mound joined it to the
  coast - ordinary re-use of a name for two genuinely different points,
  the same shape as the Kap Leukas/Alopekia pattern, not a duplicate).
- The new bug: a lake's own citation carrying a `"(Mitte)"` position
  marker ("Asphaltites-See (Mitte)" - the Dead Sea, topostext: "Part of
  the Jordan river toward the Asphaltitis lake divides Ioudaia, the
  midpoint of which is...") matches `_RIVER_COURSE_RE` before the lake
  check further down the function ever gets a turn - the exact same
  collision the mountain `"(Mitte)"` fix solved for `mountain`, one
  category over. Three more catalogue-wide: "Lychnitis-See (Mitte)",
  "Arsessa-See (Mitte)" (both Greater Armenia's lakes, `5.13.08`) and
  "Chelonidai-Seen (Mitte)" (Book 4's Libyan lakes) - the last needing
  `_LAKE_RE` broadened to accept the German plural "Seen", not just "See",
  which in turn newly caught "Nil (Vereinigung der Flüsse aus Nil-Seen)" -
  the Nile's own confluence point, merely *naming* the lakes its
  tributaries come from - needing the same location-reference guard
  (`_LAKE_LOCATION_REF_RE`, mirroring `_MOUNTAIN_LOCATION_REF_RE`) so a
  river point mentioning a lake as its location doesn't get swept up
  alongside the lake's own citations. `lake`: 30 → 34.
- Confirmed, not fixed *at the time*: a short run of Sarmatia-in-Asia's
  Pontos/Maiotis lake-shore coastal points (`5.09.02`'s Paniardis/Patarue,
  `5.09.08`'s Sindikos/Bata, topostext explicitly calling the latter two
  "harbor") sitting in `city` because their sections' own headers name the
  sea by Greek proper noun ("Pontos Euxeinos", "Maiotis-See") rather than a
  generic German sea word `_COASTAL_HDR_RE` recognizes. Checked whether
  broadening the header regex to catch a bare "Mündung" header would fix
  it generally first - it would not: a scan of every such header across
  the whole catalogue found the pattern is mostly *inland* river-boundary
  recaps (Rhône/Rhine/Danube tributary sections listing ordinary interior
  cities), so a blanket fix would have wrongly coastal-ized dozens of
  unrelated points. This handful needed individual treatment (a `coast`/
  `harbor` point-override mechanism, which didn't exist yet) rather than a
  quick regex change, and was left for a future pass rather than rushed -
  see the second round of visual-inspection fixes further down, where that
  mechanism (`_COASTAL_APPENDIX_SECTIONS`) got built and this exact section
  range was the first thing it was used to fix.

A twelfth pilot run - Babylonia (`§5.20`, closing book 5), and all of
books 6 and 7 (Assyria through Taprobane/Sri Lanka, `§6.1`-`§7.4.14`,
the Geographica's own closing paragraph) - covers the **entire remaining
catalogue**: books 2 through 7 are now fully cross-checked against
topostext, start to finish. This chunk came from a different, older
public-domain translation (McCrindle-style, archaic phrasing and a few
OCR-looking artifacts - stray dashes, a missing "1" here and there)
rather than topostext's own smoother modern prose, but parses and scores
the same way; the coordinate+name matching absorbed the rougher text
without needing any parser changes.

- One more named-mountains section safe to force whole: Media's
  (`6.02.04` - Zagros, Orontes, Iasonion, and the already-`-Gebirge`
  Koronos, topostext: "The most important mountains of Media are the
  Zagros, midpoint...the Orontes, midpoint...the Iasonion...and the
  western part of Korono...").
- Two point-level mountain fixes in a section not safe to force whole:
  Arabia Felix's `6.07.20` names Zames and the bare-name Klimax (the
  latter confirmed as a mountain not by a marker on its own citation but
  by three separate later mentions in the same chunk - "beyond Klimax
  mountain", "extending as far as Klimax mountain") alongside a genuine
  spring/river-source point, "Wasser der Styx (Quelle)", that a
  whole-section force would have wrongly swept up.
- Five more island-list sections safe to force whole: Persis's
  (`6.04.08` - Tabiana, Sophtha, plus the already-island "Insel des
  Alexander bzw. Arakia"), Iabadios/Java's own two-point extent citation
  (`7.02.29` - west and southeast ends, the same shape as Thule/Scandia's
  W/O/N/S citations), and the group of six islands in front of Taprobane
  (`7.04.11`). Plus two lone-island point overrides: Talka, "a sea island
  off" Hyrkania (`6.09.08.02`), and Barake, a single-island section off
  India's Gulf of Kanthi (`7.01.94.03`).
- One more real coastline-graph bug, the same spurious-tail pattern as
  Paena/Erythia and Astarte/Myron earlier, except this time on *both*
  ends of the same coastline: Karmania's islands (`6.08.15` - Sagdana,
  Vorochtha, "the islands lying off Karmania...in the Persian Gulf" - and
  `6.08.16` - Polla, Karminna, Liba, "In the Indian sea") had been strung
  onto the start and end of `coastline_045_AS06` by simple proximity, the
  first two before the coastal walk even begins (per topostext, the real
  description starts at the next section's river mouths) and the last
  three after its real endpoint (a Gedrosia/Karmania boundary point).
  Reclassifying both groups trimmed the coastline from 28 points down to
  its real 23, coastline count itself unchanged (61).
- Confirmed, not fixed: a small set of named "coastal mountains" (Arabia
  Felix's Kabubathra, Didyma-Berge, topostext's own "Coastal mountains of
  Eudaimon Arabia" list) that are already correctly `coast` and part of a
  real coastline - the same "protect a real coastline over a mountain
  keyword match" reasoning as `_MOUNTAIN_BAREWORD_BERG_RE`'s guard, left
  alone rather than broken for the sake of a stricter mountain match.

**Found by visual inspection, not cross-referencing**: rendering a static
map of the Red Sea/Arabia region turned up a real gap that topostext
cross-checking alone hadn't caught, since the mismatch is between the
catalogue's own points and how they're *classified*, not between the
catalogue and topostext - the user reported "it's as if one coastline is
missing, and there's what looks like a row of coastal cities marked as
cities" and "some coastline is blocking the mouth of the Red Sea". Arabia
Felix's own Red Sea-facing coast (`6.07`, sections `02`-`19`) was entirely
missing its `coast` classification: Ptolemy narrates this coastal walk
tribe-by-tribe ("In the country of the Kinaidokolpitans...", "The
Kassanite country...", "Country of the Elisarans...") rather than
repeating "Arabian Gulf"/"Red Sea" at every section, so `_COASTAL_HDR_RE`
(which looks for a sea/gulf word in the section header) only fired for a
few of those sections - every other plain-named port town on that coast
(Kopar, Zabram, Thebai, Badeo, Mamala, Muza, Okelis, and more - several
well-attested real Red Sea/Gulf-of-Aden ports) fell through to the default
`city`, so no coastline was ever traced there at all. The opposite African
shore (`4.07`) was already correctly traced, so the rendered map showed
one real coastline and one gap dense with city dots and the Red Sea
islands (`6.07.43`/`45`/`46`/`47`) - reading, at a glance, like the
islands themselves ought to have been the missing coast. (The "blocking
the mouth" impression was a side effect of the same gap, not a separate
bug: with only the African coastline drawn, its own real bend around the
Adulitic Bay and the Horn of Africa - confirmed against topostext, "in the
Adulitic Bay, Sabat city...Mountainous peninsula...Adulis...Krouos or
Kronos promontory" - reads as if it cuts across the strait; with the
Arabian coast now also drawn alongside it, the gap between the two reads
as open water again, as it should.) Fixed with a new override list,
`_COASTAL_APPENDIX_SECTIONS` - the coastal-walk counterpart of
`_NONCOASTAL_EXCEPTION_SECTIONS` - forcing `section_is_coastal = True` for
the verified sections regardless of header wording; safe even where a
section also has a genuine river source/mouth (`_RIVERFEAT_RE`/`_MOUTH_RE`
are still checked first) or a genuine coastal-mountain citation (Melan/
"Schwarzer Berg" in `6.07.09`, previously miscategorized `mountain` by the
*same* underlying bug - `_MOUNTAIN_BAREWORD_BERG_RE`'s bare-word tier only
skips a point when its section already reads as coastal, so the missing
`section_is_coastal` had also been quietly stealing this point from the
coastline it belongs to). Confirmed against topostext's English
translation, which frames the whole `02`-`19` span as one continuous
enumeration down the Arabian Gulf coast and round into the Persian Gulf.
`coast`: 619 → 669, `city`: 4306 → 4257, `mountain`: 293 → 292 (net zero -
all reclassified into `coast`); coastline feature count actually *dropped*
(61 → 58, 1099 → 1135 points) even though more points became coastal,
because several formerly-isolated points on this stretch turned out to
share a real, continuous walk once correctly classified and merged into
fewer, longer lines instead of many short ones.

**A second round of visual-inspection fixes**, from the same map, after
the Red Sea fix above: the user reported the Arabian peninsula's own
coastline "doesn't close correctly", a zigzag where Oman rounds into the
Strait of Hormuz, and - on the opposite side of the catalogue entirely -
"two strange lines connecting inland points on the Black Sea's west coast,
as if it's trying to connect the wrong features", plus general gaps in the
Black Sea coast (Turkey's north coast by name).

- **The Hormuz zigzag** turned out to be the same underlying shape as the
  Red Sea gap, but showing up as a *graph* bug rather than a
  classification one: book.map `6.07` sections `12`-`13` are Ptolemy's own
  summary recap of "the coastal mountains of Eudaimon Arabia" and "coastal
  rivers", re-listing points already cited earlier *at the same
  coordinate*, each one self-marked in the catalogue's own text with a
  back-reference arrow ("Didyma-Berge –> 6.7.11", "Lar-Mündung < 6,7,14").
  Node-collapsing (any two points within 0.05°) merges a recap citation
  into the *same graph node* as its original, turning an ordinary coastal
  point into a spurious junction with edges to whatever precedes/follows
  it in the recap list - which has no real geographic relationship to the
  original's actual neighbours. The result: `build_coastlines`'s graph
  walk left the real path to detour through the recap list and back. Fixed
  with `_RECAP_BACKREF_RE`, a regex on the arrow notation itself (checked
  against the whole catalogue - all 15 matches are exactly these two
  sections, nowhere else) - excluded from coastline edges, river-line and
  mountain-line grouping alike, the same signal working for all three
  since the arrow marks "this is a duplicate, not a new point" regardless
  of which kind of line it would otherwise join.
- **The "peninsula doesn't close" impression** wasn't a separate bug - it
  was the same Red Sea/Hormuz gaps read differently: with roughly a third
  of Arabia's own coastline missing or zigzagging, the traced line looked
  broken rather than like a single open arc from the Persian Gulf around
  to the Red Sea. Arabia's coastline was never *supposed* to close into a
  loop - it's a peninsula joined to the mainland at the top, not an island
  - and with both fixes in place it now reads as the open arc it should
  be.
- **The two "strange lines" on the Black Sea** are two different things
  bundled into one impression. One is real Ptolemaic distortion, not a
  bug: the Danube's course through Pannonia/Dacia/Moesia (cited under
  three different names for different stretches - `Danuvius` upstream,
  `Danubios` and `Ister` downstream, all confirmed the same river by
  `Modern_location` = "Donau") is one of Ptolemy's least accurate regions,
  and a straight line between two real, correctly-classified river bends
  can visibly cross the modern coastline when his own coordinates for
  inland Dacia/Pannonia are this far off true position - the same
  "systematically stretched and skewed" distortion already disclosed for
  the catalogue generally, just unusually visible here. The other *is* a
  bug, the same duplicate-citation shape as Hormuz but without an arrow
  marker to catch it generically: `3.10.14.01` ("Borysthenes-Mündung",
  Lower Moesia's own coastal description resuming after a digression into
  inland Danube-bank legionary camps) is a bit-identical coordinate
  duplicate of `3.05.07.01` (Sarmatia-in-Europe's own citation of the same
  Dnieper mouth) - an orientation reference opening the resumed walk, not
  a new point, but with nothing in its text marking it as such. Added to
  `_COASTLINE_SKIP_REF_IDS` by hand, the same mechanism (and the same
  "introductory boundary citation" shape) as the pre-existing
  Acheloos-Mündung entry.
- **The Black Sea coastal gaps** were a third occurrence of the Red Sea's
  own bug shape: Paphlagonia/Pontus's coast (book.map `5.04`, sections
  `02`-`03`) states "Pontos Euxeinos" (Black Sea) only once at the very
  start of the book.map, then heads every section that actually
  enumerates the coast with a place name instead - so two of antiquity's
  best-known Black Sea ports, Sinope and Amisos (Sinop and Samsun today),
  were sitting in plain `city`. Bithynia's own Gulf-of-Astakos bay
  indentation (`5.01.03` - Astakos, Olbia, Nikomedeia) had the same gap,
  distinguished from the genuinely inland cities `5.01.13`/`14` right next
  to it by topostext's own text, which introduces *that* list explicitly
  as "the following are the inland cities" and says nothing of the sort
  about section `03`. And Sarmatia-in-Asia's own Sea of Azov/Kerch-strait
  coast (book.map `5.09`, sections `02`-`10`, real Bosporan-kingdom port
  towns - Phanagoria, Hermonassa, Sindikos, the last one topostext calls a
  "harbor" outright) was the exact case already documented above as
  "confirmed, not fixed... needs individual treatment (a `coast`/`harbor`
  point-override mechanism, which doesn't exist yet)" - now fixed, using
  the section-override mechanism (`_COASTAL_APPENDIX_SECTIONS`) the Red
  Sea fix introduced.
- `coast`: 669 → 706, `city`: 4257 → 4220 (net zero, all reclassified);
  river lines dropped the two spurious 2-point Hormuz recap groups
  (111 → 109 lines, 281 → 277 points); coastline count itself rose only
  slightly (58 → 59) despite far more points joining, since most of the
  newly `coast` points filled gaps *within* already-existing trails rather
  than starting new ones.

**A third round**: after the Hormuz/Black Sea fixes above, the user
reported the Black Sea, Bosphorus and Thrace/Bithynia coast still "hopping
and dancing" - explicitly noting the *points* looked right, it was the
*connection order* that was wrong. That framing was the clue: it's not a
classification problem in the usual sense, it's a *connectivity* one.
Checked every section across the whole catalogue headed by a Greek Pontic
sea-name our German-only `_COASTAL_HDR_RE` can't match ("Pontos Euxeinos",
"Propontis", "Kimmerischer Bosporos") and triaged each by hand - most were
already fine or genuinely inland (`5.06.09`-`11`'s header uses "Pontos" as
a *province* name, Amaseia and neighbours, nowhere near the shore), but
eleven had a real, topostext-confirmed gap: Crimea's own coast
(`3.06.02`/`04` - Eupatoria, the Bosporan Kingdom's capital Pantikapaia),
Thrace's Black Sea coast and its Propontis coast on the other side of
Byzantion (`3.11.03`/`05`/`06` - `05` is Byzantion itself, the missing
hinge point the two other sections needed to connect *through*), Bithynia
(`5.01.02`/`05` - Chalkedon, Artake), the Troad's Propontis shore
(`5.02.02` - Kyzikos, Parion), and the three Roman "Pontus" sub-provinces'
own coast further east (`5.06.03`/`04`/`05` - Themiskyra, Polemonion,
Kerasous/Giresun, Pharnakia, on the way to Trapezous/Trebizond). With
those real waypoints missing, the coastline graph had nothing to connect
but the few points that already happened to match some other keyword,
forcing long, geographically senseless edges between them - which is
exactly what reads as points "hopping and dancing" once so many of a
region's real stepping-stones are missing from the graph. `coast`: 706 →
739, `city`: 4220 → 4187 (net zero); coastline feature count held at 59
(1171 → 1204 points) - all fill-in, no new lines needed.

**A fourth round**: asked to go through the Black Sea region systematically
rather than fix-what's-visible, since "there are still clearly points
being connected as coast that shouldn't be - the points look correct, the
*order* is what's off." Wrote a small one-off sweep (not part of the
regular pipeline) computing the distance between every consecutive pair of
points in every coastline trail across the wider Black Sea/Sea of
Azov/Sarmatia region, flagging anything over ~1.8° for individual review
against topostext and the raw section headers - the same manual
verification standard as every fix above, just driven by a systematic scan
instead of eyeballing a render. Most flagged jumps turned out legitimate
(a real long sandspit, a documented narrative transition, already
cross-checked above); two were real:

- Sarmatia-in-Europe's own coast (book.map `3.05`) had the same
  header-language gap one section earlier than the sweep had reached:
  sections `11`-`13` open the walk itself ("Neue Festung" - topostext's
  "Neon Teichos", the walk's own starting point) and continue it (Leianon,
  Akra, Kneme, Hygreis, Karoia) - all sitting in `city` with nothing to
  connect them, verified by name against topostext (whose own section
  numbering for this book.map runs well ahead of the catalogue's, so
  matched by content, not section index).
- Crimea's coast (`3.06.03`) was missing Theodosia (Feodosia) and
  Nymphaion entirely - topostext's own text puts them directly between two
  *already*-coastal sections ("...Istrianos river mouth, Theodosia,
  Nymphaion..."), a one-section gap the third round's `3.06.02`/`04` fix
  had stepped right over.
- The opposite problem, once: `5.09.11`'s own header happens to include
  "Hyrkanisches Meer" (the Caspian) as the far endpoint of an inland
  *boundary-line* description ("thence along Albania to the limit on the
  Hyrkanian sea" - topostext) - Sarmatia-in-Asia's border with
  Iberia/Albania, not a continuation of its Black Sea coast (which
  topostext explicitly ends one section earlier, at the Kolchis boundary).
  "Sarmatische Pforten" (the Sarmatian Gates, a Caucasus mountain pass) had
  been swept into `coast` by that header match and strung onto the real
  coastline as a spurious ~2° detour. Fixed the other way round from the
  rest of this round - `_NONCOASTAL_EXCEPTION_SECTIONS`, not
  `_COASTAL_APPENDIX_SECTIONS`.

`coast`: 739 → 747, `city`: 4187 → 4179 (net: 8 points gained `coast`, one
lost it). Re-ran the full pipeline; topostext coverage unaffected.

**A fifth round, and a new permanent diagnostic**: the user's own framing
broke the pattern of the previous four rounds - "a coastline is by
definition non-crossing, like a road on a map" - and asked for an
algorithm, not another eyeballed render. `check_self_intersections.py` is
that algorithm: it builds every drawn coastline/river/island/mountain line
and checks each pair of *non-adjacent* segments for a real crossing (via
shapely), independent of any distance threshold - a self-crossing line has
an ordering bug almost by definition, whether or not the jump that causes
it happens to look large. It's a diagnostic, not part of the regular
pipeline - run it after any classification/line-building change, the same
way the edge-distance sweep was used ad hoc for the fourth round, except
this one doesn't need a threshold picked by hand and catches crossings a
distance sweep can miss entirely (a short "return" edge can still cut back
through a much longer earlier detour).

Run once, it found real bugs immediately - the same *introductory
boundary citation* shape as `_COASTLINE_SKIP_REF_IDS`'s existing entries,
just surfaced as a crossing instead of a visible jump:

- Macedonia's own southern border marker, "Malischer Golf" (`3.13.06.05`,
  cited alongside the Pindos/Oite mountains' own boundary midpoints,
  before the region's coastal walk actually begins at Neapolis) - left in,
  its first edge crossed twelve of the walk's own later segments.
- The same shape, three more times, in Lykia/Pamphylia/Kilikia
  (`5.03.01.06`/`5.05.01.09`/`5.08.01.09`) - each book.map opens with an
  explicit "limit of [province] ... to the sea at [point]" boundary-line
  sentence (topostext) *before* "the following" starts the actual coastal
  enumeration from a different point entirely.
- One more undermarked re-citation, the same shape as Borysthenes-Mündung
  earlier but without an arrow this time: "Kap Bithynia" (`5.01.05.04`)
  re-describes the same headland as "Spitze Bithyniens mit
  Artemis-Heiligtum" (`5.01.02.02`, same latitude exactly, topostext
  re-describing it near-verbatim) to reorient the reader after a detour
  into the Gulf of Astakos - left in, it cut straight back across that
  detour's own segments.
- Two false "close the loop" calls whose closing edge cut straight across
  the rest of the trail - the same shape the third round's Macedonia/
  Thessaly entry already covers, just for two more trails
  (`3.10.02.05`/`3.10.14.04`, Lower Moesia's Danube-delta-to-Dniester
  coast; `3.11.02.01`/`3.11.06.09`, Thrace's Aegean-to-Propontis coast) -
  plus a *follow-on* case the fix itself created: once those two trails
  stopped falsely closing on their own, the real Nessos-Mündung/Neapolis
  boundary stitch correctly merged Thrace and Macedonia/Thessaly into one
  ~58-point trail, whose own two new loose ends (Paktye, Spercheios-
  Mündung) then satisfied the same false-closing check *themselves*,
  closing a loop across the whole Aegean. Same fix, one level up
  (`3.11.06.09`/`3.13.17.10`) - a reminder that this class of check needs
  re-running after a fix, not just before one.

Not every crossing found is a bug: a genuinely complex bay or peninsula
sampled by only a handful of named points can still cross itself in a
straight-line rendering even though the real shore never does - that's a
sparse-sampling artifact of connecting the dots, not an ordering error, and
isn't safe to "fix" by reordering points without the same kind of textual
evidence every other fix in this README rests on. A few such crossings
remain (currently in the catalogue's Iberia and Liguria/Campania regions,
and a small one in Bithynia's Gulf of Astakos) - left for a future pass
rather than forced without that evidence.

**Bithynia's Gulf of Astakos, investigated further** after the user
spotted the crossing directly in a rendered screenshot: one real
classification gap found and fixed along the way (`5.01.04`'s Prusias and
Apameia - Modern_location Gemlik and Mudanya, both real Marmara ports -
were sitting in `city` between two already-coastal river mouths, the same
shape as every other fix this session), but that alone didn't resolve the
crossing - see the sixth round below for how it was actually fixed.

**A sixth round, and a narrower tool**: the user kept looking, this time
pointing at two *exact edges* directly in a rendered screenshot ("the line
from this point onward is wrong") rather than a general area, plus two
cities they could see sitting in open water. `_COASTLINE_SKIP_REF_IDS`
turned out to be the wrong tool for what these needed - it drops a point
from *every* edge it touches, but in both cases the point itself is a
real, correctly-placed step that should stay connected to what comes
*before* it in the walk, just not to what catalogue order happens to put
right after it. `_COASTLINE_HARD_BREAKS` is the narrower fix: a set of
specific ref_id *pairs* whose edge is skipped, leaving both points free to
connect normally to everything else.

- `3.11.02.10` ("Grenzpunkt der Thrakischen Chersones an der Propontis")
  correctly ends Thrace's Aegean-coast walk, but catalogue order puts
  `3.11.03.05` ("Grenze bei Moesia Inferior") right after it - and
  topostext shows that's not a continuation at all: "On the east by the
  Propontis and the mouth of Pontos...and by the onward shores of Pontos
  until the border with Lower Moesia" is a fresh *restatement* of
  Thrace's whole eastern boundary line, whose own enumeration ("which
  border the description is the following: after Mesembria of Moesia,
  Anchialos...") starts a new, independent coastal walk that never comes
  back near the Chersonese. Breaking just this edge stopped it bridging
  3.2 degrees across Thrace's interior to a point it was never
  narratively connected to - and, as a side effect, un-did the
  `_BOUNDARY_STITCH_REF_ID_PAIRS`-driven merge with Macedonia/Thessaly
  from the fifth round (that merge point, Nessos-Mündung, is on the
  *Aegean* side and is unaffected; the Black-Sea-and-Propontis stretch
  this break frees up was never really part of that merge's own story).
- `5.01.04.07` (Rhyndakos-Mündung) correctly ends the Gulf of
  Astakos/Marmara-south-shore digression, but catalogue order bridges it
  straight to Artake (`5.01.05.05`, where the main Propontis coast
  resumes past the already-excluded Kap Bithynia re-citation) - an edge
  that cut back across the whole digression regardless of which
  intermediate points were included. No boundary-line sentence marks this
  one as explicitly as the Thrace case, but every other fact fits the same
  shape, and breaking it resolved the crossing completely.
- The Thracian Chersonese (book.map `3.12`) turned out to be its own
  self-contained peninsula loop, described separately from mainland
  Thrace's coast - topostext files it under book 3 map 11's own section 9
  rather than giving it a separate map number: "the part of Propontis on
  that side as far as Kallipolis...on the west...Kardia city...Mastousia
  promontory...on the south...the city Elaious...the protruding
  promontory...on the East by the Hellespont, on which are the cities:
  Koila, Sestos, next the above-mentioned Kallipolis" - an explicit closed
  loop back to its own start. Section `04`'s own header is "Hellespont"
  (a Greek proper noun, not `_COASTAL_HDR_RE`'s German sea words) - Koila
  and Sestos, the two cities the user spotted floating unconnected in the
  water north of Kap gleich daneben, were sitting in `city` for the usual
  reason. The loop-closing re-citation of Kallipolis itself
  (`3.12.04.05`, a bit-identical coordinate duplicate of `3.12.01.05`) got
  the same treatment as Borysthenes-Mündung earlier - `_COASTLINE_SKIP_REF_IDS`,
  letting the ordinary close-loop mechanism do the job once instead of
  re-closing the same node a second time.

`coast`: 750 → 753 (Koila, Sestos, and the now-unused Kallipolis
duplicate); the self-intersection checker is clean across the whole
Black Sea/Aegean/Propontis region after this round.

**A seventh round, back to `_BOUNDARY_STITCH_REF_ID_PAIRS`**: with the
crossings gone, the user zoomed out and spotted three real gaps along
Turkey's own north/east Black Sea coast instead - the coastline breaking
cleanly at three points rather than connecting wrong. Not a new bug shape,
just three more instances of the existing "real province-boundary river,
split across a book.map change" pattern (`_BOUNDARY_STITCH_REF_ID_PAIRS`
already has five other such pairs, e.g. the Morocco/Algeria and
Algeria/Tunisia border rivers). Bithynia (`5.01`), Paphlagonia+Pontus
(`5.04`), the three "Pontus" sub-provinces (`5.06`), and Colchis (`5.10`)
are four different Roman-administrative book.maps covering one continuous
real shore, and each handoff sits at a real, named river confirmed by
`Modern_location`:

- `5.01.07.07` → `5.04.02.02`: Parthenios-Mündung (Bartın Su) - the real
  Bithynia/Paphlagonia border river.
- `5.04.03.07` → `5.06.02.03`: Amisos (Samsun) → Iris-Mündung
  (Yeşilırmak) - the coast right at Samsun.
- `5.06.07.02` → `5.10.02.09`: Apsorros-Mündung (Çoruh) → Phasis-Mündung
  (Rioni) - the real Turkey/Georgia border river, handing off to the
  Rioni, the Golden Fleece's own river in Colchis.

Coastline feature count dropped from 58 to 55 (three pairs of trails
merged into three longer ones); `check_self_intersections.py` stays clean
- a stitch join only fires within the existing tight tolerance or an
explicit pair like these, so it can't introduce a new crossing the way a
distance-based bridge could.

**An eighth round**, back at the Danube delta: the user spotted
Axiakes-Mündung (`3.10.14.02`) looking disconnected in a rendered map. It
was technically already part of a coastline (linked to Panysus-Mündung
across the same large, already-documented digression-jump as the Danube
bends), but the walk *past* it dead-ended, because the three points that
should carry it onward - Physke, "Dorf des Hermonax", Harpis
(`3.10.14.03`/`.05`/`.06`) - were sitting in `city`. Section `14` has no
header of its own; topostext confirms the real sequence is a clean coastal
run matching the catalogue's own item order exactly: "northernmost mouth
of the Istros until the mouth of the Borysthenes...Axiakos river mouth /
Physke city / Tyras river mouth / Hermonaktos village / Arpis city".
Fixing it created a fresh instance of the same false-loop-closure shape
seen twice already this session (the trail's new endpoint, Harpis, landed
close enough to the delta's own start, Heilige Mündung, to pass the
closing-ratio check) - updated the existing `3.10.02.05` `_NO_CLOSE_LOOP_TRAILS`
entry to match the trail's new last point rather than adding a redundant
one. `coast`: 753 → 756; `check_self_intersections.py` stays clean.

**A ninth round, on the Danube delta's real shape**: even fixed, the delta
still looked wrong to the user - pointing at two more edges directly
("3.10.8.10 is completely wrongly connected to 3.10.14.02", "3.10.02.05 is
wrongly connected to 3.10.04.03") and naming the actual cause: "old maps
draw the Danube as ending in four/five/six branches from one point - you
need to go through these parts step by step and make sure the order is
right so nothing crosses." That reframed the whole problem. `build_coastlines`
assumes catalogue order is walking order - true for an ordinary coastal
survey, false for a river delta, which topostext describes as a nested
*branching tree*, not a line: "The first division of the mouths at
Noviodunum...the southernmost part...flows out by the Sacred mouth...the
northernmost divides again...divides again...flows out by Thiagola or
Psilon...The more southerly of the second division also splits...flows
out by Boreios...also divides...flows out by Narakion...also divides...
flows out by Pseudostomon...the more southerly flows out by Kalon." The
catalogue's own four division-point citations ("Ister (1. Teilung bei
Noviodunum)", "...Teilung des nördlichsten Armes", two more bare "Ister
(Teilung)") confirm every split in that description one-for-one - and
they'd been sitting in `city` themselves, the same `_RIVER_COURSE_RE` gap
as "Aufteilung" elsewhere in the catalogue (Nile delta, India), just
missing the bare word "teilung". Fixed generally (checked the whole
catalogue first - every other hit was already an "-aufteilung" match, so
broadening to the bare word adds no false positives).

Reading the nested south/north branching in written order and walking it
gives a real geographic south-to-north sequence - confirmed decisively by
the six mouths' own latitude increasing monotonically in exactly this
order, where catalogue/ref_id order does not. There's no existing
mechanism for "reorder these specific points" (every fix so far only ever
excluded a point or an edge, never resequenced), so this needed a new one:
`_COASTLINE_EXPLICIT_ORDER_OVERRIDES` gives five of the six mouths a
synthetic sort key placing them immediately after the sixth (the
southernmost, already ref_id-first) in the derived order, leaving every
other point in book.map `3.10` untouched.

That alone wasn't sufficient, and the self-intersection checker caught
why on the next run: the coast heading south toward Thrace (Kap Pteron
onward) naturally continues in ref_id order from wherever the six mouths'
*last* one landed - the *northernmost* mouth - cutting straight back
across the delta's own southward-opening branches (three confirmed
crossings). topostext's own text puts Kap Pteron right next to the
*southern* mouth instead ("Sacred mouth of the Istros river, Pteron
promontory" - one citation, not two). `_COASTLINE_HARD_BREAKS` cut the
wrong (northern-end) connection; the ordinary proximity stitch then
reconnected Kap Pteron to the southern mouth on its own; the same
mechanism separately cut the unrelated ~4-degree jump from Panysus-
Mündung to Axiakes-Mündung the user had flagged - topostext frames that as
two different stretches heading in opposite directions from the delta
(south toward Thrace vs. north toward the Dniester), never connected in
the text at all.

`river`: 300 → 304 (the four division points); `check_self_intersections.py`
stays clean, and the delta now reads, top to bottom, exactly like the old
maps the user was comparing against: one river forking into six mouths in
correct geographic order, rejoining the rest of the coast at the correct
end.

topostext's covered range is now **all of books 2 through 7** (book 2
maps 02-16, book 3 maps 01-17, book 4 maps 01-08, and all of books 5, 6,
and 7 in full - book 1 has no coordinate data to check, being Ptolemy's
own theoretical/methodological introduction) - `link_matches.py`'s
`_COVERED_MAPS` and `build_labels.py`'s `_PROVINCE_LABELS` updated to
match, adding 26 more province labels (Babylonia through Taprobane), for
85 in total.

**A tenth round, a systematic whole-catalogue review** rather than another
region-by-region eyeball pass: with the three-layer method (catalogue ->
topostext -> geometric self-intersection check) now proven on the Danube
delta, the same rigor was pointed at `check_self_intersections.py`'s full,
whole-catalogue output instead of one region at a time - six crossings,
three of them (the Danuvius river ones) previously waved through as
"genuine Ptolemaic distortion" without being checked against topostext
first, the same kind of premature call already corrected once this session.
All six were re-examined from scratch:

- **Iberia** (`coastline_002_EU02`): `Anas (Grenzpunkt Baetica,
  Lusitania, Tarraconensis)` (`2.04.03.04`) and the very next citation,
  `Baetica (Ostende am Baliarischen Meer)` (`2.04.03.07`), are both
  province-boundary markers *up the river Anas/Guadiana itself*
  (topostext: "Where the river touches the border of Lusitania", "there
  along the border of Tarraconensis to where the Balearic sea ends"),
  cited right after the river's own two mouths and its eastward bend -
  the same "Grenzpunkt" boundary-citation pattern already found and fixed
  five times in the Aegean/Black Sea (`5.03.01.06`, `5.05.01.09`,
  `5.08.01.09`, `5.01.05.04`, `3.11.02.09`/`.10`), just not yet checked
  this far west. Left in as coastal, the first one's edge (from the
  river's eastern mouth, out to a point over 4 degrees inland) cut
  straight back across the walk's own western end, the Baetis/Onoba
  estuary that closes this loop. Added to `_COASTLINE_SKIP_REF_IDS`.
- **Liguria** (`coastline_005_EU06`, first crossing): `Vintium`,
  `Salinae`, `Cemenelum`, `Sanitium` (`3.01.41.03`/`3.01.42.03`/
  `3.01.43.03`/`3.01.43.04`) are inland Alpine tribal cities (topostext:
  "Of the Nerusi in the Maritime Alps Vintium", "Of the Suetri in the
  Maritime Alps Salinae", "Of the Vedianti in the Maritime Alps
  Cemenelum") - not a coastal survey at all. Their sections are each
  headed "Meeralpen" ("Maritime Alps"), which contains the bare German
  word "Meer" and satisfies `_COASTAL_HDR_RE` by accident, exactly the
  same false-positive shape as "Hyrkanisches Meer" catching the
  Sarmatian Gates mountain pass earlier this session. The real
  Ligurian-sea coast (Varus-Mündung, Nicaea, Hercules-Hafen, ...) is told
  in the separate, correctly-headed sections `3.01.01`/`3.01.02`. Added
  `("3.01","41")`/`("3.01","42")`/`("3.01","43")` to
  `_NONCOASTAL_EXCEPTION_SECTIONS`.
- **Campania** (`coastline_005_EU06`, second crossing): `Volturnum` ->
  `Liternum` X `Cumae` -> `Misenum`. Checked and left alone: all four
  resolve to real, correctly-ordered, correctly-positioned modern towns
  (Castel Volturno, Literno, Cuma, Miseno via `Modern_location`), and
  topostext confirms the exact same sequential order (positions 3-6 of
  section `3.1.6`). The crossing is real but tiny - Liternum and Cumae's
  own Ptolemaic coordinates are swapped by only 0.17° of longitude,
  a couple of kilometers at this latitude, out of an otherwise perfectly
  ordered five-town stretch. Unlike every other case in this round, there
  is no boundary-citation pattern, no alternate narrative order, and no
  category error to point at - just Ptolemy's (or the transcription's)
  own imprecision between two towns a few kilometers apart. Left
  unfixed, the one honest "genuine distortion" case in the batch.
- **The Danuvius river** (all three remaining crossings, book.maps `2.11`/
  `2.15`): re-examined properly rather than re-confirmed. The trail's
  build (`build_river_lines`) already deduplicates re-cited points at the
  same coordinate, keeping whichever sorts first by ref_id - correct for
  every case checked so far, but here it silently picked the *wrong* one
  of two identical-coordinate duplicates. `Danuvius (Einmündung des
  Savus)` (`2.15.01.06`) is Pannonia Inferior's own boundary-line
  citation (topostext, `2.15.1.1`: "...on the south by Illyria which
  extends from the indicated terminus as far as the bend in the Danube
  near which the Savos river empties into it") - an orientation point for
  a province border, not a step in the river's course. Because
  `"2.15.01"` sorts before `"2.15.02"`, the dedup kept this one and
  discarded its exact-coordinate duplicate, `Danuvius (Biegung bei der
  Einmündung des Savus)` (`2.15.02.18`) - the *correctly placed* citation
  of the same bend, sitting at the end of Moesia Superior's own
  continuous run through this stretch (`2.15.02`: Cirpi -> Dravus
  confluence -> Cornacum -> Acumincum -> Rittium -> Savus confluence, in
  that order). With the boundary citation in front, the trail visited the
  Savus bend immediately after Cirpi - out of the river's real downstream
  order - then jumped back upstream to Dravus, Cornacum and Acumincum,
  crossing its own path three times. topostext has no narrative for this
  particular stretch beyond the one boundary sentence (book.map `2.15`'s
  only citation), so the fix rests on the catalogue's own internal
  section order plus the exact coordinate match (distance 0.0° both
  ways) between the two Savus citations, not on topostext confirmation -
  the weaker of the two evidence tiers this project can draw on, flagged
  here rather than left implicit. A new mechanism,
  `_RIVER_LINE_SKIP_REF_IDS` (the river-line counterpart of
  `_COASTLINE_SKIP_REF_IDS`), excludes `2.15.01.06` before the
  dedup runs, letting `2.15.02.18` survive in its place. Plotting the
  fixed line in isolation shows a single, monotonically south-eastward
  run with no self-crossings, matching the Danube's real flow direction
  through this stretch.

`coast`: 756 -> 752 (net: -4 Maritime-Alps + 2 Iberia boundary points, but
the Maritime Alps ones were never real coastal points to begin with, so
this is a correction, not a loss); `check_self_intersections.py`: 6 -> 1
(the one deliberately-left Campania wobble). Coverage unaffected (still
6013/6178 catalogue points, 6137/6259 topostext citations matched) - every
fix here changed classification/connectivity, not point identity.

The third piece of the review, a catalogue-wide sweep of every section
header against `_COASTAL_HDR_RE` (not just the Black Sea, where this had
already been done), turned up far more false leads than real ones -
useful in itself, since it means the earlier fixes weren't leaving an
easy pattern of remaining bugs behind. Checked and correctly left alone:
region names that happen to contain "Pontos" as an administrative label,
not the sea (`"Galatischer/Polemoniakischer/Kappadokischer Pontos"`,
book.map `5.06` sections `09`-`11` - topostext's own text says "in the
*interior* of Galatian Pontos"/"in Kappadokian Pontos *inland*", settling
what could otherwise look like a Black-Sea-coast gap); boundary-line
endpoints incidentally named after the sea they terminate at (`"Endpunkt
beim Pontus"`/`"beim Pontus"`/`bei Thrakien`, `3.10.01`/`3.10.07` - both
matched, at 100%, to the same single topostext citation, a boundary
description, not a coastal citation); and a batch of `"-See"` (lake) name
hits that were never a `_COASTAL_HDR_RE` question in the first place,
since individual lake points classify by their own name pattern
regardless of section header. One genuine gap survived the check:
Troas's own Hellespont shore (book.map `5.02` section `03`) is the same
"Hellespont"-not-a-German-sea-word gap already found and fixed once this
session on the opposite shore (the Thracian Chersonese, `3.12.04`) -
topostext confirms a clean coastal run ("on the Hellespont: Abydos /
mouth of the Simoeis river / Dardanon / mouth of the Skamander river /
Sigeion promontory"), with Abydos and Dardanon sitting in `city` for lack
of a keyword of their own. Added to `_COASTAL_APPENDIX_SECTIONS`.
`coast`: 752 -> 754; `check_self_intersections.py` stays at 1.

The Nile delta (book.map `4.05`, the branching-tree candidate flagged
alongside the Danube delta) turned out to have a *different* shape, not
yet fixed: its five fork citations ("Grosses Delta", "Kleines Delta",
"Drittes Delta", two "Namenloses Delta") each have a *distinct* name, so
`build_river_lines`'s name-based grouping never puts any two of them in
the same line - each sits alone (or, for the two identically-named
"Namenloses Delta" ones, gets dropped outright by `_GENERIC_RIVER_NAME_RE`,
the same "never a safe grouping key" rule that excludes every unrelated
"Namenloser Fluss" elsewhere in the catalogue). None of this shows up as
a crossing, because nothing is drawn to cross - it's a representation gap
(a real three-way-plus branching structure sitting as five disconnected
dots), not a connectivity bug like the Danube's was. Fixing it properly
would mean identifying the Nile's own named branches (Agathos Daimon,
Bubastikos, Busiritikos, Phermuthiakos, Taly, and the mouths each ends
at) as their own lines and bridging the fork points between trunk and
branch - a larger, separate piece of work, flagged here rather than
attempted inline.

**An eleventh round, a river review**: prompted by a specific request -
find a river crossing Britain's own coastline north-to-south, look at
what topostext says about isolated river points near the Alps, and check
whether cities along the Rhine are tied to the river's own narrative in
topostext - plus "find other kinds of information yourself".

The Britain question found a real bug of a kind nothing so far had
caught: Ptolemy reuses common river names for *different* rivers within
the same book, not just across books (already known - see
`_RIVER_LINE_MAX_GAP_DEG`'s own reasoning - but only handled at the
*cross-book* scale so far). Britain alone has two rivers each called
"Deva" (topostext: `2.03.02.06` on the west coast between Iena and Novius
estuaries; `2.03.05.12` on the opposite northeast coast between Taezalon
promontory and Tina estuary - modern Dee-side Chester vs. Dee-side
Aberdeen) and two each called "Alaunus" (`2.03.04.06` on the south coast
near Magnus Portus vs. `2.03.06.01` far north near the Firth of Forth -
the Hampshire Aln vs. the Northumberland Aln). Both pairs sit close
enough (6-8 degrees) to fall under `_RIVER_LINE_MAX_GAP_DEG` and get
merged into a single two-point "river" cutting straight across the
island - short enough (one segment) to never trip
`check_self_intersections.py`'s own `len(trail) >= 4` floor, and a
*coastline* crossing rather than a self-crossing, a check that didn't
exist before this round at all. Generalizing the search (a new river-vs-
coastline crossing check, run once as a diagnostic rather than added to
`check_self_intersections.py` permanently) found five more of the same
shape catalogue-wide, each confirmed via a different `Modern_location`
and/or non-adjacent book.map rather than assumed from the gap alone:
Sala (Morocco's Bou Regreg vs. Oued Tamrakt, ~7 degrees apart), "Heiliger
Fluss"/"Sacred river" (a descriptive name, not a proper one, independently
reused on Corsica and Sardinia), Peneios (Thessaly's Pineios vs. the
Peloponnese's, both still called Pineios today), Asopos (Boiotia's, of
the Battle of Plataia, vs. the Peloponnese's near Sikyon), and Lykos
(Pontus's Kelkit Çayı vs. one much further south near Cyprus/Syria).
A new `_RIVER_LINE_NO_MERGE_REF_ID_PAIRS` mechanism forces a split
between each pair regardless of the gap check, the narrowest fix
available - lowering `_RIVER_LINE_MAX_GAP_DEG` itself would risk
splitting genuinely long, distorted rivers elsewhere (the Nile, Ganges
and Indus already have confirmed-genuine internal jumps closer to 20
degrees). Four more candidates the same crossing-check flagged
(Kaystros, Thermodon, Tyras, Inachos) turned out to be a single real
river's own mouth-and-source pair, cited together in one section,
sitting close enough to a coastline to just barely brush it - left alone,
the same "genuine geometry, not a bug" call as Campania's Volturnum/
Liternum/Cumae/Misenum wobble earlier in this review.

The Alps and Rhine questions turned up something more structural than a
bug: a whole category of narrative information the point-category model
has no place for. `2.10.04.07` ("Dubis-Quellen", the source of the
Doubs) sits alone - not part of any drawn river line - not because
anything is wrong with it, but because topostext's own text ties it to a
*differently-named* river's course instead: "part north of Lugdunum both
the Arar and the Dubis flow into it, having mixed with each other; the
sources of the Arar, which flow from the Alps" - a real tributary
confluence (and a real "north of [city]" relational fact) that
`build_river_lines`'s same-base-name grouping structurally cannot
represent, since "Dubis" and "Arar" never share a name to group by. The
Po's own headwater section (`3.01.24`) is even richer: "mouth of the
Padus river" / "the head of the river at Lario lake [Como]" / "where it
joins with the Dorias river" / "head of the Dorias river at Poenina lake"
/ "where it is diverted toward Baenacus lake [Garda]" - a small river-and-
lake network (Po/Ticino-area system, the Dora Baltea, and three named
lakes), again invisible to a same-name grouper. And the Rhine question
had a direct answer: yes - `Ganodurum` (`2.09.20.04`, plain `city`)
matches topostext's "are the Helveti along the River Rhine, with cities
Ganodurum", and `Tasgaetium` (`2.12.05.02`) matches "Towards the
headwaters of the Rhine river: Taxgaetium" - two settlements the
catalogue's category system has no way to mark as "on this river",
because only river/river_mouth/coast points carry any river information
at all.

Generalizing that finding catalogue-wide (rather than by hand for just
the Rhine) is the "find other kinds of information" part of the request,
and became a new pipeline step, `topostext/river_mentions.py`: for every
point regardless of category, scan its own `topostext_name` text for any
of the catalogue's own river base names, skip a self-mention (a river
citing itself), and skip a bare-name match with no surrounding prose (a
handful of catalogue river names coincidentally collide with unrelated
place names - "Arbis" the river vs. a plain city citation that happens to
also read "Arbis" - filtered out by requiring at least two words of
context beyond the match, which a real relational mention always has and
a homonym coincidence never does). Written to a new `river_mentions`
column, read-only and additive - no point's coordinates or category
changes. 130 of 6372 rows got a match: Gaulish cities along the Liger/
Sequana/Rhodanus (topostext's own tribal-list phrasing, "whose city is
Avaricum" beside "Liger river"), North African cities on the Bagradas,
Anatolian and Persian cities "between the Indus and the Bidaspes" or "on
the Tigris river", and real tributary/delta-fork relationships between
differently-named rivers themselves (Arar/Dubis and Padus/Dorias above;
also Kiabros/Cebrus/Danuvius in Moesia, Oxos/Ochos and Iaxartes/Demos/
Baskatis in Central Asia, Indus/Koas and Ganges/Pseudostomos/Seros in
India, Nanagunas forking into the Goaris and the Binda - the same India
river-fork family already confirmed for the `teilung`/`aufteilung`
regex fix earlier this session).

`coast`/river-line counts unaffected by this round except the two crossing
fixes (`river`: 109 -> 104, the four wrongly-merged pairs now six
separate, correctly-unconnected single points plus the fixed Britain
pair - no points lost, only wrong edges removed);
`check_self_intersections.py` stays at 1.

**A twelfth round, a coast/lake review and a color pass**: the user spotted
two odd, unconnected dark-blue "coast" dots sitting inland in Spain on a
rendered map and asked whether they should have been rivers or lakes,
plus a general review of the `lake` category and a color change (rivers
and river points to light blue instead of green, lakes to a larger
light-blue marker, harbor towns to green in the color light blue frees up).

The two Spain dots turned out to need two *different* answers, not one.
`2.04.03.04` ("Anas (Grenzpunkt Baetica, Lusitania, Tarraconensis)") is
genuinely river-related - topostext: "Where the river touches the border
of Lusitania", `Modern_location` "Guadiana" - a boundary marker sitting
*up the river Anas/Guadiana itself*, correctly excluded from the
coastline's own edges earlier this session (`_COASTLINE_SKIP_REF_IDS`)
but still carrying the wrong point category/color, since that exclusion
only touches which edges get drawn, not what a point *is*. Its own bare
name has no river keyword ("Anas" is just the river's proper name, no
"Mündung"/"Quelle"/course-marker), so nothing in `_classify_locality`
could catch it automatically - needed a new point-level override,
`_RIVER_POINT_OVERRIDES`, the river-category counterpart of the existing
`_ISLAND_POINT_OVERRIDES`/`_MOUNTAIN_POINT_OVERRIDES`. The second dot,
`2.04.03.07` ("Baetica (Ostende am Baliarischen Meer)", re-cited verbatim
at `2.06.12.05`), is neither a river nor a lake - topostext: "there along
the border of Tarraconensis to where the Balearic sea ends" - a plain
province-to-sea boundary *endpoint*, the same "Grenzpunkt" shape as the
many already-non-coastal boundary markers found earlier this session
(`5.03.01.06` etc., all `city`), just sitting in a section whose header
happens to be coastal ("Baliarisches Meer") with nothing in its own name
to redirect it. `_NONCOASTAL_POINT_OVERRIDES`, the point-level
counterpart of the existing section-level `_NONCOASTAL_EXCEPTION_SECTIONS`,
covers this shape (a single point, not a whole section, needing the
non-coastal fallback).

The general lake review found nothing wrong: every one of the 34 existing
`lake` points resolves to a real, correctly-identified lake (`Modern_location`
confirms Lake Garda, the Sivash, the Dead Sea, Lake Van's neighbors, the
Aral Sea, and so on), and the 7 catalogue names elsewhere that also
contain "See"/"Lacus"/"Palus" but *aren't* categorized `lake` are all
correctly excluded already - a river point merely naming a lake as its
own *location* ("Padus (Ausfluss aus Lacus Larius)", the Po's own point
describing where it exits Lake Como, correctly `river` not `lake`), the
same distinction `_LAKE_LOCATION_REF_RE` already exists to draw.

The color change itself (`CATEGORIES` in `ptolemy_map.py`, used by both
renderers): `river`/`river_mouth` change from green/light-green to a
shared light blue (`#6ec6ff`) - "Flodpunkter lyseblå" - so a river reads
as a lighter-weight cousin of the coastline's dark blue rather than a
distinct green family; `lake` moves to the *same* light blue rather than
its own color, on the reasoning that a lake is inland water too and
should read that way at a glance - distinguished from an ordinary river
point by marker *size* instead of color (`radius=11` vs. `8`/`5` in the
Leaflet map, `s=70` vs. `42`/`16` in the static map), so it doesn't just
blend into the river points around it. `harbor` takes the green
`river`/`lake` gave up (`#2ca02c`) - a harbor town is still coastal
(unchanged in `_COASTLINE_CATEGORIES`, still traced into the coastline
same as before), just recolored. `coast` itself (dark blue) and every
non-water category (`city`, `mountain`, `island`) are unchanged.

**A thirteenth round, closing the validation loop**: a methodological
question rather than a bug report - every fix so far this session had
been found reactively (a self-intersection, the user's own eye on a
rendered map, a targeted header scan of one region at a time), never
by a systematic, topostext-driven sweep of the *whole* catalogue's
category assignments. `crossref_topostext.py` already existed to do
exactly that (compare our `category` against what topostext's own
English phrasing implies - "mouth of"/"estuary" -> river_mouth/coast,
"harbor"/"port" -> harbor/coast, "island" -> island, etc.) but re-matched
topostext against the catalogue with its own strict 0.02deg coordinate
tolerance instead of using `link_matches.py`'s better, ~6000-match fuzzy
matches already sitting in the annotated CSV - so it had only ever
checked a subset, and, going by the absence of any fix in this session's
history that traces back to it, had likely never actually been run and
acted on. Rewritten to read the catalogue's own `topostext_matched`/
`topostext_name` columns directly (no more separate re-matching), plus
two refinements found immediately on the first run: a settlement
topostext calls a "city"/"town" isn't a disagreement when our own
category is anywhere in the coastal family (`coast`/`harbor`/
`river_mouth`) - that's this project's schema working as intended, a
coastal city still walks the shore - and a "lake" mention against a
`river` category isn't one either when the catalogue's own name already
marks it as a location reference rather than the lake's own identity
(`_LAKE_LOCATION_REF_RE`, duplicated from `ptolemy_map.py` to keep this
script self-contained).

First run: 200 candidate disagreements (up from the old script's zero
findings this session, simply because it was never run). Worked through
in short-phrase-first order (a clean "X harbor" citation is almost always
about the matched point itself; a long multi-clause boundary/region
description mentioning several features in passing is usually noise -
sorting this way put the signal at the top and the noise at the bottom
without having to solve that generally). Concrete fixes, each verified
the same way as every prior round (topostext quote + section-header
check before touching anything):

- **Marmarica/Cyrenaica's Mediterranean coast** (book.map `4.05`,
  sections `03`-`07`) and **Egypt's Red Sea coast continuation**
  (sections `14`-`15`) - the same "sea named once, not repeated" header
  gap as several regions found earlier this session, this time in North
  Africa: 14+ harbor towns (Antipyrgos, Panormos, Selinus, Leukaspis,
  Arsinoe, Myos Hormos...) sitting in `city`.
- **Epirus's own Ionian coast** (book.map `3.14`, sections `02`/`04`) -
  Orikon, Panormos, Onchesmos, Kassiope, Buthroton, Schlammhafen, the
  same gap shape, continuing section `01`'s "Ionisches Meer" header.
- **The other Ionian islands** (book.map `3.14`, sections `12`/`13`) -
  Kephallenia, Erikusa, Skopelos, Leukas, the Echinades, Ithaca, Lotoa/
  Letoa, Zakynthos - each a real, separate island cited once (not a
  single island's own coastal walk, so `_ISLAND_APPENDIX_SECTIONS`, not
  `_ISLAND_LINE_GROUPS`), sitting in `city`.
- **A wide batch of the same "plain-named harbor, no sea-word header"
  gap** across regions never checked for it before: Sardinia (explicitly
  headed "Description of the coast/southern side/eastern side" in
  topostext, book.map `3.03`), Sicily (`3.04.07`), the whole Peloponnese
  coast book.map by book.map (Korinthia/Achaia/Elis/Argolis, `3.16.03`
  through `3.16.13`), Attica (`3.15.07`), Crete's west and east coasts
  (`3.17.02`/`05`), Mauretania (`4.01.02`/`03`, `4.02.02`), Africa
  (`4.03.04`, `4.03.12`), Cyrenaica again (`4.04.03`/`05`), Pontus
  (`5.06.06`), India (`6.08.09`) - 21 sections, each independently
  confirmed via its own topostext passage before being added.

`coast`: 754 -> 864 (+110 across this round); `island`: 307 -> 317 (+10,
the Ionian islands); `check_self_intersections.py` stays at 1. The
river-vs-coastline crossing check (this session's other diagnostic, not
part of the regular pipeline either) picked up one new near-miss once
Argolis's coast was filled in - the Inachos river's straight source-to-
mouth line now grazes a *different*, unrelated stretch of the same
Peloponnese coastline near Lakonia. Checked and left alone, the same
"genuine Ptolemaic distortion of a real mouth+source pair" call as
Kaystros/Thermodon/Tyras/Volturnum-Cumae earlier - the coastline itself
didn't get any less correct by being completed, it just made a
pre-existing distortion in the *river's* coordinates newly visible.

The other ~150 remaining disagreements were checked in bulk and are not
bugs: a name shared between an island and its own city (Chios, Korkyra,
Tenedos-style - `island` is the deliberate, already-established choice);
a cape sitting on an island, correctly `island` rather than `coast`
(matches the sea it's on either way); a mountain that genuinely ends at
the shore (Mt. Athos/Akrokeraunia/Garganus-style, correctly `coast` -
verified geometrically too, each sits smoothly in-line with its coastal
neighbors' own coordinates rather than offset inland); the Maiotic Lake/
Sea of Azov, correctly treated as coastal water in this catalogue rather
than a small inland lake; a handful of fuzzy-match near-misses where the
*matched citation* is wrong, not the category (Priene/Mylasa picked up a
nearby "named mountains of Asia" citation instead of their own); and a
long tail of multi-clause boundary/region descriptions that mention a
harbor or estuary only in passing while describing an unrelated inland
city (Camulodunum, Petuaria, Flavium Brigantium, Banatia) - the same
shape already confirmed non-coastal earlier this session, re-confirmed
here rather than reversed.

**A fourteenth round, quantifying the question the whole review was
built on**: rather than another region, a methodological one - if you
classified purely from topostext's own English wording, with no access
to the catalogue's category, its German name, or any of this project's
exception lists, how often would that land on the same category the
catalogue/keyword pipeline produces? A new script, `topostext/
category_check.py`, builds exactly that: one ordered keyword list
(island > mouth/estuary > harbor/port > promontory/cape > bay/gulf >
lake > source/spring > mountain > city/town/village), first match wins,
deliberately cruder than `_classify_locality` (no section-header
context, no location-reference guards, no hand-verified exceptions) so
the comparison is a genuinely independent second opinion rather than a
restatement of the same logic.

Result: of 6207 matched points, 4600 have no recognizable category
keyword in their topostext phrase at all - just a bare name, most often
for `city` points (3666 of 4290 plain cities are uninformative this way)
- so a topostext-only classifier could never *replace* the primary one,
only check a subset of it. Where it does venture a guess (1607 points),
raw agreement is 76.5%, but that number undersells it: broken down by
category, the categories with the *lowest* raw agreement (`coast` 58%,
`harbor` 33%, `mountain` 68%, `lake` 59%) aren't lower because topostext
is right and the catalogue is wrong - pulling the actual rows behind
each shows they're overwhelmingly the same three structural mismatches
already identified by hand in the thirteenth round: a coastal city reads
`coast` in our schema but topostext's phrase just says "city" with no
coastal word (108 of the `coast`/`city` mismatches, spot-checked -
Populonium, Tempsa, Locri, Sulci, Bithia, Nora... all genuinely coastal,
several fixed *this session*); a coastal mountain reads `coast` but
topostext says "mountain" (the Athos/Akrokeraunia shape); the Maiotic
Lake reads `coast` but topostext says "lake". None of these are errors -
they're a finer-grained schema (this project distinguishes *where* a
point sits from *what kind* of feature topostext's prose calls it) being
compared against a cruder one that can't make the same distinction.

That said, the reverse direction - `city` points where topostext's own
wording implies something coastal - is exactly where a genuine miss
would hide, and checking all 26 of those (not just the ones
`crossref_topostext.py`'s wider net had already caught) found five more
real gaps the thirteenth round's manual sweep missed: Illyria's own
Ionian coast (Dyrrhachion/Apollonia/Aulon, `3.13.03`), Picenum's
Adriatic coast (`3.01.21`), Sicily's east coast including Taormina
(`3.04.09`), Numidia's coast at Cape Bon (`4.03.05`), Aiolis' own coast
including Elaia (`5.02.06`), Cape Guardafui (`4.07.05`), Doris/Caria
around Halikarnassos and Knidos (`5.02.10`) - eight sections, added to
`_COASTAL_APPENDIX_SECTIONS` the same way as every other round. One
candidate (`3.02.06.03` "Tarrabenier") turned out to be a mismatched
topostext citation (a different, unrelated "Casalus bay" citation from
a different section entirely, coincidentally scoring high enough to
match) rather than a real gap - left alone, `city` is correct (an inland
tribal-list entry, not a coastal point).

`coast`: 864 -> 895; `check_self_intersections.py` stays at 1.

**So: should this run early in the pipeline, ahead of the German-keyword
classification, the way the user asked?** No - and the numbers say why,
not just precedent. Two thirds of all matched points have no usable
signal in topostext's phrasing at all (a bare name, nothing else), and
where it does have a signal, it's frequently *coarser* than what this
project's schema actually wants (topostext doesn't distinguish "a
coastal cape" from "an inland mountain that happens to end at the
coast", or "a harbor town" from "an ordinary coastal city" the way the
catalogue-driven categories do). Running topostext-first would mean
classifying two thirds of the catalogue from nothing and the rest from a
blunter signal than what's used today. What the numbers *do* support is
exactly what this round demonstrated: topostext is a strong, independent
*validator* for the subset it can speak to, worth running as a
recurring check (the same standing as `check_self_intersections.py`
and the river-vs-coastline crossing check) - not a replacement for the
primary classification, a second opinion that catches what the primary
one's keyword rules structurally can't see.

**A fifteenth round, auditing the GeoPackage directly in QGIS**: the
user opened `ptolemy_geographica.gpkg` in QGIS and, using the new
combined line+node layers, clicked a stray `coastlines` node near the
Douro and found `2.05.01.06` ("Durius (Grenzpunkt Lusitania,
Tarraconensis)", `Modern_location` "Douro") sitting in `category=coast`
- the same shape as the Anas/Baetica boundary markers found earlier this
session, just not yet checked this far north, and asked whether the
catalogue has other "Grenzpunkt" points with the same problem.

It does, but not many: of 97 "Grenzpunkt"/"Endpunkt"/"Grenze"-named
points catalogue-wide, only 27 are `coast`. Checked each one against
its own topostext citation - 23 are genuinely coastal (topostext
explicitly names a sea/gulf as the boundary's own endpoint - "the other
on the Adriatic at", "termination at the sea", "the inner recess of
the...Maisanites Gulf" - or, for the Arabia Felix "Endpunkt am Meer"
mountain pairs, sit smoothly in-line with their coastal neighbours' own
coordinates, the Athos/Akrokeraunia shape already confirmed earlier)
and left alone. Three are not:

- `2.05.01.06` itself - fixed the same way as Anas, added to
  `_RIVER_POINT_OVERRIDES`.
- `2.16.01.04` ("Grenzpunkt (Illyricum, Pannonia Superior)") - topostext
  explicitly contrasts it with a *different*, genuinely coastal sibling
  ("Illyria is bounded on the north by the two Pannonias...the other
  [end] on the Adriatic at" - that other end is `2.16.01.05`, correctly
  left coastal). This one is the inland end.
- `6.14.01.06` ("Grenzpunkt (beide Skythien, unbekanntes Land)") - a
  pure Central-Asian land-boundary description (Sarmatia/unknown land/
  Mt. Imaos), no sea mentioned anywhere in its citation.
- `5.19.01.04` ("Grenzpunkt (Arabia Deserta, Babylonien, Mesopotamien)")
  - the same river-following-boundary shape as Durius/Anas (topostext:
  "the remaining part of the Euphrates river...to the limit point at"),
  well inland of the same walk's own two genuinely coastal points a few
  steps later (`5.19.01.11`/`.13`, both explicitly "the Persian Gulf").

These three, lacking a clean single named-river attachment the way
Durius/Anas had, went into `_NONCOASTAL_POINT_OVERRIDES` instead
(`city`, the same fallback as the earlier Baetica-Ostende case). The
7 "Grenzpunkt"-named points in `river`/`mountain`/`lake` were checked
too and are all already correct (Pyrene-Gebirge, the Rha/Volga bend,
Lake Byke's own end point, etc.).

Fixing Durius surfaced a second, independent bug once the pipeline
re-ran: with the inland Grenzpunkt gone, `Durius-Mündung` (the Douro's
real mouth, correctly `river_mouth`) became a direct coastline edge
straight to Balsa in the Algarve, cutting across the rest of Lusitania's
own coastal loop three times - a crossing that didn't exist before
purely because the *wrong* two-hop path (via the inland Grenzpunkt)
happened not to cross anything, by coincidence. Reading the full trail
(Balsa -> Ossonoba -> Heiliges Kap/Cape St Vincent -> up the west coast
-> Vacua-Mündung, a few hundredths of a degree from Durius-Mündung's own
coordinate) showed the exact Acheloos-/Borysthenes-Mündung shape from
earlier this session: Durius-Mündung is Lusitania's own *northern*
boundary marker, stated first as an orientation point (topostext: "The
southern side of Lusitania is the common boundary with...Baetica. The
northern side links to Tarraconensis along the western part of the
Dourius river...The mouth of the river, which flows into the Outer
Sea") - the walk proper starts at Balsa (the Baetica-border end) and
closes the loop back up near Porto on its own. Added to
`_COASTLINE_SKIP_REF_IDS`.

`coast`: 895 -> 891 (net: -5 recategorized, +1 Durius's own edges no
longer inflating any count); `river`: 305 -> 306;
`check_self_intersections.py` stays at 1 after both fixes, confirming
the second one closed the gap the first one opened rather than just
moving it. `export_geopackage.py` re-run to refresh the delivered file.

**A sixteenth round, the Levant coast**: the user noticed several
well-known Phoenician coastal cities - Sidon, Tyros, Byblos - plotting
inland/at sea in a rendered map, and asked whether topostext gives any
context confirming they sit on the coast (since the catalogue's own
German names alone give none - "Sidon", "Tyros", "Byblos" carry no
coastal keyword of their own).

It does, decisively. Book.map "5.15" (Syria/Phoenicia/Palestine)
section "02" is headed "Syrisches Meer" and correctly coastal
(Alexandreia bei Issos, Myriandros, Rhosos...), but sections "03"
through "05" continue the identical walk without repeating that header
- the exact "sea named once, not repeated" gap fixed a dozen times
already this session, just not yet checked for the Levant. topostext
confirms one unbroken run, matching the catalogue's own item order
exactly: "mouth of the Orontes river...Poseidion...Herakleia...
Laodikeia...Gabala...Paltos...Balaneai" (section 03) straight into
"Phoinike: mouth of Eleutheros river...Simyra...Orthosia...Tripolis...
Theou prosopon promontory...Botrys...Byblos...mouth of the Adonis
river" (section 04) straight into "Berytos...mouth of the Leon river...
Sidon...Tyros...Ekdippa...Ptolemais...Sykaminon...Karmelos mountain...
Dora...mouth of the Chorseos river" (section 05). Section "06" resumes
with Judaea's own inland boundary description (`Grenzpunkt` entries,
correctly `city`), cleanly bounding the gap to sections 03-05. All
three added to `_COASTAL_APPENDIX_SECTIONS`.

Checked the same rendered area for anything else nearby while at it:
Cyprus's own "Kleiden" (`5.14.07.02`) was sitting in `city` too -
topostext: "The islands on its coast are those called Cleides" - its
neighbour "Karpasische Inseln" had already self-classified `island` via
the bare word "Inseln" in its own name, but "Kleiden" (Cleides), a
proper name with no such keyword, hadn't. Added `("5.14", "07")` to
`_ISLAND_APPENDIX_SECTIONS` (a two-island list, the same shape as
Corfu's Ionian-island neighbours earlier). The offshore islet also
named "Tyros" (`5.15.27.03`, distinct from the mainland city - topostext:
"Islands off Syria: Arados...and Tyros just offshore") was already
correctly `island` via an existing entry.

`coast`: 891 -> 909 (+18); `island`: 317 -> 318;
`check_self_intersections.py` stays at 1. `export_geopackage.py`
re-run again to refresh the delivered file.

**A seventeenth round, generalizing the Levant fix catalogue-wide**: the
user's response to the Levant fix was pointed - this is exactly why
topostext deserves more weight than it's been given, and *why* the
earlier per-point checks (`crossref_topostext.py`/`category_check.py`)
missed it deserved a real answer, not just agreement. The reason is
structural: those checks only ever flag a `city` point when *that
point's own* topostext phrase contains a coastal keyword. Sidon's,
Tyros's and Byblos's own citations are bare names - no keyword at all.
The signal was never in their own phrase, it was in their *section*:
sitting between already-correctly-classified points that do carry a
keyword (a `-Mündung` river mouth, a `Kap` cape).

That turned out to be checkable without topostext at all, first: any
section mixing coastal-family points (`coast`/`harbor`/`river_mouth`)
with plain `city` points, and not already sea-headed, is structurally
suspicious on its own - this project's whole classification premise is
that Ptolemy's sections are narratively homogeneous (a coastal run OR
an inland list), so a section doing both at once is far more likely to
be one coastal run some of whose points merely lack their own keyword.
That test alone found **110 sections** catalogue-wide - roughly ten
times the size of any single earlier round.

Every one got checked against its own full topostext text (not just the
flagged points' bare phrases) before being added - 109 confirmed
straightforwardly coastal (Lusitania, the Basque/Catalan coast,
Dalmatia, Macedonia and Thessaly, Boiotia, Messenia, Crete's south
coast, a dozen North African provinces, a dozen Anatolian ones, the
Levant's own continuation past the earlier fix, the Persian Gulf coast
of Babylonia/Susiane/Persis, and India's Malabar/Coromandel/Ganges-delta
coasts - the full list and representative quotations are in the code
comment on `_COASTAL_APPENDIX_SECTIONS`). One, `3.05.14`, was excluded:
its own `city` point is a boundary marker at the Tanais' *source*, the
same Durius/Anas shape, not a coastal gap.

Applying 109 sections at once - roughly a third more coastal points
catalogue-wide in one commit than every prior round of this session
combined - surfaced real interaction bugs with several already-
carefully-tuned areas, exactly the same way fixing the Durius Grenzpunkt
exposed a second bug at Balsa a few rounds ago, just seven times over.
Each was tracked down with the same rigor as every other fix this
session, not batch-applied blind:

- **Lusitania** (`2.05`): a second "Tagus (Grenzpunkt Lusitania,
  Tarraconensis)" - Modern_location "Tejo" - and a second re-citation of
  Durius-Mündung itself, both newly swept in by section `2.05.04`
  becoming coastal. Fixed the same way as the Durius/Anas cases
  (`_RIVER_POINT_OVERRIDES`, `_COASTLINE_SKIP_REF_IDS`).
- **The Danube delta** (`3.10`): section `3.10.08`'s own cities (Histria,
  Tomi, Callatis, Dionysopolis, Odessus) extended that coastal run past
  its old end (Panysus-Mündung, already hard-broken from the delta) to
  its *real* end, Mesembria - matching topostext's own list exactly
  ("...Panysos river mouth...Mesembria") - but the existing hard break
  didn't follow the run's new endpoint, so the ordinary stitch wired
  Mesembria straight to the delta's Axiakes-Mündung instead. Added a
  second `_COASTLINE_HARD_BREAKS` entry at the run's new true end.
- **Macedonia** (`3.13.06`): a section that was never really a gap -
  "Malischer Golf" already self-classified via the word "Golf" - just
  happened to also contain a `Grenzpunkt` (Achaia/Epiros/Makedonia's own
  land tripoint via Mt. Pindos) that the structural mix-detector flagged
  along with it. Excluded via `_NONCOASTAL_POINT_OVERRIDES`.
- **Bithynia/Pontus** (`5.01.06`): a genuine second keyword gap, not a
  section problem - "Sangarios (erste/zweite/dritte Krümmung)" uses
  "Krümmung" ("bend"), a synonym of "Biegung" that `_RIVER_COURSE_RE`
  didn't recognize, so these river-bend points fell through to `coast`
  once their section was correctly made coastal for the river's mouth.
  Checked the whole catalogue (6 "Krümmung" hits: 5 genuine river bends,
  1 a plain administrative boundary bend that needed excluding by
  pattern, not by hand) before broadening the regex.
- **The Levant** (`5.16.01`): the exact same re-citation shape as the
  Durius case, one book.map over - a bit-identical coordinate duplicate
  of Egypt's own Grenzpunkt (`4.05.13.03`, already correctly part of
  Egypt's coastline), re-cited as Judaea's introductory boundary point
  before its own walk (Kaisareia down to Anthedon) became coastal.
- **Gedrosia/India** (`6.21`): the same shape a third time - a duplicate
  citation of the walk's own real last point re-cited earlier as an
  introduction - plus a genuine third keyword gap, "Zufluss" (inflow/
  tributary, the same shape as the already-recognized "Ausfluss"):
  "Arbis (Namenloser Zufluss aus Drangiane)" sits 5 degrees north of the
  coastal walk it was swept into, a real river-tributary point, not a
  coastal one. Checked catalogue-wide (4 "Zufluss" hits, all genuine
  tributary citations) before broadening `_RIVERFEAT_RE`.

The river-vs-coastline crossing check (not part of the regular pipeline,
run manually given the scale of this change) found two more new
near-misses once the newly-completed coastlines started passing close to
existing river lines - the Po (`3.01.24`) and the Kaikos/Bakır Çayı
(`5.02.05`). Both checked and left alone: genuine mouth-and-source pairs
of real, correctly-identified rivers (Modern_location confirms both),
the same "coastline got more complete, so a pre-existing coordinate
distortion became newly visible" shape as Kaystros/Thermodon/Tyras/
Volturnum-Cumae earlier.

`coast`: 909 -> 1268 (+359, the single largest jump of any round this
session); `river`: 306 -> 314 (Krümmung + Zufluss); `city`: 4000 -> 3634;
`check_self_intersections.py`: back down to 1 (the one deliberately-left
Campania wobble) after 8 targeted follow-up fixes.
`export_geopackage.py` re-run to refresh the delivered file.

**An eighteenth round, quantifying the classification premise itself**:
after the Levant/India rounds above, the user asked four direct
questions about the method rather than a specific point - is it actually
true that Ptolemy doesn't mix categories within a section, how much can
a section's *header* alone (from either source) tell you about its
points' category, what kind of signal only ever shows up at the
individual point, and how much do the two sources' own section headers
agree with each other. `topostext/section_header_check.py` answers all
four with real numbers instead of impression, the section-level
counterpart of `category_check.py`'s per-point question:

- **Are sections category-homogeneous?** Yes, overwhelmingly: of 1067
  catalogue sections with 2+ classified points, **939 (88.0%) are a
  single category-family** (`coast`/`harbor`/`river_mouth` counted as
  one "coastal" family, matching this project's whole classification
  premise) and another 51 (4.8%) are ≥80% one family with only a small
  aside. Only **77 (7.2%)** have no majority family at all - and
  breaking those 77 down by which two families they mix shows it isn't
  random noise: `(coastal, river)` 18, `(city, river)` 10, `(city,
  mountain)` 8, `(coastal, mountain)` 7, `(mountain, river)` 6, `(city,
  island)` 5, the rest smaller 2-3-way combinations. Every one of these
  pairings is the same shape already found and fixed by hand throughout
  this session - a boundary/source citation of a different type sitting
  as an aside inside an otherwise-homogeneous run (Durius/Anas, Argaios,
  Zames, the many `Grenzpunkt` entries) - not evidence the premise is
  wrong, evidence for *why* the point-level override lists
  (`_RIVER_POINT_OVERRIDES`/`_NONCOASTAL_POINT_OVERRIDES`/
  `_ISLAND_POINT_OVERRIDES`/`_MOUNTAIN_POINT_OVERRIDES`, 29 entries
  total) had to exist as a separate mechanism from the section-level
  ones (`_COASTAL_APPENDIX_SECTIONS` and its three siblings, 276 entries
  total) in the first place.

- **How much can a header alone tell you?** Both sources' own section
  headers were classified independently and blind (a small ordered
  German keyword list for the catalogue's own un-coordinated header
  rows; `category_check.py`'s existing English patterns, reused as-is,
  for topostext's own lead-in prose before a section's first
  coordinate), then checked against the section's actual verified
  dominant category. The catalogue's own header is a weak, sparse
  signal: of 952 checkable sections, **714 (75%) have no recognizable
  German keyword at all**, and of the 238 that do, only **50.8%** match
  the section's real category - because a header naming a sea or a
  mountain range is naming a *landmark*, not committing to what type
  every point in the section will turn out to be. topostext's own prose
  is a meaningfully stronger signal - still sparse (341/521, 65%, no
  keyword) but **70.6%** accurate when it does venture one - confirming
  by the numbers what the Levant find already showed by example.

- **What can only be read at the point level?** Two systematic classes,
  both visible directly in the confusion matrix below: a section headed
  by a *mountain range* whose points are actually river **sources**
  ("Vindion-Gebirge" heading a run of "Sources of the River Namados in
  the Ouindion range" citations - 14 such sections in India's book 7
  alone) - the header names the orienting landmark, and only the
  individual point's own "Quelle"/"Ursprung"/"sources of" wording says
  what *that point* actually is; and a section headed by a *sea name*
  whose points are actually an **island** appendix ("islands lying near
  Italy in the Ligurian sea" - 17 such sections) - the pre-existing
  shape `_ISLAND_APPENDIX_SECTIONS` already exists to handle. Beyond
  these two systematic patterns, the same point-level-only signals
  found by hand all session remain the only way to resolve the
  remaining asides: German morphological suffixes (`-Mündung`/
  `-Quelle(n)`/`-Gebirge`/`-See`), the literal word "Grenzpunkt"
  (boundary point), a `Modern_location` cross-check (Tejo confirming
  Tagus), and shared island/city names.

- **Do the two sources' own headers agree with each other?** Of 450
  sections with a header from *both* sources, only 92 get a keyword
  guess from both, and of those, **47 (51.1%) agree**. The confusion
  matrix shows the disagreement is the same two systematic patterns
  above, not noise - `mountain`(catalogue) vs `river`(topostext) (14
  cases: both readings are correct, they're just answering "what
  landmark is this near" vs "what is this point" respectively) and
  `coastal`(catalogue) vs `island`(topostext) (17 cases: topostext's
  phrasing is the more precise one, and matches `_ISLAND_APPENDIX_SECTIONS`
  exactly). So a low cross-source agreement rate here isn't evidence
  either header is unreliable in general - it's confirmation that a
  sea-name or mountain-name header is a landmark reference, not a
  category label, which is exactly why this project classifies by
  *point*, using the section header only as one input among several.

```
$ python3 section_header_check.py
```

### Coverage: how much of each catalogue is mapped to the other, and a fuzzy match score

`crossref_topostext.py` flags category disagreements on individual
matches, but doesn't say how complete the coverage is in either direction,
and a strict 0.02°-tolerance coordinate match (what "matched" meant
everywhere in this project until now) turned out to leave most real
matches on the table: two independently-edited sources round DMS
coordinates slightly differently often enough that requiring near-exact
agreement was the wrong bar. `link_matches.py` replaces that with a single
fuzzy **match score** (0-100, written to both CSVs) blending distance and
name, used everywhere "matched" is decided now:

- **distance <= 0.02°: score 100**, no question - this is the old strict
  tolerance, still exactly right when it's met.
- **distance > 3.0° (`CANDIDATE_WINDOW_DEG`): not a candidate at all**,
  regardless of name - a coincidentally-identical short name somewhere
  unrelated across a whole book shouldn't out-vote real geography.
- Between those two, a blended score: a distance component - linear
  falloff from just-under-1 to 0, but across the *tighter* 1.5°
  `DIST_SCORE_REF_DEG`, so it bottoms out at 0 well before the wider 3.0°
  candidate window does rather than staying generous all the way out -
  and a name-similarity component (`_name_similarity` in
  `verify_near_matches.py`), 55/45 weighted toward distance. Two distance
  numbers instead of one was itself a fix: catalogue "Garra" (4.02.25.04)
  and topostext's own "Garra" - the exact same name - sit 1.33° apart
  (one source's transcription drifted), rejected outright by an earlier
  single 1.2° cutoff before the name was even looked at; now a near-
  identical name can still carry a match past the threshold on its own
  once the distance component has floored to 0 (Garra scores 51).
  `_name_similarity` translates the catalogue's German descriptor
  vocabulary to English *before* folding away umlauts (translating after,
  the original bug here, silently skipped every umlauted word -
  "mündung", "ästuar", "südlich" - which is most of the vocabulary),
  strips topostext's own multi-city-run lead-in prose ("...among whom are
  the towns: X"), and compares every token of a longer descriptive phrase
  against the catalogue name (not just a whole-phrase check) with a
  *graduated*, not yes/no, per-token similarity (`_token_sim`): a shared
  *leading* stem, scaled by the longer token's length ("taurische"/
  "taurianus" -> 0.56, "sipontum"/"sipus" -> 0.38), or - for drift not at
  the very start of the word - a whole-token edit-distance ratio, but
  gated at 0.6 ("ilipa"/"illipa" -> 0.91, "orospeda"/"ortospeda" -> 0.94
  pass; "tyana"/"kydnos" -> 0.36, two words with nothing in common beyond
  scattered shared letters, doesn't). A small bonus is added when the
  phrase's implied type (`crossref_topostext.py`'s `_TYPE_HINTS` -
  "mouth of"/"estuary" implies `river_mouth`/`coast`/`harbor`, etc.)
  agrees with the candidate's actual category, to break ties between two
  real, differently-named points sitting close together (a plain city
  right next to the river-mouth point a "mouth of the X river" phrase is
  actually describing).
- A whole-*phrase* sequence-ratio fallback (for a short name that's pure
  transliteration drift, "Ebusus"/"Ebussos") only applies when both names
  are themselves a single token - applied to longer phrases it stops being
  a name check and starts rewarding coincidental character overlap
  between unrelated text, the same failure mode the per-token ratio gate
  above guards against.
- A candidate scoring below 45 isn't recorded as a match - see
  `link_matches.py`'s docstring for the full formula and reasoning. This
  raised matched coverage substantially: **944 → 165 unmapped catalogue
  points, 921 → 122 unmapped topostext citations**, at the time of
  writing - now measured across the *entire* catalogue (books 2-7), not
  just the partial range covered when those thresholds were first tuned.

**The point of this whole exercise was never a 100% match rate** - it was
to validate the catalogue against an independent source, and it did:
**6013 of 6178 catalogue points (97%) and 6137 of 6259 topostext
citations (98%)**, across the whole catalogue, now cross-confirm each
other by both coordinate and name. The ~2-3% left in
`unmapped_review.xlsx` isn't
presumed to be errors in the catalogue - topostext is itself a translated,
independently-edited secondary source and can just as easily be the one
that's wrong, abbreviated, or citing a genuinely different point. Chasing
the last few percent with an ever-more-permissive algorithm stops being
validation at some point and starts being curve-fitting to specific
examples; `link_matches.py`'s thresholds (match score 45, distance score
reference 1.5°, candidate window 3.0°) are where that line was drawn.

Three scripts, run in this order:

- `link_matches.py` computes the score both directions and writes it back
  into *both* source files: `topostext_matched`/`topostext_ref`/
  `topostext_name`/`topostext_match_score` on the annotated catalogue,
  `catalogue_matched`/`catalogue_ref_id`/`catalogue_name`/
  `catalogue_match_score` on `topostext_209.csv` - and builds
  `unmapped_review.xlsx`, a two-sheet workbook (`unmapped_catalogue`,
  `unmapped_topostext`) of what's still below the threshold, for manual
  review. Re-run it after any `annotate_dataset.py` run or newly-appended
  topostext chunk - `write_annotated_csv()` only knows its own fixed
  column list and overwrites these four extra columns' values (not the
  columns themselves) on every regeneration.
- `coverage_summary.py` prints the same two-way gap as a summary and
  dumps the full unmatched lists to `forward_unmatched.csv`/
  `reverse_unmatched.csv` (the catalogue side scoped to the book.map range
  topostext has actually covered: book 2 maps 02-16, book 3 maps 01-17,
  book 4 maps 01-08, and all of books 5-7) - it now just reads the
  columns `link_matches.py` already wrote rather than recomputing its own
  match, so run `link_matches.py` first.
- `verify_near_matches.py` is the diagnostic this scoring grew out of -
  originally built to sanity-check whether topostext's "unmatched"
  citations were really missing data or just edition/rounding drift
  against a point already in the catalogue. Its name-similarity function
  is now `link_matches.py`'s own name component, imported directly rather
  than duplicated.

## Compiling the catalogue to data: `annotate_dataset.py`

Everything described above - classification, graph reconstruction, distance
thresholds, the two exception lists, river-line name grouping - is
*reasoning* the xlsx loader has to redo every time it runs, because nobody
had gone through and settled those questions once and written the answers
down. `annotate_dataset.py` does exactly that: it runs the classifier, the
coastline graph algorithm, and the river-line grouping once over the whole
catalogue and writes the result as data, in
`data/ptolemy_catalogue_annotated.csv`:

- `category` - unchanged from the xlsx loader's output.
- `naming_observation` - *why* that category was picked: which keyword
  matched, or which manually-verified exception applied, e.g. `starts with
  'Kap' (cape) - coastal regardless of any mountain-range aside` or
  `manually verified island-appendix section
  (_ISLAND_APPENDIX_SECTIONS)`. This is an audit trail, not a new
  classification - if a point's category looks wrong, its
  `naming_observation` says which rule to fix (or, for the two exception
  lists, which `(book.map, section)` entry to add or remove) rather than
  requiring a re-read of the classifier's source.
- `feature_id` / `sequence_in_feature` / `feature_closes_loop` - which
  drawn coastline (if any) a point belongs to, its position within it, and
  whether that line closes into a loop. These are the graph algorithm's
  output, materialized: no more edges, junctions, or stitching-distance
  thresholds at draw time, just "group by `feature_id`, sort by
  `sequence_in_feature`, connect the dots, close the loop if
  `feature_closes_loop`" (`build_coastlines_from_features` in
  `ptolemy_map.py`). That's the same two-step process - set the points,
  connect the dots - a cartographer working from the Geographica's text
  would have followed by hand.
- `river_feature_id` / `river_sequence_in_feature` - the same, but for the
  river line (if any) a point belongs to, materialized from
  `build_river_lines()`. A separate pair of columns rather than reusing
  `feature_id`, because a river mouth is a member of both a coastline *and*
  a river line at once and needs to record both memberships (there's no
  loop-closing flag here - a river line never closes into a loop).
- `island_feature_id` / `island_sequence_in_feature` /
  `island_feature_closes_loop` - the same, but for an island's own coastal
  outline (if any) a point belongs to, materialized from
  `build_island_lines()` and the manually-verified `_ISLAND_LINE_GROUPS`
  allow-list.
- `mountain_feature_id` / `mountain_sequence_in_feature` - the same, but
  for a mountain range's own line (if any) a point belongs to, from
  `build_mountain_lines()`. A range is catalogued the same way a river's
  course is - its own named ends ("(W-Ende)"/"(O-Ende)", "(N-Ende)"/
  "(S-Ende)", ...) and sometimes a midpoint ("(Mitte)"), each its own
  entry - so `_mountain_base_name()` groups by the range's own name with
  its position marker cut off, the same shape as `_river_base_name()`,
  reusing the same re-citation dedup and a book-scoped gap cap (drawn as
  thick brown lines - see "Mountain-range lines" below).

`data/ptolemy_catalogue_annotated.csv` is the new default input
(`DEFAULT_INPUT` in `ptolemy_map.py`), for both `ptolemy_map.py` and
`static_map.py`. `get_coastlines()`/`get_river_lines()`/`get_island_lines()`
pick the trivial group-and-sort reconstruction whenever the loaded data
already carries a `feature_id`/`river_feature_id`/`island_feature_id`
(i.e. whenever you're reading the annotated CSV); they fall back to the
from-scratch algorithms (`build_coastlines`, `build_river_lines`,
`build_island_lines`, all described above) for the raw xlsx or any plain
CSV that hasn't been through the compiler - so pointing `--input` at
another source, or at a custom text file, still works exactly as before.

If you change a classification rule or either line-building algorithm,
regenerate the annotated CSV from the raw catalogue:

```bash
python3 annotate_dataset.py
# or, to point at a different source/output:
python3 annotate_dataset.py --input data/ptolemy_catalogue_stueckelberger.xlsx --output data/ptolemy_catalogue_annotated.csv
```

## Data

- `data/ptolemy_catalogue_annotated.csv` (default) — the compiled dataset
  described above: every plottable reference from the full catalogue
  (6,372 rows), already classified and, where applicable, already assigned
  to a coastline feature and/or river line and/or island outline and/or
  mountain-range line and draw position. Columns: `ref_id, name, category, book, tabula,
  modern_location, recension, lon_ptolemy, lat_ptolemy,
  naming_observation, feature_id, sequence_in_feature,
  feature_closes_loop, river_feature_id, river_sequence_in_feature,
  island_feature_id, island_sequence_in_feature,
  island_feature_closes_loop, mountain_feature_id,
  mountain_sequence_in_feature`. Regenerate it with `annotate_dataset.py`
  (above) after any change to the classifier or any line-building
  algorithm - don't hand-edit it except to correct a specific row's
  `category`/`naming_observation`/`feature_*`/`river_feature_*`/
  `island_feature_*`/`mountain_feature_*` fields.
- `data/ptolemy_catalogue_stueckelberger.xlsx` (compile source) —
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

## GeoPackage export (for QGIS/ArcGIS)

`export_geopackage.py` writes the same categories and constructed lines
the two map renderers draw as real vector layers instead of a picture:

```bash
python3 export_geopackage.py                # -> ptolemy_geographica.gpkg
python3 export_geopackage.py --output out.gpkg
```

One plain `Point` layer per category (`coast_points`, `river_points`,
`island_points`, ...) - every point, whether or not it's part of a
constructed line - plus one *combined* layer per line-building feature
type:

    coastlines, rivers, island_outlines, mountain_ranges

Each of these four holds both the constructed line itself and its own
ordered vertices in a single GeoPackage feature table, rather than a
separate line layer plus a separate "nodes" point layer needing a
GIS-side join to relate them - GeoPackage (like most of the OGC simple-
features model) allows a layer's geometry column to be the generic
`GEOMETRY` type instead of a single fixed type, so a `MultiLineString`
(the line, `record_type="line"`) and a `Point` (one of its vertices,
`record_type="node"`) can sit in the same table. `feature_id` is shared
between a line row and its own node rows, so grouping/filtering by it in
QGIS recovers "this one line plus its N vertices" with no join; each
node row also carries its own `sequence_in_feature` (draw order) and the
underlying point's own attributes (`category`, `Modern_location`,
Ptolemy's own coordinates), the same as the plain `..._points` layers
above, just pre-filtered to the subset that's actually part of a line.

Written via `fiona`, whose GPKG driver represents this as `schema =
{"geometry": "Unknown", ...}` - confirmed round-tripping cleanly through
both `fiona` and `geopandas` (`gdf.geom_type` shows the expected mix of
`Point`/`MultiLineString` rows, one query, no join).
