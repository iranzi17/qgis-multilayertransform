import os
from dataclasses import dataclass, field
from itertools import permutations
from math import atan2, cos, degrees, hypot, sin
from typing import Dict, List, Optional, Tuple

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QCursor, QIcon, QTransform
from qgis.core import (
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsMapLayerType,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsHighlight, QgsMapTool, QgsRubberBand, QgsVertexMarker


@dataclass
class FeatureState:
    feature: QgsFeature
    layer_geometry: QgsGeometry
    project_geometry: QgsGeometry
    preview_band: Optional[QgsRubberBand] = None


@dataclass
class LayerState:
    layer: QgsVectorLayer
    to_project: QgsCoordinateTransform
    to_layer: QgsCoordinateTransform
    features: List[FeatureState] = field(default_factory=list)


class TransformMapTool(QgsMapTool):
    stateChanged = pyqtSignal(object)
    identifyResultsChanged = pyqtSignal(object)
    warningRaised = pyqtSignal(str)
    statusMessage = pyqtSignal(str)

    def __init__(self, iface):
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.project = QgsProject.instance()

        self.mode = "move"
        self.pivot_mode = "centroid"
        self.snap_angle = 0.0
        self.only_selected_layers = False
        self.target_layer_ids = set()
        self.selection_operation = "replace"
        self.show_pivot_marker = True
        self.preview_color = QColor("#ff7f0e")

        self._layers: List[LayerState] = []
        self._layer_count = 0
        self._feature_count = 0
        self._combined_centroid: Optional[QgsPointXY] = None
        self._pivot_point: Optional[QgsPointXY] = None
        self._move_reference_point: Optional[QgsPointXY] = None
        self._rotation_reference_point: Optional[QgsPointXY] = None
        self._scale_reference_point: Optional[QgsPointXY] = None
        self._interaction_state = "idle"
        self._current_transform = None
        self._pivot_marker: Optional[QgsVertexMarker] = None
        self._selection_band: Optional[QgsRubberBand] = None
        self._selection_hover_target: Optional[Tuple[str, int]] = None
        self._selection_hover_highlight: Optional[QgsHighlight] = None
        self._selection_start_point: Optional[QgsPointXY] = None
        self._drag_move_start_point: Optional[QgsPointXY] = None
        self._orthogonalize_band: Optional[QgsRubberBand] = None
        self._identify_results = []
        self._identify_current_result: Optional[Tuple[str, int]] = None
        self._identify_highlight: Optional[QgsHighlight] = None

    def activate(self):
        super().activate()
        self.update_cursor()
        if self.mode == "select":
            self.refresh_selection_summary()
        elif self.mode == "quick_select":
            self.refresh_quick_select_state()
        elif self.mode == "identify":
            self.refresh_identify_state(clear_results=False)

    def deactivate(self):
        self.clear_preview()
        self._remove_pivot_marker()
        self._hide_selection_band()
        self._clear_selection_hover_highlight()
        self._hide_orthogonalize_band()
        self._clear_identify_highlight()
        super().deactivate()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.mode == "identify":
                self.open_identify_result()
                return
            self.apply_current_operation()
            return
        if event.key() == Qt.Key_Escape:
            self.cancel_current_operation()
            return
        super().keyPressEvent(event)

    def canvasPressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.cancel_current_operation()
            return
        if event.button() != Qt.LeftButton:
            return

        if self.mode == "select":
            self._selection_start_point = QgsPointXY(event.mapPoint())
            self._clear_selection_hover_highlight()
            self._show_selection_band(self._selection_start_point, self._selection_start_point)
            return

        if self.mode == "quick_select":
            self._perform_quick_select(QgsPointXY(event.mapPoint()), event.modifiers())
            return

        if self.mode == "identify":
            point, snap_match = self._resolve_event_point(event, use_snapping=True)
            self._perform_identify(point, snap_match=snap_match)
            return

        if self.mode == "orthogonalize":
            self._ensure_selection_ready()
            return

        if not self._ensure_selection_ready():
            return

        point = event.mapPoint()
        if self.mode == "move":
            self._handle_move_click(point, event.modifiers())
        elif self.mode == "rotate":
            self._handle_rotate_click(point, event.modifiers())
        elif self.mode == "scale":
            self._handle_scale_click(point, event.modifiers())

    def canvasMoveEvent(self, event):
        point = event.mapPoint()
        if self.mode in {"select", "quick_select"}:
            if self._selection_start_point is not None:
                self._clear_selection_hover_highlight()
                self._show_selection_band(self._selection_start_point, point)
            else:
                self._update_selection_hover(point)
            return

        if not self._layers:
            return

        if self.mode == "move" and self._interaction_state in {"await_move_target", "drag_move_active"}:
            self._update_move_preview(point)
            return

        if self.mode == "rotate" and self._interaction_state == "await_rotate_target":
            self._update_rotate_preview(point, event.modifiers())
            return

        if self.mode == "scale" and self._interaction_state == "await_scale_target":
            self._update_scale_preview(point)

    def canvasReleaseEvent(self, event):
        if self.mode == "move" and event.button() == Qt.LeftButton and self._interaction_state == "drag_move_active":
            end_point = QgsPointXY(event.mapPoint())
            start_point = QgsPointXY(self._drag_move_start_point) if self._drag_move_start_point else None
            self._drag_move_start_point = None
            if start_point is None or self._is_same_point(start_point, end_point):
                self.clear_preview()
                self._current_transform = None
                self._interaction_state = "await_move_origin"
                self._emit_state(
                    info_override=(
                        f"{self._layer_count} layers, {self._feature_count} features. "
                        "Drag directly from any selected feature to move the whole group, or click a reference point to use two-click move."
                    )
                )
                return
            self._update_move_preview(end_point)
            self.apply_current_operation(duplicate=bool(event.modifiers() & Qt.ControlModifier))
            return

        if self.mode != "select" or event.button() != Qt.LeftButton or self._selection_start_point is None:
            return

        end_point = QgsPointXY(event.mapPoint())
        start_point = QgsPointXY(self._selection_start_point)
        self._selection_start_point = None
        self._hide_selection_band()
        self._perform_selection(start_point, end_point, event.modifiers())
        self._update_selection_hover(end_point)

    def set_pivot_mode(self, pivot_mode):
        if pivot_mode in {"centroid", "pick"}:
            self.pivot_mode = pivot_mode
            if self.mode in {"rotate", "scale"}:
                self.refresh_selection()

    def set_snap_angle(self, snap_angle):
        self.snap_angle = float(snap_angle)
        if self._current_transform and self._current_transform.get("type") == "rotate":
            self._update_preview_bands()
            self._emit_state()

    def set_only_selected_layers(self, enabled):
        self.only_selected_layers = bool(enabled)
        if self.mode == "select":
            self.refresh_selection_summary()
        elif self.mode == "quick_select":
            self.refresh_quick_select_state()
        elif self.mode == "identify":
            self.refresh_identify_state(clear_results=True)
        else:
            self.refresh_selection()

    def set_target_layer_ids(self, layer_ids):
        self.target_layer_ids = set(layer_ids or [])
        if self.mode == "select":
            self.refresh_selection_summary()
        elif self.mode == "quick_select":
            self.refresh_quick_select_state()
        elif self.mode == "identify":
            self.refresh_identify_state(clear_results=True)
        else:
            self.refresh_selection()

    def set_selection_operation(self, operation):
        if operation in {"replace", "add", "remove"}:
            self.selection_operation = operation
            if self.mode == "select":
                self.refresh_selection_summary()
            elif self.mode == "quick_select":
                self.refresh_quick_select_state()

    def set_show_pivot_marker(self, enabled):
        self.show_pivot_marker = bool(enabled)
        self._update_pivot_marker()

    def set_preview_color(self, color):
        self.preview_color = QColor(color)
        self._update_preview_style()
        self._update_pivot_marker()
        self._update_selection_band_style()
        self._update_selection_hover_highlight_style()
        self._update_orthogonalize_band_style()
        self._update_identify_highlight_style()

    def has_preview(self):
        return self._current_transform is not None

    def update_cursor(self):
        self.canvas.setCursor(self._cursor_for_mode())

    def cleanup(self):
        self.dispose_preview_bands()
        self._remove_pivot_marker()
        self._hide_selection_band()
        self._clear_selection_hover_highlight()
        self._hide_orthogonalize_band()
        self._clear_identify_highlight()

    def refresh_selection_summary(self):
        self._clear_identify_session(emit_results=True, emit_state=False)
        self._layers = []
        self._selection_start_point = None
        self._hide_selection_band()
        self._clear_selection_hover_highlight()
        count_layers, count_features = self._current_selection_counts(include_only_editable=False)
        self._layer_count = count_layers
        self._feature_count = count_features
        self._emit_state(
            info_override=(
                f"Selection mode ({self.selection_operation} by default): click to select one feature; drag a box to select many. "
                "Shift adds, Ctrl removes, and plain click follows the current selection operation."
            )
        )

    def refresh_quick_select_state(self):
        self._clear_identify_session(emit_results=True, emit_state=False)
        self._layers = []
        self._selection_start_point = None
        self._hide_selection_band()
        self._clear_selection_hover_highlight()
        count_layers, count_features = self._current_selection_counts(include_only_editable=False)
        self._layer_count = count_layers
        self._feature_count = count_features
        self._interaction_state = "await_quick_select_click"
        self._emit_state(
            info_override=(
                f"Quick Select mode ({self.selection_operation} by default): click the top visible feature to select it across layers without changing the active layer. "
                "Shift adds, Ctrl removes."
            )
        )

    def refresh_identify_state(self, clear_results=True):
        self.dispose_preview_bands()
        self._remove_pivot_marker()
        self._hide_selection_band()
        self._clear_selection_hover_highlight()
        self._hide_orthogonalize_band()
        self._layers = []
        self._move_reference_point = None
        self._rotation_reference_point = None
        self._scale_reference_point = None
        self._current_transform = None
        self._pivot_point = None
        self._interaction_state = "await_identify_click"
        self._layer_count = len(self._eligible_vector_layers(require_editable=False))

        if clear_results:
            self._clear_identify_session(emit_results=True, emit_state=False)
        else:
            self._feature_count = len(self._identify_results)
            self._update_identify_highlight_from_current()

        if self._layer_count == 0:
            self._clear_identify_session(emit_results=True, emit_state=False)
            self._interaction_state = "idle"
            self._emit_state(info_override="Identify mode: no visible target vector layers are available.")
            return

        self._emit_state(
            info_override=(
                f"Identify mode is ready on {self._layer_count} visible target layer(s). "
                "Click any feature to identify it across layers without changing the active layer."
            )
        )

    def clear_current_selection(self):
        for layer in self._eligible_vector_layers(require_editable=False):
            if layer.selectedFeatureCount() > 0:
                layer.removeSelection()
        self._layers = []
        self._layer_count = 0
        self._feature_count = 0
        self.cancel_current_operation()
        self.refresh_selection_summary()
        self.statusMessage.emit("Cleared multi-layer selection.")

    def refresh_selection(self):
        self._clear_identify_session(emit_results=True, emit_state=False)
        self.dispose_preview_bands()
        self._remove_pivot_marker()
        self._clear_selection_hover_highlight()
        self._hide_orthogonalize_band()
        self._move_reference_point = None
        self._rotation_reference_point = None
        self._scale_reference_point = None
        self._current_transform = None
        self._pivot_point = None

        point_only = self.mode == "orthogonalize"
        self._layers, warnings = self._collect_selection(require_points_only=point_only)
        self._layer_count = len(self._layers)
        self._feature_count = sum(len(layer_state.features) for layer_state in self._layers)

        if self.project.crs().isGeographic():
            warnings.insert(0, "Project CRS is geographic. MultiLayerTransform works best in a projected CRS for precise geometry editing.")

        if not self._layers:
            self._interaction_state = "idle"
            self._emit_state()
            for warning in warnings:
                self.warningRaised.emit(warning)
            return

        self._combined_centroid = self._compute_group_centroid()
        self._create_preview_bands()

        if self.mode == "move":
            self._interaction_state = "await_move_origin"
            info = (
                f"{self._layer_count} layers, {self._feature_count} features. "
                "Drag directly from any selected feature to move the whole group, or click a reference point then click again to apply. "
                "Hold Ctrl on release/final click to duplicate instead of moving the originals."
            )
        elif self.mode == "rotate":
            if self.pivot_mode == "centroid":
                self._pivot_point = self._combined_centroid
                self._interaction_state = "await_rotate_reference"
                info = (
                    f"{self._layer_count} layers, {self._feature_count} features. "
                    "Using the combined selection centroid as pivot. Click a reference direction, then click a target direction. "
                    "Hold Shift to constrain rotation; Ctrl duplicates on apply."
                )
            else:
                self._interaction_state = "await_rotate_pivot"
                info = (
                    f"{self._layer_count} layers, {self._feature_count} features. "
                    "Click a pivot point, then click a reference direction, then click a target direction."
                )
        elif self.mode == "scale":
            if self.pivot_mode == "centroid":
                self._pivot_point = self._combined_centroid
                self._interaction_state = "await_scale_reference"
                info = (
                    f"{self._layer_count} layers, {self._feature_count} features. "
                    "Using the combined selection centroid as pivot. Click a reference distance, then click a target distance to preview/apply scale. "
                    "Use Preview scale in the dock for numeric X/Y factors; Ctrl duplicates on apply."
                )
            else:
                self._interaction_state = "await_scale_pivot"
                info = (
                    f"{self._layer_count} layers, {self._feature_count} features. "
                    "Click a pivot point, then click a reference distance, then click a target distance."
                )
        else:
            if not self._prepare_orthogonalize_preview(warnings):
                self._interaction_state = "idle"
                self._emit_state()
                for warning in warnings:
                    self.warningRaised.emit(warning)
                return
            self._interaction_state = "preview_ready"
            info = (
                f"Orthogonalize preview ready for {self._feature_count} selected point(s) across {self._layer_count} layer(s). "
                "Apply to square the four selected points into a best-fit rectangle. Ctrl duplicates to new corners instead of moving originals."
            )

        self._update_pivot_marker()
        self._emit_state(info_override=info)
        for warning in warnings:
            self.warningRaised.emit(warning)

    def cancel_current_operation(self):
        if self.mode == "quick_select":
            self.refresh_quick_select_state()
            return
        if self.mode == "identify":
            self.clear_identify_results()
            self.refresh_identify_state(clear_results=False)
            return

        self.clear_preview()
        self._current_transform = None
        self._move_reference_point = None
        self._rotation_reference_point = None
        self._scale_reference_point = None
        self._hide_selection_band()
        self._clear_selection_hover_highlight()
        self._selection_start_point = None
        self._hide_orthogonalize_band()

        if self.mode == "select":
            self._interaction_state = "idle"
            self.refresh_selection_summary()
            return
        if not self._layers:
            self._interaction_state = "idle"
            self._emit_state()
            return
        if self.mode == "move":
            self._interaction_state = "await_move_origin"
            self._emit_state(info_override=(f"{self._layer_count} layers, {self._feature_count} features. Drag directly from any selected feature, or click a reference point to start a move preview."))
            return
        if self.mode == "rotate":
            if self.pivot_mode == "centroid":
                self._pivot_point = self._combined_centroid
                self._interaction_state = "await_rotate_reference"
                self._update_pivot_marker()
                self._emit_state(info_override=(f"{self._layer_count} layers, {self._feature_count} features. Centroid pivot ready. Click a reference direction or preview a manual angle."))
            else:
                self._pivot_point = None
                self._interaction_state = "await_rotate_pivot"
                self._emit_state(info_override=(f"{self._layer_count} layers, {self._feature_count} features. Click a pivot point to begin rotation."))
            return
        if self.mode == "scale":
            if self.pivot_mode == "centroid":
                self._pivot_point = self._combined_centroid
                self._interaction_state = "await_scale_reference"
                self._update_pivot_marker()
                self._emit_state(info_override=(f"{self._layer_count} layers, {self._feature_count} features. Centroid pivot ready. Click a reference distance or preview numeric scale factors."))
            else:
                self._pivot_point = None
                self._interaction_state = "await_scale_pivot"
                self._emit_state(info_override=(f"{self._layer_count} layers, {self._feature_count} features. Click a pivot point to begin scaling."))
            return
        # orthogonalize
        if self.mode == "orthogonalize":
            self.refresh_selection()

    def clear_identify_results(self):
        self._clear_identify_session(emit_results=True, emit_state=False)
        self._feature_count = 0
        if self.mode == "identify":
            self._interaction_state = "await_identify_click" if self._layer_count else "idle"
            self._emit_state(
                info_override=(
                    "Identify results cleared. Click any feature to search visible target layers without changing the active layer."
                )
            )
        self.statusMessage.emit("Cleared identify results.")

    def preview_manual_rotation(self, angle_degrees):
        if self.mode != "rotate":
            self.warningRaised.emit("Manual angle preview is only available in Rotate mode.")
            return False
        if not self._ensure_selection_ready():
            return False
        if self.pivot_mode == "pick" and self._pivot_point is None:
            self.warningRaised.emit("Pick a pivot point on the canvas before previewing a manual rotation.")
            return False
        if self._pivot_point is None:
            self._pivot_point = self._combined_centroid
        self._current_transform = {"type": "rotate", "pivot": QgsPointXY(self._pivot_point), "angle": float(angle_degrees)}
        self._update_pivot_marker()
        self._update_preview_bands()
        self._emit_state()
        return True

    def preview_manual_scale(self, scale_x, scale_y):
        if self.mode != "scale":
            self.warningRaised.emit("Manual scale preview is only available in Scale mode.")
            return False
        if not self._ensure_selection_ready():
            return False
        if self.pivot_mode == "pick" and self._pivot_point is None:
            self.warningRaised.emit("Pick a pivot point on the canvas before previewing a manual scale.")
            return False
        if self._pivot_point is None:
            self._pivot_point = self._combined_centroid
        self._current_transform = {
            "type": "scale",
            "pivot": QgsPointXY(self._pivot_point),
            "scale_x": float(scale_x),
            "scale_y": float(scale_y),
        }
        self._update_pivot_marker()
        self._update_preview_bands()
        self._emit_state()
        return True

    def select_identify_result(self, layer_id, feature_id):
        if layer_id is None or feature_id is None:
            return False
        self._identify_current_result = (str(layer_id), int(feature_id))
        return self._update_identify_highlight_from_current()

    def open_identify_result(self, layer_id=None, feature_id=None):
        target = self._resolve_identify_target(layer_id, feature_id)
        if target is None:
            self.warningRaised.emit("No identify result is selected.")
            return False
        layer, feature = self._resolve_feature(target[0], target[1])
        if layer is None or feature is None:
            self.warningRaised.emit("The selected identify result is no longer available.")
            return False
        try:
            self.iface.openFeatureForm(layer, feature)
        except Exception as exc:
            self.warningRaised.emit(f"Unable to open the feature form: {exc}")
            return False
        self.select_identify_result(target[0], target[1])
        self.statusMessage.emit(f"Opened feature form for {layer.name()} | feature {feature.id()}.")
        return True

    def zoom_to_identify_result(self, layer_id=None, feature_id=None):
        target = self._resolve_identify_target(layer_id, feature_id)
        if target is None:
            self.warningRaised.emit("No identify result is selected.")
            return False
        layer, feature = self._resolve_feature(target[0], target[1])
        if layer is None or feature is None:
            self.warningRaised.emit("The selected identify result is no longer available.")
            return False
        try:
            project_geometry = QgsGeometry(feature.geometry())
            project_geometry.transform(QgsCoordinateTransform(layer.crs(), self.project.crs(), self.project))
            rect = project_geometry.boundingBox()
            if rect.isEmpty() or rect.width() <= 1e-9 or rect.height() <= 1e-9:
                center = rect.center() if not rect.isNull() else QgsPointXY(0.0, 0.0)
                padding = max(self.canvas.mapUnitsPerPixel() * 40.0, 1.0)
                rect = QgsRectangle(center.x() - padding, center.y() - padding, center.x() + padding, center.y() + padding)
            else:
                rect.grow(max(self.canvas.mapUnitsPerPixel() * 20.0, 1.0))
            self.canvas.setExtent(rect)
            self.canvas.refresh()
        except Exception as exc:
            self.warningRaised.emit(f"Unable to zoom to the feature: {exc}")
            return False
        self.select_identify_result(target[0], target[1])
        self.statusMessage.emit(f"Zoomed to {layer.name()} | feature {feature.id()}.")
        return True

    def apply_current_operation(self, duplicate=None):
        if self.mode == "select":
            self.statusMessage.emit("Selection mode does not apply geometry changes.")
            return True
        if self.mode == "identify":
            return self.open_identify_result()
        if not self._current_transform:
            self.warningRaised.emit("Create a preview before applying the transformation.")
            return False

        duplicate = bool(duplicate) if duplicate is not None else False
        transform_type = self._current_transform["type"]
        layer_commands = []
        command_label = self._command_label(transform_type, duplicate)

        try:
            for layer_state in self._layers:
                layer_state.layer.beginEditCommand(command_label)
                layer_commands.append(layer_state.layer)

            for layer_state in self._layers:
                for feature_state in layer_state.features:
                    transformed_geometry = self._build_layer_geometry(layer_state, feature_state)
                    if duplicate:
                        duplicate_feature = QgsFeature(feature_state.feature)
                        duplicate_feature.setGeometry(transformed_geometry)
                        if not layer_state.layer.addFeature(duplicate_feature):
                            raise RuntimeError(f"Unable to add duplicate feature on layer '{layer_state.layer.name()}'.")
                    else:
                        if not layer_state.layer.changeGeometry(feature_state.feature.id(), transformed_geometry):
                            raise RuntimeError(f"Unable to change feature {feature_state.feature.id()} on layer '{layer_state.layer.name()}'.")

            for layer in layer_commands:
                layer.endEditCommand()
        except Exception as exc:
            for layer in reversed(layer_commands):
                try:
                    layer.destroyEditCommand()
                except Exception:
                    pass
            self.warningRaised.emit(f"Transformation failed: {exc}")
            return False

        self.statusMessage.emit(self._success_message(transform_type, duplicate))
        self.refresh_selection()
        return True

    def clear_preview(self):
        for layer_state in self._layers:
            for feature_state in layer_state.features:
                if feature_state.preview_band is not None:
                    feature_state.preview_band.hide()
        self._hide_orthogonalize_band()

    def dispose_preview_bands(self):
        for layer_state in self._layers:
            for feature_state in layer_state.features:
                if feature_state.preview_band is None:
                    continue
                try:
                    feature_state.preview_band.hide()
                    self.canvas.scene().removeItem(feature_state.preview_band)
                except Exception:
                    pass
                feature_state.preview_band = None
        self._hide_orthogonalize_band()

    def _handle_move_click(self, point, modifiers):
        if self._interaction_state == "await_move_origin":
            if self._point_hits_selected_feature(point):
                self._drag_move_start_point = QgsPointXY(point)
                self._move_reference_point = QgsPointXY(point)
                self._interaction_state = "drag_move_active"
                self._emit_state(info_override=(f"{self._layer_count} layers, {self._feature_count} features. Direct drag move active. Drag the selected group and release to apply. Hold Ctrl while releasing to duplicate."))
                return
            self._move_reference_point = QgsPointXY(point)
            self._interaction_state = "await_move_target"
            self._emit_state(info_override=(f"{self._layer_count} layers, {self._feature_count} features. Move preview active. Move the cursor and click to confirm the destination."))
            return
        if self._interaction_state == "await_move_target":
            self._update_move_preview(point)
            self.apply_current_operation(duplicate=bool(modifiers & Qt.ControlModifier))

    def _handle_rotate_click(self, point, modifiers):
        if self._interaction_state == "await_rotate_pivot":
            self._pivot_point = QgsPointXY(point)
            self._interaction_state = "await_rotate_reference"
            self._update_pivot_marker()
            self._emit_state(info_override=(f"{self._layer_count} layers, {self._feature_count} features. Pivot fixed. Click a reference direction from the pivot."))
            return
        if self._interaction_state == "await_rotate_reference":
            if not self._pivot_point:
                return
            if self._is_same_point(self._pivot_point, point):
                self.warningRaised.emit("Reference direction must be away from the pivot point.")
                return
            self._rotation_reference_point = QgsPointXY(point)
            self._interaction_state = "await_rotate_target"
            self._emit_state(info_override=(f"{self._layer_count} layers, {self._feature_count} features. Move the cursor around the pivot to preview the angle, then click to apply."))
            return
        if self._interaction_state == "await_rotate_target":
            self._update_rotate_preview(point, modifiers)
            self.apply_current_operation(duplicate=bool(modifiers & Qt.ControlModifier))

    def _handle_scale_click(self, point, modifiers):
        if self._interaction_state == "await_scale_pivot":
            self._pivot_point = QgsPointXY(point)
            self._interaction_state = "await_scale_reference"
            self._update_pivot_marker()
            self._emit_state(info_override=(f"{self._layer_count} layers, {self._feature_count} features. Pivot fixed. Click a reference distance from the pivot."))
            return
        if self._interaction_state == "await_scale_reference":
            if not self._pivot_point:
                return
            if self._is_same_point(self._pivot_point, point):
                self.warningRaised.emit("Reference distance must be away from the pivot point.")
                return
            self._scale_reference_point = QgsPointXY(point)
            self._interaction_state = "await_scale_target"
            self._emit_state(info_override=(f"{self._layer_count} layers, {self._feature_count} features. Move the cursor to preview the scale, then click to apply."))
            return
        if self._interaction_state == "await_scale_target":
            self._update_scale_preview(point)
            self.apply_current_operation(duplicate=bool(modifiers & Qt.ControlModifier))

    def _update_move_preview(self, point):
        if not self._move_reference_point:
            return
        dx = point.x() - self._move_reference_point.x()
        dy = point.y() - self._move_reference_point.y()
        self._current_transform = {"type": "move", "dx": dx, "dy": dy}
        self._update_preview_bands()
        self._emit_state()

    def _update_rotate_preview(self, point, modifiers):
        if not self._pivot_point or not self._rotation_reference_point or self._is_same_point(self._pivot_point, point):
            return
        start_angle_ccw = degrees(atan2(self._rotation_reference_point.y() - self._pivot_point.y(), self._rotation_reference_point.x() - self._pivot_point.x()))
        current_angle_ccw = degrees(atan2(point.y() - self._pivot_point.y(), point.x() - self._pivot_point.x()))
        angle_clockwise = self._normalize_angle(start_angle_ccw - current_angle_ccw)
        snap_step = self.snap_angle
        if modifiers & Qt.ShiftModifier:
            snap_step = snap_step or 15.0
        if snap_step:
            angle_clockwise = self._snap_angle_value(angle_clockwise, snap_step)
        self._current_transform = {"type": "rotate", "pivot": QgsPointXY(self._pivot_point), "angle": angle_clockwise}
        self._update_preview_bands()
        self._emit_state()

    def _update_scale_preview(self, point):
        if not self._pivot_point or not self._scale_reference_point:
            return
        reference_dx = self._scale_reference_point.x() - self._pivot_point.x()
        reference_dy = self._scale_reference_point.y() - self._pivot_point.y()
        reference_distance = hypot(reference_dx, reference_dy)
        if reference_distance <= max(self.canvas.mapUnitsPerPixel(), 1e-9):
            return

        target_dx = point.x() - self._pivot_point.x()
        target_dy = point.y() - self._pivot_point.y()
        target_distance = hypot(target_dx, target_dy)
        scale_factor = target_distance / reference_distance

        self._current_transform = {
            "type": "scale",
            "pivot": QgsPointXY(self._pivot_point),
            "scale_x": scale_factor,
            "scale_y": scale_factor,
        }
        self._update_preview_bands()
        self._emit_state()

    def _perform_selection(self, start_point, end_point, modifiers):
        operation = self.selection_operation
        if modifiers & Qt.ShiftModifier:
            operation = "add"
        elif modifiers & Qt.ControlModifier:
            operation = "remove"

        layers = self._eligible_vector_layers(require_editable=False)
        if not layers:
            self.warningRaised.emit("No eligible visible vector layers were found for selection.")
            self.refresh_selection_summary()
            return

        rect = QgsRectangle(start_point, end_point)
        is_click = rect.width() <= self.canvas.mapUnitsPerPixel() * 2 and rect.height() <= self.canvas.mapUnitsPerPixel() * 2
        if is_click:
            tol = self.canvas.mapUnitsPerPixel() * 6
            rect = QgsRectangle(start_point.x() - tol, start_point.y() - tol, start_point.x() + tol, start_point.y() + tol)

        changed_layers = 0
        for layer in layers:
            layer_rect = self.canvas.mapSettings().mapToLayerCoordinates(layer, rect)
            request = QgsFeatureRequest().setFilterRect(layer_rect)
            ids_set = {feature.id() for feature in layer.getFeatures(request)}
            existing = set(layer.selectedFeatureIds())
            if operation == "replace":
                new_ids = ids_set
            elif operation == "add":
                new_ids = existing | ids_set
            else:
                new_ids = existing - ids_set
            if new_ids != existing:
                layer.selectByIds(list(new_ids))
                changed_layers += 1

        self.refresh_selection_summary()
        self.statusMessage.emit(f"Selection updated on {changed_layers} layer(s). Current selection: {self._feature_count} feature(s) across {self._layer_count} layer(s).")

    def _perform_quick_select(self, point, modifiers):
        operation = self.selection_operation
        if modifiers & Qt.ShiftModifier:
            operation = "add"
        elif modifiers & Qt.ControlModifier:
            operation = "remove"

        layers = self._eligible_vector_layers(require_editable=False)
        if not layers:
            self.warningRaised.emit("No eligible visible vector layers were found for quick select.")
            self.refresh_quick_select_state()
            return

        hit_layer, hit_feature = self._find_top_feature_at_point(point, require_editable=False)
        changed_layers = 0

        if hit_layer is None or hit_feature is None:
            if operation == "replace":
                for layer in layers:
                    if layer.selectedFeatureCount() > 0:
                        layer.removeSelection()
                        changed_layers += 1
                self.statusMessage.emit("Quick Select cleared the current selection.")
            else:
                self.statusMessage.emit("Quick Select found no feature under the cursor.")
            self.refresh_quick_select_state()
            self._clear_selection_hover_highlight()
            return

        hit_id = int(hit_feature.id())
        for layer in layers:
            existing = set(layer.selectedFeatureIds())
            if layer.id() == hit_layer.id():
                feature_ids = {hit_id}
                if operation == "replace":
                    new_ids = feature_ids
                elif operation == "add":
                    new_ids = existing | feature_ids
                else:
                    new_ids = existing - feature_ids
            elif operation == "replace":
                new_ids = set()
            else:
                new_ids = existing
            if new_ids != existing:
                layer.selectByIds(list(new_ids))
                changed_layers += 1

        self.refresh_quick_select_state()
        self._update_selection_hover(point)
        action_text = "removed from" if operation == "remove" else "selected on"
        self.statusMessage.emit(
            f"Quick Select {action_text} {hit_layer.name()} | feature {hit_id}. Changed {changed_layers} layer(s)."
        )

    def _update_selection_hover(self, point):
        layer, feature = self._find_top_feature_at_point(point, require_editable=False)
        if layer is None or feature is None:
            self._clear_selection_hover_highlight()
            return False

        target = (str(layer.id()), int(feature.id()))
        if self._selection_hover_target == target and self._selection_hover_highlight is not None:
            return True

        self._selection_hover_target = target
        self._show_selection_hover_highlight(layer, feature)
        return True

    def _perform_identify(self, point, snap_match=None):
        layers = self._eligible_vector_layers(require_editable=False)
        self._layer_count = len(layers)
        if not layers:
            self._interaction_state = "idle"
            self._clear_identify_session(emit_results=True, emit_state=False)
            self._emit_state(info_override="Identify mode: no visible target vector layers are available.")
            self.warningRaised.emit("No visible target vector layers are available for identify.")
            return

        snapped_layer, snapped_feature_id = self._extract_snapped_target(snap_match)
        point_geometry = QgsGeometry.fromPointXY(point)
        tolerance = max(self.canvas.mapUnitsPerPixel() * 6.0, 1e-9)
        search_rect = QgsRectangle(point.x() - tolerance, point.y() - tolerance, point.x() + tolerance, point.y() + tolerance)
        skipped_layers = []
        results = []

        for layer in layers:
            if snapped_layer is not None and layer.id() != snapped_layer.id():
                continue
            try:
                to_project = QgsCoordinateTransform(layer.crs(), self.project.crs(), self.project)
                layer_rect = self.canvas.mapSettings().mapToLayerCoordinates(layer, search_rect)
                request = QgsFeatureRequest().setFilterRect(layer_rect)
                for feature in layer.getFeatures(request):
                    if snapped_feature_id is not None and int(feature.id()) != snapped_feature_id:
                        continue
                    geometry = feature.geometry()
                    if geometry is None or geometry.isEmpty():
                        continue
                    project_geometry = QgsGeometry(geometry)
                    project_geometry.transform(to_project)
                    bbox = project_geometry.boundingBox()
                    bbox.grow(tolerance)
                    if not bbox.contains(point):
                        continue
                    try:
                        distance = project_geometry.distance(point_geometry)
                    except Exception:
                        continue
                    if distance > tolerance:
                        continue
                    results.append(
                        {
                            "layer_id": layer.id(),
                            "feature_id": int(feature.id()),
                            "layer_name": layer.name(),
                            "display": self._identify_display_value(layer, feature),
                            "distance": float(distance),
                        }
                    )
            except Exception:
                skipped_layers.append(layer.name())

        results.sort(key=lambda item: (item["distance"], item["layer_name"].lower(), item["feature_id"]))
        self._interaction_state = "await_identify_click"
        self._layer_count = len(layers)
        self._set_identify_results(results)

        if results:
            self.statusMessage.emit(
                f"Identified {len(results)} feature(s) across {self._layer_count} visible target layer(s)."
            )
        else:
            self.statusMessage.emit(f"No features were found at the clicked location across {self._layer_count} visible target layer(s).")

        info = (
            f"Identify returned {len(results)} feature(s) from {self._layer_count} visible target layer(s). "
            "Use the results list to highlight, zoom to, or open the feature form."
        )
        if snapped_layer is not None:
            info += f" Snapping constrained the identify click to layer '{snapped_layer.name()}'."
        if skipped_layers:
            info += " Skipped layer(s) that could not be transformed: " + ", ".join(skipped_layers)
        self._emit_state(info_override=info)
        if skipped_layers:
            self.warningRaised.emit("Skipped layer(s) that could not be transformed for identify: " + ", ".join(skipped_layers))

    def _ensure_selection_ready(self):
        if self._layers:
            return True
        self.refresh_selection()
        return bool(self._layers)

    def _eligible_vector_layers(self, require_editable):
        result = []
        for node in self.project.layerTreeRoot().findLayers():
            layer = node.layer()
            if layer is None or layer.type() != QgsMapLayerType.VectorLayer:
                continue
            if self.only_selected_layers and self.target_layer_ids and layer.id() not in self.target_layer_ids:
                continue
            if self.only_selected_layers and not self.target_layer_ids:
                continue
            if not node.isVisible():
                continue
            if require_editable and not layer.isEditable():
                continue
            result.append(layer)
        return result

    def _find_top_feature_at_point(self, point, require_editable):
        point_geometry = QgsGeometry.fromPointXY(point)
        tolerance = max(self.canvas.mapUnitsPerPixel() * 6.0, 1e-9)
        search_rect = QgsRectangle(point.x() - tolerance, point.y() - tolerance, point.x() + tolerance, point.y() + tolerance)
        best_hit = None

        for layer in self._eligible_vector_layers(require_editable=require_editable):
            try:
                to_project = QgsCoordinateTransform(layer.crs(), self.project.crs(), self.project)
                layer_rect = self.canvas.mapSettings().mapToLayerCoordinates(layer, search_rect)
                request = QgsFeatureRequest().setFilterRect(layer_rect)
                for feature in layer.getFeatures(request):
                    geometry = feature.geometry()
                    if geometry is None or geometry.isEmpty():
                        continue
                    project_geometry = QgsGeometry(geometry)
                    project_geometry.transform(to_project)
                    bbox = project_geometry.boundingBox()
                    bbox.grow(tolerance)
                    if not bbox.contains(point):
                        continue
                    try:
                        distance = project_geometry.distance(point_geometry)
                    except Exception:
                        continue
                    if distance > tolerance:
                        continue
                    candidate = (float(distance), layer.name().lower(), int(feature.id()), layer, QgsFeature(feature))
                    if best_hit is None or candidate[:3] < best_hit[:3]:
                        best_hit = candidate
            except Exception:
                continue

        if best_hit is None:
            return None, None
        return best_hit[3], best_hit[4]

    def _resolve_event_point(self, event, use_snapping):
        point = QgsPointXY(event.mapPoint())
        snap_match = None
        if not use_snapping:
            return point, snap_match

        try:
            event.snapPoint()
            point = QgsPointXY(event.mapPoint())
        except Exception:
            pass

        for accessor in ("mapPointMatch", "snappedMatch"):
            try:
                candidate = getattr(event, accessor)()
            except Exception:
                continue
            if candidate is None:
                continue
            try:
                if not candidate.isValid():
                    continue
            except Exception:
                pass
            snap_match = candidate
            break

        return point, snap_match

    def _extract_snapped_target(self, snap_match):
        if snap_match is None:
            return None, None

        try:
            if not snap_match.isValid():
                return None, None
        except Exception:
            pass

        snapped_layer = None
        snapped_feature_id = None

        try:
            snapped_layer = snap_match.layer()
        except Exception:
            snapped_layer = None

        try:
            feature_id = int(snap_match.featureId())
            if feature_id >= 0:
                snapped_feature_id = feature_id
        except Exception:
            snapped_feature_id = None

        return snapped_layer, snapped_feature_id

    def _set_identify_results(self, results):
        self._identify_results = list(results or [])
        self._feature_count = len(self._identify_results)

        available_targets = {(result["layer_id"], int(result["feature_id"])) for result in self._identify_results}
        if self._identify_current_result not in available_targets:
            if self._identify_results:
                first_result = self._identify_results[0]
                self._identify_current_result = (str(first_result["layer_id"]), int(first_result["feature_id"]))
            else:
                self._identify_current_result = None

        self.identifyResultsChanged.emit([self._serialize_identify_result(result) for result in self._identify_results])
        self._update_identify_highlight_from_current()

    def _clear_identify_session(self, emit_results, emit_state):
        self._identify_results = []
        self._identify_current_result = None
        self._feature_count = 0
        self._clear_identify_highlight()
        if emit_results:
            self.identifyResultsChanged.emit([])
        if emit_state:
            self._emit_state()

    def _update_identify_highlight_from_current(self):
        target = self._resolve_identify_target()
        if target is None:
            self._clear_identify_highlight()
            return False
        layer, feature = self._resolve_feature(target[0], target[1])
        if layer is None or feature is None:
            self._clear_identify_highlight()
            return False
        self._show_identify_highlight(layer, feature)
        info = (
            f"Selected identify result: {layer.name()} | {self._identify_display_value(layer, feature)} "
            f"(feature {feature.id()})."
        )
        self._emit_state(info_override=info)
        return True

    def _resolve_identify_target(self, layer_id=None, feature_id=None):
        if layer_id is not None and feature_id is not None:
            return str(layer_id), int(feature_id)
        return self._identify_current_result

    def _resolve_feature(self, layer_id, feature_id):
        try:
            layer = self.project.mapLayer(str(layer_id))
        except Exception:
            layer = None
        if layer is None or layer.type() != QgsMapLayerType.VectorLayer:
            return None, None
        try:
            request = QgsFeatureRequest().setFilterFid(int(feature_id))
            feature = next(layer.getFeatures(request), None)
        except Exception:
            feature = None
        if feature is None or not feature.isValid():
            return None, None
        return layer, feature

    def _show_identify_highlight(self, layer, feature):
        self._clear_identify_highlight()
        try:
            highlight = QgsHighlight(self.canvas, feature.geometry(), layer)
            self._apply_identify_highlight_style(highlight)
            highlight.show()
            self._identify_highlight = highlight
        except Exception:
            self._identify_highlight = None

    def _clear_identify_highlight(self):
        if self._identify_highlight is None:
            return
        try:
            self._identify_highlight.hide()
            self.canvas.scene().removeItem(self._identify_highlight)
        except Exception:
            pass
        self._identify_highlight = None

    def _update_identify_highlight_style(self):
        if self._identify_highlight is not None:
            self._apply_identify_highlight_style(self._identify_highlight)

    def _apply_identify_highlight_style(self, highlight):
        fill_color = QColor(self.preview_color)
        fill_color.setAlpha(35)
        highlight.setColor(self.preview_color)
        highlight.setFillColor(fill_color)
        highlight.setWidth(2)

    def _serialize_identify_result(self, result):
        layer, feature = self._resolve_feature(result["layer_id"], result["feature_id"])
        attributes = []
        geometry_label = ""
        if layer is not None and feature is not None:
            try:
                geometry = feature.geometry()
                if geometry is not None and not geometry.isEmpty():
                    geometry_label = QgsWkbTypes.displayString(geometry.wkbType())
            except Exception:
                geometry_label = ""
            try:
                for field in feature.fields():
                    attributes.append(
                        {
                            "name": field.name(),
                            "value": self._format_identify_value(feature[field.name()]),
                        }
                    )
            except Exception:
                attributes = []

        derived = [
            {"name": "Feature ID", "value": str(int(result["feature_id"]))},
            {"name": "Distance", "value": f"{result['distance']:.3f}"},
        ]
        if geometry_label:
            derived.append({"name": "Geometry", "value": geometry_label})

        return {
            "layer_id": result["layer_id"],
            "feature_id": int(result["feature_id"]),
            "layer_name": result["layer_name"],
            "display": result["display"],
            "attributes": attributes,
            "derived": derived,
        }

    def _identify_display_value(self, layer, feature):
        try:
            display_field = layer.displayField()
        except Exception:
            display_field = ""
        try:
            if display_field and feature.fields().indexOf(display_field) >= 0:
                value = feature[display_field]
                if value not in (None, ""):
                    return str(value)
        except Exception:
            pass
        return f"Feature {feature.id()}"

    def _format_identify_value(self, value):
        if value is None:
            return "NULL"
        try:
            return str(value)
        except Exception:
            return "<unavailable>"

    def _current_selection_counts(self, include_only_editable=False):
        layer_count = 0
        feature_count = 0
        for layer in self._eligible_vector_layers(require_editable=include_only_editable):
            selected = layer.selectedFeatureCount()
            if selected > 0:
                layer_count += 1
                feature_count += selected
        return layer_count, feature_count

    def _collect_selection(self, require_points_only=False):
        warnings = []
        selected_visible_features = 0
        selected_uneditable_layers = 0
        skipped_transform_layers = []
        non_point_layers = []
        layers = []

        for vector_layer in self._eligible_vector_layers(require_editable=False):
            selected_count = vector_layer.selectedFeatureCount()
            if selected_count == 0:
                continue
            selected_visible_features += selected_count

            if not vector_layer.isEditable():
                selected_uneditable_layers += 1
                continue

            if require_points_only and vector_layer.geometryType() != QgsWkbTypes.PointGeometry:
                non_point_layers.append(vector_layer.name())
                continue

            try:
                to_project = QgsCoordinateTransform(vector_layer.crs(), self.project.crs(), self.project)
                to_layer = QgsCoordinateTransform(self.project.crs(), vector_layer.crs(), self.project)
                layer_state = LayerState(layer=vector_layer, to_project=to_project, to_layer=to_layer)
                for feature in vector_layer.selectedFeatures():
                    geometry = feature.geometry()
                    if geometry is None or geometry.isEmpty():
                        continue
                    layer_geometry = QgsGeometry(geometry)
                    project_geometry = QgsGeometry(layer_geometry)
                    project_geometry.transform(to_project)
                    layer_state.features.append(FeatureState(feature=QgsFeature(feature), layer_geometry=layer_geometry, project_geometry=project_geometry))
                if layer_state.features:
                    layers.append(layer_state)
            except Exception:
                skipped_transform_layers.append(vector_layer.name())

        if selected_visible_features == 0:
            warnings.append("No selected features were found on visible vector layers that match the current filter.")
        elif not layers:
            if selected_uneditable_layers:
                warnings.append("Selected features were found, but none are on editable visible vector layers.")
            else:
                warnings.append("No eligible editable vector layers with selected features were found.")
        if selected_uneditable_layers:
            warnings.append(f"Ignored {selected_uneditable_layers} visible layer(s) with selected features because they are not editable.")
        if non_point_layers:
            warnings.append("Orthogonalize requires point layers only. Ignored non-point layer(s): " + ", ".join(non_point_layers))
        if skipped_transform_layers:
            warnings.append("Skipped layer(s) that could not be transformed into the project CRS: " + ", ".join(skipped_transform_layers))
        return layers, warnings

    def _prepare_orthogonalize_preview(self, warnings):
        point_refs = []
        for layer_state in self._layers:
            for feature_state in layer_state.features:
                point = self._extract_single_point(feature_state.project_geometry)
                if point is None:
                    warnings.append("Orthogonalize requires exactly four single-point geometries.")
                    return False
                point_refs.append((layer_state, feature_state, point))

        if len(point_refs) != 4:
            warnings.append(f"Orthogonalize requires exactly 4 selected point features on editable visible layers. Current eligible selection: {len(point_refs)}.")
            return False

        points = [(p.x(), p.y()) for _, _, p in point_refs]
        angle = self._principal_axis_angle(points)
        ux, uy = cos(angle), sin(angle)
        vx, vy = -sin(angle), cos(angle)
        cx = sum(x for x, _ in points) / 4.0
        cy = sum(y for _, y in points) / 4.0
        projections = [((x - cx) * ux + (y - cy) * uy, (x - cx) * vx + (y - cy) * vy) for x, y in points]
        a_vals = [p[0] for p in projections]
        b_vals = [p[1] for p in projections]
        a_min, a_max = min(a_vals), max(a_vals)
        b_min, b_max = min(b_vals), max(b_vals)
        half_w = max((a_max - a_min) / 2.0, self.canvas.mapUnitsPerPixel())
        half_h = max((b_max - b_min) / 2.0, self.canvas.mapUnitsPerPixel())
        center_a = (a_min + a_max) / 2.0
        center_b = (b_min + b_max) / 2.0
        rcx = cx + center_a * ux + center_b * vx
        rcy = cy + center_a * uy + center_b * vy

        corner_ab = [(half_w, half_h), (half_w, -half_h), (-half_w, -half_h), (-half_w, half_h)]
        corners = [QgsPointXY(rcx + a * ux + b * vx, rcy + a * uy + b * vy) for a, b in corner_ab]

        best_perm = None
        best_cost = None
        for perm in permutations(range(4)):
            cost = 0.0
            for idx, corner_idx in enumerate(perm):
                px, py = points[idx]
                corner = corners[corner_idx]
                cost += (px - corner.x()) ** 2 + (py - corner.y()) ** 2
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_perm = perm

        targets = {}
        for idx, (layer_state, feature_state, _) in enumerate(point_refs):
            key = self._feature_key(layer_state, feature_state)
            targets[key] = QgsPointXY(corners[best_perm[idx]])

        self._current_transform = {"type": "orthogonalize", "targets": targets}
        self._update_preview_bands()
        self._show_orthogonalize_band(corners)
        return True

    def _feature_key(self, layer_state, feature_state):
        return (layer_state.layer.id(), int(feature_state.feature.id()))

    def _extract_single_point(self, geometry):
        try:
            if geometry.isMultipart():
                pts = geometry.asMultiPoint()
                if len(pts) == 1:
                    return QgsPointXY(pts[0])
                return None
            return QgsPointXY(geometry.asPoint())
        except Exception:
            return None

    def _principal_axis_angle(self, points):
        cx = sum(x for x, _ in points) / len(points)
        cy = sum(y for _, y in points) / len(points)
        sxx = sum((x - cx) ** 2 for x, _ in points)
        syy = sum((y - cy) ** 2 for _, y in points)
        sxy = sum((x - cx) * (y - cy) for x, y in points)
        if abs(sxy) < 1e-12 and abs(sxx - syy) < 1e-12:
            return 0.0
        return 0.5 * atan2(2.0 * sxy, sxx - syy)

    def _point_hits_selected_feature(self, point):
        if not self._layers:
            return False
        point_geometry = QgsGeometry.fromPointXY(point)
        tolerance = max(self.canvas.mapUnitsPerPixel() * 6.0, 1e-9)
        for layer_state in self._layers:
            for feature_state in layer_state.features:
                geom = feature_state.project_geometry
                if geom is None or geom.isEmpty():
                    continue
                bbox = geom.boundingBox()
                bbox.grow(tolerance)
                if not bbox.contains(point):
                    continue
                try:
                    if geom.distance(point_geometry) <= tolerance:
                        return True
                except Exception:
                    continue
        return False

    def _compute_group_centroid(self):
        geometries = []
        combined_extent = None
        for layer_state in self._layers:
            for feature_state in layer_state.features:
                geometry = QgsGeometry(feature_state.project_geometry)
                geometries.append(geometry)
                bbox = geometry.boundingBox()
                if combined_extent is None:
                    combined_extent = QgsRectangle(bbox)
                else:
                    combined_extent.combineExtentWith(bbox)
        if geometries:
            try:
                collection = QgsGeometry.collectGeometry(geometries)
                centroid = collection.centroid()
                if centroid and not centroid.isEmpty():
                    return centroid.asPoint()
            except Exception:
                pass
        if combined_extent is not None:
            return combined_extent.center()
        return QgsPointXY(0.0, 0.0)

    def _create_preview_bands(self):
        for layer_state in self._layers:
            for feature_state in layer_state.features:
                band = QgsRubberBand(self.canvas, layer_state.layer.geometryType())
                feature_state.preview_band = band
                self._apply_preview_style(band)
                band.hide()

    def _update_preview_style(self):
        for layer_state in self._layers:
            for feature_state in layer_state.features:
                if feature_state.preview_band is not None:
                    self._apply_preview_style(feature_state.preview_band)

    def _apply_preview_style(self, band):
        fill_color = QColor(self.preview_color)
        fill_color.setAlpha(40)
        band.setColor(self.preview_color)
        band.setFillColor(fill_color)
        band.setWidth(2)

    def _cursor_for_mode(self):
        if self.mode == "identify":
            try:
                icon_path = os.path.join(os.path.dirname(__file__), "icons", "identify.svg")
                pixmap = QIcon(icon_path).pixmap(24, 24)
                if not pixmap.isNull():
                    return QCursor(pixmap, 5, 5)
            except Exception:
                pass
            return QCursor(Qt.PointingHandCursor)
        return QCursor(Qt.CrossCursor)

    def _show_selection_hover_highlight(self, layer, feature):
        self._clear_selection_hover_highlight()
        try:
            highlight = QgsHighlight(self.canvas, feature.geometry(), layer)
            self._apply_selection_hover_highlight_style(highlight)
            highlight.show()
            self._selection_hover_highlight = highlight
        except Exception:
            self._selection_hover_highlight = None

    def _clear_selection_hover_highlight(self):
        self._selection_hover_target = None
        if self._selection_hover_highlight is None:
            return
        try:
            self._selection_hover_highlight.hide()
            self.canvas.scene().removeItem(self._selection_hover_highlight)
        except Exception:
            pass
        self._selection_hover_highlight = None

    def _update_selection_hover_highlight_style(self):
        if self._selection_hover_highlight is not None:
            self._apply_selection_hover_highlight_style(self._selection_hover_highlight)

    def _apply_selection_hover_highlight_style(self, highlight):
        fill_color = QColor(self.preview_color)
        fill_color.setAlpha(18)
        highlight.setColor(self.preview_color)
        highlight.setFillColor(fill_color)
        highlight.setWidth(3)

    def _show_selection_band(self, start_point, end_point):
        if self._selection_band is None:
            self._selection_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
            self._update_selection_band_style()
        rect = QgsRectangle(start_point, end_point)
        self._selection_band.setToGeometry(QgsGeometry.fromRect(rect), None)
        self._selection_band.show()

    def _update_selection_band_style(self):
        if self._selection_band is None:
            return
        fill_color = QColor(self.preview_color)
        fill_color.setAlpha(25)
        self._selection_band.setColor(self.preview_color)
        self._selection_band.setFillColor(fill_color)
        self._selection_band.setWidth(1)

    def _hide_selection_band(self):
        if self._selection_band is None:
            return
        try:
            self._selection_band.hide()
            self.canvas.scene().removeItem(self._selection_band)
        except Exception:
            pass
        self._selection_band = None

    def _show_orthogonalize_band(self, corners):
        if self.mode != "orthogonalize":
            return
        if self._orthogonalize_band is None:
            self._orthogonalize_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
            self._update_orthogonalize_band_style()
        polygon = list(corners) + [corners[0]]
        self._orthogonalize_band.setToGeometry(QgsGeometry.fromPolygonXY([polygon]), None)
        self._orthogonalize_band.show()

    def _update_orthogonalize_band_style(self):
        if self._orthogonalize_band is None:
            return
        fill = QColor(self.preview_color)
        fill.setAlpha(15)
        self._orthogonalize_band.setColor(self.preview_color)
        self._orthogonalize_band.setFillColor(fill)
        self._orthogonalize_band.setWidth(1)

    def _hide_orthogonalize_band(self):
        if self._orthogonalize_band is None:
            return
        try:
            self._orthogonalize_band.hide()
            self.canvas.scene().removeItem(self._orthogonalize_band)
        except Exception:
            pass
        self._orthogonalize_band = None

    def _update_pivot_marker(self):
        if not self.show_pivot_marker or self._pivot_point is None or self.mode not in {"rotate", "scale"}:
            self._remove_pivot_marker()
            return
        if self._pivot_marker is None:
            self._pivot_marker = QgsVertexMarker(self.canvas)
            self._pivot_marker.setIconType(QgsVertexMarker.ICON_CROSS)
            self._pivot_marker.setIconSize(14)
            self._pivot_marker.setPenWidth(3)
        self._pivot_marker.setColor(self.preview_color)
        self._pivot_marker.setCenter(self._pivot_point)
        self._pivot_marker.show()

    def _remove_pivot_marker(self):
        if self._pivot_marker is None:
            return
        try:
            self.canvas.scene().removeItem(self._pivot_marker)
        except Exception:
            pass
        self._pivot_marker = None

    def _update_preview_bands(self):
        if not self._current_transform:
            self.clear_preview()
            return
        for layer_state in self._layers:
            for feature_state in layer_state.features:
                if feature_state.preview_band is None:
                    continue
                transformed = self._transform_project_geometry(feature_state.project_geometry, self._feature_key(layer_state, feature_state))
                feature_state.preview_band.setToGeometry(transformed, None)
                feature_state.preview_band.show()

    def _transform_project_geometry(self, geometry, feature_key=None):
        transformed = QgsGeometry(geometry)
        transform_type = self._current_transform["type"]
        if transform_type == "move":
            transformed.translate(self._current_transform["dx"], self._current_transform["dy"])
            return transformed
        if transform_type == "rotate":
            transformed.rotate(self._current_transform["angle"], self._current_transform["pivot"])
            return transformed
        if transform_type == "scale":
            transform = QTransform()
            pivot = self._current_transform["pivot"]
            transform.translate(pivot.x(), pivot.y())
            transform.scale(self._current_transform["scale_x"], self._current_transform["scale_y"])
            transform.translate(-pivot.x(), -pivot.y())
            transformed.transform(transform)
            return transformed
        target = self._current_transform["targets"].get(feature_key)
        return QgsGeometry.fromPointXY(target) if target is not None else transformed

    def _build_layer_geometry(self, layer_state, feature_state):
        key = self._feature_key(layer_state, feature_state)
        transformed_project = self._transform_project_geometry(feature_state.project_geometry, key)
        transformed_layer = QgsGeometry(transformed_project)
        transformed_layer.transform(layer_state.to_layer)
        return transformed_layer

    def _command_label(self, transform_type, duplicate):
        if transform_type == "orthogonalize":
            return "Duplicate and orthogonalize selected points" if duplicate else "Orthogonalize selected points"
        if duplicate:
            return "Duplicate and transform selected features"
        if transform_type == "move":
            return "Move selected features"
        if transform_type == "rotate":
            return "Rotate selected features"
        return "Scale selected features"

    def _success_message(self, transform_type, duplicate):
        if transform_type == "move":
            action = "Duplicated and moved" if duplicate else "Moved"
            return f"{action} {self._feature_count} feature(s) across {self._layer_count} layer(s). dx={self._current_transform['dx']:.3f}, dy={self._current_transform['dy']:.3f}"
        if transform_type == "rotate":
            action = "Duplicated and rotated" if duplicate else "Rotated"
            return f"{action} {self._feature_count} feature(s) across {self._layer_count} layer(s). angle={self._current_transform['angle']:.2f} deg"
        if transform_type == "scale":
            action = "Duplicated and scaled" if duplicate else "Scaled"
            return (
                f"{action} {self._feature_count} feature(s) across {self._layer_count} layer(s). "
                f"scale x={self._current_transform['scale_x']:.4f}, y={self._current_transform['scale_y']:.4f}"
            )
        action = "Duplicated and orthogonalized" if duplicate else "Orthogonalized"
        return f"{action} 4 point feature(s) across {self._layer_count} layer(s) into a best-fit rectangle."

    def _emit_state(self, info_override=None):
        angle = 0.0
        dx = None
        dy = None
        scale_x = 1.0
        scale_y = 1.0
        transform_type = None
        lines = [f"Layers involved: {self._layer_count}", f"Features involved: {self._feature_count}"]
        if self._current_transform:
            transform_type = self._current_transform["type"]
            if transform_type == "move":
                dx = float(self._current_transform["dx"])
                dy = float(self._current_transform["dy"])
                lines.append(f"dx: {dx:.3f} | dy: {dy:.3f}")
            elif transform_type == "rotate":
                angle = float(self._current_transform["angle"])
                lines.append(f"Angle (clockwise +): {angle:.2f} deg")
            elif transform_type == "scale":
                scale_x = float(self._current_transform["scale_x"])
                scale_y = float(self._current_transform["scale_y"])
                lines.append(f"Scale x: {scale_x:.4f} | Scale y: {scale_y:.4f}")
            else:
                lines.append("Orthogonalize preview: best-fit rectangle ready")
        if self.mode in {"rotate", "scale"} and self._pivot_point is not None:
            lines.append(f"Pivot: {self._pivot_point.x():.3f}, {self._pivot_point.y():.3f}")
        if info_override:
            lines.append(info_override)
        elif self.mode == "quick_select" and self._interaction_state == "await_quick_select_click":
            lines.append("Quick Select mode: click the top visible feature to select it across layers without changing the active layer.")
        elif self.mode == "identify" and self._interaction_state == "idle":
            lines.append("Identify mode: no visible target vector layers are available.")
        elif self.mode == "identify" and self._interaction_state == "await_identify_click":
            lines.append("Identify mode: click any visible feature to search across layers without changing the active layer.")
        elif self.mode == "select":
            lines.append(f"Selection mode: click or drag a box. Default operation is {self.selection_operation}; Shift adds and Ctrl removes.")
        elif self.mode == "orthogonalize":
            lines.append("Select exactly 4 editable point features, then use Orthogonalize to square them into a rectangle across layers.")
        elif self._interaction_state == "idle":
            lines.append("No active selection is ready for transformation.")
        elif self._interaction_state == "await_move_origin":
            lines.append("Drag from any selected feature to move the group, or click a reference point to start a move preview.")
        elif self._interaction_state == "await_move_target":
            lines.append("Move the cursor and click to set the destination.")
        elif self._interaction_state == "drag_move_active":
            lines.append("Drag move active: release to apply the move.")
        elif self._interaction_state == "await_rotate_pivot":
            lines.append("Click a pivot point to begin rotation.")
        elif self._interaction_state == "await_rotate_reference":
            lines.append("Click a reference direction from the pivot or preview a manual angle.")
        elif self._interaction_state == "await_rotate_target":
            lines.append("Move the cursor around the pivot and click to apply the angle.")
        elif self._interaction_state == "await_scale_pivot":
            lines.append("Click a pivot point to begin scaling.")
        elif self._interaction_state == "await_scale_reference":
            lines.append("Click a reference distance from the pivot or preview numeric X/Y factors.")
        elif self._interaction_state == "await_scale_target":
            lines.append("Move the cursor away from the pivot and click to apply the scale.")
        elif self.mode == "scale":
            lines.append("Scale mode: click a reference distance then a target distance, or use numeric X/Y factors from the dock.")
        payload = {
            "layer_count": self._layer_count,
            "feature_count": self._feature_count,
            "angle": angle,
            "dx": dx,
            "dy": dy,
            "scale_x": scale_x,
            "scale_y": scale_y,
            "transform_type": transform_type,
            "mode": self.mode,
            "text": "\n".join(lines),
        }
        self.stateChanged.emit(payload)

    def _is_same_point(self, point_a, point_b):
        tolerance = self.canvas.mapUnitsPerPixel() * 2.0
        return abs(point_a.x() - point_b.x()) <= tolerance and abs(point_a.y() - point_b.y()) <= tolerance

    def _normalize_angle(self, angle):
        while angle <= -180.0:
            angle += 360.0
        while angle > 180.0:
            angle -= 360.0
        return angle

    def _snap_angle_value(self, angle, step):
        return angle if not step else round(angle / step) * step
