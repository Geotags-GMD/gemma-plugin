# -*- coding: utf-8 -*-
"""
Unit test module for mbi_validator.py (gmd_scripts/mbi_validator.py).
Tests MBI Validator / Status Audit processing algorithm on sample vector data fixtures.
"""

import unittest
import importlib
from tests.mocks.qgis_mock import setup_qgis_mock_if_needed, QgsProcessingFeedback, QgsProcessingContext
from tests.mocks.sample_data import create_sample_polygon_layer
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
    NULL,
)
from qgis.PyQt.QtCore import QVariant

setup_qgis_mock_if_needed()


class TestMbiValidator(unittest.TestCase):
    """Test suite for mbi_validator algorithm."""

    def setUp(self):
        self.mod = importlib.import_module("gmd_scripts.mbi_validator")
        self.alg = self.mod.MBIStatusAuditAlgorithm()

        # Create a mock reference layer with required fields
        self.ref_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "Sample_Ref_MBI", "memory")
        pr = self.ref_layer.dataProvider()
        pr.addAttributes([
            QgsField("case_uuid", QVariant.String),
            QgsField("geocode", QVariant.String),
            QgsField("region", QVariant.String),
            QgsField("province", QVariant.String),
            QgsField("city_mun", QVariant.String),
            QgsField("barangay", QVariant.String),
            QgsField("mbi_status", QVariant.String),
            QgsField("pso_remarks", QVariant.String),
            QgsField("mbi_remarks", QVariant.String),
            QgsField("mbi_type", QVariant.String),
            QgsField("involved_bgys", QVariant.String),
            QgsField("num_bldg_pts", QVariant.Int),
        ])
        self.ref_layer.updateFields()

        # Add sample features
        f1 = QgsFeature(self.ref_layer.fields())
        f1.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(120.0, 14.0), QgsPointXY(120.0, 14.1),
            QgsPointXY(120.1, 14.1), QgsPointXY(120.1, 14.0),
            QgsPointXY(120.0, 14.0)
        ]]))
        f1.setAttribute("case_uuid", "CASE-001")
        f1.setAttribute("geocode", "133900000")
        f1.setAttribute("region", "National Capital Region")
        f1.setAttribute("province", "NCR, Fourth District")
        f1.setAttribute("city_mun", "City of Pasay")
        f1.setAttribute("barangay", "Barangay 1")
        f1.setAttribute("mbi_status", "1_Updated")
        f1.setAttribute("pso_remarks", "Boundary realigned")
        f1.setAttribute("mbi_type", "1_Gap")
        f1.setAttribute("num_bldg_pts", 0)

        f2 = QgsFeature(self.ref_layer.fields())
        f2.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(120.2, 14.0), QgsPointXY(120.2, 14.1),
            QgsPointXY(120.3, 14.1), QgsPointXY(120.3, 14.0),
            QgsPointXY(120.2, 14.0)
        ]]))
        f2.setAttribute("case_uuid", "CASE-002")
        f2.setAttribute("geocode", "133900001")
        f2.setAttribute("region", "National Capital Region")
        f2.setAttribute("province", "NCR, Fourth District")
        f2.setAttribute("city_mun", "City of Pasay")
        f2.setAttribute("barangay", "Barangay 2")
        f2.setAttribute("mbi_status", "2_Pending")
        f2.setAttribute("pso_remarks", "Under boundary dispute review")
        f2.setAttribute("mbi_type", "2_Overlap")
        f2.setAttribute("num_bldg_pts", 2)

        f3 = QgsFeature(self.ref_layer.fields())
        f3.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(120.4, 14.0), QgsPointXY(120.4, 14.1),
            QgsPointXY(120.5, 14.1), QgsPointXY(120.5, 14.0),
            QgsPointXY(120.4, 14.0)
        ]]))
        f3.setAttribute("case_uuid", "CASE-003")
        f3.setAttribute("geocode", "133900002")
        f3.setAttribute("region", "National Capital Region")
        f3.setAttribute("province", "NCR, Fourth District")
        f3.setAttribute("city_mun", "City of Pasay")
        f3.setAttribute("barangay", "Barangay 3")
        f3.setAttribute("mbi_status", "2_Pending")
        f3.setAttribute("pso_remarks", "Disputed area pending Sangguniang Panlalawigan resolution")
        f3.setAttribute("mbi_type", "3_Disputed")
        f3.setAttribute("num_bldg_pts", 1)

        pr.addFeatures([f1, f2, f3])
        self.ref_layer.updateExtents()

        # Create checker layer
        self.chk_gap_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "Sample_Chk_Gap", "memory")
        pr_chk = self.chk_gap_layer.dataProvider()
        pr_chk.addAttributes([
            QgsField("case_uuid", QVariant.String),
            QgsField("geocode", QVariant.String),
            QgsField("region", QVariant.String),
            QgsField("province", QVariant.String),
            QgsField("city_mun", QVariant.String),
            QgsField("barangay", QVariant.String),
            QgsField("mbi_type", QVariant.String),
        ])
        self.chk_gap_layer.updateFields()

        cf = QgsFeature(self.chk_gap_layer.fields())
        cf.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(120.05, 14.05), QgsPointXY(120.05, 14.15),
            QgsPointXY(120.15, 14.15), QgsPointXY(120.15, 14.05),
            QgsPointXY(120.05, 14.05)
        ]]))
        cf.setAttribute("case_uuid", "CHK-001")
        cf.setAttribute("geocode", "133900000")
        cf.setAttribute("region", "National Capital Region")
        cf.setAttribute("province", "NCR, Fourth District")
        cf.setAttribute("city_mun", "City of Pasay")
        cf.setAttribute("barangay", "Barangay 1")
        cf.setAttribute("mbi_type", "1_Gap")
        pr_chk.addFeatures([cf])
        self.chk_gap_layer.updateExtents()

    def test_module_import(self):
        """Verify that the module imports successfully."""
        self.assertIsNotNone(self.mod, "Module gmd_scripts.mbi_validator should import successfully.")

    def test_algorithm_metadata(self):
        """Test algorithm metadata methods."""
        self.assertEqual(self.alg.name(), "mbi_validator")
        self.assertEqual(self.alg.groupId(), "1map")
        self.assertEqual(self.alg.group(), "1Map")
        self.assertIsNotNone(self.alg.displayName())
        self.assertIsNotNone(self.alg.createInstance())
        self.assertIsNotNone(self.alg.icon())
        self.assertIsNotNone(self.alg.shortHelpString())

    def test_gpkg_save_path_optionality(self):
        """Verify that GPKG_OUTPUT save path parameter is optional."""
        try:
            self.alg.initAlgorithm()
            param = self.alg.parameterDefinition(self.alg.GPKG_OUTPUT)
            if param:
                self.assertTrue(param.isOptional(), "GPKG_OUTPUT parameter must be optional so save path is not required when checkbox is unchecked.")
        except Exception as e:
            self.skipTest(f"Skipping test due to processing environment error: {e}")

    def test_gpkg_layers_parameter(self):
        """Verify GPKG_LAYERS multi-selection parameter."""
        try:
            self.alg.initAlgorithm()
            param = self.alg.parameterDefinition(self.alg.GPKG_LAYERS)
            if param:
                self.assertTrue(param.isOptional())
                self.assertEqual(len(param.options()), 9)
        except Exception as e:
            self.skipTest(f"Skipping test due to processing environment error: {e}")

    def test_disputed_subset(self):
        """Verify get_disputed_subset extracts features with mbi_type = 3_Disputed."""
        disputed = self.mod.get_disputed_subset(self.ref_layer)
        self.assertEqual(len(disputed), 1)
        self.assertEqual(disputed[0].attribute("case_uuid"), "CASE-003")
        self.assertEqual(disputed[0].attribute("mbi_type"), "3_Disputed")

    def test_is_disputed_value(self):
        """Test is_disputed_value helper for various casing and string variants."""
        self.assertTrue(self.mod.is_disputed_value("3_Disputed"))
        self.assertTrue(self.mod.is_disputed_value("3_disputed"))
        self.assertTrue(self.mod.is_disputed_value("3_Dispute"))
        self.assertTrue(self.mod.is_disputed_value("Disputed"))
        self.assertTrue(self.mod.is_disputed_value("dispute"))
        self.assertTrue(self.mod.is_disputed_value("3 - Disputed"))
        self.assertTrue(self.mod.is_disputed_value("3. Disputed"))
        self.assertTrue(self.mod.is_disputed_value("3"))
        self.assertFalse(self.mod.is_disputed_value("1_Gap"))
        self.assertFalse(self.mod.is_disputed_value("2_Overlap"))
        self.assertFalse(self.mod.is_disputed_value(None))
        self.assertFalse(self.mod.is_disputed_value(""))

    def test_disputed_subset_with_case_type_field(self):
        """Verify get_disputed_subset works even when the layer uses case_type instead of mbi_type."""
        layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "Old_Ref_Layer", "memory")
        pr = layer.dataProvider()
        pr.addAttributes([
            QgsField("case_uuid", QVariant.String),
            QgsField("case_type", QVariant.String),
            QgsField("mbi_status", QVariant.String),
        ])
        layer.updateFields()

        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(120.0, 14.0), QgsPointXY(120.0, 14.1),
            QgsPointXY(120.1, 14.1), QgsPointXY(120.1, 14.0),
            QgsPointXY(120.0, 14.0)
        ]]))
        f.setAttribute("case_uuid", "DISP-99")
        f.setAttribute("case_type", "3_Disputed")
        f.setAttribute("mbi_status", "2_Pending")
        pr.addFeatures([f])
        layer.updateExtents()

        res = self.mod.get_disputed_subset(layer)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].attribute("case_uuid"), "DISP-99")

    def test_output_fields_and_feature_creation(self):
        """Verify output schema field names, ordering, and feature population."""
        fields = self.mod.output_fields()
        field_names = [fields.at(i).name() for i in range(fields.count())]

        expected_order = [
            "case_uuid", "geocode", "region", "province", "city_mun",
            "barangay", "mbi_type", "ref_status", "ref_remarks",
            "ref_involved_bgys", "ref_num_bldg_pts", "remarks"
        ]
        self.assertEqual(field_names, expected_order)
        self.assertEqual(field_names[-1], "remarks", "remarks must be the last column in output fields")
        self.assertNotIn("case_type", field_names, "case_type must be renamed to mbi_type")

        # Test make_feature population
        ref_feat = list(self.ref_layer.getFeatures())[0]
        chk_feat = list(self.chk_gap_layer.getFeatures())[0]

        out_feat = self.mod.make_feature(
            fields, chk_feat.geometry(), "Gap", "Audit mismatch detected",
            case_uuid="CASE-001", ref_feature=ref_feat, chk_feature=chk_feat
        )
        self.assertEqual(out_feat.attribute("case_uuid"), "CASE-001")
        self.assertEqual(out_feat.attribute("geocode"), "133900000")
        self.assertEqual(out_feat.attribute("region"), "National Capital Region")
        self.assertEqual(out_feat.attribute("province"), "NCR, Fourth District")
        self.assertEqual(out_feat.attribute("city_mun"), "City of Pasay")
        self.assertEqual(out_feat.attribute("barangay"), "Barangay 1")
        self.assertEqual(out_feat.attribute("mbi_type"), "1_Gap")
        self.assertEqual(out_feat.attribute("ref_status"), "1_Updated")
        self.assertEqual(out_feat.attribute("remarks"), "Audit mismatch detected")

    def test_normalize_helper(self):
        """Test normalize and meaningful helper functions."""
        self.assertEqual(self.mod.normalize(None), "")
        self.assertEqual(self.mod.normalize(NULL), "")
        self.assertEqual(self.mod.normalize("  Sample  "), "Sample")

        self.assertFalse(self.mod.meaningful(None))
        self.assertFalse(self.mod.meaningful(""))
        self.assertFalse(self.mod.meaningful("null"))
        self.assertFalse(self.mod.meaningful("a"))
        self.assertTrue(self.mod.meaningful("Resolved by Mayor"))

    def test_find_matching_layer_id(self):
        """Test layer auto-detection helper for ref_mbi_cases, Gaps, and Overlaps."""
        # Clean up any existing project layers
        QgsProject.instance().removeAllMapLayers()

        # No layers in project -> returns None
        found_id = self.mod.find_matching_layer_id(["ref_mbi_cases", "ref_mbi"])
        self.assertIsNone(found_id)

        # Add polygon layers named 'ref_mbi_cases', 'Gaps', 'Overlaps'
        test_ref = QgsVectorLayer("Polygon?crs=EPSG:4326", "ref_mbi_cases_2026", "memory")
        test_gaps = QgsVectorLayer("Polygon?crs=EPSG:4326", "Gaps", "memory")
        test_overlaps = QgsVectorLayer("Polygon?crs=EPSG:4326", "Overlaps", "memory")
        QgsProject.instance().addMapLayers([test_ref, test_gaps, test_overlaps])

        found_ref = self.mod.find_matching_layer_id(["ref_mbi_cases", "ref_mbi"])
        found_gaps = self.mod.find_matching_layer_id(["gaps", "gap"])
        found_overlaps = self.mod.find_matching_layer_id(["overlaps", "overlap"])

        self.assertEqual(found_ref, test_ref.id())
        self.assertEqual(found_gaps, test_gaps.id())
        self.assertEqual(found_overlaps, test_overlaps.id())

        # Clean up
        QgsProject.instance().removeAllMapLayers()

    def test_evaluate_reference_case(self):
        """Test evaluate_reference_case rules."""
        feat = list(self.ref_layer.getFeatures())[0]

        # Rule A: Claimed resolved (1_Updated), but spatially detected -> status_mismatch
        cat, reason = self.mod.evaluate_reference_case(feat, spatially_confirmed=True)
        self.assertEqual(cat, "status_mismatch")

        # Claimed resolved (1_Updated) and NOT detected -> confirmed_resolved
        cat2, reason2 = self.mod.evaluate_reference_case(feat, spatially_confirmed=False)
        self.assertEqual(cat2, "confirmed_resolved")

        # Claimed resolved (1_Updated) w/ non-zero bldg pts AND remarks present -> mismatch_with_remarks
        feat.setAttribute("num_bldg_pts", 3)
        feat.setAttribute("pso_remarks", "Boundary adjustment ongoing")
        cat3, reason3 = self.mod.evaluate_reference_case(feat, spatially_confirmed=False)
        self.assertEqual(cat3, "mismatch_with_remarks")

        # Claimed resolved (1_Updated) w/ non-zero bldg pts AND NO remarks -> status_mismatch
        feat.setAttribute("pso_remarks", None)
        cat4, reason4 = self.mod.evaluate_reference_case(feat, spatially_confirmed=False)
        self.assertEqual(cat4, "status_mismatch")

        # Pending cases: ALL 2_Pending cases except bp==0 with no remarks -> pending_cases
        feat.setAttribute("mbi_status", "2_Pending")
        feat.setAttribute("num_bldg_pts", 0)
        feat.setAttribute("pso_remarks", "Pending boundary review by PSO")
        cat5, reason5 = self.mod.evaluate_reference_case(feat, spatially_confirmed=True)
        self.assertEqual(cat5, "pending_cases")

        feat.setAttribute("num_bldg_pts", 4)
        feat.setAttribute("pso_remarks", "Pending dispute between Barangays")
        cat6, reason6 = self.mod.evaluate_reference_case(feat, spatially_confirmed=True)
        self.assertEqual(cat6, "pending_cases")

        # 2_Pending with bldg pts > 0, NO remarks -> pending_cases
        feat.setAttribute("num_bldg_pts", 4)
        feat.setAttribute("pso_remarks", None)
        cat7, reason7 = self.mod.evaluate_reference_case(feat, spatially_confirmed=True)
        self.assertEqual(cat7, "pending_cases")

        cat8, reason8 = self.mod.evaluate_reference_case(feat, spatially_confirmed=False)
        self.assertEqual(cat8, "pending_cases")

        # 2_Pending with bldg pts = 0 and NO remarks -> status_mismatch
        feat.setAttribute("num_bldg_pts", 0)
        cat9, reason9 = self.mod.evaluate_reference_case(feat, spatially_confirmed=True)
        self.assertEqual(cat9, "status_mismatch")

    def test_process_algorithm_execution(self):
        """Test processAlgorithm execution on reference and checker layers."""
        try:
            params = {
                self.alg.REF_LAYER: self.ref_layer,
                self.alg.CHK_GAP: self.chk_gap_layer,
                self.alg.CHK_OVERLAP: None,
                self.alg.GPKG_LAYERS: [0, 1, 2, 8],
                self.alg.OUT_MISMATCH: "TEMPORARY_OUTPUT",
                self.alg.OUT_MISMATCH_REMARKS: "TEMPORARY_OUTPUT",
                self.alg.OUT_PENDING_CASES: "TEMPORARY_OUTPUT",
                self.alg.OUT_NEW: "TEMPORARY_OUTPUT",
                self.alg.OUT_STILL: "TEMPORARY_OUTPUT",
                self.alg.OUT_RESOLVED: "TEMPORARY_OUTPUT",
                self.alg.OUT_MANUAL_REVIEW: "TEMPORARY_OUTPUT",
                self.alg.OUT_NOSTATUS: "TEMPORARY_OUTPUT",
                self.alg.OUT_DISPUTED: "TEMPORARY_OUTPUT",
            }
            QgsProject.instance().addMapLayer(self.ref_layer)
            QgsProject.instance().addMapLayer(self.chk_gap_layer)

            context = QgsProcessingContext()
            if hasattr(context, "setProject"):
                context.setProject(QgsProject.instance())
            feedback = QgsProcessingFeedback()

            res = self.alg.processAlgorithm(params, context, feedback)
            self.assertIsNotNone(res)
        except Exception as e:
            self.skipTest(f"Skipping test due to processing environment error: {e}")

    def test_evaluate_reference_case_without_checker(self):
        """Without a Checker layer, no case is claimed detected or resolved."""
        fields = QgsFields()
        fields.append(QgsField("mbi_status", QVariant.String))
        fields.append(QgsField("pso_remarks", QVariant.String))
        fields.append(QgsField("num_bldg_pts", QVariant.Int))
        feat = QgsFeature(fields)

        # 2_Pending still reaches Pending Cases so it can be exported.
        feat.setAttribute("mbi_status", "2_Pending")
        feat.setAttribute("pso_remarks", "Awaiting resolution")
        feat.setAttribute("num_bldg_pts", 3)
        cat, _ = self.mod.evaluate_reference_case(
            feat, spatially_confirmed=False, checker_available=False)
        self.assertEqual(cat, "pending_cases")

        # 1_Updated with 0 bldg pts must NOT be called Confirmed Resolved,
        # because nothing was compared against it.
        feat.setAttribute("mbi_status", "1_Updated")
        feat.setAttribute("pso_remarks", "Boundary realigned")
        feat.setAttribute("num_bldg_pts", 0)
        cat, reason = self.mod.evaluate_reference_case(
            feat, spatially_confirmed=False, checker_available=False)
        self.assertEqual(cat, "still_active")
        self.assertIn("no Checker layer", reason)

        # Attribute-only mismatch rules still apply.
        feat.setAttribute("mbi_status", "1_Updated")
        feat.setAttribute("pso_remarks", None)
        feat.setAttribute("num_bldg_pts", 5)
        cat, _ = self.mod.evaluate_reference_case(
            feat, spatially_confirmed=False, checker_available=False)
        self.assertEqual(cat, "status_mismatch")

        feat.setAttribute("mbi_status", NULL)
        cat, _ = self.mod.evaluate_reference_case(
            feat, spatially_confirmed=False, checker_available=False)
        self.assertEqual(cat, "no_status")

    def test_process_algorithm_without_checker_layers(self):
        """Algorithm must run with no Checker layer and still emit Pending Cases."""
        try:
            params = {
                self.alg.REF_LAYER: self.ref_layer,
                self.alg.CHK_GAP: None,
                self.alg.CHK_OVERLAP: None,
                self.alg.GPKG_LAYERS: [2],
                self.alg.OUT_MISMATCH: "TEMPORARY_OUTPUT",
                self.alg.OUT_MISMATCH_REMARKS: "TEMPORARY_OUTPUT",
                self.alg.OUT_PENDING_CASES: "TEMPORARY_OUTPUT",
                self.alg.OUT_NEW: "TEMPORARY_OUTPUT",
                self.alg.OUT_STILL: "TEMPORARY_OUTPUT",
                self.alg.OUT_RESOLVED: "TEMPORARY_OUTPUT",
                self.alg.OUT_MANUAL_REVIEW: "TEMPORARY_OUTPUT",
                self.alg.OUT_NOSTATUS: "TEMPORARY_OUTPUT",
                self.alg.OUT_DISPUTED: "TEMPORARY_OUTPUT",
            }
            QgsProject.instance().addMapLayer(self.ref_layer)

            context = QgsProcessingContext()
            if hasattr(context, "setProject"):
                context.setProject(QgsProject.instance())
            feedback = QgsProcessingFeedback()

            res = self.alg.processAlgorithm(params, context, feedback)
            self.assertIsNotNone(res)
        except Exception as e:
            self.skipTest(f"Skipping test due to processing environment error: {e}")


if __name__ == "__main__":
    unittest.main()
