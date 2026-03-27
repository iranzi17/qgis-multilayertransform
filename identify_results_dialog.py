from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class IdentifyResultsDockWidget(QDockWidget):
    resultSelected = pyqtSignal(str, int)
    openRequested = pyqtSignal(str, int)
    zoomRequested = pyqtSignal(str, int)
    clearRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Identify Results", parent)
        self.setObjectName("MultiLayerTransformIdentifyResultsDock")
        self._building_ui = False
        self._setup_ui()

    def _setup_ui(self):
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Feature", "Value"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(False)
        layout.addWidget(self.tree)

        buttons = QHBoxLayout()
        self.open_button = QPushButton("Open Form")
        self.zoom_button = QPushButton("Zoom To")
        self.clear_button = QPushButton("Clear")
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.zoom_button)
        buttons.addStretch(1)
        buttons.addWidget(self.clear_button)
        layout.addLayout(buttons)

        container.setLayout(layout)
        self.setWidget(container)

        self.tree.currentItemChanged.connect(self._emit_result_selected)
        self.tree.itemDoubleClicked.connect(self._handle_item_double_clicked)
        self.open_button.clicked.connect(self._emit_open_requested)
        self.zoom_button.clicked.connect(self._emit_zoom_requested)
        self.clear_button.clicked.connect(self.clearRequested)

        self._update_buttons()

    def set_results(self, results):
        results = list(results or [])
        current_target = self.current_target()

        self._building_ui = True
        self.tree.clear()
        first_selectable = None

        for result in results:
            target = (str(result.get("layer_id")), int(result.get("feature_id", -1)))
            title = f"{result.get('layer_name', 'Layer')} - {result.get('display', 'Feature')}"
            top_item = QTreeWidgetItem([title, ""])
            top_item.setData(0, Qt.UserRole, target)
            self.tree.addTopLevelItem(top_item)

            for attribute in result.get("attributes", []):
                child = QTreeWidgetItem([attribute.get("name", ""), attribute.get("value", "")])
                child.setData(0, Qt.UserRole, target)
                top_item.addChild(child)

            derived = result.get("derived", [])
            if derived:
                derived_item = QTreeWidgetItem(["(Derived)", ""])
                derived_item.setData(0, Qt.UserRole, target)
                top_item.addChild(derived_item)
                for derived_row in derived:
                    child = QTreeWidgetItem([derived_row.get("name", ""), derived_row.get("value", "")])
                    child.setData(0, Qt.UserRole, target)
                    derived_item.addChild(child)

            actions_item = QTreeWidgetItem(["(Actions)", ""])
            actions_item.setData(0, Qt.UserRole, target)
            top_item.addChild(actions_item)

            open_item = QTreeWidgetItem(["Open feature form", ""])
            open_item.setData(0, Qt.UserRole, target)
            open_item.setData(0, Qt.UserRole + 1, "open")
            actions_item.addChild(open_item)

            zoom_item = QTreeWidgetItem(["Zoom to feature", ""])
            zoom_item.setData(0, Qt.UserRole, target)
            zoom_item.setData(0, Qt.UserRole + 1, "zoom")
            actions_item.addChild(zoom_item)

            top_item.setExpanded(True)
            if current_target == target or first_selectable is None:
                first_selectable = top_item

        if first_selectable is not None:
            self.tree.setCurrentItem(first_selectable)

        self._building_ui = False
        self._update_buttons()
        self.tree.resizeColumnToContents(0)

        if not results:
            self.hide()
            return

        self.show()
        self.raise_()
        self.activateWindow()
        if self.tree.currentItem() is not None:
            self._emit_result_selected()

    def current_target(self):
        item = self.tree.currentItem()
        while item is not None:
            target = item.data(0, Qt.UserRole)
            if target:
                return str(target[0]), int(target[1])
            item = item.parent()
        return None, None

    def clear_results(self):
        self._building_ui = True
        self.tree.clear()
        self._building_ui = False
        self._update_buttons()
        self.hide()

    def _emit_result_selected(self, *args):
        if self._building_ui:
            return
        self._update_buttons()
        layer_id, feature_id = self.current_target()
        if layer_id is not None and feature_id is not None:
            self.resultSelected.emit(layer_id, feature_id)

    def _emit_open_requested(self):
        layer_id, feature_id = self.current_target()
        if layer_id is not None and feature_id is not None:
            self.openRequested.emit(layer_id, feature_id)

    def _emit_zoom_requested(self):
        layer_id, feature_id = self.current_target()
        if layer_id is not None and feature_id is not None:
            self.zoomRequested.emit(layer_id, feature_id)

    def _handle_item_double_clicked(self, item, column):
        action = item.data(0, Qt.UserRole + 1)
        if action == "zoom":
            self._emit_zoom_requested()
            return
        self._emit_open_requested()

    def _update_buttons(self):
        has_target = self.current_target()[0] is not None
        has_items = self.tree.topLevelItemCount() > 0
        self.open_button.setEnabled(has_target)
        self.zoom_button.setEnabled(has_target)
        self.clear_button.setEnabled(has_items)
