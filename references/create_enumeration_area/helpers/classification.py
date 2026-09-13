from typing import Dict, Any, Set, Optional
from qgis.core import QgsFeature

def get_classification_count(ea_item: Dict[str, Any]) -> float:
    """Return household count for classification decisions."""
    return ea_item.get('hh_count', 0.0)


def is_parent_delineation_candidate(
    ea_item: Dict[str, Any],
    eadel_indi_col_idx: int,
    full_ea_by_id: Dict[int, QgsFeature]
) -> bool:
    """Check if EA item is explicitly designated for delineation via attribute field."""
    orig_id = ea_item.get('original_id')
    if orig_id is not None and eadel_indi_col_idx != -1 and orig_id in full_ea_by_id:
        val = full_ea_by_id[orig_id].attribute(eadel_indi_col_idx)
        return val is not None and str(val).strip().lower() in ("for delineation", "for_delineation")
    return False


def is_delineation_candidate(
    ea_item: Dict[str, Any],
    max_household: float,
    eadel_indi_col_idx: int = -1,
    full_ea_by_id: Optional[Dict[int, QgsFeature]] = None,
    delineation_candidate_ids: Optional[Set[int]] = None
) -> bool:
    """Check if EA item is a candidate for delineation."""
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


def is_merge_candidate(
    ea_item: Dict[str, Any],
    min_household: float,
    merge_candidate_ids: Set[int]
) -> bool:
    """Check if EA item is a candidate for merging."""
    if ea_item.get('from_split', False) or ea_item.get('has_proposed_split', False):
        return False
    if ea_item.get('is_special_ea', False):
        return False
    if ea_item.get('from_merge', False):
        return ea_item.get('hh_count', 0.0) <= min_household
    orig_id = ea_item.get('original_id')
    return (orig_id in merge_candidate_ids) or (ea_item.get('hh_count', 0.0) <= min_household)
