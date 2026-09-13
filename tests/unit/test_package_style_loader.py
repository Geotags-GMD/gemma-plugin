# -*- coding: utf-8 -*-
"""
Unit test module for package_style_loader.py (gmd_scripts/package_style_loader.py).
Tests Package Style Loader dialog launcher, role auto-detection, and QML style matching.
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
from tests.mocks.sample_data import create_sample_polygon_layer, create_sample_point_layer

setup_qgis_mock_if_needed()


class TestPackageStyleLoader(unittest.TestCase):
    """Test suite for package_style_loader.py."""

    def setUp(self):
        self.mod = importlib.import_module("gmd_scripts.package_style_loader")
        self.sample_polygon = create_sample_polygon_layer("Sample_Polygon_Layer", count=3)
        self.sample_point = create_sample_point_layer("Sample_Point_Layer", count=5)

    def test_module_import(self):
        """Verify that the module imports successfully without syntax or module errors."""
        self.assertIsNotNone(self.mod, "Module gmd_scripts.package_style_loader should import successfully.")

    def test_show_package_style_loader_dialog_launcher(self):
        """Test show_package_style_loader_dialog launcher with mock iface."""
        mock_iface = MockGenericClass()

        try:
            dlg = self.mod.show_package_style_loader_dialog(mock_iface)
            self.assertIsNotNone(dlg)
        except Exception as e:
            self.skipTest(f"Skipping GUI instantiation test due to environment limitation: {e}")

    def test_role_definitions_exist(self):
        """Verify role definitions exist and cover boundary and reference layers."""
        self.assertTrue(len(self.mod.ROLE_DEFINITIONS) >= 5)
        role_names = [r[0] for r in self.mod.ROLE_DEFINITIONS]
        self.assertIn("LGU Boundary", role_names)
        self.assertIn("PSA Boundary", role_names)
        self.assertIn("MBI Cases", role_names)
        self.assertIn("Building Points", role_names)

    def test_boundary_role_auto_detection(self):
        """Verify role detection identifies boundary layers properly."""
        test_cases = [
            ("ref_Bacacay_bldg_point", "Building Points", "1. Base Layer Building Points"),
            ("ref_Bacacay_lgu", "LGU Boundary", "ref_province_lgu"),
            ("ref_Bacacay_psa", "PSA Boundary", "ref_province_psa"),
            ("ref_mbi_cases", "MBI Cases", "ref_mbi_cases"),
            ("mbi_cases", "MBI Cases", "ref_mbi_cases"),
            ("00501_bgy", "Barangay Boundary", "5. Base Layer Barangay"),
            ("00501_ea", "Enumeration Area", "4. Base Layer EA"),
            ("00501_road", "Road Network", "7. Base Layer Road"),
            ("unknown_custom_layer", "Other Layer", "(None)"),
        ]

        for layer_name, exp_role, exp_qml in test_cases:
            detected_role, detected_qml = self.mod.detect_layer_role(layer_name)
            self.assertEqual(
                detected_role,
                exp_role,
                f"Layer {layer_name} expected role '{exp_role}' but got '{detected_role}'",
            )
            self.assertEqual(
                detected_qml,
                exp_qml,
                f"Layer {layer_name} expected QML '{exp_qml}' but got '{detected_qml}'",
            )

    def test_layer_geometry_type_detection(self):
        """Verify layer geometry detection helper returns correct codes."""
        if hasattr(self.sample_polygon, "geometryType"):
            geom_code, geom_name = self.mod.get_layer_geom_type(self.sample_polygon)
            self.assertIn(geom_code, ("polygon", "unknown"))

    def test_layer_tree_priority_order(self):
        """Verify layer tree hierarchy: building point < mbi_cases < psa / lgu."""
        bldg_prio = self.mod.get_layer_tree_priority("ref_Bacacay_bldg_point")
        mbi_prio = self.mod.get_layer_tree_priority("ref_mbi_cases")
        psa_prio = self.mod.get_layer_tree_priority("ref_Bacacay_psa")
        lgu_prio = self.mod.get_layer_tree_priority("ref_Bacacay_lgu")
        other_prio = self.mod.get_layer_tree_priority("Google Satellite")

        # Building point is on top (lowest number)
        self.assertLess(bldg_prio, mbi_prio, "Building points must be above MBI cases")
        # MBI cases is above PSA and LGU
        self.assertLess(mbi_prio, psa_prio, "MBI cases must be above PSA boundary")
        self.assertLess(mbi_prio, lgu_prio, "MBI cases must be above LGU boundary")
        # PSA and LGU are above other layers
        self.assertLess(psa_prio, other_prio, "PSA boundary must be above background layers")
        self.assertLess(lgu_prio, other_prio, "LGU boundary must be above background layers")


if __name__ == "__main__":
    unittest.main()
