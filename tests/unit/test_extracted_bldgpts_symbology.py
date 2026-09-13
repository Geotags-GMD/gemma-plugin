# -*- coding: utf-8 -*-
"""
Unit test module for extracted building points QML symbology (extracted_bldgpts.qml).
Verifies file existence, QGIS style path resolution, color palette isolation (brown vs yellow),
and correct style file mapping across the Create Enumeration Area dialog, processing algorithm,
and auto-arrange subsystem.
"""

import os
import unittest
import xml.etree.ElementTree as ET
from tests.mocks.qgis_mock import setup_qgis_mock_if_needed

setup_qgis_mock_if_needed()


class TestExtractedBldgptsSymbology(unittest.TestCase):
    """Test suite for extracted building points symbology styling."""

    def test_qml_file_exists_and_resolves(self):
        """Verify extracted_bldgpts.qml exists in 'qml styles' and resolves via get_qml_file_path."""
        from references.create_enumeration_area.helpers.style import get_qml_file_path

        resolved_path = get_qml_file_path("extracted_bldgpts.qml")
        self.assertTrue(resolved_path, "get_qml_file_path should find extracted_bldgpts.qml")
        self.assertTrue(os.path.isfile(resolved_path), f"File {resolved_path} must exist on disk")

        # Test resolution without .qml extension
        resolved_no_ext = get_qml_file_path("extracted_bldgpts")
        self.assertEqual(resolved_path, resolved_no_ext)

    def test_qml_symbology_colors_and_rules(self):
        """Verify extracted_bldgpts.qml uses brown symbology without yellow conflicts."""
        from references.create_enumeration_area.helpers.style import get_qml_file_path

        qml_path = get_qml_file_path("extracted_bldgpts.qml")
        with open(qml_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Must not contain bright yellow symbol colors that conflict with QGIS feature selection
        self.assertNotIn("251,255,0,255", content, "extracted_bldgpts.qml must not use yellow symbology color")

        # Must contain brown symbol color (145,82,45,255)
        self.assertIn("145,82,45,255", content, "extracted_bldgpts.qml must use brown symbology color")

        # Parse XML structure to verify RuleRenderer rules and symbols
        tree = ET.fromstring(content)
        renderer = tree.find(".//renderer-v2")
        self.assertIsNotNone(renderer)
        self.assertEqual(renderer.attrib.get("type"), "RuleRenderer")

        rules = renderer.findall(".//rule")
        rule_labels = [r.attrib.get("label", "") for r in rules]
        self.assertIn("Extracted Building Points", rule_labels)

        # Check marker layers in the renderer symbols for brown color
        renderer_markers = renderer.findall(".//layer[@class='SimpleMarker']")
        self.assertTrue(len(renderer_markers) >= 3, "Should define scale-dependent marker layers")
        for lyr in renderer_markers:
            color_props = [p.attrib.get("v") for p in lyr.findall("prop") if p.attrib.get("k") == "color"]
            for cp in color_props:
                self.assertEqual(cp, "145,82,45,255", "Marker layers must have brown fill color")

    def test_dialog_output_mapping_uses_extracted_bldgpts(self):
        """Verify EALauncherDialog output mapping maps EXTRACTED_BUILDINGS_OUTPUT to extracted_bldgpts.qml."""
        import inspect
        from references.create_enumeration_area import dialog

        src = inspect.getsource(dialog.EALauncherDialog.run_pipeline)
        self.assertIn("extracted_bldgpts.qml", src, "Dialog output mapping must use extracted_bldgpts.qml")
        self.assertNotIn(
            "('EXTRACTED_BUILDINGS_OUTPUT', f\"{geo5}_extracted_bldgpts\", reference_group, \"1. Base Layer Building Points.qml\"",
            src,
            "Dialog must not assign yellow 1. Base Layer Building Points.qml to extracted buildings"
        )

    def test_algorithm_post_process_mapping(self):
        """Verify EADMCandidatesAlgorithm postProcessAlgorithm includes extracted_bldgpts.qml."""
        import inspect
        from references.create_enumeration_area.eadm_candidates import EADMCandidatesAlgorithm

        src = inspect.getsource(EADMCandidatesAlgorithm.postProcessAlgorithm)
        self.assertIn("self.EXTRACTED_BUILDINGS_OUTPUT: \"extracted_bldgpts.qml\"", src)

    def test_auto_arrange_mapping(self):
        """Verify auto_arrange finds extracted_bldgpts.qml for extracted building points layers."""
        from references.create_enumeration_area.auto_arrange import find_qml_style_for_layer

        self.assertEqual(find_qml_style_for_layer("00123_extracted_bldgpts"), "extracted_bldgpts.qml")
        self.assertEqual(find_qml_style_for_layer("01716_extracted_bldg_pts"), "extracted_bldgpts.qml")
        self.assertEqual(find_qml_style_for_layer("01716_extracted_building"), "extracted_bldgpts.qml")


if __name__ == "__main__":
    unittest.main()
