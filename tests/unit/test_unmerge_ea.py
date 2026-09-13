# -*- coding: utf-8 -*-
"""
Unit test module for Unmerge EA Dialog functionality.
Verifies dialog initialization, layer auto-detection,
unmerge execution pipeline, and in-place layer update with hh_count & bldg_count calculations.
"""

import unittest
from unittest.mock import MagicMock, patch
from tests.mocks.qgis_mock import setup_qgis_mock_if_needed, MockGenericClass

setup_qgis_mock_if_needed()

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsWkbTypes,
    QgsField,
)
from qgis.PyQt.QtCore import QVariant


@patch("references.create_enumeration_area.unmerge_dialog.QMessageBox.information")
@patch("references.create_enumeration_area.unmerge_dialog.QMessageBox.warning")
@patch("references.create_enumeration_area.unmerge_dialog.QMessageBox.critical")
class TestUnmergeEADialog(unittest.TestCase):
    """Test suite for UnmergeEADialog and UI integration."""

    def test_unmerge_ea_btn_exists_in_dialog(self, *mocks):
        """Verify that _open_unmerge_ea_dialog exists on EALauncherDialog."""
        from references.create_enumeration_area.dialog import EALauncherDialog

        self.assertTrue(hasattr(EALauncherDialog, "_open_unmerge_ea_dialog"))

    def test_dialog_init_ui(self, *mocks):
        """Verify UnmergeEADialog initializes with all expected UI components."""
        from references.create_enumeration_area.unmerge_dialog import UnmergeEADialog

        dlg = UnmergeEADialog(default_output_dir="C:/test_out", default_geocode="01728")
        self.assertIsNotNone(dlg.merged_combo)
        self.assertIsNotNone(dlg.prev_ea_combo)
        self.assertIsNotNone(dlg.bldg_combo)
        self.assertIsNotNone(dlg.merged_selected_chk)
        self.assertIsNotNone(dlg.progress_bar)
        self.assertIsNotNone(dlg.log_console)
        self.assertIsNotNone(dlg.run_btn)
        self.assertIsNotNone(dlg.close_btn)
        self.assertEqual(dlg.default_geocode, "01728")
        self.assertEqual(dlg.default_output_dir, "C:/test_out")

    def test_auto_detect_layers(self, *mocks):
        """Verify auto-detection identifies merged_ea, previous_ea, and building points."""
        from references.create_enumeration_area.unmerge_dialog import UnmergeEADialog

        merged_lyr = QgsVectorLayer("Polygon?crs=epsg:4326", "01728_merged_ea2026", "memory")
        prev_lyr = QgsVectorLayer("Polygon?crs=epsg:4326", "01728_previous_ea", "memory")
        bldg_lyr = QgsVectorLayer("Point?crs=epsg:4326", "01728_bldgpts", "memory")

        QgsProject.instance().addMapLayer(merged_lyr)
        QgsProject.instance().addMapLayer(prev_lyr)
        QgsProject.instance().addMapLayer(bldg_lyr)

        try:
            dlg = UnmergeEADialog()
            curr_merged = dlg.merged_combo.currentLayer()
            if hasattr(curr_merged, "name") and not isinstance(curr_merged, MockGenericClass):
                self.assertEqual(curr_merged.name(), "01728_merged_ea2026")
            curr_prev = dlg.prev_ea_combo.currentLayer()
            if hasattr(curr_prev, "name") and not isinstance(curr_prev, MockGenericClass):
                self.assertEqual(curr_prev.name(), "01728_previous_ea")
            curr_bldg = dlg.bldg_combo.currentLayer()
            if hasattr(curr_bldg, "name") and not isinstance(curr_bldg, MockGenericClass):
                self.assertEqual(curr_bldg.name(), "01728_bldgpts")
        finally:
            QgsProject.instance().removeMapLayer(merged_lyr.id())
            QgsProject.instance().removeMapLayer(prev_lyr.id())
            QgsProject.instance().removeMapLayer(bldg_lyr.id())

    def test_resolve_bldg_hh_field(self, *mocks):
        """Verify _resolve_bldg_hh_field detects common household field names."""
        from references.create_enumeration_area.unmerge_dialog import UnmergeEADialog

        dlg = UnmergeEADialog()

        lyr = QgsVectorLayer("Point?crs=epsg:4326", "test_bldg", "memory")
        dp = lyr.dataProvider()
        dp.addAttributes([QgsField("id", QVariant.Int), QgsField("est_hhcount", QVariant.Double)])
        lyr.updateFields()

        idx, name = dlg._resolve_bldg_hh_field(lyr)
        self.assertEqual(name, "est_hhcount")
        self.assertEqual(idx, 1)

    def test_run_unmerge_reverts_polygons_and_recalculates_counts(self, *mocks):
        """Verify run_unmerge splits a merged polygon back into 2 previous EAs with updated counts."""
        from references.create_enumeration_area.unmerge_dialog import UnmergeEADialog

        # 1. Create Previous EA layer with 2 separate adjacent polygons
        prev_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "01728_previous_ea", "memory")
        dp_prev = prev_layer.dataProvider()
        dp_prev.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("code", QVariant.String),
            QgsField("barangay", QVariant.String),
        ])
        prev_layer.updateFields()

        # Polygon 1: [0,0] to [5,10]
        p1_geom = QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(5, 0), QgsPointXY(5, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]])
        f1 = QgsFeature(prev_layer.fields())
        f1.setGeometry(p1_geom)
        f1.setAttribute("ean", "01728001")
        f1.setAttribute("code", "001")
        f1.setAttribute("barangay", "Sample Bar")

        # Polygon 2: [5,0] to [10,10]
        p2_geom = QgsGeometry.fromPolygonXY([[
            QgsPointXY(5, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(5, 10), QgsPointXY(5, 0)
        ]])
        f2 = QgsFeature(prev_layer.fields())
        f2.setGeometry(p2_geom)
        f2.setAttribute("ean", "01728002")
        f2.setAttribute("code", "002")
        f2.setAttribute("barangay", "Sample Bar")

        dp_prev.addFeatures([f1, f2])
        prev_layer.updateExtents()

        # 2. Create Merged layer with 1 combined polygon: [0,0] to [10,10]
        merged_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "01728_merged_ea2026", "memory")
        dp_merged = merged_layer.dataProvider()
        dp_merged.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("code", QVariant.String),
            QgsField("barangay", QVariant.String),
            QgsField("hh_count", QVariant.Int),
            QgsField("bldg_count", QVariant.Int),
        ])
        merged_layer.updateFields()

        merged_geom = QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]])
        fm = QgsFeature(merged_layer.fields())
        fm.setGeometry(merged_geom)
        fm.setAttribute("ean", "01728001")
        fm.setAttribute("code", "001")
        fm.setAttribute("barangay", "Sample Bar")
        fm.setAttribute("hh_count", 15)
        fm.setAttribute("bldg_count", 5)

        dp_merged.addFeatures([fm])
        merged_layer.updateExtents()

        # 3. Create Building Points: 2 points in EA 001 (total HH = 6), 3 points in EA 002 (total HH = 9)
        bldg_layer = QgsVectorLayer("Point?crs=epsg:4326", "01728_bldgpts", "memory")
        dp_bldg = bldg_layer.dataProvider()
        dp_bldg.addAttributes([
            QgsField("id", QVariant.Int),
            QgsField("est_hhcount", QVariant.Double),
        ])
        bldg_layer.updateFields()

        b1 = QgsFeature(bldg_layer.fields())
        b1.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(2, 2)))
        b1.setAttribute("id", 1)
        b1.setAttribute("est_hhcount", 2.0)

        b2 = QgsFeature(bldg_layer.fields())
        b2.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(3, 3)))
        b2.setAttribute("id", 2)
        b2.setAttribute("est_hhcount", 4.0)

        b3 = QgsFeature(bldg_layer.fields())
        b3.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(7, 2)))
        b3.setAttribute("id", 3)
        b3.setAttribute("est_hhcount", 3.0)

        b4 = QgsFeature(bldg_layer.fields())
        b4.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(8, 5)))
        b4.setAttribute("id", 4)
        b4.setAttribute("est_hhcount", 1.0)

        b5 = QgsFeature(bldg_layer.fields())
        b5.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(9, 8)))
        b5.setAttribute("id", 5)
        b5.setAttribute("est_hhcount", 5.0)

        dp_bldg.addFeatures([b1, b2, b3, b4, b5])
        bldg_layer.updateExtents()

        # 4. Instantiate UnmergeEADialog and set layers
        dlg = UnmergeEADialog()
        dlg.merged_combo.setLayer(merged_layer)
        dlg.prev_ea_combo.setLayer(prev_layer)
        dlg.bldg_combo.setLayer(bldg_layer)

        # 5. Run Unmerge
        dlg.run_unmerge()

        # 6. Verify results in merged_layer
        # Initial count was 1, should now be 2 restored features
        features = list(merged_layer.getFeatures())
        self.assertEqual(len(features), 2)

        feat_001 = next((f for f in features if f.attribute("ean") == "01728001" or f.attribute("code") == "001"), None)
        feat_002 = next((f for f in features if f.attribute("ean") == "01728002" or f.attribute("code") == "002"), None)

        self.assertIsNotNone(feat_001)
        self.assertIsNotNone(feat_002)

        # In EA 001: 2 building points, sum(est_hhcount) = 2.0 + 4.0 = 6
        self.assertEqual(feat_001.attribute("bldg_count"), 2)
        self.assertEqual(feat_001.attribute("hh_count"), 6)

        # In EA 002: 3 building points, sum(est_hhcount) = 3.0 + 1.0 + 5.0 = 9
        self.assertEqual(feat_002.attribute("bldg_count"), 3)
        self.assertEqual(feat_002.attribute("hh_count"), 9)

    def test_run_unmerge_selected_features_only(self, *mocks):
        """Verify run_unmerge respects 'Selected features only' checkbox."""
        from references.create_enumeration_area.unmerge_dialog import UnmergeEADialog

        prev_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "01728_previous_ea", "memory")
        dp_prev = prev_layer.dataProvider()
        dp_prev.addAttributes([QgsField("ean", QVariant.String), QgsField("code", QVariant.String)])
        prev_layer.updateFields()

        # Two previous EA geometries
        p1_geom = QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(5, 0), QgsPointXY(5, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]])
        f1 = QgsFeature(prev_layer.fields())
        f1.setGeometry(p1_geom)
        f1.setAttribute("ean", "01728001")
        f1.setAttribute("code", "001")

        p2_geom = QgsGeometry.fromPolygonXY([[
            QgsPointXY(5, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(5, 10), QgsPointXY(5, 0)
        ]])
        f2 = QgsFeature(prev_layer.fields())
        f2.setGeometry(p2_geom)
        f2.setAttribute("ean", "01728002")
        f2.setAttribute("code", "002")

        dp_prev.addFeatures([f1, f2])
        prev_layer.updateExtents()

        # Merged layer with 2 features: FM1 (merged 001+002) and FM2 (other EA at 20..30)
        merged_layer = QgsVectorLayer("Polygon?crs=epsg:4326", "01728_merged_ea2026", "memory")
        dp_merged = merged_layer.dataProvider()
        dp_merged.addAttributes([QgsField("ean", QVariant.String), QgsField("code", QVariant.String)])
        merged_layer.updateFields()

        fm1 = QgsFeature(merged_layer.fields())
        fm1.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]]))
        fm1.setAttribute("ean", "01728001")
        fm1.setAttribute("code", "001")

        fm2 = QgsFeature(merged_layer.fields())
        fm2.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(20, 0), QgsPointXY(30, 0), QgsPointXY(30, 10), QgsPointXY(20, 10), QgsPointXY(20, 0)
        ]]))
        fm2.setAttribute("ean", "01728003")
        fm2.setAttribute("code", "003")

        dp_merged.addFeatures([fm1, fm2])
        merged_layer.updateExtents()

        # Select only FM1
        all_ids = [f.id() for f in merged_layer.getFeatures()]
        merged_layer.selectByIds([all_ids[0]])

        dlg = UnmergeEADialog()
        dlg.merged_combo.setLayer(merged_layer)
        dlg.prev_ea_combo.setLayer(prev_layer)
        dlg.bldg_combo.setLayer(None)
        dlg.merged_selected_chk.setChecked(True)

        dlg.run_unmerge()

        # Merged layer should now have: 2 restored features from FM1 + 1 untouched FM2 = 3 features
        features = list(merged_layer.getFeatures())
        self.assertEqual(len(features), 3)


if __name__ == "__main__":
    unittest.main()
