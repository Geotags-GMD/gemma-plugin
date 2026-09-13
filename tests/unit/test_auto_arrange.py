# -*- coding: utf-8 -*-
"""
Unit test module for auto_arrange.py (gmd_scripts/auto_arrange.py).
Tests priority calculation, attribute-based prefix extraction, layer auto-arrange execution, and QML style auto-detection.
"""

import unittest
import importlib
from qgis.core import QgsVectorLayer, QgsField, QgsFeature
from qgis.PyQt.QtCore import QVariant
from tests.mocks.qgis_mock import setup_qgis_mock_if_needed

setup_qgis_mock_if_needed()


class TestAutoArrange(unittest.TestCase):
    """Test suite for auto_arrange module."""

    def setUp(self):
        self.mod = importlib.import_module("references.create_enumeration_area.auto_arrange")

    def test_module_import(self):
        """Verify module imports successfully."""
        self.assertIsNotNone(self.mod, "Module references.create_enumeration_area.auto_arrange should import successfully.")
        self.assertTrue(hasattr(self.mod, "auto_arrange_layers"))
        self.assertTrue(hasattr(self.mod, "extract_project_prefix"))
        self.assertTrue(hasattr(self.mod, "get_layer_group_and_rank"))
        self.assertTrue(hasattr(self.mod, "find_qml_style_for_layer"))

    def test_find_qml_style_for_layer(self):
        """Test base layer QML style matching for official style files."""
        self.assertEqual(self.mod.find_qml_style_for_layer("01716_extracted_bldgpts"), "extracted_bldgpts.qml")
        self.assertEqual(self.mod.find_qml_style_for_layer("01716_bldg_point"), "1. Base Layer Building Points.qml")
        self.assertEqual(self.mod.find_qml_style_for_layer("01716_sf_landmark"), "2. Base Layer Landmark.qml")
        self.assertEqual(self.mod.find_qml_style_for_layer("01716_old_landmark"), "2. Base Layer Landmark.qml")
        self.assertEqual(self.mod.find_qml_style_for_layer("01716_block"), "3. Base Layer Block.qml")
        self.assertEqual(self.mod.find_qml_style_for_layer("01716_ea"), "4. Base Layer EA.qml")
        self.assertEqual(self.mod.find_qml_style_for_layer("01716_bgy"), "5. Base Layer Barangay.qml")
        self.assertEqual(self.mod.find_qml_style_for_layer("01716_road"), "6. Base Layer Road.qml")
        self.assertEqual(self.mod.find_qml_style_for_layer("01716_river"), "7. Base Layer River.qml")
        self.assertEqual(self.mod.find_qml_style_for_layer("01716_railroad"), "8. Base Layer Railroad.qml")
        self.assertIsNone(self.mod.find_qml_style_for_layer("01716_gaps"))
        self.assertIsNone(self.mod.find_qml_style_for_layer("01716_overlaps"))

    def test_extract_project_prefix_from_attributes(self):
        """Test layer prefix extraction using geocode and city_mun feature attributes."""
        lyr = QgsVectorLayer("Polygon?crs=EPSG:4326", "01716_bgy", "memory")
        prov = lyr.dataProvider()
        prov.addAttributes([
            QgsField("geocode", QVariant.String),
            QgsField("city_mun", QVariant.String)
        ])
        lyr.updateFields()

        feat = QgsFeature(lyr.fields())
        feat.setAttribute("geocode", "01716001000000")
        feat.setAttribute("city_mun", "City of Iriga")
        prov.addFeatures([feat])

        prefix = self.mod.extract_project_prefix([lyr])
        self.assertEqual(prefix, "01716_City of Iriga_")

    def test_extract_project_prefix_fallback_to_name(self):
        """Test layer prefix extraction fallback using layer name."""
        lyr1 = QgsVectorLayer("Polygon?crs=EPSG:4326", "01716_City of Iriga_bgy", "memory")
        lyr2 = QgsVectorLayer("Polygon?crs=EPSG:4326", "01716_City of Iriga_ea", "memory")
        prefix = self.mod.extract_project_prefix([lyr1, lyr2])
        self.assertEqual(prefix, "01716_City of Iriga_")

    def test_get_layer_group_and_rank(self):
        """Test layer rank priority assignment for various layer names."""
        mbi_name = "01716_City of Iriga_MBI"
        base_name = "01716_City of Iriga_baselayers"

        grp, rank = self.mod.get_layer_group_and_rank("01716_bldg_point", 0, mbi_name, base_name)
        self.assertEqual(rank, 10)
        self.assertEqual(grp, base_name)

        grp, rank = self.mod.get_layer_group_and_rank("01716_road", 1, mbi_name, base_name)
        self.assertEqual(rank, 50)
        self.assertEqual(grp, base_name)

        grp, rank = self.mod.get_layer_group_and_rank("01716_ea", 2, mbi_name, base_name)
        self.assertEqual(rank, 60)
        self.assertEqual(grp, base_name)

        grp, rank = self.mod.get_layer_group_and_rank("01716_gaps", 2, mbi_name, base_name)
        self.assertEqual(rank, 10)
        self.assertEqual(grp, mbi_name)

        grp, rank = self.mod.get_layer_group_and_rank("01716_overlaps", 2, mbi_name, base_name)
        self.assertEqual(rank, 20)
        self.assertEqual(grp, mbi_name)

    def test_auto_arrange_layers_runs(self):
        """Test auto_arrange_layers function returns summary dictionary cleanly."""
        res = self.mod.auto_arrange_layers()
        self.assertIsInstance(res, dict)
        self.assertIn("total", res)
        self.assertIn("styled", res)
        self.assertIn("reordered", res)

    def test_auto_arrange_button_in_tab1_not_tab2(self):
        """Verify that Auto Arrange button is placed in Tab 1 and omitted from Tab 2."""
        import inspect
        from references.create_enumeration_area import dialog
        tab1_source = inspect.getsource(dialog.EALauncherDialog._build_pre_ea_tab)
        self.assertIn("pre_ea_auto_arrange_btn", tab1_source)
        self.assertIn("Auto Arrange", tab1_source)

        tab2_delin_source = inspect.getsource(dialog.EALauncherDialog._build_proposed_delineation_content)
        self.assertNotIn("self.auto_arrange_btn = QPushButton(\"Auto Arrange\")", tab2_delin_source)

        tab2_merge_source = inspect.getsource(dialog.EALauncherDialog._build_proposed_merging_content)
        self.assertNotIn("self.merge_auto_arrange_btn = QPushButton(\"Auto Arrange\")", tab2_merge_source)

    def test_auto_arrange_methods_exist_and_execute(self):
        """Verify that _pre_ea_auto_arrange_and_detect_layers and auto_arrange_and_detect_layers exist and run cleanly."""
        from unittest.mock import MagicMock
        from references.create_enumeration_area.dialog import EALauncherDialog

        mock_dlg = MagicMock(spec=EALauncherDialog)
        mock_dlg.pre_ea_log_console = MagicMock()
        mock_dlg.log_console = MagicMock()
        mock_dlg.merge_log_console = MagicMock()
        mock_dlg._pre_ea_auto_detect_layers = MagicMock()
        mock_dlg.auto_detect_layers = MagicMock()
        mock_dlg._ea_merge_auto_detect_ea_layer = MagicMock()

        EALauncherDialog._pre_ea_auto_arrange_and_detect_layers(mock_dlg)
        mock_dlg._pre_ea_auto_detect_layers.assert_called_once()
        mock_dlg.auto_detect_layers.assert_called_once()
        mock_dlg._ea_merge_auto_detect_ea_layer.assert_called_once()
        mock_dlg.pre_ea_log_console.append.assert_called_once()

        # Test delegation
        mock_dlg.reset_mock()
        mock_dlg._pre_ea_auto_arrange_and_detect_layers = MagicMock()
        EALauncherDialog.auto_arrange_and_detect_layers(mock_dlg)
        mock_dlg._pre_ea_auto_arrange_and_detect_layers.assert_called_once()


if __name__ == "__main__":
    unittest.main()
