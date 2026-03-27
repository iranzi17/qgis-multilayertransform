# MultiLayerTransform

MultiLayerTransform is a QGIS 3.40+ Python plugin for quick-selecting, identifying, selecting, moving, rotating, and scaling features across multiple visible vector layers as grouped workflows.

## Architecture

The plugin is split into three main pieces:

- `multilayer_transform.py` registers the plugin, creates toolbar/menu actions, owns the dock widget, and connects UI events to the map tool.
- `transform_dialog.py` provides the main dock widget for mode selection, selection operation, target layer checklist, pivot behavior, angle snapping, preview color, manual angle/scale entry, and apply/cancel actions.
- `identify_results_dialog.py` provides the popup-style Identify Results dock with a feature/value tree similar to QGIS's standard identify panel.
- `transform_map_tool.py` implements the custom `QgsMapTool` that gathers eligible identify/selection targets, builds rubber-band previews in project coordinates, and commits undo-safe geometry edits back to each layer.

The map tool computes one transformation in project/map coordinates and applies that same transform to every selected feature across all eligible layers. For mixed-layer CRS projects, feature geometries are temporarily transformed into the project CRS, previewed/transformed there, and then transformed back into each source layer CRS before writing the edit.

## Features

- Quick Select the top visible feature across multiple visible vector layers without first making a layer active in the Layers panel.
- Identify visible features across multiple visible vector layers without first making a layer active in the Layers panel.
- Select features across multiple visible vector layers with click or drag-box workflows.
- Move selected features across multiple visible editable vector layers together.
- Rotate selected features across multiple visible editable vector layers together.
- Scale selected features across multiple visible editable vector layers together.
- Works with point, line, polygon, and multipart geometries.
- Uses a single group transform, preserving relative arrangement between all selected features.
- Supports centroid pivot and user-picked pivot for rotation and scaling.
- Supports manual angle preview and numeric X/Y scale preview from the dock.
- Shows live hover tracing in selection workflows so you can see the feature under the cursor before you click.
- Shows identify results in a popup-style dock, with attribute tree, highlight, zoom-to, and feature-form opening.
- Shows live rubber-band previews before commit.
- Uses layer edit commands so changes can be undone and redone.
- Warns when the project CRS is geographic.
- Optional filters and helpers:
  - checked target layers from the dock
  - pivot marker display
  - preview color customization
  - Shift to constrain rotation
  - Ctrl to duplicate and transform instead of editing originals

## Folder Structure

```text
MultiLayerTransform/
  __init__.py
  metadata.txt
  identify_results_dialog.py
  multilayer_transform.py
  transform_map_tool.py
  transform_dialog.py
  resources.qrc
  resources.py
  README.md
  icons/
    quick_select.svg
    identify.svg
    move.svg
    rotate.svg
    scale.svg
    orthogonalize.svg
    multilayer_transform.svg
```

## Installation

1. Close QGIS if you want to copy directly into a profile folder.
2. Copy the `MultiLayerTransform` folder into your QGIS profile plugin directory.
3. Start QGIS.
4. Open `Plugins > Manage and Install Plugins...`.
5. Enable `MultiLayerTransform`.

Typical plugin folder locations:

- Windows: `%APPDATA%\\QGIS\\QGIS3\\profiles\\default\\python\\plugins\\`
- Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
- macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`

## Zip And Install

To install as a zip package:

1. Make sure the zip contains the top-level folder `MultiLayerTransform`.
2. From the parent directory, create a zip of that folder.
3. In QGIS, open `Plugins > Manage and Install Plugins... > Install from ZIP`.
4. Pick the generated zip file and install it.

Example PowerShell command from the parent folder:

```powershell
Compress-Archive -Path .\MultiLayerTransform -DestinationPath .\MultiLayerTransform.zip -Force
```

## Usage

1. Open the plugin dock and optionally check only the target layers you want to use.
2. For **Quick Select**:
   - switch to **Quick Select** mode
   - click the top visible feature under the cursor
   - the tool selects it across layers without requiring an active layer
3. For **Identify**:
   - switch to **Identify** mode
   - click any visible feature
   - review the result list and double-click an item to open its feature form
4. For **Select**:
   - switch to **Select** mode
   - click-select or drag a rectangle across multiple layers
   - use Shift to add and Ctrl to remove, or change the default selection operation in the dock
5. Put the target vector layers into edit mode when you want to move, rotate, or scale them.
6. Switch to **Move**, **Rotate**, or **Scale** mode.
7. Use the dock to choose pivot behavior, snap angle, scale factors, and other options.
8. For move:
   - click a reference point
   - move the cursor
   - click again to apply
9. For rotate with centroid pivot:
   - click a reference direction from the pivot
   - move the cursor around the pivot
   - click again to apply
10. For rotate with picked pivot:
   - click the pivot point
   - click a reference direction
   - move the cursor and click again to apply
11. For scale with centroid pivot:
   - click a reference distance from the pivot
   - move the cursor closer/farther from the pivot
   - click again to apply a proportional group scale
12. For scale with picked pivot:
   - click the pivot point
   - click a reference distance
   - move the cursor and click again to apply
13. Use `Preview angle` for manual rotation preview or `Preview scale` for numeric X/Y scale preview, then `Apply`.
14. Press `Esc` or use `Cancel` to clear the current preview.
15. Use Ctrl on the final move/rotate/scale click if you want to duplicate and transform instead of changing the originals.

## Notes And Limitations

- Best accuracy is achieved in a projected project CRS. The plugin warns if the project CRS is geographic.
- Quick Select, Identify, and Select search visible target vector layers. Transform modes only include editable visible vector layers that currently have selected features.
- Raster layers, hidden layers, uneditable layers, and layers without selected features are ignored.
- Z and M values are preserved when supported by QGIS geometry and CRS transformation handling, but the transform logic is still driven by 2D map coordinates.
- Cross-layer edits are grouped as per-layer edit commands. This gives clean undo/redo behavior in QGIS, but it is not a provider-level database transaction across all layers.

## Future Improvements

- Optional non-destructive ghosting of original geometry during preview.
- Explicit selection handoff to duplicated features.
- Additional snapping presets and angle locking shortcuts.
- Persistent settings storage for dock options.
- Optional support for numeric move offsets entered directly in the dock.


## New in this build

- Added **Quick Select** mode for ArcGIS-Pro-style click selection of the top visible feature across layers without requiring an active layer.
- Quick Select honors the existing Replace/Add/Remove selection operation and modifier keys.
- Added **Identify** mode that searches all visible target layers, not just the layer currently active in the Layers panel.
- Identify results now open in a popup-style Identify Results dock and show full attribute rows in a Feature/Value tree.
- Direct drag-move in **Move** mode: click-drag from any currently selected feature to move the whole multi-layer selection together.
- Keep **Ctrl** pressed on release to duplicate while moving.
- The earlier two-click move workflow is still available when you start from an empty location.
- Added **Scale** mode with centroid or picked pivot, live preview, and numeric X/Y scale factors.
- Scale applies as one grouped transform across selected editable features from different visible vector layers.


## New in 0.5.0

- Added **Orthogonalize 4 points** mode.
- Works across multiple editable visible point layers.
- Select exactly four point features, switch to Orthogonalize, review the preview rectangle, then click **Apply**.
- Ctrl while applying duplicates the selected points to the orthogonalized corners instead of moving the originals.
