from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class TransformDockWidget(QDockWidget):
    modeChanged = pyqtSignal(str)
    pivotChanged = pyqtSignal(str)
    snapChanged = pyqtSignal(float)
    selectedLayersOnlyChanged = pyqtSignal(bool)
    showPivotMarkerChanged = pyqtSignal(bool)
    previewColorChanged = pyqtSignal(QColor)
    manualAnglePreviewRequested = pyqtSignal(float)
    manualScalePreviewRequested = pyqtSignal(float, float)
    applyRequested = pyqtSignal()
    cancelRequested = pyqtSignal()
    refreshRequested = pyqtSignal()
    clearSelectionRequested = pyqtSignal()
    targetLayersChanged = pyqtSignal(list)
    selectionOperationChanged = pyqtSignal(str)
    identifyResultSelected = pyqtSignal(str, int)
    identifyOpenRequested = pyqtSignal(str, int)
    identifyZoomRequested = pyqtSignal(str, int)
    identifyClearRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("MultiLayerTransform", parent)
        self.setObjectName("MultiLayerTransformDock")
        self._building_ui = False
        self._preview_color = QColor("#ff7f0e")
        self._syncing_scale_spins = False
        self._setup_ui()

    def _setup_ui(self):
        self._building_ui = True
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        setup_group = QGroupBox("Transform")
        setup_form = QFormLayout(setup_group)
        setup_form.setLabelAlignment(Qt.AlignLeft)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Select", "select")
        self.mode_combo.addItem("Quick Select", "quick_select")
        self.mode_combo.addItem("Identify", "identify")
        self.mode_combo.addItem("Move", "move")
        self.mode_combo.addItem("Rotate", "rotate")
        self.mode_combo.addItem("Scale", "scale")
        self.mode_combo.addItem("Orthogonalize 4 points", "orthogonalize")
        setup_form.addRow("Mode", self.mode_combo)

        self.selection_op_combo = QComboBox()
        self.selection_op_combo.addItem("Replace", "replace")
        self.selection_op_combo.addItem("Add", "add")
        self.selection_op_combo.addItem("Remove", "remove")
        self.selection_op_combo.setToolTip(
            "Default selection behavior in Select mode. Keyboard modifiers still work: Shift adds and Ctrl removes."
        )
        setup_form.addRow("Select op", self.selection_op_combo)

        self.pivot_combo = QComboBox()
        self.pivot_combo.addItem("Selection centroid", "centroid")
        self.pivot_combo.addItem("Pick point", "pick")
        setup_form.addRow("Pivot", self.pivot_combo)

        self.snap_combo = QComboBox()
        self.snap_combo.addItem("None", 0.0)
        self.snap_combo.addItem("15 deg", 15.0)
        self.snap_combo.addItem("30 deg", 30.0)
        self.snap_combo.addItem("45 deg", 45.0)
        self.snap_combo.addItem("90 deg", 90.0)
        setup_form.addRow("Snap", self.snap_combo)

        self.angle_spin = QDoubleSpinBox()
        self.angle_spin.setDecimals(2)
        self.angle_spin.setRange(-360.0, 360.0)
        self.angle_spin.setSingleStep(1.0)
        self.angle_spin.setSuffix(" deg")
        self.angle_spin.setToolTip("Manual rotation angle. Positive values rotate clockwise.")
        setup_form.addRow("Angle", self.angle_spin)

        self.preview_angle_button = QPushButton("Preview angle")
        self.preview_angle_button.setToolTip("Preview a manual rotation using the angle above.")
        setup_form.addRow("", self.preview_angle_button)

        self.scale_x_spin = QDoubleSpinBox()
        self.scale_x_spin.setDecimals(4)
        self.scale_x_spin.setRange(-1000.0, 1000.0)
        self.scale_x_spin.setSingleStep(0.1)
        self.scale_x_spin.setValue(1.0)
        self.scale_x_spin.setToolTip("Manual scale factor on the X axis.")
        setup_form.addRow("Scale X", self.scale_x_spin)

        self.scale_y_spin = QDoubleSpinBox()
        self.scale_y_spin.setDecimals(4)
        self.scale_y_spin.setRange(-1000.0, 1000.0)
        self.scale_y_spin.setSingleStep(0.1)
        self.scale_y_spin.setValue(1.0)
        self.scale_y_spin.setToolTip("Manual scale factor on the Y axis.")
        setup_form.addRow("Scale Y", self.scale_y_spin)

        self.scale_link_checkbox = QCheckBox("Lock X/Y factors")
        self.scale_link_checkbox.setChecked(True)
        self.scale_link_checkbox.setToolTip("Keep the X and Y scale factors identical for proportional scaling.")
        setup_form.addRow("", self.scale_link_checkbox)

        self.preview_scale_button = QPushButton("Preview scale")
        self.preview_scale_button.setToolTip("Preview manual scale factors using the current pivot.")
        setup_form.addRow("", self.preview_scale_button)

        layout.addWidget(setup_group)

        layers_group = QGroupBox("Target Layers")
        layers_layout = QVBoxLayout(layers_group)
        layers_layout.setContentsMargins(10, 10, 10, 10)

        self.selected_layers_checkbox = QCheckBox("Use checked target layers instead of all visible layers")
        layers_layout.addWidget(self.selected_layers_checkbox)

        layers_hint = QLabel(
            "Check the layers you want to participate. Quick Select, Select, and Identify can search visible vector layers; "
            "Move/Rotate/Scale/Orthogonalize only change editable layers."
        )
        layers_hint.setWordWrap(True)
        layers_layout.addWidget(layers_hint)

        self.layers_list = QListWidget()
        self.layers_list.setMinimumHeight(140)
        self.layers_list.setAlternatingRowColors(True)
        layers_layout.addWidget(self.layers_list)

        layer_buttons = QHBoxLayout()
        self.check_all_layers_button = QPushButton("All")
        self.check_visible_layers_button = QPushButton("Visible")
        self.uncheck_all_layers_button = QPushButton("None")
        layer_buttons.addWidget(self.check_all_layers_button)
        layer_buttons.addWidget(self.check_visible_layers_button)
        layer_buttons.addWidget(self.uncheck_all_layers_button)
        layer_buttons.addStretch(1)
        layers_layout.addLayout(layer_buttons)

        layout.addWidget(layers_group)

        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)
        options_layout.setContentsMargins(10, 10, 10, 10)

        self.show_pivot_checkbox = QCheckBox("Show pivot marker")
        self.show_pivot_checkbox.setChecked(True)
        options_layout.addWidget(self.show_pivot_checkbox)

        preview_layout = QHBoxLayout()
        preview_label = QLabel("Preview color")
        self.preview_color_button = QPushButton("Change")
        self.preview_color_button.setFixedWidth(90)
        preview_layout.addWidget(preview_label)
        preview_layout.addStretch(1)
        preview_layout.addWidget(self.preview_color_button)
        options_layout.addLayout(preview_layout)
        layout.addWidget(options_group)

        info_group = QGroupBox("Live Info")
        info_layout = QVBoxLayout(info_group)
        info_layout.setContentsMargins(10, 10, 10, 10)
        self.selection_label = QLabel("Layers: 0 | Features: 0")
        self.selection_label.setWordWrap(True)
        info_layout.addWidget(self.selection_label)
        self.current_angle_label = QLabel("Current angle: 0.00 deg")
        info_layout.addWidget(self.current_angle_label)
        self.current_scale_label = QLabel("Current scale: x=1.0000 | y=1.0000")
        info_layout.addWidget(self.current_scale_label)
        self.info_label = QLabel("Activate Quick Select, Identify, Select, Move, Rotate, Scale, or Orthogonalize.")
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        info_layout.addWidget(self.info_label)
        layout.addWidget(info_group)

        identify_group = QGroupBox("Identify Results")
        identify_layout = QVBoxLayout(identify_group)
        identify_layout.setContentsMargins(10, 10, 10, 10)

        self.identify_summary_label = QLabel("Results: 0")
        identify_layout.addWidget(self.identify_summary_label)

        self.identify_results_list = QListWidget()
        self.identify_results_list.setMinimumHeight(160)
        self.identify_results_list.setAlternatingRowColors(True)
        identify_layout.addWidget(self.identify_results_list)

        identify_buttons = QHBoxLayout()
        self.identify_open_button = QPushButton("Open Form")
        self.identify_zoom_button = QPushButton("Zoom To")
        self.identify_clear_button = QPushButton("Clear Results")
        identify_buttons.addWidget(self.identify_open_button)
        identify_buttons.addWidget(self.identify_zoom_button)
        identify_buttons.addStretch(1)
        identify_buttons.addWidget(self.identify_clear_button)
        identify_layout.addLayout(identify_buttons)

        identify_group.hide()
        layout.addWidget(identify_group)

        button_row = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.clear_selection_button = QPushButton("Clear Selection")
        self.apply_button = QPushButton("Apply")
        self.cancel_button = QPushButton("Cancel")
        button_row.addWidget(self.refresh_button)
        button_row.addWidget(self.clear_selection_button)
        button_row.addStretch(1)
        button_row.addWidget(self.apply_button)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

        shortcuts_label = QLabel(
            "Shortcuts: Shift = add, Ctrl = remove in Quick Select/Select mode. "
            "Ctrl during Move/Rotate/Scale/Orthogonalize apply = duplicate and transform. "
            "Double-click an identify result to open its feature form. Right click or Esc = cancel."
        )
        shortcuts_label.setWordWrap(True)
        layout.addWidget(shortcuts_label)

        layout.addStretch(1)
        container.setLayout(layout)
        self.setWidget(container)

        self.mode_combo.currentIndexChanged.connect(self._emit_mode_changed)
        self.selection_op_combo.currentIndexChanged.connect(self._emit_selection_operation_changed)
        self.pivot_combo.currentIndexChanged.connect(self._emit_pivot_changed)
        self.snap_combo.currentIndexChanged.connect(self._emit_snap_changed)
        self.selected_layers_checkbox.toggled.connect(self.selectedLayersOnlyChanged)
        self.show_pivot_checkbox.toggled.connect(self.showPivotMarkerChanged)
        self.preview_color_button.clicked.connect(self._choose_preview_color)
        self.preview_angle_button.clicked.connect(self._emit_manual_angle_preview)
        self.preview_scale_button.clicked.connect(self._emit_manual_scale_preview)
        self.refresh_button.clicked.connect(self.refreshRequested)
        self.clear_selection_button.clicked.connect(self.clearSelectionRequested)
        self.apply_button.clicked.connect(self.applyRequested)
        self.cancel_button.clicked.connect(self.cancelRequested)
        self.layers_list.itemChanged.connect(self._emit_target_layers_changed)
        self.check_all_layers_button.clicked.connect(self._check_all_layers)
        self.check_visible_layers_button.clicked.connect(self._check_visible_layers)
        self.uncheck_all_layers_button.clicked.connect(self._uncheck_all_layers)
        self.scale_link_checkbox.toggled.connect(self._handle_scale_link_toggled)
        self.scale_x_spin.valueChanged.connect(self._handle_scale_x_changed)
        self.scale_y_spin.valueChanged.connect(self._handle_scale_y_changed)
        self.identify_results_list.currentItemChanged.connect(self._emit_identify_result_selected)
        self.identify_results_list.itemDoubleClicked.connect(lambda *_: self._emit_identify_open_requested())
        self.identify_open_button.clicked.connect(self._emit_identify_open_requested)
        self.identify_zoom_button.clicked.connect(self._emit_identify_zoom_requested)
        self.identify_clear_button.clicked.connect(self.identifyClearRequested)

        self._update_preview_color_button()
        self._update_mode_controls()
        self._building_ui = False

    def _emit_mode_changed(self):
        if self._building_ui:
            return
        self._update_mode_controls()
        self.modeChanged.emit(self.mode_combo.currentData())

    def _emit_selection_operation_changed(self):
        if not self._building_ui:
            self.selectionOperationChanged.emit(self.selection_operation())

    def _emit_pivot_changed(self):
        if not self._building_ui:
            self.pivotChanged.emit(self.pivot_combo.currentData())

    def _emit_snap_changed(self):
        if not self._building_ui:
            self.snapChanged.emit(float(self.snap_combo.currentData()))

    def _emit_manual_angle_preview(self):
        self.manualAnglePreviewRequested.emit(self.manual_angle())

    def _emit_manual_scale_preview(self):
        scale_x, scale_y = self.manual_scale_factors()
        self.manualScalePreviewRequested.emit(scale_x, scale_y)

    def _choose_preview_color(self):
        color = QColorDialog.getColor(self._preview_color, self, "Preview Color")
        if not color.isValid():
            return
        self._preview_color = color
        self._update_preview_color_button()
        self.previewColorChanged.emit(color)

    def _update_preview_color_button(self):
        self.preview_color_button.setStyleSheet(
            "QPushButton {"
            f"background-color: {self._preview_color.name()};"
            "color: black; border: 1px solid #666; padding: 4px 10px; }"
        )

    def _update_mode_controls(self):
        mode = self.current_mode()
        is_select = mode in {"select", "quick_select"}
        is_identify = mode == "identify"
        is_rotate = mode == "rotate"
        is_scale = mode == "scale"
        is_transform = mode in {"move", "rotate", "scale", "orthogonalize"}
        has_identify_target = self.identify_results_list.currentItem() is not None
        self.selection_op_combo.setEnabled(is_select)
        self.pivot_combo.setEnabled(is_rotate or is_scale)
        self.snap_combo.setEnabled(is_rotate)
        self.angle_spin.setEnabled(is_rotate)
        self.preview_angle_button.setEnabled(is_rotate)
        self.current_angle_label.setVisible(is_rotate)
        self.scale_x_spin.setEnabled(is_scale)
        self.scale_y_spin.setEnabled(is_scale)
        self.scale_link_checkbox.setEnabled(is_scale)
        self.preview_scale_button.setEnabled(is_scale)
        self.current_scale_label.setVisible(is_scale)
        self.apply_button.setEnabled(is_transform)
        self.cancel_button.setEnabled(is_transform)
        self.show_pivot_checkbox.setEnabled(is_rotate or is_scale)
        self.identify_results_list.setEnabled(is_identify)
        self.identify_open_button.setEnabled(is_identify and has_identify_target)
        self.identify_zoom_button.setEnabled(is_identify and has_identify_target)
        self.identify_clear_button.setEnabled(is_identify and self.identify_results_list.count() > 0)

    def current_mode(self):
        return self.mode_combo.currentData()

    def selection_operation(self):
        return self.selection_op_combo.currentData()

    def current_pivot_mode(self):
        return self.pivot_combo.currentData()

    def current_snap_angle(self):
        return float(self.snap_combo.currentData())

    def manual_angle(self):
        return float(self.angle_spin.value())

    def manual_scale_factors(self):
        return float(self.scale_x_spin.value()), float(self.scale_y_spin.value())

    def only_selected_layers(self):
        return self.selected_layers_checkbox.isChecked()

    def show_pivot_marker(self):
        return self.show_pivot_checkbox.isChecked()

    def preview_color(self):
        return QColor(self._preview_color)

    def checked_layer_ids(self):
        result = []
        for i in range(self.layers_list.count()):
            item = self.layers_list.item(i)
            if item.checkState() == Qt.Checked:
                result.append(item.data(Qt.UserRole))
        return result

    def populate_layers(self, layer_items, keep_existing_checks=True):
        existing_checks = {}
        if keep_existing_checks:
            for i in range(self.layers_list.count()):
                item = self.layers_list.item(i)
                existing_checks[item.data(Qt.UserRole)] = item.checkState()

        self._building_ui = True
        self.layers_list.clear()
        for layer_item in layer_items:
            item = QListWidgetItem(layer_item.get("label", layer_item.get("name", "Layer")))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setData(Qt.UserRole, layer_item["id"])
            default_state = Qt.Checked if layer_item.get("visible", True) else Qt.Unchecked
            item.setCheckState(existing_checks.get(layer_item["id"], default_state))
            self.layers_list.addItem(item)
        self._building_ui = False
        self._emit_target_layers_changed()

    def set_mode(self, mode):
        index = self.mode_combo.findData(mode)
        if index < 0:
            return
        self._building_ui = True
        self.mode_combo.setCurrentIndex(index)
        self._update_mode_controls()
        self._building_ui = False

    def set_selection_operation(self, operation):
        index = self.selection_op_combo.findData(operation)
        if index >= 0:
            self._building_ui = True
            self.selection_op_combo.setCurrentIndex(index)
            self._building_ui = False

    def set_pivot_mode(self, pivot_mode):
        index = self.pivot_combo.findData(pivot_mode)
        if index >= 0:
            self._building_ui = True
            self.pivot_combo.setCurrentIndex(index)
            self._building_ui = False

    def set_snap_angle(self, snap_angle):
        index = self.snap_combo.findData(float(snap_angle))
        if index >= 0:
            self._building_ui = True
            self.snap_combo.setCurrentIndex(index)
            self._building_ui = False

    def set_show_pivot_marker(self, enabled):
        self._building_ui = True
        self.show_pivot_checkbox.setChecked(bool(enabled))
        self._building_ui = False

    def set_preview_color(self, color):
        self._preview_color = QColor(color)
        self._update_preview_color_button()

    def set_selection_summary(self, layer_count, feature_count):
        self.selection_label.setText(f"Layers: {layer_count} | Features: {feature_count}")

    def set_current_angle(self, angle):
        self.current_angle_label.setText(f"Current angle: {float(angle):.2f} deg")

    def set_current_scale(self, scale_x, scale_y):
        self.current_scale_label.setText(f"Current scale: x={float(scale_x):.4f} | y={float(scale_y):.4f}")

    def set_live_info(self, text):
        self.info_label.setText(text)

    def current_identify_target(self):
        item = self.identify_results_list.currentItem()
        if item is None:
            return None, None
        layer_id, feature_id = item.data(Qt.UserRole) or (None, None)
        if layer_id is None or feature_id is None:
            return None, None
        return str(layer_id), int(feature_id)

    def set_identify_results(self, results):
        results = list(results or [])
        current_target = self.current_identify_target()

        self._building_ui = True
        self.identify_results_list.clear()
        selected_row = 0
        for idx, result in enumerate(results):
            title = result.get("title", "Feature")
            subtitle = result.get("subtitle", "")
            text = title if not subtitle else f"{title}\n{subtitle}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, (result.get("layer_id"), int(result.get("feature_id", -1))))
            self.identify_results_list.addItem(item)
            target = (str(result.get("layer_id")), int(result.get("feature_id", -1)))
            if current_target == target:
                selected_row = idx
        if results:
            self.identify_results_list.setCurrentRow(selected_row)
        self._building_ui = False

        self.identify_summary_label.setText(f"Results: {len(results)}")
        self._update_mode_controls()
        if results and self.identify_results_list.currentItem() is not None:
            self._emit_identify_result_selected()

    def clear_identify_results(self):
        self.set_identify_results([])

    def _emit_target_layers_changed(self, *args):
        if not self._building_ui:
            self.targetLayersChanged.emit(self.checked_layer_ids())

    def _emit_identify_result_selected(self, *args):
        if self._building_ui:
            return
        self._update_mode_controls()
        layer_id, feature_id = self.current_identify_target()
        if layer_id is not None and feature_id is not None:
            self.identifyResultSelected.emit(layer_id, feature_id)

    def _emit_identify_open_requested(self):
        layer_id, feature_id = self.current_identify_target()
        if layer_id is not None and feature_id is not None:
            self.identifyOpenRequested.emit(layer_id, feature_id)

    def _emit_identify_zoom_requested(self):
        layer_id, feature_id = self.current_identify_target()
        if layer_id is not None and feature_id is not None:
            self.identifyZoomRequested.emit(layer_id, feature_id)

    def _handle_scale_link_toggled(self, enabled):
        if enabled:
            self._sync_scale_spin_pair(self.scale_x_spin.value(), self.scale_x_spin.value())

    def _handle_scale_x_changed(self, value):
        if self._syncing_scale_spins or not self.scale_link_checkbox.isChecked():
            return
        self._sync_scale_spin_pair(value, value)

    def _handle_scale_y_changed(self, value):
        if self._syncing_scale_spins or not self.scale_link_checkbox.isChecked():
            return
        self._sync_scale_spin_pair(value, value)

    def _sync_scale_spin_pair(self, scale_x, scale_y):
        self._syncing_scale_spins = True
        self.scale_x_spin.setValue(float(scale_x))
        self.scale_y_spin.setValue(float(scale_y))
        self._syncing_scale_spins = False

    def _set_all_layers_check_state(self, state):
        self._building_ui = True
        for i in range(self.layers_list.count()):
            self.layers_list.item(i).setCheckState(state)
        self._building_ui = False
        self._emit_target_layers_changed()

    def _check_all_layers(self):
        self._set_all_layers_check_state(Qt.Checked)

    def _check_visible_layers(self):
        self._building_ui = True
        for i in range(self.layers_list.count()):
            item = self.layers_list.item(i)
            item.setCheckState(Qt.Checked if "(hidden" not in item.text().lower() else Qt.Unchecked)
        self._building_ui = False
        self._emit_target_layers_changed()

    def _uncheck_all_layers(self):
        self._set_all_layers_check_state(Qt.Unchecked)
