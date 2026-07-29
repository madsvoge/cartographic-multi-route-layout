#!/usr/bin/env python3
"""
Add synthetic "label" rows to the annotated catalogue for province/region
names, named island groups, and named mountain ranges - so the map can
carry a text label ("Thrace", "Britannia", "Corfu", "Pyrene-Gebirge") in
addition to its individual points.

Three sources, in order of how much verification each needed:

1. Province/region labels (_PROVINCE_LABELS below) - one per book.map,
   positioned at the centroid of every catalogue point in that book.map.
   The name comes from topostext's own opening sentence for that
   province's first section ("Position of Macedonia", "Setting of
   Hivernia British island", "Sarmatia is bounded on the north..."), a
   pattern confirmed near-universal across the whole covered range (see
   the raw_209_*.txt files' §B.M.1 openings). This is NOT free of gotchas
   - topostext's own book.map numbering runs one map ahead of ours for a
   stretch of book 3 (their §3.12 "Position of Macedonia" describes what
   our catalogue's Modern_location column confirms is actually book.map
   3.13, because our catalogue gives the Thracian Chersonese its own
   separate map 3.12 that topostext doesn't number separately) - each
   entry below was verified against a sample of that book.map's own
   Modern_location values, not assumed from the section number alone.
2. Named island-group labels - the five confirmed one-island coastal
   walks in _ISLAND_LINE_GROUPS (ptolemy_map.py) already carry a verified
   name; centroid of that built island line's own points.
3. Named mountain-range labels - every build_mountain_lines() feature
   already carries its shared base name (mountain_feature_id encodes it);
   centroid of that line's own points.

Only 2 (mountains) needs no topostext lookup, and 2/3 both reuse grouping
this project already computes - only 1 (provinces) required fresh manual
verification against topostext + Modern_location, the same "verify
against real evidence" standard as every other fix this session.

Re-run after annotate_dataset.py and/or link_matches.py, same as those -
this script first strips any previously-added category=="label" rows
before regenerating them, so it's safe to re-run any number of times.

Usage
-----
    python3 build_labels.py
"""

from __future__ import annotations

import csv
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CATALOGUE = SCRIPT_DIR.parent / "data" / "ptolemy_catalogue_annotated.csv"

# (book.map, name, note) - one per province/region, verified against
# topostext's §B.M.1 opening sentence AND a sample of the book.map's own
# Modern_location values (see module docstring re: the book-3 offset).
_PROVINCE_LABELS = [
    ("2.02", "Hivernia", "Ireland; topostext: \"Setting of Hivernia British island\""),
    ("2.03", "Albion", "Britannia / Great Britain; topostext: \"The position of Albion island of Britannia\""),
    ("2.04", "Baetica", "southern Hispania; name inferred from repeated in-text tribe mentions (Bastuli, Turdetani, Turduli) - this book.map's own opening line (§2.4.1) wasn't in the pasted chunk"),
    ("2.05", "Lusitania", ""),
    ("2.06", "Tarraconensis", "Hispania Tarraconensis"),
    ("2.07", "Aquitania", ""),
    ("2.08", "Lugdunensis", ""),
    ("2.09", "Belgica", ""),
    ("2.10", "Narbonensis", "Gallia Narbonensis"),
    ("2.11", "Germania", "Germania Magna"),
    ("2.12", "Raetia", "Raetia and Vindelicia"),
    ("2.13", "Noricum", ""),
    ("2.14", "Upper Pannonia", "Pannonia Superior"),
    ("2.15", "Lower Pannonia", "Pannonia Inferior"),
    ("2.16", "Illyria", "Illyricum; Liburnia and Dalmatia"),
    ("3.01", "Italy", ""),
    ("3.02", "Kyrnos", "Corsica"),
    ("3.03", "Sardinia", ""),
    ("3.04", "Sicily", ""),
    ("3.05", "Sarmatia", "European Sarmatia"),
    ("3.06", "Tauric Chersonese", "Crimea"),
    ("3.07", "Iazyges", "the Migratory/Sarmatian Iazyges, a nomadic people, not a settled province"),
    ("3.08", "Dacia", ""),
    ("3.09", "Upper Moesia", "Moesia Superior"),
    ("3.10", "Lower Moesia", "Moesia Inferior"),
    ("3.11", "Thrace", ""),
    ("3.12", "Thracian Chersonese", "Gallipoli peninsula; named directly in the catalogue's own section header (\"Thrakische Chersones\") - topostext's own map numbering runs one map ahead from here (their §3.12 is our 3.13, etc.)"),
    ("3.13", "Macedonia", ""),
    ("3.14", "Epiros", "Epirus"),
    ("3.15", "Achaia", "mainland Greece north of the Corinthian Gulf"),
    ("3.16", "Peloponnesos", "the Peloponnese"),
    ("3.17", "Crete", ""),
    ("4.01", "Mauritania Tingitana", ""),
    ("4.02", "Mauritania Caesariensis", ""),
    ("4.03", "Africa", "the Roman province of Africa proper, roughly Tunisia/NW Libya"),
    ("4.04", "Cyrenaica", ""),
    ("4.05", "Marmarike", "Marmarike with Libya and Egypt"),
    ("4.06", "Interior Libya", "Inner Libya, the Saharan hinterland behind the coastal provinces"),
    ("4.07", "Ethiopia below Egypt", "the Red Sea / Eritrea-Sudan coast"),
    ("4.08", "Interior Aethiopia", "Agisymba; the source's own section numbering quirk mislabels this content \"§4.9\" in topostext_209.csv - see parse_topostext.py"),
    ("5.01", "Pontos and Bithynia", ""),
    ("5.02", "Asia", "Asia proper, the Roman province - roughly western Anatolia"),
    ("5.03", "Lykia", ""),
    ("5.04", "Galatia", ""),
    ("5.05", "Pamphylia", ""),
    ("5.06", "Kappadokia", ""),
    ("5.07", "Lesser Armenia", "Armenia Minor"),
    ("5.08", "Kilikia", "Cilicia"),
    ("5.09", "Sarmatia in Asia", "Asiatic Sarmatia, north of the Kaukasos"),
    ("5.10", "Kolchis", "Colchis"),
    ("5.11", "Iberia", "Caucasian Iberia, modern-day Georgia - not the Hispanic Iberia of books 2/4"),
    ("5.12", "Albania", "Caucasian Albania, modern-day Azerbaijan/Dagestan"),
    ("5.13", "Greater Armenia", "Armenia Major"),
    ("5.14", "Cyprus", ""),
    ("5.15", "Syria", ""),
    ("5.16", "Ioudaia", "Palestine/Judaea"),
    ("5.17", "Arabia Petraia", ""),
    ("5.18", "Mesopotamia", ""),
    ("5.19", "Eremos Arabia", "Arabia Deserta"),
]


def load_rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def centroid(rows: list[dict]) -> tuple[float, float]:
    lons = [float(r["lon_ptolemy"]) for r in rows]
    lats = [float(r["lat_ptolemy"]) for r in rows]
    return sum(lons) / len(lons), sum(lats) / len(lats)


def blank_row(fieldnames: list[str]) -> dict:
    return {f: "" for f in fieldnames}


def main() -> int:
    fieldnames, rows = load_rows(CATALOGUE)
    if "label_note" not in fieldnames:
        fieldnames = fieldnames + ["label_note"]
    rows = [r for r in rows if r.get("category") != "label"]  # idempotent re-run

    point_rows = [r for r in rows if r.get("ref_id") and r.get("lon_ptolemy")]
    by_book_map: dict[str, list[dict]] = {}
    for r in point_rows:
        parts = r["ref_id"].split(".")
        if len(parts) < 3:
            continue
        by_book_map.setdefault(f"{parts[0]}.{parts[1]}", []).append(r)

    new_rows: list[dict] = []

    # 1. Province/region labels.
    missing_book_maps = []
    for book_map, name, note in _PROVINCE_LABELS:
        members = by_book_map.get(book_map, [])
        if not members:
            missing_book_maps.append(book_map)
            continue
        lon, lat = centroid(members)
        row = blank_row(fieldnames)
        row.update(
            ref_id=f"label.region.{book_map}",
            name=name,
            category="label",
            book=members[0].get("book", ""),
            tabula=members[0].get("tabula", ""),
            lon_ptolemy=lon,
            lat_ptolemy=lat,
            naming_observation=f"region label - centroid of {len(members)} points in book.map {book_map}, name verified against topostext's own opening sentence",
            label_note=note,
        )
        new_rows.append(row)
    if missing_book_maps:
        print(f"warning: no catalogue points found for province book.map(s) {missing_book_maps} - skipped")

    # 2. Named island-group labels (the confirmed one-island coastal walks).
    island_groups: dict[str, list[dict]] = {}
    for r in point_rows:
        fid = r.get("island_feature_id", "")
        if fid:
            island_groups.setdefault(fid, []).append(r)
    for fid, members in island_groups.items():
        name = fid.split("_", 2)[2] if fid.count("_") >= 2 else fid
        lon, lat = centroid(members)
        row = blank_row(fieldnames)
        row.update(
            ref_id=f"label.island.{fid}",
            name=name,
            category="label",
            book=members[0].get("book", ""),
            tabula=members[0].get("tabula", ""),
            lon_ptolemy=lon,
            lat_ptolemy=lat,
            naming_observation=f"island-group label - centroid of island outline {fid} ({len(members)} points), name from _ISLAND_LINE_GROUPS",
        )
        new_rows.append(row)

    # 3. Named mountain-range labels.
    mountain_groups: dict[str, list[dict]] = {}
    for r in point_rows:
        fid = r.get("mountain_feature_id", "")
        if fid:
            mountain_groups.setdefault(fid, []).append(r)
    for fid, members in mountain_groups.items():
        name = fid.split("_", 2)[2] if fid.count("_") >= 2 else fid
        lon, lat = centroid(members)
        row = blank_row(fieldnames)
        row.update(
            ref_id=f"label.mountain.{fid}",
            name=name,
            category="label",
            book=members[0].get("book", ""),
            tabula=members[0].get("tabula", ""),
            lon_ptolemy=lon,
            lat_ptolemy=lat,
            naming_observation=f"mountain-range label - centroid of mountain line {fid} ({len(members)} points)",
        )
        new_rows.append(row)

    all_rows = rows + new_rows
    with CATALOGUE.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"{len(all_rows)} total rows ({len(new_rows)} label rows: "
          f"{len(_PROVINCE_LABELS) - len(missing_book_maps)} regions, "
          f"{len(island_groups)} island groups, {len(mountain_groups)} mountain ranges) -> {CATALOGUE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
