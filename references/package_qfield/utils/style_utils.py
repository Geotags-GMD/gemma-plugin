# -*- coding: utf-8 -*-
"""
Utility module for managing QML styles embedded in the plugin.

The plugin ships with a 'qml styles' folder containing .qml files.
This module provides functions to:
- List available QML styles
- Auto-detect the best matching QML style for a given layer name
- Apply a QML style to a QGIS layer
"""

import os
import re
from qgis.core import QgsProject


def get_qml_styles_dir():
    """Return the absolute path to the 'qml styles' folder in the plugin directory.

    Does NOT create it — it is expected to ship with the plugin.
    """
    # Navigate from references/package_qfield/utils/ up to the plugin root (gmd-pipeline-v2/)
    plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(plugin_dir, "qml styles")


def _natural_sort_key(filename):
    """Sort key for natural sorting so '10.' comes after '8.', not before '2.'."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', filename)]


def get_available_qml_files():
    """Return a naturally sorted list of QML filenames (with extension) found in the
    'qml styles' folder.  Returns an empty list if the folder doesn't exist.
    """
    qml_dir = get_qml_styles_dir()
    if not os.path.isdir(qml_dir):
        return []
    return sorted(
        (f for f in os.listdir(qml_dir) if f.lower().endswith(".qml")),
        key=_natural_sort_key
    )


def get_available_qml_display_names():
    """Return a sorted list of QML display names (filename without .qml extension).

    Example: '1. Base Layer Barangay'
    """
    return [os.path.splitext(f)[0] for f in get_available_qml_files()]


# ---------------------------------------------------------------------------
# Abbreviation / keyword map used for auto-detection.
# Keys = lowercase keywords extracted from QML display names.
# Values = list of lowercase layer-name suffixes or substrings that should
#           match this QML style.
# ---------------------------------------------------------------------------
_KEYWORD_ALIAS_MAP = {
    "barangay": ["bgy", "brgy", "barangay"],
    "ea": ["_ea", "ea2024"],
    "building points": ["bldgpts", "bldg_points", "bldg_point", "bldg"],
    "landmark": ["landmark", "landmarks"],
    "road": ["road"],
    "river": ["river"],
    "block": ["block"],
    "railroad": ["railroad", "rail"],
    "delineated ea line": ["delineated_ea_line", "delineated_line"],
    "delineated ea polygon": ["delineated_ea", "delineated_ea2026", "delineated_polygon"],
    "merged ea polygon": ["merged_ea", "merged_ea2026", "merged_polygon"],
    "ref_mbi_cases": ["ref_mbi_cases", "mbi_cases", "ref_mbi"],
    "mbi cases": ["ref_mbi_cases", "mbi_cases", "ref_mbi"],
    "ref_province_lgu": ["_lgu", "ref_province_lgu", "province_lgu", "lgu"],
    "ref_province_psa": ["_psa", "ref_province_psa", "province_psa", "psa"],
}


def _extract_qml_keyword(display_name):
    """Extract the meaningful keyword from a QML display name.

    '1. Base Layer Barangay' → 'barangay'
    '4. Base Layer EA'       → 'ea'
    """
    name = display_name.strip()
    # Strip leading number + dot  (e.g. '1. ')
    name = re.sub(r"^\d+\.\s*", "", name)
    # Strip common prefixes
    name = re.sub(r"^Base\s+Layer\s*", "", name, flags=re.IGNORECASE)
    return name.strip().lower()


def auto_detect_qml_for_layer(layer_name, available_display_names=None):
    """Return the best-matching QML display name for *layer_name*, or '' if
    no match is found.

    Matching priority:
      1. Keyword alias map (covers abbreviations like bgy → Barangay)
      2. Substring / suffix match against the extracted keyword
    """
    if available_display_names is None:
        available_display_names = get_available_qml_display_names()

    layer_lower = layer_name.lower()

    # Build keyword → display_name lookup
    keyword_to_display = {}
    for dname in available_display_names:
        kw = _extract_qml_keyword(dname)
        keyword_to_display[kw] = dname

    # --- Pass 1: alias map --------------------------------------------------
    for kw, aliases in _KEYWORD_ALIAS_MAP.items():
        if kw not in keyword_to_display:
            continue
        for alias in aliases:
            # Check if the layer name ends with the alias (after _ or at start)
            if layer_lower.endswith(alias) or layer_lower.endswith("_" + alias):
                return keyword_to_display[kw]

    # --- Pass 2: direct substring match on the extracted keyword -------------
    for kw, dname in keyword_to_display.items():
        if kw and kw in layer_lower:
            return dname

    return ""


def get_qml_file_path(display_name):
    """Return the full file path for a QML given its display name."""
    if not display_name or display_name == "(None)":
        return ""
    qml_dir = get_qml_styles_dir()
    name = display_name if display_name.lower().endswith(".qml") else display_name + ".qml"
    path = os.path.join(qml_dir, name)
    if os.path.isfile(path):
        return path
    for root_dir, _, files in os.walk(qml_dir):
        if name in files:
            return os.path.join(root_dir, name)
    return path


def apply_qml_to_layer(layer, display_name):
    """Apply the QML style identified by *display_name* to *layer*.

    Returns True on success, False on failure.
    """
    if not layer or not display_name or display_name == "(None)":
        return False

    qml_path = get_qml_file_path(display_name)
    if not os.path.isfile(qml_path):
        print(f"[QML ERROR] File does not exist: {qml_path}")
        return False

    normalized_path = qml_path.replace("\\", "/")
    print(f"[QML ATTEMPT] Layer='{layer.name()}' QML='{display_name}' path='{normalized_path}'")

    from qgis.core import QgsMapLayer
    # Specify categories: Symbology + Labeling (prevents overriding layer flags / readOnly / scale limits)
    categories = QgsMapLayer.Symbology | QgsMapLayer.Labeling

    success = False
    err_log = ""

    # Method 1: PyQGIS importNamedStyle with Symbology + Labeling categories
    try:
        from qgis.PyQt.QtXml import QDomDocument
        doc = QDomDocument()
        with open(qml_path, "r", encoding="utf-8") as f:
            xml_content = f.read()
        if doc.setContent(xml_content):
            res = layer.importNamedStyle(doc, categories)
            if isinstance(res, tuple):
                err_log = res[0]
                success = bool(res[1])
            elif isinstance(res, bool):
                success = res
            print(f"[QML IMPORT RESULT] Layer='{layer.name()}' ok={success} err_msg='{err_log}'")
    except Exception as e:
        print(f"[QML IMPORT EXCEPTION] {e}")

    # Method 2: Standard loadNamedStyle fallback with Symbology + Labeling categories
    if not success:
        res = layer.loadNamedStyle(normalized_path, categories)
        if isinstance(res, tuple):
            err_log = res[0]
            success = bool(res[1])
        elif isinstance(res, bool):
            success = res
        print(f"[QML LOAD RESULT] Layer='{layer.name()}' ok={success} msg='{err_log}'")

    # Ensure layer readOnly flag is disabled so layer stays visible/editable
    if hasattr(layer, "setReadOnly"):
        layer.setReadOnly(False)

    if success or layer.isValid():
        layer.emitStyleChanged()
        layer.triggerRepaint()

        try:
            from qgis.core import QgsProject
            from qgis.utils import iface
            
            node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
            if iface:
                if node and iface.layerTreeView() and iface.layerTreeView().layerTreeModel():
                    iface.layerTreeView().layerTreeModel().refreshLayerLegend(node)
                elif iface.layerTreeView():
                    iface.layerTreeView().refreshLayerSymbology(layer.id())
                if iface.mapCanvas():
                    iface.mapCanvas().refresh()
        except Exception as e:
            print(f"[QML ERROR] Refresh failed: {e}")

    return success


def apply_embedded_qml_styles(project=None):
    """Auto-detect and apply QML styles to ALL layers in the current project.

    Returns a dict  { layer_name: applied_qml_display_name_or_empty }.
    """
    if project is None:
        project = QgsProject.instance()

    available = get_available_qml_display_names()
    results = {}

    for layer in project.mapLayers().values():
        lname = layer.name()
        match = auto_detect_qml_for_layer(lname, available)
        if match:
            apply_qml_to_layer(layer, match)
        results[lname] = match

    return results

