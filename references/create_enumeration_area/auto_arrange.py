# -*- coding: utf-8 -*-
"""
Auto Arrange Module for GEMMA QGIS Plugin
-----------------------------------------
Provides automated layer tree restructuring, re-ordering, group creation,
and QML symbology/labeling application across QGIS project layers,
extracting PSGC code and City/Municipality name directly from layer feature
attributes (geocode and city_mun fields) to form group names
(<PSGC>_<City_Mun>_MBI and <PSGC>_<City_Mun>_baselayers), renaming gap and
overlap layers to match PSGC pattern (<PSGC>_gaps and <PSGC>_overlaps),
applying single-symbol fill styling to gaps (Orange) and overlaps (Red)
without Categorized renderer dependencies, and applying official QML base layer styles
(1. Base Layer Building Points, 2. Base Layer Landmark, 3. Base Layer Block,
4. Base Layer EA, 5. Base Layer Barangay, 6. Base Layer Road, 7. Base Layer River,
8. Base Layer Railroad).
"""

import os
import re
from collections import Counter
from qgis.core import (
    QgsProject, QgsMapLayer, QgsMessageLog, Qgis, QgsVectorLayer,
    QgsLayerTreeGroup, QgsLayerTreeLayer, QgsSingleSymbolRenderer, QgsFillSymbol
)

# Official QML Style Mapping for Base Layers
QML_BASE_LAYER_MAP = [
    (["extracted_bldgpts", "extracted_bldg_pts", "extracted_building"], "extracted_bldgpts.qml"),
    (["bldg_point", "bldgpts", "bldg_pts", "building_point"], "1. Base Layer Building Points.qml"),
    (["sf_landmark", "old_landmark", "landmark"], "2. Base Layer Landmark.qml"),
    (["block"], "3. Base Layer Block.qml"),
    (["_ea2024", "_ea2023", "_ea2025", "_ea2026", "_ea", "enumeration_area"], "4. Base Layer EA.qml"),
    (["_bgy", "_brgy", "barangay"], "5. Base Layer Barangay.qml"),
    (["railroad", "rail"], "8. Base Layer Railroad.qml"),
    (["road", "highway"], "6. Base Layer Road.qml"),
    (["river", "stream", "creek"], "7. Base Layer River.qml"),
]


def find_qml_style_for_layer(layer_name):
    """
    Returns the exact matching QML filename for a given layer name based on
    official base layer styling rules.
    """
    lname = layer_name.lower()
    for patterns, qml_file in QML_BASE_LAYER_MAP:
        if any(pat in lname for pat in patterns):
            return qml_file
    return None


def extract_project_prefix(layers):
    """
    Extracts the common layer prefix (e.g. '01716_City of Iriga_') from:
    1. Feature attributes (geocode[:5] and city_mun/municipality field in Barangay or EA layer).
    2. Fallback: Layer names in the project.
    """
    psgc_prefix = ""
    city_mun_name = ""

    # Priority target layers to check attributes: Barangay (*_bgy) or EA (*_ea)
    target_layers = []
    for lyr in layers:
        if isinstance(lyr, QgsVectorLayer):
            lname = lyr.name().lower()
            if any(k in lname for k in ["bgy", "brgy", "barangay", "ea"]):
                target_layers.append(lyr)

    # 1. Attribute inspection pass
    for lyr in target_layers:
        fields_map = {f.name().lower(): f.name() for f in lyr.fields()}

        # Identify geocode field
        geocode_field = None
        for g_candidate in ["geocode", "psgc", "brgy_code", "bgy_code"]:
            if g_candidate in fields_map:
                geocode_field = fields_map[g_candidate]
                break

        # Identify city/municipality field
        city_field = None
        for c_candidate in ["city_mun", "citymun", "city", "municipality", "mun_name", "city_name"]:
            if c_candidate in fields_map:
                city_field = fields_map[c_candidate]
                break

        if geocode_field or city_field:
            try:
                for feat in lyr.getFeatures():
                    if not psgc_prefix and geocode_field:
                        val = str(feat[geocode_field] or "").strip()
                        if len(val) >= 5 and val[:5].isdigit():
                            psgc_prefix = val[:5]
                    if not city_mun_name and city_field:
                        val = str(feat[city_field] or "").strip()
                        if val and val.lower() != "null":
                            city_mun_name = val
                    if psgc_prefix and city_mun_name:
                        break
            except Exception:
                pass

        if psgc_prefix and city_mun_name:
            break

    if psgc_prefix and city_mun_name:
        return f"{psgc_prefix}_{city_mun_name}_"
    elif psgc_prefix:
        return f"{psgc_prefix}_"

    # 2. Fallback: Layer name regex / keyword scanning
    keywords = [
        "bgy", "brgy", "barangay", "ea", "ea2024", "bldg_point", "bldgpts",
        "sf_landmark", "old_landmark", "landmark", "road", "river", "gaps", "overlaps"
    ]
    prefixes = []
    for lyr in layers:
        lname = lyr.name()
        lname_lower = lname.lower()
        for kw in keywords:
            if kw in lname_lower:
                idx = lname_lower.find(kw)
                if idx > 0:
                    prefix = lname[:idx]
                    prefixes.append(prefix)
                break

    if prefixes:
        most_common = Counter(prefixes).most_common(1)[0][0]
        return most_common
    return ""


def get_layer_group_and_rank(layer_name, layer_type, mbi_group_name, baselayers_group_name):
    """
    Determines target group name and internal rank score (lower = displayed higher)
    for a layer matching GEMMA standard structure.

    Returns:
        (group_name, rank_score)
    """
    lname = layer_name.lower()

    # 1. MBI Quality Check Group (Gaps and Overlaps)
    if "gaps" in lname:
        return (mbi_group_name, 10)
    elif "overlaps" in lname:
        return (mbi_group_name, 20)

    # 2. Baselayers Group
    if any(k in lname for k in ["bldg_point", "bldgpts", "bldg_pts", "building_point"]):
        return (baselayers_group_name, 10)
    elif "old_landmark" in lname:
        return (baselayers_group_name, 20)
    elif "sf_landmark" in lname or "landmark" in lname:
        return (baselayers_group_name, 30)
    elif "river" in lname:
        return (baselayers_group_name, 40)
    elif "road" in lname:
        return (baselayers_group_name, 50)
    elif any(k in lname for k in ["_ea", "ea2024", "enumeration_area"]):
        return (baselayers_group_name, 60)
    elif any(k in lname for k in ["_bgy", "_brgy", "barangay"]):
        return (baselayers_group_name, 70)

    # Fallback vector layers
    if layer_type == QgsMapLayer.VectorLayer:
        return (baselayers_group_name, 80)

    # Rasters / Basemaps (Outside group at bottom)
    return ("", 100)


def auto_arrange_layers(iface=None, project=None):
    """
    Restructure, re-order, rename gaps/overlaps, and apply single-symbol / QML styles
    to all layers in the active project.
    Groups layers into <Prefix>_MBI and <Prefix>_baselayers in exact order.

    Args:
        iface: Optional QGIS Interface instance.
        project: Optional QgsProject instance (defaults to QgsProject.instance()).

    Returns:
        dict with status summary: {'total': int, 'styled': int, 'reordered': int}
    """
    project = project or QgsProject.instance()
    root = project.layerTreeRoot()
    layers = list(project.mapLayers().values())

    if not layers:
        return {"total": 0, "styled": 0, "reordered": 0}

    prefix = extract_project_prefix(layers)

    # Derive short PSGC code prefix (e.g. '01716_' from '01716_City of Iriga_' or '01716_')
    short_prefix = prefix
    if "_" in prefix:
        first_part = prefix.split("_")[0]
        if first_part.isdigit() and len(first_part) >= 4:
            short_prefix = f"{first_part}_"

    target_gaps_name = f"{short_prefix}gaps" if short_prefix else "gaps"
    target_overlaps_name = f"{short_prefix}overlaps" if short_prefix else "overlaps"

    # Step 1: Rename Gap and Overlap layers to match PSGC pattern
    for layer in layers:
        lname = layer.name().lower()
        if "gaps" in lname or ("gap" in lname and "overlaps" not in lname):
            if layer.name() != target_gaps_name:
                layer.setName(target_gaps_name)
        elif "overlaps" in lname or "overlap" in lname:
            if layer.name() != target_overlaps_name:
                layer.setName(target_overlaps_name)

    # Import QML style utilities
    apply_qml_to_layer_fn = None
    try:
        from ..package_qfield.utils.style_utils import apply_qml_to_layer
        apply_qml_to_layer_fn = apply_qml_to_layer
    except Exception as e:
        QgsMessageLog.logMessage(f"Style utils import notice: {e}", "GEMMA", Qgis.Info)

    styled_count = 0

    # Step 2: Apply styles to vector layers
    for layer in layers:
        if not isinstance(layer, QgsVectorLayer):
            continue

        layer_name = layer.name()
        lname_lower = layer_name.lower()

        # Handle Gap and Overlap single symbol rendering directly
        if "gaps" in lname_lower:
            try:
                gap_sym = QgsFillSymbol.createSimple({
                    'color': '249,115,22,165',
                    'outline_style': 'no',
                    'style': 'solid'
                })
                layer.setRenderer(QgsSingleSymbolRenderer(gap_sym))
                styled_count += 1
                layer.triggerRepaint()
                continue
            except Exception as e:
                QgsMessageLog.logMessage(f"Error styling gap layer: {e}", "GEMMA", Qgis.Warning)

        elif "overlaps" in lname_lower:
            try:
                overlap_sym = QgsFillSymbol.createSimple({
                    'color': '239,68,68,165',
                    'outline_style': 'no',
                    'style': 'solid'
                })
                layer.setRenderer(QgsSingleSymbolRenderer(overlap_sym))
                styled_count += 1
                layer.triggerRepaint()
                continue
            except Exception as e:
                QgsMessageLog.logMessage(f"Error styling overlap layer: {e}", "GEMMA", Qgis.Warning)

        # Standard base layer QML style application
        qml_filename = find_qml_style_for_layer(layer_name)

        if qml_filename and apply_qml_to_layer_fn:
            try:
                success = apply_qml_to_layer_fn(layer, qml_filename)
                if success:
                    styled_count += 1
                    layer.triggerRepaint()
            except Exception as e:
                QgsMessageLog.logMessage(f"Error applying style {qml_filename} to {layer_name}: {e}", "GEMMA", Qgis.Warning)

    # Step 3: Determine dynamic group names matching project prefix
    mbi_group_name = None
    baselayers_group_name = None

    for child in root.children():
        if isinstance(child, QgsLayerTreeGroup):
            gname = child.name()
            if gname.lower().endswith("mbi") or "_mbi" in gname.lower():
                mbi_group_name = gname
            elif gname.lower().endswith("baselayers") or "_baselayers" in gname.lower():
                baselayers_group_name = gname

    if not mbi_group_name:
        mbi_group_name = f"{prefix}MBI" if prefix else "MBI"
    if not baselayers_group_name:
        baselayers_group_name = f"{prefix}baselayers" if prefix else "baselayers"

    # Ensure top-level groups exist in root in correct top-to-bottom order:
    # 1. MBI Group
    # 2. Baselayers Group
    mbi_group_node = root.findGroup(mbi_group_name)
    if not mbi_group_node:
        mbi_group_node = root.insertGroup(0, mbi_group_name)

    baselayers_group_node = root.findGroup(baselayers_group_name)
    if not baselayers_group_node:
        baselayers_group_node = root.insertGroup(1, baselayers_group_name)

    # Ensure group top-level index order
    children = list(root.children())
    if mbi_group_node in children and children.index(mbi_group_node) != 0:
        clone_mbi = mbi_group_node.clone()
        root.insertChildNode(0, clone_mbi)
        root.removeChildNode(mbi_group_node)
        mbi_group_node = clone_mbi

    children = list(root.children())
    if baselayers_group_node in children and children.index(baselayers_group_node) != 1:
        clone_base = baselayers_group_node.clone()
        root.insertChildNode(1, clone_base)
        root.removeChildNode(baselayers_group_node)
        baselayers_group_node = clone_base

    # Step 4: Categorize and rank each layer
    mbi_items = []
    baselayer_items = []
    root_items = []

    for layer in layers:
        target_grp, rank = get_layer_group_and_rank(layer.name(), layer.type(), mbi_group_name, baselayers_group_name)
        if target_grp == mbi_group_name:
            mbi_items.append((rank, layer))
        elif target_grp == baselayers_group_name:
            baselayer_items.append((rank, layer))
        else:
            root_items.append((rank, layer))

    mbi_items.sort(key=lambda x: x[0])
    baselayer_items.sort(key=lambda x: x[0])
    root_items.sort(key=lambda x: x[0])

    reordered_count = 0

    # Helper function to place layer nodes at exact index under target group
    def sync_nodes(item_list, target_parent):
        nonlocal reordered_count
        for idx, (rank, lyr) in enumerate(item_list):
            node = root.findLayer(lyr.id())
            if not node:
                continue

            curr_children = list(target_parent.children())
            if node.parent() != target_parent or node not in curr_children or curr_children.index(node) != idx:
                clone = node.clone()
                target_parent.insertChildNode(idx, clone)
                if node.parent():
                    node.parent().removeChildNode(node)
                reordered_count += 1

    sync_nodes(mbi_items, mbi_group_node)
    sync_nodes(baselayer_items, baselayers_group_node)
    sync_nodes(root_items, root)

    # Refresh canvas if interface provided
    if iface and hasattr(iface, 'mapCanvas'):
        try:
            iface.mapCanvas().refresh()
        except Exception:
            pass

    log_msg = f"Auto Arrange complete: {len(layers)} layers organized into '{mbi_group_name}' and '{baselayers_group_name}', {styled_count} styled."
    QgsMessageLog.logMessage(log_msg, "GEMMA", Qgis.Success)

    return {
        "total": len(layers),
        "styled": styled_count,
        "reordered": reordered_count,
        "mbi_group": mbi_group_name,
        "baselayers_group": baselayers_group_name
    }
