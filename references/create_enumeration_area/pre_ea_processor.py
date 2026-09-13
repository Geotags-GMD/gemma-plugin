# -*- coding: utf-8 -*-
"""
Pre-EA Processor
----------------
Implements the EA Preprocessing workflow for the EA Delineation and Merging plugin.

Workflow:
  Phase 1 — EA-to-Barangay matching (attribute geocode prefix, spatial fallback)
  Phase 2 — Clip each EA to its parent Barangay boundary
  Phase 3 — Detect uncovered Barangay areas (gaps) after clipping
  Phase 4 — Assign each gap to the contiguous EA with the longest shared boundary
  Phase 5 — Final spatial validation
  Phase 6 — Build and return the output memory layer

Purpose:
  Ensure all EA polygons are completely contained within their corresponding
  Barangay polygon and that no meaningful uncovered area (gap) remains
  within the Barangay after EA boundary adjustments.

Inputs:
  - Barangay polygon layer
  - EA polygon layer

Output:
  - New in-memory polygon layer named <pppmm>_ea2026_preprocessed
  - PreEAResult dataclass containing summary statistics, per-row results, and log lines

Dependencies:
  PyQGIS (QGIS 3.x LTR / PyQt5)
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsDistanceArea,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsSpatialIndex,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from .helpers.constants import create_qgs_field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Attribute field names searched (case-insensitive) when matching EA to Barangay.
_GEOCODE_FIELDS = ("geocode", "geo_code", "psgc", "adm4_pcode", "adm_pcode", "brgy_code")
_EA_GEOCODE_FIELDS = ("geocode", "geo_code", "psgc", "ean", "ea_code", "adm4_pcode")

# Number of geocode prefix characters used for attribute-based matching.
_GEOCODE_PREFIX_LEN = 9


# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------


@dataclass
class ResultRow:
    """One row in the processing results table."""

    barangay_id: str
    ea_id: str
    original_area: float  # square metres
    corrected_area: float  # square metres
    area_change: float     # corrected - original (signed)
    action: str            # "No Change" | "Clipped" | "Gap Assigned" | "Geometry Fixed" | "Unresolved" | "Error"
    status: str            # "Valid" | "Corrected" | "Unresolved" | "Error"


@dataclass
class PreEASummary:
    """Aggregate statistics after processing."""

    barangays_processed: int = 0
    eas_processed: int = 0
    eas_requiring_correction: int = 0
    eas_clipped: int = 0
    overlaps_detected: int = 0
    overlaps_resolved: int = 0
    final_ea_overlaps: int = 0
    gaps_detected: int = 0
    gaps_assigned: int = 0
    unresolved_gaps: int = 0
    final_eas_outside_bgy: int = 0
    final_uncovered_area: float = 0.0  # total area of unresolved gaps in m²
    output_name: str = ""
    overall_status: str = "PASS"  # "PASS" | "WARNING" | "ERROR"


@dataclass
class PreEAResult:
    """Full result returned by PreEAProcessor.run()."""

    output_layer: Optional[QgsVectorLayer]
    summary: PreEASummary
    result_rows: List[ResultRow]
    log_lines: List[str]
    success: bool
    error_message: str = ""


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class PreEAProcessor:
    """
    Executes the Pre-EA Processing workflow.

    Usage::

        processor = PreEAProcessor()
        result = processor.run(
            barangay_layer=bgy_layer,
            ea_layer=ea_layer,
            gap_tolerance=1.0,
            clip_to_bgy=True,
            detect_gaps=True,
            assign_gaps=True,
            feedback_callback=my_log_fn,
            progress_callback=my_progress_fn,
            is_cancelled_fn=lambda: False,
        )
    """

    @staticmethod
    def short_help_string() -> str:
        """Returns the HTML description string for EA Preprocessing."""
        return (
            "<h3>EA Preprocessing</h3>"
            "<p>Prepares an existing Enumeration Area (EA) layer for use in the Create Enumeration Areas "
            "workflow by enforcing two fundamental spatial rules: clipping EAs extending outside their parent "
            "Barangay and filling uncovered coverage gaps within the Barangay boundary.</p>"

            "<h4>Inputs</h4>"
            "<b>Required</b>"
            "<ul>"
            "<li><b>Barangay Layer</b> (polygon) — Administrative barangay polygon boundaries. "
            "Must contain a <i>geocode</i> attribute field used to match EAs to their parent Barangay. "
            "Auto-detected by <code>*_bgy</code> layer name pattern.</li>"
            "<li><b>EA Layer</b> (polygon) — Starting EA polygon boundaries to be pre-processed. "
            "Must contain a <i>geocode</i> attribute field. Auto-detected by <code>*_ea</code> or <code>*_ea2024</code> layer name pattern.</li>"
            "<li><b>Gap Area Tolerance (m²)</b> — Minimum area threshold (default 1.0 m²) for a gap to be processed; "
            "smaller gaps are treated as geometry precision slivers and skipped.</li>"
            "<li><b>Clip EA to Barangay Boundary</b> — When enabled (default: True), clips any portion of an EA extending outside its parent Barangay boundary.</li>"
            "<li><b>Resolve EA Overlaps</b> — When enabled (default: True), detects and eliminates overlapping polygon regions between adjacent EAs within each Barangay.</li>"
            "<li><b>Detect Uncovered Barangay Areas</b> — When enabled (default: True), identifies uncovered gaps within each Barangay after clipping.</li>"
            "<li><b>Assign Gaps to Contiguous EA</b> — When enabled (default: True), assigns each detected gap to the adjacent EA sharing the longest boundary.</li>"
            "</ul>"

            "<h4>Process</h4>"
            "<ol>"
            "<li>Validates input Barangay and EA vector layers and repairs invalid geometries.</li>"
            "<li>Matches each EA to its parent Barangay using attribute geocode prefix matching, centroid containment, or largest spatial overlap.</li>"
            "<li>Clips EAs extending beyond parent Barangay boundaries by computing spatial intersections.</li>"
            "<li>Detects and resolves spatial overlaps between adjacent EA polygons by partitioning overlapping regions cleanly based on proximity.</li>"
            "<li>Computes uncovered Barangay coverage gaps by taking the spatial difference between the Barangay polygon and the union of constituent EAs.</li>"
            "<li>Decomposes gap geometries and assigns each gap polygon to the adjacent contiguous EA sharing the longest boundary (or nearest/largest EA).</li>"
            "<li>Performs final topological validation to ensure zero EAs extend outside Barangays, zero overlaps remain, and no uncovered gaps exist.</li>"
            "<li>Generates pre-processed output polygon features preserving original fields and adding process summary metadata.</li>"
            "</ol>"

            "<h4>Output</h4>"
            "<ul>"
            "<li><b>Pre-Processed EA Layer</b> (polygon, named <i>&lt;5-digit geocode&gt;_ea2026_preprocessed</i>) — "
            "In-memory vector layer containing pre-processed EAs fully aligned with Barangay boundaries, overlap-free, and gap-filled. "
            "All fields from the original EA layer are preserved. Additional/updated fields:</li>"
            "<li><i>hhcount</i> — Household count for the EA polygon.</li>"
            "<li><i>bldgcount</i> — Building count for the EA polygon.</li>"
            "<li><i>sy</i> — Statistical/survey year (set to <i>2026</i>).</li>"
            "<li><i>original_area</i> — Original surface area of the EA polygon in square metres.</li>"
            "<li><i>corrected_area</i> — Corrected surface area of the EA polygon after clipping and gap assignment.</li>"
            "<li><i>area_change</i> — Net area change (square metres) after pre-processing.</li>"
            "<li><i>pre_action</i> — Pre-processing action applied to the feature (e.g. <i>No Change</i>, <i>Clipped</i>, <i>Overlap Resolved</i>, <i>Gap Assigned</i>).</li>"
            "<li><i>pre_status</i> — Pre-processing validation status (e.g. <i>Valid</i>, <i>Corrected</i>, <i>Unresolved</i>).</li>"
            "</ul>"
        )

    def run(
        self,
        barangay_layer: QgsVectorLayer,
        ea_layer: Optional[QgsVectorLayer] = None,
        gap_tolerance: float = 1.0,
        snap_tolerance: float = 25.0,
        clip_to_bgy: bool = True,
        resolve_overlaps: bool = True,
        detect_gaps: bool = True,
        assign_gaps: bool = True,
        output_folder: Optional[str] = None,
        output_file_path: Optional[str] = None,
        feedback_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        is_cancelled_fn: Optional[Callable[[], bool]] = None,
    ) -> PreEAResult:
        """
        Run the full Pre-EA Processing workflow.

        :param barangay_layer: Polygon vector layer of Barangays.
        :param ea_layer: Polygon vector layer of EAs. Optional; if omitted, a new EA layer is created from barangay_layer.
        :param gap_tolerance: Minimum area (m²) for a gap to be considered meaningful.
        :param snap_tolerance: Distance (m) to snap boundary vertices onto Barangay & adjacent EA edges.
        :param clip_to_bgy: Whether to clip EAs extending outside their parent Barangay.
        :param resolve_overlaps: Whether to detect and eliminate overlapping polygon areas between EAs.
        :param detect_gaps: Whether to detect uncovered areas within each Barangay.
        :param assign_gaps: Whether to assign detected gaps to contiguous EAs.
        :param output_folder: Optional filesystem path where output GPKG layer will be exported.
        :param feedback_callback: Optional callable receiving log message strings.
        :param progress_callback: Optional callable receiving integer 0-100 progress values.
        :param is_cancelled_fn: Optional callable returning True when the user cancels.
        :returns: PreEAResult containing the output layer, summary, per-EA rows, and logs.
        """
        log_lines: List[str] = []
        result_rows: List[ResultRow] = []
        summary = PreEASummary()

        def _log(msg: str) -> None:
            log_lines.append(msg)
            if feedback_callback:
                feedback_callback(msg)

        def _progress(pct: int) -> None:
            if progress_callback:
                progress_callback(pct)

        def _cancelled() -> bool:
            return bool(is_cancelled_fn and is_cancelled_fn())

        try:
            _log("[INFO] Starting EA Preprocessing...")
            bgy_name = barangay_layer.name() if barangay_layer else "None"
            _log(f"[INFO] Barangay Layer: {bgy_name}")
            _log("[INFO] Validating input layers...")

            # -- Input validation -------------------------------------------------
            validation_error = self._validate_inputs(barangay_layer, ea_layer)
            if validation_error:
                _log(f"[ERROR] {validation_error}")
                summary.overall_status = "ERROR"
                return PreEAResult(
                    output_layer=None,
                    summary=summary,
                    result_rows=result_rows,
                    log_lines=log_lines,
                    success=False,
                    error_message=validation_error,
                )

            if ea_layer is None:
                _log("[INFO] No EA layer provided. Creating a new EA layer from Barangay layer...")
                ea_layer = self.create_ea_layer_from_barangay(barangay_layer)

            _log(f"[INFO] EA Layer: {ea_layer.name()}")

            # -- Repair input geometries ------------------------------------------
            _log("[INFO] Checking and repairing input geometries...")
            bgy_features = self._load_and_repair_features(barangay_layer, _log, "Barangay")
            ea_features = self._load_and_repair_features(ea_layer, _log, "EA")

            if not bgy_features:
                msg = "Barangay layer has no valid features after geometry repair."
                _log(f"[ERROR] {msg}")
                summary.overall_status = "ERROR"
                return PreEAResult(None, summary, result_rows, log_lines, False, msg)

            if not ea_features:
                msg = "EA layer has no valid features after geometry repair."
                _log(f"[ERROR] {msg}")
                summary.overall_status = "ERROR"
                return PreEAResult(None, summary, result_rows, log_lines, False, msg)

            _progress(5)

            # -- Phase 1: EA-to-Barangay matching ---------------------------------
            _log("[INFO] Matching EAs to parent Barangays...")
            bgy_index = QgsSpatialIndex()
            bgy_by_fid: Dict[int, QgsFeature] = {}
            for feat in bgy_features:
                bgy_index.addFeature(feat)
                bgy_by_fid[feat.id()] = feat

            ea_to_bgy: Dict[int, int] = self._match_ea_to_barangay(
                ea_features, bgy_by_fid, bgy_index, _log
            )

            if _cancelled():
                _log("[INFO] Processing cancelled by user.")
                summary.overall_status = "ERROR"
                return PreEAResult(None, summary, result_rows, log_lines, False, "Cancelled")

            _progress(15)

            # -- Build per-Barangay EA lists --------------------------------------
            bgy_to_eas: Dict[int, List[QgsFeature]] = {}
            for ea_feat in ea_features:
                bgy_fid = ea_to_bgy.get(ea_feat.id())
                if bgy_fid is None:
                    _log(
                        f"[WARNING] EA {self._ea_label(ea_feat)} could not be matched "
                        "to a parent Barangay. It will be skipped."
                    )
                    continue
                bgy_to_eas.setdefault(bgy_fid, []).append(ea_feat)

            # -- Corrected geometry dict: ea_fid -> QgsGeometry ------------------
            corrected_geoms: Dict[int, QgsGeometry] = {}

            total_bgys = len(bgy_to_eas)
            summary.barangays_processed = total_bgys

            for bgy_step, (bgy_fid, eas_in_bgy) in enumerate(bgy_to_eas.items()):
                if _cancelled():
                    _log("[INFO] Processing cancelled by user.")
                    summary.overall_status = "ERROR"
                    return PreEAResult(None, summary, result_rows, log_lines, False, "Cancelled")

                bgy_feat = bgy_by_fid[bgy_fid]
                bgy_geom = bgy_feat.geometry()
                bgy_label = self._bgy_label(bgy_feat)
                _log(f"[INFO] Processing Barangay {bgy_label} ({len(eas_in_bgy)} EAs)...")

                # ---- Phase 2: Clip EAs to Barangay ----------------------------
                for ea_feat in eas_in_bgy:
                    ea_geom = ea_feat.geometry()
                    ea_label = self._ea_label(ea_feat)
                    original_area = ea_geom.area()

                    if not clip_to_bgy:
                        corrected_geoms[ea_feat.id()] = ea_geom
                        summary.eas_processed += 1
                        result_rows.append(ResultRow(
                            barangay_id=bgy_label,
                            ea_id=ea_label,
                            original_area=original_area,
                            corrected_area=original_area,
                            area_change=0.0,
                            action="No Change",
                            status="Valid",
                        ))
                        continue

                    # Check if EA extends beyond the Barangay
                    if bgy_geom.contains(ea_geom):
                        corrected_geoms[ea_feat.id()] = ea_geom
                        summary.eas_processed += 1
                        result_rows.append(ResultRow(
                            barangay_id=bgy_label,
                            ea_id=ea_label,
                            original_area=original_area,
                            corrected_area=original_area,
                            area_change=0.0,
                            action="No Change",
                            status="Valid",
                        ))
                    else:
                        _log(f"[INFO] EA {ea_label} extends outside Barangay {bgy_label}. Clipping...")
                        summary.eas_requiring_correction += 1
                        clipped = ea_geom.intersection(bgy_geom)
                        clipped = self._clean_geometry(clipped, _log, f"EA {ea_label} (clipped)")
                        if clipped is None or clipped.isEmpty():
                            _log(
                                f"[WARNING] EA {ea_label} intersection with Barangay {bgy_label} "
                                "produced an empty geometry. Skipping EA."
                            )
                            result_rows.append(ResultRow(
                                barangay_id=bgy_label,
                                ea_id=ea_label,
                                original_area=original_area,
                                corrected_area=0.0,
                                area_change=-original_area,
                                action="Error",
                                status="Error",
                            ))
                        else:
                            corrected_area = clipped.area()
                            corrected_geoms[ea_feat.id()] = clipped
                            summary.eas_clipped += 1
                            summary.eas_processed += 1
                            _log(f"[INFO] EA {ea_label} clipped successfully.")
                            result_rows.append(ResultRow(
                                barangay_id=bgy_label,
                                ea_id=ea_label,
                                original_area=original_area,
                                corrected_area=corrected_area,
                                area_change=corrected_area - original_area,
                                action="Clipped",
                                status="Corrected",
                            ))

                # ---- Phase 2.5: Resolve EA Overlaps within Barangay ----------
                if resolve_overlaps:
                    ea_fids_in_bgy = [f.id() for f in eas_in_bgy]
                    num_resolved = self._resolve_ea_overlaps(
                        ea_fids=ea_fids_in_bgy,
                        geoms=corrected_geoms,
                        log_fn=_log,
                        crs=barangay_layer.crs(),
                    )
                    summary.overlaps_resolved += num_resolved

                # ---- Phase 3+4: Fill Barangay gaps ---------------------------
                if detect_gaps and assign_gaps:
                    self._fill_barangay_gaps(
                        bgy_geom=bgy_geom,
                        bgy_label=bgy_label,
                        eas_in_bgy=eas_in_bgy,
                        corrected_geoms=corrected_geoms,
                        gap_tolerance=gap_tolerance,
                        summary=summary,
                        result_rows=result_rows,
                        log_fn=_log,
                        crs=barangay_layer.crs(),
                    )

                bgy_step_pct = 15 + int((bgy_step + 1) / max(total_bgys, 1) * 70)
                _progress(bgy_step_pct)


            _progress(85)

            # -- Phase 5: Final validation ----------------------------------------
            _log("[INFO] Performing final topology validation...")
            self._final_validation(
                bgy_by_fid, bgy_to_eas, ea_to_bgy, corrected_geoms, summary, _log, crs=barangay_layer.crs()
            )

            _progress(90)

            # -- Phase 6: Build output layer --------------------------------------
            output_name = self._build_output_name(barangay_layer, ea_layer)
            summary.output_name = output_name
            _log(f"[INFO] Building output layer: {output_name}")

            output_layer = self._build_output_layer(
                ea_layer, ea_features, corrected_geoms, ea_to_bgy, bgy_by_fid, output_name, _log,
                crs=barangay_layer.crs(),
                snap_tolerance=snap_tolerance,
                gap_tolerance=gap_tolerance,
                resolve_overlaps=resolve_overlaps,
            )

            if output_layer is None or output_layer.featureCount() == 0:
                _log(f"[INFO] Output layer '{output_name}' has 0 features; skipping layer generation.")
                summary.overall_status = "PASS" if (summary.unresolved_gaps == 0 and summary.final_eas_outside_bgy == 0) else "WARNING"
                _progress(100)
                return PreEAResult(None, summary, result_rows, log_lines, True, "")

            # Export to designated GeoPackage (.gpkg) file
            saved_to_gpkg = False

            if not output_file_path:
                if output_folder:
                    output_file_path = os.path.join(output_folder, f"{output_name}.gpkg")
                else:
                    proj = QgsProject.instance() if QgsProject.instance() else None
                    proj_fn = proj.fileName() if proj and hasattr(proj, 'fileName') else None
                    proj_hp = proj.homePath() if proj and hasattr(proj, 'homePath') else None
                    if isinstance(proj_fn, str) and proj_fn.strip():
                        output_file_path = os.path.join(os.path.dirname(proj_fn), f"{output_name}.gpkg")
                    elif isinstance(proj_hp, str) and proj_hp.strip():
                        output_file_path = os.path.join(proj_hp, f"{output_name}.gpkg")
                    else:
                        output_file_path = os.path.join(tempfile.gettempdir(), f"{output_name}.gpkg")

            from .helpers.pre_ea_detector import get_unique_filepath
            out_dir = os.path.dirname(output_file_path)
            base_fn = os.path.splitext(os.path.basename(output_file_path))[0]
            if not out_dir:
                out_dir = tempfile.gettempdir()
            output_file_path = get_unique_filepath(out_dir, base_fn, ".gpkg")
            final_layer_name = os.path.splitext(os.path.basename(output_file_path))[0]

            try:
                os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
                if self._export_layer_to_gpkg(output_layer, output_file_path, final_layer_name, _log):
                    _log(f"[INFO] Output layer successfully saved to GeoPackage (.gpkg): {output_file_path}")
                    
                    gpkg_layer = QgsVectorLayer(f"{output_file_path}|layername={final_layer_name}", final_layer_name, "ogr")
                    if not gpkg_layer.isValid():
                        gpkg_layer = QgsVectorLayer(output_file_path, final_layer_name, "ogr")

                    if gpkg_layer.isValid():
                        proj = QgsProject.instance()
                        if proj:
                            # Remove any leftover temporary memory layers with the same name
                            for old_lyr in list(proj.mapLayersByName(final_layer_name)):
                                proj.removeMapLayer(old_lyr.id())
                            proj.addMapLayer(gpkg_layer)
                        _log(f"[INFO] Permanent GeoPackage layer (.gpkg) added to QGIS canvas: {final_layer_name}")
                        output_layer = gpkg_layer
                        summary.output_name = final_layer_name
                        saved_to_gpkg = True
                    else:
                        _log(f"[ERROR] Could not load saved GeoPackage layer from: {output_file_path}")
                else:
                    _log(f"[ERROR] Failed to save GeoPackage (.gpkg) to {output_file_path}")
            except Exception as save_err:
                _log(f"[ERROR] Output layer GeoPackage export failed with exception: {save_err}")

            if not saved_to_gpkg:
                # Add in-memory layer ONLY if GPKG export was not performed or failed
                QgsProject.instance().addMapLayer(output_layer)
                _log(f"[WARNING] Falling back to temporary in-memory layer: {output_name}")

            _progress(100)

            # Determine overall status
            if summary.unresolved_gaps > 0 or summary.final_eas_outside_bgy > 0 or summary.final_ea_overlaps > 0:
                summary.overall_status = "WARNING"
            else:
                summary.overall_status = "PASS"

            _log(f"[INFO] Processing completed. Status: {summary.overall_status}")
            _log(f"[INFO] Output: {output_name}")

            return PreEAResult(
                output_layer=output_layer,
                summary=summary,
                result_rows=result_rows,
                log_lines=log_lines,
                success=True,
            )

        except Exception as exc:
            error_msg = f"Unexpected error during EA Preprocessing: {exc}"
            _log(f"[ERROR] {error_msg}")
            summary.overall_status = "ERROR"
            return PreEAResult(
                output_layer=None,
                summary=summary,
                result_rows=result_rows,
                log_lines=log_lines,
                success=False,
                error_message=error_msg,
            )

    @staticmethod
    def create_ea_layer_from_barangay(barangay_layer: QgsVectorLayer) -> QgsVectorLayer:
        """
        Create a new in-memory EA polygon layer based on the input Barangay layer.

        Copies features from the Barangay layer and ensures standard EA fields
        ('ean', 'hhcount', 'bldgcount') exist.
        """
        if not barangay_layer or not barangay_layer.isValid():
            raise ValueError("Invalid Barangay layer provided for EA layer creation.")

        base_name = barangay_layer.name()
        layer_name = f"{base_name}_ea"
        for pat in ("_bgy", "_barangay", "_brgy"):
            if base_name.lower().endswith(pat):
                layer_name = base_name[: -len(pat)] + "_ea"
                break

        crs_auth = barangay_layer.crs().authid() if barangay_layer.crs().isValid() else "EPSG:4326"
        geom_type = QgsWkbTypes.displayString(barangay_layer.wkbType())
        uri = f"{geom_type}?crs={crs_auth}"

        ea_layer = QgsVectorLayer(uri, layer_name, "memory")
        dp = ea_layer.dataProvider()

        bgy_fields = barangay_layer.fields()
        fields = QgsFields()
        for i in range(bgy_fields.count()):
            f = bgy_fields.at(i)
            if f.name().lower() == "source":
                continue
            fields.append(f)

        existing_names = [fields.at(i).name().lower() for i in range(fields.count())]

        ean_field_name = None
        for name in ("ean", "ea_code", "ea_no", "ea_number"):
            if name in existing_names:
                ean_field_name = name
                break

        if ean_field_name is None:
            fields.append(create_qgs_field("ean", QVariant.String))
            existing_names.append("ean")
            ean_field_name = "ean"

        if "hhcount" not in existing_names and "hh_count" not in existing_names:
            fields.append(create_qgs_field("hhcount", QVariant.Double))
            existing_names.append("hhcount")

        if "bldgcount" not in existing_names and "bldg_count" not in existing_names:
            fields.append(create_qgs_field("bldgcount", QVariant.Int))
            existing_names.append("bldgcount")

        if "sy" not in existing_names:
            fields.append(create_qgs_field("sy", QVariant.String))
            existing_names.append("sy")

        dp.addAttributes(fields)
        ea_layer.updateFields()

        ean_idx = ea_layer.fields().indexOf(ean_field_name)
        hh_idx = ea_layer.fields().indexOf("hhcount") if "hhcount" in existing_names else ea_layer.fields().indexOf("hh_count")
        bldg_idx = ea_layer.fields().indexOf("bldgcount") if "bldgcount" in existing_names else ea_layer.fields().indexOf("bldg_count")
        sy_idx = ea_layer.fields().indexOf("sy")

        fid_idx = ea_layer.fields().indexOf("fid")
        new_features = []
        for i, bgy_feat in enumerate(barangay_layer.getFeatures()):
            ea_feat = QgsFeature(ea_layer.fields())
            ea_feat.setGeometry(bgy_feat.geometry())
            if fid_idx != -1:
                ea_feat.setAttribute(fid_idx, i + 1)
            ea_feat.setId(i + 1)

            for bgy_i in range(bgy_fields.count()):
                bgy_field_name = bgy_fields.at(bgy_i).name()
                if bgy_field_name.lower() == "source":
                    continue
                ea_field_idx = ea_layer.fields().indexOf(bgy_field_name)
                if ea_field_idx != -1:
                    ea_feat.setAttribute(ea_field_idx, bgy_feat.attribute(bgy_i))

            if ean_idx != -1 and (ea_feat.attribute(ean_idx) is None or str(ea_feat.attribute(ean_idx)).strip() in ("", "NULL", "None")):
                ea_feat.setAttribute(ean_idx, "000000")

            if hh_idx != -1 and (ea_feat.attribute(hh_idx) is None or str(ea_feat.attribute(hh_idx)).strip() in ("NULL", "None")):
                ea_feat.setAttribute(hh_idx, 0.0)

            if bldg_idx != -1 and (ea_feat.attribute(bldg_idx) is None or str(ea_feat.attribute(bldg_idx)).strip() in ("NULL", "None")):
                ea_feat.setAttribute(bldg_idx, 0)

            if sy_idx != -1:
                ea_feat.setAttribute(sy_idx, "2026")

            new_features.append(ea_feat)

        dp.addFeatures(new_features)
        ea_layer.updateExtents()
        return ea_layer

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    def _validate_inputs(
        self, barangay_layer: QgsVectorLayer, ea_layer: Optional[QgsVectorLayer] = None
    ) -> Optional[str]:
        """Return an error string if inputs are invalid, else None."""
        if not barangay_layer:
            return "Barangay Layer is required."
        if not barangay_layer.isValid():
            return "Barangay Layer is not a valid layer."
        if barangay_layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            return "Barangay Layer must be a polygon layer."
        if barangay_layer.featureCount() == 0:
            return "Barangay Layer contains no features."

        if ea_layer is not None:
            if not ea_layer.isValid():
                return "EA Layer is not a valid layer."
            if ea_layer.geometryType() != QgsWkbTypes.PolygonGeometry:
                return "EA Layer must be a polygon layer."
            if ea_layer.featureCount() == 0:
                return "EA Layer contains no features."

        return None

    # -------------------------------------------------------------------------
    # Geometry helpers
    # -------------------------------------------------------------------------

    def _load_and_repair_features(
        self,
        layer: QgsVectorLayer,
        log_fn: Callable[[str], None],
        layer_label: str,
    ) -> List[QgsFeature]:
        """Load all features from a layer, repairing invalid geometries."""
        features: List[QgsFeature] = []
        seen_ids: Set[int] = set()
        next_id = 1

        for feat in layer.getFeatures():
            fid = feat.id()
            if fid in seen_ids or fid <= 0:
                while next_id in seen_ids:
                    next_id += 1
                if hasattr(feat, "setId"):
                    feat.setId(next_id)
                else:
                    setattr(feat, "_id", next_id)
                seen_ids.add(next_id)
            else:
                seen_ids.add(fid)

            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                log_fn(
                    f"[WARNING] Empty geometry in {layer_label} feature id={feat.id()}. Skipping."
                )
                continue
            if not geom.isGeosValid():
                repaired = geom.makeValid()
                if repaired and not repaired.isEmpty():
                    fixed_feat = QgsFeature(feat)
                    fixed_feat.setGeometry(repaired)
                    features.append(fixed_feat)
                    log_fn(
                        f"[INFO] Invalid geometry repaired for {layer_label} feature id={feat.id()}."
                    )
                else:
                    log_fn(
                        f"[WARNING] Could not repair geometry for {layer_label} feature id={feat.id()}. Skipping."
                    )
            else:
                features.append(feat)
        return features

    def _remove_interior_rings(self, geom: Optional[QgsGeometry]) -> Optional[QgsGeometry]:
        """Remove all interior rings (holes) from a Polygon or MultiPolygon geometry."""
        if geom is None or geom.isEmpty():
            return geom
        flat_type = QgsWkbTypes.flatType(geom.wkbType())
        try:
            if flat_type == QgsWkbTypes.Polygon:
                poly_xy = geom.asPolygon()
                if poly_xy and len(poly_xy) > 1:
                    return QgsGeometry.fromPolygonXY([poly_xy[0]])
            elif flat_type == QgsWkbTypes.MultiPolygon:
                mpoly_xy = geom.asMultiPolygon()
                cleaned_mpoly = []
                has_holes = False
                for poly_xy in mpoly_xy:
                    if poly_xy:
                        if len(poly_xy) > 1:
                            has_holes = True
                        cleaned_mpoly.append([poly_xy[0]])
                if has_holes:
                    return QgsGeometry.fromMultiPolygonXY(cleaned_mpoly)
        except Exception:
            pass
        return geom

    def _clean_geometry(
        self,
        geom: Optional[QgsGeometry],
        log_fn: Callable[[str], None],
        label: str,
    ) -> Optional[QgsGeometry]:
        """Repair a geometry if invalid; return None if it cannot be repaired."""
        if geom is None or geom.isEmpty():
            return None
        if not geom.isGeosValid():
            repaired = geom.makeValid()
            if repaired and not repaired.isEmpty():
                geom = repaired
            else:
                log_fn(f"[WARNING] Could not repair geometry for {label}.")
                return None
        return self._remove_interior_rings(geom)

    def _eliminate_sliver_parts(
        self,
        geom: Optional[QgsGeometry],
        min_area: float,
        crs: Optional[QgsCoordinateReferenceSystem] = None,
    ) -> Optional[QgsGeometry]:
        """
        Decomposes geometry into polygon parts and filters out any sliver parts
        whose area is below min_area (e.g. 1.0 m²). Returns unified cleaned geometry.
        """
        if geom is None or geom.isEmpty() or min_area <= 0:
            return geom

        parts = self._explode_to_polygons(geom)
        valid_parts = [p for p in parts if self._measure_area(p, crs) >= min_area]

        if not valid_parts:
            # If all parts were slivers, keep the largest part to avoid dropping feature completely
            if parts:
                return max(parts, key=lambda p: self._measure_area(p, crs))
            return None

        if len(valid_parts) == 1:
            return valid_parts[0]

        return QgsGeometry.unaryUnion(valid_parts)

    def _explode_to_polygons(self, geom: QgsGeometry) -> List[QgsGeometry]:
        """Decompose a geometry into a list of single-part polygon geometries."""
        polygons: List[QgsGeometry] = []
        if geom is None or geom.isEmpty():
            return polygons

        flat_type = QgsWkbTypes.flatType(geom.wkbType())
        if flat_type == QgsWkbTypes.Polygon:
            polygons.append(geom)
        elif flat_type == QgsWkbTypes.MultiPolygon:
            for part in geom.constParts():
                polygons.append(QgsGeometry(part.clone()))
        elif flat_type == QgsWkbTypes.GeometryCollection or geom.isMultipart():
            try:
                for part in geom.constParts():
                    part_geom = QgsGeometry(part.clone())
                    part_flat = QgsWkbTypes.flatType(part_geom.wkbType())
                    if part_flat == QgsWkbTypes.Polygon:
                        polygons.append(part_geom)
                    elif part_flat == QgsWkbTypes.MultiPolygon:
                        for sub_part in part_geom.constParts():
                            polygons.append(QgsGeometry(sub_part.clone()))
                    elif part_flat == QgsWkbTypes.GeometryCollection:
                        polygons.extend(self._explode_to_polygons(part_geom))
            except Exception:
                if flat_type in (QgsWkbTypes.Polygon, QgsWkbTypes.MultiPolygon):
                    polygons.append(geom)
        else:
            if flat_type in (QgsWkbTypes.Polygon, QgsWkbTypes.MultiPolygon):
                polygons.append(geom)
        return polygons

    def _measure_area(
        self,
        geom: Optional[QgsGeometry],
        crs: Optional[QgsCoordinateReferenceSystem] = None,
    ) -> float:
        """
        Measure geometry surface area in square metres (m²).

        Handles both Geographic (EPSG:4326 lat/lon) and Projected Coordinate Reference Systems
        by leveraging QgsDistanceArea with WGS84 ellipsoid transformation context.
        """
        if geom is None or geom.isEmpty():
            return 0.0
        try:
            if crs and crs.isValid():
                da = QgsDistanceArea()
                da.setSourceCrs(crs, QgsProject.instance().transformContext())
                da.setEllipsoid("WGS84" if crs.isGeographic() else QgsProject.instance().ellipsoid() or "WGS84")
                val = da.measureArea(geom)
                if isinstance(val, (int, float)):
                    return abs(float(val))
        except Exception:
            pass
        try:
            val = geom.area()
            if isinstance(val, (int, float)):
                return abs(float(val))
        except Exception:
            pass
        return 0.0

    def _get_effective_snap_tolerance(
        self,
        crs: Optional[QgsCoordinateReferenceSystem],
        snap_tolerance: float = 1.0,
    ) -> float:
        """
        Compute effective snapping tolerance in native CRS map units.
        For Projected CRS: snap_tolerance in metres (default 1.0 m).
        For Geographic CRS (EPSG:4326): converts metres to degrees (~1m ≈ 0.000009 deg).
        """
        is_geo = bool(crs and crs.isValid() and crs.isGeographic())
        if is_geo:
            return max(snap_tolerance * 0.000009, 0.000001)
        return max(snap_tolerance, 0.1)

    def _snap_ring_vertices_to_line(
        self,
        ring: List[QgsPointXY],
        ref_line: QgsGeometry,
        snap_tolerance: float,
    ) -> List[QgsPointXY]:
        """
        Snap vertices of a closed polygon ring to ref_line if distance <= snap_tolerance.
        """
        if not ring:
            return ring
        snapped_ring: List[QgsPointXY] = []
        is_closed = (len(ring) > 1 and ring[0] == ring[-1])
        unique_pts = ring[:-1] if is_closed else ring

        for pt in unique_pts:
            pt_geom = QgsGeometry.fromPointXY(pt)
            dist = ref_line.distance(pt_geom)
            if 0 < dist <= snap_tolerance:
                nearest = ref_line.nearestPoint(pt_geom)
                if nearest and not nearest.isEmpty():
                    try:
                        snapped_pt = nearest.asPoint()
                        snapped_ring.append(snapped_pt)
                    except Exception:
                        snapped_ring.append(pt)
                else:
                    snapped_ring.append(pt)
            else:
                snapped_ring.append(pt)

        if is_closed and snapped_ring:
            snapped_ring.append(snapped_ring[0])
        return snapped_ring

    def _snap_geometry_to_line(
        self,
        geom: QgsGeometry,
        ref_line: QgsGeometry,
        snap_tolerance: float,
    ) -> QgsGeometry:
        """
        Snap all vertices of geom that lie within snap_tolerance of ref_line
        directly onto ref_line so boundary segments snap into 1 line.
        """
        if geom is None or geom.isEmpty() or ref_line is None or ref_line.isEmpty():
            return geom

        flat_type = QgsWkbTypes.flatType(geom.wkbType())

        try:
            if flat_type == QgsWkbTypes.Polygon:
                poly_xy = geom.asPolygon()
                snapped_poly = []
                for ring in poly_xy:
                    snapped_ring = self._snap_ring_vertices_to_line(ring, ref_line, snap_tolerance)
                    snapped_poly.append(snapped_ring)
                snapped = QgsGeometry.fromPolygonXY(snapped_poly)
                if snapped and not snapped.isEmpty():
                    snapped = snapped.makeValid()
                    if geom.area() > 0 and snapped.area() < geom.area() * 0.8:
                        return geom
                    return snapped
                return geom

            elif flat_type == QgsWkbTypes.MultiPolygon:
                mpoly_xy = geom.asMultiPolygon()
                snapped_mpoly = []
                for poly in mpoly_xy:
                    snapped_poly = []
                    for ring in poly:
                        snapped_ring = self._snap_ring_vertices_to_line(ring, ref_line, snap_tolerance)
                        snapped_poly.append(snapped_ring)
                    snapped_mpoly.append(snapped_poly)
                snapped = QgsGeometry.fromMultiPolygonXY(snapped_mpoly)
                if snapped and not snapped.isEmpty():
                    snapped = snapped.makeValid()
                    if geom.area() > 0 and snapped.area() < geom.area() * 0.8:
                        return geom
                    return snapped
                return geom
        except Exception:
            return geom

        return geom

    def _snap_geometry_to_barangay_boundary(
        self,
        geom: QgsGeometry,
        bgy_geom: QgsGeometry,
        snap_tolerance: float,
    ) -> QgsGeometry:
        """
        Snap vertices of geom directly onto parent Barangay boundary line.
        """
        if bgy_geom is None or bgy_geom.isEmpty():
            return geom
        try:
            bgy_boundary = bgy_geom.boundary()
            if bgy_boundary is None or bgy_boundary.isEmpty():
                bgy_boundary = bgy_geom.convertToType(QgsWkbTypes.LineGeometry)
        except Exception:
            bgy_boundary = bgy_geom.convertToType(QgsWkbTypes.LineGeometry)

        if bgy_boundary is None or bgy_boundary.isEmpty():
            bgy_boundary = bgy_geom

        return self._snap_geometry_to_line(geom, bgy_boundary, snap_tolerance)

    def _snap_eas_to_each_other(
        self,
        ea_fids: List[int],
        final_geoms: Dict[int, QgsGeometry],
        snap_tolerance: float,
    ) -> None:
        """
        Snap vertices of adjacent EA geometries to each other so that shared internal
        boundaries between EAs match vertex-for-vertex and render as 1 single line.
        """
        if len(ea_fids) <= 1:
            return

        for pass_num in range(2):
            for target_fid in ea_fids:
                target_geom = final_geoms.get(target_fid)
                if target_geom is None or target_geom.isEmpty():
                    continue

                other_geoms = [
                    final_geoms[other_fid]
                    for other_fid in ea_fids
                    if other_fid != target_fid
                    and final_geoms.get(other_fid)
                    and not final_geoms[other_fid].isEmpty()
                ]

                if not other_geoms:
                    continue

                other_union = QgsGeometry.unaryUnion(other_geoms)
                if other_union is None or other_union.isEmpty():
                    continue

                other_boundary = other_union.convertToType(QgsWkbTypes.LineGeometry)
                if other_boundary is None or other_boundary.isEmpty():
                    other_boundary = other_union

                snapped_geom = self._snap_geometry_to_line(target_geom, other_boundary, snap_tolerance)
                if snapped_geom and not snapped_geom.isEmpty():
                    final_geoms[target_fid] = snapped_geom

    # -------------------------------------------------------------------------
    # EA-to-Barangay matching
    # -------------------------------------------------------------------------

    def _match_ea_to_barangay(
        self,
        ea_features: List[QgsFeature],
        bgy_by_fid: Dict[int, QgsFeature],
        bgy_index: QgsSpatialIndex,
        log_fn: Callable[[str], None],
    ) -> Dict[int, int]:
        """
        Return a mapping of EA feature id -> Barangay feature id.

        Strategy:
          1. Attribute geocode prefix match (first _GEOCODE_PREFIX_LEN digits).
          2. Spatial fallback: Barangay whose polygon contains the EA centroid,
             or has the largest intersection area with the EA.
        """
        ea_to_bgy: Dict[int, int] = {}

        # Pre-extract Barangay geocode prefixes for attribute matching
        bgy_geocode_map: Dict[str, int] = {}  # prefix -> bgy fid
        for bgy_fid, bgy_feat in bgy_by_fid.items():
            prefix = self._extract_geocode_prefix(bgy_feat, _GEOCODE_FIELDS)
            if prefix:
                bgy_geocode_map[prefix] = bgy_fid

        for ea_feat in ea_features:
            ea_fid = ea_feat.id()
            matched_bgy_fid: Optional[int] = None

            # Strategy 1: attribute geocode prefix
            ea_prefix = self._extract_geocode_prefix(ea_feat, _EA_GEOCODE_FIELDS)
            if ea_prefix and ea_prefix in bgy_geocode_map:
                matched_bgy_fid = bgy_geocode_map[ea_prefix]

            # Strategy 2: spatial — Barangay containing the EA centroid
            if matched_bgy_fid is None:
                centroid = ea_feat.geometry().centroid()
                candidate_fids = bgy_index.intersects(centroid.boundingBox())
                for bgy_fid in candidate_fids:
                    bgy_geom = bgy_by_fid[bgy_fid].geometry()
                    if bgy_geom.contains(centroid):
                        matched_bgy_fid = bgy_fid
                        break

            # Strategy 3: spatial — largest intersection area
            if matched_bgy_fid is None:
                ea_bbox = ea_feat.geometry().boundingBox()
                candidate_fids = bgy_index.intersects(ea_bbox)
                best_area = 0.0
                for bgy_fid in candidate_fids:
                    bgy_geom = bgy_by_fid[bgy_fid].geometry()
                    inter = ea_feat.geometry().intersection(bgy_geom)
                    if inter and not inter.isEmpty():
                        area = inter.area()
                        if area > best_area:
                            best_area = area
                            matched_bgy_fid = bgy_fid

            if matched_bgy_fid is not None:
                ea_to_bgy[ea_fid] = matched_bgy_fid
            else:
                log_fn(
                    f"[WARNING] EA {self._ea_label(ea_feat)} could not be matched to any Barangay."
                )

        return ea_to_bgy

    def _extract_geocode_prefix(
        self, feat: QgsFeature, field_names: Tuple[str, ...]
    ) -> Optional[str]:
        """
        Extract the first _GEOCODE_PREFIX_LEN digit characters from a geocode
        attribute field.  Returns None if no match is found.
        """
        feat_fields = feat.fields()
        for candidate_name in field_names:
            # Case-insensitive field lookup
            for i in range(feat_fields.count()):
                if feat_fields.at(i).name().lower() == candidate_name.lower():
                    val = feat.attribute(i)
                    if val is None:
                        break
                    digits = re.sub(r"\D", "", str(val))
                    if len(digits) >= _GEOCODE_PREFIX_LEN:
                        return digits[:_GEOCODE_PREFIX_LEN]
                    elif len(digits) >= 5:
                        return digits[:5]
                    break
        # Fallback: try layer name digits
        return None

    def _extract_numeric_attribute(
        self, feat: QgsFeature, field_candidates: Tuple[str, ...]
    ) -> Optional[float]:
        """
        Case-insensitively search for an attribute among field_candidates in feat.
        Return float value if found and valid, otherwise None.
        """
        feat_fields = feat.fields()
        for candidate in field_candidates:
            for i in range(feat_fields.count()):
                if feat_fields.at(i).name().lower() == candidate.lower():
                    val = feat.attribute(i)
                    if val is not None and val != "":
                        try:
                            return float(val)
                        except (ValueError, TypeError):
                            pass
        return None

    # -------------------------------------------------------------------------
    # Gap assignment
    # -------------------------------------------------------------------------

    def _fill_barangay_gaps(
        self,
        bgy_geom: QgsGeometry,
        bgy_label: str,
        eas_in_bgy: List[QgsFeature],
        corrected_geoms: Dict[int, QgsGeometry],
        gap_tolerance: float,
        summary: "PreEASummary",
        result_rows: List["ResultRow"],
        log_fn: Callable[[str], None],
        crs: Optional[QgsCoordinateReferenceSystem] = None,
    ) -> None:
        """
        Fill every gap inside a Barangay polygon by distributing uncovered areas
        into adjacent EAs.

        The Barangay polygon is the definitive outer boundary.  The gap is
        computed as::

            gap = bgy_geom.difference( union_of_all_eas_in_barangay )

        Each gap piece is assigned to the adjacent or nearest EA sharing the longest
        boundary or closest distance.

        :param bgy_geom:       Geometry of the Barangay polygon.
        :param bgy_label:      Human-readable label used in log messages.
        :param eas_in_bgy:     EA features that belong to this Barangay.
        :param corrected_geoms: Mutable dict of ea_fid -> current geometry.
                                Updated in-place as gaps are merged.
        :param gap_tolerance:  Minimum gap area (m²) to report as a distinct gap item.
        :param summary:        PreEASummary counters, updated in-place.
        :param result_rows:    Per-EA result rows, updated in-place.
        :param log_fn:         Logging callback.
        :param crs:            Optional Coordinate Reference System for distance thresholds.
        """
        ea_geoms_in_bgy = [
            corrected_geoms[ea_feat.id()]
            for ea_feat in eas_in_bgy
            if ea_feat.id() in corrected_geoms
        ]

        if not ea_geoms_in_bgy:
            return

        # Single EA shortcut: if only 1 EA in Barangay, assign the full Barangay geometry
        if len(eas_in_bgy) == 1:
            single_fid = eas_in_bgy[0].id()
            ea_label_for_gap = self._ea_label(eas_in_bgy[0])
            corrected_geoms[single_fid] = bgy_geom
            summary.gaps_assigned += 1
            log_fn(f"[INFO] Single EA {ea_label_for_gap} aligned to full Barangay {bgy_label} boundary.")
            return

        # Compute total gap = Barangay polygon minus union of all EAs
        ea_union = QgsGeometry.unaryUnion(ea_geoms_in_bgy)
        if ea_union is None:
            ea_union = QgsGeometry()

        gap_geom = bgy_geom.difference(ea_union)
        gap_geom = self._clean_geometry(gap_geom, log_fn, f"Barangay {bgy_label} gap")

        if gap_geom is None or gap_geom.isEmpty():
            return  # Barangay already fully covered — nothing to do

        # Decompose multipart gap into individual polygons for assignment
        gap_parts = self._explode_to_polygons(gap_geom)
        
        # Sort gap parts by area descending so larger gaps are assigned first
        gap_parts.sort(key=lambda g: self._measure_area(g, crs), reverse=True)

        meaningful_count = sum(1 for g in gap_parts if self._measure_area(g, crs) >= gap_tolerance)
        if meaningful_count > 0:
            log_fn(f"[INFO] {meaningful_count} gap(s) detected in Barangay {bgy_label}.")
            summary.gaps_detected += meaningful_count

        buf_dist = 0.000001 if (crs and crs.isValid() and crs.isGeographic()) else 0.01

        for gap in gap_parts:
            gap_area_m2 = self._measure_area(gap, crs)
            if gap_area_m2 < 0.01:
                continue

            # Primary: EA with the longest shared boundary or nearest proximity
            best_ea_fid, best_shared_len = self._find_best_ea_for_gap(
                gap, eas_in_bgy, corrected_geoms, crs
            )

            if best_ea_fid is None:
                # Fallback: largest-area EA in the Barangay
                best_ea_fid = self._largest_ea_fid(eas_in_bgy, corrected_geoms)

            if best_ea_fid is None:
                if gap_area_m2 >= gap_tolerance:
                    summary.unresolved_gaps += 1
                    log_fn(
                        f"[WARNING] Unresolved gap in Barangay {bgy_label} "
                        f"({gap_area_m2:.2f} m²). No EA available."
                    )
                    result_rows.append(ResultRow(
                        barangay_id=bgy_label,
                        ea_id="(gap)",
                        original_area=gap_area_m2,
                        corrected_area=gap_area_m2,
                        area_change=0.0,
                        action="Unresolved",
                        status="Unresolved",
                    ))
                continue

            # Merge the gap into the chosen EA with small buffer to seal edge gaps
            current_geom = corrected_geoms[best_ea_fid]
            gap_buffered = gap.buffer(buf_dist, 3)
            merged_geom = current_geom.combine(gap_buffered)
            merged_geom = self._clean_geometry(merged_geom, log_fn, "Gap merged EA")
            if merged_geom is None or merged_geom.isEmpty():
                merged_geom = current_geom
            else:
                # Keep merged EA bounded strictly inside parent Barangay polygon
                if not bgy_geom.contains(merged_geom):
                    clipped = merged_geom.intersection(bgy_geom)
                    if clipped and not clipped.isEmpty():
                        merged_geom = clipped

                # Ensure gap merging does not overlap other EAs in the Barangay
                other_geoms = [
                    corrected_geoms[of.id()]
                    for of in eas_in_bgy
                    if of.id() != best_ea_fid
                    and of.id() in corrected_geoms
                    and corrected_geoms[of.id()]
                    and not corrected_geoms[of.id()].isEmpty()
                ]
                if other_geoms:
                    other_union = QgsGeometry.unaryUnion(other_geoms)
                    if other_union and not other_union.isEmpty():
                        non_overlap = merged_geom.difference(other_union)
                        if non_overlap and not non_overlap.isEmpty():
                            merged_geom = non_overlap

            corrected_geoms[best_ea_fid] = merged_geom

            if gap_area_m2 >= gap_tolerance:
                summary.gaps_assigned += 1

            ea_label_for_gap = self._ea_label_by_fid(best_ea_fid, eas_in_bgy)
            log_fn(
                f"[INFO] Gap ({gap_area_m2:.2f} m²) in Barangay {bgy_label} → "
                f"EA {ea_label_for_gap} (shared edge: {best_shared_len:.2f} m)."
            )

            curr_area_m2 = self._measure_area(current_geom, crs)
            merged_area_m2 = self._measure_area(merged_geom, crs)

            # Update or create the result row for the receiving EA
            for row in result_rows:
                if row.barangay_id == bgy_label and row.ea_id == ea_label_for_gap:
                    row.corrected_area = merged_area_m2
                    row.area_change = merged_area_m2 - row.original_area
                    if row.action in ("No Change", "Clipped"):
                        row.action = "Gap Assigned"
                        row.status = "Corrected"
                    break
            else:
                result_rows.append(ResultRow(
                    barangay_id=bgy_label,
                    ea_id=ea_label_for_gap,
                    original_area=curr_area_m2,
                    corrected_area=merged_area_m2,
                    area_change=merged_area_m2 - curr_area_m2,
                    action="Gap Assigned",
                    status="Corrected",
                ))

    def _find_best_ea_for_gap(
        self,
        gap: QgsGeometry,
        eas_in_bgy: List[QgsFeature],
        corrected_geoms: Dict[int, QgsGeometry],
        crs: Optional[QgsCoordinateReferenceSystem] = None,
    ) -> Tuple[Optional[int], float]:
        """
        Find the EA in eas_in_bgy best suited to absorb the gap.

        Primary criterion: EA sharing the longest boundary / perimeter with the gap.
        Secondary criterion: closest EA by distance (for near-touching gaps).

        :returns: (best_ea_fid, best_shared_length_or_score) or (None, 0.0)
        """
        search_radius = self._get_effective_snap_tolerance(crs, 25.0)

        gap_buffered = gap.buffer(search_radius, 5)

        best_fid: Optional[int] = None
        best_shared_len: float = -1.0
        best_dist: float = float("inf")

        for ea_feat in eas_in_bgy:
            ea_fid = ea_feat.id()
            ea_geom = corrected_geoms.get(ea_fid)
            if ea_geom is None or ea_geom.isEmpty():
                continue

            dist = gap.distance(ea_geom)

            # Measure shared boundary length
            shared = gap_buffered.intersection(ea_geom)
            shared_len = shared.length() if shared else 0.0

            if shared_len > best_shared_len or (shared_len == best_shared_len and dist < best_dist):
                best_shared_len = shared_len
                best_dist = dist
                best_fid = ea_fid

        if best_fid is not None:
            return best_fid, max(best_shared_len, 0.0)

        return None, 0.0

    def _largest_ea_fid(
        self,
        eas_in_bgy: List[QgsFeature],
        corrected_geoms: Dict[int, QgsGeometry],
    ) -> Optional[int]:
        """
        Return the feature id of the EA with the largest area among eas_in_bgy.

        Used as the last-resort fallback when no contiguous EA can be found
        for a gap, ensuring the gap is always absorbed by some EA rather than
        left unassigned.

        :returns: Feature id of the largest EA, or None if eas_in_bgy is empty.
        """
        best_fid: Optional[int] = None
        best_area: float = -1.0

        for ea_feat in eas_in_bgy:
            ea_fid = ea_feat.id()
            ea_geom = corrected_geoms.get(ea_fid)
            if ea_geom is None or ea_geom.isEmpty():
                continue
            area = ea_geom.area()
            if area > best_area:
                best_area = area
                best_fid = ea_fid

        return best_fid

    def _resolve_ea_overlaps(
        self,
        ea_fids: List[int],
        geoms: Dict[int, QgsGeometry],
        log_fn: Callable[[str], None],
        crs: Optional[QgsCoordinateReferenceSystem] = None,
    ) -> int:
        """
        Detect and resolve spatial overlaps between EA geometries in ea_fids.

        For each pair of overlapping EAs, the overlapping area is decomposed into
        polygon parts and each part is assigned to the EA whose centroid is closest
        to the overlap part's centroid, subtracting it from the other EA.

        :returns: Total count of resolved overlap occurrences.
        """
        if len(ea_fids) <= 1:
            return 0

        resolved_count = 0
        for iteration in range(3):
            overlap_found_in_pass = False
            for i in range(len(ea_fids)):
                fid1 = ea_fids[i]
                g1 = geoms.get(fid1)
                if g1 is None or g1.isEmpty():
                    continue
                for j in range(i + 1, len(ea_fids)):
                    fid2 = ea_fids[j]
                    g2 = geoms.get(fid2)
                    if g2 is None or g2.isEmpty():
                        continue

                    if not g1.intersects(g2):
                        continue

                    inter = g1.intersection(g2)
                    inter = self._clean_geometry(inter, log_fn, "EA overlap")
                    if inter is None or inter.isEmpty():
                        continue

                    overlap_parts = self._explode_to_polygons(inter)
                    inter_area = sum(self._measure_area(p, crs) for p in overlap_parts)
                    if inter_area < 0.001:
                        continue

                    overlap_found_in_pass = True
                    resolved_count += 1
                    log_fn(
                        f"[INFO] Detected overlap ({inter_area:.2f} m²) between EA fid={fid1} and EA fid={fid2}. Resolving..."
                    )

                    for part in overlap_parts:
                        part_area = self._measure_area(part, crs)
                        if part_area < 0.0001:
                            continue

                        part_c = part.centroid()
                        c1 = g1.centroid()
                        c2 = g2.centroid()
                        dist1 = part_c.distance(c1) if c1 and not c1.isEmpty() else float("inf")
                        dist2 = part_c.distance(c2) if c2 and not c2.isEmpty() else float("inf")

                        if dist1 <= dist2:
                            # Keep in g1, subtract from g2
                            g2_sub = g2.difference(part)
                            g2_sub = self._clean_geometry(g2_sub, log_fn, f"EA fid={fid2} post-overlap")
                            if g2_sub and not g2_sub.isEmpty():
                                g2 = g2_sub
                                geoms[fid2] = g2
                        else:
                            # Keep in g2, subtract from g1
                            g1_sub = g1.difference(part)
                            g1_sub = self._clean_geometry(g1_sub, log_fn, f"EA fid={fid1} post-overlap")
                            if g1_sub and not g1_sub.isEmpty():
                                g1 = g1_sub
                                geoms[fid1] = g1
                                # Refresh g1 for remaining j iterations
                                break

            if not overlap_found_in_pass:
                break

        return resolved_count

    # -------------------------------------------------------------------------
    # Final validation
    # -------------------------------------------------------------------------

    def _final_validation(
        self,
        bgy_by_fid: Dict[int, QgsFeature],
        bgy_to_eas: Dict[int, List[QgsFeature]],
        ea_to_bgy: Dict[int, int],
        corrected_geoms: Dict[int, QgsGeometry],
        summary: PreEASummary,
        log_fn: Callable[[str], None],
        crs: Optional[QgsCoordinateReferenceSystem] = None,
    ) -> None:
        """Run post-processing spatial validation checks."""
        outside_count = 0
        uncovered_total = 0.0
        overlap_count = 0

        for bgy_fid, eas_in_bgy in bgy_to_eas.items():
            bgy_feat = bgy_by_fid[bgy_fid]
            bgy_geom = bgy_feat.geometry()
            bgy_label = self._bgy_label(bgy_feat)

            ea_geoms_in_bgy = [
                corrected_geoms[ea_feat.id()]
                for ea_feat in eas_in_bgy
                if ea_feat.id() in corrected_geoms
            ]

            # Validation 1: No EA outside Barangay
            for ea_feat in eas_in_bgy:
                ea_fid = ea_feat.id()
                ea_geom = corrected_geoms.get(ea_fid)
                if ea_geom is None:
                    continue
                if not bgy_geom.contains(ea_geom):
                    # Allow a very small tolerance (floating point slivers)
                    outside_area = ea_geom.difference(bgy_geom)
                    outside_area_m2 = self._measure_area(outside_area, crs)
                    if outside_area and not outside_area.isEmpty() and outside_area_m2 > 0.01:
                        outside_count += 1
                        log_fn(
                            f"[WARNING] Validation: EA {self._ea_label(ea_feat)} still extends "
                            f"outside Barangay {bgy_label} (area={outside_area_m2:.4f} m²)."
                        )

            # Validation 2: No EA-to-EA overlaps within Barangay
            valid_ea_fids = [
                ea_feat.id() for ea_feat in eas_in_bgy
                if ea_feat.id() in corrected_geoms and corrected_geoms[ea_feat.id()] and not corrected_geoms[ea_feat.id()].isEmpty()
            ]
            for i in range(len(valid_ea_fids)):
                fid1 = valid_ea_fids[i]
                g1 = corrected_geoms[fid1]
                for j in range(i + 1, len(valid_ea_fids)):
                    fid2 = valid_ea_fids[j]
                    g2 = corrected_geoms[fid2]
                    if g1.intersects(g2):
                        inter = g1.intersection(g2)
                        if inter and not inter.isEmpty():
                            inter_parts = self._explode_to_polygons(inter)
                            inter_area = sum(self._measure_area(p, crs) for p in inter_parts)
                            if inter_area > 0.001:
                                overlap_count += 1
                                lbl1 = self._ea_label_by_fid(fid1, eas_in_bgy)
                                lbl2 = self._ea_label_by_fid(fid2, eas_in_bgy)
                                log_fn(
                                    f"[WARNING] Validation: EA {lbl1} and EA {lbl2} "
                                    f"overlap in Barangay {bgy_label} (area={inter_area:.4f} m²)."
                                )

            # Validation 3: No meaningful uncovered Barangay area
            if ea_geoms_in_bgy:
                ea_union = QgsGeometry.unaryUnion(ea_geoms_in_bgy)
                if ea_union:
                    residual_gap = bgy_geom.difference(ea_union)
                    if residual_gap and not residual_gap.isEmpty():
                        gap_area = self._measure_area(residual_gap, crs)
                        if gap_area > 1.0:
                            uncovered_total += gap_area
                            log_fn(
                                f"[WARNING] Validation: Barangay {bgy_label} has residual "
                                f"uncovered area of {gap_area:.2f} m²."
                            )

        summary.final_eas_outside_bgy = outside_count
        summary.final_uncovered_area = uncovered_total
        summary.final_ea_overlaps = overlap_count

        if outside_count == 0 and uncovered_total == 0.0 and overlap_count == 0:
            log_fn("[INFO] Final validation passed.")
        else:
            log_fn(
                f"[WARNING] Final validation: {outside_count} EA(s) outside Barangay, "
                f"{overlap_count} EA overlap(s), {uncovered_total:.2f} m² uncovered area."
            )

    # -------------------------------------------------------------------------
    # Output layer construction
    # -------------------------------------------------------------------------

    def _build_output_layer(
        self,
        ea_layer: QgsVectorLayer,
        ea_features: List[QgsFeature],
        corrected_geoms: Dict[int, QgsGeometry],
        ea_to_bgy: Dict[int, int],
        bgy_by_fid: Dict[int, QgsFeature],
        output_name: str,
        log_fn: Callable[[str], None],
        crs: Optional[QgsCoordinateReferenceSystem] = None,
        snap_tolerance: float = 25.0,
        gap_tolerance: float = 1.0,
        resolve_overlaps: bool = True,
    ) -> Optional[QgsVectorLayer]:
        """
        Construct the output in-memory polygon layer.

        Copies all field definitions from the input EA layer and writes each
        EA feature with its corrected geometry and original attribute values.

        Two guarantees are enforced on every output geometry:
          1. Final clip: each EA is intersected with its parent Barangay so no
             output polygon crosses a Barangay boundary.
          2. Final reconciliation: after writing all EAs, any area within a
             Barangay not yet covered by the output EAs is decomposed into gap
             parts and merged into adjacent/nearest EAs — ensuring 100% complete
             coverage of the Barangay polygon.
        """
        # Determine CRS
        crs_auth = ea_layer.crs().authid()
        uri = f"Polygon?crs={crs_auth}"
        output_layer = QgsVectorLayer(uri, output_name, "memory")

        if not output_layer.isValid():
            log_fn("[ERROR] Failed to create output memory layer.")
            return None

        # Copy field schema from input EA layer (excluding 'source') and ensure hhcount, bldgcount & sy exist
        dp = output_layer.dataProvider()
        ea_fields: QgsFields = ea_layer.fields()
        fields_to_add = QgsFields()
        for i in range(ea_fields.count()):
            f = ea_fields.at(i)
            if f.name().lower() == "source":
                continue
            fields_to_add.append(f)

        existing_names = [fields_to_add.at(i).name().lower() for i in range(fields_to_add.count())]
        if "hhcount" not in existing_names:
            fields_to_add.append(create_qgs_field("hhcount", QVariant.Double))
        if "bldgcount" not in existing_names:
            fields_to_add.append(create_qgs_field("bldgcount", QVariant.Int))
        if "sy" not in existing_names:
            fields_to_add.append(create_qgs_field("sy", QVariant.String))

        dp.addAttributes(fields_to_add)
        output_layer.updateFields()

        # ── Pass 1: build a mutable geometry dict with the final clip applied ──
        # Maps ea_fid → final output geometry (clipped to Barangay)
        final_geoms: Dict[int, QgsGeometry] = {}

        for ea_feat in ea_features:
            ea_fid = ea_feat.id()
            geom = corrected_geoms.get(ea_fid)
            if geom is None:
                geom = ea_feat.geometry()

            # Clip to parent Barangay boundary
            bgy_fid = ea_to_bgy.get(ea_fid)
            if bgy_fid is not None and bgy_fid in bgy_by_fid:
                bgy_geom = bgy_by_fid[bgy_fid].geometry()
                if not bgy_geom.contains(geom):
                    clipped = geom.intersection(bgy_geom)
                    if clipped and not clipped.isEmpty():
                        geom = clipped

            final_geoms[ea_fid] = geom

        # Group EAs by Barangay to check coverage & resolve overlaps
        bgy_to_ea_fids: Dict[int, List[int]] = {}
        for ea_fid, bgy_fid in ea_to_bgy.items():
            if ea_fid in final_geoms:
                bgy_to_ea_fids.setdefault(bgy_fid, []).append(ea_fid)

        # ── Pass 1.5: resolve EA overlaps before reconciliation ───────────────
        if resolve_overlaps:
            for bgy_fid, ea_fids in bgy_to_ea_fids.items():
                if len(ea_fids) > 1:
                    self._resolve_ea_overlaps(ea_fids, final_geoms, log_fn, crs)

        # ── Pass 2: reconcile — ensure every Barangay is fully covered ────────
        for bgy_fid, ea_fids in bgy_to_ea_fids.items():
            bgy_feat = bgy_by_fid.get(bgy_fid)
            if bgy_feat is None or not ea_fids:
                continue
            bgy_geom = bgy_feat.geometry()

            # Single EA in Barangay: assign 100% of Barangay geometry directly
            if len(ea_fids) == 1:
                final_geoms[ea_fids[0]] = bgy_geom
                continue

            buf_dist = 0.000001 if (crs and crs.isValid() and crs.isGeographic()) else 0.01

            # Multi-EA Barangay: run up to 3 iterative reconciliation passes
            for iteration in range(3):
                valid_geoms = [
                    final_geoms[fid] for fid in ea_fids
                    if final_geoms.get(fid) and not final_geoms[fid].isEmpty()
                ]
                if not valid_geoms:
                    break

                ea_union = QgsGeometry.unaryUnion(valid_geoms)
                if ea_union is None or ea_union.isEmpty():
                    residual = bgy_geom
                else:
                    residual = bgy_geom.difference(ea_union)

                residual_area_m2 = self._measure_area(residual, crs)
                if residual is None or residual.isEmpty() or residual_area_m2 < 0.1:
                    break  # Fully covered (less than 0.1 m² gap remaining)

                residual_parts = self._explode_to_polygons(residual)
                eas_in_bgy_subset = [f for f in ea_features if f.id() in ea_fids]

                merged_any = False
                for r_part in residual_parts:
                    r_part_m2 = self._measure_area(r_part, crs)
                    if r_part is None or r_part.isEmpty() or r_part_m2 < 0.01:
                        continue

                    best_fid, _ = self._find_best_ea_for_gap(r_part, eas_in_bgy_subset, final_geoms, crs)
                    if best_fid is None:
                        best_fid = self._largest_ea_fid(eas_in_bgy_subset, final_geoms)

                    if best_fid is not None:
                        r_part_buf = r_part.buffer(buf_dist, 3)
                        merged = final_geoms[best_fid].combine(r_part_buf)
                        merged = self._clean_geometry(merged, log_fn, "Reconciliation EA")
                        if merged and not merged.isEmpty():
                            if not bgy_geom.contains(merged):
                                clipped = merged.intersection(bgy_geom)
                                if clipped and not clipped.isEmpty():
                                    merged = clipped

                            # Ensure zero overlap with other EAs in the Barangay
                            other_geoms = [
                                final_geoms[other_fid]
                                for other_fid in ea_fids
                                if other_fid != best_fid
                                and final_geoms.get(other_fid)
                                and not final_geoms[other_fid].isEmpty()
                            ]
                            if other_geoms:
                                other_union = QgsGeometry.unaryUnion(other_geoms)
                                if other_union and not other_union.isEmpty():
                                    non_overlap = merged.difference(other_union)
                                    if non_overlap and not non_overlap.isEmpty():
                                        merged = non_overlap

                            final_geoms[best_fid] = merged
                            merged_any = True
                            log_fn(
                                f"[INFO] Reconciliation (iter {iteration+1}): residual {r_part_m2:.2f} m² "
                                f"in Barangay {self._bgy_label(bgy_feat)} merged into EA fid={best_fid}."
                            )

                if not merged_any:
                    break

        # ── Pass 2.5: mutual EA-to-EA vertex snapping for clean internal shared borders ─
        snap_tol = self._get_effective_snap_tolerance(crs, snap_tolerance)
        for bgy_fid, ea_fids in bgy_to_ea_fids.items():
            if len(ea_fids) > 1:
                self._snap_eas_to_each_other(ea_fids, final_geoms, snap_tol)

        # ── Pass 2.6: final pass of overlap resolution after snapping ──────────
        if resolve_overlaps:
            for bgy_fid, ea_fids in bgy_to_ea_fids.items():
                if len(ea_fids) > 1:
                    self._resolve_ea_overlaps(ea_fids, final_geoms, log_fn, crs)

        # ── Pass 3: write output features ──────────────────────────────────────
        out_fields = output_layer.fields()
        fid_idx = out_fields.indexOf("fid")
        hhcount_idx = -1
        bldgcount_idx = -1
        sy_idx = -1
        for i in range(out_fields.count()):
            name_lower = out_fields.at(i).name().lower()
            if name_lower == "hhcount":
                hhcount_idx = i
            elif name_lower == "bldgcount":
                bldgcount_idx = i
            elif name_lower == "sy":
                sy_idx = i

        new_features: List[QgsFeature] = []
        for ea_feat in ea_features:
            ea_fid = ea_feat.id()
            geom = final_geoms.get(ea_fid)
            if geom is None or geom.isEmpty():
                continue

            # Snap EA boundary vertices to parent Barangay boundary line so they render as 1 single shared line
            bgy_fid = ea_to_bgy.get(ea_fid)
            if bgy_fid is not None and bgy_fid in bgy_by_fid:
                bgy_geom = bgy_by_fid[bgy_fid].geometry()
                geom = self._snap_geometry_to_barangay_boundary(geom, bgy_geom, snap_tol)

            # Eliminate sliver polygon parts below gap_tolerance
            geom = self._eliminate_sliver_parts(geom, gap_tolerance, crs)
            geom = self._remove_interior_rings(geom)
            if geom is None or geom.isEmpty():
                continue

            new_feat = QgsFeature(out_fields)
            new_feat.setGeometry(geom)

            # Copy existing fields from input EA (matching by field name, excluding 'source')
            for i in range(ea_fields.count()):
                src_field_name = ea_fields.at(i).name()
                if src_field_name.lower() == "source":
                    continue
                out_idx = out_fields.indexOf(src_field_name)
                if out_idx != -1:
                    new_feat.setAttribute(out_idx, ea_feat.attribute(i))

            # Ensure hhcount field is populated
            if hhcount_idx != -1:
                hh_val = self._extract_numeric_attribute(
                    ea_feat, ("hhcount", "new_hhcount", "hh_count", "hh_cnt", "household", "household_count", "pop", "population")
                )
                new_feat.setAttribute(hhcount_idx, float(hh_val) if hh_val is not None else 0.0)

            # Ensure bldgcount field is populated
            if bldgcount_idx != -1:
                bldg_val = self._extract_numeric_attribute(
                    ea_feat, ("bldgcount", "new_bldgcount", "bldg_count", "bldg_cnt", "bldgpts_cnt", "bldg_points")
                )
                new_feat.setAttribute(bldgcount_idx, int(round(bldg_val)) if bldg_val is not None else 0)

            # Ensure sy field is populated with "2026"
            if sy_idx != -1:
                new_feat.setAttribute(sy_idx, "2026")

            out_fid = len(new_features) + 1
            if fid_idx != -1:
                new_feat.setAttribute(fid_idx, out_fid)
            new_feat.setId(out_fid)

            new_features.append(new_feat)

        if len(new_features) == 0:
            log_fn(f"[INFO] No valid output features to build layer '{output_name}'.")
            return None

        dp.addFeatures(new_features)
        output_layer.updateExtents()

        log_fn(f"[INFO] Output layer '{output_name}' created with {len(new_features)} features.")
        return output_layer

    # -------------------------------------------------------------------------
    # Output naming
    # -------------------------------------------------------------------------

    def _build_output_name(
        self, barangay_layer: QgsVectorLayer, ea_layer: QgsVectorLayer
    ) -> str:
        """
        Derive the output layer name as <pppmm>_ea2026_preprocessed.

        The 5-digit geographic code is extracted exclusively from the Barangay
        input layer, in the following priority order:

          1. The Barangay layer name (first 5 consecutive digits).
             e.g. "04340_bgy"  ->  "04340"
          2. The geocode / PSGC attribute of the first Barangay feature.
          3. Falls back to 'xxxxx' if no code can be determined.

        The EA layer name is intentionally not used as a code source so that
        the output name always mirrors the Barangay input layer.
        """
        # Priority 1: digits in the Barangay layer name
        digits = re.sub(r"\D", "", barangay_layer.name())
        if len(digits) >= 5:
            return f"{digits[:5]}_ea2026_preprocessed"

        # Priority 2: geocode attribute of the first Barangay feature
        for field_name in _GEOCODE_FIELDS:
            idx = -1
            for i in range(barangay_layer.fields().count()):
                if barangay_layer.fields().at(i).name().lower() == field_name.lower():
                    idx = i
                    break
            if idx != -1:
                feat = next(barangay_layer.getFeatures(QgsFeatureRequest().setLimit(1)), None)
                if feat:
                    val = str(feat.attribute(idx))
                    digits = re.sub(r"\D", "", val)
                    if len(digits) >= 5:
                        return f"{digits[:5]}_ea2026_preprocessed"

        return "xxxxx_ea2026_preprocessed"


    # -------------------------------------------------------------------------
    # Label helpers
    # -------------------------------------------------------------------------

    def _bgy_label(self, feat: QgsFeature) -> str:
        """Return a human-readable label for a Barangay feature."""
        fields = feat.fields()
        for candidate in ("name", "barangay", "bgy_name", "brgy_name", "adm4_en", "geocode"):
            for i in range(fields.count()):
                if fields.at(i).name().lower() == candidate:
                    val = feat.attribute(i)
                    if val is not None:
                        s = str(val).strip()
                        if s:
                            return s
        return f"fid={feat.id()}"

    def _ea_label(self, feat: QgsFeature) -> str:
        """Return a human-readable label for an EA feature."""
        fields = feat.fields()
        for candidate in ("ea_name", "ea_no", "ean", "ea_number", "geocode", "id"):
            for i in range(fields.count()):
                if fields.at(i).name().lower() == candidate:
                    val = feat.attribute(i)
                    if val is not None:
                        s = str(val).strip()
                        if s.endswith(".0"):
                            s = s[:-2]
                        if s:
                            return s
        return f"fid={feat.id()}"

    def _ea_label_by_fid(self, ea_fid: int, eas_in_bgy: List[QgsFeature]) -> str:
        """Return the label for an EA given its feature id."""
        for feat in eas_in_bgy:
            if feat.id() == ea_fid:
                return self._ea_label(feat)
        return f"fid={ea_fid}"

    def _export_layer_to_gpkg(self, layer: QgsVectorLayer, file_path: str, layer_name: str, log_fn) -> bool:
        """Export a vector layer to a permanent GeoPackage (.gpkg) file on disk using QGIS Processing / QgsVectorFileWriter."""
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # Method 1: QGIS Processing native:savefeatures (native C++ engine, robust GPKG creation)
            try:
                import processing
                params = {
                    "INPUT": layer,
                    "OUTPUT": file_path,
                    "LAYER_NAME": layer_name
                }
                res = processing.run("native:savefeatures", params)
                if res and os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                    log_fn(f"[INFO] Layer successfully written to GeoPackage via QGIS Processing: {file_path}")
                    return True
            except Exception as pe:
                log_fn(f"[DEBUG] QGIS Processing native:savefeatures fallback: {pe}")

            from qgis.core import (
                QgsVectorFileWriter,
                QgsCoordinateTransformContext,
                QgsProject,
            )

            # Method 2: SaveVectorOptions with writeAsVectorFormatV3 / V2
            save_options = QgsVectorFileWriter.SaveVectorOptions()
            save_options.driverName = "GPKG"
            save_options.layerName = layer_name
            save_options.fileEncoding = "UTF-8"
            if os.path.exists(file_path):
                save_options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
            else:
                save_options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

            ctx = (
                QgsProject.instance().transformContext()
                if (QgsProject.instance() and hasattr(QgsProject.instance(), 'transformContext'))
                else QgsCoordinateTransformContext()
            )

            if hasattr(QgsVectorFileWriter, 'writeAsVectorFormatV3'):
                res = QgsVectorFileWriter.writeAsVectorFormatV3(layer, file_path, ctx, save_options)
                if res[0] == QgsVectorFileWriter.NoError:
                    return True
                log_fn(f"[DEBUG] writeAsVectorFormatV3 code={res[0]}: {res[1] if len(res) > 1 else ''}")

            if hasattr(QgsVectorFileWriter, 'writeAsVectorFormatV2'):
                res = QgsVectorFileWriter.writeAsVectorFormatV2(layer, file_path, ctx, save_options)
                if res[0] == QgsVectorFileWriter.NoError:
                    return True
                log_fn(f"[DEBUG] writeAsVectorFormatV2 code={res[0]}: {res[1] if len(res) > 1 else ''}")

            # Method 3: Legacy writeAsVectorFormat
            if hasattr(QgsVectorFileWriter, 'writeAsVectorFormat'):
                res = QgsVectorFileWriter.writeAsVectorFormat(layer, file_path, "UTF-8", layer.crs(), "GPKG")
                if res == QgsVectorFileWriter.NoError:
                    return True
                log_fn(f"[DEBUG] writeAsVectorFormat code={res}")

            # Method 4: Direct writer feature-by-feature
            writer = QgsVectorFileWriter(file_path, "UTF-8", layer.fields(), layer.wkbType(), layer.crs(), "GPKG")
            if writer.hasError() == QgsVectorFileWriter.NoError:
                for feat in layer.getFeatures():
                    writer.addFeature(feat)
                del writer
                return True
            else:
                log_fn(f"[DEBUG] Direct QgsVectorFileWriter error={writer.errorMessage()}")

        except Exception as e:
            log_fn(f"[ERROR] Exception during GeoPackage export: {e}")
            return False

        return os.path.exists(file_path) and os.path.getsize(file_path) > 0
