# -*- coding: utf-8 -*-
"""
Unit tests for verifying that Tab 2 - Sub 1 delineated_ea output only contains
EAs above the threshold (max_household).
"""

import unittest
from tests.mocks.qgis_mock import setup_qgis_mock_if_needed

setup_qgis_mock_if_needed()

from qgis.core import (
    QgsVectorLayer,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsFields,
    QgsField,
)
from PyQt5.QtCore import QVariant


class TestDelineatedEAThreshold(unittest.TestCase):
    """Tests ensuring delineated_ea contains only EAs above max_household threshold."""

    def test_delineation_candidate_below_threshold_exempted(self):
        """Verify that an EA with household count below max_household is NOT a delineation candidate even with for_delineation indicator."""
        from references.create_enumeration_area.phases.phase2_candidates import run_phase_2

        from unittest.mock import MagicMock
        feedback = MagicMock()
        feedback.isCanceled.return_value = False

        class DummyAlg:
            DELINEATED_OUTPUT = "DELINEATED_OUTPUT"
            MERGED_OUTPUT = "MERGED_OUTPUT"
            SPECIAL_EA_OUTPUT = "SPECIAL_EA_OUTPUT"
            DELINEATION_CANDIDATE_OUTPUT = "DELINEATION_CANDIDATE_OUTPUT"
            EXTRACTED_BUILDINGS_OUTPUT = "EXTRACTED_BUILDINGS_OUTPUT"

            def parameterAsSink(self, params, name, ctx, fields, wkb, crs):
                return (None, f"dest_{name}")

        alg = DummyAlg()

        # Create EA layer with 2 features:
        # EA 1: hhcount = 450 (above max 300) -> Candidate
        # EA 2: hhcount = 200 (below max 300, above min 100, but marked "for delineation") -> Should NOT be candidate
        ea_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "ea", "memory")
        pr = ea_layer.dataProvider()
        pr.addAttributes([
            QgsField("ean", QVariant.String),
            QgsField("hhcount", QVariant.Double),
            QgsField("eadel_indi", QVariant.String),
        ])
        ea_layer.updateFields()

        poly1 = QgsGeometry.fromPolygonXY([[QgsPointXY(0,0), QgsPointXY(1,0), QgsPointXY(1,1), QgsPointXY(0,1), QgsPointXY(0,0)]])
        poly2 = QgsGeometry.fromPolygonXY([[QgsPointXY(1,0), QgsPointXY(2,0), QgsPointXY(2,1), QgsPointXY(1,1), QgsPointXY(1,0)]])

        f1 = QgsFeature(ea_layer.fields())
        f1.setGeometry(poly1)
        f1.setAttribute("ean", "001000")
        f1.setAttribute("hhcount", 450.0)
        f1.setAttribute("eadel_indi", "")

        f2 = QgsFeature(ea_layer.fields())
        f2.setGeometry(poly2)
        f2.setAttribute("ean", "002000")
        f2.setAttribute("hhcount", 200.0)
        f2.setAttribute("eadel_indi", "for delineation")

        pr.addFeatures([f1, f2])
        ea_layer.updateExtents()

        p1 = {
            "barangay_source": QgsVectorLayer("Polygon?crs=EPSG:4326", "bgy", "memory"),
            "previous_ea_source": ea_layer,
            "building_source": QgsVectorLayer("Point?crs=EPSG:4326", "bldg", "memory"),
            "gap_source": None,
            "overlap_source": None,
            "target_crs": ea_layer.crs(),
            "area_threshold": 1.0,
            "max_household": 300,
            "min_household": 100,
            "target_household": 200,
            "household_field": "hhcount",
            "bldg_hh_field": "hhcount",
            "bldgcount_field": "bldgcount",
            "ea_id_field": "ean",
            "barangay_id_field": "geocode",
            "bar_geocode_field": "geocode",
            "eadel_indi_col_idx": 2,
            "merge_indi_col_idx": -1,
            "special_ea_info": {},
            "special_ea_ids": set(),
            "output_layer_name": "00000_delineated_ea2026",
            "transform": None,
            "preview_only": False,
            "_dc_geo_idx": -1,
            "barangay_by_id": {},
            "all_ea_features": list(ea_layer.getFeatures()),
            "barangay_index": None,
            "ea_fields": ea_layer.fields(),
            "out_fields": ea_layer.fields(),
            "ea_id_idx": 0,
            "export_fields": ea_layer.fields(),
            "merged_export_fields": ea_layer.fields(),
            "special_ea_export_fields": ea_layer.fields(),
        }

        context = MagicMock()
        p2 = run_phase_2(alg, {}, context, feedback, feedback, p1)
        delin_ids = p2["delineation_candidate_ids"]

        # Only f1 (id=1, hhcount=450 >= 300) should be a delineation candidate
        self.assertIn(1, delin_ids)
        self.assertNotIn(2, delin_ids)

    def test_phase8_delineated_sink_only_contains_above_threshold(self):
        """Verify that Phase 8 only writes EAs >= max_household to the delineated_sink."""
        from references.create_enumeration_area.phases.phase8_output import run_phase_8
        from unittest.mock import MagicMock

        class MockSink:
            def __init__(self):
                self.features = []
            def addFeature(self, feat, flags=None):
                self.features.append(feat)
                return True

        feedback = MagicMock()
        feedback.isCanceled.return_value = False

        class DummyAlg:
            DELINEATED_OUTPUT = "DELINEATED_OUTPUT"
            MERGED_OUTPUT = "MERGED_OUTPUT"
            SPECIAL_EA_OUTPUT = "SPECIAL_EA_OUTPUT"
            DELINEATION_CANDIDATE_OUTPUT = "DELINEATION_CANDIDATE_OUTPUT"
            EXTRACTED_BUILDINGS_OUTPUT = "EXTRACTED_BUILDINGS_OUTPUT"

        alg = DummyAlg()
        delin_sink = MockSink()

        fields = QgsFields()
        for f in ["fid", "map_uuid", "geocode", "region", "province", "city_mun", "barangay", "code", "name", "ean", "hhcount", "bldgcount", "sy", "new_ean", "hh_count", "bldg_count", "ea_type", "remarks"]:
            fields.append(QgsField(f, QVariant.Int if f == "fid" else (QVariant.Double if f == "hhcount" else (QVariant.Int if "count" in f else QVariant.String))))

        poly1 = QgsGeometry.fromPolygonXY([[QgsPointXY(0,0), QgsPointXY(1,0), QgsPointXY(1,1), QgsPointXY(0,1), QgsPointXY(0,0)]])
        poly2 = QgsGeometry.fromPolygonXY([[QgsPointXY(1,0), QgsPointXY(2,0), QgsPointXY(2,1), QgsPointXY(1,1), QgsPointXY(1,0)]])

        eas = [
            {'geom': poly1, 'original_id': 1, 'original_code': '001000', 'new_ea_code': '001000', 'parent_barangay': '043404001', 'is_special_ea': False, 'hh_count': 450.0, 'original_hhcount': 450.0, 'bldg_count': 45, 'buildings': [], 'from_split': False},
            {'geom': poly2, 'original_id': 2, 'original_code': '002000', 'new_ea_code': '002000', 'parent_barangay': '043404001', 'is_special_ea': False, 'hh_count': 200.0, 'original_hhcount': 200.0, 'bldg_count': 20, 'buildings': [], 'from_split': False},
        ]

        p1 = {
            "previous_ea_source": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory"),
            "building_source": None,
            "target_crs": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory").crs(),
            "area_threshold": 1.0,
            "max_household": 300,
            "min_household": 100,
            "bldg_hh_field": "hhcount",
            "ea_id_field": "ean",
            "bar_geocode_field": "geocode",
            "barangay_by_id": {},
        }
        p2 = {
            "out_fields": fields,
            "export_fields": fields,
            "delineation_candidate_ids": {1},
            "merge_candidate_ids": set(),
            "adjacent_ea_ids": set(),
            "delineated_sink": delin_sink,
            "delineated_dest_id": "dest_delin",
        }
        p3 = {"road_geoms": {}, "river_geoms": {}}
        p4 = {"max_ea_number": {}, "barangay_sibling_ean_codes": {}}
        p7 = {"eas": eas}

        results = run_phase_8(alg, {}, None, feedback, feedback, p1, p2, p3, p4, p7)

        # delineated_sink should only contain EA 1 (450 HH >= 300)
        self.assertEqual(len(delin_sink.features), 1)
        self.assertEqual(delin_sink.features[0].attribute("code"), "001000")


if __name__ == '__main__':
    unittest.main()
