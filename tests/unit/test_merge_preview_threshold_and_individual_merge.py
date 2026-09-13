# -*- coding: utf-8 -*-
"""
Unit tests for Merge Preview Maximum Household Threshold Gating and Individual EA Merge Execution.
"""

import unittest
from unittest.mock import MagicMock, patch
from qgis.core import (
    QgsApplication,
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
    QgsField,
    QgsProject,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import QComboBox, QPushButton, QTableWidget, QTextEdit

from references.create_enumeration_area.dialog import EALauncherDialog


class TestMergePreviewThresholdAndIndividualMerge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qgs = QgsApplication([], False)
        cls.qgs.initQgis()

    @classmethod
    def tearDownClass(cls):
        cls.qgs.exitQgis()

    def tearDown(self):
        QgsProject.instance().clear()

    def test_sync_max_hh_and_merge_max_hh(self):
        """Verify two-way sync helper methods between max_hh_spin and merge_max_hh_spin."""
        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.max_hh_spin = MagicMock()
        mock_dlg.merge_max_hh_spin = MagicMock()

        # Tab 1 -> Tab 2 Sub-tab 2
        EALauncherDialog._sync_max_hh(mock_dlg, 250)
        mock_dlg.merge_max_hh_spin.setValue.assert_called_with(250)

        # Tab 2 Sub-tab 2 -> Tab 1
        EALauncherDialog._sync_merge_max_hh(mock_dlg, 350)
        mock_dlg.max_hh_spin.setValue.assert_called_with(350)

    def test_generate_preview_threshold_gating(self):
        """Verify that neighbors exceeding merge_max_hh are filtered out, leaving empty partners when over limit."""
        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.delineation_table = MagicMock()
        mock_dlg.merge_table = MagicMock()
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.merge_prev_ea_combo = MagicMock()
        mock_dlg.merge_ea_combo = MagicMock()
        mock_dlg.all_delineation_candidates = []
        mock_dlg.all_merge_candidates = []
        mock_dlg.all_merged_ea_candidates = []
        mock_dlg.min_hh_spin = MagicMock()
        mock_dlg.min_hh_spin.value.return_value = 99
        mock_dlg.max_hh_spin = MagicMock()
        mock_dlg.max_hh_spin.value.return_value = 300
        mock_dlg.merge_max_hh_spin = MagicMock()
        mock_dlg.merge_max_hh_spin.value.return_value = 300
        mock_dlg.kpi_delin_val = MagicMock()
        mock_dlg.kpi_merge_val = MagicMock()
        mock_dlg.kpi_merged_ea_val = MagicMock()
        mock_dlg.filter_previews = MagicMock()
        mock_dlg.output_folder_widget = MagicMock()
        mock_dlg.output_folder_widget.filePath.return_value = "C:/test"
        mock_dlg.merge_output_folder_widget = MagicMock()
        mock_dlg.merge_output_folder_widget.filePath.return_value = ""
        mock_dlg._get_ea_name = lambda feat, ean, fields: f"EA {ean}"

        # 1. Previous EA layer with Partner 1 (100 HH) and Partner 2 (150 HH)
        prev_ea_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Prev_EAs", "memory")
        pr = prev_ea_layer.dataProvider()
        pr.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("geocode", QVariant.String),
            QgsField("barangay", QVariant.String),
            QgsField("hh_count", QVariant.Double)
        ])
        prev_ea_layer.updateFields()

        f1 = QgsFeature(prev_ea_layer.fields())
        f1.setAttributes(["01701001001", "01701001", "Poblacion", 100.0])
        f1.setGeometry(QgsGeometry.fromRect(QgsRectangle(0, 0, 1, 1)))

        f2 = QgsFeature(prev_ea_layer.fields())
        f2.setAttributes(["01701001002", "01701001", "Poblacion", 150.0])
        f2.setGeometry(QgsGeometry.fromRect(QgsRectangle(1, 0, 2, 1)))
        pr.addFeatures([f1, f2])

        # 2. Merged EA layer with candidate (180 HH)
        merge_ea_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Merge_EA", "memory")
        mpr = merge_ea_layer.dataProvider()
        mpr.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("geocode", QVariant.String),
            QgsField("barangay", QVariant.String),
            QgsField("hh_count", QVariant.Double)
        ])
        merge_ea_layer.updateFields()

        fcand = QgsFeature(merge_ea_layer.fields())
        fcand.setAttributes(["01701001099", "01701001", "Poblacion", 180.0])
        fcand.setGeometry(QgsGeometry.fromRect(QgsRectangle(0, 1, 1, 2)))
        mpr.addFeatures([fcand])

        mock_dlg._safe_get_layer.side_effect = lambda combo: (
            prev_ea_layer if combo in (mock_dlg.prev_ea_combo, getattr(mock_dlg, 'merge_prev_ea_combo', None))
            else merge_ea_layer
        )

        # Case A: max_hh is 300
        # Partner 1 (100 HH) -> Combined = 280 <= 300 (VALID)
        # Partner 2 (150 HH) -> Combined = 330 > 300 (EXCLUDED)
        EALauncherDialog.generate_preview(mock_dlg)
        self.assertEqual(len(mock_dlg.all_merged_ea_candidates), 1)
        cand_row = mock_dlg.all_merged_ea_candidates[0]
        neighbors = cand_row[5]
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0][0], "01701001001")

        # Case B: max_hh is 250
        # Partner 1 (100 HH) -> Combined = 280 > 250 (EXCLUDED)
        # Partner 2 (150 HH) -> Combined = 330 > 250 (EXCLUDED)
        # Neighbors list must be empty []
        mock_dlg.all_merged_ea_candidates.clear()
        mock_dlg.merge_max_hh_spin.value.return_value = 250
        EALauncherDialog.generate_preview(mock_dlg)
        self.assertEqual(len(mock_dlg.all_merged_ea_candidates), 1)
        cand_row_250 = mock_dlg.all_merged_ea_candidates[0]
        self.assertEqual(cand_row_250[5], [])

    def test_populate_table_rows_empty_partner_dropdown_and_action_button(self):
        """Verify that when partners exceed threshold (empty neighbors), partner combo is empty/disabled, and Action button is disabled."""
        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.current_theme = "light"
        table = EALauncherDialog._create_preview_table(mock_dlg, include_merge_partner=True)

        # 1. Candidate with no eligible partners (empty list)
        candidates_empty = [
            ("01701001099", "EA 99", "Poblacion", 280.0, "Candidate (280 HH)", [])
        ]
        EALauncherDialog._populate_table_rows(mock_dlg, table, candidates_empty, is_delineation=False)

        combo_empty = table.cellWidget(0, 5)
        self.assertIsInstance(combo_empty, QComboBox)
        self.assertEqual(combo_empty.count(), 0)
        self.assertFalse(combo_empty.isEnabled())

        # Total HH cell shows "—"
        total_cell = table.item(0, 6)
        self.assertIsNotNone(total_cell)
        self.assertEqual(total_cell.text(), "—")

        # Action button is disabled
        action_btn_disabled = table.cellWidget(0, 7)
        self.assertIsInstance(action_btn_disabled, QPushButton)
        self.assertFalse(action_btn_disabled.isEnabled())

        # 2. Candidate with eligible partner
        candidates_with_partner = [
            ("01701001099", "EA 99", "Poblacion", 80.0, "Initiator (<= 99 HH)", [("01701001001", 100.0)])
        ]
        EALauncherDialog._populate_table_rows(mock_dlg, table, candidates_with_partner, is_delineation=False)

        combo_valid = table.cellWidget(0, 5)
        self.assertIsInstance(combo_valid, QComboBox)
        self.assertEqual(combo_valid.count(), 1)
        self.assertTrue(combo_valid.isEnabled())
        self.assertEqual(combo_valid.currentText(), "01701001001")

        total_cell_valid = table.item(0, 6)
        self.assertEqual(total_cell_valid.text(), "180")

        action_btn_enabled = table.cellWidget(0, 7)
        self.assertIsInstance(action_btn_enabled, QPushButton)
        self.assertTrue(action_btn_enabled.isEnabled())

    def test_individual_merge_row_logic(self):
        """Verify _merge_individual_row correctly combines geometry, sums HH, adds feature to target layer, and provides UI feedback."""
        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.merge_prev_ea_combo = MagicMock()
        mock_dlg.merge_ea_combo = MagicMock()
        mock_dlg._find_feature_in_layer = EALauncherDialog._find_feature_in_layer
        mock_dlg._extract_5digit_geocode.return_value = "01701"
        mock_dlg.merge_output_folder_widget = MagicMock()
        mock_dlg.merge_output_folder_widget.filePath.return_value = ""
        mock_dlg.output_folder_widget = MagicMock()
        mock_dlg.output_folder_widget.filePath.return_value = ""
        mock_dlg.merge_log_console = QTextEdit()

        prev_ea_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Prev_EAs", "memory")
        pr = prev_ea_layer.dataProvider()
        pr.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("geocode", QVariant.String),
            QgsField("barangay", QVariant.String),
            QgsField("hh_count", QVariant.Double)
        ])
        prev_ea_layer.updateFields()

        f_partner = QgsFeature(prev_ea_layer.fields())
        f_partner.setAttributes(["01701001001", "01701001", "Poblacion", 80.0])
        f_partner.setGeometry(QgsGeometry.fromRect(QgsRectangle(0, 0, 1, 1)))
        pr.addFeatures([f_partner])

        merge_ea_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Merge_EA", "memory")
        mpr = merge_ea_layer.dataProvider()
        mpr.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("geocode", QVariant.String),
            QgsField("barangay", QVariant.String),
            QgsField("hh_count", QVariant.Double)
        ])
        merge_ea_layer.updateFields()

        f_cand = QgsFeature(merge_ea_layer.fields())
        f_cand.setAttributes(["01701001099", "01701001", "Poblacion", 40.0])
        f_cand.setGeometry(QgsGeometry.fromRect(QgsRectangle(1, 0, 2, 1)))
        mpr.addFeatures([f_cand])

        mock_dlg._safe_get_layer.side_effect = lambda combo: (
            prev_ea_layer if combo in (mock_dlg.prev_ea_combo, getattr(mock_dlg, 'merge_prev_ea_combo', None))
            else merge_ea_layer
        )

        table = EALauncherDialog._create_preview_table(mock_dlg, include_merge_partner=True)
        candidates = [
            ("01701001099", "EA 99", "Poblacion", 40.0, "Initiator (<= 99 HH)", [("01701001001", 80.0)])
        ]
        EALauncherDialog._populate_table_rows(mock_dlg, table, candidates, is_delineation=False)

        partner_combo = table.cellWidget(0, 5)
        btn_merge = table.cellWidget(0, 7)

        # Execute individual merge
        EALauncherDialog._merge_individual_row(
            mock_dlg, 0, "01701001099", "EA 99", "Poblacion", 40.0, partner_combo, table, btn_merge
        )

        # Verify UI state updates
        self.assertFalse(btn_merge.isEnabled())
        self.assertEqual(btn_merge.text(), "Merged")
        self.assertEqual(table.item(0, 4).text(), "Merged ✓")
        self.assertFalse(partner_combo.isEnabled())

        # Verify target layer creation in QgsProject
        merged_layers = QgsProject.instance().mapLayersByName("01701_merged_ea2026")
        self.assertTrue(len(merged_layers) >= 1)
        merged_lyr = merged_layers[0]

        self.assertEqual(merged_lyr.featureCount(), 1)
        out_feat = next(merged_lyr.getFeatures())
        self.assertEqual(out_feat["ean"], "01701001001")
        self.assertEqual(out_feat["hh_count"], 120.0)
        self.assertEqual(out_feat["ea_type"], "MERGED")
        self.assertIn("01701001099 + 01701001001", out_feat["remarks"])

        # Geometry bounding box covers combined extent from x=0 to x=2
        bbox = out_feat.geometry().boundingBox()
        self.assertAlmostEqual(bbox.xMinimum(), 0.0, places=3)
        self.assertAlmostEqual(bbox.xMaximum(), 2.0, places=3)

        # Log console received success message
        log_text = mock_dlg.merge_log_console.toPlainText()
        self.assertIn("[MERGE SUCCESS]", log_text)
        self.assertIn("01701001099", log_text)
        self.assertIn("01701001001", log_text)
        self.assertIn("Total HH: 120", log_text)
        self.assertIn("Total Buildings: 0", log_text)

    def test_find_feature_in_layer_14digit_geocode_and_short_ean(self):
        """Verify _find_feature_in_layer correctly resolves 14-digit geocodes matching 6-digit EANs or geocode fields."""
        layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Test_Layer", "memory")
        pr = layer.dataProvider()
        pr.addAttributes([
            QgsField("geocode", QVariant.String),
            QgsField("ean", QVariant.String),
            QgsField("barangay", QVariant.String)
        ])
        layer.updateFields()

        feat = QgsFeature(layer.fields())
        feat.setAttributes(["01718014001000", "001000", "San Pedro"])
        feat.setGeometry(QgsGeometry.fromRect(QgsRectangle(0, 0, 1, 1)))
        pr.addFeatures([feat])

        # 1. Exact match by full 14-digit geocode
        f_by_geocode = EALauncherDialog._find_feature_in_layer(layer, "01718014001000")
        self.assertIsNotNone(f_by_geocode)
        self.assertEqual(f_by_geocode["ean"], "001000")

        # 2. Exact match by short 6-digit EAN
        f_by_ean = EALauncherDialog._find_feature_in_layer(layer, "001000")
        self.assertIsNotNone(f_by_ean)
        self.assertEqual(f_by_ean["geocode"], "01718014001000")

        # 3. Layer having only short EAN field searched with 14-digit target
        layer_short = QgsVectorLayer("Polygon?crs=epsg:4326", "Short_Layer", "memory")
        layer_short.dataProvider().addAttributes([
            QgsField("ean", QVariant.String)
        ])
        layer_short.updateFields()
        f_short = QgsFeature(layer_short.fields())
        f_short.setAttributes(["001000"])
        f_short.setGeometry(QgsGeometry.fromRect(QgsRectangle(0, 0, 1, 1)))
        layer_short.dataProvider().addFeatures([f_short])

        f_resolved = EALauncherDialog._find_feature_in_layer(layer_short, "01718014001000")
        self.assertIsNotNone(f_resolved)
        self.assertEqual(f_resolved["ean"], "001000")

    def test_individual_merge_with_integer_remarks_and_in_place_update(self):
        """Verify _merge_individual_row safely updates in-place when target_layer already has candidate and has integer remarks."""
        QgsProject.instance().removeAllMapLayers()

        # Existing target layer with integer remarks
        target_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "01701_merged_ea2026", "memory")
        pr_target = target_layer.dataProvider()
        pr_target.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("geocode", QVariant.String),
            QgsField("barangay", QVariant.String),
            QgsField("hh_count", QVariant.Double),
            QgsField("remarks", QVariant.Int)
        ])
        target_layer.updateFields()

        # Candidate is already inside target_layer (x: 0->1)
        f_cand = QgsFeature(target_layer.fields())
        f_cand.setAttributes(["01701001099", "01701001099", "Poblacion", 40.0, 0])
        f_cand.setGeometry(QgsGeometry.fromRect(QgsRectangle(0, 0, 1, 1)))
        pr_target.addFeatures([f_cand])
        QgsProject.instance().addMapLayer(target_layer)

        # Partner layer (x: 1->2)
        partner_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Prev_EA", "memory")
        pr_partner = partner_layer.dataProvider()
        pr_partner.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("geocode", QVariant.String),
            QgsField("barangay", QVariant.String),
            QgsField("hh_count", QVariant.Double)
        ])
        partner_layer.updateFields()
        f_partner = QgsFeature(partner_layer.fields())
        f_partner.setAttributes(["01701001001", "01701001001", "Poblacion", 80.0])
        f_partner.setGeometry(QgsGeometry.fromRect(QgsRectangle(1, 0, 2, 1)))
        pr_partner.addFeatures([f_partner])
        QgsProject.instance().addMapLayer(partner_layer)

        mock_dlg = MagicMock()
        mock_dlg.merge_ea_combo = MagicMock()
        mock_dlg.merge_prev_ea_combo = MagicMock()
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.merge_log_console = QTextEdit()
        mock_dlg.merge_output_folder_widget = MagicMock()
        mock_dlg.merge_output_folder_widget.filePath.return_value = ""
        mock_dlg.output_folder_widget = MagicMock()
        mock_dlg.output_folder_widget.filePath.return_value = ""
        mock_dlg.iface = None
        mock_dlg._extract_5digit_geocode.return_value = "01701"
        mock_dlg._find_feature_in_layer = EALauncherDialog._find_feature_in_layer
        mock_dlg._safe_get_layer = lambda combo: (
            partner_layer if combo in (mock_dlg.prev_ea_combo, getattr(mock_dlg, 'merge_prev_ea_combo', None))
            else target_layer
        )

        table = EALauncherDialog._create_preview_table(mock_dlg, include_merge_partner=True)
        candidates = [
            ("01701001099", "EA 99", "Poblacion", 40.0, "Initiator (<= 99 HH)", [("01701001001", 80.0)])
        ]
        EALauncherDialog._populate_table_rows(mock_dlg, table, candidates, is_delineation=False)
        partner_combo = table.cellWidget(0, 5)
        btn_merge = table.cellWidget(0, 7)

        # Merge candidate into partner
        EALauncherDialog._merge_individual_row(
            mock_dlg, 0, "01701001099", "EA 99", "Poblacion", 40.0, partner_combo, table, btn_merge
        )

        self.assertEqual(target_layer.featureCount(), 1)
        feat = next(target_layer.getFeatures())
        self.assertEqual(feat["hh_count"], 120.0)
        # Original EAN is preserved, not overwritten
        self.assertEqual(feat["ean"], "01701001099")
        # new_ean holds highest household count EAN (partner 80 > candidate 40)
        self.assertEqual(feat["new_ean"], "01701001001")
        # ea_type is set to MERGED
        self.assertEqual(feat["ea_type"], "MERGED")
        # Remarks must be 1 (integer field safety)
        self.assertEqual(feat["remarks"], 1)
        # Geometry must span x=0 to x=2
        bbox = feat.geometry().boundingBox()
        self.assertAlmostEqual(bbox.xMinimum(), 0.0, places=3)
        self.assertAlmostEqual(bbox.xMaximum(), 2.0, places=3)

    def test_individual_merge_with_length_restricted_remarks(self):
        """Verify _merge_individual_row truncates or fits remarks when field length is limited."""
        QgsProject.instance().removeAllMapLayers()

        target_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "01701_merged_ea2026", "memory")
        pr_target = target_layer.dataProvider()
        pr_target.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("hh_count", QVariant.Double),
            QgsField("remarks", QVariant.String, len=15)
        ])
        target_layer.updateFields()
        QgsProject.instance().addMapLayer(target_layer)

        prev_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Prev_EA", "memory")
        pr_prev = prev_layer.dataProvider()
        pr_prev.addAttributes([QgsField("ean", QVariant.String), QgsField("hh_count", QVariant.Double)])
        prev_layer.updateFields()
        f_cand = QgsFeature(prev_layer.fields())
        f_cand.setAttributes(["01701001099", 40.0])
        f_cand.setGeometry(QgsGeometry.fromRect(QgsRectangle(0, 0, 1, 1)))
        f_partner = QgsFeature(prev_layer.fields())
        f_partner.setAttributes(["01701001001", 80.0])
        f_partner.setGeometry(QgsGeometry.fromRect(QgsRectangle(1, 0, 2, 1)))
        pr_prev.addFeatures([f_cand, f_partner])
        QgsProject.instance().addMapLayer(prev_layer)

        mock_dlg = MagicMock()
        mock_dlg.merge_ea_combo = MagicMock()
        mock_dlg.merge_prev_ea_combo = MagicMock()
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.merge_log_console = QTextEdit()
        mock_dlg.merge_output_folder_widget = MagicMock()
        mock_dlg.merge_output_folder_widget.filePath.return_value = ""
        mock_dlg.output_folder_widget = MagicMock()
        mock_dlg.output_folder_widget.filePath.return_value = ""
        mock_dlg.iface = None
        mock_dlg._extract_5digit_geocode.return_value = "01701"
        mock_dlg._find_feature_in_layer = EALauncherDialog._find_feature_in_layer
        mock_dlg._safe_get_layer = lambda combo: prev_layer

        table = EALauncherDialog._create_preview_table(mock_dlg, include_merge_partner=True)
        candidates = [
            ("01701001099", "EA 99", "Poblacion", 40.0, "Initiator (<= 99 HH)", [("01701001001", 80.0)])
        ]
        EALauncherDialog._populate_table_rows(mock_dlg, table, candidates, is_delineation=False)
        partner_combo = table.cellWidget(0, 5)
        btn_merge = table.cellWidget(0, 7)

        EALauncherDialog._merge_individual_row(
            mock_dlg, 0, "01701001099", "EA 99", "Poblacion", 40.0, partner_combo, table, btn_merge
        )

        self.assertEqual(target_layer.featureCount(), 1)
        feat = next(target_layer.getFeatures())
        self.assertTrue(len(str(feat["remarks"])) <= 15)

    def test_individual_merge_with_building_points_spatial_aggregation(self):
        """Verify _merge_individual_row computes total building points and sums est_hhcount within merged polygon."""
        QgsProject.instance().removeAllMapLayers()

        prev_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Prev_EA", "memory")
        pr_prev = prev_layer.dataProvider()
        pr_prev.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("geocode", QVariant.String),
            QgsField("barangay", QVariant.String),
            QgsField("hh_count", QVariant.Double),
            QgsField("bldg_count", QVariant.Int)
        ])
        prev_layer.updateFields()

        # Candidate feature: [0, 0] to [1, 1]
        f_cand = QgsFeature(prev_layer.fields())
        f_cand.setAttributes(["01701001099", "01701001", "Poblacion", 10.0, 1])
        f_cand.setGeometry(QgsGeometry.fromRect(QgsRectangle(0, 0, 1, 1)))

        # Partner feature: [1, 0] to [2, 1]
        f_partner = QgsFeature(prev_layer.fields())
        f_partner.setAttributes(["01701001001", "01701001", "Poblacion", 20.0, 2])
        f_partner.setGeometry(QgsGeometry.fromRect(QgsRectangle(1, 0, 2, 1)))
        pr_prev.addFeatures([f_cand, f_partner])
        QgsProject.instance().addMapLayer(prev_layer)

        # Building Points layer
        bldg_layer = QgsVectorLayer("Point?crs=epsg:4326", "Building_Points", "memory")
        pr_bldg = bldg_layer.dataProvider()
        pr_bldg.addAttributes([
            QgsField("building_id", QVariant.Int),
            QgsField("est_hhcount", QVariant.Double)
        ])
        bldg_layer.updateFields()

        # Building 1: inside candidate polygon (0.5, 0.5) with 3 households
        b1 = QgsFeature(bldg_layer.fields())
        b1.setAttributes([1, 3.0])
        b1.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(0.5, 0.5)))

        # Building 2: inside partner polygon (1.5, 0.5) with 5 households
        b2 = QgsFeature(bldg_layer.fields())
        b2.setAttributes([2, 5.0])
        b2.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(1.5, 0.5)))

        # Building 3: inside merged polygon (1.2, 0.8) with 2 households
        b3 = QgsFeature(bldg_layer.fields())
        b3.setAttributes([3, 2.0])
        b3.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(1.2, 0.8)))

        # Building 4: outside merged polygon (5.0, 5.0) with 10 households
        b4 = QgsFeature(bldg_layer.fields())
        b4.setAttributes([4, 10.0])
        b4.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(5.0, 5.0)))

        pr_bldg.addFeatures([b1, b2, b3, b4])
        QgsProject.instance().addMapLayer(bldg_layer)

        mock_dlg = MagicMock()
        mock_dlg.merge_ea_combo = MagicMock()
        mock_dlg.merge_prev_ea_combo = MagicMock()
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.bldg_combo = MagicMock()
        mock_dlg.merge_bldg_combo = MagicMock()
        mock_dlg.merge_log_console = QTextEdit()
        mock_dlg.merge_output_folder_widget = MagicMock()
        mock_dlg.merge_output_folder_widget.filePath.return_value = ""
        mock_dlg.output_folder_widget = MagicMock()
        mock_dlg.output_folder_widget.filePath.return_value = ""
        mock_dlg.iface = None
        mock_dlg._extract_5digit_geocode.return_value = "01701"
        mock_dlg._find_feature_in_layer = EALauncherDialog._find_feature_in_layer

        def _safe_get_layer(combo):
            if combo in (mock_dlg.bldg_combo, mock_dlg.merge_bldg_combo):
                return bldg_layer
            return prev_layer

        mock_dlg._safe_get_layer = _safe_get_layer

        table = EALauncherDialog._create_preview_table(mock_dlg, include_merge_partner=True)
        candidates = [
            ("01701001099", "EA 99", "Poblacion", 10.0, "Initiator (<= 99 HH)", [("01701001001", 20.0)])
        ]
        EALauncherDialog._populate_table_rows(mock_dlg, table, candidates, is_delineation=False)
        partner_combo = table.cellWidget(0, 5)
        btn_merge = table.cellWidget(0, 7)

        # Execute merge
        EALauncherDialog._merge_individual_row(
            mock_dlg, 0, "01701001099", "EA 99", "Poblacion", 10.0, partner_combo, table, btn_merge
        )

        merged_layers = QgsProject.instance().mapLayersByName("01701_merged_ea2026")
        self.assertTrue(len(merged_layers) >= 1)
        merged_lyr = merged_layers[0]

        self.assertEqual(merged_lyr.featureCount(), 1)
        out_feat = next(merged_lyr.getFeatures())

        # Total buildings inside merged polygon: b1, b2, b3 = 3 buildings
        self.assertEqual(out_feat["bldg_count"], 3)
        self.assertIsInstance(out_feat["bldg_count"], int)
        # Total households from building points: 3.0 + 5.0 + 2.0 = 10 (whole number)
        self.assertEqual(out_feat["hh_count"], 10)
        self.assertIsInstance(out_feat["hh_count"], int)

        log_text = mock_dlg.merge_log_console.toPlainText()
        self.assertIn("Total HH: 10", log_text)
        self.assertIn("Total Buildings: 3", log_text)

    def test_individual_merge_imputes_candidate_ean_when_candidate_has_higher_hh(self):
        """Verify _merge_individual_row preserves ean and imputes candidate's EAN into new_ean when candidate has higher HH."""
        QgsProject.instance().removeAllMapLayers()

        prev_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Prev_EA", "memory")
        pr_prev = prev_layer.dataProvider()
        pr_prev.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("geocode", QVariant.String),
            QgsField("barangay", QVariant.String),
            QgsField("hh_count", QVariant.Double),
            QgsField("bldg_count", QVariant.Int)
        ])
        prev_layer.updateFields()

        # Candidate feature (for merging): 120 HH
        f_cand = QgsFeature(prev_layer.fields())
        f_cand.setAttributes(["01701001099", "01701001", "Poblacion", 120.0, 5])
        f_cand.setGeometry(QgsGeometry.fromRect(QgsRectangle(0, 0, 1, 1)))

        # Partner feature (merge partner): 30 HH
        f_partner = QgsFeature(prev_layer.fields())
        f_partner.setAttributes(["01701001001", "01701001", "Poblacion", 30.0, 2])
        f_partner.setGeometry(QgsGeometry.fromRect(QgsRectangle(1, 0, 2, 1)))
        pr_prev.addFeatures([f_cand, f_partner])
        QgsProject.instance().addMapLayer(prev_layer)

        mock_dlg = MagicMock()
        mock_dlg.merge_ea_combo = MagicMock()
        mock_dlg.merge_prev_ea_combo = MagicMock()
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.bldg_combo = MagicMock()
        mock_dlg.merge_bldg_combo = MagicMock()
        mock_dlg.merge_log_console = QTextEdit()
        mock_dlg.merge_output_folder_widget = MagicMock()
        mock_dlg.merge_output_folder_widget.filePath.return_value = ""
        mock_dlg.output_folder_widget = MagicMock()
        mock_dlg.output_folder_widget.filePath.return_value = ""
        mock_dlg.iface = None
        mock_dlg._extract_5digit_geocode.return_value = "01701"
        mock_dlg._find_feature_in_layer = EALauncherDialog._find_feature_in_layer
        mock_dlg._safe_get_layer = lambda combo: prev_layer

        table = EALauncherDialog._create_preview_table(mock_dlg, include_merge_partner=True)
        candidates = [
            ("01701001099", "EA 99", "Poblacion", 120.0, "Initiator (<= 99 HH)", [("01701001001", 30.0)])
        ]
        EALauncherDialog._populate_table_rows(mock_dlg, table, candidates, is_delineation=False)
        partner_combo = table.cellWidget(0, 5)
        btn_merge = table.cellWidget(0, 7)

        # Merge candidate (120 HH) and partner (30 HH)
        EALauncherDialog._merge_individual_row(
            mock_dlg, 0, "01701001099", "EA 99", "Poblacion", 120.0, partner_combo, table, btn_merge
        )

        merged_layers = QgsProject.instance().mapLayersByName("01701_merged_ea2026")
        self.assertTrue(len(merged_layers) >= 1)
        merged_lyr = merged_layers[0]

        self.assertEqual(merged_lyr.featureCount(), 1)
        out_feat = next(merged_lyr.getFeatures())

        # Original ean is preserved from partner_feat ("01701001001")
        self.assertEqual(out_feat["ean"], "01701001001")
        # new_ean is imputed with the higher HH count EAN (candidate "01701001099" with 120 HH > partner with 30 HH)
        self.assertEqual(out_feat["new_ean"], "01701001099")
        self.assertEqual(out_feat["hh_count"], 150)

    def test_individual_merge_preserves_hhcount_and_only_updates_hh_count(self):
        """Verify that hhcount remains unchanged and only hh_count is updated during merge."""
        QgsProject.instance().removeAllMapLayers()

        prev_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Prev_EA", "memory")
        pr_prev = prev_layer.dataProvider()
        pr_prev.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("geocode", QVariant.String),
            QgsField("barangay", QVariant.String),
            QgsField("hhcount", QVariant.Double),
            QgsField("hh_count", QVariant.Double),
            QgsField("bldg_count", QVariant.Int)
        ])
        prev_layer.updateFields()

        # Candidate feature: original hhcount = 77.0, hh_count = 40.0
        f_cand = QgsFeature(prev_layer.fields())
        f_cand.setAttributes(["01701001099", "01701001", "Poblacion", 77.0, 40.0, 2])
        f_cand.setGeometry(QgsGeometry.fromRect(QgsRectangle(0, 0, 1, 1)))

        # Partner feature: original hhcount = 55.0, hh_count = 30.0
        f_partner = QgsFeature(prev_layer.fields())
        f_partner.setAttributes(["01701001001", "01701001", "Poblacion", 55.0, 30.0, 3])
        f_partner.setGeometry(QgsGeometry.fromRect(QgsRectangle(1, 0, 2, 1)))
        pr_prev.addFeatures([f_cand, f_partner])
        QgsProject.instance().addMapLayer(prev_layer)

        mock_dlg = MagicMock()
        mock_dlg.merge_ea_combo = MagicMock()
        mock_dlg.merge_prev_ea_combo = MagicMock()
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.bldg_combo = MagicMock()
        mock_dlg.merge_bldg_combo = MagicMock()
        mock_dlg.merge_log_console = QTextEdit()
        mock_dlg.merge_output_folder_widget = MagicMock()
        mock_dlg.merge_output_folder_widget.filePath.return_value = ""
        mock_dlg.output_folder_widget = MagicMock()
        mock_dlg.output_folder_widget.filePath.return_value = ""
        mock_dlg.iface = None
        mock_dlg._extract_5digit_geocode.return_value = "01701"
        mock_dlg._find_feature_in_layer = EALauncherDialog._find_feature_in_layer
        mock_dlg._safe_get_layer = lambda combo: prev_layer

        table = EALauncherDialog._create_preview_table(mock_dlg, include_merge_partner=True)
        candidates = [
            ("01701001099", "EA 99", "Poblacion", 40.0, "Initiator (<= 99 HH)", [("01701001001", 30.0)])
        ]
        EALauncherDialog._populate_table_rows(mock_dlg, table, candidates, is_delineation=False)
        partner_combo = table.cellWidget(0, 5)
        btn_merge = table.cellWidget(0, 7)

        # Merge candidate (40 HH) and partner (30 HH) -> Total = 70 HH
        EALauncherDialog._merge_individual_row(
            mock_dlg, 0, "01701001099", "EA 99", "Poblacion", 40.0, partner_combo, table, btn_merge
        )

        merged_layers = QgsProject.instance().mapLayersByName("01701_merged_ea2026")
        self.assertTrue(len(merged_layers) >= 1)
        merged_lyr = merged_layers[0]

        self.assertEqual(merged_lyr.featureCount(), 1)
        out_feat = next(merged_lyr.getFeatures())

        # ONLY hh_count is updated to the merged total
        self.assertEqual(out_feat["hh_count"], 70)
        # hhcount is NOT changed, preserving original partner value
        self.assertEqual(out_feat["hhcount"], 55.0)
        # ea_type is set to MERGED
        self.assertEqual(out_feat["ea_type"], "MERGED")

    def test_individual_merge_updates_ea_type_to_merged_on_existing_feature(self):
        """Verify that ea_type is explicitly updated to MERGED even when an existing feature had RETAINED."""
        QgsProject.instance().removeAllMapLayers()

        prev_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Prev_EA", "memory")
        pr_prev = prev_layer.dataProvider()
        pr_prev.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("geocode", QVariant.String),
            QgsField("barangay", QVariant.String),
            QgsField("hh_count", QVariant.Double),
            QgsField("ea_type", QVariant.String),
        ])
        prev_layer.updateFields()

        f_cand = QgsFeature(prev_layer.fields())
        f_cand.setAttributes(["01701001099", "01701001", "Poblacion", 45.0, "RETAINED"])
        f_cand.setGeometry(QgsGeometry.fromRect(QgsRectangle(0, 0, 1, 1)))

        f_partner = QgsFeature(prev_layer.fields())
        f_partner.setAttributes(["01701001001", "01701001", "Poblacion", 35.0, "RETAINED"])
        f_partner.setGeometry(QgsGeometry.fromRect(QgsRectangle(1, 0, 2, 1)))
        pr_prev.addFeatures([f_cand, f_partner])
        QgsProject.instance().addMapLayer(prev_layer)

        # Pre-existing target layer with candidate feature having ea_type = "RETAINED"
        target_layer = QgsVectorLayer("MultiPolygon?crs=epsg:4326", "01701_merged_ea2026", "memory")
        pr_target = target_layer.dataProvider()
        pr_target.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("geocode", QVariant.String),
            QgsField("barangay", QVariant.String),
            QgsField("hh_count", QVariant.Double),
            QgsField("new_ean", QVariant.String),
            QgsField("ea_type", QVariant.String),
            QgsField("remarks", QVariant.String),
        ])
        target_layer.updateFields()

        f_existing = QgsFeature(target_layer.fields())
        f_existing.setAttributes(["01701001099", "01701001", "Poblacion", 45.0, "", "RETAINED", ""])
        f_existing.setGeometry(QgsGeometry.fromRect(QgsRectangle(0, 0, 1, 1)))
        pr_target.addFeatures([f_existing])
        QgsProject.instance().addMapLayer(target_layer)

        mock_dlg = MagicMock()
        mock_dlg.merge_ea_combo = MagicMock()
        mock_dlg.merge_prev_ea_combo = MagicMock()
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.bldg_combo = MagicMock()
        mock_dlg.merge_bldg_combo = MagicMock()
        mock_dlg.merge_log_console = QTextEdit()
        mock_dlg.merge_output_folder_widget = MagicMock()
        mock_dlg.merge_output_folder_widget.filePath.return_value = ""
        mock_dlg.output_folder_widget = MagicMock()
        mock_dlg.output_folder_widget.filePath.return_value = ""
        mock_dlg.iface = None
        mock_dlg._extract_5digit_geocode.return_value = "01701"
        mock_dlg._find_feature_in_layer = EALauncherDialog._find_feature_in_layer
        mock_dlg._safe_get_layer = lambda combo: prev_layer

        table = EALauncherDialog._create_preview_table(mock_dlg, include_merge_partner=True)
        candidates = [
            ("01701001099", "EA 99", "Poblacion", 45.0, "Initiator (<= 99 HH)", [("01701001001", 35.0)])
        ]
        EALauncherDialog._populate_table_rows(mock_dlg, table, candidates, is_delineation=False)
        partner_combo = table.cellWidget(0, 5)
        btn_merge = table.cellWidget(0, 7)

        # Execute merge on existing feature
        EALauncherDialog._merge_individual_row(
            mock_dlg, 0, "01701001099", "EA 99", "Poblacion", 45.0, partner_combo, table, btn_merge
        )

        updated_feat = next(target_layer.getFeatures())
        self.assertEqual(updated_feat["ean"], "01701001099")
        self.assertEqual(updated_feat["new_ean"], "01701001099")
        self.assertEqual(updated_feat["hh_count"], 80)
        # Verify ea_type was updated from RETAINED to MERGED
        self.assertEqual(updated_feat["ea_type"], "MERGED")


if __name__ == "__main__":
    unittest.main()
