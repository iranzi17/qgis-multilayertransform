import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QActionGroup

from .identify_results_dialog import IdentifyResultsDockWidget
from .transform_dialog import TransformDockWidget
from .transform_map_tool import TransformMapTool


class MultiLayerTransformPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.plugin_dir = os.path.dirname(__file__)
        self.menu_name = "&MultiLayerTransform"

        self.toolbar = None
        self.action_group = None
        self.quick_select_action = None
        self.identify_action = None
        self.select_action = None
        self.move_action = None
        self.rotate_action = None
        self.scale_action = None
        self.orthogonalize_action = None
        self.dock = None
        self.identify_results_dock = None
        self.map_tool = None
        self.previous_map_tool = None
        self._updating_actions = False

    def initGui(self):
        self.toolbar = self.iface.addToolBar("MultiLayerTransform")
        self.toolbar.setObjectName("MultiLayerTransformToolbar")

        self.action_group = QActionGroup(self.iface.mainWindow())
        self.action_group.setExclusive(False)

        actions = [
            ("quick_select", "quick_select.svg", "Quick Select Across Layers"),
            ("identify", "identify.svg", "Identify Across Layers"),
            ("select", "multilayer_transform.svg", "Select Across Layers"),
            ("move", "move.svg", "Move Multi-Layer Selection"),
            ("rotate", "rotate.svg", "Rotate Multi-Layer Selection"),
            ("scale", "scale.svg", "Scale Multi-Layer Selection"),
            ("orthogonalize", "orthogonalize.svg", "Orthogonalize 4 Selected Points"),
        ]

        created = {}
        for mode, icon_name, label in actions:
            action = QAction(QIcon(self._icon_path(icon_name)), label, self.iface.mainWindow())
            action.setCheckable(True)
            action.toggled.connect(lambda checked, m=mode: self._handle_action_toggled(m, checked))
            self.action_group.addAction(action)
            self.iface.addPluginToMenu(self.menu_name, action)
            self.toolbar.addAction(action)
            created[mode] = action

        self.quick_select_action = created["quick_select"]
        self.identify_action = created["identify"]
        self.select_action = created["select"]
        self.move_action = created["move"]
        self.rotate_action = created["rotate"]
        self.scale_action = created["scale"]
        self.orthogonalize_action = created["orthogonalize"]

        self.dock = TransformDockWidget(self.iface.mainWindow())
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.hide()
        self.dock.visibilityChanged.connect(self._handle_main_dock_visibility_changed)

        self.identify_results_dock = IdentifyResultsDockWidget(self.iface.mainWindow())
        self.iface.addDockWidget(Qt.RightDockWidgetArea, self.identify_results_dock)
        self.identify_results_dock.hide()

        self.map_tool = TransformMapTool(self.iface)
        self.map_tool.stateChanged.connect(self._handle_tool_state)
        self.map_tool.identifyResultsChanged.connect(self.identify_results_dock.set_results)
        self.map_tool.warningRaised.connect(self._handle_tool_warning)
        self.map_tool.statusMessage.connect(self._handle_tool_status)

        self.dock.modeChanged.connect(self.activate_mode)
        self.dock.pivotChanged.connect(self.map_tool.set_pivot_mode)
        self.dock.snapChanged.connect(self.map_tool.set_snap_angle)
        self.dock.selectedLayersOnlyChanged.connect(self.map_tool.set_only_selected_layers)
        self.dock.targetLayersChanged.connect(self.map_tool.set_target_layer_ids)
        self.dock.selectionOperationChanged.connect(self.map_tool.set_selection_operation)
        self.dock.showPivotMarkerChanged.connect(self.map_tool.set_show_pivot_marker)
        self.dock.previewColorChanged.connect(self.map_tool.set_preview_color)
        self.dock.manualAnglePreviewRequested.connect(self._preview_manual_angle)
        self.dock.manualScalePreviewRequested.connect(self._preview_manual_scale)
        self.dock.applyRequested.connect(self._apply_requested)
        self.dock.cancelRequested.connect(self.map_tool.cancel_current_operation)
        self.dock.clearSelectionRequested.connect(self.map_tool.clear_current_selection)
        self.dock.refreshRequested.connect(self._refresh_requested)
        self.identify_results_dock.resultSelected.connect(self.map_tool.select_identify_result)
        self.identify_results_dock.openRequested.connect(self.map_tool.open_identify_result)
        self.identify_results_dock.zoomRequested.connect(self.map_tool.zoom_to_identify_result)
        self.identify_results_dock.clearRequested.connect(self.map_tool.clear_identify_results)

        self.canvas.mapToolSet.connect(self._on_map_tool_set)
        self.iface.layerTreeView().currentLayerChanged.connect(lambda *_: self._populate_target_layers())
        self.iface.layerTreeView().layerTreeModel().rowsInserted.connect(lambda *_: self._populate_target_layers())
        self.iface.layerTreeView().layerTreeModel().rowsRemoved.connect(lambda *_: self._populate_target_layers())

        try:
            from qgis.core import QgsProject

            QgsProject.instance().layersAdded.connect(lambda *_: self._populate_target_layers())
            QgsProject.instance().layersRemoved.connect(lambda *_: self._populate_target_layers())
        except Exception:
            pass

        self._populate_target_layers()
        self.dock.set_mode("select")
        self.dock.set_selection_operation("replace")
        self.dock.set_pivot_mode("centroid")
        self.dock.set_snap_angle(0.0)
        self.dock.set_show_pivot_marker(True)
        self.dock.set_preview_color(self.dock.preview_color())
        self.dock.set_current_scale(1.0, 1.0)

    def unload(self):
        if self.canvas.mapTool() is self.map_tool:
            if self.previous_map_tool is not None:
                self.canvas.setMapTool(self.previous_map_tool)
            else:
                self.canvas.unsetMapTool(self.map_tool)

        if self.map_tool is not None:
            try:
                self.map_tool.cleanup()
            except Exception:
                pass

        try:
            self.canvas.mapToolSet.disconnect(self._on_map_tool_set)
        except Exception:
            pass

        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None

        if self.identify_results_dock is not None:
            self.iface.removeDockWidget(self.identify_results_dock)
            self.identify_results_dock.deleteLater()
            self.identify_results_dock = None

        for action in (
            self.select_action,
            self.quick_select_action,
            self.identify_action,
            self.move_action,
            self.rotate_action,
            self.scale_action,
            self.orthogonalize_action,
        ):
            if action is None:
                continue
            self.iface.removePluginMenu(self.menu_name, action)

        if self.toolbar is not None:
            self.iface.mainWindow().removeToolBar(self.toolbar)
            self.toolbar = None

        self.action_group = None
        self.quick_select_action = None
        self.identify_action = None
        self.select_action = None
        self.move_action = None
        self.rotate_action = None
        self.scale_action = None
        self.orthogonalize_action = None
        self.map_tool = None

    def activate_mode(self, mode):
        self._ensure_active_tool(mode, refresh=True)

    def deactivate_tool(self, hide_docks=False):
        if self.map_tool is not None:
            try:
                self.map_tool.cleanup()
            except Exception:
                pass

        if self.canvas.mapTool() is self.map_tool:
            restore_tool = self.previous_map_tool if self.previous_map_tool is not self.map_tool else None
            self.previous_map_tool = None
            if restore_tool is not None:
                self.canvas.setMapTool(restore_tool)
            else:
                self.canvas.unsetMapTool(self.map_tool)
        else:
            self.previous_map_tool = None

        self._set_checked_mode(None)

        if hide_docks:
            if self.dock is not None:
                self.dock.hide()
            if self.identify_results_dock is not None:
                self.identify_results_dock.hide()

    def _ensure_active_tool(self, mode, refresh):
        if mode not in {"quick_select", "identify", "select", "move", "rotate", "scale", "orthogonalize"}:
            return False
        if self.map_tool is None or self.dock is None:
            return False

        self.dock.show()
        self.dock.raise_()
        self.dock.set_mode(mode)
        self._set_checked_mode(mode)

        if self.canvas.mapTool() is not self.map_tool:
            self.previous_map_tool = self.canvas.mapTool()
            self.canvas.setMapTool(self.map_tool)

        self.map_tool.mode = mode
        self.map_tool.pivot_mode = self.dock.current_pivot_mode()
        self.map_tool.snap_angle = self.dock.current_snap_angle()
        self.map_tool.only_selected_layers = self.dock.only_selected_layers()
        self.map_tool.show_pivot_marker = self.dock.show_pivot_marker()
        self.map_tool.preview_color = self.dock.preview_color()
        self.map_tool.update_cursor()

        if refresh:
            if mode == "select":
                self.map_tool.refresh_selection_summary()
            elif mode == "quick_select":
                self.map_tool.refresh_quick_select_state()
            elif mode == "identify":
                self.map_tool.refresh_identify_state(clear_results=False)
            else:
                self.map_tool.refresh_selection()
        else:
            self.map_tool.set_show_pivot_marker(self.dock.show_pivot_marker())
            self.map_tool.set_preview_color(self.dock.preview_color())
        return True

    def _handle_action_toggled(self, mode, checked):
        if self._updating_actions:
            return
        if checked:
            self.activate_mode(mode)
            return
        if self.canvas.mapTool() is self.map_tool and self.dock is not None and self.dock.current_mode() == mode:
            self.deactivate_tool(hide_docks=True)

    def _refresh_requested(self):
        if self.dock is not None:
            self.activate_mode(self.dock.current_mode())

    def _preview_manual_angle(self, angle):
        self._ensure_active_tool("rotate", refresh=not self.map_tool.has_preview())
        self.map_tool.preview_manual_rotation(angle)

    def _preview_manual_scale(self, scale_x, scale_y):
        self._ensure_active_tool("scale", refresh=not self.map_tool.has_preview())
        self.map_tool.preview_manual_scale(scale_x, scale_y)

    def _apply_requested(self):
        if self.dock is None:
            return

        mode = self.dock.current_mode()
        self._ensure_active_tool(mode, refresh=not self.map_tool.has_preview())

        if mode == "rotate" and not self.map_tool.has_preview():
            angle = self.dock.manual_angle()
            if abs(angle) > 1e-9 and not self.map_tool.preview_manual_rotation(angle):
                return
        elif mode == "scale" and not self.map_tool.has_preview():
            scale_x, scale_y = self.dock.manual_scale_factors()
            if (abs(scale_x - 1.0) > 1e-9 or abs(scale_y - 1.0) > 1e-9) and not self.map_tool.preview_manual_scale(scale_x, scale_y):
                return

        self.map_tool.apply_current_operation()

    def _handle_tool_state(self, payload):
        if self.dock is None:
            return

        self.dock.set_selection_summary(payload.get("layer_count", 0), payload.get("feature_count", 0))
        self.dock.set_current_angle(payload.get("angle", 0.0))
        self.dock.set_current_scale(payload.get("scale_x", 1.0), payload.get("scale_y", 1.0))
        self.dock.set_live_info(payload.get("text", ""))

        layer_count = payload.get("layer_count", 0)
        feature_count = payload.get("feature_count", 0)
        transform_type = payload.get("transform_type")
        mode = payload.get("mode")

        if mode == "identify" and layer_count == 0:
            status = "Identify: no visible target layers are available."
        elif mode == "quick_select":
            status = f"Quick Select: {feature_count} selected feature(s) across {layer_count} layer(s)"
        elif layer_count == 0:
            status = "No eligible selection is ready."
        elif mode == "identify":
            status = f"Identify: {feature_count} result(s) across {layer_count} searchable layer(s)"
        elif mode == "select":
            status = f"Selection: {layer_count} layer(s) | {feature_count} feature(s)"
        elif transform_type == "move":
            status = (
                f"{layer_count} layer(s) | {feature_count} feature(s) | "
                f"dx={payload.get('dx', 0.0):.3f}, dy={payload.get('dy', 0.0):.3f}"
            )
        elif transform_type == "rotate":
            status = (
                f"{layer_count} layer(s) | {feature_count} feature(s) | "
                f"angle={payload.get('angle', 0.0):.2f} deg"
            )
        elif transform_type == "scale":
            status = (
                f"{layer_count} layer(s) | {feature_count} feature(s) | "
                f"scale x={payload.get('scale_x', 1.0):.4f}, y={payload.get('scale_y', 1.0):.4f}"
            )
        elif transform_type == "orthogonalize":
            status = f"Orthogonalize preview: {feature_count} point(s) across {layer_count} layer(s)"
        else:
            status = f"{layer_count} layer(s) | {feature_count} feature(s)"

        self._show_status(status)

    def _handle_tool_warning(self, message):
        self.iface.messageBar().pushWarning("MultiLayerTransform", message)
        self._show_status(message, 5000)

    def _handle_tool_status(self, message):
        self._show_status(message, 5000)

    def _on_map_tool_set(self, new_tool, old_tool):
        if new_tool is self.map_tool or old_tool is not self.map_tool:
            return
        self.previous_map_tool = None
        self._set_checked_mode(None)

    def _handle_main_dock_visibility_changed(self, visible):
        if visible:
            return
        if self.canvas.mapTool() is self.map_tool:
            self.deactivate_tool(hide_docks=False)

    def _set_checked_mode(self, mode):
        action_by_mode = {
            "quick_select": self.quick_select_action,
            "identify": self.identify_action,
            "select": self.select_action,
            "move": self.move_action,
            "rotate": self.rotate_action,
            "scale": self.scale_action,
            "orthogonalize": self.orthogonalize_action,
        }
        self._updating_actions = True
        for current_mode, action in action_by_mode.items():
            if action is None:
                continue
            action.blockSignals(True)
            action.setChecked(current_mode == mode)
            action.blockSignals(False)
        self._updating_actions = False

    def _show_status(self, message, timeout=0):
        self.iface.statusBarIface().showMessage(message, timeout)

    def _populate_target_layers(self):
        if self.dock is None or self.map_tool is None:
            return

        layer_items = []
        root = self.iface.layerTreeView().layerTreeModel().rootGroup()
        for node in root.findLayers():
            layer = node.layer()
            if layer is None:
                continue
            try:
                from qgis.core import QgsMapLayerType

                if layer.type() != QgsMapLayerType.VectorLayer:
                    continue
            except Exception:
                continue

            status = []
            status.append("editable" if layer.isEditable() else "read-only")
            if not node.isVisible():
                status.insert(0, "hidden")
            label = f"{layer.name()} ({', '.join(status)})"
            layer_items.append(
                {
                    "id": layer.id(),
                    "name": layer.name(),
                    "label": label,
                    "visible": node.isVisible(),
                    "editable": layer.isEditable(),
                }
            )

        self.dock.populate_layers(layer_items, keep_existing_checks=True)
        self.map_tool.set_target_layer_ids(self.dock.checked_layer_ids())

    def _icon_path(self, icon_name):
        return os.path.join(self.plugin_dir, "icons", icon_name)
