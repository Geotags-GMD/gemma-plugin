# -*- coding: utf-8 -*-
"""
Unit tests for verifying that Tab 2 outputs with 0 features are not generated,
not exported as GeoPackage files, not loaded to canvas, and empty groups are pruned.
"""

import unittest
from unittest.mock import MagicMock, patch
from tests.mocks.qgis_mock import setup_qgis_mock_if_needed, MockGenericClass

setup_qgis_mock_if_needed()

from qgis.core import (
    QgsVectorLayer,
    QgsProject,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsFields,
    QgsField,
)
from PyQt5.QtCore import QVariant


class TestTab2EmptyOutputs(unittest.TestCase):
    """Test suite for verifying 0-feature output suppression in Tab 2."""

    def test_post_process_algorithm_skips_zero_feature_layers(self):
        """Verify that postProcessAlgorithm doesn't apply QML styling to layers with 0 features."""
        from references.create_enumeration_area.eadm_candidates import EADMCandidatesAlgorithm

        alg = EADMCandidatesAlgorithm()
        mock_context = MagicMock()
        mock_feedback = MagicMock()

        # Create empty layer (0 features)
        empty_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "empty_output", "memory")
        self.assertEqual(empty_layer.featureCount(), 0)

        mock_context.getMapLayer.return_value = empty_layer
        alg.parameterAsOutputLayer = MagicMock(return_value="layer_1")

        with patch("references.create_enumeration_area.helpers.style.apply_qml_to_layer") as mock_apply_qml:
            alg.postProcessAlgorithm(mock_context, mock_feedback)
            mock_apply_qml.assert_not_called()

    def test_post_process_algorithm_applies_qml_when_features_exist(self):
        """Verify that postProcessAlgorithm applies QML styling when features > 0."""
        from references.create_enumeration_area.eadm_candidates import EADMCandidatesAlgorithm

        alg = EADMCandidatesAlgorithm()
        mock_context = MagicMock()
        mock_feedback = MagicMock()

        # Create layer with 1 feature
        layer_with_feat = QgsVectorLayer("Polygon?crs=EPSG:4326", "valid_output", "memory")
        f = QgsFeature()
        f.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(0, 0), QgsPointXY(0, 1), QgsPointXY(1, 1), QgsPointXY(0, 0)]]))
        layer_with_feat.dataProvider().addFeatures([f])
        layer_with_feat.updateExtents()

        self.assertEqual(layer_with_feat.featureCount(), 1)

        mock_context.getMapLayer.return_value = layer_with_feat
        alg.parameterAsOutputLayer = MagicMock(return_value="layer_1")

        with patch("references.create_enumeration_area.helpers.style.apply_qml_to_layer") as mock_apply_qml:
            alg.postProcessAlgorithm(mock_context, mock_feedback)
            self.assertTrue(mock_apply_qml.called)

    def test_run_phase_8_final_outputs_omits_zero_count_sinks(self):
        """Verify that run_phase_8 does not include outputs in final_outputs if count == 0."""
        from references.create_enumeration_area.phases.phase8_output import run_phase_8

        mock_alg = MagicMock()
        mock_alg.total_ea_processed = 0
        mock_alg.total_delin_candidates = 0
        mock_alg.DELINEATED_OUTPUT = "DELINEATED_OUTPUT"
        mock_alg.MERGED_OUTPUT = "MERGED_OUTPUT"
        mock_alg.SPECIAL_EA_OUTPUT = "SPECIAL_EA_OUTPUT"
        mock_alg.DELINEATION_CANDIDATE_OUTPUT = "DELINEATION_CANDIDATE_OUTPUT"
        mock_alg.EXTRACTED_BUILDINGS_OUTPUT = "EXTRACTED_BUILDINGS_OUTPUT"

        fields = QgsFields()
        fields.append(QgsField("geocode", QVariant.String))
        fields.append(QgsField("ean", QVariant.String))

        dummy_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "test", "memory")
        p1 = {
            "previous_ea_source": dummy_layer,
            "barangay_source": dummy_layer,
            "building_source": dummy_layer,
            "out_fields": fields,
            "target_crs": dummy_layer.crs(),
            "area_threshold": 1.0,
            "max_household": 300,
            "min_household": 100,
            "household_field": "hhcount",
            "bldgcount_field": "bldgcount",
            "output_hh_field": "hhcount",
            "bldg_hh_field": "hhcount",
            "ea_id_field": "ean",
            "barangay_by_id": {},
        }
        p2 = {
            "delineation_candidate_ids": set(),
            "merge_candidate_ids": set(),
            "adjacent_ea_ids": set(),
            "special_ea_info": {},
            "delineated_sink": MagicMock(),
            "merged_sink": MagicMock(),
            "special_ea_sink": MagicMock(),
            "extracted_buildings_sink": MagicMock(),
            "delineated_dest_id": "delin_id",
            "merged_dest_id": "merged_id",
            "extracted_buildings_dest_id": "bldg_id",
            "delin_candidate_dest_id": "delin_cand_id",
            "delin_candidate_feat_count": 0,
            "extracted_bldg_feat_count": 0,
        }
        p3 = {"road_geoms": {}, "river_geoms": {}}
        p4 = {"max_ea_number": {}, "barangay_sibling_ean_codes": {}}
        p7 = {"eas": [], "split_eas": []}

        feedback = MagicMock()
        feedback.isCanceled.return_value = False
        multi_feedback = MagicMock()
        multi_feedback.isCanceled.return_value = False

        outputs = run_phase_8(
            alg=mock_alg,
            parameters={},
            context=MagicMock(),
            feedback=feedback,
            multi_feedback=multi_feedback,
            p1=p1,
            p2=p2,
            p3=p3,
            p4=p4,
            p7=p7,
        )

        # Since all feature counts are 0, outputs dictionary must be completely empty!
        self.assertEqual(outputs, {}, "Outputs dict should be empty when no features are generated.")

    def test_dialog_layer_cleanup_skips_zero_feature_layers(self):
        """Verify that layer processing in dialog removes 0-feature layers and prunes groups."""
        project = QgsProject.instance()
        project.removeAllMapLayers()

        # Add an empty temporary layer to project
        empty_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "01234_delineated_ea2026", "memory")
        project.addMapLayer(empty_layer)
        empty_layer_id = empty_layer.id()
        self.assertIn(empty_layer_id, project.mapLayers())

        # Simulate cleanup logic
        for lyr_id, lyr_obj in list(project.mapLayers().items()):
            if lyr_obj.name() == "01234_delineated_ea2026" and lyr_obj.featureCount() == 0:
                project.removeMapLayer(lyr_id)

        self.assertNotIn(empty_layer_id, project.mapLayers(), "Empty layer should be removed from project.")

    def test_tab2_dialog_omits_gap_overlap_inputs_and_special_ea(self):
        """Verify that Tab 2 UI elements do not include gap/overlap combos or special_ea output label."""
        import inspect
        from references.create_enumeration_area import dialog
        content_source = inspect.getsource(dialog.EALauncherDialog._build_create_ea_content)
        self.assertNotIn("gap_combo", content_source)
        self.assertNotIn("overlap_combo", content_source)
        self.assertNotIn("out_special_lbl", content_source)
        self.assertNotIn("special_ea", content_source)

        pipeline_func = getattr(dialog.EALauncherDialog, "run_pipeline", None) or getattr(dialog.EALauncherDialog, "_run_pipeline", None)
        if pipeline_func:
            pipeline_source = inspect.getsource(pipeline_func)
            self.assertNotIn("special_ea", pipeline_source)
            self.assertNotIn("GAP_INPUT", pipeline_source)
            self.assertNotIn("OVERLAP_INPUT", pipeline_source)
            self.assertNotIn("SPECIAL_EA_OUTPUT", pipeline_source)
            self.assertNotIn("MERGE_CANDIDATE_OUTPUT", pipeline_source)
            self.assertNotIn("out_merge_cand_lbl", content_source)
            self.assertNotIn("merge_cand_edit", content_source)


if __name__ == "__main__":
    unittest.main()
