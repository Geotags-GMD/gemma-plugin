# -*- coding: utf-8 -*-
"""
Unit test module for gaps_overlaps_checker.py (gmd_scripts/gaps_overlaps_checker.py).
Tests MBI Checker / GapsOverlaps algorithm metadata and instantiation using sample polygon and point layers.
"""

import unittest
import importlib
from tests.mocks.qgis_mock import setup_qgis_mock_if_needed, QgsProcessingFeedback, QgsProcessingContext
from tests.mocks.sample_data import create_sample_polygon_layer, create_sample_point_layer

setup_qgis_mock_if_needed()


class TestGapsOverlapsChecker(unittest.TestCase):
    """Test suite for GapsOverlaps processing algorithm."""

    def setUp(self):
        self.mod = importlib.import_module("gmd_scripts.gaps_overlaps_checker")
        self.alg = self.mod.GapsOverlaps()
        self.sample_polygons = create_sample_polygon_layer("Barangay_Polygons", count=3)
        self.sample_points = create_sample_point_layer("Building_Points", count=5)

    def test_module_import(self):
        """Verify that the module imports successfully."""
        self.assertIsNotNone(self.mod, "Module gmd_scripts.gaps_overlaps_checker should import successfully.")

    def test_algorithm_metadata(self):
        """Test algorithm metadata methods."""
        self.assertIn(self.alg.name(), ["mbi_checker_for_GEOTAGS", "gaps_overlaps_checker"])
        self.assertEqual(self.alg.groupId(), "1map")
        self.assertEqual(self.alg.displayName(), "MBI Checker")
        self.assertIsNotNone(self.alg.createInstance())
        self.assertIsNotNone(self.alg.icon())

    def test_algorithm_parameters(self):
        """Test that algorithm parameters are properly registered in initAlgorithm."""
        self.alg.initAlgorithm()
        self.assertIsNotNone(self.alg.parameterDefinition(self.alg.INPUT1))
        self.assertIsNotNone(self.alg.parameterDefinition(self.alg.INPUT2))
        self.assertIsNotNone(self.alg.parameterDefinition(self.alg.REF_MBI_CASES))
        self.assertIsNotNone(self.alg.parameterDefinition(self.alg.RUN_MODE))


if __name__ == "__main__":
    unittest.main()
