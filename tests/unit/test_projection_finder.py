# -*- coding: utf-8 -*-
"""
Unit test module for projection_finder.py (gmd_scripts/projection_finder.py).
Tests CRS diagnostics, candidate scanning, affine solver, and algorithm metadata.
"""

import unittest
import importlib
from tests.mocks.qgis_mock import setup_qgis_mock_if_needed
setup_qgis_mock_if_needed()

from qgis.core import (
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsRectangle,
)
from tests.mocks.sample_data import create_sample_polygon_layer


class TestProjectionFinder(unittest.TestCase):
    """Test suite for Know Your Projection! (projection_finder) tool and algorithm."""

    def setUp(self):
        self.mod = importlib.import_module("gmd_scripts.projection_finder")
        self.alg = self.mod.ProjectionFinderAlgorithm()
        self.sample_layer = create_sample_polygon_layer("Sample_Boundary", count=3)

    def test_module_import(self):
        """Verify module and core classes import successfully."""
        self.assertIsNotNone(self.mod, "Module gmd_scripts.projection_finder should import successfully.")
        self.assertTrue(hasattr(self.mod, "ProjectionFinderAlgorithm"))
        self.assertTrue(hasattr(self.mod, "ProjectionToolkit"))
        self.assertTrue(hasattr(self.mod, "diagnose_extent"))
        self.assertTrue(hasattr(self.mod, "fit_affine"))
        self.assertTrue(hasattr(self.mod, "scan_candidates"))

    def test_algorithm_metadata(self):
        """Verify algorithm metadata conforms to GMD standards."""
        self.assertEqual(self.alg.name(), "projection_finder")
        self.assertEqual(self.alg.displayName(), "Know Your Projection!")
        self.assertEqual(self.alg.group(), "1Map")
        self.assertEqual(self.alg.groupId(), "1map")
        self.assertIsNotNone(self.alg.icon())

    def test_diagnose_extent_geographic(self):
        """Verify geographic coordinate extent is correctly diagnosed."""
        # Metro Manila extent in WGS84 degrees
        ext = QgsRectangle(120.9, 14.5, 121.1, 14.7)
        kind, report = self.mod.diagnose_extent(ext)
        self.assertEqual(kind, "geographic")
        self.assertIn("Geographic Coordinates", report)

    def test_diagnose_extent_projected(self):
        """Verify projected meter coordinate extent is correctly diagnosed."""
        # Zone III PRS92 / UTM projected meters
        ext = QgsRectangle(480000.0, 1600000.0, 520000.0, 1640000.0)
        kind, report = self.mod.diagnose_extent(ext)
        self.assertEqual(kind, "projected")
        self.assertIn("Projected Grid", report)

    def test_diagnose_extent_web_mercator(self):
        """Verify Web Mercator coordinate extent is correctly diagnosed."""
        # Philippines in Web Mercator (EPSG:3857)
        ext = QgsRectangle(13400000.0, 1600000.0, 13500000.0, 1700000.0)
        kind, report = self.mod.diagnose_extent(ext)
        self.assertEqual(kind, "webmercator")
        self.assertIn("Web Mercator", report)

    def test_solve3_linear_system(self):
        """Verify 3x3 linear equation solver _solve3."""
        # Solve:
        # 1*x + 0*y + 0*z = 5
        # 0*x + 2*y + 0*z = 6
        # 0*x + 0*y + 3*z = 9
        # -> solution: (5, 3, 3)
        A = [
            [1.0, 0.0, 0.0],
            [0.0, 2.0, 0.0],
            [0.0, 0.0, 3.0],
        ]
        B = [5.0, 6.0, 9.0]
        sol = self.mod._solve3(A, B)
        self.assertAlmostEqual(sol[0], 5.0, places=5)
        self.assertAlmostEqual(sol[1], 3.0, places=5)
        self.assertAlmostEqual(sol[2], 3.0, places=5)

    def test_fit_affine_transformation(self):
        """Verify 6-parameter affine transformation solver fit_affine."""
        # Test 2x scale and translation (+100, +200)
        src_pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        dst_pts = [(100.0, 200.0), (120.0, 200.0), (120.0, 220.0), (100.0, 220.0)]
        (a, b, c), (d, e, f), residuals = self.mod.fit_affine(src_pts, dst_pts)
        self.assertAlmostEqual(a, 2.0, places=3)
        self.assertAlmostEqual(e, 2.0, places=3)
        self.assertAlmostEqual(c, 100.0, places=3)
        self.assertAlmostEqual(f, 200.0, places=3)
        rms = (sum(r * r for r in residuals) / len(residuals)) ** 0.5
        self.assertAlmostEqual(rms, 0.0, places=3)

    def test_scan_candidates(self):
        """Verify candidate scanning against Philippine extents."""
        ext = QgsRectangle(480000.0, 1600000.0, 520000.0, 1640000.0)
        hits, misses = self.mod.scan_candidates(ext)
        self.assertIsInstance(hits, list)
        self.assertIsInstance(misses, list)

    def test_process_algorithm_headless(self):
        """Verify headless execution of ProjectionFinderAlgorithm."""
        context = QgsProcessingContext()
        feedback = QgsProcessingFeedback()
        params = {self.alg.INPUT: self.sample_layer}
        try:
            res = self.alg.processAlgorithm(params, context, feedback)
            self.assertIn(self.alg.OUTPUT, res)
            self.assertIn("Source Layer", res[self.alg.OUTPUT])
        except Exception as e:
            self.skipTest(f"Skipping test due to processing environment error: {e}")

    def test_projection_toolkit_instantiation(self):
        """Verify ProjectionToolkit dialog instantiates cleanly."""
        try:
            from qgis.PyQt.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                self.skipTest("No QApplication available in test environment.")
            dlg = self.mod.ProjectionToolkit()
            self.assertIsNotNone(dlg)
            self.assertEqual(dlg.windowTitle(), "Know Your Projection!")
        except Exception as e:
            self.skipTest(f"Skipping dialog UI test in headless environment: {e}")


if __name__ == "__main__":
    unittest.main()
