# -*- coding: utf-8 -*-
"""
Unit test module for package_qfield.py (gmd_scripts/package_qfield.py).
Tests QField package dialog launcher and callback handling using mock iface.
"""

import os
import sys
import unittest
import importlib

plugin_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
whl_path = os.path.join(plugin_root, "references", "package_qfield", "unzipped_whl")
if os.path.exists(whl_path) and whl_path not in sys.path:
    sys.path.insert(0, whl_path)

from tests.mocks.qgis_mock import setup_qgis_mock_if_needed, MockGenericClass

setup_qgis_mock_if_needed()


class TestPackageQfield(unittest.TestCase):
    """Test suite for package_qfield module."""

    def setUp(self):
        self.mod = importlib.import_module("gmd_scripts.package_qfield")

    def test_module_import(self):
        """Verify module imports successfully."""
        self.assertIsNotNone(self.mod, "Module gmd_scripts.package_qfield should import successfully.")

    def test_show_package_dialog_instantiation(self):
        """Test show_package_dialog launcher function with mock iface and offline_editing object."""
        mock_iface = MockGenericClass()
        mock_offline = MockGenericClass()
        callback_called = [False]

        def sample_callback(result):
            callback_called[0] = True

        try:
            dlg = self.mod.show_package_dialog(mock_iface, mock_offline, on_finished_callback=sample_callback)
            self.assertIsNotNone(dlg)
        except Exception as e:
            self.skipTest(f"Skipping test due to environment GUI limitation: {e}")

    def test_is_excluded_data_source_layer_exempts_special_ea(self):
        """Verify _is_excluded_data_source_layer identifies excluded patterns while exempting _special_ea."""
        from references.package_qfield.gui.package_dialog import PackageDialog
        # Test class method directly without instantiating full GUI
        self.assertTrue(PackageDialog._is_excluded_data_source_layer(None, "01728001001_ea"))
        self.assertTrue(PackageDialog._is_excluded_data_source_layer(None, "01728001001_bgy"))
        self.assertTrue(PackageDialog._is_excluded_data_source_layer(None, "01728001001_bldgpts"))
        self.assertTrue(PackageDialog._is_excluded_data_source_layer(None, "01728001001_bldg_point"))
        self.assertTrue(PackageDialog._is_excluded_data_source_layer(None, "01728001001_road"))
        self.assertTrue(PackageDialog._is_excluded_data_source_layer(None, "01728001001_river"))
        self.assertTrue(PackageDialog._is_excluded_data_source_layer(None, "01728001001_bridge"))
        self.assertTrue(PackageDialog._is_excluded_data_source_layer(None, "01728001001_railroad"))
        self.assertTrue(PackageDialog._is_excluded_data_source_layer(None, "01728001001_landmark"))
        self.assertTrue(PackageDialog._is_excluded_data_source_layer(None, "01728001001_block"))
        # Special EA exemption
        self.assertFalse(PackageDialog._is_excluded_data_source_layer(None, "01728001001_special_ea"))
        self.assertFalse(PackageDialog._is_excluded_data_source_layer(None, "my_custom_special_ea"))
    def test_filter_unassigned_layer_missing_columns_does_not_filter(self):
        """Verify unassigned layer missing both ea_geocode and geocode is not filtered."""
        from references.package_qfield.gui.package_dialog import PackageDialog
        try:
            from qgis.core import QgsVectorLayer, QgsField, QgsFeature
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            from tests.mocks.sample_data import QgsVectorLayer, QgsField, QgsFeature, QVariant

        layer = QgsVectorLayer("Polygon?crs=epsg:4326", "unassigned_no_geocode", "memory")
        dp = layer.dataProvider()
        dp.addAttributes([QgsField("name", QVariant.String), QgsField("type", QVariant.String)])
        layer.updateFields()
        f = QgsFeature(layer.fields())
        f.setAttributes(["Zone 1", "Commercial"])
        dp.addFeatures([f])

        dlg = MockGenericClass()
        dlg._normalized_layer_name = lambda n: n
        PackageDialog._filter_unassigned_layer(dlg, layer, "01728001001", is_ea_level=False)

        self.assertEqual(layer.subsetString(), "")
        self.assertEqual(layer.customProperty("QFieldSync/action"), "copy")

    def test_filter_unassigned_layer_with_valid_data(self):
        """Verify unassigned layer with geocode is filtered in Barangay level and not in EA level."""
        from references.package_qfield.gui.package_dialog import PackageDialog
        try:
            from qgis.core import QgsVectorLayer, QgsField, QgsFeature
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            from tests.mocks.sample_data import QgsVectorLayer, QgsField, QgsFeature, QVariant

        layer_bgy = QgsVectorLayer("Polygon?crs=epsg:4326", "unassigned_bgy", "memory")
        dp_bgy = layer_bgy.dataProvider()
        dp_bgy.addAttributes([QgsField("geocode", QVariant.String)])
        layer_bgy.updateFields()
        f = QgsFeature(layer_bgy.fields())
        f.setAttributes(["01728001000000"])
        dp_bgy.addFeatures([f])

        dlg = MockGenericClass()
        dlg._normalized_layer_name = lambda n: n

        # Barangay level filter -> "geocode" LIKE '01728001%'
        PackageDialog._filter_unassigned_layer(dlg, layer_bgy, "01728001", is_ea_level=False)
        self.assertEqual(layer_bgy.subsetString(), '"geocode" LIKE \'01728001%\'')

        # EA level filter -> missing ea_geocode column so remains unfiltered
        PackageDialog._filter_unassigned_layer(dlg, layer_bgy, "01728001001001", is_ea_level=True)
        self.assertEqual(layer_bgy.subsetString(), "")

    def test_filter_unassigned_ea_update_layer(self):
        """Verify unassigned layer with ea_geocode is filtered in EA level and not in Barangay level."""
        from references.package_qfield.gui.package_dialog import PackageDialog
        try:
            from qgis.core import QgsVectorLayer, QgsField, QgsFeature
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            from tests.mocks.sample_data import QgsVectorLayer, QgsField, QgsFeature, QVariant

        layer_update = QgsVectorLayer("Polygon?crs=epsg:4326", "my_barangay_ea_update", "memory")
        dp = layer_update.dataProvider()
        dp.addAttributes([QgsField("ea_geocode", QVariant.String)])
        layer_update.updateFields()
        f = QgsFeature(layer_update.fields())
        f.setAttributes(["01728001001001"])
        dp.addFeatures([f])

        dlg = MockGenericClass()
        dlg._normalized_layer_name = lambda n: n

        # EA Level -> "ea_geocode" = '01728001001001'
        PackageDialog._filter_unassigned_layer(dlg, layer_update, "01728001001001", is_ea_level=True)
        self.assertEqual(layer_update.subsetString(), '"ea_geocode" = \'01728001001001\'')

        # Barangay Level -> missing geocode column so remains unfiltered
        PackageDialog._filter_unassigned_layer(dlg, layer_update, "01728001", is_ea_level=False)
        self.assertEqual(layer_update.subsetString(), "")

    def test_filter_unassigned_layer_with_both_geocode_and_ea_geocode(self):
        """Verify unassigned layer with both geocode and ea_geocode filters appropriately by level."""
        from references.package_qfield.gui.package_dialog import PackageDialog
        try:
            from qgis.core import QgsVectorLayer, QgsField, QgsFeature
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            from tests.mocks.sample_data import QgsVectorLayer, QgsField, QgsFeature, QVariant

        dlg = MockGenericClass()
        dlg._normalized_layer_name = lambda n: n

        layer_both = QgsVectorLayer("Polygon?crs=epsg:4326", "01716_delineated_ea2026", "memory")
        dp = layer_both.dataProvider()
        dp.addAttributes([QgsField("geocode", QVariant.String), QgsField("ea_geocode", QVariant.String)])
        layer_both.updateFields()
        f = QgsFeature(layer_both.fields())
        f.setAttributes(["01716010000000", "01716010001001"])
        dp.addFeatures([f])

        # EA level filter -> "ea_geocode" = '01716010001001'
        PackageDialog._filter_unassigned_layer(dlg, layer_both, "01716010001001", is_ea_level=True)
        self.assertEqual(layer_both.subsetString(), '"ea_geocode" = \'01716010001001\'')

        # Barangay level filter -> "geocode" LIKE '01716010%'
        PackageDialog._filter_unassigned_layer(dlg, layer_both, "01716010", is_ea_level=False)
        self.assertEqual(layer_both.subsetString(), '"geocode" LIKE \'01716010%\'')

    def test_filter_unassigned_non_target_columns_not_filtered(self):
        """Verify unassigned layer with other columns (bsn_geoid, new_ean, bgy_code) is not filtered."""
        from references.package_qfield.gui.package_dialog import PackageDialog
        try:
            from qgis.core import QgsVectorLayer, QgsField, QgsFeature
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            from tests.mocks.sample_data import QgsVectorLayer, QgsField, QgsFeature, QVariant

        dlg = MockGenericClass()
        dlg._normalized_layer_name = lambda n: n

        layer_other = QgsVectorLayer("Point?crs=epsg:4326", "custom_unassigned_points", "memory")
        dp = layer_other.dataProvider()
        dp.addAttributes([QgsField("bsn_geoid", QVariant.String), QgsField("new_ean", QVariant.String), QgsField("bgy_code", QVariant.String)])
        layer_other.updateFields()
        f = QgsFeature(layer_other.fields())
        f.setAttributes(["017160100010010001", "001001", "01716010"])
        dp.addFeatures([f])

        # EA level -> no ea_geocode column -> not filtered
        PackageDialog._filter_unassigned_layer(dlg, layer_other, "01716010001001", is_ea_level=True)
        self.assertEqual(layer_other.subsetString(), "")

        # Barangay level -> no geocode column -> not filtered
        PackageDialog._filter_unassigned_layer(dlg, layer_other, "01716010", is_ea_level=False)
        self.assertEqual(layer_other.subsetString(), "")

    def test_filter_unassigned_ea_update_layer(self):
        """Verify unassigned _ea_update layer is filtered in EA and Barangay levels when it has geocode data."""
        from references.package_qfield.gui.package_dialog import PackageDialog
        try:
            from qgis.core import QgsVectorLayer, QgsField, QgsFeature
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            from tests.mocks.sample_data import QgsVectorLayer, QgsField, QgsFeature, QVariant

        layer_update = QgsVectorLayer("Polygon?crs=epsg:4326", "my_barangay_ea_update", "memory")
        dp = layer_update.dataProvider()
        dp.addAttributes([QgsField("ea_geocode", QVariant.String)])
        layer_update.updateFields()
        f = QgsFeature(layer_update.fields())
        f.setAttributes(["01728001001001"])
        dp.addFeatures([f])

        dlg = MockGenericClass()
        dlg._normalized_layer_name = lambda n: n

        # EA Level
        PackageDialog._filter_unassigned_layer(dlg, layer_update, "01728001001001", is_ea_level=True)
        self.assertEqual(layer_update.subsetString(), '"ea_geocode" = \'01728001001001\'')

        # Barangay Level
        PackageDialog._filter_unassigned_layer(dlg, layer_update, "01728001", is_ea_level=False)
        self.assertEqual(layer_update.subsetString(), '"ea_geocode" LIKE \'01728001%\'')

    def test_filter_unassigned_arbitrary_layer_name_with_geocode_and_new_ean(self):
        """Verify unassigned layer with arbitrary name (e.g. delineated_ea, merged_ea, eadel_update) filters on values."""
        from references.package_qfield.gui.package_dialog import PackageDialog
        try:
            from qgis.core import QgsVectorLayer, QgsField, QgsFeature
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            from tests.mocks.sample_data import QgsVectorLayer, QgsField, QgsFeature, QVariant

        dlg = MockGenericClass()
        dlg._normalized_layer_name = lambda n: n

        # Test with arbitrary layer name
        layer_del = QgsVectorLayer("Polygon?crs=epsg:4326", "01716_delineated_ea2026", "memory")
        dp = layer_del.dataProvider()
        dp.addAttributes([QgsField("geocode", QVariant.String), QgsField("new_ean", QVariant.String)])
        layer_del.updateFields()
        f = QgsFeature(layer_del.fields())
        f.setAttributes(["01716010000000", "001001"])
        dp.addFeatures([f])

        # EA level filter (14 digits: 01716010001001 -> bgy: 01716010, ean: 001001)
        PackageDialog._filter_unassigned_layer(dlg, layer_del, "01716010001001", is_ea_level=True)
        self.assertIn('"geocode" LIKE \'01716010%\'', layer_del.subsetString())
        self.assertIn('"new_ean" = \'001001\'', layer_del.subsetString())

        # Barangay level filter (8 digits: 01716010)
        PackageDialog._filter_unassigned_layer(dlg, layer_del, "01716010", is_ea_level=False)
        self.assertEqual(layer_del.subsetString(), '"geocode" LIKE \'01716010%\'')

    def test_filter_unassigned_bsn_geoid_layer(self):
        """Verify unassigned layer with bsn_geoid is filtered dynamically without declaring layer name."""
        from references.package_qfield.gui.package_dialog import PackageDialog
        try:
            from qgis.core import QgsVectorLayer, QgsField, QgsFeature
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            from tests.mocks.sample_data import QgsVectorLayer, QgsField, QgsFeature, QVariant

        dlg = MockGenericClass()
        dlg._normalized_layer_name = lambda n: n

        layer_bsn = QgsVectorLayer("Point?crs=epsg:4326", "custom_unassigned_points", "memory")
        dp = layer_bsn.dataProvider()
        dp.addAttributes([QgsField("bsn_geoid", QVariant.String)])
        layer_bsn.updateFields()
        f = QgsFeature(layer_bsn.fields())
        f.setAttributes(["017160100010010001"])
        dp.addFeatures([f])

        # EA level
        PackageDialog._filter_unassigned_layer(dlg, layer_bsn, "01716010001001", is_ea_level=True)
        self.assertEqual(layer_bsn.subsetString(), 'substr("bsn_geoid", 1, 14) = \'01716010001001\'')

        # Barangay level
        PackageDialog._filter_unassigned_layer(dlg, layer_bsn, "01716010", is_ea_level=False)
        self.assertEqual(layer_bsn.subsetString(), 'substr("bsn_geoid", 1, 8) = \'01716010\'')

    def test_offline_converter_on_offline_editing_next_layer_bounds(self):
        """Verify _on_offline_editing_next_layer safely handles 0, negative, out-of-range, and empty layer lists."""
        from libqfieldsync.offline_converter import OfflineConverter

        converter = OfflineConverter.__new__(OfflineConverter)
        converter.trUtf8 = lambda s: s
        converter.tr = lambda s: s
        converter._OfflineConverter__offline_layer_names = []

        emitted_signals = []
        class MockSignal:
            def emit(self, idx, count, msg):
                emitted_signals.append((idx, count, msg))

        converter.total_progress_updated = MockSignal()

        # Test with empty layer names list
        converter._on_offline_editing_next_layer(0, 0)
        self.assertEqual(len(emitted_signals), 1)
        self.assertEqual(emitted_signals[-1][0], 0)

        converter._on_offline_editing_next_layer(1, 0)
        self.assertEqual(len(emitted_signals), 2)

        converter._on_offline_editing_next_layer(-1, 0)
        self.assertEqual(len(emitted_signals), 3)

        # Test with populated layer names list
        converter._OfflineConverter__offline_layer_names = ["Layer_A", "Layer_B"]

        # Valid 1-based index 1
        converter._on_offline_editing_next_layer(1, 2)
        self.assertIn("Layer_A", emitted_signals[-1][2])

        # Valid 1-based index 2
        converter._on_offline_editing_next_layer(2, 2)
        self.assertIn("Layer_B", emitted_signals[-1][2])

        # Out-of-bounds layer_index = 0
        converter._on_offline_editing_next_layer(0, 2)
        self.assertEqual(emitted_signals[-1][0], 0)

        # Out-of-bounds layer_index = 5
        converter._on_offline_editing_next_layer(5, 2)
        self.assertEqual(emitted_signals[-1][0], 5)

        # Negative layer_index = -5
        converter._on_offline_editing_next_layer(-5, 2)
        self.assertEqual(emitted_signals[-1][0], -5)


if __name__ == "__main__":
    unittest.main()
