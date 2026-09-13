
from typing import Any, Optional

from PyQt5.QtCore import QVariant, Qt
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSizePolicy,
    QCheckBox,
    QTabWidget,
)
from PyQt5.QtGui import QFont, QColor
from processing.gui.wrappers import WidgetWrapper


class TablePreviewWidgetWrapper(WidgetWrapper):
    """
    Custom widget wrapper that renders a live, color-coded QTabWidget preview
    of the EAs that are candidates for delineation and merging,
    updating dynamically before the algorithm is run.
    """

    def __init__(self, *args, **kwargs):
        self.container = None
        self.header_label = None
        self.stats_label = None
        self.tabs = None
        self.delineation_table = None
        self.merge_table = None
        self.refresh_btn = None
        
        self.prev_ea_input_wrapper = None
        self.ea_id_field_wrapper = None
        self.household_field_wrapper = None
        self.min_household_wrapper = None
        self.max_household_wrapper = None
        self.gap_input_wrapper = None
        self.overlap_input_wrapper = None
        super().__init__(*args, **kwargs)

    def createWidget(self):
        self.container = QWidget()
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(0, 5, 0, 5)
        layout.setSpacing(6)
        
        header_layout = QHBoxLayout()
        self.header_label = QLabel("Candidates Preview (Before Running)")
        header_font = QFont("Segoe UI", 10, QFont.Bold)
        self.header_label.setFont(header_font)
        self.header_label.setStyleSheet("color: #1f6feb; margin-top: 10px;")
        header_layout.addWidget(self.header_label)
        header_layout.addStretch()
        
        self.toggle_checkbox = QCheckBox("Show Preview Table")
        self.toggle_checkbox.setChecked(False)
        self.toggle_checkbox.setStyleSheet("""
            QCheckBox {
                color: #24292f;
                font-weight: bold;
                font-size: 11px;
                margin-top: 10px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
        """)
        self.toggle_checkbox.stateChanged.connect(self.on_toggle_changed)
        header_layout.addWidget(self.toggle_checkbox)
        layout.addLayout(header_layout)
        
        self.stats_label = QLabel("Please configure all input parameters to generate a preview.")
        self.stats_label.setStyleSheet("color: #555; font-style: italic;")
        self.stats_label.setWordWrap(True)
        layout.addWidget(self.stats_label)
        
        # Instantiate Tab Widget
        self.tabs = QTabWidget()
        
        # Table 1: Delineation Table
        self.delineation_table = QTableWidget()
        self.delineation_table.setColumnCount(4)
        self.delineation_table.setHorizontalHeaderLabels([
            "Geocode", "Barangay", "EA Name", "Household Count"
        ])
        delin_hdr = self.delineation_table.horizontalHeader()
        delin_hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        delin_hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        delin_hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        delin_hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.delineation_table.verticalHeader().setVisible(False)
        self.delineation_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.delineation_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.delineation_table.setAlternatingRowColors(True)
        self.delineation_table.setMinimumHeight(150)
        self.delineation_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Table 2: Merge Table
        self.merge_table = QTableWidget()
        self.merge_table.setColumnCount(4)
        self.merge_table.setHorizontalHeaderLabels([
            "Geocode", "Barangay", "EA Name", "Household Count"
        ])
        merge_hdr = self.merge_table.horizontalHeader()
        merge_hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        merge_hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        merge_hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        merge_hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.merge_table.verticalHeader().setVisible(False)
        self.merge_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.merge_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.merge_table.setAlternatingRowColors(True)
        self.merge_table.setMinimumHeight(150)
        self.merge_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        table_style = """
            QTableWidget {
                background-color: #ffffff;
                alternate-background-color: #f7f9fc;
                border: 1px solid #dcdcdc;
                gridline-color: #e8e8e8;
                border-radius: 4px;
            }
            QHeaderView::section {
                background-color: #f0f4f8;
                padding: 6px;
                border: 1px solid #e0e0e0;
                font-weight: bold;
                color: #333333;
            }
        """
        self.delineation_table.setStyleSheet(table_style)
        self.merge_table.setStyleSheet(table_style)
        
        # Apply tab widget styling (makes it look clean, flat and premium)
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #dcdcdc;
                background: white;
                border-radius: 4px;
            }
            QTabBar::tab {
                background: #f0f4f8;
                border: 1px solid #dcdcdc;
                border-bottom-color: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
                color: #555555;
            }
            QTabBar::tab:selected, QTabBar::tab:hover {
                background: white;
                color: #1f6feb;
                border-bottom-color: white;
            }
        """)
        
        self.tabs.addTab(self.delineation_table, "Delineation")
        self.tabs.addTab(self.merge_table, "Merging")
        
        layout.addWidget(self.tabs)
        
        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh Preview")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                color: white;
                border: none;
                padding: 6px 12px;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2ea043;
            }
            QPushButton:pressed {
                background-color: #1f7730;
            }
        """)
        self.refresh_btn.clicked.connect(self.generate_preview)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # Initially hide elements until checkbox is checked
        self.tabs.setVisible(False)
        self.stats_label.setVisible(False)
        self.refresh_btn.setVisible(False)
        
        return self.container

    def on_toggle_changed(self, state):
        is_checked = (state == Qt.Checked)
        self.tabs.setVisible(is_checked)
        self.stats_label.setVisible(is_checked)
        self.refresh_btn.setVisible(is_checked)
        if is_checked:
            self.generate_preview()

    def postInitialize(self, wrappers):
        super().postInitialize(wrappers)
        for w in wrappers:
            name = w.parameterDefinition().name()
            if name == "PREVIOUS_EA_INPUT":
                self.prev_ea_input_wrapper = w
            elif name == "EA_ID_FIELD":
                self.ea_id_field_wrapper = w
            elif name == "HOUSEHOLD_FIELD":
                self.household_field_wrapper = w
            elif name == "MIN_HOUSEHOLD":
                self.min_household_wrapper = w
            elif name == "MAX_HOUSEHOLD":
                self.max_household_wrapper = w
            elif name == "GAP_INPUT":
                self.gap_input_wrapper = w
            elif name == "OVERLAP_INPUT":
                self.overlap_input_wrapper = w

        for w in [self.prev_ea_input_wrapper, self.ea_id_field_wrapper,
                  self.household_field_wrapper, self.min_household_wrapper,
                  self.max_household_wrapper, self.gap_input_wrapper, self.overlap_input_wrapper]:
            if w:
                try:
                    w.widgetValueHasChanged.connect(self.trigger_auto_refresh)
                except Exception:
                    pass
        self.trigger_auto_refresh()

    def trigger_auto_refresh(self, *args, **kwargs):
        try:
            self.generate_preview()
        except Exception:
            pass

    def _get_wrapper_value(self, wrapper):
        if not wrapper:
            return ""
        if hasattr(wrapper, "value"):
            try:
                val = wrapper.value()
                if val is not None:
                    return val
            except Exception:
                pass
        if hasattr(wrapper, "parameterValue"):
            try:
                val = wrapper.parameterValue()
                if val is not None:
                    return val
            except Exception:
                pass
        return ""

    def _get_selected_layer(self, wrapper):
        if not wrapper:
            return None
        layer_val = self._get_wrapper_value(wrapper)
        if not layer_val:
            return None
        from qgis.core import QgsProject, QgsVectorLayer
        import os
        layer = QgsProject.instance().mapLayer(str(layer_val))
        if not layer or not layer.isValid():
            if os.path.exists(str(layer_val)):
                layer = QgsVectorLayer(str(layer_val), "temp_preview", "ogr")
        return layer if (layer and layer.isValid()) else None

    def _get_ea_name(self, feat, ean_str, fields):
        ea_fields = ["ea_name", "ea_no", "eano", "ea_number", "eaname"]
        for name in ea_fields:
            idx = fields.indexOf(name)
            if idx == -1:
                for i in range(fields.count()):
                    if fields.at(i).name().lower() == name:
                        idx = i
                        break
            if idx != -1:
                val = feat.attribute(idx)
                if val is not None:
                    val_str = str(val).strip()
                    if val_str.endswith(".0"):
                        val_str = val_str[:-2]
                    if val_str:
                        if not val_str.upper().startswith("EA "):
                            return f"EA {val_str}"
                        return val_str
        if ean_str:
            if len(ean_str) >= 6 and ean_str[-6:].isdigit():
                return f"EA {ean_str[-6:]}"
            elif len(ean_str) >= 3 and ean_str[-3:].isdigit():
                return f"EA {ean_str[-3:]}"
            else:
                return f"EA {ean_str}"
        return "EA Unknown"

    def generate_preview(self):
        if not self.delineation_table or not self.merge_table:
            return
        if hasattr(self, "toggle_checkbox") and not self.toggle_checkbox.isChecked():
            return
            
        self.delineation_table.setRowCount(0)
        self.merge_table.setRowCount(0)
        
        prev_ea_layer = self._get_selected_layer(self.prev_ea_input_wrapper)
        
        try:
            min_hh = float(self._get_wrapper_value(self.min_household_wrapper) or 100)
        except Exception:
            min_hh = 100.0
            
        try:
            max_hh = float(self._get_wrapper_value(self.max_household_wrapper) or 300)
        except Exception:
            max_hh = 300.0
            
        if not prev_ea_layer:
            self.stats_label.setText("<i>Previous EA Layer is not selected.</i>")
            self.stats_label.setStyleSheet("color: #777; font-style: italic;")
            return

        fields = prev_ea_layer.fields()
        
        # Resolve household field index case-insensitively with hh_count taking priority
        hh_idx = -1
        for candidate in ["hh_count", "new_hhcount", "hhcount", "household", "household_count", "pop", "population"]:
            for i in range(fields.count()):
                if fields.at(i).name().lower() == candidate:
                    hh_idx = i
                    break
            if hh_idx != -1:
                break
                
        # Resolve EA ID field index case-insensitively
        ean_idx = -1
        for i in range(fields.count()):
            name_lower = fields.at(i).name().lower()
            if name_lower in ["ean", "new_ean", "ea_number", "ea_code", "id", "geocode"]:
                ean_idx = i
                break

        # Resolve Barangay name field index case-insensitively
        bgy_name_idx = -1
        for i in range(fields.count()):
            name_lower = fields.at(i).name().lower()
            if name_lower in ["barangay", "bgy", "brgy", "barangay_name", "bgy_name", "brgy_name", "barangay_n", "bgy_n", "brgy_n"]:
                bgy_name_idx = i
                break
        
        # Resolve eadel_indi and merge_indi field indices
        eadel_indi_idx = -1
        merge_indi_idx = -1
        for i in range(fields.count()):
            name_lower = fields.at(i).name().lower()
            if name_lower in ("eadel_indi", "indicator"):
                eadel_indi_idx = i
            elif name_lower == "merge_indi":
                merge_indi_idx = i

        if hh_idx == -1:
            self.stats_label.setText("Field 'hhcount' or 'household' not found in Previous EA layer.")
            self.stats_label.setStyleSheet("color: #d32f2f; font-weight: bold;")
            return
        if ean_idx == -1:
            self.stats_label.setText("Field 'ean' or 'ea_number' not found in Previous EA layer.")
            self.stats_label.setStyleSheet("color: #d32f2f; font-weight: bold;")
            return

        from qgis.core import QgsSpatialIndex
        
        # Build candidate lookup
        delineation_candidates = []
        merge_candidates = []

        temp_ea_index = QgsSpatialIndex()
        temp_ea_by_id = {}

        for feat in prev_ea_layer.getFeatures():
            ean_val = feat.attribute(ean_idx)
            ean_str = str(ean_val).strip() if ean_val is not None else ""
            if ean_str.endswith(".0"):
                ean_str = ean_str[:-2]

            ea_name_str = self._get_ea_name(feat, ean_str, fields)

            bgy_name_val = feat.attribute(bgy_name_idx) if bgy_name_idx != -1 else ""
            if bgy_name_val is None or (isinstance(bgy_name_val, QVariant) and bgy_name_val.isNull()):
                bgy_name_str = "Unknown"
            else:
                bgy_name_str = str(bgy_name_val).strip()
                if bgy_name_str.endswith(".0"):
                    bgy_name_str = bgy_name_str[:-2]

            hh_val = feat.attribute(hh_idx)
            try:
                hh = float(hh_val) if hh_val is not None else 0.0
            except Exception:
                hh = 0.0

            # Classify by hhcount thresholds & explicit indicators (strictly above max threshold)
            is_delin = (hh > max_hh)
            if not is_delin and eadel_indi_idx != -1:
                val = feat.attribute(eadel_indi_idx)
                if val is not None and str(val).strip().lower() in ("for delineation", "for_delineation"):
                    if hh > max_hh:
                        is_delin = True

            is_merge = False
            if not is_delin and merge_indi_idx != -1:
                val = feat.attribute(merge_indi_idx)
                if val is not None and str(val).strip().lower() in ("for merging", "for_merging"):
                    is_merge = True

            if not is_delin and not is_merge:
                is_merge = (hh <= min_hh)

            if is_delin:
                delineation_candidates.append((ean_str, ea_name_str, bgy_name_str, hh, feat))
                temp_ea_index.addFeature(feat)
                temp_ea_by_id[feat.id()] = (ean_str, ea_name_str, bgy_name_str, hh, feat)
            elif is_merge:
                merge_candidates.append((ean_str, ea_name_str, bgy_name_str, hh, feat))
                temp_ea_index.addFeature(feat)
                temp_ea_by_id[feat.id()] = (ean_str, ea_name_str, bgy_name_str, hh, feat)

        # 1. Populate Delineation Table
        show_delin = delineation_candidates[:15]
        self.delineation_table.setRowCount(len(show_delin))
        for row_idx, (ean_str, ea_name_str, bgy_name_str, hh, feat) in enumerate(show_delin):
            item_ean = QTableWidgetItem(ean_str)
            item_name = QTableWidgetItem(ea_name_str)
            item_bgy = QTableWidgetItem(bgy_name_str)
            item_hh = QTableWidgetItem(f"{hh:.0f}")
            
            item_ean.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            item_name.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            item_bgy.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            item_hh.setTextAlignment(Qt.AlignCenter)
            
            for item in [item_ean, item_name, item_bgy, item_hh]:
                item.setBackground(QColor("#fff5f5"))
            item_ean.setForeground(QColor("#cb2431"))
            
            self.delineation_table.setItem(row_idx, 0, item_ean)
            self.delineation_table.setItem(row_idx, 1, item_bgy)
            self.delineation_table.setItem(row_idx, 2, item_name)
            self.delineation_table.setItem(row_idx, 3, item_hh)

        # 2. Populate Merge Table
        show_merge = merge_candidates[:15]
        self.merge_table.setRowCount(len(show_merge))
        for row_idx, (ean_str, ea_name_str, bgy_name_str, hh, feat) in enumerate(show_merge):
            item_ean = QTableWidgetItem(ean_str)
            item_bgy = QTableWidgetItem(bgy_name_str)
            item_name = QTableWidgetItem(ea_name_str)
            item_hh = QTableWidgetItem(f"{hh:.0f}")
            
            item_ean.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            item_bgy.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            item_name.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            item_hh.setTextAlignment(Qt.AlignCenter)
            
            for item in [item_ean, item_bgy, item_name, item_hh]:
                item.setBackground(QColor("#f0fff4"))
            item_ean.setForeground(QColor("#22863a"))
            
            self.merge_table.setItem(row_idx, 0, item_ean)
            self.merge_table.setItem(row_idx, 1, item_bgy)
            self.merge_table.setItem(row_idx, 2, item_name)
            self.merge_table.setItem(row_idx, 3, item_hh)

        stats_text = (
            f"<b>Candidates Summary:</b> Found <b>{len(delineation_candidates)}</b> delineation candidate(s) "
            f"and <b>{len(merge_candidates)}</b> merge candidate(s) in Previous EA Layer. "
            f"Showing preview of first 15 records per sheet."
        )
        self.stats_label.setText(stats_text)
        self.stats_label.setStyleSheet("color: #0366d6; font-weight: bold; font-size: 11px;")

    def value(self):
        return "preview"

    def setValue(self, value):
        pass
