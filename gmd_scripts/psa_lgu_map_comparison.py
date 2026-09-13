import os
import re

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.core import (
    QgsProject,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterField,
    QgsProcessingLayerPostProcessorInterface,
    QgsExpression,
    QgsVectorLayer,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsGeometry,
    QgsSpatialIndex,
    QgsCoordinateTransform,
    QgsWkbTypes,
    QgsFillSymbol,
    QgsMarkerSymbol,
    QgsSingleSymbolRenderer,
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling,
    QgsTextFormat,
    QgsTextBufferSettings,
)


# Only a field literally named "Geocode" (any case) is auto-detected --
# other spellings/codes (PSGC, brgy_code, etc.) are not guessed, so the
# user is expected to pick those explicitly when auto-detection fails.
GEOCODE_FIELD_HINTS = ["geocode"]

# Layer-name keywords used to pre-select the three input layers when the
# dialog opens. Each list is tried in order, so the more specific spelling
# wins over the looser one (e.g. "000102_psa" before a bare "psa").
PSA_LAYER_HINTS = ["_psa", "psa"]
LGU_LAYER_HINTS = ["_lgu", "lgu"]
BUILDING_LAYER_HINTS = [
    "bldgpts", "bldg_point", "bldgpoint", "building point", "building_point",
    "geotagged", "bldg", "building",
]

# Name fragments of this algorithm's own output layers. They match the input
# hints above ("000102_PSA_Matched" contains "psa"), so they're skipped when
# picking defaults -- otherwise a second run would pre-select the first run's
# results instead of the original source layers.
OUTPUT_NAME_MARKERS = [
    "_matched", "_unmatched", "inside lgu boundary", "outside lgu boundary",
]


def find_default_layer_id(hints, geometry_type, exclude_ids=()):
    """Return the id of a loaded vector layer of geometry_type whose name
    contains one of hints (case-insensitive), or None if the project has no
    such layer. Candidates are considered in name order so that reopening
    the dialog on an unchanged project always pre-selects the same layer.
    Returns None rather than raising if the project can't be read -- a
    missing default just leaves that box empty."""
    try:
        project = QgsProject.instance()
        if project is None:
            return None
        candidates = []
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                continue
            if layer.id() in exclude_ids:
                continue
            if layer.geometryType() != geometry_type:
                continue
            name_lower = layer.name().lower()
            if any(marker in name_lower for marker in OUTPUT_NAME_MARKERS):
                continue
            candidates.append((name_lower, layer.id()))
        candidates.sort()
        for hint in hints:
            for name_lower, layer_id in candidates:
                if hint in name_lower:
                    return layer_id
    except Exception:
        return None
    return None


def find_default_geocode_field(layer_id):
    """Return the Geocode field name on the layer with layer_id, so the
    dialog's Geocode box comes up already filled in for a pre-selected
    layer. None (no such layer, or no Geocode-like field) leaves the box
    empty, which processAlgorithm() then resolves the same way as before."""
    if not layer_id:
        return None
    try:
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is None:
            return None
        return guess_geocode_field([f.name() for f in layer.fields()])
    except Exception:
        return None


def _unique_field_name(base_name, fields):
    """Return base_name, or base_name with a numeric suffix appended, so
    that it is guaranteed not to already exist on *fields* (compared
    case-insensitively, matching how GeoPackage/most providers treat
    column names).

    QgsFields.append() does NOT raise or rename when asked to add a field
    whose name already exists on the target schema -- for the memory
    provider used throughout this module, appending an exact-case duplicate
    is a silent no-op: the field count does not change, and the extra value
    later passed to setAttributes() for it is silently dropped rather than
    stored anywhere. Since PSA/LGU/Building source layers routinely already
    carry a field literally named "geocode" (auto-detection for the Geocode
    Field parameter looks for exactly that name), appending another
    "geocode" column to report the matched barangay silently failed to add
    anything -- the output layer kept showing each point's own original,
    untouched geocode value instead, which is why a building shown under
    barangay X's filter could display a geocode that names a different
    barangay entirely.
    """
    existing = {f.name().lower() for f in fields}
    if base_name.lower() not in existing:
        return base_name
    suffix = 2
    while f"{base_name}_{suffix}".lower() in existing:
        suffix += 1
    return f"{base_name}_{suffix}"


def _move_layer_node(layer_id, insert_index=None):
    """Move the tree node for layer_id to be a direct child of the project's
    layer tree root, either inserted at insert_index (0 = very top of the
    Layers panel) or appended at the end (insert_index=None, the bottom).

    Repositioning explicitly like this -- rather than relying on QGIS's own
    position for newly added layers, which is a user-configurable setting
    (Settings > Options > General > "Add new layers to...") and not
    guaranteed to be "top" -- is what actually guarantees the ordering this
    module promises: output layers above the original inputs, and the
    basemap below everything. No-op if the layer has no tree node (e.g. it
    was removed from the project before this ran)."""
    root = QgsProject.instance().layerTreeRoot()
    node = root.findLayer(layer_id)
    if node is None:
        return
    parent = node.parent()
    clone = node.clone()
    if insert_index is None:
        root.addChildNode(clone)
    else:
        root.insertChildNode(insert_index, clone)
    if parent is not None:
        parent.removeChildNode(node)


# Same display name HCMGIS > Basemaps > Google Satellite uses for the layer
# it adds -- used both to build the layer and to recognize one already in
# the project, so a re-run never piles up duplicates.
GOOGLE_SATELLITE_BASEMAP_NAME = "Google Satellite"


def ensure_google_satellite_basemap():
    """Load the same "Google Satellite" XYZ basemap that HCMGIS > Basemaps >
    Google Satellite adds, positioned at the very bottom of the layer tree
    so it sits underneath every other layer instead of on top of them --
    then the reviewer always has imagery to compare against without adding
    it by hand.

    A no-op when a layer named "Google Satellite" is already in the
    project (this only ever needs to run once), or when the HCMGIS plugin
    isn't installed/importable. HCMGIS is a required dependency of this
    plugin (see dependency_checker.py), but this is a convenience on top of
    the comparison run, not part of it -- its absence must never fail the
    algorithm itself.
    """
    project = QgsProject.instance()
    for layer in project.mapLayers().values():
        if layer.name().lower() == GOOGLE_SATELLITE_BASEMAP_NAME.lower():
            return
    try:
        from HCMGIS import hcmgis_library
    except ImportError:
        return
    try:
        before_ids = set(project.mapLayers().keys())
        hcmgis_library.hcmgis_basemap(GOOGLE_SATELLITE_BASEMAP_NAME)
        added_ids = set(project.mapLayers().keys()) - before_ids
    except Exception:
        return
    if not added_ids:
        return
    try:
        for layer_id in added_ids:
            _move_layer_node(layer_id)  # appended at the end == bottom
    except Exception:
        pass


def guess_geocode_field(field_names):
    """Return the field name if one is literally named "Geocode" (case
    insensitive), or None if no such field exists. Tries an exact match
    first, then falls back to a substring match so e.g. "Geocode_10"
    still gets picked up."""
    lower_to_actual = {n.lower(): n for n in field_names}
    for hint in GEOCODE_FIELD_HINTS:
        if hint in lower_to_actual:
            return lower_to_actual[hint]
    for hint in GEOCODE_FIELD_HINTS:
        for lower_name, actual_name in lower_to_actual.items():
            if hint in lower_name:
                return actual_name
    return None


def extract_code(layer_name):
    """Pull the leading pppmm-style code off a layer name like
    "000102_LGU" or "00102_PSA_Boundary" -> "000102" / "00102".
    Falls back to a leading run of digits, and finally to the whole
    name if no code-like prefix is found."""
    if not layer_name:
        return ""
    m = re.match(r"^(.*?)_(PSA|LGU)\b", layer_name, re.IGNORECASE)
    if m:
        return m.group(1)
    m2 = re.match(r"^(\d+)", layer_name)
    if m2:
        return m2.group(1)
    return layer_name


def style_boundary_outline(layer, color):
    """Style a polygon layer as a transparent-fill, colored-outline
    boundary -- used to tell Matched_PSA (blue) and Matched_LGU (yellow)
    apart on the map at a glance."""
    symbol = QgsFillSymbol.createSimple({
        "color": "0,0,0,0",       # transparent fill
        "outline_color": color,
        "outline_width": "0.6",
        "outline_width_unit": "MM",
    })
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))


def style_building_points(layer, color):
    """Style a building-point layer as small filled circles in color --
    used to tell the points inside the LGU boundary (green) from the ones
    outside it (red) without having to click them. Both output layers would
    otherwise get QGIS's random default symbol, which says nothing."""
    symbol = QgsMarkerSymbol.createSimple({
        "name": "circle",
        "color": color,
        "outline_color": "black",
        "outline_width": "0.2",
        "size": "2.0",
        "size_unit": "MM",
    })
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))


def label_by_field(layer, field_name, source_suffix=None, color=None):
    """Turn on map labels for a polygon layer, showing the value of
    field_name for each feature in bold text with a dark halo so it stays
    readable over any fill color or basemap. The field is matched
    case-insensitively (source data may store it as "barangay",
    "Barangay", "BARANGAY", etc.). Does nothing (and returns False) if
    the layer doesn't actually have that field, so a missing "barangay"
    column on the source data doesn't break the rest of the run.

    When source_suffix is given (e.g. "PSA" or "LGU"), it is appended in
    parentheses -- "Poblacion (PSA)" -- so the two overlaid, same-named
    barangay labels from the PSA and LGU layers can be told apart on the
    map at a glance instead of reading as duplicate text.

    color, when given, is the same color name/spec passed to
    style_boundary_outline() for this layer's own outline -- the label then
    reads in that color too, so a
    label can be matched back to its polygon at a glance instead of every
    layer's labels looking identical. Defaults to white when omitted.
    """
    lower_to_actual = {f.name().lower(): f.name() for f in layer.fields()}
    actual_field_name = lower_to_actual.get(field_name.lower())
    if actual_field_name is None:
        return False
    field_name = actual_field_name

    text_format = QgsTextFormat()
    text_format.setColor(QColor(color) if color else QColor(255, 255, 255))
    font = text_format.font()
    font.setBold(True)
    font.setPointSize(10)
    text_format.setFont(font)

    buffer_settings = QgsTextBufferSettings()
    buffer_settings.setEnabled(True)
    buffer_settings.setSize(1.0)
    buffer_settings.setColor(QColor(0, 0, 0))  # dark halo for contrast
    text_format.setBuffer(buffer_settings)

    settings = QgsPalLayerSettings()
    if source_suffix:
        settings.fieldName = "{} || {}".format(
            QgsExpression.quotedColumnRef(field_name),
            QgsExpression.quotedString(" ({})".format(source_suffix)),
        )
        settings.isExpression = True
    else:
        settings.fieldName = field_name
    settings.enabled = True
    settings.setFormat(text_format)

    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    return True


def first8(value):
    """First 8 characters of a value's string form. This is the matching
    rule used for PSA vs LGU boundary polygons -- comparing geocode/PSGC-
    style codes at the region-province-municipality-barangay level while
    ignoring trailing digits/suffixes that may differ between layers.

    For building points it picks WHICH barangay a point is checked against:
    the point then has to actually fall inside that barangay's LGU polygon
    to count as inside (see _LguBoundaryLocator).

    CAVEAT: if a geocode column is stored as a NUMBER field rather than
    text, leading zeros may already be lost (e.g. "01030200" -> 1030200),
    which would make the first-8 comparison unreliable. Text/string
    geocode columns are recommended.
    """
    if value is None:
        return ""
    s = str(value).strip()
    return s[:8]


class _LguBoundaryLocator:
    """Point-in-polygon lookup over a set of boundary polygons, keyed by
    first-8 geocode -- used for the LGU layer.

    A building point counts as inside when it falls within the polygon(s)
    of the barangay ITS OWN GEOCODE names -- not merely somewhere within
    the municipality. Almost every point in a submission lands inside some
    barangay, so a municipality-wide test finds nothing wrong and leaves
    the Outside layer empty; the error actually worth catching is a point
    sitting outside the barangay it is labelled with, which is what
    appears as points scattered beyond the outline while reviewing that
    barangay in the comparison panel.

    contains() answers that per-barangay question. code_for() answers the
    follow-up for the points that fail it -- which barangay the point does
    fall in, if any -- and is what fills the "in_geocode" column on the
    Outside layer, separating a mis-coded point from one captured outside
    the municipality altogether.

    Polygons added via add() are keyed on feature id for the spatial
    index, so those features must come from a layer (provider ids are
    unique).
    """

    def __init__(self):
        self._index = QgsSpatialIndex()
        self._entries = {}
        self._by_code = {}

    def add(self, feature, code):
        """Index one polygon under its first-8 geocode. Null/empty
        geometries are skipped -- they can't contain anything."""
        geometry = feature.geometry()
        if geometry is None or geometry.isEmpty():
            return
        self._index.addFeature(feature)
        self._entries[feature.id()] = (geometry, code)
        self._by_code.setdefault(code, []).append(geometry)

    def is_empty(self):
        return not self._entries

    def contains(self, code, point_geometry):
        """True when point_geometry falls inside one of the LGU polygons
        carrying first-8 geocode *code*.

        A barangay split into several shapes (islands) is several polygons
        under one code, and landing in any of them counts. A point sitting
        exactly on the barangay's edge counts as inside too -- the edge
        belongs to the barangay as much as its interior does, and points
        are routinely digitised onto the line.

        A blank code matches nothing: there is no barangay to check
        against, so such a point can never be confirmed inside.
        """
        if not code or point_geometry is None or point_geometry.isEmpty():
            return False

        for geometry in self._by_code.get(code, ()):
            try:
                if geometry.contains(point_geometry) or geometry.intersects(point_geometry):
                    return True
            except Exception:
                # An invalid/self-intersecting LGU polygon makes GEOS throw.
                # It can't answer for this point; the barangay's other parts
                # still can.
                continue
        return False

    def code_for(self, point_geometry):
        """Return the first-8 geocode of the LGU polygon containing
        point_geometry, or None when it falls outside all of them.

        A point sitting exactly on a shared barangay edge is properly
        contained by neither neighbour, so a merely-touching polygon is
        remembered and returned only when nothing contains the point --
        that keeps points digitised onto a boundary line inside the
        municipality instead of dropping them into the Outside layer.
        """
        if point_geometry is None or point_geometry.isEmpty():
            return None

        on_edge = None
        for fid in self._index.intersects(point_geometry.boundingBox()):
            entry = self._entries.get(fid)
            if entry is None:
                continue
            geometry, code = entry
            try:
                if geometry.contains(point_geometry):
                    return code
                if on_edge is None and geometry.intersects(point_geometry):
                    on_edge = code
            except Exception:
                # An invalid/self-intersecting LGU polygon makes GEOS throw.
                # It simply can't answer for this point; the others still can.
                continue
        return on_edge


class _RunCoordinator:
    """Tracks one run's output layers as they land in the project and
    drives four main-thread-only cleanup steps from postProcessLayer() --
    the documented hook for it, since processAlgorithm() itself executes on
    a Processing worker thread where touching the layer tree or iface is
    never safe:

    - Moves each output layer into one layer-tree group for this run (see
      _move_into_group), created at the very top of the tree the first time
      any output lands, so every Matched/Unmatched result from one run stays
      visually bundled together instead of scattered as loose top-level
      layers.
    - Hides the original PSA / LGU / Building Point input layers in the
      layer tree as soon as any output from this run has landed, so the map
      view shows the new Matched/Unmatched results instead of the raw
      source layers underneath them.
    - Loads the HCMGIS "Google Satellite" basemap at the bottom of the
      layer tree (once per project, not per run) so there is imagery to
      compare the boundaries against without the user adding it by hand.
    - Opens the review panel once every expected Matched output (PSA, LGU,
      and Building when present) has landed. QGIS stores layers-to-load-
      on-completion in a container keyed by layer id, not registration
      order, so postProcessLayer() can fire for them in any order; waiting
      for the full expected set makes this order-independent.
    """

    def __init__(self, input_layer_ids, panel_psa_id, panel_lgu_id, panel_building_id,
                 panel_unmatched_building_id=None, group_name=None):
        self.input_layer_ids = [lid for lid in input_layer_ids if lid]
        self.panel_psa_id = panel_psa_id
        self.panel_lgu_id = panel_lgu_id
        self.panel_building_id = panel_building_id
        self.panel_unmatched_building_id = panel_unmatched_building_id
        self.panel_expected = {
            lid for lid in (panel_psa_id, panel_lgu_id, panel_building_id,
                             panel_unmatched_building_id) if lid
        }
        self.group_name = group_name or "PSA - LGU Comparison"
        self.group = None
        self.seen = set()
        self.inputs_hidden = False
        self.basemap_loaded = False
        self.panel_shown = False

    def mark_seen(self, layer_id, feedback):
        self.seen.add(layer_id)
        self._move_into_group(layer_id)
        self._hide_inputs()
        self._load_basemap()
        self._maybe_show_panel(feedback)

    def _ensure_group(self):
        if self.group is None:
            root = QgsProject.instance().layerTreeRoot()
            self.group = root.insertGroup(0, self.group_name)
        return self.group

    def _move_into_group(self, layer_id):
        try:
            root = QgsProject.instance().layerTreeRoot()
            node = root.findLayer(layer_id)
            if node is None:
                return
            parent = node.parent()
            clone = node.clone()
            self._ensure_group().insertChildNode(0, clone)
            if parent is not None:
                parent.removeChildNode(node)
        except Exception:
            pass

    def _hide_inputs(self):
        if self.inputs_hidden or not self.input_layer_ids:
            return
        self.inputs_hidden = True
        try:
            root = QgsProject.instance().layerTreeRoot()
            for layer_id in self.input_layer_ids:
                node = root.findLayer(layer_id)
                if node is not None:
                    node.setItemVisibilityChecked(False)
        except Exception:
            pass

    def _load_basemap(self):
        if self.basemap_loaded:
            return
        self.basemap_loaded = True
        try:
            ensure_google_satellite_basemap()
        except Exception:
            pass

    def _maybe_show_panel(self, feedback):
        if self.panel_shown or not self.panel_expected.issubset(self.seen):
            return
        self.panel_shown = True

        try:
            from qgis.utils import iface
        except ImportError:
            return
        # Headless runs (qgis_process, standalone PyQGIS) have no iface --
        # the algorithm must still complete normally there, just with no GUI.
        if iface is None:
            return
        try:
            from .psa_lgu_comparison_panel import show_comparison_panel
            show_comparison_panel(
                iface, self.panel_psa_id, self.panel_lgu_id, self.panel_building_id,
                self.panel_unmatched_building_id)
        except Exception as exc:
            feedback.pushInfo("Could not open the comparison review panel: {}".format(exc))


class _ComparisonPanelPostProcessor(QgsProcessingLayerPostProcessorInterface):
    """Reports one layer's arrival in the project to a shared coordinator.

    processAlgorithm() runs on a Processing worker thread, where touching
    iface or building widgets is never safe. postProcessLayer() is the
    documented main-thread hook, so both cleanup steps are driven from here
    instead.
    """

    def __init__(self, coordinator):
        super().__init__()
        self.coordinator = coordinator

    def postProcessLayer(self, layer, context, feedback):
        self.coordinator.mark_seen(layer.id(), feedback)


# QGIS takes ownership of a post processor, but the Python wrapper can still be
# garbage collected before postProcessLayer() runs; holding a module-level
# reference is the documented workaround. Only the most recent runs are kept
# so repeated runs don't grow this list without bound.
_PANEL_POST_PROCESSORS = []


def _make_run_post_processors(input_layer_ids, output_layer_ids,
                               panel_psa_id, panel_lgu_id, panel_building_id,
                               panel_unmatched_building_id=None, group_name=None):
    """Return {layer_id: post_processor} for every output layer id this run
    is about to load -- not just the ones the review panel needs -- so that
    hiding the original input layers happens regardless of whether a
    Matched panel ends up opening (e.g. a run where nothing matched still
    only loads Unmatched layers). All share one coordinator, and each output
    layer id gets its own processor instance -- QGIS takes ownership
    per-attachment, so the same instance cannot safely be reused across
    multiple LayerDetails."""
    coordinator = _RunCoordinator(
        input_layer_ids, panel_psa_id, panel_lgu_id, panel_building_id,
        panel_unmatched_building_id, group_name)
    processors = {}
    for layer_id in output_layer_ids:
        if not layer_id:
            continue
        processor = _ComparisonPanelPostProcessor(coordinator)
        _PANEL_POST_PROCESSORS.append(processor)
        processors[layer_id] = processor
    del _PANEL_POST_PROCESSORS[:-15]
    return processors


class PsaLguComparisonAlgorithm(QgsProcessingAlgorithm):
    """
    Matches PSA and LGU-submitted boundary polygons by comparing the first
    8 characters of a geocode field on each layer, splits the Building
    Points by whether each one falls inside the LGU polygon of the barangay
    its own geocode names, then loads styled/labeled Matched and Unmatched
    output layers into the project.
    """

    PSA_LAYER = 'PSA_LAYER'
    PSA_GEOCODE_FIELD = 'PSA_GEOCODE_FIELD'
    LGU_LAYER = 'LGU_LAYER'
    LGU_GEOCODE_FIELD = 'LGU_GEOCODE_FIELD'
    BUILDING_LAYER = 'BUILDING_LAYER'
    BUILDING_GEOCODE_FIELD = 'BUILDING_GEOCODE_FIELD'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return PsaLguComparisonAlgorithm()

    def name(self):
        return 'psalgu_boundary_comparison'

    def displayName(self):
        return self.tr('PSA - LGU Boundary Comparison')

    def group(self):
        return self.tr('1Map')

    def groupId(self):
        return '1map'

    def icon(self):
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons', 'compare_boundaries.svg')
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return QIcon(":/images/themes/default/mActionFilter.svg")

    def shortHelpString(self):
        return self.tr(
            "Matches PSA and LGU-submitted boundary polygons by comparing the first 8 characters "
            "of a geocode field on each layer -- names are not used for matching, so spelling "
            "differences between the two maps don't matter. If a barangay is made up of several "
            "separate shapes (like islands), they all stay grouped together as one barangay.\n\n"
            "Building Points are checked against the barangay their own geocode names: the point "
            "must actually fall inside that barangay's LGU boundary (reprojected first when the "
            "layers use different CRSs) to count as inside. A point labelled with a barangay it "
            "does not sit in goes to the Outside layer, even when it sits inside the municipality "
            "-- that mismatch is the error this check exists to find.\n\n"
            "The three layer boxes and their Geocode fields are pre-filled from the layers already "
            "loaded in the project -- a polygon layer named '*PSA*', another named '*LGU*', and a "
            "building-point layer -- skipping this tool's own output layers. Any of them can be "
            "changed before running, and boxes with nothing to pre-fill are simply left empty.\n\n"
            "If a Geocode field is left blank, a field literally named 'Geocode' (any case) is "
            "auto-detected on that layer; other spellings/codes (PSGC, brgy_code, etc.) are not "
            "guessed and must be selected explicitly.\n\n"
            "Boundary output layers (only created when they contain at least one feature):\n"
            "- <code>_PSA_Matched -- blue outline, labeled with the PSA layer's 'barangay' field\n"
            "- <code>_LGU_Matched -- yellow outline, labeled with the LGU layer's 'barangay' field\n"
            "- <code>_PSA_Unmatched / <code>_LGU_Unmatched\n\n"
            "Building Point output layers (both always created, even when empty, so an empty "
            "'Outside' layer reads as 'nothing outside' rather than as a check that never ran):\n"
            "- Building Points inside LGU Boundary -- green dots: the point falls inside the "
            "barangay its geocode names, and carries that barangay's match_id and geocode\n"
            "- Building Points Outside LGU Boundary -- red dots: geocode_first8 is the point's "
            "own code, and in_geocode is the barangay it actually sits in (checked against the "
            "original LGU shape) -- filled in with a different code for a mis-coded point, and "
            "left empty for a point that falls outside every barangay. Carries match_id (set when "
            "the point's own code names the barangay under review) and in_match_id (set when it "
            "geographically landed inside that barangay instead) so the review panel can scope it "
            "to one barangay the same way it scopes the Matched layers. A point whose own geocode "
            "names a barangay from a DIFFERENT LGU entirely (not present in either this run's PSA "
            "or LGU layer) and that doesn't geographically fall inside this LGU either is excluded "
            "altogether -- it has nothing to do with the boundary being checked here, so it does "
            "not pad out this layer as a false 'outside' result.\n\n"
            "Every output layer above is moved into one '<code> PSA - LGU Comparison' group at the "
            "top of the Layers panel as it loads, so a run's results stay bundled together above "
            "the original PSA, LGU and Building Point input layers instead of scattered as loose "
            "top-level layers. The original input layers are then unchecked in place (not removed, "
            "not grouped -- they can be re-checked at any time) so the map view shows only the new "
            "results.\n\n"
            "A 'Google Satellite' basemap (same one as HCMGIS > Basemaps > Google Satellite) is "
            "loaded at the bottom of the layer tree the first time this is run in a project, so "
            "there is imagery underneath to compare the boundaries against. Skipped silently if "
            "one is already loaded, or if the HCMGIS plugin isn't installed.\n\n"
            "<code> is the pppmm-style prefix parsed from the PSA (or LGU) layer name, e.g. "
            "'000102_PSA' -> '000102'.\n\n"
            "A blank geocode never counts as a match, even blank-vs-blank, and a building point "
            "with no geocode has no barangay to be checked against, so it always lands in the "
            "Outside layer. A point that does sit inside the barangay its geocode names, where "
            "that barangay has no PSA counterpart, is inside but gets no match_id -- there is no "
            "matched pair to review it under."
        )

    def initAlgorithm(self, config=None):
        # Pre-fill every box from the layers already loaded in the project:
        # a polygon layer named "*PSA*", another named "*LGU*", a
        # building-point layer, and each one's Geocode field. QGIS builds a
        # fresh algorithm instance each time the dialog opens, so these
        # reflect the project as it stands right then. They're only starting
        # points -- the user can change any of them, and a default of None
        # simply leaves that box empty as before.
        default_psa = find_default_layer_id(
            PSA_LAYER_HINTS, QgsWkbTypes.PolygonGeometry)
        # PSA and LGU share the polygon hint space, so the PSA pick is taken
        # out of the running before the LGU one is made -- otherwise a layer
        # named e.g. "PSA_LGU_draft" could end up selected for both.
        default_lgu = find_default_layer_id(
            LGU_LAYER_HINTS, QgsWkbTypes.PolygonGeometry,
            exclude_ids=(default_psa,) if default_psa else ())
        default_building = find_default_layer_id(
            BUILDING_LAYER_HINTS, QgsWkbTypes.PointGeometry)

        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.PSA_LAYER,
                self.tr('PSA Boundary Layer'),
                [QgsProcessing.TypeVectorPolygon],
                defaultValue=default_psa
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.PSA_GEOCODE_FIELD,
                self.tr('Geocode Field (PSA)'),
                parentLayerParameterName=self.PSA_LAYER,
                type=QgsProcessingParameterField.Any,
                optional=True,
                defaultValue=find_default_geocode_field(default_psa)
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.LGU_LAYER,
                self.tr('LGU-Submitted Boundary Layer'),
                [QgsProcessing.TypeVectorPolygon],
                defaultValue=default_lgu
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.LGU_GEOCODE_FIELD,
                self.tr('Geocode Field (LGU)'),
                parentLayerParameterName=self.LGU_LAYER,
                type=QgsProcessingParameterField.Any,
                optional=True,
                defaultValue=find_default_geocode_field(default_lgu)
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.BUILDING_LAYER,
                self.tr('Building Point Layer'),
                [QgsProcessing.TypeVectorPoint],
                defaultValue=default_building
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.BUILDING_GEOCODE_FIELD,
                self.tr('Geocode Field (Building Point)'),
                parentLayerParameterName=self.BUILDING_LAYER,
                type=QgsProcessingParameterField.Any,
                optional=True,
                defaultValue=find_default_geocode_field(default_building)
            )
        )
    def _resolve_geocode_field(self, layer, selected_field, label, feedback):
        """Return the user-selected geocode field, or auto-detect a field
        literally named "Geocode" on the layer if none was selected."""
        if selected_field:
            return selected_field
        guess = guess_geocode_field([f.name() for f in layer.fields()])
        if guess is None:
            raise QgsProcessingException(
                self.tr(f"Could not auto-detect a Geocode field on the {label} layer; "
                        f"please select one explicitly.")
            )
        feedback.pushInfo(self.tr(f"Auto-detected Geocode field ({label}): '{guess}'"))
        return guess

    def processAlgorithm(self, parameters, context, feedback: QgsProcessingFeedback):
        layer_psa = self.parameterAsVectorLayer(parameters, self.PSA_LAYER, context)
        layer_lgu = self.parameterAsVectorLayer(parameters, self.LGU_LAYER, context)
        building_layer = self.parameterAsVectorLayer(parameters, self.BUILDING_LAYER, context)

        if layer_psa is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.PSA_LAYER))
        if layer_lgu is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.LGU_LAYER))
        if building_layer is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.BUILDING_LAYER))

        geocode_field_psa = self._resolve_geocode_field(
            layer_psa, self.parameterAsString(parameters, self.PSA_GEOCODE_FIELD, context),
            'PSA', feedback)
        geocode_field_lgu = self._resolve_geocode_field(
            layer_lgu, self.parameterAsString(parameters, self.LGU_GEOCODE_FIELD, context),
            'LGU', feedback)
        building_field = self._resolve_geocode_field(
            building_layer, self.parameterAsString(parameters, self.BUILDING_GEOCODE_FIELD, context),
            'Building Point', feedback)

        if layer_psa.id() == layer_lgu.id():
            feedback.pushInfo(self.tr("Warning: PSA and LGU layers are the same layer. Continuing anyway."))

        feedback.setProgress(5)

        def load_layer(layer, name, post_processor=None):
            if layer is None:
                return None
            layer.setName(name)
            details = QgsProcessingContext.LayerDetails(name, context.project(), 'OUTPUT')
            if post_processor is not None:
                details.setPostProcessor(post_processor)
            context.temporaryLayerStore().addMapLayer(layer)
            context.addLayerToLoadOnCompletion(layer.id(), details)
            return layer.id()

        feats_psa = list(layer_psa.getFeatures())
        feats_lgu = list(layer_lgu.getFeatures())

        code_psa = [first8(f[geocode_field_psa]) for f in feats_psa]
        code_lgu = [first8(f[geocode_field_lgu]) for f in feats_lgu]

        # Group feature indices by geocode (first 8 chars) within each
        # layer (this is what lets a multi-part barangay travel together
        # as one group).
        group_psa = {}
        for i, c in enumerate(code_psa):
            group_psa.setdefault(c, []).append(i)
        group_lgu = {}
        for j, c in enumerate(code_lgu):
            group_lgu.setdefault(c, []).append(j)

        # A blank geocode never counts as a match, even blank-vs-blank.
        codes_psa = set(c for c in group_psa if c)
        codes_lgu = set(c for c in group_lgu if c)
        matched_codes = sorted(codes_psa & codes_lgu)

        # assign stable match_ids in sorted-code order
        pairs = [(i, code) for i, code in enumerate(matched_codes)]
        matched_code_set = set(code for _, code in pairs)

        matched_polys_psa = sum(len(group_psa[code]) for _, code in pairs)
        matched_polys_lgu = sum(len(group_lgu[code]) for _, code in pairs)
        unmatched_polys_psa = len(feats_psa) - matched_polys_psa
        unmatched_polys_lgu = len(feats_lgu) - matched_polys_lgu

        feedback.pushInfo(self.tr(
            f"Matched barangays: {len(pairs)} | Matched polygons -- PSA: {matched_polys_psa}, "
            f"LGU: {matched_polys_lgu} | Unmatched -- PSA: {unmatched_polys_psa}, LGU: {unmatched_polys_lgu}"
        ))
        feedback.setProgress(20)

        crs_psa = layer_psa.crs().authid()
        crs_lgu = layer_lgu.crs().authid()
        geom_psa = QgsWkbTypes.displayString(layer_psa.wkbType())
        geom_lgu = QgsWkbTypes.displayString(layer_lgu.wkbType())

        # pppmm-style code shared by the PSA and LGU layer names, used to
        # prefix every output layer so outputs from different
        # municipalities/cities don't collide or get confused with each
        # other. Prefer the code parsed from the PSA layer name; fall back
        # to the LGU layer name if the PSA name didn't yield one.
        code_prefix = extract_code(layer_psa.name()) or extract_code(layer_lgu.name())
        name_matched_psa = "{}_PSA_Matched".format(code_prefix)
        name_matched_lgu = "{}_LGU_Matched".format(code_prefix)
        name_unmatched_psa = "{}_PSA_Unmatched".format(code_prefix)
        name_unmatched_lgu = "{}_LGU_Unmatched".format(code_prefix)

        # Every appended field name below is resolved through
        # _unique_field_name() first: PSA/LGU/Building source layers
        # routinely already carry a field literally named "geocode" (that's
        # exactly what the Geocode Field auto-detection looks for), and
        # appending a second field under that same name is a silent no-op --
        # the column never actually gets added, and the value meant for it
        # quietly vanishes instead of landing anywhere. A field that
        # survives under a different name (match_id_2, geocode_2, ...)
        # still works correctly everywhere in THIS module, since every
        # value below is written positionally; only the review panel reads
        # "match_id" back by that literal name, so a rename there is
        # reported to the user instead of failing silently a second time.
        # "match_id" here matches the MATCH_ID_FIELD constant in
        # psa_lgu_comparison_panel.py by convention -- that module is
        # GUI-only and imported lazily by this one, so the literal is
        # duplicated rather than imported, to keep this algorithm usable
        # headless (qgis_process / standalone PyQGIS) where no iface exists.
        MATCH_ID_FIELD_NAME = "match_id"

        # Custom property key the review panel reads back (see
        # GEOCODE_FIELD_PROPERTY in psa_lgu_comparison_panel.py -- same
        # duplicated-literal convention as MATCH_ID_FIELD_NAME above) to
        # find the field appended just below, whatever name it actually
        # landed under. A blind case-insensitive search for a field named
        # "geocode" is NOT reliable here the way it is for match_id: unlike
        # match_id, "geocode" routinely already exists on the source PSA/LGU
        # layer (Geocode Field auto-detection looks for exactly that name),
        # so the appended column silently renames to "geocode_2" and a name
        # search keeps finding the ORIGINAL, untruncated source attribute
        # instead of this run's first8-truncated one -- which shows up as
        # the wrong code in the review panel's barangay dropdown label.
        GEOCODE_FIELD_PROPERTY = "psalgu_geocode_field"

        fields_matched_psa = QgsFields(layer_psa.fields())
        match_id_field_psa = _unique_field_name(MATCH_ID_FIELD_NAME, fields_matched_psa)
        fields_matched_psa.append(QgsField(match_id_field_psa, QVariant.Int))
        geocode_field_psa_out = _unique_field_name("geocode", fields_matched_psa)
        fields_matched_psa.append(QgsField(geocode_field_psa_out, QVariant.String))

        fields_matched_lgu = QgsFields(layer_lgu.fields())
        match_id_field_lgu = _unique_field_name(MATCH_ID_FIELD_NAME, fields_matched_lgu)
        fields_matched_lgu.append(QgsField(match_id_field_lgu, QVariant.Int))
        geocode_field_lgu_out = _unique_field_name("geocode", fields_matched_lgu)
        fields_matched_lgu.append(QgsField(geocode_field_lgu_out, QVariant.String))

        for label, resolved in (("PSA", match_id_field_psa), ("LGU", match_id_field_lgu)):
            if resolved != MATCH_ID_FIELD_NAME:
                feedback.pushInfo(self.tr(
                    f"Warning: the {label} layer already has a '{MATCH_ID_FIELD_NAME}' field, so "
                    f"this run's grouping field was added as '{resolved}' instead -- the review "
                    f"panel's per-barangay filter will not work on this output."
                ))
        for label, resolved in (("PSA", geocode_field_psa_out), ("LGU", geocode_field_lgu_out)):
            if resolved != "geocode":
                feedback.pushInfo(self.tr(
                    f"Note: the {label} layer already has a 'geocode' field, so this run's "
                    f"first-8-digit barangay code was added as '{resolved}' instead. The review "
                    f"panel is tagged to find it there, so its barangay dropdown label still uses "
                    f"the correct value rather than the original field."
                ))

        fields_unmatched_psa = QgsFields(layer_psa.fields())
        fields_unmatched_psa.append(QgsField(
            _unique_field_name("geocode_first8", fields_unmatched_psa), QVariant.String))
        fields_unmatched_lgu = QgsFields(layer_lgu.fields())
        fields_unmatched_lgu.append(QgsField(
            _unique_field_name("geocode_first8", fields_unmatched_lgu), QVariant.String))

        matched_psa = QgsVectorLayer("{}?crs={}".format(geom_psa, crs_psa), name_matched_psa, "memory")
        matched_lgu = QgsVectorLayer("{}?crs={}".format(geom_lgu, crs_lgu), name_matched_lgu, "memory")
        unmatched_psa = QgsVectorLayer("{}?crs={}".format(geom_psa, crs_psa), name_unmatched_psa, "memory")
        unmatched_lgu = QgsVectorLayer("{}?crs={}".format(geom_lgu, crs_lgu), name_unmatched_lgu, "memory")

        # PSA_Matched gets a blue outline, LGU_Matched a yellow outline (both
        # transparent fill) so the two boundary sources are easy to tell
        # apart on the map when overlaid.
        style_boundary_outline(matched_psa, "blue")
        style_boundary_outline(matched_lgu, "yellow")

        matched_psa.dataProvider().addAttributes(fields_matched_psa)
        matched_psa.updateFields()
        matched_lgu.dataProvider().addAttributes(fields_matched_lgu)
        matched_lgu.updateFields()
        matched_psa.setCustomProperty(GEOCODE_FIELD_PROPERTY, geocode_field_psa_out)
        matched_lgu.setCustomProperty(GEOCODE_FIELD_PROPERTY, geocode_field_lgu_out)

        # Label matched PSA and LGU shapes with the barangay name from
        # each layer's own "barangay" column -- these are just map
        # labels, not used for matching.
        labeled_psa = label_by_field(matched_psa, "barangay", source_suffix="PSA", color="blue")
        labeled_lgu = label_by_field(matched_lgu, "barangay", source_suffix="LGU", color="yellow")
        if not labeled_psa or not labeled_lgu:
            missing = []
            if not labeled_psa:
                missing.append("PSA (fields: {})".format(
                    ", ".join(f.name() for f in matched_psa.fields())))
            if not labeled_lgu:
                missing.append("LGU (fields: {})".format(
                    ", ".join(f.name() for f in matched_lgu.fields())))
            feedback.pushInfo(self.tr(
                "Warning: no 'barangay' field on -- {}".format("; ".join(missing))
            ))

        unmatched_psa.dataProvider().addAttributes(fields_unmatched_psa)
        unmatched_psa.updateFields()
        unmatched_lgu.dataProvider().addAttributes(fields_unmatched_lgu)
        unmatched_lgu.updateFields()

        matched_psa_feats, matched_lgu_feats = [], []
        # match_id -> set of distinct PSA geocode-first8 values (for Building Point matching)
        geocode_values_by_match = {}
        for match_id, code in pairs:
            geocode_values_by_match.setdefault(match_id, set()).add(code)
            for i in group_psa[code]:
                fp = feats_psa[i]
                out_f = QgsFeature(matched_psa.fields())
                out_f.setGeometry(fp.geometry())
                out_f.setAttributes(fp.attributes() + [match_id, code])
                matched_psa_feats.append(out_f)
            for j in group_lgu[code]:
                fl = feats_lgu[j]
                out_f = QgsFeature(matched_lgu.fields())
                out_f.setGeometry(fl.geometry())
                out_f.setAttributes(fl.attributes() + [match_id, code])
                matched_lgu_feats.append(out_f)

        unmatched_psa_feats = []
        for code, idxs in group_psa.items():
            if code not in matched_code_set:
                for i in idxs:
                    fp = feats_psa[i]
                    out_f = QgsFeature(unmatched_psa.fields())
                    out_f.setGeometry(fp.geometry())
                    out_f.setAttributes(fp.attributes() + [code])
                    unmatched_psa_feats.append(out_f)

        unmatched_lgu_feats = []
        for code, idxs in group_lgu.items():
            if code not in matched_code_set:
                for j in idxs:
                    fl = feats_lgu[j]
                    out_f = QgsFeature(unmatched_lgu.fields())
                    out_f.setGeometry(fl.geometry())
                    out_f.setAttributes(fl.attributes() + [code])
                    unmatched_lgu_feats.append(out_f)

        matched_psa.dataProvider().addFeatures(matched_psa_feats)
        matched_lgu.dataProvider().addFeatures(matched_lgu_feats)
        unmatched_psa.dataProvider().addFeatures(unmatched_psa_feats)
        unmatched_lgu.dataProvider().addFeatures(unmatched_lgu_feats)

        for lyr in (matched_psa, matched_lgu, unmatched_psa, unmatched_lgu):
            lyr.updateExtents()

        feedback.setProgress(50)

        # --- Building Point classification: does each point fall inside ---
        # --- the boundary of the barangay its geocode names?            ---
        # The geocode picks which barangay a point is checked against, and
        # the geometry decides the answer -- neither on its own is enough.
        # Geocode alone put points in the "inside" layer that sit well
        # outside the outline they are reviewed under; geometry alone
        # (anywhere in the municipality) passes practically every point and
        # leaves the Outside layer empty.
        # first8 code -> match_id (first barangay group wins on a rare collision)
        code8_to_match_id = {}
        for mid, codes in geocode_values_by_match.items():
            for c in codes:
                code8_to_match_id.setdefault(c, mid)

        crs_building = building_layer.crs().authid()
        geom_building = QgsWkbTypes.displayString(building_layer.wkbType())

        fields_building_matched = QgsFields(building_layer.fields())
        match_id_field_building = _unique_field_name(MATCH_ID_FIELD_NAME, fields_building_matched)
        fields_building_matched.append(QgsField(match_id_field_building, QVariant.Int))
        fields_building_matched.append(
            QgsField(_unique_field_name("geocode", fields_building_matched), QVariant.String))
        if match_id_field_building != MATCH_ID_FIELD_NAME:
            feedback.pushInfo(self.tr(
                f"Warning: the Building Point layer already has a '{MATCH_ID_FIELD_NAME}' field, "
                f"so this run's grouping field was added as '{match_id_field_building}' instead -- "
                f"the review panel's per-barangay filter will not work on this output."
            ))

        fields_building_unmatched = QgsFields(building_layer.fields())
        fields_building_unmatched.append(
            QgsField(_unique_field_name("geocode_first8", fields_building_unmatched), QVariant.String))
        # Which barangay the point DOES sit in, when it sits in one at all.
        # This is what separates a mis-coded point (in_geocode filled in, and
        # different from geocode_first8) from one captured outside the
        # municipality entirely (in_geocode empty).
        fields_building_unmatched.append(
            QgsField(_unique_field_name("in_geocode", fields_building_unmatched), QVariant.String))
        # match_id / in_match_id are what let the review panel scope this
        # Outside layer to one barangay, the same way it already scopes the
        # Matched layers -- without them, every barangay's outside points
        # show up together no matter which one is being reviewed. A point
        # can be relevant to a barangay two different ways: match_id is set
        # when the point's OWN geocode names that barangay (it was supposed
        # to be there and failed the boundary test); in_match_id is set when
        # the point was found to actually sit inside that barangay's LGU
        # polygon despite carrying a different code (or none). Either or
        # both may be NULL -- a point with a blank geocode and sitting
        # outside every LGU polygon has no barangay to be relevant to.
        match_id_field_unmatched = _unique_field_name(MATCH_ID_FIELD_NAME, fields_building_unmatched)
        fields_building_unmatched.append(QgsField(match_id_field_unmatched, QVariant.Int))
        in_match_id_field_unmatched = _unique_field_name("in_match_id", fields_building_unmatched)
        fields_building_unmatched.append(QgsField(in_match_id_field_unmatched, QVariant.Int))
        if match_id_field_unmatched != MATCH_ID_FIELD_NAME:
            feedback.pushInfo(self.tr(
                f"Warning: the Building Point layer already has a '{MATCH_ID_FIELD_NAME}' field, "
                f"so this run's grouping field on the Outside layer was added as "
                f"'{match_id_field_unmatched}' instead -- the review panel's per-barangay filter "
                f"will not work on this output."
            ))

        matched_building = QgsVectorLayer(
            "{}?crs={}".format(geom_building, crs_building),
            "Building Points inside LGU Boundary", "memory")
        unmatched_building = QgsVectorLayer(
            "{}?crs={}".format(geom_building, crs_building),
            "Building Points Outside LGU Boundary", "memory")

        matched_building.dataProvider().addAttributes(fields_building_matched)
        matched_building.updateFields()
        unmatched_building.dataProvider().addAttributes(fields_building_unmatched)
        unmatched_building.updateFields()

        style_building_points(matched_building, "0,153,0")   # inside  -- green
        style_building_points(unmatched_building, "227,26,28")  # outside -- red

        lgu_locator = _LguBoundaryLocator()
        for fl, code in zip(feats_lgu, code_lgu):
            lgu_locator.add(fl, code)
        if lgu_locator.is_empty():
            feedback.pushInfo(self.tr(
                "Warning: the LGU layer has no usable polygon geometry -- every building "
                "point is reported outside."
            ))

        def point_is_inside(code8, test_geom):
            """True when *test_geom* falls inside the LGU polygon(s) carrying
            first-8 geocode *code8*."""
            return lgu_locator.contains(code8, test_geom)

        def point_landed_in(test_geom):
            """Which barangay's LGU polygon *test_geom* actually sits in."""
            return lgu_locator.code_for(test_geom)

        # The test runs in the LGU layer's CRS, so a building layer in a
        # different CRS is reprojected first. Comparing raw coordinates from
        # two systems would silently place every point outside the boundary.
        point_transform = None
        crs_differs = building_layer.crs() != layer_lgu.crs()
        if crs_differs and not (building_layer.crs().isValid() and layer_lgu.crs().isValid()):
            feedback.pushInfo(self.tr(
                "Warning: the building point and LGU layers declare different CRSs but at "
                "least one of them is undefined, so the points are tested as-is -- assign a "
                "CRS to both layers if the inside/outside split looks wrong."
            ))
        elif crs_differs:
            point_transform = QgsCoordinateTransform(
                building_layer.crs(), layer_lgu.crs(),
                QgsProject.instance().transformContext()
            )
            feedback.pushInfo(self.tr(
                "Reprojecting building points from {} to {} for the boundary test.".format(
                    crs_building or "unknown CRS", crs_lgu or "unknown CRS")
            ))

        # Every first-8 geocode this run actually knows about, from either
        # side (matched or not) -- used below to tell a genuine boundary
        # violation for THIS LGU apart from a building that simply belongs
        # to a different city/municipality's PSGC entirely and has nothing
        # to do with this comparison run.
        all_run_codes = codes_psa | codes_lgu

        matched_building_feats, unmatched_building_feats = [], []
        # Why each outside point is outside -- mutually exclusive, so the
        # three add up to the Outside layer's feature count.
        blank_code = 0        # no geocode at all: nothing to check it against
        wrong_barangay = 0    # sits inside a different barangay
        outside_all = 0       # sits inside no LGU barangay whatsoever
        foreign_lgu = 0       # own geocode names a barangay from a different LGU entirely
        total_buildings = building_layer.featureCount()
        for processed, feat in enumerate(building_layer.getFeatures(), start=1):
            if feedback.isCanceled():
                return {}

            # The test geometry is a copy: reprojecting it must not disturb
            # the geometry written to the output, which stays in the building
            # layer's own CRS (the CRS both output layers were created with).
            test_geom = QgsGeometry(feat.geometry()) if feat.hasGeometry() else None
            if test_geom is not None and point_transform is not None:
                try:
                    test_geom.transform(point_transform)
                except Exception:
                    # Un-transformable coordinates can't be placed at all.
                    test_geom = None

            code8 = first8(feat[building_field])

            if point_is_inside(code8, test_geom):
                # match_id is NULL when the barangay the point sits in has no
                # PSA counterpart: the point is where its geocode says it
                # should be, but there is no matched pair to review it under.
                out_f = QgsFeature(matched_building.fields())
                out_f.setGeometry(feat.geometry())
                out_f.setAttributes(
                    feat.attributes() + [code8_to_match_id.get(code8), code8])
                matched_building_feats.append(out_f)
            else:
                landed_in = point_landed_in(test_geom)

                if code8 and code8 not in all_run_codes and not landed_in:
                    # The point's own geocode names a barangay from a
                    # different LGU entirely -- not merely a different
                    # barangay within this one -- and it doesn't
                    # geographically fall inside any of this run's PSA/LGU
                    # barangays either. It has nothing to do with the
                    # boundary being checked here, so it is excluded
                    # instead of padding out the Outside layer with a
                    # "violation" against a municipality this run never
                    # touched (e.g. 02917004000000 showing up as outside
                    # 02915002000000's boundary).
                    foreign_lgu += 1
                    continue

                if not code8:
                    blank_code += 1
                elif landed_in:
                    wrong_barangay += 1
                else:
                    outside_all += 1
                out_f = QgsFeature(unmatched_building.fields())
                out_f.setGeometry(feat.geometry())
                out_f.setAttributes(feat.attributes() + [
                    code8, landed_in or "",
                    code8_to_match_id.get(code8),
                    code8_to_match_id.get(landed_in) if landed_in else None,
                ])
                unmatched_building_feats.append(out_f)

            if total_buildings > 0 and processed % 500 == 0:
                feedback.setProgress(50 + int(40.0 * processed / total_buildings))

        matched_building.dataProvider().addFeatures(matched_building_feats)
        unmatched_building.dataProvider().addFeatures(unmatched_building_feats)
        matched_building.updateExtents()
        unmatched_building.updateExtents()

        feedback.pushInfo(self.tr(
            f"Building points -- inside the barangay their geocode names: "
            f"{len(matched_building_feats)}, outside it: {len(unmatched_building_feats)}"
        ))
        if unmatched_building_feats:
            feedback.pushInfo(self.tr(
                f"  Of those outside -- {wrong_barangay} sit inside a different barangay "
                f"(its code is in the in_geocode column), {outside_all} fall outside every "
                f"LGU barangay, {blank_code} have no geocode to check against."
            ))
        if foreign_lgu:
            feedback.pushInfo(self.tr(
                f"  {foreign_lgu} building point(s) carry a geocode naming a barangay from a "
                f"different LGU entirely (not present in either this run's PSA or LGU layer) and "
                f"don't geographically fall inside this LGU either -- excluded from both outputs "
                f"as not relevant to this comparison."
            ))
        feedback.setProgress(90)

        # Only load layers that actually contain features -- an empty
        # matched/unmatched group is common (e.g. every barangay matched)
        # and would just clutter the Layers panel with nothing to show.
        #
        # The two Building Point layers are the exception: both are always
        # loaded, empty or not. "Building Points Outside LGU Boundary" is the
        # answer to the question this tool is run to ask, so it has to be on
        # the map to be read -- an empty one states "nothing outside", while
        # a missing one is indistinguishable from the tool not having checked.
        always_load = {matched_building.id(), unmatched_building.id()}
        output_layer_ids = [
            lid for lid, has_feats in (
                (matched_psa.id(), matched_psa_feats),
                (matched_lgu.id(), matched_lgu_feats),
                (unmatched_psa.id(), unmatched_psa_feats),
                (unmatched_lgu.id(), unmatched_lgu_feats),
                (matched_building.id(), matched_building_feats),
                (unmatched_building.id(), unmatched_building_feats),
            ) if has_feats or lid in always_load
        ]

        # The review panel needs both Matched layers (and, when present, the
        # Matched and Unmatched Building layers, so the Outside points can be
        # scoped to whichever barangay is under review too). Every output
        # layer above still gets a post processor -- built below, sharing
        # one coordinator -- so that the original PSA/LGU/Building input
        # layers get hidden from the map view regardless of whether a run
        # produces a full Matched set (a run where nothing matched still
        # only loads Unmatched layers).
        have_panel = bool(matched_psa_feats and matched_lgu_feats)
        panel_psa_id = matched_psa.id() if have_panel else None
        panel_lgu_id = matched_lgu.id() if have_panel else None
        panel_building_id = matched_building.id() if have_panel and matched_building_feats else None
        panel_unmatched_building_id = unmatched_building.id() if have_panel else None
        run_processors = _make_run_post_processors(
            (layer_psa.id(), layer_lgu.id(), building_layer.id()),
            output_layer_ids, panel_psa_id, panel_lgu_id, panel_building_id,
            panel_unmatched_building_id,
            group_name="{} PSA - LGU Comparison".format(code_prefix))

        results = {
            'MATCHED_PSA': load_layer(
                matched_psa, name_matched_psa,
                run_processors.get(matched_psa.id())) if matched_psa_feats else None,
            'MATCHED_LGU': load_layer(
                matched_lgu, name_matched_lgu,
                run_processors.get(matched_lgu.id())) if matched_lgu_feats else None,
            'UNMATCHED_PSA': load_layer(
                unmatched_psa, name_unmatched_psa,
                run_processors.get(unmatched_psa.id())) if unmatched_psa_feats else None,
            'UNMATCHED_LGU': load_layer(
                unmatched_lgu, name_unmatched_lgu,
                run_processors.get(unmatched_lgu.id())) if unmatched_lgu_feats else None,
            'MATCHED_BUILDING': load_layer(
                matched_building, "Building Points inside LGU Boundary",
                run_processors.get(matched_building.id())),
            'UNMATCHED_BUILDING': load_layer(
                unmatched_building, "Building Points Outside LGU Boundary",
                run_processors.get(unmatched_building.id())),
        }

        feedback.setProgress(100)
        feedback.pushInfo(self.tr("Finished PSA - LGU Boundary Comparison."))
        return results
