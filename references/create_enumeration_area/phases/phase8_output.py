# -*- coding: utf-8 -*-
"""
Phase 8: Output Feature Generation & Writing.
Spatially sorts EAs, cleans unsnapped boundary vertices, writes features to sinks,
and renders HTML execution summary tables.
"""

import math
import os
from typing import Dict, Any, List
from PyQt5.QtCore import QVariant
from qgis.core import (
    QgsFeatureSink,
    QgsProcessingException,
    QgsWkbTypes,
    QgsGeometry,
    QgsSpatialIndex,
    QgsFeature,
    QgsCoordinateTransform,
    QgsFields,
    QgsField,
    QgsProject,
    QgsVectorLayer,
    QgsPointXY,
    NULL,
)

from ..helpers.constants import _PHASE_LABELS, yield_to_ui, create_qgs_field
from ..helpers.geometry import get_polygons_from_geom, allocate_gaps_to_parts
from ..helpers.style import apply_qml_to_layer
from ..helpers.spatial import get_parent_barangay


def refine_split_line(geom: QgsGeometry, gap_tolerance: float, min_branch_len: float) -> QgsGeometry:
    """Return a refined QgsGeometry with gaps bridged and tiny branches pruned."""
    if geom is None or geom.isEmpty():
        return geom

    # Decompose into individual LineString parts
    parts = []
    flat = QgsWkbTypes.flatType(geom.wkbType())
    if flat == QgsWkbTypes.LineString:
        parts = [geom]
    elif flat == QgsWkbTypes.MultiLineString:
        parts = geom.asGeometryCollection()
    elif flat == QgsWkbTypes.GeometryCollection or geom.isMultipart():
        try:
            for part in geom.constParts():
                part_geom = QgsGeometry(part.clone())
                part_flat = QgsWkbTypes.flatType(part_geom.wkbType())
                if part_flat in (QgsWkbTypes.LineString, QgsWkbTypes.MultiLineString):
                    parts.append(part_geom)
        except Exception:
            pass
    else:
        return geom

    if len(parts) <= 1:
        return geom

    def endpoints(line_geom):
        pts = line_geom.asPolyline()
        if not pts or len(pts) < 2:
            return None, None
        return pts[0], pts[-1]

    def pt_dist(a, b):
        return math.sqrt((a.x() - b.x()) ** 2 + (a.y() - b.y()) ** 2)

    ep_map = {}
    for idx, part in enumerate(parts):
        s, e = endpoints(part)
        if s:
            ep_map[(idx, 0)] = s
        if e:
            ep_map[(idx, 1)] = e

    keys = list(ep_map.keys())
    connected = set()
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            ka, kb = keys[a], keys[b]
            if ka[0] == kb[0]:
                continue
            if pt_dist(ep_map[ka], ep_map[kb]) < 1e-8:
                connected.add(ka)
                connected.add(kb)

    dangling = [k for k in keys if k not in connected]
    bridge_segments = []
    bridged = set()

    for a in range(len(dangling)):
        for b in range(a + 1, len(dangling)):
            ka, kb = dangling[a], dangling[b]
            if ka[0] == kb[0]:
                continue
            if ka in bridged or kb in bridged:
                continue
            dist = pt_dist(ep_map[ka], ep_map[kb])
            if dist <= gap_tolerance:
                pa, pb = ep_map[ka], ep_map[kb]
                bridge = QgsGeometry.fromPolylineXY([pa, pb])
                if not bridge.isEmpty():
                    bridge_segments.append(bridge)
                bridged.add(ka)
                bridged.add(kb)

    pruned_indices = set()
    for idx, part in enumerate(parts):
        k_start = (idx, 0)
        k_end = (idx, 1)
        both_dangling = (k_start in dangling or k_start not in ep_map) and \
                        (k_end in dangling or k_end not in ep_map)
        if both_dangling and part.length() < min_branch_len:
            pruned_indices.add(idx)

    kept = [p for idx, p in enumerate(parts) if idx not in pruned_indices]
    all_geoms = kept + bridge_segments
    if not all_geoms:
        return geom

    refined = QgsGeometry.unaryUnion(all_geoms)
    if refined is None or refined.isEmpty():
        return geom
    result = refined.mergeLines()
    return result if result and not result.isEmpty() else refined


def clean_and_remove_holes(geometry: QgsGeometry, target_crs: Any, remove_holes: bool = True) -> QgsGeometry:
    if geometry.isEmpty():
        return geometry

    flat_type = QgsWkbTypes.flatType(geometry.wkbType())
    sliver_limit = 1e-9 if target_crs.isGeographic() else 1.0

    if flat_type == QgsWkbTypes.Polygon:
        poly_pts = geometry.asPolygon()
        if poly_pts:
            ext_poly = QgsGeometry.fromPolygonXY([poly_pts[0]])
            if ext_poly.area() >= sliver_limit:
                if remove_holes:
                    return ext_poly
                else:
                    return geometry
        return QgsGeometry()
    elif flat_type == QgsWkbTypes.MultiPolygon:
        multipoly_pts = geometry.asMultiPolygon()
        new_multipoly = []
        for poly in multipoly_pts:
            if poly:
                ext_poly = QgsGeometry.fromPolygonXY([poly[0]])
                if ext_poly.area() >= sliver_limit:
                    if remove_holes:
                        new_multipoly.append([poly[0]])
                    else:
                        new_multipoly.append(poly)
        if new_multipoly:
            return QgsGeometry.fromMultiPolygonXY(new_multipoly)
        return QgsGeometry()
    elif flat_type == QgsWkbTypes.GeometryCollection or geometry.isMultipart():
        parts = []
        for part in geometry.constParts():
            part_geom = QgsGeometry(part.clone())
            clean_part = clean_and_remove_holes(part_geom, target_crs, remove_holes)
            if not clean_part.isEmpty():
                parts.append(clean_part)
        if parts:
            collected = QgsGeometry.collectGeometry(parts)
            return collected
        return QgsGeometry()
    return geometry


def clean_unsnapped_vertices(eas_list: List[dict], snap_tolerance: float, road_geoms: dict, river_geoms: dict, barangay_by_id: dict):
    idx_spatial = QgsSpatialIndex()
    ea_map = {}
    for idx_ea, ea_item in enumerate(eas_list):
        f_ea = QgsFeature(idx_ea)
        f_ea.setGeometry(ea_item['geom'])
        idx_spatial.addFeature(f_ea)
        ea_map[idx_ea] = ea_item

    constraint_geoms = []
    for r in road_geoms.values():
        constraint_geoms.append(r)
    for r in river_geoms.values():
        constraint_geoms.append(r)
    for r in barangay_by_id.values():
        g_bar = r.geometry()
        if g_bar.isEmpty():
            continue
        flat_type_bar = QgsWkbTypes.flatType(g_bar.wkbType())
        if flat_type_bar == QgsWkbTypes.Polygon:
            for ring in g_bar.asPolygon():
                constraint_geoms.append(QgsGeometry.fromPolylineXY(ring))
        elif flat_type_bar == QgsWkbTypes.MultiPolygon:
            for part in g_bar.asMultiPolygon():
                for ring in part:
                    constraint_geoms.append(QgsGeometry.fromPolylineXY(ring))

    def lies_on_constraint(pt):
        pt_geom = QgsGeometry.fromPointXY(pt)
        for cg in constraint_geoms:
            if cg.distance(pt_geom) < 1e-7:
                return True
        return False

    modified = True
    iteration = 0
    max_iterations = 3

    while modified and iteration < max_iterations:
        modified = False
        iteration += 1

        for idx_ea, ea_item in ea_map.items():
            geom = ea_item['geom']
            if geom.isEmpty():
                continue

            flat_type = QgsWkbTypes.flatType(geom.wkbType())
            if flat_type not in (QgsWkbTypes.Polygon, QgsWkbTypes.MultiPolygon):
                continue

            neighbor_ids = idx_spatial.intersects(geom.boundingBox())
            neighbors = [ea_map[nid]['geom'] for nid in neighbor_ids if nid != idx_ea and not ea_map[nid]['geom'].isEmpty()]
            if not neighbors:
                continue

            neighbor_vertices = set()
            for n_geom in neighbors:
                n_type = QgsWkbTypes.flatType(n_geom.wkbType())
                if n_type == QgsWkbTypes.Polygon:
                    p_list = [n_geom.asPolygon()]
                elif n_type == QgsWkbTypes.MultiPolygon:
                    p_list = n_geom.asMultiPolygon()
                else:
                    continue

                for part_pts in p_list:
                    for ring_pts in part_pts:
                        for pt_val in ring_pts:
                            neighbor_vertices.add((round(pt_val.x(), 8), round(pt_val.y(), 8)))

            if flat_type == QgsWkbTypes.Polygon:
                parts_list = [geom.asPolygon()]
            else:
                parts_list = geom.asMultiPolygon()

            polygon_changed = False
            new_parts = []

            for part_idx, part_pts in enumerate(parts_list):
                new_rings = []
                for ring_idx, ring_pts in enumerate(part_pts):
                    pts = list(ring_pts)
                    if len(pts) <= 4:
                        new_rings.append(pts)
                        continue

                    n_pts = len(pts) - 1
                    pt_idx = 0

                    while pt_idx < n_pts:
                        if len(pts) <= 4:
                            break

                        pt_val = pts[pt_idx]
                        pt_rounded = (round(pt_val.x(), 8), round(pt_val.y(), 8))

                        if pt_rounded in neighbor_vertices:
                            pt_idx += 1
                            continue

                        if lies_on_constraint(pt_val):
                            pt_idx += 1
                            continue

                        pt_geom = QgsGeometry.fromPointXY(pt_val)
                        min_dist = float('inf')
                        for n_geom in neighbors:
                            dist_val = n_geom.distance(pt_geom)
                            if dist_val < min_dist:
                                min_dist = dist_val

                        if not (0.0 < min_dist <= snap_tolerance):
                            pt_idx += 1
                            continue

                        candidate_pts = [p for idx_p, p in enumerate(pts) if idx_p != pt_idx]
                        if pt_idx == 0:
                            candidate_pts[-1] = candidate_pts[0]
                        elif pt_idx == n_pts - 1:
                            candidate_pts[0] = candidate_pts[-1]

                        test_parts = []
                        for p_p in new_parts:
                            test_parts.append(p_p)

                        current_test_rings = []
                        for r in new_rings:
                            current_test_rings.append(r)
                        current_test_rings.append(candidate_pts)
                        for r in part_pts[len(new_rings) + 1:]:
                            current_test_rings.append(r)
                        test_parts.append(current_test_rings)

                        for p_p in parts_list[len(new_parts) + 1:]:
                            test_parts.append(p_p)

                        if flat_type == QgsWkbTypes.Polygon:
                            temp_geom = QgsGeometry.fromPolygonXY(test_parts[0])
                        else:
                            temp_geom = QgsGeometry.fromMultiPolygonXY(test_parts)

                        if not temp_geom.isGeosValid() or temp_geom.isEmpty():
                            pt_idx += 1
                            continue

                        buildings_lost = False
                        for b in ea_item.get('buildings', []):
                            b_geom = QgsGeometry.fromPointXY(b['point'])
                            if not temp_geom.intersects(b_geom):
                                buildings_lost = True
                                break
                        if buildings_lost:
                            pt_idx += 1
                            continue

                        overlap_ok = True
                        for n_geom in neighbors:
                            old_overlap = geom.intersection(n_geom).area()
                            new_overlap = temp_geom.intersection(n_geom).area()
                            if new_overlap - old_overlap > 1e-9:
                                overlap_ok = False
                                break
                        if not overlap_ok:
                            pt_idx += 1
                            continue

                        pts = candidate_pts
                        n_pts = len(pts) - 1
                        polygon_changed = True
                        modified = True

                    new_rings.append(pts)
                new_parts.append(new_rings)

            if polygon_changed:
                old_geom = geom
                if flat_type == QgsWkbTypes.Polygon:
                    ea_item['geom'] = QgsGeometry.fromPolygonXY(new_parts[0])
                else:
                    ea_item['geom'] = QgsGeometry.fromMultiPolygonXY(new_parts)

                f_del = QgsFeature(idx_ea)
                f_del.setGeometry(old_geom)
                idx_spatial.deleteFeature(f_del)
                f_ea = QgsFeature(idx_ea)
                f_ea.setGeometry(ea_item['geom'])
                idx_spatial.addFeature(f_ea)


def run_phase_8(
    alg: Any,
    parameters: Dict[str, Any],
    context: Any,
    feedback: Any,
    multi_feedback: Any,
    p1: Dict[str, Any],
    p2: Dict[str, Any],
    p3: Dict[str, Any],
    p4: Dict[str, Any],
    p7: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Executes Phase 8: Spatial Sorting, Boundary Vertices Cleanup & Sink Feature Writing.
    """
    eas = list(p7.get("eas") or p7.get("split_eas", []))
    previous_ea_source = p1["previous_ea_source"]
    building_source = p1["building_source"]
    out_fields = p2.get("out_fields") if p2.get("out_fields") is not None else p1.get("out_fields")
    target_crs = p1["target_crs"]
    max_ea_number = p4.get("max_ea_number") if p4 else p1.get("max_ea_number", {})
    area_threshold = p1["area_threshold"]
    max_household = p1["max_household"]
    min_household = p1["min_household"]
    household_field = p1.get("household_field") or p2.get("household_field")
    bldgcount_field = p1.get("bldgcount_field")
    output_hh_field = p2.get("output_hh_field") or p1.get("output_hh_field", "household")
    bldg_hh_field = p1["bldg_hh_field"]
    ea_id_field = p1["ea_id_field"]
    barangay_by_id = p1["barangay_by_id"]

    delineation_candidate_ids = p2["delineation_candidate_ids"]
    merge_candidate_ids = p2["merge_candidate_ids"]
    adjacent_ea_ids = p2["adjacent_ea_ids"]
    special_ea_info = p2.get("special_ea_info", {})

    road_geoms = p3["road_geoms"]
    river_geoms = p3["river_geoms"]

    # Memory-only registry of all EA codes per delineation-candidate barangay (from Phase 4)
    barangay_sibling_ean_codes = p4.get("barangay_sibling_ean_codes", {})

    # Sinks & Count trackers from p2 (or p1)
    delineated_sink = p2.get("delineated_sink") or p1.get("delineated_sink")
    merged_sink = p2.get("merged_sink") or p1.get("merged_sink")
    special_ea_sink = p2.get("special_ea_sink") or p1.get("special_ea_sink")
    extracted_buildings_sink = p2.get("extracted_buildings_sink") or p1.get("extracted_buildings_sink")
    delineated_dest_id = p2.get("delineated_dest_id")
    merged_dest_id = p2.get("merged_dest_id")
    special_ea_dest_id = p2.get("special_ea_dest_id")
    extracted_buildings_dest_id = p2.get("extracted_buildings_dest_id")
    delin_candidate_dest_id = p2.get("delin_candidate_dest_id")
    delin_candidate_feat_count = p2.get("delin_candidate_feat_count", 0)
    extracted_bldg_feat_count = p2.get("extracted_bldg_feat_count", 0)

    export_fields = p2.get("export_fields")
    if not export_fields:
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

    merged_export_fields = p2.get("merged_export_fields")
    if not merged_export_fields:
        merged_export_fields = QgsFields(export_fields)
        for fname in ("indicator", "gps", "min_circle"):
            if merged_export_fields.indexOf(fname) == -1:
                merged_export_fields.append(create_qgs_field(fname, QVariant.String))

    special_ea_export_fields = p2.get("special_ea_export_fields")
    if not special_ea_export_fields:
        special_ea_export_fields = QgsFields()
        for f in export_fields:
            if f.name() in ("hhcount", "bldgcount"):
                continue
            special_ea_export_fields.append(f)
    if special_ea_export_fields.indexOf("special_type") == -1:
        special_ea_export_fields.append(create_qgs_field("special_type", QVariant.String))

    def make_export_feature(src_feat: QgsFeature, exp_fields: QgsFields) -> QgsFeature:
        exp_feat = QgsFeature(exp_fields)
        exp_feat.setGeometry(src_feat.geometry())
        exp_attrs = []
        src_flds = src_feat.fields()
        for f in exp_fields:
            idx = src_flds.indexOf(f.name())
            if idx == -1:
                for j in range(src_flds.count()):
                    if src_flds.at(j).name().lower() == f.name().lower():
                        idx = j
                        break
            if idx != -1:
                val = src_feat.attribute(idx)
            else:
                val = None
            if f.name().lower() == "sy":
                val = "2026"
            elif f.name().lower() in ("remarks", "remark", "delin_remark", "delin_remarks"):
                if val is None or val == NULL:
                    val = ""
            exp_attrs.append(val if val is not None else None)
        exp_feat.setAttributes(exp_attrs)
        return exp_feat

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

    delineated_feat_count = 0
    merged_feat_count = 0
    special_ea_feat_count = 0
    extracted_bldg_feat_count = 0
    split_by_counts = {}

    delin_candidate_feat_count = p2.get("delin_candidate_feat_count", len(delineation_candidate_ids))

    # Post-Processing: Spatial Barangay Sorting & Code Assignment
    feedback.pushInfo("Post-processing: Spatially sorting EAs within parent barangays and assigning new_ea codes...")

    barangay_to_final_eas = {}
    for ea in eas:
        bar = ea['parent_barangay']
        if bar not in barangay_to_final_eas:
            barangay_to_final_eas[bar] = []
        barangay_to_final_eas[bar].append(ea)

    def get_sort_key(ea_item):
        centroid = ea_item['geom'].centroid().asPoint()
        return (centroid.x(), centroid.y())

    bar_geocode_field = p1.get("bar_geocode_field", "geocode")

    # Accumulate (barangay_geocode, gap_geom, parent_bgy_feat) tuples for all internally detected
    # Barangay gaps and (barangay_geocode, overlap_geom, parent_bgy_feat) for EA-to-EA overlaps
    # so they can be written to SPECIAL_EA_OUTPUT after the main loop.
    internal_gap_geoms: list = []  # List[Tuple[str, QgsGeometry, Optional[QgsFeature]]]
    internal_overlap_geoms: list = []  # List[Tuple[str, QgsGeometry, Optional[QgsFeature]]]
    special_prefix_by_barangay: dict = {}  # Dict[str, int] tracked per barangay

    for bar in sorted(barangay_to_final_eas.keys(), key=lambda k: str(k) if k is not None else ""):
        bar_eas = barangay_to_final_eas[bar]

        # Resolve parent_bgy_feat first
        parent_bgy_feat = None
        bar_str = str(bar).strip() if bar is not None else ""
        if bar_str.endswith(".0"):
            bar_str = bar_str[:-2]
        for b_feat in barangay_by_id.values():
            val = b_feat.attribute(bar_geocode_field)
            if val is not None:
                val_str = str(val).strip()
                if val_str.endswith(".0"):
                    val_str = val_str[:-2]
                if val_str == bar_str or (len(val_str) >= 9 and len(bar_str) >= 9 and val_str[:9] == bar_str[:9]):
                    parent_bgy_feat = b_feat
                    break
        if parent_bgy_feat is None and isinstance(bar, int) and bar in barangay_by_id:
            parent_bgy_feat = barangay_by_id[bar]

        _bar_geocode = (
            get_text_attr(parent_bgy_feat, ["geocode"], prefer_text=False)
            or bar_str
        )
        if _bar_geocode.endswith(".0"):
            _bar_geocode = _bar_geocode[:-2]

        # 1. Detect any EA-to-EA overlaps within this barangay
        for _ea_i in range(len(bar_eas)):
            _g_i = bar_eas[_ea_i].get('geom')
            if not _g_i or _g_i.isEmpty():
                continue
            for _ea_j in range(_ea_i + 1, len(bar_eas)):
                _g_j = bar_eas[_ea_j].get('geom')
                if not _g_j or _g_j.isEmpty():
                    continue
                if _g_i.intersects(_g_j):
                    _inter = _g_i.intersection(_g_j)
                    if _inter and not _inter.isEmpty() and _inter.area() >= 1.0:
                        _inter_polys = get_polygons_from_geom(_inter)
                        for _ip in _inter_polys:
                            if _ip and not _ip.isEmpty() and _ip.area() >= 1.0:
                                internal_overlap_geoms.append((_bar_geocode, _ip, parent_bgy_feat))

        # 2. Allocate uncovered Barangay gaps into constituent EAs
        if parent_bgy_feat and parent_bgy_feat.geometry() and not parent_bgy_feat.geometry().isEmpty():
            bar_eas, _detected_gaps = allocate_gaps_to_parts(bar_eas, parent_bgy_feat.geometry())
            if _detected_gaps:
                for _gap_geom in _detected_gaps:
                    internal_gap_geoms.append((_bar_geocode, _gap_geom, parent_bgy_feat))

        # Determine maximum starting sequence (child YYY) already in use in this barangay.
        # Scan both the in-memory loaded EAs AND all sibling EA codes collected from the
        # full barangay in Phase 4 so new child numbers never collide with existing EAs.
        max_seq = max_ea_number.get(bar, 0)

        # 1. Scan loaded in-memory EAs
        for ea_item in bar_eas:
            code_str = str(ea_item.get('original_code', '')).strip()
            if code_str.endswith(".0"):
                code_str = code_str[:-2]
            digits = "".join([c for c in code_str if c.isdigit()])
            if len(digits) >= 3:
                try:
                    seq_val = int(digits[:3])
                    if seq_val > max_seq:
                        max_seq = seq_val
                except ValueError:
                    pass

        # 2. Scan sibling EAs in the same barangay (loaded from whole-barangay registry)
        bar_str_key = str(bar).strip() if bar is not None else ""
        if bar_str_key.endswith(".0"):
            bar_str_key = bar_str_key[:-2]
        sibling_codes = barangay_sibling_ean_codes.get(bar_str_key, [])
        for sib_code in sibling_codes:
            sib_digits = "".join([c for c in sib_code if c.isdigit()])
            # Each 6-digit EAN: last 3 digits are the child (YYY); first 3 are the parent (XXX)
            if len(sib_digits) == 6:
                try:
                    child_num = int(sib_digits[3:])
                    if child_num > max_seq:
                        max_seq = child_num
                    # Also track the parent (XXX) prefix max so new EAs don't reuse it
                    parent_num = int(sib_digits[:3])
                    if parent_num > max_seq:
                        max_seq = parent_num
                except ValueError:
                    pass
            elif len(sib_digits) >= 3:
                try:
                    seq_val = int(sib_digits[:3])
                    if seq_val > max_seq:
                        max_seq = seq_val
                except ValueError:
                    pass

        # Helper to extract parent 6-digit EA code and 3-digit prefix
        def extract_parent_code_and_prefix(ea_item):
            code_6 = ""
            attrs = ea_item.get('attributes', [])

            # 1. Priority 1: ean field (6-digit code e.g. 000000)
            ean_idx = out_fields.indexOf("ean")
            if ean_idx != -1 and ean_idx < len(attrs) and attrs[ean_idx] is not None:
                val_str = str(attrs[ean_idx]).strip()
                if val_str not in ('', 'NULL', 'None'):
                    if val_str.endswith(".0"):
                        val_str = val_str[:-2]
                    digits = "".join([c for c in val_str if c.isdigit()])
                    if len(digits) >= 6:
                        code_6 = digits[:6]
                    elif len(digits) > 0:
                        code_6 = digits.zfill(6)

            # 2. Priority 2: name field (prefix "EA " + 6-digit code e.g. EA 000000)
            if not code_6:
                name_idx = out_fields.indexOf("name")
                if name_idx != -1 and name_idx < len(attrs) and attrs[name_idx] is not None:
                    val_str = str(attrs[name_idx]).strip()
                    if val_str not in ('', 'NULL', 'None'):
                        if val_str.upper().startswith("EA"):
                            val_str = val_str[2:].strip()
                        digits = "".join([c for c in val_str if c.isdigit()])
                        if len(digits) >= 6:
                            code_6 = digits[:6]
                        elif len(digits) > 0:
                            code_6 = digits.zfill(6)

            # 3. Priority 3: geocode field (last 6 digits of 14-digit geocode e.g. 01801015000000 -> 000000)
            if not code_6:
                gc_idx = out_fields.indexOf("geocode")
                if gc_idx != -1 and gc_idx < len(attrs) and attrs[gc_idx] is not None:
                    val_str = str(attrs[gc_idx]).strip()
                    if val_str not in ('', 'NULL', 'None'):
                        if val_str.endswith(".0"):
                            val_str = val_str[:-2]
                        digits = "".join([c for c in val_str if c.isdigit()])
                        if len(digits) >= 6:
                            code_6 = digits[-6:]
                        elif len(digits) > 0:
                            code_6 = digits.zfill(6)

            if not code_6:
                orig_code = str(ea_item.get('original_code', '000000')).strip()
                if orig_code.endswith(".0"):
                    orig_code = orig_code[:-2]
                digits = "".join([c for c in orig_code if c.isdigit()])
                if len(digits) >= 6:
                    code_6 = digits[-6:]
                elif len(digits) > 0:
                    code_6 = digits.zfill(6)
                else:
                    code_6 = "000000"

            prefix_3 = code_6[:3] if len(code_6) >= 3 else "000"
            return code_6, prefix_3

        # Group EAs in this barangay by original parent feature ID
        parent_groups = {}
        for ea_item in bar_eas:
            pid = ea_item.get('original_id', id(ea_item))
            parent_groups.setdefault(pid, []).append(ea_item)

        # Step 1: Assign new_ea_code to non-special EAs first (retained, merged, delineated)
        for pid, group in parent_groups.items():
            if len(group) == 1:
                ea = group[0]
                if ea.get('is_special_ea', False) or ea.get('is_new', False):
                    continue  # Handled in Step 3 for Special EAs
                code_6, orig_last3 = extract_parent_code_and_prefix(ea)
                if ea.get('from_merge', False):
                    if not ea.get('new_ea_code'):
                        ea['new_ea_code'] = ea.get('original_code', '000000')
                else:
                    if orig_last3 == "000" or code_6 in ("000000", "000", "0"):
                        ea['new_ea_code'] = "000000"
                    elif len(code_6) == 6 and code_6.isdigit():
                        ea['new_ea_code'] = code_6
                    else:
                        ea['new_ea_code'] = orig_last3 + "000"
            else:
                # Delineated / Split parent EA:
                group.sort(key=lambda item: float(item.get('hh_count', 0.0)), reverse=True)
                sample_code, sample_orig = extract_parent_code_and_prefix(group[0])

                if sample_orig == "000" or sample_code in ("000000", "000", "0"):
                    # Special Rule for parent EA 000000 / 000:
                    # Largest hh_count gets 001000, 2nd largest gets 002000, 3rd gets 003000, etc.
                    for g_idx, ea in enumerate(group):
                        seq_num = g_idx + 1
                        seq_str = f"{seq_num:03d}"
                        ea['new_ea_code'] = seq_str + "000"
                        if seq_num > max_seq:
                            max_seq = seq_num
                else:
                    # Standard Rule for parent EA (e.g. 001 with existing 001, 002, 003):
                    # 1. Largest hh_count sub-EA gets parent_code + "000" (e.g. 001000)
                    # 2. Succeeding sub-EAs get parent_code + (max_seq + N) (e.g. 001004, 001005)
                    for g_idx, ea in enumerate(group):
                        _, orig_last3 = extract_parent_code_and_prefix(ea)
                        if g_idx == 0:
                            ea['new_ea_code'] = orig_last3 + "000"
                        else:
                            max_seq += 1
                            seq_str = f"{max_seq:03d}"
                            ea['new_ea_code'] = orig_last3 + seq_str

        # Step 2: Determine highest_prefix and highest_suffix among non-special EAs in barangay
        highest_prefix = 0
        highest_suffix = 0

        # Scan non-special EAs in bar_eas
        for ea_item in bar_eas:
            if ea_item.get('is_special_ea', False) or ea_item.get('is_new', False):
                continue
            c_val = str(ea_item.get('new_ea_code') or ea_item.get('original_code', '')).strip()
            if c_val.endswith(".0"):
                c_val = c_val[:-2]
            digits = "".join([c for c in c_val if c.isdigit()])
            if len(digits) == 6:
                try:
                    p_val = int(digits[:3])
                    s_val = int(digits[3:])
                    if p_val > highest_prefix:
                        highest_prefix = p_val
                    if s_val > highest_suffix:
                        highest_suffix = s_val
                except ValueError:
                    pass
            elif len(digits) >= 3:
                try:
                    p_val = int(digits[:3])
                    if p_val > highest_prefix:
                        highest_prefix = p_val
                except ValueError:
                    pass

        # Scan sibling EAs in whole barangay registry
        for sib_code in sibling_codes:
            sib_digits = "".join([c for c in str(sib_code) if c.isdigit()])
            if len(sib_digits) == 6:
                try:
                    p_val = int(sib_digits[:3])
                    s_val = int(sib_digits[3:])
                    if p_val > highest_prefix:
                        highest_prefix = p_val
                    if s_val > highest_suffix:
                        highest_suffix = s_val
                except ValueError:
                    pass
            elif len(sib_digits) >= 3:
                try:
                    p_val = int(sib_digits[:3])
                    if p_val > highest_prefix:
                        highest_prefix = p_val
                except ValueError:
                    pass

        # Step 3: Determine starting prefix for Special EAs:
        # If highest suffix > 0, prefix follows highest suffix + 1.
        # If highest suffix == 0 (e.g. only 000 suffixes), prefix follows highest prefix + 1.
        if highest_suffix > 0:
            special_prefix = highest_suffix + 1
        else:
            special_prefix = highest_prefix + 1

        # Step 4: Assign new_ea_code to Special EAs in bar_eas
        for pid, group in parent_groups.items():
            if len(group) == 1:
                ea = group[0]
                if ea.get('is_special_ea', False) or ea.get('is_new', False):
                    seq_str = f"{special_prefix:03d}"
                    ea['new_ea_code'] = f"{seq_str}000"
                    special_prefix += 1

        # Track special_prefix for this barangay so internally detected gaps/overlaps can continue numbering
        special_prefix_by_barangay[_bar_geocode] = special_prefix
        if bar_str:
            special_prefix_by_barangay[bar_str] = special_prefix

        # Re-sort all EAs in barangay spatially for sort_index
        has_delin = any(ea.get('original_id') in delineation_candidate_ids for ea in bar_eas)
        if has_delin:
            bar_eas.sort(key=get_sort_key)
        else:
            def get_original_order_key(ea_item):
                orig_id = ea_item.get('original_id', 99999999)
                centroid = ea_item['geom'].centroid().asPoint()
                return (orig_id, centroid.x())
            bar_eas.sort(key=get_original_order_key)

        for i, ea in enumerate(bar_eas):
            ea['new_ea_tracker'] = ea['new_ea_code']
            ea['sort_index'] = i

    # Phase 8: Output Generation & Writing
    if multi_feedback:
        multi_feedback.setCurrentStep(7)
        multi_feedback.setProgressText(f"{_PHASE_LABELS[7]} [0/{len(eas):,}]...")
    feedback.pushInfo("Phase 8/8: Writing output features...")

    source_crs = previous_ea_source.sourceCrs()
    v_tolerance = math.sqrt(area_threshold) * 0.1
    if source_crs.isGeographic():
        v_tolerance = max(1e-7, min(v_tolerance, 1e-5))
    else:
        v_tolerance = max(0.01, min(v_tolerance, 0.5))

    feedback.pushInfo("Cleaning up unsnapped vertices along shared boundaries...")
    clean_unsnapped_vertices(eas, v_tolerance, road_geoms, river_geoms, barangay_by_id)

    eas.sort(key=lambda ea: (
        str(ea.get('parent_barangay', '')) if ea.get('parent_barangay') is not None else '',
        ea.get('sort_index', 0)
    ))

    barangay_to_target = None
    if previous_ea_source.sourceCrs() != target_crs:
        feedback.pushInfo(f"Transforming output to {target_crs.authid()}...")
        t_ctx = context.transformContext() if context is not None else QgsProject.instance().transformContext()
        barangay_to_target = QgsCoordinateTransform(
            previous_ea_source.sourceCrs(), target_crs, t_ctx
        )

    barangay_index = p1.get("barangay_index")
    full_ea_by_id = {feat.id(): feat for feat in p1.get("all_ea_features", [])}

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

    final_geom_by_candidate = {}
    written_delineation_candidate_ids = set()

    for i, ea in enumerate(eas):
        if (multi_feedback and multi_feedback.isCanceled()) or (feedback and feedback.isCanceled()):
            raise QgsProcessingException("Algorithm cancelled by user.")
        yield_to_ui(i, 50)

        geom = QgsGeometry(ea['geom'])
        if barangay_to_target:
            geom.transform(barangay_to_target)

        geom = geom.makeValid()

        poly_parts = get_polygons_from_geom(geom)
        if not poly_parts:
            feedback.pushWarning(
                f"[Output] EA (code={ea.get('original_code', '?')}, "
                f"pop={ea.get('hh_count', '?')}) has no polygon geometry after "
                f"filtering — skipping feature."
            )
            continue

        geom = poly_parts[0]
        for p in poly_parts[1:]:
            geom = geom.combine(p)
        geom = geom.buffer(0.0, 3)
        geom.convertToMultiType()

        is_unchanged_retain = False
        if not ea.get('from_split', False) and not ea.get('from_merge', False):
            _ea_id = ea.get('original_id')
            if _ea_id not in delineation_candidate_ids and _ea_id not in merge_candidate_ids:
                is_unchanged_retain = True

        geom = clean_and_remove_holes(geom, target_crs, remove_holes=(not is_unchanged_retain))

        simp_tolerance = 1e-7 if target_crs.isGeographic() else 0.01
        geom = geom.simplify(simp_tolerance)
        geom = geom.makeValid()

        _ea_id = ea.get('original_id')
        if _ea_id in delineation_candidate_ids or ea.get('from_split', False):
            final_geom_by_candidate.setdefault(_ea_id, []).append((QgsGeometry(geom), ea))

        out_feat = QgsFeature(out_fields)
        out_feat.setGeometry(geom)
        attrs = list(ea.get('attributes') or [])
        if len(attrs) < out_fields.count():
            attrs.extend([None] * (out_fields.count() - len(attrs)))
        out_feat.setAttributes(attrs)

        parent_feat = full_ea_by_id.get(_ea_id)

        # 1. Primary: Spatial overlay with Barangay Layer
        parent_bgy_feat = None
        if barangay_index is not None:
            parent_bgy_feat = get_parent_barangay(ea.get('geom', geom), barangay_index, barangay_by_id)

        # 2. Secondary fallback: Attribute / Geocode match
        if parent_bgy_feat is None:
            bar = ea.get('parent_barangay')
            if bar is not None:
                bar_str = str(bar).strip()
                if bar_str.endswith(".0"):
                    bar_str = bar_str[:-2]
                for b_feat in barangay_by_id.values():
                    val = b_feat.attribute(bar_geocode_field)
                    if val is not None:
                        val_str = str(val).strip()
                        if val_str.endswith(".0"):
                            val_str = val_str[:-2]
                        if val_str == bar_str or (len(val_str) >= 9 and len(bar_str) >= 9 and val_str[:9] == bar_str[:9]):
                            parent_bgy_feat = b_feat
                            break
                if parent_bgy_feat is None and isinstance(bar, int) and bar in barangay_by_id:
                    parent_bgy_feat = barangay_by_id[bar]

        final_pop = ea.get('original_hhcount', ea.get('hh_count', 0.0)) if is_unchanged_retain else ea.get('hh_count', 0.0)

        pop_idx = out_fields.indexOf(output_hh_field)
        if pop_idx != -1 and output_hh_field.lower() not in ("hhcount", "bldgcount"):
            out_feat.setAttribute(pop_idx, final_pop)

        fid_idx = out_fields.indexOf("fid")
        cur_fid = i + 1
        if fid_idx != -1:
            out_feat.setAttribute(fid_idx, cur_fid)
        out_feat.setId(cur_fid)

        new_ea_idx = out_fields.indexOf("new_ean")
        if new_ea_idx == -1:
            new_ea_idx = out_fields.indexOf("new_ea")
        if new_ea_idx != -1:
            out_feat.setAttribute(new_ea_idx, ea.get('new_ea_tracker'))

        name_idx = out_fields.indexOf("name")
        if name_idx != -1:
            cur_name = out_feat.attribute(name_idx)
            if cur_name is None or cur_name == NULL or str(cur_name).strip() in ('', 'NULL', 'None'):
                inh_name = (
                    get_text_attr(parent_feat, ["name", "ean_name", "ea_name"], prefer_text=False)
                    or (f"EA {ea.get('original_code')}" if ea.get('original_code') else None)
                )
                if inh_name:
                    out_feat.setAttribute(name_idx, str(inh_name))

        geocode_idx = out_fields.indexOf("geocode")
        if geocode_idx != -1:
            cur_gc = out_feat.attribute(geocode_idx)
            inh_gc = (
                get_text_attr(parent_feat, ["geocode"], prefer_text=False)
                or get_text_attr(parent_bgy_feat, ["geocode"], prefer_text=False)
                or ea.get('parent_barangay')
            )
            if cur_gc is None or cur_gc == NULL or str(cur_gc).strip() in ('', 'NULL', 'None'):
                if inh_gc:
                    inh_gc_str = str(inh_gc).strip()
                    if inh_gc_str.endswith(".0"):
                        inh_gc_str = inh_gc_str[:-2]
                    out_feat.setAttribute(geocode_idx, inh_gc_str)
            else:
                gc_str = str(cur_gc).strip()
                if gc_str.endswith(".0"):
                    gc_str = gc_str[:-2]
                if inh_gc:
                    inh_gc_str = str(inh_gc).strip()
                    if inh_gc_str.endswith(".0"):
                        inh_gc_str = inh_gc_str[:-2]
                    if len(inh_gc_str) > len(gc_str) and (inh_gc_str.startswith(gc_str) or gc_str in inh_gc_str):
                        gc_str = inh_gc_str
                out_feat.setAttribute(geocode_idx, gc_str)

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

        # Inherit & enrich standard fields: map_uuid, region, province, city_mun, barangay, code
        map_uuid_idx = out_fields.indexOf("map_uuid")
        if map_uuid_idx != -1:
            cur_uuid = out_feat.attribute(map_uuid_idx)
            if cur_uuid is None or cur_uuid == NULL or str(cur_uuid).strip() in ('', 'NULL', 'None'):
                inh_uuid = (
                    get_text_attr(parent_bgy_feat, ["map_uuid", "mapuuid", "uuid", "map_id"], prefer_text=False)
                    or get_text_attr(parent_feat, ["map_uuid", "mapuuid", "uuid", "map_id"], prefer_text=False)
                )
                if inh_uuid:
                    out_feat.setAttribute(map_uuid_idx, inh_uuid)

        region_idx = out_fields.indexOf("region")
        if region_idx != -1:
            cur_reg = out_feat.attribute(region_idx)
            if cur_reg is None or cur_reg == NULL or str(cur_reg).strip() in ('', 'NULL', 'None') or str(cur_reg).strip().isdigit():
                reg_val = (
                    get_text_attr(parent_bgy_feat, ["region", "reg_name", "region_name", "reg_desc", "adm1_en", "reg", "region_n", "reg_n"])
                    or get_text_attr(parent_feat, ["region", "reg_name", "region_name", "reg_desc", "adm1_en", "reg", "region_n", "reg_n"])
                )
                if reg_val:
                    out_feat.setAttribute(region_idx, reg_val)

        province_idx = out_fields.indexOf("province")
        if province_idx != -1:
            cur_prov = out_feat.attribute(province_idx)
            if cur_prov is None or cur_prov == NULL or str(cur_prov).strip() in ('', 'NULL', 'None') or str(cur_prov).strip().isdigit():
                prov_val = (
                    get_text_attr(parent_bgy_feat, ["province", "prov_name", "province_name", "prov_desc", "adm2_en", "prov", "province_n", "prov_n"])
                    or get_text_attr(parent_feat, ["province", "prov_name", "province_name", "prov_desc", "adm2_en", "prov", "province_n", "prov_n"])
                )
                if prov_val:
                    out_feat.setAttribute(province_idx, prov_val)

        city_mun_idx = out_fields.indexOf("city_mun")
        if city_mun_idx != -1:
            cur_cm = out_feat.attribute(city_mun_idx)
            if cur_cm is None or cur_cm == NULL or str(cur_cm).strip() in ('', 'NULL', 'None') or str(cur_cm).strip().isdigit():
                cm_val = (
                    get_text_attr(parent_bgy_feat, ["city_mun", "citymun", "city_mun_name", "citymun_name", "municipality", "city_name", "mun_name", "city", "mun", "adm3_en", "mun_desc", "city_n", "mun_n"])
                    or get_text_attr(parent_feat, ["city_mun", "citymun", "city_mun_name", "citymun_name", "municipality", "city_name", "mun_name", "city", "mun", "adm3_en", "mun_desc", "city_n", "mun_n"])
                )
                if cm_val:
                    out_feat.setAttribute(city_mun_idx, cm_val)

        barangay_idx = out_fields.indexOf("barangay")
        if barangay_idx != -1:
            cur_bgy = out_feat.attribute(barangay_idx)
            if cur_bgy is None or cur_bgy == NULL or str(cur_bgy).strip() in ('', 'NULL', 'None') or str(cur_bgy).strip().isdigit():
                bgy_val = (
                    get_text_attr(parent_bgy_feat, ["barangay", "bgy_name", "brgy_name", "barangay_name", "bgy_desc", "brgy_desc", "adm4_en", "name", "bgy", "brgy", "barangay_n", "bgy_n", "brgy_n"])
                    or get_text_attr(parent_feat, ["barangay", "bgy_name", "brgy_name", "barangay_name", "bgy_desc", "brgy_desc", "adm4_en", "name", "bgy", "brgy", "barangay_n", "bgy_n", "brgy_n"])
                )
                if bgy_val:
                    out_feat.setAttribute(barangay_idx, bgy_val)

        code_idx = out_fields.indexOf("code")
        if code_idx != -1:
            cur_code = out_feat.attribute(code_idx)
            if cur_code is None or cur_code == NULL or str(cur_code).strip() in ('', 'NULL', 'None'):
                c_val = get_text_attr(parent_feat, ["code", "ea_code", "eacode"], prefer_text=False)
                if not c_val:
                    c_val = ea.get('new_ea_code') or ea.get('original_code')
                if c_val:
                    out_feat.setAttribute(code_idx, str(c_val))

        sy_idx = out_fields.indexOf("sy")
        if sy_idx != -1:
            out_feat.setAttribute(sy_idx, "2026")

        # Special EAs rule: if bldg_count is 0 or empty/null, hh_count must also be set to 0 or empty/null
        if ea.get('is_special_ea', False):
            special_bldgs = ea.get('buildings', [])
            raw_bldg_cnt = ea.get('bldg_count')
            if raw_bldg_cnt is None and not special_bldgs:
                # If explicitly None and no buildings
                if 'bldg_count' in ea and ea['bldg_count'] is None:
                    raw_bldg_cnt = None
                else:
                    raw_bldg_cnt = 0
            elif special_bldgs:
                raw_bldg_cnt = len(special_bldgs)

            if raw_bldg_cnt is None or (isinstance(raw_bldg_cnt, str) and raw_bldg_cnt.strip() in ('', 'NULL', 'None')):
                ea['bldg_count'] = None
                ea['hh_count'] = None
                val_bldg = None
                val_hh = None
                new_bldg_val = None
                new_hh_val = None
            elif safe_int(raw_bldg_cnt, 0) == 0:
                ea['bldg_count'] = 0
                ea['hh_count'] = 0.0
                val_bldg = 0
                val_hh = 0.0
                new_bldg_val = 0
                new_hh_val = 0
            else:
                ea['bldg_count'] = len(special_bldgs) if special_bldgs else safe_int(raw_bldg_cnt, 0)
                val_bldg = ea['bldg_count']
                new_bldg_val = val_bldg
                val_hh = safe_float(ea.get('hh_count', ea.get('original_hhcount', 0.0)), 0.0)
                new_hh_val = safe_int(val_hh, 0)
        else:
            val_hh = ea.get('original_hhcount')
            if val_hh is None:
                hh_names = ["hhcount", "new_hhcount", "hh_count", "hh_cnt", "household", "household_count", "pop", "population"]
                if household_field and household_field not in hh_names:
                    hh_names.insert(0, household_field)
                val_hh = get_field_val(parent_feat, hh_names, default=None)
            if val_hh is not None:
                val_hh = safe_float(val_hh, 0.0)
            else:
                cur_hh = None
                for j in range(out_fields.count()):
                    if out_fields.at(j).name().lower() == "hhcount":
                        cur_hh = out_feat.attribute(j)
                        if cur_hh is not None and cur_hh != NULL and str(cur_hh).strip() not in ('', 'NULL', 'None'):
                            break
                val_hh = safe_float(cur_hh, 0.0) if cur_hh is not None and str(cur_hh).strip() not in ('', 'NULL', 'None') else 0.0

            # Delineated EA bldgcount inherits directly from original_bldgcount / parent feature
            val_bldg = ea.get('original_bldgcount')
            if val_bldg is None:
                bldg_names = ["bldgcount", "new_bldgcount", "bldg_count", "bldg_cnt", "bldgpts_cnt", "bldg_points", "building_count", "bldg_total", "buildings", "bldgs", "total_bldg", "num_bldg"]
                if bldgcount_field and bldgcount_field not in bldg_names:
                    bldg_names.insert(0, bldgcount_field)
                val_bldg = get_field_val(parent_feat, bldg_names, default=None)
            if val_bldg is not None:
                val_bldg = safe_int(val_bldg, 0)
            else:
                cur_bldg = None
                for j in range(out_fields.count()):
                    if out_fields.at(j).name().lower() == "bldgcount":
                        cur_bldg = out_feat.attribute(j)
                        if cur_bldg is not None and cur_bldg != NULL and str(cur_bldg).strip() not in ('', 'NULL', 'None'):
                            break
                val_bldg = safe_int(cur_bldg, 0) if cur_bldg is not None and str(cur_bldg).strip() not in ('', 'NULL', 'None') else 0

            # hh_count holds the new calculated household count
            new_hh_val = safe_int(ea.get('hh_count', 0.0), 0)

            # bldg_count holds the new calculated building count
            new_bldg_val = safe_int(ea.get('bldg_count', len(ea.get('buildings', []))), 0)

        for j in range(out_fields.count()):
            if out_fields.at(j).name().lower() == "hhcount":
                out_feat.setAttribute(j, val_hh)
            elif out_fields.at(j).name().lower() == "hh_count":
                out_feat.setAttribute(j, new_hh_val)
            elif out_fields.at(j).name().lower() == "bldgcount":
                out_feat.setAttribute(j, val_bldg)
            elif out_fields.at(j).name().lower() == "bldg_count":
                out_feat.setAttribute(j, new_bldg_val)

        bldgpts_val_idx = out_fields.indexOf("bldgpoints_value")
        if bldgpts_val_idx != -1:
            out_feat.setAttribute(bldgpts_val_idx, ea.get('bldgpoints_value', 0.0))

        split_by_idx = out_fields.indexOf("split_by")
        if split_by_idx != -1:
            out_feat.setAttribute(split_by_idx, ea.get('split_by', 'none'))

        ean_field_idx = out_fields.indexOf(ea_id_field)
        if ean_field_idx != -1 and ea_id_field.lower() != "geocode":
            cur_ean = out_feat.attribute(ean_field_idx)
            if cur_ean is None or cur_ean == NULL or str(cur_ean).strip() in ('', 'NULL', 'None'):
                inh_ean = (
                    get_text_attr(parent_feat, [ea_id_field, "ean", "code", "ea_code", "ean_code"], prefer_text=False)
                    or ea.get('original_code')
                )
                if inh_ean:
                    out_feat.setAttribute(ean_field_idx, str(inh_ean))

        ean_std_idx = out_fields.indexOf("ean")
        if ean_std_idx != -1 and ean_std_idx != ean_field_idx:
            cur_ean_std = out_feat.attribute(ean_std_idx)
            if cur_ean_std is None or cur_ean_std == NULL or str(cur_ean_std).strip() in ('', 'NULL', 'None'):
                inh_ean = (
                    get_text_attr(parent_feat, ["ean", "code", "ea_code", "ean_code", ea_id_field], prefer_text=False)
                    or ea.get('original_code')
                )
                if inh_ean:
                    out_feat.setAttribute(ean_std_idx, str(inh_ean))

        ea_type_idx = out_fields.indexOf("ea_type")
        if ea_type_idx != -1:
            explicit_ea_type = ea.get('ea_type')
            if explicit_ea_type and str(explicit_ea_type).strip() not in ('RETAINED', '', 'None', 'NULL'):
                ea_type_val = str(explicit_ea_type).strip()
            elif ea.get('from_split', False):
                ea_type_val = 'DELINEATED'
            elif ea.get('from_merge', False):
                ea_type_val = 'MERGED'
            elif ea.get('is_special_ea', False):
                ea_type_val = str(ea.get('special_type', 'SPECIAL'))
            else:
                ea_type_val = 'RETAINED'
            out_feat.setAttribute(ea_type_idx, ea_type_val)

        special_type_idx = out_fields.indexOf("special_type")
        if special_type_idx != -1:
            out_feat.setAttribute(special_type_idx, ea.get('special_type', None))

        source_id_idx = out_fields.indexOf("source_id")
        if source_id_idx != -1:
            out_feat.setAttribute(source_id_idx, ea.get('source_id', None))

        for rem_fname in ("remarks", "remark", "delin_remark", "delin_remarks"):
            rem_idx = out_fields.indexOf(rem_fname)
            if rem_idx != -1:
                out_feat.setAttribute(rem_idx, "")

        corr_ea_geo_idx = out_fields.indexOf("correspondence_ea_geocode")
        if corr_ea_geo_idx != -1:
            map_uuid_idx = out_fields.indexOf("map_uuid")
            geocode_idx = out_fields.indexOf("geocode")
            sy_idx = out_fields.indexOf("sy")

            map_uuid_val = out_feat.attribute(map_uuid_idx) if map_uuid_idx != -1 else ""
            geocode_val = out_feat.attribute(geocode_idx) if geocode_idx != -1 else ""
            sy_val = out_feat.attribute(sy_idx) if sy_idx != -1 else ""

            map_uuid_str = str(map_uuid_val) if map_uuid_val is not None else ""
            geocode_str = str(geocode_val) if geocode_val is not None else ""
            sy_str = str(sy_val) if sy_val is not None else ""

            if map_uuid_str.endswith(".0"):
                map_uuid_str = map_uuid_str[:-2]
            if geocode_str.endswith(".0"):
                geocode_str = geocode_str[:-2]
            if sy_str.endswith(".0"):
                sy_str = sy_str[:-2]

            concat_val = f"{map_uuid_str}:{geocode_str}:{sy_str}"
            out_feat.setAttribute(corr_ea_geo_idx, concat_val)

        # Explicitly set indicator field
        indicator_out_idx = out_fields.indexOf("indicator")
        if indicator_out_idx == -1:
            indicator_out_idx = out_fields.indexOf("eadel_indi")
        if indicator_out_idx != -1:
            _ea_id_tmp = ea.get('original_id')
            is_delin_feat = (_ea_id_tmp in delineation_candidate_ids) or ea.get('from_split', False)
            out_feat.setAttribute(indicator_out_idx, "for_delineation" if is_delin_feat else "ea_reference")

        # Check if EA feature geometry is empty
        _is_blank_feat = out_feat.geometry().isEmpty()

        if _is_blank_feat:
            feedback.pushWarning(f"[Output] Skipped writing empty geometry EA feature to output layer (code={ea.get('original_code', '?')}).")
        else:
            _ea_id = ea.get('original_id')
            exp_feat = make_export_feature(out_feat, export_fields)

            # 1. Add to Special EAs sink if it is a Special EA (Gap/Overlap)
            if ea.get('is_special_ea', False):
                if special_ea_sink is not None:
                    exp_feat_special = make_export_feature(out_feat, special_ea_export_fields)
                    special_ea_fid = special_ea_feat_count + 1
                    fid_idx_spec = special_ea_export_fields.indexOf("fid")
                    if fid_idx_spec != -1:
                        exp_feat_special.setAttribute(fid_idx_spec, special_ea_fid)
                    exp_feat_special.setId(special_ea_fid)
                    if special_ea_sink.addFeature(exp_feat_special, QgsFeatureSink.Flag.FastInsert):
                        special_ea_feat_count += 1
                    else:
                        feedback.reportError(f"Failed to add Special EA {i} to special EA sink.")

            # 2. Add to Delineated EAs sink (only extract whole candidate EAs above the max household threshold or valid split parts)
            if ea.get('from_split', False) and not ea.get('is_special_ea', False):
                if ea.get('hh_count', 0) < min_household:
                    feedback.pushWarning(
                        f"[Output Sink] Skipping EA {ea.get('original_code')} from delineated output: "
                        f"hh_count ({ea.get('hh_count', 0)}) is below minimum threshold ({min_household})."
                    )
                else:
                    sb = ea.get('proposed_split_by') or ea.get('split_by', 'point_based')
                    split_by_counts[sb] = split_by_counts.get(sb, 0) + 1
                    if delineated_sink is not None:
                        delin_fid = delineated_feat_count + 1
                        fid_idx_delin = export_fields.indexOf("fid")
                        if fid_idx_delin != -1:
                            exp_feat.setAttribute(fid_idx_delin, delin_fid)
                        exp_feat.setId(delin_fid)
                        if delineated_sink.addFeature(exp_feat, QgsFeatureSink.Flag.FastInsert):
                            delineated_feat_count += 1
                        else:
                            feedback.reportError(f"Failed to add EA {i} to delineated sink.")
            elif not ea.get('from_split', False) and not ea.get('is_special_ea', False):
                _orig_cand_id = ea.get('original_id')
                if _orig_cand_id in delineation_candidate_ids:
                    if _orig_cand_id not in written_delineation_candidate_ids:
                        written_delineation_candidate_ids.add(_orig_cand_id)
                        parent_feat = full_ea_by_id.get(_orig_cand_id)
                        cand_geom = None
                        if parent_feat and parent_feat.hasGeometry() and not parent_feat.geometry().isEmpty():
                            cand_geom = QgsGeometry(parent_feat.geometry())
                        elif ea.get('geom'):
                            cand_geom = QgsGeometry(ea['geom'])

                        if cand_geom and not cand_geom.isEmpty():
                            _orig_hh_val = ea.get('original_hhcount', ea.get('hh_count', 0.0))
                            if _orig_hh_val > max_household:
                                if delineated_sink is not None:
                                    if barangay_to_target:
                                        cand_geom.transform(barangay_to_target)
                                    cand_geom = cand_geom.makeValid()
                                    cand_geom.convertToMultiType()

                                    cand_exp_feat = make_export_feature(out_feat, export_fields)
                                    cand_exp_feat.setGeometry(cand_geom)

                                    delin_fid = delineated_feat_count + 1
                                    fid_idx_delin = export_fields.indexOf("fid")
                                    if fid_idx_delin != -1:
                                        cand_exp_feat.setAttribute(fid_idx_delin, delin_fid)
                                    cand_exp_feat.setId(delin_fid)

                                    for fname in ("hhcount", "hh_count"):
                                        f_idx = export_fields.indexOf(fname)
                                        if f_idx != -1:
                                            cand_exp_feat.setAttribute(f_idx, int(round(_orig_hh_val)))
                                    for fname in ("bldgcount", "bldg_count"):
                                        f_idx = export_fields.indexOf(fname)
                                        if f_idx != -1:
                                            cand_exp_feat.setAttribute(f_idx, get_field_val(parent_feat, ["bldgcount", "bldg_count"], 0))

                                    ind_idx = export_fields.indexOf("indicator")
                                    if ind_idx == -1:
                                        ind_idx = export_fields.indexOf("eadel_indi")
                                    if ind_idx != -1:
                                        cand_exp_feat.setAttribute(ind_idx, "for_delineation")

                                    if delineated_sink.addFeature(cand_exp_feat, QgsFeatureSink.Flag.FastInsert):
                                        delineated_feat_count += 1
                                    else:
                                        feedback.reportError(f"Failed to add candidate EA {_orig_cand_id} to delineated sink.")

            # 3. Add to Merged EAs sink if feature was generated from EA merging
            if ea.get('from_merge', False) and not ea.get('is_special_ea', False):
                if merged_sink is not None:
                    exp_feat_merged = make_export_feature(out_feat, merged_export_fields)
                    merged_fid = merged_feat_count + 1
                    fid_idx_merged = merged_export_fields.indexOf("fid")
                    if fid_idx_merged != -1:
                        exp_feat_merged.setAttribute(fid_idx_merged, merged_fid)
                    exp_feat_merged.setId(merged_fid)
                    indicator_merged_idx = merged_export_fields.indexOf("indicator")
                    if indicator_merged_idx != -1:
                        exp_feat_merged.setAttribute(indicator_merged_idx, "")
                    if merged_sink.addFeature(exp_feat_merged, QgsFeatureSink.Flag.FastInsert):
                        merged_feat_count += 1
                    else:
                        feedback.reportError(f"Failed to add EA {i} to merged sink.")

        # Add matched buildings to extracted buildings sink
        if extracted_buildings_sink is not None:
            bldg_out_fields = QgsFields(building_source.fields())
            if bldg_out_fields.indexOf("parent_ean") == -1:
                bldg_out_fields.append(create_qgs_field("parent_ean", QVariant.String))

            bldgpts_idx = bldg_out_fields.indexOf("bldgpoints_value")
            if bldgpts_idx == -1:
                bldgpts_idx = bldg_out_fields.indexOf("bldgpts_val")
            if bldgpts_idx == -1:
                bldg_out_fields.append(create_qgs_field("bldgpoints_value", QVariant.Double))
                bldgpts_idx = bldg_out_fields.count() - 1

            pop_out_idx = bldg_out_fields.indexOf("pop")
            if pop_out_idx == -1:
                pop_out_idx = bldg_out_fields.indexOf(bldg_hh_field)
            if pop_out_idx == -1:
                bldg_out_fields.append(create_qgs_field("pop", QVariant.Double))
                pop_out_idx = bldg_out_fields.count() - 1

            parent_ean_idx = bldg_out_fields.indexOf("parent_ean")

            _ea_orig_id = ea.get('original_id')
            _ea_orig_code = ea.get('original_code', '')
            parent_ean_val = ea.get('new_ea_code', _ea_orig_code)
            _is_target_ea = (
                ea.get('from_split', False)
                or ea.get('from_merge', False)
                or _ea_orig_id in delineation_candidate_ids
                or _ea_orig_id in merge_candidate_ids
                or _ea_orig_id in adjacent_ea_ids
            )
            if _is_target_ea:
                for b in ea.get('buildings', []):
                    b_feat = QgsFeature(bldg_out_fields)
                    b_geom = QgsGeometry.fromPointXY(b['point'])
                    if barangay_to_target:
                        b_geom.transform(barangay_to_target)
                    b_feat.setGeometry(b_geom)

                    b_attrs = list(b['attributes']) if 'attributes' in b else []
                    needed = bldg_out_fields.count() - len(b_attrs)
                    if needed > 0:
                        b_attrs.extend([None] * needed)
                    elif len(b_attrs) > bldg_out_fields.count():
                        b_attrs = b_attrs[:bldg_out_fields.count()]

                    if bldgpts_idx != -1:
                        b_attrs[bldgpts_idx] = b['bldgpoints_value']
                    if pop_out_idx != -1:
                        b_attrs[pop_out_idx] = b['pop']
                    if parent_ean_idx != -1:
                        b_attrs[parent_ean_idx] = str(parent_ean_val)

                    bldg_fid = extracted_bldg_feat_count + 1
                    fid_idx_bldg = bldg_out_fields.indexOf("fid")
                    if fid_idx_bldg != -1:
                        b_attrs[fid_idx_bldg] = bldg_fid

                    b_feat.setAttributes(b_attrs)
                    b_feat.setId(bldg_fid)
                    if extracted_buildings_sink.addFeature(b_feat, QgsFeatureSink.Flag.FastInsert):
                        extracted_bldg_feat_count += 1
                    else:
                        feedback.reportWarning("Failed to add building point to extracted buildings sink.")

        if multi_feedback:
            _out_pct = int((i + 1) / max(len(eas), 1) * 100)
            multi_feedback.setProgress(_out_pct)
            if i % 100 == 0 or _out_pct == 100:
                multi_feedback.setProgressText(
                    f"{_PHASE_LABELS[7]} [{i + 1:,}/{len(eas):,}]..."
                )

    if multi_feedback:
        multi_feedback.setProgress(100)

    # ── Write internally detected Barangay gaps & overlaps to SPECIAL_EA_OUTPUT ──
    # These include gaps inside Barangay boundaries and EA-to-EA overlaps that
    # existed in the data. We write them as additional features in the
    # SPECIAL_EA_OUTPUT layer so users have a complete spatial record of every
    # area that required gap-filling or overlap resolution.
    if special_ea_sink is not None and (internal_gap_geoms or internal_overlap_geoms):
        _fid_idx = special_ea_export_fields.indexOf("fid")
        _geocode_idx = special_ea_export_fields.indexOf("geocode")
        _ea_type_idx = special_ea_export_fields.indexOf("ea_type")
        _special_type_idx = special_ea_export_fields.indexOf("special_type")
        _sy_idx = special_ea_export_fields.indexOf("sy")
        _remarks_idx = special_ea_export_fields.indexOf("remarks")
        _bldg_cnt_idx = special_ea_export_fields.indexOf("bldg_count")
        _hh_cnt_idx = special_ea_export_fields.indexOf("hh_count")
        _new_ean_idx = special_ea_export_fields.indexOf("new_ean")
        if _new_ean_idx == -1:
            _new_ean_idx = special_ea_export_fields.indexOf("new_ea")
        _ean_idx = special_ea_export_fields.indexOf("ean")
        _name_idx = special_ea_export_fields.indexOf("name")
        _code_idx = special_ea_export_fields.indexOf("code")

        if internal_gap_geoms:
            feedback.pushInfo(
                f"Writing {len(internal_gap_geoms)} internally detected Barangay gap(s) to Special EA output..."
            )
            for _item in internal_gap_geoms:
                _bar_geocode = _item[0]
                _gap_geom = _item[1]
                _bgy_feat = _item[2] if len(_item) > 2 else None
                if barangay_to_target:
                    _gap_geom = QgsGeometry(_gap_geom)
                    _gap_geom.transform(barangay_to_target)
                _gap_feat = QgsFeature(special_ea_export_fields)
                _gap_feat.setGeometry(_gap_geom)
                _gap_fid = special_ea_feat_count + 1
                if _fid_idx != -1:
                    _gap_feat.setAttribute(_fid_idx, _gap_fid)
                _gap_feat.setId(_gap_fid)

                _sp_prefix = special_prefix_by_barangay.get(_bar_geocode, 1)
                _sp_ean = f"{_sp_prefix:03d}000"
                special_prefix_by_barangay[_bar_geocode] = _sp_prefix + 1

                if _new_ean_idx != -1:
                    _gap_feat.setAttribute(_new_ean_idx, _sp_ean)
                if _ean_idx != -1:
                    _gap_feat.setAttribute(_ean_idx, _sp_ean)
                if _name_idx != -1:
                    _gap_feat.setAttribute(_name_idx, f"EA {_sp_ean}")
                if _code_idx != -1:
                    _gap_feat.setAttribute(_code_idx, _sp_ean)
                if _geocode_idx != -1:
                    _gc_prefix = _bar_geocode if len(_bar_geocode) <= 9 else _bar_geocode[:9]
                    _gap_feat.setAttribute(_geocode_idx, _gc_prefix + _sp_ean)
                if _ea_type_idx != -1:
                    _gap_feat.setAttribute(_ea_type_idx, "GAP")
                if _special_type_idx != -1:
                    _gap_feat.setAttribute(_special_type_idx, "GAP")
                if _sy_idx != -1:
                    _gap_feat.setAttribute(_sy_idx, "2026")
                if _remarks_idx != -1:
                    _gap_feat.setAttribute(_remarks_idx, "Internal Barangay Gap")
                if _bldg_cnt_idx != -1:
                    _gap_feat.setAttribute(_bldg_cnt_idx, 0)
                if _hh_cnt_idx != -1:
                    _gap_feat.setAttribute(_hh_cnt_idx, 0)
                if _bgy_feat:
                    for _fname, _cands in [
                        ("map_uuid", ["map_uuid", "mapuuid", "uuid", "map_id"]),
                        ("region", ["region", "reg_name", "region_name", "reg_desc", "adm1_en", "reg", "region_n", "reg_n"]),
                        ("province", ["province", "prov_name", "province_name", "prov_desc", "adm2_en", "prov", "province_n", "prov_n"]),
                        ("city_mun", ["city_mun", "citymun", "city_municipality", "city_name", "mun_name", "adm3_en", "city", "municipality", "mun", "citymun_n"]),
                        ("barangay", ["barangay", "bgy_name", "brgy_name", "adm4_en", "bgy", "brgy", "barangay_n", "bgy_n"]),
                        ("code", ["code", "bgy_code", "brgy_code", "barangay_code", "adm4_pcode"]),
                    ]:
                        _f_idx = special_ea_export_fields.indexOf(_fname)
                        if _f_idx != -1:
                            _v = get_text_attr(_bgy_feat, _cands)
                            if _v:
                                _gap_feat.setAttribute(_f_idx, _v)
                if special_ea_sink.addFeature(_gap_feat, QgsFeatureSink.Flag.FastInsert):
                    special_ea_feat_count += 1
                else:
                    feedback.reportError(
                        f"Failed to write internally detected gap in barangay '{_bar_geocode}' to Special EA sink."
                    )

        if internal_overlap_geoms:
            feedback.pushInfo(
                f"Writing {len(internal_overlap_geoms)} internally detected EA overlap(s) to Special EA output..."
            )
            for _item in internal_overlap_geoms:
                _bar_geocode = _item[0]
                _overlap_geom = _item[1]
                _bgy_feat = _item[2] if len(_item) > 2 else None
                if barangay_to_target:
                    _overlap_geom = QgsGeometry(_overlap_geom)
                    _overlap_geom.transform(barangay_to_target)
                _ov_feat = QgsFeature(special_ea_export_fields)
                _ov_feat.setGeometry(_overlap_geom)
                _ov_fid = special_ea_feat_count + 1
                if _fid_idx != -1:
                    _ov_feat.setAttribute(_fid_idx, _ov_fid)
                _ov_feat.setId(_ov_fid)

                _sp_prefix = special_prefix_by_barangay.get(_bar_geocode, 1)
                _sp_ean = f"{_sp_prefix:03d}000"
                special_prefix_by_barangay[_bar_geocode] = _sp_prefix + 1

                if _new_ean_idx != -1:
                    _ov_feat.setAttribute(_new_ean_idx, _sp_ean)
                if _ean_idx != -1:
                    _ov_feat.setAttribute(_ean_idx, _sp_ean)
                if _name_idx != -1:
                    _ov_feat.setAttribute(_name_idx, f"EA {_sp_ean}")
                if _code_idx != -1:
                    _ov_feat.setAttribute(_code_idx, _sp_ean)
                if _geocode_idx != -1:
                    _gc_prefix = _bar_geocode if len(_bar_geocode) <= 9 else _bar_geocode[:9]
                    _ov_feat.setAttribute(_geocode_idx, _gc_prefix + _sp_ean)
                if _ea_type_idx != -1:
                    _ov_feat.setAttribute(_ea_type_idx, "OVERLAP")
                if _special_type_idx != -1:
                    _ov_feat.setAttribute(_special_type_idx, "OVERLAP")
                if _sy_idx != -1:
                    _ov_feat.setAttribute(_sy_idx, "2026")
                if _remarks_idx != -1:
                    _ov_feat.setAttribute(_remarks_idx, "Internal EA Overlap")
                if _bldg_cnt_idx != -1:
                    _ov_feat.setAttribute(_bldg_cnt_idx, 0)
                if _hh_cnt_idx != -1:
                    _ov_feat.setAttribute(_hh_cnt_idx, 0)
                if _bgy_feat:
                    for _fname, _cands in [
                        ("map_uuid", ["map_uuid", "mapuuid", "uuid", "map_id"]),
                        ("region", ["region", "reg_name", "region_name", "reg_desc", "adm1_en", "reg", "region_n", "reg_n"]),
                        ("province", ["province", "prov_name", "province_name", "prov_desc", "adm2_en", "prov", "province_n", "prov_n"]),
                        ("city_mun", ["city_mun", "citymun", "city_municipality", "city_name", "mun_name", "adm3_en", "city", "municipality", "mun", "citymun_n"]),
                        ("barangay", ["barangay", "bgy_name", "brgy_name", "adm4_en", "bgy", "brgy", "barangay_n", "bgy_n"]),
                        ("code", ["code", "bgy_code", "brgy_code", "barangay_code", "adm4_pcode"]),
                    ]:
                        _f_idx = special_ea_export_fields.indexOf(_fname)
                        if _f_idx != -1:
                            _v = get_text_attr(_bgy_feat, _cands)
                            if _v:
                                _ov_feat.setAttribute(_f_idx, _v)
                if special_ea_sink.addFeature(_ov_feat, QgsFeatureSink.Flag.FastInsert):
                    special_ea_feat_count += 1
                else:
                    feedback.reportError(
                        f"Failed to write internally detected overlap in barangay '{_bar_geocode}' to Special EA sink."
                    )

        feedback.pushInfo(
            f"Done — {special_ea_feat_count} total Special EA feature(s) written (includes all gaps and overlaps)."
        )

    # ── Output Splitting Lines Layer (Single Unified Layer: {geo5}_eadel_update) ──
    full_ea_by_id = {feat.id(): feat for feat in p1.get("all_ea_features", [])}
    snap_tolerance = p1.get("snap_tolerance", 15.0)

    src_fields = previous_ea_source.fields()
    geocode_idx = src_fields.indexOf("geocode")
    ean_idx = src_fields.indexOf(ea_id_field) if ea_id_field else src_fields.indexOf("ean")
    region_idx = src_fields.indexOf("region")
    province_idx = src_fields.indexOf("province")
    city_mun_idx = src_fields.indexOf("city_mun")
    barangay_idx_col = src_fields.indexOf("barangay")
    if barangay_idx_col == -1:
        barangay_idx_col = src_fields.indexOf("bgy")
    eadel_indi_idx = src_fields.indexOf("indicator")
    if eadel_indi_idx == -1:
        eadel_indi_idx = src_fields.indexOf("eadel_indi")
    remarks_idx = src_fields.indexOf("remarks")

    all_splitting_lines = []
    proposed_lines = p7.get("proposed_lines", [])

    if proposed_lines:
        for p_line in proposed_lines:
            cand_id = p_line.get('ea_id')
            line_geom = p_line.get('geom')
            if line_geom is None or line_geom.isEmpty():
                continue

            parent_feat = full_ea_by_id.get(cand_id)
            if parent_feat is None:
                continue

            _gap_tol = snap_tolerance * 4
            _min_branch = snap_tolerance * 2
            merged = refine_split_line(line_geom, _gap_tol, _min_branch)

            line_bgy_feat = None
            if barangay_index is not None and parent_feat.hasGeometry():
                line_bgy_feat = get_parent_barangay(parent_feat.geometry(), barangay_index, barangay_by_id)

            line_gc = str(parent_feat.attribute(geocode_idx) or "") if geocode_idx != -1 else ""
            if line_bgy_feat is None and line_gc:
                for b_feat in barangay_by_id.values():
                    val = b_feat.attribute(bar_geocode_field)
                    if val is not None:
                        val_str = str(val).strip()
                        if val_str.endswith(".0"):
                            val_str = val_str[:-2]
                        if val_str and line_gc.startswith(val_str):
                            line_bgy_feat = b_feat
                            break

            line_reg = (
                get_text_attr(line_bgy_feat, ["region", "reg_name", "region_name", "reg_desc", "adm1_en", "reg", "region_n", "reg_n"])
                or get_text_attr(parent_feat, ["region", "reg_name", "region_name", "reg_desc", "adm1_en", "reg", "region_n", "reg_n"])
                or ""
            )
            line_prov = (
                get_text_attr(line_bgy_feat, ["province", "prov_name", "province_name", "prov_desc", "adm2_en", "prov", "province_n", "prov_n"])
                or get_text_attr(parent_feat, ["province", "prov_name", "province_name", "prov_desc", "adm2_en", "prov", "province_n", "prov_n"])
                or ""
            )
            line_cm = (
                get_text_attr(line_bgy_feat, ["city_mun", "citymun", "city_mun_name", "citymun_name", "municipality", "city_name", "mun_name", "city", "mun", "adm3_en", "mun_desc", "city_n", "mun_n"])
                or get_text_attr(parent_feat, ["city_mun", "citymun", "city_mun_name", "citymun_name", "municipality", "city_name", "mun_name", "city", "mun", "adm3_en", "mun_desc", "city_n", "mun_n"])
                or ""
            )
            line_bgy = (
                get_text_attr(line_bgy_feat, ["barangay", "bgy_name", "brgy_name", "barangay_name", "bgy_desc", "brgy_desc", "adm4_en", "name", "bgy", "brgy", "barangay_n", "bgy_n", "brgy_n"])
                or get_text_attr(parent_feat, ["barangay", "bgy_name", "brgy_name", "barangay_name", "bgy_desc", "brgy_desc", "adm4_en", "name", "bgy", "brgy", "barangay_n", "bgy_n", "brgy_n"])
                or ""
            )
            line_ean = get_text_attr(parent_feat, ["ean", "code", "ea_code"], prefer_text=False) or (str(parent_feat.attribute(ean_idx)) if ean_idx != -1 and parent_feat.attribute(ean_idx) is not None else "")

            attrs = {
                'geocode': line_gc,
                'ean': line_ean,
                'region': line_reg,
                'province': line_prov,
                'city_mun': line_cm,
                'barangay': line_bgy,
                'indicator': str(parent_feat.attribute(eadel_indi_idx)) if eadel_indi_idx != -1 and parent_feat.attribute(eadel_indi_idx) is not None else "FOR DELINEATION",
                'remarks': "Proposed delineation line",
                'split_by': p_line.get('split_by', 'voronoi'),
                'num_parts': p_line.get('num_parts', 2),
                'part_hh_counts': p_line.get('part_hh_counts', []),
                'parent_ea': p_line.get('parent_ea'),
            }

            all_splitting_lines.append((merged, attrs))
    else:
        for candidate_id, part_tuples in final_geom_by_candidate.items():
            if len(part_tuples) < 2:
                continue

            if candidate_id not in full_ea_by_id:
                continue
            parent_feat = full_ea_by_id[candidate_id]

            shared_edges = []
            for p_i in range(len(part_tuples)):
                for p_j in range(p_i + 1, len(part_tuples)):
                    geom_i = part_tuples[p_i][0]
                    geom_j = part_tuples[p_j][0]
                    if geom_i.isEmpty() or geom_j.isEmpty():
                        continue
                    shared = geom_i.intersection(geom_j)
                    if shared is None or shared.isEmpty():
                        continue
                    flat = QgsWkbTypes.flatType(shared.wkbType())
                    if flat in (QgsWkbTypes.LineString, QgsWkbTypes.MultiLineString):
                        shared_edges.append(shared)
                    elif flat == QgsWkbTypes.GeometryCollection or shared.isMultipart():
                        try:
                            for sub_part in shared.constParts():
                                sub_geom = QgsGeometry(sub_part.clone())
                                ptype = QgsWkbTypes.flatType(sub_geom.wkbType())
                                if ptype in (QgsWkbTypes.LineString, QgsWkbTypes.MultiLineString):
                                    shared_edges.append(sub_geom)
                        except Exception:
                            pass

            if not shared_edges:
                continue

            all_shared = QgsGeometry.unaryUnion(shared_edges)
            if all_shared is None or all_shared.isEmpty():
                feedback.pushWarning(
                    f"[eadel_update] unaryUnion of shared edges produced empty geometry "
                    f"for candidate {candidate_id}; skipping."
                )
                continue

            merged = all_shared.mergeLines()
            if merged is None or merged.isEmpty():
                merged = all_shared

            _gap_tol = snap_tolerance * 4
            _min_branch = snap_tolerance * 2
            merged = refine_split_line(merged, _gap_tol, _min_branch)

            line_bgy_feat = None
            if barangay_index is not None and parent_feat.hasGeometry():
                line_bgy_feat = get_parent_barangay(parent_feat.geometry(), barangay_index, barangay_by_id)

            line_gc = str(parent_feat.attribute(geocode_idx) or "") if geocode_idx != -1 else ""
            if line_bgy_feat is None and line_gc:
                for b_feat in barangay_by_id.values():
                    val = b_feat.attribute(bar_geocode_field)
                    if val is not None:
                        val_str = str(val).strip()
                        if val_str.endswith(".0"):
                            val_str = val_str[:-2]
                        if val_str and line_gc.startswith(val_str):
                            line_bgy_feat = b_feat
                            break

            line_reg = (
                get_text_attr(line_bgy_feat, ["region", "reg_name", "region_name", "reg_desc", "adm1_en", "reg", "region_n", "reg_n"])
                or get_text_attr(parent_feat, ["region", "reg_name", "region_name", "reg_desc", "adm1_en", "reg", "region_n", "reg_n"])
                or ""
            )
            line_prov = (
                get_text_attr(line_bgy_feat, ["province", "prov_name", "province_name", "prov_desc", "adm2_en", "prov", "province_n", "prov_n"])
                or get_text_attr(parent_feat, ["province", "prov_name", "province_name", "prov_desc", "adm2_en", "prov", "province_n", "prov_n"])
                or ""
            )
            line_cm = (
                get_text_attr(line_bgy_feat, ["city_mun", "citymun", "city_mun_name", "citymun_name", "municipality", "city_name", "mun_name", "city", "mun", "adm3_en", "mun_desc", "city_n", "mun_n"])
                or get_text_attr(parent_feat, ["city_mun", "citymun", "city_mun_name", "citymun_name", "municipality", "city_name", "mun_name", "city", "mun", "adm3_en", "mun_desc", "city_n", "mun_n"])
                or ""
            )
            line_bgy = (
                get_text_attr(line_bgy_feat, ["barangay", "bgy_name", "brgy_name", "barangay_name", "bgy_desc", "brgy_desc", "adm4_en", "name", "bgy", "brgy", "barangay_n", "bgy_n", "brgy_n"])
                or get_text_attr(parent_feat, ["barangay", "bgy_name", "brgy_name", "barangay_name", "bgy_desc", "brgy_desc", "adm4_en", "name", "bgy", "brgy", "barangay_n", "bgy_n", "brgy_n"])
                or ""
            )
            line_ean = get_text_attr(parent_feat, ["ean", "code", "ea_code"], prefer_text=False) or (str(parent_feat.attribute(ean_idx)) if ean_idx != -1 and parent_feat.attribute(ean_idx) is not None else "")

            attrs = {
                'geocode': line_gc,
                'ean': line_ean,
                'region': line_reg,
                'province': line_prov,
                'city_mun': line_cm,
                'barangay': line_bgy,
                'indicator': str(parent_feat.attribute(eadel_indi_idx)) if eadel_indi_idx != -1 and parent_feat.attribute(eadel_indi_idx) is not None else "",
                'remarks': str(parent_feat.attribute(remarks_idx)) if remarks_idx != -1 and parent_feat.attribute(remarks_idx) is not None else "",
            }

            all_splitting_lines.append((merged, attrs))

    if all_splitting_lines:
        geo5 = "00000"
        for ea_item in eas:
            bar = ea_item.get('parent_barangay')
            if bar:
                digits = "".join([c for c in str(bar) if c.isdigit()])
                if len(digits) >= 5:
                    geo5 = digits[:5]
                    break
        if geo5 == "00000":
            for feat in p1.get("all_ea_features", []):
                for fname in ["geocode"]:
                    idx = feat.fields().indexOf(fname)
                    if idx != -1:
                        val = str(feat.attribute(idx) or "").strip()
                        digits = "".join([c for c in val if c.isdigit()])
                        if len(digits) >= 5:
                            geo5 = digits[:5]
                            break
                if geo5 != "00000":
                    break

        layer_name = f"{geo5}_eadel_update"

        crs_auth_id = target_crs.authid()
        uri = f"MultiLineString?crs={crs_auth_id}&field=fid:int&field=geocode:string&field=ean:string&field=region:string&field=province:string&field=city_mun:string&field=barangay:string&field=indicator:string&field=remarks:string"

        features_to_add = []
        for line_idx, (line_geom, attrs) in enumerate(all_splitting_lines, start=1):
            if not line_geom.isMultipart():
                line_geom.convertToMultiType()
            f = QgsFeature()
            f.setGeometry(line_geom)
            f.setId(line_idx)
            f.setAttributes([
                line_idx,
                attrs.get('geocode', ''),
                attrs.get('ean', ''),
                attrs.get('region', ''),
                attrs.get('province', ''),
                attrs.get('city_mun', ''),
                attrs.get('barangay', ''),
                attrs.get('indicator', ''),
                attrs.get('remarks', ''),
            ])
            features_to_add.append(f)

        if features_to_add:
            line_layer = QgsVectorLayer(uri, layer_name, "memory")
            if line_layer.isValid():
                pr = line_layer.dataProvider()
                pr.addFeatures(features_to_add)
                line_layer.updateExtents()

                apply_qml_to_layer(line_layer, "eadel_update_lines.qml")

                project = QgsProject.instance()
                if project:
                    project.addMapLayer(line_layer)
                feedback.pushInfo(
                    f"Created line layer '{layer_name}' with {len(features_to_add)} "
                    f"feature(s) ({len(all_splitting_lines)} candidate(s) processed)."
                )
            else:
                feedback.reportError(f"Failed to create memory layer for {layer_name}")

    feedback.pushInfo("Successfully created and structured Enumeration Areas.")

    # ── Summary Report Generation ──────────────────────────────────────────
    primary_delin_cnt = len(delineation_candidate_ids)
    splitting_lines_count = len(all_splitting_lines)

    if splitting_lines_count > 0:
        delin_remark = f"Generated {splitting_lines_count} proposed delineation boundary cut line(s) (EAs preserved whole)."
    elif primary_delin_cnt > 0:
        delin_remark = f"Found {primary_delin_cnt} over-populated area(s), but no proposed cut lines generated."
    else:
        delin_remark = "No areas needed delineation (all within household limits)."

    primary_merge_cnt = 2 if len(merge_candidate_ids) >= 2 else len(merge_candidate_ids)

    if merged_feat_count == 0:
        if len(merge_candidate_ids) > 0:
            merge_remark = f"Found {primary_merge_cnt} small area(s) (under {min_household} households), but could not merge because no suitable neighbor area was available in the same Barangay."
        else:
            merge_remark = f"No small areas (under {min_household} households) needed merging."
    else:
        merge_remark = f"Successfully combined small areas to create {merged_feat_count} new merged area(s)."

    delin_cand_desc = f"Includes {primary_delin_cnt} primary candidate(s) over {max_household} households + {max(0, delin_candidate_feat_count - primary_delin_cnt)} neighbor reference area(s)"

    if splitting_lines_count > 0:
        split_lines_remark = f"Generated {splitting_lines_count} proposed boundary cut line(s) along features"
    else:
        split_lines_remark = "No splitting lines generated."

    breakdown_table = ""
    if all_splitting_lines:
        rows = []
        for line_geom, attrs in all_splitting_lines:
            parent_bar = attrs.get('barangay', '')
            parent_ean = attrs.get('ean', 'Unknown')
            p_ea = attrs.get('parent_ea')
            orig_pop = p_ea.get('hh_count', 0.0) if p_ea else 0.0
            num_p = attrs.get('num_parts', 2)
            sb_label = attrs.get('split_by', 'voronoi')
            part_hhs = attrs.get('part_hh_counts', [])
            if part_hhs:
                part_strs = [f"Part {pi+1}: ~{ph:,.1f} HH" for pi, ph in enumerate(part_hhs)]
                parts_html = "<br/>".join(part_strs)
            else:
                parts_html = f"{num_p} proposed sub-zones"

            rows.append(
                f"<tr>"
                f"<td>{parent_bar}</td>"
                f"<td align='center'><b>{parent_ean}</b></td>"
                f"<td align='center'>{orig_pop:,.1f}</td>"
                f"<td align='center'><b>{num_p}</b></td>"
                f"<td>{parts_html}</td>"
                f"<td align='center'><code>{sb_label}</code></td>"
                f"<td>Proposed cut line generated (EA polygon kept intact)</td>"
                f"</tr>"
            )

        if rows:
            breakdown_table = (
                "<br/><b>Proposed Delineation Cut Lines Breakdown</b>"
                "<table border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse; width:100%; margin:8px 0; font-family:sans-serif; font-size:11px;'>"
                "<tr style='background-color:#2d3748; color:#ffffff; font-weight:bold;'>"
                "<th align='left'>Parent Barangay</th>"
                "<th align='center'>Parent EA</th>"
                "<th align='center'>Original HH</th>"
                "<th align='center'>Proposed Parts</th>"
                "<th align='left'>Estimated Distribution</th>"
                "<th align='center'>Split Strategy</th>"
                "<th align='left'>Status</th>"
                "</tr>"
                + "".join(rows)
                + "</table>"
            )

    html_table = (
        "<html_table>"
        "<br/><b>Execution Results &amp; Output Summary</b>"
        "<table border='1' cellspacing='0' cellpadding='6' style='border-collapse:collapse; width:100%; margin:8px 0; font-family:sans-serif; font-size:11px;'>"
        "<tr style='background-color:#2d3748; color:#ffffff; font-weight:bold;'>"
        "<th align='left'>Output Layer</th>"
        "<th align='center'>Feature Count</th>"
        "<th align='left'>Execution Remark / Status</th>"
        "</tr>"
        f"<tr><td><b>Proposed Splitting Lines</b></td><td align='center'><b>{splitting_lines_count:,}</b></td><td>{split_lines_remark}</td></tr>"
        f"<tr><td><b>Merged EAs</b></td><td align='center'><b>{merged_feat_count:,}</b></td><td>{merge_remark}</td></tr>"
        f"<tr><td><b>Special EAs</b></td><td align='center'><b>{special_ea_feat_count:,}</b></td><td>Areas created to fix boundary gaps and overlaps</td></tr>"
        f"<tr><td><b>Delineation Candidates</b></td><td align='center'><b>{delin_candidate_feat_count:,}</b></td><td>{delin_cand_desc}</td></tr>"
        f"<tr><td><b>Extracted Building Points</b></td><td align='center'>{extracted_bldg_feat_count:,}</td><td>Total houses/buildings counted inside checked areas</td></tr>"
        "</table>"
        + breakdown_table
        + "</html_table>"
    )

    final_outputs = {}
    if delineated_feat_count > 0 and delineated_dest_id is not None:
        final_outputs[getattr(alg, 'DELINEATED_OUTPUT', 'DELINEATED_OUTPUT')] = delineated_dest_id
    if merged_feat_count > 0 and merged_dest_id is not None:
        final_outputs[getattr(alg, 'MERGED_OUTPUT', 'MERGED_OUTPUT')] = merged_dest_id
    if special_ea_feat_count > 0 and special_ea_dest_id is not None:
        final_outputs[getattr(alg, 'SPECIAL_EA_OUTPUT', 'SPECIAL_EA_OUTPUT')] = special_ea_dest_id
    if delin_candidate_feat_count > 0 and delin_candidate_dest_id is not None:
        final_outputs[getattr(alg, 'DELINEATION_CANDIDATE_OUTPUT', 'DELINEATION_CANDIDATE_OUTPUT')] = delin_candidate_dest_id
    if extracted_bldg_feat_count > 0 and extracted_buildings_dest_id is not None:
        final_outputs[getattr(alg, 'EXTRACTED_BUILDINGS_OUTPUT', 'EXTRACTED_BUILDINGS_OUTPUT')] = extracted_buildings_dest_id

    return final_outputs
