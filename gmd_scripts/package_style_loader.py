# -*- coding: utf-8 -*-
"""
Package Style Loader Dialog
GEMMA > Updating of Boundaries > Package Style Loader

A dedicated, professional dialog for organizing and applying official QML styles
(PSA, LGU, MBI Cases, Building Points, Barangay, etc.) to packaged municipal
boundary layers.
"""

import os
import re
from typing import Optional, List, Dict, Tuple

from qgis.PyQt.QtCore import Qt, QSize
from qgis.PyQt.QtGui import QIcon, QColor, QFont
from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QGroupBox,
    QCheckBox,
    QFileDialog,
    QMessageBox,
    QWidget,
    QLineEdit,
    QAbstractItemView,
    QFrame,
)
from qgis.core import (
    QgsProject,
    QgsMapLayer,
    QgsVectorLayer,
    QgsWkbTypes,
    QgsLayerTreeGroup,
    QgsLayerTreeLayer,
)

# Relative / absolute import fallback for style utilities
try:
    from ..references.package_qfield.utils.style_utils import (
        get_available_qml_display_names,
        get_qml_file_path,
        apply_qml_to_layer,
        auto_detect_qml_for_layer,
    )
except (ImportError, ValueError):
    try:
        from references.package_qfield.utils.style_utils import (
            get_available_qml_display_names,
            get_qml_file_path,
            apply_qml_to_layer,
            auto_detect_qml_for_layer,
        )
    except (ImportError, ValueError):
        def get_available_qml_display_names():
            return [
                "ref_province_lgu",
                "ref_province_psa",
                "ref_mbi_cases",
                "1. Base Layer Building Points",
                "5. Base Layer Barangay",
                "4. Base Layer EA",
                "7. Base Layer Road",
                "9. Base Layer River",
                "2. Base Layer Landmark",
            ]

        def get_qml_file_path(dname):
            return ""

        def apply_qml_to_layer(lyr, dname):
            return False

        def auto_detect_qml_for_layer(name, names=None):
            return ""


# -----------------------------------------------------------------------------
# Role and Style Auto-Detection Rules for Boundary Updating
# -----------------------------------------------------------------------------
ROLE_DEFINITIONS: List[Tuple[str, List[str], str]] = [
    (
        "LGU Boundary",
        ["_lgu", "ref_province_lgu", "province_lgu", "lgu"],
        "ref_province_lgu",
    ),
    (
        "PSA Boundary",
        ["_psa", "ref_province_psa", "province_psa", "psa"],
        "ref_province_psa",
    ),
    (
        "MBI Cases",
        ["_mbi_cases", "ref_mbi_cases", "mbi_cases", "ref_mbi"],
        "ref_mbi_cases",
    ),
    (
        "Building Points",
        ["_bldg_point", "bldg_points", "bldg_point", "bldgpts", "building points"],
        "1. Base Layer Building Points",
    ),
    (
        "Barangay Boundary",
        ["_bgy", "brgy", "barangay"],
        "5. Base Layer Barangay",
    ),
    (
        "Enumeration Area",
        ["_ea", "ea2024", "ea2026", "ea_boundary"],
        "4. Base Layer EA",
    ),
    (
        "Road Network",
        ["_road", "roads", "road"],
        "7. Base Layer Road",
    ),
    (
        "River / Water",
        ["_river", "rivers", "waterway"],
        "9. Base Layer River",
    ),
    (
        "Landmarks",
        ["_landmark", "landmarks", "landmark"],
        "2. Base Layer Landmark",
    ),
]


def detect_layer_role(layer_name: str) -> Tuple[str, str]:
    """
    Detect the operational boundary role and matching QML style for a given layer name.
    Returns (role_label, suggested_qml_name).
    """
    layer_lower = layer_name.lower().strip()

    for role_label, patterns, qml_name in ROLE_DEFINITIONS:
        for pattern in patterns:
            # Check suffix (e.g. ref_Bacacay_bldg_point ends with _bldg_point)
            if layer_lower.endswith(pattern) or layer_lower.endswith("_" + pattern):
                return role_label, qml_name
            # Check standalone or separated word
            if pattern in layer_lower and ("_" + pattern in layer_lower or pattern + "_" in layer_lower or layer_lower == pattern):
                return role_label, qml_name

    # Fallback to style_utils heuristic
    fallback_qml = auto_detect_qml_for_layer(layer_name)
    if fallback_qml:
        return "Boundary Layer", fallback_qml

    return "Other Layer", "(None)"


def get_layer_geom_type(layer: QgsMapLayer) -> Tuple[str, str]:
    """
    Return (type_code, display_name) for a layer.
    type_code in ('point', 'line', 'polygon', 'table', 'unknown')
    """
    if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
        return "unknown", "Unknown"

    geom_type = layer.geometryType()
    if geom_type == QgsWkbTypes.PointGeometry:
        return "point", "Point"
    elif geom_type == QgsWkbTypes.LineGeometry:
        return "line", "Line"
    elif geom_type == QgsWkbTypes.PolygonGeometry:
        return "polygon", "Polygon"
    elif geom_type == QgsWkbTypes.NullGeometry:
        return "table", "Table"
    return "unknown", "Other"


def get_layer_tree_priority(layer_name: str) -> int:
    """
    Returns an integer priority for ordering in the QGIS Layer Tree.
    Lower number = higher in the tree (drawn on top):
      0: Building Points (*_bldg_point, bldg_points, etc.)
      1: MBI Cases (*_mbi_cases, mbi_cases, etc.)
      2: PSA Boundary (*_psa, province_psa, etc.)
      3: LGU Boundary (*_lgu, province_lgu, etc.)
      4: Barangay Boundary (*_bgy, etc.)
      5: Enumeration Area (*_ea, etc.)
      6: Other linear/polygon features
      10: Background / other layers
    """
    name_lower = layer_name.lower().strip()

    # 1. Building Points (Topmost)
    if any(k in name_lower for k in ("bldg_point", "bldg_points", "bldgpts", "building points", "building_points")):
        return 0

    # 2. MBI Cases (Second)
    if any(k in name_lower for k in ("mbi_cases", "ref_mbi", "mbi")):
        return 1

    # 3. PSA Boundary
    if any(k in name_lower for k in ("_psa", "ref_province_psa", "province_psa", "psa")):
        return 2

    # 4. LGU Boundary
    if any(k in name_lower for k in ("_lgu", "ref_province_lgu", "province_lgu", "lgu")):
        return 3

    # 5. Other standard boundary layers
    if any(k in name_lower for k in ("_bgy", "brgy", "barangay")):
        return 4
    if any(k in name_lower for k in ("_ea", "ea2024", "ea2026")):
        return 5

    return 10


# Stylesheets for dropdowns to guarantee readable text on hover and selection
SCOPE_COMBO_STYLE = """
    QComboBox {
        background-color: white;
        color: #1E293B;
        font-weight: 500;
        padding: 4px 8px;
        border: 1px solid #CBD5E1;
        border-radius: 4px;
    }
    QComboBox:hover {
        border-color: #0284C7;
    }
    QComboBox QAbstractItemView {
        border: 1px solid #CBD5E1;
        background-color: white;
        color: #1E293B;
        selection-background-color: #0284C7;
        selection-color: white;
        outline: none;
    }
    QComboBox QAbstractItemView::item {
        min-height: 24px;
        padding: 4px 8px;
        color: #1E293B;
        background-color: white;
    }
    QComboBox QAbstractItemView::item:hover {
        background-color: #0284C7;
        color: white;
    }
    QComboBox QAbstractItemView::item:selected {
        background-color: #0284C7;
        color: white;
    }
"""

TABLE_COMBO_STYLE = """
    QComboBox {
        background-color: white;
        color: #1E293B;
        padding: 2px 6px;
        border: 1px solid #CBD5E1;
        border-radius: 3px;
    }
    QComboBox:hover {
        border-color: #0284C7;
    }
    QComboBox QAbstractItemView {
        border: 1px solid #CBD5E1;
        background-color: white;
        color: #1E293B;
        selection-background-color: #0284C7;
        selection-color: white;
        outline: none;
    }
    QComboBox QAbstractItemView::item {
        min-height: 22px;
        padding: 3px 6px;
        color: #1E293B;
        background-color: white;
    }
    QComboBox QAbstractItemView::item:hover {
        background-color: #0284C7;
        color: white;
    }
    QComboBox QAbstractItemView::item:selected {
        background-color: #0284C7;
        color: white;
    }
"""


# -----------------------------------------------------------------------------
# Main Package Style Loader Dialog
# -----------------------------------------------------------------------------
class PackageStyleLoaderDialog(QDialog):
    """
    Dedicated style loading dialog for municipal packaged layers.
    Features:
      - Scope selector (Packaged Layers, municipal groups, or all layers)
      - Structured layer-to-style mapping table with geometry icons & role tags
      - Pre-selected QML styles with live map preview capability
      - Custom QML external file picker
      - Automatic layer drawing-order reordering (Points > Lines > Polygons)
    """

    def __init__(self, parent: Optional[QWidget] = None, iface=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("Package Style Loader")
        self.setMinimumSize(820, 620)
        self.resize(860, 650)

        # Set window icon
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "icons",
            "package_style_loader.svg",
        )
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.available_qml_styles = ["(None)"] + get_available_qml_display_names()
        # Cache for custom loaded QML file paths: row -> file_path
        self.custom_qml_paths: Dict[int, str] = {}

        self._init_ui()
        self._populate_scope_combo()
        self._load_layers_for_current_scope()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # ---------------------------------------------------------------------
        # 1. Header Card Banner
        # ---------------------------------------------------------------------
        header_frame = QFrame()
        header_frame.setObjectName("headerFrame")
        header_frame.setStyleSheet("""
            QFrame#headerFrame {
                background-color: #F8F9FA;
                border: 1px solid #E2E8F0;
                border-radius: 6px;
                padding: 10px;
            }
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setSpacing(12)

        # Icon
        icon_label = QLabel()
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "icons",
            "package_style_loader.svg",
        )
        if os.path.exists(icon_path):
            icon_label.setPixmap(QIcon(icon_path).pixmap(40, 40))
        header_layout.addWidget(icon_label)

        # Text container
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_lbl = QLabel("Package Style Loader")
        title_lbl.setStyleSheet("font-size: 15pt; font-weight: bold; color: #1E293B;")
        desc_lbl = QLabel(
            "Batch-apply official PSA, LGU, MBI Cases, and Building Point styling to packaged boundary layers."
        )
        desc_lbl.setStyleSheet("font-size: 9.5pt; color: #64748B;")
        title_box.addWidget(title_lbl)
        title_box.addWidget(desc_lbl)
        header_layout.addLayout(title_box, 1)

        main_layout.addWidget(header_frame)

        # ---------------------------------------------------------------------
        # 2. Scope & Target Selection Section
        # ---------------------------------------------------------------------
        scope_group = QGroupBox("1. Target Layer Scope")
        scope_group.setStyleSheet("QGroupBox { font-weight: bold; color: #334155; }")
        scope_layout = QHBoxLayout(scope_group)
        scope_layout.setContentsMargins(12, 12, 12, 12)
        scope_layout.setSpacing(10)

        scope_lbl = QLabel("Scope / Group:")
        scope_lbl.setStyleSheet("font-weight: normal; color: #475569;")
        scope_layout.addWidget(scope_lbl)

        self.scope_combo = QComboBox()
        self.scope_combo.setMinimumWidth(260)
        self.scope_combo.setStyleSheet(SCOPE_COMBO_STYLE)
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        scope_layout.addWidget(self.scope_combo, 1)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setToolTip("Reload layers and groups from the active QGIS project")
        self.btn_refresh.clicked.connect(self._on_refresh_clicked)
        scope_layout.addWidget(self.btn_refresh)

        self.btn_auto_match = QPushButton("Auto-Match Styles")
        self.btn_auto_match.setToolTip("Automatically detect roles and assign matching QML styles")
        self.btn_auto_match.setStyleSheet("""
            QPushButton {
                background-color: #0284C7;
                color: white;
                font-weight: bold;
                padding: 5px 12px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #0369A1; }
        """)
        self.btn_auto_match.clicked.connect(self._on_auto_match_clicked)
        scope_layout.addWidget(self.btn_auto_match)

        main_layout.addWidget(scope_group)

        # ---------------------------------------------------------------------
        # 3. Layer & Style Mapping Table
        # ---------------------------------------------------------------------
        table_group = QGroupBox("2. Layer Style Mapping")
        table_group.setStyleSheet("QGroupBox { font-weight: bold; color: #334155; }")
        table_layout = QVBoxLayout(table_group)
        table_layout.setContentsMargins(12, 12, 12, 12)
        table_layout.setSpacing(8)

        # Search / Filter Bar
        filter_layout = QHBoxLayout()
        filter_lbl = QLabel("Search:")
        filter_lbl.setStyleSheet("font-weight: normal; color: #64748B;")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filter layers by name...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._filter_table)
        filter_layout.addWidget(filter_lbl)
        filter_layout.addWidget(self.search_edit, 1)

        btn_select_all = QPushButton("Select All")
        btn_select_all.clicked.connect(lambda: self._set_all_checks(True))
        btn_deselect_all = QPushButton("Deselect All")
        btn_deselect_all.clicked.connect(lambda: self._set_all_checks(False))
        btn_matched_only = QPushButton("Select Matched")
        btn_matched_only.setToolTip("Select only rows with a detected QML style")
        btn_matched_only.clicked.connect(self._select_matched_only)

        filter_layout.addWidget(btn_select_all)
        filter_layout.addWidget(btn_deselect_all)
        filter_layout.addWidget(btn_matched_only)
        table_layout.addLayout(filter_layout)

        # Table Widget
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Apply",
            "Layer Name",
            "Detected Role",
            "QML Style",
            "Custom",
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #CBD5E1;
                border-radius: 4px;
                background-color: white;
                gridline-color: #F1F5F9;
            }
            QHeaderView::section {
                background-color: #F8FAFC;
                color: #475569;
                font-weight: bold;
                padding: 6px;
                border: none;
                border-bottom: 1px solid #E2E8F0;
            }
        """)

        # Column sizing
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 50)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 50)

        table_layout.addWidget(self.table)

        # Table stats label
        self.lbl_table_stats = QLabel("0 layers loaded")
        self.lbl_table_stats.setStyleSheet("font-size: 9pt; color: #64748B;")
        table_layout.addWidget(self.lbl_table_stats)

        main_layout.addWidget(table_group, 1)

        # ---------------------------------------------------------------------
        # 4. Organization & Execution Options
        # ---------------------------------------------------------------------
        opts_group = QGroupBox("3. Layer Tree Organization")
        opts_group.setStyleSheet("QGroupBox { font-weight: bold; color: #334155; }")
        opts_layout = QHBoxLayout(opts_group)
        opts_layout.setContentsMargins(12, 10, 12, 10)
        opts_layout.setSpacing(16)

        self.chk_reorder = QCheckBox("Order layer tree: Building Points → MBI Cases → PSA / LGU Boundaries")
        self.chk_reorder.setChecked(True)
        self.chk_reorder.setToolTip(
            "Re-arranges layers in the QGIS Layer Tree to match official boundary updating hierarchy: "
            "Building Points (top) -> MBI Cases -> PSA / LGU Boundaries -> Other layers."
        )
        opts_layout.addWidget(self.chk_reorder)

        self.chk_visibility = QCheckBox("Turn on layer visibility")
        self.chk_visibility.setChecked(True)
        opts_layout.addWidget(self.chk_visibility)

        main_layout.addWidget(opts_group)

        # ---------------------------------------------------------------------
        # 5. Bottom Action Bar
        # ---------------------------------------------------------------------
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(12)

        self.lbl_status = QLabel("Ready")
        self.lbl_status.setStyleSheet("color: #475569; font-size: 9.5pt;")
        action_layout.addWidget(self.lbl_status, 1)

        self.btn_apply = QPushButton("Apply Package Styles")
        self.btn_apply.setStyleSheet("""
            QPushButton {
                background-color: #10B981;
                color: white;
                font-weight: bold;
                font-size: 10pt;
                padding: 8px 20px;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #059669; }
            QPushButton:disabled { background-color: #9CA3AF; }
        """)
        self.btn_apply.clicked.connect(self._on_apply_styles)
        action_layout.addWidget(self.btn_apply)

        btn_close = QPushButton("Close")
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #E2E8F0;
                color: #1E293B;
                font-weight: bold;
                padding: 8px 16px;
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #CBD5E1; }
        """)
        btn_close.clicked.connect(self.close)
        action_layout.addWidget(btn_close)

        main_layout.addLayout(action_layout)

    # -------------------------------------------------------------------------
    # Scope Population & Layer Fetching
    # -------------------------------------------------------------------------
    def _populate_scope_combo(self):
        """Scan QgsProject for layer groups and populate the Scope dropdown."""
        self.scope_combo.blockSignals(True)
        self.scope_combo.clear()

        self.scope_combo.addItem("All Project Layers", "all")

        root = QgsProject.instance().layerTreeRoot()
        packaged_idx = -1

        def collect_groups(parent_group, prefix=""):
            nonlocal packaged_idx
            for child in parent_group.children():
                if isinstance(child, QgsLayerTreeGroup):
                    display_text = f"{prefix}{child.name()}"
                    self.scope_combo.addItem(display_text, child.name())
                    if child.name() == "Packaged Layers" and packaged_idx == -1:
                        packaged_idx = self.scope_combo.count() - 1
                    collect_groups(child, prefix=prefix + "  ↳ ")

        collect_groups(root)

        # Default to "Packaged Layers" if present, else first child group or all
        if packaged_idx != -1:
            self.scope_combo.setCurrentIndex(packaged_idx)
        elif self.scope_combo.count() > 1:
            self.scope_combo.setCurrentIndex(1)
        else:
            self.scope_combo.setCurrentIndex(0)

        self.scope_combo.blockSignals(False)

    def _get_layers_for_scope(self, scope_val: str) -> List[QgsMapLayer]:
        """Collect map layers belonging to the selected scope."""
        if scope_val == "all":
            return list(QgsProject.instance().mapLayers().values())

        root = QgsProject.instance().layerTreeRoot()
        target_group = root.findGroup(scope_val)
        if not target_group:
            return []

        layers = []
        for child in target_group.findLayers():
            lyr = child.layer()
            if lyr is not None and lyr.isValid():
                layers.append(lyr)
        return layers

    def _on_scope_changed(self):
        self._load_layers_for_current_scope()

    def _on_refresh_clicked(self):
        cur_scope = self.scope_combo.currentData()
        self._populate_scope_combo()
        # Restore scope if possible
        idx = self.scope_combo.findData(cur_scope)
        if idx != -1:
            self.scope_combo.setCurrentIndex(idx)
        self._load_layers_for_current_scope()
        self.lbl_status.setText("Layer scope refreshed.")

    # -------------------------------------------------------------------------
    # Table Population & Auto-Detection
    # -------------------------------------------------------------------------
    def _load_layers_for_current_scope(self):
        """Populate the mapping table with layers matching the selected scope."""
        scope_val = self.scope_combo.currentData() or "all"
        layers = self._get_layers_for_scope(scope_val)

        # Filter only vector layers and sort by tree priority: Building Points -> MBI Cases -> PSA / LGU -> Others
        vector_layers = [lyr for lyr in layers if isinstance(lyr, QgsVectorLayer)]
        vector_layers.sort(key=lambda lyr: (get_layer_tree_priority(lyr.name()), lyr.name().lower()))

        self.table.setRowCount(len(vector_layers))
        self.custom_qml_paths.clear()

        matched_count = 0

        for row, lyr in enumerate(vector_layers):
            layer_name = lyr.name()
            geom_code, geom_name = get_layer_geom_type(lyr)
            detected_role, suggested_qml = detect_layer_role(layer_name)

            is_matched = suggested_qml != "(None)"
            if is_matched:
                matched_count += 1

            # Col 0: Checkbox
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            chk_item.setCheckState(Qt.Checked if is_matched else Qt.Unchecked)
            chk_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, chk_item)

            # Col 1: Layer Name
            name_item = QTableWidgetItem(layer_name)
            name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            name_item.setData(Qt.UserRole, lyr.id())
            name_item.setData(Qt.UserRole + 1, layer_name)
            name_item.setData(Qt.UserRole + 2, geom_code)
            self.table.setItem(row, 1, name_item)

            # Col 2: Detected Role (Styled Label)
            role_item = QTableWidgetItem(detected_role)
            role_item.setFlags(Qt.ItemIsEnabled)
            role_item.setTextAlignment(Qt.AlignCenter)
            if detected_role == "LGU Boundary":
                role_item.setForeground(QColor("#0284C7"))
            elif detected_role == "PSA Boundary":
                role_item.setForeground(QColor("#0D9488"))
            elif detected_role == "MBI Cases":
                role_item.setForeground(QColor("#D97706"))
            elif detected_role == "Building Points":
                role_item.setForeground(QColor("#DC2626"))
            elif detected_role == "Barangay Boundary":
                role_item.setForeground(QColor("#7C3AED"))
            self.table.setItem(row, 2, role_item)

            # Col 3: QML Style Dropdown
            combo = QComboBox()
            combo.addItems(self.available_qml_styles)
            combo.setStyleSheet(TABLE_COMBO_STYLE)

            if suggested_qml in self.available_qml_styles:
                combo.setCurrentText(suggested_qml)
            else:
                combo.setCurrentText("(None)")

            self.table.setCellWidget(row, 3, combo)

            # Col 4: Browse Custom QML Button
            btn_browse = QPushButton("...")
            btn_browse.setToolTip("Select custom external .qml style")
            btn_browse.setMaximumWidth(36)
            btn_browse.setStyleSheet("padding: 2px; font-weight: bold;")
            btn_browse.clicked.connect(lambda checked, r=row: self._browse_custom_qml(r))
            self.table.setCellWidget(row, 4, btn_browse)

        total_count = len(vector_layers)
        self.lbl_table_stats.setText(
            f"{total_count} layers in scope | {matched_count} auto-matched with styles"
        )
        self.lbl_status.setText(
            f"Ready: {matched_count} of {total_count} layers ready for styling."
        )

    def _browse_custom_qml(self, row: int):
        """Open a file dialog to assign a custom external .qml file to the row."""
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Select Custom QML Style",
            "",
            "QGIS Layer Style (*.qml);;All Files (*.*)",
        )
        if filepath and os.path.isfile(filepath):
            self.custom_qml_paths[row] = filepath
            display_name = os.path.splitext(os.path.basename(filepath))[0] + " (Custom)"

            combo = self.table.cellWidget(row, 3)
            if isinstance(combo, QComboBox):
                if combo.findText(display_name) == -1:
                    combo.addItem(display_name)
                combo.setCurrentText(display_name)

            chk = self.table.item(row, 0)
            if chk:
                chk.setCheckState(Qt.Checked)

            self.lbl_status.setText(f"Assigned custom style: {os.path.basename(filepath)}")

    def _on_auto_match_clicked(self):
        """Re-scan all rows in the table and match layer name suffixes against rules."""
        matched_count = 0
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 1)
            if not name_item:
                continue
            layer_name = name_item.data(Qt.UserRole + 1) or ""
            detected_role, suggested_qml = detect_layer_role(layer_name)

            # Update role cell
            role_item = self.table.item(row, 2)
            if role_item:
                role_item.setText(detected_role)

            # Update QML combo
            combo = self.table.cellWidget(row, 3)
            if isinstance(combo, QComboBox):
                if suggested_qml in self.available_qml_styles:
                    combo.setCurrentText(suggested_qml)
                    matched_count += 1
                else:
                    combo.setCurrentText("(None)")

            # Check if matched
            chk = self.table.item(row, 0)
            if chk:
                chk.setCheckState(Qt.Checked if suggested_qml != "(None)" else Qt.Unchecked)

        self.lbl_status.setText(f"Auto-match completed: {matched_count} styles assigned.")

    def _filter_table(self, text: str):
        """Filter rows in the table matching the search text."""
        search = text.strip().lower()
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 1)
            role_item = self.table.item(row, 2)
            layer_name = (name_item.data(Qt.UserRole + 1) if name_item else "").lower()
            role_text = (role_item.text() if role_item else "").lower()

            match = search in layer_name or search in role_text
            self.table.setRowHidden(row, not match)

    def _set_all_checks(self, checked: bool):
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                chk = self.table.item(row, 0)
                if chk:
                    chk.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _select_matched_only(self):
        for row in range(self.table.rowCount()):
            combo = self.table.cellWidget(row, 3)
            qml_val = combo.currentText() if isinstance(combo, QComboBox) else ""
            has_match = bool(qml_val and qml_val != "(None)")
            chk = self.table.item(row, 0)
            if chk:
                chk.setCheckState(Qt.Checked if has_match else Qt.Unchecked)

    # -------------------------------------------------------------------------
    # Apply Package Styles Execution
    # -------------------------------------------------------------------------
    def _on_apply_styles(self):
        """Apply the selected QML styles to checked layers and reorder if requested."""
        selected_rows = []
        for row in range(self.table.rowCount()):
            chk = self.table.item(row, 0)
            if chk and chk.checkState() == Qt.Checked:
                selected_rows.append(row)

        if not selected_rows:
            QMessageBox.information(
                self,
                "No Selection",
                "Please check at least one layer to apply styles.",
            )
            return

        applied_count = 0
        error_count = 0
        project = QgsProject.instance()

        self.btn_apply.setEnabled(False)
        self.lbl_status.setText("Applying styles to layers...")

        styled_layers: List[Tuple[QgsMapLayer, str]] = []

        for row in selected_rows:
            name_item = self.table.item(row, 1)
            if not name_item:
                continue

            layer_id = name_item.data(Qt.UserRole)
            layer = project.mapLayer(layer_id)
            if not layer or not layer.isValid():
                error_count += 1
                continue

            combo = self.table.cellWidget(row, 3)
            style_name = combo.currentText() if isinstance(combo, QComboBox) else ""

            # Check if custom file was selected for this row
            custom_path = self.custom_qml_paths.get(row, "")
            success = False

            if custom_path and os.path.isfile(custom_path):
                try:
                    res = layer.loadNamedStyle(custom_path)
                    if isinstance(res, tuple):
                        success = bool(res[1])
                    elif isinstance(res, bool):
                        success = res
                    layer.triggerRepaint()
                except Exception as e:
                    print(f"Error applying custom QML: {e}")
                    success = False
            elif style_name and style_name != "(None)":
                success = apply_qml_to_layer(layer, style_name)

            if success:
                applied_count += 1
                geom_code = name_item.data(Qt.UserRole + 2) or "unknown"
                styled_layers.append((layer, geom_code))
                if self.chk_visibility.isChecked():
                    layer_node = project.layerTreeRoot().findLayer(layer.id())
                    if layer_node:
                        layer_node.setItemVisibilityChecked(True)
            else:
                if style_name != "(None)":
                    error_count += 1

        # Reorder layers by priority if requested: Building Points -> MBI Cases -> PSA / LGU
        if self.chk_reorder.isChecked() and styled_layers:
            self._reorder_layers_by_priority(styled_layers)

        # Refresh map canvas
        if self.iface and hasattr(self.iface, "mapCanvas"):
            self.iface.mapCanvas().refresh()

        self.btn_apply.setEnabled(True)
        summary_msg = f"Applied styles to {applied_count} layer(s)."
        if error_count > 0:
            summary_msg += f" ({error_count} style(s) failed to load)"
        self.lbl_status.setText(summary_msg)

        QMessageBox.information(
            self,
            "Styles Applied",
            f"Successfully applied styles to {applied_count} layer(s)!\n\n"
            + ("Layers organized: Building Points → MBI Cases → PSA / LGU." if self.chk_reorder.isChecked() else ""),
        )

    def _reorder_layers_by_priority(self, styled_layers: List[Tuple[QgsMapLayer, str]]):
        """
        Reorder styled layers inside their parent group to match official hierarchy:
        Building Points (top) -> MBI Cases -> PSA / LGU Boundaries -> Other layers.
        """
        root = QgsProject.instance().layerTreeRoot()

        # Find unique parent groups of styled layers
        parent_groups: Dict[str, QgsLayerTreeGroup] = {}
        for layer, _ in styled_layers:
            tree_layer = root.findLayer(layer.id())
            if tree_layer:
                parent = tree_layer.parent()
                if isinstance(parent, QgsLayerTreeGroup):
                    parent_groups[parent.name()] = parent

        # Fallback to root if layers are at root level
        if not parent_groups:
            parent_groups["root"] = root

        # Reorder within each parent group
        for group in parent_groups.values():
            child_layers = []
            for child in group.children():
                if isinstance(child, QgsLayerTreeLayer):
                    lyr = child.layer()
                    if lyr is not None:
                        prio = get_layer_tree_priority(lyr.name())
                        child_layers.append((child, prio, lyr.name().lower()))

            if len(child_layers) > 1:
                # Sort children: lowest priority number first (Building Points -> MBI Cases -> PSA / LGU)
                child_layers.sort(key=lambda x: (x[1], x[2]))
                for idx, (child_node, _, _) in enumerate(child_layers):
                    cloned = child_node.clone()
                    group.insertChildNode(idx, cloned)
                    group.removeChildNode(child_node)


# -----------------------------------------------------------------------------
# Public Dialog Launcher
# -----------------------------------------------------------------------------
def show_package_style_loader_dialog(iface=None) -> PackageStyleLoaderDialog:
    """Instantiate and present the Package Style Loader dialog."""
    parent = iface.mainWindow() if iface else None
    dlg = PackageStyleLoaderDialog(parent=parent, iface=iface)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg
