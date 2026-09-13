# -*- coding: utf-8 -*-
"""
Split EA Dialog
----------------
Modal pop-up panel for splitting EA polygons (delineation_ea) using proposed cut lines (eadel_update).
Directly updates the selected polygon layer in-place with the split features,
and recalculates 'hh_count' (from est_hhcount of building points) and 'bldg_count' within each split polygon.
"""

import os
import math
from typing import Optional, Dict, Any, List, Tuple

from qgis.PyQt.QtCore import Qt, QObject, pyqtSignal, QVariant
from qgis.PyQt.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QProgressBar,
    QTextEdit,
    QDoubleSpinBox,
    QSpinBox,
    QCheckBox,
    QFrame,
    QMessageBox,
    QApplication,
)
from qgis.PyQt.QtGui import QFont
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsWkbTypes,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProcessingFeedback,
    QgsField,
    QgsMapLayerProxyModel,
    QgsSpatialIndex,
    NULL,
)

from .helpers.constants import create_qgs_field
from qgis.gui import QgsMapLayerComboBox

try:
    import processing
except ImportError:
    processing = None


class SplitEADialog(QDialog):
    """Pop-up dialog to split EA polygons with proposed cut lines and update layer & counts in-place."""

    def __init__(
        self,
        parent=None,
        default_output_dir: str = "",
        default_geocode: str = "",
        default_bldg_layer: Optional[QgsVectorLayer] = None,
        default_min_hh: int = 99,
    ):
        super().__init__(parent)
        self.setWindowTitle("Run Delineation - Split EA Polygons")
        self.setMinimumSize(560, 680)
        self.resize(620, 720)

        self.default_output_dir = default_output_dir or ""
        self.default_geocode = default_geocode or ""
        self.default_bldg_layer = default_bldg_layer
        self.default_min_hh = int(default_min_hh or 99)

        self._prev_poly_layer = None
        self._prev_line_layer = None
        self._poly_user_toggled = False
        self._line_user_toggled = False

        self._init_ui()
        self._auto_detect_layers()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        # ── Header Description ─────────────────────────────────────────────
        header_lbl = QLabel(
            "<b>Split EA Polygons:</b> Select the input EA polygon layer, proposed cut lines layer, and building point layer. "
            "Running the split will bisect the candidate EAs, update the polygon layer in-place, and recalculate "
            "<b>hh_count</b> (from <i>est_hhcount</i>) and <b>bldg_count</b> for each split EA."
        )
        header_lbl.setWordWrap(True)
        main_layout.addWidget(header_lbl)

        # ── 1. Input Layers Group ──────────────────────────────────────────
        inputs_group = QGroupBox("Input Layers")
        inputs_layout = QVBoxLayout(inputs_group)
        inputs_layout.setContentsMargins(10, 10, 10, 10)
        inputs_layout.setSpacing(4)

        # EA Polygon Layer (delineation_ea)
        inputs_layout.addWidget(QLabel("Target EA Polygon Layer (delineation_ea)*:"))
        self.poly_combo = QgsMapLayerComboBox(self)
        self.poly_combo.setMinimumHeight(28)
        self.poly_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.poly_combo.layerChanged.connect(self._on_layer_selection_changed)
        inputs_layout.addWidget(self.poly_combo)

        poly_sel_row = QHBoxLayout()
        self.poly_selected_chk = QCheckBox("Selected features only (0 selected)")
        self.poly_selected_chk.setMinimumHeight(22)
        self.poly_selected_chk.setToolTip("When checked, only the selected/highlighted polygon features in this layer will be split.")
        self.poly_selected_chk.toggled.connect(self._on_poly_chk_toggled)
        poly_sel_row.addWidget(self.poly_selected_chk)
        poly_sel_row.addStretch()
        inputs_layout.addLayout(poly_sel_row)

        self.poly_status_lbl = QLabel("No polygon layer selected.")
        self.poly_status_lbl.setStyleSheet("color: #7F8C8D; font-size: 11px;")
        inputs_layout.addWidget(self.poly_status_lbl)

        inputs_layout.addSpacing(4)

        # Proposed Cut Lines Layer (eadel_update)
        inputs_layout.addWidget(QLabel("Proposed Cut Lines Layer (eadel_update)*:"))
        self.line_combo = QgsMapLayerComboBox(self)
        self.line_combo.setMinimumHeight(28)
        self.line_combo.setFilters(QgsMapLayerProxyModel.LineLayer)
        self.line_combo.layerChanged.connect(self._on_layer_selection_changed)
        inputs_layout.addWidget(self.line_combo)

        line_sel_row = QHBoxLayout()
        self.line_selected_chk = QCheckBox("Selected features only (0 selected)")
        self.line_selected_chk.setMinimumHeight(22)
        self.line_selected_chk.setToolTip("When checked, only the selected/highlighted cut lines in this layer will be used for splitting.")
        self.line_selected_chk.toggled.connect(self._on_line_chk_toggled)
        line_sel_row.addWidget(self.line_selected_chk)
        line_sel_row.addStretch()
        inputs_layout.addLayout(line_sel_row)

        self.line_status_lbl = QLabel("No line layer selected.")
        self.line_status_lbl.setStyleSheet("color: #7F8C8D; font-size: 11px;")
        inputs_layout.addWidget(self.line_status_lbl)

        inputs_layout.addSpacing(4)

        # Building Points Layer
        inputs_layout.addWidget(QLabel("Building Point Layer (bldgpts)*:"))
        self.bldg_combo = QgsMapLayerComboBox(self)
        self.bldg_combo.setMinimumHeight(28)
        self.bldg_combo.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.bldg_combo.layerChanged.connect(self._on_layer_selection_changed)
        inputs_layout.addWidget(self.bldg_combo)

        self.bldg_status_lbl = QLabel("No building point layer selected.")
        self.bldg_status_lbl.setStyleSheet("color: #7F8C8D; font-size: 11px;")
        inputs_layout.addWidget(self.bldg_status_lbl)

        main_layout.addWidget(inputs_group)

        # ── 2. Settings Group ──────────────────────────────────────────────
        settings_group = QGroupBox("Splitting Options")
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setContentsMargins(10, 10, 10, 10)
        settings_layout.setSpacing(6)

        # Minimum Household Threshold
        min_hh_layout = QHBoxLayout()
        min_hh_layout.addWidget(QLabel("Minimum Household Threshold per EA:"))
        self.min_hh_spin = QSpinBox()
        self.min_hh_spin.setMinimumHeight(26)
        self.min_hh_spin.setRange(1, 99999)
        self.min_hh_spin.setValue(self.default_min_hh)
        self.min_hh_spin.setToolTip(
            "Minimum household count required per EA. If any resulting split part falls below this threshold, the split for that EA is prevented to avoid creating under-threshold EAs."
        )
        min_hh_layout.addWidget(self.min_hh_spin)
        min_hh_layout.addStretch()
        settings_layout.addLayout(min_hh_layout)

        # Line extension tolerance
        tol_layout = QHBoxLayout()
        tol_layout.addWidget(QLabel("Line Endpoint Extension (meters):"))
        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setMinimumHeight(26)
        self.tolerance_spin.setRange(0.0, 50.0)
        self.tolerance_spin.setValue(1.0)
        self.tolerance_spin.setSingleStep(0.5)
        self.tolerance_spin.setToolTip(
            "Slightly extends line endpoints across the polygon boundary to prevent undershoots and ensure clean bisection."
        )
        tol_layout.addWidget(self.tolerance_spin)
        tol_layout.addStretch()
        settings_layout.addLayout(tol_layout)

        main_layout.addWidget(settings_group)

        # ── 3. Execution Logs & Status ─────────────────────────────────────
        self.status_banner = QLabel("Ready to execute split.")
        self.status_banner.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.status_banner.setStyleSheet("color: #2c3e50;")
        main_layout.addWidget(self.status_banner)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(20)
        main_layout.addWidget(self.progress_bar)

        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setMinimumHeight(90)
        self.log_console.setMaximumHeight(140)
        self.log_console.setFont(QFont("Consolas", 8))
        main_layout.addWidget(self.log_console)

        # ── 4. Bottom Action Buttons ───────────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.close_btn = QPushButton("Close")
        self.close_btn.setMinimumWidth(80)
        self.close_btn.setMinimumHeight(28)
        self.close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.close_btn)

        btn_layout.addStretch()

        self.run_btn = QPushButton("Run Split")
        self.run_btn.setMinimumWidth(130)
        self.run_btn.setMinimumHeight(28)
        self.run_btn.setStyleSheet("font-weight: bold; background-color: #27ae60; color: white;")
        self.run_btn.clicked.connect(self.run_split)
        btn_layout.addWidget(self.run_btn)

        main_layout.addLayout(btn_layout)

    def _auto_detect_layers(self):
        """Auto-detect matching delineation_ea, eadel_update, and building point layers."""
        project = QgsProject.instance()
        all_layers = list(project.mapLayers().values())

        poly_candidate = None
        line_candidate = None
        bldg_candidate = self.default_bldg_layer if (self.default_bldg_layer and self.default_bldg_layer.isValid()) else None

        # Prioritize layers with specific names
        for layer in all_layers:
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                continue

            name = layer.name().lower()

            # Detect proposed cut line layer (*_eadel_update, eadel_update)
            if layer.geometryType() == QgsWkbTypes.LineGeometry:
                if "_eadel_update" in name or name == "eadel_update" or "splitting_lines" in name:
                    line_candidate = layer
                elif not line_candidate:
                    line_candidate = layer

            # Detect delineation EA polygon layer (*_delineated_ea*, *_delineation_ea*, delineation_ea)
            elif layer.geometryType() == QgsWkbTypes.PolygonGeometry:
                if "_delineated_ea" in name or "_delineation_ea" in name or "delineation_ea" in name:
                    poly_candidate = layer
                elif "delineation_candidates" in name and not poly_candidate:
                    poly_candidate = layer
                elif not poly_candidate and ("ea" in name or "barangay" not in name):
                    poly_candidate = layer

            # Detect building point layer (*bldgpts*, *building*, *bldg*)
            elif layer.geometryType() == QgsWkbTypes.PointGeometry:
                if not bldg_candidate:
                    if "bldgpts" in name or "extracted_bldgpts" in name:
                        bldg_candidate = layer
                    elif "bldg" in name or "building" in name:
                        bldg_candidate = layer

        if poly_candidate:
            self.poly_combo.setLayer(poly_candidate)
        if line_candidate:
            self.line_combo.setLayer(line_candidate)
        if bldg_candidate:
            self.bldg_combo.setLayer(bldg_candidate)

        self._on_layer_selection_changed()

    def closeEvent(self, event):
        self._disconnect_selection_signals()
        super().closeEvent(event)

    def _disconnect_selection_signals(self):
        if self._prev_poly_layer and hasattr(self._prev_poly_layer, "selectionChanged"):
            try:
                self._prev_poly_layer.selectionChanged.disconnect(self._update_poly_selection_ui)
            except Exception:
                pass
        if self._prev_line_layer and hasattr(self._prev_line_layer, "selectionChanged"):
            try:
                self._prev_line_layer.selectionChanged.disconnect(self._update_line_selection_ui)
            except Exception:
                pass

    def _on_poly_chk_toggled(self, checked: bool):
        self._poly_user_toggled = True

    def _on_line_chk_toggled(self, checked: bool):
        self._line_user_toggled = True

    def _update_poly_selection_ui(self):
        """Update polygon selection checkbox state and label."""
        poly_layer = self.poly_combo.currentLayer()
        if poly_layer and poly_layer.isValid() and hasattr(poly_layer, "selectedFeatureCount"):
            try:
                count = int(poly_layer.selectedFeatureCount())
            except (ValueError, TypeError):
                count = 0
            self.poly_selected_chk.setText(f"Selected features only ({count} selected)")
            if count > 0:
                self.poly_selected_chk.setEnabled(True)
                if not self._poly_user_toggled:
                    self.poly_selected_chk.setChecked(True)
            else:
                self.poly_selected_chk.setChecked(False)
                self.poly_selected_chk.setEnabled(False)
                self._poly_user_toggled = False
        else:
            self.poly_selected_chk.setText("Selected features only (0 selected)")
            self.poly_selected_chk.setChecked(False)
            self.poly_selected_chk.setEnabled(False)
            self._poly_user_toggled = False

    def _update_line_selection_ui(self):
        """Update cut lines selection checkbox state and label."""
        line_layer = self.line_combo.currentLayer()
        if line_layer and line_layer.isValid() and hasattr(line_layer, "selectedFeatureCount"):
            try:
                count = int(line_layer.selectedFeatureCount())
            except (ValueError, TypeError):
                count = 0
            self.line_selected_chk.setText(f"Selected features only ({count} selected)")
            if count > 0:
                self.line_selected_chk.setEnabled(True)
                if not self._line_user_toggled:
                    self.line_selected_chk.setChecked(True)
            else:
                self.line_selected_chk.setChecked(False)
                self.line_selected_chk.setEnabled(False)
                self._line_user_toggled = False
        else:
            self.line_selected_chk.setText("Selected features only (0 selected)")
            self.line_selected_chk.setChecked(False)
            self.line_selected_chk.setEnabled(False)
            self._line_user_toggled = False

    def _on_layer_selection_changed(self):
        """Update layer info labels and dynamic selection listeners when layers change."""
        poly_layer = self.poly_combo.currentLayer()
        if self._prev_poly_layer != poly_layer:
            if self._prev_poly_layer and hasattr(self._prev_poly_layer, "selectionChanged"):
                try:
                    self._prev_poly_layer.selectionChanged.disconnect(self._update_poly_selection_ui)
                except Exception:
                    pass
            self._prev_poly_layer = poly_layer
            self._poly_user_toggled = False
            if poly_layer and hasattr(poly_layer, "selectionChanged"):
                try:
                    poly_layer.selectionChanged.connect(self._update_poly_selection_ui)
                except Exception:
                    pass

        line_layer = self.line_combo.currentLayer()
        if self._prev_line_layer != line_layer:
            if self._prev_line_layer and hasattr(self._prev_line_layer, "selectionChanged"):
                try:
                    self._prev_line_layer.selectionChanged.disconnect(self._update_line_selection_ui)
                except Exception:
                    pass
            self._prev_line_layer = line_layer
            self._line_user_toggled = False
            if line_layer and hasattr(line_layer, "selectionChanged"):
                try:
                    line_layer.selectionChanged.connect(self._update_line_selection_ui)
                except Exception:
                    pass

        self._update_poly_selection_ui()
        self._update_line_selection_ui()

        if poly_layer and poly_layer.isValid():
            self.poly_status_lbl.setText(
                f"Target to update: <b>{poly_layer.name()}</b> ({poly_layer.featureCount()} polygon features)"
            )
            self.poly_status_lbl.setStyleSheet("color: #27ae60; font-size: 11px;")
        else:
            self.poly_status_lbl.setText("No valid polygon layer selected.")
            self.poly_status_lbl.setStyleSheet("color: #e74c3c; font-size: 11px;")

        if line_layer and line_layer.isValid():
            self.line_status_lbl.setText(
                f"Selected cut lines: <b>{line_layer.name()}</b> ({line_layer.featureCount()} line features)"
            )
            self.line_status_lbl.setStyleSheet("color: #27ae60; font-size: 11px;")
        else:
            self.line_status_lbl.setText("No valid line layer selected.")
            self.line_status_lbl.setStyleSheet("color: #e74c3c; font-size: 11px;")

        bldg_layer = self.bldg_combo.currentLayer()
        if bldg_layer and bldg_layer.isValid():
            self.bldg_status_lbl.setText(
                f"Selected building points: <b>{bldg_layer.name()}</b> ({bldg_layer.featureCount()} point features)"
            )
            self.bldg_status_lbl.setStyleSheet("color: #27ae60; font-size: 11px;")
        else:
            self.bldg_status_lbl.setText("Optional / No building point layer selected.")
            self.bldg_status_lbl.setStyleSheet("color: #7F8C8D; font-size: 11px;")

    def _log(self, message: str, level: str = "INFO"):
        """Append formatted message to log console."""
        colors = {
            "INFO": "#2980b9",
            "SUCCESS": "#27ae60",
            "WARNING": "#e67e22",
            "ERROR": "#c0392b",
        }
        color = colors.get(level, "#333333")
        self.log_console.append(f"<span style='color:{color}; font-weight:bold;'>[{level}]</span> {message}")
        if hasattr(QApplication, "processEvents"):
            QApplication.processEvents()

    def _extend_line_endpoints(self, line_geom: QgsGeometry, extend_dist: float) -> QgsGeometry:
        """Extend line endpoints outwards by extend_dist to eliminate boundary undershoots."""
        if extend_dist <= 0.0 or not line_geom or line_geom.isEmpty():
            return line_geom

        if line_geom.isMultipart():
            lines = line_geom.asMultiPolyline()
            extended_multi = []
            for polyline in lines:
                if len(polyline) < 2:
                    extended_multi.append(polyline)
                    continue
                new_poly = list(polyline)
                # Extend start point
                p0, p1 = new_poly[0], new_poly[1]
                dx, dy = p0.x() - p1.x(), p0.y() - p1.y()
                dist = math.hypot(dx, dy)
                if dist > 1e-9:
                    new_p0 = QgsPointXY(p0.x() + (dx / dist) * extend_dist, p0.y() + (dy / dist) * extend_dist)
                    new_poly[0] = new_p0

                # Extend end point
                pn, pn_prev = new_poly[-1], new_poly[-2]
                dx, dy = pn.x() - pn_prev.x(), pn.y() - pn_prev.y()
                dist = math.hypot(dx, dy)
                if dist > 1e-9:
                    new_pn = QgsPointXY(pn.x() + (dx / dist) * extend_dist, pn.y() + (dy / dist) * extend_dist)
                    new_poly[-1] = new_pn

                extended_multi.append(new_poly)
            return QgsGeometry.fromMultiPolylineXY(extended_multi)
        else:
            polyline = line_geom.asPolyline()
            if len(polyline) < 2:
                return line_geom
            new_poly = list(polyline)
            # Extend start point
            p0, p1 = new_poly[0], new_poly[1]
            dx, dy = p0.x() - p1.x(), p0.y() - p1.y()
            dist = math.hypot(dx, dy)
            if dist > 1e-9:
                new_p0 = QgsPointXY(p0.x() + (dx / dist) * extend_dist, p0.y() + (dy / dist) * extend_dist)
                new_poly[0] = new_p0

            # Extend end point
            pn, pn_prev = new_poly[-1], new_poly[-2]
            dx, dy = pn.x() - pn_prev.x(), pn.y() - pn_prev.y()
            dist = math.hypot(dx, dy)
            if dist > 1e-9:
                new_pn = QgsPointXY(pn.x() + (dx / dist) * extend_dist, pn.y() + (dy / dist) * extend_dist)
                new_poly[-1] = new_pn

            return QgsGeometry.fromPolylineXY(new_poly)

    def _extend_line_to_traverse_polygon(
        self,
        line_geom: QgsGeometry,
        poly_geom: QgsGeometry,
        extend_dist_map_units: float = 0.001,
        extend_tol: Optional[float] = None,
    ) -> QgsGeometry:
        """Extend cut line endpoints outward to guarantee it fully traverses through the target polygon boundary."""
        if extend_tol is not None:
            extend_dist_map_units = extend_tol
        if not line_geom or line_geom.isEmpty():
            return line_geom
        if not poly_geom or poly_geom.isEmpty():
            return self._extend_line_endpoints(line_geom, extend_dist_map_units)

        bbox = poly_geom.boundingBox()
        poly_diag = math.hypot(bbox.width(), bbox.height())
        if poly_diag < 1e-9:
            poly_diag = 1.0

        ext_len = max(poly_diag * 0.5, extend_dist_map_units) + (extend_dist_map_units * 2.0)

        def extend_segment_coords(pts: List[QgsPointXY]) -> List[QgsPointXY]:
            if len(pts) < 2:
                return pts
            if pts[0] == pts[-1] and len(pts) > 2:
                # Closed ring / loop already traverses
                return pts

            new_pts = list(pts)

            # Extend start point p0 outward away from p1
            p0, p1 = new_pts[0], new_pts[1]
            dx0, dy0 = p0.x() - p1.x(), p0.y() - p1.y()
            dist0 = math.hypot(dx0, dy0)
            if dist0 > 1e-12:
                new_p0 = QgsPointXY(p0.x() + (dx0 / dist0) * ext_len, p0.y() + (dy0 / dist0) * ext_len)
                new_pts[0] = new_p0

            # Extend end point pn outward away from pn_prev
            pn, pn_prev = new_pts[-1], new_pts[-2]
            dxn, dyn = pn.x() - pn_prev.x(), pn.y() - pn_prev.y()
            distn = math.hypot(dxn, dyn)
            if distn > 1e-12:
                new_pn = QgsPointXY(pn.x() + (dxn / distn) * ext_len, pn.y() + (dyn / distn) * ext_len)
                new_pts[-1] = new_pn

            return new_pts

        if line_geom.isMultipart():
            extended_multi = []
            for polyline in line_geom.asMultiPolyline():
                extended_multi.append(extend_segment_coords(polyline))
            return QgsGeometry.fromMultiPolylineXY(extended_multi)
        else:
            polyline = line_geom.asPolyline()
            return QgsGeometry.fromPolylineXY(extend_segment_coords(polyline))

    def _prepare_extended_cut_lines(self, line_layer: QgsVectorLayer, extend_dist: float) -> QgsVectorLayer:
        """Create memory layer containing extended cut lines."""
        crs_auth = line_layer.crs().authid() if line_layer.crs().isValid() else "EPSG:4326"
        temp_lines = QgsVectorLayer(f"LineString?crs={crs_auth}", "temp_extended_lines", "memory")
        dp = temp_lines.dataProvider()
        dp.addAttributes(line_layer.fields())
        temp_lines.updateFields()

        feats = []
        for feat in line_layer.getFeatures():
            geom = feat.geometry()
            if geom and not geom.isEmpty():
                ext_geom = self._extend_line_endpoints(geom, extend_dist)
                new_feat = QgsFeature(feat)
                new_feat.setGeometry(ext_geom)
                feats.append(new_feat)

        dp.addFeatures(feats)
        temp_lines.updateExtents()
        return temp_lines

    def _resolve_bldg_hh_field(self, bldg_layer: QgsVectorLayer) -> Tuple[int, str]:
        """Find the index and name of the household count field in building point layer."""
        fields = bldg_layer.fields()
        candidate_names = [
            "est_hhcount",
            "est_hh_count",
            "est_hh",
        ]
        for cname in candidate_names:
            for idx in range(fields.count()):
                if fields.at(idx).name().lower() == cname:
                    return idx, fields.at(idx).name()
        return -1, ""

    def _extract_parent_code_and_prefix(self, feat: QgsFeature, fields: Any = None) -> Tuple[str, str]:
        """Extract standardized 6-digit code and 3-digit prefix from parent feature."""
        candidate_fields = ["ean", "new_ean", "code", "ea_code", "ea_number", "id", "name"]
        for fname in candidate_fields:
            try:
                raw_val = feat.attribute(fname)
                if raw_val is not None and raw_val != NULL:
                    s = str(raw_val).strip()
                    if s.endswith(".0"):
                        s = s[:-2]
                    if s and s.lower() not in ("null", "none", "nan", "false"):
                        digits = "".join([c for c in s if c.isdigit()])
                        if len(digits) >= 6:
                            code_6 = digits[-6:]
                            prefix_3 = code_6[:3]
                            return code_6, prefix_3
                        elif len(digits) == 3:
                            return digits + "000", digits
                        elif digits:
                            code_6 = digits.zfill(6)
                            return code_6, code_6[:3]
            except Exception:
                pass

        if fields is not None:
            for fname in candidate_fields:
                idx = -1
                if hasattr(fields, "indexOf"):
                    idx = fields.indexOf(fname)
                elif hasattr(fields, "lookupField"):
                    idx = fields.lookupField(fname)
                elif hasattr(fields, "indexFromName"):
                    idx = fields.indexFromName(fname)
                elif isinstance(fields, (list, tuple)):
                    for i, f in enumerate(fields):
                        if hasattr(f, "name") and f.name().lower() == fname:
                            idx = i
                            break
                if idx != -1:
                    raw_val = feat.attribute(idx)
                    if raw_val is not None and raw_val != NULL:
                        s = str(raw_val).strip()
                        if s.endswith(".0"):
                            s = s[:-2]
                        if s and s.lower() not in ("null", "none", "nan", "false"):
                            digits = "".join([c for c in s if c.isdigit()])
                            if len(digits) >= 6:
                                code_6 = digits[-6:]
                                prefix_3 = code_6[:3]
                                return code_6, prefix_3
                            elif len(digits) == 3:
                                return digits + "000", digits
                            elif digits:
                                code_6 = digits.zfill(6)
                                return code_6, code_6[:3]

        return "001000", "001"

    def run_split(self):
        """Execute polygon splitting pipeline and directly update target polygon layer and counts in-place."""
        poly_layer = self.poly_combo.currentLayer()
        line_layer = self.line_combo.currentLayer()
        bldg_layer = self.bldg_combo.currentLayer()

        if not poly_layer or not poly_layer.isValid():
            QMessageBox.warning(self, "Invalid Input", "Please select a valid EA polygon layer.")
            return
        if not line_layer or not line_layer.isValid():
            QMessageBox.warning(self, "Invalid Input", "Please select a valid cut lines layer.")
            return

        in_poly_count = poly_layer.featureCount()
        in_line_count = line_layer.featureCount()

        if in_poly_count == 0:
            QMessageBox.warning(self, "Empty Input", "The selected polygon layer contains 0 features.")
            return
        if in_line_count == 0:
            QMessageBox.warning(self, "Empty Input", "The selected cut lines layer contains 0 features.")
            return

        use_selected_poly = self.poly_selected_chk.isChecked() and (poly_layer.selectedFeatureCount() > 0)
        selected_poly_ids = set(poly_layer.selectedFeatureIds()) if use_selected_poly else set()
        if self.poly_selected_chk.isChecked() and poly_layer.selectedFeatureCount() == 0:
            QMessageBox.warning(
                self,
                "No Polygons Selected",
                "The 'Selected features only' option is checked for the polygon layer, but no polygon features are currently selected in QGIS.",
            )
            return

        use_selected_lines = self.line_selected_chk.isChecked() and (line_layer.selectedFeatureCount() > 0)
        if self.line_selected_chk.isChecked() and line_layer.selectedFeatureCount() == 0:
            QMessageBox.warning(
                self,
                "No Cut Lines Selected",
                "The 'Selected features only' option is checked for cut lines, but no cut line features are currently selected in QGIS.",
            )
            return

        poly_crs = poly_layer.crs()
        line_crs = line_layer.crs()

        xform_line_to_poly = None
        if poly_crs.isValid() and line_crs.isValid() and poly_crs.authid() != line_crs.authid():
            try:
                xform_line_to_poly = QgsCoordinateTransform(line_crs, poly_crs, QgsProject.instance())
            except Exception:
                xform_line_to_poly = None

        raw_line_feats = line_layer.selectedFeatures() if use_selected_lines else list(line_layer.getFeatures())
        selected_line_feats = []
        for lf in raw_line_feats:
            if not lf or not lf.hasGeometry() or lf.geometry().isEmpty():
                continue
            geom = QgsGeometry(lf.geometry())
            if xform_line_to_poly:
                try:
                    geom.transform(xform_line_to_poly)
                except Exception:
                    pass
            new_lf = QgsFeature(lf)
            new_lf.setGeometry(geom)
            selected_line_feats.append(new_lf)

        if self.line_selected_chk.isChecked() and len(selected_line_feats) == 0:
            QMessageBox.warning(
                self,
                "No Cut Lines Selected",
                "The 'Selected features only' option is checked for cut lines, but no cut line features are currently selected in QGIS.",
            )
            return

        self.run_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.progress_bar.setValue(10)
        self.log_console.clear()
        self.status_banner.setText("Executing polygon split...")
        self.status_banner.setStyleSheet("color: #2980b9; font-weight: bold;")

        self._log(f"Starting EA polygon split pipeline...")
        if use_selected_poly:
            self._log(f"Target polygon layer: '{poly_layer.name()}' — Splitting {len(selected_poly_ids)} SELECTED feature(s) of {in_poly_count} total")
        else:
            self._log(f"Target polygon layer: '{poly_layer.name()}' ({in_poly_count} features)")

        if use_selected_lines:
            self._log(f"Input cut lines layer: '{line_layer.name()}' — Using {len(selected_line_feats)} SELECTED line(s) of {in_line_count} total")
        else:
            self._log(f"Input cut lines layer: '{line_layer.name()}' ({in_line_count} features)")

        if bldg_layer and bldg_layer.isValid():
            self._log(f"Building points layer: '{bldg_layer.name()}' ({bldg_layer.featureCount()} features)")

        try:
            extend_tol = self.tolerance_spin.value()
            crs_auth = poly_crs.authid() if poly_crs.isValid() else "EPSG:4326"

            is_geographic = poly_crs.isGeographic() if poly_crs.isValid() else False
            if is_geographic:
                extend_dist_map_units = max(extend_tol / 111320.0, 0.00001)
            else:
                extend_dist_map_units = max(extend_tol, 0.5)

            self.progress_bar.setValue(20)
            self._log("Indexing proposed cut lines and matching to EA polygons...")

            line_spatial_index = QgsSpatialIndex()
            for lf in selected_line_feats:
                if lf and lf.hasGeometry() and not lf.geometry().isEmpty():
                    line_spatial_index.addFeature(lf)
            line_lookup = {f.id(): f for f in selected_line_feats}

            exploded_features = []
            parent_split_groups = []

            for p_idx, poly_feat in enumerate(poly_layer.getFeatures()):
                poly_geom = poly_feat.geometry()
                if not poly_geom or poly_geom.isEmpty():
                    continue

                if use_selected_poly and poly_feat.id() not in selected_poly_ids:
                    # Unselected polygon -> preserve whole and untouched
                    exploded_features.append(poly_feat)
                    parent_split_groups.append({"parent": poly_feat, "parts": [poly_geom]})
                    continue

                # Find cut lines that intersect this specific polygon
                if use_selected_lines:
                    candidate_lines = selected_line_feats
                else:
                    cand_line_ids = line_spatial_index.intersects(poly_geom.boundingBox())
                    candidate_lines = [line_lookup[lid] for lid in cand_line_ids if lid in line_lookup]

                matching_lines = []
                for lfeat in candidate_lines:
                    if lfeat and lfeat.geometry() and not lfeat.geometry().isEmpty():
                        lg = lfeat.geometry()
                        if (
                            (use_selected_poly and use_selected_lines)
                            or poly_geom.intersects(lg)
                            or poly_geom.distance(lg) < max(extend_dist_map_units * 5.0, 50.0 if not is_geographic else 0.001)
                        ):
                            matching_lines.append(lfeat)

                if not matching_lines:
                    # No cut lines intersect this EA -> preserve whole
                    if use_selected_poly:
                        self._log(
                            f"Selected polygon '{poly_feat.attribute('ean') or poly_feat.id()}' did not intersect any of the {len(selected_line_feats)} cut line(s).",
                            "WARNING",
                        )
                    exploded_features.append(poly_feat)
                    parent_split_groups.append({"parent": poly_feat, "parts": [poly_geom]})
                    continue

                # Create single polygon layer for isolated split (MultiPolygon supports both Polygon and MultiPolygon)
                single_poly_layer = QgsVectorLayer(f"MultiPolygon?crs={crs_auth}", "single_poly", "memory")
                dp_poly = single_poly_layer.dataProvider()
                dp_poly.addAttributes(poly_layer.fields())
                single_poly_layer.updateFields()
                pf_copy = QgsFeature(poly_layer.fields())
                pf_copy.setGeometry(poly_geom)
                for fld in poly_layer.fields():
                    val = poly_feat.attribute(fld.name())
                    if val is not None and val != NULL:
                        pf_copy.setAttribute(fld.name(), val)
                dp_poly.addFeatures([pf_copy])
                single_poly_layer.updateExtents()

                # Create lines layer for matching cut lines only (MultiLineString supports both single & multipart)
                single_lines_layer = QgsVectorLayer(f"MultiLineString?crs={crs_auth}", "single_lines", "memory")
                dp_lines = single_lines_layer.dataProvider()
                dp_lines.addAttributes(line_layer.fields())
                single_lines_layer.updateFields()

                prepared_line_feats = []
                for lf in matching_lines:
                    lg = lf.geometry()
                    if extend_tol > 0.0:
                        lg = self._extend_line_to_traverse_polygon(lg, poly_geom, extend_dist_map_units)
                    new_lf = QgsFeature(line_layer.fields())
                    new_lf.setGeometry(lg)
                    prepared_line_feats.append(new_lf)
                dp_lines.addFeatures(prepared_line_feats)
                single_lines_layer.updateExtents()

                child_geoms = []

                # Attempt 1: Run native:splitwithlines on this single polygon
                if processing:
                    try:
                        split_res = processing.run(
                            "native:splitwithlines",
                            {
                                "INPUT": single_poly_layer,
                                "LINES": single_lines_layer,
                                "OUTPUT": "TEMPORARY_OUTPUT",
                            },
                        )
                        raw_split = split_res.get("OUTPUT")

                        single_res = processing.run(
                            "native:multiparttosingleparts",
                            {
                                "INPUT": raw_split,
                                "OUTPUT": "TEMPORARY_OUTPUT",
                            },
                        )
                        exploded = single_res.get("OUTPUT")

                        if exploded and isinstance(exploded, QgsVectorLayer) and exploded.featureCount() > 0:
                            for sub_feat in exploded.getFeatures():
                                if sub_feat.geometry() and not sub_feat.geometry().isEmpty():
                                    child_geoms.append(sub_feat.geometry())
                    except Exception as e:
                        self._log(f"Split algorithm notice: {str(e)}", "INFO")

                # Attempt 2: Planar Polygonization fallback (combines polygon boundary + cut lines)
                if len(child_geoms) <= 1 and processing:
                    try:
                        boundary_res = processing.run(
                            "native:boundary",
                            {
                                "INPUT": single_poly_layer,
                                "OUTPUT": "TEMPORARY_OUTPUT",
                            },
                        )
                        boundary_lyr = boundary_res.get("OUTPUT")
                        merged_lines_res = processing.run(
                            "native:mergevectorlayers",
                            {
                                "LAYERS": [boundary_lyr, single_lines_layer],
                                "OUTPUT": "TEMPORARY_OUTPUT",
                            },
                        )
                        merged_lines_lyr = merged_lines_res.get("OUTPUT")
                        polygonized_res = processing.run(
                            "native:polygonize",
                            {
                                "INPUT": merged_lines_lyr,
                                "OUTPUT": "TEMPORARY_OUTPUT",
                            },
                        )
                        poly_output = polygonized_res.get("OUTPUT")
                        if poly_output and isinstance(poly_output, QgsVectorLayer) and poly_output.featureCount() > 1:
                            cand_parts = []
                            for p_feat in poly_output.getFeatures():
                                pg = p_feat.geometry()
                                if pg and not pg.isEmpty():
                                    pt_surface = pg.pointOnSurface()
                                    if poly_geom.contains(pt_surface) or poly_geom.intersects(pt_surface):
                                        cand_parts.append(pg)
                            if len(cand_parts) > 1:
                                child_geoms = cand_parts
                    except Exception as e:
                        self._log(f"Planar polygonization notice: {str(e)}", "INFO")

                # Attempt 3: Iterative QgsGeometry.splitGeometry across all matching lines
                if len(child_geoms) <= 1:
                    # Deconstruct polygon into constituent parts to handle both single and multi-polygons
                    if poly_geom.isMultipart():
                        raw_parts = [QgsGeometry.fromPolygonXY(p) for p in poly_geom.asMultiPolygon()]
                    else:
                        raw_parts = [QgsGeometry(poly_geom)]

                    current_pieces = list(raw_parts)
                    for lf in prepared_line_feats:
                        lg = lf.geometry()
                        if not lg or lg.isEmpty():
                            continue
                        polylines = lg.asMultiPolyline() if lg.isMultipart() else [lg.asPolyline()]
                        for pline in polylines:
                            if len(pline) < 2:
                                continue
                            next_pieces = []
                            for piece in current_pieces:
                                working_piece = QgsGeometry(piece)
                                # Try topological=True then topological=False
                                res, new_subgeoms, _ = working_piece.splitGeometry(pline, True)
                                if res != 0 or not new_subgeoms:
                                    working_piece = QgsGeometry(piece)
                                    res, new_subgeoms, _ = working_piece.splitGeometry(pline, False)
                                if res == 0 and new_subgeoms:
                                    next_pieces.append(working_piece)
                                    next_pieces.extend(new_subgeoms)
                                else:
                                    next_pieces.append(piece)
                            current_pieces = next_pieces
                    if len(current_pieces) > 1:
                        child_geoms = current_pieces

                if len(child_geoms) > 1:
                    for cg in child_geoms:
                        sub_feat_full = QgsFeature(poly_layer.fields())
                        sub_feat_full.setGeometry(cg)
                        for fld in poly_layer.fields():
                            fname = fld.name()
                            val = poly_feat.attribute(fname)
                            if val is not None and val != NULL:
                                sub_feat_full.setAttribute(fname, val)
                        exploded_features.append(sub_feat_full)
                else:
                    child_geoms = [poly_geom]
                    exploded_features.append(poly_feat)

                parent_split_groups.append({"parent": poly_feat, "parts": child_geoms})

            self.progress_bar.setValue(60)

            # 4. Strict Post-Split Verification Checks
            self._log("Verifying split results and geometry integrity...")
            out_poly_count = len(exploded_features)
            delta_count = out_poly_count - in_poly_count

            # Calculate total areas for conservation check
            total_in_area = sum(f.geometry().area() for f in poly_layer.getFeatures() if f.geometry())
            total_out_area = sum(f.geometry().area() for f in exploded_features if f.geometry())
            area_diff = abs(total_out_area - total_in_area)
            rel_area_diff = (area_diff / total_in_area) if total_in_area > 0 else 0.0

            self._log(f"Initial polygon count: {in_poly_count}")
            self._log(f"Resulting polygon count: {out_poly_count} (Delta: +{delta_count} new features)")
            self._log(f"Area conservation difference: {area_diff:.6f} sq units (Relative: {rel_area_diff:.6%})")

            is_truly_split = delta_count > 0 and rel_area_diff < 0.001

            if is_truly_split:
                self._log(
                    f"CONFIRMED: Polygons successfully split into {out_poly_count} discrete features!",
                    "SUCCESS",
                )
            elif delta_count == 0:
                self._log(
                    "WARNING: Output polygon count equals input count. Cut lines did not intersect/bisect any polygon boundary.",
                    "WARNING",
                )
            else:
                self._log(
                    f"NOTICE: Split produced {out_poly_count} features.",
                    "INFO",
                )

            self.progress_bar.setValue(75)

            # 5. Calculate hh_count (from est_hhcount) and bldg_count from building points
            bldg_spatial_index = None
            bldg_lookup = {}
            bldg_hh_idx, bldg_hh_name = -1, ""

            if bldg_layer and bldg_layer.isValid() and bldg_layer.featureCount() > 0:
                bldg_hh_idx, bldg_hh_name = self._resolve_bldg_hh_field(bldg_layer)
                self._log(
                    f"Computing building & household counts using '{bldg_layer.name()}' "
                    f"(household field: '{bldg_hh_name or 'none [fallback 1/point]'}')..."
                )
                bldg_spatial_index = QgsSpatialIndex()
                for bf in bldg_layer.getFeatures():
                    if bf and bf.hasGeometry() and not bf.geometry().isEmpty():
                        bldg_spatial_index.addFeature(bf)
                bldg_lookup = {f.id(): f for f in bldg_layer.getFeatures()}

            # Ensure poly_layer has hh_count, bldg_count, new_ean, and ea_type fields
            poly_fields = poly_layer.fields()
            poly_field_names_lower = [poly_fields.at(i).name().lower() for i in range(poly_fields.count())]
            fields_to_add = []
            if "hh_count" not in poly_field_names_lower:
                fields_to_add.append(create_qgs_field("hh_count", QVariant.Int))
            if "bldg_count" not in poly_field_names_lower:
                fields_to_add.append(create_qgs_field("bldg_count", QVariant.Int))
            if "new_ean" not in poly_field_names_lower:
                fields_to_add.append(create_qgs_field("new_ean", QVariant.String))
            if not any(f in poly_field_names_lower for f in ("ea_type", "eatype", "type")):
                fields_to_add.append(create_qgs_field("ea_type", QVariant.String))

            if fields_to_add:
                poly_layer.dataProvider().addAttributes(fields_to_add)
                poly_layer.updateFields()
                poly_fields = poly_layer.fields()
                poly_field_names_lower = [poly_fields.at(i).name().lower() for i in range(poly_fields.count())]

            # 6. Build new features, assign recalculated counts, and format new_ean according to delineation rules
            total_hh_sum = 0
            total_bldg_sum = 0
            new_features = []

            # Scan layer to identify existing highest suffix sequences per prefix
            max_seq_by_prefix = {}
            for feat in poly_layer.getFeatures():
                code_6, prefix_3 = self._extract_parent_code_and_prefix(feat, poly_layer.fields())
                suffix_3 = code_6[3:]
                try:
                    s_val = int(suffix_3)
                    if s_val > max_seq_by_prefix.get(prefix_3, 0):
                        max_seq_by_prefix[prefix_3] = s_val
                except ValueError:
                    pass

            for group in parent_split_groups:
                parent_feat = group["parent"]
                parts = group["parts"]
                parent_code_6, orig_prefix = self._extract_parent_code_and_prefix(parent_feat, poly_layer.fields())

                # Calculate counts for each child part
                part_data = []
                for p_geom in parts:
                    inside_bldg_count = 0
                    inside_hh_float = 0.0

                    if bldg_spatial_index and p_geom and not p_geom.isEmpty():
                        candidate_ids = bldg_spatial_index.intersects(p_geom.boundingBox())
                        for bid in candidate_ids:
                            bfeat = bldg_lookup.get(bid)
                            if not bfeat:
                                continue
                            bgeom = bfeat.geometry()
                            if not bgeom or bgeom.isEmpty():
                                continue
                            if p_geom.contains(bgeom) or p_geom.intersects(bgeom):
                                inside_bldg_count += 1
                                if bldg_hh_idx != -1:
                                    raw_val = bfeat.attribute(bldg_hh_idx)
                                    if raw_val is not None and raw_val != NULL:
                                        try:
                                            inside_hh_float += float(raw_val)
                                        except (ValueError, TypeError):
                                            inside_hh_float += 1.0
                                    else:
                                        inside_hh_float += 1.0
                                else:
                                    inside_hh_float += 1.0

                    inside_hh_count = int(math.ceil(inside_hh_float))
                    area_val = p_geom.area() if p_geom else 0.0
                    part_data.append({
                        "geom": p_geom,
                        "hh_count": inside_hh_count,
                        "bldg_count": inside_bldg_count,
                        "area": area_val,
                    })

                # If split into multiple parts, log notice if any resulting piece falls below min_hh_threshold
                if len(part_data) > 1 and bldg_spatial_index:
                    min_hh_threshold = self.min_hh_spin.value() if hasattr(self, "min_hh_spin") else 99
                    under_threshold_parts = [p for p in part_data if p["hh_count"] < min_hh_threshold]
                    if under_threshold_parts:
                        min_hh_found = min(p["hh_count"] for p in part_data)
                        self._log(
                            f"Notice: Resulting sub-EA for EA '{parent_code_6}' has {min_hh_found} households "
                            f"(below threshold of {min_hh_threshold} HH). Sub-EAs successfully created.",
                            "WARNING",
                        )

                # If still split into multiple parts, sort by hh_count descending (with area as tie-breaker)
                if len(part_data) > 1:
                    part_data.sort(key=lambda item: (item["hh_count"], item["area"]), reverse=True)

                for idx, p_item in enumerate(part_data):
                    inside_hh_count = p_item["hh_count"]
                    inside_bldg_count = p_item["bldg_count"]
                    p_geom = p_item["geom"]

                    total_hh_sum += inside_hh_count
                    total_bldg_sum += inside_bldg_count

                    # Determine new_ean based on standard PSA Delineation Rules
                    if len(part_data) > 1:
                        if orig_prefix == "000" or parent_code_6 in ("000000", "000", "0"):
                            # Special Rule for parent EA 000000:
                            # 1st largest -> 001000, 2nd largest -> 002000, 3rd -> 003000, etc.
                            seq_num = idx + 1
                            assigned_new_ean = f"{seq_num:03d}000"
                        else:
                            # Standard Delineation Rule for parent EA (e.g., 001000):
                            # 1. Largest hh_count sub-EA gets parent_code + "000" (e.g., 001000)
                            # 2. Succeeding sub-EAs get parent_code + (max_seq + 1) (e.g., 001001, 001002, ...)
                            if idx == 0:
                                assigned_new_ean = f"{orig_prefix}000"
                            else:
                                curr_max = max_seq_by_prefix.get(orig_prefix, 0) + 1
                                max_seq_by_prefix[orig_prefix] = curr_max
                                assigned_new_ean = f"{orig_prefix}{curr_max:03d}"
                    else:
                        # Retained un-split polygon
                        existing_new_ean = parent_feat.attribute("new_ean") if "new_ean" in poly_field_names_lower else None
                        if existing_new_ean and str(existing_new_ean).strip().upper() not in ("", "NULL", "NONE"):
                            assigned_new_ean = str(existing_new_ean).strip()
                        else:
                            assigned_new_ean = parent_code_6

                    new_feat = QgsFeature(poly_fields)
                    new_feat.setGeometry(p_geom)
                    for fld in poly_fields:
                        fname = fld.name()
                        fname_lower = fname.lower()
                        if fname_lower in ("fid", "ogc_fid") and fld.type() in (QVariant.Int, QVariant.LongLong):
                            continue

                        # Only hh_count and bldg_count are updated based on building points
                        # Baseline fields (hhcount, bldgcount, bldgpoint, code, etc.) are strictly preserved
                        if fname_lower == "hh_count" and bldg_spatial_index:
                            new_feat.setAttribute(fname, inside_hh_count)
                        elif fname_lower == "bldg_count" and bldg_spatial_index:
                            new_feat.setAttribute(fname, inside_bldg_count)
                        elif fname_lower == "new_ean":
                            new_feat.setAttribute(fname, assigned_new_ean)
                        elif fname_lower in ("ea_type", "eatype", "type"):
                            if len(part_data) > 1:
                                new_feat.setAttribute(fname, "DELINEATED")
                            else:
                                val = parent_feat.attribute(fname)
                                new_feat.setAttribute(fname, val if val is not None and val != NULL and str(val).strip() not in ("", "None", "NULL") else "RETAINED")
                        else:
                            val = parent_feat.attribute(fname)
                            if val is not None and val != NULL:
                                new_feat.setAttribute(fname, val)

                    new_features.append(new_feat)

            self.progress_bar.setValue(85)

            # 7. Directly update the target polygon layer in-place
            self._log(f"Updating '{poly_layer.name()}' in-place with {out_poly_count} split features...")

            all_fids = [f.id() for f in poly_layer.getFeatures()]
            dp = poly_layer.dataProvider()

            is_edited = False
            try:
                if not poly_layer.isEditable():
                    poly_layer.startEditing()
                poly_layer.deleteFeatures(all_fids)
                poly_layer.addFeatures(new_features)
                is_edited = poly_layer.commitChanges()
            except Exception:
                is_edited = False

            if not is_edited:
                # Fallback to direct provider edit
                dp.deleteFeatures(all_fids)
                dp.addFeatures(new_features)

            poly_layer.updateExtents()
            poly_layer.triggerRepaint()

            # Highlight newly delineated child features on canvas
            delineated_fids = [
                f.id() for f in poly_layer.getFeatures()
                if str(f.attribute("ea_type") or "").upper() == "DELINEATED"
            ]
            if delineated_fids:
                try:
                    poly_layer.selectByIds(delineated_fids)
                except Exception:
                    pass

            if bldg_spatial_index:
                self._log(
                    f"Recalculated counts across {out_poly_count} split polygons: "
                    f"Total HH = {total_hh_sum:,}, Total Buildings = {total_bldg_sum:,}.",
                    "SUCCESS",
                )

            self._log(f"Successfully updated '{poly_layer.name()}' with {out_poly_count} features.", "SUCCESS")
            self.progress_bar.setValue(100)

            # Update status banner
            if is_truly_split:
                count_info = f" | Total HH: {total_hh_sum:,}" if bldg_spatial_index else ""
                self.status_banner.setText(
                    f"PASS: Updated '{poly_layer.name()}' — {out_poly_count} features (+{delta_count}){count_info}"
                )
                self.status_banner.setStyleSheet("color: #27ae60; font-weight: bold;")
            else:
                self.status_banner.setText(
                    f"Completed — '{poly_layer.name()}' has {out_poly_count} features"
                )
                self.status_banner.setStyleSheet("color: #e67e22; font-weight: bold;")

        except Exception as e:
            self._log(f"Error during polygon splitting: {str(e)}", "ERROR")
            self.status_banner.setText(f"Error: {str(e)}")
            self.status_banner.setStyleSheet("color: #c0392b; font-weight: bold;")
            QMessageBox.critical(self, "Split Error", f"An error occurred during splitting:\n{str(e)}")

        finally:
            self.run_btn.setEnabled(True)
            self.close_btn.setEnabled(True)
