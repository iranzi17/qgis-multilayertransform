# QGIS MultiLayerTransform

A QGIS plugin for selecting, identifying, and transforming features across multiple visible vector layers without constantly switching the active layer.

## Overview

MultiLayerTransform is built for GIS users who edit infrastructure, utility, cadastral, or engineering datasets where related features are spread across several layers. Instead of selecting and editing one active layer at a time, the plugin helps users work with visible target layers as a group.

The plugin provides quick selection, identify, box selection, move, rotate, scale, and four-point orthogonalization tools in one QGIS dock, with live preview before applying edits.

## Problem addressed

QGIS is powerful, but multi-layer editing can become slow when features that belong to the same real-world object are stored in separate layers. This is common in infrastructure and utility GIS, where poles, lines, structures, boundaries, and annotations may need to be adjusted together.

This plugin reduces that friction by supporting cross-layer selection and grouped transformation inside QGIS.

## Main tools

- **Quick Select** — selects the top visible feature under the cursor across target layers
- **Identify** — opens a result panel with attributes, derived values, and actions
- **Box Selection** — selects features from multiple visible target layers
- **Move** — moves selected features together across editable layers
- **Rotate** — rotates selected features using centroid or picked pivot options
- **Scale** — scales selected features with preview before applying edits
- **Orthogonalize 4 Points** — squares four selected points into a clean rectangular shape

## Editing behavior

- visible target layers can be filtered from the dock
- hover tracing shows the feature under the cursor before selection
- identify can use snapping for better precision
- move, rotate, and scale support live preview
- Ctrl can duplicate and transform instead of editing originals
- edits are written through QGIS edit commands so undo/redo behavior remains clean

## Typical workflow

1. Open the plugin dock.
2. Choose the visible target layers.
3. Use Quick Select, Identify, or Box Selection.
4. Put the relevant layers into edit mode.
5. Apply Move, Rotate, Scale, or Orthogonalize.
6. Review the preview and commit the edit.

## Installation

Install from ZIP through:

`Plugins > Manage and Install Plugins > Install from ZIP`

Or copy the `MultiLayerTransform` folder into your QGIS profile plugin directory and restart QGIS.

Typical plugin locations:

- Windows: `%APPDATA%\\QGIS\\QGIS3\\profiles\\default\\python\\plugins\\`
- Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
- macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`

## Project files

- `multilayer_transform.py` — QGIS plugin entry point and main dock management
- `transform_dialog.py` — dock controls and user interface
- `transform_map_tool.py` — cross-layer selection, identify, preview, and transformation logic
- `identify_results_dialog.py` — identify results panel

## Skills demonstrated

- QGIS plugin development
- PyQGIS scripting
- GIS editing workflow design
- multi-layer vector editing
- spatial-data automation
- infrastructure and utility GIS support

## Current release

Version `0.8.3` focuses on the public release build and the full cross-layer toolset:

- quick select across visible layers
- snapping-aware identify with attribute popup
- hover tracing during selection
- grouped move, rotate, and scale across layers
- four-point orthogonalization

## Professional relevance

This project demonstrates my ability to build GIS tools that improve real editing workflows for infrastructure and utility mapping teams using QGIS.
