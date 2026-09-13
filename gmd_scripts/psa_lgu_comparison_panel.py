"""
Review panel for the PSA - LGU Boundary Comparison algorithm.

Docks below the Layers panel and lets the user step through every matched
barangay one at a time -- zooming the canvas to each barangay so the PSA
(blue) and LGU (yellow) outlines are framed together for visual comparison.

This module is GUI-only and is imported lazily by
psa_lgu_map_comparison.py, so that algorithm stays usable headless
(qgis_process / standalone PyQGIS) where no iface exists.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox,
)
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsExpression,
    QgsFeatureRequest,
    QgsRectangle,
    QgsCoordinateTransform,
)


DOCK_OBJECT_NAME = "GemmaPsaLguComparisonPanel"

# The comparison algorithm appends these fields to its Matched outputs (and
# match_id/in_match_id to the Unmatched Building output -- see below).
# match_id is the grouping key used here in preference to geocode: source
# layers very often already carry a field literally named "geocode" (the
# algorithm's own auto-detection looks for exactly that), and the appended
# column then lands under a different name ("geocode_2", ...) to avoid
# clobbering it -- see GEOCODE_FIELD_PROPERTY below for how the correct one
# is still found. match_id practically never collides this way.
MATCH_ID_FIELD = "match_id"
GEOCODE_FIELD = "geocode"

# Custom property the algorithm tags a Matched PSA/LGU layer with, naming
# the exact field that holds ITS first8-truncated barangay geocode (see
# GEOCODE_FIELD_PROPERTY in psa_lgu_map_comparison.py -- duplicated here by
# the same convention as MATCH_ID_FIELD/GEOCODE_FIELD above, so this module
# stays importable without pulling in the algorithm module).
#
# A plain case-insensitive search for a field named "geocode" is NOT
# reliable for this: when the source PSA/LGU layer already had its own
# "geocode" field, the algorithm's appended column silently renames to
# "geocode_2", and a name search keeps finding the ORIGINAL, untruncated
# source attribute instead -- which shows up as the wrong code in the
# barangay dropdown label, and would also feed any future geocode-prefix
# filter (like the fallback path in _filter_expression below) the wrong
# value. This is what the property lookup fixes.
GEOCODE_FIELD_PROPERTY = "psalgu_geocode_field"

# On the Unmatched Building output only: the match_id of the barangay the
# point was actually found sitting inside (independent of what its own
# geocode says). Together with match_id this is what lets the Outside layer
# be scoped to one barangay the same way the Matched layers already are --
# a point qualifies either because its own code names that barangay, or
# because it geographically landed inside it.
IN_MATCH_ID_FIELD = "in_match_id"

PSA_MATCHED_SUFFIX = "_psa_matched"
LGU_MATCHED_SUFFIX = "_lgu_matched"

# Fixed names the algorithm always uses for the Building outputs -- unlike
# the PSA/LGU Matched layers they carry no <code> prefix, since a project
# only ever has one Building Point comparison result at a time.
BUILDING_MATCHED_LAYER_NAME = "building points inside lgu boundary"
BUILDING_UNMATCHED_LAYER_NAME = "building points outside lgu boundary"

# Grow the zoom extent by this fraction so the barangay is not flush against
# the canvas edge -- same framing factor the Check and Update dialog uses.
ZOOM_PADDING_RATIO = 0.15

_PANEL_INSTANCE = None


def _field_lookup(layer, name):
    """Return the layer's actual field name matching *name* case
    insensitively, or None when the layer has no such field."""
    for field in layer.fields():
        if field.name().lower() == name.lower():
            return field.name()
    return None


def _geocode_field(layer):
    """Return the field on *layer* holding the algorithm's first8-truncated
    barangay geocode -- the field the algorithm tagged via
    GEOCODE_FIELD_PROPERTY when it's present, falling back to a plain
    "geocode" name search for layers that predate the tag (or aren't one of
    this algorithm's own outputs, e.g. a manually added layer). See
    GEOCODE_FIELD_PROPERTY above for why the tag matters."""
    tagged = layer.customProperty(GEOCODE_FIELD_PROPERTY)
    if tagged:
        found = _field_lookup(layer, tagged)
        if found:
            return found
    return _field_lookup(layer, GEOCODE_FIELD)


def _barangay_field(layer):
    """Return the layer's barangay-name field, trying the spellings the
    source data is known to use. Returns None when none are present."""
    for candidate in ("barangay", "brgy_name", "bgy_name", "brgy", "bgy", "name"):
        found = _field_lookup(layer, candidate)
        if found:
            return found
    return None


def find_matched_layers():
    """Locate a PSA_Matched / LGU_Matched / Matched Building / Unmatched
    Building output set already in the project.

    Walks the layer tree in display order and takes the first
    "<code>_PSA_Matched" layer found, then pairs it with the
    "<code>_LGU_Matched" layer carrying the same code prefix so that
    outputs from different municipalities are never mixed. The two
    Building layers carry no code prefix, so they are matched by their
    fixed names alone.
    Returns (psa_id, lgu_id, building_id, unmatched_building_id), any of
    which may be None.
    """
    project = QgsProject.instance()
    layers = [n.layer() for n in project.layerTreeRoot().findLayers()]

    building_layer = None
    unmatched_building_layer = None
    for layer in layers:
        if not isinstance(layer, QgsVectorLayer):
            continue
        name_lower = layer.name().lower()
        if building_layer is None and name_lower == BUILDING_MATCHED_LAYER_NAME:
            building_layer = layer
        elif unmatched_building_layer is None and name_lower == BUILDING_UNMATCHED_LAYER_NAME:
            unmatched_building_layer = layer
    building_id = building_layer.id() if building_layer else None
    unmatched_building_id = unmatched_building_layer.id() if unmatched_building_layer else None

    psa_layer = None
    for layer in layers:
        if isinstance(layer, QgsVectorLayer) and layer.name().lower().endswith(PSA_MATCHED_SUFFIX):
            psa_layer = layer
            break
    if psa_layer is None:
        return None, None, building_id, unmatched_building_id

    prefix = psa_layer.name()[:-len(PSA_MATCHED_SUFFIX)]
    expected_lgu = (prefix + LGU_MATCHED_SUFFIX).lower()
    lgu_id = None
    for layer in layers:
        if not isinstance(layer, QgsVectorLayer):
            continue
        if lgu_id is None and layer.name().lower() == expected_lgu:
            lgu_id = layer.id()
            break

    return psa_layer.id(), lgu_id, building_id, unmatched_building_id


class PsaLguComparisonPanel(QDockWidget):
    """Dock listing every matched barangay with jump-to and Previous/Next
    navigation that zooms the canvas to the selected barangay."""

    def __init__(self, iface, psa_layer_id, lgu_layer_id, building_layer_id=None,
                 unmatched_building_layer_id=None):
        super().__init__("PSA - LGU Comparison Review", iface.mainWindow())
        self.setObjectName(DOCK_OBJECT_NAME)
        self.iface = iface
        # Layers are held by id, never by object: the user can delete an
        # output layer at any time and a stale C++ reference would raise
        # RuntimeError on access. Resolving through the project each time
        # keeps the panel safe against that.
        self.psa_layer_id = psa_layer_id
        self.lgu_layer_id = lgu_layer_id
        self.building_layer_id = building_layer_id
        self.unmatched_building_layer_id = unmatched_building_layer_id
        self.setAllowedAreas(
            Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea
            | Qt.BottomDockWidgetArea | Qt.TopDockWidgetArea
        )

        self._build_ui()
        self.populate()

    # ── UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        main_widget = QWidget(self)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        combo_layout = QHBoxLayout()
        combo_layout.setSpacing(6)

        title_lbl = QLabel("Barangay:")
        title_lbl.setStyleSheet("font-weight: bold; font-size: 12px; color: #2C3E50;")
        combo_layout.addWidget(title_lbl)

        self.barangay_combo = QComboBox()
        self.barangay_combo.setStyleSheet("""
            QComboBox {
                font-weight: bold;
                padding: 3px 6px;
                border: 1px solid #BDC3C7;
                border-radius: 4px;
                background-color: white;
                color: #2C3E50;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #BDC3C7;
                background-color: white;
                color: #2C3E50;
                selection-background-color: #2980B9;
                selection-color: white;
            }
            QComboBox QAbstractItemView::item {
                min-height: 22px;
                color: #2C3E50;
            }
            QComboBox QAbstractItemView::item:selected {
                background-color: #2980B9;
                color: white;
            }
        """)
        self.barangay_combo.currentIndexChanged.connect(self._on_barangay_selected)
        combo_layout.addWidget(self.barangay_combo, 1)
        layout.addLayout(combo_layout)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)

        self.show_all_btn = QPushButton("Show All")
        self.show_all_btn.setToolTip(
            "Clear the barangay filter and zoom out to the whole city/municipality -- "
            "every matched barangay at once."
        )
        self.show_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #27AE60;
                color: white;
                font-weight: bold;
                padding: 4px 8px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #1E8449; }
            QPushButton:disabled { background-color: #D5D8DC; color: #909497; }
        """)
        self.show_all_btn.clicked.connect(self.show_all)
        btn_layout.addWidget(self.show_all_btn)

        self.prev_btn = QPushButton("Previous")
        self.prev_btn.setStyleSheet("""
            QPushButton {
                background-color: #7F8C8D;
                color: white;
                font-weight: bold;
                padding: 4px 8px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #616D6E; }
            QPushButton:disabled { background-color: #D5D8DC; color: #909497; }
        """)
        self.prev_btn.clicked.connect(self.go_previous)

        self.next_btn = QPushButton("Next")
        self.next_btn.setStyleSheet("""
            QPushButton {
                background-color: #2980B9;
                color: white;
                font-weight: bold;
                padding: 4px 8px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #1F618D; }
            QPushButton:disabled { background-color: #D5D8DC; color: #909497; }
        """)
        self.next_btn.clicked.connect(self.go_next)

        btn_layout.addWidget(self.prev_btn)
        btn_layout.addWidget(self.next_btn)
        btn_layout.addStretch()

        self.position_lbl = QLabel("")
        self.position_lbl.setStyleSheet("font-size: 11px; color: #7F8C8D;")
        btn_layout.addWidget(self.position_lbl)

        layout.addLayout(btn_layout)
        self.setWidget(main_widget)

    # ── Layer access ────────────────────────────────────────────────────
    def psa_layer(self):
        return QgsProject.instance().mapLayer(self.psa_layer_id) if self.psa_layer_id else None

    def lgu_layer(self):
        return QgsProject.instance().mapLayer(self.lgu_layer_id) if self.lgu_layer_id else None

    def building_layer(self):
        return QgsProject.instance().mapLayer(self.building_layer_id) if self.building_layer_id else None

    def unmatched_building_layer(self):
        return (QgsProject.instance().mapLayer(self.unmatched_building_layer_id)
                if self.unmatched_building_layer_id else None)

    def _filterable_layers(self):
        """PSA/LGU Matched and the Matched Building layer, when present --
        every layer that should be isolated to one barangay by simple field
        equality. The Unmatched Building layer is scoped separately (see
        _apply_filter/_clear_filter) since it needs an OR of two fields
        instead of one."""
        return (self.psa_layer(), self.lgu_layer(), self.building_layer())

    def set_layers(self, psa_layer_id, lgu_layer_id, building_layer_id=None,
                    unmatched_building_layer_id=None):
        """Point the panel at a different output set and rebuild the list."""
        self._clear_filter()
        self.psa_layer_id = psa_layer_id
        self.lgu_layer_id = lgu_layer_id
        self.building_layer_id = building_layer_id
        self.unmatched_building_layer_id = unmatched_building_layer_id
        self.populate()

    # ── Population ──────────────────────────────────────────────────────
    def populate(self):
        """Rebuild the barangay list from the PSA Matched layer.

        Entries are keyed on match_id and de-duplicated, so a barangay split
        into several polygons (islands) appears once and navigates as one
        unit -- matching how the algorithm groups them.
        """
        self.barangay_combo.blockSignals(True)
        self.barangay_combo.clear()

        layer = self.psa_layer()
        if layer is None or not layer.isValid():
            self.barangay_combo.blockSignals(False)
            self._update_controls()
            return

        self._clear_filter()

        key_field = _field_lookup(layer, MATCH_ID_FIELD) or _geocode_field(layer)
        name_field = _barangay_field(layer)
        geocode_field = _geocode_field(layer)

        seen = set()
        entries = []
        for feat in layer.getFeatures():
            key = feat[key_field] if key_field else feat.id()
            if key is None or key in seen:
                continue
            seen.add(key)

            name = str(feat[name_field]).strip() if name_field and feat[name_field] is not None else ""
            code = str(feat[geocode_field]).strip() if geocode_field and feat[geocode_field] is not None else ""
            if name and code:
                label = "{} - {}".format(name, code)
            else:
                label = name or code or "Barangay {}".format(key)
            entries.append((key, label))

        for key, label in entries:
            self.barangay_combo.addItem(label, key)

        self.barangay_combo.blockSignals(False)
        if self.barangay_combo.count():
            self.barangay_combo.setCurrentIndex(0)
            self._show_current()
        self._update_controls()

    def _update_controls(self):
        count = self.barangay_combo.count()
        idx = self.barangay_combo.currentIndex()
        has_items = count > 0
        self.show_all_btn.setEnabled(has_items)
        self.prev_btn.setEnabled(has_items)
        self.next_btn.setEnabled(has_items)
        self.position_lbl.setText("{} of {}".format(idx + 1, count) if has_items else "No matched barangays")

    # ── Navigation ──────────────────────────────────────────────────────
    def go_next(self):
        count = self.barangay_combo.count()
        if count:
            self.barangay_combo.setCurrentIndex((self.barangay_combo.currentIndex() + 1) % count)

    def go_previous(self):
        count = self.barangay_combo.count()
        if count:
            self.barangay_combo.setCurrentIndex((self.barangay_combo.currentIndex() - 1) % count)

    def _on_barangay_selected(self, index):
        if index >= 0:
            self._show_current()
        self._update_controls()

    # ── Filtering ───────────────────────────────────────────────────────
    def _filter_expression(self, layer, key):
        """Return the "key_field = key" expression string used to isolate
        one barangay on *layer*, or None when it has no usable key field."""
        key_field = _field_lookup(layer, MATCH_ID_FIELD) or _geocode_field(layer)
        if not key_field:
            return None
        return QgsExpression.createFieldEqualityExpression(key_field, key)

    def _unmatched_building_filter_expression(self, layer, key):
        """Return the expression that isolates barangay *key* on the
        Unmatched Building (Outside) layer, or None when it has neither
        usable field.

        Unlike every other layer this panel filters, a point can belong to
        the barangay under review two different ways: match_id is set when
        the point's OWN geocode names that barangay (it was supposed to be
        there and failed the boundary test), and in_match_id is set when the
        point was found to actually sit inside that barangay's LGU polygon
        despite carrying a different code or none. Without this, the
        Outside layer showed every barangay's rejected points together no
        matter which one the panel had zoomed to."""
        match_field = _field_lookup(layer, MATCH_ID_FIELD)
        in_match_field = _field_lookup(layer, IN_MATCH_ID_FIELD)
        parts = [
            QgsExpression.createFieldEqualityExpression(f, key)
            for f in (match_field, in_match_field) if f
        ]
        if not parts:
            return None
        return " OR ".join("({})".format(p) for p in parts)

    def _apply_filter(self, key):
        """Restrict the Matched PSA, Matched LGU, Matched Building and
        Unmatched Building layers to just barangay *key*, via
        setSubsetString, so nothing from the rest of the barangays --
        polygons or building points, inside or outside the boundary -- is
        drawn underneath the one being reviewed."""
        for layer in self._filterable_layers():
            if layer is None or not layer.isValid():
                continue
            expression = self._filter_expression(layer, key)
            if expression:
                layer.setSubsetString(expression)

        unmatched_building = self.unmatched_building_layer()
        if unmatched_building is not None and unmatched_building.isValid():
            expression = self._unmatched_building_filter_expression(unmatched_building, key)
            if expression:
                unmatched_building.setSubsetString(expression)

    def _clear_filter(self):
        """Remove any barangay filter from the Matched PSA/LGU/Building and
        Unmatched Building layers, restoring the full set of features to
        view."""
        layers = self._filterable_layers() + (self.unmatched_building_layer(),)
        for layer in layers:
            if layer is not None and layer.isValid() and layer.subsetString():
                layer.setSubsetString("")

    def _show_current(self):
        """Filter both Matched layers down to the selected barangay and zoom
        the canvas to it -- the combined effect of the Next/Prev/dropdown
        navigation."""
        key = self.barangay_combo.currentData()
        if key is None:
            return
        self._apply_filter(key)
        self._zoom_to_current(key)

    # ── Zooming ─────────────────────────────────────────────────────────
    def _selection_extent(self, layer, key):
        """Return the combined bounding box (in canvas CRS) of *layer*'s
        features belonging to barangay *key*, or None. The subset filter
        applied by _apply_filter() is what isolates the barangay on the
        map -- this does not select/highlight features on top of that."""
        if layer is None or not layer.isValid():
            return None

        expression = self._filter_expression(layer, key)
        if not expression:
            return None
        request = QgsFeatureRequest().setFilterExpression(expression)

        rect = None
        for feat in layer.getFeatures(request):
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            box = geom.boundingBox()
            rect = QgsRectangle(box) if rect is None else rect
            rect.combineExtentWith(box)

        if rect is None:
            return None

        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        if layer.crs() != canvas_crs:
            transform = QgsCoordinateTransform(
                layer.crs(), canvas_crs, QgsProject.instance().transformContext()
            )
            rect = transform.transformBoundingBox(rect)
        return rect

    def _zoom_to_current(self, key):
        extent = None
        for layer in (self.psa_layer(), self.lgu_layer()):
            rect = self._selection_extent(layer, key)
            if rect is None:
                continue
            extent = QgsRectangle(rect) if extent is None else extent
            extent.combineExtentWith(rect)
        self._apply_extent(extent)

    def _full_extent(self, layer):
        """Return layer's full extent (in canvas CRS), ignoring any
        barangay filter currently applied -- the whole-city/municipality
        view that show_all() zooms to."""
        if layer is None or not layer.isValid():
            return None
        rect = layer.extent()
        if rect is None or rect.isEmpty():
            return None

        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        if layer.crs() != canvas_crs:
            transform = QgsCoordinateTransform(
                layer.crs(), canvas_crs, QgsProject.instance().transformContext()
            )
            rect = transform.transformBoundingBox(rect)
        return rect

    def _apply_extent(self, extent):
        if extent is None:
            return

        # A zero-size extent (a single point, or a degenerate polygon) cannot
        # be framed by ratio, so fall back to a small absolute buffer.
        padding = max(extent.width(), extent.height()) * ZOOM_PADDING_RATIO
        extent.grow(padding if padding > 0 else 0.0001)

        canvas = self.iface.mapCanvas()
        canvas.setExtent(extent)
        canvas.refresh()

    def show_all(self):
        """Clear the per-barangay filter and zoom out to the combined
        extent of the PSA and LGU layers, so the whole city/municipality is
        visible at once instead of one barangay at a time. Previous/Next/
        the dropdown all re-apply the per-barangay filter the next time
        they're used, same as before this was added."""
        self._clear_filter()
        extent = None
        for layer in (self.psa_layer(), self.lgu_layer()):
            rect = self._full_extent(layer)
            if rect is None:
                continue
            extent = QgsRectangle(rect) if extent is None else extent
            extent.combineExtentWith(rect)
        self._apply_extent(extent)
        self.position_lbl.setText(
            "Showing all {} barangay(s)".format(self.barangay_combo.count()))

    # ── Lifecycle ───────────────────────────────────────────────────────
    def closeEvent(self, event):
        global _PANEL_INSTANCE
        # Closing the panel should not leave the map silently filtered down
        # to one barangay with no visible way to explain why.
        self._clear_filter()
        if _PANEL_INSTANCE is self:
            _PANEL_INSTANCE = None
        super().closeEvent(event)


def show_comparison_panel(iface, psa_layer_id=None, lgu_layer_id=None, building_layer_id=None,
                           unmatched_building_layer_id=None):
    """Create, re-dock or refresh the singleton review panel.

    When no layer ids are given the set is auto-discovered from the project,
    which is how the Gemma menu entry reopens the panel for outputs that are
    already loaded. Returns the panel, or None when there is nothing to show.
    """
    global _PANEL_INSTANCE

    if psa_layer_id is None and lgu_layer_id is None and building_layer_id is None:
        (psa_layer_id, lgu_layer_id, building_layer_id,
         unmatched_building_layer_id) = find_matched_layers()
    if psa_layer_id is None:
        return None

    panel = _PANEL_INSTANCE
    if panel is None:
        panel = PsaLguComparisonPanel(
            iface, psa_layer_id, lgu_layer_id, building_layer_id,
            unmatched_building_layer_id)
        iface.addDockWidget(Qt.LeftDockWidgetArea, panel)
        _PANEL_INSTANCE = panel
    else:
        panel.set_layers(psa_layer_id, lgu_layer_id, building_layer_id,
                          unmatched_building_layer_id)

    panel.show()
    panel.raise_()
    return panel


def close_comparison_panel(iface):
    """Remove the panel from the main window. Called from plugin unload() so
    every addDockWidget has a matching removal."""
    global _PANEL_INSTANCE
    if _PANEL_INSTANCE is None:
        return
    try:
        _PANEL_INSTANCE._clear_filter()
        iface.removeDockWidget(_PANEL_INSTANCE)
        _PANEL_INSTANCE.deleteLater()
    except Exception:
        pass
    _PANEL_INSTANCE = None
