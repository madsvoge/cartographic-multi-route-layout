# Cartographic Multi-Route Layout

This repository contains a QGIS Python script for cartographic route layout and automatic lane generation.

## Contents

- `CartographicMultiRouteLayout_v8_1.py` - main QGIS processing engine and route layout implementation.
- `ptolemy_geographica/` - standalone script that extracts geographical references from Ptolemy's *Geographica* and plots them on an OpenStreetMap-based interactive map. See `ptolemy_geographica/README.md`.
- `LICENSE` - MIT license.
- `metadata.txt` - basic project metadata.

## Usage

1. Open QGIS.
2. Load the script in the Python console or configure it as a Processing algorithm.
3. Select one or more line route layers and run the tool.

## Notes

- The script is designed for meter-based project Coordinate Reference Systems.
- The project includes corridor detection, lane ordering, preferred-order orientation, and manual route materialization.
