"""
    PackageDialog class for exporting QGIS projects to QField.

    Note: This plugin is designed to facilitate the export of QGIS projects to QField.
    Plugin Name: AuQCBMS 
    Plugin Version: 1.0.2
    Copyright (C) 2024 GMDev Team. All rights reserved.

    ------------------------------------------

    Modified Version: QField 4.11.0
Copyright (C) 2024 QField Team.
"""

import os
import subprocess
import json
import traceback
import shutil  # Add this import at the top of your file
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from libqfieldsync.layer import LayerSource, SyncAction
from libqfieldsync.offline_converter import ExportType, OfflineConverter, PackagingCanceledError
import sip
import sys
from qgis import utils
# TODO this try/catch was added due to module structure changes in QFS 4.8.0. Remove this as enough time has passed since March 2024.
try:
    from libqfieldsync.offliners import QgisCoreOffliner
except ModuleNotFoundError:
    from qgis.PyQt.QtCore import QCoreApplication, QTimer
    from qgis.PyQt.QtWidgets import QMessageBox

    QMessageBox.warning(
        None,
        QCoreApplication.translate("AuQCBMS", "Please restart QGIS"),
        QCoreApplication.translate(
            "AuQCBMS", "To finalize the AuQCBMS upgrade, please restart QGIS."
        ),
    )
from libqfieldsync.project import ProjectConfiguration
from libqfieldsync.project_checker import ProjectChecker
from libqfieldsync.utils.file_utils import fileparts
from libqfieldsync.utils.qgis import get_project_title
from qgis.core import Qgis, QgsApplication, QgsProject, QgsLayerTreeGroup, QgsLayerTreeLayer, QgsVectorLayer, QgsRasterLayer, QgsVectorFileWriter, QgsTask, QgsTaskManager, QgsSnappingConfig, QgsTolerance, QgsGeometry, QgsFeatureRequest, QgsCoordinateTransform, QgsMapLayer, NULL
from qgis.PyQt.QtCore import QDir, Qt, QUrl, QTimer, QEvent, QVariant
from qgis.PyQt.QtGui import QIcon, QBrush, QPixmap, QImage, QPainter
from qgis.PyQt.QtSvg import QSvgRenderer
from qgis.PyQt.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox, QLabel, QListWidget, QListWidgetItem, QWidget, QHBoxLayout, QPushButton, QComboBox, QGridLayout, QGroupBox, QSizePolicy, QScrollArea, QFrame, QVBoxLayout, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QTreeWidget, QTreeWidgetItem, QTabWidget, QLineEdit, QInputDialog, QFileDialog, QToolButton, QAbstractItemView
from qgis.PyQt.uic import loadUiType
from .checker_feedback_table import CheckerFeedbackTable
from ..core.preferences import Preferences
from .dirs_to_copy_widget import DirsToCopyWidget
from .project_configuration_dialog import ProjectConfigurationDialog
import processing
from ..utils.qt_utils import make_folder_selector
from ..utils.style_utils import (
    get_qml_styles_dir,
    get_available_qml_display_names,
    auto_detect_qml_for_layer,
    apply_qml_to_layer,
    apply_embedded_qml_styles,
)
from tempfile import TemporaryDirectory
import re
from qgis.utils import iface
from qgis.gui import QgsFileWidget
from PyQt5.QtCore import QSettings
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QFileDialog

DialogUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/package_dialog.ui")
)

BUILTIN_PRESETS = {
    "EA Field Verification": [
        # Top-level parent group
        {
            "path": ["For Verification"],
            "is_group": True,
            "checked": True
        },
        # Sub-folder inside "For Verification"
        {
            "path": ["For Verification", "Delineated EA"],
            "is_group": True,
            "checked": True
        },
        # Sub-folder inside "For Verification"
        {
            "path": ["For Verification", "Merged EA"],
            "is_group": True,
            "checked": True
        },
        # Another top-level parent group
        {
            "path": ["Base Layers"],
            "is_group": True,
            "checked": True
        }
    ],
    "Form 2 Layout": [
        {
            "path": ["Geotagged Building Point"],
            "is_group": True,
            "checked": True
        },
        {
            "path": ["Reference Building Point"],
            "is_group": True,
            "checked": True
        },
        {
            "path": ["Base Layers"],
            "is_group": True,
            "checked": True
        }
    ]
}


class MultiSelectDialog(QDialog):
    def __init__(self, title, label_text, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.adjustSize()
        self.resize(700, 240)

        
        layout = QVBoxLayout(self)
        
        self.label = QLabel(label_text)
        layout.addWidget(self.label)
        
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        self.list_widget.addItems(items)
        layout.addWidget(self.list_widget)
        
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
        
    def selected_items(self):
        return [item.text() for item in self.list_widget.selectedItems()]


class LayerGroupsTreeWidget(QTreeWidget):
    def dragEnterEvent(self, event):
        if event.source() == self:
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.source() == self:
            super().dragMoveEvent(event)
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        selected_items = self.selectedItems()
        if not selected_items:
            event.ignore()
            return

        # Save combo widgets for all dragged items (layers or children inside dragged groups)
        self._dragged_qml = {}
        self._dragged_assigned = {}

        def record_combos(item):
            name = item.text(0) or item.text(1)
            qml_combo = self.itemWidget(item, 2)
            if qml_combo:
                self._dragged_qml[name] = qml_combo.currentText()
            assigned_combo = self.itemWidget(item, 1)
            if assigned_combo:
                self._dragged_assigned[name] = assigned_combo.currentData()
            for c in range(item.childCount()):
                record_combos(item.child(c))

        for item in selected_items:
            record_combos(item)

        super().dropEvent(event)
        QTimer.singleShot(0, self._restore_missing_combos)

    def _restore_missing_combos(self):
        def check_and_restore(item):
            child_name = item.text(0) or item.text(1)
            is_layer = item.data(0, Qt.UserRole) is not None
            if is_layer:
                dlg = self.parent()
                while dlg and not hasattr(dlg, '_create_qml_combo_for_layer'):
                    dlg = dlg.parent()
                
                # Restore Assigned Role combo in Col 1 if missing
                if self.itemWidget(item, 1) is None and dlg:
                    preset_id = getattr(self, '_dragged_assigned', {}).get(child_name, None)
                    dlg._create_assigned_layer_combo_for_layer(item, child_name, preset_id=preset_id)

                # Restore QML Style combo in Col 2 if missing
                if self.itemWidget(item, 2) is None and dlg:
                    preset_qml = getattr(self, '_dragged_qml', {}).get(child_name, "")
                    dlg._create_qml_combo_for_layer(item, child_name, preset_qml=preset_qml)

            for c in range(item.childCount()):
                check_and_restore(item.child(c))

        for i in range(self.topLevelItemCount()):
            check_and_restore(self.topLevelItem(i))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            selected_items = self.selectedItems()
            if selected_items:
                first_state = selected_items[0].checkState(0)
                new_state = Qt.Unchecked if first_state == Qt.Checked else Qt.Checked

                def set_check_recursive(item, state):
                    item.setCheckState(0, state)
                    for i in range(item.childCount()):
                        set_check_recursive(item.child(i), state)

                self.blockSignals(True)
                for item in selected_items:
                    set_check_recursive(item, new_state)
                self.blockSignals(False)

                event.accept()
                return

        if event.modifiers() & Qt.AltModifier:
            dlg = self.parent()
            while dlg and not hasattr(dlg, '_on_move_item_up'):
                dlg = dlg.parent()

            if dlg:
                if event.key() == Qt.Key_Up:
                    dlg._on_move_item_up()
                    event.accept()
                    return
                elif event.key() == Qt.Key_Down:
                    dlg._on_move_item_down()
                    event.accept()
                    return
                elif event.key() == Qt.Key_Left:
                    dlg._on_move_item_out()
                    event.accept()
                    return
                elif event.key() == Qt.Key_Right:
                    dlg._on_move_item_in()
                    event.accept()
                    return
        super().keyPressEvent(event)


class PackageDialog(QDialog, DialogUi):
    def _normalized_layer_name(self, name):
        """Strip trailing count labels like ' [123]' from a layer display name."""
        if not name:
            return ""
        return re.sub(r"\s*\[\d+\]\s*$", "", name).strip()

    def _ensure_ea_update_not_offline_and_writable(self):
        """Keep _ea_update layers writable and out of OFFLINE sync action."""
        project = QgsProject.instance()

        for layer in project.mapLayers().values():
            layer_name = self._normalized_layer_name(layer.name()).lower()
            if not layer_name.endswith('_ea_update'):
                continue

            try:
                if isinstance(layer, QgsVectorLayer):
                    layer.setReadOnly(False)
                project.writeEntry("ReadOnlyLayers", layer.id(), "False")
            except Exception:
                pass

            try:
                layer_source = LayerSource(layer)
                available_actions = [a for a, _ in layer_source.available_actions]
                if layer_source.action == SyncAction.OFFLINE:
                    candidate = None
                    if hasattr(SyncAction, "COPY") and SyncAction.COPY in available_actions:
                        candidate = SyncAction.COPY
                    else:
                        for action in available_actions:
                            if action not in (SyncAction.OFFLINE, SyncAction.REMOVE):
                                candidate = action
                                break
                    if candidate is not None:
                        layer_source.action = candidate
                        layer_source.apply()
            except Exception:
                pass

    def filter_geocode_by_citymun(self):
        """Filter geocode_dropdown based on selected citymun_dropdown value."""
        selected_citymun = self.citymun_dropdown.currentText()
        if selected_citymun.lower() == "all":
            self.populate_geocode_dropdown()
            return
        citymun_prefix = selected_citymun.split('_')[0]

        # Get the layer
        selected_layer = None
        selected_data = self.layer_dropdown.currentData()
        if isinstance(selected_data, str):
            selected_layer = QgsProject.instance().mapLayer(selected_data)
        if selected_layer is None and self.layer_dropdown.currentText():
            sel_name = self.layer_dropdown.currentText()
            for lyr in QgsProject.instance().mapLayers().values():
                if lyr.name() == sel_name:
                    selected_layer = lyr
                    break

        self.geocode_dropdown.clear()
        desired = '_ea' if self.output_dropdown.currentText() == self.tr('EA Level') else '_bgy'
        is_ea = self.output_dropdown.currentText() == self.tr('EA Level')
        if selected_layer and selected_layer.name().endswith(desired):
            geocode_index = -1
            for fname in (['ea_geocode', 'geocode', 'ea_code', 'code'] if is_ea else ['geocode', 'bgy_code', 'ea_geocode', 'code']):
                idx = selected_layer.fields().indexOf(fname)
                if idx != -1:
                    geocode_index = idx
                    break
            geocode_name_index = selected_layer.fields().indexOf('barangay')
            if geocode_name_index == -1:
                geocode_name_index = selected_layer.fields().indexOf('Barangay')
            if geocode_index != -1 and geocode_name_index != -1:
                filtered_values = [
                    f"{feature.attributes()[geocode_index]}_{feature.attributes()[geocode_name_index]}"
                    for feature in selected_layer.getFeatures()
                    if str(feature.attributes()[geocode_index])[:5] == citymun_prefix
                ]
                self.geocode_dropdown.addItems(sorted(filtered_values))
                print(f"Filtered geocode values for citymun {selected_citymun}: {filtered_values}")
            else:
                print("Missing geocode or barangay field.")

    def _get_active_project_layers(self):
        """Return a list of layer names currently in the QGIS project."""
        project = QgsProject.instance()
        return [layer.name() for layer in project.mapLayers().values()]

    def _layer_type_key(self, layer_name):
        """Extract the layer type suffix after the first '_'.

        E.g. '813_railroad' → 'railroad', '456_bldg_point' → 'bldg_point'.
        If it's a description like 'Building points (*_bldg_point)', extract 'bldg_point'.
        """
        import re
        match = re.search(r'\(\*_(.*?)\)', layer_name)
        if match:
            return match.group(1)
            
        idx = layer_name.find('_')
        return layer_name[idx + 1:] if idx >= 0 else layer_name

    def _get_already_grouped_layers(self):
        """Return a set of layer names that are checked in any group."""
        assigned = set()
        for i in range(self.layer_groups_tree.topLevelItemCount()):
            group_item = self.layer_groups_tree.topLevelItem(i)
            for j in range(group_item.childCount()):
                layer_item = group_item.child(j)
                if layer_item.checkState(0) == Qt.Checked:
                    assigned.add(layer_item.text(0))
        return assigned

    def _update_layer_assignment_ui(self):
        """Rebuilds the tree widget mirroring the QGIS layers panel with Role and QML style assignments."""
        if not hasattr(self, 'layer_groups_tree'):
            return

        self.layer_groups_tree.clear()
        self.layer_groups_tree.setColumnCount(3)
        self.layer_groups_tree.setHeaderLabels([self.tr("Layer / Group"), self.tr("Assigned Role"), self.tr("QML Style")])

        def build_tree(qgs_node, parent_item):
            from qgis.core import QgsLayerTreeGroup, QgsLayerTreeLayer
            
            for child in qgs_node.children():
                if isinstance(child, QgsLayerTreeGroup):
                    group_item = QTreeWidgetItem(parent_item)
                    group_item.setText(0, child.name())
                    group_item.setData(0, Qt.UserRole + 1, "group")
                    group_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate | Qt.ItemIsEditable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
                    group_item.setCheckState(0, Qt.Checked if child.itemVisibilityChecked() else Qt.Unchecked)
                    build_tree(child, group_item)
                    group_item.setExpanded(child.isExpanded())
                elif isinstance(child, QgsLayerTreeLayer):
                    lyr = child.layer()
                    if not lyr: continue
                    layer_item = QTreeWidgetItem(parent_item)
                    layer_item.setText(0, child.name())
                    layer_item.setData(0, Qt.UserRole + 1, "layer")
                    layer_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsEditable | Qt.ItemIsDragEnabled)
                    layer_item.setCheckState(0, Qt.Checked if child.itemVisibilityChecked() else Qt.Unchecked)
                    
                    # Store layer ID in UserRole to fetch it later
                    layer_item.setData(0, Qt.UserRole, lyr.id())
                    
                    # Create Assigned Role Combo (Col 1) and QML Style Combo (Col 2)
                    self._create_assigned_layer_combo_for_layer(layer_item, lyr.name())
                    self._create_qml_combo_for_layer(layer_item, lyr.name())

        root = QgsProject.instance().layerTreeRoot()
        build_tree(root, self.layer_groups_tree)
        header = self.layer_groups_tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.layer_groups_tree.setColumnWidth(1, 200)
        self.layer_groups_tree.setColumnWidth(2, 220)

    def _create_assigned_layer_combo_for_layer(self, layer_item, layer_name, preset_id=None):
        """Create and attach an Assigned Role dropdown in column 1 for a layer tree item."""
        role_combo = QComboBox()
        role_options = [
            (self.tr("(Unassigned)"), None),
            (self.tr("Building points (*_bldg_point)"), "_ea_combo_bldg"),
            (self.tr("Barangay layer (*_bgy)"), "_ea_combo_bgy"),
            (self.tr("EA layer (*_ea)"), "_ea_combo_ea"),
            (self.tr("Landmark layer (*_landmark)"), "_ea_combo_landmark"),
            (self.tr("Block layer (*_block)"), "_ea_combo_block"),
            (self.tr("Road layer (*_road)"), "_ea_combo_road"),
            (self.tr("River layer (*_river)"), "_ea_combo_river"),
            (self.tr("Bridge layer (*_bridge)"), "_ea_combo_bridge"),
            (self.tr("Railroad layer (*_railroad)"), "_ea_combo_railroad"),
        ]
        for label, data in role_options:
            role_combo.addItem(label, data)
            
        if preset_id is not None:
            for i in range(role_combo.count()):
                if role_combo.itemData(i) == preset_id:
                    role_combo.setCurrentIndex(i)
                    break
        else:
            # Auto-detect role based on layer name
            lname = layer_name.lower()
            detected_role = None
            if lname.endswith("_special_ea"):
                detected_role = None
            elif any(lname.endswith(s) or lname.endswith(s + " (offline)") for s in ("_bldg_point", "_bldgpts", "_bldg_points")):
                detected_role = "_ea_combo_bldg"
            elif any(lname.endswith(s) or lname.endswith(s + " (offline)") for s in ("_geocode", "_geotagged", "pppmmbbbeeeeee")):
                detected_role = "_ea_combo_geocode"
            elif any(lname.endswith(s) or lname.endswith(s + " (offline)") for s in ("_bgy",)):
                detected_role = "_ea_combo_bgy"
            elif any(lname.endswith(s) or lname.endswith(s + " (offline)") for s in ("_ea",)):
                detected_role = "_ea_combo_ea"
            elif any(lname.endswith(s) or lname.endswith(s + " (offline)") for s in ("_landmark",)):
                detected_role = "_ea_combo_landmark"
            elif any(lname.endswith(s) or lname.endswith(s + " (offline)") for s in ("_block",)):
                detected_role = "_ea_combo_block"
            elif any(lname.endswith(s) or lname.endswith(s + " (offline)") for s in ("_road",)):
                detected_role = "_ea_combo_road"
            elif any(lname.endswith(s) or lname.endswith(s + " (offline)") for s in ("_river",)):
                detected_role = "_ea_combo_river"
            elif any(lname.endswith(s) or lname.endswith(s + " (offline)") for s in ("_bridge",)):
                detected_role = "_ea_combo_bridge"
            elif any(lname.endswith(s) or lname.endswith(s + " (offline)") for s in ("_railroad",)):
                detected_role = "_ea_combo_railroad"
                
            if detected_role:
                for i in range(role_combo.count()):
                    if role_combo.itemData(i) == detected_role:
                        role_combo.setCurrentIndex(i)
                        break

        self.layer_groups_tree.setItemWidget(layer_item, 1, role_combo)
        return role_combo

    def _create_qml_combo_for_layer(self, layer_item, layer_name, preset_qml=None):
        """Create and attach a QML Style dropdown in column 2 for a layer tree item."""
        from ..utils.style_utils import get_available_qml_display_names, auto_detect_qml_for_layer, apply_qml_to_layer
        available_qml = get_available_qml_display_names()
        style_combo = QComboBox()
        style_combo.addItem(self.tr("(None)"))
        style_combo.addItems(available_qml)
        
        settings = QSettings()
        saved_qml = settings.value(f"gmd_pipeline/qml_for_layer_{layer_name}", "")
        
        if preset_qml and preset_qml in available_qml:
            style_combo.setCurrentText(preset_qml)
        elif saved_qml and saved_qml in available_qml:
            style_combo.setCurrentText(saved_qml)
        else:
            detected = auto_detect_qml_for_layer(layer_name, available_qml)
            if detected:
                style_combo.setCurrentText(detected)
                
        layer_item.setText(2, style_combo.currentText())

        layer_id = layer_item.data(0, Qt.UserRole)

        style_combo.currentTextChanged.connect(
            lambda text, item=layer_item, lid=layer_id, name=layer_name: self._on_qml_combo_changed(item, lid, name, text)
        )
        self.layer_groups_tree.setItemWidget(layer_item, 2, style_combo)
        return style_combo

    def _on_qml_combo_changed(self, layer_item, layer_id, layer_name, text):
        try:
            if layer_item and not sip.isdeleted(layer_item):
                layer_item.setText(2, text)
        except Exception:
            pass

        settings = QSettings()
        if text == self.tr("(None)"):
            settings.remove(f"gmd_pipeline/qml_for_layer_{layer_name}")
        else:
            settings.setValue(f"gmd_pipeline/qml_for_layer_{layer_name}", text)
            lyr = None
            if layer_id:
                try:
                    lyr = QgsProject.instance().mapLayer(layer_id)
                except Exception:
                    lyr = None
            if not lyr:
                try:
                    layers = QgsProject.instance().mapLayersByName(layer_name)
                    if layers:
                        lyr = layers[0]
                except Exception:
                    lyr = None
            if lyr is not None:
                try:
                    if not sip.isdeleted(lyr) and lyr.isValid():
                        from ..utils.style_utils import get_qml_file_path, apply_qml_to_layer
                        qml_path = get_qml_file_path(text)
                        if qml_path and os.path.isfile(qml_path):
                            apply_qml_to_layer(lyr, text)
                except Exception:
                    pass

    def _on_add_group(self):
        """Prompt user for a new group name and add a new group to the Layer Groups & Styles tree."""
        group_name, ok = QInputDialog.getText(self, self.tr("Add Group"), self.tr("Enter new group name:"))
        if ok and group_name.strip():
            group_name = group_name.strip()
            selected = self.layer_groups_tree.selectedItems()
            parent_item = self.layer_groups_tree.invisibleRootItem()
            if selected:
                sel = selected[0]
                if sel.parent() is None and sel.data(0, Qt.UserRole) is None:
                    parent_item = sel

            group_item = QTreeWidgetItem(parent_item)
            group_item.setText(0, group_name)
            group_item.setData(0, Qt.UserRole + 1, "group")
            group_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate | Qt.ItemIsEditable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
            group_item.setCheckState(0, Qt.Checked)
            group_item.setExpanded(True)
            self.layer_groups_tree.setCurrentItem(group_item)

    def _on_delete_group(self):
        """Remove selected group(s) or layer item(s) from the Layer Groups & Styles tree."""
        selected = self.layer_groups_tree.selectedItems()
        if not selected:
            QMessageBox.information(self, self.tr("No Selection"), self.tr("Please select a group or layer item to delete."))
            return

        reply = QMessageBox.question(
            self,
            self.tr("Confirm Delete"),
            self.tr("Are you sure you want to remove the selected item(s) from the tree?"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            for item in selected:
                parent = item.parent() or self.layer_groups_tree.invisibleRootItem()
                parent.removeChild(item)

    def _reposition_single_item(self, item, target_parent, target_idx):
        child_name = item.text(0)
        is_layer = item.data(0, Qt.UserRole) is not None
        saved_role = None
        saved_qml = ""
        if is_layer:
            role_combo = self.layer_groups_tree.itemWidget(item, 1)
            qml_combo = self.layer_groups_tree.itemWidget(item, 2)
            if role_combo: saved_role = role_combo.currentData()
            if qml_combo: saved_qml = qml_combo.currentText()

        old_parent = item.parent() or self.layer_groups_tree.invisibleRootItem()
        curr_idx = old_parent.indexOfChild(item)
        if curr_idx >= 0:
            taken = old_parent.takeChild(curr_idx)
            target_parent.insertChild(target_idx, taken)
            self.layer_groups_tree.setCurrentItem(taken)
            if is_layer:
                self._create_assigned_layer_combo_for_layer(taken, child_name, preset_id=saved_role)
                self._create_qml_combo_for_layer(taken, child_name, preset_qml=saved_qml)

    def _on_move_item_up(self):
        """Move all selected items UP in layer_groups_tree."""
        selected = self.layer_groups_tree.selectedItems()
        if not selected:
            return
        for item in selected:
            parent = item.parent() or self.layer_groups_tree.invisibleRootItem()
            idx = parent.indexOfChild(item)
            if idx > 0:
                self._reposition_single_item(item, parent, idx - 1)

    def _on_move_item_down(self):
        """Move all selected items DOWN in layer_groups_tree."""
        selected = self.layer_groups_tree.selectedItems()
        if not selected:
            return
        for item in reversed(selected):
            parent = item.parent() or self.layer_groups_tree.invisibleRootItem()
            idx = parent.indexOfChild(item)
            if idx < parent.childCount() - 1:
                self._reposition_single_item(item, parent, idx + 1)

    def _on_move_item_out(self):
        """Move all selected items OUT of their current group to the parent level."""
        selected = self.layer_groups_tree.selectedItems()
        if not selected:
            return
        for item in selected:
            parent = item.parent()
            if parent:
                grandparent = parent.parent() or self.layer_groups_tree.invisibleRootItem()
                parent_idx = grandparent.indexOfChild(parent)
                self._reposition_single_item(item, grandparent, parent_idx + 1)

    def _on_move_item_in(self):
        """Move all selected items INTO the group item directly preceding them."""
        selected = self.layer_groups_tree.selectedItems()
        if not selected:
            return
        for item in selected:
            parent = item.parent() or self.layer_groups_tree.invisibleRootItem()
            idx = parent.indexOfChild(item)
            if idx > 0:
                prev_sibling = parent.child(idx - 1)
                is_sibling_layer = prev_sibling.data(0, Qt.UserRole) is not None
                if not is_sibling_layer:
                    self._reposition_single_item(item, prev_sibling, prev_sibling.childCount())

    def _get_active_layer_name(self, layer_item):
        """Returns the name of the QGIS layer associated with this tree item."""
        return layer_item.text(0)


    def _get_all_presets(self):
        presets = dict(BUILTIN_PRESETS)
        settings = QSettings()
        user_json = settings.value("gmd_pipeline/layer_groups_presets_dict", "{}")
        try:
            user_presets = json.loads(user_json)
            if isinstance(user_presets, dict):
                presets.update(user_presets)
        except Exception:
            pass
        return presets

    def _on_save_groups_preset(self):
        """Save ONLY the group structure (group names and group hierarchy) into a named preset."""
        text, ok = QInputDialog.getText(self, self.tr("Save Preset"), self.tr("Enter preset name:"))
        if ok and text and text.strip():
            text = text.strip()
            settings = QSettings()
            user_json = settings.value("gmd_pipeline/layer_groups_presets_dict", "{}")
            try:
                user_presets = json.loads(user_json)
                if not isinstance(user_presets, dict): user_presets = {}
            except Exception:
                user_presets = {}
            
            preset_groups = []
            
            def save_groups(parent_item, current_path):
                for i in range(parent_item.childCount()):
                    item = parent_item.child(i)
                    is_layer = item.data(0, Qt.UserRole + 1) == "layer" or item.data(0, Qt.UserRole) is not None
                    if not is_layer:
                        item_path = current_path + [item.text(0)]
                        preset_groups.append({
                            "path": item_path,
                            "is_group": True,
                            "checked": item.checkState(0) == Qt.Checked
                        })
                        save_groups(item, item_path)
                    
            save_groups(self.layer_groups_tree.invisibleRootItem(), [])
            user_presets[text] = preset_groups
            settings.setValue("gmd_pipeline/layer_groups_presets_dict", json.dumps(user_presets))
            QMessageBox.information(self, self.tr("Success"), self.tr(f"Group layout preset '{text}' saved successfully."))

    def _on_load_groups_preset(self):
        """Load group structure preset and present all current project layers for easy drag-and-drop grouping."""
        all_presets = self._get_all_presets()
        if not all_presets:
            QMessageBox.warning(self, self.tr("No Presets"), self.tr("No presets available."))
            return
            
        name, ok = QInputDialog.getItem(
            self, self.tr("Load Preset"), self.tr("Select group layout preset to load:"),
            list(all_presets.keys()), 0, False
        )
        if ok and name:
            preset_data = all_presets[name]
            
            self.layer_groups_tree.blockSignals(True)
            try:
                from qgis.core import QgsProject
                project = QgsProject.instance()
                project_layers = list(project.mapLayers().values())
                
                self.layer_groups_tree.clear()
                item_map = {}
                
                def get_or_create_parent(path_tuple):
                    if not path_tuple:
                        return self.layer_groups_tree.invisibleRootItem()
                    if path_tuple in item_map:
                        return item_map[path_tuple]
                    
                    parent = get_or_create_parent(path_tuple[:-1])
                    group_item = QTreeWidgetItem(parent)
                    group_item.setText(0, path_tuple[-1])
                    group_item.setData(0, Qt.UserRole + 1, "group")
                    group_item.setFlags(
                        Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable |
                        Qt.ItemIsAutoTristate | Qt.ItemIsEditable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
                    )
                    group_item.setCheckState(0, Qt.Checked)
                    group_item.setExpanded(True)
                    item_map[path_tuple] = group_item
                    return group_item

                if isinstance(preset_data, list):
                    for item_data in preset_data:
                        if not isinstance(item_data, dict): continue
                        path = item_data.get("path", [])
                        if not path: continue
                        path_tuple = tuple(path)
                        is_group = item_data.get("is_group", True)
                        if is_group:
                            get_or_create_parent(path_tuple)

                # Add all project layers at root level for easy drag-and-drop into groups
                for lyr in project_layers:
                    layer_item = QTreeWidgetItem(self.layer_groups_tree.invisibleRootItem())
                    layer_item.setText(0, lyr.name())
                    layer_item.setData(0, Qt.UserRole + 1, "layer")
                    layer_item.setData(0, Qt.UserRole, lyr.id())
                    layer_item.setFlags(
                        Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable |
                        Qt.ItemIsEditable | Qt.ItemIsDragEnabled
                    )
                    layer_item.setCheckState(0, Qt.Checked)
                    self._create_assigned_layer_combo_for_layer(layer_item, lyr.name())
                    self._create_qml_combo_for_layer(layer_item, lyr.name())

            finally:
                self.layer_groups_tree.blockSignals(False)

            QMessageBox.information(
                self, self.tr("Preset Loaded"),
                self.tr(f"Group layout '{name}' loaded! Group folders have been created—you can now drag and drop your layers into them.")
            )

    def _on_delete_groups_preset(self):
        settings = QSettings()
        user_json = settings.value("gmd_pipeline/layer_groups_presets_dict", "{}")
        try:
            user_presets = json.loads(user_json)
            if not isinstance(user_presets, dict): user_presets = {}
        except Exception:
            user_presets = {}

        if not user_presets:
            QMessageBox.information(self, self.tr("No User Presets"), self.tr("No custom user-saved presets available to delete. (Built-in presets cannot be deleted)"))
            return
            
        preset_names = list(user_presets.keys())
        name, ok = QInputDialog.getItem(
            self, self.tr("Delete Preset"), self.tr("Select user preset to delete:"), preset_names, 0, False
        )
        if ok and name:
            reply = QMessageBox.question(
                self, self.tr("Confirm Delete"), 
                self.tr(f"Are you sure you want to delete the preset '{name}'?"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                user_presets.pop(name, None)
                settings.setValue("gmd_pipeline/layer_groups_presets_dict", json.dumps(user_presets))
                QMessageBox.information(self, self.tr("Success"), self.tr(f"Preset '{name}' deleted successfully."))

    def _on_apply_layer_groups(self, apply_qml=False, show_prompt=False):
        """Restructure, re-order, and update visibility. Apply QML styles ONLY if apply_qml is True."""
        from qgis.PyQt.QtCore import QCoreApplication
        from qgis.core import QgsProject, QgsMessageLog, Qgis
        
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        
        applied_summary = []

        def find_map_layer_for_item(item):
            try:
                if sip.isdeleted(item):
                    return None
            except Exception:
                pass

            layer_id = item.data(0, Qt.UserRole)
            if layer_id:
                try:
                    lyr = project.mapLayer(layer_id)
                    if lyr and not sip.isdeleted(lyr) and lyr.isValid():
                        return lyr
                except Exception:
                    pass
            
            raw_name = item.text(0).strip()
            try:
                match = project.mapLayersByName(raw_name)
                if match and not sip.isdeleted(match[0]) and match[0].isValid():
                    return match[0]
            except Exception:
                pass
            
            clean_name = re.sub(r"\s*\(\s*offline\s*\)$", "", raw_name, flags=re.IGNORECASE).strip()
            try:
                match = project.mapLayersByName(clean_name)
                if match and not sip.isdeleted(match[0]) and match[0].isValid():
                    return match[0]
            except Exception:
                pass
            
            try:
                for lyr in project.mapLayers().values():
                    if lyr and not sip.isdeleted(lyr) and lyr.isValid():
                        if lyr.name().lower() == raw_name.lower() or lyr.name().lower() == clean_name.lower():
                            return lyr
            except Exception:
                pass
            return None

        # 1. Apply QML styles ONLY when explicitly requested (e.g. via 'Apply Groups & Styles' button)
        if apply_qml:
            def apply_styles(item):
                lyr = find_map_layer_for_item(item)
                if lyr:
                    qml_text = ""
                    qml_combo = self.layer_groups_tree.itemWidget(item, 2)
                    if qml_combo and qml_combo.currentText():
                        qml_text = qml_combo.currentText()
                    elif item.text(2):
                        qml_text = item.text(2)

                    if qml_text and qml_text != self.tr("(None)"):
                        from ..utils.style_utils import apply_qml_to_layer
                        res = apply_qml_to_layer(lyr, qml_text)
                        log_msg = f"Layer '{lyr.name()}' ← QML '{qml_text}' (Success: {res})"
                        print(f"[APPLY STYLES LOG] {log_msg}")
                        QgsMessageLog.logMessage(log_msg, "AuQCBMS", Qgis.Info)
                        applied_summary.append(log_msg)
                for c in range(item.childCount()):
                    apply_styles(item.child(c))

            apply_styles(self.layer_groups_tree.invisibleRootItem())
            QCoreApplication.processEvents()

        # 2. Sync custom groups and layer hierarchy to QGIS layerTreeRoot with exact ordering (insertChildNode at index idx)
        def sync_tree(parent_item, qgs_parent):
            for idx in range(parent_item.childCount()):
                item = parent_item.child(idx)
                item_name = item.text(0)
                is_layer_item = item.data(0, Qt.UserRole + 1) == "layer" or item.data(0, Qt.UserRole) is not None
                is_group = not is_layer_item and (item.childCount() > 0 or item.data(0, Qt.UserRole) is None)
                
                if is_group:
                    qgs_grp = qgs_parent.findGroup(item_name)
                    if not qgs_grp:
                        qgs_grp = qgs_parent.insertGroup(idx, item_name)
                    else:
                        curr_children = list(qgs_parent.children())
                        if qgs_grp in curr_children and curr_children.index(qgs_grp) != idx:
                            clone_grp = qgs_grp.clone()
                            qgs_parent.insertChildNode(idx, clone_grp)
                            qgs_parent.removeChildNode(qgs_grp)
                            qgs_grp = clone_grp
                            
                    qgs_grp.setItemVisibilityChecked(item.checkState(0) == Qt.Checked)
                    sync_tree(item, qgs_grp)
                else:
                    layer_id = item.data(0, Qt.UserRole)
                    lyr = project.mapLayer(layer_id) if layer_id else None
                    if not lyr:
                        lyr = find_map_layer_for_item(item)
                        
                    if lyr:
                        node = root.findLayer(lyr.id())
                        if node:
                            old_parent = node.parent()
                            curr_children = list(qgs_parent.children())
                            if old_parent != qgs_parent or node not in curr_children or curr_children.index(node) != idx:
                                node_clone = node.clone()
                                qgs_parent.insertChildNode(idx, node_clone)
                                if old_parent:
                                    old_parent.removeChildNode(node)
                                node = node_clone
                            node.setItemVisibilityChecked(item.checkState(0) == Qt.Checked)

        sync_tree(self.layer_groups_tree.invisibleRootItem(), root)

        # 3. Purge old/renamed/empty groups from QGIS
        valid_group_names = set()
        def collect_group_names(parent_item):
            for i in range(parent_item.childCount()):
                item = parent_item.child(i)
                is_layer_item = item.data(0, Qt.UserRole + 1) == "layer" or item.data(0, Qt.UserRole) is not None
                if not is_layer_item:
                    valid_group_names.add(item.text(0))
                    collect_group_names(item)

        collect_group_names(self.layer_groups_tree.invisibleRootItem())

        for g in list(root.findGroups()):
            if g.name() not in valid_group_names or len(g.children()) == 0:
                p = g.parent()
                if p:
                    p.removeChildNode(g)

        QCoreApplication.processEvents()

        if self.iface and self.iface.mapCanvas():
            self.iface.mapCanvas().refresh()
            
        if show_prompt:
            summary_text = "\n".join(applied_summary) if applied_summary else self.tr("No QML styles selected.")
            QMessageBox.information(
                self, self.tr("Success"),
                self.tr(f"Groups & Layer structure applied!\n\nStyle Results:\n{summary_text}")
            )

    def _refresh_all_qml_combos(self):
        """Refresh the items in all QML Style dropdowns in column 2 of layer_groups_tree."""
        from ..utils.style_utils import get_available_qml_display_names
        available_qml = get_available_qml_display_names()

        def refresh_item(item):
            qml_combo = self.layer_groups_tree.itemWidget(item, 2)
            if qml_combo:
                current_text = qml_combo.currentText()
                qml_combo.blockSignals(True)
                qml_combo.clear()
                qml_combo.addItem(self.tr("(None)"))
                qml_combo.addItems(available_qml)
                idx = qml_combo.findText(current_text)
                if idx >= 0:
                    qml_combo.setCurrentIndex(idx)
                else:
                    qml_combo.setCurrentIndex(0)
                qml_combo.blockSignals(False)
            for c in range(item.childCount()):
                refresh_item(item.child(c))

        for i in range(self.layer_groups_tree.topLevelItemCount()):
            refresh_item(self.layer_groups_tree.topLevelItem(i))

    def _on_import_qml_styles(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, self.tr("Select QML Styles"), "", "QML Files (*.qml)"
        )
        if not files:
            return

        dest_folder = get_qml_styles_dir()
        if not os.path.exists(dest_folder):
            os.makedirs(dest_folder)

        copied = 0
        for fpath in files:
            fname = os.path.basename(fpath)
            shutil.copy2(fpath, os.path.join(dest_folder, fname))
            copied += 1

        if copied:
            self._refresh_all_qml_combos()
            QMessageBox.information(
                self, self.tr("Success"),
                self.tr(f"{copied} QML file(s) imported successfully.")
            )
    def update_button_box_visibility(self):
        """Update visibility of the button box based on current tab and page."""
        if hasattr(self, 'button_box'):
            if hasattr(self, 'stackedWidget') and hasattr(self, 'packagePage'):
                if self.stackedWidget.currentWidget() == self.packagePage:
                    self.button_box.setVisible(True)
                else:
                    self.button_box.setVisible(False)
            else:
                self.button_box.setVisible(True)

    def __init__(self, iface, project, offline_editing, parent=None):
        """Constructor."""
        super(PackageDialog, self).__init__(parent=parent)
        self.setupUi(self)

        try:
            svg_path = os.path.join(os.path.dirname(__file__), "..", "resources", "qfield.svg")
            renderer = QSvgRenderer(svg_path)
            if renderer.isValid():
                dpr = getattr(self, 'devicePixelRatioF', self.devicePixelRatio)()
                sz = renderer.defaultSize()
                h = 100
                w = int(h * (sz.width() / max(sz.height(), 1)))
                pixmap = QPixmap(int(w * dpr), int(h * dpr))
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
                renderer.render(painter)
                painter.end()
                pixmap.setDevicePixelRatio(dpr)
                self.photo.setPixmap(pixmap)
                self.photo.setFixedHeight(h)
        except Exception:
            pass  # fall back to the .ui-provided pixmap
        
        # Define layer roles
        self._ea_layer_roles = [
            ("_ea_combo_bldg",       self.tr("Building points (*_bldg_point)"),  True),
            ("_ea_combo_landmark",   self.tr("Landmark layer (*_landmark)"),     True),
            ("_ea_combo_block",      self.tr("Block layer (*_block)"),           False),
            ("_ea_combo_ea",         self.tr("EA layer (*_ea)"),                 True),
            ("_ea_combo_bgy",        self.tr("Barangay layer (*_bgy)"),         True),
            ("_ea_combo_railroad",   self.tr("Railroad layer (*_railroad)"),     False),
            ("_ea_combo_bridge",     self.tr("Bridge layer (*_bridge)"),         False),
            ("_ea_combo_road",       self.tr("Road layer (*_road)"),             False),
            ("_ea_combo_river",      self.tr("River layer (*_river)"),           False),
        ]
        
        self._bgy_layer_roles = [
            ("_bgy_combo_bldg",      self.tr("Building points (*_bldg_point)"),  True),
            ("_bgy_combo_landmark",  self.tr("Landmark layer (*_landmark)"),     True),
            ("_bgy_combo_block",     self.tr("Block layer (*_block)"),           False),
            ("_bgy_combo_ea",        self.tr("EA layer (*_ea)"),                 True),
            ("_bgy_combo_bgy",       self.tr("Barangay layer (*_bgy)"),          True),
            ("_bgy_combo_railroad",  self.tr("Railroad layer (*_railroad)"),     False),
            ("_bgy_combo_bridge",    self.tr("Bridge layer (*_bridge)"),         False),
            ("_bgy_combo_road",      self.tr("Road layer (*_road)"),             False),
            ("_bgy_combo_river",     self.tr("River layer (*_river)"),           False),
        ]

        # Add Help and Properties buttons to upper right
        self.help_button = QPushButton(self.tr("Help"))
        self.help_button.clicked.connect(self.show_help)
        
        self.config_button = QPushButton(self.tr("⚙ Configuration"))
        self.config_button.setIcon(QIcon(QgsApplication.iconPath("mActionOptions.svg")))
        self.config_button.clicked.connect(self._show_configuration_dialog)

        _help_layout = QHBoxLayout()
        _help_layout.addWidget(self.config_button)
        _help_layout.addStretch()
        _help_layout.addWidget(self.help_button)
        self.verticalLayout_3.insertLayout(0, _help_layout)

        # Wrap the stackedWidget in a QScrollArea so the dialog is scrollable.
        # The button_box (Export/Reset/Close) stays outside, always visible.
        _scroll = QScrollArea()
        _scroll.setWidgetResizable(True)
        _scroll.setFrameShape(QFrame.NoFrame)
        _scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for _i in range(self.verticalLayout_3.count()):
            _item = self.verticalLayout_3.itemAt(_i)
            if _item and _item.widget() is self.stackedWidget:
                self.verticalLayout_3.takeAt(_i)
                break
        # Create a wrapper widget with a VBoxLayout to place panels above Process
        self._scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.setSpacing(0)
        
        # Container for Layer Assignment and Raster Configuration above Process
        self._top_panels_widget = QWidget()
        self._top_panels_layout = QVBoxLayout(self._top_panels_widget)
        self._top_panels_layout.setContentsMargins(9, 6, 9, 0)
        self._top_panels_layout.setSpacing(4)
        
        self._scroll_layout.addWidget(self._top_panels_widget)
        self._scroll_layout.addWidget(self.stackedWidget)
        
        _scroll.setWidget(self._scroll_content)
        
        # Initially hide the top panels until packagePage is shown
        self._top_panels_widget.setVisible(False)
        
        # Hide old export directory widgets from main flow
        self.label_4.setVisible(False)
        self.manualDir.setVisible(False)
        self.manualDir_btn.setVisible(False)
        
        # ── Configuration Dialog ───────────────────────────────────────────────
        self._build_configuration_dialog()

        # ── Move Output Level Dropdowns to Top ─────────────────────────────────
        self._output_selection_panel = QGroupBox(self.tr("Output Selection"))
        _output_layout = QGridLayout(self._output_selection_panel)
        _output_layout.setContentsMargins(6, 6, 6, 6)
        
        # Row 0: Output Level
        _output_layout.addWidget(self.label_8, 0, 0)
        _output_layout.addWidget(self.output_dropdown, 0, 1)
        
        # Row 1: Group/Base Layer
        _output_layout.addWidget(self.label, 1, 0)
        _output_layout.addWidget(self.group_dropdown, 1, 1)
        
        # Row 2: Barangay/EA Layer
        _output_layout.addWidget(self.label_3, 2, 0)
        _output_layout.addWidget(self.layer_dropdown, 2, 1)
        
        self._top_panels_layout.addWidget(self._output_selection_panel)

        # ── Layer Groups & Styles Panel ─────────────────────────────────────────
        self._groups_styles_panel = QGroupBox(self.tr("Layer Groups && Styles"))
        groups_layout = QVBoxLayout(self._groups_styles_panel)

        # ── Toolbar ──────────────────────────────────────────────────────────
        toolbar_layout = QHBoxLayout()
        
        self.apply_groups_btn = QPushButton(self.tr("▶ Apply Groups && Styles"))
        self.apply_groups_btn.setStyleSheet(
            "QPushButton { font-weight: bold; font-size: 13px; padding: 4px 8px; }"
        )
        
        self.add_group_btn = QPushButton(self.tr("➕ Add Group"))
        self.delete_group_btn = QPushButton(self.tr("🗑 Delete Item"))
        
        self.load_preset_btn = QPushButton(self.tr("📂 Load"))
        self.save_preset_btn = QPushButton(self.tr("💾 Save"))
        self.delete_preset_btn = QPushButton(self.tr("🗑 Delete Preset"))
        
        self.import_qml_btn = QPushButton(self.tr("📥 Import QML..."))
        self.import_qml_btn.setToolTip(self.tr(
            "Import additional QML style files if the built-in styles are not sufficient."
        ))
        
        toolbar_layout.addWidget(self.apply_groups_btn)
        toolbar_layout.addWidget(self.add_group_btn)
        toolbar_layout.addWidget(self.delete_group_btn)
        toolbar_layout.addWidget(self.load_preset_btn)
        toolbar_layout.addWidget(self.save_preset_btn)
        toolbar_layout.addWidget(self.delete_preset_btn)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self.import_qml_btn)
        
        groups_layout.addLayout(toolbar_layout)

        # Simple layout for Tree widget
        tree_row_layout = QHBoxLayout()

        self.layer_groups_tree = LayerGroupsTreeWidget(self)
        self.layer_groups_tree.setMinimumHeight(400)
        self.layer_groups_tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.layer_groups_tree.setDragEnabled(True)
        self.layer_groups_tree.setAcceptDrops(True)
        self.layer_groups_tree.setDropIndicatorShown(True)
        self.layer_groups_tree.setDefaultDropAction(Qt.MoveAction)
        self.layer_groups_tree.setDragDropMode(QTreeWidget.InternalMove)
        
        # 3 columns: Layer / Group, Assigned Role, and QML Style
        self.layer_groups_tree.setColumnCount(3)
        self.layer_groups_tree.setHeaderLabels([self.tr("Layer / Group"), self.tr("Assigned Role"), self.tr("QML Style")])
        
        # Center align header text for columns 1 and 2
        self.layer_groups_tree.headerItem().setTextAlignment(0, Qt.AlignLeft)
        self.layer_groups_tree.headerItem().setTextAlignment(1, Qt.AlignCenter)
        self.layer_groups_tree.headerItem().setTextAlignment(2, Qt.AlignCenter)
        
        # Set column sizing
        header = self.layer_groups_tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.layer_groups_tree.setColumnWidth(1, 200)
        self.layer_groups_tree.setColumnWidth(2, 220)
        
        tree_row_layout.addWidget(self.layer_groups_tree)
        groups_layout.addLayout(tree_row_layout)

        step2_note = QLabel(self.tr(
            "Layer roles and QML styles are auto-detected for each layer. "
            "Verify the selections above and adjust if needed."
        ))
        step2_note.setWordWrap(True)
        step2_note.setStyleSheet("color: gray; font-size: 11px; margin-bottom: 2px;")
        groups_layout.addWidget(step2_note)
        
        # Add the completed groups panel to the top panels layout
        self._top_panels_layout.addWidget(self._groups_styles_panel)
        
        # Connect signals for groups

        self.apply_groups_btn.clicked.connect(lambda: self._on_apply_layer_groups(apply_qml=True, show_prompt=True))
        self.add_group_btn.clicked.connect(self._on_add_group)
        self.delete_group_btn.clicked.connect(self._on_delete_group)
        self.save_preset_btn.clicked.connect(self._on_save_groups_preset)
        self.load_preset_btn.clicked.connect(self._on_load_groups_preset)
        self.delete_preset_btn.clicked.connect(self._on_delete_groups_preset)
        self.import_qml_btn.clicked.connect(self._on_import_qml_styles)
        # self.layer_groups_tree.itemChanged.connect(self._on_tree_item_changed)
        
        self.verticalLayout_3.insertWidget(_i, _scroll)
        self.setMinimumHeight(500)
        self.resize(1024, 800)
        self.setSizeGripEnabled(True)
        
        # Call it once to set initial visibility state
        self.update_button_box_visibility()

        # ensure output dropdown contains the expected options
        # (combo box named in the .ui file as "output_dropdown")
        self.output_dropdown.clear()
        self.output_dropdown.addItems([
            self.tr("Barangay Level"),
            self.tr("EA Level"),
        ])
        # only repopulate layers when output level changes; renaming happens on Filter click
        self.output_dropdown.currentTextChanged.connect(self.populate_layers_dropdown)
        self.output_dropdown.currentTextChanged.connect(self._update_ui_for_output_level)

        self.iface = iface
        self.offliner = QgisCoreOffliner(offline_editing=offline_editing)
        self.project = project
        self.qfield_preferences = Preferences()
        self.dirsToCopyWidget = DirsToCopyWidget()
        self.__project_configuration = ProjectConfiguration(self.project)
        self.run_button.clicked.connect(self.run)

        self.next_geocode.clicked.connect(self.next_geo)
        self.run_batch.clicked.connect(self.batch)
      
        self.run_clip.clicked.connect(self.run_raster)
        self.run_clip.setEnabled(False)
        self.group_dropdown.currentIndexChanged.connect(self.populate_layers_dropdown)
        self.group_dropdown.currentIndexChanged.connect(self.validate_group_selection)
        
        # When layer changes, populate the top-level tree filter
        self.layer_dropdown.currentIndexChanged.connect(self.populate_geocode_dropdown)
        self.layer_dropdown.currentIndexChanged.connect(self._populate_filter_tree)
        
        # We will disconnect the old dropdowns to avoid side-effects
        # self.citymun_dropdown.currentIndexChanged.connect(...)
        # self.bgy_dropdown.currentIndexChanged.connect(...)

        settings = QSettings()
        saved_raster_path = settings.value('raster_file_path', '', type=str)  # Default to empty string if no saved path

        if saved_raster_path:
            # Set the path to the file widget if a path is saved
            self.select_rasterlayer.setFilePath(saved_raster_path)
            print(f"Loaded saved raster file path: {saved_raster_path}")

        self.select_rasterlayer.setStorageMode(QgsFileWidget.StorageMode.GetFile)  # Set to select a file
        self.select_rasterlayer.setDialogTitle("Select Raster Layer")  # Set dialog title
        self.select_rasterlayer.setFilter(" Raster Layer (*_img.gpkg);;GeoPackage files (*.gpkg)")

        # Connect the fileChanged signal to a slot that updates the path in the settings
        self.select_rasterlayer.fileChanged.connect(self.update_raster_path)

        # EA geocode list widget has been merged into the main City/Municipality Tree Filter

        # Combined City/Municipality and Barangay Tree Filter
        self._filter_tree_label = QLabel(self.tr("Select City/Municipality"))
        
        # Search bar for tree
        self._filter_tree_search_bar = QLineEdit()
        self._filter_tree_search_bar.setPlaceholderText(self.tr("Search City/Municipality..."))
        self._filter_tree_search_bar.textChanged.connect(self._on_tree_search_changed)
        
        self._filter_tree_widget = QTreeWidget()
        self._filter_tree_widget.setHeaderHidden(True)
        self._filter_tree_widget.setMinimumHeight(150)
        self._filter_tree_widget.itemExpanded.connect(lambda: self._adjust_widget_height_to_content(self._filter_tree_widget))
        self._filter_tree_widget.itemCollapsed.connect(lambda: self._adjust_widget_height_to_content(self._filter_tree_widget))
        self._filter_tree_widget.setSelectionMode(QTreeWidget.ExtendedSelection)
        self._last_clicked_tree_item = None
        self._filter_tree_select_all_btn = QPushButton(self.tr("Select All"))
        self._filter_tree_deselect_all_btn = QPushButton(self.tr("Deselect All"))
        _filter_tree_btn_container = QWidget()
        _filter_tree_btn_layout = QHBoxLayout(_filter_tree_btn_container)
        _filter_tree_btn_layout.setContentsMargins(0, 0, 0, 0)
        _filter_tree_btn_layout.addWidget(self._filter_tree_select_all_btn)
        _filter_tree_btn_layout.addWidget(self._filter_tree_deselect_all_btn)
        self._filter_tree_btn_container = _filter_tree_btn_container
        self._filter_tree_select_all_btn.clicked.connect(self._filter_tree_select_all)
        self._filter_tree_deselect_all_btn.clicked.connect(self._filter_tree_deselect_all)
        self.gridLayout.addWidget(self._filter_tree_label, 30, 0, 1, 2)
        self.gridLayout.addWidget(self._filter_tree_search_bar, 31, 0, 1, 2)
        self.gridLayout.addWidget(self._filter_tree_widget, 32, 0, 1, 2)
        self.gridLayout.addWidget(self._filter_tree_btn_container, 33, 0, 1, 2)
        self._filter_tree_label.setVisible(False)
        self._filter_tree_search_bar.setVisible(False)
        self._filter_tree_widget.setVisible(False)
        self._filter_tree_btn_container.setVisible(False)
        self._filter_tree_widget.itemChanged.connect(self._on_filter_tree_item_changed)
        self._filter_tree_widget.itemClicked.connect(self._on_filter_tree_item_clicked)
        self._filter_tree_widget.installEventFilter(self)
        if hasattr(self._filter_tree_widget, 'viewport'):
            self._filter_tree_widget.viewport().installEventFilter(self)
        if hasattr(self, 'layer_groups_tree'):
            self.layer_groups_tree.installEventFilter(self)
            if hasattr(self.layer_groups_tree, 'viewport'):
                self.layer_groups_tree.viewport().installEventFilter(self)

        # BGY geocode list widget has been merged into the main City/Municipality Tree Filter

        # 

        # Raster Configuration and Individual Export are now inside the Configuration dialog
        self.gridGroupBox.setVisible(False)
        self.run_clip.setVisible(False)

        self.project_lbl.setText(get_project_title(self.project))
        self.button_box.button(QDialogButtonBox.Save).setText(self.tr("Export"))
        self.button_box.button(QDialogButtonBox.Save).clicked.connect(
            self.package_project
        )
        self.button_box.button(QDialogButtonBox.Save).setEnabled(False)
        self.button_box.button(QDialogButtonBox.Reset).clicked.connect(
            self.reset_filter
        )
        self.button_box.button(QDialogButtonBox.Reset).setText(self.tr("Clear Filter"))

        self.devices = None
        self.project_checker = ProjectChecker(QgsProject.instance())
        self.setup_gui()

         # Initialize variables
        self.layers = {}

        self.offliner.warning.connect(self.show_warning)

        # Load groups on dialog initialization
        self.load_layer_groups()
        # Apply initial UI state based on the default output level.
        self._update_ui_for_output_level()
        
        # Populate data sources table
        self._populate_data_sources()

        # Flag to control batch mode
        self.is_batch_mode = False
        # Flag to handle batch cancellation
        self.batch_cancel_requested = False
        # Track enabled-state snapshot while batch is running.
        self._batch_prev_enabled_states = {}

    def _set_batch_ui_locked(self, locked):
        """Disable interactive controls during batch and restore them afterwards."""
        controls = {
            "run_button": self.run_button,
            "next_geocode": self.next_geocode,
            "run_batch": self.run_batch,
            "run_clip": self.run_clip,
            "manualDir_btn": self.manualDir_btn,
            "group_dropdown": self.group_dropdown,
            "layer_dropdown": self.layer_dropdown,
            "geocode_dropdown": self.geocode_dropdown,
            "citymun_dropdown": self.citymun_dropdown,
            "bgy_dropdown": self.bgy_dropdown,
            "output_dropdown": self.output_dropdown,
            "save_button": self.button_box.button(QDialogButtonBox.Save),
            "reset_button": self.button_box.button(QDialogButtonBox.Reset),
            "select_rasterlayer": self.select_rasterlayer,
        }

        if locked:
            self._batch_prev_enabled_states = {}
            for key, widget in controls.items():
                if widget is None:
                    continue
                try:
                    self._batch_prev_enabled_states[key] = widget.isEnabled()
                    widget.setEnabled(False)
                except Exception:
                    continue
            return

        for key, widget in controls.items():
            if widget is None:
                continue
            if key not in self._batch_prev_enabled_states:
                continue
            try:
                widget.setEnabled(self._batch_prev_enabled_states[key])
            except Exception:
                continue
        self._batch_prev_enabled_states = {}

    def _build_configuration_dialog(self):
        self.config_dialog = QDialog(self)
        self.config_dialog.setWindowTitle(self.tr("Configuration"))
        self.config_dialog.resize(700, 600)
        
        main_layout = QVBoxLayout(self.config_dialog)
        main_layout.setContentsMargins(9, 9, 9, 9)
        main_layout.setSpacing(6)
        
        # ── Export Settings ──────────────────────────────────────────────────
        export_group = QGroupBox(self.tr("Export Settings"))
        export_layout = QGridLayout(export_group)
        export_layout.setContentsMargins(6, 6, 6, 6)
        
        export_label = QLabel(self.tr("Export Directory"))
        self.config_export_dir = QLineEdit()
        self.config_export_dir.setReadOnly(True)
        self.config_export_dir.setText(self.manualDir.text())
        
        self.config_export_dir_btn = QToolButton()
        self.config_export_dir_btn.setText("...")
        
        export_layout.addWidget(export_label, 0, 0)
        export_layout.addWidget(self.config_export_dir, 0, 1)
        export_layout.addWidget(self.config_export_dir_btn, 0, 2)
        
        main_layout.addWidget(export_group)
        
        def _on_config_folder_selected():
            self.manualDir_btn.click() 
            self.config_export_dir.setText(self.manualDir.text())
            
        self.config_export_dir_btn.clicked.connect(_on_config_folder_selected)
        
        # ── Raster Configuration ─────────────────────────────────────────────
        self._raster_config_panel = self._build_raster_config_panel()
        main_layout.addWidget(self._raster_config_panel)
        
        # ── Layer Properties ─────────────────────────────────────────────────
        # ── Layer Properties ─────────────────────────────────────────────────
        layer_group = QGroupBox()
        layer_layout = QVBoxLayout(layer_group)
        
        # Header row: "Layer Properties" label + Data Source icon button right next to it
        _layer_header_layout = QHBoxLayout()
        _layer_header_layout.setContentsMargins(0, 0, 0, 0)
        _layer_header_layout.setSpacing(6)
        
        _layer_title_label = QLabel(self.tr("Layer Properties"))
        _layer_title_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        
        self._data_source_icon_btn = QToolButton()
        self._data_source_icon_btn.setIcon(QIcon(QgsApplication.iconPath("mActionOpenTable.svg")))
        self._data_source_icon_btn.setToolTip(self.tr(
            "Configure per-layer data source properties for active layers.\n"
            "Opens a popup dialog showing active project layers (excluding standard system role layers)\n"
            "with individual QField Action, Identifiable, Read-only, Searchable,\n"
            "and Export Format settings."
        ))
        self._data_source_icon_btn.setCheckable(False)
        self._data_source_icon_btn.setStyleSheet(
            "QToolButton { border: 1px solid #aaa; border-radius: 3px; padding: 2px 6px; }"
            "QToolButton:hover { background-color: #eef; border-color: #68a; }"
        )
        self._data_source_icon_btn.clicked.connect(self._on_toggle_layer_data_sources)
        
        _layer_header_layout.addWidget(_layer_title_label)
        _layer_header_layout.addWidget(self._data_source_icon_btn)
        _layer_header_layout.addStretch()
        layer_layout.addLayout(_layer_header_layout)
        
        self.data_sources_table = QTableWidget()
        self.data_sources_table.setColumnCount(5)
        self.data_sources_table.setHorizontalHeaderLabels([
            self.tr("Assigned Role"), self.tr("QField Action"), 
            self.tr("Identifiable"), self.tr("Read-only"), self.tr("Searchable")
        ])
        
        header = self.data_sources_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.data_sources_table.verticalHeader().setVisible(False)
        self.data_sources_table.setSelectionMode(QTableWidget.NoSelection)
        self.data_sources_table.setAlternatingRowColors(True)
        
        layer_layout.addWidget(self.data_sources_table)
        self.data_sources_table.itemChanged.connect(self._on_data_source_changed)
        
        main_layout.addWidget(layer_group)
        
        # ── Buttons ──────────────────────────────────────────────────────────
        btn_layout = QHBoxLayout()
        self.restore_defaults_btn = QPushButton(self.tr("Restore Defaults"))
        self.restore_defaults_btn.clicked.connect(self._on_restore_defaults)
        
        close_btn = QPushButton(self.tr("Close"))
        close_btn.clicked.connect(self.config_dialog.accept)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.restore_defaults_btn)
        btn_layout.addWidget(close_btn)
        main_layout.addLayout(btn_layout)

    def _show_configuration_dialog(self):
        self.config_export_dir.setText(self.manualDir.text())
        self._populate_data_sources()
        # Refresh per-layer data sources if table is visible
        if hasattr(self, 'layer_data_sources_table') and self.layer_data_sources_table.isVisible():
            self._populate_layer_data_sources()
        self.config_dialog.exec_()
        
    def _on_restore_defaults(self):
        from PyQt5.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self.config_dialog,
            self.tr("Restore Defaults"),
            self.tr("Are you sure you want to reset all configuration settings to their defaults?"),
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            settings = QSettings()
            settings.remove("exportDirectoryManual")
            settings.remove("raster_satellite_format")
            settings.remove("satellite_dir_path")
            settings.remove("raster_convert_mbtiles")
            settings.remove("additional_raster_dir_path")
            settings.remove("gmd_pipeline/role_policies_dict")
            settings.remove("gmd_pipeline/layer_data_sources_dict")
            
            # Refresh fields
            self.setup_gui()
            self.config_export_dir.setText(self.manualDir.text())
            
            # Reset raster fields
            self._raster_type_combo.setCurrentIndex(0)
            self._raster_satellite_dir.setFilePath("")
            self._raster_convert_mbtiles.setChecked(True)
            self._raster_additional_dir.setFilePath("")
            self._on_satellite_format_changed(0)
            self._populate_data_sources()
            
            # Reset per-layer data sources
            if hasattr(self, '_data_source_icon_btn'):
                self._data_source_icon_btn.setChecked(False)
            if hasattr(self, '_layer_ds_separator'):
                self._layer_ds_separator.setVisible(False)
            if hasattr(self, 'layer_data_sources_table'):
                self.layer_data_sources_table.setVisible(False)
                self.layer_data_sources_table.setRowCount(0)

    def _populate_data_sources(self):
        self.data_sources_table.blockSignals(True)
        self.data_sources_table.setRowCount(0)
        self.data_sources_table.setColumnCount(6)
        self.data_sources_table.setHorizontalHeaderLabels([
            self.tr("Assigned Role"), self.tr("QField Action"), 
            self.tr("Identifiable"), self.tr("Read-only"), self.tr("Searchable"), self.tr("Export Format")
        ])
        
        header = self.data_sources_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.data_sources_table.verticalHeader().setVisible(False)
        self.data_sources_table.setSelectionMode(QTableWidget.NoSelection)
        self.data_sources_table.setAlternatingRowColors(True)

        system_role_policies = [
            ("_ea_combo_bldg",     self.tr("Building points (*_bldg_point)"),                  "offline", True,  False, True,  ".geojson"),
            ("_ea_combo_bgy",      self.tr("Barangay layer (*_bgy)"),                          "copy",    True,  True,  True,  "(data.gpkg)"),
            ("_ea_combo_ea",       self.tr("EA layer (*_ea)"),                                 "copy",    True,  True,  True,  "(data.gpkg)"),
            ("_ea_combo_landmark", self.tr("Landmark layer (*_landmark)"),                     "copy",    True,  True,  True,  "(data.gpkg)"),
            ("_ea_combo_block",    self.tr("Block layer (*_block)"),                           "copy",    True,  True,  True,  "(data.gpkg)"),
            ("_ea_combo_road",     self.tr("Road layer (*_road)"),                             "copy",    True,  True,  True,  "(data.gpkg)"),
            ("_ea_combo_river",    self.tr("River layer (*_river)"),                           "copy",    True,  True,  True,  "(data.gpkg)"),
            ("_ea_combo_bridge",   self.tr("Bridge layer (*_bridge)"),                         "copy",    True,  True,  True,  "(data.gpkg)"),
            ("_ea_combo_railroad", self.tr("Railroad layer (*_railroad)"),                     "copy",    True,  True,  True,  "(data.gpkg)"),
        ]

        settings = QSettings()
        user_json = settings.value("gmd_pipeline/role_policies_dict", "{}")
        try:
            saved_policies = json.loads(user_json)
            if not isinstance(saved_policies, dict): saved_policies = {}
        except Exception:
            saved_policies = {}

        self.data_sources_table.setRowCount(len(system_role_policies))

        for row, (role_id, role_name, def_action, def_ident, def_ro, def_search, def_fmt) in enumerate(system_role_policies):
            policy = saved_policies.get(role_id, {})
            curr_action = policy.get("action", def_action)
            curr_ident = policy.get("identifiable", def_ident)
            curr_ro = policy.get("readonly", def_ro)
            curr_search = policy.get("searchable", def_search)
            curr_fmt = policy.get("format", def_fmt)

            # Col 0: Assigned Role Name
            name_item = QTableWidgetItem(role_name)
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            name_item.setData(Qt.UserRole, role_id)
            self.data_sources_table.setItem(row, 0, name_item)

            # Col 1: QField Action
            action_combo = QComboBox()
            action_combo.addItem(self.tr("Offline Editing"), "offline")
            action_combo.addItem(self.tr("Copy / Read-Only"), "copy")
            if curr_action == "copy":
                action_combo.setCurrentIndex(1)
            else:
                action_combo.setCurrentIndex(0)
            action_combo.currentIndexChanged.connect(self._save_role_policies_from_table)
            self.data_sources_table.setCellWidget(row, 1, action_combo)

            # Col 2: Identifiable
            ident_item = QTableWidgetItem()
            ident_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            ident_item.setCheckState(Qt.Checked if curr_ident else Qt.Unchecked)
            self.data_sources_table.setItem(row, 2, ident_item)

            # Col 3: Read-Only
            ro_item = QTableWidgetItem()
            ro_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            ro_item.setCheckState(Qt.Checked if curr_ro else Qt.Unchecked)
            self.data_sources_table.setItem(row, 3, ro_item)

            # Col 4: Searchable
            search_item = QTableWidgetItem()
            search_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            search_item.setCheckState(Qt.Checked if curr_search else Qt.Unchecked)
            self.data_sources_table.setItem(row, 4, search_item)

            # Col 5: Export Format
            format_combo = QComboBox()
            format_combo.addItems(["(data.gpkg)", ".geojson", ".gpkg", ".shp"])
            if curr_fmt in ("(data.gpkg)", ".geojson", ".gpkg", ".shp"):
                format_combo.setCurrentText(curr_fmt)
            else:
                format_combo.setCurrentText(def_fmt)
            format_combo.currentIndexChanged.connect(self._save_role_policies_from_table)
            self.data_sources_table.setCellWidget(row, 5, format_combo)

        self.data_sources_table.blockSignals(False)

    def _save_role_policies_from_table(self, *args):
        policies = {}
        for row in range(self.data_sources_table.rowCount()):
            item0 = self.data_sources_table.item(row, 0)
            if not item0: continue
            role_id = item0.data(Qt.UserRole)
            if not role_id: continue

            action_combo = self.data_sources_table.cellWidget(row, 1)
            curr_action = action_combo.currentData() if action_combo else "copy"

            ident_item = self.data_sources_table.item(row, 2)
            ro_item = self.data_sources_table.item(row, 3)
            search_item = self.data_sources_table.item(row, 4)

            format_combo = self.data_sources_table.cellWidget(row, 5)
            curr_fmt = format_combo.currentText() if format_combo else "(data.gpkg)"

            policies[role_id] = {
                "action": curr_action,
                "identifiable": ident_item.checkState() == Qt.Checked if ident_item else True,
                "readonly": ro_item.checkState() == Qt.Checked if ro_item else False,
                "searchable": search_item.checkState() == Qt.Checked if search_item else True,
                "format": curr_fmt,
            }

        settings = QSettings()
        settings.setValue("gmd_pipeline/role_policies_dict", json.dumps(policies))

    def _on_data_source_changed(self, item):
        self._save_role_policies_from_table()

    def _is_excluded_data_source_layer(self, layer_name):
        """
        Check if a layer name ends with any of the excluded system role layer pattern suffixes:
        _bldg_point, _bldgpts, _bgy, _ea, _landmark, _block, _road, _river, _bridge, _railroad.
        Exempts layers ending with '_special_ea'.
        """
        if not layer_name:
            return True
        name_lower = layer_name.strip().lower()
        if name_lower.endswith("_special_ea"):
            return False
        excluded_patterns = [
            "_bldg_point",
            "_bldgpts",
            "_bgy",
            "_ea",
            "_landmark",
            "_block",
            "_road",
            "_river",
            "_bridge",
            "_railroad",
        ]
        for pat in excluded_patterns:
            if name_lower.endswith(pat):
                return True
        return False

    def _on_toggle_layer_data_sources(self, *args):
        """Open a popup dialog to configure per-layer data source properties for active layers."""
        self._show_layer_data_sources_dialog()

    def _show_layer_data_sources_dialog(self):
        """Popup additional UI dialog for per-layer data sources."""
        parent_widget = getattr(self, 'config_dialog', None) or self
        dialog = QDialog(parent_widget)
        dialog.setWindowTitle(self.tr("Per-Layer Data Sources"))
        dialog.resize(750, 450)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        info_label = QLabel(self.tr("Configure per-layer data source properties for active project layers (excluding standard system role layers):"))
        info_label.setStyleSheet("color: #444; font-size: 11px;")
        layout.addWidget(info_label)

        table = QTableWidget()
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels([
            self.tr("Layer Name"), self.tr("QField Action"),
            self.tr("Identifiable"), self.tr("Read-only"),
            self.tr("Searchable"), self.tr("Export Format")
        ])

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setAlternatingRowColors(True)

        layout.addWidget(table)

        self._populate_popup_layer_data_sources(table)

        table.itemChanged.connect(lambda item: self._save_popup_layer_data_sources(table))

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok)
        btn_box.accepted.connect(dialog.accept)
        layout.addWidget(btn_box)

        dialog.exec_()

    def _populate_popup_layer_data_sources(self, table):
        """Populate the popup dialog per-layer data sources table with active layers, excluding base layers, rasters, and system role layers matching excluded suffixes."""
        table.blockSignals(True)
        table.setRowCount(0)

        base_layer_ids = self._get_base_layer_ids()

        settings = QSettings()
        saved_json = settings.value("gmd_pipeline/layer_data_sources_dict", "{}")
        try:
            saved_layer_ds = json.loads(saved_json)
            if not isinstance(saved_layer_ds, dict):
                saved_layer_ds = {}
        except Exception:
            saved_layer_ds = {}

        project = QgsProject.instance()
        layers = sorted(project.mapLayers().values(), key=lambda l: l.name())

        row = 0
        for lyr in layers:
            if lyr.id() in base_layer_ids or isinstance(lyr, QgsRasterLayer):
                continue

            if self._is_excluded_data_source_layer(lyr.name()):
                continue

            table.setRowCount(row + 1)
            saved = saved_layer_ds.get(lyr.id(), {})

            name_item = QTableWidgetItem(lyr.name())
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            name_item.setData(Qt.UserRole, lyr.id())
            table.setItem(row, 0, name_item)

            action_combo = QComboBox()
            action_combo.addItem(self.tr("Offline Editing"), "offline")
            action_combo.addItem(self.tr("Copy / Read-Only"), "copy")
            curr_action = saved.get("action", None)
            if curr_action is None:
                try:
                    layer_source = LayerSource(lyr)
                    if layer_source.action == SyncAction.OFFLINE:
                        curr_action = "offline"
                    else:
                        curr_action = "copy"
                except Exception:
                    curr_action = "copy"
            action_combo.setCurrentIndex(0 if curr_action == "offline" else 1)
            action_combo.currentIndexChanged.connect(lambda _, t=table: self._save_popup_layer_data_sources(t))
            table.setCellWidget(row, 1, action_combo)

            ident_item = QTableWidgetItem()
            ident_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            if "identifiable" in saved:
                ident_item.setCheckState(Qt.Checked if saved["identifiable"] else Qt.Unchecked)
            else:
                try:
                    ident_flag = Qgis.MapLayerFlag.Identifiable if hasattr(Qgis, "MapLayerFlag") else QgsMapLayer.Identifiable
                    ident_item.setCheckState(Qt.Checked if (lyr.flags() & ident_flag) else Qt.Unchecked)
                except Exception:
                    ident_item.setCheckState(Qt.Checked)
            table.setItem(row, 2, ident_item)

            ro_item = QTableWidgetItem()
            ro_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            if "readonly" in saved:
                ro_item.setCheckState(Qt.Checked if saved["readonly"] else Qt.Unchecked)
            else:
                is_ro = lyr.readOnly() if hasattr(lyr, "readOnly") else False
                ro_item.setCheckState(Qt.Checked if is_ro else Qt.Unchecked)
            table.setItem(row, 3, ro_item)

            search_item = QTableWidgetItem()
            search_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            if "searchable" in saved:
                search_item.setCheckState(Qt.Checked if saved["searchable"] else Qt.Unchecked)
            else:
                try:
                    search_flag = Qgis.MapLayerFlag.Searchable if hasattr(Qgis, "MapLayerFlag") else QgsMapLayer.Searchable
                    search_item.setCheckState(Qt.Checked if (lyr.flags() & search_flag) else Qt.Unchecked)
                except Exception:
                    search_item.setCheckState(Qt.Checked)
            table.setItem(row, 4, search_item)

            format_combo = QComboBox()
            format_combo.addItems(["(data.gpkg)", ".geojson", ".gpkg", ".shp"])
            curr_fmt = saved.get("format", "(data.gpkg)")
            if curr_fmt in ("(data.gpkg)", ".geojson", ".gpkg", ".shp"):
                format_combo.setCurrentText(curr_fmt)
            format_combo.currentIndexChanged.connect(lambda _, t=table: self._save_popup_layer_data_sources(t))
            table.setCellWidget(row, 5, format_combo)

            row += 1

        table.blockSignals(False)

    def _save_popup_layer_data_sources(self, table):
        """Persist per-layer data source settings from popup table to QSettings."""
        settings = QSettings()
        saved_json = settings.value("gmd_pipeline/layer_data_sources_dict", "{}")
        try:
            layer_ds = json.loads(saved_json)
            if not isinstance(layer_ds, dict):
                layer_ds = {}
        except Exception:
            layer_ds = {}

        for row in range(table.rowCount()):
            item0 = table.item(row, 0)
            if not item0:
                continue
            layer_id = item0.data(Qt.UserRole)
            if not layer_id:
                continue

            action_combo = table.cellWidget(row, 1)
            curr_action = action_combo.currentData() if action_combo else "copy"

            ident_item = table.item(row, 2)
            ro_item = table.item(row, 3)
            search_item = table.item(row, 4)

            format_combo = table.cellWidget(row, 5)
            curr_fmt = format_combo.currentText() if format_combo else "(data.gpkg)"

            layer_ds[layer_id] = {
                "action": curr_action,
                "identifiable": ident_item.checkState() == Qt.Checked if ident_item else True,
                "readonly": ro_item.checkState() == Qt.Checked if ro_item else False,
                "searchable": search_item.checkState() == Qt.Checked if search_item else True,
                "format": curr_fmt,
            }

        settings.setValue("gmd_pipeline/layer_data_sources_dict", json.dumps(layer_ds))

    def _get_base_layer_ids(self):
        """Return a set of layer IDs that belong to any group named 'Base Layers' (case-insensitive)."""
        base_ids = set()
        root = QgsProject.instance().layerTreeRoot()

        def collect_from_group(group_node):
            for child in group_node.children():
                if isinstance(child, QgsLayerTreeGroup):
                    if child.name().strip().lower() == "base layers":
                        _collect_all_layer_ids(child, base_ids)
                    else:
                        collect_from_group(child)

        def _collect_all_layer_ids(group_node, id_set):
            for child in group_node.children():
                if isinstance(child, QgsLayerTreeLayer):
                    lyr = child.layer()
                    if lyr:
                        id_set.add(lyr.id())
                elif isinstance(child, QgsLayerTreeGroup):
                    _collect_all_layer_ids(child, id_set)

        collect_from_group(root)
        return base_ids

    def _populate_layer_data_sources(self):
        """Populate the per-layer data sources table with all active layers, excluding Base Layers group."""
        self.layer_data_sources_table.blockSignals(True)
        self.layer_data_sources_table.setRowCount(0)

        base_layer_ids = self._get_base_layer_ids()

        # Load saved per-layer overrides
        settings = QSettings()
        saved_json = settings.value("gmd_pipeline/layer_data_sources_dict", "{}")
        try:
            saved_layer_ds = json.loads(saved_json)
            if not isinstance(saved_layer_ds, dict):
                saved_layer_ds = {}
        except Exception:
            saved_layer_ds = {}

        project = QgsProject.instance()
        layers = sorted(project.mapLayers().values(), key=lambda l: l.name())

        row = 0
        for lyr in layers:
            # Skip base layers and raster layers
            if lyr.id() in base_layer_ids:
                continue
            if isinstance(lyr, QgsRasterLayer):
                continue

            self.layer_data_sources_table.setRowCount(row + 1)

            # Read saved overrides or use defaults from layer state
            saved = saved_layer_ds.get(lyr.id(), {})

            # Col 0: Layer Name (read-only)
            name_item = QTableWidgetItem(lyr.name())
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            name_item.setData(Qt.UserRole, lyr.id())
            self.layer_data_sources_table.setItem(row, 0, name_item)

            # Col 1: QField Action
            action_combo = QComboBox()
            action_combo.addItem(self.tr("Offline Editing"), "offline")
            action_combo.addItem(self.tr("Copy / Read-Only"), "copy")
            curr_action = saved.get("action", None)
            if curr_action is None:
                # Detect from layer's current QFieldSync/action property
                try:
                    layer_source = LayerSource(lyr)
                    if layer_source.action == SyncAction.OFFLINE:
                        curr_action = "offline"
                    else:
                        curr_action = "copy"
                except Exception:
                    curr_action = "copy"
            action_combo.setCurrentIndex(0 if curr_action == "offline" else 1)
            action_combo.currentIndexChanged.connect(self._save_layer_data_sources)
            self.layer_data_sources_table.setCellWidget(row, 1, action_combo)

            # Col 2: Identifiable
            ident_item = QTableWidgetItem()
            ident_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            if "identifiable" in saved:
                ident_item.setCheckState(Qt.Checked if saved["identifiable"] else Qt.Unchecked)
            else:
                # Read from QGIS layer flags
                try:
                    ident_flag = Qgis.MapLayerFlag.Identifiable if hasattr(Qgis, "MapLayerFlag") else QgsMapLayer.Identifiable
                    ident_item.setCheckState(Qt.Checked if (lyr.flags() & ident_flag) else Qt.Unchecked)
                except Exception:
                    ident_item.setCheckState(Qt.Checked)
            self.layer_data_sources_table.setItem(row, 2, ident_item)

            # Col 3: Read-only
            ro_item = QTableWidgetItem()
            ro_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            if "readonly" in saved:
                ro_item.setCheckState(Qt.Checked if saved["readonly"] else Qt.Unchecked)
            else:
                is_ro = lyr.readOnly() if hasattr(lyr, "readOnly") else False
                ro_item.setCheckState(Qt.Checked if is_ro else Qt.Unchecked)
            self.layer_data_sources_table.setItem(row, 3, ro_item)

            # Col 4: Searchable
            search_item = QTableWidgetItem()
            search_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            if "searchable" in saved:
                search_item.setCheckState(Qt.Checked if saved["searchable"] else Qt.Unchecked)
            else:
                try:
                    search_flag = Qgis.MapLayerFlag.Searchable if hasattr(Qgis, "MapLayerFlag") else QgsMapLayer.Searchable
                    search_item.setCheckState(Qt.Checked if (lyr.flags() & search_flag) else Qt.Unchecked)
                except Exception:
                    search_item.setCheckState(Qt.Checked)
            self.layer_data_sources_table.setItem(row, 4, search_item)

            # Col 5: Export Format
            format_combo = QComboBox()
            format_combo.addItems(["(data.gpkg)", ".geojson", ".gpkg", ".shp"])
            curr_fmt = saved.get("format", "(data.gpkg)")
            if curr_fmt in ("(data.gpkg)", ".geojson", ".gpkg", ".shp"):
                format_combo.setCurrentText(curr_fmt)
            format_combo.currentIndexChanged.connect(self._save_layer_data_sources)
            self.layer_data_sources_table.setCellWidget(row, 5, format_combo)

            row += 1

        self.layer_data_sources_table.blockSignals(False)

    def _save_layer_data_sources(self, *args):
        """Persist per-layer data source settings to QSettings."""
        layer_ds = {}
        for row in range(self.layer_data_sources_table.rowCount()):
            item0 = self.layer_data_sources_table.item(row, 0)
            if not item0:
                continue
            layer_id = item0.data(Qt.UserRole)
            if not layer_id:
                continue

            action_combo = self.layer_data_sources_table.cellWidget(row, 1)
            curr_action = action_combo.currentData() if action_combo else "copy"

            ident_item = self.layer_data_sources_table.item(row, 2)
            ro_item = self.layer_data_sources_table.item(row, 3)
            search_item = self.layer_data_sources_table.item(row, 4)

            format_combo = self.layer_data_sources_table.cellWidget(row, 5)
            curr_fmt = format_combo.currentText() if format_combo else "(data.gpkg)"

            layer_ds[layer_id] = {
                "action": curr_action,
                "identifiable": ident_item.checkState() == Qt.Checked if ident_item else True,
                "readonly": ro_item.checkState() == Qt.Checked if ro_item else False,
                "searchable": search_item.checkState() == Qt.Checked if search_item else True,
                "format": curr_fmt,
            }

        settings = QSettings()
        settings.setValue("gmd_pipeline/layer_data_sources_dict", json.dumps(layer_ds))

    def _on_layer_data_source_item_changed(self, item):
        """Handle checkbox changes in the per-layer data sources table."""
        self._save_layer_data_sources()

    def _apply_role_policies_to_project_layers(self):
        """Applies configured Role Policies (identifiable, readonly, searchable) to project layers based on Layer Groups & Styles assignments."""
        settings = QSettings()
        user_json = settings.value("gmd_pipeline/role_policies_dict", "{}")
        try:
            saved_policies = json.loads(user_json)
            if not isinstance(saved_policies, dict): saved_policies = {}
        except Exception:
            saved_policies = {}

        default_policies = {
            "_ea_combo_bldg":     {"action": "offline", "identifiable": True, "readonly": False, "searchable": True},
            "_ea_combo_bgy":      {"action": "copy",    "identifiable": True, "readonly": True,  "searchable": True},
            "_ea_combo_ea":       {"action": "copy",    "identifiable": True, "readonly": True,  "searchable": True},
            "_ea_combo_landmark": {"action": "copy",    "identifiable": True, "readonly": True,  "searchable": True},
            "_ea_combo_block":    {"action": "copy",    "identifiable": True, "readonly": True,  "searchable": True},
            "_ea_combo_road":     {"action": "copy",    "identifiable": True, "readonly": True,  "searchable": True},
            "_ea_combo_river":    {"action": "copy",    "identifiable": True, "readonly": True,  "searchable": True},
            "_ea_combo_bridge":   {"action": "copy",    "identifiable": True, "readonly": True,  "searchable": True},
            "_ea_combo_railroad": {"action": "copy",    "identifiable": True, "readonly": True,  "searchable": True},
        }

        project = QgsProject.instance()

        def get_item_role(item):
            combo = self.layer_groups_tree.itemWidget(item, 1)
            if combo and combo.currentData():
                return combo.currentData()
            return None

        def process_item(item):
            is_layer = item.data(0, Qt.UserRole + 1) == "layer" or item.data(0, Qt.UserRole) is not None
            if is_layer:
                layer_id = item.data(0, Qt.UserRole)
                lyr = project.mapLayer(layer_id) if layer_id else None
                if not lyr:
                    raw_name = item.text(0).strip()
                    match = project.mapLayersByName(raw_name)
                    if match: lyr = match[0]

                if lyr:
                    role_id = get_item_role(item)
                    if role_id:
                        policy = saved_policies.get(role_id, default_policies.get(role_id, {}))
                        if policy:
                            action_val = policy.get("action")
                            if action_val:
                                try:
                                    layer_source = LayerSource(lyr)
                                    if action_val == "offline":
                                        layer_source.action = SyncAction.OFFLINE
                                    elif action_val == "copy":
                                        layer_source.action = SyncAction.COPY
                                except Exception:
                                    lyr.setCustomProperty("QFieldSync/action", action_val)

                            try:
                                flags = lyr.flags()
                                ident_flag = Qgis.MapLayerFlag.Identifiable if hasattr(Qgis, "MapLayerFlag") else QgsMapLayer.Identifiable
                                search_flag = Qgis.MapLayerFlag.Searchable if hasattr(Qgis, "MapLayerFlag") else QgsMapLayer.Searchable
                                
                                if policy.get("identifiable", True):
                                    flags |= ident_flag
                                else:
                                    flags &= ~ident_flag

                                if policy.get("searchable", True):
                                    flags |= search_flag
                                else:
                                    flags &= ~search_flag

                                lyr.setFlags(flags)
                            except Exception as e:
                                print(f"[ROLE POLICY FLAG ERROR] {e}")

                            if hasattr(lyr, "setReadOnly"):
                                lyr.setReadOnly(policy.get("readonly", False))

            for c in range(item.childCount()):
                process_item(item.child(c))

        for i in range(self.layer_groups_tree.topLevelItemCount()):
            process_item(self.layer_groups_tree.topLevelItem(i))

        # ── Apply per-layer overrides from Data Source table ──────────────
        # Per-layer settings take priority over role-based policies.
        layer_ds_json = settings.value("gmd_pipeline/layer_data_sources_dict", "{}")
        try:
            layer_ds_policies = json.loads(layer_ds_json)
            if not isinstance(layer_ds_policies, dict):
                layer_ds_policies = {}
        except Exception:
            layer_ds_policies = {}

        for layer_id, policy in layer_ds_policies.items():
            lyr = project.mapLayer(layer_id)
            if not lyr or not policy:
                continue

            action_val = policy.get("action")
            if action_val:
                try:
                    layer_source = LayerSource(lyr)
                    if action_val == "offline":
                        layer_source.action = SyncAction.OFFLINE
                    elif action_val == "copy":
                        layer_source.action = SyncAction.COPY
                except Exception:
                    lyr.setCustomProperty("QFieldSync/action", action_val)

            try:
                flags = lyr.flags()
                ident_flag = Qgis.MapLayerFlag.Identifiable if hasattr(Qgis, "MapLayerFlag") else QgsMapLayer.Identifiable
                search_flag = Qgis.MapLayerFlag.Searchable if hasattr(Qgis, "MapLayerFlag") else QgsMapLayer.Searchable

                if policy.get("identifiable", True):
                    flags |= ident_flag
                else:
                    flags &= ~ident_flag

                if policy.get("searchable", True):
                    flags |= search_flag
                else:
                    flags &= ~search_flag

                lyr.setFlags(flags)
            except Exception as e:
                print(f"[PER-LAYER POLICY FLAG ERROR] {e}")

            if hasattr(lyr, "setReadOnly"):
                lyr.setReadOnly(policy.get("readonly", False))

    def _update_lists_from_filter_tree(self):
        pass

    def _adjust_widget_height_to_content(self, widget, min_height=80, max_height=250):
        if not widget:
            return
        
        if isinstance(widget, QTreeWidget):
            count = 0
            def count_visible(item):
                nonlocal count
                if item.isHidden():
                    return
                count += 1
                if item.isExpanded():
                    for i in range(item.childCount()):
                        count_visible(item.child(i))
                        
            for i in range(widget.topLevelItemCount()):
                count_visible(widget.topLevelItem(i))
                
            row_height = widget.sizeHintForRow(0)
            if row_height <= 0:
                row_height = 22 # fallback row height
                
            header_height = widget.header().height() if not widget.isHeaderHidden() else 0
            frame_width = widget.frameWidth() * 2
            calculated_height = (count * row_height) + header_height + frame_width + 6
            
        elif isinstance(widget, QListWidget):
            count = 0
            for i in range(widget.count()):
                if not widget.item(i).isHidden():
                    count += 1
            row_height = widget.sizeHintForRow(0)
            if row_height <= 0:
                row_height = 22 # fallback row height
            frame_width = widget.frameWidth() * 2
            calculated_height = (count * row_height) + frame_width + 6
        else:
            return

        target_height = max(min_height, min(calculated_height, max_height))
        widget.setFixedHeight(target_height)

    def _on_tree_search_changed(self, text):
        search_str = text.lower()
        for i in range(self._filter_tree_widget.topLevelItemCount()):
            parent_item = self._filter_tree_widget.topLevelItem(i)
            if search_str in parent_item.text(0).lower():
                parent_item.setHidden(False)
            else:
                parent_item.setHidden(True)
        self._adjust_widget_height_to_content(self._filter_tree_widget)

    def eventFilter(self, source, event):
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Space:
            target_tree = None
            if hasattr(self, '_filter_tree_widget') and (source is self._filter_tree_widget or (hasattr(self._filter_tree_widget, 'viewport') and source is self._filter_tree_widget.viewport())):
                target_tree = self._filter_tree_widget
                is_filter_tree = True
            elif hasattr(self, 'layer_groups_tree') and (source is self.layer_groups_tree or (hasattr(self.layer_groups_tree, 'viewport') and source is self.layer_groups_tree.viewport())):
                target_tree = self.layer_groups_tree
                is_filter_tree = False

            if target_tree:
                selected_items = target_tree.selectedItems()
                if selected_items:
                    first_item_state = selected_items[0].checkState(0)
                    new_state = Qt.Unchecked if first_item_state == Qt.Checked else Qt.Checked
                    
                    def set_check_recursive(item, state):
                        item.setCheckState(0, state)
                        for i in range(item.childCount()):
                            set_check_recursive(item.child(i), state)

                    target_tree.blockSignals(True)
                    for item in selected_items:
                        set_check_recursive(item, new_state)
                    target_tree.blockSignals(False)
                    if is_filter_tree and hasattr(self, '_update_lists_from_filter_tree'):
                        self._update_lists_from_filter_tree()
                    return True # Event handled
        
        return super(PackageDialog, self).eventFilter(source, event)

    def _update_ui_for_output_level(self):
        """Show/hide controls based on the selected output level."""
        is_ea = self.output_dropdown.currentText() == self.tr("EA Level")
        is_bgy = self.output_dropdown.currentText() == self.tr("Barangay Level")

        # Controls hidden in EA Level and Barangay Level (handled by batch Export)
        _hide = is_ea or is_bgy
        self.label.setVisible(not _hide)          # "Select Base Layer" (group label)
        self.group_dropdown.setVisible(not _hide)
        self.label_5.setVisible(not _hide)        # "Select Barangay Geocode"
        self.geocode_dropdown.setVisible(not _hide)
        self.run_button.setVisible(not _hide)     # Filter button
        self.next_geocode.setVisible(not _hide)   # Next Geocode button
        self.run_batch.setVisible(not _hide)      # Batch button
        self.run_clip.setVisible(False)           # Clip button removed (batch-only)

        # Old Dropdowns are now completely hidden to avoid confusion
        self.label_7.setVisible(False)
        self.citymun_dropdown.setVisible(False)
        self.label_9.setVisible(False)
        self.bgy_dropdown.setVisible(False)

        if is_ea:
            self.label_3.setText(self.tr("Select EA Layer"))
        elif is_bgy:
            self.label_3.setText(self.tr("Select Barangay Layer"))
        else:
            self.label_3.setText(self.tr("Select Layer"))

        # For EA/Barangay Level, enable Export as soon as a layer is loaded;
        if is_ea or is_bgy:
            self.button_box.button(QDialogButtonBox.Save).setEnabled(self.layer_dropdown.count() > 0)
        else:
            self.button_box.button(QDialogButtonBox.Save).setEnabled(self.geocode_dropdown.count() > 0)

        if hasattr(self, '_filter_tree_label'):
            self._filter_tree_label.setVisible(is_bgy or is_ea)
            self._filter_tree_search_bar.setVisible(is_bgy or is_ea)
            self._filter_tree_widget.setVisible(is_bgy or is_ea)
            self._filter_tree_btn_container.setVisible(is_bgy or is_ea)

        # Update Layer Groups & Styles Tree Widget with Base Layers if empty
        if hasattr(self, '_update_layer_assignment_ui') and hasattr(self, 'layer_groups_tree'):
            if self.layer_groups_tree.topLevelItemCount() == 0:
                self._update_layer_assignment_ui()


        # Note: Raster config and individual exports are handled via the Configuration dialog

    def showEvent(self, event):
        super(PackageDialog, self).showEvent(event)
        self.button_box.button(QDialogButtonBox.Save).setText(self.tr("Export"))

    def next_geo(self):
        # Check if "Base Layers" group is selected
        if self.group_dropdown.currentText() != "Base Layers":
            QMessageBox.warning(self, "Group Selection", "Please select the Base Layers group.")
            return
        
        current_index = self.geocode_dropdown.currentIndex()
        total_items = self.geocode_dropdown.count()

        if current_index < total_items - 1:
            self.geocode_dropdown.setCurrentIndex(current_index + 1)
        else:
            QMessageBox.information(self, "End of List", "You have reached the end of the geocode list.")

    def validate_group_selection(self):
        """Enable/disable next_geo and run_batch buttons based on group selection."""
        selected_group = self.group_dropdown.currentData() or self.group_dropdown.currentText()
        is_base_layers = str(selected_group).strip().lower() == "base layers"
        self.next_geocode.setEnabled(is_base_layers)
        self.run_batch.setEnabled(is_base_layers)

    def batch(self):
        """Run filter, clip, and export from the selected geocode onward.

        Do not reset the dropdown inside the loop (reset once after processing all items),
        otherwise the remaining geocodes are cleared and iteration stops.
        """
        if self.is_batch_mode:
            QMessageBox.information(self, "Batch Run", "Batch processing is already running.")
            return

        count = self.geocode_dropdown.count()
        if count == 0:
            QMessageBox.information(self, "Batch Run", "No geocodes available to process.")
            return

        start_index = self.geocode_dropdown.currentIndex()
        if start_index < 0:
            start_index = 0
        
        # Set batch mode flag to prevent dialog from closing during processing
        self.is_batch_mode = True
        self._set_batch_ui_locked(True)

        geocodes = [
            self.geocode_dropdown.itemText(i)
            for i in range(start_index, count)
        ]
        last_geocode_processed = None
        processed_count = 0
        errors = []

        try:
            for code in geocodes:
                try:
                    # Check if cancel was requested
                    if self.batch_cancel_requested:
                        break

                    # Select the geocode so other methods read the correct currentText
                    idx = self.geocode_dropdown.findText(code)
                    if idx != -1:
                        self.geocode_dropdown.setCurrentIndex(idx)

                    # Filtering
                    self.run()

                    # Raster clip (wait for worker to finish)
                    self.run_raster()
                    if hasattr(self, 'worker') and getattr(self, 'worker') is not None:
                        try:
                            # wait with a timeout to avoid indefinite blocking
                            self.worker.wait(300000)
                            # Ensure queued finished-signal UI updates (including
                            # raster layer registration) are processed before export.
                            QApplication.processEvents()
                        except Exception:
                            pass

                    # Export
                    self.package_project()

                    # Allow the event loop to process (UI updates, signals)
                    try:
                        QApplication.processEvents()
                    except Exception:
                        pass

                    last_geocode_processed = code
                    processed_count += 1

                except Exception as e:
                    errors.append(f"{code}: {e}")

            # Reset once after all iterations
            try:
                self.reset_filter()
            except Exception:
                pass
        finally:
            # Check if batch was cancelled before resetting flags
            was_cancelled = self.batch_cancel_requested

            # Exit batch mode
            self.is_batch_mode = False
            self.batch_cancel_requested = False
            self._set_batch_ui_locked(False)

        # Determine message based on cancellation status
        if was_cancelled:
            summary = f"Batch Run Cancelled\n\nProcessed: {processed_count}\nLast processed: {last_geocode_processed or 'none'}"
        else:
            summary = f"Total geocodes processed: {processed_count}\nLast processed: {last_geocode_processed or 'none'}"
        
        # Store results for display
        self.batch_summary = summary
        
        # Defer message box and dialog close to allow batch to complete fully
        QTimer.singleShot(100, self._show_batch_completion_and_close)

    def _show_batch_completion_and_close(self):
        """Helper method to show batch completion message and close dialog."""
        QMessageBox.information(None, "Batch Run Completed", self.batch_summary)

        # After an EA batch, OfflineConverter has left all project layers in
        # offline mode (datasources repointed to export .gpkg files).  Reload
        # the original project to restore layer states so that interacting with
        # layers afterwards doesn't crash QGIS.
        if getattr(self, "_reload_project_after_ea_batch", False):
            self._reload_project_after_ea_batch = False
            try:
                project_file = QgsProject.instance().fileName()
                if project_file and os.path.exists(project_file):
                    QgsProject.instance().read(project_file)
            except Exception:
                pass

    def reject(self):
        """Override reject to handle batch cancellation."""
        if self.is_batch_mode:
            self.batch_cancel_requested = True
        else:
            super().reject()


    def _on_raster_type_changed(self, index):
        if not hasattr(self, 'select_rasterlayer'):
            return
        if index == 0:
            self.select_rasterlayer.setFilter(self.tr("Raster Layer (*_img.gpkg);;GeoPackage files (*.gpkg)"))
            if hasattr(self, 'raster_subtitle_label'):
                self.raster_subtitle_label.setText(self.tr("Acceptable filename: *_img.gpkg"))
        elif index == 1:
            self.select_rasterlayer.setFilter(self.tr("Raster Layer (*_img.mbtiles);;MBTiles files (*.mbtiles)"))
            if hasattr(self, 'raster_subtitle_label'):
                self.raster_subtitle_label.setText(self.tr("Acceptable filename: *_img.mbtiles"))
        elif index == 2:
            self.select_rasterlayer.setFilter(self.tr("Raster Layer (*_img.gpkg *_img.mbtiles);;GeoPackage files (*.gpkg);;MBTiles files (*.mbtiles)"))
            if hasattr(self, 'raster_subtitle_label'):
                self.raster_subtitle_label.setText(self.tr("Acceptable filenames: *_img.gpkg or *_img.mbtiles"))

    def update_raster_path(self, new_path):
        settings = QSettings()
        is_ea = self.output_dropdown.currentText() == self.tr("EA Level")
        is_bgy = self.output_dropdown.currentText() == self.tr("Barangay Level")
        
        if is_ea or is_bgy:
            settings.setValue("satellite_dir_path", new_path)
            print(f"Updated satellite directory path: {new_path}")
        else:
            settings.setValue("raster_file_path", new_path)
            print(f"Updated raster file path: {new_path}")
        
    def update_progress(self, sent, total):
        progress = float(sent) / total * 100
        self.progress_bar.setValue(progress)

    def setup_gui(self):
        """Populate gui and connect signals of the push dialog"""
        # Restore the last manually selected export directory if available
        try:
            manual_export_dir = self.qfield_preferences.value("exportDirectoryManual")
        except NameError:
            manual_export_dir = None
        if manual_export_dir:
            export_dirname = manual_export_dir
        else:
            try:
                export_dirname = self.qfield_preferences.value("exportDirectoryProject")
            except NameError:
                export_dirname = None
            
            # Extract parent directory from the subfolder path created during export
            # This ensures we always show the directory the user selected, not the export subfolder
            if export_dirname:
                parent_path = str(Path(export_dirname).parent)
                # Use parent if it's different from current (i.e., current is a subfolder)
                if os.path.isdir(parent_path) and parent_path != export_dirname:
                    export_dirname = parent_path
            
            if not export_dirname:
                export_dirname = os.path.join(
                    self.qfield_preferences.value("exportDirectory"),
                    fileparts(QgsProject.instance().fileName())[1],
                )

        self.manualDir.setText(QDir.toNativeSeparators(str(export_dirname)))
        # Connect folder selector and save selection to preferences
        def select_folder():
            make_folder_selector(self.manualDir)()
            try:
                self.qfield_preferences.set_value("exportDirectoryManual", self.manualDir.text())
            except NameError:
                if hasattr(self.qfield_preferences, "register_setting"):
                    self.qfield_preferences.register_setting("exportDirectoryManual", self.manualDir.text())
                else:
                    pass
        self.manualDir_btn.clicked.connect(select_folder)
        self.update_info_visibility()

        self.nextButton.clicked.connect(lambda: self.show_package_page())
        self.nextButton.setVisible(False)
        self.update_button_box_visibility()


        self.dirsToCopyWidget.set_path(QgsProject().instance().homePath())
        self.dirsToCopyWidget.refresh_tree()

        # Skip the QFieldSync project checker warnings completely
        self.show_package_page()

    def _disable_unused_qfield_actions(self):
        """Temporarily sets QFieldSync/action to 'no_action' for unselected layers.
        Returns a dict of original actions so they can be restored.
        """
        project = QgsProject.instance()
        tree_checked_layer_ids = set()
        tree_unchecked_layer_ids = set()
        
        # 1. Group Panel (LayerGroupsTreeWidget) - traverse recursively
        if hasattr(self, 'layer_groups_tree'):
            def collect_tree_states(item):
                lid = item.data(0, Qt.UserRole)
                if lid:
                    if item.checkState(0) == Qt.Checked:
                        tree_checked_layer_ids.add(lid)
                    else:
                        tree_unchecked_layer_ids.add(lid)
                for i in range(item.childCount()):
                    collect_tree_states(item.child(i))

            for i in range(self.layer_groups_tree.topLevelItemCount()):
                collect_tree_states(self.layer_groups_tree.topLevelItem(i))

        # 3. Raster Configuration
        if hasattr(self, 'raster_table'):
            for row in range(self.raster_table.rowCount()):
                chk_item = self.raster_table.item(row, 0)
                if chk_item and chk_item.checkState() == Qt.Checked:
                    layer_id = chk_item.data(Qt.UserRole)
                    if layer_id:
                        tree_checked_layer_ids.add(layer_id)

        # 4. Per-layer Data Source Configuration
        settings = QSettings()
        layer_ds_json = settings.value("gmd_pipeline/layer_data_sources_dict", "{}")
        try:
            layer_ds_policies = json.loads(layer_ds_json)
            if isinstance(layer_ds_policies, dict):
                for layer_id in layer_ds_policies.keys():
                    tree_checked_layer_ids.add(layer_id)
        except Exception:
            pass
                        
        original_actions = {}
        original_layer_names = {}
        for layer in project.mapLayers().values():
            val = layer.customProperty("QFieldSync/action")
            original_actions[layer.id()] = val if val is not None else ""

            is_generated_img = False
            lyr_name = layer.name().lower()
            lyr_source = (layer.source() or "").lower()

            if isinstance(layer, QgsRasterLayer):
                if "_img" in lyr_name or "_img" in lyr_source:
                    is_generated_img = True
                elif any(ext in lyr_name or ext in lyr_source for ext in [".mbtiles", ".tif", ".tiff", ".gpkg"]):
                    is_generated_img = True
            elif "_img" in lyr_name or "_img" in lyr_source:
                is_generated_img = True

            if is_generated_img:
                layer.setCustomProperty("QFieldSync/action", "copy")
            elif layer.id() in tree_checked_layer_ids:
                # Explicitly checked in the layer groups tree -> package layer
                if not layer.customProperty("QFieldSync/action"):
                    layer.setCustomProperty("QFieldSync/action", "copy")
            elif layer.id() in tree_unchecked_layer_ids:
                # Explicitly unchecked in the layer groups tree -> skip packaging
                layer.setCustomProperty("QFieldSync/action", "no_action")
            else:
                # Not explicitly in tree -> check for geocode attributes
                field_names = [f.name().strip().lower() for f in layer.fields()] if hasattr(layer, 'fields') else []
                known_geocodes = (
                    "ea_geocode", "eageocode", "geocode", "ea_code", "eacode",
                    "bgy_code", "bgycode", "bsn_geoid", "ean", "new_ean", "new_ea",
                    "code", "psgc", "bgy_geocode", "correspondence_ea_geocode",
                    "brgy_code", "barangay_code"
                )
                has_any_geocode = any(k in field_names for k in known_geocodes)
                if has_any_geocode:
                    layer.setCustomProperty("QFieldSync/action", "copy")
                    orig_name = layer.name()
                    m = re.match(r"^\d+_(.+)$", orig_name)
                    if m:
                        original_layer_names[layer.id()] = orig_name
                        layer.setName(m.group(1))
                else:
                    layer.setCustomProperty("QFieldSync/action", "no_action")

        self._temp_original_layer_names = original_layer_names
        return original_actions

    def _restore_qfield_actions(self, original_actions):
        """Restores QFieldSync/action and original layer names to their pre-export state."""
        project = QgsProject.instance()
        for layer_id, action in original_actions.items():
            layer = project.mapLayer(layer_id)
            if layer:
                if action == "":
                    layer.removeCustomProperty("QFieldSync/action")
                else:
                    layer.setCustomProperty("QFieldSync/action", action)

        for layer_id, orig_name in getattr(self, '_temp_original_layer_names', {}).items():
            lyr = project.mapLayer(layer_id)
            if lyr:
                lyr.setName(orig_name)
        self._temp_original_layer_names = {}

    def get_export_folder_from_dialog(self):
        """Get the export folder according to the inputs in the selected"""
        # manual
        return self.manualDir.text()

    def show_package_page(self):
        self.nextButton.setVisible(False)
        self.stackedWidget.setCurrentWidget(self.packagePage)
        # Show the top panels (Layer Assignment, Raster Configuration)
        if hasattr(self, '_top_panels_widget'):
            self._top_panels_widget.setVisible(True)
        self.update_button_box_visibility()


    def package_project(self):
        # Synchronize layer visibility check states and group structure (without re-applying QML styles)
        try:
            self._on_apply_layer_groups(apply_qml=False)
        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"Auto-sync layer visibility before package: {e}", "GMD Pipeline", Qgis.Warning)

        # EA Level uses a dedicated batch export that iterates all EA features.
        if self.output_dropdown.currentText() == self.tr("EA Level"):
            self.run_ea_batch_export()
            return
        
        # BGY Level uses a dedicated batch export that iterates all BGY features.
        if self.output_dropdown.currentText() == self.tr("Barangay Level"):
            self.run_bgy_batch_export()
            return

        self.button_box.button(QDialogButtonBox.StandardButton.Save).setEnabled(False)

        # Use existing UI elements: manualDir for export folder path
        export_folder = Path(self.manualDir.text())

        selected_geocode = self.geocode_dropdown.currentText()
        # derive code prefix based on selected output level
        prefix = selected_geocode.split('_', 1)[0] if selected_geocode else ''
        if self.output_dropdown.currentText() == self.tr("EA Level"):
            code_digits = prefix[:14]
        else:
            code_digits = prefix[:8]
        barangay_name = selected_geocode.split('_', 1)[1] if '_' in selected_geocode else ""
        subfolder_name = f"{code_digits}_{barangay_name}"

        # Create subfolder with format: "8-digit-code_barangay-name".
        # If it already exists, clear its contents in a lock-safe way so files
        # are overwritten without failing on temporarily locked rasters.
        subfolder_path = export_folder / subfolder_name
        if subfolder_path.exists():
            subfolder_abs = os.path.normcase(os.path.abspath(str(subfolder_path)))
            raster_base_name = f"{code_digits}_img.tif"
            keep_raster_abs = os.path.normcase(
                os.path.abspath(
                    getattr(
                        self,
                        "final_raster_path",
                        str(subfolder_path / raster_base_name),
                    )
                )
            )

            # Release QGIS locks for rasters currently loaded from this folder.
            project = QgsProject.instance()
            for lyr in list(project.mapLayers().values()):
                try:
                    src = lyr.source() if hasattr(lyr, "source") else ""
                    if not src or not isinstance(lyr, QgsRasterLayer):
                        continue
                    src_abs = os.path.normcase(os.path.abspath(src))
                    # Keep the current clipped raster layer in the project so
                    # OfflineConverter can package it into the exported qgz.
                    if src_abs.startswith(subfolder_abs) and src_abs != keep_raster_abs:
                        project.removeMapLayer(lyr.id())
                except Exception:
                    continue

            try:
                QApplication.processEvents()
            except Exception:
                pass

            # Remove old files/folders; skip locked files instead of crashing.
            for item in subfolder_path.iterdir():
                try:
                    # Keep the clipped raster and its sidecar files so they are
                    # still available for OfflineConverter packaging.
                    if item.is_file() and (
                        item.name == raster_base_name
                        or item.name.startswith(raster_base_name + ".")
                    ):
                        continue

                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        removed = False
                        for _ in range(5):
                            try:
                                item.unlink()
                                removed = True
                                break
                            except PermissionError:
                                QApplication.processEvents()
                                time.sleep(0.2)
                        if not removed and item.exists():
                            QgsApplication.instance().messageLog().logMessage(
                                f"Could not remove locked file before export: {item}",
                                "GMD Pipeline",
                                Qgis.Warning,
                            )
                except Exception as e:
                    QgsApplication.instance().messageLog().logMessage(
                        f"Could not clear export item '{item}': {e}",
                        "GMD Pipeline",
                        Qgis.Warning,
                    )
        subfolder_path.mkdir(parents=True, exist_ok=True)

        # Create project file path inside the subfolder
        packaged_project_file = subfolder_path / f"{code_digits}.qgz"

        area_of_interest = (
            self.__project_configuration.area_of_interest
            if self.__project_configuration.area_of_interest
            else self.iface.mapCanvas().extent().asWktPolygon()
        )
        area_of_interest_crs = (
            self.__project_configuration.area_of_interest_crs
            if self.__project_configuration.area_of_interest_crs
            else QgsProject.instance().crs().authid()
        )

        # Only update exportDirectoryProject (for internal use), never manualDir or exportDirectoryManual
        self.qfield_preferences.set_value(
            "exportDirectoryProject", str(subfolder_path)
        )
        self.dirsToCopyWidget.save_settings()
        self._ensure_ea_update_not_offline_and_writable()

        # Ensure all unassigned layers are filtered to this geocode before packaging
        is_ea_mode = self.output_dropdown.currentText() == self.tr("EA Level")
        for _unassigned_lyr in self._get_unassigned_map_layers():
            self._filter_unassigned_layer(_unassigned_lyr, code_digits, is_ea_level=is_ea_mode)

        # In batch mode, old generated rasters from previous iterations may
        # still be loaded and get copied again. Keep only the current raster.
        try:
            keep_sources = set()
            if hasattr(self, 'temp_raster_path') and self.temp_raster_path:
                keep_sources.add(os.path.normcase(os.path.abspath(self.temp_raster_path)))

            project = QgsProject.instance()
            for lyr in list(project.mapLayers().values()):
                if not isinstance(lyr, QgsRasterLayer):
                    continue
                src = lyr.source() or ""
                if not src:
                    continue
                src_abs = os.path.normcase(os.path.abspath(src))
                src_name = os.path.basename(src_abs).lower()
                lyr_name = (lyr.name() or "").lower()
                is_generated_img = src_name.endswith('_img.tif') or lyr_name.endswith('_img') or lyr_name.endswith('_img.tif')
                if is_generated_img and src_abs not in keep_sources:
                    project.removeMapLayer(lyr.id())
        except Exception:
            pass

        # Safety net: in batch mode, if raster completion signal has not yet
        # materialized the current raster layer in project, add/update it now.
        try:
            desired_raster_name = f"{code_digits}_img"
            current_raster_path = None
            if hasattr(self, 'temp_raster_path') and self.temp_raster_path and os.path.exists(self.temp_raster_path):
                current_raster_path = self.temp_raster_path
            elif hasattr(self, 'final_raster_path') and self.final_raster_path and os.path.exists(self.final_raster_path):
                current_raster_path = self.final_raster_path

            if current_raster_path:
                current_abs = os.path.normcase(os.path.abspath(current_raster_path))
                found_current = False
                for lyr in QgsProject.instance().mapLayers().values():
                    if not isinstance(lyr, QgsRasterLayer):
                        continue
                    src = lyr.source() or ""
                    if src and os.path.normcase(os.path.abspath(src)) == current_abs:
                        lyr.setName(desired_raster_name)
                        found_current = True
                        break

                if not found_current:
                    raster_layer = QgsRasterLayer(current_raster_path, desired_raster_name)
                    if raster_layer.isValid():
                        QgsProject.instance().addMapLayer(raster_layer, False)
                        QgsProject.instance().layerTreeRoot().addLayer(raster_layer)
                        self.clipped_raster_layer = raster_layer
        except Exception:
            pass

        def _build_converter(offliner_instance):
            converter = OfflineConverter(
                self.project,
                packaged_project_file,
                area_of_interest,
                area_of_interest_crs,
                self.qfield_preferences.value("attachmentDirs"),
                offliner_instance,
                ExportType.Cable,
                dirs_to_copy=self.dirsToCopyWidget.dirs_to_copy(),
                export_title=code_digits,
            )
            converter.total_progress_updated.connect(self.update_total)
            converter.task_progress_updated.connect(self.update_task)
            converter.warning.connect(
                lambda title, body: QMessageBox.warning(None, title, body)
            )
            return converter

        def _rewrite_packaged_project_raster_source():
            """Ensure packaged project references the local exported raster file."""
            actual_raster = getattr(self, "final_raster_path", None) or getattr(self, "temp_raster_path", None)
            if actual_raster:
                raster_filename = os.path.basename(actual_raster)
            else:
                found_rasters = list(subfolder_path.glob(f"{code_digits}_img.*"))
                if found_rasters:
                    raster_filename = found_rasters[0].name
                else:
                    raster_filename = f"{code_digits}_img.mbtiles" if (hasattr(self, '_raster_convert_mbtiles') and self._raster_convert_mbtiles.isChecked()) else f"{code_digits}_img.tif"
            raster_layer_name = f"{code_digits}_img"
            target_ds = raster_filename

            def _rewrite_qgs_text(text):
                # Prefer XML-aware rewrite to avoid brittle text substitutions.
                try:
                    root = ET.fromstring(text)
                    changed = False

                    for ml in root.findall('.//maplayer'):
                        name_el = ml.find('layername')
                        ds_el = ml.find('datasource')
                        layer_name = (name_el.text or '').lower() if name_el is not None else ''
                        ds_text = (ds_el.text or '') if ds_el is not None else ''

                        should_rewrite = raster_filename.lower() in ds_text.lower() or layer_name.endswith('_img')
                        if should_rewrite and ds_el is not None:
                            ds_el.text = target_ds
                            changed = True

                        src_attr = ml.attrib.get('source', '')
                        if src_attr and should_rewrite:
                            ml.attrib['source'] = target_ds
                            changed = True

                    for lt in root.findall('.//layer-tree-layer'):
                        src_attr = lt.attrib.get('source', '')
                        name_attr = (lt.attrib.get('name', '') or '').lower()
                        if raster_filename.lower() in src_attr.lower() or name_attr.endswith('_img'):
                            lt.attrib['source'] = target_ds
                            changed = True

                    if changed:
                        return ET.tostring(root, encoding='unicode')
                except Exception:
                    pass

                # Fallback regex rewrite.
                out = re.sub(
                    rf"(<datasource>)[^<]*{re.escape(raster_filename)}(</datasource>)",
                    rf"\\1{target_ds}\\2",
                    text,
                    flags=re.IGNORECASE,
                )
                out = re.sub(
                    rf"(source=\")[^\"]*{re.escape(raster_filename)}(\")",
                    rf"\\1{target_ds}\\2",
                    out,
                    flags=re.IGNORECASE,
                )

                # Fallback by layer block name (handles unusual XML formatting).
                out = re.sub(
                    rf"(<maplayer[^>]*>.*?<layername>\s*{re.escape(raster_layer_name)}(?:\.tif)?\s*</layername>.*?<datasource>)[^<]*(</datasource>)",
                    rf"\\1{target_ds}\\2",
                    out,
                    flags=re.IGNORECASE | re.DOTALL,
                )

                out = re.sub(
                    rf"(<layer-tree-layer[^>]*\bname=\"{re.escape(raster_layer_name)}(?:\.tif)?\"[^>]*\bsource=\")[^\"]*(\")",
                    rf"\\1{target_ds}\\2",
                    out,
                    flags=re.IGNORECASE | re.DOTALL,
                )

                return out

            project_path = str(packaged_project_file)
            if not os.path.exists(project_path):
                return

            if project_path.lower().endswith('.qgz'):
                tmp_qgz = project_path + '.tmp'
                with zipfile.ZipFile(project_path, 'r') as zin:
                    names = zin.namelist()
                    qgs_name = next((n for n in names if n.lower().endswith('.qgs')), None)
                    if not qgs_name:
                        return
                    qgs_text = zin.read(qgs_name).decode('utf-8', errors='ignore')
                    rewritten = _rewrite_qgs_text(qgs_text)

                    with zipfile.ZipFile(tmp_qgz, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
                        for name in names:
                            if name == qgs_name:
                                zout.writestr(name, rewritten.encode('utf-8'))
                            else:
                                zout.writestr(name, zin.read(name))

                os.replace(tmp_qgz, project_path)
            else:
                with open(project_path, 'r', encoding='utf-8', errors='ignore') as f:
                    qgs_text = f.read()
                rewritten = _rewrite_qgs_text(qgs_text)
                with open(project_path, 'w', encoding='utf-8') as f:
                    f.write(rewritten)

        def _validate_packaged_project_sources():
            """Validate local file references in packaged qgs/qgz and report missing ones."""
            project_path = str(packaged_project_file)
            if not os.path.exists(project_path):
                return

            qgs_text = ""
            if project_path.lower().endswith('.qgz'):
                with zipfile.ZipFile(project_path, 'r') as zin:
                    names = zin.namelist()
                    qgs_name = next((n for n in names if n.lower().endswith('.qgs')), None)
                    if not qgs_name:
                        return
                    qgs_text = zin.read(qgs_name).decode('utf-8', errors='ignore')
            else:
                with open(project_path, 'r', encoding='utf-8', errors='ignore') as f:
                    qgs_text = f.read()

            refs = []
            refs.extend(re.findall(r"<datasource>([^<]+)</datasource>", qgs_text, flags=re.IGNORECASE))
            refs.extend(re.findall(r"\ssource=\"([^\"]+)\"", qgs_text, flags=re.IGNORECASE))

            def resolve_local_path(ref):
                if not ref:
                    return None
                value = ref.strip()
                if not value:
                    return None

                # Keep only path part when provider params are appended.
                value = value.split('|', 1)[0]

                low = value.lower()
                # Skip non-file/provider URIs.
                if low.startswith((
                    'dbname=', 'host=', 'http://', 'https://', 'wms:', 'wmts:',
                    'xyz:', 'postgres', 'point(', 'linestring(', 'polygon('
                )):
                    return None

                if low.startswith('file://'):
                    value = QUrl(value).toLocalFile() or value

                # Normalize relative refs against export subfolder.
                if not os.path.isabs(value):
                    value = os.path.join(str(subfolder_path), value.lstrip('./\\'))

                return os.path.abspath(value)

            missing = []
            seen = set()
            for ref in refs:
                candidate = resolve_local_path(ref)
                if not candidate:
                    continue
                if candidate in seen:
                    continue
                seen.add(candidate)
                if not os.path.exists(candidate):
                    missing.append(candidate)

            if missing:
                preview = "\n".join(missing[:5])
                if len(missing) > 5:
                    preview += f"\n... and {len(missing) - 5} more"
                self.iface.messageBar().pushWarning(
                    "Export Validation",
                    f"Packaged project has missing referenced files:\n{preview}",
                )
            else:
                QgsApplication.instance().messageLog().logMessage(
                    f"Packaged project validation passed: {project_path}",
                    "GMD Pipeline",
                    Qgis.Info,
                )

        def _convert_with_same_file_guard():
            self._apply_role_policies_to_project_layers()
            orig_actions = self._disable_unused_qfield_actions()
            try:
                self._offline_convertor.convert()
            except shutil.SameFileError as e:
                src = getattr(e, "filename", None)
                dst = getattr(e, "filename2", None)

                # If converter reports SameFileError for different paths,
                # force overwrite by replacing destination.
                if src and dst:
                    src_abs = os.path.normcase(os.path.abspath(src))
                    dst_abs = os.path.normcase(os.path.abspath(dst))
                    if src_abs != dst_abs:
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        if os.path.exists(dst):
                            os.remove(dst)
                        shutil.copy2(src, dst)
                        return

                # True same-path copy (src == dst): nothing to overwrite.
                # Keep export silent and continue.
                QgsApplication.instance().messageLog().logMessage(
                    f"Ignoring same-path copy during export: {e}",
                    "GMD Pipeline",
                    Qgis.Info,
                )
            finally:
                self._restore_qfield_actions(orig_actions)

        self._offline_convertor = _build_converter(self.offliner)

        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            # Make the satellite raster visible in the layer panel right before
            # OfflineConverter snapshots the project state into the QGZ.
            _root = QgsProject.instance().layerTreeRoot()
            for _rl in list(QgsProject.instance().mapLayers().values()):
                if isinstance(_rl, QgsRasterLayer) and self._normalized_layer_name(_rl.name()).lower().endswith("_img"):
                    _rn = _root.findLayer(_rl.id())
                    if _rn:
                        _rn.setItemVisibilityChecked(True)
            try:
                _convert_with_same_file_guard()
            except IndexError as e:
                # Workaround for a libqfieldsync bug where offline layer progress
                # can desync and trigger `offline_layer_names` index errors.
                QgsApplication.instance().messageLog().logMessage(
                    f"Offline export retry (offline editing disabled) after IndexError: {e}",
                    "GMD Pipeline",
                    Qgis.Warning,
                )
                self.iface.messageBar().pushWarning(
                    "Export Warning",
                    "Offline editing failed for a layer. Retrying export with offline editing disabled.",
                )
                fallback_offliner = QgisCoreOffliner(offline_editing=False)
                fallback_offliner.warning.connect(self.show_warning)
                self._offline_convertor = _build_converter(fallback_offliner)
                _convert_with_same_file_guard()
            
            # Robust raster export: always remove old raster layers with the same path, always add raster from export folder
            if hasattr(self, 'temp_raster_path') and hasattr(self, 'final_raster_path'):
                if os.path.exists(self.temp_raster_path):
                    try:
                        os.makedirs(os.path.dirname(self.final_raster_path), exist_ok=True)
                        if os.path.exists(self.final_raster_path):
                            try:
                                os.remove(self.final_raster_path)
                            except Exception:
                                pass
                        shutil.copy2(self.temp_raster_path, self.final_raster_path)
                        try:
                            os.remove(self.temp_raster_path)
                        except Exception:
                            pass
                        print(f"Copied raster from temp to subfolder: {self.final_raster_path}")
                        # Remove any previous raster layers with the same path
                        for lyr in QgsProject.instance().mapLayers().values():
                            if isinstance(lyr, QgsRasterLayer) and lyr.source() == self.final_raster_path:
                                QgsProject.instance().removeMapLayer(lyr.id())
                        # Add the raster to the project and update reference
                        clipped_raster_layer = QgsRasterLayer(self.final_raster_path, f"{code_digits}_img")
                        if clipped_raster_layer.isValid():
                            QgsProject.instance().addMapLayer(clipped_raster_layer, False)
                            QgsProject.instance().layerTreeRoot().addLayer(clipped_raster_layer)
                            self.clipped_raster_layer = clipped_raster_layer
                            print(f"Raster layer added to project: {self.final_raster_path}")
                        else:
                            print(f"Warning: Could not load raster layer: {self.final_raster_path}")
                    except Exception as e:
                        print(f"Warning: Could not move raster to subfolder: {str(e)}")

            # Ensure exported project points to the raster inside the export
            # folder, not to a temporary path.
            try:
                _rewrite_packaged_project_raster_source()
            except Exception as e:
                QgsApplication.instance().messageLog().logMessage(
                    f"Could not rewrite packaged raster datasource: {e}",
                    "GMD Pipeline",
                    Qgis.Warning,
                )

            # Rename any *_ea_update.gpkg in the export folder to use an
            # 8-digit prefix and patch the QGZ to match.
            try:
                ea_prefix = re.sub(r"\D", "", (selected_geocode.split('_', 1)[0] if selected_geocode else ""))[:8]
                if len(ea_prefix) < 8:
                    folder_prefix = re.sub(r"\D", "", subfolder_path.name.split('_', 1)[0])[:8]
                    if len(folder_prefix) == 8:
                        ea_prefix = folder_prefix
                if len(ea_prefix) < 8:
                    for _img in subfolder_path.glob('*_img.tif'):
                        img_prefix = re.sub(r"\D", "", _img.stem.replace('_img', ''))[:8]
                        if len(img_prefix) == 8:
                            ea_prefix = img_prefix
                            break
                if len(ea_prefix) < 8:
                    fallback = re.sub(r"\D", "", str(code_digits))[:8]
                    ea_prefix = fallback.ljust(8, '0')

                ea_new_name = f"{ea_prefix}_ea_update.gpkg"
                _proj_path = str(packaged_project_file)
                _ea_found = list(Path(subfolder_path).rglob('*_ea_update.gpkg'))
                for _ea_old_path in _ea_found:
                    _ea_old_name = _ea_old_path.name
                    if _ea_old_name == ea_new_name:
                        continue
                    _ea_new_path = _ea_old_path.parent / ea_new_name
                    try:
                        if _ea_new_path.exists():
                            _ea_new_path.unlink()
                        _ea_old_path.rename(_ea_new_path)
                    except Exception as e:
                        QgsApplication.instance().messageLog().logMessage(
                            f"Could not rename ea_update file '{_ea_old_name}': {e}",
                            "GMD Pipeline", Qgis.Warning)
                        continue
                    if os.path.exists(_proj_path):
                        if _proj_path.lower().endswith('.qgz'):
                            _tmp = _proj_path + '.tmp_ea'
                            try:
                                with zipfile.ZipFile(_proj_path, 'r') as _zin:
                                    _names = _zin.namelist()
                                    _qgs = next((n for n in _names if n.lower().endswith('.qgs')), None)
                                    if _qgs:
                                        _txt = _zin.read(_qgs).decode('utf-8', errors='ignore').replace(_ea_old_name, ea_new_name)
                                        with zipfile.ZipFile(_tmp, 'w', compression=zipfile.ZIP_DEFLATED) as _zout:
                                            for _n in _names:
                                                _zout.writestr(_n, _txt.encode('utf-8') if _n == _qgs else _zin.read(_n))
                                os.replace(_tmp, _proj_path)
                            except Exception as e:
                                QgsApplication.instance().messageLog().logMessage(
                                    f"Could not patch qgz for ea_update rename: {e}", "GMD Pipeline", Qgis.Warning)
                                if os.path.exists(_tmp):
                                    os.remove(_tmp)
                        else:
                            try:
                                with open(_proj_path, 'r', encoding='utf-8', errors='ignore') as _f:
                                    _txt = _f.read().replace(_ea_old_name, ea_new_name)
                                with open(_proj_path, 'w', encoding='utf-8') as _f:
                                    _f.write(_txt)
                            except Exception as e:
                                QgsApplication.instance().messageLog().logMessage(
                                    f"Could not patch qgs for ea_update rename: {e}", "GMD Pipeline", Qgis.Warning)
            except Exception as e:
                QgsApplication.instance().messageLog().logMessage(
                    f"ea_update rename block failed: {e}", "GMD Pipeline", Qgis.Warning)

            # Final check before reporting success: warn immediately if the
            # packaged project still references missing local files.
            try:
                _validate_packaged_project_sources()
            except Exception as e:
                QgsApplication.instance().messageLog().logMessage(
                    f"Could not validate packaged project sources: {e}",
                    "GMD Pipeline",
                    Qgis.Warning,
                )
            try:
                # Ensure unassigned layers are filtered right before export
                is_ea_mode = self.output_dropdown.currentText() == self.tr("EA Level")
                for _unassigned_lyr in self._get_unassigned_map_layers():
                    self._filter_unassigned_layer(_unassigned_lyr, code_digits, is_ea_level=is_ea_mode)
                self._export_individual_layers(code_digits, subfolder_path, packaged_project_file)
            except Exception as e:
                QgsApplication.instance().messageLog().logMessage(
                    f"Could not export individual layers for {code_digits}: {e}",
                    "GMD Pipeline",
                    Qgis.Warning,
                )

            self.do_post_offline_convert_action(True)
        except PackagingCanceledError:
            # packaging was canceled by user, we do nothing.
            return
        except Exception as e:
            QgsApplication.instance().messageLog().logMessage(
                "Packaging failed with exception:\n{}\n{}".format(e, traceback.format_exc()),
                "GMD Pipeline",
                Qgis.Critical,
            )
            self.iface.messageBar().pushWarning("Export Error", str(e))
            self.do_post_offline_convert_action(False)
        finally:
            QApplication.restoreOverrideCursor()
            self._offline_convertor = None
            try:
                self.reset_filter()
            except Exception:
                pass

        # Keep dialog open after export so user can continue working.
        # Batch mode still closes via _show_batch_completion_and_close().

        self.progress_group.setEnabled(True)
        # Recompute button states after export; these can remain disabled
        # depending on prior UI transitions.
        self.validate_group_selection()
        # Keep single-run workflow responsive right after export.
        if not self.is_batch_mode:
            self.next_geocode.setEnabled(True)
            self.run_batch.setEnabled(True)
        

    # ------------------------------------------------------------------
    # EA Level helpers
    # ------------------------------------------------------------------
    def _run_alg_async(self, alg_id, params, message):
        """Run a processing algorithm asynchronously using a local event loop.
        This keeps the UI responsive while avoiding QThread crashes.
        """
        from qgis.core import QgsProcessingAlgRunnerTask, QgsApplication, QgsProcessingContext, QgsProject
        from qgis.PyQt.QtCore import QEventLoop, QTimer
        
        context = QgsProcessingContext()
        context.setProject(QgsProject.instance())
        alg = QgsApplication.processingRegistry().algorithmById(alg_id)
        task = QgsProcessingAlgRunnerTask(alg, params, context)
        loop = QEventLoop()
        result_dict = {}
        success_flag = False
        
        def on_executed(success, results):
            nonlocal success_flag, result_dict
            success_flag = success
            result_dict = results
            loop.quit()
            
        task.executed.connect(on_executed)
        QgsApplication.taskManager().addTask(task)
        
        # Poll for cancel request while task is running
        cancel_timer = QTimer()
        cancel_timer.setInterval(200)
        def check_cancel():
            if self.batch_cancel_requested:
                task.cancel()
                loop.quit()
        cancel_timer.timeout.connect(check_cancel)
        cancel_timer.start()
        
        loop.exec_()
        cancel_timer.stop()
        
        return success_flag, result_dict

    def _run_subprocess_async(self, cmd_args):
        """Run a subprocess asynchronously using QProcess and a local event loop."""
        from qgis.PyQt.QtCore import QProcess, QEventLoop, QTimer
        
        process = QProcess()
        loop = QEventLoop()
        
        def on_finished():
            loop.quit()
            
        process.finished.connect(on_finished)
        process.start(cmd_args[0], cmd_args[1:])
        
        # Poll for cancel request while task is running
        cancel_timer = QTimer()
        cancel_timer.setInterval(200)
        def check_cancel():
            if self.batch_cancel_requested:
                process.kill()
                loop.quit()
        cancel_timer.timeout.connect(check_cancel)
        cancel_timer.start()
        
        loop.exec_()
        cancel_timer.stop()
        
        if self.batch_cancel_requested:
            raise RuntimeError("Subprocess cancelled")
        
        if process.exitStatus() == QProcess.CrashExit:
            raise RuntimeError("Process crashed")
            
        if process.exitCode() != 0:
            err = bytes(process.readAllStandardError()).decode('utf-8')
            raise RuntimeError(f"Process failed with code {process.exitCode()}: {err}")

    def _clip_raster_sync(self, raster_file, selected_layer, code_digits, parent_export_path, convert_to_mbtiles=True, output_suffix="_img"):
        """Clip *raster_file* to *selected_layer* on the main thread.

        Returns (success: bool, message: str).  ``message`` is the output
        raster path on success, or an error string on failure.
        Source raster is a GeoPackage (*_img.gpkg); output is a GeoTIFF.
        When *convert_to_mbtiles* is True the TIF is further converted to
        MBTiles via gdal_translate; otherwise the TIF is kept as-is.
        QGIS processing calls use QgsProcessingAlgRunnerTask with a local
        event loop to keep the UI perfectly responsive without crashing.
        """
        try:
            self.update_total(0, 100, f"Clipping raster for {code_digits}...")
            self.update_task(0, 100)
            QApplication.processEvents()

            if not raster_file or not os.path.exists(raster_file):
                return False, "Invalid raster file."

            if not isinstance(selected_layer, QgsVectorLayer):
                return False, "Invalid vector layer."

            # Guard check: Ensure boundary vector layer has features before buffering
            if selected_layer.featureCount() == 0:
                print(f"[RASTER CLIP WARNING] Layer '{selected_layer.name()}' has 0 features for area code '{code_digits}'. Skipping raster clip.")
                return False, f"No boundary features found for area {code_digits}."

            self.update_total(30, 100, "Creating buffer mask...")
            self.update_task(30, 100)
            QApplication.processEvents()

            buffer_distance = 0.001000
            buffer_output = os.path.join(tempfile.gettempdir(), f"{code_digits}_buffered_mask.gpkg")
            
            # Use QgsProcessingAlgRunnerTask for responsive UI
            success, buffer_result = self._run_alg_async("native:buffer", {
                "INPUT": selected_layer,
                "DISTANCE": buffer_distance,
                "SEGMENTS": 5,
                "DISSOLVE": True,
                "OUTPUT": buffer_output,
            }, "Creating buffer mask...")
            
            if not success or not os.path.exists(buffer_output):
                return False, "Buffer creation failed."

            # Guard check: Verify buffered mask layer contains valid cutline features before GDAL warp
            mask_check = QgsVectorLayer(buffer_output, "mask_check")
            if not mask_check.isValid() or mask_check.featureCount() == 0:
                print(f"[RASTER CLIP WARNING] Buffered mask layer for '{code_digits}' contains 0 cutline features. Skipping GDAL clip.")
                return False, f"Mask layer contains 0 cutline features for area {code_digits}."

            self.update_total(60, 100, "Clipping raster...")
            self.update_task(60, 100)
            QApplication.processEvents()

            os.makedirs(parent_export_path, exist_ok=True)
            output_raster = os.path.join(parent_export_path, f"{code_digits}{output_suffix}.tif")

            success, clip_result = self._run_alg_async("gdal:cliprasterbymasklayer", {
                "INPUT": raster_file,
                "MASK": buffer_output,
                "SOURCE_CRS": None,
                "TARGET_CRS": None,
                "NODATA": None,
                "ALPHA_BAND": False,
                "CROP_TO_CUTLINE": True,
                "KEEP_RESOLUTION": True,
                "SET_RESOLUTION": False,
                "X_RESOLUTION": None,
                "Y_RESOLUTION": None,
                "MULTITHREADING": False,
                "OPTIONS": "",
                "DATA_TYPE": 0,
                "EXTRA": "",
                "OUTPUT": output_raster,
            }, "Clipping raster by mask layer...")
            
            if not success or not os.path.exists(output_raster):
                return False, "Clipped output file was not created."

            self.update_total(90, 100, "Building pyramids...")
            self.update_task(90, 100)
            QApplication.processEvents()

            self._run_alg_async("gdal:overviews", {
                "INPUT": output_raster,
                "FORMAT": 0,
                "LEVELS": "8 16 32 64 128",
                "RESAMPLING": None,
            }, "Building pyramids...")

            # Convert .tif → .mbtiles using QGIS-bundled gdal_translate
            if convert_to_mbtiles:
                self.update_total(95, 100, "Converting to MBTiles...")
                self.update_task(95, 100)
                QApplication.processEvents()

                mbtiles_output = output_raster[:-4] + ".mbtiles"
                try:
                    gdal_translate_exe = os.path.join(
                        QgsApplication.prefixPath(), "bin", "gdal_translate.exe"
                    )
                    if not os.path.exists(gdal_translate_exe):
                        gdal_translate_exe = "gdal_translate"
                    self._run_subprocess_async([
                        gdal_translate_exe,
                        "-of", "MBTiles",
                        "-co", "TILE_FORMAT=JPEG",
                        output_raster,
                        mbtiles_output,
                    ])
                    try:
                        os.remove(output_raster)
                    except Exception:
                        pass
                    output_raster = mbtiles_output
                except Exception as _conv_err:
                    # Clean up intermediate .tif before surfacing the error
                    try:
                        os.remove(output_raster)
                    except Exception:
                        pass
                    return False, f"MBTiles conversion failed: {_conv_err}"

            self.update_total(100, 100, f"Raster ready for {code_digits}")
            self.update_task(100, 100)
            QApplication.processEvents()

            return True, output_raster

        except Exception as e:
            return False, str(e)

    # ------------------------------------------------------------------

    def _build_raster_config_panel(self):
        """Create the raster configuration panel with satellite image and additional mbtiles selectors."""
        panel = QGroupBox(self.tr("Raster Configuration"))
        grid = QGridLayout(panel)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setVerticalSpacing(4)



        # --- Row 1: Satellite Image Format dropdown ---
        format_label = QLabel(self.tr("Satellite Image Source Format"))
        grid.addWidget(format_label, 1, 0)

        self._raster_type_combo = QComboBox()
        self._raster_type_combo.addItems([
            self.tr("GeoPackage (*_img.gpkg)"),
            self.tr("MBTiles (*_img.mbtiles)"),
            self.tr("Both GPKG and MBTiles")
        ])
        settings = QSettings()
        saved_format = settings.value("raster_satellite_format", 0, type=int)
        self._raster_type_combo.setCurrentIndex(saved_format)
        grid.addWidget(self._raster_type_combo, 1, 1)

        # --- Row 2: Satellite Image directory ---
        self._raster_satellite_dir_label = QLabel(self.tr("Satellite Image Directory"))
        self._raster_satellite_dir_label.setToolTip(self.tr("Directory containing satellite image files"))
        grid.addWidget(self._raster_satellite_dir_label, 2, 0)

        self._raster_satellite_dir = QgsFileWidget()
        self._raster_satellite_dir.setStorageMode(QgsFileWidget.StorageMode.GetDirectory)
        self._raster_satellite_dir.setDialogTitle(self.tr("Select Satellite Image Directory"))
        self._raster_satellite_dir.setFilter("")
        saved_sat_dir = settings.value("satellite_dir_path", "", type=str)
        if saved_sat_dir:
            self._raster_satellite_dir.setFilePath(saved_sat_dir)
        self._raster_satellite_dir.fileChanged.connect(
            lambda path: QSettings().setValue("satellite_dir_path", path)
        )
        grid.addWidget(self._raster_satellite_dir, 2, 1)



        # --- Row 3: Convert to MBTiles checkbox ---
        self._raster_convert_mbtiles = QCheckBox(self.tr("Convert satellite to MBTiles"))
        saved_convert = settings.value("raster_convert_mbtiles", True, type=bool)
        self._raster_convert_mbtiles.setChecked(saved_convert)
        self._raster_convert_mbtiles.setToolTip(self.tr(
            "Convert the clipped satellite .tif to .mbtiles format. Uncheck to keep as .tif."
        ))
        self._raster_convert_mbtiles.stateChanged.connect(
            lambda state: QSettings().setValue("raster_convert_mbtiles", state == Qt.Checked)
        )
        grid.addWidget(self._raster_convert_mbtiles, 3, 0, 1, 2)

        # --- Row 4: Additional raster (.mbtiles) directory ---
        self._raster_additional_dir_label = QLabel(self.tr("Additional Raster Directory (.mbtiles)"))
        self._raster_additional_dir_label.setToolTip(self.tr("Directory containing {pppmm}.mbtiles files"))
        self._raster_additional_dir_label.setStyleSheet("color: gray;")
        grid.addWidget(self._raster_additional_dir_label, 4, 0)

        self._raster_additional_dir = QgsFileWidget()
        self._raster_additional_dir.setStorageMode(QgsFileWidget.StorageMode.GetDirectory)
        self._raster_additional_dir.setDialogTitle(self.tr("Select Additional Raster Directory"))
        self._raster_additional_dir.setFilter("")
        saved_add_dir = settings.value("additional_raster_dir_path", "", type=str)
        if saved_add_dir:
            self._raster_additional_dir.setFilePath(saved_add_dir)
        self._raster_additional_dir.fileChanged.connect(
            lambda path: QSettings().setValue("additional_raster_dir_path", path)
        )
        grid.addWidget(self._raster_additional_dir, 4, 1)



        # Connect format dropdown index change to handle dynamic showing/hiding
        self._raster_type_combo.currentIndexChanged.connect(self._on_satellite_format_changed)
        self._raster_type_combo.currentIndexChanged.connect(
            lambda index: QSettings().setValue("raster_satellite_format", index)
        )
        # Initialize dynamic flow state
        self._on_satellite_format_changed(saved_format)

        return panel

    def _on_satellite_format_changed(self, index):
        """Show/hide options based on the chosen format selection."""
        # Check if elements are fully initialized before trying to modify visibility
        has_sat = hasattr(self, '_raster_satellite_dir') and hasattr(self, '_raster_satellite_dir_label')
        has_convert = hasattr(self, '_raster_convert_mbtiles')
        has_add = hasattr(self, '_raster_additional_dir') and hasattr(self, '_raster_additional_dir_label')

        if index == 0:  # GeoPackage
            # Show Satellite Image Directory
            if has_sat:
                self._raster_satellite_dir_label.setVisible(True)
                self._raster_satellite_dir.setVisible(True)
            # Show and enable Convert to MBTiles option
            if has_convert:
                self._raster_convert_mbtiles.setVisible(True)
                self._raster_convert_mbtiles.setEnabled(True)
                saved_convert = QSettings().value("raster_convert_mbtiles", True, type=bool)
                self._raster_convert_mbtiles.setChecked(saved_convert)
                self._raster_convert_mbtiles.setToolTip(self.tr(
                    "Convert the clipped satellite .tif to .mbtiles format. Uncheck to keep as .tif."
                ))
            # Hide Additional Raster Directory
            if has_add:
                self._raster_additional_dir_label.setVisible(False)
                self._raster_additional_dir.setVisible(False)

        elif index == 1:  # MBTiles
            # Show Satellite Image Directory
            if has_sat:
                self._raster_satellite_dir_label.setVisible(True)
                self._raster_satellite_dir.setVisible(True)
            # Hide Convert to MBTiles option (output is automatically MBTiles)
            if has_convert:
                self._raster_convert_mbtiles.setChecked(True)
                self._raster_convert_mbtiles.setVisible(False)
            # Hide Additional Raster Directory
            if has_add:
                self._raster_additional_dir_label.setVisible(False)
                self._raster_additional_dir.setVisible(False)

        elif index == 2:  # Both GPKG and MBTiles
            # Show Satellite Image Directory
            if has_sat:
                self._raster_satellite_dir_label.setVisible(True)
                self._raster_satellite_dir.setVisible(True)
            # Show and enable Convert to MBTiles option
            if has_convert:
                self._raster_convert_mbtiles.setVisible(True)
                self._raster_convert_mbtiles.setEnabled(True)
                saved_convert = QSettings().value("raster_convert_mbtiles", True, type=bool)
                self._raster_convert_mbtiles.setChecked(saved_convert)
                self._raster_convert_mbtiles.setToolTip(self.tr(
                    "Convert the clipped satellite .tif to .mbtiles format. Uncheck to keep as .tif."
                ))
            # Show Additional Raster Directory
            if has_add:
                self._raster_additional_dir_label.setVisible(True)
                self._raster_additional_dir.setVisible(True)

    def _get_ea_assigned_layer(self, attr):
        return self._get_assigned_layer_from_tree(attr)

    def _get_bgy_assigned_layer(self, attr):
        return self._get_assigned_layer_from_tree(attr)

    def _get_assigned_layer_from_tree(self, attr):
        from qgis.core import QgsProject, QgsVectorLayer

        # 1. Search tree widget for explicit role assignment in Column 1
        if hasattr(self, 'layer_groups_tree'):
            normalized_attr = attr.replace("_bgy_combo_", "_ea_combo_")
            
            def search_item(parent_item):
                for i in range(parent_item.childCount()):
                    item = parent_item.child(i)
                    combo = self.layer_groups_tree.itemWidget(item, 1)
                    if combo and combo.currentData() is not None:
                        combo_data = str(combo.currentData()).replace("_bgy_combo_", "_ea_combo_")
                        if combo_data == normalized_attr:
                            layer_id = item.data(0, Qt.UserRole)
                            if layer_id:
                                lyr = QgsProject.instance().mapLayer(layer_id)
                                if lyr and lyr.isValid():
                                    return lyr
                            layer_name = item.text(0)
                            layers = QgsProject.instance().mapLayersByName(layer_name)
                            if layers:
                                return layers[0]
                    res = search_item(item)
                    if res:
                        return res
                return None

            found_lyr = search_item(self.layer_groups_tree.invisibleRootItem())
            if found_lyr:
                return found_lyr

        # 2. Fallback to suffix matching logic
        suffix_map = {
            "_ea_combo_ea": ("_ea",),
            "_ea_combo_bgy": ("_bgy",),
            "_ea_combo_bldg": ("_bldg_point", "_bldgpts", "_bldg_points"),
            "_ea_combo_landmark": ("_landmark",),
            "_ea_combo_block": ("_block",),
            "_ea_combo_road": ("_road",),
            "_ea_combo_river": ("_river",),
            "_ea_combo_bridge": ("_bridge",),
            "_ea_combo_railroad": ("_railroad",),
            "_bgy_combo_bgy": ("_bgy",),
            "_bgy_combo_ea": ("_ea",),
            "_bgy_combo_bldg": ("_bldg_point", "_bldgpts", "_bldg_points"),
            "_bgy_combo_landmark": ("_landmark",),
            "_bgy_combo_block": ("_block",),
            "_bgy_combo_road": ("_road",),
            "_bgy_combo_river": ("_river",),
            "_bgy_combo_bridge": ("_bridge",),
            "_bgy_combo_railroad": ("_railroad",),
        }
        
        suffixes = suffix_map.get(attr, ())
        if not suffixes: return None
        
        all_vector_layers = sorted([
            lyr for lyr in QgsProject.instance().mapLayers().values()
            if isinstance(lyr, QgsVectorLayer) and lyr.isValid()
        ], key=lambda l: l.name())
        
        for lyr in all_vector_layers:
            lname = lyr.name().lower()
            if lname.endswith("_special_ea"):
                continue
            if any(lname.endswith(s) for s in suffixes) or any(lname.endswith(s + " (offline)") for s in suffixes):
                return lyr
                
        return None

    def _get_checked_ea_geocodes(self):
        checked = []
        for i in range(self._filter_tree_widget.topLevelItemCount()):
            city = self._filter_tree_widget.topLevelItem(i)
            for j in range(city.childCount()):
                bgy = city.child(j)
                for k in range(bgy.childCount()):
                    ea = bgy.child(k)
                    if ea.checkState(0) == Qt.Checked:
                        checked.append(ea.text(0).split('_')[0])
        return checked

    def _populate_filter_tree(self):
        """Fill the Tree filter with City/Municipalities as parents and Barangays/EAs as children."""
        if not hasattr(self, '_filter_tree_widget'):
            return
            
        output_level = self.output_dropdown.currentText()
        if output_level not in [self.tr("Barangay Level"), self.tr("EA Level")]:
            return
            
        self._filter_tree_widget.blockSignals(True)
        self._filter_tree_widget.clear()
        
        selected_layer = None
        selected_data = self.layer_dropdown.currentData()
        if isinstance(selected_data, str):
            selected_layer = QgsProject.instance().mapLayer(selected_data)
            
        if selected_layer is None and self.layer_dropdown.currentText():
            sel_name = self.layer_dropdown.currentText()
            for lyr in QgsProject.instance().mapLayers().values():
                try:
                    if lyr.name() == sel_name:
                        selected_layer = lyr
                        break
                except Exception:
                    continue

        desired = '_ea' if output_level == self.tr('EA Level') else '_bgy'
        is_ea = output_level == self.tr('EA Level')
        if selected_layer and selected_layer.name().endswith(desired):
            geocode_index = -1
            for fname in (['ea_geocode', 'geocode', 'ea_code', 'code'] if is_ea else ['geocode', 'bgy_code', 'ea_geocode', 'code']):
                idx = selected_layer.fields().indexOf(fname)
                if idx != -1:
                    geocode_index = idx
                    break
            citymun_index = selected_layer.fields().indexOf('city_mun')
            if citymun_index == -1:
                citymun_index = selected_layer.fields().indexOf('City_mun')
            barangay_index = selected_layer.fields().indexOf('barangay')
            if barangay_index == -1:
                barangay_index = selected_layer.fields().indexOf('Barangay')

            if geocode_index != -1 and citymun_index != -1 and barangay_index != -1:
                # Build hierarchy
                hierarchy = {}
                request = QgsFeatureRequest()
                request.setFlags(QgsFeatureRequest.NoGeometry)
                request.setSubsetOfAttributes([geocode_index, citymun_index, barangay_index])
                for feature in selected_layer.getFeatures(request):
                    code = str(feature.attributes()[geocode_index])
                    city_name = str(feature.attributes()[citymun_index])
                    bgy_name = str(feature.attributes()[barangay_index])
                    if not code or not city_name or not bgy_name:
                        continue
                        
                    city_key = f"{code[:5]}_{city_name}"
                    bgy_key = f"{code[:8]}_{bgy_name}"
                    ea_key = code
                    
                    if city_key not in hierarchy:
                        hierarchy[city_key] = {}
                    if bgy_key not in hierarchy[city_key]:
                        hierarchy[city_key][bgy_key] = set()
                        
                    if output_level == self.tr('EA Level'):
                        hierarchy[city_key][bgy_key].add(ea_key)
                
                for city_key in sorted(hierarchy.keys()):
                    city_item = QTreeWidgetItem(self._filter_tree_widget)
                    city_item.setText(0, city_key)
                    city_item.setFlags(city_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                    city_item.setCheckState(0, Qt.Checked)
                    
                    for bgy_key in sorted(hierarchy[city_key].keys()):
                        bgy_item = QTreeWidgetItem(city_item)
                        bgy_item.setText(0, bgy_key)
                        bgy_item.setFlags(bgy_item.flags() | Qt.ItemIsUserCheckable | (Qt.ItemIsAutoTristate if output_level == self.tr('EA Level') else 0))
                        bgy_item.setCheckState(0, Qt.Checked)
                        
                        if output_level == self.tr('EA Level'):
                            for ea_key in sorted(hierarchy[city_key][bgy_key]):
                                ea_item = QTreeWidgetItem(bgy_item)
                                ea_item.setText(0, ea_key)
                                ea_item.setFlags(ea_item.flags() | Qt.ItemIsUserCheckable)
                                ea_item.setCheckState(0, Qt.Checked)

        self._filter_tree_widget.blockSignals(False)
        self._adjust_widget_height_to_content(self._filter_tree_widget)
        # Re-trigger update of checked items cache if needed
        # self._update_lists_from_filter_tree()


    def _on_filter_tree_item_changed(self, item, column):
        # We use Qt.ItemIsAutoTristate, so checking/unchecking parents automatically cascades to children.
        # We just need to trigger the final list population.
        self._update_lists_from_filter_tree()

    def _on_filter_tree_item_clicked(self, item, column):
        modifiers = QApplication.keyboardModifiers()
        
        if modifiers & Qt.ShiftModifier and getattr(self, '_last_clicked_tree_item', None):
            # Flatten tree
            all_items = []
            for i in range(self._filter_tree_widget.topLevelItemCount()):
                top = self._filter_tree_widget.topLevelItem(i)
                all_items.append(top)
                for j in range(top.childCount()):
                    all_items.append(top.child(j))
                    
            try:
                start_idx = all_items.index(self._last_clicked_tree_item)
                end_idx = all_items.index(item)
                
                if start_idx > end_idx:
                    start_idx, end_idx = end_idx, start_idx
                    
                target_state = item.checkState(0)
                
                self._filter_tree_widget.blockSignals(True)
                for i in range(start_idx, end_idx + 1):
                    all_items[i].setCheckState(0, target_state)
                self._filter_tree_widget.blockSignals(False)
                self._update_lists_from_filter_tree()
            except ValueError:
                pass
                
        self._last_clicked_tree_item = item

    def _filter_tree_select_all(self):
        self._filter_tree_widget.blockSignals(True)
        for i in range(self._filter_tree_widget.topLevelItemCount()):
            item = self._filter_tree_widget.topLevelItem(i)
            item.setCheckState(0, Qt.Checked)
        self._filter_tree_widget.blockSignals(False)
        self._update_lists_from_filter_tree()

    def _filter_tree_deselect_all(self):
        self._filter_tree_widget.blockSignals(True)
        for i in range(self._filter_tree_widget.topLevelItemCount()):
            item = self._filter_tree_widget.topLevelItem(i)
            item.setCheckState(0, Qt.Unchecked)
        self._filter_tree_widget.blockSignals(False)
        self._update_lists_from_filter_tree()

    def _get_checked_bgy_names(self):
        checked_bgy_prefixes = []
        for i in range(self._filter_tree_widget.topLevelItemCount()):
            parent_item = self._filter_tree_widget.topLevelItem(i)
            if parent_item.checkState(0) == Qt.Checked:
                # extract the 5-digit prefix
                checked_bgy_prefixes.append(parent_item.text(0).split('_')[0])
        return checked_bgy_prefixes

    def _get_checked_bgy_geocodes(self):
        geocodes = []
        for i in range(self._filter_tree_widget.topLevelItemCount()):
            parent = self._filter_tree_widget.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.checkState(0) == Qt.Checked:
                    geocodes.append(child.text(0).split('_')[0])
        return geocodes

    # ------------------------------------------------------------------
    # EA Level batch export
    # ------------------------------------------------------------------

    def run_ea_batch_export(self):
        """Iterate through every feature of the EA layer and package each one.

        Steps per EA geocode:
          1. Filter project layers to that EA (ea_geocode field).
          2. Clip the satellite raster to that EA's geometry.
          3. Package the filtered project as a QField .qgz into
             ``{ExportDir}/{ea_geocode}/``.
        """
        # Synchronize layer visibility check states and group structure (without re-applying QML styles)
        try:
            self._on_apply_layer_groups(apply_qml=False)
        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"Auto-sync layer visibility before EA batch export: {e}", "GMD Pipeline", Qgis.Warning)

        # --- Validate inputs ---
        selected_layer = None
        selected_data = self.layer_dropdown.currentData()
        if isinstance(selected_data, str):
            selected_layer = QgsProject.instance().mapLayer(selected_data)
        if selected_layer is None:
            QMessageBox.warning(self, "Selection Error", "Please select a valid EA layer.")
            return

        ea_geocode_index = selected_layer.fields().indexOf("ea_geocode")
        if ea_geocode_index == -1:
            QMessageBox.warning(
                self, "Field Error",
                "The selected EA layer must have an 'ea_geocode' field.",
            )
            return

        satellite_dir = self._raster_satellite_dir.filePath()
        if not satellite_dir or not os.path.isdir(satellite_dir):
            QMessageBox.warning(
                self, "Directory Error",
                "Please select a valid satellite image directory before exporting.",
            )
            return

        # Validate required layer assignments
        missing_required = []
        for attr, label, required in getattr(self, "_ea_layer_roles", []):
            if required and self._get_ea_assigned_layer(attr) is None:
                missing_required.append(label)
        if missing_required:
            QMessageBox.warning(
                self, "Missing Required Layers",
                "The following required layers are not assigned:\n\n"
                + "\n".join(f"  • {l}" for l in missing_required)
                + "\n\nPlease assign them in the Layer Assignment panel.",
            )
            return

        # Use the checked items from the EA list widget
        geocodes = self._get_checked_ea_geocodes()
        if not geocodes:
            QMessageBox.warning(self, "No Selection", "Please check at least one EA geocode to process.")
            return

        export_folder = Path(self.manualDir.text())

        # Lock the UI during the batch run
        self.is_batch_mode = True
        self.batch_cancel_requested = False
        self._set_batch_ui_locked(True)
        self.button_box.button(QDialogButtonBox.Save).setEnabled(False)

        # Disable the QGIS layer tree so the user cannot double-click / drag
        # layers while OfflineConverter is rebuilding them.  Interacting with
        # a layer whose C++ object is being recreated causes an access violation.
        try:
            self.iface.layerTreeView().setEnabled(False)
        except Exception:
            pass

        processed_count = 0
        errors = []
        total_geocodes = len(geocodes)

        # Initialise the total (batch) progress bar for EA count tracking.
        # OfflineConverter's per-layer progress will be redirected to
        # layerProgressBar via the _ea_batch_total flag in update_total().
        self._ea_batch_total = total_geocodes
        self.totalProgressBar.setMaximum(total_geocodes)
        self.totalProgressBar.setValue(0)

        try:
            for ea_index, ea_geocode in enumerate(geocodes):
                if self.batch_cancel_requested:
                    break
                try:
                    self.statusLabel.setText(
                        f"EA {ea_index + 1}/{total_geocodes}: {ea_geocode} — filtering layers..."
                    )
                    QApplication.processEvents()

                    # Re-fetch the EA layer by ID each iteration — OfflineConverter
                    # can delete and recreate layer C++ objects, so any reference
                    # obtained before the loop becomes a dangling pointer after the
                    # first export.
                    current_ea_layer = QgsProject.instance().mapLayer(selected_data)
                    if current_ea_layer is None or not current_ea_layer.isValid():
                        raise RuntimeError(
                            "EA layer is no longer available in the project. "
                            "Re-open the dialog and try again."
                        )

                    # 1. Filter all project layers to this EA
                    self._filter_ea_layers(current_ea_layer, ea_geocode)
                    QApplication.processEvents()

                    # 2. Resolve satellite image for this EA geocode
                    # Source: {satellite_dir}/{pppmm}_img.<ext> based on format selection
                    pppmm = ea_geocode[:5]
                    
                    format_idx = self._raster_type_combo.currentIndex() if hasattr(self, '_raster_type_combo') else 0
                    raster_file = None
                    if format_idx == 0:
                        raster_file = os.path.join(satellite_dir, f"{pppmm}_img.gpkg")
                    elif format_idx == 1:
                        raster_file = os.path.join(satellite_dir, f"{pppmm}_img.mbtiles")
                    else:
                        # Try GPKG first, then MBTiles
                        gpkg_path = os.path.join(satellite_dir, f"{pppmm}_img.gpkg")
                        mbtiles_path = os.path.join(satellite_dir, f"{pppmm}_img.mbtiles")
                        if os.path.exists(gpkg_path):
                            raster_file = gpkg_path
                        elif os.path.exists(mbtiles_path):
                            raster_file = mbtiles_path
                        else:
                            raster_file = gpkg_path  # Default for error reporting
                    
                    if not raster_file or not os.path.exists(raster_file):
                        ext_str = "_img.gpkg" if format_idx == 0 else ("_img.mbtiles" if format_idx == 1 else "_img.gpkg or _img.mbtiles")
                        QgsApplication.instance().messageLog().logMessage(
                            f"No satellite image found for {ea_geocode}: {raster_file}",
                            "GMD Pipeline", Qgis.Warning,
                        )
                        errors.append(f"{ea_geocode}: Missing satellite image ({pppmm}{ext_str}) — skipped")
                        continue

                    self.statusLabel.setText(
                        f"EA {ea_index + 1}/{total_geocodes}: {ea_geocode} — clipping satellite image..."
                    )
                    QApplication.processEvents()

                    # 3. Clip the satellite raster to this EA's geometry (main thread)
                    subfolder_path = str(export_folder / ea_geocode)
                    # temp/final paths will be resolved from the actual clip output
                    # (_clip_raster_sync returns .mbtiles on success or .tif as fallback)
                    self.temp_raster_path = None
                    self.final_raster_path = None

                    clip_ok, clip_msg = self._clip_raster_sync(
                        raster_file, current_ea_layer, ea_geocode, tempfile.gettempdir(),
                        convert_to_mbtiles=self._raster_convert_mbtiles.isChecked()
                    )
                    QApplication.processEvents()

                    if not clip_ok:
                        raise RuntimeError(f"Raster clipping failed: {clip_msg}")

                    # Derive correct extension from actual output (.mbtiles or .tif)
                    actual_ext = os.path.splitext(clip_msg)[1]  # e.g. ".mbtiles"
                    self.temp_raster_path = clip_msg
                    self.final_raster_path = os.path.join(
                        subfolder_path, f"{ea_geocode}_img{actual_ext}"
                    )

                    # 3b. Clip additional raster (.mbtiles) if configured
                    self._additional_raster_temp_path = None
                    self._additional_raster_final_path = None
                    add_dir = self._raster_additional_dir.filePath() if hasattr(self, '_raster_additional_dir') else ""
                    if add_dir and os.path.isdir(add_dir):
                        add_src = os.path.join(add_dir, f"{pppmm}.mbtiles")
                        if os.path.exists(add_src):
                            self.statusLabel.setText(
                                f"EA {ea_index + 1}/{total_geocodes}: {ea_geocode} — clipping additional raster..."
                            )
                            QApplication.processEvents()

                            add_clip_ok, add_clip_msg = self._clip_raster_sync(
                                add_src, current_ea_layer, ea_geocode, tempfile.gettempdir(),
                                convert_to_mbtiles=True, output_suffix="_img_new"
                            )
                            if add_clip_ok:
                                self._additional_raster_temp_path = add_clip_msg
                                self._additional_raster_final_path = os.path.join(
                                    subfolder_path, f"{ea_geocode}_img_new.mbtiles"
                                )
                            else:
                                QgsApplication.instance().messageLog().logMessage(
                                    f"Additional raster clip failed for {ea_geocode}: {add_clip_msg}",
                                    "GMD Pipeline", Qgis.Warning,
                                )

                    self.statusLabel.setText(
                        f"EA {ea_index + 1}/{total_geocodes}: {ea_geocode} — packaging..."
                    )
                    QApplication.processEvents()

                    # 4. Package the project for this EA
                    self._package_ea_single(ea_geocode, export_folder)
                    QApplication.processEvents()

                    processed_count += 1
                    self.totalProgressBar.setValue(processed_count)
                    self.statusLabel.setText(
                        f"EA {processed_count}/{total_geocodes} done — last: {ea_geocode}"
                    )
                    QApplication.processEvents()

                except Exception as e:
                    errors.append(f"{ea_geocode}: {e}")

            # Reset layer filters after all iterations
            try:
                self.reset_filter()
            except Exception:
                pass

        finally:
            was_cancelled = self.batch_cancel_requested
            self.is_batch_mode = False
            self.batch_cancel_requested = False
            self._ea_batch_total = 0  # Restore update_total to normal mode
            self._set_batch_ui_locked(False)
            try:
                self.iface.layerTreeView().setEnabled(True)
            except Exception:
                pass

        # Summary
        if was_cancelled:
            summary = (
                f"EA Export Cancelled\n\n"
                f"Processed: {processed_count} of {len(geocodes)}"
            )
        else:
            summary = (
                f"EA Export Complete\n\n"
                f"Total packaged: {processed_count} of {len(geocodes)}"
            )
        if errors:
            preview = "\n".join(errors[:5])
            if len(errors) > 5:
                preview += f"\n...and {len(errors) - 5} more"
            summary += f"\n\nErrors:\n{preview}"

        self.batch_summary = summary
        self._reload_project_after_ea_batch = True
        QTimer.singleShot(100, self._show_batch_completion_and_close)

    def _get_unassigned_map_layers(self):
        """Return a list of QgsMapLayer objects that are unassigned in layer_groups_tree."""
        if not hasattr(self, 'layer_groups_tree'):
            return []

        if self.layer_groups_tree.topLevelItemCount() == 0 and hasattr(self, '_update_layer_assignment_ui'):
            self._update_layer_assignment_ui()

        assigned_layer_ids = set()

        def collect_assigned(item):
            combo = self.layer_groups_tree.itemWidget(item, 1)
            if combo and combo.currentData():
                layer_id = item.data(0, Qt.UserRole)
                if layer_id:
                    assigned_layer_ids.add(layer_id)
            for i in range(item.childCount()):
                collect_assigned(item.child(i))

        for i in range(self.layer_groups_tree.topLevelItemCount()):
            collect_assigned(self.layer_groups_tree.topLevelItem(i))

        unassigned_layers = []
        for lyr in QgsProject.instance().mapLayers().values():
            if isinstance(lyr, QgsVectorLayer) and lyr.isValid() and lyr.id() not in assigned_layer_ids:
                unassigned_layers.append(lyr)

        return unassigned_layers

    def _cleanup_duplicate_code_filenames(self, subfolder_path, code_digits):
        """Rename files and zip entries in subfolder_path to strip duplicate/old code prefixes before suffix (extracting from 1st '_')."""
        if not subfolder_path or not os.path.exists(subfolder_path):
            return

        target_prefix = f"{code_digits}_"

        # 1. Clean up loose files on disk
        file_renames = {}
        for fname in os.listdir(subfolder_path):
            if not fname.startswith(target_prefix):
                continue
            rest = fname[len(target_prefix):]
            m = re.match(r"^(\d+)_(.+)$", rest)
            if m:
                new_fname = f"{code_digits}_{m.group(2)}"
                old_path = os.path.join(subfolder_path, fname)
                new_path = os.path.join(subfolder_path, new_fname)
                if old_path != new_path:
                    try:
                        if os.path.exists(new_path):
                            try:
                                os.remove(new_path)
                            except Exception:
                                pass
                        os.rename(old_path, new_path)
                        file_renames[fname] = new_fname
                        old_base = os.path.splitext(fname)[0]
                        new_base = os.path.splitext(new_fname)[0]
                        file_renames[old_base] = new_base
                    except Exception as e:
                        print(f"Could not rename file {fname} to {new_fname}: {e}")

        # 2. Inspect and clean up entries inside .qgz files
        qgz_files = [f for f in os.listdir(subfolder_path) if f.lower().endswith('.qgz')]
        for qgz_name in qgz_files:
            proj_path = os.path.join(subfolder_path, qgz_name)
            if not os.path.exists(proj_path):
                continue
            try:
                zip_renames = dict(file_renames)
                tmp_path = proj_path + '.tmp_clean'
                
                with zipfile.ZipFile(proj_path, 'r') as zin:
                    names = zin.namelist()
                    # Check for duplicate-coded zip entries inside the .qgz archive
                    for name in names:
                        if name.startswith(target_prefix):
                            rest = name[len(target_prefix):]
                            m = re.match(r"^(\d+)_(.+)$", rest)
                            if m:
                                new_name = f"{code_digits}_{m.group(2)}"
                                zip_renames[name] = new_name
                                old_base = os.path.splitext(name)[0]
                                new_base = os.path.splitext(new_name)[0]
                                zip_renames[old_base] = new_base

                    qgs_name = next((n for n in names if n.lower().endswith('.qgs')), None)
                    if not qgs_name:
                        continue

                    qgs_text = zin.read(qgs_name).decode('utf-8', errors='ignore')
                    for old_f, new_f in zip_renames.items():
                        qgs_text = qgs_text.replace(old_f, new_f)

                    with zipfile.ZipFile(tmp_path, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
                        for entry in names:
                            data = zin.read(entry)
                            target_entry = zip_renames.get(entry, entry)
                            if entry == qgs_name:
                                zout.writestr(target_entry, qgs_text.encode('utf-8'))
                            else:
                                zout.writestr(target_entry, data)

                os.replace(tmp_path, proj_path)
            except Exception as e:
                print(f"Could not update QGZ zip entries for duplicate code cleanup: {e}")

    def _filter_unassigned_layer(self, layer, target_geocode, is_ea_level):
        """Filter an unassigned layer based on target geocode level.
        
        - Barangay Level: Filters on "geocode" column using LIKE '<bgy_prefix>%' (e.g. "geocode" LIKE '01728001%').
        - EA Level: Filters on "ea_geocode" column using exact match (e.g. "ea_geocode" = '01716010001001').
        - No other columns will be detected or used as fallbacks.
        - If the target column is missing, leaves the layer unfiltered (clears any stale subset string).
        """
        if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
            return

        if layer.isEditable():
            layer.rollBack()

        raw_geocode = str(target_geocode).split('_', 1)[0].strip() if target_geocode else ""
        if raw_geocode.isdigit():
            if len(raw_geocode) in (13, 7, 4):
                clean_target_geocode = raw_geocode.zfill(len(raw_geocode) + 1)
            elif len(raw_geocode) < 14 and is_ea_level:
                clean_target_geocode = raw_geocode.zfill(14)
            elif len(raw_geocode) < 8 and not is_ea_level:
                clean_target_geocode = raw_geocode.zfill(8)
            else:
                clean_target_geocode = raw_geocode
        else:
            clean_target_geocode = raw_geocode

        bgy_prefix = clean_target_geocode[:8] if clean_target_geocode else ""

        # Build case-insensitive field mapping: lowercase_name -> (actual_name, index, field_obj)
        field_map = {}
        for i, fld in enumerate(layer.fields()):
            field_map[fld.name().strip().lower()] = (fld.name(), i, fld)

        if is_ea_level:
            # -------------------------------------------------------------
            # EA Level (14 digits) -> "ea_geocode" = '01716010001001'
            # -------------------------------------------------------------
            if "ea_geocode" in field_map:
                actual_name = field_map["ea_geocode"][0]
                layer.setSubsetString(f"\"{actual_name}\" = '{clean_target_geocode}'")
            else:
                layer.setSubsetString("")
        else:
            # -------------------------------------------------------------
            # Barangay Level (8 digits) -> "geocode" LIKE '01728001%'
            # -------------------------------------------------------------
            if "geocode" in field_map:
                actual_name = field_map["geocode"][0]
                layer.setSubsetString(f"\"{actual_name}\" LIKE '{bgy_prefix}%'")
            else:
                layer.setSubsetString("")

        layer.setCustomProperty("QFieldSync/action", "copy")

    def _filter_ea_layers(self, ea_layer, ea_geocode):
        """Apply subset filters for ``ea_geocode`` using the user-assigned layers.

        Layers are NOT renamed — original names are preserved.
        Optional linear layers (_road, _river, _bridge, _railroad) are spatially
        clipped to the bgy layer extent so only features in the area are exported.
        """
        # --- Assigned layers from the panel ---
        bgy_layer      = self._get_ea_assigned_layer("_ea_combo_bgy")
        bldg_layer     = self._get_ea_assigned_layer("_ea_combo_bldg")
        landmark_layer = self._get_ea_assigned_layer("_ea_combo_landmark")
        block_layer    = self._get_ea_assigned_layer("_ea_combo_block")
        road_layer     = self._get_ea_assigned_layer("_ea_combo_road")
        river_layer    = self._get_ea_assigned_layer("_ea_combo_river")
        bridge_layer   = self._get_ea_assigned_layer("_ea_combo_bridge")
        railroad_layer = self._get_ea_assigned_layer("_ea_combo_railroad")

        # --- Apply subset filters (no renaming) ---
        bgy_prefix = ea_geocode[:8]   # first 8 chars = pppmmbbb

        # EA layer: exact match on ea_geocode
        if isinstance(ea_layer, QgsVectorLayer) and ea_layer.isValid():
            ea_layer.setSubsetString(f"ea_geocode = '{ea_geocode}'")

        # Barangay layer: match first 8 chars of geocode column (geocode stores pppmmbbb000000)
        for lyr in (bgy_layer, landmark_layer):
            if not isinstance(lyr, QgsVectorLayer) or not lyr.isValid():
                continue
            lyr.setSubsetString(f"substr(\"geocode\", 1, 8) = '{bgy_prefix}'")

        # Building points layer: prefer ea_geocode column (exact match),
        # fall back to first 14 chars of bsn_geoid column.
        # Block layer: same logic.
        for lyr in (bldg_layer, block_layer):
            if not isinstance(lyr, QgsVectorLayer) or not lyr.isValid():
                continue
            fields = lyr.fields()
            if fields.indexOf("ea_geocode") != -1:
                lyr.setSubsetString(f"\"ea_geocode\" = '{ea_geocode}'")
            elif fields.indexOf("bsn_geoid") != -1:
                lyr.setSubsetString(f"substr(\"bsn_geoid\", 1, 14) = '{ea_geocode}'")
            else:
                # Last resort: geocode prefix match
                lyr.setSubsetString(f"substr(\"geocode\", 1, 8) = '{bgy_prefix}'")

        # Filter unassigned layers
        unassigned_layers = self._get_unassigned_map_layers()
        for lyr in unassigned_layers:
            self._filter_unassigned_layer(lyr, ea_geocode, is_ea_level=True)

        # Optional linear layers: select by location against the bgy layer
        linear_layers = [l for l in (road_layer, river_layer, bridge_layer, railroad_layer) if l]
        if linear_layers and bgy_layer and bgy_layer.isValid():
            # Build the union geometry directly from the filtered bgy features.
            # Using qgis:selectbylocation with a subset-filtered layer as the
            # INTERSECT input is unreliable — some QGIS versions evaluate
            # against the full unfiltered dataset, causing zero matches.
            bgy_geoms = [
                f.geometry()
                for f in bgy_layer.getFeatures()
                if f.geometry() and not f.geometry().isNull()
            ]
            bgy_union = QgsGeometry.unaryUnion(bgy_geoms) if bgy_geoms else None

            if bgy_union and not bgy_union.isEmpty():
                bgy_crs = bgy_layer.crs()
                bgy_bbox = bgy_union.boundingBox()
                for lyr in linear_layers:
                    if not isinstance(lyr, QgsVectorLayer) or not lyr.isValid():
                        continue
                    try:
                        lyr_crs = lyr.crs()
                        # Transform to the linear layer's CRS if needed
                        if bgy_crs != lyr_crs:
                            xform = QgsCoordinateTransform(
                                bgy_crs, lyr_crs, QgsProject.instance()
                            )
                            lyr_union = QgsGeometry(bgy_union)
                            lyr_union.transform(xform)
                            lyr_bbox = xform.transformBoundingBox(bgy_bbox)
                        else:
                            lyr_union = bgy_union
                            lyr_bbox = bgy_bbox

                        # Bounding-box pre-filter (fast), then exact intersection check
                        request = QgsFeatureRequest().setFilterRect(lyr_bbox)

                        # Determine the actual primary key field name — it varies
                        # by format (GeoPackage: fid, Shapefile: may differ, etc.)
                        pk_indices = lyr.dataProvider().pkAttributeIndexes()
                        if pk_indices:
                            pk_field = lyr.fields().at(pk_indices[0]).name()
                            candidate_ids = [
                                str(f.attribute(pk_indices[0]))
                                for f in lyr.getFeatures(request)
                                if f.geometry() and not f.geometry().isNull()
                                and f.geometry().intersects(lyr_union)
                            ]
                        else:
                            pk_field = "fid"
                            candidate_ids = [
                                str(f.id())
                                for f in lyr.getFeatures(request)
                                if f.geometry() and not f.geometry().isNull()
                                and f.geometry().intersects(lyr_union)
                            ]

                        if candidate_ids:
                            lyr.setSubsetString(f'"{pk_field}" IN ({",".join(candidate_ids)})')
                        else:
                            lyr.setSubsetString("1=0")
                    except Exception as e:
                        QgsApplication.instance().messageLog().logMessage(
                            f"Could not spatially filter {lyr.name()}: {e}",
                            "GMD Pipeline", Qgis.Warning,
                        )
            else:
                # bgy features empty after filter — leave linear layers unfiltered
                for lyr in linear_layers:
                    lyr.setSubsetString("")
        elif linear_layers:
            # No bgy layer assigned — leave linear layers unfiltered
            for lyr in linear_layers:
                lyr.setSubsetString("")

        self._ensure_ea_update_not_offline_and_writable()

        # Set initial map canvas extent to the EA layer (filtered to this geocode)
        # so QField opens zoomed to the individual EA boundary.
        try:
            if ea_layer and ea_layer.isValid():
                # updateExtents() forces QGIS to recalculate the layer extent
                # based on the active subset filter set earlier in this method.
                # Without it, extent() returns the stale cached full-layer extent.
                ea_layer.updateExtents()
                extent = ea_layer.extent()
                if not extent.isEmpty():
                    # Add a small buffer so features aren't at the very edge.
                    extent = extent.buffered(extent.width() * 0.1 or 0.001)
                    self.iface.mapCanvas().setExtent(extent)
                    self.iface.mapCanvas().refresh()
        except Exception as _e:
            QgsApplication.instance().messageLog().logMessage(
                f"Could not zoom canvas to EA extent: {_e}", "GMD Pipeline", Qgis.Warning,
            )

        # Apply snapping config so it is saved into the exported QGZ.
        try:
            self.auto_snap_layer()
        except Exception as _e:
            QgsApplication.instance().messageLog().logMessage(
                f"Could not apply snapping for EA export: {_e}", "GMD Pipeline", Qgis.Warning,
            )

        QgsProject.instance().write()

    def _package_ea_single(self, ea_geocode, export_folder):
        """Run OfflineConverter to package the project for one EA geocode.

        The output is written to ``{export_folder}/{ea_geocode}/{ea_geocode}.qgz``.
        """
        code_digits = str(ea_geocode)
        subfolder_path = export_folder / code_digits
        packaged_project_file = subfolder_path / f"{code_digits}.qgz"
        _actual_final = getattr(self, "final_raster_path", None)
        raster_base_name = (
            os.path.basename(_actual_final)
            if _actual_final
            else f"{code_digits}_img.tif"
        )

        # --- Clear / create export subfolder ---------------------------------
        if subfolder_path.exists():
            subfolder_abs = os.path.normcase(os.path.abspath(str(subfolder_path)))
            keep_raster_abs = os.path.normcase(
                os.path.abspath(
                    getattr(self, "final_raster_path", str(subfolder_path / raster_base_name))
                )
            )
            project = QgsProject.instance()
            for lyr in list(project.mapLayers().values()):
                try:
                    src = lyr.source() if hasattr(lyr, "source") else ""
                    if not src or not isinstance(lyr, QgsRasterLayer):
                        continue
                    src_abs = os.path.normcase(os.path.abspath(src))
                    if src_abs.startswith(subfolder_abs) and src_abs != keep_raster_abs:
                        project.removeMapLayer(lyr.id())
                except Exception:
                    continue
            try:
                QApplication.processEvents()
            except Exception:
                pass
            for item in subfolder_path.iterdir():
                try:
                    if item.is_file() and (
                        item.name == raster_base_name
                        or item.name.startswith(raster_base_name + ".")
                    ):
                        continue
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        for _ in range(5):
                            try:
                                item.unlink()
                                break
                            except PermissionError:
                                QApplication.processEvents()
                                time.sleep(0.2)
                except Exception:
                    pass
        subfolder_path.mkdir(parents=True, exist_ok=True)

        self.qfield_preferences.set_value("exportDirectoryProject", str(subfolder_path))
        self.dirsToCopyWidget.save_settings()
        self._ensure_ea_update_not_offline_and_writable()

        # Ensure all unassigned layers are filtered to this EA geocode before packaging
        for _unassigned_lyr in self._get_unassigned_map_layers():
            self._filter_unassigned_layer(_unassigned_lyr, code_digits, is_ea_level=True)

        # Remove stale generated rasters from previous iterations
        try:
            keep_sources = set()
            if hasattr(self, "temp_raster_path") and self.temp_raster_path:
                keep_sources.add(os.path.normcase(os.path.abspath(self.temp_raster_path)))
            project = QgsProject.instance()
            for lyr in list(project.mapLayers().values()):
                if not isinstance(lyr, QgsRasterLayer):
                    continue
                src = lyr.source() or ""
                if not src:
                    continue
                src_abs = os.path.normcase(os.path.abspath(src))
                src_name = os.path.basename(src_abs).lower()
                lyr_name = (lyr.name() or "").lower()
                if (
                    src_name.endswith("_img.tif")
                    or src_name.endswith("_img.mbtiles")
                    or lyr_name.endswith("_img")
                ) and src_abs not in keep_sources:
                    project.removeMapLayer(lyr.id())
        except Exception:
            pass

        # Ensure the current clipped raster is registered in the project
        try:
            desired_raster_name = f"{code_digits}_img"
            current_raster_path = None
            if hasattr(self, "temp_raster_path") and self.temp_raster_path and os.path.exists(self.temp_raster_path):
                current_raster_path = self.temp_raster_path
            elif hasattr(self, "final_raster_path") and self.final_raster_path and os.path.exists(self.final_raster_path):
                current_raster_path = self.final_raster_path
            if current_raster_path:
                current_abs = os.path.normcase(os.path.abspath(current_raster_path))
                found_current = False
                for lyr in QgsProject.instance().mapLayers().values():
                    if not isinstance(lyr, QgsRasterLayer):
                        continue
                    src = lyr.source() or ""
                    if src and os.path.normcase(os.path.abspath(src)) == current_abs:
                        lyr.setName(desired_raster_name)
                        found_current = True
                        break
                if not found_current:
                    raster_layer = QgsRasterLayer(current_raster_path, desired_raster_name)
                    if raster_layer.isValid():
                        QgsProject.instance().addMapLayer(raster_layer, False)
                        QgsProject.instance().layerTreeRoot().addLayer(raster_layer)
                        self.clipped_raster_layer = raster_layer
        except Exception:
            pass

        # EA Level: derive area_of_interest directly from the EA layer's
        # filtered extent so QField opens zoomed to the individual EA boundary.
        # Reading from the canvas is unreliable — compute it from the features.
        area_of_interest_crs = QgsProject.instance().crs().authid()
        area_of_interest = None
        try:
            _ea_lid = self.layer_dropdown.currentData()
            _ea_lyr = QgsProject.instance().mapLayer(_ea_lid) if _ea_lid else None
            if isinstance(_ea_lyr, QgsVectorLayer) and _ea_lyr.isValid():
                # Build the union of all filtered EA features so the AOI polygon
                # tightly wraps the individual EA boundary.
                _ea_geoms = [
                    f.geometry()
                    for f in _ea_lyr.getFeatures()
                    if f.geometry() and not f.geometry().isNull()
                ]
                if _ea_geoms:
                    _ea_union = QgsGeometry.unaryUnion(_ea_geoms)
                    if _ea_union and not _ea_union.isEmpty():
                        # Buffer 10 % so features aren't clipped at the very edge.
                        _bbox = _ea_union.boundingBox()
                        _buf = _bbox.width() * 0.1 or 0.001
                        _ea_union = _ea_union.buffer(_buf, 5)
                        area_of_interest = _ea_union.asWkt()
        except Exception as _aoi_err:
            QgsApplication.instance().messageLog().logMessage(
                f"Could not compute EA area_of_interest from layer: {_aoi_err}",
                "GMD Pipeline", Qgis.Warning,
            )
        if not area_of_interest:
            # Fallback to canvas extent if geometry union failed.
            area_of_interest = self.iface.mapCanvas().extent().asWktPolygon()

        def _build_converter(offliner_instance):
            converter = OfflineConverter(
                self.project,
                packaged_project_file,
                area_of_interest,
                area_of_interest_crs,
                self.qfield_preferences.value("attachmentDirs"),
                offliner_instance,
                ExportType.Cable,
                dirs_to_copy={},  # EA Level: no extra directories to copy
                export_title=code_digits,
            )
            converter.total_progress_updated.connect(self.update_total)
            converter.task_progress_updated.connect(self.update_task)
            converter.warning.connect(
                lambda title, body: QMessageBox.warning(None, title, body)
            )
            return converter

        def _rewrite_raster_source():
            _actual = getattr(self, "final_raster_path", None)
            raster_filename = os.path.basename(_actual) if _actual else f"{code_digits}_img.tif"
            target_ds = raster_filename

            # Also handle additional raster (_img_new)
            _add_actual = getattr(self, '_additional_raster_final_path', None)
            add_raster_filename = os.path.basename(_add_actual) if _add_actual else None

            project_path = str(packaged_project_file)
            if not os.path.exists(project_path):
                return
            if project_path.lower().endswith(".qgz"):
                tmp_qgz = project_path + ".tmp"
                with zipfile.ZipFile(project_path, "r") as zin:
                    names = zin.namelist()
                    qgs_name = next((n for n in names if n.lower().endswith(".qgs")), None)
                    if not qgs_name:
                        return
                    qgs_text = zin.read(qgs_name).decode("utf-8", errors="ignore")
                    try:
                        root_xml = ET.fromstring(qgs_text)
                        changed = False
                        for ml in root_xml.findall(".//maplayer"):
                            name_el = ml.find("layername")
                            ds_el = ml.find("datasource")
                            layer_name = (name_el.text or "").lower() if name_el is not None else ""
                            ds_text = (ds_el.text or "") if ds_el is not None else ""
                            if ds_el is not None:
                                # Satellite raster (_img)
                                if (
                                    raster_filename.lower() in ds_text.lower()
                                    or (layer_name.endswith("_img") and not layer_name.endswith("_img_new"))
                                ):
                                    ds_el.text = target_ds
                                    changed = True
                                # Additional raster (_img_new)
                                elif add_raster_filename and (
                                    add_raster_filename.lower() in ds_text.lower()
                                    or layer_name.endswith("_img_new")
                                ):
                                    ds_el.text = add_raster_filename
                                    changed = True
                        rewritten = ET.tostring(root_xml, encoding="unicode") if changed else qgs_text
                    except Exception:
                        rewritten = re.sub(
                            rf"(<datasource>)[^<]*{re.escape(raster_filename)}(</datasource>)",
                            rf"\1{target_ds}\2",
                            qgs_text,
                            flags=re.IGNORECASE,
                        )
                    with zipfile.ZipFile(tmp_qgz, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                        for name in names:
                            zout.writestr(
                                name,
                                rewritten.encode("utf-8") if name == qgs_name else zin.read(name),
                            )
                os.replace(tmp_qgz, project_path)
            else:
                with open(project_path, "r", encoding="utf-8", errors="ignore") as f:
                    qgs_text = f.read()
                rewritten = re.sub(
                    rf"(<datasource>)[^<]*{re.escape(raster_filename)}(</datasource>)",
                    rf"\1{target_ds}\2",
                    qgs_text,
                    flags=re.IGNORECASE,
                )
                with open(project_path, "w", encoding="utf-8") as f:
                    f.write(rewritten)

        # Build layer rename map: original display name → {ea_geocode}_suffix
        # Must be captured NOW, before _convert() recreates the C++ layer objects.
        _role_suffixes = {
            "_ea_combo_bgy":      "_bgy",
            "_ea_combo_bldg":     "_bldgpts",
            "_ea_combo_landmark": "_landmark",
            "_ea_combo_block":    "_block",
            "_ea_combo_road":     "_road",
            "_ea_combo_river":    "_river",
            "_ea_combo_bridge":   "_bridge",
            "_ea_combo_railroad": "_railroad",
        }
        layer_rename_map = {}
        for _attr, _suffix in _role_suffixes.items():
            _lyr = self._get_ea_assigned_layer(_attr)
            if _lyr and _lyr.isValid():
                layer_rename_map[self._normalized_layer_name(_lyr.name())] = f"{code_digits}{_suffix}"
        # Also rename the EA layer itself
        _ea_lid = self.layer_dropdown.currentData()
        if _ea_lid:
            _ea_lyr = QgsProject.instance().mapLayer(_ea_lid)
            if _ea_lyr and _ea_lyr.isValid():
                layer_rename_map[self._normalized_layer_name(_ea_lyr.name())] = f"{code_digits}_ea"

        # Rename the Form 2 Geotagging template layer (pppmmbbbeeeeee) to the EA geocode
        _FORM2_TEMPLATE_NAME = "pppmmbbbeeeeee"
        for _lyr in QgsProject.instance().mapLayers().values():
            if self._normalized_layer_name(_lyr.name()) == _FORM2_TEMPLATE_NAME:
                layer_rename_map[_FORM2_TEMPLATE_NAME] = code_digits
                break

        # Add all layers containing placeholders to layer_rename_map (handles copy layers, custom layers, etc.)
        for _lyr in QgsProject.instance().mapLayers().values():
            orig_name = self._normalized_layer_name(_lyr.name())
            new_name = orig_name
            for placeholder in ("pppmmbbbeeeeee", "pppmmbbb", "pppmm"):
                if placeholder in orig_name.lower():
                    idx = orig_name.lower().find(placeholder)
                    part_after = orig_name[idx + len(placeholder):]
                    
                    # Apply suffix transformation rule
                    if "_" in part_after:
                        u_idx = part_after.find("_")
                        suffix = part_after[u_idx:]
                    else:
                        suffix = ""
                    
                    new_name = orig_name[:idx] + code_digits + suffix
                    break
            if new_name != orig_name:
                layer_rename_map[orig_name] = new_name

        # Add all unassigned layers to layer_rename_map using suffix starting from the 1st '_'
        unassigned_layers = self._get_unassigned_map_layers()
        for _lyr in unassigned_layers:
            if not isinstance(_lyr, QgsVectorLayer) or not _lyr.isValid():
                continue
            orig_name = self._normalized_layer_name(_lyr.name()).strip()
            if orig_name in layer_rename_map:
                continue
            if "_" in orig_name:
                idx = orig_name.find("_")
                suffix = orig_name[idx:]
            else:
                suffix = f"_{orig_name}"
            layer_rename_map[orig_name] = f"{code_digits}{suffix}"

        bldg_new_name = f"{code_digits}_bldgpts"

        def _rename_and_regroup_layers():
            """Rename exported layers in the packaged QGZ."""
            project_path = str(packaged_project_file)
            if not layer_rename_map or not os.path.exists(project_path):
                return

            def _patch(text):
                try:
                    root = ET.fromstring(text)
                    changed = False

                    # Rename <layername> (and <title>) in every maplayer
                    for ml in root.findall(".//maplayer"):
                        for tag in ("layername", "title"):
                            el = ml.find(tag)
                            if el is not None and el.text and el.text.strip() in layer_rename_map:
                                el.text = layer_rename_map[el.text.strip()]
                                changed = True

                    # Rename name= attribute on every layer-tree-layer
                    for ltl in root.findall(".//layer-tree-layer"):
                        old = ltl.get("name", "")
                        if old in layer_rename_map:
                            ltl.set("name", layer_rename_map[old])
                            changed = True

                    if changed:
                        return ET.tostring(root, encoding="unicode")
                    return text
                except Exception as e:
                    QgsApplication.instance().messageLog().logMessage(
                        f"Layer rename patch error: {e}", "GMD Pipeline", Qgis.Warning,
                    )
                    return text

            if project_path.lower().endswith(".qgz"):
                tmp = project_path + ".renametmp"
                with zipfile.ZipFile(project_path, "r") as zin:
                    names = zin.namelist()
                    qgs_name = next((n for n in names if n.lower().endswith(".qgs")), None)
                    if not qgs_name:
                        return
                    qgs_text = zin.read(qgs_name).decode("utf-8", errors="ignore")
                    patched = _patch(qgs_text)
                    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                        for name in names:
                            zout.writestr(
                                name,
                                patched.encode("utf-8") if name == qgs_name else zin.read(name),
                            )
                os.replace(tmp, project_path)
            else:
                with open(project_path, "r", encoding="utf-8", errors="ignore") as f:
                    qgs_text = f.read()
                patched = _patch(qgs_text)
                with open(project_path, "w", encoding="utf-8") as f:
                    f.write(patched)



        def _convert():
            self._apply_role_policies_to_project_layers()
            # Ensure raster file is in subfolder_path BEFORE convert() runs
            if hasattr(self, "temp_raster_path") and hasattr(self, "final_raster_path"):
                if self.temp_raster_path and os.path.exists(self.temp_raster_path) and self.final_raster_path:
                    try:
                        os.makedirs(os.path.dirname(self.final_raster_path), exist_ok=True)
                        if self.temp_raster_path != self.final_raster_path:
                            shutil.copy2(self.temp_raster_path, self.final_raster_path)
                    except Exception:
                        pass
            orig_actions = self._disable_unused_qfield_actions()
            try:
                self._offline_convertor.convert()
            except shutil.SameFileError as e:
                src = getattr(e, "filename", None)
                dst = getattr(e, "filename2", None)
                if src and dst:
                    src_abs = os.path.normcase(os.path.abspath(src))
                    dst_abs = os.path.normcase(os.path.abspath(dst))
                    if src_abs != dst_abs:
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        if os.path.exists(dst):
                            os.remove(dst)
                        shutil.copy2(src, dst)
                        return
                QgsApplication.instance().messageLog().logMessage(
                    f"Ignoring same-path copy during EA export: {e}", "GMD Pipeline", Qgis.Info,
                )
            finally:
                self._restore_qfield_actions(orig_actions)

        self._offline_convertor = _build_converter(self.offliner)
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            # Make the satellite raster visible in the layer panel right before
            # OfflineConverter snapshots the project state into the QGZ.
            _root = QgsProject.instance().layerTreeRoot()
            _sat_visible = self._raster_satellite_visible.isChecked() if hasattr(self, '_raster_satellite_visible') else True
            for _rl in list(QgsProject.instance().mapLayers().values()):
                if isinstance(_rl, QgsRasterLayer) and self._normalized_layer_name(_rl.name()).lower().endswith("_img"):
                    _rn = _root.findLayer(_rl.id())
                    if _rn:
                        _rn.setItemVisibilityChecked(_sat_visible)

            # Load the additional raster (.mbtiles) into the project so
            # OfflineConverter includes it with full rendering XML.
            _add_temp = getattr(self, '_additional_raster_temp_path', None)
            _add_visible = self._raster_additional_visible.isChecked() if hasattr(self, '_raster_additional_visible') else True
            if _add_temp and os.path.exists(_add_temp):
                _add_rl = QgsRasterLayer(_add_temp, f"{code_digits}_img_new")
                if _add_rl.isValid():
                    QgsProject.instance().addMapLayer(_add_rl, False)
                    _add_node = _root.addLayer(_add_rl)
                    if _add_node:
                        _add_node.setItemVisibilityChecked(_add_visible)

            # Set canvas extent to the filtered EA feature right before convert()
            # so the QGZ stores the correct initial view for QField.
            # zoom_to_layer() uses selectAll()+zoomToSelected() which respects
            # the active subset filter and is more reliable than extent().
            try:
                self.zoom_to_layer(code_digits)
            except Exception:
                pass
            try:
                _convert()
            except IndexError as e:
                QgsApplication.instance().messageLog().logMessage(
                    f"EA export retry after IndexError: {e}", "GMD Pipeline", Qgis.Warning,
                )
                fallback_offliner = QgisCoreOffliner(offline_editing=False)
                fallback_offliner.warning.connect(self.show_warning)
                self._offline_convertor = _build_converter(fallback_offliner)
                _convert()

            # Move temp raster into the export subfolder
            if hasattr(self, "temp_raster_path") and hasattr(self, "final_raster_path"):
                if os.path.exists(self.temp_raster_path):
                    try:
                        os.makedirs(os.path.dirname(self.final_raster_path), exist_ok=True)
                        if os.path.exists(self.final_raster_path):
                            try:
                                os.remove(self.final_raster_path)
                            except Exception:
                                pass
                        shutil.copy2(self.temp_raster_path, self.final_raster_path)
                        try:
                            os.remove(self.temp_raster_path)
                        except Exception:
                            pass
                        for lyr in QgsProject.instance().mapLayers().values():
                            if isinstance(lyr, QgsRasterLayer) and lyr.source() == self.final_raster_path:
                                QgsProject.instance().removeMapLayer(lyr.id())
                        clipped_raster_layer = QgsRasterLayer(
                            self.final_raster_path, f"{code_digits}_img"
                        )
                        if clipped_raster_layer.isValid():
                            QgsProject.instance().addMapLayer(clipped_raster_layer, False)
                            QgsProject.instance().layerTreeRoot().addLayer(clipped_raster_layer)
                            self.clipped_raster_layer = clipped_raster_layer
                    except Exception as e:
                        QgsApplication.instance().messageLog().logMessage(
                            f"Could not move raster for {code_digits}: {e}",
                            "GMD Pipeline", Qgis.Warning,
                        )

            # Move additional raster into the export subfolder
            _add_temp = getattr(self, '_additional_raster_temp_path', None)
            _add_final = getattr(self, '_additional_raster_final_path', None)
            if _add_temp and _add_final and os.path.exists(_add_temp):
                try:
                    os.makedirs(os.path.dirname(_add_final), exist_ok=True)
                    if os.path.exists(_add_final):
                        try:
                            os.remove(_add_final)
                        except Exception:
                            pass
                    shutil.copy2(_add_temp, _add_final)
                    try:
                        os.remove(_add_temp)
                    except Exception:
                        pass
                    # Remove old _img_new layers from project, then re-add
                    # so the layer is available for the next iteration.
                    for lyr in list(QgsProject.instance().mapLayers().values()):
                        if isinstance(lyr, QgsRasterLayer) and self._normalized_layer_name(lyr.name()).lower().endswith("_img_new"):
                            QgsProject.instance().removeMapLayer(lyr.id())
                    _new_rl = QgsRasterLayer(_add_final, f"{code_digits}_img_new")
                    if _new_rl.isValid():
                        QgsProject.instance().addMapLayer(_new_rl, False)
                        QgsProject.instance().layerTreeRoot().addLayer(_new_rl)
                except Exception as e:
                    QgsApplication.instance().messageLog().logMessage(
                        f"Could not move additional raster for {code_digits}: {e}",
                        "GMD Pipeline", Qgis.Warning,
                    )

            try:
                _rewrite_raster_source()
            except Exception as e:
                QgsApplication.instance().messageLog().logMessage(
                    f"Could not rewrite raster source for {code_digits}: {e}",
                    "GMD Pipeline", Qgis.Warning,
                )

            try:
                _rename_and_regroup_layers()
                self._cleanup_duplicate_code_filenames(str(subfolder_path), code_digits)
            except Exception as e:
                QgsApplication.instance().messageLog().logMessage(
                    f"Could not rename/regroup layers for {code_digits}: {e}",
                    "GMD Pipeline", Qgis.Warning,
                )

            try:
                for _unassigned_lyr in self._get_unassigned_map_layers():
                    self._filter_unassigned_layer(_unassigned_lyr, code_digits, is_ea_level=True)
                self._export_individual_layers(code_digits, subfolder_path, packaged_project_file)
            except Exception as e:
                QgsApplication.instance().messageLog().logMessage(
                    f"Could not export individual layers for {code_digits}: {e}",
                    "GMD Pipeline", Qgis.Warning,
                )

            # Copy additional raster (.mbtiles) and patch visibility for both rasters
            try:
                self._copy_additional_raster_and_patch_visibility(code_digits, subfolder_path, packaged_project_file)
            except Exception as e:
                QgsApplication.instance().messageLog().logMessage(
                    f"Could not copy additional raster for {code_digits}: {e}",
                    "GMD Pipeline", Qgis.Warning,
                )


            self.do_post_offline_convert_action(True)
        except PackagingCanceledError:
            return
        except Exception as e:
            QgsApplication.instance().messageLog().logMessage(
                f"EA packaging failed for {code_digits}: {e}\n{traceback.format_exc()}",
                "GMD Pipeline", Qgis.Critical,
            )
            raise
        finally:
            QApplication.restoreOverrideCursor()
            self._offline_convertor = None

    def _export_individual_layers(self, code_digits, subfolder_path, packaged_project_file):
        """
        Physically trims vector layer features to target geocode and exports each layer 
        to its configured format from Configuration -> Layer Properties (.geojson, .gpkg, .shp, (data.gpkg)).
        Updates QGZ project datasources and clears subset strings.
        """
        import xml.etree.ElementTree as ET
        import zipfile
        import json
        import os
        from qgis.core import QgsVectorFileWriter, QgsProject, QgsVectorLayer, QgsSettings

        user_json = QSettings().value("gmd_pipeline/role_policies_dict", "{}")
        try:
            role_policies = json.loads(user_json) if isinstance(user_json, str) else user_json
            if not isinstance(role_policies, dict):
                role_policies = {}
        except Exception:
            role_policies = {}

        # Load per-layer data source overrides
        layer_ds_json = QSettings().value("gmd_pipeline/layer_data_sources_dict", "{}")
        try:
            layer_ds_policies = json.loads(layer_ds_json) if isinstance(layer_ds_json, str) else layer_ds_json
            if not isinstance(layer_ds_policies, dict):
                layer_ds_policies = {}
        except Exception:
            layer_ds_policies = {}

        attr_to_suffix = {
            "_ea_combo_geocode": "",
            "_bgy_combo_geocode": "",
            "_ea_combo_ea": "_ea",
            "_ea_combo_bgy": "_bgy",
            "_ea_combo_bldg": "_bldg_point",
            "_ea_combo_landmark": "_landmark",
            "_ea_combo_block": "_block",
            "_ea_combo_road": "_road",
            "_ea_combo_river": "_river",
            "_ea_combo_bridge": "_bridge",
            "_ea_combo_railroad": "_railroad",
            "_bgy_combo_ea": "_ea",
            "_bgy_combo_bgy": "_bgy",
            "_bgy_combo_bldg": "_bldg_point",
            "_bgy_combo_landmark": "_landmark",
            "_bgy_combo_block": "_block",
            "_bgy_combo_road": "_road",
            "_bgy_combo_river": "_river",
            "_bgy_combo_bridge": "_bridge",
            "_bgy_combo_railroad": "_railroad",
        }

        layer_role_info = {}
        if hasattr(self, 'layer_groups_tree'):
            def traverse(parent_item):
                for i in range(parent_item.childCount()):
                    item = parent_item.child(i)
                    combo = self.layer_groups_tree.itemWidget(item, 1)
                    if combo and combo.currentData() is not None:
                        attr_key = str(combo.currentData())
                        layer_name = item.text(0)
                        policy = role_policies.get(attr_key, {})
                        export_fmt = policy.get("format") or policy.get("export_format") or "(data.gpkg)"
                        suffix = attr_to_suffix.get(attr_key, f"_{self._normalized_layer_name(layer_name)}")
                        layer_role_info[layer_name] = {
                            "attr_key": attr_key,
                            "export_format": export_fmt,
                            "suffix": suffix,
                        }
                    traverse(item)
            traverse(self.layer_groups_tree.invisibleRootItem())

        project = QgsProject.instance()
        data_gpkg_path = os.path.join(str(subfolder_path), "data.gpkg")

        new_datasources = {}

        for layer in list(project.mapLayers().values()):
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                continue

            lname = layer.name()
            norm_name = self._normalized_layer_name(lname).lower()

            info = layer_role_info.get(lname, layer_role_info.get(norm_name, {}))
            fmt = info.get("export_format")

            # Per-layer data source override takes priority
            layer_ds_override = layer_ds_policies.get(layer.id(), {})
            if layer_ds_override.get("format"):
                fmt = layer_ds_override["format"]

            if not fmt:
                if norm_name.endswith("_special_ea"):
                    fmt = ".gpkg"
                    suffix = "_special_ea"
                elif norm_name.endswith(("_ea_update", "_bgy_update", "_geocode", "_geotag")) or "geotag" in norm_name or "update" in norm_name:
                    fmt = ".shp"
                    suffix = ""
                elif norm_name.endswith(("_bldg_point", "_bldgpts", "_bldg_points")):
                    fmt = ".geojson"
                    suffix = "_bldg_point"
                elif norm_name.endswith("_bgy"):
                    fmt = ".geojson"
                    suffix = "_bgy"
                elif norm_name.endswith("_ea"):
                    fmt = "(data.gpkg)"
                    suffix = "_ea"
                elif norm_name.endswith("_landmark"):
                    fmt = "(data.gpkg)"
                    suffix = "_landmark"
                elif norm_name.endswith("_block"):
                    fmt = "(data.gpkg)"
                    suffix = "_block"
                elif norm_name.endswith("_road"):
                    fmt = "(data.gpkg)"
                    suffix = "_road"
                elif norm_name.endswith("_river"):
                    fmt = "(data.gpkg)"
                    suffix = "_river"
                elif norm_name.endswith("_bridge"):
                    fmt = "(data.gpkg)"
                    suffix = "_bridge"
                elif norm_name.endswith("_railroad"):
                    fmt = "(data.gpkg)"
                    suffix = "_railroad"
                else:
                    fmt = "(data.gpkg)"
                    if "_" in lname:
                        idx = lname.find("_")
                        suffix = lname[idx:]
                    else:
                        suffix = ""
            else:
                if "_" in lname:
                    idx = lname.find("_")
                    suffix = lname[idx:]
                else:
                    suffix = info.get("suffix", "")

            if fmt == ".geojson":
                driver_name = "GeoJSON"
                out_filename = f"{code_digits}{suffix}.geojson"
                out_filepath = os.path.join(str(subfolder_path), out_filename)
                layer_table_name = None
            elif fmt == ".gpkg":
                driver_name = "GPKG"
                out_filename = f"{code_digits}{suffix}.gpkg"
                out_filepath = os.path.join(str(subfolder_path), out_filename)
                layer_table_name = f"{code_digits}{suffix}"
            elif fmt == ".shp":
                driver_name = "ESRI Shapefile"
                out_filename = f"{code_digits}{suffix}.shp"
                out_filepath = os.path.join(str(subfolder_path), out_filename)
                layer_table_name = None
            else:
                driver_name = "GPKG"
                out_filename = "data.gpkg"
                out_filepath = data_gpkg_path
                layer_table_name = lname

            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = driver_name
            options.fileEncoding = "UTF-8"
            if layer_table_name:
                options.layerName = layer_table_name

            if os.path.exists(out_filepath) and fmt == "(data.gpkg)":
                options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
            else:
                options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

            err, err_msg, out_path, out_name = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                out_filepath,
                project.transformContext(),
                options
            )

            if err == QgsVectorFileWriter.NoError:
                rel_path = os.path.relpath(out_filepath, str(subfolder_path)).replace("\\", "/")
                if layer_table_name:
                    new_ds = f"./{rel_path}|layername={layer_table_name}"
                else:
                    new_ds = f"./{rel_path}"
                new_datasources[layer.id()] = new_ds
                print(f"[TRIMMED EXPORT] Layer '{lname}' -> '{out_filename}' ({layer.featureCount()} features)")
            else:
                print(f"[TRIMMED EXPORT ERROR] Layer '{lname}': {err_msg}")

        project_path = str(packaged_project_file)
        if os.path.exists(project_path) and new_datasources:
            self._update_qgz_datasources(project_path, new_datasources)

        # Clean up any leftover raw source GPKG files (e.g. 04920_Pantabangan.gpkg) in subfolder
        referenced_files = set()
        if os.path.exists(project_path):
            try:
                import re
                if project_path.lower().endswith('.qgz'):
                    with zipfile.ZipFile(project_path, 'r') as zin:
                        qgs_name = next((n for n in zin.namelist() if n.lower().endswith('.qgs')), None)
                        if qgs_name:
                            qgs_text = zin.read(qgs_name).decode('utf-8', errors='ignore')
                            for ds_match in re.findall(r'<datasource>([^<]+)</datasource>', qgs_text, flags=re.IGNORECASE):
                                referenced_files.add(os.path.basename(ds_match.split('|')[0]))
                else:
                    with open(project_path, 'r', encoding='utf-8', errors='ignore') as f_in:
                        qgs_text = f_in.read()
                        for ds_match in re.findall(r'<datasource>([^<]+)</datasource>', qgs_text, flags=re.IGNORECASE):
                            referenced_files.add(os.path.basename(ds_match.split('|')[0]))
            except Exception:
                pass

        for f in os.listdir(str(subfolder_path)):
            if f.endswith(".gpkg") and f != "data.gpkg" and not f.startswith(code_digits) and f not in referenced_files:
                raw_gpkg_path = os.path.join(str(subfolder_path), f)
                try:
                    os.remove(raw_gpkg_path)
                    print(f"[CLEANUP] Removed unreferenced raw GPKG: {f}")
                except Exception:
                    pass

    def _update_qgz_datasources(self, project_path, new_datasources):
        """
        Updates <datasource> and clears <subsetexpression> tags in the packaged .qgz/.qgs project.
        """
        import zipfile
        import xml.etree.ElementTree as ET

        if project_path.lower().endswith('.qgz'):
            tmp_zip = project_path + ".tmp"
            try:
                with zipfile.ZipFile(project_path, 'r') as zin:
                    names = zin.namelist()
                    qgs_name = next((n for n in names if n.lower().endswith('.qgs')), None)
                    if not qgs_name:
                        return
                    qgs_bytes = zin.read(qgs_name)

                    root = ET.fromstring(qgs_bytes)
                    for layer_elem in root.findall(".//maplayer"):
                        id_elem = layer_elem.find("id")
                        if id_elem is not None and id_elem.text in new_datasources:
                            new_ds = new_datasources[id_elem.text]
                            ds_elem = layer_elem.find("datasource")
                            if ds_elem is not None:
                                ds_elem.text = new_ds
                            sub_elem = layer_elem.find("subsetexpression")
                            if sub_elem is not None:
                                sub_elem.text = ""
                            provider_elem = layer_elem.find("provider")
                            if provider_elem is not None:
                                provider_elem.text = "ogr"

                    updated_qgs = ET.tostring(root, encoding='utf-8')

                    with zipfile.ZipFile(tmp_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
                        for name in names:
                            if name == qgs_name:
                                zout.writestr(name, updated_qgs)
                            else:
                                zout.writestr(name, zin.read(name))
                os.replace(tmp_zip, project_path)
            except Exception as e:
                print(f"Error rewriting QGZ datasources: {e}")

    def do_post_offline_convert_action(self, is_success):
        """
        Show an information label that the project has been copied
        with a nice link to open the result folder.
        """
        if is_success:
            export_folder = self.get_export_folder_from_dialog()
            result_message = self.tr(
                "Finished creating the project at {result_folder}. Please copy this folder to "
                "your QField device."
            ).format(
                result_folder='<a href="{folder}">{display_folder}</a>'.format(
                    folder=QUrl.fromLocalFile(export_folder).toString(),
                    display_folder=QDir.toNativeSeparators(export_folder),
                )
            )
            status = Qgis.Success
        else:
            result_message = self.tr(
                "Failed to package project. See message log (Python Error) for more details."
            )
            status = Qgis.Warning

        self.iface.messageBar().pushMessage(result_message, status, 0)


    def update_info_visibility(self):
        """
        Show the info label if there are unconfigured layers
        """
        localizedDataPathLayers = []
        for layer in list(self.project.mapLayers().values()):
            layer_source = LayerSource(layer)

            if layer_source.is_localized_path:
                localizedDataPathLayers.append(
                    "- {} ({})".format(layer.name(), layer_source.filename)
                )

        if localizedDataPathLayers:
            if len(localizedDataPathLayers) == 1:
                self.infoLocalizedLayersLabel.setText(
                    self.tr("The layer stored in a localized data path is:\n{}").format(
                        "\n".join(localizedDataPathLayers)
                    )
                )
            else:
                self.infoLocalizedLayersLabel.setText(
                    self.tr(
                        "The layers stored in a localized data path are:\n{}"
                    ).format("\n".join(localizedDataPathLayers))
                )
            self.infoLocalizedLayersLabel.setVisible(True)
            self.infoLocalizedPresentLabel.setVisible(True)
        else:
            self.infoLocalizedLayersLabel.setVisible(False)
            self.infoLocalizedPresentLabel.setVisible(False)
        self.infoGroupBox.setVisible(len(localizedDataPathLayers) > 0)

    def show_settings(self):
        if Qgis.QGIS_VERSION_INT >= 31500:
            self.iface.showProjectPropertiesDialog("QField")
        else:
            dlg = ProjectConfigurationDialog(self.iface.mainWindow())
            dlg.exec_()
        self.update_info_visibility()

    def update_total(self, current, layer_count, message):
        if getattr(self, "_ea_batch_total", 0) > 0 or getattr(self, "_bgy_batch_total", 0) > 0:
            # Batch mode (EA or BGY): OfflineConverter's per-layer "total" progress goes
            # to the layer bar, while the total bar tracks batch progress.
            self.layerProgressBar.setMaximum(layer_count)
            self.layerProgressBar.setValue(current)
            # Don't overwrite the batch status label during OfflineConverter runs
        else:
            self.totalProgressBar.setMaximum(layer_count)
            self.totalProgressBar.setValue(current)
            self.statusLabel.setText(message)

    def update_task(self, progress, max_progress):
        self.layerProgressBar.setMaximum(max_progress)
        self.layerProgressBar.setValue(progress)

    def show_warning(self, _, message):
        # Most messages from the offline editing plugin are not important enough to show in the message bar.
        # In case we find important ones in the future, we need to filter them.
        QgsApplication.instance().messageLog().logMessage(message, "GMD Pipeline")



    # Custom code
    def run(self):
        try:
            # Initialize progress
            self.update_total(0, 100, "Starting process...")
            self.update_task(0, 100)

            # Resolve selected layer from combo data (we store layer ids)
            selected_layer = None
            selected_data = self.layer_dropdown.currentData()
            if isinstance(selected_data, str):
                selected_layer = QgsProject.instance().mapLayer(selected_data)

            # Fallback: resolve by displayed name if needed
            if selected_layer is None:
                selected_name = self.layer_dropdown.currentText()
                if selected_name:
                    for lyr in QgsProject.instance().mapLayers().values():
                        try:
                            if lyr.name() == selected_name:
                                selected_layer = lyr
                                break
                        except Exception:
                            continue

            selected_geocode = self.geocode_dropdown.currentText()

            # If still no valid layer, warn and stop to avoid crashes when
            # calling methods on None.
            if not selected_layer:
                QMessageBox.warning(self, "Selection Error", "Please select a valid layer.")
                return

            # Initial validation (10%)
            self.update_total(10, 100, "Validating inputs...")
            self.update_task(10, 100)

            if not isinstance(selected_layer, (QgsVectorLayer, QgsRasterLayer)):
                QMessageBox.warning(self, "Selection Error", "Please select a valid layer.")
                return

            if not selected_geocode:
                QMessageBox.warning(self, "Selection Error", "Please select a valid geocode.")
                return

            # Determine prefix based on selected output level (8 or 14 digits)
            base_pref = selected_geocode.split('_', 1)[0] if selected_geocode else ''
            if self.output_dropdown.currentText() == self.tr("EA Level"):
                prefix = base_pref[:14]
            else:
                prefix = base_pref[:8]

            # Layer name validation (20%)
            self.update_total(20, 100, "Checking layer names...")
            self.update_task(20, 100)
            
            print(f"Selected layer: {selected_layer.name()}")
            required = '_ea' if self.output_dropdown.currentText() == self.tr("EA Level") else '_bgy'
            if not selected_layer.name().endswith(required) or selected_layer.name().lower().endswith('_special_ea'):
                QMessageBox.warning(self, "Layer Error", f"The selected layer must have the suffix '{required}'.")
                return

            # Load layer mapping (30%)
            self.update_total(30, 100, "Loading layer mappings...")
            self.update_task(30, 100)

            self.layers = {
                layer.id(): layer for layer in QgsProject.instance().mapLayers().values()
                if (not self._normalized_layer_name(layer.name()).lower().endswith('_special_ea')) and layer.name().endswith((
                    '_bgy', '_ea', '_ea_update', '_block',
                    '_bldgpts', '_bldg_point', '_bldg_points',
                    '_landmark', '_road', '_river', '_bridge', '_railroad'
                ))
            }

            # Process CBMS Form 8 group (60%)
            self.update_total(60, 100, "Processing...")
            self.update_task(60, 100)

            # project = QgsProject.instance()
            # root = project.layerTreeRoot()
            # cbms_group = root.findGroup('CBMS Form 8')
            # if cbms_group is None:
            #     cbms_group = root.addGroup('CBMS Form 8')

            # Process layers (80%)
            self.update_total(80, 100, "Processing layers...")
            self.update_task(80, 100)

            # Rename layers in Base Layers and For Verification groups to reflect current prefix
            root = QgsProject.instance().layerTreeRoot()
            groups = [child for child in root.children() if isinstance(child, QgsLayerTreeGroup)]
            for group in groups:
                if 'Base Layers' in group.name():  # Check for "Base Layers" group
                    for layer in group.findLayers():
                        layer_name = self._normalized_layer_name(layer.layer().name()).lower()
                        if layer_name.endswith('_special_ea'):
                            continue
                        # `prefix` was determined earlier from the selected geocode/output level
                        if layer_name.endswith('_bgy'):
                            new_name = f"{prefix}_bgy"
                            layer.layer().setName(new_name)
                            print(f"Renamed base layer '{layer.layer().name()}' to '{new_name}'")
                        elif layer_name.endswith('_ea'):
                            new_name = f"{prefix}_ea"
                            layer.layer().setName(new_name)
                            print(f"Renamed base layer '{layer.layer().name()}' to '{new_name}'")
                        elif layer_name.endswith('_block'):
                            new_name = f"{prefix}_block"
                            layer.layer().setName(new_name)
                            print(f"Renamed base layer '{layer.layer().name()}' to '{new_name}'")
                        elif layer_name.endswith('_bldgpts'):
                            new_name = f"{prefix}_bldgpts"
                            layer.layer().setName(new_name)
                            print(f"Renamed base layer '{layer.layer().name()}' to '{new_name}'")
                        elif layer_name.endswith('_bldg_point'):
                            new_name = f"{prefix}_bldgpts"
                            layer.layer().setName(new_name)
                            print(f"Renamed base layer '{layer.layer().name()}' to '{new_name}'")
                        elif layer_name.endswith('_bldg_points'):
                            new_name = f"{prefix}_bldgpts"
                            layer.layer().setName(new_name)
                            print(f"Renamed base layer '{layer.layer().name()}' to '{new_name}'")
                        elif layer_name.endswith('_landmark'):
                            new_name = f"{prefix}_landmark"
                            layer.layer().setName(new_name)
                            print(f"Renamed base layer '{layer.layer().name()}' to '{new_name}'")
                        elif layer_name.endswith('_road'):
                            new_name = f"{prefix}_road"
                            layer.layer().setName(new_name)
                            print(f"Renamed base layer '{layer.layer().name()}' to '{new_name}'")
                        elif layer_name.endswith('_river'):
                            new_name = f"{prefix}_river"
                            layer.layer().setName(new_name)
                            print(f"Renamed base layer '{layer.layer().name()}' to '{new_name}'")
                        elif layer_name.endswith('_bridge'):
                            new_name = f"{prefix}_bridge"
                            layer.layer().setName(new_name)
                            print(f"Renamed base layer '{layer.layer().name()}' to '{new_name}'")
                        elif layer_name.endswith('_railroad'):
                            new_name = f"{prefix}_railroad"
                            layer.layer().setName(new_name)
                            print(f"Renamed base layer '{layer.layer().name()}' to '{new_name}'")
                        elif layer_name.endswith('_ea_update'):
                            new_name = f"{prefix}_ea_update"
                            layer.layer().setName(new_name)
                            print(f"Renamed base layer '{layer.layer().name()}' to '{new_name}'")

                elif 'For Verification' in group.name():  # Check for "For Verification" group
                    for layer in group.findLayers():
                        layer_name = self._normalized_layer_name(layer.layer().name()).lower()
                        if layer_name.endswith('_special_ea'):
                            continue
                        if layer_name.endswith('_ea_update'):
                            new_name = f"{prefix}_ea_update"
                            layer.layer().setName(new_name)
                            print(f"Renamed verification layer '{layer.layer().name()}' to '{new_name}'")

            # Call the instance method to filter layers
            self.filter_layers(self.layers, selected_geocode)
            is_ea = self.output_dropdown.currentText() == self.tr("EA Level")
            unassigned_layers = self._get_unassigned_map_layers()
            for lyr in unassigned_layers:
                self._filter_unassigned_layer(lyr, selected_geocode, is_ea_level=is_ea)
            self._ensure_ea_update_not_offline_and_writable()

            project = QgsProject.instance()
            project.write()  # Save the project
            print("Project auto-saved.")

            # Complete (100%)
            self.update_total(100, 100, "Filtering complete")
            self.update_task(100, 100)

        except Exception as e:
            # Handle any unexpected exceptions
            QMessageBox.critical(self, "Error", f"An unexpected error occurred: {str(e)}")
            print(f"Exception: {e}")  # Print the exception for debugging

    # ------------------------------------------------------------------
    # BGY Level batch export
    # ------------------------------------------------------------------

    def run_bgy_batch_export(self):
        """Iterate through every Barangay geocode and package each one.

        Steps per BGY geocode (first 8 digits of geocode):
          1. Filter project layers to that BGY (geocode field first 8 chars).
          2. Clip the satellite raster to that BGY's geometry.
          3. Package the filtered project as a QField .qgz into
             ``{ExportDir}/{bgy_geocode}/{bgy_geocode}.qgz``.
        """
        # Synchronize layer visibility check states and group structure (without re-applying QML styles)
        try:
            self._on_apply_layer_groups(apply_qml=False)
        except Exception as e:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"Auto-sync layer visibility before BGY batch export: {e}", "GMD Pipeline", Qgis.Warning)

        # --- Validate inputs ---
        selected_layer = None
        selected_data = self.layer_dropdown.currentData()
        if isinstance(selected_data, str):
            selected_layer = QgsProject.instance().mapLayer(selected_data)
        if selected_layer is None:
            QMessageBox.warning(self, "Selection Error", "Please select a valid Barangay layer.")
            return

        geocode_index = selected_layer.fields().indexOf("geocode")
        if geocode_index == -1:
            QMessageBox.warning(
                self, "Field Error",
                "The selected Barangay layer must have a 'geocode' field.",
            )
            return

        satellite_dir = self._raster_satellite_dir.filePath()
        if not satellite_dir or not os.path.isdir(satellite_dir):
            QMessageBox.warning(
                self, "Directory Error",
                "Please select a valid satellite image directory before exporting.",
            )
            return

        # Validate required layer assignments
        missing_required = []
        for attr, label, required in getattr(self, "_bgy_layer_roles", []):
            if required and self._get_bgy_assigned_layer(attr) is None:
                missing_required.append(label)
        if missing_required:
            QMessageBox.warning(
                self, "Missing Required Layers",
                "The following required layers are not assigned:\n\n"
                + "\n".join(f"  • {l}" for l in missing_required)
                + "\n\nPlease assign them in the Layer Assignment panel.",
            )
            return

        # Use the checked items from the BGY list widget
        geocodes = self._get_checked_bgy_geocodes()
        if not geocodes:
            QMessageBox.warning(self, "No Selection", "Please check at least one BGY geocode to process.")
            return

        export_folder = Path(self.manualDir.text())

        # Lock the UI during the batch run
        self.is_batch_mode = True
        self.batch_cancel_requested = False
        self._set_batch_ui_locked(True)
        self.button_box.button(QDialogButtonBox.Save).setEnabled(False)

        # Disable the QGIS layer tree so the user cannot double-click / drag
        # layers while OfflineConverter is rebuilding them.
        try:
            self.iface.layerTreeView().setEnabled(False)
        except Exception:
            pass

        processed_count = 0
        errors = []
        total_geocodes = len(geocodes)

        # Initialize the total (batch) progress bar for BGY count tracking.
        self._bgy_batch_total = total_geocodes
        self.totalProgressBar.setMaximum(total_geocodes)
        self.totalProgressBar.setValue(0)

        try:
            for bgy_index, bgy_geocode in enumerate(geocodes):
                if self.batch_cancel_requested:
                    break
                try:
                    self.statusLabel.setText(
                        f"BGY {bgy_index + 1}/{total_geocodes}: {bgy_geocode} — filtering layers..."
                    )
                    QApplication.processEvents()

                    # Re-fetch the BGY layer by ID each iteration
                    current_bgy_layer = QgsProject.instance().mapLayer(selected_data)
                    if current_bgy_layer is None or not current_bgy_layer.isValid():
                        raise RuntimeError(
                            "BGY layer is no longer available in the project. "
                            "Re-open the dialog and try again."
                        )

                    # 1. Filter all project layers to this BGY
                    self._filter_bgy_layers(current_bgy_layer, bgy_geocode)
                    QApplication.processEvents()

                    # 2. Resolve satellite image for this BGY geocode
                    # Source: {satellite_dir}/{pppmm}_img.<ext> based on format selection
                    pppmm = bgy_geocode[:5]
                    
                    format_idx = self._raster_type_combo.currentIndex() if hasattr(self, '_raster_type_combo') else 0
                    raster_file = None
                    if format_idx == 0:
                        raster_file = os.path.join(satellite_dir, f"{pppmm}_img.gpkg")
                    elif format_idx == 1:
                        raster_file = os.path.join(satellite_dir, f"{pppmm}_img.mbtiles")
                    else:
                        # Try GPKG first, then MBTiles
                        gpkg_path = os.path.join(satellite_dir, f"{pppmm}_img.gpkg")
                        mbtiles_path = os.path.join(satellite_dir, f"{pppmm}_img.mbtiles")
                        if os.path.exists(gpkg_path):
                            raster_file = gpkg_path
                        elif os.path.exists(mbtiles_path):
                            raster_file = mbtiles_path
                        else:
                            raster_file = gpkg_path  # Default for error reporting
                    
                    if not raster_file or not os.path.exists(raster_file):
                        ext_str = "_img.gpkg" if format_idx == 0 else ("_img.mbtiles" if format_idx == 1 else "_img.gpkg or _img.mbtiles")
                        QgsApplication.instance().messageLog().logMessage(
                            f"No satellite image found for {bgy_geocode}: {raster_file}",
                            "GMD Pipeline", Qgis.Warning,
                        )
                        errors.append(f"{bgy_geocode}: Missing satellite image ({pppmm}{ext_str}) — skipped")
                        continue

                    self.statusLabel.setText(
                        f"BGY {bgy_index + 1}/{total_geocodes}: {bgy_geocode} — clipping satellite image..."
                    )
                    QApplication.processEvents()

                    # 3. Clip the satellite raster to this BGY's geometry (main thread)
                    subfolder_path = str(export_folder / bgy_geocode)
                    self.temp_raster_path = None
                    self.final_raster_path = None

                    clip_ok, clip_msg = self._clip_raster_sync(
                        raster_file, current_bgy_layer, bgy_geocode, tempfile.gettempdir(),
                        convert_to_mbtiles=self._raster_convert_mbtiles.isChecked()
                    )
                    QApplication.processEvents()

                    if not clip_ok:
                        raise RuntimeError(f"Raster clipping failed: {clip_msg}")

                    # Derive correct extension from actual output (.mbtiles or .tif)
                    actual_ext = os.path.splitext(clip_msg)[1]  # e.g. ".mbtiles"
                    self.temp_raster_path = clip_msg
                    self.final_raster_path = os.path.join(
                        subfolder_path, f"{bgy_geocode}_img{actual_ext}"
                    )

                    # 3b. Clip additional raster (.mbtiles) if configured
                    self._additional_raster_temp_path = None
                    self._additional_raster_final_path = None
                    add_dir = self._raster_additional_dir.filePath() if hasattr(self, '_raster_additional_dir') else ""
                    if add_dir and os.path.isdir(add_dir):
                        add_src = os.path.join(add_dir, f"{pppmm}.mbtiles")
                        if os.path.exists(add_src):
                            self.statusLabel.setText(
                                f"BGY {bgy_index + 1}/{total_geocodes}: {bgy_geocode} — clipping additional raster..."
                            )
                            QApplication.processEvents()

                            add_clip_ok, add_clip_msg = self._clip_raster_sync(
                                add_src, current_bgy_layer, bgy_geocode, tempfile.gettempdir(),
                                convert_to_mbtiles=True, output_suffix="_img_new"
                            )
                            if add_clip_ok:
                                self._additional_raster_temp_path = add_clip_msg
                                self._additional_raster_final_path = os.path.join(
                                    subfolder_path, f"{bgy_geocode}_img_new.mbtiles"
                                )
                            else:
                                QgsApplication.instance().messageLog().logMessage(
                                    f"Additional raster clip failed for BGY {bgy_geocode}: {add_clip_msg}",
                                    "GMD Pipeline", Qgis.Warning,
                                )

                    self.statusLabel.setText(
                        f"BGY {bgy_index + 1}/{total_geocodes}: {bgy_geocode} — packaging..."
                    )
                    QApplication.processEvents()

                    # 4. Package the project for this BGY
                    self._package_bgy_single(bgy_geocode, export_folder)
                    QApplication.processEvents()

                    processed_count += 1
                    self.totalProgressBar.setValue(processed_count)
                    self.statusLabel.setText(
                        f"BGY {processed_count}/{total_geocodes} done — last: {bgy_geocode}"
                    )
                    QApplication.processEvents()

                except Exception as e:
                    errors.append(f"{bgy_geocode}: {e}")

            # Reset layer filters after all iterations
            try:
                self.reset_filter()
            except Exception:
                pass

        finally:
            was_cancelled = self.batch_cancel_requested
            self.is_batch_mode = False
            self.batch_cancel_requested = False
            self._bgy_batch_total = 0  # Restore update_total to normal mode
            self._set_batch_ui_locked(False)
            try:
                self.iface.layerTreeView().setEnabled(True)
            except Exception:
                pass

        # Summary
        if was_cancelled:
            summary = (
                f"BGY Export Cancelled\n\n"
                f"Processed: {processed_count} of {len(geocodes)}"
            )
        else:
            summary = (
                f"BGY Export Complete\n\n"
                f"Total packaged: {processed_count} of {len(geocodes)}"
            )
        if errors:
            preview = "\n".join(errors[:5])
            if len(errors) > 5:
                preview += f"\n...and {len(errors) - 5} more"
            summary += f"\n\nErrors:\n{preview}"

        self.batch_summary = summary
        QTimer.singleShot(100, self._show_batch_completion_and_close)

    def _filter_bgy_layers(self, bgy_layer, bgy_geocode):
        """Apply subset filters for first 8 chars of ``bgy_geocode`` using the user-assigned layers.

        Layers are NOT renamed — original names are preserved.
        Optional linear layers (_road, _river, _bridge, _railroad) are spatially
        clipped to the bgy layer extent so only features in the area are exported.
        """
        # --- Assigned layers from the panel ---
        ea_layer        = self._get_bgy_assigned_layer("_bgy_combo_ea")
        bldg_layer      = self._get_bgy_assigned_layer("_bgy_combo_bldg")
        landmark_layer  = self._get_bgy_assigned_layer("_bgy_combo_landmark")
        block_layer     = self._get_bgy_assigned_layer("_bgy_combo_block")
        road_layer      = self._get_bgy_assigned_layer("_bgy_combo_road")
        river_layer     = self._get_bgy_assigned_layer("_bgy_combo_river")
        bridge_layer    = self._get_bgy_assigned_layer("_bgy_combo_bridge")
        railroad_layer  = self._get_bgy_assigned_layer("_bgy_combo_railroad")

        # --- Apply subset filters (no renaming) ---
        bgy_prefix = bgy_geocode[:8]   # first 8 chars = pppmmbbb

        def apply_subset(layer, prefix, length=8):
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                return
            fields = layer.fields()
            found_field = None
            for fname in ("ea_geocode", "geocode", "bgy_code", "bsn_geoid", "code", "psgc"):
                if fields.indexOf(fname) != -1:
                    found_field = fname
                    break
            if found_field:
                layer.setSubsetString(f"substr(\"{found_field}\", 1, {length}) = '{prefix[:length]}'")
            else:
                layer.setSubsetString("")

        # BGY, EA, Landmark layers: match first 8 chars of geocode column
        apply_subset(bgy_layer, bgy_prefix, 8)
        apply_subset(ea_layer, bgy_prefix, 8)
        apply_subset(landmark_layer, bgy_prefix, 8)
        apply_subset(bldg_layer, bgy_prefix, 8)
        apply_subset(block_layer, bgy_prefix, 8)

        # Filter unassigned layers for Barangay level
        unassigned_layers = self._get_unassigned_map_layers()
        for lyr in unassigned_layers:
            self._filter_unassigned_layer(lyr, bgy_geocode, is_ea_level=False)

        # Optional linear layers: select by location against the bgy layer
        linear_layers = [l for l in (road_layer, river_layer, bridge_layer, railroad_layer) if l]
        if linear_layers and bgy_layer and bgy_layer.isValid():
            # Build the union geometry directly from the filtered bgy features.
            bgy_geoms = [
                f.geometry()
                for f in bgy_layer.getFeatures()
                if f.geometry() and not f.geometry().isNull()
            ]
            bgy_union = QgsGeometry.unaryUnion(bgy_geoms) if bgy_geoms else None

            if bgy_union and not bgy_union.isEmpty():
                bgy_crs = bgy_layer.crs()
                bgy_bbox = bgy_union.boundingBox()
                for lyr in linear_layers:
                    if not isinstance(lyr, QgsVectorLayer) or not lyr.isValid():
                        continue
                    try:
                        lyr_crs = lyr.crs()
                        # Transform to the linear layer's CRS if needed
                        if bgy_crs != lyr_crs:
                            xform = QgsCoordinateTransform(
                                bgy_crs, lyr_crs, QgsProject.instance()
                            )
                            lyr_union = QgsGeometry(bgy_union)
                            lyr_union.transform(xform)
                            lyr_bbox = xform.transformBoundingBox(bgy_bbox)
                        else:
                            lyr_union = bgy_union
                            lyr_bbox = bgy_bbox

                        # Bounding-box pre-filter (fast), then exact intersection check
                        request = QgsFeatureRequest().setFilterRect(lyr_bbox)

                        # Determine the actual primary key field name
                        pk_indices = lyr.dataProvider().pkAttributeIndexes()
                        if pk_indices:
                            pk_field = lyr.fields().at(pk_indices[0]).name()
                            candidate_ids = [
                                str(f.attribute(pk_indices[0]))
                                for f in lyr.getFeatures(request)
                                if f.geometry() and not f.geometry().isNull()
                                and f.geometry().intersects(lyr_union)
                            ]
                        else:
                            pk_field = "fid"
                            candidate_ids = [
                                str(f.id())
                                for f in lyr.getFeatures(request)
                                if f.geometry() and not f.geometry().isNull()
                                and f.geometry().intersects(lyr_union)
                            ]

                        if candidate_ids:
                            lyr.setSubsetString(f'"{pk_field}" IN ({",".join(candidate_ids)})')
                        else:
                            lyr.setSubsetString("1=0")
                    except Exception as e:
                        QgsApplication.instance().messageLog().logMessage(
                            f"Could not spatially filter {lyr.name()}: {e}",
                            "GMD Pipeline", Qgis.Warning,
                        )
            else:
                # bgy features empty after filter — leave linear layers unfiltered
                for lyr in linear_layers:
                    lyr.setSubsetString("")
        elif linear_layers:
            # No bgy layer assigned — leave linear layers unfiltered
            for lyr in linear_layers:
                lyr.setSubsetString("")

        self._ensure_ea_update_not_offline_and_writable()

        # Set initial map canvas extent to the BGY layer (filtered to this geocode)
        # so QField opens zoomed to the individual BGY boundary.
        try:
            if bgy_layer and bgy_layer.isValid():
                # updateExtents() forces QGIS to recalculate the layer extent
                # based on the active subset filter set earlier in this method.
                bgy_layer.updateExtents()
                extent = bgy_layer.extent()
                if not extent.isEmpty():
                    # Add a small buffer so features aren't at the very edge.
                    extent = extent.buffered(extent.width() * 0.1 or 0.001)
                    self.iface.mapCanvas().setExtent(extent)
                    self.iface.mapCanvas().refresh()
        except Exception as _e:
            QgsApplication.instance().messageLog().logMessage(
                f"Could not zoom canvas to BGY extent: {_e}", "GMD Pipeline", Qgis.Warning,
            )

        # Apply snapping config so it is saved into the exported QGZ.
        try:
            self.auto_snap_layer()
        except Exception as _e:
            QgsApplication.instance().messageLog().logMessage(
                f"Could not apply snapping for BGY export: {_e}", "GMD Pipeline", Qgis.Warning,
            )

        QgsProject.instance().write()

    def _package_bgy_single(self, bgy_geocode, export_folder):
        """Run OfflineConverter to package the project for one BGY geocode.

        The output is written to ``{export_folder}/{bgy_geocode}/{bgy_geocode}.qgz``.
        """
        code_digits = str(bgy_geocode)
        subfolder_path = export_folder / code_digits
        packaged_project_file = subfolder_path / f"{code_digits}.qgz"
        _actual_final = getattr(self, "final_raster_path", None)
        raster_base_name = (
            os.path.basename(_actual_final)
            if _actual_final
            else f"{code_digits}_img.tif"
        )

        # --- Clear / create export subfolder ---------------------------------
        if subfolder_path.exists():
            subfolder_abs = os.path.normcase(os.path.abspath(str(subfolder_path)))
            keep_raster_abs = os.path.normcase(
                os.path.abspath(
                    getattr(self, "final_raster_path", str(subfolder_path / raster_base_name))
                )
            )
            project = QgsProject.instance()
            for lyr in list(project.mapLayers().values()):
                try:
                    src = lyr.source() if hasattr(lyr, "source") else ""
                    if not src or not isinstance(lyr, QgsRasterLayer):
                        continue
                    src_abs = os.path.normcase(os.path.abspath(src))
                    if src_abs.startswith(subfolder_abs) and src_abs != keep_raster_abs:
                        project.removeMapLayer(lyr.id())
                except Exception:
                    continue
            try:
                QApplication.processEvents()
            except Exception:
                pass
            for item in subfolder_path.iterdir():
                try:
                    if item.is_file() and (
                        item.name == raster_base_name
                        or item.name.startswith(raster_base_name + ".")
                    ):
                        continue
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        for _ in range(5):
                            try:
                                item.unlink()
                                break
                            except PermissionError:
                                QApplication.processEvents()
                                time.sleep(0.2)
                except Exception:
                    pass
        subfolder_path.mkdir(parents=True, exist_ok=True)

        self.qfield_preferences.set_value("exportDirectoryProject", str(subfolder_path))
        self.dirsToCopyWidget.save_settings()
        self._ensure_ea_update_not_offline_and_writable()

        # Ensure all unassigned layers are filtered to this BGY geocode before packaging
        for _unassigned_lyr in self._get_unassigned_map_layers():
            self._filter_unassigned_layer(_unassigned_lyr, code_digits, is_ea_level=False)

        # Remove stale generated rasters from previous iterations
        try:
            keep_sources = set()
            if hasattr(self, "temp_raster_path") and self.temp_raster_path:
                keep_sources.add(os.path.normcase(os.path.abspath(self.temp_raster_path)))
            project = QgsProject.instance()
            for lyr in list(project.mapLayers().values()):
                if not isinstance(lyr, QgsRasterLayer):
                    continue
                src = lyr.source() or ""
                if not src:
                    continue
                src_abs = os.path.normcase(os.path.abspath(src))
                src_name = os.path.basename(src_abs).lower()
                lyr_name = (lyr.name() or "").lower()
                if (
                    src_name.endswith("_img.tif")
                    or src_name.endswith("_img.mbtiles")
                    or lyr_name.endswith("_img")
                ) and src_abs not in keep_sources:
                    project.removeMapLayer(lyr.id())
        except Exception:
            pass

        # Ensure the current clipped raster is registered in the project
        try:
            desired_raster_name = f"{code_digits}_img"
            current_raster_path = None
            if hasattr(self, "temp_raster_path") and self.temp_raster_path and os.path.exists(self.temp_raster_path):
                current_raster_path = self.temp_raster_path
            elif hasattr(self, "final_raster_path") and self.final_raster_path and os.path.exists(self.final_raster_path):
                current_raster_path = self.final_raster_path

            if current_raster_path:
                # Check if already in project
                found = False
                for lyr in QgsProject.instance().mapLayers().values():
                    try:
                        if isinstance(lyr, QgsRasterLayer):
                            src = lyr.source() or ""
                            src_norm = os.path.normcase(os.path.abspath(src))
                            curr_norm = os.path.normcase(os.path.abspath(current_raster_path))
                            if src_norm == curr_norm:
                                found = True
                                break
                    except Exception:
                        pass

                if not found:
                    # Register the raster layer at the BOTTOM of the layer tree
                    rlayer = QgsRasterLayer(current_raster_path, desired_raster_name)
                    if rlayer.isValid():
                        QgsProject.instance().addMapLayer(rlayer, False)
                        _root_tree = QgsProject.instance().layerTreeRoot()
                        _root_tree.addChildNode(QgsLayerTreeLayer(rlayer))
        except Exception as e:
            QgsApplication.instance().messageLog().logMessage(
                f"Could not register raster layer: {e}", "GMD Pipeline", Qgis.Warning,
            )

        # --- Build OfflineConverter with full parameters (matching EA export) ---
        area_of_interest_crs = QgsProject.instance().crs().authid()
        area_of_interest = None
        try:
            _bgy_lid = self.layer_dropdown.currentData()
            _bgy_lyr = QgsProject.instance().mapLayer(_bgy_lid) if _bgy_lid else None
            if isinstance(_bgy_lyr, QgsVectorLayer) and _bgy_lyr.isValid():
                _bgy_geoms = [
                    f.geometry()
                    for f in _bgy_lyr.getFeatures()
                    if f.geometry() and not f.geometry().isNull()
                ]
                if _bgy_geoms:
                    _bgy_union = QgsGeometry.unaryUnion(_bgy_geoms)
                    if _bgy_union and not _bgy_union.isEmpty():
                        _bbox = _bgy_union.boundingBox()
                        _buf = _bbox.width() * 0.1 or 0.001
                        _bgy_union = _bgy_union.buffer(_buf, 5)
                        area_of_interest = _bgy_union.asWkt()
        except Exception as _aoi_err:
            QgsApplication.instance().messageLog().logMessage(
                f"Could not compute BGY area_of_interest from layer: {_aoi_err}",
                "GMD Pipeline", Qgis.Warning,
            )
        if not area_of_interest:
            area_of_interest = self.iface.mapCanvas().extent().asWktPolygon()

        def _build_converter(offliner_instance):
            converter = OfflineConverter(
                self.project,
                packaged_project_file,
                area_of_interest,
                area_of_interest_crs,
                self.qfield_preferences.value("attachmentDirs"),
                offliner_instance,
                ExportType.Cable,
                dirs_to_copy={},
                export_title=code_digits,
            )
            converter.total_progress_updated.connect(self.update_total)
            converter.task_progress_updated.connect(self.update_task)
            converter.warning.connect(
                lambda title, body: QMessageBox.warning(None, title, body)
            )
            return converter

        def _rewrite_raster_source():
            _actual = getattr(self, "final_raster_path", None)
            raster_filename = os.path.basename(_actual) if _actual else f"{code_digits}_img.tif"
            target_ds = raster_filename

            # Also handle additional raster (_img_new)
            _add_actual = getattr(self, '_additional_raster_final_path', None)
            add_raster_filename = os.path.basename(_add_actual) if _add_actual else None

            project_path = str(packaged_project_file)
            if not os.path.exists(project_path):
                return
            if project_path.lower().endswith(".qgz"):
                tmp_qgz = project_path + ".tmp"
                with zipfile.ZipFile(project_path, "r") as zin:
                    names = zin.namelist()
                    qgs_name = next((n for n in names if n.lower().endswith(".qgs")), None)
                    if not qgs_name:
                        return
                    qgs_text = zin.read(qgs_name).decode("utf-8", errors="ignore")
                    try:
                        root_xml = ET.fromstring(qgs_text)
                        changed = False
                        for ml in root_xml.findall(".//maplayer"):
                            name_el = ml.find("layername")
                            ds_el = ml.find("datasource")
                            layer_name = (name_el.text or "").lower() if name_el is not None else ""
                            ds_text = (ds_el.text or "") if ds_el is not None else ""
                            if ds_el is not None:
                                # Satellite raster (_img)
                                if (
                                    raster_filename.lower() in ds_text.lower()
                                    or (layer_name.endswith("_img") and not layer_name.endswith("_img_new"))
                                ):
                                    ds_el.text = target_ds
                                    changed = True
                                # Additional raster (_img_new)
                                elif add_raster_filename and (
                                    add_raster_filename.lower() in ds_text.lower()
                                    or layer_name.endswith("_img_new")
                                ):
                                    ds_el.text = add_raster_filename
                                    changed = True
                        
                        # Move raster layer to the bottom of the layer tree
                        layer_tree = root_xml.find("layer-tree-group")
                        if layer_tree is not None:
                            raster_node = None
                            raster_parent = None
                            # Search recursively: the raster might be inside a nested group
                            def _find_raster_node(parent):
                                for child in list(parent):
                                    if child.tag == "layer-tree-layer":
                                        name = child.get("name", "")
                                        if name == f"{code_digits}_img" or name.endswith("_img"):
                                            return parent, child
                                    elif child.tag == "layer-tree-group":
                                        result = _find_raster_node(child)
                                        if result:
                                            return result
                                return None
                            
                            result = _find_raster_node(layer_tree)
                            if result:
                                raster_parent, raster_node = result
                                raster_parent.remove(raster_node)
                                # Always append to the ROOT layer-tree-group (bottom)
                                layer_tree.append(raster_node)
                                changed = True
                                
                        rewritten = ET.tostring(root_xml, encoding="unicode") if changed else qgs_text
                    except Exception:
                        rewritten = re.sub(
                            rf"(<datasource>)[^<]*{re.escape(raster_filename)}(</datasource>)",
                            rf"\1{target_ds}\2",
                            qgs_text,
                            flags=re.IGNORECASE,
                        )
                    with zipfile.ZipFile(tmp_qgz, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                        for name in names:
                            zout.writestr(
                                name,
                                rewritten.encode("utf-8") if name == qgs_name else zin.read(name),
                            )
                os.replace(tmp_qgz, project_path)
            else:
                with open(project_path, "r", encoding="utf-8", errors="ignore") as f:
                    qgs_text = f.read()
                rewritten = re.sub(
                    rf"(<datasource>)[^<]*{re.escape(raster_filename)}(</datasource>)",
                    rf"\1{target_ds}\2",
                    qgs_text,
                    flags=re.IGNORECASE,
                )
                with open(project_path, "w", encoding="utf-8") as f:
                    f.write(rewritten)

        # Build layer rename map: original display name -> {bgy_geocode}_suffix
        _role_suffixes = {
            "_bgy_combo_ea":       "_ea",
            "_bgy_combo_bldg":     "_bldgpts",
            "_bgy_combo_landmark": "_landmark",
            "_bgy_combo_block":    "_block",
            "_bgy_combo_road":     "_road",
            "_bgy_combo_river":    "_river",
            "_bgy_combo_bridge":   "_bridge",
            "_bgy_combo_railroad": "_railroad",
        }
        layer_rename_map = {}
        for _attr, _suffix in _role_suffixes.items():
            _lyr = self._get_bgy_assigned_layer(_attr)
            if _lyr and _lyr.isValid():
                layer_rename_map[self._normalized_layer_name(_lyr.name())] = f"{code_digits}{_suffix}"
        # Also rename the BGY layer itself
        _bgy_lid = self.layer_dropdown.currentData()
        if _bgy_lid:
            _bgy_lyr = QgsProject.instance().mapLayer(_bgy_lid)
            if _bgy_lyr and _bgy_lyr.isValid():
                layer_rename_map[self._normalized_layer_name(_bgy_lyr.name())] = f"{code_digits}_bgy"

        # Rename the Form 2 Geotagging template layer (pppmmbbbeeeeee) to the BGY geocode
        _FORM2_TEMPLATE_NAME = "pppmmbbbeeeeee"
        for _lyr in QgsProject.instance().mapLayers().values():
            if self._normalized_layer_name(_lyr.name()) == _FORM2_TEMPLATE_NAME:
                layer_rename_map[_FORM2_TEMPLATE_NAME] = code_digits
                break

        # Add all layers containing placeholders to layer_rename_map (handles copy layers, custom layers, etc.)
        for _lyr in QgsProject.instance().mapLayers().values():
            orig_name = self._normalized_layer_name(_lyr.name())
            new_name = orig_name
            for placeholder in ("pppmmbbbeeeeee", "pppmmbbb", "pppmm"):
                if placeholder in orig_name.lower():
                    idx = orig_name.lower().find(placeholder)
                    part_after = orig_name[idx + len(placeholder):]
                    
                    # Apply suffix transformation rule
                    if "_" in part_after:
                        u_idx = part_after.find("_")
                        suffix = part_after[u_idx:]
                    else:
                        suffix = ""
                    
                    new_name = orig_name[:idx] + code_digits + suffix
                    break
            if new_name != orig_name:
                layer_rename_map[orig_name] = new_name

        # Add all unassigned layers to layer_rename_map using suffix starting from the 1st '_'
        unassigned_layers = self._get_unassigned_map_layers()
        for _lyr in unassigned_layers:
            if not isinstance(_lyr, QgsVectorLayer) or not _lyr.isValid():
                continue
            orig_name = self._normalized_layer_name(_lyr.name()).strip()
            if orig_name in layer_rename_map:
                continue
            if "_" in orig_name:
                idx = orig_name.find("_")
                suffix = orig_name[idx:]
            else:
                suffix = f"_{orig_name}"
            layer_rename_map[orig_name] = f"{code_digits}{suffix}"

        bldg_new_name = f"{code_digits}_bldgpts"

        def _rename_and_regroup_layers():
            project_path = str(packaged_project_file)
            if not layer_rename_map or not os.path.exists(project_path):
                return

            def _patch(text):
                try:
                    root = ET.fromstring(text)
                    changed = False
                    for ml in root.findall(".//maplayer"):
                        for tag in ("layername", "title"):
                            el = ml.find(tag)
                            if el is not None and el.text and el.text.strip() in layer_rename_map:
                                el.text = layer_rename_map[el.text.strip()]
                                changed = True
                    for ltl in root.findall(".//layer-tree-layer"):
                        old = ltl.get("name", "")
                        if old in layer_rename_map:
                            ltl.set("name", layer_rename_map[old])
                            changed = True
                    if changed:
                        return ET.tostring(root, encoding="unicode")
                    return text
                except Exception as e:
                    QgsApplication.instance().messageLog().logMessage(
                        f"BGY layer rename patch error: {e}", "GMD Pipeline", Qgis.Warning,
                    )
                    return text

            if project_path.lower().endswith(".qgz"):
                tmp = project_path + ".renametmp"
                with zipfile.ZipFile(project_path, "r") as zin:
                    names = zin.namelist()
                    qgs_name = next((n for n in names if n.lower().endswith(".qgs")), None)
                    if not qgs_name:
                        return
                    qgs_text = zin.read(qgs_name).decode("utf-8", errors="ignore")
                    patched = _patch(qgs_text)
                    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                        for name in names:
                            zout.writestr(
                                name,
                                patched.encode("utf-8") if name == qgs_name else zin.read(name),
                            )
                os.replace(tmp, project_path)
            else:
                with open(project_path, "r", encoding="utf-8", errors="ignore") as f:
                    qgs_text = f.read()
                patched = _patch(qgs_text)
                with open(project_path, "w", encoding="utf-8") as f:
                    f.write(patched)



        def _convert():
            self._apply_role_policies_to_project_layers()
            # Ensure raster file is in subfolder_path BEFORE convert() runs
            if hasattr(self, "temp_raster_path") and hasattr(self, "final_raster_path"):
                if self.temp_raster_path and os.path.exists(self.temp_raster_path) and self.final_raster_path:
                    try:
                        os.makedirs(os.path.dirname(self.final_raster_path), exist_ok=True)
                        if self.temp_raster_path != self.final_raster_path:
                            shutil.copy2(self.temp_raster_path, self.final_raster_path)
                    except Exception:
                        pass
            orig_actions = self._disable_unused_qfield_actions()
            try:
                self._offline_convertor.convert()
            except shutil.SameFileError as e:
                src = getattr(e, "filename", None)
                dst = getattr(e, "filename2", None)
                if src and dst:
                    src_abs = os.path.normcase(os.path.abspath(src))
                    dst_abs = os.path.normcase(os.path.abspath(dst))
                    if src_abs != dst_abs:
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        if os.path.exists(dst):
                            os.remove(dst)
                        shutil.copy2(src, dst)
                        return
                QgsApplication.instance().messageLog().logMessage(
                    f"Ignoring same-path copy during BGY export: {e}", "GMD Pipeline", Qgis.Info,
                )
            finally:
                self._restore_qfield_actions(orig_actions)

        self._offline_convertor = _build_converter(self.offliner)
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            _root = QgsProject.instance().layerTreeRoot()
            _sat_visible = self._raster_satellite_visible.isChecked() if hasattr(self, '_raster_satellite_visible') else True
            for _rl in list(QgsProject.instance().mapLayers().values()):
                if isinstance(_rl, QgsRasterLayer) and self._normalized_layer_name(_rl.name()).lower().endswith("_img"):
                    _rn = _root.findLayer(_rl.id())
                    if _rn:
                        _rn.setItemVisibilityChecked(_sat_visible)

            # Load the additional raster (.mbtiles) into the project so
            # OfflineConverter includes it with full rendering XML.
            _add_temp = getattr(self, '_additional_raster_temp_path', None)
            _add_visible = self._raster_additional_visible.isChecked() if hasattr(self, '_raster_additional_visible') else True
            if _add_temp and os.path.exists(_add_temp):
                _add_rl = QgsRasterLayer(_add_temp, f"{code_digits}_img_new")
                if _add_rl.isValid():
                    QgsProject.instance().addMapLayer(_add_rl, False)
                    _add_node = _root.addLayer(_add_rl)
                    if _add_node:
                        _add_node.setItemVisibilityChecked(_add_visible)

            try:
                self.zoom_to_layer(code_digits)
            except Exception:
                pass
            try:
                _convert()
            except IndexError as e:
                QgsApplication.instance().messageLog().logMessage(
                    f"BGY export retry after IndexError: {e}", "GMD Pipeline", Qgis.Warning,
                )
                fallback_offliner = QgisCoreOffliner(offline_editing=False)
                fallback_offliner.warning.connect(self.show_warning)
                self._offline_convertor = _build_converter(fallback_offliner)
                _convert()

            # Move temp raster into the export subfolder
            if hasattr(self, "temp_raster_path") and hasattr(self, "final_raster_path"):
                if self.temp_raster_path and os.path.exists(self.temp_raster_path):
                    try:
                        os.makedirs(os.path.dirname(self.final_raster_path), exist_ok=True)
                        if os.path.exists(self.final_raster_path):
                            try:
                                os.remove(self.final_raster_path)
                            except Exception:
                                pass
                        shutil.copy2(self.temp_raster_path, self.final_raster_path)
                        try:
                            os.remove(self.temp_raster_path)
                        except Exception:
                            pass
                        for lyr in QgsProject.instance().mapLayers().values():
                            if isinstance(lyr, QgsRasterLayer) and lyr.source() == self.final_raster_path:
                                QgsProject.instance().removeMapLayer(lyr.id())
                        clipped_raster_layer = QgsRasterLayer(
                            self.final_raster_path, f"{code_digits}_img"
                        )
                        if clipped_raster_layer.isValid():
                            QgsProject.instance().addMapLayer(clipped_raster_layer, False)
                            # Add to the bottom of the layer tree (as the last layer) so it doesn't cover vectors
                            QgsProject.instance().layerTreeRoot().addChildNode(QgsLayerTreeLayer(clipped_raster_layer))
                            self.clipped_raster_layer = clipped_raster_layer
                    except Exception as e:
                        QgsApplication.instance().messageLog().logMessage(
                            f"Could not move raster for BGY {code_digits}: {e}",
                            "GMD Pipeline", Qgis.Warning,
                        )

            # Move additional raster into the export subfolder
            _add_temp = getattr(self, '_additional_raster_temp_path', None)
            _add_final = getattr(self, '_additional_raster_final_path', None)
            if _add_temp and _add_final and os.path.exists(_add_temp):
                try:
                    os.makedirs(os.path.dirname(_add_final), exist_ok=True)
                    if os.path.exists(_add_final):
                        try:
                            os.remove(_add_final)
                        except Exception:
                            pass
                    shutil.copy2(_add_temp, _add_final)
                    try:
                        os.remove(_add_temp)
                    except Exception:
                        pass
                    # Remove old _img_new layers from project, then re-add
                    for lyr in list(QgsProject.instance().mapLayers().values()):
                        if isinstance(lyr, QgsRasterLayer) and self._normalized_layer_name(lyr.name()).lower().endswith("_img_new"):
                            QgsProject.instance().removeMapLayer(lyr.id())
                    _new_rl = QgsRasterLayer(_add_final, f"{code_digits}_img_new")
                    if _new_rl.isValid():
                        QgsProject.instance().addMapLayer(_new_rl, False)
                        QgsProject.instance().layerTreeRoot().addLayer(_new_rl)
                except Exception as e:
                    QgsApplication.instance().messageLog().logMessage(
                        f"Could not move additional raster for BGY {code_digits}: {e}",
                        "GMD Pipeline", Qgis.Warning,
                    )

            try:
                _rewrite_raster_source()
            except Exception as e:
                QgsApplication.instance().messageLog().logMessage(
                    f"Could not rewrite raster source for BGY {code_digits}: {e}",
                    "GMD Pipeline", Qgis.Warning,
                )
            try:
                _rename_and_regroup_layers()
                self._cleanup_duplicate_code_filenames(str(subfolder_path), code_digits)
            except Exception as e:
                QgsApplication.instance().messageLog().logMessage(
                    f"Could not rename/regroup layers for BGY {code_digits}: {e}",
                    "GMD Pipeline", Qgis.Warning,
                )
            try:
                for _unassigned_lyr in self._get_unassigned_map_layers():
                    self._filter_unassigned_layer(_unassigned_lyr, code_digits, is_ea_level=False)
                self._export_individual_layers(code_digits, subfolder_path, packaged_project_file)
            except Exception as e:
                QgsApplication.instance().messageLog().logMessage(
                    f"Could not export individual layers for BGY {code_digits}: {e}",
                    "GMD Pipeline", Qgis.Warning,
                )

            # Copy additional raster (.mbtiles) and patch visibility for both rasters
            try:
                self._copy_additional_raster_and_patch_visibility(code_digits, subfolder_path, packaged_project_file)
            except Exception as e:
                QgsApplication.instance().messageLog().logMessage(
                    f"Could not copy additional raster for BGY {code_digits}: {e}",
                    "GMD Pipeline", Qgis.Warning,
                )

            self.do_post_offline_convert_action(True)
        except PackagingCanceledError:
            return
        except Exception as e:
            QgsApplication.instance().messageLog().logMessage(
                f"BGY packaging failed for {code_digits}: {e}\n{traceback.format_exc()}",
                "GMD Pipeline", Qgis.Critical,
            )
            raise
        finally:
            QApplication.restoreOverrideCursor()
            self._offline_convertor = None

    def save_raster_path(self, file_path):
        """Save the file path when the user selects a raster."""
        if file_path:
            self.saved_raster_file = file_path  # Save the selected raster file path
            print(f"Raster file selected: {self.saved_raster_file}")


    def run_raster(self):
        """Clips a raster layer using a buffered mask vector layer and builds pyramids on the result."""
        
        selected_geocode = self.geocode_dropdown.currentText()
        raster_file = self._raster_satellite_dir.filePath()

        # Resolve selected layer safely (we store layer ids in the combo)
        selected_layer = None
        selected_data = self.layer_dropdown.currentData()
        if isinstance(selected_data, str):
            selected_layer = QgsProject.instance().mapLayer(selected_data)
        # fallback: resolve by displayed name
        if selected_layer is None:
            selected_name = self.layer_dropdown.currentText()
            if selected_name:
                for lyr in QgsProject.instance().mapLayers().values():
                    try:
                        if lyr.name() == selected_name:
                            selected_layer = lyr
                            break
                    except Exception:
                        continue

        # Get the export folder path and temporary location for raster
        export_folder = Path(self.manualDir.text())
        # decide prefix length by output level
        prefix = selected_geocode.split('_', 1)[0] if selected_geocode else ''
        if self.output_dropdown.currentText() == self.tr("EA Level"):
            code_digits = prefix[:14]
        else:
            code_digits = prefix[:8]
        barangay_name = selected_geocode.split('_', 1)[1] if '_' in selected_geocode else ""
        subfolder_name = f"{code_digits}_{barangay_name}"
        subfolder_path = str(export_folder / subfolder_name)
        
        # Save raster to temp folder to avoid OfflineConverter conflicts
        temp_raster_dir = tempfile.gettempdir()
        
        # Store these for later use in package_project
        self.temp_raster_dir = temp_raster_dir
        self.temp_raster_path = os.path.join(temp_raster_dir, f"{code_digits}_img.tif")
        self.final_raster_path = os.path.join(str(subfolder_path), f"{code_digits}_img.tif")

        # Create and configure worker (pass code_digits so worker doesn't need to recompute)
        self.worker = RasterClipWorker(raster_file, selected_layer, selected_geocode, temp_raster_dir, subfolder_path, code_digits)
        
        # Connect signals
        self.worker.progress.connect(self.update_total)
        self.worker.task_progress.connect(self.update_task)
        self.worker.finished.connect(self.raster_process_complete)

        # Disable UI elements
        self.run_clip.setEnabled(False)
        self.button_box.setEnabled(False)

        # Start worker
        self.worker.start()

    def raster_process_complete(self, success, result):
        """Handle completion of raster processing."""
        if success:
            output_raster = result
            export_folder = Path(self.manualDir.text())
            selected_code = self.geocode_dropdown.currentText()
            prefix = selected_code.split('_', 1)[0] if selected_code else ''
            if self.output_dropdown.currentText() == self.tr("EA Level"):
                code_digits = prefix[:14]
            else:
                code_digits = prefix[:8]
            barangay_name = selected_code.split('_', 1)[1] if '_' in selected_code else ""
            subfolder_name = f"{code_digits}_{barangay_name}"
            subfolder_path = str(export_folder / subfolder_name)
            final_raster_path = os.path.join(subfolder_path, f"{code_digits}_img.tif")
            os.makedirs(subfolder_path, exist_ok=True)

            # Keep raster in temp until packaging. This avoids SameFileError
            # inside OfflineConverter and allows full export/copy of all files.
            self.temp_raster_path = output_raster
            self.final_raster_path = final_raster_path
            active_raster_path = output_raster

            # Remove old generated image rasters so only the current one is exported.
            for lyr in QgsProject.instance().mapLayers().values():
                if not isinstance(lyr, QgsRasterLayer):
                    continue
                src = lyr.source() or ""
                src_abs = os.path.normcase(os.path.abspath(src)) if src else ""
                src_name = os.path.basename(src_abs).lower() if src_abs else ""
                lyr_name = (lyr.name() or "").lower()
                is_generated_img = src_name.endswith('_img.tif') or lyr_name.endswith('_img') or lyr_name.endswith('_img.tif')
                if is_generated_img:
                    QgsProject.instance().removeMapLayer(lyr.id())

            # Add the raster to the project so user can see it in layers panel
            clipped_raster_layer = QgsRasterLayer(active_raster_path, f"{code_digits}_img")
            if clipped_raster_layer.isValid():
                QgsProject.instance().addMapLayer(clipped_raster_layer, False)
                root = QgsProject.instance().layerTreeRoot()
                root.addLayer(clipped_raster_layer)
                self.clipped_raster_layer = clipped_raster_layer
                iface.messageBar().pushInfo("Process Complete", f"Raster clipped and staged for export:\n{active_raster_path}")
            else:
                iface.messageBar().pushInfo("Layer Error", "Failed to load clipped raster layer.")
        else:
            iface.messageBar().pushInfo("Error", f"Process failed: {result}")

        # Re-enable UI elements
        self.run_clip.setEnabled(True)
        self.button_box.setEnabled(True)
  
    def reset_filter(self):
        self.zoom_to_mun()
        # put group selector back to Base Layers
        idx = self.group_dropdown.findText('Base Layers')
        if idx != -1:
            self.group_dropdown.setCurrentIndex(idx)
        # Get the currently selected geocode from the geocode_dropdown widget
        selected_geocode = self.geocode_dropdown.currentText()
        # choose default prefix according to output level
        level = self.output_dropdown.currentText().lower()
        if "ea" in level:
            default_prefix = 'pppmmbbb'
        else:
            # fallback to barangay-level default
            default_prefix = 'pppmm'

        print("Resetting filters...")  # Debugging line
        self.layer_dropdown.clear()      # Clear the layer dropdown
        self.geocode_dropdown.clear()    # Clear the geocode dropdown
        self.infoLocalizedLayersLabel.setVisible(False)  # Hide any info labels
        self.infoLocalizedPresentLabel.setVisible(False)
        self.infoGroupBox.setVisible(False)

        # Get the current QGIS project instance
        project = QgsProject.instance()
        if not project:
            return

        # Reset filters on all vector layers
        for layer in list(project.mapLayers().values()):
            try:
                if sip.isdeleted(layer):
                    continue
                if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                    continue
                print("Resetting filter on layer:", layer.name())
                layer.setSubsetString("")  # Clear the subset string to reset the filter
                try:
                    tree_layer = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
                    if tree_layer is not None and not sip.isdeleted(tree_layer):
                        tree_layer.setCustomProperty("showFeatureCount", False)
                        layer_name = self._normalized_layer_name(layer.name())
                        tree_layer.setName(layer_name)
                except Exception:
                    pass
            except Exception:
                pass
            except Exception as e:
                print(f"Error resetting filter on layer: {e}")

        # Remove raster layers whose names end with '_img' and delete the corresponding files
        for layer in list(project.mapLayers().values()):
            try:
                if sip.isdeleted(layer):
                    continue
                if isinstance(layer, QgsRasterLayer) and layer.name().endswith('_img'):
                    file_path = layer.source()
                    print("Removing raster layer:", layer.name(), "with file:", file_path)
                    project.removeMapLayer(layer.id())
                    if os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            print("Deleted file:", file_path)
                        except Exception as e:
                            print("Error deleting file:", file_path, e)
            except Exception:
                pass

        # Modify this section to check for layers inside the "Base Layers"  group
        root = QgsProject.instance().layerTreeRoot()
        for group in root.children():
            if isinstance(group, QgsLayerTreeGroup):
                if group.name() == 'Base Layers':  
                    for layer in group.findLayers():
                        layer_name = self._normalized_layer_name(layer.layer().name()).lower()
                        if layer_name.endswith('_special_ea'):
                            continue
                        # determine base prefix (up to underscore) then trim by output level
                        base_pref = selected_geocode.split('_', 1)[0] if selected_geocode else default_prefix
                        if self.output_dropdown.currentText() == self.tr("EA Level"):
                            prefix = base_pref[:14]
                        else:
                            prefix = base_pref[:8]
                        if layer_name.endswith('_bgy'):
                            new_name = f"{prefix}_bgy"
                        elif layer_name.endswith('_ea_update'):
                            new_name = f"{prefix}_ea_update"
                        elif layer_name.endswith('_ea'):
                            new_name = f"{prefix}_ea"
                        elif layer_name.endswith('_block'):
                            new_name = f"{prefix}_block"
                        elif layer_name.endswith('_bldgpts'):
                            new_name = f"{prefix}_bldgpts"
                        elif layer_name.endswith('_bldg_point'):
                            new_name = f"{prefix}_bldgpts"
                        elif layer_name.endswith('_bldg_points'):
                            new_name = f"{prefix}_bldgpts"
                        elif layer_name.endswith('_landmark'):
                            new_name = f"{prefix}_landmark"
                        elif layer_name.endswith('_road'):
                            new_name = f"{prefix}_road"
                        elif layer_name.endswith('_river'):
                            new_name = f"{prefix}_river"
                        elif layer_name.endswith('_bridge'):
                            new_name = f"{prefix}_bridge"
                        elif layer_name.endswith('_railroad'):
                            new_name = f"{prefix}_railroad"
                        else:
                            continue
                        layer.layer().setName(new_name)
                        print(f"Renamed base layer to '{new_name}'")

                elif group.name() == 'For Verification':  
                    for layer in group.findLayers():
                        layer_name = self._normalized_layer_name(layer.layer().name()).lower()
                        if layer_name.endswith('_special_ea'):
                            continue
                        # determine prefix according to output level
                        base_pref = selected_geocode.split('_', 1)[0] if selected_geocode else default_prefix
                        if self.output_dropdown.currentText() == self.tr("EA Level"):
                            prefix = base_pref[:14]
                        else:
                            prefix = base_pref[:8]
                        if layer_name.endswith('_ea_update'):
                            new_name = f"{prefix}_ea_update"
                        else:
                            continue
                        layer.layer().setName(new_name)
                        print(f"Renamed verification layer to '{new_name}'")

        # switch back to Base Layers group, then rename layers so they reflect the default prefix
        idx = self.group_dropdown.findText('Base Layers')
        if idx != -1:
            self.group_dropdown.setCurrentIndex(idx)
        self.rename_layers_by_output_level()

        # Optionally, repopulate the dropdowns if needed
        self.populate_layers_dropdown()
        self.populate_geocode_dropdown()
        self.populate_citymun_dropdown()
        self.populate_bgy_dropdown()

        # Disable the Save button and other UI elements as needed
        self.button_box.button(QDialogButtonBox.Save).setEnabled(False)
        self.run_clip.setEnabled(False)
        self.zoom_to_mun()
        project = QgsProject.instance()
        # Set project title using selected geocode or default prefix, trimmed by output level
        base_pref = selected_geocode.split('_', 1)[0] if selected_geocode else default_prefix
        if self.output_dropdown.currentText() == self.tr("EA Level"):
            title_prefix = base_pref[:14]
        else:
            title_prefix = base_pref[:8]
        project.setTitle(title_prefix)
        project.write()

   
    def rename_layers_by_output_level(self):
        """Rename existing project layers according to the current
        geocode and output level formatting (8 vs 14 digits).

        When no geocode is selected (e.g. immediately after a reset) fall
        back to a generic default prefix so the layer tree still reflects
        the chosen output level.
        """
        selected_geocode = self.geocode_dropdown.currentText()
        if selected_geocode:
            base_pref = selected_geocode.split('_', 1)[0]
        else:
            # no geocode, choose default prefix per level
            if self.output_dropdown.currentText() == self.tr("EA Level"):
                base_pref = 'pppmmbbb'
            else:
                base_pref = 'pppmm'

        if self.output_dropdown.currentText() == self.tr("EA Level"):
            prefix = base_pref[:14]
        else:
            prefix = base_pref[:8]

        for layer in QgsProject.instance().mapLayers().values():
            name = self._normalized_layer_name(layer.name()).lower()
            if name.endswith("_special_ea"):
                continue
            for sfx in (
                '_bgy', '_ea', '_ea_update', '_block',
                '_bldgpts', '_bldg_point', '_bldg_points',
                '_landmark', '_road', '_river', '_bridge', '_railroad'
            ):
                if name.endswith(sfx):
                    layer.setName(prefix + sfx)
                    break

    def filter_layers(self, layers, selected_geocode):
        # determine prefix length from user choice; use only the part before the underscore
        if selected_geocode:
            base_pref = selected_geocode.split('_', 1)[0]
            if self.output_dropdown.currentText() == self.tr("EA Level"):
                prefix = base_pref[:14]
            else:
                prefix = base_pref[:8]
        else:
            prefix = ''

        # Loop through each layer in the dictionary and apply relevant filters
        updated_layers = []
        for layer_key, layer in layers.items():
            if layer is not None and layer.isValid():
                # Apply filters based on suffixes
                layer_name = self._normalized_layer_name(layer.name())
                if layer_name.lower().endswith('_special_ea'):
                    continue
                elif layer_name.endswith('_bgy'):
                    layer.setSubsetString(f"geocode LIKE '{prefix}%'")
                    updated_layers.append(layer)
                elif layer_name.endswith('_ea'):
                    layer.setSubsetString(f"geocode LIKE '{prefix}%'")
                    updated_layers.append(layer)
                elif layer_name.endswith('_bldgpts'):
                    layer.setSubsetString(f"geocode LIKE '{prefix}%'")
                    updated_layers.append(layer)
                elif layer_name.endswith('_bldg_point'):
                    layer.setSubsetString(f"geocode LIKE '{prefix}%'")
                    updated_layers.append(layer)
                elif layer_name.endswith('_bldg_points'):
                    layer.setSubsetString(f"geocode LIKE '{prefix}%'")
                    updated_layers.append(layer)
                elif layer_name.endswith('_landmark'):
                    layer.setSubsetString(f"geocode LIKE '{prefix}%'")
                    updated_layers.append(layer)
                elif layer_name.endswith('_ea_update'):
                    layer.setSubsetString(f"geocode LIKE '{prefix}%'")
                    updated_layers.append(layer)
                elif layer_name.endswith('_block'):
                    layer.setSubsetString(f"geocode LIKE '{prefix}%'")
                    updated_layers.append(layer)
                elif layer_name.endswith(('_road', '_river', '_bridge', '_railroad')):
                    # No subset filter — show all features for these reference layers
                    updated_layers.append(layer)
                else:
                    QMessageBox.warning(None, "Unsupported Layer", f"Layer '{layer.name()}' does not match any known suffixes.")
            else:
                QMessageBox.warning(None, "Layer Invalid", f"The layer '{layer_key}' is not valid or does not exist.")

        # Force layer tree and map canvas refresh so filtered features are shown immediately.
        for lyr in updated_layers:
            try:
                tree_layer = QgsProject.instance().layerTreeRoot().findLayer(lyr.id())
                if tree_layer is not None:
                    tree_layer.setCustomProperty("showFeatureCount", False)
                    tree_layer.setName(self._normalized_layer_name(lyr.name()))
                lyr.triggerRepaint()
                self.iface.layerTreeView().refreshLayerSymbology(lyr.id())
            except Exception:
                pass

        try:
            self.iface.mapCanvas().refreshAllLayers()
            self.iface.mapCanvas().refresh()
        except Exception:
            pass

        # Call select_by_location after filtering layers
        self.select_by_location()
        self.button_box.button(QDialogButtonBox.Save).setEnabled(True)
        self.run_clip.setEnabled(True)
        self.zoom_to_layer(prefix)
        self.auto_snap_layer()
        self.update_value_relations()
        self.set_read_only_for_selected_layers()

    
    def zoom_to_layer(self, geocode):
        is_ea_level = "ea level" in self.output_dropdown.currentText().lower()
        preferred_suffix = "_ea" if is_ea_level else "_bgy"
        fallback_suffix  = "_bgy" if is_ea_level else None
        target_layer = None

        root = QgsProject.instance().layerTreeRoot()
        base_group = root.findGroup("Base Layers")

        for suffix in ([preferred_suffix] + ([fallback_suffix] if fallback_suffix else [])):
            # First search inside Base Layers group to avoid picking up
            # unfiltered layers from other groups (e.g. For Verification).
            if base_group:
                for tree_layer in base_group.findLayers():
                    lyr = tree_layer.layer()
                    if lyr and isinstance(lyr, QgsVectorLayer):
                        lname = self._normalized_layer_name(lyr.name()).lower()
                        if lname.endswith(suffix):
                            target_layer = lyr
                            break
            # Fallback: search all layers if not found in Base Layers.
            if not target_layer:
                for lyr in QgsProject.instance().mapLayers().values():
                    if isinstance(lyr, QgsVectorLayer):
                        lname = self._normalized_layer_name(lyr.name()).lower()
                        if lname.endswith(suffix):
                            target_layer = lyr
                            break
            if target_layer:
                break

        if target_layer:
            target_layer.selectAll()
            iface.mapCanvas().zoomToSelected(target_layer)
            target_layer.removeSelection()
            print(f"Zoomed to filtered layer: {target_layer.name()} with geocode = {geocode}")
        else:
            print(f"No layer found ending with '{preferred_suffix}'")

    def zoom_to_mun(self):
        # Retrieve all layers in the project
        layers = QgsProject.instance().mapLayers().values()

        # Iterate through each layer
        for layer in layers:
            # Check if the layer's name ends with 'river'
            if self._normalized_layer_name(layer.name()).endswith('_river'):
                # Get the extent of the layer
                extent = layer.extent()
                # Set the map canvas to the layer's extent
                iface.mapCanvas().setExtent(extent)
                iface.mapCanvas().refresh()
                print(f"Zoomed to the extent of the layer: {layer.name()}")
                break
        else:
            print("No layer found with a name ending with 'river'.")


    def load_layer_groups(self):
        # Populate the group dropdown with layer groups in the project
        self.group_dropdown.clear()
        root = QgsProject.instance().layerTreeRoot()
        groups = [child for child in root.children() if isinstance(child, QgsLayerTreeGroup)]
        for group in groups:
            # Store only the group name (string) as combo data to avoid holding
            # references to C++ objects that may become invalid after project
            # modifications. Resolve the group fresh when needed.
            self.group_dropdown.addItem(group.name(), group.name())
        
        # If 'Base Layers' exists choose it by default
        idx = self.group_dropdown.findText('Base Layers')
        if idx != -1:
            self.group_dropdown.setCurrentIndex(idx)
        
        # Validate group selection after loading groups
        self.validate_group_selection()





    def populate_layers_dropdown(self):
        """Populate the layer dropdown based on the selected group or output level."""
        self.layer_dropdown.blockSignals(True)
        try:
            # For EA Level: scan all project layers for _ea suffix (no group filter needed).
            if self.output_dropdown.currentText() == self.tr("EA Level"):
                self.layer_dropdown.clear()
                for layer_obj in sorted(
                    QgsProject.instance().mapLayers().values(),
                    key=lambda l: l.name(),
                ):
                    name_lower = self._normalized_layer_name(layer_obj.name()).lower()
                    if name_lower.endswith("_special_ea"):
                        continue
                    if name_lower.endswith("_ea"):
                        self.layer_dropdown.addItem(layer_obj.name(), layer_obj.id())
                if self.layer_dropdown.count() > 0:
                    self.layer_dropdown.setCurrentIndex(0)
                    self.button_box.button(QDialogButtonBox.Save).setEnabled(True)
                return

            # For BGY Level: scan all project layers for _bgy suffix (no group filter needed).
            if self.output_dropdown.currentText() == self.tr("Barangay Level"):
                self.layer_dropdown.clear()
                for layer_obj in sorted(
                    QgsProject.instance().mapLayers().values(),
                    key=lambda l: l.name(),
                ):
                    if self._normalized_layer_name(layer_obj.name()).lower().endswith("_bgy"):
                        self.layer_dropdown.addItem(layer_obj.name(), layer_obj.id())
                if self.layer_dropdown.count() > 0:
                    self.layer_dropdown.setCurrentIndex(0)
                return

            # --- Barangay Level: filter by group (existing behaviour) ---
            # Show/hide the Barangay filter row based on output level.
            is_ea = "ea" in self.output_dropdown.currentText().lower()
            self.label_9.setVisible(is_ea)
            self.bgy_dropdown.setVisible(is_ea)

            selected_group_name = self.group_dropdown.currentData()
            if not selected_group_name:
                return

            # Resolve the group from the project layer tree by name each time to
            # ensure we have a valid, up-to-date `QgsLayerTreeGroup` instance.
            root = QgsProject.instance().layerTreeRoot()
            selected_group = root.findGroup(selected_group_name)
            if selected_group is None:
                return

            # Populate the layer dropdown with layers in the selected group,
            # filtering by the current output level suffix.
            self.layer_dropdown.clear()
            layers = [layer for layer in selected_group.findLayers()]
            desired = '_ea' if self.output_dropdown.currentText() == self.tr('EA Level') else '_bgy'
            matching = []

            for layer in layers:
                layer_obj = layer.layer()
                name = layer_obj.name() if layer_obj is not None else layer.name()
                name_lower = name.lower()
                if name_lower.endswith("_special_ea"):
                    continue
                if not name_lower.endswith(desired):
                    continue
                layer_id = layer_obj.id() if layer_obj is not None else None
                self.layer_dropdown.addItem(name, layer_id)
                matching.append(layer)

            # auto-select first matching layer
            if matching:
                first_layer = matching[0].layer()
                first_name = first_layer.name() if first_layer is not None else matching[0].name()
                idx = self.layer_dropdown.findText(first_name)
                if idx != -1:
                    self.layer_dropdown.setCurrentIndex(idx)

            # Clear geocode dropdown
            self.geocode_dropdown.clear()
        finally:
            self.layer_dropdown.blockSignals(False)
            self.layer_dropdown.currentIndexChanged.emit(self.layer_dropdown.currentIndex())

    def populate_geocode_dropdown(self):
        """Populate the geocode dropdown based on the selected layer."""
        selected_layer = None
        selected_data = self.layer_dropdown.currentData()
        if isinstance(selected_data, str):
            selected_layer = QgsProject.instance().mapLayer(selected_data)

        # fallback by name
        if selected_layer is None and self.layer_dropdown.currentText():
            sel_name = self.layer_dropdown.currentText()
            for lyr in QgsProject.instance().mapLayers().values():
                try:
                    if lyr.name() == sel_name:
                        selected_layer = lyr
                        break
                except Exception:
                    continue

        self.geocode_dropdown.clear()
        desired = '_ea' if self.output_dropdown.currentText() == self.tr('EA Level') else '_bgy'
        is_ea = self.output_dropdown.currentText() == self.tr('EA Level')
        if selected_layer and selected_layer.name().endswith(desired):
            geocode_index = -1
            for fname in (['ea_geocode', 'geocode', 'ea_code', 'code'] if is_ea else ['geocode', 'bgy_code', 'ea_geocode', 'code']):
                idx = selected_layer.fields().indexOf(fname)
                if idx != -1:
                    geocode_index = idx
                    break
            geocode_name_index = selected_layer.fields().indexOf('barangay')
            if geocode_name_index == -1:
                geocode_name_index = selected_layer.fields().indexOf('Barangay')

            if geocode_index != -1 and geocode_name_index != -1:
                formatted_values = [
                    f"{feature.attributes()[geocode_index]}_{feature.attributes()[geocode_name_index]}"
                    for feature in selected_layer.getFeatures()
                ]
                self.geocode_dropdown.addItems(sorted(formatted_values))
                print(f"Geocode and names for layer: {selected_layer.name()}")
            else:
                missing_fields = []
                if geocode_index == -1:
                    missing_fields.append('ea_geocode or geocode')
                if geocode_name_index == -1:
                    missing_fields.append('barangay or Barangay')
                print(f"Missing field(s) {', '.join(missing_fields)} in layer: {selected_layer.name()}")
                QMessageBox.warning(self, "Missing Fields", f"Missing field(s): {', '.join(missing_fields)} in layer: {selected_layer.name()}")
                
    def populate_citymun_dropdown(self):
        """Populate the citymun dropdown based on the selected layer."""
        selected_layer = None
        selected_data = self.layer_dropdown.currentData()
        if isinstance(selected_data, str):
            selected_layer = QgsProject.instance().mapLayer(selected_data)

        # fallback by name
        if selected_layer is None and self.layer_dropdown.currentText():
            sel_name = self.layer_dropdown.currentText()
            for lyr in QgsProject.instance().mapLayers().values():
                try:
                    if lyr.name() == sel_name:
                        selected_layer = lyr
                        break
                except Exception:
                    continue

        self.citymun_dropdown.blockSignals(True)
        try:
            self.citymun_dropdown.clear()
            self.citymun_dropdown.addItem("All")

            desired = '_ea' if self.output_dropdown.currentText() == self.tr('EA Level') else '_bgy'
            is_ea = self.output_dropdown.currentText() == self.tr('EA Level')
            if selected_layer and selected_layer.name().endswith(desired):
                geocode_index = -1
                for fname in (['ea_geocode', 'geocode', 'ea_code', 'code'] if is_ea else ['geocode', 'bgy_code', 'ea_geocode', 'code']):
                    idx = selected_layer.fields().indexOf(fname)
                    if idx != -1:
                        geocode_index = idx
                        break
                geocode_name_index = selected_layer.fields().indexOf('city_mun')
                if geocode_name_index == -1:
                    geocode_name_index = selected_layer.fields().indexOf('City_mun')

                if geocode_index != -1 and geocode_name_index != -1:
                    formatted_values = set(
                        f"{str(feature.attributes()[geocode_index])[:5]}_{feature.attributes()[geocode_name_index]}"
                        for feature in selected_layer.getFeatures()
                    )
                    self.citymun_dropdown.addItems(sorted(formatted_values))
                    print(f"City/Municipality dropdown unique values: {formatted_values}")
                else:
                    missing_fields = []
                    if geocode_index == -1:
                        missing_fields.append('ea_geocode or geocode')
                    if geocode_name_index == -1:
                        missing_fields.append('city_mun or City_mun')
                    print(f"Missing field(s) {', '.join(missing_fields)} in layer: {selected_layer.name()}")
                    QMessageBox.warning(self, "Missing Fields", f"Missing field(s): {', '.join(missing_fields)} in layer: {selected_layer.name()}")
        finally:
            self.citymun_dropdown.blockSignals(False)

    def populate_bgy_dropdown(self):
        """Populate the barangay dropdown based on the selected layer.

        Values use the first eight digits of the geocode followed by the
        barangay name, separated by an underscore.  An "All" entry is added
        at the top to allow de‑selection.
        """
        selected_layer = None
        selected_data = self.layer_dropdown.currentData()
        if isinstance(selected_data, str):
            selected_layer = QgsProject.instance().mapLayer(selected_data)

        # fallback by name
        if selected_layer is None and self.layer_dropdown.currentText():
            sel_name = self.layer_dropdown.currentText()
            for lyr in QgsProject.instance().mapLayers().values():
                try:
                    if lyr.name() == sel_name:
                        selected_layer = lyr
                        break
                except Exception:
                    continue

        self.bgy_dropdown.blockSignals(True)
        try:
            self.bgy_dropdown.clear()
            self.bgy_dropdown.addItem("All")

            # Keep Barangay Level fixed to the default "All" entry only.
            if self.output_dropdown.currentText() != self.tr('EA Level'):
                self.bgy_dropdown.setCurrentIndex(0)
                return

            # EA level uses the _ea layer and follows the existing population logic.
            desired = '_ea' if self.output_dropdown.currentText() == self.tr('EA Level') else '_bgy'
            is_ea = self.output_dropdown.currentText() == self.tr('EA Level')

            # determine citymun filter prefix (first 5 digits) if one is selected
            citymun_text = self.citymun_dropdown.currentText()
            citymun_prefix = None
            if citymun_text and citymun_text.lower() != "all":
                citymun_prefix = citymun_text.split('_')[0]

            if selected_layer and selected_layer.name().endswith(desired):
                geocode_index = -1
                for fname in (['ea_geocode', 'geocode', 'ea_code', 'code'] if is_ea else ['geocode', 'bgy_code', 'ea_geocode', 'code']):
                    idx = selected_layer.fields().indexOf(fname)
                    if idx != -1:
                        geocode_index = idx
                        break
                barangay_index = selected_layer.fields().indexOf('barangay')
                if barangay_index == -1:
                    barangay_index = selected_layer.fields().indexOf('Barangay')

                if geocode_index != -1 and barangay_index != -1:
                    formatted_values = set()
                    for feature in selected_layer.getFeatures():
                        code = str(feature.attributes()[geocode_index])
                        if citymun_prefix and code[:5] != citymun_prefix:
                            continue
                        formatted_values.add(f"{code[:8]}_{feature.attributes()[barangay_index]}")

                    self.bgy_dropdown.addItems(sorted(formatted_values))
                    print(f"Barangay dropdown unique values: {formatted_values}")
                else:
                    missing_fields = []
                    if geocode_index == -1:
                        missing_fields.append('ea_geocode or geocode')
                    if barangay_index == -1:
                        missing_fields.append('barangay or Barangay')
                    print(f"Missing field(s) {', '.join(missing_fields)} in layer: {selected_layer.name()}")
                    QMessageBox.warning(self, "Missing Fields", f"Missing field(s): {', '.join(missing_fields)} in layer: {selected_layer.name()}")
        finally:
            self.bgy_dropdown.blockSignals(False)

        # no additional default handling needed; Barangay Level returns above.

    def filter_geocode_by_bgy(self):
        """Filter the geocode dropdown when a barangay value is selected."""
        selected_bgy = self.bgy_dropdown.currentText()
        if selected_bgy.lower() == "all":
            self.populate_geocode_dropdown()
            return
        bgy_prefix = selected_bgy.split('_')[0]

        # resolve the layer exactly like the other filter method
        selected_layer = None
        selected_data = self.layer_dropdown.currentData()
        if isinstance(selected_data, str):
            selected_layer = QgsProject.instance().mapLayer(selected_data)
        if selected_layer is None and self.layer_dropdown.currentText():
            sel_name = self.layer_dropdown.currentText()
            for lyr in QgsProject.instance().mapLayers().values():
                if lyr.name() == sel_name:
                    selected_layer = lyr
                    break

        self.geocode_dropdown.clear()
        desired = '_ea' if self.output_dropdown.currentText() == self.tr('EA Level') else '_bgy'
        is_ea = self.output_dropdown.currentText() == self.tr('EA Level')
        if selected_layer and selected_layer.name().endswith(desired):
            geocode_index = -1
            for fname in (['ea_geocode', 'geocode', 'ea_code', 'code'] if is_ea else ['geocode', 'bgy_code', 'ea_geocode', 'code']):
                idx = selected_layer.fields().indexOf(fname)
                if idx != -1:
                    geocode_index = idx
                    break
            geocode_name_index = selected_layer.fields().indexOf('barangay')
            if geocode_name_index == -1:
                geocode_name_index = selected_layer.fields().indexOf('Barangay')
            if geocode_index != -1 and geocode_name_index != -1:
                filtered_values = [
                    f"{feature.attributes()[geocode_index]}_{feature.attributes()[geocode_name_index]}"
                    for feature in selected_layer.getFeatures()
                    if str(feature.attributes()[geocode_index])[:8] == bgy_prefix
                ]
                self.geocode_dropdown.addItems(sorted(filtered_values))
                print(f"Filtered geocode values for barangay {selected_bgy}: {filtered_values}")
            else:
                print("Missing geocode or barangay field.")

    def select_by_location(self):
        # Get the layer named with the suffix '_road', '_block', '_river'
        input_layers = [
            layer for layer in QgsProject.instance().mapLayers().values()
            if layer.name().endswith(('_road', '_block', '_river'))
        ]
        
        # Get all layers that end with '_bgy'
        overlay_layers = [
            layer for layer in QgsProject.instance().mapLayers().values()
            if layer.name().endswith('_bgy')
        ]
        
        # Check if input_layers and overlay_layers are found
        if not input_layers:
            print("No input layers found with '_road', '_block', or '_river' suffix.")
            return
        
        if not overlay_layers:
            print("No overlay layers found with '_bgy' suffix.")
            return
        
        # Define the list of predicates
        predicates = [0]  # 'intersects', 'within', 'crosses', 'equals'

        # Run Select by Location for each input layer and each overlay layer with each predicate
        for input_layer in input_layers:
            for overlay_layer in overlay_layers:
                for predicate in predicates:
                    result = processing.run("qgis:selectbylocation", {
                        'INPUT': input_layer,
                        'PREDICATE': predicate,
                        'INTERSECT': overlay_layer,
                        'METHOD': 0  # 0 for "Create new selection"
                    })
                    print(f"Selection done for {input_layer.name()} with predicate: {predicate} and overlay: {overlay_layer.name()}")
                    
                    # Check if any features were selected
                    selected_count = input_layer.selectedFeatureCount()
                    print(f"Number of selected features in {input_layer.name()}: {selected_count}")
        
        print("Selection by location completed.")

    def reload_plugin(self, plugin_name):
        """Reload a specified QGIS plugin."""
        # Try to initially load the selected plugin if not loaded yet
        if plugin_name not in utils.plugins:
            try:
                utils.loadPlugin(plugin_name)
                utils.startPlugin(plugin_name)
                utils.updateAvailablePlugins()
                print(f"Plugin '{plugin_name}' loaded successfully.")
            except Exception as e:
                print(f"Failed to load plugin '{plugin_name}': {str(e)}")
                return
        
        try:
            # Unload the plugin
            utils.unloadPlugin(plugin_name)

            # Remove submodules left by qgis.utils.unloadPlugin
            for key in list(sys.modules.keys()):
                if plugin_name in key:
                    if hasattr(sys.modules[key], 'qCleanupResources'):
                        sys.modules[key].qCleanupResources()
                    del sys.modules[key]

            # Reload the plugin
            utils.loadPlugin(plugin_name)
            utils.startPlugin(plugin_name)
            print(f"Plugin '{plugin_name}' reloaded successfully.")

        except Exception as e:
            print(f"Failed to reload plugin '{plugin_name}': {str(e)}")
            QMessageBox.critical(None, "Error", f"Failed to reload plugin '{plugin_name}': {str(e)}")



    def auto_snap_layer(self):
        """
        Enables snapping for layers with names ending in _SF, _GP, or _bldgpts.
        Snapping is configured to snap to both vertices and segments with a tolerance of 10 pixels.
        """
        project = QgsProject.instance()
        snapping_config = project.snappingConfig()

        # Loop through all layers in the project
        for layer in project.mapLayers().values():
            layer_name = layer.name()
            if layer_name.endswith('_SF') or layer_name.endswith('_GP') or layer_name.endswith('_bldgpts'):
                # Create individual snapping settings for this layer
                settings = QgsSnappingConfig.IndividualLayerSettings()
                settings.setEnabled(True)
                # Set snapping mode to snap to both vertices and segments
                settings.setType(QgsSnappingConfig.Vertex)
                # Set the tolerance to 10 pixels (adjust if needed)
                settings.setTolerance(10)
                settings.setUnits(QgsTolerance.Pixels)

                # Apply these settings to the layer
                snapping_config.setIndividualLayerSettings(layer, settings)

        # Enable snapping for the project and update the project configuration
        snapping_config.setEnabled(True)
        project.setSnappingConfig(snapping_config)
        project.write()
        print("Auto-snapping configured for layers ending with _SF, _GP or _bldgpts.")

   
    def update_value_relations(self):
        """
        Automatically update ValueRelation widget configurations for all layers
        whose names end with '_SF' or '_GP' based on predefined mappings.
        """
        # Predefined mappings for source layers ending with _SF and _GP respectively
        mapping_sf = {
            "UPDT_1NAME": "SF_RefData",
            "UPDT_ADDRE": "SF_RefData",
            "UPDT_INSTY": "SF_RefData",
            "UPDT_SECTO": "SF_RefData",
            "UPDT_SPECT": "SF_RefData",
            "SPECTYPE": "2024 POPCEN-CBMS SF Specific Types",
            "OTHER_USE": "2024 POPCEN-CBMS SF Specific Types"
        }
        
        mapping_gp = {
            "UPDT_1NAME": "GP_RefData",
            "UPDT_ADDRE": "GP_RefData",
            "UPDT_SECTO": "GP_RefData",
            "UPDT_STATU": "GP_RefData",
            "UPDT_SDATE": "GP_RefData",
            "UPDT_CDATE": "GP_RefData",
            "UPDT_INSTY": "GP_RefData",
            "UPDT_FUND": "GP_RefData",
            "TYPE_OCCU": "BCCB", 
            "GP_INSFUND": "2024 POPCEN-CBMS GP Fund",
            "UPDT_BUDGE": "GP_RefData"
        }
        
        # Get all project layers
        project_layers = list(QgsProject.instance().mapLayers().values())
        
        # Create a lookup dictionary for project layers by name
        layers_by_name = {layer.name(): layer for layer in project_layers}
        
        processed_layer_count = 0

        # Iterate over each layer in the project
        for source_layer in project_layers:
            layer_name = source_layer.name()
            if not (layer_name.endswith("_SF") or layer_name.endswith("_GP")):
                continue  # Skip layers not ending with _SF or _GP
            
            # Select the appropriate mapping based on the layer's suffix
            current_mapping = mapping_sf if layer_name.endswith("_SF") else mapping_gp
            
            print(f"Processing layer: {layer_name}")
            
            # Iterate through the fields of the source layer
            for field in source_layer.fields():
                field_index = source_layer.fields().lookupField(field.name())
                widget_setup = source_layer.editorWidgetSetup(field_index)
                
                # Process only fields with a ValueRelation widget
                if widget_setup.type() != "ValueRelation":
                    continue
                
                # Update only if the field name exists in the mapping
                if field.name() in current_mapping:
                    desired_target_name = current_mapping[field.name()]
                    if desired_target_name in layers_by_name:
                        new_target_layer_id = layers_by_name[desired_target_name].id()
                    else:
                        print(f"  - Desired target layer '{desired_target_name}' not found in project for field '{field.name()}'.")
                        continue
                else:
                    continue
                
                # Update the widget configuration with the new target layer ID
                config = widget_setup.config()
                config["Layer"] = new_target_layer_id
                source_layer.setEditorWidgetSetup(field_index, widget_setup.__class__(widget_setup.type(), config))
                print(f"  - Updated field '{field.name()}' to target layer '{desired_target_name}'.")
            
            processed_layer_count += 1

        if processed_layer_count == 0:
            print("No layers with names ending with '_SF' or '_GP' were found.")
        else:
            print("All applicable ValueRelation fields updated for processed layers.")


    def set_read_only_for_selected_layers(self):
        project = QgsProject.instance()
        
        # Define target suffixes
        target_suffixes = ("_bldgpts", "_landmark", "_bgy", "_ea", "_block", "_road", "_river", "_river")

        modified = False  # Track if any changes were made

        for layer in project.mapLayers().values():
            name_lower = self._normalized_layer_name(layer.name()).lower()
            if name_lower.endswith("_special_ea"):
                continue
            if layer.name().endswith(target_suffixes) and isinstance(layer, QgsVectorLayer):  
                # Check if read-only is already set in project metadata
                key = f"ReadOnlyLayers/{layer.id()}"
                read_only_status, found = project.readEntry("ReadOnlyLayers", layer.id(), "False")

                if not found or read_only_status != "True":  # Only update if not already set
                    layer.setReadOnly(True)  # Set the layer as read-only
                    project.writeEntry("ReadOnlyLayers", layer.id(), "True")  # Store status
                    modified = True  # Mark project as modified
                    print(f"Set read-only: {layer.name()}")

        # Save project only if changes were made
        if modified:
            project.write()
            print("Project saved with updated read-only settings.")
        else:
            print("No changes needed. Read-only settings already applied.")

    def show_help(self):
        """Open the Package for QField documentation page in the system browser."""
        from qgis.PyQt.QtCore import QUrl
        from qgis.PyQt.QtGui import QDesktopServices

        QDesktopServices.openUrl(
            QUrl('https://gemma-plugin.vercel.app/tools/package-qfield.html')
        )


class RasterClipWorker(QThread):
    """Worker thread for raster clipping operations."""
    progress = pyqtSignal(int, int, str)  # total progress
    task_progress = pyqtSignal(int, int)  # task progress
    finished = pyqtSignal(bool, str)  # success status and message

    def __init__(self, raster_file, selected_layer, selected_geocode, parent_export_path, subfolder_path, code_digits):
        super().__init__()
        self.raster_file = raster_file
        self.selected_layer = selected_layer
        self.selected_geocode = selected_geocode
        self.parent_export_path = parent_export_path
        self.subfolder_path = subfolder_path
        self.code_digits = code_digits
        
    def run(self):
        try:
            self.progress.emit(0, 100, "Starting process...")
            self.task_progress.emit(0, 100)

            if not self.selected_geocode:
                self.finished.emit(False, "No geocode selected.")
                return

            self.progress.emit(10, 100, "Geocode selected")
            self.task_progress.emit(10, 100)

            if not self.raster_file or not os.path.exists(self.raster_file):
                self.finished.emit(False, "Invalid raster file selected.")
                return

            self.progress.emit(20, 100, "Raster file verified")
            self.task_progress.emit(20, 100)

            raster_layer = QgsRasterLayer(self.raster_file, os.path.basename(self.raster_file))
            if not raster_layer.isValid():
                self.finished.emit(False, "Failed to load the raster layer.")
                return

            self.progress.emit(30, 100, "Raster layer loaded")
            self.task_progress.emit(30, 100)

            if not isinstance(self.selected_layer, QgsVectorLayer):
                self.finished.emit(False, "Invalid vector layer.")
                return

            if self.selected_layer.featureCount() == 0:
                self.finished.emit(False, f"No boundary features found for area {self.selected_geocode}.")
                return

            self.progress.emit(40, 100, "Vector layer validated")
            self.task_progress.emit(40, 100)

            # Create buffer
            buffer_distance = 0.001000
            buffer_output = os.path.join(os.path.dirname(self.raster_file), "buffered_mask.gpkg")
            buffer_params = {
                'INPUT': self.selected_layer,
                'DISTANCE': buffer_distance,
                'SEGMENTS': 5,
                'DISSOLVE': True,
                'OUTPUT': buffer_output
            }
            
            try:
                buffer_result = processing.run("native:buffer", buffer_params)
                if not buffer_result or not os.path.exists(buffer_output):
                    self.finished.emit(False, "Failed to create buffer.")
                    return

                mask_chk = QgsVectorLayer(buffer_output, "mask_chk")
                if not mask_chk.isValid() or mask_chk.featureCount() == 0:
                    self.finished.emit(False, f"Mask layer contains 0 cutline features for geocode {self.selected_geocode}.")
                    return
            except Exception as e:
                self.finished.emit(False, f"Buffer creation error: {str(e)}")
                return

            self.progress.emit(60, 100, "Buffer created")
            self.task_progress.emit(60, 100)

            # Ensure parent output directory exists
            try:
                os.makedirs(self.parent_export_path, exist_ok=True)
            except Exception as e:
                self.finished.emit(False, f"Failed to create output directory: {str(e)}")
                return

            output_raster = os.path.join(self.parent_export_path, f"{self.code_digits}_img.tif")

            # Clip raster
            try:
                params = {
                    'INPUT': raster_layer,
                    'MASK': buffer_output,
                    'OUTPUT': output_raster
                }

                result = processing.run("gdal:cliprasterbymasklayer", params)
                
                if result and os.path.exists(output_raster):
                    # Build pyramids
                    self.progress.emit(90, 100, "Building pyramids...")
                    self.task_progress.emit(90, 100)
                    
                    pyramid_params = {
                        'INPUT': output_raster,
                        'FORMAT': 0,
                        'LEVELS': '8 16 32 64 128',
                        'RESAMPLING': None
                    }
                    processing.run("gdal:overviews", pyramid_params)
                    
                    self.progress.emit(100, 100, "Process complete")
                    self.task_progress.emit(100, 100)
                    self.finished.emit(True, output_raster)
                else:
                    self.finished.emit(False, "Failed to clip raster. Output file not created.")
            except Exception as e:
                self.finished.emit(False, f"Clip error: {str(e)}")

        except Exception as e:
            self.finished.emit(False, str(e))








