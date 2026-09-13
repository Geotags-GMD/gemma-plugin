

from typing import Any, Optional
import math

from qgis.core import (
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterString,
    QgsProcessingParameterCrs,
    QgsProcessingParameterEnum,
    QgsFeature,
    QgsGeometry,
    QgsCoordinateTransform,
    QgsCoordinateReferenceSystem,
    QgsSpatialIndex,
)
from qgis import processing

from PyQt5.QtCore import QVariant

from .preview_widget import TablePreviewWidgetWrapper
from .helpers.geometry import get_polygons_from_geom



class EADMCandidatesAlgorithm(QgsProcessingAlgorithm):
    """
    EADM Candidates Pipeline: Consolidates scanning, delineation, and merging logic
    into a single standalone workflow.
    """

    # Constants used to refer to parameters and outputs
    BARANGAY_INPUT = "BARANGAY_INPUT"
    BUILDING_INPUT = "BUILDING_INPUT"
    PREVIOUS_EA_INPUT = "PREVIOUS_EA_INPUT"
    BARANGAY_ID_FIELD = "BARANGAY_ID_FIELD"
    EA_ID_FIELD = "EA_ID_FIELD"
    HOUSEHOLD_FIELD = "HOUSEHOLD_FIELD"
    MIN_HOUSEHOLD = "MIN_HOUSEHOLD"
    MAX_HOUSEHOLD = "MAX_HOUSEHOLD"
    USE_COMPACTNESS = "USE_COMPACTNESS"
    ALLOW_CANDIDATE_MERGE = "ALLOW_CANDIDATE_MERGE"
    TARGET_CRS = "TARGET_CRS"
    OUTPUT = "OUTPUT"
    DELINEATED_OUTPUT = "DELINEATED_OUTPUT"
    MERGED_OUTPUT = "MERGED_OUTPUT"
    SPECIAL_EA_OUTPUT = "SPECIAL_EA_OUTPUT"
    DELINEATION_CANDIDATE_OUTPUT = "DELINEATION_CANDIDATE_OUTPUT"
    EXTRACTED_BUILDINGS_OUTPUT = "EXTRACTED_BUILDINGS_OUTPUT"
    SLIVER_THRESHOLD = "SLIVER_THRESHOLD"
    PREVIEW_ONLY = "PREVIEW_ONLY"
    PREVIEW = "PREVIEW"
    # New optional linear layer parameters
    ROAD_INPUT = "ROAD_INPUT"
    RIVER_INPUT = "RIVER_INPUT"
    GAP_INPUT = "GAP_INPUT"
    OVERLAP_INPUT = "OVERLAP_INPUT"
    SNAP_TOLERANCE = "SNAP_TOLERANCE"
    ENABLE_THRESHOLDS = "ENABLE_THRESHOLDS"
    SPLIT_STRATEGY = "SPLIT_STRATEGY"
    SPLIT_TYPE = "SPLIT_TYPE"
    # Buffer tolerance (meters) for snapping splits to linear features
    LINE_BUFFER_TOLERANCE = 0.5

    def name(self) -> str:
        """Returns the algorithm name (unique identifier)."""
        return "createea"

    def displayName(self) -> str:
        """Returns the translated algorithm name for display."""
        return "EA Delineation and Merging"

    def createInstance(self):
        return EADMCandidatesAlgorithm()

    def group(self) -> str:
        """Returns the name of the algorithm group."""
        return "1Map"

    def groupId(self) -> str:
        """Returns the unique ID of the group."""
        return "1map"

    def flags(self):
        """Hides algorithm from Processing Toolbox while keeping it registered for custom UI dialog."""
        return super().flags() | QgsProcessingAlgorithm.FlagHideFromToolbox

    def icon(self):
        """Returns the algorithm icon."""
        import os
        from PyQt5.QtGui import QIcon
        icon_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "icons", "create_ea.svg")
        )
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return super().icon()

    def shortHelpString(self) -> str:
        """Returns a short description of the algorithm."""
        return (
            "<h3>EA Delineation and Merging</h3>"
            "<p>Delineates new Enumeration Areas (EAs) by spatially aggregating or splitting "
            "existing EA polygons to meet household-count thresholds, with optional alignment "
            "to road and river boundaries.</p>"

            "<h4>Inputs</h4>"
            "<b>Required</b>"
            "<ul>"
            "<li><b>Barangay Layer</b> (polygon) — Administrative barangay boundaries. "
            "Must contain a <i>geocode</i> field used to assign parent barangay codes to output EAs.</li>"
            "<li><b>Building Point Layer</b> (point) — Structure/building points with an "
            "<i>hhcount</i> field representing the household count per building. "
            "Used to calculate the total household load of each EA candidate.</li>"
            "<li><b>Previous EA Layer</b> (polygon) — Starting EA boundaries from the previous "
            "census round. Must contain a <i>geocode</i> field. "
            "Fields and region attributes from this layer are inherited by the output.</li>"
            "<li><b>Minimum / Maximum Household Count per EA</b> — Target range (default 100–300 HH). "
            "EAs below the minimum are merged with neighbours; EAs above the maximum are split.</li>"
            "<li><b>Splitting Rule for Large Areas (&gt;300 Houses)</b> — Controls how strictly household limits are enforced during splits. "
            "Options: <i>Follow Roads & Rivers (Recommended)</i>, <i>Strict Minimum 100 Houses</i>, or <i>Do Not Split</i>.</li>"
            "<li><b>Boundary Cut Method</b> — Selects the line tool used to cut boundaries. "
            "Options: <i>Auto (Roads First, then Houses)</i>, <i>Roads & Rivers Only</i>, <i>House Groups Only</i>, <i>Straight Line Only</i>, or <i>Do Not Split</i>.</li>"
            "<li><b>Optimize for Compactness</b> — When enabled, the clustering algorithm "
            "prefers spatially compact EA shapes over purely household-balanced splits.</li>"
            "<li><b>Allow Merging Between Under-Threshold Candidate EAs</b> — When enabled (default: True), "
            "under-threshold EAs (&lt;= min_household) can merge with each other when no reference EAs are available in the barangay.</li>"
            "<li><b>Sliver Polygon Area Threshold</b> — Controls how small a remnant polygon "
            "must be before it is discarded as a sliver. <i>Auto-detect</i> derives the threshold "
            "from the average nearest-neighbour spacing of building points.</li>"
            "<li><b>Target CRS</b> — Output coordinate reference system (default EPSG:4326).</li>"
            "</ul>"
            "<b>Optional</b>"
            "<ul>"
            "<li><b>Road Layer</b> (line) — Road network used to snap EA split boundaries "
            "to road centrelines, producing more survey-friendly EAs.</li>"
            "<li><b>River Layer</b> (line) — River/waterway network used in the same "
            "boundary-snapping process as the road layer.</li>"
            "<li><b>Snapping Tolerance (metres)</b> — Maximum distance a proposed split line "
            "is shifted to coincide with the nearest road or river segment (default 15 m).</li>"
            "</ul>"

            "<h4>Process</h4>"
            "<ol>"
            "<li>Auto-detects project layers by name pattern (_bgy, _ea, _bldgpts, road, river).</li>"
            "<li>Transforms building points to the barangay/EA CRS if they differ.</li>"
            "<li>Spatially joins building points to starting EAs and sums <i>hhcount</i> per EA.</li>"
            "<li>EAs within the target range are passed through unchanged.</li>"
            "<li>Over-populated EAs are split using weighted K-Means clustering on building points, "
            "optionally snapping split boundaries to road/river lines.</li>"
            "<li>Under-populated EAs are merged with the most suitable adjacent EA in the "
            "same barangay (including adjacent candidate EAs if candidate merging is enabled).</li>"
            "<li>Sliver polygons smaller than the chosen area threshold are dissolved into "
            "their largest neighbour.</li>"
            "<li>Each output EA inherits attributes from the previous EA layer and receives "
            "updated household count, building-count, and split-method fields.</li>"
            "</ol>"

            "<h4>Output</h4>"
            "<ul>"
            "<li><b>Output EA Layer</b> (polygon, named <i>&lt;5-digit geocode&gt;_ea2026</i>) — "
            "All fields from the previous EA layer are preserved. Additional/updated fields:</li>"
            "<li><i>hhcount</i> — Total household count for the EA.</li>"
            "<li><i>bldgcount</i> — Number of building points within the EA.</li>"
            "<li><i>split_by</i> — Method used to split the EA (e.g. <i>road</i>, <i>river</i>, "
            "<i>kmeans</i>), or empty if unchanged/merged.</li>"
            "<li><i>new_ean</i> — Flag/code indicating whether the EA is newly created.</li>"
            "<li><i>correspondence_ea_geocode</i> — Geocode of the originating previous EA.</li>"
            "<li><i>indicator</i> — Delineation status/indicator (e.g., <i>for_delineation</i>, <i>ea_reference</i>).</li>"
            "<li><i>remarks</i> — Remarks describing split/merge operations.</li>"
            "</ul>"
            "<li><b>Delineated EAs Layer</b> (polygon, named <i>&lt;5-digit geocode&gt;_delineated_ea2026</i>) — "
            "Contains all sub-polygons generated from delineation, fully covering the split candidate EAs.</li>"
            "<li><b>Merged EAs Layer</b> (polygon, named <i>&lt;5-digit geocode&gt;_merged_ea2026</i>) — "
            "Contains EAs created by merging distinct starting EAs.</li>"
            "<li><b>Special EAs Layer</b> (polygon, named <i>&lt;5-digit geocode&gt;_special_ea</i>) — "
            "Contains EAs generated from processing user-supplied Gap or Overlap polygon layers.</li>"
            "<li><b>Delineation Candidate Layer</b> (polygon, named <i>&lt;5-digit geocode&gt;_delineation_candidates</i>) — "
            "Contains starting EAs exceeding the maximum household limit (>= max_household) or intersecting Gap/Overlap layers.</li>"
            "<li><b>Extracted Building Points Layer</b> (point, named <i>&lt;5-digit geocode&gt;_extracted_bldgpts</i>) — "
            "Contains building points extracted within the candidate EAs.</li>"
            "</ul>"
        )

    def initAlgorithm(self, config: Optional[dict[str, Any]] = None):
        """Defines the inputs and outputs of the algorithm."""
        from qgis.core import QgsProject
        
        # Auto-detect layers in the current QGIS project
        default_bgy = None
        default_ea = None
        default_bldgpts = None
        default_road = None
        default_river = None
        
        try:
            layers = QgsProject.instance().mapLayers().values()
            for layer in layers:
                name_lower = layer.name().lower()
                if "_bgy" in name_lower and default_bgy is None:
                    default_bgy = layer
                elif "_ea" in name_lower and default_ea is None:
                    default_ea = layer
                elif ("_bldgpts" in name_lower or "_bldg_point" in name_lower or "_bldg_points" in name_lower) and default_bldgpts is None:
                    default_bldgpts = layer
                elif "road" in name_lower and default_road is None:
                    default_road = layer
                elif "river" in name_lower and default_river is None:
                    default_river = layer
        except Exception:
            pass

        # Barangay polygon input
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.BARANGAY_INPUT,
                "Barangay Layer",
                [QgsProcessing.SourceType.TypeVectorPolygon],
                defaultValue=default_bgy,
            )
        )
       
        # Building point input
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.BUILDING_INPUT,
                "Building Point Layer",
                [QgsProcessing.SourceType.TypeVectorPoint],
                defaultValue=default_bldgpts,
            )
        )

        # Previous EA layer (required for region assignment)
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.PREVIOUS_EA_INPUT,
                "Previous EA Layer",
                [QgsProcessing.SourceType.TypeVectorPolygon],
                defaultValue=default_ea,
            )
        )
        
        # Optional Road layer
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.ROAD_INPUT,
                "Road Layer (optional)",
                [QgsProcessing.SourceType.TypeVectorLine],
                defaultValue=default_road,
                optional=True,
            )
        )
        # Optional River layer
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.RIVER_INPUT,
                "River Layer (optional)",
                [QgsProcessing.SourceType.TypeVectorLine],
                defaultValue=default_river,
                optional=True,
            )
        )
        # Optional Gap layer
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.GAP_INPUT,
                "Gap Layer (optional)",
                [QgsProcessing.SourceType.TypeVectorPolygon],
                defaultValue=None,
                optional=True,
            )
        )
        # Optional Overlap layer
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.OVERLAP_INPUT,
                "Overlap Layer (optional)",
                [QgsProcessing.SourceType.TypeVectorPolygon],
                defaultValue=None,
                optional=True,
            )
        )

        # Snapping Tolerance
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SNAP_TOLERANCE,
                "Snapping Tolerance (meters) for road/river alignment",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=15.0,
                minValue=0.0,
            )
        )

        # Hidden fields for Barangay ID, EA ID, and Household Count are hardcoded in processAlgorithm

        # Enable Household Thresholds option
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ENABLE_THRESHOLDS,
                "Enable Household Count Thresholds",
                defaultValue=True,
            )
        )

        # Minimum household threshold
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_HOUSEHOLD,
                "Minimum Household Count per EA",
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=99,
                minValue=1,
            )
        )

        # Maximum household threshold
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_HOUSEHOLD,
                "Maximum Household Count per EA",
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=300,
                minValue=1,
            )
        )
        # Split Strategy option for large EAs
        self.addParameter(
            QgsProcessingParameterEnum(
                self.SPLIT_STRATEGY,
                "Splitting Rule for Large Areas (>300 Houses)",
                options=[
                    "Follow Roads & Rivers (Recommended)",
                    "Strict Minimum 100 Houses",
                    "Do Not Split",
                ],
                defaultValue=0,
            )
        )
        # Split Type option (algorithm selection)
        self.addParameter(
            QgsProcessingParameterEnum(
                self.SPLIT_TYPE,
                "Boundary Cut Method",
                options=[
                    "Auto (Roads First, then Houses)",
                    "Roads & Rivers Only",
                    "House Groups Only",
                    "Straight Line Only",
                    "Do Not Split",
                ],
                defaultValue=0,
            )
        )


        # Use compactness optimization
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.USE_COMPACTNESS,
                "Optimize for Compactness",
                defaultValue=True,
            )
        )

        # Allow Candidate Merging (candidate-to-candidate merging)
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ALLOW_CANDIDATE_MERGE,
                "Allow Merging Between Under-Threshold Candidate EAs",
                defaultValue=True,
            )
        )

        # Sliver Polygon Area Threshold (options for automatic threshold chosen based on CRS units)
        self.addParameter(
            QgsProcessingParameterEnum(
                self.SLIVER_THRESHOLD,
                "Sliver Polygon Area Threshold",
                options=[
                    "Auto-detect (Script Chosen / Dynamic)",
                    "Automatic (Conservative - 1e-11 deg / 1e-4 m²)",
                    "Automatic (Standard - 1e-9 deg / 1e-2 m²)",
                    "Automatic (Moderate - 1e-7 deg / 1 m²)",
                    "Automatic (Aggressive - 1e-5 deg / 100 m²)",
                    "Automatic (Ultra-Conservative - 1e-13 deg / 1e-6 m²)",
                    "Automatic (Super Aggressive - 1e-4 deg / 1,000 m²)",
                    "Automatic (Extremely Aggressive - 1e-3 deg / 10,000 m²)"
                ],
                defaultValue=0,
            )
        )

        # Target CRS (Defaulting to EPSG:4326)
        self.addParameter(
            QgsProcessingParameterCrs(
                self.TARGET_CRS,
                "Target CRS",
                defaultValue="EPSG:4326",
            )
        )

        # Preview Candidates Only checkbox
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.PREVIEW_ONLY,
                "Preview Candidates Only (Exit early after creating candidate layers)",
                defaultValue=False,
            )
        )

        # Candidates Preview Table (using custom TablePreviewWidgetWrapper)
        preview_param = QgsProcessingParameterString(
            self.PREVIEW,
            "Candidates Preview Table",
            defaultValue="",
            optional=True,
        )
        preview_param.setMetadata({"widget_wrapper": {"class": TablePreviewWidgetWrapper}})
        self.addParameter(preview_param)

        # Output layer
#        self.addParameter(
#            QgsProcessingParameterFeatureSink(
#                self.OUTPUT,
#                "Output EA Layer",
#            )
#        )

        # Delineated output layer
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.DELINEATED_OUTPUT,
                "Delineated EAs Layer",
                optional=True,
            )
        )

        # Merged output layer
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.MERGED_OUTPUT,
                "Merged EAs Layer",
                optional=True,
            )
        )

        # Special EAs output layer (Gap/Overlap)
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.SPECIAL_EA_OUTPUT,
                "Special EAs Layer (Gap/Overlap)",
                optional=True,
            )
        )

        # Candidate for delineation output layer
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.DELINEATION_CANDIDATE_OUTPUT,
                "Candidate for Delineation Layer",
                type=QgsProcessing.SourceType.TypeVector,
                optional=True,
            )
        )

        # Extracted building points output layer
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.EXTRACTED_BUILDINGS_OUTPUT,
                "Extracted Building Points Layer",
                type=QgsProcessing.SourceType.TypeVectorPoint,
                optional=True,
            )
        )

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        """Main processing logic for EA creation."""
        # Yield to GUI event loop to ensure QGIS remains responsive and Cancel click is registered
        from .helpers.constants import _TOTAL_PHASES, _PHASE_LABELS, yield_to_ui

        import math
        import random
        from qgis.PyQt.QtCore import QVariant
        from qgis.core import (
            QgsFields,
            QgsField,
            QgsSpatialIndex,
            QgsFeature,
            QgsGeometry,
            QgsPointXY,
            QgsWkbTypes,
            QgsCoordinateTransform,
        )

        from qgis.core import QgsProcessingMultiStepFeedback
        multi_feedback = QgsProcessingMultiStepFeedback(_TOTAL_PHASES, feedback)
        multi_feedback.setCurrentStep(0)
        multi_feedback.setProgressText(f"{_PHASE_LABELS[0]}...")
        feedback.pushInfo("Phase 1/8: Initializing — reading parameters...")

        from .phases.phase1_init import run_phase_1
        p1 = run_phase_1(self, parameters, context, feedback)

        barangay_source = p1["barangay_source"]
        building_source = p1["building_source"]
        previous_ea_source = p1["previous_ea_source"]
        road_source = p1["road_source"]
        river_source = p1["river_source"]
        gap_source = p1["gap_source"]
        overlap_source = p1["overlap_source"]
        snap_tolerance_m = p1["snap_tolerance_m"]
        preview_only = p1["preview_only"]
        eadel_indi_col_idx = p1["eadel_indi_col_idx"]
        merge_indi_col_idx = p1["merge_indi_col_idx"]
        ea_id_field = p1["ea_id_field"]
        household_field = p1["household_field"]
        bldg_hh_field = p1["bldg_hh_field"]
        barangay_id_field = p1["barangay_id_field"]
        bar_geocode_field = p1["bar_geocode_field"]
        min_household = p1["min_household"]
        max_household = p1["max_household"]
        target_household = p1["target_household"]
        target_crs = p1["target_crs"]
        barangay_index = p1["barangay_index"]
        barangay_by_id = p1["barangay_by_id"]
        active_barangay_geocodes = p1["active_barangay_geocodes"]
        _dc_geo_idx = p1["_dc_geo_idx"]
        all_ea_features = p1["all_ea_features"]
        special_ea_info = p1["special_ea_info"]
        special_ea_ids = p1["special_ea_ids"]
        output_layer_name = p1["output_layer_name"]
        snap_tolerance = p1["snap_tolerance"]
        densify_dist = p1["densify_dist"]
        transform = p1["transform"]
        area_threshold = p1["area_threshold"]
        source_crs = p1["source_crs"]

        def get_parent_barangay(ea_geom):
            candidates = barangay_index.intersects(ea_geom.boundingBox())
            max_overlap = -1
            parent_feat = None
            for cid in candidates:
                bar = barangay_by_id[cid]
                bar_geom = bar.geometry()
                if bar_geom.intersects(ea_geom):
                    overlap_area = bar_geom.intersection(ea_geom).area()
                    if overlap_area > max_overlap:
                        max_overlap = overlap_area
                        parent_feat = bar
            return parent_feat

        def resolve_ea_parent_barangay(ea_feat):
            parent_feat = get_parent_barangay(ea_feat.geometry())
            if parent_feat:
                val = None
                for f in parent_feat.fields():
                    if f.name().lower() == "geocode":
                        val = parent_feat.attribute(f.name())
                        break
                if val is None and parent_feat.fields().indexOf(barangay_id_field) != -1:
                    val = parent_feat.attribute(barangay_id_field)
                if val is not None and not (isinstance(val, QVariant) and val.isNull()):
                    val_str = str(val).strip()
                    if val_str.endswith(".0"):
                        val_str = val_str[:-2]
                    if val_str:
                        return val_str
            if _dc_geo_idx != -1:
                val = ea_feat.attribute(_dc_geo_idx)
                if val is not None and not (isinstance(val, QVariant) and val.isNull()):
                    val_str = str(val).strip()
                    if val_str.endswith(".0"):
                        val_str = val_str[:-2]
                    if val_str:
                        if len(val_str) > 5 and len(val_str) in (9, 10, 11, 12):
                            return val_str[:5]
            for f in ea_feat.fields():
                if f.name().lower() == "geocode":
                    val = ea_feat.attribute(f.name())
                    if val is not None and not (isinstance(val, QVariant) and val.isNull()):
                        val_str = str(val).strip()
                        if val_str.endswith(".0"):
                            val_str = val_str[:-2]
                        if val_str:
                            if len(val_str) > 5 and len(val_str) in (9, 10, 11, 12):
                                return val_str[:5]
                        return val_str
            return "Unknown"

        import os
        cpu_cores = os.cpu_count()
        num_cores = max(1, cpu_cores - 4) if cpu_cores else 4

        from .phases.phase2_candidates import run_phase_2
        all_ea_features = p1["all_ea_features"]
        previous_ea_count = len(all_ea_features)
        p2 = run_phase_2(self, parameters, context, feedback, multi_feedback, p1)

        if p2["preview_exit"]:
            return p2["outputs"]

        outputs = p2["outputs"]
        out_fields = p2["out_fields"]
        out_wkb_type = p2["out_wkb_type"]
        delineated_sink = p2["delineated_sink"]
        merged_sink = p2["merged_sink"]
        extracted_buildings_sink = p2["extracted_buildings_sink"]
        delin_candidate_sink = p2["delin_candidate_sink"]
        delineated_feat_count = p2["delineated_feat_count"]
        merged_feat_count = p2["merged_feat_count"]
        delin_candidate_feat_count = p2["delin_candidate_feat_count"]
        extracted_bldg_feat_count = p2["extracted_bldg_feat_count"]
        delineation_candidate_ids = p2["delineation_candidate_ids"]
        merge_candidate_ids = p2["merge_candidate_ids"]
        delineation_candidate_hhdivthres = p2["delineation_candidate_hhdivthres"]
        delineation_candidates_by_geocode = p2["delineation_candidates_by_geocode"]
        delineation_candidate_bar_geocodes = p2["delineation_candidate_bar_geocodes"]
        adjacent_ea_ids = p2["adjacent_ea_ids"]
        imputed_hhcount = p2["imputed_hhcount"]
        ea_index = p2["ea_index"]
        ea_by_id = p2["ea_by_id"]
        temp_ea_index = p2["temp_ea_index"]
        temp_ea_by_id = p2["temp_ea_by_id"]
        ea_id_to_buildings = p2["ea_id_to_buildings"]
        output_hh_field = p2["output_hh_field"]


        from .phases.phase3_indexes import run_phase_3
        p3 = run_phase_3(self, parameters, context, feedback, multi_feedback, p1, p2)
        ea_index = p3["ea_index"]
        ea_by_id = p3["ea_by_id"]
        road_index = p3["road_index"]
        road_geoms = p3["road_geoms"]
        river_index = p3["river_index"]
        river_geoms = p3["river_geoms"]

        from .phases.phase4_load_eas import run_phase_4
        p4 = run_phase_4(
            self, parameters, context, feedback, multi_feedback, p1, p2, previous_ea_count
        )
        eas = p4["eas"]
        active_barangays = p4["active_barangays"]
        needed_ea_ids = p4["needed_ea_ids"]
        max_ea_number = p4["max_ea_number"]

        from .phases.phase5_delineate import run_phase_5
        p5 = run_phase_5(
            self, parameters, context, feedback, multi_feedback, p1, p2, p3, p4
        )
        split_eas = p5["split_eas"]

        from .phases.phase6_merge import run_phase_6
        p6 = run_phase_6(
            self, parameters, context, feedback, multi_feedback, p1, p2, p5
        )
        eas = p6["merged_eas"]

        from .phases.phase7_compliance import run_phase_7
        p7 = run_phase_7(
            self, parameters, context, feedback, multi_feedback, p1, p2, p6
        )

        from .phases.phase8_output import run_phase_8
        return run_phase_8(
            self, parameters, context, feedback, multi_feedback, p1, p2, p3, p4, p7
        )

    def postProcessAlgorithm(self, context, feedback):
        """Automatically apply QML styles and automated labeling to generated output layers."""
        try:
            from .helpers.style import apply_qml_to_layer

            styles_map = {
                self.EXTRACTED_BUILDINGS_OUTPUT: "extracted_bldgpts.qml",
                self.DELINEATED_OUTPUT: "ea_output.qml",
                self.MERGED_OUTPUT: "ea_output.qml",
                self.DELINEATION_CANDIDATE_OUTPUT: "delineation_candidates.qml",
            }

            for param_name, qml_filename in styles_map.items():
                layer_id = self.parameterAsOutputLayer(context, param_name)
                if layer_id:
                    layer = context.getMapLayer(layer_id)
                    if layer is not None and layer.featureCount() > 0:
                        apply_qml_to_layer(layer, qml_filename)
        except Exception as e:
            if feedback:
                feedback.pushInfo(f"Note: Could not auto-apply QML style: {str(e)}")

        if hasattr(super(), "postProcessAlgorithm"):
            try:
                return super().postProcessAlgorithm(context, feedback)
            except (AttributeError, TypeError, Exception):
                pass
        return {}

    def createInstance(self):
        """Create a new instance of this algorithm."""
        return self.__class__()

