# -*- coding: utf-8 -*-
"""
Unit test module for EA Delineation and Merging dialog refresh functionality.
Verifies that opening/refreshing the dialog resets all inputs, process states,
logs, KPI cards, results tables, and summaries across Tab 1, Tab 2, and Tab 3.
"""

import unittest
from unittest.mock import MagicMock, patch
from tests.mocks.qgis_mock import setup_qgis_mock_if_needed, MockGenericClass

setup_qgis_mock_if_needed()


class TestEADialogRefresh(unittest.TestCase):
    """Test suite for EALauncherDialog refresh lifecycle methods."""

    def test_refresh_all_methods_exist(self):
        """Verify that refresh methods exist on EALauncherDialog class."""
        from references.create_enumeration_area.dialog import EALauncherDialog

        self.assertTrue(hasattr(EALauncherDialog, "refresh_all"), "EALauncherDialog must have refresh_all method")
        self.assertTrue(hasattr(EALauncherDialog, "_pre_ea_refresh"), "EALauncherDialog must have _pre_ea_refresh method")
        self.assertTrue(hasattr(EALauncherDialog, "_create_ea_refresh"), "EALauncherDialog must have _create_ea_refresh method")
        self.assertTrue(hasattr(EALauncherDialog, "_ea_merge_refresh"), "EALauncherDialog must have _ea_merge_refresh method")

    def test_refresh_all_calls_sub_refreshes(self):
        """Verify that refresh_all calls _pre_ea_refresh, _create_ea_refresh, and _ea_merge_refresh."""
        from references.create_enumeration_area.dialog import EALauncherDialog

        # Create a mock instance with methods mocked
        mock_dlg = MagicMock(spec=EALauncherDialog)
        # Bind the real refresh_all method to mock_dlg
        EALauncherDialog.refresh_all(mock_dlg)

        mock_dlg._pre_ea_refresh.assert_called_once()
        mock_dlg._create_ea_refresh.assert_called_once()
        mock_dlg._ea_merge_refresh.assert_called_once()

    def test_pre_ea_refresh_resets_state(self):
        """Verify that _pre_ea_refresh resets controls, logs, tables, and runs auto-detection."""
        from references.create_enumeration_area.dialog import EALauncherDialog

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.pre_ea_bgy_combo = MagicMock()
        mock_dlg.pre_ea_ea_combo = MagicMock()
        mock_dlg.pre_ea_output_folder_widget = MagicMock()
        mock_dlg.pre_ea_gap_tol_spin = MagicMock()
        mock_dlg.pre_ea_clip_chk = MagicMock()
        mock_dlg.pre_ea_resolve_overlaps_chk = MagicMock()
        mock_dlg.pre_ea_detect_gaps_chk = MagicMock()
        mock_dlg.pre_ea_assign_gaps_chk = MagicMock()
        mock_dlg.pre_ea_progress_bar = MagicMock()
        mock_dlg.pre_ea_cancel_btn = MagicMock()
        mock_dlg.pre_ea_status_banner = MagicMock()
        mock_dlg.pre_ea_results_table = MagicMock()
        mock_dlg.pre_ea_log_console = MagicMock()
        mock_dlg.pre_ea_right_tabs = MagicMock()
        mock_dlg._pre_ea_sum_status_lbl = MagicMock()
        mock_dlg._pre_ea_sum_bgy_val = MagicMock()

        # Call real method
        EALauncherDialog._pre_ea_refresh(mock_dlg)

        mock_dlg.pre_ea_bgy_combo.setLayer.assert_called_once_with(None)
        mock_dlg.pre_ea_ea_combo.setLayer.assert_called_once_with(None)
        mock_dlg.pre_ea_output_folder_widget.setFilePath.assert_called_once_with("")
        mock_dlg.pre_ea_gap_tol_spin.setValue.assert_called_once_with(1.0)
        mock_dlg.pre_ea_progress_bar.setValue.assert_called_once_with(0)
        mock_dlg.pre_ea_cancel_btn.setEnabled.assert_called_once_with(False)
        mock_dlg.pre_ea_results_table.setRowCount.assert_called_once_with(0)
        mock_dlg.pre_ea_log_console.clear.assert_called_once()
        mock_dlg._pre_ea_auto_detect_layers.assert_called_once()
        mock_dlg.pre_ea_right_tabs.setCurrentIndex.assert_called_once_with(0)

    def test_create_ea_refresh_resets_state(self):
        """Verify that _create_ea_refresh resets controls, logs, KPI cards, and runs auto-detection."""
        from references.create_enumeration_area.dialog import EALauncherDialog

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.all_delineation_candidates = ["item1"]
        mock_dlg.all_merge_candidates = ["item2"]
        mock_dlg.bar_combo = MagicMock()
        mock_dlg.bldg_combo = MagicMock()
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.enable_thresholds_chk = MagicMock()
        mock_dlg.min_hh_spin = MagicMock()
        mock_dlg.max_hh_spin = MagicMock()
        mock_dlg.tolerance_spin = MagicMock()
        mock_dlg.compact_chk = MagicMock()
        mock_dlg.allow_candidate_merge_chk = MagicMock()
        mock_dlg.sliver_combo = MagicMock()
        mock_dlg.crs_widget = MagicMock()
        mock_dlg.params_group = MagicMock()
        mock_dlg.output_folder_widget = MagicMock()
        mock_dlg.delineated_edit = MagicMock()
        mock_dlg.merged_edit = MagicMock()
        mock_dlg.search_edit = MagicMock()
        mock_dlg.progress_bar = MagicMock()
        mock_dlg.cancel_btn = MagicMock()
        mock_dlg.run_btn = MagicMock()
        mock_dlg.status_banner = MagicMock()
        mock_dlg.kpi_delin_val = MagicMock()
        mock_dlg.kpi_merge_val = MagicMock()
        mock_dlg.delineation_table = MagicMock()
        mock_dlg.merge_table = MagicMock()
        mock_dlg.log_console = MagicMock()
        mock_dlg.tab_widget = MagicMock()

        # prev_ea_combo has no layer after reset
        mock_dlg._safe_get_layer.return_value = None

        EALauncherDialog._create_ea_refresh(mock_dlg)

        self.assertEqual(len(mock_dlg.all_delineation_candidates), 0)
        self.assertEqual(len(mock_dlg.all_merge_candidates), 0)
        mock_dlg.output_folder_widget.setFilePath.assert_called_once_with("")
        mock_dlg.enable_thresholds_chk.setChecked.assert_called_once_with(False)
        mock_dlg.min_hh_spin.setValue.assert_called_once_with(99)
        mock_dlg.max_hh_spin.setValue.assert_called_once_with(300)
        mock_dlg.params_group.setCollapsed.assert_called_once_with(True)
        mock_dlg.progress_bar.setValue.assert_called_once_with(0)
        mock_dlg.cancel_btn.setEnabled.assert_called_once_with(False)
        mock_dlg.run_btn.setEnabled.assert_called_once_with(True)
        mock_dlg.kpi_delin_val.setText.assert_called_once_with("0")
        mock_dlg.kpi_merge_val.setText.assert_called_once_with("0")
        mock_dlg.delineation_table.setRowCount.assert_called_once_with(0)
        mock_dlg.merge_table.setRowCount.assert_called_once_with(0)
        mock_dlg.log_console.clear.assert_called_once()
        mock_dlg.auto_detect_layers.assert_called_once()
        mock_dlg.tab_widget.setCurrentIndex.assert_called_once_with(0)

    def test_ea_merge_refresh_resets_state(self):
        """Verify that _ea_merge_refresh resets controls, replacement list, summaries, and logs."""
        from references.create_enumeration_area.dialog import EALauncherDialog

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.ea_merge_ea_combo = MagicMock()
        mock_dlg.ea_merge_output_folder_widget = MagicMock()
        mock_dlg.ea_merge_layers_list = MagicMock()
        mock_dlg.ea_merge_progress_bar = MagicMock()
        mock_dlg.ea_merge_cancel_btn = MagicMock()
        mock_dlg.ea_merge_run_btn = MagicMock()
        mock_dlg.ea_merge_status_banner = MagicMock()
        mock_dlg.ea_merge_log_console = MagicMock()
        mock_dlg.ea_merge_right_tabs = MagicMock()
        mock_dlg._ea_merge_sum_status_lbl = MagicMock()
        mock_dlg._ea_merge_sum_geocode_val = MagicMock()

        EALauncherDialog._ea_merge_refresh(mock_dlg)

        self.assertEqual(mock_dlg._ea_merge_replacement_layers, [])
        mock_dlg.ea_merge_layers_list.clear.assert_called_once()
        mock_dlg.ea_merge_output_folder_widget.setFilePath.assert_called_once_with("")
        mock_dlg.ea_merge_progress_bar.setValue.assert_called_once_with(0)
        mock_dlg.ea_merge_cancel_btn.setEnabled.assert_called_once_with(False)
        mock_dlg.ea_merge_run_btn.setEnabled.assert_called_once_with(True)
        mock_dlg._ea_merge_sum_status_lbl.setText.assert_called_once_with("Status: READY")
        mock_dlg.ea_merge_log_console.clear.assert_called_once()
        mock_dlg._ea_merge_auto_detect_ea_layer.assert_called_once()
        mock_dlg.ea_merge_right_tabs.setCurrentIndex.assert_called_once_with(0)

    @patch("references.create_enumeration_area.dialog.QMessageBox")
    def test_fill_missing_hh_count_strictly_requires_hh_count_in_ea_layer(self, mock_msgbox):
        """Verify that fill_missing_hh_count rejects layers having only 'hhcount' or 'household'."""
        from references.create_enumeration_area.dialog import EALauncherDialog
        from qgis.core import QgsVectorLayer, QgsField
        from qgis.PyQt.QtCore import QVariant

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.bldg_combo = MagicMock()

        # EA layer with legacy 'hhcount' instead of 'hh_count'
        ea_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Test_EA", "memory")
        ea_layer.dataProvider().addAttributes([QgsField("hhcount", QVariant.Double)])
        ea_layer.updateFields()

        bldg_layer = QgsVectorLayer("Point?crs=epsg:4326", "Test_Bldg", "memory")
        bldg_layer.dataProvider().addAttributes([QgsField("hh_count", QVariant.Double)])
        bldg_layer.updateFields()

        def safe_get_layer(combo):
            if combo is mock_dlg.prev_ea_combo:
                return ea_layer
            if combo is mock_dlg.bldg_combo:
                return bldg_layer
            return None

        mock_dlg._safe_get_layer.side_effect = safe_get_layer

        EALauncherDialog.fill_missing_hh_count(mock_dlg)

        mock_msgbox.critical.assert_called_once()
        args = mock_msgbox.critical.call_args[0]
        self.assertIn("Previous EA layer does not contain 'hh_count' field", args[2])

    @patch("references.create_enumeration_area.dialog.QMessageBox")
    def test_fill_missing_hh_count_rejects_missing_household_in_bldg_layer(self, mock_msgbox):
        """Verify that fill_missing_hh_count rejects building layers lacking est_hhcount/est_hh."""
        from references.create_enumeration_area.dialog import EALauncherDialog
        from qgis.core import QgsVectorLayer, QgsField
        from qgis.PyQt.QtCore import QVariant

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.bldg_combo = MagicMock()

        ea_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Test_EA", "memory")
        ea_layer.dataProvider().addAttributes([QgsField("hh_count", QVariant.Double)])
        ea_layer.updateFields()

        # Bldg layer with irrelevant field
        bldg_layer = QgsVectorLayer("Point?crs=epsg:4326", "Test_Bldg", "memory")
        bldg_layer.dataProvider().addAttributes([QgsField("other_field", QVariant.Double)])
        bldg_layer.updateFields()

        def safe_get_layer(combo):
            if combo is mock_dlg.prev_ea_combo:
                return ea_layer
            if combo is mock_dlg.bldg_combo:
                return bldg_layer
            return None

        mock_dlg._safe_get_layer.side_effect = safe_get_layer

        EALauncherDialog.fill_missing_hh_count(mock_dlg)

        mock_msgbox.critical.assert_called_once()
        args = mock_msgbox.critical.call_args[0]
        self.assertIn("Building point layer does not contain 'est_hhcount'", args[2])

    @patch("references.create_enumeration_area.dialog.QMessageBox")
    def test_fill_missing_hh_count_populates_from_bldg_hhcount(self, mock_msgbox):
        """Verify that fill_missing_hh_count computes and updates hh_count and bldg_count in EA from building 'est_hhcount'."""
        from references.create_enumeration_area.dialog import EALauncherDialog
        from qgis.core import QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY
        from qgis.PyQt.QtCore import QVariant

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.bldg_combo = MagicMock()
        mock_dlg.generate_preview = MagicMock()

        ea_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Test_EA", "memory")
        ea_layer.dataProvider().addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("hh_count", QVariant.Double),
            QgsField("bldg_count", QVariant.Int),
        ])
        ea_layer.updateFields()

        ea_feat = QgsFeature(ea_layer.fields())
        ea_feat.setAttribute("ean", "001")
        ea_feat.setAttribute("hh_count", None) # Missing hh_count
        ea_feat.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]]))
        ea_layer.dataProvider().addFeatures([ea_feat])

        bldg_layer = QgsVectorLayer("Point?crs=epsg:4326", "Test_Bldg", "memory")
        bldg_layer.dataProvider().addAttributes([QgsField("est_hhcount", QVariant.Double)])
        bldg_layer.updateFields()

        pt1 = QgsFeature(bldg_layer.fields())
        pt1.setAttribute("est_hhcount", 3.0)
        pt1.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(2, 2)))

        pt2 = QgsFeature(bldg_layer.fields())
        pt2.setAttribute("est_hhcount", 5.0)
        pt2.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(4, 4)))

        bldg_layer.dataProvider().addFeatures([pt1, pt2])

        def safe_get_layer(combo):
            if combo is mock_dlg.prev_ea_combo:
                return ea_layer
            if combo is mock_dlg.bldg_combo:
                return bldg_layer
            return None

        mock_dlg._safe_get_layer.side_effect = safe_get_layer

        EALauncherDialog.fill_missing_hh_count(mock_dlg)

        updated_feats = list(ea_layer.getFeatures())
        self.assertEqual(len(updated_feats), 1)
        self.assertEqual(float(updated_feats[0].attribute("hh_count")), 8.0)
        self.assertEqual(int(updated_feats[0].attribute("bldg_count")), 2)
        mock_dlg.generate_preview.assert_called_once()
        mock_msgbox.information.assert_called_once()

    @patch("references.create_enumeration_area.dialog.QMessageBox")
    def test_fill_missing_hh_count_proportional_scaling_to_parent_hhcount(self, mock_msgbox):
        """Verify that fill_missing_hh_count proportionally scales building point counts to match parent hhcount and sets bldg_count."""
        from references.create_enumeration_area.dialog import EALauncherDialog
        from qgis.core import QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY
        from qgis.PyQt.QtCore import QVariant

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.bldg_combo = MagicMock()
        mock_dlg.generate_preview = MagicMock()

        ea_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Test_Delineated_EA", "memory")
        ea_layer.dataProvider().addAttributes([
            QgsField("code", QVariant.String),
            QgsField("ean", QVariant.String),
            QgsField("hhcount", QVariant.Double),
            QgsField("hh_count", QVariant.Double),
        ])
        ea_layer.updateFields()

        # Sub-EA 1 (001000) from parent 000000 with hhcount 302
        sub_ea1 = QgsFeature(ea_layer.fields())
        sub_ea1.setAttribute("code", "000000")
        sub_ea1.setAttribute("ean", "001000")
        sub_ea1.setAttribute("hhcount", 302.0)
        sub_ea1.setAttribute("hh_count", None)
        sub_ea1.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(5, 0), QgsPointXY(5, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]]))

        # Sub-EA 2 (002000) from parent 000000 with hhcount 302
        sub_ea2 = QgsFeature(ea_layer.fields())
        sub_ea2.setAttribute("code", "000000")
        sub_ea2.setAttribute("ean", "002000")
        sub_ea2.setAttribute("hhcount", 302.0)
        sub_ea2.setAttribute("hh_count", None)
        sub_ea2.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(5, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(5, 10), QgsPointXY(5, 0)
        ]]))

        ea_layer.dataProvider().addFeatures([sub_ea1, sub_ea2])

        bldg_layer = QgsVectorLayer("Point?crs=epsg:4326", "Test_Bldg", "memory")
        bldg_layer.dataProvider().addAttributes([QgsField("est_hhcount", QVariant.Double)])
        bldg_layer.updateFields()

        # 204 HH inside Sub-EA 1 (2 building points)
        pt1 = QgsFeature(bldg_layer.fields())
        pt1.setAttribute("est_hhcount", 104.0)
        pt1.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(2, 5)))

        pt2 = QgsFeature(bldg_layer.fields())
        pt2.setAttribute("est_hhcount", 100.0)
        pt2.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(3, 5)))

        # 106 HH inside Sub-EA 2 (1 building point)
        pt3 = QgsFeature(bldg_layer.fields())
        pt3.setAttribute("est_hhcount", 106.0)
        pt3.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(7, 5)))

        bldg_layer.dataProvider().addFeatures([pt1, pt2, pt3])

        def safe_get_layer(combo):
            if combo is mock_dlg.prev_ea_combo:
                return ea_layer
            if combo is mock_dlg.bldg_combo:
                return bldg_layer
            return None

        mock_dlg._safe_get_layer.side_effect = safe_get_layer

        EALauncherDialog.fill_missing_hh_count(mock_dlg)

        updated_feats = list(ea_layer.getFeatures())
        self.assertEqual(len(updated_feats), 2)

        feat_by_ean = {f.attribute("ean"): f for f in updated_feats}
        # 204 * 302 / 310 = 198.748 -> 199
        self.assertEqual(float(feat_by_ean["001000"].attribute("hh_count")), 199.0)
        self.assertEqual(int(feat_by_ean["001000"].attribute("bldg_count")), 2)

        # 106 * 302 / 310 = 103.251 -> 103
        self.assertEqual(float(feat_by_ean["002000"].attribute("hh_count")), 103.0)
        self.assertEqual(int(feat_by_ean["002000"].attribute("bldg_count")), 1)

        # Total sum matches parent hhcount 302.0
        self.assertEqual(
            float(feat_by_ean["001000"].attribute("hh_count")) + float(feat_by_ean["002000"].attribute("hh_count")),
            302.0
        )
        mock_dlg.generate_preview.assert_called_once()
        mock_msgbox.information.assert_called_once()

    @patch("references.create_enumeration_area.dialog.QMessageBox")
    def test_fill_missing_hh_count_updates_existing_non_empty_values(self, mock_msgbox):
        """Verify that fill_missing_hh_count updates EAs even when hh_count is already non-empty."""
        from references.create_enumeration_area.dialog import EALauncherDialog
        from qgis.core import QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY
        from qgis.PyQt.QtCore import QVariant

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.bldg_combo = MagicMock()
        mock_dlg.generate_preview = MagicMock()

        ea_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Test_EA", "memory")
        ea_layer.dataProvider().addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("hh_count", QVariant.Double),
            QgsField("bldg_count", QVariant.Int),
        ])
        ea_layer.updateFields()

        ea_feat = QgsFeature(ea_layer.fields())
        ea_feat.setAttribute("ean", "001")
        ea_feat.setAttribute("hh_count", 999.0) # Pre-existing non-empty hh_count
        ea_feat.setAttribute("bldg_count", 0)
        ea_feat.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]]))
        ea_layer.dataProvider().addFeatures([ea_feat])

        bldg_layer = QgsVectorLayer("Point?crs=epsg:4326", "Test_Bldg", "memory")
        bldg_layer.dataProvider().addAttributes([QgsField("est_hhcount", QVariant.Double)])
        bldg_layer.updateFields()

        pt1 = QgsFeature(bldg_layer.fields())
        pt1.setAttribute("est_hhcount", 15.0)
        pt1.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(2, 2)))

        bldg_layer.dataProvider().addFeatures([pt1])

        def safe_get_layer(combo):
            if combo is mock_dlg.prev_ea_combo:
                return ea_layer
            if combo is mock_dlg.bldg_combo:
                return bldg_layer
            return None

        mock_dlg._safe_get_layer.side_effect = safe_get_layer

        EALauncherDialog.fill_missing_hh_count(mock_dlg)

        updated_feats = list(ea_layer.getFeatures())
        self.assertEqual(len(updated_feats), 1)
        self.assertEqual(float(updated_feats[0].attribute("hh_count")), 15.0)
        self.assertEqual(int(updated_feats[0].attribute("bldg_count")), 1)
        mock_dlg.generate_preview.assert_called_once()
        mock_msgbox.information.assert_called_once()

    @patch("references.create_enumeration_area.dialog.QMessageBox")
    def test_fill_missing_hh_count_building_fallback_to_one(self, mock_msgbox):
        """Verify delineation logic: building points with null/empty/0 hhcount fallback to 1.0."""
        from references.create_enumeration_area.dialog import EALauncherDialog
        from qgis.core import QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY
        from qgis.PyQt.QtCore import QVariant

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.bldg_combo = MagicMock()
        mock_dlg.generate_preview = MagicMock()

        ea_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Test_EA", "memory")
        ea_layer.dataProvider().addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("hh_count", QVariant.Double),
        ])
        ea_layer.updateFields()

        ea_feat = QgsFeature(ea_layer.fields())
        ea_feat.setAttribute("ean", "001")
        ea_feat.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]]))
        ea_layer.dataProvider().addFeatures([ea_feat])

        bldg_layer = QgsVectorLayer("Point?crs=epsg:4326", "Test_Bldg", "memory")
        bldg_layer.dataProvider().addAttributes([QgsField("est_hhcount", QVariant.Double)])
        bldg_layer.updateFields()

        pt1 = QgsFeature(bldg_layer.fields())
        pt1.setAttribute("est_hhcount", None) # Null -> fallback to 1.0
        pt1.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(2, 2)))

        pt2 = QgsFeature(bldg_layer.fields())
        pt2.setAttribute("est_hhcount", 0.0) # 0.0 -> fallback to 1.0
        pt2.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(3, 3)))

        pt3 = QgsFeature(bldg_layer.fields())
        pt3.setAttribute("est_hhcount", 4.0) # 4.0 -> keeps 4.0
        pt3.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(4, 4)))

        bldg_layer.dataProvider().addFeatures([pt1, pt2, pt3])

        def safe_get_layer(combo):
            if combo is mock_dlg.prev_ea_combo:
                return ea_layer
            if combo is mock_dlg.bldg_combo:
                return bldg_layer
            return None

        mock_dlg._safe_get_layer.side_effect = safe_get_layer

        EALauncherDialog.fill_missing_hh_count(mock_dlg)

        updated_feats = list(ea_layer.getFeatures())
        self.assertEqual(len(updated_feats), 1)
        # 1.0 + 1.0 + 4.0 = 6.0
        self.assertEqual(float(updated_feats[0].attribute("hh_count")), 6.0)
        self.assertEqual(int(updated_feats[0].attribute("bldg_count")), 3)

    @patch("references.create_enumeration_area.dialog.QMessageBox")
    def test_fill_missing_hh_count_scales_to_match_hhcount_for_split_sub_eas(self, mock_msgbox):
        """Verify that sub-EAs with parent hhcount 320 and building sums (67, 96 = 163) strictly scale to sum to 320."""
        from references.create_enumeration_area.dialog import EALauncherDialog
        from qgis.core import QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY
        from qgis.PyQt.QtCore import QVariant

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.bldg_combo = MagicMock()
        mock_dlg.generate_preview = MagicMock()

        ea_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Test_Delineated_EA", "memory")
        ea_layer.dataProvider().addAttributes([
            QgsField("barangay", QVariant.String),
            QgsField("code", QVariant.String),
            QgsField("ean", QVariant.String),
            QgsField("hhcount", QVariant.Double),
            QgsField("bldgcount", QVariant.Int),
            QgsField("new_ean", QVariant.String),
            QgsField("hh_count", QVariant.Double),
            QgsField("bldg_count", QVariant.Int),
        ])
        ea_layer.updateFields()

        # Row 1: Sub-EA 002000
        sub_ea1 = QgsFeature(ea_layer.fields())
        sub_ea1.setAttribute("barangay", "EA 000000")
        sub_ea1.setAttribute("code", "1004")
        sub_ea1.setAttribute("ean", "1004")
        sub_ea1.setAttribute("hhcount", 320.0)
        sub_ea1.setAttribute("bldgcount", 274)
        sub_ea1.setAttribute("new_ean", "002000")
        sub_ea1.setAttribute("hh_count", None)
        sub_ea1.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(5, 0), QgsPointXY(5, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]]))

        # Row 2: Sub-EA 001000
        sub_ea2 = QgsFeature(ea_layer.fields())
        sub_ea2.setAttribute("barangay", "EA 000000")
        sub_ea2.setAttribute("code", "1004")
        sub_ea2.setAttribute("ean", "1004")
        sub_ea2.setAttribute("hhcount", 320.0)
        sub_ea2.setAttribute("bldgcount", 274)
        sub_ea2.setAttribute("new_ean", "001000")
        sub_ea2.setAttribute("hh_count", None)
        sub_ea2.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(5, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(5, 10), QgsPointXY(5, 0)
        ]]))

        ea_layer.dataProvider().addFeatures([sub_ea1, sub_ea2])

        bldg_layer = QgsVectorLayer("Point?crs=epsg:4326", "Test_Bldg", "memory")
        bldg_layer.dataProvider().addAttributes([QgsField("est_hhcount", QVariant.Double)])
        bldg_layer.updateFields()

        # 109 building points in Sub-EA 1 with total est_hhcount = 67.0
        bldgs = []
        # 67 points with 1.0, 42 points with 0.0 (fallback to 1.0 in delineation, or suppose 67.0 total)
        for i in range(67):
            pt = QgsFeature(bldg_layer.fields())
            pt.setAttribute("est_hhcount", 1.0)
            pt.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(2, 2)))
            bldgs.append(pt)

        # 96 points with 1.0 in Sub-EA 2
        for i in range(96):
            pt = QgsFeature(bldg_layer.fields())
            pt.setAttribute("est_hhcount", 1.0)
            pt.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(7, 7)))
            bldgs.append(pt)

        bldg_layer.dataProvider().addFeatures(bldgs)

        def safe_get_layer(combo):
            if combo is mock_dlg.prev_ea_combo:
                return ea_layer
            if combo is mock_dlg.bldg_combo:
                return bldg_layer
            return None

        mock_dlg._safe_get_layer.side_effect = safe_get_layer

        EALauncherDialog.fill_missing_hh_count(mock_dlg)

        updated_feats = list(ea_layer.getFeatures())
        self.assertEqual(len(updated_feats), 2)

        feat_by_new_ean = {f.attribute("new_ean"): f for f in updated_feats}
        hh1 = float(feat_by_new_ean["002000"].attribute("hh_count"))
        hh2 = float(feat_by_new_ean["001000"].attribute("hh_count"))

        # Quotas: 67 * 320 / 163 = 131.53 -> 132, 96 * 320 / 163 = 188.46 -> 188
        self.assertEqual(hh1, 132.0)
        self.assertEqual(hh2, 188.0)
        # Total strictly equals parent hhcount 320.0
        self.assertEqual(hh1 + hh2, 320.0)

    def test_create_ea_subtabs_structure_and_separation(self):
        """Verify that Tab 2 has two dedicated sub-tabs with separated preview and log widgets."""
        from references.create_enumeration_area.dialog import EALauncherDialog

        mock_dlg = MagicMock()
        mock_dlg.algo = MagicMock()
        mock_dlg.algo.shortHelpString.return_value = "Help"
        mock_dlg.main_tabs = MagicMock()

        # Call real _build_create_ea_tab
        EALauncherDialog._build_create_ea_tab(mock_dlg)

        self.assertIsNotNone(mock_dlg.create_ea_sub_tabs)
        self.assertIsNotNone(mock_dlg.proposed_delineation_tab)
        self.assertIsNotNone(mock_dlg.proposed_merging_tab)
        self.assertIsNotNone(mock_dlg.delineation_table)
        self.assertIsNotNone(mock_dlg.merge_table)
        self.assertIsNotNone(mock_dlg.log_console)
        self.assertIsNotNone(mock_dlg.merge_log_console)
        self.assertIsNotNone(mock_dlg.delin_right_tabs)
        self.assertIsNotNone(mock_dlg.merge_right_tabs)

    def test_two_way_sync_helpers(self):
        """Verify two-way sync helper methods prevent infinite recursive loops using guards."""
        from references.create_enumeration_area.dialog import EALauncherDialog

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.validate_layer_inputs = MagicMock()
        mock_dlg.filter_previews = MagicMock()

        # Test combo sync
        target_combo = MagicMock()
        mock_layer = MagicMock()
        EALauncherDialog._sync_combo(mock_dlg, target_combo, mock_layer)
        mock_dlg.validate_layer_inputs.assert_called_once()

        # Test output folder sync
        target_folder_widget = MagicMock()
        EALauncherDialog._sync_output_folder(mock_dlg, target_folder_widget, "C:/test_folder")
        target_folder_widget.setFilePath.assert_called_once_with("C:/test_folder")

        # Test search text sync
        target_search = MagicMock()
        EALauncherDialog._sync_search_text(mock_dlg, target_search, "EA 001")
        target_search.setText.assert_called_once_with("EA 001")
        mock_dlg.filter_previews.assert_called_once()

    def test_run_delineation_merging_delegation(self):
        """Verify that run_delineation and run_merging correctly invoke run_pipeline with explicit modes."""
        from references.create_enumeration_area.dialog import EALauncherDialog

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.run_pipeline = MagicMock()

        EALauncherDialog.run_delineation(mock_dlg)
        mock_dlg.run_pipeline.assert_called_once_with(mode="delineation")

        mock_dlg.run_pipeline.reset_mock()
        EALauncherDialog.run_merging(mock_dlg)
        mock_dlg.run_pipeline.assert_called_once_with(mode="merging")

    @patch("references.create_enumeration_area.dialog.QgsProject")
    @patch("references.create_enumeration_area.dialog.CustomProcessingFeedback")
    @patch("qgis.processing.runAndLoadResults")
    def test_run_pipeline_output_filtering_delineation_mode(self, mock_run, mock_feedback_cls, mock_project_cls):
        """Verify that running in delineation mode retains only delineation outputs and splitting lines."""
        from references.create_enumeration_area.dialog import EALauncherDialog
        from qgis.core import QgsVectorLayer, QgsField
        from qgis.PyQt.QtCore import QVariant
        import tempfile

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.bar_combo = MagicMock()
        mock_dlg.bldg_combo = MagicMock()
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.road_combo = MagicMock()
        mock_dlg.river_combo = MagicMock()
        mock_dlg.tolerance_spin = MagicMock(value=lambda: 5.0)
        mock_dlg.enable_thresholds_chk = MagicMock(isChecked=lambda: True)
        mock_dlg.min_hh_spin = MagicMock(value=lambda: 100)
        mock_dlg.max_hh_spin = MagicMock(value=lambda: 300)
        mock_dlg.compact_chk = MagicMock(isChecked=lambda: True)
        mock_dlg.allow_candidate_merge_chk = MagicMock(isChecked=lambda: False)
        mock_dlg.sliver_combo = MagicMock(currentIndex=lambda: 1)
        mock_dlg.crs_widget = MagicMock(crs=lambda: None)
        mock_dlg.log_console = MagicMock()
        mock_dlg.progress_bar = MagicMock()
        mock_dlg.run_btn = MagicMock()
        mock_dlg.cancel_btn = MagicMock()
        mock_dlg.status_banner = MagicMock()
        mock_dlg.ALGORITHM_ID = "gmd:create_ea"
        mock_dlg.algo = MagicMock()
        mock_dlg._extract_5digit_geocode.return_value = "12345"
        mock_dlg._export_layer_to_gpkg.return_value = False

        tmp_dir = tempfile.mkdtemp()
        mock_dlg.output_folder_widget = MagicMock(filePath=lambda: tmp_dir)

        delin_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "12345_delineated_ea2026", "memory")
        delin_layer.dataProvider().addAttributes([QgsField("split_by", QVariant.String), QgsField("remarks", QVariant.String)])
        delin_layer.updateFields()

        merge_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "12345_merged_ea2026", "memory")

        mock_dlg._safe_get_layer.return_value = delin_layer
        mock_run.return_value = {
            'DELINEATED_OUTPUT': delin_layer,
            'MERGED_OUTPUT': merge_layer,
        }

        mock_proj = MagicMock()
        mock_root = MagicMock()
        mock_group = MagicMock()
        mock_root.findGroup.return_value = mock_group
        mock_group.findGroup.return_value = mock_group
        mock_root.findLayer.return_value = None
        mock_proj.layerTreeRoot.return_value = mock_root
        mock_proj.mapLayers.return_value = {}
        mock_project_cls.instance.return_value = mock_proj
        mock_feedback_inst = mock_feedback_cls.return_value
        mock_feedback_inst.isCanceled.return_value = False

        EALauncherDialog.run_pipeline(mock_dlg, mode="delineation")

        # In delineation mode, merge_layer should be discarded/removed from project
        mock_proj.removeMapLayer.assert_any_call(merge_layer.id())

    @patch("references.create_enumeration_area.dialog.QgsProject")
    @patch("references.create_enumeration_area.dialog.CustomProcessingFeedback")
    @patch("qgis.processing.runAndLoadResults")
    def test_run_pipeline_output_filtering_merging_mode(self, mock_run, mock_feedback_cls, mock_project_cls):
        """Verify that running in merging mode retains only merging outputs and removes splitting lines & delineation layers."""
        from references.create_enumeration_area.dialog import EALauncherDialog
        from qgis.core import QgsVectorLayer, QgsField
        from qgis.PyQt.QtCore import QVariant
        import tempfile

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.bar_combo = MagicMock()
        mock_dlg.bldg_combo = MagicMock()
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.road_combo = MagicMock()
        mock_dlg.river_combo = MagicMock()
        mock_dlg.tolerance_spin = MagicMock(value=lambda: 5.0)
        mock_dlg.enable_thresholds_chk = MagicMock(isChecked=lambda: True)
        mock_dlg.min_hh_spin = MagicMock(value=lambda: 100)
        mock_dlg.max_hh_spin = MagicMock(value=lambda: 300)
        mock_dlg.compact_chk = MagicMock(isChecked=lambda: True)
        mock_dlg.allow_candidate_merge_chk = MagicMock(isChecked=lambda: True)
        mock_dlg.sliver_combo = MagicMock(currentIndex=lambda: 1)
        mock_dlg.crs_widget = MagicMock(crs=lambda: None)
        mock_dlg.merge_log_console = MagicMock()
        mock_dlg.merge_progress_bar = MagicMock()
        mock_dlg.merge_run_btn = MagicMock()
        mock_dlg.merge_cancel_btn = MagicMock()
        mock_dlg.merge_status_banner = MagicMock()
        mock_dlg.ALGORITHM_ID = "gmd:create_ea"
        mock_dlg.algo = MagicMock()
        mock_dlg._extract_5digit_geocode.return_value = "12345"
        mock_dlg._export_layer_to_gpkg.return_value = False

        tmp_dir = tempfile.mkdtemp()
        mock_dlg.output_folder_widget = MagicMock(filePath=lambda: tmp_dir)

        delin_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "12345_delineated_ea2026", "memory")
        merge_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "12345_merged_ea2026", "memory")
        split_line_layer = QgsVectorLayer("LineString?crs=epsg:4326", "12345_eadel_update", "memory")

        mock_dlg._safe_get_layer.return_value = merge_layer
        mock_run.return_value = {
            'DELINEATED_OUTPUT': delin_layer,
            'MERGED_OUTPUT': merge_layer,
        }

        mock_proj = MagicMock()
        mock_root = MagicMock()
        mock_group = MagicMock()
        mock_root.findGroup.return_value = mock_group
        mock_group.findGroup.return_value = mock_group
        mock_root.findLayer.return_value = None
        mock_proj.layerTreeRoot.return_value = mock_root
        mock_proj.mapLayers.return_value = {
            "split_line_id": split_line_layer,
        }
        mock_project_cls.instance.return_value = mock_proj
        mock_feedback_inst = mock_feedback_cls.return_value
        mock_feedback_inst.isCanceled.return_value = False

        EALauncherDialog.run_pipeline(mock_dlg, mode="merging")

        # In merging mode, delin_layer should be discarded/removed
        mock_proj.removeMapLayer.assert_any_call(delin_layer.id())
        # In merging mode, any splitting line layer should also be removed
        mock_proj.removeMapLayer.assert_any_call("split_line_id")


    def test_create_preview_table_columns_merge_mode(self):
        """Verify that _create_preview_table(include_merge_partner=True) creates 8 columns with Total HH Count and Action."""
        from references.create_enumeration_area.dialog import EALauncherDialog
        mock_dlg = MagicMock(spec=EALauncherDialog)
        table = EALauncherDialog._create_preview_table(mock_dlg, include_merge_partner=True)
        self.assertEqual(table.columnCount(), 8)
        headers = [table.horizontalHeaderItem(i).text() for i in range(8)]
        self.assertIn("Merge Partner (EAN)", headers[5])
        self.assertIn("Total HH Count", headers[6])
        self.assertIn("Action", headers[7])

    def test_populate_table_rows_combined_hh_count_dynamic_update(self):
        """Verify that selecting a merge partner updates the Total HH Count column dynamically."""
        from references.create_enumeration_area.dialog import EALauncherDialog
        from qgis.PyQt.QtWidgets import QComboBox
        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.current_theme = "light"
        table = EALauncherDialog._create_preview_table(mock_dlg, include_merge_partner=True)

        candidates = [
            ("01701001", "EA 1", "Barangay 1", 50.0, "Initiator (<= 150 HH)", [("01701002", 120.0), ("01701003", 200.0)])
        ]
        EALauncherDialog._populate_table_rows(mock_dlg, table, candidates, is_delineation=False)

        self.assertEqual(table.rowCount(), 1)
        combo = table.cellWidget(0, 5)
        self.assertIsInstance(combo, QComboBox)
        self.assertEqual(combo.count(), 2)

        # Initial combined count: 50 + 120 = 170
        col6_item = table.item(0, 6)
        self.assertIsNotNone(col6_item)
        self.assertEqual(col6_item.text(), "170")

        # Change selection to second neighbor (200 HH): 50 + 200 = 250
        combo.setCurrentIndex(1)
        self.assertEqual(table.item(0, 6).text(), "250")

    def test_auto_detect_layers_separates_merged_ea_and_prev_ea(self):
        """Verify auto-detection maps *_merged_ea* to merge_ea and base EA layers to prev_ea."""
        from references.create_enumeration_area.dialog import EALauncherDialog
        from qgis.core import QgsVectorLayer
        from unittest.mock import patch

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.bar_combo = MagicMock()
        mock_dlg.bldg_combo = MagicMock()
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.road_combo = MagicMock()
        mock_dlg.river_combo = MagicMock()
        mock_dlg.merge_ea_combo = MagicMock()
        mock_dlg._safe_set_layer = MagicMock()

        merged_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "01701_merged_ea2026", "memory")
        prev_ea_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "01701_ea", "memory")

        with patch("references.create_enumeration_area.dialog.QgsProject") as mock_project_cls:
            mock_proj = MagicMock()
            mock_proj.mapLayers.return_value = {
                "m_id": merged_layer,
                "p_id": prev_ea_layer,
            }
            mock_project_cls.instance.return_value = mock_proj

            EALauncherDialog.auto_detect_layers(mock_dlg)

            # Check that merge_ea_combo received the merged_ea layer
            mock_dlg._safe_set_layer.assert_any_call(mock_dlg.merge_ea_combo, merged_layer)
            # Check that prev_ea_combo received the baseline ea layer
            mock_dlg._safe_set_layer.assert_any_call(mock_dlg.prev_ea_combo, prev_ea_layer)


    def test_reborn_live_preview_and_new_merge_preview_tabs(self):
        """Verify that merge_table is 5 columns (reborn Live Preview) and merged_ea_table is 8 columns (Merge Preview)."""
        from references.create_enumeration_area.dialog import EALauncherDialog
        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.current_theme = "light"

        # 1. Reborn Live Preview table: 5 columns
        reborn_table = EALauncherDialog._create_preview_table(mock_dlg, include_merge_partner=False)
        self.assertEqual(reborn_table.columnCount(), 5)
        headers_5 = [reborn_table.horizontalHeaderItem(i).text() for i in range(5)]
        self.assertNotIn("Merge Partner (EAN)", headers_5)
        self.assertNotIn("Total HH Count", headers_5)

        # 2. New Merge Preview table: 8 columns
        merge_preview_table = EALauncherDialog._create_preview_table(mock_dlg, include_merge_partner=True)
        self.assertEqual(merge_preview_table.columnCount(), 8)
        headers_8 = [merge_preview_table.horizontalHeaderItem(i).text() for i in range(8)]
        self.assertIn("Merge Partner (EAN)", headers_8[5])
        self.assertIn("Total HH Count", headers_8[6])
        self.assertIn("Action", headers_8[7])

        # 3. Populating reborn table with standard merge candidates (5 columns)
        reborn_candidates = [
            ("01701001", "EA 1", "Barangay 1", 45.0, "Initiator (<= 150 HH)")
        ]
        EALauncherDialog._populate_table_rows(mock_dlg, reborn_table, reborn_candidates, is_delineation=False)
        self.assertEqual(reborn_table.rowCount(), 1)
        self.assertIsNone(reborn_table.cellWidget(0, 5))  # No dropdown widget
        self.assertEqual(reborn_table.item(0, 3).text(), "45")

        # 4. Populating new Merge Preview table with candidates + neighbors (7 columns)
        merge_ea_candidates = [
            ("01701001", "EA 1", "Barangay 1", 45.0, "Initiator (<= 150 HH)", [("01701002", 100.0)])
        ]
        EALauncherDialog._populate_table_rows(mock_dlg, merge_preview_table, merge_ea_candidates, is_delineation=False)
        self.assertEqual(merge_preview_table.rowCount(), 1)
        combo = merge_preview_table.cellWidget(0, 5)
        self.assertIsNotNone(combo)
        self.assertEqual(merge_preview_table.item(0, 6).text(), "145")  # 45 + 100

    def test_extract_merge_candidate_enabling_and_tooltips(self):
        """Verify that Extract Merge Candidate button (self.merge_run_btn) validates inputs and explains missing requirements."""
        from references.create_enumeration_area.dialog import EALauncherDialog
        from qgis.core import QgsVectorLayer, QgsField
        from qgis.PyQt.QtCore import QVariant

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.bar_combo = MagicMock()
        mock_dlg.bldg_combo = MagicMock()
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.road_combo = MagicMock()
        mock_dlg.river_combo = MagicMock()
        mock_dlg.merge_bar_combo = MagicMock()
        mock_dlg.merge_bldg_combo = MagicMock()
        mock_dlg.merge_prev_ea_combo = MagicMock()
        mock_dlg.merge_ea_combo = MagicMock()
        mock_dlg.output_folder_widget = MagicMock()
        mock_dlg.merge_output_folder_widget = MagicMock()
        mock_dlg.bar_status_lbl = MagicMock()
        mock_dlg.bldg_status_lbl = MagicMock()
        mock_dlg.prev_ea_status_lbl = MagicMock()
        mock_dlg.merge_bar_status_lbl = MagicMock()
        mock_dlg.merge_bldg_status_lbl = MagicMock()
        mock_dlg.merge_prev_ea_status_lbl = MagicMock()
        mock_dlg.merge_ea_status_lbl = MagicMock()
        mock_dlg.road_status_lbl = MagicMock()
        mock_dlg.river_status_lbl = MagicMock()
        mock_dlg.fill_missing_btn = MagicMock()
        mock_dlg.merge_fill_missing_btn = MagicMock()
        mock_dlg.run_btn = MagicMock()
        mock_dlg.merge_run_btn = MagicMock()
        mock_dlg._extract_5digit_geocode.return_value = "01701"

        # Case 1: No layers and no output folder -> merge_run_btn disabled with informative tooltip
        mock_dlg._safe_get_layer.return_value = None
        mock_dlg.output_folder_widget.filePath.return_value = ""
        mock_dlg.merge_output_folder_widget.filePath.return_value = ""

        EALauncherDialog.validate_layer_inputs(mock_dlg)

        mock_dlg.merge_run_btn.setEnabled.assert_called_with(False)
        tooltip_call = mock_dlg.merge_run_btn.setToolTip.call_args[0][0]
        self.assertIn("Cannot run:", tooltip_call)
        self.assertIn("Barangay Boundary is required", tooltip_call)
        self.assertIn("Designated output folder is required", tooltip_call)

        # Case 2: Layers valid and output folder set in Sub-tab 2 -> merge_run_btn enabled!
        bar_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Test_Bar", "memory")
        bldg_layer = QgsVectorLayer("Point?crs=epsg:4326", "Test_Bldg", "memory")
        bldg_layer.dataProvider().addAttributes([QgsField("hhcount", QVariant.Double)])
        bldg_layer.updateFields()
        prev_ea_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Test_EA", "memory")
        prev_ea_layer.dataProvider().addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("hh_count", QVariant.Double)
        ])
        prev_ea_layer.updateFields()

        def safe_get(combo):
            if combo in (mock_dlg.bar_combo, mock_dlg.merge_bar_combo):
                return bar_layer
            if combo in (mock_dlg.bldg_combo, mock_dlg.merge_bldg_combo):
                return bldg_layer
            if combo in (mock_dlg.prev_ea_combo, mock_dlg.merge_prev_ea_combo):
                return prev_ea_layer
            return None

        mock_dlg._safe_get_layer.side_effect = safe_get
        # Output folder present in Sub-tab 2's merge_output_folder_widget
        mock_dlg.output_folder_widget.filePath.return_value = ""
        mock_dlg.merge_output_folder_widget.filePath.return_value = "C:/Outputs"

        EALauncherDialog.validate_layer_inputs(mock_dlg)

        mock_dlg.merge_run_btn.setEnabled.assert_called_with(True)
        self.assertEqual(mock_dlg.merge_run_btn.setToolTip.call_args[0][0], "Extract Merge Candidates")

    def test_neighbor_detection_same_barangay_and_enabled_dropdown(self):
        """Verify that generate_preview detects contiguous EAs in the same barangay and enables the dropdown."""
        from references.create_enumeration_area.dialog import EALauncherDialog
        from qgis.core import QgsVectorLayer, QgsField, QgsFeature, QgsGeometry
        from qgis.PyQt.QtCore import QVariant

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.delineation_table = MagicMock()
        mock_dlg.merge_table = MagicMock()
        mock_dlg.prev_ea_combo = MagicMock()
        mock_dlg.merge_ea_combo = MagicMock()
        mock_dlg.all_delineation_candidates = []
        mock_dlg.all_merge_candidates = []
        mock_dlg.all_merged_ea_candidates = []
        mock_dlg.min_hh_spin = MagicMock()
        mock_dlg.min_hh_spin.value.return_value = 150
        mock_dlg.max_hh_spin = MagicMock()
        mock_dlg.max_hh_spin.value.return_value = 350
        mock_dlg.kpi_delin_val = MagicMock()
        mock_dlg.kpi_merge_val = MagicMock()
        mock_dlg.kpi_merged_ea_val = MagicMock()
        mock_dlg.filter_previews = MagicMock()
        mock_dlg.output_folder_widget = MagicMock()
        mock_dlg.output_folder_widget.filePath.return_value = "C:/test"
        mock_dlg.merge_output_folder_widget = MagicMock()
        mock_dlg.merge_output_folder_widget.filePath.return_value = ""
        mock_dlg._get_ea_name = lambda feat, ean, fields: f"EA {ean}"

        # 1. Previous EA layer with two adjacent EAs in the same barangay "Barangay Alpha"
        prev_ea_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Prev_EAs", "memory")
        prev_ea_layer.dataProvider().addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("geocode", QVariant.String),
            QgsField("barangay", QVariant.String),
            QgsField("hh_count", QVariant.Double)
        ])
        prev_ea_layer.updateFields()

        # EA 001: polygon (0,0) to (1,1)
        f1 = QgsFeature(prev_ea_layer.fields())
        f1.setAttributes(["001", "017280010001", "Barangay Alpha", 50.0])
        f1.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"))

        # EA 002: adjacent polygon (1,0) to (2,1)
        f2 = QgsFeature(prev_ea_layer.fields())
        f2.setAttributes(["002", "017280010002", "Barangay Alpha", 120.0])
        f2.setGeometry(QgsGeometry.fromWkt("POLYGON((1 0, 2 0, 2 1, 1 1, 1 0))"))

        prev_ea_layer.dataProvider().addFeatures([f1, f2])

        # 2. Merged EA layer containing candidate EA 001
        merge_ea_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "Merge_EA", "memory")
        merge_ea_layer.dataProvider().addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("geocode", QVariant.String),
            QgsField("barangay", QVariant.String),
            QgsField("hh_count", QVariant.Double)
        ])
        merge_ea_layer.updateFields()
        mf1 = QgsFeature(merge_ea_layer.fields())
        mf1.setAttributes(["001", "017280010001", "Barangay Alpha", 50.0])
        mf1.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"))
        merge_ea_layer.dataProvider().addFeatures([mf1])

        mock_dlg._safe_get_layer.side_effect = lambda combo: (
            prev_ea_layer if combo in (mock_dlg.prev_ea_combo, getattr(mock_dlg, 'merge_prev_ea_combo', None))
            else merge_ea_layer
        )

        EALauncherDialog.generate_preview(mock_dlg)

        # Verify all_merged_ea_candidates has EA 001 and detected neighbor EA 002
        self.assertEqual(len(mock_dlg.all_merged_ea_candidates), 1)
        cand = mock_dlg.all_merged_ea_candidates[0]
        self.assertEqual(cand[0], "001")
        self.assertEqual(len(cand[5]), 1)  # Neighbors list
        self.assertEqual(cand[5][0][0], "002")
        self.assertEqual(cand[5][0][1], 120.0)

        # Verify rendered table cell dropdown is enabled with partner EA 002
        table = EALauncherDialog._create_preview_table(mock_dlg, include_merge_partner=True)
        EALauncherDialog._populate_table_rows(mock_dlg, table, mock_dlg.all_merged_ea_candidates, is_delineation=False)
        combo = table.cellWidget(0, 5)
        self.assertIsNotNone(combo)
        self.assertTrue(combo.isEnabled())
        self.assertEqual(combo.currentText(), "002")
        self.assertEqual(table.item(0, 6).text(), "170")  # 50 + 120


if __name__ == "__main__":
    unittest.main()



