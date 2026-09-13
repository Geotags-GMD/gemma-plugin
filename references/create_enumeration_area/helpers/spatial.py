from typing import Optional, Dict, Any
from qgis.core import QgsFeature, QgsGeometry, QgsSpatialIndex, NULL
from PyQt5.QtCore import QVariant


def normalize_to_8_digits(val: Any) -> str:
    """Standardize a barangay / geocode identifier to an 8-digit numeric string."""
    if val is None or val == NULL or str(val).strip() in ('', 'NULL', 'None'):
        return ""
    if isinstance(val, QVariant) and val.isNull():
        return ""
    val_str = str(val).strip()
    if val_str.endswith(".0"):
        val_str = val_str[:-2]
    digits = "".join([c for c in val_str if c.isdigit()])
    if len(digits) >= 8:
        return digits[:8]
    elif len(digits) > 0:
        return digits.zfill(8)
    return val_str[:8] if len(val_str) >= 8 else val_str


def get_parent_barangay(
    ea_geom: QgsGeometry,
    barangay_index: QgsSpatialIndex,
    barangay_by_id: Dict[int, QgsFeature]
) -> Optional[QgsFeature]:
    """Find parent barangay feature by maximum area overlap."""
    candidates = barangay_index.intersects(ea_geom.boundingBox())
    max_overlap = -1.0
    parent_feat = None
    for cid in candidates:
        bar = barangay_by_id.get(cid)
        if not bar:
            continue
        bar_geom = bar.geometry()
        if bar_geom.intersects(ea_geom):
            overlap_area = bar_geom.intersection(ea_geom).area()
            if overlap_area > max_overlap:
                max_overlap = overlap_area
                parent_feat = bar
    return parent_feat


def resolve_ea_parent_barangay(
    ea_feat: QgsFeature,
    dc_geo_idx: int,
    barangay_id_field: str,
    barangay_index: QgsSpatialIndex,
    barangay_by_id: Dict[int, QgsFeature]
) -> str:
    """Resolve barangay code for an EA feature standardized to 8 digits via spatial overlay (primary) or field attribute fallback."""
    # 1. Primary: Spatial overlay with Barangay Layer
    parent_feat = get_parent_barangay(ea_feat.geometry(), barangay_index, barangay_by_id)
    if parent_feat:
        val = None
        for f in parent_feat.fields():
            if f.name().lower() == "geocode":
                val = parent_feat.attribute(f.name())
                break
        if val is None and parent_feat.fields().indexOf(barangay_id_field) != -1:
            val = parent_feat.attribute(barangay_id_field)
        res = normalize_to_8_digits(val)
        if res:
            return res

    # 2. Fallback: Attribute from EA layer
    if dc_geo_idx != -1:
        val = ea_feat.attribute(dc_geo_idx)
        res = normalize_to_8_digits(val)
        if res:
            return res
    for f in ea_feat.fields():
        if f.name().lower() == "geocode":
            res = normalize_to_8_digits(ea_feat.attribute(f.name()))
            if res:
                return res
    return "Unknown"
