# -----------------------------------------------------------------------------
# Package Layers by City/Mun
#
# Groups features from four reference layers into one GeoPackage (.gpkg) per
# city/mun, each placed in its own folder, named:
#
#       folder:  pppmm_CITYMUN/
#       gpkg  :  pppmm_CITYMUN/pppmm_CITYMUN.gpkg
#
#   ppp = 3-digit province code
#   mm  = 2-digit city/mun code
#   (together, ppp+mm = the first 5 characters of the geocode field)
#
# Available from the QGIS menu bar under Gemma > Others > Package Layers by
# City/Mun, and from the Processing Toolbox under 1Map > Package Layers by
# City/Mun. Pick the four reference layers, confirm the field names, choose
# an output folder, and click Run.
# -----------------------------------------------------------------------------

import os

import qgis.utils

from qgis.core import (
    QgsProject, QgsVectorFileWriter, QgsMapLayerProxyModel, QgsMapLayer,
    QgsVectorLayer, QgsLayerTreeGroup, QgsLayerTreeLayer,
    QgsProcessingAlgorithm, QgsProcessingOutputString,
)
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt, QTimer, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPushButton, QFileDialog, QPlainTextEdit, QComboBox,
    QMessageBox, QWidget, QProgressBar, QCheckBox, QSplitter, QScrollArea,
)


# -----------------------------------------------------------------------------
# Session-wide auto-organize: whenever a layer from one of our packaged
# GeoPackages gets added to the project — whether by this dialog's own
# "Load packaged layers" option, or by the user manually browsing to the
# .gpkg through Add Vector Layer / the Browser panel — file it into its
# city/mun group and strip the "<file> — <table>" name QGIS's Add Layer
# dialog applies by default, so both paths end up looking identical.
# -----------------------------------------------------------------------------

TOP_GROUP_NAME = "Packaged Layers"


def _get_packaged_top_group():
    root = QgsProject.instance().layerTreeRoot()
    group = root.findGroup(TOP_GROUP_NAME)
    if group is None:
        group = root.insertGroup(0, TOP_GROUP_NAME)
    # Explicit: a run must never leave the user staring at a collapsed tree.
    group.setExpanded(True)
    return group


def _collect_group_layer_ids(group):
    """Recursively collect the ids of every layer nested under this group."""
    ids = []
    for child in group.children():
        if isinstance(child, QgsLayerTreeLayer):
            lyr = child.layer()
            if lyr is not None:
                ids.append(lyr.id())
        elif isinstance(child, QgsLayerTreeGroup):
            ids.extend(_collect_group_layer_ids(child))
    return ids


def _get_citymun_group(group_id, replace=False):
    top = _get_packaged_top_group()
    existing = top.findGroup(group_id)
    if existing is not None:
        if replace:
            # Fully unregister the old group's layers (not just detach
            # their tree nodes) so a re-run doesn't leave orphaned layers
            # sitting invisibly in the project.
            layer_ids = _collect_group_layer_ids(existing)
            if layer_ids:
                QgsProject.instance().removeMapLayers(layer_ids)
            still_there = top.findGroup(group_id)
            if still_there is not None:
                top.removeChildNode(still_there)
        else:
            existing.setExpanded(True)
            return existing
    group = top.addGroup(group_id)
    group.setExpanded(True)
    return group


def _clean_layer_display_name(layer, fallback):
    name = layer.name()
    if " — " in name:
        name = name.rpartition(" — ")[2] or fallback
    if not name:
        name = fallback
    if layer.name() != name:
        layer.setName(name)


def _remove_duplicate_layers(group, new_layer):
    """Drop any other layer already in this group that points at exactly the
    same GeoPackage table (e.g. the same file added a second time), so the
    newest one replaces it instead of sitting next to it as a duplicate."""
    new_source = new_layer.source()
    doomed = []
    # Collect first, remove second — removing a layer also destroys its tree
    # node, so mutating while walking children() is not safe.
    for child in group.children():
        if isinstance(child, QgsLayerTreeLayer):
            lyr = child.layer()
            if lyr is not None and lyr.id() != new_layer.id() and lyr.source() == new_source:
                doomed.append(lyr.id())
    if doomed:
        QgsProject.instance().removeMapLayers(doomed)


def _place_layer_in_group(layer, group_id, table_name):
    project = QgsProject.instance()
    root = project.layerTreeRoot()

    _clean_layer_display_name(layer, table_name)
    group = _get_citymun_group(group_id)
    _remove_duplicate_layers(group, layer)

    # Collapse every tree node referencing this layer down to exactly one
    # node inside the target group. A manual add can leave more than one
    # behind, because QGIS inserts its own node for the layer as well.
    #
    # Order matters: the node is added to the group FIRST and the old nodes
    # are removed after. QGIS's layer-tree bridge unregisters a layer from
    # the project the moment its last remaining tree node goes away, so the
    # layer must never be left without one, even briefly.
    stale_nodes = [n for n in root.findLayers() if n.layerId() == layer.id()]

    group.addLayer(layer)

    for node in stale_nodes:
        parent = node.parent()
        if parent is not None:
            parent.removeChildNode(node)


def _cleanup_duplicate_packaged_layers():
    """Remove duplicate layers sitting in the Packaged Layers groups, keeping
    the first of each source. Returns the number of layers removed."""
    project = QgsProject.instance()
    top = project.layerTreeRoot().findGroup(TOP_GROUP_NAME)
    if top is None:
        return 0

    removed = 0
    for citymun_group in [c for c in top.children() if isinstance(c, QgsLayerTreeGroup)]:
        seen_sources = set()
        doomed = []
        for child in citymun_group.children():
            if not isinstance(child, QgsLayerTreeLayer):
                continue
            lyr = child.layer()
            if lyr is None:
                continue
            source = lyr.source()
            if source in seen_sources:
                doomed.append(lyr.id())
            else:
                seen_sources.add(source)
        if doomed:
            project.removeMapLayers(doomed)
            removed += len(doomed)
    return removed


def _group_id_and_table_from_source(layer):
    """Return (group_id, table_name) if this layer's source looks like one
    of our packaged GeoPackage tables, else (None, None)."""
    try:
        source = layer.source()
    except Exception:
        return None, None
    if "|layername=" not in source:
        return None, None
    gpkg_path, _, remainder = source.partition("|layername=")
    table_name = remainder.split("|")[0]
    if not gpkg_path.lower().endswith(".gpkg"):
        return None, None
    group_id = os.path.splitext(os.path.basename(gpkg_path))[0]
    return group_id, table_name


def _organize_layer_ids(layer_ids):
    project = QgsProject.instance()
    for layer_id in layer_ids:
        try:
            layer = project.mapLayer(layer_id)
            if layer is None:
                continue  # removed again before we got to it
            group_id, table_name = _group_id_and_table_from_source(layer)
            if group_id is None:
                continue
            _place_layer_in_group(layer, group_id, table_name)
        except Exception:
            pass


def _auto_organize_layers(layers):
    # Deferred to the next event-loop pass on purpose. When a layer is added
    # manually, QGIS inserts its own tree node for it right after this signal
    # fires — doing the grouping inline races with that and leaves a second,
    # duplicate node behind. Waiting until QGIS has finished lets us collapse
    # whatever nodes exist down to exactly one. Layer *ids* are captured
    # rather than the layer objects, so a layer removed in the meantime is
    # simply skipped instead of crashing.
    layer_ids = [lyr.id() for lyr in layers]
    QTimer.singleShot(0, lambda: _organize_layer_ids(layer_ids))


_HANDLER_KEY = "_package_layers_by_citymun_autogroup_handler"

# Re-running this script must REPLACE the handler an earlier run connected,
# not stack another one on top of it. The previous run's function object is
# stashed on the always-loaded qgis.utils module, which survives between
# script runs in the same QGIS session, so it can be found and disconnected
# here. (Calling layersAdded.disconnect() with no argument is deliberately
# avoided — that would also tear down QGIS's own internal connections.)
_previous_handler = getattr(qgis.utils, _HANDLER_KEY, None)
if _previous_handler is not None:
    try:
        QgsProject.instance().layersAdded.disconnect(_previous_handler)
    except Exception:
        pass

QgsProject.instance().layersAdded.connect(_auto_organize_layers)
setattr(qgis.utils, _HANDLER_KEY, _auto_organize_layers)


# -----------------------------------------------------------------------------
# Styling for the packaged layers. Applied only when the dialog's "Load
# packaged layers" option puts them into the project — deliberately NOT in
# _auto_organize_layers() above, so manually browsing to a .gpkg still gets
# the grouping/renaming without having its symbology overwritten.
# -----------------------------------------------------------------------------

QML_STYLE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "qml styles")

# Matched against the end of the output layer name, so the "{citymun}" part
# of the templates below is irrelevant: ref_Iriga_lgu -> ref_province_lgu.qml.
PACKAGED_LAYER_STYLES = [
    ("_bldg_point", "1. Base Layer Building Points.qml"),
    ("_lgu", "ref_province_lgu.qml"),
    ("_psa", "ref_province_psa.qml"),
    ("ref_mbi_cases", "ref_mbi_cases.qml"),
]


def _apply_packaged_layer_style(layer):
    """Load the QML matching this layer's name from the plugin's "qml styles"
    folder. Returns the filename applied, or None if nothing matched, the
    file is missing, or QGIS rejected it."""
    name = layer.name().lower()
    for suffix, qml_file in PACKAGED_LAYER_STYLES:
        if not name.endswith(suffix):
            continue
        path = os.path.join(QML_STYLE_DIR, qml_file)
        if not os.path.isfile(path):
            return None
        # Symbology + labeling only: several of these QMLs also carry field
        # aliases, form layouts and absolute editform paths from the project
        # they were saved out of, which have no business on a packaged layer.
        _, ok = layer.loadNamedStyle(
            path, QgsMapLayer.Symbology | QgsMapLayer.Labeling
        )
        if not ok:
            return None
        layer.triggerRepaint()
        return qml_file
    return None


class PackageLayersDialog(QDialog):

    # Output layer-name templates. "{citymun}" is replaced with the
    # sanitized city/mun name for each group.
    LAYER_NAME_TEMPLATES = {
        "ref_mbi_cases": "ref_mbi_cases",
        "ref_province_lgu": "ref_{citymun}_lgu",
        "ref_province_psa": "ref_{citymun}_psa",
        "ref_provincename_bldg_point": "ref_{citymun}_bldg_point",
    }

    # Attribute names stripped from every output table on write, matched
    # case-insensitively. See the write call for why each one goes.
    DROPPED_FIELDS = {"fid", "layer", "path"}

    # Best-guess field names, checked in order, used to prefill the
    # editable field dropdowns once the selected layers' fields are known.
    GEOCODE_FIELD_CANDIDATES = ["geocode", "sa_geocode"]
    CITYMUN_FIELD_CANDIDATES = ["city_mun", "citymun"]

    # Keywords (checked as case-insensitive substrings of the layer name)
    # used to auto-preselect each role's dropdown. This is more forgiving
    # than an exact-name match, since real project layer names often carry
    # extra prefixes/suffixes (dates, versions, copy numbers, etc.).
    ROLE_KEYWORDS = {
        "ref_mbi_cases": ["mbi_cases", "mbi cases"],
        "ref_provincename_bldg_point": ["bldg_point", "bldg point", "building_point", "bldgpoint"],
        "ref_province_psa": ["province_psa", "psa"],
        "ref_province_lgu": ["province_lgu", "lgu"],
    }

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.setWindowTitle("Package Layers by City/Mun")
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
        )
        self.setSizeGripEnabled(True)
        self.setMinimumSize(640, 440)
        self.resize(880, 560)
        self._build_ui()

    # ------------------------------------------------------------------ UI --

    def _build_ui(self):
        main_layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        main_layout.addWidget(splitter)

        left_widget = QWidget()
        left_widget.setMinimumWidth(360)
        left = QVBoxLayout(left_widget)

        title = QLabel("<b>Package Layers by City/Mun</b>")
        title.setStyleSheet("font-size: 13pt;")
        left.addWidget(title)

        form = QFormLayout()

        self.cbo_cases = self._make_layer_combo()
        form.addRow("Cases layer:", self.cbo_cases)

        self.cbo_bldg = self._make_layer_combo()
        form.addRow("Building points layer:", self.cbo_bldg)

        self.cbo_psa = self._make_layer_combo()
        form.addRow("Province PSA layer:", self.cbo_psa)

        self.cbo_lgu = self._make_layer_combo()
        form.addRow("Province LGU layer:", self.cbo_lgu)

        # Best-effort preselect based on the layer names used in this project
        self._try_preselect(self.cbo_cases, "ref_mbi_cases")
        self._try_preselect(self.cbo_bldg, "ref_provincename_bldg_point")
        self._try_preselect(self.cbo_psa, "ref_province_psa")
        self._try_preselect(self.cbo_lgu, "ref_province_lgu")

        # Editable dropdowns: populated from the fields common to the
        # selected layers, and auto-prefilled with the best-guess match.
        self.cbo_geocode_field = QComboBox()
        self.cbo_geocode_field.setEditable(True)
        form.addRow("Geocode field name:", self.cbo_geocode_field)

        self.cbo_citymun_field = QComboBox()
        self.cbo_citymun_field.setEditable(True)
        form.addRow("City/Mun name field:", self.cbo_citymun_field)

        left.addLayout(form)

        # Keep the field dropdowns in sync with whichever layers are picked
        for combo in (self.cbo_cases, self.cbo_bldg, self.cbo_psa, self.cbo_lgu):
            combo.layerChanged.connect(self._refresh_field_options)
        self._refresh_field_options()

        left.addWidget(QLabel("Output folder:"))
        out_row = QHBoxLayout()
        self.txt_output = QLineEdit()
        self.txt_output.setPlaceholderText("Choose a folder to save the packaged GeoPackages...")
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self._browse_output)
        out_row.addWidget(self.txt_output)
        out_row.addWidget(btn_browse)
        left.addLayout(out_row)

        self.chk_load_layers = QCheckBox(
            "Load packaged layers into QGIS after Run (grouped per city/mun)"
        )
        self.chk_load_layers.setChecked(False)
        left.addWidget(self.chk_load_layers)

        self.chk_basemap = QCheckBox("Add Google Satellite basemap below the layers")
        self.chk_basemap.setChecked(False)
        self.chk_basemap.setEnabled(False)
        self.chk_basemap.setToolTip(
            "Adds the same XYZ basemap as HCMGIS > Basemaps > Google Satellite, "
            "placed at the bottom of the layer tree so it sits underneath "
            "everything else. Requires the HCMGIS plugin."
        )
        self.chk_basemap.setStyleSheet("margin-left: 18px;")
        # Only meaningful when there are freshly loaded layers to sit under.
        self.chk_load_layers.toggled.connect(self.chk_basemap.setEnabled)
        left.addWidget(self.chk_basemap)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        left.addWidget(self.progress)

        btn_row = QHBoxLayout()
        self.btn_cleanup = QPushButton("Clean up duplicates")
        self.btn_cleanup.setToolTip(
            "Remove duplicate layers already sitting in the Packaged Layers "
            "groups, keeping one copy of each."
        )
        self.btn_cleanup.clicked.connect(self._cleanup_duplicates)
        self.btn_run = QPushButton("Run")
        self.btn_run.clicked.connect(self._run)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_cleanup)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_run)
        btn_row.addWidget(self.btn_close)
        left.addLayout(btn_row)

        left.addWidget(QLabel("Log:"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        left.addWidget(self.log)

        # ------------------------------------------------ description panel --

        desc = QLabel()
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignTop)
        desc.setTextFormat(Qt.RichText)
        desc.setText(
            "<h3>About this tool</h3>"
            "<p>Splits your reference layers into one GeoPackage per "
            "city/municipality, each in its own folder.</p>"
            "<p><b>Naming convention</b><br>"
            "Folder: <code>pppmm_CITYMUN</code><br>"
            "GeoPackage: <code>pppmm_CITYMUN.gpkg</code></p>"
            "<p><b>ppp</b> = 3-digit province code<br>"
            "<b>mm</b> = 2-digit city/mun code<br>"
            "(together, the first 5 characters of the geocode field)</p>"
            "<p>Each output GeoPackage contains all four selected layers, "
            "filtered to only the features belonging to that city/mun. "
            "Layers inside the GeoPackage are renamed as:</p>"
            "<p><code>ref_mbi_cases</code><br>"
            "<code>ref_CITYMUN_lgu</code><br>"
            "<code>ref_CITYMUN_psa</code><br>"
            "<code>ref_CITYMUN_bldg_point</code></p>"
            "<p>The source \"fid\", \"layer\" and \"path\" attribute fields "
            "are dropped on write. Dropping \"fid\" lets GeoPackage assign a "
            "fresh, unique one per output table (prevents \"UNIQUE "
            "constraint failed: fid\" errors); \"layer\" and \"path\" are "
            "merge leftovers naming the source file, which have no place in "
            "a packaged deliverable.</p>"
            "<p>The list of city/mun codes and names is always built from "
            "all four selected layers combined, so nothing is missed.</p>"
            "<p>Once this script has run in the session, ANY layer you add "
            "afterwards from a packaged GeoPackage — including manually via "
            "Add Vector Layer or the Browser panel — is automatically "
            "placed in its city/mun group and has the \"&lt;file&gt; — "
            "&lt;table&gt;\" name QGIS's Add Layer dialog applies by "
            "default stripped back down to just the table name. Adding the "
            "same table again replaces the existing copy rather than "
            "duplicating it.</p>"
            "<p><b>Clean up duplicates</b> sweeps the existing \"Packaged "
            "Layers\" groups and removes any duplicate copies already "
            "sitting there from earlier loads, keeping one of each.</p>"
            "<p><b>How to use</b></p>"
            "<ol>"
            "<li>Pick the layer for each of the four roles.</li>"
            "<li>Confirm the geocode and city/mun field names.</li>"
            "<li>Choose an output folder.</li>"
            "<li>Click <b>Run</b>. Nothing is added to the Layers panel "
            "automatically — the run only writes files to disk.</li>"
            "<li>Optionally tick \"Load packaged layers into QGIS\" first "
            "if you want the results added straight to the Layers panel, "
            "each city/mun in its own group under a top-level \"Packaged "
            "Layers\" group. Best used for spot-checking a few city/mun — "
            "leave it off for a large, national-scale run, since adding "
            "hundreds of groups/layers can slow QGIS down.</li>"
            "<li>With that ticked, you can also tick \"Add Google Satellite "
            "basemap below the layers\" to drop the HCMGIS Google Satellite "
            "imagery at the bottom of the layer tree, underneath everything "
            "loaded. Needs the HCMGIS plugin installed.</li>"
            "</ol>"
            "<p><i>Tip: if province codes start with 0 (e.g. 013), make "
            "sure the geocode field is stored as text, not a number — "
            "otherwise the leading zero may already be lost.</i></p>"
            "<p><i>The log lists how many features matched each layer per "
            "city/mun. If that count looks the same as the whole layer's "
            "total feature count for every group, the geocode field picked "
            "for that layer doesn't actually vary by city/mun — double-"
            "check the field selected for that role.</i></p>"
        )
        desc.setStyleSheet("padding: 12px;")

        desc_scroll = QScrollArea()
        desc_scroll.setWidgetResizable(True)
        desc_scroll.setMinimumWidth(260)
        desc_scroll.setWidget(desc)
        desc_scroll.setStyleSheet(
            "QScrollArea { background-color: palette(base); border: 1px solid palette(mid); }"
        )

        splitter.addWidget(left_widget)
        splitter.addWidget(desc_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([540, 340])

    def _make_layer_combo(self):
        combo = QgsMapLayerComboBox()
        combo.setFilters(QgsMapLayerProxyModel.VectorLayer)
        return combo

    def _try_preselect(self, combo, role):
        # 1) Exact name match first (fastest path when names match exactly).
        exact = QgsProject.instance().mapLayersByName(role)
        if exact:
            combo.setLayer(exact[0])
            return

        # 2) Fall back to a case-insensitive keyword match, e.g. any loaded
        #    layer whose name contains "mbi_cases", "bldg_point", etc.
        keywords = self.ROLE_KEYWORDS.get(role, [])
        if not keywords:
            return
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.type() != QgsMapLayer.VectorLayer:
                continue
            name_lower = lyr.name().lower()
            if any(k in name_lower for k in keywords):
                combo.setLayer(lyr)
                return

    def _refresh_field_options(self):
        """Repopulate the geocode/city_mun field dropdowns from the fields
        found across the currently selected layers, keeping the current
        selection if it still exists, else prefilling with the best guess."""
        layers = [
            self.cbo_cases.currentLayer(),
            self.cbo_bldg.currentLayer(),
            self.cbo_psa.currentLayer(),
            self.cbo_lgu.currentLayer(),
        ]
        field_names = []
        seen = set()
        for lyr in layers:
            if lyr is None:
                continue
            for f in lyr.fields():
                if f.name().lower() not in seen:
                    seen.add(f.name().lower())
                    field_names.append(f.name())
        field_names.sort(key=str.lower)

        self._fill_field_combo(self.cbo_geocode_field, field_names, self.GEOCODE_FIELD_CANDIDATES)
        self._fill_field_combo(self.cbo_citymun_field, field_names, self.CITYMUN_FIELD_CANDIDATES)

    @staticmethod
    def _fill_field_combo(combo, field_names, candidates):
        previous = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(field_names)
        combo.blockSignals(False)

        lower_names = {n.lower(): n for n in field_names}
        if previous and previous.lower() in lower_names:
            combo.setCurrentText(lower_names[previous.lower()])
            return
        for candidate in candidates:
            if candidate.lower() in lower_names:
                combo.setCurrentText(lower_names[candidate.lower()])
                return
        if candidates:
            combo.setCurrentText(candidates[0])

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select output folder")
        if folder:
            self.txt_output.setText(folder)

    def _cleanup_duplicates(self):
        removed = _cleanup_duplicate_packaged_layers()
        self._log(f"Cleaned up {removed} duplicate layer(s).")
        QMessageBox.information(
            self, "Clean up duplicates",
            f"Removed {removed} duplicate layer(s) from the "
            f"\"{TOP_GROUP_NAME}\" groups."
        )

    def _log(self, msg):
        self.log.appendPlainText(msg)
        QApplication.processEvents()

    # --------------------------------------------------------------- logic --

    @staticmethod
    def _find_field(layer, field_name):
        lower_map = {f.name().lower(): f.name() for f in layer.fields()}
        actual = lower_map.get(field_name.strip().lower())
        if not actual:
            raise Exception(
                f"Field '{field_name}' not found in layer '{layer.name()}'. "
                f"Available fields: {[f.name() for f in layer.fields()]}"
            )
        return actual

    @staticmethod
    def _sanitize(name):
        keep = "-_() "
        cleaned = "".join(c for c in str(name).strip() if c.isalnum() or c in keep)
        return cleaned.strip().replace(" ", "_")

    def _add_group_to_project(self, gpkg_path, group_id, layer_names):
        """Load the just-written layers back into QGIS under their own
        city/mun group. Placement and naming are handled by the session-wide
        _auto_organize_layers() handler (connected near the top of this
        script) as soon as each layer is added, so this does exactly what a
        manual "Add Vector Layer" would do — just triggered from code."""
        # Clear any previous run's group for this city/mun first, so
        # re-running doesn't pile up duplicate layers inside it.
        _get_citymun_group(group_id, replace=True)

        for name in layer_names:
            uri = f"{gpkg_path}|layername={name}"
            vlayer = QgsVectorLayer(uri, name, "ogr")
            if not vlayer.isValid():
                self._log(f"    WARNING: could not load '{name}' into the project")
                continue
            # Styled before the layer is added, so it never renders unstyled.
            applied = _apply_packaged_layer_style(vlayer)
            if applied:
                self._log(f"    styled '{name}' with {applied}")
            QgsProject.instance().addMapLayer(vlayer, False)

    def _expand_packaged_groups(self):
        """Expand the Packaged Layers tree in the Layers panel itself.

        node.setExpanded(True) alone only sets state that gets saved to the
        project — the live panel is a QgsLayerTreeView whose expansion is
        driven by its own (proxy) model, and our group nodes get created and
        re-parented after the view has already built its items. So the view
        has to be told directly, through a proxy-mapped index."""
        view = self.iface.layerTreeView()
        if view is None:
            return
        top = QgsProject.instance().layerTreeRoot().findGroup(TOP_GROUP_NAME)
        if top is None:
            return

        groups = [top] + [c for c in top.children() if isinstance(c, QgsLayerTreeGroup)]
        for node in groups:
            node.setExpanded(True)
            # QgsLayerTreeView.node2index(), not the model's: the view's own
            # returns an index already mapped through its proxy, which is
            # what setExpanded() needs.
            index = view.node2index(node)
            if index.isValid():
                view.setExpanded(index, True)

    def _add_basemap(self):
        """Put the Google Satellite XYZ basemap at the bottom of the layer
        tree, underneath everything just loaded. Reuses the implementation
        the PSA/LGU comparison tool already ships rather than repeating it."""
        from .psa_lgu_map_comparison import (
            GOOGLE_SATELLITE_BASEMAP_NAME,
            ensure_google_satellite_basemap,
        )

        # Silent on every failure path (HCMGIS missing, basemap already
        # there), so check the project rather than trusting a return value.
        ensure_google_satellite_basemap()
        present = any(
            lyr.name().lower() == GOOGLE_SATELLITE_BASEMAP_NAME.lower()
            for lyr in QgsProject.instance().mapLayers().values()
        )
        if present:
            self._log(f"\nBasemap: '{GOOGLE_SATELLITE_BASEMAP_NAME}' is at the bottom of the layer tree.")
        else:
            self._log(
                "\nWARNING: could not add the Google Satellite basemap — "
                "the HCMGIS plugin does not appear to be installed."
            )

    def _run(self):
        self.log.clear()
        self.progress.setValue(0)

        # ---- Gather + validate inputs ----
        role_layers = {
            "ref_mbi_cases": self.cbo_cases.currentLayer(),
            "ref_provincename_bldg_point": self.cbo_bldg.currentLayer(),
            "ref_province_psa": self.cbo_psa.currentLayer(),
            "ref_province_lgu": self.cbo_lgu.currentLayer(),
        }
        missing = [role for role, lyr in role_layers.items() if lyr is None]
        if missing:
            QMessageBox.warning(self, "Missing layers", f"Please select a layer for: {', '.join(missing)}")
            return

        output_root = self.txt_output.text().strip()
        if not output_root:
            QMessageBox.warning(self, "Missing output folder", "Please choose an output folder.")
            return

        geocode_field_name = self.cbo_geocode_field.currentText().strip()
        citymun_field_name = self.cbo_citymun_field.currentText().strip()
        if not geocode_field_name or not citymun_field_name:
            QMessageBox.warning(self, "Missing field names", "Please enter both the geocode and city/mun field names.")
            return

        try:
            geocode_fields = {role: self._find_field(lyr, geocode_field_name) for role, lyr in role_layers.items()}
            citymun_fields = {role: self._find_field(lyr, citymun_field_name) for role, lyr in role_layers.items()}
        except Exception as e:
            QMessageBox.critical(self, "Field error", str(e))
            return

        self.btn_run.setEnabled(False)
        try:
            self._do_package(role_layers, geocode_fields, citymun_fields, output_root)
        except Exception as e:
            self._log(f"ERROR: {e}")
            QMessageBox.critical(self, "Error", str(e))
        finally:
            self.btn_run.setEnabled(True)

    def _do_package(self, role_layers, geocode_fields, citymun_fields, output_root):
        # City/mun codes and names are built from all four selected layers,
        # so no city/mun combination present in any of them is missed.
        self._log("Building city/mun code list from all 4 layers...")
        citymun_lookup = {}
        for role in role_layers.keys():
            lyr = role_layers[role]
            gfield = geocode_fields[role]
            cfield = citymun_fields[role]
            for feat in lyr.getFeatures():
                geocode = feat[gfield]
                if geocode is None:
                    continue
                geocode = str(geocode).strip()
                if len(geocode) < 5:
                    continue
                pppmm = geocode[:5]
                cname = feat[cfield]
                if pppmm not in citymun_lookup and cname not in (None, ""):
                    citymun_lookup[pppmm] = str(cname).strip()

        self._log(f"Found {len(citymun_lookup)} unique city/mun codes.\n")

        os.makedirs(output_root, exist_ok=True)
        transform_context = QgsProject.instance().transformContext()

        total = len(citymun_lookup)
        self.progress.setMaximum(max(total, 1))

        for n, (pppmm, citymun_name) in enumerate(sorted(citymun_lookup.items()), start=1):
            safe_citymun = self._sanitize(citymun_name)
            group_id = f"{pppmm}_{safe_citymun}"

            out_folder = os.path.join(output_root, group_id)
            os.makedirs(out_folder, exist_ok=True)
            gpkg_path = os.path.join(out_folder, f"{group_id}.gpkg")

            if os.path.exists(gpkg_path):
                os.remove(gpkg_path)

            self._log(f"[{n}/{total}] Packaging {group_id}")
            written_layers = []

            for i, role in enumerate(role_layers.keys()):
                lyr = role_layers[role]
                gfield = geocode_fields[role]
                filter_expr = f'left(to_string("{gfield}"), 5) = \'{pppmm}\''
                out_layer_name = self.LAYER_NAME_TEMPLATES.get(role, role).format(citymun=safe_citymun)

                # Select the matching features explicitly (rather than
                # relying on SaveVectorOptions.filterExpression, which in
                # some QGIS versions is not reliably applied by the writer
                # and can silently export the whole layer). selectByExpression
                # uses the same expression engine QGIS uses everywhere else,
                # so this is the most dependable way to isolate just this
                # city/mun's features before writing.
                lyr.removeSelection()
                lyr.selectByExpression(filter_expr)
                matched = lyr.selectedFeatureCount()
                self._log(f"    {role}: {matched} feature(s) match {pppmm} ({filter_expr})")

                options = QgsVectorFileWriter.SaveVectorOptions()
                options.driverName = "GPKG"
                options.layerName = out_layer_name
                options.onlySelectedFeatures = True
                options.fileEncoding = "UTF-8"
                options.actionOnExistingFile = (
                    QgsVectorFileWriter.CreateOrOverwriteFile
                    if i == 0
                    else QgsVectorFileWriter.CreateOrOverwriteLayer
                )

                # "fid": GPKG reserves it as the table's integer primary
                # key. A source layer carrying its own "fid" attribute
                # (common when it was itself merged from several datasets)
                # often has values that are not unique within the filtered
                # subset, raising "UNIQUE constraint failed: <table>.fid".
                # Dropping it lets GDAL renumber from scratch per table.
                #
                # "layer"/"path": provenance columns Merge Vector Layers
                # appends, naming the source file each feature came from.
                # They are noise in a packaged deliverable.
                fields = lyr.fields()
                keep_indices = [
                    idx for idx in range(len(fields))
                    if fields[idx].name().lower() not in self.DROPPED_FIELDS
                ]
                if len(keep_indices) != len(fields):
                    options.attributes = keep_indices

                try:
                    result = QgsVectorFileWriter.writeAsVectorFormatV3(lyr, gpkg_path, transform_context, options)
                    error_code = result[0]
                    error_message = result[1] if len(result) > 1 else ""

                    if error_code != QgsVectorFileWriter.NoError:
                        self._log(f"    ERROR writing layer '{out_layer_name}': {error_message}")
                    else:
                        self._log(f"    OK: layer '{out_layer_name}' written ({matched} feature(s))")
                        written_layers.append(out_layer_name)
                finally:
                    lyr.removeSelection()

            if self.chk_load_layers.isChecked() and written_layers:
                self._add_group_to_project(gpkg_path, group_id, written_layers)

            self.progress.setValue(n)

        # After every group, so the basemap lands beneath all of them.
        if self.chk_load_layers.isChecked() and self.chk_basemap.isChecked():
            self._add_basemap()

        if self.chk_load_layers.isChecked():
            # Queued, not called directly: _auto_organize_layers defers its
            # own work onto singleShot(0) too, so the layers are not in their
            # final groups yet. Same-delay timers fire in order, and this one
            # is queued last, so it runs once the tree has settled.
            QTimer.singleShot(0, self._expand_packaged_groups)

        self._log("\nDone.")
        QMessageBox.information(self, "Finished", f"Packaged {total} city/mun GeoPackage(s) to:\n{output_root}")


class PackageLayersAlgorithm(QgsProcessingAlgorithm):
    """
    Processing Toolbox entry point for Package Layers by City/Mun. The tool
    is inherently interactive (pick layers, confirm field names, browse an
    output folder), so running it from the Toolbox in QGIS Desktop simply
    opens the same dialog available from Gemma > Others.
    """

    OUTPUT = "OUTPUT"

    def tr(self, string):
        return QCoreApplication.translate("Processing", string)

    def createInstance(self):
        return PackageLayersAlgorithm()

    def name(self):
        return "package_layers_by_citymun"

    def displayName(self):
        return self.tr("Package Layers by City/Mun")

    def group(self):
        return self.tr("1Map")

    def groupId(self):
        return "1map"

    def icon(self):
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icons", "package_layers.svg")
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return QIcon(":/images/themes/default/mActionFilter.svg")

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def shortHelpString(self):
        return self.tr(
            "Splits four reference layers into one GeoPackage per city/mun, each "
            "in its own folder, for LGU presentation packaging.\n\n"
            "Opens the interactive Package Layers by City/Mun dialog, where you pick "
            "the four layers, confirm the geocode and city/mun field names, choose "
            "an output folder, and click Run."
        )

    def initAlgorithm(self, config=None):
        self.addOutput(QgsProcessingOutputString(self.OUTPUT, self.tr("Result")))

    def processAlgorithm(self, parameters, context, feedback):
        message = "Opened the Package Layers by City/Mun dialog."
        try:
            from qgis.PyQt.QtWidgets import QApplication as _QApplication
            app = _QApplication.instance()
            if app is not None and app.property("appType") != "headless":
                # exec_(), not show(): dlg is a local, so once this method
                # returns the only thing keeping the dialog alive is its Qt
                # parent. exec_() holds it in a proper modal event loop for
                # as long as it is open. Safe on the main thread via
                # FlagNoThreading.
                dlg = PackageLayersDialog(qgis.utils.iface)
                dlg.exec_()
            else:
                message = "No GUI available: Package Layers by City/Mun requires QGIS Desktop."
        except Exception as e:
            message = f"Could not open the Package Layers by City/Mun dialog: {e}"
            if feedback is not None:
                feedback.reportError(message)

        if feedback is not None:
            feedback.pushInfo(message)
        return {self.OUTPUT: message}