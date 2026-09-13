# -*- coding: utf-8 -*-
"""
Unit test module for psa_lgu_map_comparison.py (gmd_scripts/psa_lgu_map_comparison.py).
Tests module import, the pure geocode-matching helper functions, and
PsaLguComparisonAlgorithm processing-algorithm metadata.
"""

import unittest
import importlib
from tests.mocks.qgis_mock import setup_qgis_mock_if_needed

setup_qgis_mock_if_needed()


class TestPsaLguMapComparison(unittest.TestCase):
    """Test suite for psa_lgu_map_comparison module."""

    def setUp(self):
        self.mod = importlib.import_module("gmd_scripts.psa_lgu_map_comparison")
        self.alg = self.mod.PsaLguComparisonAlgorithm()

    def test_module_import(self):
        """Verify module imports successfully."""
        self.assertIsNotNone(self.mod, "Module gmd_scripts.psa_lgu_map_comparison should import successfully.")

    def test_algorithm_metadata(self):
        """Test algorithm metadata methods."""
        self.assertEqual(self.alg.name(), "psalgu_boundary_comparison")
        self.assertEqual(self.alg.groupId(), "1map")
        self.assertIsNotNone(self.alg.displayName())
        self.assertIsNotNone(self.alg.createInstance())

    def test_first8_truncates_and_handles_none(self):
        """first8 should truncate to 8 characters and treat None as empty."""
        self.assertEqual(self.mod.first8("012345678900"), "01234567")
        self.assertEqual(self.mod.first8("0123"), "0123")
        self.assertEqual(self.mod.first8(None), "")

    def test_guess_geocode_field_exact_and_substring(self):
        """guess_geocode_field should prefer an exact 'Geocode' match, then fall back to substring."""
        self.assertEqual(self.mod.guess_geocode_field(["Barangay", "Geocode"]), "Geocode")
        self.assertEqual(self.mod.guess_geocode_field(["Barangay", "Geocode_10"]), "Geocode_10")
        self.assertIsNone(self.mod.guess_geocode_field(["Barangay", "PSGC"]))

    def test_extract_code_from_layer_name(self):
        """extract_code should pull the pppmm-style prefix off PSA/LGU layer names."""
        self.assertEqual(self.mod.extract_code("000102_LGU"), "000102")
        self.assertEqual(self.mod.extract_code("00102_PSA_Boundary"), "00102")
        self.assertEqual(self.mod.extract_code("12345_no_suffix"), "12345")
        self.assertEqual(self.mod.extract_code(""), "")

    def test_unique_field_name_no_collision_keeps_base_name(self):
        """When the base name isn't taken, it's returned unchanged."""
        fields = self.mod.QgsFields()
        fields.append(self.mod.QgsField("BSN", self.mod.QVariant.String))
        self.assertEqual(self.mod._unique_field_name("geocode", fields), "geocode")

    def test_unique_field_name_avoids_exact_case_collision(self):
        """The regression this fixes: QgsFields.append() silently no-ops on
        an exact-name duplicate, and the value meant for it is then lost --
        this is what made a building's displayed 'geocode' column show its
        own untouched source value instead of the barangay it matched."""
        fields = self.mod.QgsFields()
        fields.append(self.mod.QgsField("geocode", self.mod.QVariant.String))
        self.assertEqual(self.mod._unique_field_name("geocode", fields), "geocode_2")

    def test_unique_field_name_is_case_insensitive(self):
        """Treated case-insensitively to match how GeoPackage and most
        providers treat column names, even though the in-memory provider
        used for this module's own outputs happens to allow same-name
        fields that differ only in case."""
        fields = self.mod.QgsFields()
        fields.append(self.mod.QgsField("Geocode", self.mod.QVariant.String))
        self.assertEqual(self.mod._unique_field_name("geocode", fields), "geocode_2")

    def test_unique_field_name_skips_every_taken_suffix(self):
        """geocode and geocode_2 both taken -> geocode_3."""
        fields = self.mod.QgsFields()
        fields.append(self.mod.QgsField("geocode", self.mod.QVariant.String))
        fields.append(self.mod.QgsField("geocode_2", self.mod.QVariant.String))
        self.assertEqual(self.mod._unique_field_name("geocode", fields), "geocode_3")


class TestFindDefaultLayerId(unittest.TestCase):
    """Test suite for the dialog pre-fill helper find_default_layer_id."""

    def setUp(self):
        self.mod = importlib.import_module("gmd_scripts.psa_lgu_map_comparison")
        self.project = self.mod.QgsProject.instance()
        self.project.removeAllMapLayers()

    def tearDown(self):
        self.project.removeAllMapLayers()

    def add_polygon_layer(self, name):
        layer = self.mod.QgsVectorLayer("Polygon?crs=EPSG:4326", name, "memory")
        self.project.addMapLayer(layer)
        return layer

    def find(self, hints, exclude_ids=()):
        return self.mod.find_default_layer_id(
            hints, self.mod.QgsWkbTypes.PolygonGeometry, exclude_ids=exclude_ids)

    def test_picks_psa_and_lgu_layers_by_name(self):
        """The PSA hints should find the PSA layer and the LGU hints the LGU one."""
        psa = self.add_polygon_layer("000102_PSA")
        lgu = self.add_polygon_layer("000102_LGU")
        self.assertEqual(self.find(self.mod.PSA_LAYER_HINTS), psa.id())
        self.assertEqual(self.find(self.mod.LGU_LAYER_HINTS), lgu.id())

    def test_returns_none_when_no_layer_matches(self):
        """A project with no PSA-like layer should pre-fill nothing."""
        self.add_polygon_layer("Barangay Boundary")
        self.assertIsNone(self.find(self.mod.PSA_LAYER_HINTS))

    def test_skips_this_algorithms_own_output_layers(self):
        """Outputs of a previous run must not be offered as inputs on a re-run."""
        self.add_polygon_layer("000102_PSA_Matched")
        self.add_polygon_layer("000102_PSA_Unmatched")
        self.assertIsNone(self.find(self.mod.PSA_LAYER_HINTS))
        source = self.add_polygon_layer("000102_PSA")
        self.assertEqual(self.find(self.mod.PSA_LAYER_HINTS), source.id())

    def test_exclude_ids_keeps_psa_pick_out_of_the_lgu_running(self):
        """A layer already chosen for PSA is not reused for LGU."""
        both = self.add_polygon_layer("000102_PSA_LGU_draft")
        self.assertEqual(self.find(self.mod.PSA_LAYER_HINTS), both.id())
        self.assertIsNone(self.find(self.mod.LGU_LAYER_HINTS, exclude_ids=(both.id(),)))


class TestLguBoundaryLocator(unittest.TestCase):
    """Test suite for _LguBoundaryLocator, the point-in-polygon lookup that
    decides whether a building point is inside the barangay its geocode
    names, and which barangay it does sit in when it is not.

    The two polygons are kept apart (0-10 and 20-30 on x) so no test point
    can ever be a candidate for both -- that keeps the expected answer the
    same whether the containment test is GEOS, Shapely or the bounding-box
    fallback in the mock."""

    def setUp(self):
        self.mod = importlib.import_module("gmd_scripts.psa_lgu_map_comparison")
        from qgis.core import QgsPointXY
        self.QgsPointXY = QgsPointXY

    def square(self, x0, y0, x1, y1):
        pts = [
            self.QgsPointXY(x0, y0), self.QgsPointXY(x1, y0),
            self.QgsPointXY(x1, y1), self.QgsPointXY(x0, y1),
            self.QgsPointXY(x0, y0),
        ]
        return self.mod.QgsGeometry.fromPolygonXY([pts])

    def polygon_feature(self, fid, geometry):
        feat = self.mod.QgsFeature()
        feat.setId(fid)
        feat.setGeometry(geometry)
        return feat

    def point(self, x, y):
        return self.mod.QgsGeometry.fromPointXY(self.QgsPointXY(x, y))

    def locator(self):
        """Two barangays: 'A' covering x 0-10, 'B' covering x 20-30."""
        locator = self.mod._LguBoundaryLocator()
        locator.add(self.polygon_feature(1, self.square(0, 0, 10, 10)), "00010201")
        locator.add(self.polygon_feature(2, self.square(20, 0, 30, 10)), "00010202")
        return locator

    def test_point_inside_the_barangay_its_geocode_names(self):
        """The everyday case: the point is where its geocode says it is."""
        self.assertTrue(self.locator().contains("00010201", self.point(5, 5)))
        self.assertTrue(self.locator().contains("00010202", self.point(25, 5)))

    def test_point_inside_a_different_barangay_is_not_contained(self):
        """The regression this fixes. A point carrying barangay A's geocode
        but sitting in barangay B is outside -- being somewhere within the
        municipality is not enough, or nothing would ever be reported."""
        locator = self.locator()
        self.assertFalse(locator.contains("00010201", self.point(25, 5)))
        # ...and the Outside layer records where it actually is.
        self.assertEqual(locator.code_for(self.point(25, 5)), "00010202")

    def test_point_outside_the_municipality_is_not_contained(self):
        """A point in no barangay at all is outside, with nothing to record
        in in_geocode."""
        locator = self.locator()
        self.assertFalse(locator.contains("00010201", self.point(50, 50)))
        self.assertIsNone(locator.code_for(self.point(50, 50)))

    def test_blank_geocode_is_never_contained(self):
        """With no geocode there is no barangay to check against, so the
        point can't be confirmed inside wherever it sits."""
        locator = self.locator()
        self.assertFalse(locator.contains("", self.point(5, 5)))
        self.assertFalse(locator.contains(None, self.point(5, 5)))

    def test_unknown_geocode_is_never_contained(self):
        """A geocode naming no LGU barangay matches no polygon."""
        self.assertFalse(self.locator().contains("99999999", self.point(5, 5)))

    def test_multipart_barangay_counts_any_of_its_parts(self):
        """An island barangay is several polygons under one geocode, and
        landing in any one of them is inside."""
        locator = self.mod._LguBoundaryLocator()
        locator.add(self.polygon_feature(1, self.square(0, 0, 10, 10)), "00010201")
        locator.add(self.polygon_feature(2, self.square(20, 0, 30, 10)), "00010201")
        self.assertTrue(locator.contains("00010201", self.point(5, 5)))
        self.assertTrue(locator.contains("00010201", self.point(25, 5)))

    def test_point_inside_a_polygon_returns_its_geocode(self):
        """A point well inside a barangay is placed in that barangay."""
        self.assertEqual(self.locator().code_for(self.point(5, 5)), "00010201")
        self.assertEqual(self.locator().code_for(self.point(25, 5)), "00010202")

    def test_point_outside_every_polygon_returns_none(self):
        """The regression this fixes: a point outside the boundary must not
        be reported as inside, whatever its geocode column says."""
        self.assertIsNone(self.locator().code_for(self.point(50, 50)))
        self.assertIsNone(self.locator().code_for(self.point(15, 5)))

    def test_point_on_a_boundary_line_stays_inside(self):
        """A point digitised onto the edge is properly contained by no
        polygon, and counts as inside the barangay it touches rather than
        being reported as outside it."""
        self.assertTrue(self.locator().contains("00010201", self.point(10, 5)))
        self.assertEqual(self.locator().code_for(self.point(10, 5)), "00010201")

    def test_missing_geometry_returns_none(self):
        """A building with no geometry can't be placed -- it goes Outside."""
        self.assertIsNone(self.locator().code_for(None))
        self.assertFalse(self.locator().contains("00010201", None))

    def test_empty_locator_reports_itself_empty(self):
        """An LGU layer with no usable geometry places nothing at all."""
        empty = self.mod._LguBoundaryLocator()
        self.assertTrue(empty.is_empty())
        self.assertIsNone(empty.code_for(self.point(5, 5)))
        self.assertFalse(empty.contains("00010201", self.point(5, 5)))
        self.assertFalse(self.locator().is_empty())

    def test_polygon_without_geometry_is_not_indexed(self):
        """An LGU feature carrying no geometry is skipped, not indexed."""
        locator = self.mod._LguBoundaryLocator()
        locator.add(self.polygon_feature(1, self.mod.QgsGeometry()), "00010201")
        self.assertTrue(locator.is_empty())


if __name__ == "__main__":
    unittest.main()
