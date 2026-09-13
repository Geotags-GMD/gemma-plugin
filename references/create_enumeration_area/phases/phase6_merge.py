import time
import concurrent.futures
from typing import Dict, Any, List

from qgis.core import (
    QgsProcessingException,
)
from qgis.PyQt.QtCore import QCoreApplication, QThread

from ..helpers.constants import _PHASE_LABELS


def run_phase_6(alg, parameters, context, feedback, multi_feedback, p1, p2, p5):
    """
    Executes Phase 6 (Iterative Per-Barangay Merging & Partner Allocation).

    Returns dictionary containing:
    - merged_eas: List[dict] of EAs after iterative merging
    """
    eadel_indi_col_idx = p1["eadel_indi_col_idx"]
    full_ea_by_id = p2["full_ea_by_id"]
    min_household = p1["min_household"]
    max_household = p1["max_household"]
    num_cores = p1.get("num_cores", QThread.idealThreadCount())

    delineation_candidate_ids = p2["delineation_candidate_ids"]
    merge_candidate_ids = p2["merge_candidate_ids"]

    split_eas = p5["split_eas"]

def is_delineation_candidate(ea_item, max_household, eadel_indi_col_idx=-1, full_ea_by_id=None, delineation_candidate_ids=None):
    if ea_item.get('from_split', False) or ea_item.get('from_merge', False):
        return False
    if ea_item.get('is_special_ea', False):
        return False
    if ea_item.get('has_proposed_split', False):
        return True
    orig_id = ea_item.get('original_id')
    if orig_id is None:
        return False
    if delineation_candidate_ids is not None:
        return orig_id in delineation_candidate_ids
    is_explicit = False
    if eadel_indi_col_idx != -1 and full_ea_by_id and orig_id in full_ea_by_id:
        val = full_ea_by_id[orig_id].attribute(eadel_indi_col_idx)
        is_explicit = (val is not None and str(val).strip().lower() in ("for delineation", "for_delineation"))
    if is_explicit and ea_item.get('hh_count', 0) > max_household:
        return True
    return ea_item.get('hh_count', 0) > max_household


def is_merge_candidate(ea_item, min_household, merge_candidate_ids=None):
    if ea_item.get('from_split', False) or ea_item.get('has_proposed_split', False):
        return False
    if ea_item.get('is_special_ea', False):
        return False
    if ea_item.get('from_merge', False):
        return ea_item.get('hh_count', 0.0) <= min_household
    orig_id = ea_item.get('original_id')
    merge_set = merge_candidate_ids or set()
    return (orig_id in merge_set) or (ea_item.get('hh_count', 0.0) <= min_household)


def process_barangay_merge(
    bar_code: str,
    bar_eas: List[dict],
    fback: Any,
    min_household: float = 100.0,
    max_household: float = 300.0,
    eadel_indi_col_idx: int = -1,
    full_ea_by_id: Dict[int, Any] = None,
    delineation_candidate_ids: Any = None,
    merge_candidate_ids: Any = None,
    allow_candidate_merge: bool = True,
) -> List[dict]:
    full_ea_by_id = full_ea_by_id or {}
    delineation_candidate_ids = delineation_candidate_ids or set()
    merge_candidate_ids = merge_candidate_ids or set()

    iteration = 0
    max_iterations = 10
    changed = True

    while changed and iteration < max_iterations:
        if fback.isCanceled():
            break

        has_unders = False
        for ea in bar_eas:
            if is_merge_candidate(ea, min_household, merge_candidate_ids) or (ea['hh_count'] == 0 and not ea.get('from_split', False) and not ea.get('is_special_ea', False)):
                has_unders = True
                break

        if not has_unders:
            break

        changed = False
        merged_indices = set()
        new_eas = []

        for idx in range(len(bar_eas)):
            if idx in merged_indices:
                continue

            ea = bar_eas[idx]

            if ea.get('from_split', False) or ea.get('is_special_ea', False):
                new_eas.append(ea)
                continue

            if ea['hh_count'] == 0:
                best_neighbor_idx = -1
                best_neighbor_score = float('inf')

                for j in range(len(bar_eas)):
                    if idx == j or j in merged_indices:
                        continue

                    neighbor = bar_eas[j]
                    if neighbor.get('from_split', False) or neighbor.get('is_special_ea', False):
                        continue
                    if is_delineation_candidate(neighbor, max_household, eadel_indi_col_idx, full_ea_by_id, delineation_candidate_ids):
                        continue
                    if neighbor.get('original_id') in delineation_candidate_ids:
                        continue
                    if ea['geom'].touches(neighbor['geom']) or ea['geom'].intersects(neighbor['geom']):
                        combined_hh = ea['hh_count'] + neighbor['hh_count']
                        score = combined_hh
                        if score < best_neighbor_score:
                            best_neighbor_score = score
                            best_neighbor_idx = j

                if best_neighbor_idx != -1:
                    neighbor = bar_eas[best_neighbor_idx]
                    merged_geom = ea['geom'].combine(neighbor['geom'])
                    merged_geom = merged_geom.buffer(0.0, 3)

                    ea_orig_hh = ea.get('original_hhcount', 0.0)
                    neighbor_orig_hh = neighbor.get('original_hhcount', 0.0)
                    ea_max_orig = ea.get('max_orig_hh', ea_orig_hh)
                    neighbor_max_orig = neighbor.get('max_orig_hh', neighbor_orig_hh)
                    ea_code = ea.get('new_ea_code') or ea.get('original_code')
                    neighbor_code = neighbor.get('new_ea_code') or neighbor.get('original_code')

                    if ea_max_orig >= neighbor_max_orig:
                        prevailing_ean = ea_code
                        max_orig_hh = ea_max_orig
                    else:
                        prevailing_ean = neighbor_code
                        max_orig_hh = neighbor_max_orig

                    merged_ea = {
                        'geom': merged_geom,
                        'buildings': ea.get('buildings', []) + neighbor.get('buildings', []),
                        'hh_count': ea['hh_count'] + neighbor['hh_count'],
                        'original_hhcount': ea.get('original_hhcount', ea.get('hh_count', 0.0)),
                        'original_bldgcount': ea.get('original_bldgcount', ea.get('bldg_count', 0)),
                        'bldg_count': ea.get('bldg_count', 0) + neighbor.get('bldg_count', 0),
                        'attributes': list(ea['attributes']),
                        'original_id': ea['original_id'],
                        'original_code': ea['original_code'],
                        'new_ea_code': prevailing_ean,
                        'max_orig_hh': max_orig_hh,
                        'is_new': False,
                        'split_by': ea.get('split_by', 'none'),
                        'from_merge': True,
                        'ea_type': 'MERGED',
                        'parent_barangay': bar_code
                    }

                    if best_neighbor_idx < idx:
                        try:
                            new_eas.remove(neighbor)
                        except ValueError:
                            pass

                    new_eas.append(merged_ea)
                    merged_indices.add(best_neighbor_idx)
                    merged_indices.add(idx)
                    changed = True
                    fback.pushInfo(f"[Barangay {bar_code}] Force-merged 0-household EA (code={ea['original_code']}) with adjacent neighbor (pop={neighbor['hh_count']}) -> Combined={merged_ea['hh_count']}")
                    continue

            if is_delineation_candidate(ea, max_household, eadel_indi_col_idx, full_ea_by_id, delineation_candidate_ids):
                new_eas.append(ea)
                continue

            if is_merge_candidate(ea, min_household, merge_candidate_ids):
                best_neighbor_idx = -1
                best_neighbor_score = (float('inf'), float('inf'))

                for j in range(len(bar_eas)):
                    if idx == j or j in merged_indices:
                        continue

                    neighbor = bar_eas[j]
                    if neighbor.get('from_split', False) or neighbor.get('is_special_ea', False):
                        continue
                    if is_delineation_candidate(neighbor, max_household, eadel_indi_col_idx, full_ea_by_id, delineation_candidate_ids):
                        continue
                    if neighbor.get('original_id') in delineation_candidate_ids:
                        continue

                    is_adjacent = (
                        ea['geom'].touches(neighbor['geom'])
                        or ea['geom'].intersects(neighbor['geom'])
                        or ea['geom'].buffer(0.001, 3).intersects(neighbor['geom'])
                    )
                    if is_adjacent:
                        combined_hh = ea['hh_count'] + neighbor['hh_count']
                        if combined_hh <= max_household:
                            score = (0 if combined_hh >= min_household else 1, float(neighbor.get('hh_count', 0.0)), neighbor['geom'].area())
                            if score < best_neighbor_score:
                                best_neighbor_score = score
                                best_neighbor_idx = j

                if best_neighbor_idx == -1:
                    new_eas.append(ea)
                    continue

                if best_neighbor_idx != -1:
                    neighbor = bar_eas[best_neighbor_idx]
                    merged_geom = ea['geom'].combine(neighbor['geom'])
                    merged_geom = merged_geom.buffer(0.0, 3)

                    ea_orig_hh = ea.get('original_hhcount', 0.0)
                    neighbor_orig_hh = neighbor.get('original_hhcount', 0.0)
                    ea_max_orig = ea.get('max_orig_hh', ea_orig_hh)
                    neighbor_max_orig = neighbor.get('max_orig_hh', neighbor_orig_hh)
                    ea_code = ea.get('new_ea_code') or ea.get('original_code')
                    neighbor_code = neighbor.get('new_ea_code') or neighbor.get('original_code')

                    if ea_max_orig >= neighbor_max_orig:
                        prevailing_ean = ea_code
                        max_orig_hh = ea_max_orig
                    else:
                        prevailing_ean = neighbor_code
                        max_orig_hh = neighbor_max_orig

                    merged_ea = {
                        'geom': merged_geom,
                        'buildings': ea.get('buildings', []) + neighbor.get('buildings', []),
                        'hh_count': ea['hh_count'] + neighbor['hh_count'],
                        'original_hhcount': ea.get('original_hhcount', ea.get('hh_count', 0.0)),
                        'original_bldgcount': ea.get('original_bldgcount', ea.get('bldg_count', 0)),
                        'bldg_count': ea.get('bldg_count', 0) + neighbor.get('bldg_count', 0),
                        'attributes': list(ea['attributes']),
                        'original_id': ea['original_id'],
                        'original_code': ea['original_code'],
                        'new_ea_code': prevailing_ean,
                        'max_orig_hh': max_orig_hh,
                        'is_new': False,
                        'split_by': ea.get('split_by', 'none'),
                        'from_merge': True,
                        'ea_type': 'MERGED',
                        'parent_barangay': bar_code
                    }

                    if best_neighbor_idx < idx:
                        try:
                            new_eas.remove(neighbor)
                        except ValueError:
                            pass

                    new_eas.append(merged_ea)
                    merged_indices.add(best_neighbor_idx)
                    merged_indices.add(idx)
                    changed = True
                    fback.pushInfo(f"[Barangay {bar_code}] Merged small EA (pop={ea['hh_count']}) with adjacent neighbor (pop={neighbor['hh_count']}) -> Combined={merged_ea['hh_count']}")
                else:
                    new_eas.append(ea)
            else:
                new_eas.append(ea)

        bar_eas = new_eas
        if not changed:
            break
        iteration += 1

    remaining_unders = [ea for ea in bar_eas if is_merge_candidate(ea, min_household, merge_candidate_ids)]
    for ea in remaining_unders:
        unique_pt_count = len(set((b['point'].x(), b['point'].y()) for b in ea.get('buildings', [])))
        fback.pushInfo(
            f"[Barangay {bar_code}] UNRESOLVED UNDER-THRESHOLD: EA (code={ea['original_code']}, "
            f"hh_count={ea['hh_count']}, bldg_count={ea.get('bldg_count',0)}, "
            f"unique_pts={unique_pt_count}) — no valid merge neighbour found after {iteration} iteration(s)."
        )

    return bar_eas


def run_phase_6(alg, parameters, context, feedback, multi_feedback, p1, p2, p5):
    """
    Executes Phase 6 (Iterative Per-Barangay Merging & Partner Allocation).

    Returns dictionary containing:
    - merged_eas: List[dict] of EAs after iterative merging
    """
    eadel_indi_col_idx = p1["eadel_indi_col_idx"]
    full_ea_by_id = p2["full_ea_by_id"]
    min_household = p1["min_household"]
    max_household = p1["max_household"]
    num_cores = p1.get("num_cores", QThread.idealThreadCount())

    delineation_candidate_ids = p2["delineation_candidate_ids"]
    merge_candidate_ids = p2["merge_candidate_ids"]

    split_eas = p5["split_eas"]

    barangay_split_groups = {}
    for ea in split_eas:
        bar = ea['parent_barangay']
        barangay_split_groups.setdefault(bar, []).append(ea)

    sorted_split_bar_keys = sorted(
        barangay_split_groups.keys(),
        key=lambda k: str(k) if k is not None else ""
    )

    allow_candidate_merge = p1.get("allow_candidate_merge", True)

    merge_bar_keys = [
        bar_code for bar_code in sorted_split_bar_keys
        if any(is_merge_candidate(ea, min_household, merge_candidate_ids) or ea['hh_count'] == 0 for ea in barangay_split_groups[bar_code])
    ]

    multi_feedback.setCurrentStep(5)
    multi_feedback.setProgressText(
        f"{_PHASE_LABELS[5]} [0/{len(merge_bar_keys)} barangay(s)]..."
    )

    def process_barangay_merge_wrapper(bar_code, bar_eas, parent_feedback):
        result = process_barangay_merge(
            bar_code,
            bar_eas,
            parent_feedback,
            min_household=min_household,
            max_household=max_household,
            eadel_indi_col_idx=eadel_indi_col_idx,
            full_ea_by_id=full_ea_by_id,
            delineation_candidate_ids=delineation_candidate_ids,
            merge_candidate_ids=merge_candidate_ids,
            allow_candidate_merge=allow_candidate_merge,
        )
        return result, []

    final_merged_eas = []
    if merge_bar_keys:
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_cores) as executor:
            futures = {
                executor.submit(process_barangay_merge_wrapper, bar_code, barangay_split_groups[bar_code], feedback): bar_code 
                for bar_code in merge_bar_keys
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
                        f"{_PHASE_LABELS[5]} [{_n_done}/{len(futures)} barangay(s) done]..."
                    )
                    _last_n_done = _n_done

            ordered_futures = {bar_code: future for future, bar_code in futures.items()}
            for bar_code in sorted_split_bar_keys:
                if bar_code in ordered_futures:
                    future = ordered_futures[bar_code]
                    if future.cancelled():
                        final_merged_eas.extend(barangay_split_groups[bar_code])
                        continue
                    try:
                        result, logs = future.result()
                        final_merged_eas.extend(result)
                        for log_type, msg in logs:
                            if log_type == 'info':
                                feedback.pushInfo(msg)
                            elif log_type == 'warning':
                                feedback.pushWarning(msg)
                    except Exception as e:
                        feedback.reportError(f"Error merging Barangay {bar_code}: {str(e)}")
                else:
                    final_merged_eas.extend(barangay_split_groups[bar_code])
    else:
        for bar_code in sorted_split_bar_keys:
            final_merged_eas.extend(barangay_split_groups[bar_code])

    multi_feedback.setProgress(100)

    if multi_feedback.isCanceled():
        raise QgsProcessingException("Algorithm cancelled by user.")

    return {
        "merged_eas": final_merged_eas,
        "proposed_lines": p5.get("proposed_lines", []),
    }
