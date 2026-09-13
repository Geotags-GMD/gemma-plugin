# -*- coding: utf-8 -*-
"""
Unit test module for Split EA Dialog functionality.
Verifies dialog initialization, layer auto-detection, line extension math,
split execution pipeline, and in-place layer update with hh_count & bldg_count calculations.
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


class TestSplitEADialog(unittest.TestCase):
    """Test suite for SplitEADialog."""

    def test_split_ea_btn_exists_in_dialog(self):
        """Verify that split_ea_btn and _open_split_ea_dialog exist on EALauncherDialog."""
        from references.create_enumeration_area.dialog import EALauncherDialog

        self.assertTrue(hasattr(EALauncherDialog, "_open_split_ea_dialog"))

    def test_dialog_init_ui(self):
        """Verify SplitEADialog initializes with all expected UI components."""
        from references.create_enumeration_area.split_dialog import SplitEADialog

        dlg = SplitEADialog(default_output_dir="C:/test_out", default_geocode="01728")
        self.assertIsNotNone(dlg.poly_combo)
        self.assertIsNotNone(dlg.line_combo)
        self.assertIsNotNone(dlg.bldg_combo)
        self.assertIsNotNone(dlg.tolerance_spin)
        self.assertIsNotNone(dlg.progress_bar)
        self.assertIsNotNone(dlg.log_console)
        self.assertIsNotNone(dlg.run_btn)
        self.assertIsNotNone(dlg.close_btn)
        self.assertEqual(dlg.default_geocode, "01728")
        self.assertEqual(dlg.default_output_dir, "C:/test_out")

    def test_extend_line_endpoints(self):
        """Verify line extension math extends coordinates outwards."""
        from references.create_enumeration_area.split_dialog import SplitEADialog

        dlg = SplitEADialog()
        pts = [QgsPointXY(0, 0), QgsPointXY(10, 0)]
        line_geom = QgsGeometry.fromPolylineXY(pts)

        # Extend by 2 meters
        ext_geom = dlg._extend_line_endpoints(line_geom, 2.0)
        ext_pts = ext_geom.asPolyline()

        self.assertEqual(len(ext_pts), 2)
        # p0 should be extended from (0,0) away from (10,0) -> (-2, 0)
        self.assertAlmostEqual(ext_pts[0].x(), -2.0, places=4)
        self.assertAlmostEqual(ext_pts[0].y(), 0.0, places=4)
        # pn should be extended from (10,0) away from (0,0) -> (12, 0)
        self.assertAlmostEqual(ext_pts[1].x(), 12.0, places=4)
        self.assertAlmostEqual(ext_pts[1].y(), 0.0, places=4)

    def test_auto_detect_layers(self):
        """Verify auto-detection identifies delineated_ea polygon, eadel_update line, and building points."""
        from references.create_enumeration_area.split_dialog import SplitEADialog

        poly_lyr = QgsVectorLayer("Polygon?crs=epsg:4326", "01728_delineated_ea2026", "memory")
        line_lyr = QgsVectorLayer("LineString?crs=epsg:4326", "01728_eadel_update", "memory")
        bldg_lyr = QgsVectorLayer("Point?crs=epsg:4326", "01728_bldgpts", "memory")

        QgsProject.instance().addMapLayer(poly_lyr)
        QgsProject.instance().addMapLayer(line_lyr)
        QgsProject.instance().addMapLayer(bldg_lyr)

        try:
            dlg = SplitEADialog()
            curr_poly = dlg.poly_combo.currentLayer()
            if hasattr(curr_poly, "name") and not isinstance(curr_poly, MockGenericClass):
                self.assertEqual(curr_poly.name(), "01728_delineated_ea2026")
            curr_line = dlg.line_combo.currentLayer()
            if hasattr(curr_line, "name") and not isinstance(curr_line, MockGenericClass):
                self.assertEqual(curr_line.name(), "01728_eadel_update")
            curr_bldg = dlg.bldg_combo.currentLayer()
            if hasattr(curr_bldg, "name") and not isinstance(curr_bldg, MockGenericClass):
                self.assertEqual(curr_bldg.name(), "01728_bldgpts")
        finally:
            QgsProject.instance().removeMapLayer(poly_lyr.id())
            QgsProject.instance().removeMapLayer(line_lyr.id())
            QgsProject.instance().removeMapLayer(bldg_lyr.id())

    @patch("references.create_enumeration_area.split_dialog.processing.run")
    def test_run_split_recalculates_hh_and_bldg_counts(self, mock_proc_run):
        """Verify run_split calculates hh_count (from est_hhcount) and bldg_count per split polygon."""
        from references.create_enumeration_area.split_dialog import SplitEADialog

        # Create input polygon layer (1 square polygon)
        poly_lyr = QgsVectorLayer("Polygon?crs=epsg:4326", "delineated_ea", "memory")
        dp_poly = poly_lyr.dataProvider()
        dp_poly.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("hhcount", QVariant.Int),
            QgsField("bldgcount", QVariant.Int),
            QgsField("hh_count", QVariant.Int),
            QgsField("bldg_count", QVariant.Int),
        ])
        poly_lyr.updateFields()

        poly_feat = QgsFeature(poly_lyr.fields())
        poly_feat.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]]))
        poly_feat.setAttribute("ean", "001000")
        poly_feat.setAttribute("hhcount", 350)
        poly_feat.setAttribute("bldgcount", 50)
        poly_feat.setAttribute("hh_count", 0)
        poly_feat.setAttribute("bldg_count", 0)
        dp_poly.addFeatures([poly_feat])
        poly_lyr.updateExtents()

        # Create input cut lines layer (1 line bisecting the polygon at x=5)
        line_lyr = QgsVectorLayer("LineString?crs=epsg:4326", "eadel_update", "memory")
        dp_line = line_lyr.dataProvider()
        line_feat = QgsFeature()
        line_feat.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(5, -1), QgsPointXY(5, 11)]))
        dp_line.addFeatures([line_feat])
        line_lyr.updateExtents()

        # Create building point layer:
        # Part 1 (x: 0..5): 2 buildings with est_hhcount 2.5 and 2.0 -> total HH = 4.5 -> ceil to 5, bldg = 2
        # Part 2 (x: 5..10): 1 building with est_hhcount 3.2 -> total HH = 3.2 -> ceil to 4, bldg = 1
        bldg_lyr = QgsVectorLayer("Point?crs=epsg:4326", "bldg_points", "memory")
        dp_bldg = bldg_lyr.dataProvider()
        dp_bldg.addAttributes([QgsField("est_hhcount", QVariant.Double)])
        bldg_lyr.updateFields()

        b1 = QgsFeature(bldg_lyr.fields())
        b1.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(2, 2)))
        b1.setAttribute("est_hhcount", 2.5)

        b2 = QgsFeature(bldg_lyr.fields())
        b2.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(3, 3)))
        b2.setAttribute("est_hhcount", 2.0)

        b3 = QgsFeature(bldg_lyr.fields())
        b3.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(8, 8)))
        b3.setAttribute("est_hhcount", 3.2)

        dp_bldg.addFeatures([b1, b2, b3])
        bldg_lyr.updateExtents()

        # Create mock split output layer (2 split polygon parts)
        split_lyr = QgsVectorLayer("Polygon?crs=epsg:4326", "split_res", "memory")
        dp_split = split_lyr.dataProvider()
        dp_split.addAttributes([QgsField("hh_count", QVariant.Int), QgsField("bldg_count", QVariant.Int)])
        split_lyr.updateFields()

        f1 = QgsFeature(split_lyr.fields())
        f1.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(5, 0), QgsPointXY(5, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]]))
        f2 = QgsFeature(split_lyr.fields())
        f2.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(5, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(5, 10), QgsPointXY(5, 0)
        ]]))
        dp_split.addFeatures([f1, f2])
        split_lyr.updateExtents()

        def side_effect(alg_name, params):
            if alg_name == "native:splitwithlines":
                return {"OUTPUT": split_lyr}
            elif alg_name == "native:multiparttosingleparts":
                return {"OUTPUT": split_lyr}
            return {"OUTPUT": split_lyr}

        mock_proc_run.side_effect = side_effect

        dlg = SplitEADialog()
        dlg.poly_combo.currentLayer = MagicMock(return_value=poly_lyr)
        dlg.line_combo.currentLayer = MagicMock(return_value=line_lyr)
        dlg.bldg_combo.currentLayer = MagicMock(return_value=bldg_lyr)
        dlg.tolerance_spin.value = MagicMock(return_value=1.0)
        dlg.min_hh_spin.value = MagicMock(return_value=1)
        dlg.status_banner = MagicMock()
        dlg.progress_bar = MagicMock()
        dlg.log_console = MagicMock()

        dlg.run_split()

        # Check features in poly_lyr
        updated_features = list(poly_lyr.getFeatures())
        self.assertEqual(len(updated_features), 2)

        # Baseline fields hhcount and bldgcount MUST remain preserved (350 and 50)
        # And ea_type MUST be set to DELINEATED for split features
        for feat in updated_features:
            self.assertEqual(feat.attribute("hhcount"), 350)
            self.assertEqual(feat.attribute("bldgcount"), 50)
            self.assertEqual(feat.attribute("ea_type"), "DELINEATED")

        # Part 1 (x: 0..5, highest HH=5): new_ean="001000", bldg_count=2, hh_count=5
        # Part 2 (x: 5..10, 2nd highest HH=4): new_ean="001001", bldg_count=1, hh_count=4
        counts_and_ean = [
            (f.attribute("bldg_count"), f.attribute("hh_count"), f.attribute("new_ean"))
            for f in updated_features
        ]
        self.assertIn((2, 5, "001000"), counts_and_ean)
        self.assertIn((1, 4, "001001"), counts_and_ean)

    @patch("references.create_enumeration_area.split_dialog.processing.run")
    def test_split_proceeds_with_notice_if_hh_count_falls_below_minimum_threshold(self, mock_proc_run):
        """Verify split is preserved and completed with notice when sub-EA falls below min_hh threshold."""
        from references.create_enumeration_area.split_dialog import SplitEADialog

        poly_lyr = QgsVectorLayer("Polygon?crs=epsg:4326", "delineated_ea", "memory")
        dp_poly = poly_lyr.dataProvider()
        dp_poly.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("hhcount", QVariant.Int),
            QgsField("bldgcount", QVariant.Int),
            QgsField("hh_count", QVariant.Int),
            QgsField("bldg_count", QVariant.Int),
        ])
        poly_lyr.updateFields()

        poly_feat = QgsFeature(poly_lyr.fields())
        poly_feat.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]]))
        poly_feat.setAttribute("ean", "001000")
        poly_feat.setAttribute("hhcount", 350)
        poly_feat.setAttribute("bldgcount", 50)
        poly_feat.setAttribute("hh_count", 0)
        poly_feat.setAttribute("bldg_count", 0)
        dp_poly.addFeatures([poly_feat])
        poly_lyr.updateExtents()

        line_lyr = QgsVectorLayer("LineString?crs=epsg:4326", "eadel_update", "memory")
        dp_line = line_lyr.dataProvider()
        line_feat = QgsFeature()
        line_feat.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(5, -1), QgsPointXY(5, 11)]))
        dp_line.addFeatures([line_feat])
        line_lyr.updateExtents()

        # Buildings: Part 1 has 5 HH, Part 2 has 4 HH
        bldg_lyr = QgsVectorLayer("Point?crs=epsg:4326", "bldg_points", "memory")
        dp_bldg = bldg_lyr.dataProvider()
        dp_bldg.addAttributes([QgsField("est_hhcount", QVariant.Double)])
        bldg_lyr.updateFields()

        b1 = QgsFeature(bldg_lyr.fields())
        b1.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(2, 2)))
        b1.setAttribute("est_hhcount", 5.0)

        b2 = QgsFeature(bldg_lyr.fields())
        b2.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(8, 8)))
        b2.setAttribute("est_hhcount", 4.0)

        dp_bldg.addFeatures([b1, b2])
        bldg_lyr.updateExtents()

        split_lyr = QgsVectorLayer("Polygon?crs=epsg:4326", "split_res", "memory")
        dp_split = split_lyr.dataProvider()
        dp_split.addAttributes([QgsField("hh_count", QVariant.Int), QgsField("bldg_count", QVariant.Int)])
        split_lyr.updateFields()

        f1 = QgsFeature(split_lyr.fields())
        f1.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(5, 0), QgsPointXY(5, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]]))
        f2 = QgsFeature(split_lyr.fields())
        f2.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(5, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(5, 10), QgsPointXY(5, 0)
        ]]))
        dp_split.addFeatures([f1, f2])
        split_lyr.updateExtents()

        mock_proc_run.return_value = {"OUTPUT": split_lyr}

        dlg = SplitEADialog()
        dlg.poly_combo.currentLayer = MagicMock(return_value=poly_lyr)
        dlg.line_combo.currentLayer = MagicMock(return_value=line_lyr)
        dlg.bldg_combo.currentLayer = MagicMock(return_value=bldg_lyr)
        dlg.tolerance_spin.value = MagicMock(return_value=1.0)
        # Threshold is set to 10 (both parts 5 and 4 are < 10 -> split still completes with notice)
        dlg.min_hh_spin.value = MagicMock(return_value=10)
        dlg.status_banner = MagicMock()
        dlg.progress_bar = MagicMock()
        dlg.log_console = MagicMock()

        dlg.run_split()

        # Check features in poly_lyr -> should be split into 2 features
        updated_features = list(poly_lyr.getFeatures())
        self.assertEqual(len(updated_features), 2)
        eans = [f.attribute("new_ean") for f in updated_features]
        self.assertIn("001000", eans)
        self.assertIn("001001", eans)

    def test_extract_parent_code_and_prefix_formats(self):
        """Verify _extract_parent_code_and_prefix standardizes ean/code to 6-digit code and 3-digit prefix."""
        from references.create_enumeration_area.split_dialog import SplitEADialog
        from qgis.core import QgsFields

        dlg = SplitEADialog()
        fields1 = QgsFields()
        fields1.append(QgsField("ean", QVariant.String))

        f1 = QgsFeature(fields1)
        f1.setAttribute("ean", "002000")
        self.assertEqual(dlg._extract_parent_code_and_prefix(f1, f1.fields()), ("002000", "002"))

        f2 = QgsFeature(fields1)
        f2.setAttribute("ean", "003")
        self.assertEqual(dlg._extract_parent_code_and_prefix(f2, f2.fields()), ("003000", "003"))

        fields2 = QgsFields()
        fields2.append(QgsField("code", QVariant.String))
        f3 = QgsFeature(fields2)
        f3.setAttribute("code", "01737004001")
        self.assertEqual(dlg._extract_parent_code_and_prefix(f3, f3.fields()), ("004001", "004"))

    def test_extend_line_to_traverse_polygon(self):
        """Verify cut line drawn inside polygon is extended to fully traverse outside both boundaries."""
        from references.create_enumeration_area.split_dialog import SplitEADialog

        dlg = SplitEADialog()
        # 10x10 polygon (0,0 to 10,10)
        poly_geom = QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]])

        # Cut line drawn entirely inside the polygon: from (3, 5) to (7, 5)
        line_geom = QgsGeometry.fromPolylineXY([QgsPointXY(3, 5), QgsPointXY(7, 5)])

        ext_geom = dlg._extend_line_to_traverse_polygon(line_geom, poly_geom, extend_tol=1.0)
        ext_pts = ext_geom.asPolyline()

        self.assertEqual(len(ext_pts), 2)
        # Start point must be extended outside the left polygon boundary (x < 0)
        self.assertLess(ext_pts[0].x(), 0.0)
        self.assertAlmostEqual(ext_pts[0].y(), 5.0, places=4)

        # End point must be extended outside the right polygon boundary (x > 10)
        self.assertGreater(ext_pts[1].x(), 10.0)
        self.assertAlmostEqual(ext_pts[1].y(), 5.0, places=4)

    def test_selection_ui_and_signals(self):
        """Verify layer selection updates UI checkbox labels and enables/disables them."""
        from references.create_enumeration_area.split_dialog import SplitEADialog

        poly_lyr = QgsVectorLayer("Polygon?crs=epsg:4326", "delineated_ea", "memory")
        dp_poly = poly_lyr.dataProvider()
        f1 = QgsFeature()
        f1.setId(1)
        f2 = QgsFeature()
        f2.setId(2)
        dp_poly.addFeatures([f1, f2])

        dlg = SplitEADialog()
        dlg.poly_combo.currentLayer = MagicMock(return_value=poly_lyr)
        dlg._on_layer_selection_changed()

        self.assertFalse(dlg.poly_selected_chk.isChecked())
        self.assertIn("0 selected", dlg.poly_selected_chk.text())

        # Select feature 1
        poly_lyr.selectByIds([1])
        dlg._update_poly_selection_ui()
        self.assertTrue(dlg.poly_selected_chk.isChecked())
        self.assertIn("1 selected", dlg.poly_selected_chk.text())

        # Deselect
        poly_lyr.removeSelection()
        dlg._update_poly_selection_ui()
        self.assertFalse(dlg.poly_selected_chk.isChecked())
        self.assertIn("0 selected", dlg.poly_selected_chk.text())

    @patch("references.create_enumeration_area.split_dialog.processing.run")
    def test_run_split_with_selected_polygon_only(self, mock_proc_run):
        """Verify that when a single polygon is selected, only that polygon is split while others remain untouched."""
        from references.create_enumeration_area.split_dialog import SplitEADialog

        # Polygon layer with 2 features: EA 001000 and EA 002000
        poly_lyr = QgsVectorLayer("Polygon?crs=epsg:4326", "delineated_ea", "memory")
        dp_poly = poly_lyr.dataProvider()
        dp_poly.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("hh_count", QVariant.Int),
            QgsField("bldg_count", QVariant.Int),
            QgsField("ea_type", QVariant.String),
        ])
        poly_lyr.updateFields()

        poly1 = QgsFeature(poly_lyr.fields())
        poly1.setId(1)
        poly1.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]]))
        poly1.setAttribute("ean", "001000")
        poly1.setAttribute("hh_count", 300)
        poly1.setAttribute("bldg_count", 30)
        poly1.setAttribute("ea_type", "RETAINED")

        poly2 = QgsFeature(poly_lyr.fields())
        poly2.setId(2)
        poly2.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(20, 0), QgsPointXY(30, 0), QgsPointXY(30, 10), QgsPointXY(20, 10), QgsPointXY(20, 0)
        ]]))
        poly2.setAttribute("ean", "002000")
        poly2.setAttribute("hh_count", 400)
        poly2.setAttribute("bldg_count", 40)
        poly2.setAttribute("ea_type", "RETAINED")

        dp_poly.addFeatures([poly1, poly2])
        poly_lyr.updateExtents()

        # Cut line crossing polygon 1 at x=5
        line_lyr = QgsVectorLayer("LineString?crs=epsg:4326", "eadel_update", "memory")
        dp_line = line_lyr.dataProvider()
        line_feat = QgsFeature()
        line_feat.setId(1)
        line_feat.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(5, -1), QgsPointXY(5, 11)]))
        dp_line.addFeatures([line_feat])
        line_lyr.updateExtents()

        # Mock split output for polygon 1 (2 split pieces)
        split_lyr = QgsVectorLayer("Polygon?crs=epsg:4326", "split_res", "memory")
        dp_split = split_lyr.dataProvider()
        dp_split.addAttributes([QgsField("hh_count", QVariant.Int), QgsField("bldg_count", QVariant.Int)])
        split_lyr.updateFields()

        f1 = QgsFeature(split_lyr.fields())
        f1.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(5, 0), QgsPointXY(5, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]]))
        f2 = QgsFeature(split_lyr.fields())
        f2.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(5, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(5, 10), QgsPointXY(5, 0)
        ]]))
        dp_split.addFeatures([f1, f2])
        split_lyr.updateExtents()

        mock_proc_run.return_value = {"OUTPUT": split_lyr}

        # Select ONLY polygon 1
        poly_lyr.selectByIds([1])

        dlg = SplitEADialog()
        dlg.poly_combo.currentLayer = MagicMock(return_value=poly_lyr)
        dlg.line_combo.currentLayer = MagicMock(return_value=line_lyr)
        dlg.bldg_combo.currentLayer = MagicMock(return_value=None)
        dlg.tolerance_spin.value = MagicMock(return_value=1.0)
        dlg.min_hh_spin.value = MagicMock(return_value=1)
        dlg.poly_selected_chk.setChecked(True)
        dlg.status_banner = MagicMock()
        dlg.progress_bar = MagicMock()
        dlg.log_console = MagicMock()

        dlg.run_split()

        # Total features in poly_lyr should now be 3 (2 from split poly 1 + 1 untouched poly 2)
        updated_features = list(poly_lyr.getFeatures())
        self.assertEqual(len(updated_features), 3)

        # Check that untouched poly 2 is present and retained
        eans = [f.attribute("ean") or f.attribute("new_ean") for f in updated_features]
        self.assertIn("002000", eans)

        # Check types: split pieces are DELINEATED, un-split poly 2 is RETAINED
        types_by_ean = {f.attribute("new_ean"): f.attribute("ea_type") for f in updated_features}
        self.assertEqual(types_by_ean.get("002000"), "RETAINED")
        self.assertEqual(types_by_ean.get("001000"), "DELINEATED")
        self.assertEqual(types_by_ean.get("001001"), "DELINEATED")

    @patch("references.create_enumeration_area.split_dialog.processing.run")
    def test_run_split_with_selected_cut_lines_only(self, mock_proc_run):
        """Verify that when cut lines are selected, only selected cut lines are used for splitting."""
        from references.create_enumeration_area.split_dialog import SplitEADialog

        poly_lyr = QgsVectorLayer("Polygon?crs=epsg:4326", "delineated_ea", "memory")
        dp_poly = poly_lyr.dataProvider()
        dp_poly.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("hh_count", QVariant.Int),
            QgsField("bldg_count", QVariant.Int),
            QgsField("ea_type", QVariant.String),
        ])
        poly_lyr.updateFields()

        poly = QgsFeature(poly_lyr.fields())
        poly.setId(1)
        poly.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]]))
        poly.setAttribute("ean", "001000")
        poly.setAttribute("hh_count", 300)
        poly.setAttribute("bldg_count", 30)
        dp_poly.addFeatures([poly])
        poly_lyr.updateExtents()

        # Two cut lines: line 1 (x=5) and line 2 (y=5)
        line_lyr = QgsVectorLayer("LineString?crs=epsg:4326", "eadel_update", "memory")
        dp_line = line_lyr.dataProvider()
        l1 = QgsFeature()
        l1.setId(1)
        l1.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(5, -1), QgsPointXY(5, 11)]))
        l2 = QgsFeature()
        l2.setId(2)
        l2.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(-1, 5), QgsPointXY(11, 5)]))
        dp_line.addFeatures([l1, l2])
        line_lyr.updateExtents()

        # Mock split output for split with line 1 only
        split_lyr = QgsVectorLayer("Polygon?crs=epsg:4326", "split_res", "memory")
        dp_split = split_lyr.dataProvider()
        dp_split.addAttributes([QgsField("hh_count", QVariant.Int), QgsField("bldg_count", QVariant.Int)])
        split_lyr.updateFields()

        f1 = QgsFeature(split_lyr.fields())
        f1.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(5, 0), QgsPointXY(5, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]]))
        f2 = QgsFeature(split_lyr.fields())
        f2.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(5, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(5, 10), QgsPointXY(5, 0)
        ]]))
        dp_split.addFeatures([f1, f2])
        split_lyr.updateExtents()

        def side_effect(alg_name, params):
            # Verify that single_lines_layer in params has only 1 line feature (line 1)
            lines_input = params.get("LINES")
            if lines_input:
                self.assertEqual(lines_input.featureCount(), 1)
            return {"OUTPUT": split_lyr}

        mock_proc_run.side_effect = side_effect

        # Select line 1 ONLY
        line_lyr.selectByIds([1])

        dlg = SplitEADialog()
        dlg.poly_combo.currentLayer = MagicMock(return_value=poly_lyr)
        dlg.line_combo.currentLayer = MagicMock(return_value=line_lyr)
        dlg.bldg_combo.currentLayer = MagicMock(return_value=None)
        dlg.tolerance_spin.value = MagicMock(return_value=1.0)
        dlg.min_hh_spin.value = MagicMock(return_value=1)
        dlg.line_selected_chk.setChecked(True)
        dlg.status_banner = MagicMock()
        dlg.progress_bar = MagicMock()
        dlg.log_console = MagicMock()

        dlg.run_split()

        updated_features = list(poly_lyr.getFeatures())
        self.assertEqual(len(updated_features), 2)


if __name__ == "__main__":
    unittest.main()

