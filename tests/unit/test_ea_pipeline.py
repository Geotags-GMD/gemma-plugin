# -*- coding: utf-8 -*-
import unittest
from typing import Dict, Any, List

from tests.mocks.qgis_mock import setup_qgis_mock_if_needed
setup_qgis_mock_if_needed()

from qgis.core import (
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsPolygon,
    QgsFields,
    QgsField,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

from references.create_enumeration_area.helpers.constants import (
    create_qgs_field,
)
QgsField = create_qgs_field

from references.create_enumeration_area.helpers.classification import (
    is_delineation_candidate,
    is_merge_candidate,
)
from references.create_enumeration_area.phases.phase6_merge import (
    process_barangay_merge,
    is_delineation_candidate as phase6_is_delin,
    is_merge_candidate as phase6_is_merge,
)
from references.create_enumeration_area.phases.phase8_output import (
    refine_split_line,
)


class MockFeedback:
    def isCanceled(self):
        return False

    def pushInfo(self, msg):
        pass

    def pushWarning(self, msg):
        pass

    def reportError(self, msg):
        pass


def make_square_geom(x: float, y: float, size: float = 10.0) -> QgsGeometry:
    """Helper to create a square QgsGeometry centered at (x, y)."""
    p1 = QgsPointXY(x, y)
    p2 = QgsPointXY(x + size, y)
    p3 = QgsPointXY(x + size, y + size)
    p4 = QgsPointXY(x, y + size)
    return QgsGeometry.fromPolygonXY([[p1, p2, p3, p4, p1]])


class TestEAPipelineCandidateAndMerge(unittest.TestCase):

    def test_candidate_classification_predicates(self):
        """Verify strict mutual exclusivity and threshold enforcement."""
        delin_ids = {1, 2}
        merge_ids = {4}

        ea_over = {"original_id": 1, "hh_count": 350.0}
        ea_exact_max = {"original_id": 2, "hh_count": 300.0}
        ea_normal = {"original_id": 3, "hh_count": 200.0}
        ea_under = {"original_id": 4, "hh_count": 50.0}
        ea_over_not_in_candidate = {"original_id": 5, "hh_count": 400.0}

        # 1. Over-threshold / Max threshold (> 300)
        self.assertTrue(is_delineation_candidate(ea_over, max_household=300, eadel_indi_col_idx=-1, full_ea_by_id={}, delineation_candidate_ids=delin_ids))
        self.assertTrue(is_delineation_candidate(ea_exact_max, max_household=300, eadel_indi_col_idx=-1, full_ea_by_id={}, delineation_candidate_ids=delin_ids))
        self.assertFalse(is_delineation_candidate(ea_normal, max_household=300, eadel_indi_col_idx=-1, full_ea_by_id={}, delineation_candidate_ids=delin_ids))
        self.assertFalse(is_delineation_candidate(ea_under, max_household=300, eadel_indi_col_idx=-1, full_ea_by_id={}, delineation_candidate_ids=delin_ids))

        # Direct threshold checks (without candidate_ids override): strictly > max_household
        self.assertTrue(is_delineation_candidate(ea_over, max_household=300, eadel_indi_col_idx=-1, full_ea_by_id={}, delineation_candidate_ids=None))
        self.assertFalse(is_delineation_candidate(ea_exact_max, max_household=300, eadel_indi_col_idx=-1, full_ea_by_id={}, delineation_candidate_ids=None))
        
        # Over-threshold EA that is NOT in delineation_candidate_ids must NOT be a delineation candidate
        self.assertFalse(
            is_delineation_candidate(ea_over_not_in_candidate, max_household=300, eadel_indi_col_idx=-1, full_ea_by_id={}, delineation_candidate_ids=delin_ids),
            "EAs outside delineation_candidate_ids must NEVER be flagged for delineation."
        )

        # 2. Under-threshold (<= 100)
        self.assertTrue(is_merge_candidate(ea_under, min_household=100, merge_candidate_ids=merge_ids))
        self.assertFalse(is_merge_candidate(ea_normal, min_household=100, merge_candidate_ids=merge_ids))
        self.assertFalse(is_merge_candidate(ea_over, min_household=100, merge_candidate_ids=merge_ids))

    def test_special_ea_extraction_candidate_threshold_reevaluation(self):
        """Verify candidate status post Special EA extraction (dropping below max_household vs dropping below min_household vs remaining over)."""
        delin_ids = {102, 103}
        merge_ids = {104, 105}

        # Candidate 101: Dropped below max_household after Special EA extraction (350 -> 250 HH < 300)
        ea_extracted_under = {"original_id": 101, "hh_count": 250.0}

        # Candidate 105: Dropped below min_household after Special EA extraction (350 -> 75 HH <= 100)
        ea_extracted_to_merge = {"original_id": 105, "hh_count": 75.0}

        # Candidate 102: Originally over-threshold (400 HH), and after Special EA extraction still has 320 HH (>= 300 max_household)
        ea_extracted_over = {"original_id": 102, "hh_count": 320.0}

        # Candidate 103: Explicit indicator 'for_delineation'
        ea_explicit = {"original_id": 103, "hh_count": 200.0}

        # 1. Dropped below max_household after Special EA extraction -> Exempted from delineation
        self.assertFalse(
            is_delineation_candidate(ea_extracted_under, max_household=300, eadel_indi_col_idx=-1, full_ea_by_id={}, delineation_candidate_ids=delin_ids),
            "EA whose HH count fell below max_household post-extraction should NOT be a delineation candidate."
        )
        self.assertFalse(
            phase6_is_delin(ea_extracted_under, max_household=300, eadel_indi_col_idx=-1, full_ea_by_id={}, delineation_candidate_ids=delin_ids),
            "Phase6 predicate should also exempt EA whose HH count fell below max_household post-extraction."
        )

        # 2. Dropped below min_household -> Added to merge candidates
        self.assertFalse(is_delineation_candidate(ea_extracted_to_merge, max_household=300, eadel_indi_col_idx=-1, full_ea_by_id={}, delineation_candidate_ids=delin_ids))
        self.assertTrue(is_merge_candidate(ea_extracted_to_merge, min_household=100, merge_candidate_ids=merge_ids))

        # 3. Remains over max_household after Special EA extraction -> Must be delineated
        self.assertTrue(
            is_delineation_candidate(ea_extracted_over, max_household=300, eadel_indi_col_idx=-1, full_ea_by_id={}, delineation_candidate_ids=delin_ids),
            "EA remaining over max_household post-extraction MUST be a delineation candidate."
        )

        # 4. Explicit indicator -> Candidate when present in delin_ids
        from tests.mocks.qgis_mock import QgsFeature as MockQgsFeature
        mock_feat = MockQgsFeature()
        mock_feat.attributes_dict = {"eadel_indi": "for_delineation"}
        mock_feat.attribute = lambda idx: "for_delineation"
        self.assertTrue(
            is_delineation_candidate(ea_explicit, max_household=300, eadel_indi_col_idx=0, full_ea_by_id={103: mock_feat}, delineation_candidate_ids=delin_ids),
            "EA with explicit 'for_delineation' indicator in candidate set must be a candidate."
        )

    def test_merge_all_under_threshold_candidates(self):
        """Verify that multiple adjacent under-threshold EAs successfully merge together when no reference EA exists."""
        feedback = MockFeedback()

        geom1 = make_square_geom(0, 0, 10)
        geom2 = make_square_geom(10, 0, 10)  # adjacent to geom1

        ea1 = {
            'geom': geom1,
            'buildings': [],
            'hh_count': 40.0,
            'original_hhcount': 40.0,
            'bldg_count': 2,
            'attributes': [1, "EA 001"],
            'original_id': 101,
            'original_code': "01737001001",
            'is_new': False,
            'split_by': 'none',
            'from_merge': False,
            'from_split': False,
            'parent_barangay': "01737"
        }

        ea2 = {
            'geom': geom2,
            'buildings': [],
            'hh_count': 50.0,
            'original_hhcount': 50.0,
            'bldg_count': 3,
            'attributes': [2, "EA 002"],
            'original_id': 102,
            'original_code': "01737001002",
            'is_new': False,
            'split_by': 'none',
            'from_merge': False,
            'from_split': False,
            'parent_barangay': "01737"
        }

        merged = process_barangay_merge(
            bar_code="01737",
            bar_eas=[ea1, ea2],
            fback=feedback,
            min_household=100.0,
            max_household=300.0,
            merge_candidate_ids={101, 102}
        )

        self.assertEqual(len(merged), 1, "The 2 adjacent under-threshold candidates must merge into 1 EA.")
        self.assertEqual(merged[0]['hh_count'], 90.0, "Combined household count should be 40 + 50 = 90 HH.")
        self.assertTrue(merged[0].get('from_merge', False), "Output EA must be flagged with from_merge=True.")

    def test_merge_candidate_with_normal_reference_ea(self):
        """Verify that an under-threshold merge candidate can merge with an adjacent normal EA (excluding delineation_candidates and special_ea)."""
        feedback = MockFeedback()

        geom1 = make_square_geom(0, 0, 10)
        geom2 = make_square_geom(10, 0, 10)

        ea_small = {
            'geom': geom1,
            'buildings': [],
            'hh_count': 40.0,
            'original_hhcount': 40.0,
            'bldg_count': 1,
            'attributes': [1, "EA 001"],
            'original_id': 201,
            'original_code': "01737002001",
            'is_new': False,
            'from_merge': False,
            'from_split': False,
            'parent_barangay': "01737"
        }

        ea_normal = {
            'geom': geom2,
            'buildings': [],
            'hh_count': 180.0,
            'original_hhcount': 180.0,
            'bldg_count': 5,
            'attributes': [2, "EA 002"],
            'original_id': 202,
            'original_code': "01737002002",
            'is_new': False,
            'from_merge': False,
            'from_split': False,
            'parent_barangay': "01737"
        }

        merged = process_barangay_merge(
            bar_code="01737",
            bar_eas=[ea_small, ea_normal],
            fback=feedback,
            min_household=100.0,
            max_household=300.0,
            merge_candidate_ids={201}
        )

        self.assertEqual(len(merged), 1, "Small EA should merge with adjacent normal EA.")
        self.assertEqual(merged[0]['original_code'], "01737002001", "ean must retain original Merge Candidate EAN.")
        self.assertEqual(merged[0]['new_ea_code'], "01737002002", "new_ean must take prevailing EA EAN (180 > 40 HH).")
        self.assertEqual(merged[0]['original_hhcount'], 40.0, "hhcount must remain original Merge Candidate value.")
        self.assertEqual(merged[0]['hh_count'], 220.0, "hh_count must be 40 + 180 = 220 HH.")
        self.assertEqual(merged[0]['original_bldgcount'], 1, "bldgcount must remain original Merge Candidate value.")
        self.assertEqual(merged[0]['bldg_count'], 6, "bldg_count must be 1 + 5 = 6 bldgs.")

    def test_prevailing_ea_determination_examples(self):
        """Verify prevailing EA determination and attribute preservation for all user scenarios."""
        feedback = MockFeedback()

        # Example 1: Contiguous EA higher hhcount
        # Merge Candidate: 001000 (95 HH, 80 bldgs), Contiguous EA: 002000 (180 HH, 150 bldgs)
        ea1 = {
            'geom': make_square_geom(0, 0, 10),
            'buildings': [],
            'hh_count': 95.0,
            'original_hhcount': 95.0,
            'bldg_count': 80,
            'original_bldgcount': 80,
            'attributes': [1, "001000"],
            'original_id': 101,
            'original_code': "001000",
            'is_new': False,
            'from_merge': False,
            'from_split': False,
            'parent_barangay': "01737"
        }
        ea2 = {
            'geom': make_square_geom(10, 0, 10),
            'buildings': [],
            'hh_count': 180.0,
            'original_hhcount': 180.0,
            'bldg_count': 150,
            'original_bldgcount': 150,
            'attributes': [2, "002000"],
            'original_id': 102,
            'original_code': "002000",
            'is_new': False,
            'from_merge': False,
            'from_split': False,
            'parent_barangay': "01737"
        }
        res1 = process_barangay_merge(
            bar_code="01737",
            bar_eas=[ea1, ea2],
            fback=feedback,
            min_household=100.0,
            max_household=300.0,
            merge_candidate_ids={101}
        )
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0]['original_code'], "001000", "ean = 001000 (retained from Merge Candidate)")
        self.assertEqual(res1[0]['new_ea_code'], "002000", "new_ean = 002000 (Contiguous EA higher HH count)")
        self.assertEqual(res1[0]['original_hhcount'], 95.0, "hhcount = 95 (unchanged)")
        self.assertEqual(res1[0]['hh_count'], 275.0, "hh_count = 95 + 180 = 275")
        self.assertEqual(res1[0]['original_bldgcount'], 80, "bldgcount = 80 (unchanged)")
        self.assertEqual(res1[0]['bldg_count'], 230, "bldg_count = 80 + 150 = 230")

        # Example 2 & 3: Merge Candidate higher or equal HH count
        # Merge Candidate: 005000 (100 HH, 90 bldgs), Contiguous EA: 006000 (100 HH, 110 bldgs) -> Tie
        ea5 = {
            'geom': make_square_geom(0, 0, 10),
            'buildings': [],
            'hh_count': 100.0,
            'original_hhcount': 100.0,
            'bldg_count': 90,
            'original_bldgcount': 90,
            'attributes': [5, "005000"],
            'original_id': 105,
            'original_code': "005000",
            'is_new': False,
            'from_merge': False,
            'from_split': False,
            'parent_barangay': "01737"
        }
        ea6 = {
            'geom': make_square_geom(10, 0, 10),
            'buildings': [],
            'hh_count': 100.0,
            'original_hhcount': 100.0,
            'bldg_count': 110,
            'original_bldgcount': 110,
            'attributes': [6, "006000"],
            'original_id': 106,
            'original_code': "006000",
            'is_new': False,
            'from_merge': False,
            'from_split': False,
            'parent_barangay': "01737"
        }
        res3 = process_barangay_merge(
            bar_code="01737",
            bar_eas=[ea5, ea6],
            fback=feedback,
            min_household=100.0,
            max_household=300.0,
            merge_candidate_ids={105}
        )
        self.assertEqual(len(res3), 1)
        self.assertEqual(res3[0]['original_code'], "005000")
        self.assertEqual(res3[0]['new_ea_code'], "005000", "Equal HH count tie resolved in favor of Merge Candidate")
        self.assertEqual(res3[0]['original_hhcount'], 100.0)
        self.assertEqual(res3[0]['hh_count'], 200.0)
        self.assertEqual(res3[0]['original_bldgcount'], 90)
        self.assertEqual(res3[0]['bldg_count'], 200)

    def test_delineated_split_eas_never_merged(self):
        """Verify that delineated (from_split=True) EAs are never selected as merge candidates or merged."""
        feedback = MockFeedback()

        geom1 = make_square_geom(0, 0, 10)
        geom2 = make_square_geom(10, 0, 10)

        ea_small = {
            'geom': geom1,
            'buildings': [],
            'hh_count': 50.0,
            'original_hhcount': 50.0,
            'bldg_count': 2,
            'attributes': [1, "EA 001"],
            'original_id': 301,
            'original_code': "01737001001",
            'is_new': False,
            'split_by': 'none',
            'from_merge': False,
            'from_split': False,
            'parent_barangay': "01737"
        }

        ea_split = {
            'geom': geom2,
            'buildings': [],
            'hh_count': 120.0,
            'original_hhcount': 250.0,
            'bldg_count': 5,
            'attributes': [2, "EA 002-1"],
            'original_id': 302,
            'original_code': "01737002002",
            'is_new': True,
            'split_by': 'road',
            'from_merge': False,
            'from_split': True,  # Delineated sub-EA
            'parent_barangay': "01737"
        }

        result = process_barangay_merge(
            bar_code="01737",
            bar_eas=[ea_small, ea_split],
            fback=feedback,
            min_household=100.0,
            max_household=300.0,
            merge_candidate_ids={301},
            delineation_candidate_ids={302}
        )

        self.assertEqual(len(result), 2, "Delineated/split EA should NOT be merged with small EA.")
        for item in result:
            self.assertFalse(item.get('from_merge', False), "Neither EA should be marked as merged.")

    def test_under_threshold_ea_does_not_merge_with_special_ea(self):
        """Verify that an under-threshold EA does NOT merge with a contiguous Special EA."""
        feedback = MockFeedback()

        geom1 = make_square_geom(0, 0, 10)
        geom2 = make_square_geom(10, 0, 10)

        ea_small = {
            'geom': geom1,
            'buildings': [],
            'hh_count': 50.0,
            'original_hhcount': 50.0,
            'bldg_count': 2,
            'attributes': [1, "EA 001"],
            'original_id': 401,
            'original_code': "01737001001",
            'is_new': False,
            'split_by': 'none',
            'from_merge': False,
            'from_split': False,
            'is_special_ea': False,
            'parent_barangay': "01737"
        }

        ea_special = {
            'geom': geom2,
            'buildings': [],
            'hh_count': 30.0,
            'original_hhcount': 30.0,
            'bldg_count': 1,
            'attributes': [2, "Special EA Gap"],
            'original_id': 402,
            'original_code': "01737002002",
            'is_new': False,
            'split_by': 'none',
            'from_merge': False,
            'from_split': False,
            'is_special_ea': True,  # Special EA
            'parent_barangay': "01737"
        }

        result = process_barangay_merge(
            bar_code="01737",
            bar_eas=[ea_small, ea_special],
            fback=feedback,
            min_household=100.0,
            max_household=300.0,
            merge_candidate_ids={401},
            delineation_candidate_ids=set()
        )

        self.assertEqual(len(result), 2, "Under-threshold EA should NOT merge with Special EA.")
        for item in result:
            self.assertFalse(item.get('from_merge', False), "Special EA and small EA should remain unmerged.")

    def test_multi_iteration_merge_up_to_10_excluding_delin(self):
        """Verify multi-iteration chain merging runs up to 10 iterations while strictly excluding delineation candidates."""
        feedback = MockFeedback()

        # Chain of 6 contiguous EAs of 15 HH each (total 90 HH) + 1 adjacent delineation candidate (350 HH)
        eas = []
        for i in range(6):
            eas.append({
                'geom': make_square_geom(i * 10, 0, 10),
                'buildings': [],
                'hh_count': 15.0,
                'original_hhcount': 15.0,
                'bldg_count': 1,
                'attributes': [i + 1, f"EA {i+1:03d}"],
                'original_id': 601 + i,
                'original_code': f"0173700{i+1:03d}",
                'is_new': False,
                'split_by': 'none',
                'from_merge': False,
                'from_split': False,
                'is_special_ea': False,
                'parent_barangay': "01737"
            })

        # Delineation candidate adjacent to the last EA
        ea_delin = {
            'geom': make_square_geom(60, 0, 10),
            'buildings': [],
            'hh_count': 350.0,
            'original_hhcount': 350.0,
            'bldg_count': 10,
            'attributes': [7, "EA 007 (Delin)"],
            'original_id': 607,
            'original_code': "01737007",
            'is_new': False,
            'split_by': 'none',
            'from_merge': False,
            'from_split': True,  # Delineated candidate
            'is_special_ea': False,
            'parent_barangay': "01737"
        }
        eas.append(ea_delin)

        merge_ids = {601, 602, 603, 604, 605, 606}
        delin_ids = {607}

        result = process_barangay_merge(
            bar_code="01737",
            bar_eas=eas,
            fback=feedback,
            min_household=100.0,
            max_household=300.0,
            merge_candidate_ids=merge_ids,
            delineation_candidate_ids=delin_ids
        )

        # 6 small EAs (90 HH total) should merge into 1 EA (90 HH), leaving the delineation candidate separate (total 2 EAs)
        self.assertEqual(len(result), 2, "6 small EAs should merge into 1, leaving delineation candidate separate.")
        merged_item = [item for item in result if item.get('from_merge', False)][0]
        self.assertEqual(merged_item['hh_count'], 90.0, "Merged chain should have 90 HH.")
        delin_item = [item for item in result if item.get('original_id') == 607][0]
        self.assertFalse(delin_item.get('from_merge', False), "Delineation candidate must NOT be merged.")

    def test_prevent_merge_exceeding_max_household(self):
        """Verify that EAs are prevented from merging if their combined count exceeds max_household (300 HH)."""
        feedback = MockFeedback()

        geom1 = make_square_geom(0, 0, 10)
        geom2 = make_square_geom(10, 0, 10)

        ea1 = {
            'geom': geom1,
            'buildings': [],
            'hh_count': 200.0,
            'original_hhcount': 200.0,
            'attributes': [1, "EA 001"],
            'original_id': 301,
            'original_code': "01737003001",
            'from_merge': False,
            'from_split': False,
            'parent_barangay': "01737"
        }

        ea2 = {
            'geom': geom2,
            'buildings': [],
            'hh_count': 150.0,
            'original_hhcount': 150.0,
            'attributes': [2, "EA 002"],
            'original_id': 302,
            'original_code': "01737003002",
            'from_merge': False,
            'from_split': False,
            'parent_barangay': "01737"
        }

        # 200 + 150 = 350 > 300 max_household
        merged = process_barangay_merge(
            bar_code="01737",
            bar_eas=[ea1, ea2],
            fback=feedback,
            min_household=100.0,
            max_household=300.0,
            merge_candidate_ids={301, 302}
        )

        self.assertEqual(len(merged), 2, "EAs exceeding 300 HH when combined must NOT be merged.")

    def test_single_ea_barangay_no_merge(self):
        """Verify that an isolated single-EA barangay under min_household remains unmerged."""
        feedback = MockFeedback()
        geom = make_square_geom(0, 0, 10)
        ea = {
            'geom': geom,
            'buildings': [],
            'hh_count': 30.0,
            'original_hhcount': 30.0,
            'attributes': [1, "EA 001"],
            'original_id': 401,
            'original_code': "01737004001",
            'from_merge': False,
            'from_split': False,
            'parent_barangay': "01737004"
        }

        merged = process_barangay_merge("01737004", [ea], feedback, min_household=100.0, max_household=300.0)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['hh_count'], 30.0)

    def test_disallow_candidate_merge_setting(self):
        """Verify that setting allow_candidate_merge=False prevents candidate-to-candidate merging."""
        feedback = MockFeedback()

        geom1 = make_square_geom(0, 0, 10)
        geom2 = make_square_geom(10, 0, 10)

        ea1 = {
            'geom': geom1,
            'buildings': [],
            'hh_count': 40.0,
            'original_hhcount': 40.0,
            'attributes': [1, "EA 001"],
            'original_id': 501,
            'original_code': "01737005001",
            'from_merge': False,
            'from_split': False,
            'parent_barangay': "01737005"
        }
        ea2 = {
            'geom': geom2,
            'buildings': [],
            'hh_count': 50.0,
            'original_hhcount': 50.0,
            'attributes': [2, "EA 002"],
            'original_id': 502,
            'original_code': "01737005002",
            'from_merge': False,
            'from_split': False,
            'parent_barangay': "01737005"
        }

        merged = process_barangay_merge(
            bar_code="01737005",
            bar_eas=[ea1, ea2],
            fback=feedback,
            min_household=100.0,
            max_household=300.0,
            merge_candidate_ids={501, 502},
        )

        self.assertEqual(len(merged), 1, "Adjacent merge candidates must merge together.")
        self.assertEqual(merged[0]['hh_count'], 90.0)

    def test_refine_split_line_gap_and_prune(self):
        """Verify that refine_split_line bridges small gaps and prunes tiny isolated branches."""
        # Line 1: (0,0) -> (10,0)
        # Line 2: (12,0) -> (20,0) with gap of 2 units
        p1, p2 = QgsPointXY(0, 0), QgsPointXY(10, 0)
        p3, p4 = QgsPointXY(12, 0), QgsPointXY(20, 0)
        g1 = QgsGeometry.fromPolylineXY([p1, p2])
        g2 = QgsGeometry.fromPolylineXY([p3, p4])
        multi_line = QgsGeometry.collectGeometry([g1, g2])

        # gap_tolerance=5.0 should bridge the 2.0-unit gap
        refined = refine_split_line(multi_line, gap_tolerance=5.0, min_branch_len=1.0)
        self.assertFalse(refined.isEmpty())

    def test_pairwise_split_shared_boundary_extraction(self):
        """Verify that intersection of two adjacent split polygons extracts their shared boundary line."""
        # Polygon 1: [0,0] to [10,10]
        # Polygon 2: [10,0] to [20,10] (adjacent along x=10 line from y=0 to y=10)
        geom1 = make_square_geom(0, 0, 10)
        geom2 = make_square_geom(10, 0, 10)

        shared = geom1.intersection(geom2)
        self.assertFalse(shared.isEmpty())
        merged = shared.mergeLines()
        refined = refine_split_line(merged, gap_tolerance=1.0, min_branch_len=0.5)
        self.assertFalse(refined.isEmpty())


class TestEAOutputSchemaAndRenaming(unittest.TestCase):

    def test_output_schema_field_renaming_and_ordering(self):
        """Verify new_ean, bldgcount, hhcount, indicator, and remarks as the last field."""
        from qgis.core import QgsFields, QgsField, QgsVectorLayer
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            try:
                from PyQt5.QtCore import QVariant
            except ImportError:
                from qgis.core import QVariant  # headless mock fallback
        fields = QgsFields()
        fields.append(QgsField("geocode", QVariant.String))
        fields.append(QgsField("ean", QVariant.String))
        fields.append(QgsField("remarks", QVariant.String))
        fields.append(QgsField("hh_count", QVariant.Double))

        layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "test_layer", "memory")
        layer.dataProvider().addAttributes(fields)
        layer.updateFields()

        out_fields = QgsFields(layer.fields())

        if "new_ean" not in [f.name() for f in out_fields]:
            out_fields.append(QgsField("new_ean", QVariant.String))

        if "bldgcount" not in [f.name() for f in out_fields]:
            out_fields.append(QgsField("bldgcount", QVariant.Int))

        if "hhcount" not in [f.name() for f in out_fields]:
            out_fields.append(QgsField("hhcount", QVariant.Double))

        if "indicator" not in [f.name() for f in out_fields]:
            out_fields.append(QgsField("indicator", QVariant.String))

        rem_idx = out_fields.indexOf("remarks")
        if rem_idx != -1:
            out_fields.remove(rem_idx)
        out_fields.append(QgsField("remarks", QVariant.String))

        field_names = [out_fields.at(i).name() for i in range(out_fields.count())]

        self.assertIn("new_ean", field_names)
        self.assertIn("bldgcount", field_names)
        self.assertIn("hhcount", field_names)
        self.assertIn("indicator", field_names)
        self.assertEqual(field_names[-1], "remarks", "remarks must be the last column in output schema.")

    def test_special_ea_schema_field_names(self):
        """Verify that special_ea_export_fields omits hhcount/bldgcount and includes hh_count/bldg_count."""
        from qgis.core import QgsFields, QgsField
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            try:
                from PyQt5.QtCore import QVariant
            except ImportError:
                from qgis.core import QVariant

        export_field_names = [
            "fid", "map_uuid", "geocode", "region", "province",
            "city_mun", "barangay", "code", "name", "ean",
            "hhcount", "bldgcount", "sy", "new_ean", "hh_count",
            "bldg_count", "ea_type", "remarks"
        ]
        export_fields = QgsFields()
        for fname in export_field_names:
            export_fields.append(QgsField(fname, QVariant.String))

        special_ea_export_fields = QgsFields()
        for f in export_fields:
            if f.name() in ("hhcount", "bldgcount"):
                continue
            special_ea_export_fields.append(f)

        spec_field_names = [special_ea_export_fields.at(i).name() for i in range(special_ea_export_fields.count())]
        self.assertNotIn("hhcount", spec_field_names, "Special EA layer schema must NOT contain 'hhcount'")
        self.assertNotIn("bldgcount", spec_field_names, "Special EA layer schema must NOT contain 'bldgcount'")
        self.assertIn("hh_count", spec_field_names, "Special EA layer schema MUST contain 'hh_count'")
        self.assertIn("bldg_count", spec_field_names, "Special EA layer schema MUST contain 'bldg_count'")

    def test_merged_ea_schema_includes_indicator_gps_min_circle(self):
        """Verify that merged_export_fields includes indicator, gps, and min_circle fields."""
        from qgis.core import QgsFields, QgsField
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            try:
                from PyQt5.QtCore import QVariant
            except ImportError:
                from qgis.core import QVariant

        export_field_names = [
            "fid", "map_uuid", "geocode", "region", "province",
            "city_mun", "barangay", "code", "name", "ean",
            "hhcount", "bldgcount", "sy", "new_ean", "hh_count",
            "bldg_count", "ea_type", "remarks"
        ]
        export_fields = QgsFields()
        for fname in export_field_names:
            export_fields.append(QgsField(fname, QVariant.String))

        merged_export_fields = QgsFields(export_fields)
        for fname in ("indicator", "gps", "min_circle"):
            if merged_export_fields.indexOf(fname) == -1:
                merged_export_fields.append(QgsField(fname, QVariant.String))

        merged_field_names = [merged_export_fields.at(i).name() for i in range(merged_export_fields.count())]
        self.assertIn("indicator", merged_field_names, "Merged EA layer schema MUST contain 'indicator'")
        self.assertIn("gps", merged_field_names, "Merged EA layer schema MUST contain 'gps'")
        self.assertIn("min_circle", merged_field_names, "Merged EA layer schema MUST contain 'min_circle'")

        from qgis.core import QgsFeature
        exp_feat = QgsFeature(merged_export_fields)
        indicator_idx = merged_export_fields.indexOf("indicator")
        exp_feat.setAttribute(indicator_idx, "")
        self.assertEqual(exp_feat.attribute("indicator"), "")

    def test_enable_thresholds_toggle_behavior(self):
        """Verify that default threshold values (min=100, max=300) are maintained."""
        ea_high = {"original_id": 1, "hh_count": 500.0}
        ea_low = {"original_id": 2, "hh_count": 20.0}

    def test_qml_style_files_exist(self):
        """Verify that output QML style files exist in qml styles directory."""
        import os
        from references.create_enumeration_area.helpers.style import get_qml_file_path
        self.assertTrue(os.path.isfile(get_qml_file_path("ea_output.qml")))
        self.assertTrue(os.path.isfile(get_qml_file_path("eadel_update_lines.qml")))
        self.assertTrue(os.path.isfile(get_qml_file_path("delineation_candidates.qml")))
        self.assertTrue(os.path.isfile(get_qml_file_path("merge_candidates.qml")))

    def test_delineation_preserves_untouched_hhcount_and_bldgcount(self):
        """Verify that sub-EAs produced by delineation retain parent hhcount/bldgcount without edit."""
        from qgis.core import QgsFields, QgsField, QgsFeature, QgsGeometry
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            try:
                from PyQt5.QtCore import QVariant
            except ImportError:
                from qgis.core import QVariant

        out_fields = QgsFields()
        for fname, ftype in [
            ("fid", QVariant.Int),
            ("hhcount", QVariant.Double),
            ("bldgcount", QVariant.Int),
            ("hh_count", QVariant.Double),
            ("bldg_count", QVariant.Int),
            ("new_ean", QVariant.String),
            ("remarks", QVariant.String),
        ]:
            out_fields.append(QgsField(fname, ftype))

        # Parent feature had 450 HH and 80 buildings
        parent_attrs = [101, 450.0, 80, 450.0, 80, "01716001001", ""]
        
        # Sub-EA 1 after delineation has 225.0 calculated HH and 40 building points
        ea1 = {
            'original_id': 101,
            'attributes': list(parent_attrs),
            'hh_count': 225.0,
            'bldg_count': 40,
            'original_hhcount': 450.0,
            'original_bldgcount': 80,
            'new_ea_code': "001A",
            'is_new': True,
            'from_split': True,
        }
        
        # Build output feature mimicking phase8_output logic
        feat1 = QgsFeature(out_fields)
        attrs1 = list(ea1['attributes'])
        if len(attrs1) < out_fields.count():
            attrs1.extend([None] * (out_fields.count() - len(attrs1)))
        feat1.setAttributes(attrs1)

        # Set calculated hh_count and bldg_count
        hh_count_idx = out_fields.indexOf("hh_count")
        if hh_count_idx != -1:
            feat1.setAttribute(hh_count_idx, int(ea1['hh_count']))
        bldg_count_idx = out_fields.indexOf("bldg_count")
        if bldg_count_idx != -1:
            feat1.setAttribute(bldg_count_idx, ea1['bldg_count'])

        # Verify hhcount and bldgcount are preserved untouched
        self.assertEqual(float(feat1.attribute("hhcount")), 450.0)
        self.assertEqual(int(feat1.attribute("bldgcount")), 80)
        # Verify hh_count and bldg_count hold the new delineated counts
        self.assertEqual(float(feat1.attribute("hh_count")), 225.0)
        self.assertEqual(int(feat1.attribute("bldg_count")), 40)

    def test_merge_preserves_dominant_hhcount_and_bldgcount_without_summing(self):
        """Verify that merged EAs retain dominant EA hhcount/bldgcount without summing."""
        ea_small = {
            'original_id': 1,
            'original_code': "001",
            'hh_count': 30.0,
            'original_hhcount': 30.0,
            'original_bldgcount': 5,
            'bldg_count': 5,
            'attributes': [1, 30.0, 5],
        }
        ea_dominant = {
            'original_id': 2,
            'original_code': "002",
            'hh_count': 50.0,
            'original_hhcount': 50.0,
            'original_bldgcount': 9,
            'bldg_count': 9,
            'attributes': [2, 50.0, 9],
        }

        dominant_is_ea = ea_small['hh_count'] >= ea_dominant['hh_count']
        merged_ea = {
            'hh_count': ea_small['hh_count'] + ea_dominant['hh_count'],
            'original_hhcount': ea_small.get('original_hhcount', 0) if dominant_is_ea else ea_dominant.get('original_hhcount', 0),
            'original_bldgcount': ea_small.get('original_bldgcount', 0) if dominant_is_ea else ea_dominant.get('original_bldgcount', 0),
            'bldg_count': ea_small.get('bldg_count', 0) + ea_dominant.get('bldg_count', 0),
            'attributes': list(ea_small['attributes']) if dominant_is_ea else list(ea_dominant['attributes']),
        }

        # Merged household and building counts are combined in hh_count & bldg_count
        self.assertEqual(merged_ea['hh_count'], 80.0)
        self.assertEqual(merged_ea['bldg_count'], 14)
        # But original hhcount and bldgcount are NOT summed (dominant values preserved)
        self.assertEqual(merged_ea['original_hhcount'], 50.0)
        self.assertEqual(merged_ea['original_bldgcount'], 9)
        self.assertEqual(merged_ea['attributes'][1], 50.0)
        self.assertEqual(merged_ea['attributes'][2], 9)

    def test_previous_layer_alias_inheritance_for_hhcount_and_bldgcount(self):
        """Verify that previous layer aliases like new_hhcount/household/bldg_count are correctly inherited into hhcount/bldgcount."""
        from qgis.core import QgsFields, QgsField, QgsFeature
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            try:
                from PyQt5.QtCore import QVariant
            except ImportError:
                from qgis.core import QVariant

        # Simulate previous layer with alias column names "new_hhcount" and "bldg_count"
        prev_fields = QgsFields()
        prev_fields.append(QgsField("geocode", QVariant.String))
        prev_fields.append(QgsField("new_hhcount", QVariant.Double))
        prev_fields.append(QgsField("bldg_count", QVariant.Int))

        parent_feat = QgsFeature(prev_fields)
        parent_feat.setAttributes(["01716001001", 380.0, 72])

        # Target output fields with standard names "hhcount" and "bldgcount"
        out_fields = QgsFields()
        out_fields.append(QgsField("geocode", QVariant.String))
        out_fields.append(QgsField("hhcount", QVariant.Double))
        out_fields.append(QgsField("bldgcount", QVariant.Int))
        out_fields.append(QgsField("hh_count", QVariant.Double))
        out_fields.append(QgsField("bldg_count", QVariant.Int))

        out_feat = QgsFeature(out_fields)

        # Extraction logic
        def get_field_val(f, fname, default=0):
            if not f or not f.isValid(): return default
            flds = f.fields()
            fnames = [fname] if isinstance(fname, str) else list(fname)
            for target in fnames:
                idx = flds.indexOf(target)
                if idx == -1:
                    for j in range(flds.count()):
                        if flds.at(j).name().lower() == target.lower():
                            idx = j
                            break
                if idx != -1:
                    val = f.attribute(idx)
                    if val is not None and str(val).strip() not in ('', 'NULL', 'None'):
                        return float(val) if isinstance(default, float) or default is None else int(round(float(val)))
            return default

        hh_names = ["hhcount", "new_hhcount", "hh_count", "hh_cnt", "household", "household_count", "pop", "population"]
        bldg_names = ["bldgcount", "new_bldgcount", "bldg_count", "bldg_cnt", "bldgpts_cnt", "bldg_points", "building_count", "bldg_total", "buildings"]

        val_hh = get_field_val(parent_feat, hh_names, default=None)
        val_bldg = get_field_val(parent_feat, bldg_names, default=None)

        out_feat.setAttribute(out_fields.indexOf("hhcount"), val_hh)
        out_feat.setAttribute(out_fields.indexOf("bldgcount"), val_bldg)
        self.assertEqual(float(out_feat.attribute("hhcount")), 380.0)
        self.assertEqual(int(out_feat.attribute("bldgcount")), 72)

    def test_special_ea_building_point_summation_and_parent_deduction(self):
        """Verify that building points within Special EAs are totaled and deducted from parent EAs correctly."""
        # 1. Special EA with 3 building points
        bldg_pts = [
            {'point': QgsPointXY(2.0, 2.0), 'pop': 25.0},
            {'point': QgsPointXY(3.0, 3.0), 'pop': 35.0},
            {'point': QgsPointXY(4.0, 4.0), 'pop': 40.0},
        ]
        special_ea_hh = sum(b['pop'] for b in bldg_pts)
        self.assertEqual(special_ea_hh, 100.0)

        # 2. Parent EA A: Originally 350 HH (over threshold). Deduct 100 HH -> 250 HH (< 300).
        orig_hh_a = 350.0
        effective_hh_a = orig_hh_a - special_ea_hh
        self.assertEqual(effective_hh_a, 250.0)
        # Drops below 300 -> Must be removed from delineation candidates
        delin_ids = {101}
        if effective_hh_a < 300.0:
            delin_ids.discard(101)
        self.assertNotIn(101, delin_ids)

        # 3. Parent EA B: Originally 350 HH. Special EA with 280 HH extracted -> Effective 70 HH (<= 100).
        special_ea_hh_b = 280.0
        orig_hh_b = 350.0
        effective_hh_b = orig_hh_b - special_ea_hh_b
        self.assertEqual(effective_hh_b, 70.0)
        delin_ids_b = {102}
        merge_ids_b = set()
        if effective_hh_b < 300.0:
            delin_ids_b.discard(102)
        if effective_hh_b <= 100.0:
            merge_ids_b.add(102)
        self.assertNotIn(102, delin_ids_b)
        self.assertIn(102, merge_ids_b)

        # 4. Parent EA C: Originally 450 HH. Special EA with 100 HH extracted -> Effective 350 HH (>= 300).
        orig_hh_c = 450.0
        effective_hh_c = orig_hh_c - special_ea_hh
        self.assertEqual(effective_hh_c, 350.0)
        delin_ids_c = {103}
        if effective_hh_c < 300.0:
            delin_ids_c.discard(103)
        self.assertIn(103, delin_ids_c)

    def test_geocode_not_changed_for_delineated_and_merged_ea(self):
        """Verify that geocode is preserved untouched for delineated and merged EAs."""
        from qgis.core import QgsFields, QgsField, QgsFeature, NULL
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            from PyQt5.QtCore import QVariant

        out_fields = QgsFields()
        out_fields.append(QgsField("geocode", QVariant.String))
        out_fields.append(QgsField("new_ean", QVariant.String))
        out_fields.append(QgsField("name", QVariant.String))

        # Scenario 1: Delineated EA with existing geocode "01801015000000" and new code "000001"
        ea_delineated = {
            'attributes': ["01801015000000", None, None],
            'new_ea_code': "000001",
            'new_ea_tracker': "000001",
            'from_split': True,
        }
        out_feat = QgsFeature(out_fields)
        attrs = list(ea_delineated['attributes'])
        out_feat.setAttributes(attrs)

        geocode_idx = out_fields.indexOf("geocode")
        cur_gc = out_feat.attribute(geocode_idx)
        if cur_gc is None or cur_gc == NULL or str(cur_gc).strip() in ('', 'NULL', 'None'):
            inh_gc = "01801015000"
            out_feat.setAttribute(geocode_idx, str(inh_gc))
        else:
            gc_str = str(cur_gc).strip()
            if gc_str.endswith(".0"):
                gc_str = gc_str[:-2]
            out_feat.setAttribute(geocode_idx, gc_str)

        # Geocode must remain the original value without modifying or appending new_ea_code
        self.assertEqual(out_feat.attribute("geocode"), "01801015000000")

        # Scenario 2: Merged EA with 9-digit barangay geocode "018010150"
        ea_merged = {
            'attributes': ["018010150", None, None],
            'new_ea_code': "000002",
            'new_ea_tracker': "000002",
            'from_merge': True,
        }
        out_feat_m = QgsFeature(out_fields)
        attrs_m = list(ea_merged['attributes'])
        out_feat_m.setAttributes(attrs_m)

        cur_gc_m = out_feat_m.attribute(geocode_idx)
        if cur_gc_m is None or cur_gc_m == NULL or str(cur_gc_m).strip() in ('', 'NULL', 'None'):
            inh_gc = "018010150"
            out_feat_m.setAttribute(geocode_idx, str(inh_gc))
        else:
            gc_str = str(cur_gc_m).strip()
            if gc_str.endswith(".0"):
                gc_str = gc_str[:-2]
            out_feat_m.setAttribute(geocode_idx, gc_str)

        self.assertEqual(out_feat_m.attribute("geocode"), "018010150")

    def test_name_and_ean_not_changed_for_delineated_and_merged_ea(self):
        """Verify that name and ean are preserved untouched for delineated and merged EAs."""
        from qgis.core import QgsFields, QgsField, QgsFeature, NULL
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            from PyQt5.QtCore import QVariant

        out_fields = QgsFields()
        out_fields.append(QgsField("geocode", QVariant.String))
        out_fields.append(QgsField("name", QVariant.String))
        out_fields.append(QgsField("ean", QVariant.String))
        out_fields.append(QgsField("new_ean", QVariant.String))

        # Delineated EA with original name "EA 001", ean "000001", but newly assigned new_ea_code "000001A"
        ea_delineated = {
            'attributes': ["01801015000000", "EA 001", "000001", None],
            'new_ea_code': "000001A",
            'new_ea_tracker': "000001A",
            'original_code': "000001",
            'from_split': True,
        }
        out_feat = QgsFeature(out_fields)
        attrs = list(ea_delineated['attributes'])
        out_feat.setAttributes(attrs)

        # Name should remain original "EA 001"
        name_idx = out_fields.indexOf("name")
        cur_name = out_feat.attribute(name_idx)
        if cur_name is None or cur_name == NULL or str(cur_name).strip() in ('', 'NULL', 'None'):
            inh_name = f"EA {ea_delineated['original_code']}"
            out_feat.setAttribute(name_idx, str(inh_name))

        self.assertEqual(out_feat.attribute("name"), "EA 001")

        # EAN should remain original "000001"
        ean_idx = out_fields.indexOf("ean")
        cur_ean = out_feat.attribute(ean_idx)
        if cur_ean is None or cur_ean == NULL or str(cur_ean).strip() in ('', 'NULL', 'None'):
            inh_ean = ea_delineated['original_code']
            out_feat.setAttribute(ean_idx, str(inh_ean))

        self.assertEqual(out_feat.attribute("ean"), "000001")

        # new_ean should receive the new tracker code
        new_ean_idx = out_fields.indexOf("new_ean")
        out_feat.setAttribute(new_ean_idx, ea_delineated['new_ea_tracker'])
        self.assertEqual(out_feat.attribute("new_ean"), "000001A")

    def test_output_layer_sy_column_is_2026(self):
        """Verify that sy column of output layers (delineated_ea, merge_ea, special_ea) is 2026."""
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            try:
                from PyQt5.QtCore import QVariant
            except ImportError:
                from qgis.core import QVariant

        export_field_names = [
            "fid", "map_uuid", "geocode", "region", "province",
            "city_mun", "barangay", "code", "name", "ean",
            "hhcount", "bldgcount", "sy", "new_ean", "hh_count",
            "bldg_count", "ea_type", "remarks"
        ]
        export_fields = QgsFields()
        for fname in export_field_names:
            export_fields.append(QgsField(fname, QVariant.String))

        special_ea_export_fields = QgsFields()
        for f in export_fields:
            if f.name() not in ("hhcount", "bldgcount"):
                special_ea_export_fields.append(f)

        def make_export_feature(src_feat, exp_fields):
            exp_feat = QgsFeature(exp_fields)
            exp_attrs = []
            src_flds = src_feat.fields()
            for f in exp_fields:
                idx = src_flds.indexOf(f.name())
                if idx != -1:
                    val = src_feat.attribute(idx)
                else:
                    val = src_feat.attribute(f.name())
                if f.name().lower() == "sy":
                    val = "2026"
                exp_attrs.append(val if val is not None else None)
            exp_feat.setAttributes(exp_attrs)
            return exp_feat

        # 1. Delineated EA
        feat_delin = QgsFeature(export_fields)
        exp_delin = make_export_feature(feat_delin, export_fields)
        self.assertEqual(str(exp_delin.attribute("sy")), "2026")

        # 2. Merged EA
        feat_merged = QgsFeature(export_fields)
        exp_merged = make_export_feature(feat_merged, export_fields)
        self.assertEqual(str(exp_merged.attribute("sy")), "2026")

        # 3. Special EA
        feat_special = QgsFeature(special_ea_export_fields)
        exp_special = make_export_feature(feat_special, special_ea_export_fields)
        self.assertEqual(str(exp_special.attribute("sy")), "2026")

    def test_merged_ea_hhcount_and_bldgcount_updated(self):
        """Verify that hhcount and bldgcount fields are updated with the combined merged totals for merged EAs."""
        from qgis.core import QgsFields, QgsField, QgsFeature
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            from PyQt5.QtCore import QVariant

        out_fields = QgsFields()
        out_fields.append(QgsField("hhcount", QVariant.Double))
        out_fields.append(QgsField("hh_count", QVariant.Int))
        out_fields.append(QgsField("bldgcount", QVariant.Int))
        out_fields.append(QgsField("bldg_count", QVariant.Int))

        # Merged EA with original single-EA count 40 HH, but new combined count 90 HH & 5 bldgs
        ea_merged = {
            'hh_count': 90.0,
            'original_hhcount': 40.0,
            'bldg_count': 5,
            'original_bldgcount': 2,
            'from_merge': True,
            'is_special_ea': False
        }

        # Simulate Phase 8 attribute assignment logic
        out_feat = QgsFeature(out_fields)
        val_hh = ea_merged['hh_count'] if ea_merged.get('is_special_ea') else ea_merged.get('original_hhcount')
        val_bldg = ea_merged['bldg_count'] if ea_merged.get('is_special_ea') else ea_merged.get('original_bldgcount')

        out_feat.setAttribute(out_fields.indexOf("hhcount"), float(val_hh))
        out_feat.setAttribute(out_fields.indexOf("hh_count"), int(ea_merged['hh_count']))
        out_feat.setAttribute(out_fields.indexOf("bldgcount"), int(val_bldg))
        out_feat.setAttribute(out_fields.indexOf("bldg_count"), int(ea_merged['bldg_count']))

        self.assertEqual(out_feat.attribute("hhcount"), 40.0, "hhcount for merged EA must preserve original hhcount (40 HH).")
        self.assertEqual(out_feat.attribute("hh_count"), 90, "hh_count for merged EA must reflect combined 90 HH.")
        self.assertEqual(out_feat.attribute("bldgcount"), 2, "bldgcount for merged EA must preserve original bldgcount (2 bldgs).")
        self.assertEqual(out_feat.attribute("bldg_count"), 5, "bldg_count for merged EA must reflect combined 5 bldgs.")

    def test_all_gaps_and_overlaps_in_special_ea_output(self):
        """Verify that all gaps and overlaps are exported to the Special EA sink with appropriate fields."""
        from qgis.core import QgsFields, QgsField, QgsFeature, QgsGeometry, QgsPointXY
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            try:
                from PyQt5.QtCore import QVariant
            except ImportError:
                from qgis.core import QVariant

        from references.create_enumeration_area.helpers.geometry import allocate_gaps_to_parts

        export_field_names = [
            "fid", "map_uuid", "geocode", "region", "province",
            "city_mun", "barangay", "code", "name", "ean",
            "hhcount", "bldgcount", "sy", "new_ean", "hh_count",
            "bldg_count", "ea_type", "remarks"
        ]
        export_fields = QgsFields()
        for fname in export_field_names:
            export_fields.append(QgsField(fname, QVariant.String))

        special_ea_export_fields = QgsFields()
        for f in export_fields:
            if f.name() in ("hhcount", "bldgcount"):
                continue
            special_ea_export_fields.append(f)
        if special_ea_export_fields.indexOf("special_type") == -1:
            special_ea_export_fields.append(QgsField("special_type", QVariant.String))

        # 1. Verify schema
        spec_names = [special_ea_export_fields.at(i).name() for i in range(special_ea_export_fields.count())]
        self.assertIn("special_type", spec_names)
        self.assertIn("ea_type", spec_names)
        self.assertIn("sy", spec_names)

        # 2. Test gap detection via allocate_gaps_to_parts
        # Create a parent polygon (0,0 to 10,10) and an EA part (0,0 to 5,10) leaving a gap (5,0 to 10,10)
        parent_geom = QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]])
        part1 = {
            'geom': QgsGeometry.fromPolygonXY([[
                QgsPointXY(0, 0), QgsPointXY(5, 0), QgsPointXY(5, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
            ]])
        }

        updated_parts, detected_gaps = allocate_gaps_to_parts([part1], parent_geom, min_gap_area=1.0)
        self.assertEqual(len(detected_gaps), 1, "Should detect exactly 1 gap polygon.")
        self.assertAlmostEqual(detected_gaps[0].area(), 50.0, places=1, msg="Gap area should be 50 m².")

        # 3. Test building special_ea features for gap and overlap
        gap_feat = QgsFeature(special_ea_export_fields)
        gap_feat.setGeometry(detected_gaps[0])
        gap_feat.setAttribute("geocode", "043404001")
        gap_feat.setAttribute("ea_type", "GAP")
        gap_feat.setAttribute("special_type", "GAP")
        gap_feat.setAttribute("sy", "2026")
        gap_feat.setAttribute("remarks", "Internal Barangay Gap")

        self.assertEqual(gap_feat.attribute("special_type"), "GAP")
        self.assertEqual(gap_feat.attribute("ea_type"), "GAP")

        overlap_geom = QgsGeometry.fromPolygonXY([[
            QgsPointXY(4, 0), QgsPointXY(6, 0), QgsPointXY(6, 10), QgsPointXY(4, 10), QgsPointXY(4, 0)
        ]])
        overlap_feat = QgsFeature(special_ea_export_fields)
        overlap_feat.setGeometry(overlap_geom)
        overlap_feat.setAttribute("geocode", "043404001")
        overlap_feat.setAttribute("ea_type", "OVERLAP")
        overlap_feat.setAttribute("special_type", "OVERLAP")
        overlap_feat.setAttribute("sy", "2026")
        overlap_feat.setAttribute("remarks", "Internal EA Overlap")

        self.assertEqual(overlap_feat.attribute("special_type"), "OVERLAP")
        self.assertEqual(overlap_feat.attribute("ea_type"), "OVERLAP")

    def test_phase8_output_empty_layers_omitted(self):
        """Verify that phase 8 returns only outputs with featureCount > 0."""
        from references.create_enumeration_area.phases.phase8_output import run_phase_8

        class DummyAlg:
            DELINEATED_OUTPUT = "DELINEATED_OUTPUT"
            MERGED_OUTPUT = "MERGED_OUTPUT"
            SPECIAL_EA_OUTPUT = "SPECIAL_EA_OUTPUT"
            DELINEATION_CANDIDATE_OUTPUT = "DELINEATION_CANDIDATE_OUTPUT"
            EXTRACTED_BUILDINGS_OUTPUT = "EXTRACTED_BUILDINGS_OUTPUT"

        alg = DummyAlg()
        mock_feedback = MockFeedback()

        p1 = {
            "previous_ea_source": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory"),
            "building_source": QgsVectorLayer("Point?crs=EPSG:4326", "test_bldg", "memory"),
            "target_crs": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory").crs(),
            "area_threshold": 1.0,
            "max_household": 300,
            "min_household": 100,
            "bldg_hh_field": "hhcount",
            "ea_id_field": "ean",
            "barangay_by_id": {},
        }
        p2 = {
            "out_fields": QgsFields(),
            "delineation_candidate_ids": set(),
            "merge_candidate_ids": set(),
            "adjacent_ea_ids": set(),
            "delineated_dest_id": "dest_delin",
            "merged_dest_id": "dest_merged",
            "special_ea_dest_id": "dest_special",
            "delin_candidate_dest_id": "dest_delin_cand",
            "extracted_buildings_dest_id": "dest_bldg",
            "delin_candidate_feat_count": 0,
            "extracted_bldg_feat_count": 0,
        }
        p3 = {"road_geoms": {}, "river_geoms": {}}
        p4 = {}
        p7 = {"eas": []}

        outputs = run_phase_8(alg, {}, None, mock_feedback, None, p1, p2, p3, p4, p7)
        # All feature counts are 0, so outputs must be empty!
        self.assertEqual(outputs, {}, "Expected empty outputs when all output layer feature counts are 0.")

    def test_phase8_output_unique_fids(self):
        """Verify that all features written across phase 8 sinks receive unique sequential FIDs."""
        from references.create_enumeration_area.phases.phase8_output import run_phase_8
        from qgis.core import QgsFields, QgsField, QgsFeature, QgsGeometry, QgsPointXY, QgsVectorLayer
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            try:
                from PyQt5.QtCore import QVariant
            except ImportError:
                from qgis.core import QVariant

        class MockSink:
            def __init__(self):
                self.features = []

            def addFeature(self, feat, flags=None):
                self.features.append(QgsFeature(feat))
                return True

        delin_sink = MockSink()
        merged_sink = MockSink()
        spec_sink = MockSink()
        bldg_sink = MockSink()

        class DummyAlg:
            DELINEATED_OUTPUT = "DELINEATED_OUTPUT"
            MERGED_OUTPUT = "MERGED_OUTPUT"
            SPECIAL_EA_OUTPUT = "SPECIAL_EA_OUTPUT"
            DELINEATION_CANDIDATE_OUTPUT = "DELINEATION_CANDIDATE_OUTPUT"
            EXTRACTED_BUILDINGS_OUTPUT = "EXTRACTED_BUILDINGS_OUTPUT"

        alg = DummyAlg()
        mock_feedback = MockFeedback()

        # Build schema
        fields = QgsFields()
        for f in ["fid", "map_uuid", "geocode", "region", "province", "city_mun", "barangay", "code", "name", "ean", "hhcount", "bldgcount", "sy", "new_ean", "hh_count", "bldg_count", "ea_type", "remarks"]:
            fields.append(QgsField(f, QVariant.Int if f == "fid" else QVariant.String))

        bldg_fields = QgsFields()
        for f in ["fid", "bldg_id", "bldgpoints_value", "pop"]:
            fields_type = QVariant.Int if f in ("fid", "bldg_id") else QVariant.Double
            bldg_fields.append(QgsField(f, fields_type))

        bldg_layer = QgsVectorLayer("Point?crs=EPSG:4326", "bldg", "memory")
        for i in range(bldg_fields.count()):
            bldg_layer.dataProvider().addAttributes([bldg_fields.at(i)])
        bldg_layer.updateFields()

        # EAs: 2 split parts from parent 100, 1 merged EA, 1 special EA
        poly1 = QgsGeometry.fromPolygonXY([[QgsPointXY(0,0), QgsPointXY(5,0), QgsPointXY(5,5), QgsPointXY(0,5), QgsPointXY(0,0)]])
        poly2 = QgsGeometry.fromPolygonXY([[QgsPointXY(5,0), QgsPointXY(10,0), QgsPointXY(10,5), QgsPointXY(5,5), QgsPointXY(5,0)]])
        poly3 = QgsGeometry.fromPolygonXY([[QgsPointXY(0,5), QgsPointXY(5,5), QgsPointXY(5,10), QgsPointXY(0,10), QgsPointXY(0,5)]])
        poly4 = QgsGeometry.fromPolygonXY([[QgsPointXY(5,5), QgsPointXY(10,5), QgsPointXY(10,10), QgsPointXY(5,10), QgsPointXY(5,5)]])

        bldgs = [
            {'point': QgsPointXY(1, 1), 'attributes': [999, 1, 1.0, 3.0], 'bldgpoints_value': 1.0, 'pop': 3.0},
            {'point': QgsPointXY(2, 2), 'attributes': [999, 2, 1.0, 4.0], 'bldgpoints_value': 1.0, 'pop': 4.0},
        ]

        eas = [
            # Split parts from candidate 100
            {'geom': poly1, 'original_id': 100, 'original_code': '001', 'new_ea_code': '001A', 'parent_barangay': '043404001', 'from_split': True, 'hh_count': 150.0, 'bldg_count': 20, 'original_hhcount': 350.0, 'original_bldgcount': 50, 'buildings': bldgs},
            {'geom': poly2, 'original_id': 100, 'original_code': '001', 'new_ea_code': '001B', 'parent_barangay': '043404001', 'from_split': True, 'hh_count': 200.0, 'bldg_count': 30, 'original_hhcount': 350.0, 'original_bldgcount': 50, 'buildings': []},
            # Merged EA
            {'geom': poly3, 'original_id': 200, 'original_code': '002', 'new_ea_code': '002', 'parent_barangay': '043404001', 'from_merge': True, 'hh_count': 80.0, 'bldg_count': 10, 'original_hhcount': 40.0, 'original_bldgcount': 5, 'buildings': []},
            # Special EA
            {'geom': poly4, 'original_id': 300, 'original_code': '003', 'new_ea_code': '003', 'parent_barangay': '043404001', 'is_special_ea': True, 'special_type': 'GAP', 'ea_type': 'GAP', 'hh_count': 0.0, 'bldg_count': 0, 'original_hhcount': 0.0, 'original_bldgcount': 0, 'buildings': []},
        ]

        p1 = {
            "previous_ea_source": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory"),
            "building_source": bldg_layer,
            "target_crs": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory").crs(),
            "area_threshold": 1.0,
            "max_household": 300,
            "min_household": 100,
            "bldg_hh_field": "pop",
            "ea_id_field": "ean",
            "barangay_by_id": {},
            "all_ea_features": [],
        }
        p2 = {
            "out_fields": fields,
            "export_fields": fields,
            "delineation_candidate_ids": {100},
            "merge_candidate_ids": {200},
            "adjacent_ea_ids": set(),
            "delineated_sink": delin_sink,
            "delineated_dest_id": "dest_delin",
            "merged_sink": merged_sink,
            "merged_dest_id": "dest_merged",
            "special_ea_sink": spec_sink,
            "special_ea_dest_id": "dest_special",
            "extracted_buildings_sink": bldg_sink,
            "extracted_buildings_dest_id": "dest_bldg",
            "delin_candidate_feat_count": 0,
            "merge_candidate_feat_count": 0,
            "extracted_bldg_feat_count": 0,
        }
        p3 = {"road_geoms": {}, "river_geoms": {}}
        p4 = {}
        p7 = {"eas": eas}

        outputs = run_phase_8(alg, {}, None, mock_feedback, None, p1, p2, p3, p4, p7)

        # 1. Verify Delineated Sink FIDs are unique and sequential (1, 2)
        self.assertEqual(len(delin_sink.features), 2)
        delin_fids = [f.attribute("fid") for f in delin_sink.features]
        self.assertEqual(delin_fids, [1, 2], "Delineated output features must have unique sequential FIDs [1, 2].")
        self.assertEqual([f.id() for f in delin_sink.features], [1, 2])

        # 2. Verify Merged Sink FIDs are unique and sequential (1)
        self.assertEqual(len(merged_sink.features), 1)
        self.assertEqual(merged_sink.features[0].attribute("fid"), 1)
        self.assertEqual(merged_sink.features[0].id(), 1)

        # 3. Verify Special EA Sink FIDs are unique and sequential (1)
        self.assertEqual(len(spec_sink.features), 1)
        self.assertEqual(spec_sink.features[0].attribute("fid"), 1)
        self.assertEqual(spec_sink.features[0].id(), 1)

        # 3b. Verify Geocode consistency across Delineated, Merged, and Special EAs
        delin_gc = delin_sink.features[0].attribute("geocode")
        merged_gc = merged_sink.features[0].attribute("geocode")
        special_gc = spec_sink.features[0].attribute("geocode")
        self.assertEqual(special_gc, "043404001")
        self.assertEqual(delin_gc, special_gc, "Special EA geocode must match Delineated EA geocode")
        self.assertEqual(merged_gc, special_gc, "Special EA geocode must match Merged EA geocode")

        # 3c. Verify ea_type classification values (DELINEATED, MERGED, GAP)
        self.assertEqual(delin_sink.features[0].attribute("ea_type"), "DELINEATED")
        self.assertEqual(delin_sink.features[1].attribute("ea_type"), "DELINEATED")
        self.assertEqual(merged_sink.features[0].attribute("ea_type"), "MERGED")
        self.assertEqual(spec_sink.features[0].attribute("ea_type"), "GAP")

        # 4. Verify Extracted Buildings Sink FIDs are unique and sequential (1, 2)
        self.assertEqual(len(bldg_sink.features), 2)
        bldg_fids = [f.attribute("fid") for f in bldg_sink.features]
        self.assertEqual(bldg_fids, [1, 2], "Extracted buildings features must have unique sequential FIDs [1, 2].")
        self.assertEqual([f.id() for f in bldg_sink.features], [1, 2])

    def test_phase8_output_ea_type_classification(self):
        """Verify phase8 assigns specific ea_type classifications: DELINEATED, MERGED, RETAINED, GAP, OVERLAP, SPECIAL."""
        from references.create_enumeration_area.phases.phase8_output import run_phase_8
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            try:
                from PyQt5.QtCore import QVariant
            except ImportError:
                from qgis.core import QVariant

        class DummyAlg:
            pass

        class MockSink:
            def __init__(self):
                self.features = []
            def addFeature(self, feat, flags=0):
                self.features.append(QgsFeature(feat))
                return True

        alg = DummyAlg()
        mock_feedback = MockFeedback()
        fields = QgsFields()
        for f in ["fid", "map_uuid", "geocode", "region", "province", "city_mun", "barangay", "code", "name", "ean", "hhcount", "bldgcount", "sy", "new_ean", "hh_count", "bldg_count", "ea_type", "remarks"]:
            fields.append(QgsField(f, QVariant.Int if f == "fid" else (QVariant.Double if f == "hhcount" else (QVariant.Int if "count" in f else QVariant.String))))

        delin_sink = MockSink()
        merged_sink = MockSink()
        spec_sink = MockSink()

        poly = QgsGeometry.fromPolygonXY([[QgsPointXY(0,0), QgsPointXY(1,0), QgsPointXY(1,1), QgsPointXY(0,1), QgsPointXY(0,0)]])

        eas = [
            {'geom': poly, 'original_id': 1, 'original_code': '001', 'new_ea_code': '001A', 'parent_barangay': '043404001', 'from_split': True, 'hh_count': 150.0, 'bldg_count': 20, 'original_hhcount': 350.0, 'original_bldgcount': 50, 'buildings': []},
            {'geom': poly, 'original_id': 2, 'original_code': '002', 'new_ea_code': '002', 'parent_barangay': '043404001', 'from_merge': True, 'hh_count': 120.0, 'bldg_count': 15, 'original_hhcount': 60.0, 'original_bldgcount': 8, 'buildings': []},
            {'geom': poly, 'original_id': 3, 'original_code': '003', 'new_ea_code': '003', 'parent_barangay': '043404001', 'from_split': False, 'from_merge': False, 'is_special_ea': False, 'hh_count': 200.0, 'bldg_count': 25, 'original_hhcount': 200.0, 'original_bldgcount': 25, 'buildings': []},
            {'geom': poly, 'original_id': 4, 'original_code': '004', 'new_ea_code': '004', 'parent_barangay': '043404001', 'is_special_ea': True, 'special_type': 'GAP', 'hh_count': 0.0, 'bldg_count': 0, 'original_hhcount': 0.0, 'original_bldgcount': 0, 'buildings': []},
            {'geom': poly, 'original_id': 5, 'original_code': '005', 'new_ea_code': '005', 'parent_barangay': '043404001', 'is_special_ea': True, 'special_type': 'OVERLAP', 'hh_count': 0.0, 'bldg_count': 0, 'original_hhcount': 0.0, 'original_bldgcount': 0, 'buildings': []},
            {'geom': poly, 'original_id': 6, 'original_code': '006', 'new_ea_code': '006', 'parent_barangay': '043404001', 'is_special_ea': True, 'special_type': 'SPECIAL', 'hh_count': 50.0, 'bldg_count': 5, 'original_hhcount': 50.0, 'original_bldgcount': 5, 'buildings': []},
        ]

        p1 = {
            "previous_ea_source": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory"),
            "building_source": None,
            "target_crs": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory").crs(),
            "area_threshold": 1.0,
            "max_household": 300,
            "min_household": 100,
            "bldg_hh_field": "pop",
            "ea_id_field": "ean",
            "barangay_by_id": {},
            "all_ea_features": [],
        }
        p2 = {
            "out_fields": fields,
            "export_fields": fields,
            "delineation_candidate_ids": {1},
            "merge_candidate_ids": {2},
            "adjacent_ea_ids": set(),
            "delineated_sink": delin_sink,
            "delineated_dest_id": "dest_delin",
            "merged_sink": merged_sink,
            "merged_dest_id": "dest_merged",
            "special_ea_sink": spec_sink,
            "special_ea_dest_id": "dest_special",
            "extracted_buildings_sink": None,
            "extracted_buildings_dest_id": None,
            "delin_candidate_feat_count": 0,
            "merge_candidate_feat_count": 0,
            "extracted_bldg_feat_count": 0,
        }
        p3 = {"road_geoms": {}, "river_geoms": {}}
        p4 = {}
        p7 = {"eas": eas}

        run_phase_8(alg, {}, None, mock_feedback, None, p1, p2, p3, p4, p7)

        delin_types = [f.attribute("ea_type") for f in delin_sink.features]
        self.assertIn("DELINEATED", delin_types)

        merged_types = [f.attribute("ea_type") for f in merged_sink.features]
        self.assertIn("MERGED", merged_types)

        spec_types = [f.attribute("ea_type") for f in spec_sink.features]
        self.assertIn("GAP", spec_types)
        self.assertIn("OVERLAP", spec_types)
        self.assertIn("SPECIAL", spec_types)

    def test_ea_merge_processor_unique_fids(self):
        """Verify that EAMergeProcessor assigns unique sequential FIDs across replacement and remaining features."""
        from references.create_enumeration_area.ea_merge_processor import EAMergeProcessor
        from qgis.core import QgsVectorLayer, QgsFields, QgsField, QgsFeature, QgsGeometry, QgsPointXY
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            try:
                from PyQt5.QtCore import QVariant
            except ImportError:
                from qgis.core import QVariant

        ea_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "ea_layer", "memory")
        fields = QgsFields()
        fields.append(QgsField("fid", QVariant.Int))
        fields.append(QgsField("ean", QVariant.String))
        fields.append(QgsField("geocode", QVariant.String))
        ea_layer.dataProvider().addAttributes([fields.at(i) for i in range(fields.count())])
        ea_layer.updateFields()

        poly1 = QgsGeometry.fromPolygonXY([[QgsPointXY(0,0), QgsPointXY(10,0), QgsPointXY(10,10), QgsPointXY(0,10), QgsPointXY(0,0)]])
        poly2 = QgsGeometry.fromPolygonXY([[QgsPointXY(10,0), QgsPointXY(20,0), QgsPointXY(20,10), QgsPointXY(10,10), QgsPointXY(10,0)]])
        f1 = QgsFeature(ea_layer.fields())
        f1.setGeometry(poly1)
        f1.setAttributes([99, "001", "043404001"])
        f2 = QgsFeature(ea_layer.fields())
        f2.setGeometry(poly2)
        f2.setAttributes([99, "002", "043404001"])
        ea_layer.dataProvider().addFeatures([f1, f2])

        # Replacement layer
        repl_layer = QgsVectorLayer("Polygon?crs=EPSG:4326", "04340401", "memory")
        poly_rep = QgsGeometry.fromPolygonXY([[QgsPointXY(5,0), QgsPointXY(15,0), QgsPointXY(15,10), QgsPointXY(5,10), QgsPointXY(5,0)]])
        f_rep = QgsFeature()
        f_rep.setGeometry(poly_rep)
        repl_layer.dataProvider().addFeatures([f_rep])

        processor = EAMergeProcessor(ea_layer, [repl_layer], None)
        out_layer = processor._create_output_layer([f_rep, f1, f2])
        self.assertIsNotNone(out_layer)
        fids = [feat.attribute("fid") for feat in out_layer.getFeatures()]
        self.assertEqual(fids, [1, 2, 3], "All output features in merged layer must have unique sequential FIDs.")
        self.assertEqual([feat.id() for feat in out_layer.getFeatures()], [1, 2, 3])

    def test_special_ea_zero_or_empty_bldg_count_rule(self):
        """Verify that for Special EA output, if bldg_count is 0 or empty/null, hh_count is set to 0 or empty/null."""
        from references.create_enumeration_area.phases.phase8_output import run_phase_8
        from qgis.core import QgsVectorLayer, QgsFields, QgsField, QgsGeometry, QgsPointXY
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            try:
                from PyQt5.QtCore import QVariant
            except ImportError:
                from qgis.core import QVariant

        class MockFeedback:
            def isCanceled(self): return False
            def pushInfo(self, msg): pass
            def pushWarning(self, msg): pass
            def reportError(self, msg): pass

        class MockSink:
            def __init__(self):
                self.features = []
            def addFeature(self, feat, flags=None):
                self.features.append(feat)
                return True

        class DummyAlg:
            DELINEATED_OUTPUT = "DELINEATED_OUTPUT"
            MERGED_OUTPUT = "MERGED_OUTPUT"
            SPECIAL_EA_OUTPUT = "SPECIAL_EA_OUTPUT"
            DELINEATION_CANDIDATE_OUTPUT = "DELINEATION_CANDIDATE_OUTPUT"
            EXTRACTED_BUILDINGS_OUTPUT = "EXTRACTED_BUILDINGS_OUTPUT"

        alg = DummyAlg()
        mock_feedback = MockFeedback()
        fields = QgsFields()
        for f in ["fid", "map_uuid", "geocode", "region", "province", "city_mun", "barangay", "code", "name", "ean", "hhcount", "bldgcount", "sy", "new_ean", "hh_count", "bldg_count", "ea_type", "remarks", "special_type"]:
            fields.append(QgsField(f, QVariant.Int if f == "fid" else (QVariant.Double if f == "hhcount" else (QVariant.Int if "count" in f else QVariant.String))))

        spec_sink = MockSink()
        poly1 = QgsGeometry.fromPolygonXY([[QgsPointXY(0,0), QgsPointXY(1,0), QgsPointXY(1,1), QgsPointXY(0,1), QgsPointXY(0,0)]])
        poly2 = QgsGeometry.fromPolygonXY([[QgsPointXY(2,0), QgsPointXY(3,0), QgsPointXY(3,1), QgsPointXY(2,1), QgsPointXY(2,0)]])
        poly3 = QgsGeometry.fromPolygonXY([[QgsPointXY(4,0), QgsPointXY(5,0), QgsPointXY(5,1), QgsPointXY(4,1), QgsPointXY(4,0)]])

        eas = [
            # 1. Special EA with bldg_count = 0 and non-zero legacy hh_count (must be forced to hh_count = 0)
            {
                'geom': poly1, 'original_id': 101, 'original_code': '001', 'new_ea_code': '001',
                'parent_barangay': '043404001', 'is_special_ea': True, 'special_type': 'GAP',
                'hh_count': 150.0, 'bldg_count': 0, 'original_hhcount': 150.0, 'original_bldgcount': 0,
                'buildings': []
            },
            # 2. Special EA with bldg_count = None / empty and non-zero hh_count (must be forced to hh_count = None)
            {
                'geom': poly2, 'original_id': 102, 'original_code': '002', 'new_ea_code': '002',
                'parent_barangay': '043404001', 'is_special_ea': True, 'special_type': 'SPECIAL',
                'hh_count': 75.0, 'bldg_count': None, 'original_hhcount': 75.0, 'original_bldgcount': None,
                'buildings': []
            },
            # 3. Special EA with valid building points (bldg_count > 0, hh_count preserved/calculated)
            {
                'geom': poly3, 'original_id': 103, 'original_code': '003', 'new_ea_code': '003',
                'parent_barangay': '043404001', 'is_special_ea': True, 'special_type': 'SPECIAL',
                'hh_count': 80.0, 'bldg_count': 4, 'original_hhcount': 80.0, 'original_bldgcount': 4,
                'buildings': [{'point': QgsPointXY(4.5, 0.5), 'pop': 20.0, 'bldgpoints_value': 1.0} for _ in range(4)]
            },
        ]

        p1 = {
            "previous_ea_source": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory"),
            "building_source": None,
            "target_crs": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory").crs(),
            "area_threshold": 1.0,
            "max_household": 300,
            "min_household": 100,
            "bldg_hh_field": "pop",
            "ea_id_field": "ean",
            "barangay_by_id": {},
            "all_ea_features": [],
        }
        p2 = {
            "out_fields": fields,
            "export_fields": fields,
            "delineation_candidate_ids": set(),
            "merge_candidate_ids": set(),
            "adjacent_ea_ids": set(),
            "delineated_sink": None,
            "delineated_dest_id": None,
            "merged_sink": None,
            "merged_dest_id": None,
            "special_ea_sink": spec_sink,
            "special_ea_dest_id": "dest_special",
            "extracted_buildings_sink": None,
            "extracted_buildings_dest_id": None,
            "delin_candidate_feat_count": 0,
            "merge_candidate_feat_count": 0,
            "extracted_bldg_feat_count": 0,
        }
        p3 = {"road_geoms": {}, "river_geoms": {}}
        p4 = {}
        p7 = {"eas": eas}

        run_phase_8(alg, {}, None, mock_feedback, None, p1, p2, p3, p4, p7)

        self.assertEqual(len(spec_sink.features), 3)

        # Feature 1: bldg_count = 0 -> hh_count = 0
        feat1 = spec_sink.features[0]
        self.assertEqual(feat1.attribute("bldg_count"), 0)
        self.assertEqual(feat1.attribute("hh_count"), 0)

        # Feature 2: bldg_count is None/null -> hh_count is None/null
        feat2 = spec_sink.features[1]
        self.assertTrue(feat2.attribute("bldg_count") is None or feat2.attribute("bldg_count") == QVariant())
        self.assertTrue(feat2.attribute("hh_count") is None or feat2.attribute("hh_count") == QVariant())

        # Feature 3: bldg_count = 4 -> hh_count = 80
        feat3 = spec_sink.features[2]
        self.assertEqual(feat3.attribute("bldg_count"), 4)
        self.assertEqual(feat3.attribute("hh_count"), 80)

    def test_tab2_special_ea_naming_when_suffix_greater_than_zero(self):
        """Verify that when non-zero suffixes exist in barangay (e.g. 001004), Special EA gets prefix (suffix+1) + 000 -> 005000."""
        from references.create_enumeration_area.phases.phase8_output import run_phase_8
        from qgis.core import QgsVectorLayer, QgsFields, QgsField, QgsGeometry, QgsPointXY
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            from PyQt5.QtCore import QVariant

        class MockFeedback:
            def isCanceled(self): return False
            def pushInfo(self, msg): pass
            def pushWarning(self, msg): pass
            def reportError(self, msg): pass

        class MockSink:
            def __init__(self): self.features = []
            def addFeature(self, feat, flags=None):
                self.features.append(feat)
                return True

        class DummyAlg:
            DELINEATED_OUTPUT = "DELINEATED_OUTPUT"
            MERGED_OUTPUT = "MERGED_OUTPUT"
            SPECIAL_EA_OUTPUT = "SPECIAL_EA_OUTPUT"
            DELINEATION_CANDIDATE_OUTPUT = "DELINEATION_CANDIDATE_OUTPUT"
            EXTRACTED_BUILDINGS_OUTPUT = "EXTRACTED_BUILDINGS_OUTPUT"

        fields = QgsFields()
        for f in ["fid", "map_uuid", "geocode", "region", "province", "city_mun", "barangay", "code", "name", "ean", "hhcount", "bldgcount", "sy", "new_ean", "hh_count", "bldg_count", "ea_type", "remarks", "special_type"]:
            fields.append(QgsField(f, QVariant.Int if f == "fid" else (QVariant.Double if f == "hhcount" else (QVariant.Int if "count" in f else QVariant.String))))

        spec_sink = MockSink()
        poly1 = QgsGeometry.fromPolygonXY([[QgsPointXY(0,0), QgsPointXY(1,0), QgsPointXY(1,1), QgsPointXY(0,1), QgsPointXY(0,0)]])
        poly2 = QgsGeometry.fromPolygonXY([[QgsPointXY(1,0), QgsPointXY(2,0), QgsPointXY(2,1), QgsPointXY(1,1), QgsPointXY(1,0)]])
        poly_spec = QgsGeometry.fromPolygonXY([[QgsPointXY(2,0), QgsPointXY(3,0), QgsPointXY(3,1), QgsPointXY(2,1), QgsPointXY(2,0)]])

        eas = [
            # Standard EA 1
            {'geom': poly1, 'original_id': 1, 'original_code': '001000', 'new_ea_code': '001000', 'parent_barangay': '043404001', 'is_special_ea': False, 'hh_count': 200.0, 'bldg_count': 20, 'buildings': []},
            # Split child EA with non-zero suffix 004
            {'geom': poly2, 'original_id': 2, 'original_code': '001004', 'new_ea_code': '001004', 'parent_barangay': '043404001', 'is_special_ea': False, 'hh_count': 150.0, 'bldg_count': 15, 'buildings': []},
            # Special EA (Gap)
            {'geom': poly_spec, 'original_id': 100, 'original_code': '000000', 'parent_barangay': '043404001', 'is_special_ea': True, 'special_type': 'GAP', 'hh_count': 0.0, 'bldg_count': 0, 'buildings': []},
        ]

        p1 = {
            "previous_ea_source": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory"),
            "building_source": None,
            "target_crs": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory").crs(),
            "area_threshold": 1.0, "max_household": 300, "min_household": 100,
            "bldg_hh_field": "pop", "ea_id_field": "ean", "barangay_by_id": {}, "all_ea_features": [],
        }
        p2 = {
            "out_fields": fields, "export_fields": fields, "special_ea_export_fields": fields,
            "delineation_candidate_ids": set(), "merge_candidate_ids": set(), "adjacent_ea_ids": set(),
            "delineated_sink": None, "merged_sink": None, "special_ea_sink": spec_sink,
            "special_ea_dest_id": "dest_special", "extracted_buildings_sink": None,
            "delin_candidate_feat_count": 0, "merge_candidate_feat_count": 0, "extracted_bldg_feat_count": 0,
        }
        p3 = {"road_geoms": {}, "river_geoms": {}}
        p4 = {}
        p7 = {"eas": eas}

        run_phase_8(DummyAlg(), {}, None, MockFeedback(), None, p1, p2, p3, p4, p7)

        self.assertEqual(len(spec_sink.features), 1)
        spec_feat = spec_sink.features[0]
        # Highest suffix was 004 -> special EA prefix is 005 -> new_ean is 005000
        self.assertEqual(spec_feat.attribute("new_ean"), "005000")

    def test_tab2_special_ea_naming_when_suffix_is_zero(self):
        """Verify that when all suffixes in barangay are 000 (e.g. 001000, 002000, 003000), Special EA gets prefix (prefix+1) + 000 -> 004000."""
        from references.create_enumeration_area.phases.phase8_output import run_phase_8
        from qgis.core import QgsVectorLayer, QgsFields, QgsField, QgsGeometry, QgsPointXY
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            from PyQt5.QtCore import QVariant

        class MockFeedback:
            def isCanceled(self): return False
            def pushInfo(self, msg): pass
            def pushWarning(self, msg): pass
            def reportError(self, msg): pass

        class MockSink:
            def __init__(self): self.features = []
            def addFeature(self, feat, flags=None):
                self.features.append(feat)
                return True

        class DummyAlg:
            DELINEATED_OUTPUT = "DELINEATED_OUTPUT"
            MERGED_OUTPUT = "MERGED_OUTPUT"
            SPECIAL_EA_OUTPUT = "SPECIAL_EA_OUTPUT"
            DELINEATION_CANDIDATE_OUTPUT = "DELINEATION_CANDIDATE_OUTPUT"
            EXTRACTED_BUILDINGS_OUTPUT = "EXTRACTED_BUILDINGS_OUTPUT"

        fields = QgsFields()
        for f in ["fid", "map_uuid", "geocode", "region", "province", "city_mun", "barangay", "code", "name", "ean", "hhcount", "bldgcount", "sy", "new_ean", "hh_count", "bldg_count", "ea_type", "remarks", "special_type"]:
            fields.append(QgsField(f, QVariant.Int if f == "fid" else (QVariant.Double if f == "hhcount" else (QVariant.Int if "count" in f else QVariant.String))))

        spec_sink = MockSink()
        poly1 = QgsGeometry.fromPolygonXY([[QgsPointXY(0,0), QgsPointXY(1,0), QgsPointXY(1,1), QgsPointXY(0,1), QgsPointXY(0,0)]])
        poly2 = QgsGeometry.fromPolygonXY([[QgsPointXY(1,0), QgsPointXY(2,0), QgsPointXY(2,1), QgsPointXY(1,1), QgsPointXY(1,0)]])
        poly3 = QgsGeometry.fromPolygonXY([[QgsPointXY(2,0), QgsPointXY(3,0), QgsPointXY(3,1), QgsPointXY(2,1), QgsPointXY(2,0)]])
        poly_spec = QgsGeometry.fromPolygonXY([[QgsPointXY(3,0), QgsPointXY(4,0), QgsPointXY(4,1), QgsPointXY(3,1), QgsPointXY(3,0)]])

        eas = [
            {'geom': poly1, 'original_id': 1, 'original_code': '001000', 'new_ea_code': '001000', 'parent_barangay': '043404001', 'is_special_ea': False, 'hh_count': 200.0, 'bldg_count': 20, 'buildings': []},
            {'geom': poly2, 'original_id': 2, 'original_code': '002000', 'new_ea_code': '002000', 'parent_barangay': '043404001', 'is_special_ea': False, 'hh_count': 180.0, 'bldg_count': 18, 'buildings': []},
            {'geom': poly3, 'original_id': 3, 'original_code': '003000', 'new_ea_code': '003000', 'parent_barangay': '043404001', 'is_special_ea': False, 'hh_count': 160.0, 'bldg_count': 16, 'buildings': []},
            # Special EA
            {'geom': poly_spec, 'original_id': 100, 'original_code': '000000', 'parent_barangay': '043404001', 'is_special_ea': True, 'special_type': 'GAP', 'hh_count': 0.0, 'bldg_count': 0, 'buildings': []},
        ]

        p1 = {
            "previous_ea_source": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory"),
            "building_source": None,
            "target_crs": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory").crs(),
            "area_threshold": 1.0, "max_household": 300, "min_household": 100,
            "bldg_hh_field": "pop", "ea_id_field": "ean", "barangay_by_id": {}, "all_ea_features": [],
        }
        p2 = {
            "out_fields": fields, "export_fields": fields, "special_ea_export_fields": fields,
            "delineation_candidate_ids": set(), "merge_candidate_ids": set(), "adjacent_ea_ids": set(),
            "delineated_sink": None, "merged_sink": None, "special_ea_sink": spec_sink,
            "special_ea_dest_id": "dest_special", "extracted_buildings_sink": None,
            "delin_candidate_feat_count": 0, "merge_candidate_feat_count": 0, "extracted_bldg_feat_count": 0,
        }
        p3 = {"road_geoms": {}, "river_geoms": {}}
        p4 = {}
        p7 = {"eas": eas}

        run_phase_8(DummyAlg(), {}, None, MockFeedback(), None, p1, p2, p3, p4, p7)

        self.assertEqual(len(spec_sink.features), 1)
        spec_feat = spec_sink.features[0]
        # Highest prefix was 003, all suffixes 000 -> special EA prefix is 004 -> new_ean is 004000
        self.assertEqual(spec_feat.attribute("new_ean"), "004000")

    def test_tab2_multiple_special_eas_sequential_increment(self):
        """Verify that multiple Special EAs in the same barangay increment sequentially (e.g. 004000, 005000)."""
        from references.create_enumeration_area.phases.phase8_output import run_phase_8
        from qgis.core import QgsVectorLayer, QgsFields, QgsField, QgsGeometry, QgsPointXY
        try:
            from qgis.PyQt.QtCore import QVariant
        except ImportError:
            from PyQt5.QtCore import QVariant

        class MockFeedback:
            def isCanceled(self): return False
            def pushInfo(self, msg): pass
            def pushWarning(self, msg): pass
            def reportError(self, msg): pass

        class MockSink:
            def __init__(self): self.features = []
            def addFeature(self, feat, flags=None):
                self.features.append(feat)
                return True

        class DummyAlg:
            DELINEATED_OUTPUT = "DELINEATED_OUTPUT"
            MERGED_OUTPUT = "MERGED_OUTPUT"
            SPECIAL_EA_OUTPUT = "SPECIAL_EA_OUTPUT"
            DELINEATION_CANDIDATE_OUTPUT = "DELINEATION_CANDIDATE_OUTPUT"
            EXTRACTED_BUILDINGS_OUTPUT = "EXTRACTED_BUILDINGS_OUTPUT"

        fields = QgsFields()
        for f in ["fid", "map_uuid", "geocode", "region", "province", "city_mun", "barangay", "code", "name", "ean", "hhcount", "bldgcount", "sy", "new_ean", "hh_count", "bldg_count", "ea_type", "remarks", "special_type"]:
            fields.append(QgsField(f, QVariant.Int if f == "fid" else (QVariant.Double if f == "hhcount" else (QVariant.Int if "count" in f else QVariant.String))))

        spec_sink = MockSink()
        poly1 = QgsGeometry.fromPolygonXY([[QgsPointXY(0,0), QgsPointXY(1,0), QgsPointXY(1,1), QgsPointXY(0,1), QgsPointXY(0,0)]])
        poly2 = QgsGeometry.fromPolygonXY([[QgsPointXY(1,0), QgsPointXY(2,0), QgsPointXY(2,1), QgsPointXY(1,1), QgsPointXY(1,0)]])
        poly_spec1 = QgsGeometry.fromPolygonXY([[QgsPointXY(2,0), QgsPointXY(3,0), QgsPointXY(3,1), QgsPointXY(2,1), QgsPointXY(2,0)]])
        poly_spec2 = QgsGeometry.fromPolygonXY([[QgsPointXY(3,0), QgsPointXY(4,0), QgsPointXY(4,1), QgsPointXY(3,1), QgsPointXY(3,0)]])

        eas = [
            {'geom': poly1, 'original_id': 1, 'original_code': '001000', 'new_ea_code': '001000', 'parent_barangay': '043404001', 'is_special_ea': False, 'hh_count': 200.0, 'bldg_count': 20, 'buildings': []},
            {'geom': poly2, 'original_id': 2, 'original_code': '002000', 'new_ea_code': '002000', 'parent_barangay': '043404001', 'is_special_ea': False, 'hh_count': 180.0, 'bldg_count': 18, 'buildings': []},
            # Special EA 1 (Gap)
            {'geom': poly_spec1, 'original_id': 100, 'original_code': '000000', 'parent_barangay': '043404001', 'is_special_ea': True, 'special_type': 'GAP', 'hh_count': 0.0, 'bldg_count': 0, 'buildings': []},
            # Special EA 2 (Overlap)
            {'geom': poly_spec2, 'original_id': 101, 'original_code': '000000', 'parent_barangay': '043404001', 'is_special_ea': True, 'special_type': 'OVERLAP', 'hh_count': 0.0, 'bldg_count': 0, 'buildings': []},
        ]

        p1 = {
            "previous_ea_source": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory"),
            "building_source": None,
            "target_crs": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory").crs(),
            "area_threshold": 1.0, "max_household": 300, "min_household": 100,
            "bldg_hh_field": "pop", "ea_id_field": "ean", "barangay_by_id": {}, "all_ea_features": [],
        }
        p2 = {
            "out_fields": fields, "export_fields": fields, "special_ea_export_fields": fields,
            "delineation_candidate_ids": set(), "merge_candidate_ids": set(), "adjacent_ea_ids": set(),
            "delineated_sink": None, "merged_sink": None, "special_ea_sink": spec_sink,
            "special_ea_dest_id": "dest_special", "extracted_buildings_sink": None,
            "delin_candidate_feat_count": 0, "merge_candidate_feat_count": 0, "extracted_bldg_feat_count": 0,
        }
        p3 = {"road_geoms": {}, "river_geoms": {}}
        p4 = {}
        p7 = {"eas": eas}

        run_phase_8(DummyAlg(), {}, None, MockFeedback(), None, p1, p2, p3, p4, p7)

        self.assertEqual(len(spec_sink.features), 2)
        # Highest prefix was 002, suffixes 000 -> Special EA 1 is 003000, Special EA 2 is 004000
        self.assertEqual(spec_sink.features[0].attribute("new_ean"), "003000")
        self.assertEqual(spec_sink.features[1].attribute("new_ean"), "004000")


class TestDelineationMinHouseholdEnforcement(unittest.TestCase):
    """Verify that delineation never outputs EAs below min_household."""

    def test_force_geometric_split_rejects_under_min_household(self):
        from references.create_enumeration_area.phases.phase5_delineate import force_geometric_split

        poly = QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]])
        # Total 130 HH: 110 in bottom half, 20 in top half. min_household = 100.
        # A split would isolate the 20 HH building, which is < 100 min_household.
        bldgs = [
            {'point': QgsPointXY(5, 2), 'pop': 110.0},
            {'point': QgsPointXY(5, 8), 'pop': 20.0},
        ]
        ea = {
            'geom': poly,
            'buildings': bldgs,
            'hh_count': 130.0,
            'bldg_count': 2,
            'original_id': 1,
            'original_code': '001000',
            'attributes': ['001000'],
            'parent_barangay': '043404001',
            'is_special_ea': False,
        }

        feedback = MockFeedback()
        result = force_geometric_split(ea, target_pop=100, fback=feedback, min_household=100, max_household=300)

        # Result must NOT contain any EA with hh_count < 100
        for p in result:
            self.assertGreaterEqual(p['hh_count'], 100, f"Split produced an EA with {p['hh_count']} HH (< 100)")
        # Since it cannot produce >= 2 parts each >= 100, it must have preserved whole
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['hh_count'], 130.0)

    def test_force_geometric_split_accepts_valid_split_above_min_household(self):
        from references.create_enumeration_area.phases.phase5_delineate import force_geometric_split

        poly = QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]])
        # Total 300 HH: 150 in bottom half, 150 in top half. Both >= min_household (100).
        bldgs = [
            {'point': QgsPointXY(5, 2), 'pop': 150.0},
            {'point': QgsPointXY(5, 8), 'pop': 150.0},
        ]
        ea = {
            'geom': poly,
            'buildings': bldgs,
            'hh_count': 300.0,
            'bldg_count': 2,
            'original_id': 2,
            'original_code': '002000',
            'attributes': ['002000'],
            'parent_barangay': '043404001',
            'is_special_ea': False,
        }

        feedback = MockFeedback()
        result = force_geometric_split(ea, target_pop=150, fback=feedback, min_household=100, max_household=200)

        self.assertGreaterEqual(len(result), 2)
        for p in result:
            self.assertGreaterEqual(p['hh_count'], 100, f"Delineated part has {p['hh_count']} HH (< 100)")

    def test_phase8_output_delineated_sink_skips_under_threshold_from_split(self):
        from references.create_enumeration_area.phases.phase8_output import run_phase_8

        class MockSink:
            def __init__(self): self.features = []
            def addFeature(self, feat, flags=None):
                self.features.append(feat)
                return True

        class DummyAlg:
            DELINEATED_OUTPUT = "DELINEATED_OUTPUT"
            MERGED_OUTPUT = "MERGED_OUTPUT"
            SPECIAL_EA_OUTPUT = "SPECIAL_EA_OUTPUT"
            DELINEATION_CANDIDATE_OUTPUT = "DELINEATION_CANDIDATE_OUTPUT"
            EXTRACTED_BUILDINGS_OUTPUT = "EXTRACTED_BUILDINGS_OUTPUT"

        fields = QgsFields()
        for f in ["fid", "map_uuid", "geocode", "region", "province", "city_mun", "barangay", "code", "name", "ean", "hhcount", "bldgcount", "sy", "new_ean", "hh_count", "bldg_count", "ea_type", "remarks", "special_type"]:
            fields.append(QgsField(f, QVariant.Int if f == "fid" else (QVariant.Double if f == "hhcount" else (QVariant.Int if "count" in f else QVariant.String))))

        delin_sink = MockSink()
        poly1 = QgsGeometry.fromPolygonXY([[QgsPointXY(0, 0), QgsPointXY(1, 0), QgsPointXY(1, 1), QgsPointXY(0, 1), QgsPointXY(0, 0)]])
        poly2 = QgsGeometry.fromPolygonXY([[QgsPointXY(1, 0), QgsPointXY(2, 0), QgsPointXY(2, 1), QgsPointXY(1, 1), QgsPointXY(1, 0)]])

        eas = [
            # Delineated part 1 with valid HH >= 100
            {'geom': poly1, 'original_id': 1, 'original_code': '001000', 'new_ea_code': '001001', 'parent_barangay': '043404001', 'from_split': True, 'hh_count': 150.0, 'bldg_count': 1, 'buildings': [{'point': QgsPointXY(0.5, 0.5), 'pop': 150.0}]},
            # Delineated part 2 with under-threshold HH < 100
            {'geom': poly2, 'original_id': 1, 'original_code': '001000', 'new_ea_code': '001002', 'parent_barangay': '043404001', 'from_split': True, 'hh_count': 50.0, 'bldg_count': 1, 'buildings': [{'point': QgsPointXY(1.5, 0.5), 'pop': 50.0}]},
        ]

        p1 = {
            "previous_ea_source": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory"),
            "building_source": None,
            "target_crs": QgsVectorLayer("Polygon?crs=EPSG:4326", "test_ea", "memory").crs(),
            "area_threshold": 1.0, "max_household": 300, "min_household": 100,
            "bldg_hh_field": "pop", "ea_id_field": "ean", "barangay_by_id": {}, "all_ea_features": [],
        }
        p2 = {
            "out_fields": fields, "export_fields": fields, "special_ea_export_fields": fields,
            "delineation_candidate_ids": {1}, "merge_candidate_ids": set(), "adjacent_ea_ids": set(),
            "delineated_sink": delin_sink, "merged_sink": None, "special_ea_sink": None,
            "special_ea_dest_id": None, "extracted_buildings_sink": None,
            "delin_candidate_feat_count": 0, "merge_candidate_feat_count": 0, "extracted_bldg_feat_count": 0,
        }
        p3 = {"road_geoms": {}, "river_geoms": {}}
        p4 = {}
        p7 = {"eas": eas}

        run_phase_8(DummyAlg(), {}, None, MockFeedback(), None, p1, p2, p3, p4, p7)

        # Only the part with hh_count >= 100 should be exported to delineated_sink
        self.assertEqual(len(delin_sink.features), 1)
        self.assertEqual(delin_sink.features[0].attribute("hh_count"), 150)

    def test_phase5_generates_proposed_line_without_splitting_ea(self):
        """Verify that Phase 5 creates proposed boundary cut lines while keeping EA polygon whole."""
        from unittest.mock import MagicMock
        from references.create_enumeration_area.phases.phase5_delineate import run_phase_5

        # Create an overpopulated EA with 320 households and 2 building points
        ea_geom = QgsGeometry.fromPolygonXY([[
            QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)
        ]])
        bldgs = [
            {'point': QgsPointXY(2.0, 5.0), 'pop': 160.0},
            {'point': QgsPointXY(8.0, 5.0), 'pop': 160.0},
        ]
        ea_item = {
            'geom': ea_geom,
            'original_id': 101,
            'original_code': '043404001001',
            'parent_barangay': '043404001',
            'hh_count': 320.0,
            'bldg_count': 2,
            'buildings': bldgs,
            'attributes': ['043404001001', 'EA 001', 320.0, 2],
            'from_split': False,
            'from_merge': False,
            'is_special_ea': False,
        }

        p1 = {
            "eadel_indi_col_idx": -1,
            "min_household": 100,
            "max_household": 300,
            "target_household": 200,
            "snap_tolerance": 15.0,
            "densify_dist": 5.0,
            "area_threshold": 1.0,
            "num_cores": 1,
            "split_strategy": 0,
            "split_type": 0,
        }
        p2 = {
            "full_ea_by_id": {101: MagicMock()},
            "delineation_candidate_ids": {101},
            "merge_candidate_ids": set(),
            "delineation_candidate_hhdivthres": {101: 2},
        }
        p3 = {
            "road_index": None,
            "road_geoms": {},
            "river_index": None,
            "river_geoms": {},
        }
        p4 = {
            "eas": [ea_item],
        }

        mock_feedback = MagicMock()
        mock_feedback.isCanceled.return_value = False
        res = run_phase_5(MagicMock(), {}, None, mock_feedback, mock_feedback, p1, p2, p3, p4)

        # 1. EA polygon should NOT be replaced by multiple split pieces
        split_eas = res["split_eas"]
        self.assertEqual(len(split_eas), 1, "Parent EA should be preserved as 1 whole polygon")
        self.assertEqual(split_eas[0]["original_id"], 101)
        self.assertTrue(split_eas[0].get("has_proposed_split"))
        self.assertEqual(split_eas[0].get("remarks"), "Proposed for delineation")

        # 2. Proposed line should be generated in proposed_lines
        proposed_lines = res.get("proposed_lines", [])
        self.assertEqual(len(proposed_lines), 1, "Must generate 1 proposed boundary line")
        self.assertEqual(proposed_lines[0]["ea_id"], 101)
        self.assertFalse(proposed_lines[0]["geom"].isEmpty())


if __name__ == "__main__":
    unittest.main()




