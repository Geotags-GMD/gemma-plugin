import math
import os
import traceback

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QTransform, QIcon
from qgis.PyQt.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QListWidget, QMessageBox, QGroupBox, QCheckBox, QScrollArea,
    QPlainTextEdit, QTextBrowser, QTabWidget, QFrame
)
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsWkbTypes, QgsFeature, QgsGeometry, QgsPoint,
    QgsRectangle, QgsProcessingAlgorithm, QgsProcessing,
    QgsProcessingParameterFeatureSource, QgsProcessingOutputString,
    QgsProcessingFeedback, QgsProcessingContext, QgsApplication
)
from qgis.utils import iface


# =============================================================================
# SHARED CONSTANTS & HELPERS
# =============================================================================

BTN_RUN    = ""
BTN_CANCEL = ""
BTN_EXPORT = ""
BTN_CLEAR  = ""
GRP_STYLE  = "QGroupBox { font-weight:600; margin-top:6px; } QGroupBox::title { subcontrol-origin:margin; left:8px; }"
LOG_STYLE  = "background:#eceff1; font-family:Consolas,monospace; font-size:11px;"

# --------------------------------------------------------------------------
# CRS candidates. v1 listed only the first few; PH municipal / census data is
# very often in a Luzon 1911 or PRS92 *zone* grid, none of which were present.
# Piddig (Ilocos Norte, ~120.8E) falls in Zone III.
#
# Note the ESRI: entries. Neither PRS92 nor Luzon 1911 on a UTM grid has an
# EPSG code - both exist only as ESRI definitions - so an EPSG-only list
# silently misses six real Philippine coordinate systems. Provincial data
# digitized in ArcGIS is routinely in exactly these. The full national set is
# 18 definitions; this list carries all of them plus WGS 84 and Web Mercator.
# --------------------------------------------------------------------------
CRS_CANDIDATES = [
    ("EPSG:4326  -  WGS 84 (Geographic)", "EPSG:4326"),
    ("EPSG:4683  -  PRS92 (Geographic)", "EPSG:4683"),
    ("EPSG:4253  -  Luzon 1911 (Geographic)", "EPSG:4253"),
    ("EPSG:32651 -  WGS 84 / UTM Zone 51N", "EPSG:32651"),
    ("EPSG:32650 -  WGS 84 / UTM Zone 50N", "EPSG:32650"),
    ("EPSG:32652 -  WGS 84 / UTM Zone 52N", "EPSG:32652"),
    ("ESRI:102457 - PRS92 / UTM Zone 51N", "ESRI:102457"),
    ("ESRI:102456 - PRS92 / UTM Zone 50N", "ESRI:102456"),
    ("ESRI:102458 - PRS92 / UTM Zone 52N", "ESRI:102458"),
    ("ESRI:102454 - Luzon 1911 / UTM Zone 51N", "ESRI:102454"),
    ("ESRI:102453 - Luzon 1911 / UTM Zone 50N", "ESRI:102453"),
    ("ESRI:102455 - Luzon 1911 / UTM Zone 52N", "ESRI:102455"),
    ("EPSG:3121  -  PRS92 / Philippines Zone 1", "EPSG:3121"),
    ("EPSG:3122  -  PRS92 / Philippines Zone 2", "EPSG:3122"),
    ("EPSG:3123  -  PRS92 / Philippines Zone 3", "EPSG:3123"),
    ("EPSG:3124  -  PRS92 / Philippines Zone 4", "EPSG:3124"),
    ("EPSG:3125  -  PRS92 / Philippines Zone 5", "EPSG:3125"),
    ("EPSG:25391 -  Luzon 1911 / Philippines Zone I", "EPSG:25391"),
    ("EPSG:25392 -  Luzon 1911 / Philippines Zone II", "EPSG:25392"),
    ("EPSG:25393 -  Luzon 1911 / Philippines Zone III", "EPSG:25393"),
    ("EPSG:25394 -  Luzon 1911 / Philippines Zone IV", "EPSG:25394"),
    ("EPSG:25395 -  Luzon 1911 / Philippines Zone V", "EPSG:25395"),
    ("EPSG:3857  -  WGS 84 / Web Mercator", "EPSG:3857"),
]

# Target CRS offered for the affine georeferencing output
FIT_TARGETS = [
    ("EPSG:32651 -  WGS 84 / UTM Zone 51N  (recommended)", "EPSG:32651"),
    ("EPSG:32650 -  WGS 84 / UTM Zone 50N  (Palawan)", "EPSG:32650"),
    ("EPSG:32652 -  WGS 84 / UTM Zone 52N  (far east)", "EPSG:32652"),
    ("ESRI:102457 - PRS92 / UTM Zone 51N  (PRS92 in metres)", "ESRI:102457"),
    ("EPSG:3123  -  PRS92 / Philippines Zone 3", "EPSG:3123"),
    ("EPSG:4326  -  WGS 84 (Geographic)", "EPSG:4326"),
]

BASEMAPS = [
    ("Google Satellite",
     "type=xyz&url=https://mt1.google.com/vt/lyrs%3Ds%26x%3D%7Bx%7D"
     "%26y%3D%7By%7D%26z%3D%7Bz%7D&zmax=20&zmin=0"),
    ("Google Hybrid (satellite + labels)",
     "type=xyz&url=https://mt1.google.com/vt/lyrs%3Dy%26x%3D%7Bx%7D"
     "%26y%3D%7By%7D%26z%3D%7Bz%7D&zmax=20&zmin=0"),
]

# Generous bounding box of the Philippines, in degrees
PH_BBOX = QgsRectangle(116.0, 4.0, 127.5, 21.5)


# --------------------------------------------------------------------------
# Small linear-algebra helper: solve a 3x3 system (no numpy dependency)
# --------------------------------------------------------------------------
def _solve3(a, b):
    m = [list(row) + [rhs] for row, rhs in zip(a, b)]
    n = 3
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(m[r][i]))
        if abs(m[p][i]) < 1e-12:
            raise ValueError(
                "Control points are collinear - the normal equations are\n"
                "singular, so rotation and scale cannot be separated. The\n"
                "points must span two dimensions.")
        m[i], m[p] = m[p], m[i]
        pv = m[i][i]
        m[i] = [v / pv for v in m[i]]
        for r in range(n):
            if r != i and m[r][i] != 0.0:
                f = m[r][i]
                m[r] = [u - f * v for u, v in zip(m[r], m[i])]
    return [m[i][3] for i in range(n)]


def fit_affine(src_pts, dst_pts):
    """Least-squares 6-parameter affine mapping src (x, y) -> dst (X, Y).

    Returns ((a, b, c), (d, e, f), residuals) where
        X = a*x + b*y + c
        Y = d*x + e*y + f

    A 6-parameter affine is used rather than a 4-parameter similarity because
    digitized and scanned sources routinely carry a small X-vs-Y scale
    difference that a similarity transform cannot absorb.
    """
    n = len(src_pts)
    if n < 3:
        raise ValueError(
            "Only %d usable control point(s); a 6-parameter affine needs at\n"
            "least 3. Rows are skipped when the longitude/latitude columns are\n"
            "empty, zero, or fall outside 116.0-127.5E / 4.0-21.5N." % n)

    # Centre the data for numerical conditioning
    xm = sum(p[0] for p in src_pts) / n
    ym = sum(p[1] for p in src_pts) / n

    sxx = sxy = syy = sx = sy = 0.0
    for (x, y) in src_pts:
        dx, dy = x - xm, y - ym
        sxx += dx * dx
        sxy += dx * dy
        syy += dy * dy
        sx += dx
        sy += dy
    ata = [[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, float(n)]]

    coeffs = []
    for k in (0, 1):
        atb = [0.0, 0.0, 0.0]
        for (x, y), d in zip(src_pts, dst_pts):
            dx, dy = x - xm, y - ym
            atb[0] += dx * d[k]
            atb[1] += dy * d[k]
            atb[2] += d[k]
        p, q, r = _solve3(ata, atb)
        coeffs.append((p, q, r - p * xm - q * ym))

    (a, b, c), (d, e, f) = coeffs
    residuals = []
    for (x, y), dst in zip(src_pts, dst_pts):
        residuals.append(
            ((a * x + b * y + c - dst[0]) ** 2
             + (d * x + e * y + f - dst[1]) ** 2) ** 0.5)
    return (a, b, c), (d, e, f), residuals


# --------------------------------------------------------------------------
# Attribute-column detection
# --------------------------------------------------------------------------
def _pick_field(fields, exact, contains, exclude=()):
    names = [f.name() for f in fields]
    for want in exact:
        for n in names:
            if n.upper() == want and n not in exclude:
                return n
    for want in contains:
        for n in names:
            if want in n.upper() and n not in exclude:
                return n
    return None


def detect_control_fields(layer):
    """Find paired local-X/Y and Longitude/Latitude columns, if present."""
    fields = layer.fields()
    lon = _pick_field(fields, ("LONGITUDE", "LONGITUDEI", "LONG", "LON"),
                      ("LONGITUD", "LON"))
    lat = _pick_field(fields, ("LATITUDE", "LATITUDEI", "LAT"),
                      ("LATITUD", "LAT"))
    used = tuple(v for v in (lon, lat) if v)
    lx = _pick_field(fields, ("XI", "X", "XCOORD", "X_COORD", "EASTING", "POINT_X"),
                     ("EASTING",), exclude=used)
    ly = _pick_field(fields, ("YI", "Y", "YCOORD", "Y_COORD", "NORTHING", "POINT_Y"),
                     ("NORTHING",), exclude=used)
    return lx, ly, lon, lat


# --------------------------------------------------------------------------
# Coordinate diagnosis
# --------------------------------------------------------------------------
def diagnose_extent(ext):
    """Classify a raw extent. Returns (kind, report text)."""
    xmin, ymin = ext.xMinimum(), ext.yMinimum()
    xmax, ymax = ext.xMaximum(), ext.yMaximum()
    big = max(abs(xmin), abs(xmax), abs(ymin), abs(ymax))

    if big <= 180.0 and abs(ymin) <= 90.0 and abs(ymax) <= 90.0:
        kind = "geographic"
    elif 1.2e7 <= abs(xmin) <= 1.45e7:
        kind = "webmercator"
    elif 1.0e5 <= xmin and xmax <= 1.0e6 and 3.0e5 <= ymin and ymax <= 2.7e6:
        kind = "projected"
    else:
        kind = "local"

    num = "%.6f" if kind == "geographic" else "%.2f"
    head = (("EXTENT:\n"
             "  X: " + num + " to " + num + "  (width:  " + num + ")\n"
             "  Y: " + num + " to " + num + "  (height: " + num + ")\n\n"
             "-------------------------------------------------------------\n\n")
            % (xmin, xmax, xmax - xmin, ymin, ymax, ymax - ymin))

    if kind == "geographic":
        return kind, head + (
            "DIAGNOSIS: Geographic Coordinates (degrees)\n"
            "Coordinates are decimal degrees (longitude/latitude).\n\n"
            "Candidate Datums:\n"
            "  - EPSG:4326 (WGS 84)     : GPS / satellite default (most common)\n"
            "  - EPSG:4683 (PRS92)      : Philippine national standard\n"
            "  - EPSG:4253 (Luzon 1911) : Historical NAMRIA maps\n\n"
            "Note: Datum shift between WGS 84 and PRS92 is ~100-200 m.")

    if kind == "webmercator":
        return kind, head + (
            "DIAGNOSIS: Web Mercator (EPSG:3857)\n"
            "Coordinates match WGS 84 / Pseudo-Mercator in metres.")

    if kind == "projected":
        return kind, head + (
            "DIAGNOSIS: Projected Grid (metres)\n"
            "Coordinates match Philippine grid ranges (UTM / PTM).\n"
            "Specific zone/datum needs to be identified.")

    return kind, head + (
        "DIAGNOSIS: Local / Non-georeferenced Grid\n"
        "Coordinates do not match any standard geographic or projected system.\n"
        "  - Min X: %.2f | Min Y: %.2f\n"
        "  - Size : %.2f x %.2f units\n"
        "Origin: Digitized in local arbitrary/CAD units without georeferencing."
        % (xmin, ymin, xmax - xmin, ymax - ymin))


def scan_candidates(ext):
    """Try every candidate CRS against an extent.

    Returns (hits, misses). A hit means that, read as that CRS, the layer lands
    inside the Philippines. Nothing is modified - the extent is only
    transformed - so this is safe to run automatically.

    Each hit records the longitude that candidate implies for the layer's
    centre. That is the only figure here that can settle anything, and it
    cannot be settled by the program: these grids differ only in where they
    start counting, so re-reading the same numbers under a different zone
    simply slides the layer along with the zone. Every zone therefore looks
    self-consistent - it lands in the country, and inside its own declared
    area of use. Only someone who knows roughly where the municipality is can
    pick the matching line, which is why the implied longitude is reported
    rather than a guess.
    """
    if ext.isEmpty():
        return [], []
    cx = ext.xMinimum() + ext.width() / 2.0
    cy = ext.yMinimum() + ext.height() / 2.0
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")

    hits, misses = [], []
    for idx, (label, code) in enumerate(CRS_CANDIDATES):
        crs = QgsCoordinateReferenceSystem(code)
        if not crs.isValid():
            continue
        try:
            xform = QgsCoordinateTransform(crs, wgs84, QgsProject.instance())
            pt = xform.transform(cx, cy)
        except Exception:
            misses.append((label, "could not be converted"))
            continue
        if not PH_BBOX.contains(pt):
            misses.append((label, "lands outside the Philippines"))
            continue

        hits.append({"label": label, "code": code, "pt": pt,
                     "lon": pt.x(), "lat": pt.y(), "order": idx})

    # Ordered west to east, so the reader can scan for the longitude that
    # matches where they know the municipality to be.
    hits.sort(key=lambda h: (h["lon"], h["order"]))
    return hits, misses


# =============================================================================
# MAIN WORKING TAB
# =============================================================================
class ProjectionFinderTab(QWidget):
    """Layer selector, CRS candidate testing, affine georeferencing and report."""

    def __init__(self):
        super().__init__()
        self.basemap_layer = None
        self._pending_crs = None
        self._original_crs = {}
        self._build()

        prj = QgsProject.instance()
        prj.layersAdded.connect(self._refresh_layers_keep_selection)
        prj.layersRemoved.connect(self._refresh_layers_keep_selection)

    # ---------------- construction ----------------
    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(8)

        # -- LEFT: CONTROLS ------------------------------------------------
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)

        grp_layer = QGroupBox("Step 1 - Input Layer")
        grp_layer.setStyleSheet(GRP_STYLE)
        gl = QVBoxLayout(grp_layer)
        self.layer_combo = QComboBox()
        self.layer_combo.setToolTip("Vector layer with an unknown or missing CRS.")
        self._populate_layers()
        gl.addWidget(self.layer_combo)
        self.diagnose_btn = QPushButton("Check Coordinates")
        self.diagnose_btn.setFixedHeight(32)
        self.diagnose_btn.setStyleSheet(BTN_RUN)
        self.diagnose_btn.setToolTip(
            "Read the layer's numbers and attribute table, then say what is wrong\n"
            "with it and which option fixes it.")
        self.diagnose_btn.clicked.connect(self.diagnose)
        gl.addWidget(self.diagnose_btn)
        ll.addWidget(grp_layer)

        grp_base = QGroupBox("Step 2 - Reference Basemap")
        grp_base.setStyleSheet(GRP_STYLE)
        bl = QVBoxLayout(grp_base)
        self.basemap_check = QCheckBox("Add basemap when previewing")
        self.basemap_check.setChecked(True)
        bl.addWidget(self.basemap_check)
        self.basemap_combo = QComboBox()
        for name, uri in BASEMAPS:
            self.basemap_combo.addItem(name, uri)
        bl.addWidget(self.basemap_combo)
        ll.addWidget(grp_base)

        # Options A and B are alternative routes, not sequential steps: A resolves
        # a CRS that exists, B builds one that never did. Both act on the selected
        # layer through its own edit session - nothing reaches disk until the user
        # commits via QGIS's own Toggle Editing (Save Edits / Discard Edits).
        grp_crs = QGroupBox("Option A - Identify a Known CRS")
        grp_crs.setStyleSheet(GRP_STYLE)
        cl = QVBoxLayout(grp_crs)
        hint_a = QLabel("Use when Check Coordinates finds a real coordinate system.")
        hint_a.setStyleSheet("color:#455a64; font-size:11px;")
        hint_a.setWordWrap(True)
        cl.addWidget(hint_a)
        self.crs_list = QListWidget()
        self.crs_list.setMinimumHeight(110)
        self.crs_list.setAlternatingRowColors(True)
        self.crs_list.setStyleSheet(
            "QListWidget { border: 1px solid #b0bec5; outline: 0; }"
            "QListWidget::item { padding: 2px 4px; }")
        for label, code in CRS_CANDIDATES:
            self.crs_list.addItem(label)
        self.crs_list.setCurrentRow(0)
        cl.addWidget(self.crs_list, stretch=1)
        self.auto_btn = QPushButton("Detect Known CRS")
        self.auto_btn.setFixedHeight(32)
        self.auto_btn.setStyleSheet(BTN_RUN)
        self.auto_btn.setToolTip(
            "Try every known Philippine coordinate system and report which ones\n"
            "could place this layer inside the country.")
        self.auto_btn.clicked.connect(self.auto_detect)
        cl.addWidget(self.auto_btn)
        crow = QHBoxLayout()
        self.preview_btn = QPushButton("Preview This CRS")
        self.preview_btn.setFixedHeight(28)
        self.preview_btn.clicked.connect(self.preview_crs)
        crow.addWidget(self.preview_btn)
        self.custom_btn = QPushButton("Custom EPSG...")
        self.custom_btn.setFixedHeight(28)
        self.custom_btn.clicked.connect(self.enter_custom_crs)
        crow.addWidget(self.custom_btn)
        cl.addLayout(crow)

        aline = QFrame()
        aline.setFrameShape(QFrame.HLine)
        aline.setStyleSheet("color:#cfd8dc;")
        cl.addWidget(aline)

        arow = QHBoxLayout()
        self.assign_btn = QPushButton("Confirm && Assign CRS")
        self.assign_btn.setFixedHeight(32)
        self.assign_btn.setStyleSheet(BTN_EXPORT)
        self.assign_btn.setEnabled(False)
        self.assign_btn.setToolTip(
            "Commit the previewed CRS and optionally write the .prj sidecar.")
        self.assign_btn.clicked.connect(self.assign_crs)
        arow.addWidget(self.assign_btn)
        self.revert_btn = QPushButton("Revert CRS")
        self.revert_btn.setFixedHeight(32)
        self.revert_btn.setStyleSheet(BTN_CANCEL)
        self.revert_btn.setToolTip(
            "Restore the CRS this layer had when the dialog opened.")
        self.revert_btn.clicked.connect(self.revert_crs)
        arow.addWidget(self.revert_btn)
        cl.addLayout(arow)
        ll.addWidget(grp_crs, stretch=1)

        grp_fit = QGroupBox("Option B - Georeference a Local Grid")
        grp_fit.setStyleSheet(GRP_STYLE)
        fl = QVBoxLayout(grp_fit)
        hint = QLabel("Use when Check Coordinates says the layer was never placed on\n"
                      "the map. Works out where it belongs from longitude/latitude\n"
                      "columns in the attribute table, then edits this layer's geometry\n"
                      "directly in an edit session. Nothing reaches disk until you\n"
                      "Save Edits (or Discard Edits) via Toggle Editing.")
        hint.setStyleSheet("color:#455a64; font-size:11px;")
        fl.addWidget(hint)
        frow = QHBoxLayout()
        frow.addWidget(QLabel("Output CRS:"))
        self.fit_combo = QComboBox()
        for label, code in FIT_TARGETS:
            self.fit_combo.addItem(label, code)
        frow.addWidget(self.fit_combo, 1)
        fl.addLayout(frow)
        self.check_fit_btn = QPushButton("Check Control Points")
        self.check_fit_btn.setFixedHeight(32)
        self.check_fit_btn.setStyleSheet(BTN_RUN)
        self.check_fit_btn.setToolTip(
            "Read-only: fits the transform and reports its RMS error. Writes nothing.")
        self.check_fit_btn.clicked.connect(self.check_fit)
        fl.addWidget(self.check_fit_btn)
        self.georef_btn = QPushButton("Georeference This Layer")
        self.georef_btn.setFixedHeight(32)
        self.georef_btn.setStyleSheet(BTN_EXPORT)
        self.georef_btn.setToolTip(
            "Apply the fitted transform to this layer's geometry in an edit "
            "session. Use Toggle Editing's Save Edits / Discard Edits to keep "
            "or undo it.")
        self.georef_btn.clicked.connect(self.georeference)
        fl.addWidget(self.georef_btn)
        ll.addWidget(grp_fit)

        # The left column packs two full option groups plus the layer/basemap
        # controls - taller than it looks, and taller than many laptop screens
        # once the dialog is shrunk. A scroll area lets the window itself go
        # short without clipping Option B's buttons off the bottom.
        left_scroll = QScrollArea()
        left_scroll.setWidget(left)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setFixedWidth(376)
        root.addWidget(left_scroll)

        # -- RIGHT: REPORT -------------------------------------------------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)

        self.summary = QLabel("No layer diagnosed yet.")
        self.summary.setStyleSheet("font-size:13px; font-weight:600; color:#37474f;")
        rl.addWidget(self.summary)

        grp_rep = QGroupBox("Logs")
        grp_rep.setStyleSheet(GRP_STYLE)
        pl = QVBoxLayout(grp_rep)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setStyleSheet(LOG_STYLE)
        self.report.setPlainText(
            "Ready.\n\n"
            "1. Select a vector layer in Step 1.\n"
            "2. Click 'Check Coordinates' to inspect layer extent and coordinate type.\n\n"
            "Options:\n"
            "  - Option A: Identify and preview known Philippine CRS candidates.\n"
            "  - Option B: Georeference local grids using attribute table control points.")
        pl.addWidget(self.report)
        rl.addWidget(grp_rep, stretch=1)

        brow = QHBoxLayout()
        brow.addStretch(1)
        self.clear_btn = QPushButton("Clear Logs")
        self.clear_btn.setFixedHeight(28)
        self.clear_btn.setStyleSheet(BTN_CLEAR)
        self.clear_btn.clicked.connect(self.clear_report)
        brow.addWidget(self.clear_btn)
        rl.addLayout(brow)

        root.addWidget(right, stretch=1)

    # ---------------- helpers ----------------
    def _populate_layers(self):
        """Fill the combo with vector layers, storing layer IDs (not pointers)."""
        self.layer_combo.clear()
        vector_layers = [l for l in QgsProject.instance().mapLayers().values()
                         if isinstance(l, QgsVectorLayer)]
        if not vector_layers:
            self.layer_combo.addItem("No vector layers loaded", None)
            return
        for lyr in sorted(vector_layers, key=lambda l: l.name().lower()):
            self.layer_combo.addItem(lyr.name(), lyr.id())

    def _refresh_layers_keep_selection(self, *args):
        current = self.layer_combo.currentData()
        self._populate_layers()
        if current is not None:
            idx = self.layer_combo.findData(current)
            if idx >= 0:
                self.layer_combo.setCurrentIndex(idx)

    def _get_selected_layer(self):
        """Resolve the combo's stored ID through QgsProject, so a removed layer
        can never be acted on through a stale pointer."""
        lyr_id = self.layer_combo.currentData()
        lyr = QgsProject.instance().mapLayer(lyr_id) if lyr_id else None
        if lyr is None:
            QMessageBox.warning(self, "No Layer",
                                "Pick a vector layer in Step 1 first.")
            return None
        if lyr.id() not in self._original_crs:
            self._original_crs[lyr.id()] = QgsCoordinateReferenceSystem(lyr.crs())
        return lyr

    def _log(self, text, summary=None):
        self.report.setPlainText(text)
        if summary is not None:
            self.summary.setText(summary)

    def clear_report(self):
        self.report.clear()
        self.summary.setText("No layer diagnosed yet.")

    def _ensure_basemap(self):
        if not self.basemap_check.isChecked():
            return
        name = self.basemap_combo.currentText()
        uri = self.basemap_combo.currentData()
        if self.basemap_layer is not None:
            try:
                if self.basemap_layer.name() == name:
                    return
            except RuntimeError:      # underlying layer was deleted
                self.basemap_layer = None
        rlayer = QgsRasterLayer(uri, name, "wms")
        if not rlayer.isValid():
            QMessageBox.warning(
                self, "Basemap Error",
                "Could not load '%s'. Check your internet connection or proxy "
                "settings." % name)
            return
        # Add WITHOUT auto-placing, then append to the bottom of the layer tree so
        # the imagery sits *under* the layer being checked instead of hiding it.
        QgsProject.instance().addMapLayer(rlayer, False)
        QgsProject.instance().layerTreeRoot().addLayer(rlayer)
        self.basemap_layer = rlayer

    def _zoom_to(self, layer):
        canvas = iface.mapCanvas()
        dest = canvas.mapSettings().destinationCrs()
        ext = layer.extent()
        if layer.crs().isValid() and dest.isValid() and layer.crs() != dest:
            try:
                xform = QgsCoordinateTransform(layer.crs(), dest, QgsProject.instance())
                ext = xform.transformBoundingBox(ext)
            except Exception:
                pass
        canvas.setExtent(ext)
        canvas.refresh()

    # ---------------- Step 1 ----------------
    def diagnose(self):
        layer = self._get_selected_layer()
        if layer is None:
            return
        kind, msg = diagnose_extent(layer.extent())
        lx, ly, lon, lat = detect_control_fields(layer)
        has_points = all((lx, ly, lon, lat))

        msg += ("\n\n-------------------------------------------------------------\n\n"
                "ATTRIBUTE CONTROL FIELDS:\n"
                "  Local X   : %s\n"
                "  Local Y   : %s\n"
                "  Longitude : %s\n"
                "  Latitude  : %s\n"
                "  Status    : %s\n\n"
                "-------------------------------------------------------------\n\n"
                % (lx or "NOT FOUND",
                   ly or "NOT FOUND",
                   lon or "NOT FOUND",
                   lat or "NOT FOUND",
                   "All 4 control fields present (usable for Option B)" if has_points else "Incomplete control fields"))

        msg += self._recommendation(kind, has_points)

        labels = {"geographic": "Longitude / latitude (degrees)",
                  "webmercator": "Web map metres",
                  "projected": "Philippine grid, in metres",
                  "local": "Never placed on the map"}
        self._log(msg, "%s  -  %s" % (layer.name(), labels.get(kind, kind)))

    def _recommendation(self, kind, has_points):
        """Provide concise recommended CRS and next operational step."""
        if kind == "webmercator":
            return ("RECOMMENDED CRS:\n"
                    "  EPSG:3857 - WGS 84 / Web Mercator\n\n"
                    "NEXT STEP:\n"
                    "  Option A -> Select EPSG:3857 -> Click 'Preview This CRS'.")

        if kind == "geographic":
            return ("RECOMMENDED CRS:\n"
                    "  EPSG:4326 - WGS 84 (recommended default)\n"
                    "  Alternatives: EPSG:4683 (PRS92), EPSG:4253 (Luzon 1911)\n\n"
                    "NEXT STEP:\n"
                    "  Option A -> Select EPSG:4326 -> Click 'Preview This CRS'.")

        if kind == "local":
            if has_points:
                return ("RECOMMENDED ACTION:\n"
                        "  No standard CRS fits raw coordinates. Control fields detected.\n"
                        "  Next: Option B -> Click 'Check Control Points' to fit affine transform.")
            return ("RECOMMENDED ACTION:\n"
                    "  No standard CRS fits raw coordinates and control fields are missing.\n"
                    "  Next: Provide .prj/control points or georeference manually (Raster > Georeferencer).")

        return ("RECOMMENDED ACTION:\n"
                "  Projected coordinates detected.\n"
                "  Next: Option A -> Click 'Detect Known CRS' to test %d candidate zones."
                % len(CRS_CANDIDATES))

    # ---------------- Option A: identify a known CRS ----------------
    def _reference_longitude(self, exclude_id=None):
        """Median centre longitude of the other georeferenced layers in the project.

        This is the only evidence available for choosing between zone grids.
        The file cannot say which zone it is - every zone reads as
        self-consistent - but if the project already holds correctly placed
        layers for the same area, the right zone is the one that puts this
        layer near them. Returns None when there is nothing to compare with.
        """
        lons = []
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        for lyr in QgsProject.instance().mapLayers().values():
            if not isinstance(lyr, QgsVectorLayer):
                continue                       # basemaps carry no useful extent
            if exclude_id and lyr.id() == exclude_id:
                continue
            crs = lyr.crs()
            ext = lyr.extent()
            if not crs.isValid() or ext.isEmpty():
                continue
            try:
                box = QgsCoordinateTransform(
                    crs, wgs84, QgsProject.instance()).transformBoundingBox(ext)
            except Exception:
                continue
            cx = box.xMinimum() + box.width() / 2.0
            cy = box.yMinimum() + box.height() / 2.0
            # Ignore world-wide or non-Philippine layers: they say nothing
            # about which zone this municipality sits in.
            if box.width() > 12.0:
                continue
            if not (116.0 <= cx <= 127.5 and 4.0 <= cy <= 21.5):
                continue
            lons.append(cx)
        if not lons:
            return None
        lons.sort()
        return lons[len(lons) // 2]

    def auto_detect(self):
        layer = self._get_selected_layer()
        if layer is None:
            return
        ext = layer.extent()
        if ext.isEmpty():
            self._log("Layer has no geometries to test.")
            return

        hits, misses = scan_candidates(ext)
        total = len(CRS_CANDIDATES)
        if hits:
            ref_lon = self._reference_longitude(exclude_id=layer.id())
            if ref_lon is not None:
                best = min(hits, key=lambda h: (round(abs(h["lon"] - ref_lon), 2),
                                                h["order"]))
                basis = "Nearest to existing project layers (%.2f°E)" % ref_lon
            else:
                best = next((h for h in hits if h["code"] == "EPSG:32651"), hits[0])
                basis = "Standard nationwide default (UTM Zone 51N)"

            out = ("DETECT KNOWN CRS:\n"
                   "Tested: %d | Candidate Matches: %d | Outside PH: %d\n\n"
                   "Candidate Zones (Implied Longitude):\n" % (total, len(hits), len(misses)))
            for h in hits:
                out += "  %s %7.2f°E   %s\n" % (
                    "->" if h is best else "  ", h["lon"], h["label"])
            out += ("\nSuggested Candidate: %s\n"
                    "Basis: %s\n\n"
                    "Reference: Palawan ~117°E | Manila ~121°E | Cebu ~124°E | Davao ~125°E\n"
                    "Next: Select candidate -> 'Preview This CRS' -> verify against basemap."
                    % (best["label"], basis))
            summary = "%s  -  %d of %d possible; suggested %s" % (
                layer.name(), len(hits), total, best["code"])
        else:
            out = ("DETECT KNOWN CRS:\n"
                   "Tested: %d | Matches: 0 (All place layer outside PH).\n\n"
                   "Status: No standard Philippine CRS fits this layer.\n"
                   "Next: Check Option B (Control Points) if attribute coordinates exist." % total)
            summary = "%s  -  no known system fits" % layer.name()
        self._log(out, summary)

    def preview_crs(self):
        layer = self._get_selected_layer()
        if layer is None:
            return
        row = self.crs_list.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No CRS Selected",
                                "Select a CRS candidate in the Option A list.")
            return
        label, code = CRS_CANDIDATES[row]
        self._apply_preview(layer, code, label)

    def enter_custom_crs(self):
        layer = self._get_selected_layer()
        if layer is None:
            return
        from qgis.gui import QgsProjectionSelectionDialog
        dlg = QgsProjectionSelectionDialog(self)
        if dlg.exec_():
            crs = dlg.crs()
            if crs.isValid():
                ident = crs.authid() or crs.description()
                self._apply_preview(layer, crs.authid() or crs.toWkt(),
                                    ident + " (custom)")

    def _apply_preview(self, layer, code, label):
        crs = QgsCoordinateReferenceSystem(code)
        if not crs.isValid():
            QMessageBox.critical(self, "Invalid CRS",
                                 "'%s' is not a recognized CRS." % code)
            return

        # Set CRS only - this labels the existing coordinates, it does not move them
        layer.setCrs(crs)
        layer.triggerRepaint()
        self._ensure_basemap()
        self._zoom_to(layer)

        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        ext = layer.extent()
        centre_txt = ""
        try:
            xform = QgsCoordinateTransform(crs, wgs84, QgsProject.instance())
            pt = xform.transform(ext.xMinimum() + ext.width() / 2.0,
                                 ext.yMinimum() + ext.height() / 2.0)
            inside = ("inside the PH bounding box" if PH_BBOX.contains(pt)
                      else "OUTSIDE the PH bounding box - wrong CRS")
            centre_txt = ("\nLayer centre: %.4fE %.4fN  (%s)\n"
                          % (pt.x(), pt.y(), inside))
        except Exception:
            pass

        self._pending_crs = crs
        self.assign_btn.setEnabled(True)
        self._log("PREVIEW: %s\n"
                  "Status: In-memory preview active (no disk changes).%s\n\n"
                  "Verification Guide:\n"
                  "  - Aligned                  : Correct CRS.\n"
                  "  - Offset ~100-200 m        : Correct zone, different datum (test PRS92/Luzon variants).\n"
                  "  - Offset by kilometers     : Wrong zone.\n"
                  "  - Wrong region / scale off : Incompatible grid.\n\n"
                  "Next Steps:\n"
                  "  - If aligned   -> Click 'Confirm & Assign CRS'\n"
                  "  - If misaligned -> Select another candidate and click 'Preview This CRS'"
                  % (label, centre_txt),
                  "%s  -  previewing %s" % (layer.name(), crs.authid() or label))

    # ---------------- Option B: georeference a local grid ----------------
    def _gather_control_points(self, layer, target_crs):
        lx, ly, lon, lat = detect_control_fields(layer)
        if not all((lx, ly, lon, lat)):
            raise ValueError(
                "Missing required control point columns in attribute table.\n\n"
                "Detected Columns:\n"
                "  Local X   : %s\n"
                "  Local Y   : %s\n"
                "  Longitude : %s\n"
                "  Latitude  : %s\n\n"
                "Action: Table requires both local coordinates (X/Y) and geographic coordinates (Lon/Lat)."
                % (lx or "NOT FOUND", ly or "NOT FOUND",
                   lon or "NOT FOUND", lat or "NOT FOUND"))

        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        xform = QgsCoordinateTransform(wgs84, target_crs, QgsProject.instance())

        src, dst = [], []
        for feat in layer.getFeatures():
            try:
                x = float(feat[lx])
                y = float(feat[ly])
                lo = float(feat[lon])
                la = float(feat[lat])
            except (TypeError, ValueError, KeyError):
                continue
            if not (116.0 <= lo <= 127.5 and 4.0 <= la <= 21.5):
                continue
            if x == 0.0 and y == 0.0:
                continue
            pt = xform.transform(lo, la)
            src.append((x, y))
            dst.append((pt.x(), pt.y()))
        return (lx, ly, lon, lat), src, dst

    def _fit_report(self, layer, target_crs):
        names, src, dst = self._gather_control_points(layer, target_crs)
        fx, fy, res = fit_affine(src, dst)
        n = len(res)

        # When the output CRS is in degrees, convert errors and scales to metres
        # so the numbers below always mean the same thing to the reader. A degree
        # of longitude is shorter than a degree of latitude, by cos(latitude), so
        # the two axes need separate factors.
        if target_crs.isGeographic():
            mean_lat = sum(p[1] for p in dst) / len(dst)
            mx = 111320.0 * math.cos(math.radians(mean_lat))
            my = 110570.0
        else:
            mx = my = 1.0

        errs = []
        for (x, y), (want_x, want_y) in zip(src, dst):
            ex = (fx[0] * x + fx[1] * y + fx[2] - want_x) * mx
            ey = (fy[0] * x + fy[1] * y + fy[2] - want_y) * my
            errs.append((ex * ex + ey * ey) ** 0.5)
        rms_m = (sum(e * e for e in errs) / len(errs)) ** 0.5
        max_m = max(errs)

        scale_x = ((fx[0] * mx) ** 2 + (fy[0] * my) ** 2) ** 0.5
        scale_y = ((fx[1] * mx) ** 2 + (fy[1] * my) ** 2) ** 0.5
        rot = math.degrees(math.atan2(fy[0], fx[0]))
        aniso = (scale_x / scale_y - 1.0) * 100.0 if scale_y else 0.0
        unit = "deg" if target_crs.isGeographic() else "m"

        if rms_m < 5.0:
            grade = "EXCELLENT"
            eval_text = "EXCELLENT (< 5 m error) - High accuracy fit."
            next_action = "Click 'Georeference This Layer', then Save Edits via Toggle Editing."
        elif rms_m < 50.0:
            grade = "ACCEPTABLE"
            eval_text = "ACCEPTABLE (< 50 m error) - Suitable for general mapping; verify against basemap."
            next_action = "Click 'Georeference This Layer', then Save Edits via Toggle Editing."
        else:
            grade = "POOR"
            eval_text = "POOR (>= 50 m error) - Large residuals. Check if columns match identical features."
            next_action = "Review attribute fields (%s/%s and %s/%s) before using." % (
                names[0], names[1], names[2], names[3])

        txt = ("AFFINE TRANSFORM FIT REPORT:\n"
               "  Control Points : %d\n"
               "  Source Fields  : %s, %s (Local X, Y)\n"
               "  Target Fields  : %s, %s (Longitude, Latitude)\n"
               "  Target CRS     : %s\n\n"
               "Fit Quality:\n"
               "  RMS Error      : %.2f m\n"
               "  Max Error      : %.2f m\n"
               "  Assessment     : %s\n\n"
               "Parameters:\n"
               "  Scale X / Y    : %.6f / %.6f m/unit (anisotropy: %.3f%%)\n"
               "  Rotation       : %.4f°\n"
               "  Matrix (%s):\n"
               "    E = %.8f*x + %.8f*y + %.3f\n"
               "    N = %.8f*x + %.8f*y + %.3f\n\n"
               "Next Action:\n"
               "  %s"
               % (n, names[0], names[1], names[2], names[3], target_crs.authid(),
                  rms_m, max_m, eval_text,
                  scale_x, scale_y, aniso, rot, unit,
                  fx[0], fx[1], fx[2], fy[0], fy[1], fy[2],
                  next_action))
        summary = "%s  -  %s fit (RMS: %.2f m, %d pts)" % (layer.name(), grade, rms_m, n)
        return fx, fy, txt, summary

    def check_fit(self):
        layer = self._get_selected_layer()
        if layer is None:
            return
        target = QgsCoordinateReferenceSystem(self.fit_combo.currentData())
        try:
            _, _, txt, summary = self._fit_report(layer, target)
        except ValueError as exc:
            self._log("TRANSFORM ERROR:\n%s" % exc,
                      "%s  -  no transform available" % layer.name())
            return
        self._log(txt, summary)

    def georeference(self):
        layer = self._get_selected_layer()
        if layer is None:
            return
        target = QgsCoordinateReferenceSystem(self.fit_combo.currentData())
        try:
            fx, fy, txt, summary = self._fit_report(layer, target)
        except ValueError as exc:
            self._log("TRANSFORM ERROR:\n%s" % exc,
                      "%s  -  no transform available" % layer.name())
            return

        if not layer.startEditing():
            QMessageBox.critical(
                self, "Cannot Edit Layer",
                "'%s' could not be put into edit mode. The data source may be "
                "read-only or locked by another editor." % layer.name())
            return

        # QTransform(m11, m12, m21, m22, dx, dy) maps
        #   x' = m11*x + m21*y + dx        y' = m12*x + m22*y + dy
        qt = QTransform(fx[0], fy[0], fx[1], fy[1], fx[2], fy[2])

        layer.beginEditCommand("Georeference (Option B)")
        changed = 0
        skipped = 0
        for feat in list(layer.getFeatures()):
            g = QgsGeometry(feat.geometry())
            if g.isNull() or g.isEmpty():
                skipped += 1
                continue
            try:
                g.transform(qt)
            except (TypeError, AttributeError):
                g.transformVertices(
                    lambda p: QgsPoint(fx[0] * p.x() + fx[1] * p.y() + fx[2],
                                       fy[0] * p.x() + fy[1] * p.y() + fy[2]))
            layer.changeGeometry(feat.id(), g)
            changed += 1
        layer.setCrs(target)
        layer.endEditCommand()

        layer.triggerRepaint()
        self._ensure_basemap()
        self._zoom_to(layer)

        self._log(
            "GEOREFERENCE APPLIED (edit session - not yet saved):\n"
            "  Layer            : %s\n"
            "  Features Changed : %d\n"
            "  Features Skipped : %d (null/empty geometry)\n"
            "  Output CRS       : %s\n"
            "  Status           : Layer is now in edit mode. Use Toggle Editing's\n"
            "                     Save Edits to keep this, or Discard Edits to put\n"
            "                     the original coordinates back.\n"
            "  Note             : The CRS label itself is not part of the edit\n"
            "                     session - Discard Edits restores the geometry but\n"
            "                     not the CRS. If you discard, also click 'Revert\n"
            "                     CRS' in Option A to restore the original label.\n\n"
            "-------------------------------------------------------------\n\n%s"
            % (layer.name(), changed, skipped, target.authid(), txt),
            "%s  -  georeferenced, edit session open" % layer.name())

    # ---------------- Option A: apply / undo ----------------
    def assign_crs(self):
        layer = self._get_selected_layer()
        if layer is None or self._pending_crs is None:
            QMessageBox.warning(self, "Nothing to Assign",
                                "Preview a CRS in Option A first.")
            return

        layer.setCrs(self._pending_crs)
        layer.triggerRepaint()

        src = layer.source().split("|")[0]
        wrote = ""
        if src.lower().endswith(".shp") and os.path.exists(src):
            answer = QMessageBox.question(
                self, "Write .prj sidecar?",
                "The assignment currently lives only in this QGIS session.\n\n"
                "Write a .prj sidecar so the shapefile carries its CRS on disk?"
                "\n\n%s" % (src[:-4] + ".prj"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                try:
                    with open(src[:-4] + ".prj", "w") as fh:
                        fh.write(self._pending_crs.toWkt(
                            QgsCoordinateReferenceSystem.WKT1_ESRI))
                    wrote = "\n.prj written: %s" % (src[:-4] + ".prj")
                except Exception as exc:
                    wrote = ("\n.prj NOT written (%s) - the assignment will be lost "
                             "when the project closes." % exc)

        QMessageBox.information(
            self, "CRS Assigned",
            "'%s' assigned %s.%s\n\n"
            "This re-labels the existing coordinates; no transformation was "
            "applied. To reproject, use Export > Save Features As with a "
            "different target CRS."
            % (layer.name(), self._pending_crs.authid(), wrote))
        self._log("CRS ASSIGNED:\n"
                  "  Layer     : %s\n"
                  "  CRS       : %s\n"
                  "  Mode      : In-memory coordinate re-labeling (geometry untouched).%s\n\n"
                  "Use 'Revert CRS' to restore prior CRS if needed."
                  % (layer.name(), self._pending_crs.authid(), wrote),
                  "%s  -  assigned %s" % (layer.name(), self._pending_crs.authid()))

    def revert_crs(self):
        layer = self._get_selected_layer()
        if layer is None:
            return
        original = self._original_crs.get(layer.id())
        if original is None:
            self._log("No prior CRS recorded for '%s'." % layer.name())
            return
        layer.setCrs(original)
        layer.triggerRepaint()
        self._zoom_to(layer)
        self._log("CRS REVERTED:\n"
                  "  Layer     : %s\n"
                  "  CRS       : %s (restored to initial session state)\n"
                  "  Note      : Any .prj file on disk was not modified."
                  % (layer.name(), original.authid() or "no CRS"),
                  "%s  -  reverted" % layer.name())


# =============================================================================
# HELP AND INFORMATION TAB
# =============================================================================
class HelpInfoTab(QWidget):
    """Embedded HTML documentation and reference guide for Know Your Projection!."""

    def __init__(self):
        super().__init__()
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.text = QTextBrowser()
        self.text.setReadOnly(True)
        self.text.setOpenExternalLinks(True)
        self.text.setStyleSheet(
            "QTextBrowser { background-color: #ffffff; color: #1f2937; font-size: 12px; border: 1px solid #d1d5db; border-radius: 4px; padding: 8px; }"
        )
        self.text.setHtml("""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1f2937; line-height: 1.5; font-size: 12px;">

          <!-- Header Section -->
          <div style="border-bottom: 2px solid #374151; padding-bottom: 8px; margin-bottom: 14px;">
            <h2 style="margin: 0 0 4px 0; color: #111827; font-size: 17px; font-weight: bold;">
              Know Your Projection!
            </h2>
            <div style="color: #4b5563; font-size: 12px;">
              Coordinate System Diagnosis, Identification and Affine Georeferencing for Philippine Boundary Layers
            </div>
          </div>

          <!-- Non-destructive callout -->
          <div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-left: 4px solid #4b5563; padding: 10px 14px; margin-bottom: 16px;">
            <b style="color: #111827;">Nothing Reaches Disk Without Your Say-So:</b>
            <span style="color: #374151;">
              Diagnosis and preview only read the layer. Assigning a CRS in Option A <b>re-labels</b> the existing coordinates in the current session; it never moves geometry, and nothing reaches disk unless you accept the <i>.prj</i> prompt. <i>Georeference This Layer</i> in Option B edits the layer's geometry directly, but only inside an ordinary QGIS edit session - it stays there until you use Toggle Editing's <b>Save Edits</b> or <b>Discard Edits</b>. Use <b>Revert CRS</b> to undo an in-session CRS assignment (from either option).
            </span>
          </div>

          <!-- Section 1: How to Use -->
          <h3 style="color: #111827; font-size: 14px; font-weight: bold; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; margin-top: 16px; margin-bottom: 10px;">
            How to Use
          </h3>
          <table width="100%" cellpadding="6" cellspacing="0" style="border-collapse: collapse; margin-bottom: 16px; border: 1px solid #e5e7eb; font-size: 11px;">
            <tr style="background-color: #ffffff;">
              <td width="75" style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">Step 1</td>
              <td style="border-bottom: 1px solid #f3f4f6;"><b>Select Input Layer:</b> Choose the vector layer with an unknown or missing CRS, then click <i>Check Coordinates</i>. Read the result before doing anything else - it says what the layer is in, recommends a coordinate system where one can honestly be recommended, and tells you whether Option A or Option B applies.</td>
            </tr>
            <tr style="background-color: #f9fafb;">
              <td style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">Step 2</td>
              <td style="border-bottom: 1px solid #f3f4f6;"><b>Reference Basemap:</b> Leave enabled. Satellite imagery is added at the <i>bottom</i> of the layer tree so it sits under the layer being checked. Hybrid adds place labels, which helps confirm the municipality.</td>
            </tr>
            <tr style="background-color: #ffffff;">
              <td style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">Option A</td>
              <td style="border-bottom: 1px solid #f3f4f6;"><b>Identify a Known CRS.</b> Click <i>Detect Known CRS</i> to try all 23 known Philippine systems and see which ones could place the layer inside the country. Select one and click <i>Preview This CRS</i> to compare against imagery; <i>Custom EPSG</i> opens the full QGIS CRS browser. When it lines up, <i>Confirm &amp; Assign CRS</i> commits it and offers to write the <i>.prj</i> sidecar, and <i>Revert CRS</i> undoes the assignment.</td>
            </tr>
            <tr style="background-color: #f9fafb;">
              <td style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">Option B</td>
              <td style="border-bottom: 1px solid #f3f4f6;"><b>Georeference a Local Grid.</b> Click <i>Check Control Points</i> (read-only) to fit the transform and see its RMS error, then <i>Georeference This Layer</i> to apply it. This edits the layer's geometry in an edit session - use Toggle Editing's Save Edits to keep it, or Discard Edits to put the original coordinates back.</td>
            </tr>
            <tr style="background-color: #ffffff;">
              <td style="font-weight: bold; vertical-align: top; color: #111827;">Verify</td>
              <td>Zoom in and confirm boundaries follow roads, rivers and coastline. This dialog is modeless, so the canvas stays usable while it is open.</td>
            </tr>
          </table>

          <!-- Section 2: Diagnosis verdicts -->
          <h3 style="color: #111827; font-size: 14px; font-weight: bold; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; margin-top: 16px; margin-bottom: 10px;">
            Diagnosis Verdicts
          </h3>
          <table width="100%" cellpadding="6" cellspacing="0" style="border-collapse: collapse; margin-bottom: 16px; border: 1px solid #d1d5db; font-size: 11px;">
            <thead>
              <tr style="background-color: #f3f4f6; color: #111827; text-align: left;">
                <th style="border: 1px solid #d1d5db; padding: 7px 10px; width: 130px;">Verdict</th>
                <th style="border: 1px solid #d1d5db; padding: 7px 10px; width: 190px;">Recognised By</th>
                <th style="border: 1px solid #d1d5db; padding: 7px 10px;">Meaning and Resolution</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">Geographic</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">All values within &plusmn;180 / &plusmn;90</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Decimal degrees; only the datum is unknown. Resolve in Option A among EPSG:4326, 4683 and 4253.</td>
              </tr>
              <tr style="background-color: #f9fafb;">
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">Projected</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Easting 1e5&ndash;1e6, northing 3e5&ndash;2.7e6</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Metres on a Philippine grid. Several grids overlap in range, so use <i>Detect Known CRS</i> rather than guessing.</td>
              </tr>
              <tr>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">Web Mercator</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Easting 1.2e7&ndash;1.45e7</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">EPSG:3857, typically exported from a web mapping tool.</td>
              </tr>
              <tr style="background-color: #f9fafb;">
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">Local</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Fallback: origin near zero, negatives present, magnitudes far below any grid</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;"><b>No EPSG code can ever apply.</b> The file was digitized in table, plotter or CAD units and never georeferenced. Extending the candidate list cannot help - use Option B.</td>
              </tr>
            </tbody>
          </table>

          <!-- Section 3: PH CRS reference -->
          <h3 style="color: #111827; font-size: 14px; font-weight: bold; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; margin-top: 16px; margin-bottom: 10px;">
            Philippine CRS Reference
          </h3>
          <div style="color: #4b5563; font-size: 11px; margin-bottom: 8px;">
            Geographic (degrees). These differ by datum only; the shift on the ground is roughly 100&ndash;200 m.
          </div>
          <table width="100%" cellpadding="6" cellspacing="0" style="border-collapse: collapse; margin-bottom: 14px; border: 1px solid #d1d5db; font-size: 11px;">
            <thead>
              <tr style="background-color: #f3f4f6; color: #111827; text-align: left;">
                <th style="border: 1px solid #d1d5db; padding: 7px 10px; width: 110px;">EPSG</th>
                <th style="border: 1px solid #d1d5db; padding: 7px 10px; width: 160px;">Datum</th>
                <th style="border: 1px solid #d1d5db; padding: 7px 10px;">Typical Source</th>
              </tr>
            </thead>
            <tbody>
              <tr><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">4326</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">WGS 84</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">GPS, satellite imagery, most modern exchange data.</td></tr>
              <tr style="background-color: #f9fafb;"><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">4683</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">PRS92</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Current Philippine national datum (Clarke 1866).</td></tr>
              <tr><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">4253</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Luzon 1911</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Older NAMRIA topographic sheets and legacy surveys.</td></tr>
            </tbody>
          </table>

          <div style="color: #4b5563; font-size: 11px; margin-bottom: 8px;">
            Projected (metres). PTM zones are 2&deg; wide; UTM zones are 6&deg; wide. All carry a false easting of 500,000 m.
          </div>
          <table width="100%" cellpadding="6" cellspacing="0" style="border-collapse: collapse; margin-bottom: 16px; border: 1px solid #d1d5db; font-size: 11px;">
            <thead>
              <tr style="background-color: #f3f4f6; color: #111827; text-align: left;">
                <th style="border: 1px solid #d1d5db; padding: 7px 10px; width: 90px;">Zone</th>
                <th style="border: 1px solid #d1d5db; padding: 7px 10px; width: 100px;">Modern datum</th>
                <th style="border: 1px solid #d1d5db; padding: 7px 10px; width: 110px;">Luzon 1911 (legacy)</th>
                <th style="border: 1px solid #d1d5db; padding: 7px 10px; width: 105px;">Central Meridian</th>
                <th style="border: 1px solid #d1d5db; padding: 7px 10px;">Covers</th>
              </tr>
            </thead>
            <tbody>
              <tr><td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">PTM 1 / I</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">3121</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">25391</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">117&deg;E</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Palawan (west)</td></tr>
              <tr style="background-color: #f9fafb;"><td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">PTM 2 / II</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">3122</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">25392</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">119&deg;E</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Palawan (east), Mindoro Occidental</td></tr>
              <tr><td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">PTM 3 / III</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">3123</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">25393</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">121&deg;E</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Most of Luzon incl. Ilocos, NCR, Mindoro Oriental, Panay</td></tr>
              <tr style="background-color: #f9fafb;"><td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">PTM 4 / IV</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">3124</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">25394</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">123&deg;E</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Bicol, Negros, Cebu, Bohol, western Mindanao</td></tr>
              <tr><td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">PTM 5 / V</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">3125</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">25395</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">125&deg;E</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Eastern Mindanao, Samar, Leyte</td></tr>
              <tr style="background-color: #f9fafb;"><td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">UTM 50N</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">EPSG:32650</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">ESRI:102453</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">117&deg;E</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">114&ndash;120&deg;E: Palawan</td></tr>
              <tr><td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">UTM 51N</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">EPSG:32651</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">ESRI:102454</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">123&deg;E</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">120&ndash;126&deg;E: most of the country</td></tr>
              <tr style="background-color: #f9fafb;"><td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">UTM 52N</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">EPSG:32652</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">ESRI:102455</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">129&deg;E</td><td style="border: 1px solid #e5e7eb; padding: 6px 10px;">126&ndash;132&deg;E: eastern seaboard</td></tr>
            </tbody>
          </table>
          <div style="color: #4b5563; font-size: 11px; margin-bottom: 16px;">
            PTM zones use scale factor 0.99995; UTM uses 0.9996. PRS92 and Luzon 1911 zone grids share identical projection parameters and differ <i>only</i> in datum, so a layer in the wrong one of the pair lands about 100&ndash;200 m off, not kilometres.
            <br><br>
            <b>Why some codes say ESRI, not EPSG.</b> Putting either Philippine datum on a UTM grid gives a CRS with no EPSG code at all - both combinations exist only as ESRI definitions: PRS92 / UTM as ESRI:102456&ndash;102458, and Luzon 1911 / UTM as ESRI:102453&ndash;102455. These are not obscure; provincial data digitized in ArcGIS is commonly in exactly them, and a candidate list built only from EPSG codes misses all six. QGIS reads ESRI codes normally, so they behave like any other candidate here.
          </div>

          <!-- Section 4: Reading the fit report -->
          <h3 style="color: #111827; font-size: 14px; font-weight: bold; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; margin-top: 16px; margin-bottom: 10px;">
            Reading the Option B Result
          </h3>
          <div style="color: #4b5563; font-size: 11px; margin-bottom: 8px;">
            These are the lines that appear in the <b>Logs</b> panel after you click <i>Check Control Points</i>. There are only three numbers that matter.
          </div>
          <table width="100%" cellpadding="6" cellspacing="0" style="border-collapse: collapse; margin-bottom: 10px; border: 1px solid #d1d5db; font-size: 11px;">
            <thead>
              <tr style="background-color: #f3f4f6; color: #111827; text-align: left;">
                <th style="border: 1px solid #d1d5db; padding: 7px 10px;" width="150">The log says</th>
                <th style="border: 1px solid #d1d5db; padding: 7px 10px;">What it means</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">Found N rows...</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">How many places in the attribute table record the same spot twice - once in the file's own numbering, once as a real longitude and latitude. These are what the calculation is based on. Three is the bare minimum; more, spread across the whole layer, is better. Rows with blank or zero coordinates are skipped, so this can be lower than the total number of features.</td>
              </tr>
              <tr style="background-color: #f9fafb;">
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">typical miss</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">After working out the answer, each of those places is put through the calculation and compared with where the table says it should be. This is the usual distance between the two, in metres. Smaller is better.</td>
              </tr>
              <tr>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">largest miss</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">The worst single place. Worth reading: one bad row can hide behind a good <i>typical miss</i>. If this is far larger than the typical, one row in the table is probably wrong.</td>
              </tr>
              <tr style="background-color: #f9fafb;">
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">EXCELLENT</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Typical miss under 5 m. Landing this close on every place is not coincidence - this is where the layer really belongs. Go ahead and save.</td>
              </tr>
              <tr>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">USABLE</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Under 50 m. Fine when you are looking at a whole town or province. Not for property boundaries or anything where a few tens of metres matter.</td>
              </tr>
              <tr style="background-color: #f9fafb;">
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">POOR</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">50 m or more. Something is wrong - usually the two sets of columns are not describing the same spot on each row. A common cause is one column holding where the map label sits and the other holding the centre of the shape. Do not use the result.</td>
              </tr>
              <tr>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">Technical details</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">The block at the bottom of the log - scale, rotation and two equations. You never need it to use the result. It is there so a specialist can check the working or reuse the same transform elsewhere.</td>
              </tr>
            </tbody>
          </table>
          <div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-left: 4px solid #4b5563; padding: 10px 14px; margin-bottom: 16px;">
            <b style="color: #111827;">A low miss means consistent, not necessarily correct.</b>
            <span style="color: #374151;">
              The calculation trusts the longitude and latitude columns as given. If those were themselves produced from a bad georeference, the result will reproduce that error faithfully and still report a small miss. Always confirm the saved layer against the satellite image.
            </span>
          </div>

          <!-- Why 32651 -->
          <h3 style="color: #111827; font-size: 14px; font-weight: bold; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; margin-top: 16px; margin-bottom: 10px;">
            Why EPSG:32651 is the Recommended Output
          </h3>
          <div style="color: #374151; font-size: 11px; margin-bottom: 10px;">
            Option B has to place the corrected geometry in <i>some</i> coordinate system, and that choice is yours in the <b>Output CRS</b> box. EPSG:32651 (WGS 84 / UTM Zone 51N) is the default for four reasons:
          </div>
          <table width="100%" cellpadding="6" cellspacing="0" style="border-collapse: collapse; margin-bottom: 10px; border: 1px solid #e5e7eb; font-size: 11px;">
            <tr style="background-color: #ffffff;">
              <td width="150" style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">It covers the country</td>
              <td style="border-bottom: 1px solid #f3f4f6;">Zone 51N spans 120&ndash;126&deg;E, which contains most of the Philippines - Luzon, the Visayas and nearly all of Mindanao - so one setting works for the great majority of municipal data.</td>
            </tr>
            <tr style="background-color: #f9fafb;">
              <td style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">It is in metres</td>
              <td style="border-bottom: 1px solid #f3f4f6;">Lengths and areas measured in QGIS come out directly in metres and square metres, with no conversion. Degrees do not behave this way: a degree is a different distance on the ground depending on where you are.</td>
            </tr>
            <tr style="background-color: #ffffff;">
              <td style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">It matches the imagery</td>
              <td style="border-bottom: 1px solid #f3f4f6;">It uses the WGS 84 datum, the same as satellite imagery and GPS, so the saved layer sits on the basemap you just checked it against - with no extra shift creeping in.</td>
            </tr>
            <tr style="background-color: #f9fafb;">
              <td style="font-weight: bold; vertical-align: top; color: #111827;">It travels well</td>
              <td>UTM is understood by every GIS, and by web tools and agencies outside the Philippines that may not carry the PRS92 or Luzon 1911 definitions.</td>
            </tr>
          </table>
          <div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-left: 4px solid #4b5563; padding: 10px 14px; margin-bottom: 12px;">
            <b style="color: #111827;">Why not EPSG:4326, when degrees are so common?</b>
            <span style="color: #374151;">
              Because the two are equally accurate but not equally usable. The layer is placed in the same spot on the ground either way - the fit is not better or worse - so this is not an accuracy decision. The difference appears the moment you measure something. Taking one Piddig barangay as a worked example: written to EPSG:32651, the field calculator's <b>$area</b> returns <b>5,579,867</b>, which is square metres, and lands within 0.07% of the true ground area. The same polygon written to EPSG:4326 returns <b>0.000476</b> - square <i>degrees</i>, which is not an area anyone can act on, and which no fixed factor converts, because the ratio between square degrees and square metres changes with latitude. You would have to switch the project to ellipsoidal measurement to recover metres. Census and boundary work runs on area and length figures, so metres is the safer default. Pick EPSG:4326 when the destination genuinely wants degrees - a web map, or an exchange format that specifies them.
            </span>
          </div>
          <div style="color: #374151; font-size: 11px; margin-bottom: 16px;">
            <b>When to choose something else.</b> Pick <b>ESRI:102457</b> (PRS92 / UTM zone 51N) if your office standardises on PRS92 but you still want metres and national coverage, or <b>EPSG:3123</b> (PRS92 zone 3) if the deliverable specifies the PTM zone grid - many agency submissions do. Pick <b>EPSG:4326</b> if you need plain degrees, for a web map or for sharing. And if your data is in <b>Palawan</b> use EPSG:32650 (zone 50N), or in the <b>far east of Mindanao or Samar</b> use EPSG:32652 (zone 52N) - a layer written far outside its own UTM zone gets progressively more stretched.
            <br><br>
            One reassurance: this choice does <i>not</i> change how accurately the layer is placed. It is placed just as precisely whichever you pick - the choice affects the units you measure in and who else can read the file, not correctness.
          </div>

          <!-- Section 5: Limitations -->
          <h3 style="color: #111827; font-size: 14px; font-weight: bold; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; margin-top: 16px; margin-bottom: 10px;">
            Limitations and Notes
          </h3>
          <table width="100%" cellpadding="6" cellspacing="0" style="border-collapse: collapse; margin-bottom: 16px; border: 1px solid #e5e7eb; font-size: 11px;">
            <tr style="background-color: #ffffff;">
              <td width="150" style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">Verdicts are heuristics</td>
              <td style="border-bottom: 1px solid #f3f4f6;">The diagnosis reads magnitudes only. A small local grid that happens to fall within &plusmn;180 / &plusmn;90 - a CAD sheet in centimetres, say - is reported as <i>geographic</i>. The tell is the extent span: a Philippine municipality in degrees is about 0.1&ndash;0.3 wide, so a "geographic" verdict spanning 12 or 150 is a local grid in disguise. Equally, the projected band is tuned for Philippine metres; data in feet can also pass it.</td>
            </tr>
            <tr style="background-color: #f9fafb;">
              <td style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">Detect Known CRS proves less than it seems</td>
              <td style="border-bottom: 1px solid #f3f4f6;">It only shows which candidates land inside the country. Datum pairs on the same grid all pass, and it cannot separate them. Use provenance, or compare at large scale against imagery.</td>
            </tr>
            <tr style="background-color: #ffffff;">
              <td style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">Assigning is not reprojecting</td>
              <td style="border-bottom: 1px solid #f3f4f6;">Assigning a CRS re-labels the coordinates already in the file. It never moves geometry. To change coordinates, use Export &gt; Save Features As with a different target CRS.</td>
            </tr>
            <tr style="background-color: #f9fafb;">
              <td style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">Affine fit is planar</td>
              <td style="border-bottom: 1px solid #f3f4f6;">The transform is a single global affine: translation, scale, rotation and shear. It cannot model sheet-by-sheet distortion, paper stretch or rubber-sheeting. For a source with local warping, use Raster &gt; Georeferencer with per-region control points instead.</td>
            </tr>
            <tr style="background-color: #ffffff;">
              <td style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">Control points are trusted as given</td>
              <td style="border-bottom: 1px solid #f3f4f6;">The fit assumes the longitude/latitude columns are correct. If they were themselves derived from a bad georeference, the fit will faithfully reproduce that error with a low RMS. A low RMS proves internal consistency, not correctness - always confirm against imagery.</td>
            </tr>
            <tr style="background-color: #f9fafb;">
              <td style="font-weight: bold; vertical-align: top; color: #111827;">Attribute areas may not match</td>
              <td>Pre-computed area or length columns carried in the table were calculated in the source's own units and are not recomputed here. After georeferencing, derive areas afresh from the new geometry rather than trusting the stored values.</td>
            </tr>
          </table>

          <div style="color: #6b7280; font-size: 10px; border-top: 1px solid #e5e7eb; padding-top: 8px; margin-top: 6px;">
            Know Your Projection! v4.0.0 &nbsp;&middot;&nbsp; 2026-09-08
          </div>

        </div>
        """)
        root.addWidget(self.text)


# =============================================================================
# CONTAINER DIALOG
# =============================================================================
class ProjectionToolkit(QDialog):
    def __init__(self, parent_or_iface=None, *args, **kwargs):
        parent = None
        if parent_or_iface is not None:
            if hasattr(parent_or_iface, "mainWindow"):
                parent = parent_or_iface.mainWindow()
            elif isinstance(parent_or_iface, QWidget):
                parent = parent_or_iface
        super().__init__(parent)
        self.setWindowTitle("Know Your Projection!")
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons', 'projection_finder.svg')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        # QDialog hides the minimize/maximize buttons by default; add them
        # back so the window can be maximized, not just edge-dragged, on
        # screens much smaller or larger than the design size below.
        self.setWindowFlags(self.windowFlags()
                             | Qt.WindowMinimizeButtonHint
                             | Qt.WindowMaximizeButtonHint)
        self.setMinimumSize(820, 520)
        self.resize(1100, 720)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        title = QLabel("Know Your Projection!")
        title.setStyleSheet("font-size:16px; font-weight:700; padding:2px 0;")
        root.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#bdbdbd;")
        root.addWidget(sep)

        tabs = QTabWidget()

        self.finder_tab = ProjectionFinderTab()
        self.help_tab = HelpInfoTab()

        tabs.addTab(self.finder_tab, "Know Your Projection")
        tabs.addTab(self.help_tab, "Help and Information")

        root.addWidget(tabs, stretch=1)


# =============================================================================
# PROCESSING ALGORITHM (DUAL-MODE: PROCESSING TOOLBOX + HEADLESS CI / TESTS)
# =============================================================================
class ProjectionFinderAlgorithm(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"

    def __init__(self):
        super().__init__()

    def tr(self, string):
        return string

    def createInstance(self):
        return ProjectionFinderAlgorithm()

    def name(self):
        return 'projection_finder'

    def displayName(self):
        return self.tr('Know Your Projection!')

    def group(self):
        return self.tr('1Map')

    def groupId(self):
        return '1map'

    def icon(self):
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons', 'projection_finder.svg')
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return QIcon(":/images/themes/default/mActionFilter.svg")

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def shortHelpString(self):
        return self.tr(
            "Identifies unknown coordinate reference systems (CRS), auto-detects Philippine "
            "projection candidates (PTM zones 1-5, UTM zones 50N-52N, WGS84, PRS92, Luzon 1911), "
            "and georeferences local CAD tabular grids using 2D 6-parameter affine transformations.\n\n"
            "When run from the Processing Toolbox inside QGIS Desktop, launches the interactive "
            "Know Your Projection! dialog. When run headlessly, audits and diagnoses coordinates of the input layer."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr('Input vector layer to diagnose (optional)'),
                types=[QgsProcessing.TypeVectorAnyGeometry],
                optional=True,
            )
        )
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT,
                self.tr('Diagnostic summary'),
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        diagnostic_text = ""

        if source is not None:
            ext = source.sourceExtent()
            diag = diagnose_extent(ext)
            diag_lines = [
                f"Source Layer: {source.sourceName()}",
                f"Declared CRS: {source.sourceCrs().authid() if source.sourceCrs().isValid() else 'None/Invalid'}",
                f"Extent: Xmin={ext.xMinimum():.4f}, Ymin={ext.yMinimum():.4f}, Xmax={ext.xMaximum():.4f}, Ymax={ext.yMaximum():.4f}",
                f"Span: Width={ext.width():.4f}, Height={ext.height():.4f}",
                f"Verdict: {diag['verdict']} ({diag['rec']})",
                f"Explanation: {diag['why']}",
            ]
            hits = scan_candidates(ext)
            if hits:
                diag_lines.append(f"Matching Candidates inside PH ({len(hits)}):")
                for h in hits:
                    diag_lines.append(f"  - {h['label']} (CRS: {h['crs'].authid()})")
            else:
                diag_lines.append("No standard Philippine CRS candidate placed the layer entirely within the country.")
            diagnostic_text = "\n".join(diag_lines)
            if feedback is not None:
                feedback.pushInfo(diagnostic_text)
        else:
            diagnostic_text = "No input layer specified. Ready for interactive CRS diagnosis."

        # If running in GUI environment, open the dialog
        try:
            from qgis.PyQt.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None and app.property("appType") != "headless":
                dlg = ProjectionToolkit()
                dlg.show()
                dlg.raise_()
                dlg.activateWindow()
        except Exception as e:
            if feedback is not None:
                feedback.pushDebugInfo(f"Interactive dialog suppressed: {e}")

        return {self.OUTPUT: diagnostic_text}


if __name__ in ("__main__", "__console__"):
    try:
        projection_finder_dlg = ProjectionToolkit()
        projection_finder_dlg.show()
    except Exception:
        traceback.print_exc()

