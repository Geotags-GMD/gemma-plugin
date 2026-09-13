# -*- coding: utf-8 -*-
"""
Unmerge EA Dialog
-----------------
Modal pop-up panel for unmerging recently merged EA polygons back into their
constituent original EAs based on the EA previous layer.
Directly updates the selected merged polygon layer in-place, restoring the
original EA boundaries and recalculating 'hh_count' (from est_hhcount of building
points) and 'bldg_count' within each unmerged polygon.
"""

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
    QCheckBox,
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
    QgsField,
    QgsMapLayerProxyModel,
    QgsSpatialIndex,
    NULL,
)

from .helpers.constants import create_qgs_field
from qgis.gui import QgsMapLayerComboBox


class UnmergeEADialog(QDialog):
    """Pop-up dialog to unmerge EA polygons back to previous EA boundaries and recalculate counts in-place."""

    def __init__(
        self,
        parent=None,
        default_output_dir: str = "",
        default_geocode: str = "",
        default_merged_layer: Optional[QgsVectorLayer] = None,
        default_prev_ea_layer: Optional[QgsVectorLayer] = None,
        default_bldg_layer: Optional[QgsVectorLayer] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Unmerge EA - Revert Merged Polygons")
        self.setMinimumSize(560, 680)
        self.resize(620, 720)

        self.default_output_dir = default_output_dir or ""
        self.default_geocode = default_geocode or ""
        self.default_merged_layer = default_merged_layer
        self.default_prev_ea_layer = default_prev_ea_layer
        self.default_bldg_layer = default_bldg_layer

        self._prev_merged_layer = None
        self._merged_user_toggled = False

        self._init_ui()
        self._auto_detect_layers()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        # ── Header Description ─────────────────────────────────────────────
        header_lbl = QLabel(
            "<b>Unmerge EA Polygons:</b> Select the target Merged EA polygon layer, EA Previous reference layer, "
            "and Building Point layer. Running unmerge will revert recently merged EAs back into their constituent "
            "original polygons, update the layer in-place, and recalculate <b>hh_count</b> (from <i>est_hhcount</i>) "
            "and <b>bldg_count</b> for each restored EA."
        )
        header_lbl.setWordWrap(True)
        main_layout.addWidget(header_lbl)

        # ── 1. Input Layers Group ──────────────────────────────────────────
        inputs_group = QGroupBox("Input Layers")
        inputs_layout = QVBoxLayout(inputs_group)
        inputs_layout.setContentsMargins(10, 10, 10, 10)
        inputs_layout.setSpacing(4)

        # Merged EA Polygon Layer
        inputs_layout.addWidget(QLabel("Target Merged EA Polygon Layer (merged_ea)*:"))
        self.merged_combo = QgsMapLayerComboBox(self)
        self.merged_combo.setMinimumHeight(28)
        self.merged_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.merged_combo.layerChanged.connect(self._on_layer_selection_changed)
        inputs_layout.addWidget(self.merged_combo)

        merged_sel_row = QHBoxLayout()
        self.merged_selected_chk = QCheckBox("Selected features only (0 selected)")
        self.merged_selected_chk.setMinimumHeight(22)
        self.merged_selected_chk.setToolTip(
            "When checked, only the selected/highlighted merged polygon features in this layer will be unmerged."
        )
        self.merged_selected_chk.toggled.connect(self._on_merged_chk_toggled)
        merged_sel_row.addWidget(self.merged_selected_chk)
        merged_sel_row.addStretch()
        inputs_layout.addLayout(merged_sel_row)

        self.merged_status_lbl = QLabel("No merged layer selected.")
        self.merged_status_lbl.setStyleSheet("color: #7F8C8D; font-size: 11px;")
        inputs_layout.addWidget(self.merged_status_lbl)

        inputs_layout.addSpacing(4)

        # Previous EA Polygon Layer
        inputs_layout.addWidget(QLabel("EA Previous Reference Layer (previous_ea)*:"))
        self.prev_ea_combo = QgsMapLayerComboBox(self)
        self.prev_ea_combo.setMinimumHeight(28)
        self.prev_ea_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.prev_ea_combo.layerChanged.connect(self._on_layer_selection_changed)
        inputs_layout.addWidget(self.prev_ea_combo)

        self.prev_ea_status_lbl = QLabel("No previous EA layer selected.")
        self.prev_ea_status_lbl.setStyleSheet("color: #7F8C8D; font-size: 11px;")
        inputs_layout.addWidget(self.prev_ea_status_lbl)

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

        # ── 2. Execution Logs & Status ─────────────────────────────────────
        self.status_banner = QLabel("Ready to execute unmerge.")
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
        self.log_console.setMinimumHeight(130)
        self.log_console.setFont(QFont("Consolas", 8))
        main_layout.addWidget(self.log_console)

        # ── 3. Bottom Action Buttons ───────────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.close_btn = QPushButton("Close")
        self.close_btn.setMinimumWidth(80)
        self.close_btn.setMinimumHeight(28)
        self.close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.close_btn)

        btn_layout.addStretch()

        self.run_btn = QPushButton("Run Unmerge")
        self.run_btn.setMinimumWidth(130)
        self.run_btn.setMinimumHeight(28)
        self.run_btn.setStyleSheet("font-weight: bold; background-color: #27ae60; color: white;")
        self.run_btn.clicked.connect(self.run_unmerge)
        btn_layout.addWidget(self.run_btn)

        main_layout.addLayout(btn_layout)

    def _auto_detect_layers(self):
        """Auto-detect matching merged_ea, previous_ea, and building point layers."""
        project = QgsProject.instance()
        all_layers = list(project.mapLayers().values())

        merged_candidate = self.default_merged_layer if (self.default_merged_layer and self.default_merged_layer.isValid()) else None
        prev_ea_candidate = self.default_prev_ea_layer if (self.default_prev_ea_layer and self.default_prev_ea_layer.isValid()) else None
        bldg_candidate = self.default_bldg_layer if (self.default_bldg_layer and self.default_bldg_layer.isValid()) else None

        for layer in all_layers:
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                continue

            name = layer.name().lower()

            # Detect merged EA polygon layer (*_merged_ea*, *_merged_ea2026*, merged_ea)
            if layer.geometryType() == QgsWkbTypes.PolygonGeometry:
                if not merged_candidate:
                    if "_merged_ea" in name or "merged_ea" in name or "merged" in name:
                        merged_candidate = layer
                if not prev_ea_candidate:
                    if "_previous_ea" in name or "previous_ea" in name or "prev_ea" in name:
                        prev_ea_candidate = layer

            # Detect building point layer (*bldgpts*, *building*, *bldg*)
            elif layer.geometryType() == QgsWkbTypes.PointGeometry:
                if not bldg_candidate:
                    if "bldgpts" in name or "extracted_bldgpts" in name:
                        bldg_candidate = layer
                    elif "bldg" in name or "building" in name:
                        bldg_candidate = layer

        # Fallback polygon assignments if needed
        if not prev_ea_candidate:
            for layer in all_layers:
                if isinstance(layer, QgsVectorLayer) and layer.isValid() and layer.geometryType() == QgsWkbTypes.PolygonGeometry:
                    name = layer.name().lower()
                    if layer != merged_candidate and ("ea" in name or "2020" in name):
                        prev_ea_candidate = layer
                        break

        if merged_candidate:
            self.merged_combo.setLayer(merged_candidate)
        if prev_ea_candidate:
            self.prev_ea_combo.setLayer(prev_ea_candidate)
        if bldg_candidate:
            self.bldg_combo.setLayer(bldg_candidate)

        self._on_layer_selection_changed()

    def closeEvent(self, event):
        self._disconnect_selection_signals()
        super().closeEvent(event)

    def _disconnect_selection_signals(self):
        if self._prev_merged_layer and hasattr(self._prev_merged_layer, "selectionChanged"):
            try:
                self._prev_merged_layer.selectionChanged.disconnect(self._update_merged_selection_ui)
            except Exception:
                pass

    def _on_merged_chk_toggled(self, checked: bool):
        self._merged_user_toggled = True

    def _update_merged_selection_ui(self):
        """Update merged selection checkbox state and label."""
        merged_layer = self.merged_combo.currentLayer()
        if merged_layer and merged_layer.isValid() and hasattr(merged_layer, "selectedFeatureCount"):
            try:
                count = int(merged_layer.selectedFeatureCount())
            except (ValueError, TypeError):
                count = 0
            self.merged_selected_chk.setText(f"Selected features only ({count} selected)")
            if count > 0:
                self.merged_selected_chk.setEnabled(True)
                if not self._merged_user_toggled:
                    self.merged_selected_chk.setChecked(True)
            else:
                self.merged_selected_chk.setChecked(False)
                self.merged_selected_chk.setEnabled(False)
                self._merged_user_toggled = False
        else:
            self.merged_selected_chk.setText("Selected features only (0 selected)")
            self.merged_selected_chk.setChecked(False)
            self.merged_selected_chk.setEnabled(False)
            self._merged_user_toggled = False

    def _on_layer_selection_changed(self):
        """Update layer info labels and dynamic selection listeners when layers change."""
        merged_layer = self.merged_combo.currentLayer()
        if self._prev_merged_layer != merged_layer:
            if self._prev_merged_layer and hasattr(self._prev_merged_layer, "selectionChanged"):
                try:
                    self._prev_merged_layer.selectionChanged.disconnect(self._update_merged_selection_ui)
                except Exception:
                    pass
            self._prev_merged_layer = merged_layer
            self._merged_user_toggled = False
            if merged_layer and hasattr(merged_layer, "selectionChanged"):
                try:
                    merged_layer.selectionChanged.connect(self._update_merged_selection_ui)
                except Exception:
                    pass

        self._update_merged_selection_ui()

        if merged_layer and merged_layer.isValid():
            self.merged_status_lbl.setText(
                f"Target to update: <b>{merged_layer.name()}</b> ({merged_layer.featureCount()} polygon features)"
            )
            self.merged_status_lbl.setStyleSheet("color: #27ae60; font-size: 11px;")
        else:
            self.merged_status_lbl.setText("No valid merged layer selected.")
            self.merged_status_lbl.setStyleSheet("color: #e74c3c; font-size: 11px;")

        prev_ea_layer = self.prev_ea_combo.currentLayer()
        if prev_ea_layer and prev_ea_layer.isValid():
            self.prev_ea_status_lbl.setText(
                f"Reference layer: <b>{prev_ea_layer.name()}</b> ({prev_ea_layer.featureCount()} previous EA features)"
            )
            self.prev_ea_status_lbl.setStyleSheet("color: #27ae60; font-size: 11px;")
        else:
            self.prev_ea_status_lbl.setText("No valid previous EA layer selected.")
            self.prev_ea_status_lbl.setStyleSheet("color: #e74c3c; font-size: 11px;")

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

    def _resolve_bldg_hh_field(self, bldg_layer: QgsVectorLayer) -> Tuple[int, str]:
        """Find the index and name of the household count field in building point layer."""
        fields = bldg_layer.fields()
        candidate_names = [
            "est_hhcount",
            "est_hh_count",
            "est_hh",
            "hh_count",
            "hhcount",
            "household",
        ]
        for cname in candidate_names:
            for idx in range(fields.count()):
                if fields.at(idx).name().lower() == cname:
                    return idx, fields.at(idx).name()
        return -1, ""

    def run_unmerge(self):
        """Execute unmerge pipeline and directly update target merged layer and counts in-place."""
        merged_layer = self.merged_combo.currentLayer()
        prev_ea_layer = self.prev_ea_combo.currentLayer()
        bldg_layer = self.bldg_combo.currentLayer()

        if not merged_layer or not merged_layer.isValid():
            QMessageBox.warning(self, "Invalid Input", "Please select a valid Merged EA polygon layer.")
            return
        if not prev_ea_layer or not prev_ea_layer.isValid():
            QMessageBox.warning(self, "Invalid Input", "Please select a valid EA Previous reference layer.")
            return

        in_merged_count = merged_layer.featureCount()
        in_prev_count = prev_ea_layer.featureCount()

        if in_merged_count == 0:
            QMessageBox.warning(self, "Empty Layer", "The target merged layer contains no features.")
            return
        if in_prev_count == 0:
            QMessageBox.warning(self, "Empty Layer", "The previous EA layer contains no features.")
            return

        use_selected = self.merged_selected_chk.isChecked() and merged_layer.selectedFeatureCount() > 0
        selected_merged_ids = set(merged_layer.selectedFeatureIds()) if use_selected else set()

        if self.merged_selected_chk.isChecked() and not selected_merged_ids:
            QMessageBox.warning(
                self,
                "No Features Selected",
                "The 'Selected features only' option is checked, but no merged polygon features are currently selected.",
            )
            return

        self.run_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.progress_bar.setValue(10)
        self.log_console.clear()
        self.status_banner.setText("Executing unmerge...")
        self.status_banner.setStyleSheet("color: #2980b9; font-weight: bold;")

        self._log("Starting EA unmerge pipeline...")
        if use_selected:
            self._log(
                f"Target merged layer: '{merged_layer.name()}' — Unmerging {len(selected_merged_ids)} SELECTED feature(s) of {in_merged_count} total"
            )
        else:
            self._log(f"Target merged layer: '{merged_layer.name()}' ({in_merged_count} features)")

        self._log(f"Previous EA reference layer: '{prev_ea_layer.name()}' ({in_prev_count} features)")
        if bldg_layer and bldg_layer.isValid():
            self._log(f"Building points layer: '{bldg_layer.name()}' ({bldg_layer.featureCount()} features)")

        try:
            merged_crs = merged_layer.crs()
            prev_crs = prev_ea_layer.crs()

            # Coordinate transform if CRS differs between layers
            xform_prev_to_merged = None
            if prev_crs.isValid() and merged_crs.isValid() and prev_crs != merged_crs:
                xform_prev_to_merged = QgsCoordinateTransform(prev_crs, merged_crs, QgsProject.instance())

            self.progress_bar.setValue(20)
            self._log("Building spatial index for previous EA reference polygons...")

            prev_spatial_index = QgsSpatialIndex()
            prev_feats_lookup = {}
            for pf in prev_ea_layer.getFeatures():
                if not pf.hasGeometry() or pf.geometry().isEmpty():
                    continue
                pg = QgsGeometry(pf.geometry())
                if xform_prev_to_merged:
                    try:
                        pg.transform(xform_prev_to_merged)
                    except Exception:
                        pass
                new_pf = QgsFeature(pf)
                new_pf.setGeometry(pg)
                prev_spatial_index.addFeature(new_pf)
                prev_feats_lookup[new_pf.id()] = new_pf

            self.progress_bar.setValue(35)
            self._log("Matching merged polygons against previous EA reference geometries...")

            # Group unmerging: target_merged_id -> List of constituent previous EA features
            unmerge_plan = []  # list of (merged_feat_id, m_feat, [prev_feats])
            untouched_feats_count = 0

            for m_feat in merged_layer.getFeatures():
                m_id = m_feat.id()
                m_geom = m_feat.geometry()

                if not m_geom or m_geom.isEmpty():
                    continue

                if use_selected and m_id not in selected_merged_ids:
                    untouched_feats_count += 1
                    continue

                cand_prev_ids = prev_spatial_index.intersects(m_geom.boundingBox())

                matched_prev_feats = []
                for pid in cand_prev_ids:
                    pf = prev_feats_lookup.get(pid)
                    if not pf or not pf.geometry() or pf.geometry().isEmpty():
                        continue
                    pg = pf.geometry()
                    p_area = pg.area()
                    if p_area <= 0:
                        continue

                    # Spatial match test: significant intersection or centroid inside
                    if m_geom.intersects(pg):
                        inter = m_geom.intersection(pg)
                        if inter and not inter.isEmpty():
                            inter_area = inter.area()
                            overlap_ratio = inter_area / p_area
                            if overlap_ratio >= 0.40 or m_geom.contains(pg.centroid()) or m_geom.contains(pg.pointOnSurface()):
                                matched_prev_feats.append(pf)

                # Determine if this feature represents a merged EA or explicit selected unmerge
                if len(matched_prev_feats) >= 2 or (use_selected and len(matched_prev_feats) >= 1):
                    unmerge_plan.append((m_id, m_feat, matched_prev_feats))
                else:
                    untouched_feats_count += 1

            if not unmerge_plan:
                self._log(
                    "No merged features matching multiple previous EAs were found to unmerge.",
                    "WARNING",
                )
                self.status_banner.setText("No merged features detected to unmerge.")
                self.status_banner.setStyleSheet("color: #e67e22; font-weight: bold;")
                self.progress_bar.setValue(100)
                self.run_btn.setEnabled(True)
                self.close_btn.setEnabled(True)
                return

            self._log(
                f"Identified {len(unmerge_plan)} merged feature(s) to unmerge into "
                f"{sum(len(p[2]) for p in unmerge_plan)} individual previous EA polygons."
            )

            self.progress_bar.setValue(55)

            # Building Points Spatial Index and HH Resolution
            bldg_spatial_index = None
            bldg_lookup = {}
            bldg_hh_idx, bldg_hh_name = -1, ""

            if bldg_layer and bldg_layer.isValid() and bldg_layer.featureCount() > 0:
                bldg_hh_idx, bldg_hh_name = self._resolve_bldg_hh_field(bldg_layer)
                self._log(
                    f"Indexing building points from '{bldg_layer.name()}' "
                    f"(household field: '{bldg_hh_name or 'fallback 1/point'}')..."
                )
                bldg_spatial_index = QgsSpatialIndex()
                xform_bldg_to_merged = None
                if bldg_layer.crs().isValid() and merged_crs.isValid() and bldg_layer.crs() != merged_crs:
                    xform_bldg_to_merged = QgsCoordinateTransform(bldg_layer.crs(), merged_crs, QgsProject.instance())

                for bf in bldg_layer.getFeatures():
                    if not bf.hasGeometry() or bf.geometry().isEmpty():
                        continue
                    bg = QgsGeometry(bf.geometry())
                    if xform_bldg_to_merged:
                        try:
                            bg.transform(xform_bldg_to_merged)
                        except Exception:
                            pass
                    new_bf = QgsFeature(bf)
                    new_bf.setGeometry(bg)
                    bldg_spatial_index.addFeature(new_bf)
                    bldg_lookup[new_bf.id()] = new_bf

            self.progress_bar.setValue(70)
            self._log("Preparing field attributes and in-place layer update transaction...")

            # Ensure merged_layer has essential fields
            merged_fields = merged_layer.fields()
            merged_field_names_lower = [merged_fields.at(i).name().lower() for i in range(merged_fields.count())]
            fields_to_add = []
            if "hh_count" not in merged_field_names_lower:
                fields_to_add.append(create_qgs_field("hh_count", QVariant.Int))
            if "bldg_count" not in merged_field_names_lower:
                fields_to_add.append(create_qgs_field("bldg_count", QVariant.Int))
            if "new_ean" not in merged_field_names_lower:
                fields_to_add.append(create_qgs_field("new_ean", QVariant.String))
            if not any(f in merged_field_names_lower for f in ("ea_type", "eatype", "type")):
                fields_to_add.append(create_qgs_field("ea_type", QVariant.String))

            if fields_to_add:
                merged_layer.dataProvider().addAttributes(fields_to_add)
                merged_layer.updateFields()
                merged_fields = merged_layer.fields()

            # Start editing session on merged_layer
            if not merged_layer.isEditable():
                merged_layer.startEditing()

            deleted_ids = []
            new_features_to_add = []

            for m_id, m_feat, constituent_prev_feats in unmerge_plan:
                deleted_ids.append(m_id)

                for pf in constituent_prev_feats:
                    pg = pf.geometry()
                    if not pg or pg.isEmpty():
                        continue

                    # Create new feature matching merged_layer fields
                    new_feat = QgsFeature(merged_fields)
                    new_feat.setGeometry(pg)

                    # Copy over attributes from previous EA feature if field exists
                    prev_fields = pf.fields()
                    for pfld in prev_fields:
                        pf_name = pfld.name()
                        val = pf.attribute(pf_name)
                        if val is not None and val != NULL:
                            # Match case-insensitively to merged_layer fields
                            for mfld in merged_fields:
                                if mfld.name().lower() == pf_name.lower():
                                    new_feat.setAttribute(mfld.name(), val)
                                    break

                    # Recalculate bldg_count and hh_count from building points inside pg
                    inside_bldg_count = 0
                    inside_hh_float = 0.0

                    if bldg_spatial_index:
                        candidate_b_ids = bldg_spatial_index.intersects(pg.boundingBox())
                        for bid in candidate_b_ids:
                            bfeat = bldg_lookup.get(bid)
                            if not bfeat or not bfeat.geometry() or bfeat.geometry().isEmpty():
                                continue
                            bg = bfeat.geometry()
                            if pg.contains(bg) or pg.intersects(bg):
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

                    # Set calculated counts in new feature
                    for mfld in merged_fields:
                        m_name_lower = mfld.name().lower()
                        if m_name_lower in ("hh_count", "hhcount", "household"):
                            new_feat.setAttribute(mfld.name(), inside_hh_count)
                        elif m_name_lower in ("bldg_count", "bldgcount"):
                            new_feat.setAttribute(mfld.name(), inside_bldg_count)
                        elif m_name_lower in ("ea_type", "eatype", "type"):
                            if new_feat.attribute(mfld.name()) in (None, NULL, ""):
                                new_feat.setAttribute(mfld.name(), "Restored Previous EA")

                    new_features_to_add.append(new_feat)

            self.progress_bar.setValue(85)
            self._log(f"Deleting {len(deleted_ids)} merged feature(s) from target layer...")
            merged_layer.deleteFeatures(deleted_ids)

            self._log(f"Adding {len(new_features_to_add)} restored unmerged EA feature(s)...")
            merged_layer.addFeatures(new_features_to_add)

            # Commit changes
            success = merged_layer.commitChanges()
            if not success:
                errors = merged_layer.commitErrors()
                self._log(f"Commit error: {errors}", "ERROR")
                merged_layer.rollBack()
                QMessageBox.critical(self, "Commit Failed", f"Failed to commit changes to layer:\n{errors}")
                return

            self.progress_bar.setValue(100)
            merged_layer.updateExtents()
            merged_layer.triggerRepaint()

            out_total_count = merged_layer.featureCount()
            delta_count = len(new_features_to_add) - len(deleted_ids)

            self._log("Unmerge pipeline completed successfully!", "SUCCESS")
            self._log(f"Merged features removed: {len(deleted_ids)}")
            self._log(f"Constituent EAs restored: {len(new_features_to_add)}")
            self._log(f"Total layer features now: {out_total_count} (Delta: +{delta_count})")

            self.status_banner.setText(
                f"Unmerge successful! Restored {len(new_features_to_add)} previous EAs in '{merged_layer.name()}'."
            )
            self.status_banner.setStyleSheet("color: #27ae60; font-weight: bold;")

            QMessageBox.information(
                self,
                "Unmerge Complete",
                f"Successfully unmerged {len(deleted_ids)} merged EA polygon(s) into {len(new_features_to_add)} restored EAs.\n"
                f"Updated household and building counts have been recalculated in-place.",
            )

        except Exception as exc:
            import traceback
            err_msg = str(exc)
            tb = traceback.format_exc()
            self._log(f"Error during unmerge: {err_msg}", "ERROR")
            self._log(tb, "ERROR")
            if merged_layer and merged_layer.isEditable():
                merged_layer.rollBack()
            QMessageBox.critical(self, "Unmerge Error", f"An error occurred during unmerge:\n{err_msg}")
        finally:
            self.run_btn.setEnabled(True)
            self.close_btn.setEnabled(True)
