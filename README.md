# MultiLayerTransform

MultiLayerTransform is a QGIS plugin for people who regularly edit features that are split across more than one layer.

Instead of switching the active layer over and over, you can work with visible layers as a group. The plugin gives you quick select, identify, box selection, move, rotate, scale, and four-point orthogonalize tools in one dock, with live preview before you commit the edit.

## Why it exists

QGIS is very strong for editing, but some day-to-day jobs become slower when the features you need are spread across several layers. This plugin was built to remove that friction:

- identify a feature without first making its layer active
- select from several visible layers in one pass
- move, rotate, or scale selected features together as one group
- keep the edit workflow inside QGIS instead of jumping between tools

## Main tools

- **Quick Select** picks the top visible feature under the cursor across target layers.
- **Identify** opens a popup-style results panel with feature attributes, derived values, and actions.
- **Select** supports click and drag-box selection across visible target layers.
- **Move**, **Rotate**, and **Scale** apply one grouped transform to selected features from different editable layers.
- **Orthogonalize 4 points** squares up four selected points into a clean rectangle preview before applying the result.

## Editing behavior

- visible target layers can be filtered from the dock
- hover tracing shows what feature is under the cursor before you click
- identify can use snapping to be more precise
- move, rotate, and scale support preview before apply
- rotation and scaling can use centroid or a picked pivot
- Ctrl can duplicate and transform instead of editing the original features
- edits are written through QGIS layer edit commands, so undo and redo stay clean

## Installation

Install from ZIP through `Plugins > Manage and Install Plugins... > Install from ZIP`, or copy the `MultiLayerTransform` folder into your QGIS profile plugin directory and restart QGIS.

Typical plugin locations:

- Windows: `%APPDATA%\\QGIS\\QGIS3\\profiles\\default\\python\\plugins\\`
- Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
- macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`

## Typical workflow

1. Open the plugin dock.
2. Check only the layers you want to target, if needed.
3. Use **Quick Select**, **Identify**, or **Select** to gather the features you want.
4. Put the relevant layers into edit mode.
5. Switch to **Move**, **Rotate**, **Scale**, or **Orthogonalize 4 points**.
6. Review the preview, then apply the result.

## Notes

- The best results come from working in a projected project CRS.
- Transform tools only use editable visible vector layers that currently have selected features.
- Raster layers, hidden layers, and non-editable layers are ignored.
- Cross-layer edits are grouped per layer for reliable QGIS undo and redo behavior.

## Project files

- `multilayer_transform.py` wires the plugin into QGIS and manages the main dock
- `transform_dialog.py` builds the dock controls
- `transform_map_tool.py` contains the cross-layer selection, identify, preview, and transform logic
- `identify_results_dialog.py` provides the identify results panel

## Current release

Version `0.8.3` focuses on the public release build and the full cross-layer toolset:

- Quick Select across visible layers
- snapping-aware Identify with attribute popup
- hover tracing during selection
- grouped Move, Rotate, and Scale across layers
- four-point Orthogonalize
