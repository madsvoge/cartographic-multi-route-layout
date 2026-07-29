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
| Harbor town | light blue | name matches "Hafen"/"Portus" - a distinct color from "Coastal point" so a harbor's own commercial/settlement role stands out, but otherwise treated identically: still sized like a coastal point and still a full participant in coastline reconstruction (see below) |
| River mouth | green | name matches "Mündung" - a distinct color from "Coastal point" for visual identification, but otherwise treated identically: still sized like a coastal point and still a full participant in coastline reconstruction (see below) |
| City / inland settlement | orange | default, for points not in a coastal section and not matching another pattern |
| River source / confluence / bend | green | name matches "Quelle" (source), "Einmündung" (confluence), "Zusammenfluss" (two rivers joining), "(Mitte)"/"Biegung" (a river's midpoint/bend), "Abzweigung"/"Aufteilung" (a delta fork) - checked *before* the coastal mouth pattern, since e.g. "Einmündung" contains the substring "mündung" and would otherwise be misread as a coastal river mouth |
| Mountain | amber | name matches "Gebirge" (mountain range) |
| Island | pink | name matches "Insel" (island), or the name ends in "(N)" - e.g. "Kassiteriden (10)" - the catalogue's convention for a scattered island group given as one count-labelled entry |
| Lake / inland water | green | name matches "See" (lake) or "Palus" (marsh/lake) |

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

This covers 121 of 234 `mountain` points, grouped into 59 lines (a
single-citation range - most of the catalogue's ~150 named peaks/ranges
only ever appear once, with no second point to connect to - still plots as
an individual point, no line).

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

The tool can't fetch topostext.org itself (blocked by this environment's
network policy), so the workflow is: paste a chunk of the site's text into
the conversation, save it under `topostext/raw_209_<range>.txt`, then:

```bash
cd topostext
python3 parse_topostext.py raw_209_<range>.txt -o topostext_209.csv --append
python3 crossref_topostext.py topostext_209.csv
```

`parse_topostext.py` splits the pasted text on `§ B.M.S` markers and pulls
every `(name phrase, longitude, latitude)` triple out of each paragraph in
catalogue order. It does *not* try to align by position within a
paragraph - topostext often folds a paragraph's opening point into its
lead sentence as a restatement of the *previous* paragraph's last point
("from the Boreum promontory which is in 11°00' . 61°00'..."), the exact
same "shared boundary citation" pattern already found directly in our own
data (Kap Oiarso, Nordspitze, Acheloos-Mündung) - so position-in-paragraph
isn't a reliable join key. `crossref_topostext.py` instead matches by
*coordinate* (both sources encode the same Ferro-relative degrees-minutes
values, so a real match is near-exact) and flags cases where our
`category` looks inconsistent with topostext's own wording.

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
    `_KAP_PREFIX_RE` already uses for "Kap Oiarso, Pyrene-Gebirge") and
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
