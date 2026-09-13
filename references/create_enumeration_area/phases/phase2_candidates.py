import math

from qgis.core import (
    QgsFeature,
    QgsFields,
    QgsField,
    QgsGeometry,
    QgsWkbTypes,
    QgsProcessingException,
    QgsSpatialIndex,
    QgsCoordinateTransform,
    QgsRectangle,
    QgsFeatureRequest,
    QgsFeatureSink,
    NULL,
)
from qgis.PyQt.QtCore import QVariant

from ..helpers.constants import _PHASE_LABELS, yield_to_ui, create_qgs_field
from ..helpers.spatial import get_parent_barangay, normalize_to_8_digits


def run_phase_2(alg, parameters, context, feedback, multi_feedback, p1):
    """
    Executes Phase 2 (Candidate Identification & Building Assignment), including:
    - Initializing output sinks and completion details
    - Phase 1.5: hhcount Imputation from Building Points if null/zero
    - Scanning Previous EAs to classify Delineation & Merge candidates
    - Identifying contiguous merge partners
    - Building candidate-only temporal spatial indexes
    - Matching building points to candidate EAs
    - Preview mode early exit handling

    Returns state dictionary containing candidate maps, sinks, counts, and building indexes.
    """
    barangay_source = p1["barangay_source"]
    building_source = p1["building_source"]
    previous_ea_source = p1["previous_ea_source"]
    gap_source = p1["gap_source"]
    overlap_source = p1["overlap_source"]
    min_household = p1["min_household"]
    max_household = p1["max_household"]
    target_household = p1["target_household"]
    target_crs = p1["target_crs"]
    ea_id_field = p1["ea_id_field"]
    household_field = p1["household_field"]
    bldg_hh_field = p1["bldg_hh_field"]
    barangay_id_field = p1["barangay_id_field"]
    bar_geocode_field = p1["bar_geocode_field"]
    eadel_indi_col_idx = p1["eadel_indi_col_idx"]
    merge_indi_col_idx = p1["merge_indi_col_idx"]
    all_ea_features = p1["all_ea_features"]
    special_ea_info = p1["special_ea_info"]
    special_ea_ids = p1["special_ea_ids"]
    output_layer_name = p1["output_layer_name"]
    geocode_prefix = output_layer_name.split("_")[0] if "_" in output_layer_name else "00000"
    transform = p1["transform"]
    preview_only = p1["preview_only"]
    barangay_index = p1["barangay_index"]
    barangay_by_id = p1["barangay_by_id"]
    _dc_geo_idx = p1["_dc_geo_idx"]

    def get_parent_barangay(ea_geom, b_index=None, b_by_id=None):
        idx = b_index if b_index is not None else barangay_index
        by_id = b_by_id if b_by_id is not None else barangay_by_id
        if idx is None or by_id is None or ea_geom is None or ea_geom.isEmpty():
            return None
        candidates = idx.intersects(ea_geom.boundingBox())
        max_overlap = -1.0
        parent_feat = None
        for cid in candidates:
            bar = by_id.get(cid)
            if not bar:
                continue
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
            if val is not None:
                res = normalize_to_8_digits(val)
                if res:
                    return res
        if _dc_geo_idx != -1:
            val = ea_feat.attribute(_dc_geo_idx)
            res = normalize_to_8_digits(val)
            if res:
                return res
        for f in ea_feat.fields():
            if f.name().lower() == "geocode":
                res = normalize_to_8_digits(ea_feat.attribute(f.name()))
                if res:
                    return res
        return "Unknown"

    # Create output schema (inherits all fields from previous_ea_source)
    out_fields = QgsFields(previous_ea_source.fields())

    output_hh_field = "household"
    if household_field in [f.name() for f in out_fields]:
        output_hh_field = household_field
    else:
        out_fields.append(create_qgs_field(output_hh_field, QVariant.Double))

    for fname, ftype in (
        ("map_uuid", QVariant.String),
        ("region", QVariant.String),
        ("province", QVariant.String),
        ("city_mun", QVariant.String),
        ("barangay", QVariant.String),
        ("code", QVariant.String),
        ("name", QVariant.String),
        ("ean", QVariant.String),
        ("sy", QVariant.String),
        ("new_ean", QVariant.String),
        ("bldgcount", QVariant.Int),
        ("hhcount", QVariant.Double),
        ("hh_count", QVariant.Double),
        ("bldg_count", QVariant.Int),
        ("bldgpoints_value", QVariant.Double),
        ("split_by", QVariant.String),
        ("correspondence_ea_geocode", QVariant.String),
        ("ea_type", QVariant.String),
        ("special_type", QVariant.String),
        ("source_id", QVariant.String),
        ("indicator", QVariant.String),
        ("gps", QVariant.String),
        ("min_circle", QVariant.String),
    ):
        if out_fields.indexOf(fname) == -1:
            out_fields.append(create_qgs_field(fname, ftype))

    if out_fields.indexOf("remarks") == -1:
        out_fields.append(create_qgs_field("remarks", QVariant.String))

    # Build export_fields containing ONLY the 18 standard output attributes
    export_field_names = [
        "fid", "map_uuid", "geocode", "region", "province",
        "city_mun", "barangay", "code", "name", "ean",
        "hhcount", "bldgcount", "sy", "new_ean", "hh_count",
        "bldg_count", "ea_type", "remarks"
    ]
    export_fields = QgsFields()
    for fname in export_field_names:
        if fname == "remarks":
            export_fields.append(create_qgs_field("remarks", QVariant.String))
            continue
        idx = out_fields.indexOf(fname)
        if idx != -1:
            export_fields.append(out_fields.at(idx))
        else:
            ftype = QVariant.String
            if fname == "fid":
                ftype = QVariant.Int
            elif fname == "hhcount":
                ftype = QVariant.Double
            elif fname in ("bldgcount", "bldg_count", "hh_count"):
                ftype = QVariant.Int
            export_fields.append(create_qgs_field(fname, ftype))

    # Build merged_export_fields for merge_ea output layer (includes indicator, gps, min_circle)
    merged_export_fields = QgsFields(export_fields)
    for fname in ("indicator", "gps", "min_circle"):
        if merged_export_fields.indexOf(fname) == -1:
            merged_export_fields.append(create_qgs_field(fname, QVariant.String))

    out_wkb_type = QgsWkbTypes.multiType(previous_ea_source.wkbType())

    delineated_sink = None
    delineated_dest_id = None
    if alg.DELINEATED_OUTPUT in parameters and parameters[alg.DELINEATED_OUTPUT] is not None:
        (delineated_sink, delineated_dest_id) = alg.parameterAsSink(
            parameters,
            alg.DELINEATED_OUTPUT,
            context,
            export_fields,
            out_wkb_type,
            target_crs,
        )

    merged_sink = None
    merged_dest_id = None
    if alg.MERGED_OUTPUT in parameters and parameters[alg.MERGED_OUTPUT] is not None:
        (merged_sink, merged_dest_id) = alg.parameterAsSink(
            parameters,
            alg.MERGED_OUTPUT,
            context,
            merged_export_fields,
            out_wkb_type,
            target_crs,
        )

    special_ea_export_fields = QgsFields()
    for f in export_fields:
        if f.name() in ("hhcount", "bldgcount"):
            continue
        special_ea_export_fields.append(f)
    if special_ea_export_fields.indexOf("special_type") == -1:
        special_ea_export_fields.append(create_qgs_field("special_type", QVariant.String))

    special_ea_sink = None
    special_ea_dest_id = None
    if alg.SPECIAL_EA_OUTPUT in parameters and parameters[alg.SPECIAL_EA_OUTPUT] is not None:
        (special_ea_sink, special_ea_dest_id) = alg.parameterAsSink(
            parameters,
            alg.SPECIAL_EA_OUTPUT,
            context,
            special_ea_export_fields,
            out_wkb_type,
            target_crs,
        )

    extracted_buildings_sink = None
    extracted_buildings_dest_id = None
    if alg.EXTRACTED_BUILDINGS_OUTPUT in parameters and parameters[alg.EXTRACTED_BUILDINGS_OUTPUT] is not None:
        bldg_out_fields = QgsFields(building_source.fields())
        if bldg_out_fields.indexOf("parent_ean") == -1:
            bldg_out_fields.append(create_qgs_field("parent_ean", QVariant.String))

        bldgpts_idx = bldg_out_fields.indexOf("bldgpoints_value")
        if bldgpts_idx == -1:
            bldgpts_idx = bldg_out_fields.indexOf("bldgpts_val")
        if bldgpts_idx == -1:
            bldg_out_fields.append(create_qgs_field("bldgpoints_value", QVariant.Double))

        pop_out_idx = bldg_out_fields.indexOf("pop")
        if pop_out_idx == -1:
            pop_out_idx = bldg_out_fields.indexOf(bldg_hh_field)
        if pop_out_idx == -1:
            bldg_out_fields.append(create_qgs_field("pop", QVariant.Double))

        (extracted_buildings_sink, extracted_buildings_dest_id) = alg.parameterAsSink(
            parameters,
            alg.EXTRACTED_BUILDINGS_OUTPUT,
            context,
            bldg_out_fields,
            building_source.wkbType(),
            target_crs,
        )

    delin_candidate_sink = None
    delin_candidate_dest_id = None
    if alg.DELINEATION_CANDIDATE_OUTPUT in parameters and parameters[alg.DELINEATION_CANDIDATE_OUTPUT] is not None:
        delin_cand_fields = QgsFields(out_fields)
        if delin_cand_fields.indexOf("hhcount") == -1:
            delin_cand_fields.append(create_qgs_field("hhcount", QVariant.Double))
        if delin_cand_fields.indexOf("bldgcount") == -1:
            delin_cand_fields.append(create_qgs_field("bldgcount", QVariant.Int))
        if delin_cand_fields.indexOf("indicator") == -1 and delin_cand_fields.indexOf("eadel_indi") == -1:
            delin_cand_fields.append(create_qgs_field("indicator", QVariant.String))
        (delin_candidate_sink, delin_candidate_dest_id) = alg.parameterAsSink(
            parameters,
            alg.DELINEATION_CANDIDATE_OUTPUT,
            context,
            delin_cand_fields,
            out_wkb_type,
            target_crs,
        )

    outputs = {}
    if delineated_dest_id is not None:
        outputs[alg.DELINEATED_OUTPUT] = delineated_dest_id
    if merged_dest_id is not None:
        outputs[alg.MERGED_OUTPUT] = merged_dest_id
    if delin_candidate_dest_id is not None:
        outputs[alg.DELINEATION_CANDIDATE_OUTPUT] = delin_candidate_dest_id
    if extracted_buildings_dest_id is not None:
        outputs[alg.EXTRACTED_BUILDINGS_OUTPUT] = extracted_buildings_dest_id
    if special_ea_dest_id is not None:
        outputs[alg.SPECIAL_EA_OUTPUT] = special_ea_dest_id

    delineated_feat_count = 0
    merged_feat_count = 0
    delin_candidate_feat_count = 0
    extracted_bldg_feat_count = 0

    try:
        if delineated_dest_id and context.willLoadLayerOnCompletion(delineated_dest_id):
            details = context.layerToLoadOnCompletionDetails(delineated_dest_id)
            details.name = f"{geocode_prefix}_delineated_ea2026"
            feedback.pushInfo(f"Set completion layer name to: {geocode_prefix}_delineated_ea2026")
    except Exception as e:
        feedback.pushInfo(f"Could not set delineated layer completion name: {str(e)}")

    try:
        if merged_dest_id and context.willLoadLayerOnCompletion(merged_dest_id):
            details = context.layerToLoadOnCompletionDetails(merged_dest_id)
            details.name = f"{geocode_prefix}_merged_ea2026"
            feedback.pushInfo(f"Set completion layer name to: {geocode_prefix}_merged_ea2026")
    except Exception as e:
        feedback.pushInfo(f"Could not set merged layer completion name: {str(e)}")

    try:
        if delin_candidate_dest_id and context.willLoadLayerOnCompletion(delin_candidate_dest_id):
            details = context.layerToLoadOnCompletionDetails(delin_candidate_dest_id)
            details.name = f"{geocode_prefix}_delineation_candidates_ea2026"
            feedback.pushInfo(f"Set completion layer name to: {geocode_prefix}_delineation_candidates_ea2026")
    except Exception as e:
        feedback.pushInfo(f"Could not set delineation candidate layer completion name: {str(e)}")

    try:
        if extracted_buildings_dest_id and context.willLoadLayerOnCompletion(extracted_buildings_dest_id):
            details = context.layerToLoadOnCompletionDetails(extracted_buildings_dest_id)
            details.name = f"{geocode_prefix}_extracted_buildings_ea2026"
            feedback.pushInfo(f"Set completion layer name to: {geocode_prefix}_extracted_buildings_ea2026")
    except Exception as e:
        feedback.pushInfo(f"Could not set extracted buildings layer completion name: {str(e)}")

    try:
        if special_ea_dest_id and context.willLoadLayerOnCompletion(special_ea_dest_id):
            details = context.layerToLoadOnCompletionDetails(special_ea_dest_id)
            details.name = f"{geocode_prefix}_special_ea"
            feedback.pushInfo(f"Set completion layer name to: {geocode_prefix}_special_ea")
    except Exception as e:
        feedback.pushInfo(f"Could not set special EA layer completion name: {str(e)}")

    # Transform target for output/candidates
    barangay_to_target = None
    if previous_ea_source.sourceCrs() != target_crs:
        feedback.pushInfo(f"Transforming output/candidates to {target_crs.authid()}...")
        barangay_to_target = QgsCoordinateTransform(
            previous_ea_source.sourceCrs(), target_crs, context.transformContext()
        )

    feedback.pushInfo(f"Previous EA Source CRS: {previous_ea_source.sourceCrs().authid()}")
    feedback.pushInfo(f"Target CRS: {target_crs.authid()}")
    feedback.pushInfo(f"Household Threshold: {min_household} - {max_household} HH (Target: {target_household} HH)")

    previous_ea_count = len(all_ea_features)
    barangay_count = barangay_source.featureCount()
    building_count = building_source.featureCount()

    feedback.pushInfo(f"Input Barangay Count: {barangay_count}")
    feedback.pushInfo(f"Input Previous EA Count: {previous_ea_count}")
    feedback.pushInfo(f"Input Building Count: {building_count}")
    multi_feedback.setProgress(100)

    if multi_feedback.isCanceled():
        raise QgsProcessingException("Algorithm cancelled by user.")

    # ── Phase 1.5: hhcount Imputation from Building Points ───────────────────────
    _dc_pop_idx_imp = previous_ea_source.fields().indexOf(household_field)
    imputed_hhcount = {}
    eas_needing_imputation = []

    for _ea_feat in all_ea_features:
        _ea_hh_val = _ea_feat.attribute(_dc_pop_idx_imp) if _dc_pop_idx_imp != -1 else None
        _needs_imputation = False
        if _ea_hh_val is None or (isinstance(_ea_hh_val, QVariant) and _ea_hh_val.isNull()):
            _needs_imputation = True
        else:
            try:
                if float(_ea_hh_val) == 0.0:
                    _needs_imputation = True
            except (TypeError, ValueError):
                _needs_imputation = True

        if _needs_imputation and _ea_feat.geometry() and not _ea_feat.geometry().isEmpty():
            eas_needing_imputation.append(_ea_feat)

    if eas_needing_imputation:
        feedback.pushInfo(
            f"Phase 1.5: Imputing null/zero hhcount for {len(eas_needing_imputation)} EA(s) from building points..."
        )
        combined_imp_bbox = QgsRectangle()
        for _eaf in eas_needing_imputation:
            combined_imp_bbox.combineExtentWith(_eaf.geometry().boundingBox())

        imp_request = QgsFeatureRequest()
        if transform and not combined_imp_bbox.isEmpty():
            bldg_to_ea_tr = QgsCoordinateTransform(previous_ea_source.sourceCrs(), building_source.sourceCrs(), context.transformContext())
            imp_request.setFilterRect(bldg_to_ea_tr.transformBoundingBox(combined_imp_bbox))
        elif not combined_imp_bbox.isEmpty():
            imp_request.setFilterRect(combined_imp_bbox)

        _imp_bldg_index = QgsSpatialIndex()
        _imp_bldg_by_id = {}
        _imp_bldg_count = 0

        _imp_bldg_hh_field = household_field
        _bldg_fields = building_source.fields()
        if _bldg_fields.indexOf(_imp_bldg_hh_field) == -1:
            for _candidate_name in ["hhcount", "hh_count", "household", "household_count", "pop", "population"]:
                if _bldg_fields.indexOf(_candidate_name) != -1:
                    _imp_bldg_hh_field = _candidate_name
                    break

        _imp_bldg_hh_idx = _bldg_fields.indexOf(_imp_bldg_hh_field)

        for _bfeat in building_source.getFeatures(imp_request):
            if multi_feedback.isCanceled():
                raise QgsProcessingException("Algorithm cancelled by user.")
            _bgeom = _bfeat.geometry()
            if not _bgeom or _bgeom.isEmpty():
                continue
            if transform:
                _bgeom = QgsGeometry(_bgeom)
                _bgeom.transform(transform)
            _bpt = _bgeom.asPoint()
            _bpop_val = _bfeat.attribute(_imp_bldg_hh_idx) if _imp_bldg_hh_idx != -1 else None
            try:
                _bpop = float(_bpop_val) if _bpop_val is not None else 1.0
            except (TypeError, ValueError):
                _bpop = 1.0
            _bindex_feat = QgsFeature(_bfeat.id())
            _bindex_feat.setGeometry(_bgeom)
            _imp_bldg_index.addFeature(_bindex_feat)
            _imp_bldg_by_id[_bfeat.id()] = (_bpt, _bpop)
            _imp_bldg_count += 1

        for _ea_feat in eas_needing_imputation:
            _ea_geom = _ea_feat.geometry()
            _ea_bbox = _ea_geom.boundingBox()
            _nearby_bldg_ids = _imp_bldg_index.intersects(_ea_bbox)
            _total_bldg_hh = 0.0
            for _bid in _nearby_bldg_ids:
                if _bid not in _imp_bldg_by_id:
                    continue
                _bpt, _bpop = _imp_bldg_by_id[_bid]
                _bpt_geom = QgsGeometry.fromPointXY(_bpt)
                if _ea_geom.contains(_bpt_geom) or _ea_geom.intersects(_bpt_geom):
                    _total_bldg_hh += _bpop

            imputed_hhcount[_ea_feat.id()] = _total_bldg_hh
            feedback.pushInfo(
                f"  EA (FID={_ea_feat.id()}) imputed {_total_bldg_hh:.0f} HH from nearby building points."
            )
    else:
        feedback.pushInfo("Phase 1.5: All EAs contain valid hhcount. Skipping building imputation.")

    feedback.pushInfo(
        f"  hhcount imputation complete: {len(imputed_hhcount)} EA(s) imputed from building points."
    )

    # ── Phase 2: Identifying and saving delineation and merge candidates ──────────
    multi_feedback.setCurrentStep(1)
    multi_feedback.setProgressText(f"{_PHASE_LABELS[1]}...")

    feedback.pushInfo("Phase 2/8: Identifying and saving delineation and merge candidates...")
    delineation_candidate_ids = set()
    merge_candidate_ids = set()
    delineation_candidate_hhdivthres = {}
    delineation_candidates_by_geocode = {}
    delineation_candidate_bar_geocodes = set()

    _dc_pop_idx = previous_ea_source.fields().indexOf(household_field)
    if _dc_pop_idx == -1:
        raise QgsProcessingException("Error: The required 'hhcount' (or configured household) field does not exist in the input Previous EA layer.")

    total_ea_processed = 0
    total_delin_candidates = 0

    ea_to_target = None
    if previous_ea_source.sourceCrs() != target_crs:
        ea_to_target = QgsCoordinateTransform(
            previous_ea_source.sourceCrs(), target_crs, context.transformContext()
        )

    gap_index = None
    gap_features = []
    gap_to_ea_transform = None
    if gap_source is not None:
        gap_index = QgsSpatialIndex()
        for go_feat in gap_source.getFeatures():
            if go_feat.geometry() and not go_feat.geometry().isEmpty():
                gap_index.addFeature(go_feat)
                gap_features.append(go_feat)
        if gap_source.sourceCrs() != previous_ea_source.sourceCrs():
            gap_to_ea_transform = QgsCoordinateTransform(gap_source.sourceCrs(), previous_ea_source.sourceCrs(), context.transformContext())

    overlap_index = None
    overlap_features = []
    overlap_to_ea_transform = None
    if overlap_source is not None:
        overlap_index = QgsSpatialIndex()
        for go_feat in overlap_source.getFeatures():
            if go_feat.geometry() and not go_feat.geometry().isEmpty():
                overlap_index.addFeature(go_feat)
                overlap_features.append(go_feat)
        if overlap_source.sourceCrs() != previous_ea_source.sourceCrs():
            overlap_to_ea_transform = QgsCoordinateTransform(overlap_source.sourceCrs(), previous_ea_source.sourceCrs(), context.transformContext())

    # ── Calculate Special EA Household Counts from Building Points & Parent EA Deductions ──
    special_ea_hh = {}
    ea_to_special_ea_hh = {}

    if special_ea_ids:
        combined_spec_bbox = QgsRectangle()
        special_ea_feats_map = {}
        for feat in all_ea_features:
            if feat.id() in special_ea_ids and feat.geometry() and not feat.geometry().isEmpty():
                special_ea_feats_map[feat.id()] = feat
                combined_spec_bbox.combineExtentWith(feat.geometry().boundingBox())

        if special_ea_feats_map and not combined_spec_bbox.isEmpty():
            spec_bldg_req = QgsFeatureRequest()
            if transform:
                bldg_to_ea_tr = QgsCoordinateTransform(previous_ea_source.sourceCrs(), building_source.sourceCrs(), context.transformContext())
                spec_bldg_req.setFilterRect(bldg_to_ea_tr.transformBoundingBox(combined_spec_bbox))
            else:
                spec_bldg_req.setFilterRect(combined_spec_bbox)

            spec_bldg_idx = QgsSpatialIndex()
            spec_bldg_map = {}
            _spec_bldg_hh_idx = building_source.fields().indexOf(household_field)
            if _spec_bldg_hh_idx == -1:
                for _cname in ["hhcount", "hh_count", "household", "household_count", "pop", "population"]:
                    if building_source.fields().indexOf(_cname) != -1:
                        _spec_bldg_hh_idx = building_source.fields().indexOf(_cname)
                        break

            for _bfeat in building_source.getFeatures(spec_bldg_req):
                _bgeom = _bfeat.geometry()
                if not _bgeom or _bgeom.isEmpty():
                    continue
                if transform:
                    _bgeom = QgsGeometry(_bgeom)
                    _bgeom.transform(transform)
                _bpt = _bgeom.asPoint()
                _bpop_val = _bfeat.attribute(_spec_bldg_hh_idx) if _spec_bldg_hh_idx != -1 else None
                try:
                    _bpop = float(_bpop_val) if _bpop_val is not None else 1.0
                    if _bpop <= 0:
                        _bpop = 1.0
                except (TypeError, ValueError):
                    _bpop = 1.0

                _bindex_feat = QgsFeature(_bfeat.id())
                _bindex_feat.setGeometry(_bgeom)
                spec_bldg_idx.addFeature(_bindex_feat)
                spec_bldg_map[_bfeat.id()] = (_bpt, _bpop)

            for spec_fid, spec_feat in special_ea_feats_map.items():
                _s_geom = spec_feat.geometry()
                _s_nearby = spec_bldg_idx.intersects(_s_geom.boundingBox())
                _s_hh_sum = 0.0
                for _bid in _s_nearby:
                    if _bid not in spec_bldg_map:
                        continue
                    _bpt, _bpop = spec_bldg_map[_bid]
                    _bpt_geom = QgsGeometry.fromPointXY(_bpt)
                    if _s_geom.contains(_bpt_geom) or _s_geom.intersects(_bpt_geom):
                        _s_hh_sum += _bpop
                special_ea_hh[spec_fid] = _s_hh_sum
                if _dc_pop_idx != -1 and _dc_pop_idx < len(spec_feat.attributes()):
                    spec_feat.setAttribute(_dc_pop_idx, _s_hh_sum)

        for spec_fid, spec_info in special_ea_info.items():
            s_hh = special_ea_hh.get(spec_fid, spec_info.get('hh_count', 0.0))
            special_ea_hh[spec_fid] = s_hh
            for p_id in spec_info.get('parent_ea_ids', []):
                ea_to_special_ea_hh[p_id] = ea_to_special_ea_hh.get(p_id, 0.0) + s_hh

    for _dc_feat in previous_ea_source.getFeatures():
        if multi_feedback.isCanceled():
            raise QgsProcessingException("Algorithm cancelled by user.")
        total_ea_processed += 1
        yield_to_ui(total_ea_processed)

        _dc_hh = 0.0
        _dc_val = _dc_feat.attribute(_dc_pop_idx)
        if _dc_feat.id() in imputed_hhcount:
            _dc_hh = imputed_hhcount[_dc_feat.id()]
        elif _dc_val is None or (isinstance(_dc_val, QVariant) and _dc_val.isNull()):
            _dc_hh = 0.0
        else:
            try:
                _dc_hh = float(_dc_val)
            except (TypeError, ValueError):
                _dc_hh = 0.0

        _dc_ean = _dc_feat.attribute(ea_id_field)
        _dc_ean_str = str(_dc_ean).strip() if _dc_ean is not None else ""
        if _dc_ean_str.endswith(".0"):
            _dc_ean_str = _dc_ean_str[:-2]

        intersects_gap_or_overlap = False
        if _dc_feat.geometry() and not _dc_feat.geometry().isEmpty():
            if gap_index:
                candidates = gap_index.intersects(_dc_feat.geometry().boundingBox())
                for go_fid in candidates:
                    go_feat = next((f for f in gap_features if f.id() == go_fid), None)
                    if go_feat:
                        go_geom = go_feat.geometry()
                        if gap_to_ea_transform:
                            go_geom = QgsGeometry(go_geom)
                            go_geom.transform(gap_to_ea_transform)
                        if _dc_feat.geometry().intersects(go_geom):
                            intersects_gap_or_overlap = True
                            break
            if not intersects_gap_or_overlap and overlap_index:
                candidates = overlap_index.intersects(_dc_feat.geometry().boundingBox())
                for go_fid in candidates:
                    go_feat = next((f for f in overlap_features if f.id() == go_fid), None)
                    if go_feat:
                        go_geom = go_feat.geometry()
                        if overlap_to_ea_transform:
                            go_geom = QgsGeometry(go_geom)
                            go_geom.transform(overlap_to_ea_transform)
                        if _dc_feat.geometry().intersects(go_geom):
                            intersects_gap_or_overlap = True
                            break

        _orig_hh = _dc_hh
        _deducted_spec_hh = ea_to_special_ea_hh.get(_dc_feat.id(), 0.0)
        _effective_hh = max(0.0, _orig_hh - _deducted_spec_hh)

        is_delin = False
        is_merge = False

        if _orig_hh > max_household:
            if _effective_hh > max_household:
                is_delin = True
            else:
                feedback.pushInfo(
                    f"[EA {_dc_ean_str}] Special EA extracted (-{_deducted_spec_hh:.0f} HH). "
                    f"Adjusted HH ({_effective_hh:.0f}) dropped below max threshold ({max_household}). "
                    f"Exempted from delineation."
                )
                if _effective_hh <= min_household:
                    is_merge = True
                    feedback.pushInfo(
                        f"[EA {_dc_ean_str}] Adjusted HH ({_effective_hh:.0f}) is below min threshold ({min_household}). "
                        f"Added to merge candidates."
                    )
        elif _effective_hh <= min_household:
            is_merge = True
        elif eadel_indi_col_idx != -1:
            val = _dc_feat.attribute(eadel_indi_col_idx)
            if val is not None and str(val).strip().lower() in ("for delineation", "for_delineation"):
                if _effective_hh > max_household:
                    is_delin = True
                elif _effective_hh <= min_household:
                    is_merge = True

        if is_delin:
            total_delin_candidates += 1
            _dc_num_parts = max(2, int(math.ceil(_effective_hh / float(max_household)))) if _effective_hh > 0 else 2
            _dc_hhdivthres = 1.0 / _dc_num_parts
            delineation_candidate_ids.add(_dc_feat.id())
            delineation_candidate_hhdivthres[_dc_feat.id()] = _dc_hhdivthres
            _dc_geo = ""
            if _dc_geo_idx != -1:
                _dc_geo_val = _dc_feat.attribute(_dc_geo_idx)
                _dc_geo = str(_dc_geo_val).strip() if _dc_geo_val is not None else ""
            delineation_candidates_by_geocode.setdefault(_dc_geo, []).append(
                (_dc_ean_str, _dc_hhdivthres)
            )

            parent_bar = resolve_ea_parent_barangay(_dc_feat)
            if parent_bar and parent_bar != "Unknown":
                delineation_candidate_bar_geocodes.add(parent_bar)
        elif is_merge:
            merge_candidate_ids.add(_dc_feat.id())

    alg.total_ea_processed = total_ea_processed
    alg.total_delin_candidates = total_delin_candidates

    barangay_index = p1.get("barangay_index")

    def get_text_attr(feat: QgsFeature, candidate_names: list, prefer_text: bool = True):
        if not feat or not feat.isValid():
            return None
        fields = feat.fields()
        best_val = None
        for name in candidate_names:
            idx = fields.indexOf(name)
            if idx == -1:
                for j in range(fields.count()):
                    if fields.at(j).name().lower() == name.lower():
                        idx = j
                        break
            if idx != -1:
                val = feat.attribute(idx)
                if val is not None and val != NULL and not (isinstance(val, QVariant) and val.isNull()):
                    val_str = str(val).strip()
                    if val_str not in ('', 'NULL', 'None'):
                        if val_str.endswith(".0"):
                            val_str = val_str[:-2]
                        if prefer_text:
                            if not val_str.isdigit():
                                return val_str
                            elif best_val is None:
                                best_val = val_str
                        else:
                            return val_str
        return best_val

    def get_field_val(f: QgsFeature, fname, default=0):
        if not f or not f.isValid():
            return default
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
                if val is not None and val != NULL and not (isinstance(val, QVariant) and val.isNull()):
                    val_str = str(val).strip()
                    if val_str not in ('', 'NULL', 'None'):
                        try:
                            return float(val) if isinstance(default, float) or default is None else int(round(float(val)))
                        except (TypeError, ValueError):
                            return val
        return default

    def safe_float(val, default=0.0):
        if val is None or val == NULL or str(val).strip() in ('', 'NULL', 'None'):
            return default
        if isinstance(val, QVariant):
            if val.isNull():
                return default
            val = val.value()
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    def safe_int(val, default=0):
        if val is None or val == NULL or str(val).strip() in ('', 'NULL', 'None'):
            return default
        if isinstance(val, QVariant):
            if val.isNull():
                return default
            val = val.value()
        try:
            return int(round(float(val)))
        except (TypeError, ValueError):
            return default

    if delin_candidate_sink is not None:
        for feat in previous_ea_source.getFeatures():
            if multi_feedback.isCanceled():
                raise QgsProcessingException("Algorithm cancelled by user.")

            is_cand = feat.id() in delineation_candidate_ids
            if not is_cand:
                continue

            out_feat = QgsFeature(delin_cand_fields)
            _dc_geom = feat.geometry()
            if ea_to_target:
                _dc_geom = QgsGeometry(_dc_geom)
                _dc_geom.transform(ea_to_target)
            out_feat.setGeometry(_dc_geom)
            attrs = []
            for f in delin_cand_fields:
                orig_idx = feat.fields().indexOf(f.name())
                if orig_idx != -1:
                    attrs.append(feat.attribute(orig_idx))
                else:
                    attrs.append(None)
            out_feat.setAttributes(attrs)

            # Inherit and enrich standard attributes
            parent_bgy_feat = None
            if barangay_index is not None and feat.hasGeometry():
                parent_bgy_feat = get_parent_barangay(feat.geometry(), barangay_index, barangay_by_id)

            if parent_bgy_feat is None and parent_bar:
                for b_feat in barangay_by_id.values():
                    val = b_feat.attribute(bar_geocode_field)
                    if val is not None:
                        val_str = str(val).strip()
                        if val_str.endswith(".0"):
                            val_str = val_str[:-2]
                        if val_str == parent_bar or (len(val_str) >= 9 and len(parent_bar) >= 9 and val_str[:9] == parent_bar[:9]):
                            parent_bgy_feat = b_feat
                            break

            map_uuid_idx = delin_cand_fields.indexOf("map_uuid")
            if map_uuid_idx != -1:
                cur_uuid = out_feat.attribute(map_uuid_idx)
                if cur_uuid is None or cur_uuid == NULL or str(cur_uuid).strip() in ('', 'NULL', 'None'):
                    inh_uuid = (
                        get_text_attr(parent_bgy_feat, ["map_uuid", "mapuuid", "uuid", "map_id"], prefer_text=False)
                        or get_text_attr(feat, ["map_uuid", "mapuuid", "uuid", "map_id"], prefer_text=False)
                    )
                    if inh_uuid:
                        out_feat.setAttribute(map_uuid_idx, inh_uuid)

            region_idx = delin_cand_fields.indexOf("region")
            if region_idx != -1:
                cur_reg = out_feat.attribute(region_idx)
                if cur_reg is None or cur_reg == NULL or str(cur_reg).strip() in ('', 'NULL', 'None') or str(cur_reg).strip().isdigit():
                    reg_val = (
                        get_text_attr(parent_bgy_feat, ["region", "reg_name", "region_name", "reg_desc", "adm1_en", "reg", "region_n", "reg_n"])
                        or get_text_attr(feat, ["region", "reg_name", "region_name", "reg_desc", "adm1_en", "reg", "region_n", "reg_n"])
                    )
                    if reg_val:
                        out_feat.setAttribute(region_idx, reg_val)

            province_idx = delin_cand_fields.indexOf("province")
            if province_idx != -1:
                cur_prov = out_feat.attribute(province_idx)
                if cur_prov is None or cur_prov == NULL or str(cur_prov).strip() in ('', 'NULL', 'None') or str(cur_prov).strip().isdigit():
                    prov_val = (
                        get_text_attr(parent_bgy_feat, ["province", "prov_name", "province_name", "prov_desc", "adm2_en", "prov", "province_n", "prov_n"])
                        or get_text_attr(feat, ["province", "prov_name", "province_name", "prov_desc", "adm2_en", "prov", "province_n", "prov_n"])
                    )
                    if prov_val:
                        out_feat.setAttribute(province_idx, prov_val)

            city_mun_idx = delin_cand_fields.indexOf("city_mun")
            if city_mun_idx != -1:
                cur_cm = out_feat.attribute(city_mun_idx)
                if cur_cm is None or cur_cm == NULL or str(cur_cm).strip() in ('', 'NULL', 'None') or str(cur_cm).strip().isdigit():
                    cm_val = (
                        get_text_attr(parent_bgy_feat, ["city_mun", "citymun", "city_mun_name", "citymun_name", "municipality", "city_name", "mun_name", "city", "mun", "adm3_en", "mun_desc", "city_n", "mun_n"])
                        or get_text_attr(feat, ["city_mun", "citymun", "city_mun_name", "citymun_name", "municipality", "city_name", "mun_name", "city", "mun", "adm3_en", "mun_desc", "city_n", "mun_n"])
                    )
                    if cm_val:
                        out_feat.setAttribute(city_mun_idx, cm_val)

            barangay_idx = delin_cand_fields.indexOf("barangay")
            if barangay_idx != -1:
                cur_bgy = out_feat.attribute(barangay_idx)
                if cur_bgy is None or cur_bgy == NULL or str(cur_bgy).strip() in ('', 'NULL', 'None') or str(cur_bgy).strip().isdigit():
                    bgy_val = (
                        get_text_attr(parent_bgy_feat, ["barangay", "bgy_name", "brgy_name", "barangay_name", "bgy_desc", "brgy_desc", "adm4_en", "name", "bgy", "brgy", "barangay_n", "bgy_n", "brgy_n"])
                        or get_text_attr(feat, ["barangay", "bgy_name", "brgy_name", "barangay_name", "bgy_desc", "brgy_desc", "adm4_en", "name", "bgy", "brgy", "barangay_n", "bgy_n", "brgy_n"])
                    )
                    if bgy_val:
                        out_feat.setAttribute(barangay_idx, bgy_val)

            code_idx = delin_cand_fields.indexOf("code")
            if code_idx != -1:
                cur_code = out_feat.attribute(code_idx)
                if cur_code is None or cur_code == NULL or str(cur_code).strip() in ('', 'NULL', 'None'):
                    c_val = get_text_attr(feat, ["code", "ea_code", "eacode"], prefer_text=False)
                    if c_val:
                        out_feat.setAttribute(code_idx, str(c_val))

            hhcount_idx = delin_cand_fields.indexOf("hhcount")
            if hhcount_idx != -1:
                hh_names = ["hhcount", "new_hhcount", "hh_count", "hh_cnt", "household", "household_count", "pop", "population"]
                if household_field and household_field not in hh_names:
                    hh_names.insert(0, household_field)
                val_hh = get_field_val(feat, hh_names, 0.0)
                if feat.id() in ea_to_special_ea_hh:
                    val_hh = max(0.0, float(val_hh) - ea_to_special_ea_hh[feat.id()])
                out_feat.setAttribute(hhcount_idx, safe_float(val_hh, 0.0))

            bldgcount_idx = delin_cand_fields.indexOf("bldgcount")
            if bldgcount_idx != -1:
                bldg_names = ["bldgcount", "new_bldgcount", "bldg_count", "bldg_cnt", "bldgpts_cnt", "bldg_points", "building_count", "bldg_total", "buildings"]
                val_bldg = get_field_val(feat, bldg_names, 0)
                out_feat.setAttribute(bldgcount_idx, safe_int(val_bldg, 0))

            sy_idx = delin_cand_fields.indexOf("sy")
            if sy_idx != -1:
                out_feat.setAttribute(sy_idx, "2026")

            corr_ea_geo_idx = delin_cand_fields.indexOf("correspondence_ea_geocode")
            if corr_ea_geo_idx != -1:
                map_uuid_idx = delin_cand_fields.indexOf("map_uuid")
                geocode_idx = delin_cand_fields.indexOf("geocode")
                sy_idx = delin_cand_fields.indexOf("sy")
                map_uuid_val = out_feat.attribute(map_uuid_idx) if map_uuid_idx != -1 else ""
                geocode_val = out_feat.attribute(geocode_idx) if geocode_idx != -1 else ""
                sy_val = out_feat.attribute(sy_idx) if sy_idx != -1 else "2026"
                map_uuid_str = str(map_uuid_val) if map_uuid_val is not None else ""
                geocode_str = str(geocode_val) if geocode_val is not None else ""
                sy_str = str(sy_val) if (sy_val is not None and str(sy_val).strip() not in ('', 'NULL', 'None')) else "2026"
                if map_uuid_str.endswith(".0"): map_uuid_str = map_uuid_str[:-2]
                if geocode_str.endswith(".0"): geocode_str = geocode_str[:-2]
                if sy_str.endswith(".0"): sy_str = sy_str[:-2]
                out_feat.setAttribute(corr_ea_geo_idx, f"{map_uuid_str}:{geocode_str}:{sy_str}")

            eadel_indi_idx = delin_cand_fields.indexOf("indicator")
            if eadel_indi_idx == -1:
                eadel_indi_idx = delin_cand_fields.indexOf("eadel_indi")
            if eadel_indi_idx != -1:
                out_feat.setAttribute(eadel_indi_idx, "for_delineation" if is_cand else "ea_reference")

            fid_idx = delin_cand_fields.indexOf("fid")
            delin_cand_fid = delin_candidate_feat_count + 1
            if fid_idx != -1:
                out_feat.setAttribute(fid_idx, delin_cand_fid)
            out_feat.setId(delin_cand_fid)

            if delin_candidate_sink.addFeature(out_feat):
                delin_candidate_feat_count += 1

    feedback.pushInfo(
        f"Delineation Candidate Index: {len(delineation_candidate_ids)} EA(s) flagged "
        f"for delineation across {len(delineation_candidates_by_geocode)} barangay(s)."
    )

    alg.total_ea_processed = total_ea_processed
    alg.total_delin_candidates = total_delin_candidates

    feedback.pushInfo("Building full previous EA spatial index for merge partner lookup...")
    full_ea_index = QgsSpatialIndex()
    full_ea_by_id = {}
    for feat in previous_ea_source.getFeatures():
        full_ea_index.addFeature(feat)
        full_ea_by_id[feat.id()] = feat

    feedback.pushInfo("Identifying contiguous partners for Merge Candidates...")
    merge_candidates_by_geocode = {}
    adjacent_ea_ids = set()
    for feat in previous_ea_source.getFeatures():
        if multi_feedback.isCanceled():
            raise QgsProcessingException("Algorithm cancelled by user.")
        geom = feat.geometry()
        if not geom or geom.isEmpty():
            continue

        _dc_val = feat.attribute(_dc_pop_idx)
        if feat.id() in imputed_hhcount:
            _dc_hh = imputed_hhcount[feat.id()]
        elif _dc_val is None or (isinstance(_dc_val, QVariant) and _dc_val.isNull()):
            _dc_hh = 0.0
        else:
            try:
                _dc_hh = float(_dc_val)
            except (TypeError, ValueError):
                _dc_hh = 0.0

        if feat.id() in merge_candidate_ids:
            partners = []
            candidates = full_ea_index.intersects(geom.boundingBox())
            parent_bar_geo = resolve_ea_parent_barangay(feat)

            for cid in candidates:
                if cid == feat.id():
                    continue
                nb_feat = full_ea_by_id[cid]
                if geom.touches(nb_feat.geometry()) or geom.intersects(nb_feat.geometry()):
                    nb_parent_bar_geo = resolve_ea_parent_barangay(nb_feat)
                    p_bar = parent_bar_geo[:9] if len(parent_bar_geo) >= 9 else parent_bar_geo
                    nb_bar = nb_parent_bar_geo[:9] if len(nb_parent_bar_geo) >= 9 else nb_parent_bar_geo
                    if p_bar and nb_bar and p_bar == nb_bar:
                        nb_ean = nb_feat.attribute(ea_id_field)
                        nb_ean_str = str(nb_ean).strip() if nb_ean is not None else ""
                        if nb_ean_str.endswith(".0"):
                            nb_ean_str = nb_ean_str[:-2]
                        if nb_ean_str:
                            adjacent_ea_ids.add(nb_feat.id())

                        nb_hh = imputed_hhcount.get(nb_feat.id(), 0.0)
                        if nb_hh == 0.0:
                            nb_hh_val = nb_feat.attribute(_dc_pop_idx)
                            try:
                                nb_hh = float(nb_hh_val) if nb_hh_val is not None else 0.0
                            except (TypeError, ValueError):
                                nb_hh = 0.0
                        if nb_hh < max_household:
                            if nb_ean_str:
                                partners.append(nb_ean_str)

            _mc_ean = feat.attribute(ea_id_field)
            _mc_ean_str = str(_mc_ean).strip() if _mc_ean is not None else ""
            merge_candidates_by_geocode.setdefault(parent_bar_geo, []).append(
                (_mc_ean_str, _dc_hh, partners)
            )

    feedback.pushInfo("Building temporal previous EA index (candidates and adjacent EAs only)...")
    temp_ea_index = QgsSpatialIndex()
    temp_ea_by_id = {}
    for feat in all_ea_features:
        _ean = feat.attribute(ea_id_field)
        _ean_str = str(_ean).strip() if _ean is not None else ""
        if _ean_str.endswith(".0"):
            _ean_str = _ean_str[:-2]
        if feat.id() in delineation_candidate_ids or feat.id() in merge_candidate_ids or feat.id() in adjacent_ea_ids:
            temp_ea_index.addFeature(feat)
            temp_ea_by_id[feat.id()] = feat

    ea_index = temp_ea_index
    ea_by_id = temp_ea_by_id

    feedback.pushInfo("Assigning building points...")
    ea_geometries = {fid: feat.geometry() for fid, feat in ea_by_id.items()}
    ea_id_to_buildings = {}

    combined_bbox = QgsRectangle()
    for parent_feat in ea_by_id.values():
        if parent_feat.geometry() and not parent_feat.geometry().isEmpty():
            combined_bbox.combineExtentWith(parent_feat.geometry().boundingBox())

    bbox_transform = None
    if building_source.sourceCrs() != previous_ea_source.sourceCrs():
        bbox_transform = QgsCoordinateTransform(previous_ea_source.sourceCrs(), building_source.sourceCrs(), context.transformContext())

    if bbox_transform and not combined_bbox.isEmpty():
        combined_bbox = bbox_transform.transformBoundingBox(combined_bbox)

    request = QgsFeatureRequest()
    if not combined_bbox.isEmpty():
        request.setFilterRect(combined_bbox)

    bldg_processed_count = 0
    bldg_matched_count = 0

    for idx, feat in enumerate(building_source.getFeatures(request)):
        if multi_feedback.isCanceled():
            raise QgsProcessingException("Algorithm cancelled by user.")

        if idx % 2000 == 0:
            yield_to_ui(idx, 100)
            multi_feedback.setProgressText(f"{_PHASE_LABELS[1]} [Processed {idx:,} building points]...")

        bldg_processed_count += 1
        geom = feat.geometry()
        if geom and not geom.isEmpty():
            if transform:
                geom_clone = QgsGeometry(geom)
                geom_clone.transform(transform)
                p = geom_clone.asPoint()
            else:
                p = geom.asPoint()

            pt_geom = QgsGeometry.fromPointXY(p)

            candidate_ids = ea_index.intersects(pt_geom.boundingBox())
            if special_ea_ids:
                candidate_ids = sorted(candidate_ids, key=lambda fid: 0 if fid in special_ea_ids else 1)
            for parent_ea_id in candidate_ids:
                parent_geom = ea_geometries[parent_ea_id]
                if parent_geom.contains(pt_geom) or parent_geom.intersects(pt_geom):
                    pop_val = feat.attribute(bldg_hh_field)
                    if pop_val is None or (isinstance(pop_val, QVariant) and pop_val.isNull()) or str(pop_val).strip() == "":
                        pop_val = 1.0
                    else:
                        try:
                            pop_val = float(pop_val)
                            if pop_val <= 0.0:
                                pop_val = 1.0
                        except (TypeError, ValueError):
                            pop_val = 1.0

                    bldg_val = None
                    bldg_val_idx = feat.fields().indexOf("bldgpoints_value")
                    if bldg_val_idx == -1:
                        bldg_val_idx = feat.fields().indexOf("bldgpts_val")
                    if bldg_val_idx != -1:
                        b_val = feat.attribute(bldg_val_idx)
                        try:
                            bldg_val = float(b_val) if b_val is not None else None
                        except (TypeError, ValueError):
                            bldg_val = None

                    ea_id_to_buildings.setdefault(parent_ea_id, []).append({
                        'point': p,
                        'pop': pop_val,
                        'bldgpoints_value': bldg_val,
                        'attributes': feat.attributes()
                    })
                    bldg_matched_count += 1
                    break

    feedback.pushInfo(f"Matched {bldg_matched_count} of {bldg_processed_count} building points.")
    multi_feedback.setProgress(100)

    if multi_feedback.isCanceled():
        raise QgsProcessingException("Algorithm cancelled by user.")

    if preview_only:
        if extracted_buildings_sink is not None:
            feedback.pushInfo("Writing matched building points to extracted buildings output layer...")
            bldg_out_fields = QgsFields(building_source.fields())
            if bldg_out_fields.indexOf("parent_ean") == -1:
                bldg_out_fields.append(create_qgs_field("parent_ean", QVariant.String))

            bldgpts_idx = bldg_out_fields.indexOf("bldgpoints_value")
            if bldgpts_idx == -1:
                bldgpts_idx = bldg_out_fields.indexOf("bldgpts_val")
            if bldgpts_idx == -1:
                bldg_out_fields.append(create_qgs_field("bldgpoints_value", QVariant.Double))

            pop_out_idx = bldg_out_fields.indexOf("pop")
            if pop_out_idx == -1:
                pop_out_idx = bldg_out_fields.indexOf(bldg_hh_field)
            if pop_out_idx == -1:
                bldg_out_fields.append(create_qgs_field("pop", QVariant.Double))

            barangay_to_target = None
            if previous_ea_source.sourceCrs() != target_crs:
                barangay_to_target = QgsCoordinateTransform(
                    previous_ea_source.sourceCrs(), target_crs, context.transformContext()
                )

            bldg_written_preview = 0
            for parent_ea_id, buildings in ea_id_to_buildings.items():
                parent_feat = ea_by_id[parent_ea_id]
                parent_ean_val = parent_feat.attribute(ea_id_field)

                for b in buildings:
                    b_feat = QgsFeature(bldg_out_fields)
                    b_geom = QgsGeometry.fromPointXY(b['point'])
                    if barangay_to_target:
                        b_geom.transform(barangay_to_target)
                    b_feat.setGeometry(b_geom)

                    b_feat.setAttributes(b['attributes'])
                    attrs = b_feat.attributes()
                    needed = bldg_out_fields.count() - len(attrs)
                    bldg_fid = extracted_bldg_feat_count + 1
                    fid_idx_bldg = bldg_out_fields.indexOf("fid")
                    if fid_idx_bldg != -1 and fid_idx_bldg < len(attrs):
                        attrs[fid_idx_bldg] = bldg_fid

                    if needed > 0:
                        attrs.extend([None] * needed)
                        b_feat.setAttributes(attrs)
                    elif fid_idx_bldg != -1:
                        b_feat.setAttributes(attrs)

                    b_feat.setId(bldg_fid)
                    if fid_idx_bldg != -1:
                        b_feat.setAttribute(fid_idx_bldg, bldg_fid)

                    b_feat["parent_ean"] = str(parent_ean_val)

                    if "pop" in [f.name() for f in bldg_out_fields]:
                        b_feat["pop"] = b['pop']
                    elif bldg_hh_field in [f.name() for f in bldg_out_fields]:
                        b_feat[bldg_hh_field] = b['pop']

                    if "bldgpoints_value" in [f.name() for f in bldg_out_fields]:
                        b_feat["bldgpoints_value"] = b['bldgpoints_value']
                    elif "bldgpts_val" in [f.name() for f in bldg_out_fields]:
                        b_feat["bldgpts_val"] = b['bldgpoints_value']

                    if extracted_buildings_sink.addFeature(b_feat, QgsFeatureSink.Flag.FastInsert):
                        bldg_written_preview += 1
                        extracted_bldg_feat_count += 1
            feedback.pushInfo(f"Successfully wrote {bldg_written_preview} building features to output in preview mode.")

        feedback.pushInfo("PREVIEW ONLY check is active — exiting early after creating candidate layers.")
        preview_outputs = {}
        if delin_candidate_feat_count > 0 and delin_candidate_dest_id is not None:
            preview_outputs[alg.DELINEATION_CANDIDATE_OUTPUT] = delin_candidate_dest_id
        if extracted_bldg_feat_count > 0 and extracted_buildings_dest_id is not None:
            preview_outputs[alg.EXTRACTED_BUILDINGS_OUTPUT] = extracted_buildings_dest_id
        return {"preview_exit": True, "outputs": preview_outputs}

    return {
        "preview_exit": False,
        "outputs": outputs,
        "out_fields": out_fields,
        "export_fields": export_fields,
        "merged_export_fields": merged_export_fields,
        "special_ea_export_fields": special_ea_export_fields,
        "out_wkb_type": out_wkb_type,
        "delineated_sink": delineated_sink,
        "merged_sink": merged_sink,
        "special_ea_sink": special_ea_sink,
        "extracted_buildings_sink": extracted_buildings_sink,
        "delin_candidate_sink": delin_candidate_sink,
        "delineated_dest_id": delineated_dest_id,
        "merged_dest_id": merged_dest_id,
        "special_ea_dest_id": special_ea_dest_id,
        "extracted_buildings_dest_id": extracted_buildings_dest_id,
        "delin_candidate_dest_id": delin_candidate_dest_id,
        "delineated_feat_count": delineated_feat_count,
        "merged_feat_count": merged_feat_count,
        "delin_candidate_feat_count": delin_candidate_feat_count,
        "extracted_bldg_feat_count": extracted_bldg_feat_count,
        "delineation_candidate_ids": delineation_candidate_ids,
        "merge_candidate_ids": merge_candidate_ids,
        "delineation_candidate_hhdivthres": delineation_candidate_hhdivthres,
        "delineation_candidates_by_geocode": delineation_candidates_by_geocode,
        "delineation_candidate_bar_geocodes": delineation_candidate_bar_geocodes,
        "adjacent_ea_ids": adjacent_ea_ids,
        "imputed_hhcount": imputed_hhcount,
        "ea_index": ea_index,
        "ea_by_id": ea_by_id,
        "temp_ea_index": temp_ea_index,
        "temp_ea_by_id": temp_ea_by_id,
        "ea_id_to_buildings": ea_id_to_buildings,
        "output_hh_field": output_hh_field,
        "full_ea_by_id": full_ea_by_id,
        "special_ea_hh": special_ea_hh,
        "ea_to_special_ea_hh": ea_to_special_ea_hh,
    }
