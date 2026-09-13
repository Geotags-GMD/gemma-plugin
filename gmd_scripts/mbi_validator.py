from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFile,
    QgsProcessingParameterEnum,
    QgsProcessingException,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsSpatialIndex,
    QgsFeatureRequest,
    QgsCoordinateTransform,
    QgsProject,
    QgsFields,
    QgsWkbTypes,
    QgsVectorFileWriter,
    QgsVectorLayer,
    NULL,
)
from PyQt5.QtCore import QCoreApplication, QVariant
from PyQt5.QtGui import QIcon
import re
import os
from datetime import datetime


# =====================================================
# CONFIG
# =====================================================

# Field name candidate lists for robust attribute extraction
STATUS_CANDIDATES = ["mbi_status", "status", "STATUS", "MBI_STATUS", "mbi_stat"]
REMARKS_CANDIDATES = ["pso_remarks", "remarks", "REMARKS", "PSO_REMARKS", "mbi_remarks", "pso_remark"]
CASE_UUID_CANDIDATES = ["case_uuid", "uuid", "CASE_UUID", "UUID", "case_id", "CASE_ID", "id", "fid"]
INVOLVED_BGYS_CANDIDATES = ["involved_bgys", "involved_barangays", "INVOLVED_BGYS", "involved_bgy", "bgys", "barangays"]
NUM_BLDG_PTS_CANDIDATES = ["num_bldg_pts", "num_bldg_pt", "NUM_BLDG_PTS", "bldg_pts", "bldg_points", "building_points", "count_bldg"]
TYPE_CANDIDATES = ["mbi_type", "case_type", "type", "CASE_TYPE", "MBI_TYPE", "Type", "mbi_typ", "casetype"]

STATUS_FIELD = "mbi_status"
REMARKS_FIELD = "pso_remarks"
CASE_UUID_FIELD = "case_uuid"
INVOLVED_BGYS_FIELD = "involved_bgys"
NUM_BLDG_PTS_FIELD = "num_bldg_pts"
TYPE_FIELD = "mbi_type"          # distinguishes Gap vs Overlap vs Disputed within the Reference layer

# Keywords used to match mbi_type values case-insensitively (e.g. "1_Gap", "2_Overlap", "3_Disputed")
TYPE_KEYWORDS = {
    "GAP": "gap",
    "OVERLAP": "overlap",
    "DISPUTED": "disput",
}

# Statuses that mean "processor claims this case is resolved"
RESOLVED_STATUSES = {"1_Updated"}

CATEGORY_GPKG_LAYER_NAMES = {
    "status_mismatch": "status_mismatch",
    "mismatch_with_remarks": "mismatch_with_remarks",
    "pending_cases": "pending_cases",
    "new_cases": "new_cases",
    "still_active": "remaining_cases",
    "confirmed_resolved": "confirmed_resolved",
    "ambiguous": "manual_review",
    "no_status": "no_status",
    "disputed_areas": "disputed_areas",
}

GPKG_LAYER_OPTIONS = [
    ("status_mismatch", "Status Mismatch"),
    ("mismatch_with_remarks", "Mismatch with Remarks"),
    ("pending_cases", "Pending Cases"),
    ("new_cases", "New Cases"),
    ("still_active", "Remaining Cases"),
    ("confirmed_resolved", "Confirmed Resolved"),
    ("ambiguous", "Manual Review"),
    ("no_status", "No Status"),
    ("disputed_areas", "Disputed Areas"),
]

# Common field alias candidates for geographic attributes
GEOCODE_CANDIDATES = ["geocode", "GEOCODE", "psgc", "psgc_code", "code"]
REGION_CANDIDATES = ["region", "REGION", "Region", "reg_name", "reg"]
PROVINCE_CANDIDATES = ["province", "PROVINCE", "Province", "prov_name", "prov"]
CITY_MUN_CANDIDATES = ["city_mun", "CITY_MUN", "city/mun", "City_Mun", "city/municipality", "city_municipality", "municipality", "city", "citymun"]
BARANGAY_CANDIDATES = ["barangay", "BARANGAY", "Barangay", "bgy_name", "brgy_name", "bgy", "brgy", "BRGY"]

# Base name used for the auto-generated GeoPackage filename.
# Final filename pattern: ref_mbi_reviewed-YYYY-MM-DD_HH-MM-SS.gpkg
# (colons are not valid in Windows filenames, so time uses hyphens instead of ':')
GPKG_BASE_NAME = "ref_mbi_reviewed"


def build_timestamped_gpkg_path(folder):
    """
    Builds the full output path inside the given folder, with the
    filename forced to: ref_mbi_reviewed-YYYY-MM-DD_HH-MM-SS.gpkg
    The processor never gets to type or edit this filename -- the
    input parameter is a folder picker only (see GPKG_OUTPUT below).
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{GPKG_BASE_NAME}-{timestamp}.gpkg"
    return os.path.join(folder, filename)


# =====================================================
# UTILITIES
# =====================================================

def normalize(val):
    if val in (None, NULL):
        return ""
    return str(val).strip()


def extract_attr(feature, candidate_names):
    """
    Safely retrieves the first non-empty attribute value from a feature
    matching any of the candidate field names (case-insensitive fallback).
    """
    if feature is None:
        return ""
    fields = feature.fields()
    # Fast path: check exact candidate names first via fields.indexOf
    for name in candidate_names:
        idx = fields.indexOf(name)
        if idx != -1:
            val = feature.attribute(idx)
            if val not in (None, NULL, ""):
                return normalize(val)
    # Case-insensitive fallback
    lower_map = {fields.at(i).name().lower(): i for i in range(fields.count())}
    for name in candidate_names:
        idx = lower_map.get(name.lower())
        if idx is not None:
            val = feature.attribute(idx)
            if val not in (None, NULL, ""):
                return normalize(val)
    return ""


def safe_get(feature, field_name_or_candidates):
    if feature is None:
        return ""
    if isinstance(field_name_or_candidates, (list, tuple, set)):
        return extract_attr(feature, field_name_or_candidates)

    fields = feature.fields()
    idx = fields.indexOf(field_name_or_candidates)
    if idx != -1:
        return normalize(feature.attribute(idx))

    lower_name = field_name_or_candidates.lower()
    for i in range(fields.count()):
        if fields.at(i).name().lower() == lower_name:
            return normalize(feature.attribute(i))
    return ""


def get_layer_field(layer, candidates):
    """
    Returns the exact field name present in layer matching any candidate (case-insensitive).
    """
    if layer is None:
        return None
    fields = layer.fields()
    for cand in candidates:
        idx = fields.indexOf(cand)
        if idx != -1:
            return fields.at(idx).name()
    lower_map = {fields.at(i).name().lower(): fields.at(i).name() for i in range(fields.count())}
    for cand in candidates:
        cand_lower = cand.lower()
        if cand_lower in lower_map:
            return lower_map[cand_lower]
    return None


def layer_has_field(layer, field_name):
    if layer is None:
        return False
    if isinstance(field_name, (list, tuple, set)):
        return get_layer_field(layer, field_name) is not None
    fields = layer.fields()
    if fields.indexOf(field_name) != -1:
        return True
    lower_name = field_name.lower()
    for i in range(fields.count()):
        if fields.at(i).name().lower() == lower_name:
            return True
    return False


def get_geo_attrs(ref_feature, chk_feature=None):
    """
    Extracts geographic metadata (geocode, region, province, city_mun, barangay)
    preferring ref_feature first, with fallback to chk_feature.
    """
    geocode = extract_attr(ref_feature, GEOCODE_CANDIDATES) or extract_attr(chk_feature, GEOCODE_CANDIDATES)
    region = extract_attr(ref_feature, REGION_CANDIDATES) or extract_attr(chk_feature, REGION_CANDIDATES)
    province = extract_attr(ref_feature, PROVINCE_CANDIDATES) or extract_attr(chk_feature, PROVINCE_CANDIDATES)
    city_mun = extract_attr(ref_feature, CITY_MUN_CANDIDATES) or extract_attr(chk_feature, CITY_MUN_CANDIDATES)
    barangay = extract_attr(ref_feature, BARANGAY_CANDIDATES) or extract_attr(chk_feature, BARANGAY_CANDIDATES)
    return geocode, region, province, city_mun, barangay


def find_matching_layer_id(keywords, geom_types=None):
    """
    Scans QgsProject.instance() for loaded vector layers whose names match
    any of the specified keywords (case-insensitive) and match geom_types.
    Returns the matching layer's ID, or None if not found.
    """
    try:
        project = QgsProject.instance()
        if not project:
            return None
        for layer in project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                if geom_types is not None and layer.geometryType() not in geom_types:
                    continue
                name_lower = layer.name().lower()
                for kw in keywords:
                    if kw.lower() in name_lower:
                        return layer.id()
    except Exception:
        pass
    return None


def meaningful(val):
    if val in (None, NULL):
        return False
    txt = str(val).strip().lower()
    if txt in ("", "null", "none", "nan"):
        return False
    return len(re.findall(r"[a-z0-9]", txt)) >= 3


def get_num_bldg_pts(feature):
    if feature is None:
        return 0
    val_str = safe_get(feature, NUM_BLDG_PTS_CANDIDATES)
    if not val_str:
        return 0
    try:
        return int(float(val_str))
    except Exception:
        return 0


def is_disputed_value(val):
    if val in (None, NULL, ""):
        return False
    v = str(val).strip().lower()
    return "disput" in v or v.startswith("3_") or v.startswith("3 -") or v.startswith("3.") or v == "3"


def get_reference_subset(reference_layer, case_type):
    """
    Returns a materialized list of reference features matching the
    given case_type ('Gap' or 'Overlap'), based on the mbi_type/case_type field.
    Case-insensitive substring match, excluding Disputed cases.
    """
    if reference_layer is None:
        return []

    type_field = get_layer_field(reference_layer, TYPE_CANDIDATES)
    keyword = TYPE_KEYWORDS[case_type.upper()]

    if type_field is None:
        # No explicit type field -> return all features excluding explicit disputed statuses
        res = []
        for f in reference_layer.getFeatures():
            stat = safe_get(f, STATUS_CANDIDATES)
            if not is_disputed_value(stat):
                res.append(f)
        return res

    expr = f"lower(\"{type_field}\") LIKE '%{keyword}%'"
    try:
        request = QgsFeatureRequest().setFilterExpression(expr)
        features = list(reference_layer.getFeatures(request))
    except Exception:
        features = list(reference_layer.getFeatures())

    return [
        f for f in features
        if keyword in safe_get(f, type_field).lower()
        and not is_disputed_value(safe_get(f, type_field))
    ]


def get_disputed_subset(reference_layer):
    """
    Returns a materialized list of reference features matching Disputed
    cases based on mbi_type / case_type / status field (e.g. '3_Disputed', 'Disputed', '3_Dispute').
    """
    if reference_layer is None:
        return []

    type_field = get_layer_field(reference_layer, TYPE_CANDIDATES)

    disputed_features = []

    if type_field is not None:
        expr = f"lower(\"{type_field}\") LIKE '%disput%' OR lower(\"{type_field}\") LIKE '3_%' OR lower(\"{type_field}\") = '3'"
        try:
            request = QgsFeatureRequest().setFilterExpression(expr)
            features = list(reference_layer.getFeatures(request))
        except Exception:
            features = list(reference_layer.getFeatures())

        for f in features:
            val = safe_get(f, type_field)
            if is_disputed_value(val):
                disputed_features.append(f)
    else:
        # Check status or remarks fields if no type field is present
        for f in reference_layer.getFeatures():
            stat = safe_get(f, STATUS_CANDIDATES)
            if is_disputed_value(stat):
                disputed_features.append(f)

    return disputed_features


def spatial_match(checker_layer, reference_features, reference_crs):
    """
    For every checker feature, find all reference features (from the
    already-filtered reference_features list) whose geometry actually
    OVERLAPS it (shares interior area) — not just touches at a shared
    edge or vertex, which would wrongly link an adjacent-but-unrelated
    (genuinely new) case to a neighboring reference case.
    Returns a list of (checker_feat, [ref_feats]).
    """
    idx = QgsSpatialIndex()
    for rf in reference_features:
        if rf.hasGeometry() and not rf.geometry().isNull() and not rf.geometry().isEmpty():
            idx.addFeature(rf)

    tr = None
    if checker_layer.sourceCrs() != reference_crs and checker_layer.sourceCrs().isValid() and reference_crs.isValid():
        try:
            tr = QgsCoordinateTransform(checker_layer.sourceCrs(), reference_crs, QgsProject.instance().transformContext())
        except Exception:
            tr = None

    ref_by_id = {rf.id(): rf for rf in reference_features}

    results = []
    for cf in checker_layer.getFeatures():
        if not cf.hasGeometry() or cf.geometry().isNull() or cf.geometry().isEmpty():
            continue
        g = QgsGeometry(cf.geometry())
        if tr:
            try:
                g.transform(tr)
            except Exception:
                pass
        if g.isNull() or g.isEmpty():
            continue

        matched_refs = []
        try:
            candidate_ids = idx.intersects(g.boundingBox())
        except Exception:
            candidate_ids = []

        for rid in candidate_ids:
            rf = ref_by_id.get(rid)
            if rf is None or not rf.hasGeometry() or not rf.geometry():
                continue

            rgeom = rf.geometry()
            if rgeom.isNull() or rgeom.isEmpty():
                continue

            try:
                # Adjacent-only (shares boundary/vertex, no interior overlap) ->
                # NOT a real match.
                if rgeom.touches(g):
                    continue

                if rgeom.intersects(g):
                    overlap_geom = rgeom.intersection(g)
                    if overlap_geom and not overlap_geom.isEmpty() and overlap_geom.area() > 0:
                        matched_refs.append(rf)
            except Exception:
                # In case of GEOS topology exception on corrupted input geometry, try makeValid
                try:
                    vg = g.makeValid() if not g.isGeosValid() else g
                    vr = rgeom.makeValid() if not rgeom.isGeosValid() else rgeom
                    if vr and vg and not vr.touches(vg) and vr.intersects(vg):
                        overlap_geom = vr.intersection(vg)
                        if overlap_geom and not overlap_geom.isEmpty() and overlap_geom.area() > 0:
                            matched_refs.append(rf)
                except Exception:
                    pass

        results.append((cf, matched_refs))
    return results


def evaluate_reference_case(rf, spatially_confirmed, checker_available=True):
    """
    Runs attribute-based rules on a single reference feature.

    Returns (category, reason) where category is one of:
      "status_mismatch", "mismatch_with_remarks", "pending_cases",
      "still_active", "confirmed_resolved", "no_status"

    Categories:
      - pending_cases: ALL '2_Pending' cases, EXCEPT the one specific
        case below (0 building points + no remarks), which is a
        Status Mismatch instead.
      - status_mismatch: claimed resolved but detected by checker,
        '2_Pending' w/ 0 bldg pts and NO remarks (the only Pending
        case that does NOT go to Pending Cases), '1_Updated' w/
        nonzero bldg pts and no remarks, or not detected without
        justification.
      - mismatch_with_remarks: '1_Updated' with nonzero building points
        where remarks ARE present (review justification)
      - confirmed_resolved: '1_Updated' with 0 building points, not detected
      - no_status: status field is blank
      - still_active: legitimately open case that isn't Pending
        (kept for any other non-Pending, non-Updated status values)

    checker_available=False means no Checker layer was supplied for this case
    type at all, so spatially_confirmed carries no information. In that mode
    only attribute-driven verdicts are returned: a case is never reported as
    "no longer detected by Checker" or "Confirmed Resolved" on the strength of
    a comparison that was never run, and anything the attributes alone cannot
    settle falls through to still_active.
    """
    status = safe_get(rf, STATUS_CANDIDATES)
    bp = get_num_bldg_pts(rf)
    rem = safe_get(rf, REMARKS_CANDIDATES)
    has_remarks = meaningful(rem)
    is_pending = (status == "2_Pending") or ("pending" in status.lower())

    if status == "":
        return "no_status", "Reference case has no status value."

    # Pending cases: ALL go here, EXCEPT bp==0 with no remarks (-> Status Mismatch)
    if is_pending:
        if bp == 0 and not has_remarks:
            return "status_mismatch", "'2_Pending' with 0 num_bldg_pts and no justifying remarks."
        if bp == 0:
            return "pending_cases", "'2_Pending' with 0 num_bldg_pts; remarks present, please verify justification."
        if has_remarks:
            return "pending_cases", f"Status='{status}' with {bp} building point(s) and remarks."
        return "pending_cases", f"Status='{status}' with {bp} building point(s), no remarks."

    plain_reasons = []
    remarks_reasons = []

    # Rule A: claimed resolved, but checker still finds it
    if checker_available and status in RESOLVED_STATUSES and spatially_confirmed:
        plain_reasons.append(f"'{status}' but case still detected by Checker.")

    # Rule C: 1_Updated but still has building points
    if status in RESOLVED_STATUSES and bp != 0:
        if has_remarks:
            remarks_reasons.append(
                f"For Review of Remarks: Status='{status}' but has {bp} building point(s) remaining."
            )
        else:
            plain_reasons.append(
                f"Status='{status}' but has {bp} building point(s) remaining and no justifying remarks."
            )

    if plain_reasons:
        return "status_mismatch", "; ".join(plain_reasons + remarks_reasons)

    if remarks_reasons:
        return "mismatch_with_remarks", "; ".join(remarks_reasons)

    if not checker_available:
        return "still_active", (
            f"Status='{status}'; no Checker layer supplied for this case type, "
            "so spatial verification was skipped."
        )

    if status in RESOLVED_STATUSES and not spatially_confirmed:
        return "confirmed_resolved", f"Status='{status}' and no longer detected by Checker."

    if not spatially_confirmed:
        return "status_mismatch", f"Status='{status}' but case no longer detected by Checker."

    return "still_active", f"Status='{status}', case remains open (Remaining Case)."


def classify(checker_layer, reference_features, reference_crs):
    """
    Classifies cases into:
      - status_mismatch: attribute rules failed, no justification on record
      - mismatch_with_remarks: 1_Updated with building points, remarks present
      - pending_cases: ALL 2_Pending cases except bp==0+no remarks
      - no_status: reference case has a blank/missing status
      - still_active: matched by checker, legitimately open (Remaining Case)
      - new_cases: checker case has no genuine reference overlap at all
      - ambiguous: checker case overlaps more than one reference feature (Manual Review)
      - confirmed_resolved: reference marked resolved, checker no longer detects it
    """
    matches = spatial_match(checker_layer, reference_features, reference_crs)

    status_mismatch, mismatch_with_remarks, pending_cases, still_active, new_cases, ambiguous, no_status = [], [], [], [], [], [], []
    matched_ref_ids = set()

    for cf, matched_refs in matches:
        if len(matched_refs) == 0:
            new_cases.append(cf)
        elif len(matched_refs) == 1:
            rf = matched_refs[0]
            matched_ref_ids.add(rf.id())
            category, reason = evaluate_reference_case(rf, spatially_confirmed=True)
            if category == "status_mismatch":
                status_mismatch.append((cf, rf, reason))
            elif category == "mismatch_with_remarks":
                mismatch_with_remarks.append((cf, rf, reason))
            elif category == "pending_cases":
                pending_cases.append((cf, rf, reason))
            elif category == "no_status":
                no_status.append((cf, rf, reason))
            else:
                still_active.append((cf, rf, reason))
        else:
            for rf in matched_refs:
                matched_ref_ids.add(rf.id())
            ambiguous.append((cf, matched_refs))

    confirmed_resolved = []
    for rf in reference_features:
        if rf.id() in matched_ref_ids:
            continue
        category, reason = evaluate_reference_case(rf, spatially_confirmed=False)
        if category == "status_mismatch":
            status_mismatch.append((None, rf, reason))
        elif category == "mismatch_with_remarks":
            mismatch_with_remarks.append((None, rf, reason))
        elif category == "pending_cases":
            pending_cases.append((None, rf, reason))
        elif category == "confirmed_resolved":
            confirmed_resolved.append((rf, reason))
        elif category == "no_status":
            no_status.append((None, rf, reason))
        else:
            still_active.append((None, rf, reason))

    return {
        "status_mismatch": status_mismatch,
        "mismatch_with_remarks": mismatch_with_remarks,
        "pending_cases": pending_cases,
        "still_active": still_active,
        "new_cases": new_cases,
        "ambiguous": ambiguous,
        "confirmed_resolved": confirmed_resolved,
        "no_status": no_status,
    }


def output_fields():
    """
    Column order (fid is auto-managed by the output provider and always
    appears leftmost automatically -- it is intentionally not defined here):
    case_uuid, geocode, region, province, city_mun, barangay, mbi_type,
    ref_status, ref_remarks, ref_involved_bgys, ref_num_bldg_pts, remarks
    """
    fields = QgsFields()
    fields.append(QgsField("case_uuid", QVariant.String, len=100))
    fields.append(QgsField("geocode", QVariant.String, len=50))
    fields.append(QgsField("region", QVariant.String, len=100))
    fields.append(QgsField("province", QVariant.String, len=100))
    fields.append(QgsField("city_mun", QVariant.String, len=100))
    fields.append(QgsField("barangay", QVariant.String, len=100))
    fields.append(QgsField("mbi_type", QVariant.String, len=50))
    fields.append(QgsField("ref_status", QVariant.String, len=60))
    fields.append(QgsField("ref_remarks", QVariant.String, len=255))
    fields.append(QgsField("ref_involved_bgys", QVariant.String, len=255))
    fields.append(QgsField("ref_num_bldg_pts", QVariant.Int))
    fields.append(QgsField("remarks", QVariant.String, len=255))
    return fields


def make_feature(fields, geometry, mbi_type, remarks, case_uuid="", ref_feature=None, chk_feature=None):
    nf = QgsFeature(fields)
    if geometry is not None and not geometry.isNull() and not geometry.isEmpty():
        nf.setGeometry(QgsGeometry(geometry))
    final_uuid = case_uuid or safe_get(ref_feature, CASE_UUID_CANDIDATES) or safe_get(chk_feature, CASE_UUID_CANDIDATES)
    mbi_type_val = safe_get(ref_feature, TYPE_CANDIDATES) or safe_get(chk_feature, TYPE_CANDIDATES) or mbi_type
    geocode, region, province, city_mun, barangay = get_geo_attrs(ref_feature, chk_feature)

    nf.setAttribute("case_uuid", final_uuid)
    nf.setAttribute("geocode", geocode)
    nf.setAttribute("region", region)
    nf.setAttribute("province", province)
    nf.setAttribute("city_mun", city_mun)
    nf.setAttribute("barangay", barangay)
    nf.setAttribute("mbi_type", mbi_type_val)
    if ref_feature is not None:
        nf.setAttribute("ref_status", safe_get(ref_feature, STATUS_CANDIDATES))
        nf.setAttribute("ref_remarks", safe_get(ref_feature, REMARKS_CANDIDATES))
        nf.setAttribute("ref_involved_bgys", safe_get(ref_feature, INVOLVED_BGYS_CANDIDATES))
        nf.setAttribute("ref_num_bldg_pts", get_num_bldg_pts(ref_feature))
    nf.setAttribute("remarks", remarks)
    return nf


# =====================================================
# PROCESSING ALGORITHM
# =====================================================

class MbiValidatorAlgorithm(QgsProcessingAlgorithm):

    REF_LAYER = "REF_LAYER"
    CHK_GAP = "CHK_GAP"
    CHK_OVERLAP = "CHK_OVERLAP"

    COMBINE_GPKG = "COMBINE_GPKG"
    GPKG_OUTPUT = "GPKG_OUTPUT"
    GPKG_LAYERS = "GPKG_LAYERS"

    OUT_MISMATCH = "OUT_MISMATCH"
    OUT_MISMATCH_REMARKS = "OUT_MISMATCH_REMARKS"
    OUT_PENDING_CASES = "OUT_PENDING_CASES"
    OUT_NEW = "OUT_NEW"
    OUT_STILL = "OUT_STILL"
    OUT_RESOLVED = "OUT_RESOLVED"
    OUT_MANUAL_REVIEW = "OUT_MANUAL_REVIEW"
    OUT_NOSTATUS = "OUT_NOSTATUS"
    OUT_DISPUTED = "OUT_DISPUTED"

    def tr(self, string):
        return QCoreApplication.translate("MbiValidatorAlgorithm", string)

    def createInstance(self):
        return MbiValidatorAlgorithm()

    def name(self):
        return "mbi_validator"

    def displayName(self):
        return self.tr("MBI Validator")

    def group(self):
        return self.tr("1Map")

    def groupId(self):
        return "1map"

    def icon(self):
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons', 'mbi_validator.svg')
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return QIcon(":/images/themes/default/mActionFilter.svg")

    def shortHelpString(self):
        return self.tr(
            "Cross-checks a single combined Reference MBI layer (Gap, Overlap, "
            "and Disputed cases distinguished by the 'mbi_type' field) against "
            "separate Checker GAP / OVERLAP layers to flag status mismatches.\n\n"
            "Layer Auto-Detection:\n"
            "Automatically detects and pre-selects matching 'ref_mbi_cases', "
            "'Gaps', and 'Overlaps' polygon layers loaded in the active project.\n\n"
            "Spatial Matching Rules:\n"
            "A Checker case is only linked to a Reference case when it "
            "genuinely overlaps it in area — merely touching a neighboring "
            "Reference polygon's edge does NOT count as a match, so a truly "
            "new case sitting next to an old one is correctly classified as "
            "a New Case.\n\n"
            "Inputs:\n"
            "Reference layer is required. Leave a Checker input empty if "
            "that case type doesn't apply. Both Checker inputs may be left "
            "empty — the algorithm then runs an attribute-only review of the "
            "Reference layer, which still produces Pending Cases, No Status "
            "and Disputed Areas for export.\n\n"
            "GeoPackage Output:\n"
            "Optionally tick 'Save outputs as GeoPackage' and pick a destination "
            "folder (required only if checkbox is checked) — selected non-empty "
            "categories will be written as separate layers inside a single .gpkg file, "
            "automatically named 'ref_mbi_reviewed-YYYY-MM-DD_HH-MM-SS.gpkg' "
            "with the current timestamp.\n\n"
            "Outputs (only generated when containing at least one feature):\n"
            "- Status Mismatch: claimed resolved but still detected, Pending w/ 0 bldg pts and no remarks, or Updated w/ nonzero bldg pts and no remarks\n"
            "- Mismatch with Remarks: Updated w/ nonzero bldg pts but remarks ARE present (verify justification)\n"
            "- Pending Cases: all Pending status cases, except Pending w/ 0 bldg pts and no remarks (which goes to Status Mismatch instead)\n"
            "- New Cases: Checker case with no genuine Reference overlap\n"
            "- Remaining Cases: in Reference layer and detected by Checker (open cases, non-Pending), plus cases left unverified because no Checker layer was supplied for their type\n"
            "- Confirmed Resolved: claimed resolved and Checker agrees\n"
            "- No Status: Reference case with blank status\n"
            "- Manual Review: one Checker case overlaps multiple Reference cases\n"
            "- Disputed Areas: Reference layer boundary cases marked as 3_Disputed"
        )

    @staticmethod
    def _hidden_sink(name, description):
        """
        Builds an optional QgsProcessingParameterFeatureSink that behaves
        exactly like before (defaults to a temporary output, skipped
        entirely in processAlgorithm() when its category has no features)
        but is flagged Hidden so it never shows a row -- not even folded
        away under "Advanced Parameters" -- in the algorithm dialog.

        FlagHidden also removes the parameter from the dialog's normal
        "load resulting layer on completion" bookkeeping (that's driven
        by the "Open output file after running algorithm" checkbox,
        which no longer exists once hidden). To compensate, processAlgorithm()
        explicitly calls context.addLayerToLoadOnCompletion(...) for each
        of these sinks itself, so the temporary layers still get added to
        the project after a run even though there's no visible checkbox
        telling QGIS to do so.
        """
        param = QgsProcessingParameterFeatureSink(
            name, description, optional=True,
            defaultValue=QgsProcessing.TEMPORARY_OUTPUT)
        param.setFlags(param.flags() | QgsProcessingParameterDefinition.FlagHidden)
        return param

    def initAlgorithm(self, config=None):
        # Auto-detect default reference layer matching 'ref_mbi_cases' or 'ref_mbi' from active project
        default_ref = find_matching_layer_id(
            ["ref_mbi_cases", "ref_mbi"],
            [QgsWkbTypes.PolygonGeometry]
        )
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.REF_LAYER, self.tr("Reference layer (ref_mbi_cases)"),
            [QgsProcessing.TypeVectorPolygon],
            optional=False,
            defaultValue=default_ref))

        default_gap = find_matching_layer_id(
            ["gaps", "gap", "chk_gap", "checker_gap"],
            [QgsWkbTypes.PolygonGeometry]
        )
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.CHK_GAP, self.tr("Checker GAP layer"),
            [QgsProcessing.TypeVectorPolygon],
            optional=True,
            defaultValue=default_gap))

        default_overlap = find_matching_layer_id(
            ["overlaps", "overlap", "chk_overlap", "checker_overlap"],
            [QgsWkbTypes.PolygonGeometry]
        )
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.CHK_OVERLAP, self.tr("Checker OVERLAP layer"),
            [QgsProcessing.TypeVectorPolygon],
            optional=True,
            defaultValue=default_overlap))

        self.addParameter(QgsProcessingParameterBoolean(
            self.COMBINE_GPKG,
            self.tr("Save outputs as GeoPackage"),
            defaultValue=False))

        # Folder picker only -- no filename box, so the auto-generated
        # timestamped filename can never be edited by the processor.
        self.addParameter(QgsProcessingParameterFile(
            self.GPKG_OUTPUT,
            self.tr("Save Path"),
            behavior=QgsProcessingParameterFile.Folder,
            optional=True))

        self.addParameter(QgsProcessingParameterEnum(
            self.GPKG_LAYERS,
            self.tr("Layers to include in GeoPackage"),
            options=[label for _, label in GPKG_LAYER_OPTIONS],
            allowMultiple=True,
            defaultValue=list(range(len(GPKG_LAYER_OPTIONS))),
            optional=True))

        # --- Individual output sinks: process-wise these are unchanged
        # (still optional QgsProcessingParameterFeatureSink, still created
        # as temporary layers, still skipped when their category is empty
        # in processAlgorithm()). FlagHidden removes their rows from the
        # dialog completely (not even under "Advanced Parameters"), since
        # "Save outputs as GeoPackage" above is now the primary output
        # path. processAlgorithm() manually re-registers each one to load
        # on completion, so they still appear as temporary layers.
        self.addParameter(self._hidden_sink(self.OUT_MISMATCH, self.tr("Status Mismatch")))
        self.addParameter(self._hidden_sink(self.OUT_MISMATCH_REMARKS, self.tr("Mismatch with Remarks")))
        self.addParameter(self._hidden_sink(self.OUT_PENDING_CASES, self.tr("Pending Cases")))
        self.addParameter(self._hidden_sink(self.OUT_NEW, self.tr("New Cases")))
        self.addParameter(self._hidden_sink(self.OUT_STILL, self.tr("Remaining Cases")))
        self.addParameter(self._hidden_sink(self.OUT_RESOLVED, self.tr("Confirmed Resolved")))
        self.addParameter(self._hidden_sink(self.OUT_MANUAL_REVIEW, self.tr("Manual Review")))
        self.addParameter(self._hidden_sink(self.OUT_NOSTATUS, self.tr("No Status")))
        self.addParameter(self._hidden_sink(self.OUT_DISPUTED, self.tr("Disputed Areas")))

    def get_selected_enum_indices(self, parameters, name, context, default_all=None):
        try:
            val = self.parameterAsEnums(parameters, name, context)
            if isinstance(val, (list, tuple, set)):
                return list(val)
            if isinstance(val, int):
                return [val]
        except Exception:
            pass
        try:
            val = self.parameterAsInts(parameters, name, context)
            if isinstance(val, (list, tuple, set)):
                return list(val)
            if isinstance(val, int):
                return [val]
        except Exception:
            pass
        if parameters and name in parameters:
            p_val = parameters[name]
            if isinstance(p_val, (list, tuple, set)):
                return list(p_val)
            if isinstance(p_val, int):
                return [p_val]
        return default_all if default_all is not None else []

    def processAlgorithm(self, parameters, context, feedback):
        ref_layer = self.parameterAsVectorLayer(parameters, self.REF_LAYER, context)
        chk_g = self.parameterAsVectorLayer(parameters, self.CHK_GAP, context)
        chk_o = self.parameterAsVectorLayer(parameters, self.CHK_OVERLAP, context)
        combine_gpkg = self.parameterAsBoolean(parameters, self.COMBINE_GPKG, context)
        gpkg_folder = self.parameterAsFile(parameters, self.GPKG_OUTPUT, context)

        if ref_layer is None:
            raise QgsProcessingException(
                self.tr("Reference layer is required.")
            )

        # Both Checker layers are optional. With neither supplied the run is a
        # pure attribute review of the Reference layer -- no spatial matching is
        # possible, so no case is claimed to be "still detected" or "no longer
        # detected", but Pending Cases, No Status, Disputed Areas and the
        # attribute-only mismatches are still produced and can be exported.
        if not chk_g and not chk_o:
            feedback.pushInfo(self.tr(
                "No Checker layer supplied -- running an attribute-only review "
                "of the Reference layer. Spatial verification is skipped."
            ))

        if not get_layer_field(ref_layer, STATUS_CANDIDATES):
            raise QgsProcessingException(
                self.tr(f"Reference layer has no '{STATUS_FIELD}' field.")
            )

        if combine_gpkg and not gpkg_folder:
            raise QgsProcessingException(
                self.tr("Please choose a folder to save the GeoPackage.")
            )

        # Filename is always auto-generated -- never taken from user input.
        gpkg_path = build_timestamped_gpkg_path(gpkg_folder) if combine_gpkg else None

        ref_crs = ref_layer.sourceCrs()
        crs = chk_g.sourceCrs() if chk_g else (chk_o.sourceCrs() if chk_o else ref_crs)
        wkb = QgsWkbTypes.MultiPolygon
        fields = output_fields()

        # --- collect classified results across Gap/Overlap without writing yet ---
        # each entry: (geometry, case_type, remarks, case_uuid, ref_feature, chk_feature)
        collected = {
            "status_mismatch": [],
            "mismatch_with_remarks": [],
            "pending_cases": [],
            "new_cases": [],
            "still_active": [],
            "confirmed_resolved": [],
            "ambiguous": [],
            "no_status": [],
            "disputed_areas": [],
        }

        pairs = []
        if chk_g is not None:
            pairs.append(("Gap", chk_g))
        if chk_o is not None:
            pairs.append(("Overlap", chk_o))

        total = len(pairs) or 1
        step = 0

        for case_type, chk_layer in pairs:
            if feedback.isCanceled():
                break

            ref_features = get_reference_subset(ref_layer, case_type)

            result = classify(chk_layer, ref_features, ref_crs)

            for cf, rf, reason in result["status_mismatch"]:
                geom = cf.geometry() if cf is not None else rf.geometry()
                remarks = reason
                collected["status_mismatch"].append((geom, case_type, remarks, "", rf, cf))

            for cf, rf, reason in result["mismatch_with_remarks"]:
                geom = cf.geometry() if cf is not None else rf.geometry()
                remarks = reason
                collected["mismatch_with_remarks"].append((geom, case_type, remarks, "", rf, cf))

            for cf, rf, reason in result["pending_cases"]:
                geom = cf.geometry() if cf is not None else rf.geometry()
                remarks = reason
                collected["pending_cases"].append((geom, case_type, remarks, "", rf, cf))

            for cf in result["new_cases"]:
                remarks = "No matching reference case found."
                chk_uuid = safe_get(cf, CASE_UUID_CANDIDATES)
                collected["new_cases"].append((cf.geometry(), case_type, remarks, chk_uuid, None, cf))

            for cf, rf, reason in result["still_active"]:
                geom = cf.geometry() if cf is not None else rf.geometry()
                remarks = reason
                collected["still_active"].append((geom, case_type, remarks, "", rf, cf))

            for cf, rf, reason in result["no_status"]:
                geom = cf.geometry() if cf is not None else rf.geometry()
                remarks = reason
                collected["no_status"].append((geom, case_type, remarks, "", rf, cf))

            for rf, reason in result["confirmed_resolved"]:
                remarks = reason
                collected["confirmed_resolved"].append((rf.geometry(), case_type, remarks, "", rf, None))

            for cf, matched_refs in result["ambiguous"]:
                uuids = ", ".join(safe_get(rf, CASE_UUID_CANDIDATES) or str(rf.id()) for rf in matched_refs)
                remarks = f"Matches {len(matched_refs)} reference cases ({uuids}). Review manually."
                chk_uuid = safe_get(cf, CASE_UUID_CANDIDATES)
                collected["ambiguous"].append((cf.geometry(), case_type, remarks, chk_uuid, None, cf))

            step += 1
            feedback.setProgress(int(100 * step / total))

        # reference-only case types (no matching checker layer provided at all)
        for case_type, chk_layer in (("Gap", chk_g), ("Overlap", chk_o)):
            if chk_layer is None:
                for rf in get_reference_subset(ref_layer, case_type):
                    category, reason = evaluate_reference_case(
                        rf, spatially_confirmed=False, checker_available=False)
                    if category == "status_mismatch":
                        remarks = reason
                        collected["status_mismatch"].append((rf.geometry(), case_type, remarks, "", rf, None))
                    elif category == "mismatch_with_remarks":
                        remarks = reason
                        collected["mismatch_with_remarks"].append((rf.geometry(), case_type, remarks, "", rf, None))
                    elif category == "pending_cases":
                        remarks = reason
                        collected["pending_cases"].append((rf.geometry(), case_type, remarks, "", rf, None))
                    elif category == "confirmed_resolved":
                        remarks = reason
                        collected["confirmed_resolved"].append((rf.geometry(), case_type, remarks, "", rf, None))
                    elif category == "no_status":
                        remarks = reason
                        collected["no_status"].append((rf.geometry(), case_type, remarks, "", rf, None))
                    else:
                        remarks = reason
                        collected["still_active"].append((rf.geometry(), case_type, remarks, "", rf, None))

        # Collect disputed areas directly from the reference layer (mbi_type = 3_Disputed / matching 'disputed')
        for rf in get_disputed_subset(ref_layer):
            mbi_val = safe_get(rf, TYPE_CANDIDATES) or "3_Disputed"
            rem_val = safe_get(rf, REMARKS_CANDIDATES) or "Disputed boundary case."
            chk_uuid = safe_get(rf, CASE_UUID_CANDIDATES)
            collected["disputed_areas"].append((rf.geometry(), mbi_val, rem_val, chk_uuid, rf, None))

        counts = {k: len(v) for k, v in collected.items()}
        results = {}

        # --- temporary-layer sinks: ALWAYS produced for non-empty categories,
        # regardless of whether "Save outputs as GeoPackage" is ticked. This
        # is the same behaviour as before GeoPackage export was added.
        # Layer names double as the label shown in the Layers panel once loaded.
        output_map = (
            (self.OUT_MISMATCH, "status_mismatch", self.tr("Status Mismatch")),
            (self.OUT_MISMATCH_REMARKS, "mismatch_with_remarks", self.tr("Mismatch with Remarks")),
            (self.OUT_PENDING_CASES, "pending_cases", self.tr("Pending Cases")),
            (self.OUT_NEW, "new_cases", self.tr("New Cases")),
            (self.OUT_STILL, "still_active", self.tr("Remaining Cases")),
            (self.OUT_RESOLVED, "confirmed_resolved", self.tr("Confirmed Resolved")),
            (self.OUT_MANUAL_REVIEW, "ambiguous", self.tr("Manual Review")),
            (self.OUT_NOSTATUS, "no_status", self.tr("No Status")),
            (self.OUT_DISPUTED, "disputed_areas", self.tr("Disputed Areas")),
        )

        for out_key, coll_key, label in output_map:
            items = collected[coll_key]

            if not items:
                # skip creating this output entirely -> keeps Layers panel clean
                continue

            sink, dest_id = self.parameterAsSink(parameters, out_key, context, fields, wkb, crs)
            if sink is None:
                # user didn't set a destination for this optional output -> skip silently
                continue

            for item in items:
                geom, case_type, remarks, case_uuid, ref_feature = item[:5]
                chk_feature = item[5] if len(item) > 5 else None

                if geom is not None and not geom.isNull() and not geom.isEmpty():
                    if ref_feature is not None and chk_feature is None and ref_crs != crs:
                        t_geom = QgsGeometry(geom)
                        tr = QgsCoordinateTransform(ref_crs, crs, context.transformContext())
                        t_geom.transform(tr)
                        geom = t_geom

                sink.addFeature(
                    make_feature(fields, geom, case_type, remarks,
                                 case_uuid=case_uuid, ref_feature=ref_feature, chk_feature=chk_feature)
                )

            results[out_key] = dest_id

            # Because these sinks are FlagHidden, the dialog has no checkbox
            # to tell it "load this on completion" -- so we register it
            # ourselves. Without this, the temporary layer would be written
            # but never added to the Layers panel.
            context.addLayerToLoadOnCompletion(
                dest_id,
                QgsProcessingContext.LayerDetails(label, context.project(), out_key)
            )

        if combine_gpkg:
            # --- ADDITIONALLY write selected non-empty categories as layers
            # inside one GeoPackage. This happens alongside the temporary
            # layers above, not instead of them.
            selected_indices = self.get_selected_enum_indices(
                parameters, self.GPKG_LAYERS, context,
                default_all=list(range(len(GPKG_LAYER_OPTIONS)))
            )
            selected_categories = {
                GPKG_LAYER_OPTIONS[idx][0] for idx in selected_indices if 0 <= idx < len(GPKG_LAYER_OPTIONS)
            } if selected_indices is not None and len(selected_indices) > 0 else {k for k, _ in GPKG_LAYER_OPTIONS}

            first_written = True
            for coll_key, items in collected.items():
                if not items:
                    continue
                if coll_key not in selected_categories:
                    continue

                layer_name = CATEGORY_GPKG_LAYER_NAMES[coll_key]

                mem_layer = QgsVectorLayer(
                    f"MultiPolygon?crs={crs.authid()}",
                    layer_name, "memory"
                )
                mem_layer.dataProvider().addAttributes(fields)
                mem_layer.updateFields()

                feats = []
                for item in items:
                    geom, case_type, remarks, case_uuid, ref_feature = item[:5]
                    chk_feature = item[5] if len(item) > 5 else None

                    if geom is not None and not geom.isNull() and not geom.isEmpty():
                        if ref_feature is not None and chk_feature is None and ref_crs != crs:
                            t_geom = QgsGeometry(geom)
                            tr = QgsCoordinateTransform(ref_crs, crs, context.transformContext())
                            t_geom.transform(tr)
                            geom = t_geom

                    feats.append(
                        make_feature(mem_layer.fields(), geom, case_type, remarks,
                                     case_uuid=case_uuid, ref_feature=ref_feature, chk_feature=chk_feature)
                    )
                mem_layer.dataProvider().addFeatures(feats)
                mem_layer.updateExtents()

                save_options = QgsVectorFileWriter.SaveVectorOptions()
                save_options.driverName = "GPKG"
                save_options.layerName = layer_name
                save_options.fileEncoding = "UTF-8"
                if not first_written:
                    save_options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

                error = QgsVectorFileWriter.writeAsVectorFormatV3(
                    mem_layer, gpkg_path, QgsProject.instance().transformContext(), save_options
                )
                if error[0] != QgsVectorFileWriter.NoError:
                    raise QgsProcessingException(
                        self.tr(f"Failed to write layer '{layer_name}' to GeoPackage: {error[1]}")
                    )

                first_written = False

            feedback.pushInfo(self.tr(f"GeoPackage saved to: {gpkg_path}"))

        feedback.pushInfo(
            f"Status Mismatch: {counts['status_mismatch']} | Mismatch with Remarks: {counts['mismatch_with_remarks']} | "
            f"Pending Cases: {counts['pending_cases']} | "
            f"New Cases: {counts['new_cases']} | "
            f"Remaining Cases: {counts['still_active']} | No Status: {counts['no_status']} | "
            f"Confirmed Resolved: {counts['confirmed_resolved']} | Manual Review: {counts['ambiguous']} | "
            f"Disputed Areas: {counts['disputed_areas']}"
        )

        if combine_gpkg:
            results[self.GPKG_OUTPUT] = gpkg_path

        return results


# Backward compatibility alias
MBIStatusAuditAlgorithm = MbiValidatorAlgorithm