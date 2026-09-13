import math
import time
import concurrent.futures
from typing import Dict, Any, List

from qgis.core import (
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsSpatialIndex,
    QgsProcessingException,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QCoreApplication, QThread

from ..helpers.constants import _PHASE_LABELS
from ..helpers.geometry import (
    get_polygons_from_geom,
    get_polylines_from_geom,
    allocate_gaps_to_parts,
    collect_linear_features,
    merge_line_geometries,
    weighted_kmeans,
    assign_buildings_to_parts,
)


def extract_proposed_cut_line(split_parts: List[Dict[str, Any]], parent_geom: QgsGeometry = None) -> QgsGeometry:
    """Extract and merge internal cut lines between split sub-polygons."""
    if not split_parts or len(split_parts) < 2:
        return None
    shared_edges = []
    for p_i in range(len(split_parts)):
        for p_j in range(p_i + 1, len(split_parts)):
            geom_i = split_parts[p_i].get('geom')
            geom_j = split_parts[p_j].get('geom')
            if not geom_i or not geom_j or geom_i.isEmpty() or geom_j.isEmpty():
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
        return None

    all_shared = QgsGeometry.unaryUnion(shared_edges)
    if all_shared is None or all_shared.isEmpty():
        return None

    merged = all_shared.mergeLines()
    if merged is None or merged.isEmpty():
        merged = all_shared

    if parent_geom is not None and not parent_geom.isEmpty():
        clipped = merged.intersection(parent_geom)
        if clipped is not None and not clipped.isEmpty():
            merged = clipped

    return merged


def enforce_min_household_parts(parts, fback, min_household=100, max_household=300, ea_geom=None):
    while len(parts) > 1:
        under = [i for i, p in enumerate(parts) if p['hh_count'] < min_household]
        if not under:
            break
        under.sort(key=lambda i: parts[i]['hh_count'])
        up_idx = under[0]
        up = parts[up_idx]

        best_idx = -1
        best_overlap = -1.0
        for j, nb in enumerate(parts):
            if j == up_idx:
                continue
            if up['geom'].intersects(nb['geom']) or up['geom'].touches(nb['geom']):
                inter = up['geom'].intersection(nb['geom'])
                overlap = inter.length() if not inter.isEmpty() else 0.0
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_idx = j

        if best_idx == -1:
            up_centroid = up['geom'].centroid().asPoint()
            best_dist = float('inf')
            best_dist_over = float('inf')
            best_idx_over = -1
            for j, nb in enumerate(parts):
                if j == up_idx:
                    continue
                dist = math.hypot(up_centroid.x() - nb['geom'].centroid().asPoint().x(), up_centroid.y() - nb['geom'].centroid().asPoint().y())
                combined = up['hh_count'] + nb['hh_count']
                if combined <= max_household:
                    if dist < best_dist:
                        best_dist = dist
                        best_idx = j
                else:
                    if dist < best_dist_over:
                        best_dist_over = dist
                        best_idx_over = j
            if best_idx == -1:
                best_idx = best_idx_over

        if best_idx == -1:
            break

        nb = parts[best_idx]
        raw_combined = nb['geom'].combine(up['geom']).buffer(0.0, 3)
        if ea_geom is not None:
            clipped = raw_combined.intersection(ea_geom).buffer(0.0, 3)
            nb['geom'] = clipped if not clipped.isEmpty() else raw_combined
        else:
            nb['geom'] = raw_combined
        nb['buildings'].extend(up['buildings'])
        nb['hh_count'] += up['hh_count']
        nb['bldg_count'] = len(nb['buildings'])
        parts.pop(up_idx)
    return parts


def force_geometric_split(ea_item, target_pop, fback, min_household=100, max_household=300):
    hh_cnt = ea_item['hh_count']
    bldgs = ea_item.get('buildings', [])
    bbox = ea_item['geom'].boundingBox()

    def make_strips(n, horizontal):
        strips = []
        for i in range(n):
            if horizontal:
                span = bbox.height() / n
                y0 = bbox.yMinimum() + i * span
                y1 = bbox.yMinimum() + (i + 1) * span
                pts = [
                    QgsPointXY(bbox.xMinimum(), y0),
                    QgsPointXY(bbox.xMaximum(), y0),
                    QgsPointXY(bbox.xMaximum(), y1),
                    QgsPointXY(bbox.xMinimum(), y1),
                    QgsPointXY(bbox.xMinimum(), y0),
                ]
            else:
                span = bbox.width() / n
                x0 = bbox.xMinimum() + i * span
                x1 = bbox.xMinimum() + (i + 1) * span
                pts = [
                    QgsPointXY(x0, bbox.yMinimum()),
                    QgsPointXY(x1, bbox.yMinimum()),
                    QgsPointXY(x1, bbox.yMaximum()),
                    QgsPointXY(x0, bbox.yMaximum()),
                    QgsPointXY(x0, bbox.yMinimum()),
                ]
            strip_geom = QgsGeometry.fromPolygonXY([pts])
            intersected = ea_item['geom'].intersection(strip_geom)
            if not intersected.isEmpty():
                strips.extend(get_polygons_from_geom(intersected))
        return strips

    use_horizontal = bbox.height() >= bbox.width()
    k_start = max(2, math.ceil(hh_cnt / float(target_pop if target_pop > 0 else 200)))
    k_max = k_start + 4

    accepted_parts = None
    accepted_k = None
    accepted_orientation = use_horizontal

    for k_val in range(k_start, k_max + 1):
        strip_polys = make_strips(k_val, horizontal=use_horizontal)
        orientation = 'horizontal'
        if len(strip_polys) < 2:
            strip_polys = make_strips(k_val, horizontal=not use_horizontal)
            orientation = 'vertical'

        if len(strip_polys) < 2:
            break

        assigned_bldgs_list = assign_buildings_to_parts(bldgs, strip_polys, fback, ea_item.get('original_code', ''))
        parts = []
        for poly, buildings_in_poly in zip(strip_polys, assigned_bldgs_list):
            sub_pop = sum(b['pop'] for b in buildings_in_poly)
            parts.append({
                'geom': poly,
                'buildings': buildings_in_poly,
                'hh_count': sub_pop,
                'original_hhcount': ea_item.get('original_hhcount') if ea_item.get('original_hhcount') is not None else ea_item.get('hh_count', 0.0),
                'original_bldgcount': ea_item.get('original_bldgcount') if ea_item.get('original_bldgcount') is not None else ea_item.get('bldg_count', 0),
                'bldg_count': len(buildings_in_poly),
                'bldgpoints_value': sub_pop / len(buildings_in_poly) if len(buildings_in_poly) > 0 else 0.0,
                'attributes': list(ea_item['attributes']),
                'original_id': ea_item['original_id'],
                'original_code': ea_item['original_code'],
                'is_new': True,
                'from_split': True,
                'split_by': 'forced_grid',
                'parent_barangay': ea_item['parent_barangay']
            })

        zero_parts = [p for p in parts if p['hh_count'] == 0]
        nonzero_parts = [p for p in parts if p['hh_count'] > 0]

        if not nonzero_parts:
            continue

        for zp in zero_parts:
            zp_centroid = zp['geom'].centroid().asPoint()
            best_nb = min(
                nonzero_parts,
                key=lambda np: zp_centroid.distance(np['geom'].centroid().asPoint())
            )
            raw_combined = best_nb['geom'].combine(zp['geom']).buffer(0.0, 3)
            clipped = raw_combined.intersection(ea_item['geom'])
            best_nb['geom'] = clipped if not clipped.isEmpty() else raw_combined
            best_nb['buildings'].extend(zp['buildings'])
            best_nb['bldg_count'] = len(best_nb['buildings'])

        parts = enforce_min_household_parts(nonzero_parts, fback, min_household=min_household, max_household=max_household, ea_geom=ea_item['geom'])
        if len(parts) < 2:
            continue

        all_valid = all(min_household <= p['hh_count'] <= max_household for p in parts)

        if accepted_parts is None or all_valid:
            accepted_parts = parts
            accepted_k = k_val
            accepted_orientation = orientation

        if all_valid:
            break

    if accepted_parts is None:
        fback.pushWarning(
            f"[EA {ea_item['original_code']}] FORCED SPLIT: Could not produce >= 2 valid "
            f"parts at any k ({k_start}–{k_max}) meeting min threshold ({min_household} HH). "
            f"EA will remain whole."
        )
        return [ea_item]

    final_parts = []
    for part in accepted_parts:
        if part['hh_count'] > max_household:
            if part.get('from_merge', False):
                final_parts.append(part)
                continue
            sub_result = force_geometric_split(part, target_pop, fback, min_household, max_household)
            if len(sub_result) > 1:
                final_parts.extend(sub_result)
            else:
                final_parts.append(part)
        else:
            final_parts.append(part)

    final_parts = enforce_min_household_parts(final_parts, fback, min_household=min_household, max_household=max_household, ea_geom=ea_item['geom'])

    if len(final_parts) < 2 or any(p['hh_count'] < min_household for p in final_parts):
        fback.pushWarning(
            f"[EA {ea_item['original_code']}] FORCED SPLIT: Resulting sub-polygons fall below min threshold "
            f"({min_household} HH). Keeping EA whole."
        )
        return [ea_item]

    orig_code_str = str(ea_item['original_code']).strip() if ea_item['original_code'] is not None else "000"
    digits = "".join([c for c in orig_code_str if c.isdigit()])
    orig_first3 = digits[:3] if len(digits) >= 3 else digits.zfill(3)
    if orig_first3 != "000" and len(final_parts) > 0:
        final_parts.sort(key=lambda x: x['hh_count'], reverse=True)
        final_parts[0]['is_new'] = False

    final_parts, _ = allocate_gaps_to_parts(final_parts, ea_item['geom'])

    parent_geom = ea_item['geom']
    for p in final_parts:
        clipped = p['geom'].intersection(parent_geom).buffer(0.0, 3)
        if not clipped.isEmpty():
            p['geom'] = clipped

    fback.pushWarning(
        f"[EA {ea_item['original_code']}] FORCED SPLIT: Applied {accepted_orientation} "
        f"strip split (k={accepted_k}) — EA (hh_count={hh_cnt}) → {len(final_parts)} part(s)."
    )
    return final_parts


def verify_point_cluster_alignment(bldgs, bbox=None, target_pop=200, k_val=2):
    """
    Verifies building point spatial alignment for EAs with clustered points in small areas.
    Calculates weighted center of mass, spatial extent, and principal alignment direction (covariance).
    Returns centroid points aligned along the principal cluster axis.
    """
    if not bldgs or len(bldgs) < 2:
        return []

    pts = []
    wts = []
    for b in bldgs:
        pt = b.get('point')
        if pt is None:
            continue
        pt_xy = pt if isinstance(pt, QgsPointXY) else QgsPointXY(pt[0], pt[1])
        pts.append((pt_xy.x(), pt_xy.y()))
        wts.append(float(b.get('pop', 1.0)))

    if len(pts) < 2:
        return []

    N = len(pts)
    sum_w = sum(wts) if sum(wts) > 0 else float(N)
    cx = sum(p[0] * w for p, w in zip(pts, wts)) / sum_w
    cy = sum(p[1] * w for p, w in zip(pts, wts)) / sum_w

    var_x = sum(w * (p[0] - cx) ** 2 for p, w in zip(pts, wts)) / sum_w
    var_y = sum(w * (p[1] - cy) ** 2 for p, w in zip(pts, wts)) / sum_w
    cov_xy = sum(w * (p[0] - cx) * (p[1] - cy) for p, w in zip(pts, wts)) / sum_w

    angle = 0.5 * math.atan2(2.0 * cov_xy, var_x - var_y + 1e-12)
    cos_a, sin_a = math.cos(angle), math.sin(angle)

    proj_coords = [(p[0] - cx) * cos_a + (p[1] - cy) * sin_a for p in pts]
    min_u, max_u = min(proj_coords), max(proj_coords)
    span_u = max_u - min_u

    centroid_pts = []
    if span_u > 1e-7 and k_val >= 2:
        step = span_u / float(k_val)
        for i in range(k_val):
            u_i = min_u + (i + 0.5) * step
            x_i = cx + u_i * cos_a
            y_i = cy + u_i * sin_a
            centroid_pts.append(QgsPointXY(x_i, y_i))

    return centroid_pts


def split_ea_voronoi_road_hybrid(ea_item, road_lines, river_lines, target_pop, fback, min_household=100, max_household=300):
    """
    Hybrid Voronoi Population Clustering + Road/River Boundary Alignment:
    1. Voronoi / Weighted K-Means determines population distribution (HH truth).
    2. Road & River lines partition the EA into physical atomic blocks.
    3. Blocks are assigned to Voronoi clusters by majority building population.
    4. Blocks per cluster are dissolved to form field-surveyable sub-EAs with road/river boundaries.
    5. Exact building assignment via assign_buildings_to_parts guarantees zero HH lost, zero HH duplicated.
    """
    if fback.isCanceled():
        return [ea_item]

    bldgs = ea_item.get('buildings', [])
    if not bldgs:
        return [ea_item]

    parent_geom = ea_item['geom']
    hh_cnt = sum(b['pop'] for b in bldgs)
    target = target_pop if target_pop > 0 else 200
    k_val = max(2, int(round(hh_cnt / float(target))))

    coord_to_pt = {}
    for b in bldgs:
        pt = b['point']
        pt_xy = pt if isinstance(pt, QgsPointXY) else QgsPointXY(pt[0], pt[1])
        coord_to_pt[(pt_xy.x(), pt_xy.y())] = pt_xy
    unique_pts = list(coord_to_pt.values())

    if len(unique_pts) < 2:
        return [ea_item]

    k_val = min(k_val, len(unique_pts))
    if k_val < 2:
        k_val = 2

    # ── Step 1: Population Clustering (Weighted K-Means) ──
    pts = [(pt.x(), pt.y()) for pt in unique_pts]
    pt_to_weight = {}
    for b in bldgs:
        pt = b['point']
        pt_xy = pt if isinstance(pt, QgsPointXY) else QgsPointXY(pt[0], pt[1])
        pt_key = (pt_xy.x(), pt_xy.y())
        pt_to_weight[pt_key] = pt_to_weight.get(pt_key, 0.0) + b['pop']
    wts = [pt_to_weight.get((pt.x(), pt.y()), 1.0) for pt in unique_pts]

    labels, centroids = weighted_kmeans(pts, wts, k_val)
    centroid_pts = [QgsPointXY(c[0], c[1]) for c in centroids]

    # ── Step 2: Physical Road/River Mesh Slicing ──
    all_input_lines = road_lines + river_lines
    if not all_input_lines:
        return [ea_item]

    all_polylines = []
    for lg in all_input_lines:
        all_polylines.extend(get_polylines_from_geom(lg))

    if not all_polylines:
        return [ea_item]

    bbox = parent_geom.boundingBox()
    ext_len = max(100.0, max(bbox.width(), bbox.height()) * 3.0)

    current_polys = [parent_geom]
    used_split = False

    for polyline in all_polylines:
        if len(polyline) < 2:
            continue

        p0, p1 = polyline[0], polyline[1]
        dx0, dy0 = p0.x() - p1.x(), p0.y() - p1.y()
        len0 = math.hypot(dx0, dy0)
        p0_ext = QgsPointXY(p0.x() + (dx0 / len0) * ext_len, p0.y() + (dy0 / len0) * ext_len) if len0 > 1e-7 else p0

        pn, pn_prev = polyline[-1], polyline[-2]
        dxn, dyn = pn.x() - pn_prev.x(), pn.y() - pn_prev.y()
        lenn = math.hypot(dxn, dyn)
        pn_ext = QgsPointXY(pn.x() + (dxn / lenn) * ext_len, pn.y() + (dyn / lenn) * ext_len) if lenn > 1e-7 else pn

        extended_line = [p0_ext] + list(polyline) + [pn_ext]

        next_polys = []
        for poly in current_polys:
            target_geom = QgsGeometry(poly)
            res, new_geoms, _ = target_geom.splitGeometry(extended_line, False)
            if res == 0 and len(new_geoms) > 0:
                split_pieces = [target_geom] + new_geoms
                valid_pieces = []
                for sp in split_pieces:
                    if sp and not sp.isEmpty() and sp.area() > 1e-6:
                        clipped = sp.intersection(parent_geom).buffer(0.0, 3)
                        if not clipped.isEmpty() and clipped.area() > 1e-6:
                            valid_pieces.append(clipped)
                if len(valid_pieces) >= 2:
                    next_polys.extend(valid_pieces)
                    used_split = True
                else:
                    next_polys.append(poly)
            else:
                next_polys.append(poly)
        current_polys = next_polys

    if not used_split or len(current_polys) < 2:
        return [ea_item]

    atomic_blocks = []
    for cp in current_polys:
        atomic_blocks.extend(get_polygons_from_geom(cp))

    atomic_blocks = [ab for ab in atomic_blocks if ab and not ab.isEmpty() and ab.area() > 1e-6]
    if len(atomic_blocks) < 2:
        return [ea_item]

    # ── Step 3: Assign Atomic Blocks to Voronoi Clusters (Majority Building Vote) ──
    block_bldgs_assigned = assign_buildings_to_parts(bldgs, atomic_blocks, fback, ea_item.get('original_code', ''))

    block_cluster_mapping = []
    for blk_idx, (blk_geom, blk_bldgs) in enumerate(zip(atomic_blocks, block_bldgs_assigned)):
        if blk_bldgs:
            cluster_votes = [0.0] * len(centroid_pts)
            for b in blk_bldgs:
                b_pt = b['point']
                b_xy = b_pt if isinstance(b_pt, QgsPointXY) else QgsPointXY(b_pt[0], b_pt[1])
                closest_c = min(
                    range(len(centroid_pts)),
                    key=lambda ci: math.hypot(b_xy.x() - centroid_pts[ci].x(), b_xy.y() - centroid_pts[ci].y())
                )
                cluster_votes[closest_c] += b['pop']
            best_cluster = max(range(len(centroid_pts)), key=lambda ci: cluster_votes[ci])
            block_cluster_mapping.append(best_cluster)
        else:
            blk_centroid = blk_geom.centroid().asPoint()
            best_cluster = min(
                range(len(centroid_pts)),
                key=lambda ci: math.hypot(blk_centroid.x() - centroid_pts[ci].x(), blk_centroid.y() - centroid_pts[ci].y())
            )
            block_cluster_mapping.append(best_cluster)

    # ── Step 4: Dissolve Blocks by Cluster ──
    cluster_geoms = {}
    for blk_geom, c_id in zip(atomic_blocks, block_cluster_mapping):
        if c_id not in cluster_geoms:
            cluster_geoms[c_id] = blk_geom
        else:
            cluster_geoms[c_id] = cluster_geoms[c_id].combine(blk_geom).buffer(0.0, 3)

    if len(cluster_geoms) < 2:
        return [ea_item]

    dissolved_parts = []
    for c_id, c_geom in cluster_geoms.items():
        clean_g = c_geom.intersection(parent_geom).buffer(0.0, 3)
        if clean_g and not clean_g.isEmpty() and clean_g.area() > 1e-6:
            polys = get_polygons_from_geom(clean_g)
            for p in polys:
                if p and not p.isEmpty() and p.area() > 1e-6:
                    dissolved_parts.append(p)

    if len(dissolved_parts) < 2:
        return [ea_item]

    split_by = 'road'
    if road_lines and river_lines:
        split_by = 'road+river'
    elif river_lines:
        split_by = 'river'

    # ── Step 5: Assign Buildings & Build Part Dictionaries ──
    part_bldgs_list = assign_buildings_to_parts(bldgs, dissolved_parts, fback, ea_item.get('original_code', ''))

    parts = []
    for poly, p_bldgs in zip(dissolved_parts, part_bldgs_list):
        sub_pop = sum(b['pop'] for b in p_bldgs)
        parts.append({
            'geom': poly,
            'buildings': p_bldgs,
            'hh_count': sub_pop,
            'original_hhcount': ea_item.get('original_hhcount') if ea_item.get('original_hhcount') is not None else ea_item.get('hh_count', 0.0),
            'original_bldgcount': ea_item.get('original_bldgcount') if ea_item.get('original_bldgcount') is not None else ea_item.get('bldg_count', 0),
            'bldg_count': len(p_bldgs),
            'bldgpoints_value': sub_pop / len(p_bldgs) if len(p_bldgs) > 0 else 0.0,
            'attributes': list(ea_item['attributes']),
            'original_id': ea_item['original_id'],
            'original_code': ea_item['original_code'],
            'is_new': True,
            'from_split': True,
            'split_by': split_by,
            'parent_barangay': ea_item['parent_barangay']
        })

    # ── Step 6: Merge Zero-Population Fragments into Adjacent Neighbor ──
    zero_parts = [p for p in parts if p['hh_count'] == 0]
    nonzero_parts = [p for p in parts if p['hh_count'] > 0]

    if not nonzero_parts:
        return [ea_item]

    for zp in zero_parts:
        best_nb = None
        best_overlap = -1.0
        for np in nonzero_parts:
            if zp['geom'].intersects(np['geom']) or zp['geom'].touches(np['geom']):
                inter = zp['geom'].intersection(np['geom'])
                overlap = inter.length() if not inter.isEmpty() else 0.0
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_nb = np
        if best_nb is None:
            zp_centroid = zp['geom'].centroid().asPoint()
            best_nb = min(nonzero_parts, key=lambda np: math.hypot(zp_centroid.x() - np['geom'].centroid().asPoint().x(), zp_centroid.y() - np['geom'].centroid().asPoint().y()))

        raw_combined = best_nb['geom'].combine(zp['geom']).buffer(0.0, 3)
        clipped = raw_combined.intersection(parent_geom).buffer(0.0, 3)
        best_nb['geom'] = clipped if not clipped.isEmpty() else raw_combined
        best_nb['buildings'].extend(zp['buildings'])
        best_nb['bldg_count'] = len(best_nb['buildings'])

    parts = nonzero_parts
    if len(parts) < 2:
        return [ea_item]

    # ── Step 7: Enforce Minimum Household Limit ──
    parts = enforce_min_household_parts(parts, fback, min_household=min_household, max_household=max_household, ea_geom=parent_geom)
    if len(parts) < 2:
        return [ea_item]

    orig_code_str = str(ea_item['original_code']).strip() if ea_item['original_code'] is not None else "000"
    digits = "".join([c for c in orig_code_str if c.isdigit()])
    orig_first3 = digits[:3] if len(digits) >= 3 else digits.zfill(3)
    if orig_first3 != "000" and len(parts) > 0:
        parts.sort(key=lambda x: x['hh_count'], reverse=True)
        parts[0]['is_new'] = False

    final_parts, _ = allocate_gaps_to_parts(parts, parent_geom)

    # Final pass: Guarantee exact building assignment with assign_buildings_to_parts
    final_bldgs_list = assign_buildings_to_parts(bldgs, [p['geom'] for p in final_parts], fback, ea_item.get('original_code', ''))
    for p, p_bldgs in zip(final_parts, final_bldgs_list):
        clipped = p['geom'].intersection(parent_geom).buffer(0.0, 3)
        if not clipped.isEmpty():
            p['geom'] = clipped
        p['buildings'] = p_bldgs
        p['hh_count'] = sum(b['pop'] for b in p_bldgs)
        p['bldg_count'] = len(p_bldgs)
        p['bldgpoints_value'] = p['hh_count'] / p['bldg_count'] if p['bldg_count'] > 0 else 0.0
        p['split_by'] = split_by

    return final_parts


split_polygon_by_linear_features = split_ea_voronoi_road_hybrid


def run_phase_5(alg, parameters, context, feedback, multi_feedback, p1, p2, p3, p4):
    """

    Executes Phase 5 (Iterative Per-Barangay Delineation / EA Splitting).

    Returns dictionary containing:
    - split_eas: List[dict] of EAs after iterative splitting
    """
    eadel_indi_col_idx = p1["eadel_indi_col_idx"]
    full_ea_by_id = p2["full_ea_by_id"]
    min_household = p1["min_household"]
    max_household = p1["max_household"]
    target_household = p1["target_household"]
    snap_tolerance = p1["snap_tolerance"]
    densify_dist = p1["densify_dist"]
    area_threshold = p1["area_threshold"]
    num_cores = p1.get("num_cores", QThread.idealThreadCount())
    split_strategy = p1.get("split_strategy", 0)
    split_type = p1.get("split_type", 0)

    delineation_candidate_ids = p2["delineation_candidate_ids"]
    merge_candidate_ids = p2["merge_candidate_ids"]
    delineation_candidate_hhdivthres = p2["delineation_candidate_hhdivthres"]

    road_index = p3["road_index"]
    road_geoms = p3["road_geoms"]
    river_index = p3["river_index"]
    river_geoms = p3["river_geoms"]

    eas = p4["eas"]

    def is_parent_delineation_candidate(ea_item):
        orig_id = ea_item.get('original_id')
        if orig_id is None or orig_id not in delineation_candidate_ids:
            return False
        if eadel_indi_col_idx != -1 and orig_id in full_ea_by_id:
            val = full_ea_by_id[orig_id].attribute(eadel_indi_col_idx)
            if val is not None and str(val).strip().lower() in ("for delineation", "for_delineation"):
                return True
        return True

    def is_delineation_candidate(ea_item):
        if ea_item.get('from_split', False) or ea_item.get('from_merge', False):
            return False
        if ea_item.get('is_special_ea', False):
            return False
        orig_id = ea_item.get('original_id')
        if orig_id is None or orig_id not in delineation_candidate_ids:
            return False
        return True

    def is_merge_candidate(ea_item):
        if ea_item.get('from_split', False) or ea_item.get('from_merge', False):
            return False
        if ea_item.get('is_special_ea', False):
            return False
        orig_id = ea_item.get('original_id')
        return (orig_id in merge_candidate_ids) or (ea_item['hh_count'] <= min_household)

    def enforce_min_household(parts, fback, ea_geom=None):
        while len(parts) > 1:
            under = [i for i, p in enumerate(parts) if p['hh_count'] < min_household]
            if not under:
                break
            under.sort(key=lambda i: parts[i]['hh_count'])
            up_idx = under[0]
            up = parts[up_idx]

            best_idx = -1
            best_overlap = -1.0
            for j, nb in enumerate(parts):
                if j == up_idx:
                    continue
                if is_delineation_candidate(nb):
                    continue
                if up['geom'].intersects(nb['geom']) or up['geom'].touches(nb['geom']):
                    inter = up['geom'].intersection(nb['geom'])
                    overlap = inter.length() if not inter.isEmpty() else 0.0
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_idx = j

            if best_idx == -1:
                up_centroid = up['geom'].centroid().asPoint()
                best_dist = float('inf')
                best_dist_over = float('inf')
                best_idx_over = -1
                for j, nb in enumerate(parts):
                    if j == up_idx:
                        continue
                    if is_delineation_candidate(nb):
                        continue
                    dist = up_centroid.distance(nb['geom'].centroid().asPoint())
                    combined = up['hh_count'] + nb['hh_count']
                    if combined <= max_household:
                        if dist < best_dist:
                            best_dist = dist
                            best_idx = j
                    else:
                        if dist < best_dist_over:
                            best_dist_over = dist
                            best_idx_over = j
                if best_idx == -1:
                    best_idx = best_idx_over

            # Fallback 1: Allow touching / intersecting neighbor even if candidate
            if best_idx == -1:
                for j, nb in enumerate(parts):
                    if j == up_idx:
                        continue
                    if up['geom'].intersects(nb['geom']) or up['geom'].touches(nb['geom']):
                        inter = up['geom'].intersection(nb['geom'])
                        overlap = inter.length() if not inter.isEmpty() else 0.0
                        if overlap > best_overlap:
                            best_overlap = overlap
                            best_idx = j

            # Fallback 2: Nearest neighbor by centroid
            if best_idx == -1:
                up_centroid = up['geom'].centroid().asPoint()
                best_dist = float('inf')
                for j, nb in enumerate(parts):
                    if j == up_idx:
                        continue
                    dist = up_centroid.distance(nb['geom'].centroid().asPoint())
                    if dist < best_dist:
                        best_dist = dist
                        best_idx = j

            if best_idx == -1:
                break

            nb = parts[best_idx]
            raw_combined = nb['geom'].combine(up['geom']).buffer(0.0, 3)
            if ea_geom is not None:
                clipped = raw_combined.intersection(ea_geom).buffer(0.0, 3)
                nb['geom'] = clipped if not clipped.isEmpty() else raw_combined
            else:
                nb['geom'] = raw_combined
            nb['buildings'].extend(up['buildings'])
            nb['hh_count'] += up['hh_count']
            nb['bldg_count'] = len(nb['buildings'])
            parts.pop(up_idx)
        return parts

    def enforce_bldgpv_threshold(parts, hhdivthres, fback, ea_geom=None):
        while len(parts) > 1:
            parts_with_pv = []
            for idx, p in enumerate(parts):
                pv = sum(b.get('bldgpoints_value', 0.0) for b in p['buildings'])
                parts_with_pv.append((idx, pv))

            parts_with_pv.sort(key=lambda x: x[1], reverse=True)
            _max_bldgpv = parts_with_pv[0][1]

            if _max_bldgpv < hhdivthres:
                break

            up_idx = parts_with_pv[0][0]
            up = parts[up_idx]

            best_idx = -1
            best_overlap = -1.0
            for j, nb in enumerate(parts):
                if j == up_idx:
                    continue
                if up['geom'].intersects(nb['geom']) or up['geom'].touches(nb['geom']):
                    inter = up['geom'].intersection(nb['geom'])
                    overlap = inter.length() if not inter.isEmpty() else 0.0
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_idx = j

            if best_idx == -1:
                up_centroid = up['geom'].centroid().asPoint()
                best_dist = float('inf')
                for j, nb in enumerate(parts):
                    if j == up_idx:
                        continue
                    dist = up_centroid.distance(nb['geom'].centroid().asPoint())
                    if dist < best_dist:
                        best_dist = dist
                        best_idx = j

            if best_idx == -1:
                for j, nb in enumerate(parts):
                    if j != up_idx:
                        best_idx = j
                        break

            if best_idx == -1:
                break

            nb = parts[best_idx]
            raw_combined = nb['geom'].combine(up['geom']).buffer(0.0, 3)
            if ea_geom is not None:
                clipped = raw_combined.intersection(ea_geom).buffer(0.0, 3)
                nb['geom'] = clipped if not clipped.isEmpty() else raw_combined
            else:
                nb['geom'] = raw_combined

            nb['buildings'].extend(up['buildings'])
            nb['hh_count'] += up['hh_count']
            nb['bldg_count'] = len(nb['buildings'])

            parts.pop(up_idx)

        return parts

    def split_ea_voronoi(ea_item, target_pop, fback, split_by='none'):
        if fback.isCanceled():
            return [ea_item]
        bldgs = ea_item.get('buildings', [])
        if not bldgs:
            fback.pushWarning(f"[EA {ea_item['original_code']}] DIAGNOSTIC: Split skipped — no building points matched to this EA.")
            return [ea_item]

        coord_to_pt = {}
        for b in bldgs:
            pt = b['point']
            coord_to_pt[(pt.x(), pt.y())] = pt
        unique_pts = list(coord_to_pt.values())

        if len(unique_pts) < 2:
            fback.pushWarning(f"[EA {ea_item['original_code']}] DIAGNOSTIC: Split skipped — only {len(unique_pts)} unique building point(s). Need at least 2 unique locations to generate Voronoi.")
            ea_item['split_by'] = split_by
            return [ea_item]

        hh_cnt = sum(b['pop'] for b in bldgs)
        k_val = max(2, int(round(hh_cnt / float(max_household))))
        k_val = min(k_val, len(unique_pts))
        if k_val < 2:
            ea_item['split_by'] = split_by
            return [ea_item]

        _OUTLIER_FACTOR = 3.0
        kmeans_pts = unique_pts

        if len(unique_pts) >= 6:
            _local_idx = QgsSpatialIndex()
            for _i_pt, _q_pt in enumerate(unique_pts):
                _pf = QgsFeature(_i_pt)
                _pf.setGeometry(QgsGeometry.fromPointXY(_q_pt))
                _local_idx.addFeature(_pf)

            _nn_dists = []
            for _i_pt, _q_pt in enumerate(unique_pts):
                _neighbors = _local_idx.nearestNeighbor(_q_pt, 2)
                _nn_d = float('inf')
                for _n_id in _neighbors:
                    if _n_id != _i_pt:
                        _n_pt = unique_pts[_n_id]
                        _nn_d = math.hypot(_q_pt.x() - _n_pt.x(), _q_pt.y() - _n_pt.y())
                        break
                _nn_dists.append(_nn_d)

            _sorted_d = sorted(d for d in _nn_dists if d < float('inf'))
            if _sorted_d:
                _median_nn = _sorted_d[len(_sorted_d) // 2]
                if _median_nn > 0:
                    _outlier_thr = _OUTLIER_FACTOR * _median_nn
                    _core = [q for q, d in zip(unique_pts, _nn_dists) if d <= _outlier_thr]
                    _n_outliers = sum(1 for d in _nn_dists if d > _outlier_thr)
                    if _n_outliers > 0 and len(_core) >= 2:
                        fback.pushInfo(
                            f"[EA {ea_item['original_code']}] Outlier filter: "
                            f"{_n_outliers} isolated building location(s) excluded from "
                            f"K-Means (NN dist > {_outlier_thr:.6f}, median={_median_nn:.6f}). "
                            f"Will be assigned via Voronoi containment after split."
                        )
                        kmeans_pts = _core

        k_val = min(k_val, len(kmeans_pts))
        if k_val < 2:
            kmeans_pts = unique_pts
            k_val = min(max(2, int(round(hh_cnt / float(target_pop)))), len(unique_pts))
            if k_val < 2:
                ea_item['split_by'] = split_by
                return [ea_item]

        pts = [(pt.x(), pt.y()) for pt in kmeans_pts]
        pt_to_weight = {}
        for b in bldgs:
            pt_key = (b['point'].x(), b['point'].y())
            pt_to_weight[pt_key] = pt_to_weight.get(pt_key, 0.0) + b['pop']
        wts = [pt_to_weight.get((pt.x(), pt.y()), 1.0) for pt in kmeans_pts]

        labels, centroids = weighted_kmeans(pts, wts, k_val)

        centroid_pts = [QgsPointXY(c[0], c[1]) for c in centroids]
        points_geom = QgsGeometry.fromMultiPointXY(centroid_pts)

        bbox = ea_item['geom'].boundingBox()
        buffer_size = max(0.01, max(bbox.width(), bbox.height()) * 0.2)
        extent_geom = QgsGeometry.fromRect(bbox.buffered(buffer_size))

        voronoi_geom = points_geom.voronoiDiagram(extent_geom)
        if voronoi_geom.isEmpty():
            ea_item['split_by'] = split_by
            return [ea_item]

        cells = get_polygons_from_geom(voronoi_geom)
        if not cells:
            ea_item['split_by'] = split_by
            return [ea_item]

        road_lines = collect_linear_features(ea_item['geom'], road_index, road_geoms)
        river_lines = collect_linear_features(ea_item['geom'], river_index, river_geoms)
        all_lines = road_lines + river_lines
        if all_lines:
            from qgis.analysis import QgsGeometrySnapper
            line_index = QgsSpatialIndex()
            line_map = {}
            for l_idx, line in enumerate(all_lines):
                feat = QgsFeature(l_idx)
                feat.setGeometry(line)
                line_index.addFeature(feat)
                line_map[l_idx] = line

            snapped_cells = []
            for cell_geom in cells:
                buffered_bbox = cell_geom.boundingBox().buffered(snap_tolerance)
                candidate_line_ids = line_index.intersects(buffered_bbox)

                if not candidate_line_ids:
                    snapped_cells.append(cell_geom)
                    continue

                nearby_lines = [line_map[lid] for lid in candidate_line_ids]

                densified_cell = cell_geom.densifyByDistance(densify_dist)
                snapped_cell = QgsGeometrySnapper.snapGeometry(
                    densified_cell,
                    snap_tolerance,
                    nearby_lines,
                    QgsGeometrySnapper.PreferClosest
                )
                clean_snapped_cell = snapped_cell.buffer(0.0, 3)
                if clean_snapped_cell and not clean_snapped_cell.isEmpty():
                    snapped_cells.append(clean_snapped_cell)
                else:
                    snapped_cells.append(cell_geom)
            cells = snapped_cells

        all_candidate_polys = []
        for cell_geom in cells:
            intersected = ea_item['geom'].intersection(cell_geom)
            if not intersected.isEmpty():
                all_candidate_polys.extend(get_polygons_from_geom(intersected))

        if not all_candidate_polys:
            ea_item['split_by'] = split_by
            return [ea_item]

        assigned_bldgs_list = assign_buildings_to_parts(bldgs, all_candidate_polys, fback, ea_item.get('original_code', ''))
        split_parts = []
        for poly, buildings_in_poly in zip(all_candidate_polys, assigned_bldgs_list):
            sub_pop = sum(b['pop'] for b in buildings_in_poly)
            split_parts.append({
                'geom': poly,
                'buildings': buildings_in_poly,
                'hh_count': sub_pop,
                'original_hhcount': ea_item.get('original_hhcount') if ea_item.get('original_hhcount') is not None else ea_item.get('hh_count', 0.0),
                'original_bldgcount': ea_item.get('original_bldgcount') if ea_item.get('original_bldgcount') is not None else ea_item.get('bldg_count', 0),
                'bldg_count': len(buildings_in_poly),
                'bldgpoints_value': sub_pop / len(buildings_in_poly) if len(buildings_in_poly) > 0 else 0.0,
                'attributes': list(ea_item['attributes']),
                'original_id': ea_item['original_id'],
                'original_code': ea_item['original_code'],
                'is_new': True,
                'from_split': True,
                'split_by': split_by,
                'parent_barangay': ea_item['parent_barangay']
            })

        zero_parts = [p for p in split_parts if p['hh_count'] == 0]
        nonzero_parts = [p for p in split_parts if p['hh_count'] > 0]

        if not nonzero_parts:
            ea_item['split_by'] = split_by
            return [ea_item]

        progress = True
        while zero_parts and progress:
            progress = False
            remaining_zero = []
            for zp in zero_parts:
                best_neighbor = None
                best_overlap = -1.0
                for np in nonzero_parts:
                    if zp['geom'].intersects(np['geom']) or zp['geom'].touches(np['geom']):
                        inter = zp['geom'].intersection(np['geom'])
                        overlap = inter.length() if not inter.isEmpty() else 0.0
                        if overlap > best_overlap:
                            best_overlap = overlap
                            best_neighbor = np
                if best_neighbor is not None:
                    raw_combined = best_neighbor['geom'].combine(zp['geom']).buffer(0.0, 3)
                    clipped = raw_combined.intersection(ea_item['geom']).buffer(0.0, 3)
                    best_neighbor['geom'] = clipped if not clipped.isEmpty() else raw_combined
                    best_neighbor['buildings'].extend(zp['buildings'])
                    best_neighbor['bldg_count'] = len(best_neighbor['buildings'])
                    progress = True
                else:
                    remaining_zero.append(zp)
            zero_parts = remaining_zero

        for zp in zero_parts:
            zp_centroid = zp['geom'].centroid().asPoint()
            best_neighbor = min(
                nonzero_parts,
                key=lambda np: zp_centroid.distance(np['geom'].centroid().asPoint())
            )
            raw_combined = best_neighbor['geom'].combine(zp['geom']).buffer(0.0, 3)
            clipped = raw_combined.intersection(ea_item['geom']).buffer(0.0, 3)
            best_neighbor['geom'] = clipped if not clipped.isEmpty() else raw_combined
            best_neighbor['buildings'].extend(zp['buildings'])
            best_neighbor['bldg_count'] = len(best_neighbor['buildings'])

        split_parts = nonzero_parts
        split_parts = enforce_min_household(split_parts, fback, ea_geom=ea_item['geom'])

        if len(split_parts) < 2:
            if is_delineation_candidate(ea_item):
                fback.pushInfo(f"[EA {ea_item['original_code']}] Sequential/Voronoi split returned < 2 parts. Falling back to forced geometric split...")
                return force_geometric_split(ea_item, target_pop, fback)
            ea_item['split_by'] = split_by
            return [ea_item]

        orig_code_str = str(ea_item['original_code']).strip() if ea_item['original_code'] is not None else "000"
        digits = "".join([c for c in orig_code_str if c.isdigit()])
        orig_first3 = digits[:3] if len(digits) >= 3 else digits.zfill(3)

        if orig_first3 != "000" and len(split_parts) > 0:
            split_parts.sort(key=lambda x: x['hh_count'], reverse=True)
            split_parts[0]['is_new'] = False

        parent_geom = ea_item['geom']
        for p in split_parts:
            clipped = p['geom'].intersection(parent_geom).buffer(0.0, 3)
            if not clipped.isEmpty():
                p['geom'] = clipped
        split_parts, _ = allocate_gaps_to_parts(split_parts, parent_geom)
        return split_parts

    def force_geometric_split(ea_item, target_pop, fback):
        hh_cnt = ea_item['hh_count']
        bldgs = ea_item.get('buildings', [])
        bbox = ea_item['geom'].boundingBox()

        def make_strips(n, horizontal):
            strips = []
            for i in range(n):
                if horizontal:
                    span = bbox.height() / n
                    y0 = bbox.yMinimum() + i * span
                    y1 = bbox.yMinimum() + (i + 1) * span
                    pts = [
                        QgsPointXY(bbox.xMinimum(), y0),
                        QgsPointXY(bbox.xMaximum(), y0),
                        QgsPointXY(bbox.xMaximum(), y1),
                        QgsPointXY(bbox.xMinimum(), y1),
                        QgsPointXY(bbox.xMinimum(), y0),
                    ]
                else:
                    span = bbox.width() / n
                    x0 = bbox.xMinimum() + i * span
                    x1 = bbox.xMinimum() + (i + 1) * span
                    pts = [
                        QgsPointXY(x0, bbox.yMinimum()),
                        QgsPointXY(x1, bbox.yMinimum()),
                        QgsPointXY(x1, bbox.yMaximum()),
                        QgsPointXY(x0, bbox.yMaximum()),
                        QgsPointXY(x0, bbox.yMinimum()),
                    ]
                strip_geom = QgsGeometry.fromPolygonXY([pts])
                intersected = ea_item['geom'].intersection(strip_geom)
                if not intersected.isEmpty():
                    strips.extend(get_polygons_from_geom(intersected))
            return strips

        use_horizontal = bbox.height() >= bbox.width()
        eff_target = float(target_pop) if target_pop and float(target_pop) > 0 else float(max_household if max_household > 0 else 200)
        eff_hh_cnt = float(hh_cnt) if hh_cnt and float(hh_cnt) > 0 else float(len(bldgs) if bldgs else 200)
        k_start = max(2, math.ceil(eff_hh_cnt / eff_target))
        k_max = k_start + 4

        accepted_parts = None
        accepted_k = None
        accepted_orientation = use_horizontal

        for k_val in range(k_start, k_max + 1):
            strip_polys = make_strips(k_val, horizontal=use_horizontal)
            orientation = 'horizontal'
            if len(strip_polys) < 2:
                strip_polys = make_strips(k_val, horizontal=not use_horizontal)
                orientation = 'vertical'

            if len(strip_polys) < 2:
                break

            parts = []
            for poly in strip_polys:
                buildings_in_poly = []
                for b in bldgs:
                    pt_geom = QgsGeometry.fromPointXY(b['point'])
                    if poly.contains(pt_geom) or poly.intersects(pt_geom):
                        buildings_in_poly.append(b)
                sub_pop = sum(b['pop'] for b in buildings_in_poly)
                parts.append({
                    'geom': poly,
                    'buildings': buildings_in_poly,
                    'hh_count': sub_pop,
                    'original_hhcount': ea_item.get('original_hhcount') if ea_item.get('original_hhcount') is not None else ea_item.get('hh_count', 0.0),
                    'original_bldgcount': ea_item.get('original_bldgcount') if ea_item.get('original_bldgcount') is not None else ea_item.get('bldg_count', 0),
                    'bldg_count': len(buildings_in_poly),
                    'bldgpoints_value': sub_pop / len(buildings_in_poly) if len(buildings_in_poly) > 0 else 0.0,
                    'attributes': list(ea_item['attributes']),
                    'original_id': ea_item['original_id'],
                    'original_code': ea_item['original_code'],
                    'is_new': True,
                    'from_split': True,
                    'split_by': 'forced_grid',
                    'parent_barangay': ea_item['parent_barangay']
                })

            is_parent_delin = is_parent_delineation_candidate(ea_item)
            if is_parent_delin:
                nonzero_parts = list(parts)
                zero_parts = []
            else:
                zero_parts = [p for p in parts if p['hh_count'] == 0]
                nonzero_parts = [p for p in parts if p['hh_count'] > 0]

            if not nonzero_parts:
                continue

            for zp in zero_parts:
                zp_centroid = zp['geom'].centroid().asPoint()
                best_nb = min(
                    nonzero_parts,
                    key=lambda np: zp_centroid.distance(np['geom'].centroid().asPoint())
                )
                raw_combined = best_nb['geom'].combine(zp['geom']).buffer(0.0, 3)
                clipped = raw_combined.intersection(ea_item['geom'])
                best_nb['geom'] = clipped if not clipped.isEmpty() else raw_combined
                best_nb['buildings'].extend(zp['buildings'])
                best_nb['bldg_count'] = len(best_nb['buildings'])

            parts = enforce_min_household(nonzero_parts, fback, ea_geom=ea_item['geom'])

            if len(parts) < 2:
                continue

            all_valid = all(min_household <= p['hh_count'] <= max_household for p in parts)

            if accepted_parts is None or all_valid:
                accepted_parts = parts
                accepted_k = k_val
                accepted_orientation = orientation

            if all_valid:
                break

        if accepted_parts is None:
            # Absolute fail-safe: slice polygon directly into 2 halves
            half_strips = make_strips(2, horizontal=use_horizontal)
            if len(half_strips) < 2:
                half_strips = make_strips(2, horizontal=not use_horizontal)
            if len(half_strips) >= 2:
                half_parts = []
                for sp in half_strips:
                    sp_bldgs = [b for b in bldgs if sp.contains(QgsGeometry.fromPointXY(b['point'])) or sp.intersects(QgsGeometry.fromPointXY(b['point']))]
                    sp_pop = sum(b['pop'] for b in sp_bldgs)
                    half_parts.append({
                        'geom': sp,
                        'buildings': sp_bldgs,
                        'hh_count': sp_pop,
                        'original_hhcount': ea_item.get('original_hhcount') if ea_item.get('original_hhcount') is not None else ea_item.get('hh_count', 0.0),
                        'original_bldgcount': ea_item.get('original_bldgcount') if ea_item.get('original_bldgcount') is not None else ea_item.get('bldg_count', 0),
                        'bldg_count': len(sp_bldgs),
                        'bldgpoints_value': sp_pop / len(sp_bldgs) if len(sp_bldgs) > 0 else 0.0,
                        'attributes': list(ea_item['attributes']),
                        'original_id': ea_item['original_id'],
                        'original_code': ea_item['original_code'],
                        'is_new': True,
                        'from_split': True,
                        'split_by': 'forced_grid',
                        'parent_barangay': ea_item['parent_barangay']
                    })
                half_parts = enforce_min_household(half_parts, fback, ea_geom=ea_item['geom'])
                if len(half_parts) >= 2 and all(p['hh_count'] >= min_household for p in half_parts):
                    accepted_parts = half_parts
                    accepted_k = 2
                    accepted_orientation = 'horizontal' if use_horizontal else 'vertical'
                else:
                    fback.pushWarning(
                        f"[EA {ea_item['original_code']}] FORCED SPLIT: Fail-safe half split cannot meet "
                        f"min threshold ({min_household} HH). EA will remain whole."
                    )
                    return [ea_item]
            else:
                fback.pushWarning(
                    f"[EA {ea_item['original_code']}] FORCED SPLIT: Could not produce >= 2 valid "
                    f"parts at any k ({k_start}–{k_max}). EA will remain over threshold."
                )
                return [ea_item]

        final_parts = []
        for part in accepted_parts:
            if part['hh_count'] > max_household:
                if part.get('from_merge', False):
                    final_parts.append(part)
                    continue
                sub_result = force_geometric_split(part, target_pop, fback)
                if len(sub_result) > 1:
                    final_parts.extend(sub_result)
                else:
                    final_parts.append(part)
            else:
                final_parts.append(part)

        final_parts = enforce_min_household(final_parts, fback, ea_geom=ea_item['geom'])
        if len(final_parts) < 2 or any(p['hh_count'] < min_household for p in final_parts):
            fback.pushWarning(
                f"[EA {ea_item['original_code']}] FORCED SPLIT: Resulting sub-polygons fall below min threshold "
                f"({min_household} HH). Keeping EA whole."
            )
            return [ea_item]

        orig_code_str = str(ea_item['original_code']).strip() if ea_item['original_code'] is not None else "000"
        digits = "".join([c for c in orig_code_str if c.isdigit()])
        orig_first3 = digits[:3] if len(digits) >= 3 else digits.zfill(3)
        if orig_first3 != "000" and len(final_parts) > 0:
            final_parts.sort(key=lambda x: x['hh_count'], reverse=True)
            final_parts[0]['is_new'] = False

        final_parts, _ = allocate_gaps_to_parts(final_parts, ea_item['geom'])

        parent_geom = ea_item['geom']
        for p in final_parts:
            clipped = p['geom'].intersection(parent_geom).buffer(0.0, 3)
            if not clipped.isEmpty():
                p['geom'] = clipped
            p['split_by'] = 'forced_grid'
            p['remarks'] = ""

        fback.pushWarning(
            f"[EA {ea_item['original_code']}] FORCED SPLIT: Applied {accepted_orientation} "
            f"strip split (k={accepted_k}) — EA (hh_count={hh_cnt}) → {len(final_parts)} part(s)."
        )
        return final_parts

    def split_ea_voronoi_road_hybrid(ea_item, road_lines, river_lines, target_pop, fback):
        """
        Hybrid Voronoi Population Clustering + Road/River Boundary Alignment:
        1. Voronoi / Weighted K-Means determines population distribution (HH truth).
        2. Road & River lines partition the EA into physical atomic blocks.
        3. Blocks are assigned to Voronoi clusters by majority building population.
        4. Blocks per cluster are dissolved to form field-surveyable sub-EAs with road/river boundaries.
        5. Exact building assignment via assign_buildings_to_parts guarantees zero HH lost, zero HH duplicated.
        """
        if fback.isCanceled():
            return [ea_item]

        bldgs = ea_item.get('buildings', [])
        if not bldgs:
            return [ea_item]

        parent_geom = ea_item['geom']
        hh_cnt = sum(b['pop'] for b in bldgs)
        target = target_pop if target_pop > 0 else 200
        k_val = max(2, int(round(hh_cnt / float(target))))

        coord_to_pt = {}
        for b in bldgs:
            pt = b['point']
            pt_xy = pt if isinstance(pt, QgsPointXY) else QgsPointXY(pt[0], pt[1])
            coord_to_pt[(pt_xy.x(), pt_xy.y())] = pt_xy
        unique_pts = list(coord_to_pt.values())

        if len(unique_pts) < 2:
            return [ea_item]

        k_val = min(k_val, len(unique_pts))
        if k_val < 2:
            k_val = 2

        # ── Step 1: Population Clustering (Weighted K-Means) ──
        pts = [(pt.x(), pt.y()) for pt in unique_pts]
        pt_to_weight = {}
        for b in bldgs:
            pt = b['point']
            pt_xy = pt if isinstance(pt, QgsPointXY) else QgsPointXY(pt[0], pt[1])
            pt_key = (pt_xy.x(), pt_xy.y())
            pt_to_weight[pt_key] = pt_to_weight.get(pt_key, 0.0) + b['pop']
        wts = [pt_to_weight.get((pt.x(), pt.y()), 1.0) for pt in unique_pts]

        labels, centroids = weighted_kmeans(pts, wts, k_val)
        centroid_pts = [QgsPointXY(c[0], c[1]) for c in centroids]

        # ── Step 2: Physical Road/River Mesh Slicing via Polygonization ──
        # Prioritize main road bisector by sorting input lines by length inside parent EA
        all_input_lines = sorted(
            road_lines + river_lines,
            key=lambda lg: lg.intersection(parent_geom).length() if lg and not lg.isEmpty() else 0.0,
            reverse=True
        )
        if not all_input_lines:
            return [ea_item]

        # Primary method: Polygonize boundary lines + road/river lines
        lines_to_union = []
        if parent_geom.isMultipart():
            for poly in parent_geom.asMultiPolygon():
                for ring in poly:
                    lines_to_union.append(QgsGeometry.fromPolylineXY(ring))
        else:
            for ring in parent_geom.asPolygon():
                lines_to_union.append(QgsGeometry.fromPolylineXY(ring))

        for lg in all_input_lines:
            if lg and not lg.isEmpty():
                inter = lg.intersection(parent_geom)
                if not inter.isEmpty():
                    lines_to_union.append(inter)

        atomic_blocks = []
        if len(lines_to_union) >= 2:
            noded = QgsGeometry.unaryUnion(lines_to_union)
            if noded and not noded.isEmpty():
                poly_collection = QgsGeometry.polygonize([noded])
                if poly_collection and not poly_collection.isEmpty():
                    for face in get_polygons_from_geom(poly_collection):
                        if face and not face.isEmpty() and face.area() > 1e-6:
                            clipped = face.intersection(parent_geom).buffer(0.0, 3)
                            if not clipped.isEmpty() and clipped.area() > 1e-6:
                                atomic_blocks.append(clipped)

        # Fallback method: Ray extension slicing if polygonization yielded < 2 blocks
        if len(atomic_blocks) < 2:
            all_polylines = []
            for lg in all_input_lines:
                all_polylines.extend(get_polylines_from_geom(lg))

            if not all_polylines:
                return [ea_item]

            bbox = parent_geom.boundingBox()
            ext_len = max(100.0, max(bbox.width(), bbox.height()) * 3.0)

            current_polys = [parent_geom]
            used_split = False

            for polyline in all_polylines:
                if len(polyline) < 2:
                    continue

                p0, p1 = polyline[0], polyline[1]
                dx0, dy0 = p0.x() - p1.x(), p0.y() - p1.y()
                len0 = math.hypot(dx0, dy0)
                p0_ext = QgsPointXY(p0.x() + (dx0 / len0) * ext_len, p0.y() + (dy0 / len0) * ext_len) if len0 > 1e-7 else p0

                pn, pn_prev = polyline[-1], polyline[-2]
                dxn, dyn = pn.x() - pn_prev.x(), pn.y() - pn_prev.y()
                lenn = math.hypot(dxn, dyn)
                pn_ext = QgsPointXY(pn.x() + (dxn / lenn) * ext_len, pn.y() + (dyn / lenn) * ext_len) if lenn > 1e-7 else pn

                extended_line = [p0_ext] + list(polyline) + [pn_ext]

                next_polys = []
                for poly in current_polys:
                    target_geom = QgsGeometry(poly)
                    res, new_geoms, _ = target_geom.splitGeometry(extended_line, False)
                    if res == 0 and len(new_geoms) > 0:
                        split_pieces = [target_geom] + new_geoms
                        valid_pieces = []
                        for sp in split_pieces:
                            if sp and not sp.isEmpty() and sp.area() > 1e-6:
                                clipped = sp.intersection(parent_geom).buffer(0.0, 3)
                                if not clipped.isEmpty() and clipped.area() > 1e-6:
                                    valid_pieces.append(clipped)
                        if len(valid_pieces) >= 2:
                            next_polys.extend(valid_pieces)
                            used_split = True
                        else:
                            next_polys.append(poly)
                    else:
                        next_polys.append(poly)
                current_polys = next_polys

            if not used_split or len(current_polys) < 2:
                return [ea_item]

            atomic_blocks = []
            for cp in current_polys:
                atomic_blocks.extend(get_polygons_from_geom(cp))

        atomic_blocks = [ab for ab in atomic_blocks if ab and not ab.isEmpty() and ab.area() > 1e-6]
        if len(atomic_blocks) < 2:
            return [ea_item]

        # ── Step 3: Assign Atomic Blocks to Voronoi Clusters (Majority Building Vote) ──
        block_bldgs_assigned = assign_buildings_to_parts(bldgs, atomic_blocks, fback, ea_item.get('original_code', ''))

        block_cluster_mapping = []
        for blk_idx, (blk_geom, blk_bldgs) in enumerate(zip(atomic_blocks, block_bldgs_assigned)):
            if blk_bldgs:
                cluster_votes = [0.0] * len(centroid_pts)
                for b in blk_bldgs:
                    b_pt = b['point']
                    b_xy = b_pt if isinstance(b_pt, QgsPointXY) else QgsPointXY(b_pt[0], b_pt[1])
                    closest_c = min(
                        range(len(centroid_pts)),
                        key=lambda ci: math.hypot(b_xy.x() - centroid_pts[ci].x(), b_xy.y() - centroid_pts[ci].y())
                    )
                    cluster_votes[closest_c] += b['pop']
                best_cluster = max(range(len(centroid_pts)), key=lambda ci: cluster_votes[ci])
                block_cluster_mapping.append(best_cluster)
            else:
                blk_centroid = blk_geom.centroid().asPoint()
                best_cluster = min(
                    range(len(centroid_pts)),
                    key=lambda ci: math.hypot(blk_centroid.x() - centroid_pts[ci].x(), blk_centroid.y() - centroid_pts[ci].y())
                )
                block_cluster_mapping.append(best_cluster)

        # ── Step 4: Dissolve Blocks by Cluster ──
        cluster_geoms = {}
        for blk_geom, c_id in zip(atomic_blocks, block_cluster_mapping):
            if c_id not in cluster_geoms:
                cluster_geoms[c_id] = blk_geom
            else:
                cluster_geoms[c_id] = cluster_geoms[c_id].combine(blk_geom).buffer(0.0, 3)

        if len(cluster_geoms) < 2:
            return [ea_item]

        dissolved_parts = []
        for c_id, c_geom in cluster_geoms.items():
            clean_g = c_geom.intersection(parent_geom).buffer(0.0, 3)
            if clean_g and not clean_g.isEmpty() and clean_g.area() > 1e-6:
                polys = get_polygons_from_geom(clean_g)
                for p in polys:
                    if p and not p.isEmpty() and p.area() > 1e-6:
                        dissolved_parts.append(p)

        if len(dissolved_parts) < 2:
            return [ea_item]

        split_by = 'road'
        if road_lines and river_lines:
            split_by = 'road+river'
        elif river_lines:
            split_by = 'river'

        # ── Step 5: Assign Buildings & Build Part Dictionaries ──
        part_bldgs_list = assign_buildings_to_parts(bldgs, dissolved_parts, fback, ea_item.get('original_code', ''))

        parts = []
        for poly, p_bldgs in zip(dissolved_parts, part_bldgs_list):
            sub_pop = sum(b['pop'] for b in p_bldgs)
            parts.append({
                'geom': poly,
                'buildings': p_bldgs,
                'hh_count': sub_pop,
                'original_hhcount': ea_item.get('original_hhcount') if ea_item.get('original_hhcount') is not None else ea_item.get('hh_count', 0.0),
                'original_bldgcount': ea_item.get('original_bldgcount') if ea_item.get('original_bldgcount') is not None else ea_item.get('bldg_count', 0),
                'bldg_count': len(p_bldgs),
                'bldgpoints_value': sub_pop / len(p_bldgs) if len(p_bldgs) > 0 else 0.0,
                'attributes': list(ea_item['attributes']),
                'original_id': ea_item['original_id'],
                'original_code': ea_item['original_code'],
                'is_new': True,
                'from_split': True,
                'split_by': split_by,
                'parent_barangay': ea_item['parent_barangay']
            })

        def is_ribbon_polygon(p):
            g = p['geom']
            area = g.area()
            peri = g.length()
            if area <= 1e-7:
                return True
            thinness = (peri * peri) / area
            # If thinness ratio > 60 and HH count <= 25, it's an impractical thin ribbon strip
            if thinness > 60.0 and p['hh_count'] <= 25.0:
                return True
            return False

        # ── Step 6: Merge Zero-Population Fragments & Thin Ribbon Corridors into Adjacent Neighbor ──
        zero_parts = [p for p in parts if p['hh_count'] == 0 or is_ribbon_polygon(p)]
        nonzero_parts = [p for p in parts if p['hh_count'] > 0 and not is_ribbon_polygon(p)]

        if not nonzero_parts:
            return [ea_item]

        for zp in zero_parts:
            best_nb = None
            best_overlap = -1.0
            for np in nonzero_parts:
                if zp['geom'].intersects(np['geom']) or zp['geom'].touches(np['geom']):
                    inter = zp['geom'].intersection(np['geom'])
                    overlap = inter.length() if not inter.isEmpty() else 0.0
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_nb = np
            if best_nb is None:
                zp_centroid = zp['geom'].centroid().asPoint()
                best_nb = min(nonzero_parts, key=lambda np: math.hypot(zp_centroid.x() - np['geom'].centroid().asPoint().x(), zp_centroid.y() - np['geom'].centroid().asPoint().y()))

            raw_combined = best_nb['geom'].combine(zp['geom']).buffer(0.0, 3)
            clipped = raw_combined.intersection(parent_geom).buffer(0.0, 3)
            best_nb['geom'] = clipped if not clipped.isEmpty() else raw_combined
            best_nb['buildings'].extend(zp['buildings'])
            best_nb['bldg_count'] = len(best_nb['buildings'])

        parts = nonzero_parts
        if len(parts) < 2:
            return [ea_item]

        # ── Step 7: Enforce Minimum Household Limit ──
        parts = enforce_min_household(parts, fback, ea_geom=parent_geom)
        if len(parts) < 2:
            return [ea_item]

        # ── Step 8: Handle Oversized Sub-parts ──
        final_parts = []
        for p in parts:
            if p['hh_count'] > max_household:
                sub_parts = split_ea_by_building_clusters(p, target_pop, fback)
                if len(sub_parts) > 1:
                    final_parts.extend(sub_parts)
                else:
                    final_parts.append(p)
            else:
                final_parts.append(p)

        orig_code_str = str(ea_item['original_code']).strip() if ea_item['original_code'] is not None else "000"
        digits = "".join([c for c in orig_code_str if c.isdigit()])
        orig_first3 = digits[:3] if len(digits) >= 3 else digits.zfill(3)
        if orig_first3 != "000" and len(final_parts) > 0:
            final_parts.sort(key=lambda x: x['hh_count'], reverse=True)
            final_parts[0]['is_new'] = False

        final_parts, _ = allocate_gaps_to_parts(final_parts, parent_geom)

        # Final pass: Guarantee exact building assignment with assign_buildings_to_parts
        final_bldgs_list = assign_buildings_to_parts(bldgs, [p['geom'] for p in final_parts], fback, ea_item.get('original_code', ''))
        for p, p_bldgs in zip(final_parts, final_bldgs_list):
            clipped = p['geom'].intersection(parent_geom).buffer(0.0, 3)
            if not clipped.isEmpty():
                p['geom'] = clipped
            p['buildings'] = p_bldgs
            p['hh_count'] = sum(b['pop'] for b in p_bldgs)
            p['bldg_count'] = len(p_bldgs)
            p['bldgpoints_value'] = p['hh_count'] / p['bldg_count'] if p['bldg_count'] > 0 else 0.0
            p['split_by'] = split_by

        if any(p['hh_count'] < min_household for p in final_parts):
            final_parts = enforce_min_household(final_parts, fback, ea_geom=parent_geom)

        # Reject the split if any resulting part falls below the min_household threshold or fewer than 2 parts
        if len(final_parts) < 2 or any(p['hh_count'] < min_household for p in final_parts):
            under_parts = [p for p in final_parts if p['hh_count'] < min_household]
            fback.pushWarning(
                f"[EA {ea_item['original_code']}] Hybrid split rejected: "
                f"{len(under_parts)} sub-polygon(s) fall below min threshold "
                f"({min_household} HH). Keeping EA whole."
            )
            return [ea_item]

        return final_parts

    split_polygon_by_linear_features = split_ea_voronoi_road_hybrid

    def split_ea_by_building_clusters(ea_item, target_pop, fback):
        if fback.isCanceled():
            return [ea_item]

        bldgs = ea_item.get('buildings', [])
        if not bldgs:
            return [ea_item]

        coord_to_pt = {}
        for b in bldgs:
            pt = b['point']
            coord_to_pt[(pt.x(), pt.y())] = pt
        unique_pts = list(coord_to_pt.values())

        if len(unique_pts) < 2:
            return [ea_item]

        hh_cnt = ea_item['hh_count']
        target = target_pop if target_pop > 0 else 200
        k_val = max(2, int(round(hh_cnt / float(target))))
        k_val = min(k_val, len(unique_pts))
        if k_val < 2:
            k_val = 2

        pts = [(pt.x(), pt.y()) for pt in unique_pts]
        pt_to_weight = {}
        for b in bldgs:
            pt_key = (b['point'].x(), b['point'].y())
            pt_to_weight[pt_key] = pt_to_weight.get(pt_key, 0.0) + b['pop']
        wts = [pt_to_weight.get((pt.x(), pt.y()), 1.0) for pt in unique_pts]

        labels, centroids = weighted_kmeans(pts, wts, k_val)
        centroid_pts = [QgsPointXY(c[0], c[1]) for c in centroids]

        aligned_centroids = verify_point_cluster_alignment(bldgs, ea_item['geom'].boundingBox(), target, k_val)
        if len(aligned_centroids) >= 2:
            bbox = ea_item['geom'].boundingBox()
            if bbox.width() < 1000.0 or bbox.height() < 1000.0 or len(centroid_pts) < 2:
                centroid_pts = aligned_centroids

        unique_centroids = []
        seen_c = set()
        for cp in centroid_pts:
            ck = (round(cp.x(), 6), round(cp.y(), 6))
            if ck not in seen_c:
                seen_c.add(ck)
                unique_centroids.append(cp)

        if len(unique_centroids) < 2:
            unique_centroids = unique_pts[:k_val]

        points_geom = QgsGeometry.fromMultiPointXY(unique_centroids)
        bbox = ea_item['geom'].boundingBox()
        buffer_size = max(0.01, max(bbox.width(), bbox.height()) * 0.5)
        extent_geom = QgsGeometry.fromRect(bbox.buffered(buffer_size))

        voronoi_geom = points_geom.voronoiDiagram(extent_geom)
        if voronoi_geom.isEmpty():
            return [ea_item]

        cells = get_polygons_from_geom(voronoi_geom)
        if not cells:
            return [ea_item]

        parent_geom = ea_item['geom']
        candidate_polys = []
        for cell in cells:
            intersected = parent_geom.intersection(cell)
            if not intersected.isEmpty():
                candidate_polys.extend(get_polygons_from_geom(intersected))

        if not candidate_polys:
            return [ea_item]

        assigned_bldgs_list = assign_buildings_to_parts(bldgs, candidate_polys, fback, ea_item.get('original_code', ''))
        split_parts = []
        for poly, buildings_in_poly in zip(candidate_polys, assigned_bldgs_list):
            sub_pop = sum(b['pop'] for b in buildings_in_poly)
            split_parts.append({
                'geom': poly,
                'buildings': buildings_in_poly,
                'hh_count': sub_pop,
                'original_hhcount': ea_item.get('original_hhcount') if ea_item.get('original_hhcount') is not None else ea_item.get('hh_count', 0.0),
                'original_bldgcount': ea_item.get('original_bldgcount') if ea_item.get('original_bldgcount') is not None else ea_item.get('bldg_count', 0),
                'bldg_count': len(buildings_in_poly),
                'bldgpoints_value': sub_pop / len(buildings_in_poly) if len(buildings_in_poly) > 0 else 0.0,
                'attributes': list(ea_item['attributes']),
                'original_id': ea_item['original_id'],
                'original_code': ea_item['original_code'],
                'is_new': True,
                'from_split': True,
                'split_by': 'point_based',
                'parent_barangay': ea_item['parent_barangay']
            })

        zero_parts = [p for p in split_parts if p['hh_count'] == 0]
        nonzero_parts = [p for p in split_parts if p['hh_count'] > 0]

        if not nonzero_parts:
            return [ea_item]

        for zp in zero_parts:
            zp_centroid = zp['geom'].centroid().asPoint()
            best_neighbor = min(nonzero_parts, key=lambda np: zp_centroid.distance(np['geom'].centroid().asPoint()))
            raw_combined = best_neighbor['geom'].combine(zp['geom']).buffer(0.0, 3)
            clipped = raw_combined.intersection(parent_geom).buffer(0.0, 3)
            best_neighbor['geom'] = clipped if not clipped.isEmpty() else raw_combined
            best_neighbor['buildings'].extend(zp['buildings'])
            best_neighbor['bldg_count'] = len(best_neighbor['buildings'])

        split_parts = nonzero_parts
        split_parts = enforce_min_household(split_parts, fback, ea_geom=parent_geom)

        if len(split_parts) < 2:
            return [ea_item]

        final_parts = []
        for p in split_parts:
            if p['hh_count'] > max_household:
                sub_parts = split_ea_by_building_clusters(p, target_pop, fback)
                if len(sub_parts) > 1:
                    final_parts.extend(sub_parts)
                else:
                    final_parts.append(p)
            else:
                final_parts.append(p)

        orig_code_str = str(ea_item['original_code']).strip() if ea_item['original_code'] is not None else "000"
        digits = "".join([c for c in orig_code_str if c.isdigit()])
        orig_first3 = digits[:3] if len(digits) >= 3 else digits.zfill(3)
        if orig_first3 != "000" and len(final_parts) > 0:
            final_parts.sort(key=lambda x: x['hh_count'], reverse=True)
            final_parts[0]['is_new'] = False

        for p in final_parts:
            clipped = p['geom'].intersection(parent_geom).buffer(0.0, 3)
            if not clipped.isEmpty():
                p['geom'] = clipped
            p['split_by'] = 'point_based'

        final_parts, _ = allocate_gaps_to_parts(final_parts, parent_geom)

        if any(p['hh_count'] < min_household for p in final_parts):
            final_parts = enforce_min_household(final_parts, fback, ea_geom=parent_geom)

        # Reject the split if any resulting part falls below the min_household threshold or fewer than 2 parts
        if len(final_parts) < 2 or any(p['hh_count'] < min_household for p in final_parts):
            under_parts = [p for p in final_parts if p['hh_count'] < min_household]
            fback.pushWarning(
                f"[EA {ea_item['original_code']}] Building-cluster split rejected: "
                f"{len(under_parts)} sub-polygon(s) fall below min threshold "
                f"({min_household} HH). Keeping EA whole."
            )
            return [ea_item]

        return final_parts

    def split_ea(ea_item, target_pop, fback):
        if fback.isCanceled():
            return [ea_item]

        # Strict Candidate Gate: NEVER delineate EAs that are not in delineation_candidate_ids
        if not is_delineation_candidate(ea_item):
            fback.pushInfo(f"[EA {ea_item.get('original_code')}] Not in delineation candidates. Preserving whole.")
            return [ea_item]

        # Mode 4 or Strategy 2: Keep Whole (No Splitting)
        if split_type == 4 or split_strategy == 2:
            fback.pushInfo(f"[EA {ea_item['original_code']}] Strategy 'Keep Whole' selected. Preserving EA whole.")
            ea_item['remarks'] = ""
            return [ea_item]

        bldgs = ea_item.get('buildings', [])
        road_lines = collect_linear_features(ea_item['geom'], road_index, road_geoms)
        river_lines = collect_linear_features(ea_item['geom'], river_index, river_geoms)

        # Mode 3: Forced Geometric Cut Only
        if split_type == 3:
            fback.pushInfo(f"[EA {ea_item['original_code']}] Forced geometric split requested...")
            return force_geometric_split(ea_item, target_pop, fback)

        # Mode 2: Building Point Voronoi Clustering Only
        if split_type == 2:
            if bldgs:
                fback.pushInfo(f"[EA {ea_item['original_code']}] Splitting by building point Voronoi cluster distribution...")
                cluster_parts = split_ea_by_building_clusters(ea_item, target_pop, fback)
                if len(cluster_parts) >= 2:
                    return cluster_parts
            if is_delineation_candidate(ea_item):
                return force_geometric_split(ea_item, target_pop, fback)
            return [ea_item]

        # Mode 1: Road & River Alignment Only
        if split_type == 1:
            if road_lines or river_lines:
                fback.pushInfo(f"[EA {ea_item['original_code']}] Partitioning with Voronoi clustering and road/river boundary alignment...")
                hybrid_parts = split_ea_voronoi_road_hybrid(ea_item, road_lines, river_lines, target_pop, fback)
                if len(hybrid_parts) >= 2:
                    return hybrid_parts
            fback.pushWarning(f"[EA {ea_item['original_code']}] Road & River alignment unavailable or yielded 1 part. Keeping whole under Road/River Only mode.")
            return [ea_item]

        # Mode 0: Auto (Hybrid Road/River -> Voronoi -> Forced Cut) [Default]
        if not bldgs:
            if is_delineation_candidate(ea_item):
                fback.pushInfo(f"[EA {ea_item['original_code']}] Delineation candidate has no building points. Forcing geometric split...")
                return force_geometric_split(ea_item, target_pop, fback)
            return [ea_item]

        # ── Tier 1: Voronoi Population Clustering + Road/River Physical Boundaries ──
        if road_lines or river_lines:
            fback.pushInfo(f"[EA {ea_item['original_code']}] Partitioning with Voronoi clustering and road/river boundary alignment...")
            hybrid_parts = split_ea_voronoi_road_hybrid(ea_item, road_lines, river_lines, target_pop, fback)
            if len(hybrid_parts) >= 2:
                fback.pushInfo(
                    f"[EA {ea_item['original_code']}] Hybrid split succeeded: "
                    f"{len(hybrid_parts)} surveyable sub-polygons created along {hybrid_parts[0].get('split_by', 'road/river')}."
                )
                return hybrid_parts

        # ── Tier 2: Voronoi Building Point Cluster Partitioning (Fallback / No roads) ──
        fback.pushInfo(f"[EA {ea_item['original_code']}] Splitting by building point Voronoi cluster distribution...")
        cluster_parts = split_ea_by_building_clusters(ea_item, target_pop, fback)
        if len(cluster_parts) >= 2:
            fback.pushInfo(
                f"[EA {ea_item['original_code']}] Building-point Voronoi split accepted: "
                f"{len(cluster_parts)} parts created."
            )
            return cluster_parts

        # ── Tier 3: Last Resort Forced Geometric Split ──────────────────────────
        if is_delineation_candidate(ea_item):
            fback.pushWarning(
                f"[EA {ea_item['original_code']}] Hybrid and Voronoi splits could not partition EA. "
                f"Falling back to forced geometric split as last resort..."
            )
            return force_geometric_split(ea_item, target_pop, fback)

        return [ea_item]

    def process_barangay_split(bar_code, bar_eas, fback):
        processed_eas = []
        bar_proposed_lines = []

        for ea in bar_eas:
            if fback.isCanceled():
                break

            if not is_delineation_candidate(ea):
                processed_eas.append(ea)
                continue

            # Mode 4 or Strategy 2: Keep Whole (No Splitting)
            if split_type == 4 or split_strategy == 2:
                fback.pushInfo(f"[EA {ea['original_code']}] Strategy 'Keep Whole' selected. Preserving EA whole.")
                ea['remarks'] = ""
                processed_eas.append(ea)
                continue

            split_parts = split_ea(ea, max_household, fback)
            if len(split_parts) > 1:
                _ea_id = ea.get('original_id')
                _ea_ean = str(ea.get('original_code', '')).strip()
                _max_part_hh = max(p['hh_count'] for p in split_parts) if split_parts else 0
                if _max_part_hh > max_household:
                    fback.pushWarning(
                        f"[Barangay {bar_code}] [EA {ea['original_code']}] "
                        f"Part exceeds max_household ({_max_part_hh} > {max_household}). "
                        f"Re-delineating over-threshold sub-polygons to enforce {min_household}–{max_household} HH range."
                    )
                    sub_divided = []
                    for p in split_parts:
                        if p['hh_count'] > max_household:
                            sub_p = split_ea_by_building_clusters(p, max_household, fback)
                            sub_divided.extend(sub_p)
                        else:
                            sub_divided.append(p)
                    split_parts = enforce_min_household(sub_divided, fback, ea_geom=ea['geom'])

                if any(p['hh_count'] < min_household for p in split_parts):
                    split_parts = enforce_min_household(split_parts, fback, ea_geom=ea['geom'])

                if len(split_parts) > 1 and all(p['hh_count'] >= min_household for p in split_parts):
                    cut_line = extract_proposed_cut_line(split_parts, parent_geom=ea['geom'])
                    if cut_line and not cut_line.isEmpty():
                        bar_proposed_lines.append({
                            'ea_id': ea.get('original_id'),
                            'geom': cut_line,
                            'parent_ea': ea,
                            'split_by': split_parts[0].get('split_by', 'voronoi'),
                            'num_parts': len(split_parts),
                            'part_hh_counts': [p['hh_count'] for p in split_parts],
                        })
                        ea['has_proposed_split'] = True
                        ea['proposed_parts_count'] = len(split_parts)
                        ea['proposed_split_by'] = split_parts[0].get('split_by', 'voronoi')
                        ea['remarks'] = "Proposed for delineation"
                        fback.pushInfo(
                            f"[Barangay {bar_code}] Generated proposed boundary cut line for over-populated EA "
                            f"(code={ea['original_code']}, pop={ea['hh_count']}) into {len(split_parts)} proposed parts."
                        )
                    else:
                        fback.pushWarning(
                            f"[Barangay {bar_code}] [EA {ea['original_code']}] "
                            f"Could not extract proposed boundary cut line geometry. Preserving EA whole."
                        )
                else:
                    fback.pushWarning(
                        f"[Barangay {bar_code}] [EA {ea['original_code']}] "
                        f"Split rejected because resulting sub-polygon(s) fall below min threshold ({min_household} HH). Preserving EA whole."
                    )
            else:
                unique_pt_count = len(set((b['point'].x(), b['point'].y()) for b in ea.get('buildings', [])))
                reason = []
                if unique_pt_count < 2:
                    reason.append(f"only {unique_pt_count} unique building point(s) — Voronoi cannot split")
                if unique_pt_count >= 2:
                    k_needed = max(2, int(round(ea['hh_count'] / float(target_household))))
                    if k_needed > unique_pt_count:
                        reason.append(f"k={k_needed} required but only {unique_pt_count} unique points available")
                if not reason:
                    reason.append("splitting returned 1 part — check sliver threshold vs cell size")
                fback.pushWarning(
                    f"[Barangay {bar_code}] UNRESOLVED OVER-THRESHOLD: EA (code={ea['original_code']}, "
                    f"hh_count={ea['hh_count']}, bldg_count={ea.get('bldg_count',0)}, "
                    f"unique_pts={unique_pt_count}). "
                    f"Reason: {'; '.join(reason)}. Preserving EA whole."
                )

            # Preserve parent EA whole without splitting polygon
            processed_eas.append(ea)

        return processed_eas, bar_proposed_lines

    feedback.pushInfo("Running normal delineation...")

    barangay_groups = {}
    for ea in eas:
        bar = ea['parent_barangay']
        barangay_groups.setdefault(bar, []).append(ea)

    sorted_bar_keys = sorted(
        barangay_groups.keys(),
        key=lambda k: str(k) if k is not None else ""
    )

    split_bar_keys = [
        bar_code for bar_code in sorted_bar_keys
        if any(is_delineation_candidate(ea) for ea in barangay_groups[bar_code])
    ]

    multi_feedback.setCurrentStep(4)
    multi_feedback.setProgressText(
        f"{_PHASE_LABELS[4]} [0/{len(split_bar_keys)} barangay(s)]..."
    )

    def process_barangay_split_wrapper(bar_code, bar_eas, parent_feedback):
        result_eas, prop_lines = process_barangay_split(bar_code, bar_eas, parent_feedback)
        return (result_eas, prop_lines), []

    split_eas = []
    all_proposed_lines = []

    if split_bar_keys:
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_cores) as executor:
            futures = {
                executor.submit(process_barangay_split_wrapper, bar_code, barangay_groups[bar_code], feedback): bar_code 
                for bar_code in split_bar_keys
            }

            _last_n_done = -1
            while not all(f.done() for f in futures.keys()):
                if multi_feedback.isCanceled():
                    for f in futures.keys():
                        f.cancel()
                    raise QgsProcessingException("Algorithm cancelled by user.")
                time.sleep(0.02)
                if QThread.currentThread() == QCoreApplication.instance().thread():
                    QCoreApplication.processEvents()

                _n_done = sum(1 for f in futures.keys() if f.done())
                if _n_done != _last_n_done:
                    _pct = int(_n_done / len(futures) * 100) if futures else 0
                    multi_feedback.setProgress(_pct)
                    multi_feedback.setProgressText(
                        f"{_PHASE_LABELS[4]} [{_n_done}/{len(futures)} barangay(s) done]..."
                    )
                    _last_n_done = _n_done

            ordered_futures = {bar_code: future for future, bar_code in futures.items()}
            for bar_code in sorted_bar_keys:
                if bar_code in ordered_futures:
                    future = ordered_futures[bar_code]
                    if future.cancelled():
                        split_eas.extend(barangay_groups[bar_code])
                        continue
                    try:
                        (result, prop_lines), logs = future.result()
                        split_eas.extend(result)
                        all_proposed_lines.extend(prop_lines)
                        for log_type, msg in logs:
                            if log_type == 'info':
                                feedback.pushInfo(msg)
                            elif log_type == 'warning':
                                feedback.pushWarning(msg)
                    except Exception as e:
                        feedback.reportError(f"Error processing proposed delineation for Barangay {bar_code}: {str(e)}")
                else:
                    split_eas.extend(barangay_groups[bar_code])
    else:
        for bar_code in sorted_bar_keys:
            split_eas.extend(barangay_groups[bar_code])

    multi_feedback.setProgress(100)

    if multi_feedback.isCanceled():
        raise QgsProcessingException("Algorithm cancelled by user.")

    return {
        "split_eas": split_eas,
        "proposed_lines": all_proposed_lines,
    }
