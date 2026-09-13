# -*- coding: utf-8 -*-
"""
Geometry Repair Toolkit (Interactive Dialog)

A standalone interactive QGIS tool for topology inspection, canvas-level error
highlighting, and in-place automated repair of polygon vector layers.

Overview:
    This module provides a GUI dialog (CheckerTab) coupled with multi-threaded
    workers (TopologyEngine, PolygonFixerWorker, NullFixerWorker) that inspect
    vector polygon layers for topological invalidities and perform in-place
    geometry repairs directly on the active layer within QGIS edit mode.

Key Error Types Handled:
    - Invalid Geometry / Self Intersection: Repaired via full polygon reconstruction
      (ring extraction, unary union planarization, face matching, and hole restoration).
    - Duplicate Vertex: Detected via QGIS's internal validator and resolved through
      progressive coordinate tolerance sweeps and node-clustering deduplication.
    - Null / Empty / Missing Geometry: Reconstructed from surrounding polygon
      spatial boundaries.
    - Ring/Structure Error: Detected when QGIS validator reports structural arrangement
      issues (e.g. holes outside exterior ring, nested parts). These are non-auto-fixable
      because GEOS considers them valid and makeValid() cannot alter them; they require
      manual correction via the QGIS Vertex Tool.
    - Duplicate Geometry & Dangles: Flagged for manual review and deduplication.

Architecture:
    - TopologyError: Defines error constants, metadata container, and bounding box logic.
    - TopologyEngine: Executes multi-threaded validation passes across layer features.
    - CheckerTab: Main UI containing the layer selector, error data table, canvas
      rubber-band / marker highlights, error filter controls, and repair dispatchers.
    - PolygonFixerWorker: Background worker executing polygon fixes with detailed
      per-feature diagnostic reporting.
    - NullFixerWorker: Background worker recovering missing geometries from neighbors.
    - HelpInfoTab: Embedded rich-text documentation viewer presenting reference
      tables, repair workflows, and operational limitations.
"""

from qgis.PyQt.QtCore import QVariant, QThread, QObject, pyqtSignal, Qt, QRect, QEvent
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QMessageBox, QTextEdit, QTextBrowser, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QGroupBox, QCheckBox, QListWidget,
    QListWidgetItem, QAbstractItemView, QWidget, QFrame,
    QTabWidget, QComboBox, QSizePolicy, QRadioButton, QButtonGroup,
    QStackedWidget, QStyle, QStyleOptionButton, QStyledItemDelegate,
    QStyleOptionViewItem, QApplication
)
from qgis.PyQt.QtGui import QColor
from qgis.gui import QgsRubberBand, QgsVertexMarker
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsFeatureRequest, QgsFeature, QgsFields, QgsField,
    QgsFeatureSink, QgsMemoryProviderUtils, QgsGeometry,
    QgsProcessingContext, QgsProcessingFeedback,
    QgsProcessingFeatureSourceDefinition, QgsSpatialIndex,
    QgsProcessingUtils, QgsRectangle, QgsPointXY,
    QgsCoordinateTransform
)
from qgis.utils import iface
import processing


# =============================================================================
# SHARED CONSTANTS & HELPERS
# =============================================================================

BTN_RUN    = ""
BTN_CANCEL = ""
BTN_EXPORT = ""
BTN_CLEAR  = ""
GRP_STYLE  = "QGroupBox { font-weight:600; margin-top:6px; } QGroupBox::title { subcontrol-origin:margin; left:8px; }"
LOG_STYLE  = "background:#eceff1; font-family:Consolas,monospace; font-size:11px;"


def colored_item(text, issue_type=None):
    # Professional UI: no issue-specific row colors.
    item = QTableWidgetItem(text)
    if issue_type:
        f = item.font()
        f.setBold(True)
        item.setFont(f)
    return item


def make_progress():
    pb = QProgressBar()
    pb.setRange(0, 100); pb.setValue(0); pb.setFixedHeight(18)
    return pb


class CheckableHeaderView(QHeaderView):
    """Horizontal header for the issues table whose first section shows a
    real, native-style checkbox indicator (select/clear all auto-fixable
    rows), instead of a unicode glyph drawn as header text. Using the same
    QStyle.CE_CheckBox control the row checkboxes are drawn with keeps size,
    spacing and appearance identical between the header and the rows.
    """

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._check_state = Qt.Unchecked
        self.setSectionsClickable(True)

    def setCheckState(self, state):
        if state != self._check_state:
            self._check_state = state
            self.updateSection(0)

    def paintSection(self, painter, rect, logicalIndex):
        if logicalIndex != 0:
            super().paintSection(painter, rect, logicalIndex)
            return
        painter.save()
        super().paintSection(painter, rect, logicalIndex)
        painter.restore()

        opt = QStyleOptionButton()
        style = self.style()
        w = style.pixelMetric(QStyle.PM_IndicatorWidth, None, self)
        h = style.pixelMetric(QStyle.PM_IndicatorHeight, None, self)
        opt.rect = QRect(rect.x() + (rect.width() - w) // 2,
                          rect.y() + (rect.height() - h) // 2, w, h)
        opt.state = QStyle.State_Enabled
        if self._check_state == Qt.Checked:
            opt.state |= QStyle.State_On
        elif self._check_state == Qt.PartiallyChecked:
            opt.state |= QStyle.State_NoChange
        else:
            opt.state |= QStyle.State_Off
        style.drawControl(QStyle.CE_CheckBox, opt, painter)


class CenteredCheckBoxDelegate(QStyledItemDelegate):
    """Paints and handles the row checkbox in column 0 centered in its cell.

    Qt's default item delegate always draws a check indicator at a fixed
    left inset, ignoring the item's text alignment — that's why setting
    Qt.AlignCenter alone didn't move it. This delegate suppresses the
    built-in (left-aligned) indicator, draws its own centered one with the
    same QStyle.CE_CheckBox control the header checkbox uses, and handles
    mouse clicks against that same centered rect so it stays clickable.
    """

    def _check_rect(self, option):
        style = QApplication.style()
        w = style.pixelMetric(QStyle.PM_IndicatorWidth)
        h = style.pixelMetric(QStyle.PM_IndicatorHeight)
        return QRect(option.rect.x() + (option.rect.width() - w) // 2,
                     option.rect.y() + (option.rect.height() - h) // 2, w, h)

    def paint(self, painter, option, index):
        check_state = index.data(Qt.CheckStateRole)
        if check_state is None:
            super().paint(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget else QApplication.style()
        opt.features &= ~QStyleOptionViewItem.HasCheckIndicator
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)

        btn = QStyleOptionButton()
        btn.rect = self._check_rect(option)
        btn.state = QStyle.State_Enabled if (index.flags() & Qt.ItemIsEnabled) else QStyle.State_None
        if check_state == Qt.Checked:
            btn.state |= QStyle.State_On
        elif check_state == Qt.PartiallyChecked:
            btn.state |= QStyle.State_NoChange
        else:
            btn.state |= QStyle.State_Off
        style.drawControl(QStyle.CE_CheckBox, btn, painter)

    def editorEvent(self, event, model, option, index):
        if not (index.flags() & Qt.ItemIsUserCheckable) or not (index.flags() & Qt.ItemIsEnabled):
            return False
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            if self._check_rect(option).contains(event.pos()):
                cur = index.data(Qt.CheckStateRole)
                new = Qt.Unchecked if cur == Qt.Checked else Qt.Checked
                model.setData(index, new, Qt.CheckStateRole)
                return True
        return False


class LayerCheckDelegate(QStyledItemDelegate):
    """Used for the Input Layers list. Clicking anywhere on a row toggles
    that layer's checkbox — not just the tiny indicator square — so
    checking several layers is a plain, deterministic click each time, with
    no dependency on Ctrl/Shift modifier state (which can be unreliable to
    read across some OS/Qt combinations). Painting is left to the default
    delegate; only the click-to-toggle hit area is widened to the whole row.
    """
    def editorEvent(self, event, model, option, index):
        if not (index.flags() & Qt.ItemIsUserCheckable) or not (index.flags() & Qt.ItemIsEnabled):
            return False
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            cur = index.data(Qt.CheckStateRole)
            new = Qt.Unchecked if cur == Qt.Checked else Qt.Checked
            model.setData(index, new, Qt.CheckStateRole)
            return True
        return False


def get_polygon_layers():
    return {
        lyr.id(): lyr
        for lyr in QgsProject.instance().mapLayers().values()
        if isinstance(lyr, QgsVectorLayer)
        and lyr.geometryType() == QgsWkbTypes.PolygonGeometry
    }


def resolve_processing_output_layer(output_value, context):
    """Return a QgsVectorLayer whether Processing returns a layer object or a layer id/path string."""
    if isinstance(output_value, QgsVectorLayer):
        return output_value
    return QgsProcessingUtils.mapLayerFromString(output_value, context)


class TopologyError:
    """Represents a single geometry or topology defect detected on a layer feature.

    Attributes:
        error_type (str): The classification string (e.g. TopologyError.INVALID_GEOMETRY).
        fid (int): The QGIS feature ID exhibiting the defect.
        layer_name (str): Display name of the layer containing the feature.
        geometry (QgsGeometry): Precise point or defect geometry (not the full feature).
        description (str): Explanatory message detailing the specific validation issue.
    """
    DUPLICATE_GEOMETRY = "Duplicate Geometry"
    SELF_INTERSECTION  = "Self Intersection"
    INVALID_GEOMETRY   = "Invalid Geometry"
    DANGLE             = "Dangle (Loose End)"
    WRONG_TYPE_GEOMETRY = "Wrong-type Geometry"
    DUPLICATE_VERTEX   = "Duplicate Vertex"
    # GEOS accepts the geometry, but QGIS's internal validator objects to how
    # its rings/parts are arranged (e.g. "ring 1 of polygon 0 not in exterior
    # ring"). This is NOT a duplicate vertex and removing nodes cannot fix it,
    # so it is deliberately kept out of FIXABLE_TYPES — see CheckerTab.
    RING_STRUCTURE_ERROR = "Ring/Structure Error"
    NULL_GEOMETRY      = "Null Geometry"

    def __init__(self, error_type, fid, layer_name, geometry, description=""):
        self.error_type  = error_type
        self.fid         = fid
        self.layer_name  = layer_name
        self.geometry    = geometry   # precise error geometry, NOT the whole feature
        self.description = description

    @property
    def bbox(self):
        if self.geometry is None or self.geometry.isNull():
            return None
        bb = self.geometry.boundingBox()
        if self.geometry.type() == QgsWkbTypes.PolygonGeometry:
            bb.scale(1.2)
            return bb
        cx, cy = bb.center().x(), bb.center().y()
        half = max(bb.width(), bb.height()) * 0.5
        min_half = 500.0
        half = max(half, min_half)
        half = min(half, 5000.0)
        return QgsRectangle(cx - half, cy - half, cx + half, cy + half)


# Short, user-facing description of what each error type means — shown as
# the tooltip on issue-table rows (see CheckerTab._apply_fix_type_filter)
# and mirrored in the Help tab's Error Types table.
ERROR_TYPE_DESCRIPTIONS = {
    TopologyError.NULL_GEOMETRY: "The feature record exists, but there is no geometry object.",
    "Empty/Missing Geometry": "The feature exists, but its geometry has no usable shape or coordinates.",
    TopologyError.INVALID_GEOMETRY: "The polygon has geometry errors such as self-intersection, ring error, spike, or folded edge.",
    TopologyError.SELF_INTERSECTION: "The polygon crosses itself.",
    TopologyError.WRONG_TYPE_GEOMETRY: "The feature's geometry type does not match the layer's declared geometry type (e.g. a line or GeometryCollection stored in a polygon layer).",
    TopologyError.DUPLICATE_GEOMETRY: "This feature's geometry is an exact duplicate of another feature's.",
    TopologyError.DANGLE: "A line endpoint doesn't connect to any other line (a loose end).",
    TopologyError.DUPLICATE_VERTEX: "The ring contains a duplicate or near-duplicate vertex (or a zero-length "
                                     "segment) — commonly an accidental self-snap while manually editing a gap "
                                     "or overlap. GEOS still accepts the geometry; QGIS's stricter internal "
                                     "validator reports it. Repaired automatically by removing the extra vertex.",
    TopologyError.RING_STRUCTURE_ERROR: "GEOS accepts this geometry, but QGIS's internal validator objects to how "
                                     "its rings or parts are arranged — e.g. a hole (interior ring) that is not "
                                     "fully inside its outer ring, or a part nested inside another part. There is "
                                     "no vertex to delete and makeValid() leaves it unchanged, so this cannot be "
                                     "repaired automatically. Open the feature with the Vertex Tool and correct "
                                     "the ring manually.",
}

# Appended to every log line that reports a feature the repair could not fix,
# so the operator is told what to do next instead of just that it failed.
MANUAL_HINT = ("Check this feature manually: select it in the table above to zoom to the "
               "error, then use the Vertex Tool to correct it.")


def _precise_invalidity_point(geom):
    # validateGeometry() uses QGIS's own internal validator by default, which
    # doesn't always agree with the GEOS-based isGeosValid()/isSimple() check
    # that flagged this geometry in the first place — so it can come back
    # empty even for a genuinely GEOS-invalid geometry. Guard against that,
    # and also against a degenerate (0,0) result, which shows up as the
    # marker/zoom landing in open ocean far from the actual feature.
    try:
        errors = geom.validateGeometry()
        if errors:
            pt = errors[0].where()
            if pt is not None and not (pt.x() == 0 and pt.y() == 0):
                return QgsGeometry.fromPointXY(pt)
    except Exception:
        pass

    # centroid() can fall outside a concave or self-intersecting shape (or
    # even collapse toward (0,0) for certain "bowtie" self-intersections,
    # since it's an area-weighted calculation and the positive/negative
    # sub-areas can partially cancel out). pointOnSurface() is guaranteed to
    # return a point that actually lies on/within the geometry, so prefer it.
    try:
        pos = geom.pointOnSurface()
        if pos is not None and not pos.isEmpty():
            return pos
    except Exception:
        pass

    try:
        c = geom.centroid()
        if c is not None and not c.isEmpty():
            return c
    except Exception:
        pass

    # Absolute last resort: the geometry's own bounding-box center is always
    # well-defined for any non-empty geometry, guaranteeing we never zoom to
    # an unrelated location like (0,0).
    bb = geom.boundingBox()
    return QgsGeometry.fromPointXY(bb.center())


def _self_intersection_point(geom):
    return _precise_invalidity_point(geom)


class TopologyEngine(QObject):
    """Multi-threaded topology and geometry validation engine for vector layers.

    Evaluates vector layers against enabled topological rules, identifying invalidities
    using GEOS validation and QGIS's internal validator. Emits progress updates and
    TopologyError instances as defects are discovered.
    """

    progress    = pyqtSignal(int, str)
    error_found = pyqtSignal(object)

    CHECKS_POLYGON = [
        TopologyError.INVALID_GEOMETRY, TopologyError.NULL_GEOMETRY,
        TopologyError.DUPLICATE_GEOMETRY, TopologyError.SELF_INTERSECTION,
        TopologyError.WRONG_TYPE_GEOMETRY, TopologyError.DUPLICATE_VERTEX,
    ]
    CHECKS_LINE = [
        TopologyError.INVALID_GEOMETRY, TopologyError.NULL_GEOMETRY,
        TopologyError.DUPLICATE_GEOMETRY, TopologyError.SELF_INTERSECTION,
        TopologyError.DANGLE, TopologyError.WRONG_TYPE_GEOMETRY, TopologyError.DUPLICATE_VERTEX,
    ]
    CHECKS_POINT = [
        TopologyError.INVALID_GEOMETRY, TopologyError.NULL_GEOMETRY,
        TopologyError.DUPLICATE_GEOMETRY,
    ]

    def __init__(self, parent=None):
        super(TopologyEngine, self).__init__(parent)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run_checks(self, layer, enabled_checks):
        self._cancelled = False
        errors = []
        if layer is None or not layer.isValid():
            return errors

        # GeometryNoCheck is set explicitly, exactly as the repair workers do.
        # A plain getFeatures() inherits whatever invalid-geometry filtering the
        # request defaults to, and this scan MUST see invalid features — they are
        # the entire point of it. Never let a filter silently hide the errors the
        # checker exists to report.
        _req = QgsFeatureRequest().setInvalidGeometryCheck(QgsFeatureRequest.GeometryNoCheck)
        features  = list(layer.getFeatures(_req))
        total     = len(features)
        if total == 0:
            return errors

        layer_name = layer.name()
        geom_type  = QgsWkbTypes.geometryType(layer.wkbType())

        use_spatial = any(c in enabled_checks for c in [
            TopologyError.DUPLICATE_GEOMETRY,
            TopologyError.DANGLE,
        ])
        spatial_index = QgsSpatialIndex() if use_spatial else None
        feat_map = {}

        # ── Pass 1: single-feature checks ────────────────────────────────
        for i, feat in enumerate(features):
            if self._cancelled:
                break

            self.progress.emit(int(i / total * 60),
                               "Checking feature {}/{}...".format(i + 1, total))
            fid  = feat.id()
            geom = feat.geometry()

            if TopologyError.NULL_GEOMETRY in enabled_checks:
                if geom is None or geom.isNull() or geom.isEmpty():
                    err = TopologyError(TopologyError.NULL_GEOMETRY, fid,
                                        layer_name, QgsGeometry(),
                                        "Feature has no geometry")
                    errors.append(err); self.error_found.emit(err)
                    if use_spatial:
                        feat_map[fid] = feat
                    continue

            geos_valid = geom.isGeosValid()
            geos_simple = geom.isSimple()

            if TopologyError.INVALID_GEOMETRY in enabled_checks:
                if not geos_valid:
                    precise_pt = _precise_invalidity_point(geom)
                    err = TopologyError(TopologyError.INVALID_GEOMETRY, fid,
                                        layer_name, precise_pt,
                                        "Geometry fails GEOS validity test")
                    errors.append(err); self.error_found.emit(err)

            if TopologyError.SELF_INTERSECTION in enabled_checks:
                if not geos_simple:
                    precise_pt = _self_intersection_point(geom)
                    err = TopologyError(TopologyError.SELF_INTERSECTION, fid,
                                        layer_name, precise_pt,
                                        "Geometry self-intersects")
                    errors.append(err); self.error_found.emit(err)

            if (TopologyError.DUPLICATE_VERTEX in enabled_checks
                    and geom_type in (QgsWkbTypes.PolygonGeometry, QgsWkbTypes.LineGeometry)
                    and not geom.isNull() and not geom.isEmpty()
                    and geos_valid and geos_simple):
                # GEOS considers this geometry fine — but GEOS is deliberately
                # tolerant of things like a duplicate/near-duplicate vertex or
                # a zero-length segment, which is exactly what an accidental
                # self-snap during manual gap/overlap digitizing produces.
                # QGIS's own internal validator (used here, not GEOS) is far
                # more literal about these and often catches what GEOS lets
                # through. Auto-fixable: repaired by simply removing the
                # duplicate/near-duplicate vertex (see PolygonFixerWorker's
                # removeDuplicateNodes() fast path).
                try:
                    qgis_errors = geom.validateGeometry()
                except Exception:
                    qgis_errors = []
                if qgis_errors:
                    first = qgis_errors[0]
                    try:
                        pt = first.where()
                        loc = QgsGeometry.fromPointXY(pt) if pt else geom.centroid()
                    except Exception:
                        loc = geom.centroid()
                    try:
                        detail = first.what()
                    except Exception:
                        detail = "flagged by QGIS's internal validator"

                    # validateGeometry() reports several unrelated problems, and
                    # only one of them is actually a duplicate vertex. Classify by
                    # what it SAID rather than labelling everything DUPLICATE_VERTEX
                    # — the label decides which repair runs, and running the
                    # remove-duplicate-nodes fixer on, say, a misplaced interior
                    # ring can never succeed and leaves the row stuck forever.
                    #   "line 1 contains 2 duplicate node(s) starting at vertex 2"
                    #       -> a real duplicate vertex, auto-fixable
                    #   "ring 1 of polygon 0 not in exterior ring"
                    #   "Polygon 1 lies inside polygon 0"
                    #       -> ring/part arrangement, NOT auto-fixable
                    if "duplicate node" in detail.lower():
                        err = TopologyError(TopologyError.DUPLICATE_VERTEX, fid,
                                            layer_name, loc,
                                            "Duplicate/near-duplicate vertex (e.g. from an accidental "
                                            "self-snap): {}".format(detail))
                    else:
                        err = TopologyError(TopologyError.RING_STRUCTURE_ERROR, fid,
                                            layer_name, loc,
                                            "QGIS's internal validator reports: {}. This is not a duplicate "
                                            "vertex — there is no node to delete — so it cannot be repaired "
                                            "automatically.".format(detail))
                    errors.append(err); self.error_found.emit(err)

            if TopologyError.WRONG_TYPE_GEOMETRY in enabled_checks:
                if (not geom.isNull() and not geom.isEmpty()
                        and QgsWkbTypes.geometryType(geom.wkbType()) != geom_type):
                    err = TopologyError(TopologyError.WRONG_TYPE_GEOMETRY, fid,
                                        layer_name, geom.centroid(),
                                        "Feature geometry type ({}) does not match "
                                        "layer geometry type ({})".format(
                                            QgsWkbTypes.displayString(geom.wkbType()),
                                            QgsWkbTypes.displayString(layer.wkbType())))
                    errors.append(err); self.error_found.emit(err)

            if use_spatial:
                feat_map[fid] = feat
                spatial_index.addFeature(feat)

        # ── Pass 2: multi-feature checks ─────────────────────────────────
        if use_spatial and not self._cancelled:
            processed = set()
            for i, feat in enumerate(features):
                if self._cancelled:
                    break
                self.progress.emit(60 + int(i / total * 35),
                                   "Cross-checking feature {}/{}...".format(i + 1, total))
                fid  = feat.id()
                geom = feat.geometry()
                if geom is None or geom.isNull() or geom.isEmpty():
                    continue

                for cid in spatial_index.intersects(geom.boundingBox()):
                    if cid == fid:
                        continue
                    pair = (min(fid, cid), max(fid, cid))
                    if pair in processed:
                        continue
                    processed.add(pair)

                    other_geom = feat_map[cid].geometry() if cid in feat_map else None
                    if other_geom is None or other_geom.isNull():
                        continue

                    if TopologyError.DUPLICATE_GEOMETRY in enabled_checks:
                        if geom.equals(other_geom):
                            err = TopologyError(
                                TopologyError.DUPLICATE_GEOMETRY, fid, layer_name,
                                geom.centroid(),
                                "Duplicate of feature {}".format(cid))
                            errors.append(err); self.error_found.emit(err)

        # ── Dangle check: per-feature, all neighbors checked before flagging ──
        if (TopologyError.DANGLE in enabled_checks
                and geom_type == QgsWkbTypes.LineGeometry
                and spatial_index is not None
                and not self._cancelled):
            for feat in features:
                if self._cancelled:
                    break
                fid  = feat.id()
                geom = feat.geometry()
                if geom is None or geom.isNull() or geom.isEmpty():
                    continue
                vertices = list(geom.vertices())
                if not vertices:
                    continue
                for ep in [vertices[0], vertices[-1]]:
                    pt  = QgsGeometry.fromPointXY(QgsPointXY(ep.x(), ep.y()))
                    buf = pt.buffer(1e-8, 5)
                    neighbors = spatial_index.intersects(buf.boundingBox())
                    connected = any(
                        feat_map[cid].geometry().intersects(buf)
                        for cid in neighbors
                        if cid != fid and cid in feat_map
                    )
                    if not connected:
                        err = TopologyError(
                            TopologyError.DANGLE, fid, layer_name, pt,
                            "Dangling endpoint at ({:.4f}, {:.4f})".format(
                                ep.x(), ep.y()))
                        errors.append(err); self.error_found.emit(err)

        self.progress.emit(100, "Done - {} error(s) found.".format(len(errors)))
        return errors


# =============================================================================
# TAB 1 — GEOMETRY CHECKER WORKER
# =============================================================================

class CheckWorker(QThread):
    progress    = pyqtSignal(int)
    issue_found = pyqtSignal(dict)
    log         = pyqtSignal(str)
    finished    = pyqtSignal(int)

    def __init__(self, layers, checks):
        super().__init__()
        self.layers = layers; self.checks = checks; self._cancel = False
        self._engine = TopologyEngine()

    def cancel(self):
        self._cancel = True
        self._engine.cancel()

    def run(self):
        grand = 0; n = len(self.layers)
        for li, layer in enumerate(self.layers):
            if self._cancel: break
            self.log.emit(f"Scanning: {layer.name()}  ({layer.featureCount()} features)")
            lg_name = QgsWkbTypes.displayString(layer.wkbType())
            geom_type = QgsWkbTypes.geometryType(layer.wkbType())

            # Map the checker-tab's simple checkbox flags onto the full
            # TopologyEngine check set, scoped to what applies to this layer's
            # geometry type (mirrors TopologyEngine.CHECKS_POLYGON/LINE/POINT).
            enabled = set()
            if self.checks.get("null"):    enabled.add(TopologyError.NULL_GEOMETRY)
            if self.checks.get("invalid"): enabled.add(TopologyError.INVALID_GEOMETRY)
            # "empty" has no direct TopologyEngine equivalent —
            # NULL_GEOMETRY already covers isNull()/isEmpty() together.
            if self.checks.get("empty"):   enabled.add(TopologyError.NULL_GEOMETRY)
            enabled |= {
                TopologyError.SELF_INTERSECTION, TopologyError.DUPLICATE_GEOMETRY,
                TopologyError.WRONG_TYPE_GEOMETRY, TopologyError.DANGLE,
                TopologyError.DUPLICATE_VERTEX,
            }
            if geom_type == QgsWkbTypes.PolygonGeometry:
                enabled &= set(TopologyEngine.CHECKS_POLYGON)
            elif geom_type == QgsWkbTypes.LineGeometry:
                enabled &= set(TopologyEngine.CHECKS_LINE)
            else:
                enabled &= set(TopologyEngine.CHECKS_POINT)

            counts = {}

            def _on_error(err, _layer=layer, _lg_name=lg_name):
                nonlocal grand
                counts[err.error_type] = counts.get(err.error_type, 0) + 1
                grand += 1
                try:
                    feat = next(_layer.getFeatures(
                        QgsFeatureRequest(err.fid)
                        .setInvalidGeometryCheck(QgsFeatureRequest.GeometryNoCheck)), None)
                    full_geom = feat.geometry() if feat else None
                except Exception:
                    full_geom = None
                fg_name = "N/A"
                if full_geom is not None and not full_geom.isNull():
                    try: fg_name = QgsWkbTypes.displayString(full_geom.wkbType())
                    except: fg_name = "Unknown"
                self.issue_found.emit({
                    "layer": _layer, "layer_name": _layer.name(),
                    "feature_id": err.fid, "issue_type": err.error_type,
                    "layer_geom_type": _lg_name, "feature_geom_type": fg_name,
                    "geometry": full_geom,
                    # extras from the ported engine, used by the new
                    # PluginStyleFixerWorker and for zoom-to-error:
                    "topo_error_type": err.error_type,
                    "error_location": err.geometry,
                    "bbox": err.bbox,
                    "description": err.description,
                })

            self._engine.error_found.connect(_on_error)
            progress_slot = lambda pct, msg, _li=li: self.progress.emit(
                int(((_li + (pct / 100)) / n) * 100))
            self._engine.progress.connect(progress_slot)
            self._engine.run_checks(layer, enabled)
            self._engine.error_found.disconnect(_on_error)
            self._engine.progress.disconnect(progress_slot)

            for lbl, cnt in counts.items():
                if cnt: self.log.emit(f"   {lbl}: {cnt}")
            self.progress.emit(int(((li+1)/n)*100))
        self.log.emit(f"\nFinished. Total issues: {grand}")
        self.finished.emit(grand)


class PluginStyleFixerWorker(QThread):
    progress = pyqtSignal(int)
    log      = pyqtSignal(str)
    finished = pyqtSignal(int, int)   # fixed, skipped

    FIXABLE = (
        TopologyError.INVALID_GEOMETRY,
        TopologyError.SELF_INTERSECTION,
        TopologyError.NULL_GEOMETRY,
    )

    def __init__(self, layer, issues, delete_null=False):
        """issues: list of the issue_found dicts emitted by CheckWorker,
        already filtered to this layer. delete_null: must be pre-confirmed
        by the caller (UI) before running, since this worker has no dialog
        of its own — mirrors the plugin's QMessageBox.question guard."""
        super().__init__()
        self.layer = layer
        self.issues = issues
        self.delete_null = delete_null
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _apply_fix(self, fid, error_type):
        layer = self.layer
        if error_type == TopologyError.NULL_GEOMETRY:
            if not self.delete_null:
                return False, "Skipped (deletion not confirmed)."
            layer.startEditing()
            ok = layer.deleteFeature(fid)
            if ok:
                layer.commitChanges(); return True, f"Deleted FID {fid}."
            layer.rollBack(); return False, f"Could not delete FID {fid}."

        if error_type in (TopologyError.INVALID_GEOMETRY, TopologyError.SELF_INTERSECTION):
            feat = next(layer.getFeatures(f"$id = {fid}"), None)
            if not feat:
                return False, f"FID {fid} not found."
            fixed_geom = feat.geometry().makeValid()
            if not fixed_geom or fixed_geom.isNull():
                return False, f"makeValid() returned null for FID {fid}."
            layer.startEditing()
            ok = layer.changeGeometry(fid, fixed_geom)
            if ok:
                layer.commitChanges(); return True, f"Fixed {error_type} on FID {fid}."
            layer.rollBack(); return False, f"changeGeometry failed for FID {fid}."

        return False, f"No fix available for {error_type}."

    def run(self):
        fixed = 0; skipped = 0
        fixable = [i for i in self.issues if i.get("topo_error_type") in self.FIXABLE]
        total = len(fixable)
        for idx, issue in enumerate(fixable):
            if self._cancel:
                break
            ok, msg = self._apply_fix(issue["feature_id"], issue["topo_error_type"])
            self.log.emit(f"   {msg}")
            if ok: fixed += 1
            else:  skipped += 1
            self.progress.emit(int(((idx + 1) / max(total, 1)) * 100))
        self.layer.triggerRepaint()
        self.finished.emit(fixed, skipped)


# =============================================================================
# TAB 1 — GEOMETRY CHECKER UI
# =============================================================================

def _purge_stale_geometry_toolkit_markers():
    """Remove any red error outline/marker left on the map canvas by a
    PREVIOUS run of this script.

    QgsRubberBand/QgsVertexMarker items are parented to the canvas at the
    C++/Qt level, so losing the Python reference to them (e.g. because the
    QGIS Python console re-ran this whole script, replacing the old `dlg`
    variable, or the console session was reset) does NOT remove them from
    the canvas — they stay visible forever with nothing left in Python that
    can find them again via the normal per-instance cleanup. Tracking them
    in a list attached directly to the canvas object itself (which is the
    same long-lived QGIS object across script re-runs, unlike our own
    dialog/tab instances) lets a fresh run find and clean up orphans left
    by any earlier one.
    """
    if not iface or not hasattr(iface, "mapCanvas"):
        return
    canvas = iface.mapCanvas()
    if not canvas:
        return
    stale = getattr(canvas, "_geom_toolkit_markers", None)
    if stale:
        for item in stale:
            try:
                canvas.scene().removeItem(item)
            except Exception:
                pass
    canvas._geom_toolkit_markers = []


def _track_canvas_marker(item):
    """Register a rubber band / vertex marker into the canvas-persistent
    list so a future run of this script can find and remove it even if
    this run's own cleanup never fires (dialog force-closed, console
    session reset, etc.)."""
    if not iface or not hasattr(iface, "mapCanvas"):
        return
    canvas = iface.mapCanvas()
    if not canvas:
        return
    if not hasattr(canvas, "_geom_toolkit_markers"):
        canvas._geom_toolkit_markers = []
    canvas._geom_toolkit_markers.append(item)


class CheckerTab(QWidget):
    """Primary interactive UI tab for Geometry Repair Toolkit.

    Provides controls for selecting input layers, launching background topology scans,
    displaying issues in an interactive table, highlighting errors on the QGIS map
    canvas, and routing fixable rows to automated in-place repair workers.
    """

    # Which TopologyError / issue-type strings each internal repair mechanism
    # handles. "Repair Selected Features" is the single user-facing action;
    # under the hood it dispatches each checked row to the right mechanism
    # automatically based on its error type.
    REPAIR_TYPES = {"Invalid Geometry", "Wrong-type Geometry", TopologyError.SELF_INTERSECTION,
                     TopologyError.DUPLICATE_VERTEX}   # -> PolygonFixerWorker (edits source layer in place)
    NULL_TYPES   = {"Null Geometry", "Empty/Missing Geometry"}          # -> NullFixerWorker (edits source layer in place)
    QUICK_TYPES  = set()                                                # -> PluginStyleFixerWorker (in-place) — none routed here anymore
    FIXABLE_TYPES = REPAIR_TYPES | NULL_TYPES | QUICK_TYPES

    def __init__(self):
        super().__init__()
        _purge_stale_geometry_toolkit_markers()
        self.issues = []
        self.worker = None
        self.fix_queue = []
        self.fix_total_jobs = 0
        self.fix_done_jobs = 0
        self._error_marker = None   # QgsVertexMarker pinned on the exact error point
        self._error_rubber = None   # QgsRubberBand outlining the offending feature
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        # ── LEFT: INPUT AND SCAN CONTROLS ─────────────────────────────
        left = QWidget(); left.setFixedWidth(315)
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0); ll.setSpacing(6)

        grp_l = QGroupBox("Input Layers"); grp_l.setStyleSheet(GRP_STYLE)
        gl = QVBoxLayout(grp_l)
        sel_row = QHBoxLayout()
        self.btn_all  = QPushButton("Select All");  self.btn_all.setFixedHeight(24)
        self.btn_none = QPushButton("Clear");        self.btn_none.setFixedHeight(24)
        sel_row.addWidget(self.btn_all); sel_row.addWidget(self.btn_none)
        gl.addLayout(sel_row)
        self.layer_list = QListWidget()
        self.layer_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.layer_list.setAlternatingRowColors(True)
        self.layer_list.setToolTip("Click a layer to check/uncheck it as an input.")
        self.layer_list.setStyleSheet("""
            QListWidget {
                border: 1px solid #b0bec5;
                outline: 0;
            }
            QListWidget::item {
                padding: 3px 4px;
            }
            QListWidget::indicator:checked {
                background-color: #1565c0;
                border: 1px solid #1565c0;
            }
        """)
        self._fill_layers()
        self.layer_list.setItemDelegate(LayerCheckDelegate(self.layer_list))
        gl.addWidget(self.layer_list)

        self.layer_count_label = QLabel("Selected layers: 0 / 0")
        self.layer_count_label.setStyleSheet("color:#455a64; font-size:11px;")
        gl.addWidget(self.layer_count_label)
        self._update_layer_count_label()

        ll.addWidget(grp_l, stretch=1)

        self.run_btn    = QPushButton("Scan Layers"); self.run_btn.setFixedHeight(32); self.run_btn.setStyleSheet(BTN_RUN)
        self.cancel_btn = QPushButton("Cancel"); self.cancel_btn.setFixedHeight(32); self.cancel_btn.setStyleSheet(BTN_CANCEL); self.cancel_btn.setEnabled(False)
        self.clear_btn  = QPushButton("Clear"); self.clear_btn.setFixedHeight(32); self.clear_btn.setStyleSheet(BTN_CLEAR)
        ll.addWidget(self.run_btn)
        r1 = QHBoxLayout(); r1.addWidget(self.cancel_btn); r1.addWidget(self.clear_btn); ll.addLayout(r1)

        self.progress = make_progress(); ll.addWidget(self.progress)
        ll.addStretch()

        # ── RIGHT: ERROR VIEWER, REPAIR PANEL, LOG ────────────────────
        right = QWidget(); rl = QVBoxLayout(right)
        rl.setContentsMargins(0,0,0,0); rl.setSpacing(6)

        self.summary = QLabel("No scanned layers. Select input layers on the left and click Scan Layers.")
        self.summary.setStyleSheet("font-size:13px; font-weight:600; color:#37474f;")
        rl.addWidget(self.summary)

        self.table = QTableWidget(); self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["", "Layer", "Feature ID", "Error Type", "Layer Geom", "Feature Geom"])
        self._header_checkbox = CheckableHeaderView(Qt.Horizontal, self.table)
        self.table.setHorizontalHeader(self._header_checkbox)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(0, 28)
        self.table.setItemDelegateForColumn(0, CenteredCheckBoxDelegate(self.table))
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self._updating_error_checks = False
        self.table.horizontalHeader().sectionClicked.connect(self._handle_error_header_clicked)
        self.table.itemChanged.connect(self._handle_error_item_changed)
        rl.addWidget(self.table, stretch=1)

        legend = QLabel(
            '<span style="background-color:#ffffff; border:1px solid #999;">&nbsp;&nbsp;&nbsp;</span> '
            'Auto-fixable &nbsp;&nbsp;'
            '<span style="background-color:#ebebeb; border:1px solid #999;">&nbsp;&nbsp;&nbsp;</span> '
            'No automatic fix — manual review'
        )
        legend.setStyleSheet("font-size:11px; color:#455a64; padding:2px 0;")
        rl.addWidget(legend)

        # Repair panel is intentionally placed below the viewer so the workflow is:
        # Scan -> Review Issues -> Repair Selected Features (auto-detects fix mechanism per row).
        self.repair_group = QGroupBox(""); self.repair_group.setStyleSheet(GRP_STYLE)
        gf = QVBoxLayout(self.repair_group)
        gf.setContentsMargins(10, 24, 10, 10)
        gf.setSpacing(7)

        self.fix_btn = QPushButton("Repair Selected Features")
        self.fix_btn.setFixedHeight(32); self.fix_btn.setStyleSheet(BTN_EXPORT)
        self.fix_btn.setEnabled(False)
        self.fix_btn.setToolTip(
            "Repairs every checked row directly on the ORIGINAL layer using the appropriate "
            "fixer automatically:\n"
            "- Invalid Geometry / Wrong-type Geometry / Self Intersection -> thorough polygon reconstruction\n"
            "- Duplicate Vertex -> removes the duplicate/near-duplicate vertex directly\n"
            "- Null / Empty Geometry -> recovery from surrounding polygons\n\n"
            "Changes are left UNSAVED (the layer enters edit mode) — use QGIS's Save Edits to "
            "keep them, or Cancel Edits to discard and revert.")
        gf.addWidget(self.fix_btn)

        self.repair_group.setEnabled(False)
        rl.addWidget(self.repair_group)

        rl.addWidget(QLabel("Log"))
        self.log_box = QTextEdit(); self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet(LOG_STYLE); self.log_box.setFixedHeight(150)
        rl.addWidget(self.log_box)

        root.addWidget(left); root.addWidget(right, stretch=1)

        self.run_btn.clicked.connect(self._run)
        self.cancel_btn.clicked.connect(self._cancel)
        self.clear_btn.clicked.connect(self._clear)
        self.btn_all.clicked.connect(self._check_all_layers)
        self.btn_none.clicked.connect(self._uncheck_all_layers)
        self.layer_list.itemChanged.connect(self._update_layer_count_label)

        # Keep the input layer viewer updated when polygon layers are added or removed in QGIS.
        QgsProject.instance().layersAdded.connect(self._refresh_layers_keep_selection)
        QgsProject.instance().layersRemoved.connect(self._refresh_layers_keep_selection)

        self.fix_btn.clicked.connect(self._fix_checked_errors)
        self.table.cellDoubleClicked.connect(self._zoom)

    def _check_all_layers(self):
        self.layer_list.blockSignals(True)
        for i in range(self.layer_list.count()):
            self.layer_list.item(i).setCheckState(Qt.Checked)
        self.layer_list.blockSignals(False)
        self._update_layer_count_label()

    def _uncheck_all_layers(self):
        self.layer_list.blockSignals(True)
        for i in range(self.layer_list.count()):
            self.layer_list.item(i).setCheckState(Qt.Unchecked)
        self.layer_list.blockSignals(False)
        self._update_layer_count_label()

    def _fill_layers(self, keep_selected_ids=None):
        """Refresh the input layer list from the current QGIS project.

        keep_selected_ids preserves the user's checked layers when QGIS
        layers are added or removed. This makes the layer viewer feel live while
        avoiding accidental loss of selected inputs.
        """
        keep_selected_ids = set(keep_selected_ids or [])
        self.layer_list.blockSignals(True)
        self.layer_list.clear(); self._lmap = {}
        for lid, lyr in get_polygon_layers().items():
            item = QListWidgetItem(lyr.name()); item.setData(Qt.UserRole, lid)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if lid in keep_selected_ids else Qt.Unchecked)
            self.layer_list.addItem(item); self._lmap[lid] = lyr
        self.layer_list.blockSignals(False)

    def _selected_layer_ids(self):
        return [self.layer_list.item(i).data(Qt.UserRole) for i in range(self.layer_list.count())
                if self.layer_list.item(i).checkState() == Qt.Checked]

    def _selected(self):
        return [self._lmap[lid] for lid in self._selected_layer_ids() if lid in self._lmap]

    def _update_layer_count_label(self):
        if not hasattr(self, "layer_count_label"):
            return
        selected = len(self._selected_layer_ids())
        total = self.layer_list.count()
        self.layer_count_label.setText(f"Selected layers: {selected} / {total}")

    def _refresh_layers_keep_selection(self, *args):
        selected_ids = self._selected_layer_ids() if hasattr(self, "layer_list") else []
        self._fill_layers(keep_selected_ids=selected_ids)
        self._update_layer_count_label()

    def _log(self, msg): self.log_box.append(msg)

    def _run(self):
        layers = self._selected()
        if not layers:
            return QMessageBox.warning(self, "No Layers", "Select at least one polygon layer.")
        # Version 1.0: always run all validation checks automatically.
        checks = {"null": True, "empty": True, "invalid": True}
        self.issues = []; self.table.setRowCount(0); self._update_error_header_checkbox(); self.log_box.clear()
        self.progress.setValue(0); self.summary.setText("Scanning geometry errors...")
        self.fix_btn.setEnabled(False); self.repair_group.setEnabled(False)
        self.run_btn.setEnabled(False); self.cancel_btn.setEnabled(True)
        self._clear_error_highlight()
        self.worker = CheckWorker(layers, checks)
        self.worker.log.connect(self._log)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.issue_found.connect(self._add_row)
        self.worker.finished.connect(self._done)
        self.worker.start()

    def _cancel(self):
        if self.worker: self.worker.cancel(); self._log("Cancelled.")
        self.run_btn.setEnabled(True); self.cancel_btn.setEnabled(False); self.fix_btn.setEnabled(bool(self.issues)); self.repair_group.setEnabled(bool(self.issues))

    def _done(self, total):
        self.run_btn.setEnabled(True); self.cancel_btn.setEnabled(False)
        self.fix_btn.setEnabled(total > 0); self.repair_group.setEnabled(total > 0)
        self.summary.setText(f"Scan complete - {total} error(s) found. Check errors in the viewer panel, then click Repair Selected Features.")
        self._apply_fix_type_filter()

    def _add_row(self, data):
        issue = data["issue_type"]

        # Self Intersection on a polygon almost always also fails the
        # general GEOS validity test, so it's reported alongside Invalid
        # Geometry for the same feature — and both route through the same
        # repair mechanism anyway. Merge them into a single row instead of
        # two duplicate-looking entries for the same Feature ID.
        MERGE_PAIR = {TopologyError.INVALID_GEOMETRY, TopologyError.SELF_INTERSECTION}
        if issue in MERGE_PAIR:
            for i, existing in enumerate(self.issues):
                if (existing["layer_name"] == data["layer_name"]
                        and existing["feature_id"] == data["feature_id"]
                        and existing["issue_type"] in MERGE_PAIR
                        and issue not in existing.get("merged_types", [existing["issue_type"]])):
                    existing.setdefault("merged_types", [existing["issue_type"]])
                    existing["merged_types"].append(issue)
                    merged_label = " + ".join(existing["merged_types"])
                    self.table.setItem(i, 3, colored_item(merged_label, existing["issue_type"]))
                    self._apply_fix_type_filter()
                    return

        self.issues.append(data)
        row = self.table.rowCount(); self.table.insertRow(row)
        self._updating_error_checks = True
        chk = QTableWidgetItem("")
        chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
        chk.setCheckState(Qt.Unchecked)
        chk.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 0, chk)
        self.table.setItem(row, 1, QTableWidgetItem(data["layer_name"]))
        self.table.setItem(row, 2, QTableWidgetItem(str(data["feature_id"])))
        self.table.setItem(row, 3, colored_item(issue, issue))
        self.table.setItem(row, 4, QTableWidgetItem(data["layer_geom_type"]))
        self.table.setItem(row, 5, QTableWidgetItem(data["feature_geom_type"]))
        self._updating_error_checks = False
        self._apply_fix_type_filter()

    def _row_status(self, row):
        """Returns 'fixable' if Repair Selected Features can act on this row
        (regardless of which internal mechanism it uses), otherwise 'none'."""
        if row >= len(self.issues):
            return "none"
        issue = self.issues[row]["issue_type"]
        return "fixable" if issue in self.FIXABLE_TYPES else "none"

    def _is_row_compatible_with_current_fix_type(self, row):
        return self._row_status(row) == "fixable"

    def _apply_fix_type_filter(self):
        """Style every error row by whether Repair Selected Features can handle it:
        - white / black : fixable (checkbox enabled)
        - grey          : no automatic fix available — manual review only (checkbox disabled)
        """
        grey_bg  = QColor(235, 235, 235); grey_fg  = QColor(140, 140, 140)
        white_bg = QColor(255, 255, 255); black_fg = QColor(0, 0, 0)

        fixable_count = 0
        none_count = 0

        for row in range(self.table.rowCount()):
            status = self._row_status(row)
            issue = self.issues[row]["issue_type"] if row < len(self.issues) else ""
            chk = self.table.item(row, 0)

            merged_types = self.issues[row].get("merged_types", [issue]) if row < len(self.issues) else [issue]
            if len(merged_types) > 1:
                desc = "\n".join(f"• {t}: {ERROR_TYPE_DESCRIPTIONS.get(t, t)}" for t in merged_types)
            else:
                desc = ERROR_TYPE_DESCRIPTIONS.get(issue, "")

            if status == "fixable":
                fixable_count += 1
                tip = f"{desc}\n\nHandled automatically by Repair Selected Features." if desc else \
                      "Handled automatically by Repair Selected Features."
                bg, fg, enable_chk = white_bg, black_fg, True
            else:
                none_count += 1
                tip = (f"{desc}\n\nNo automatic fix available — manual review required." if desc else
                       f"No automatic fix available for {issue} — manual review required.")
                bg, fg, enable_chk = grey_bg, grey_fg, False

            if chk:
                if enable_chk:
                    chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
                else:
                    chk.setCheckState(Qt.Unchecked)
                    chk.setFlags(Qt.ItemIsSelectable)
                chk.setToolTip(tip)

            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if not item:
                    continue
                item.setBackground(bg); item.setForeground(fg); item.setToolTip(tip)

        self._update_error_header_checkbox()
        self.fix_btn.setEnabled(bool(self.issues) and fixable_count > 0)
        if self.issues:
            self.summary.setText(
                f"{fixable_count} fixable by Repair Selected Features, "
                f"{none_count} manual review only."
            )

    def _compatible_error_rows(self):
        return [
            row for row in range(self.table.rowCount())
            if self._is_row_compatible_with_current_fix_type(row)
        ]

    def _set_error_rows_checked(self, checked):
        self._updating_error_checks = True
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if not item:
                continue
            if self._is_row_compatible_with_current_fix_type(row):
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            else:
                item.setCheckState(Qt.Unchecked)
        self._updating_error_checks = False
        self._update_error_header_checkbox()

    def _update_error_header_checkbox(self):
        if not hasattr(self, "table"):
            return
        compatible_rows = self._compatible_error_rows()
        if not compatible_rows:
            self._header_checkbox.setCheckState(Qt.Unchecked)
            return
        checked_rows = [
            row for row in compatible_rows
            if self.table.item(row, 0) and self.table.item(row, 0).checkState() == Qt.Checked
        ]
        if len(checked_rows) == len(compatible_rows):
            state = Qt.Checked
        elif checked_rows:
            state = Qt.PartiallyChecked
        else:
            state = Qt.Unchecked
        self._header_checkbox.setCheckState(state)
        self._header_checkbox.setToolTip("Click to select or clear all auto-fixable errors.")

    def _handle_error_header_clicked(self, logical_index):
        if logical_index != 0 or not self.issues:
            return
        compatible_rows = self._compatible_error_rows()
        if not compatible_rows:
            return
        all_checked = all(
            self.table.item(row, 0) and self.table.item(row, 0).checkState() == Qt.Checked
            for row in compatible_rows
        )
        self._set_error_rows_checked(not all_checked)

    def _handle_error_item_changed(self, item):
        if self._updating_error_checks:
            return
        if item and item.column() == 0:
            self._update_error_header_checkbox()

    def _checked_issue_rows(self):
        rows = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.Checked and row < len(self.issues):
                rows.append(row)
        if not rows:
            # Convenience: if user selected table rows but did not tick boxes, use highlighted rows.
            rows = sorted({
                i.row() for i in self.table.selectedIndexes()
                if i.row() < len(self.issues) and self._is_row_compatible_with_current_fix_type(i.row())
            })
        else:
            rows = [r for r in rows if self._is_row_compatible_with_current_fix_type(r)]
        return rows

    def _fix_checked_errors(self):
        rows = self._checked_issue_rows()
        if not rows:
            return QMessageBox.warning(self, "No Errors Selected", "Check at least one auto-fixable error in the viewer panel, or highlight rows in the table.")

        jobs = {}
        skipped = []
        for row in rows:
            d = self.issues[row]
            issue = d["issue_type"]
            layer = d["layer"]
            if issue in self.REPAIR_TYPES:
                key = (layer.id(), "polygon")
                jobs.setdefault(key, {"layer": layer, "kind": "polygon", "ids": set()})["ids"].add(d["feature_id"])
            elif issue in self.NULL_TYPES:
                key = (layer.id(), "null")
                jobs.setdefault(key, {"layer": layer, "kind": "null", "ids": set()})["ids"].add(d["feature_id"])
            elif issue in self.QUICK_TYPES:
                key = (layer.id(), "quick")
                jobs.setdefault(key, {"layer": layer, "kind": "quick", "issues": []})["issues"].append(d)
            else:
                reason = d.get("description") or ERROR_TYPE_DESCRIPTIONS.get(issue, "")
                skipped.append(f"FID {d['feature_id']} ({issue}) — {reason}" if reason
                               else f"FID {d['feature_id']} ({issue})")

        if not jobs:
            return QMessageBox.warning(
                self, "No Fixable Errors",
                "None of the checked rows can be repaired automatically.\n\n"
                "They are listed in the log with the reason for each one. "
                "These features have to be corrected manually with the Vertex Tool."
            )

        if skipped:
            self._log("These checked rows have NO automatic fix and need manual repair:")
            for msg in skipped[:20]: self._log("  - " + msg)
            if len(skipped) > 20: self._log(f"  ...and {len(skipped)-20} more")
            self._log(f"  {MANUAL_HINT}")

        self.fix_queue = list(jobs.values())
        self.fix_total_jobs = len(self.fix_queue)
        self.fix_done_jobs = 0
        self.fix_edited_layers = {}   # source layer id -> the layer itself, now in an uncommitted edit session
        self.fix_touched_fids = {}    # source layer id -> set of FIDs this run actually modified
        self.run_btn.setEnabled(False); self.fix_btn.setEnabled(False); self.repair_group.setEnabled(False); self.cancel_btn.setEnabled(True)
        self.progress.setValue(0)
        self.summary.setText("Repairing selected features…")
        self._start_next_fix_job()

    def _explode_and_clean_outputs(self):
        """Run once after all repair jobs in this run finish.

        The polygon reconstruction pipeline (Polygons-to-Lines -> Polygonize
        -> pick candidate faces -> unaryUnion) can occasionally leave a
        feature multipart even though it started as a single part — e.g.
        resolving a self-intersecting "bowtie" ring can legitimately produce
        two simple polygons, or the rebuild can pick up a stray sliver
        fragment alongside the real result.

        Since repairs now edit the ORIGINAL layer's features directly (one
        row stays one row — nothing is copied into a separate output layer),
        there's no risk of this ever creating duplicate rows. This just
        cleans up the geometry itself: fragments that are empty or
        negligibly small next to the feature's largest part are dropped,
        and the feature's own geometry is replaced with the union of
        whatever real part(s) remain — still the same one feature, still
        uncommitted.

        Only FIDs this run's fixer jobs actually changed (touched_fids) are
        ever considered — pre-existing multipart features that were never
        touched (e.g. a barangay that legitimately includes an offshore
        island) are left completely alone.
        """
        AREA_ISH_RATIO = 1e-4  # a fragment under this fraction of the feature's largest part is treated as a sliver artifact, not a real part

        for key, layer in list(self.fix_edited_layers.items()):
            if layer is None:
                continue
            touched = self.fix_touched_fids.get(key, set())
            if not touched:
                continue

            cleaned = 0
            for fid in touched:
                feat = layer.getFeature(fid)
                if feat is None or not feat.hasGeometry():
                    continue
                geom = feat.geometry()
                if not geom.isMultipart():
                    continue
                try:
                    parts = [p for p in geom.asGeometryCollection() if p and not p.isEmpty()]
                except Exception:
                    continue
                if len(parts) < 2:
                    continue

                sizes = []
                for p in parts:
                    gt = QgsWkbTypes.geometryType(p.wkbType())
                    sz = (p.area() if gt == QgsWkbTypes.PolygonGeometry else
                          p.length() if gt == QgsWkbTypes.LineGeometry else 1.0)
                    sizes.append(sz)
                max_size = max(sizes) if sizes else 0
                if max_size <= 0:
                    continue

                real_parts = [p for p, sz in zip(parts, sizes)
                              if sz > 0 and (sz / max_size) >= AREA_ISH_RATIO]
                if not real_parts or len(real_parts) == len(parts):
                    continue  # nothing to clean up — every part is legitimate, or nothing survived

                new_geom = real_parts[0] if len(real_parts) == 1 else QgsGeometry.unaryUnion(real_parts)
                layer.changeGeometry(fid, new_geom)
                cleaned += 1
                self._log(f"  FID {fid} in {layer.name()}: dropped {len(parts) - len(real_parts)} "
                          f"sliver fragment(s) left over from repair.")

            if cleaned:
                self._log(f"{layer.name()}: cleaned up sliver fragments on {cleaned} repaired feature(s).")

    def _start_next_fix_job(self):
        if not self.fix_queue:
            self._explode_and_clean_outputs()
            self.run_btn.setEnabled(True); self.fix_btn.setEnabled(bool(self.issues)); self.repair_group.setEnabled(bool(self.issues)); self.cancel_btn.setEnabled(False)
            self.progress.setValue(100)
            self.summary.setText(f"Repair complete - {self.fix_done_jobs}/{self.fix_total_jobs} job(s) processed.")
            edited = [lyr for lyr in self.fix_edited_layers.values() if lyr is not None]
            if edited:
                names = ", ".join(sorted({lyr.name() for lyr in edited}))
                self._log(f"\nRepairs were applied directly to the original layer(s) — {names} — "
                          f"and are NOT saved yet. Use Layer > Toggle Editing > Save Edits to keep "
                          f"them, or Cancel Edits to discard and revert.")
            self._apply_fix_type_filter()
            return

        job = self.fix_queue.pop(0)
        layer = job["layer"]; kind = job["kind"]
        self.fix_done_jobs_display = self.fix_done_jobs + 1
        self.current_job_layer = layer
        self.current_job_ids = set(job.get("ids", []))

        if kind == "polygon":
            ids = sorted(job["ids"])
            self._log(f"\n=== Repair job {self.fix_done_jobs + 1}/{self.fix_total_jobs}: {layer.name()} | Invalid / Wrong-type / Self-Intersection / Duplicate Vertex | features: {len(ids)} ===")
            self.worker = PolygonFixerWorker(layer, True, selected_ids=ids)
            self.worker.finished.connect(self._done_fixer)
        elif kind == "null":
            ids = sorted(job["ids"])
            self._log(f"\n=== Repair job {self.fix_done_jobs + 1}/{self.fix_total_jobs}: {layer.name()} | Null / Empty Geometry | features: {len(ids)} ===")
            self.worker = NullFixerWorker(layer, True, selected_ids=ids)
            self.worker.finished.connect(self._done_null)
        else:  # "quick"
            issues = job["issues"]
            self._log(f"\n=== Repair job {self.fix_done_jobs + 1}/{self.fix_total_jobs}: {layer.name()} | (in-place fixer — not currently used by any error type) | features: {len(issues)} ===")
            self.worker = PluginStyleFixerWorker(layer, issues, delete_null=False)
            self.worker.finished.connect(self._done_quick)

        self.worker.log.connect(self._log)
        self.worker.progress.connect(self._progress_fix_job)
        self.worker.start()

    def _progress_fix_job(self, value):
        if self.fix_total_jobs <= 1:
            self.progress.setValue(value)
        else:
            base = int((self.fix_done_jobs / self.fix_total_jobs) * 100)
            span = int(value / self.fix_total_jobs)
            self.progress.setValue(min(100, base + span))

    def _apply_worker_repaired_geometries(self, worker, layer):
        if not worker or not hasattr(worker, "repaired_geometries") or not worker.repaired_geometries:
            return
        repaired = worker.repaired_geometries
        if not layer or not layer.isValid():
            return
        if not layer.isEditable():
            if not layer.startEditing():
                self._log(f"Could not start editing on {layer.name()} to apply repairs.")
                return
            self._log(f"{layer.name()} is now in edit mode (unsaved). Use QGIS's Save/Cancel Edits to keep or discard.")
        for fid, new_geom in repaired.items():
            if new_geom is not None and not new_geom.isNull():
                layer.changeGeometry(fid, new_geom)
        layer.triggerRepaint()
        self._log(f"Applied {len(repaired)} repaired geometry updates to {layer.name()} in edit mode.")

    def _done_fixer(self, fixed, copied):
        self.fix_done_jobs += 1
        self._apply_worker_repaired_geometries(self.worker, self.current_job_layer)
        self._log(f"Fixed: {fixed}   Left unchanged: {copied}")
        key = self.current_job_layer.id()
        self.fix_edited_layers[key] = self.current_job_layer
        self.fix_touched_fids.setdefault(key, set()).update(getattr(self.worker, "touched_fids", set()))
        self._start_next_fix_job()

    def _done_null(self, recovered, copied, manual):
        self.fix_done_jobs += 1
        self._apply_worker_repaired_geometries(self.worker, self.current_job_layer)
        self._log(f"Recovered: {recovered}   Manual review: {manual}")
        key = self.current_job_layer.id()
        self.fix_edited_layers[key] = self.current_job_layer
        self.fix_touched_fids.setdefault(key, set()).update(getattr(self.worker, "touched_fids", set()))
        self._start_next_fix_job()

    def _done_quick(self, fixed, skipped):
        self.fix_done_jobs += 1
        self._log(f"In-place fix complete. Fixed: {fixed}   Skipped: {skipped}")
        self._start_next_fix_job()

    def _clear_error_highlight(self):
        """Remove any previously drawn error marker/outline from the canvas."""
        canvas = iface.mapCanvas() if (iface and hasattr(iface, "mapCanvas")) else None
        tracked = getattr(canvas, "_geom_toolkit_markers", None) if canvas else None
        if self._error_marker is not None:
            if canvas:
                try:
                    canvas.scene().removeItem(self._error_marker)
                except Exception:
                    pass
            if tracked is not None and self._error_marker in tracked:
                tracked.remove(self._error_marker)
            self._error_marker = None
        if self._error_rubber is not None:
            if canvas:
                try:
                    canvas.scene().removeItem(self._error_rubber)
                except Exception:
                    pass
            if tracked is not None and self._error_rubber in tracked:
                tracked.remove(self._error_rubber)
            self._error_rubber = None

    def _zoom(self, row, _):
        if row >= len(self.issues): return
        d = self.issues[row]
        try:
            layer = d.get("layer")
            canvas = iface.mapCanvas() if (iface and hasattr(iface, "mapCanvas")) else None
            self._clear_error_highlight()
            if not canvas:
                return

            # Fetch the full feature so we have a real reference size for
            # this feature, in its own native units. This is what fixes the
            # "zoom out to the whole world" bug: the old code used a fixed
            # 500-5000 map-unit window (via TopologyError.bbox), which is a
            # sane window in metres but is enormous for a degrees-based
            # (EPSG:4326-style) layer. Scaling to the feature's own extent
            # works the same regardless of whether the layer uses metres,
            # feet, or degrees.
            feat = None
            try:
                feat = next(layer.getFeatures(
                    QgsFeatureRequest(d["feature_id"])
                    .setInvalidGeometryCheck(QgsFeatureRequest.GeometryNoCheck)), None)
            except Exception:
                feat = None
            full_geom = feat.geometry() if feat else d.get("geometry")

            err_geom = d.get("error_location")
            has_precise_point = (
                err_geom is not None and not err_geom.isNull()
                and not err_geom.isEmpty()
                and err_geom.type() == QgsWkbTypes.PointGeometry
            )

            bb = None
            if has_precise_point and full_geom is not None and not full_geom.isNull() and not full_geom.isEmpty():
                feat_bb = full_geom.boundingBox()
                span = max(feat_bb.width(), feat_bb.height())
                half = span * 0.12 if span > 0 else 0
                if half <= 0:
                    # Degenerate/point feature — use a small fraction of the
                    # layer's own extent instead of guessing absolute units.
                    layer_extent = layer.extent()
                    half = max(layer_extent.width(), layer_extent.height()) * 0.01
                pt = err_geom.asPoint()
                bb = QgsRectangle(pt.x() - half, pt.y() - half, pt.x() + half, pt.y() + half)
            elif full_geom is not None and not full_geom.isNull() and not full_geom.isEmpty():
                bb = full_geom.boundingBox(); bb.scale(1.5)

            if bb is None:
                self._log(f"Cannot zoom: FID {d['feature_id']} has Null/Empty geometry.")
                return

            # bb (and any geometry drawn on the canvas) is in the source
            # layer's CRS — reproject to the canvas CRS before applying, so
            # this also behaves correctly on projects using on-the-fly
            # reprojection.
            layer_crs = layer.crs()
            canvas_crs = canvas.mapSettings().destinationCrs()
            xform = None
            if layer_crs.isValid() and canvas_crs.isValid() and layer_crs != canvas_crs:
                try:
                    xform = QgsCoordinateTransform(layer_crs, canvas_crs, QgsProject.instance())
                    bb = xform.transformBoundingBox(bb)
                except Exception as e:
                    self._log(f"CRS transform failed, zoom may be off: {e}")
                    xform = None

            canvas.setExtent(bb); canvas.refresh()

            # ── Visual sign: outline the offending feature in red, and pin
            # an X marker on the exact error vertex/point, so it's obvious
            # at a glance which feature and which spot triggered the error.
            if full_geom is not None and not full_geom.isNull() and not full_geom.isEmpty():
                rb_geom = QgsGeometry(full_geom)
                if xform is not None:
                    try:
                        rb_geom.transform(xform)
                    except Exception:
                        rb_geom = None
                if rb_geom is not None:
                    rb_type = (QgsWkbTypes.PolygonGeometry
                               if full_geom.type() == QgsWkbTypes.PolygonGeometry
                               else QgsWkbTypes.LineGeometry)
                    rb = QgsRubberBand(canvas, rb_type)
                    rb.setColor(QColor(255, 0, 0, 220))
                    rb.setFillColor(QColor(255, 0, 0, 0))  # outline only
                    rb.setWidth(3)
                    rb.setToGeometry(rb_geom, None)
                    self._error_rubber = rb
                    _track_canvas_marker(rb)

            if has_precise_point:
                pt_geom = QgsGeometry(err_geom)
                if xform is not None:
                    try:
                        pt_geom.transform(xform)
                    except Exception:
                        pt_geom = None
                if pt_geom is not None and not pt_geom.isNull():
                    marker = QgsVertexMarker(canvas)
                    marker.setCenter(pt_geom.asPoint())
                    marker.setColor(QColor(255, 0, 0))
                    marker.setIconType(QgsVertexMarker.ICON_X)
                    marker.setIconSize(14)
                    marker.setPenWidth(3)
                    self._error_marker = marker
                    _track_canvas_marker(marker)

            self._log(f"Zoomed to error: FID {d['feature_id']} ({d.get('issue_type', '')}) in {d['layer_name']}")
        except Exception as e:
            self._log(f"Zoom failed: {e}")

    def _clear(self):
        self.issues = []; self.table.setRowCount(0); self._update_error_header_checkbox(); self.log_box.clear()
        self.progress.setValue(0); self.summary.setText("Results cleared.")
        self.fix_btn.setEnabled(False); self.repair_group.setEnabled(False)
        self._clear_error_highlight()


# =============================================================================
# TAB 2 — GEOMETRY FIXER WORKERS
# =============================================================================

class PolygonFixerWorker(QThread):
    """Background worker thread performing in-place geometry repair on polygon layers.

    Applies progressive tolerance sweeps for duplicate node removal, full polygon
    reconstructions (planarization, polygonization, hole assignment), and makeValid
    fallbacks, providing detailed per-feature diagnostic logging when errors cannot
    be automatically repaired.
    """
    log      = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished = pyqtSignal(int, int)   # fixed, copied

    def __init__(self, layer, selected_only, selected_ids=None):
        super().__init__()
        self.layer = layer; self.selected_only = selected_only; self.forced_selected_ids = set(selected_ids or []); self._cancel = False
        self.output_layer = None   # set to the source layer itself once run() starts editing it in place
        self.touched_fids = set()  # attribute tuples of rows this worker actually changed (not copied through)

    def cancel(self): self._cancel = True

    def _clean(self, geom):
        if geom is None or geom.isEmpty(): return None
        g = QgsGeometry(geom)
        try:
            if not g.isGeosValid(): g = g.makeValid()
        except: pass
        if QgsWkbTypes.geometryType(g.wkbType()) == QgsWkbTypes.PolygonGeometry: return g
        try:
            tmp = QgsGeometry(g)
            if tmp.convertGeometryCollectionToSubclass(QgsWkbTypes.PolygonGeometry): return tmp
        except: pass
        return None

    def _force_single(self, geom):
        if geom is None or geom.isEmpty(): return None
        g = QgsGeometry(geom)
        if not g.isMultipart(): return g
        parts = [p for p in g.asGeometryCollection()
                 if p and not p.isEmpty()
                 and QgsWkbTypes.geometryType(p.wkbType()) == QgsWkbTypes.PolygonGeometry]
        return max(parts, key=lambda x: x.area()) if parts else None

    def _is_valid_polygon_geom(self, geom):
        if geom is None or geom.isEmpty():
            return False
        try:
            if QgsWkbTypes.geometryType(geom.wkbType()) != QgsWkbTypes.PolygonGeometry:
                return False
        except Exception:
            return False
        try:
            return geom.isGeosValid()
        except Exception:
            return True

    def _fit_output_wkb(self, geom, output_wkb):
        if geom is None or geom.isEmpty():
            return None
        g = QgsGeometry(geom)
        SINGLE = (QgsWkbTypes.Polygon, QgsWkbTypes.Polygon25D,
                  QgsWkbTypes.PolygonZ, QgsWkbTypes.PolygonM, QgsWkbTypes.PolygonZM)
        if output_wkb in SINGLE or QgsWkbTypes.flatType(output_wkb) == QgsWkbTypes.Polygon:
            g = self._force_single(g)
        else:
            try:
                if QgsWkbTypes.isMultiType(output_wkb) and not g.isMultipart():
                    g.convertToMultiType()
            except Exception:
                pass
        return g

    def _clean_try_makevalid_buffer(self, geom, output_wkb):
        if geom is None or geom.isEmpty():
            return None
        g = self._clean(geom)
        if g is None or g.isEmpty():
            return None
        try:
            if not g.isGeosValid():
                mg = g.makeValid()
                if mg and not mg.isEmpty():
                    g = self._clean(mg)
        except Exception:
            pass
        try:
            if g is not None and not g.isEmpty() and not g.isGeosValid():
                bg = g.buffer(0, 8)
                if bg and not bg.isEmpty():
                    g = self._clean(bg)
        except Exception:
            pass
        g = self._fit_output_wkb(g, output_wkb)
        if self._is_valid_polygon_geom(g):
            return g
        return None

    def _repair_micro_self_intersection_spike(self, geom, output_wkb):
        """Fallback for very small self-intersection spikes/loops on polygon edges.

        Some LGU/PSA boundaries have a tiny folded edge where two vertices cross
        almost at the same location. GEOS makeValid or Polygonize can keep the
        folded edge. This fallback tries conservative cleanup passes only when
        the normal 2_geometry_fixer.py workflow still returns invalid geometry.
        """
        if geom is None or geom.isEmpty():
            return None

        base = QgsGeometry(geom)
        try:
            bb = base.boundingBox()
            diag = ((bb.width() ** 2) + (bb.height() ** 2)) ** 0.5
        except Exception:
            diag = 0
        if not diag or diag <= 0:
            diag = 1.0

        # Very small tolerances first, then slightly stronger tolerances.
        # This is intended for the small red spike/loop shown after zooming in.
        tolerances = [diag * f for f in (1e-12, 5e-12, 1e-11, 5e-11, 1e-10, 5e-10,
                                        1e-9, 5e-9, 1e-8, 5e-8, 1e-7, 5e-7, 1e-6)]
        tried = []
        for tol in tolerances:
            if tol <= 0:
                continue
            # 1) Remove near-duplicate/fold vertices.
            try:
                g1 = QgsGeometry(base)
                g1.removeDuplicateNodes(tol, True)
                tried.append(g1)
            except Exception:
                pass
            # 2) Snap coordinates to a tiny grid to collapse the folded spike.
            try:
                tried.append(base.snappedToGrid(tol, tol))
            except Exception:
                pass
            # 3) Simplify only as later fallback. Very small tolerance is used.
            try:
                tried.append(base.simplify(tol))
            except Exception:
                pass

            for candidate in tried[-3:]:
                fixed = self._clean_try_makevalid_buffer(candidate, output_wkb)
                if fixed and not fixed.isEmpty():
                    return fixed

        return None

    def _raw_makevalid_last_resort(self, geom, output_wkb):
        """Bypass _clean()'s strict Polygon/GeometryCollection filtering and
        accept a raw makeValid() result directly — same approach Topology
        Checker Pro's Auto-Fix uses. Only called after our own multi-step
        cleanup chain (_clean -> polygonize/union -> QGIS Fix Geometries)
        has already failed, so this never overrides a better result."""
        if geom is None or geom.isEmpty():
            return None
        try:
            raw_fix = geom.makeValid()
        except Exception:
            return None
        if not raw_fix or raw_fix.isEmpty():
            return None
        raw_fit = self._fit_output_wkb(raw_fix, output_wkb)
        if raw_fit and self._is_valid_polygon_geom(raw_fit):
            return raw_fit
        return None

    def _finalize_fixed_geom(self, geom, output_wkb):
        """Final safety pass for the Invalid/Wrong-type fixer.

        Main workflow remains from 2_geometry_fixer.py:
        Polygons to Lines → Polygonize → makeValid/GeometryCollection-to-polygon.
        Extra fallback is only used when the normal result is still invalid,
        especially for tiny edge spikes that still report Self-intersection.
        """
        g = self._clean_try_makevalid_buffer(geom, output_wkb)
        if g and not g.isEmpty():
            return g

        # New fallback for tiny folded boundary spike / self-intersection loop.
        g = self._repair_micro_self_intersection_spike(geom, output_wkb)
        if g and not g.isEmpty():
            return g

        return None




    def _qgis_fix_single_feature_fallback(self, source_layer, source_feat, context, feedback):
        """Last-resort fast in-memory GEOS fallback for selected Invalid/Wrong-type features."""
        try:
            geom = source_feat.geometry()
            if geom is None or geom.isEmpty():
                return None
            wkb = source_layer.wkbType()
            g = self._clean_try_makevalid_buffer(geom, wkb)
            if g and not g.isEmpty() and self._is_valid_polygon_geom(g):
                return g
            g = self._repair_micro_self_intersection_spike(geom, wkb)
            if g and not g.isEmpty() and self._is_valid_polygon_geom(g):
                return g
            return None
        except Exception:
            return None

    def _why_unfixable(self, geom):
        """Best-effort, plain-language explanation of why a feature could not be
        repaired, so the log tells the operator what is actually wrong instead of
        only that the attempt failed."""
        if geom is None or geom.isNull() or geom.isEmpty():
            return "the feature has no geometry at all"
        try:
            mv = geom.makeValid()
        except Exception:
            mv = None
        if mv is None or mv.isEmpty():
            return "makeValid() could not produce any geometry from it"
        try:
            gt = QgsWkbTypes.geometryType(mv.wkbType())
        except Exception:
            gt = None
        if gt == QgsWkbTypes.LineGeometry:
            return ("it encloses no area — the outline collapses to a line (a zero-width sliver, "
                    "or vertices that all fall on one straight line), so there is no polygon left "
                    "to rebuild. This feature has to be re-digitised or deleted")
        if gt == QgsWkbTypes.PointGeometry:
            return "it collapses to a single point — the outline has no extent"
        try:
            errs = geom.validateGeometry()
            if errs:
                return errs[0].what()
        except Exception:
            pass
        return "the rebuilt geometry still did not pass the polygon validity check"

    def _make_selected_input_layer(self, source_layer, selected_ids):
        """Create a temporary in-memory polygon layer from the chosen FIDs.

        This avoids the QGIS Processing error where a layer ID coming from the
        viewer table is not found by the child processing context. The geometry
        repair workflow is still the same as 2_geometry_fixer.py: the chosen
        features are the INPUT for Polygons to Lines, then Polygonize.
        """
        tmp = QgsVectorLayer(
            f"{QgsWkbTypes.displayString(source_layer.wkbType())}?crs={source_layer.crs().authid()}",
            source_layer.name() + "_selected_error_input",
            "memory"
        )
        tmp.setCrs(source_layer.crs())
        tmp.dataProvider().addAttributes(source_layer.fields())
        tmp.updateFields()

        req = QgsFeatureRequest().setInvalidGeometryCheck(QgsFeatureRequest.GeometryNoCheck)
        req.setFilterFids(list(selected_ids))
        out_feats = []
        for feat in source_layer.getFeatures(req):
            out = QgsFeature(source_layer.fields())
            out.setAttributes(feat.attributes())
            clean_g = self._clean(feat.geometry())
            if clean_g and not clean_g.isEmpty():
                out.setGeometry(clean_g)
            else:
                out.setGeometry(feat.geometry())
            out_feats.append(out)

        tmp.dataProvider().addFeatures(out_feats)
        tmp.updateExtents()
        return tmp

    def run(self):
        layer = self.layer
        ctx = QgsProcessingContext(); ctx.setProject(QgsProject.instance()); fb = QgsProcessingFeedback()
        SINGLE = (QgsWkbTypes.Polygon, QgsWkbTypes.Polygon25D,
                  QgsWkbTypes.PolygonZ, QgsWkbTypes.PolygonM, QgsWkbTypes.PolygonZM)

        if self.selected_only:
            sel_ids = list(self.forced_selected_ids) if self.forced_selected_ids else list(layer.selectedFeatureIds())
            if not sel_ids:
                self.log.emit("No features selected."); self.finished.emit(0, 0); return

            found_ids = []
            req_check = QgsFeatureRequest().setInvalidGeometryCheck(QgsFeatureRequest.GeometryNoCheck)
            wanted = set(sel_ids)
            for f in layer.getFeatures(req_check):
                if f.id() in wanted:
                    found_ids.append(f.id())

            if not found_ids:
                self.log.emit("Selected error FID(s) were not found in the original layer.")
                self.finished.emit(0, 0); return

            sel_ids = found_ids
            src = self._make_selected_input_layer(layer, sel_ids)
        else:
            req = QgsFeatureRequest().setInvalidGeometryCheck(QgsFeatureRequest.GeometryNoCheck)
            sel_ids = [f.id() for f in layer.getFeatures(req)]
            src = layer

        self.log.emit(f"Features to process: {len(sel_ids)}")
        self.log.emit("Selected feature ID(s): " + ", ".join(str(fid) for fid in sel_ids))
        self.log.emit("Preparing selected feature boundaries…"); self.progress.emit(5)

        # Set up BEFORE the candidate-building steps below. Those steps used to
        # bail out with finished(0, 0) whenever they produced nothing, which
        # returned before this point — so repaired_geometries was never even
        # created, every per-feature fallback below was skipped, and the operator
        # got a single opaque line ("No repair candidate was created.") with no
        # indication of which features were involved or why. The candidate faces
        # are an optimisation, not a prerequisite: the loop below already handles
        # an empty candidate set and repairs each feature on its own.
        self.output_layer = layer
        self.repaired_geometries = {}

        p_feats = []; p_idx = QgsSpatialIndex(); p_lookup = {}
        ll = None; pl = None

        try:
            lr = processing.run("native:polygonstolines", {"INPUT":src,"OUTPUT":"TEMPORARY_OUTPUT"},
                                context=ctx, feedback=fb, is_child_algorithm=False)
            ll = resolve_processing_output_layer(lr["OUTPUT"], ctx)
        except Exception as e:
            self.log.emit(f"Preparing selected feature boundaries failed: {e}")

        if ll is None or ll.featureCount() == 0:
            self.log.emit("No repair boundary could be built from the selected feature(s).")
        else:
            self.log.emit("Building repair candidates…"); self.progress.emit(25)
            try:
                pr = processing.run("native:polygonize", {"INPUT":ll,"KEEP_FIELDS":False,"OUTPUT":"TEMPORARY_OUTPUT"},
                                    context=ctx, feedback=fb, is_child_algorithm=False)
                pl = resolve_processing_output_layer(pr["OUTPUT"], ctx)
            except Exception as e:
                self.log.emit(f"Building repair candidates failed: {e}")

            if pl is None or pl.featureCount() == 0:
                self.log.emit("No repair candidate was created from those boundaries.")
            else:
                self.log.emit(f"Repair candidates created: {pl.featureCount()}")
                self.log.emit("Analyzing repair candidates…"); self.progress.emit(45)
                for pf in pl.getFeatures():
                    cg = self._clean(pf.geometry())
                    if cg is None or cg.isEmpty(): continue
                    pf.setGeometry(cg); p_feats.append(pf); p_idx.addFeature(pf)
                p_lookup = {f.id(): f for f in p_feats}
                if not p_feats:
                    self.log.emit("None of the repair candidates produced a usable polygon.")

        if not p_feats:
            self.log.emit("Continuing without repair candidates — each selected feature will be "
                          "examined individually and reported on below.")

        self.log.emit("Calculating repaired geometries…"); self.progress.emit(60)

        fixed = 0; copied = 0; sel_set = set(sel_ids); total = len(sel_ids)
        req = QgsFeatureRequest().setInvalidGeometryCheck(QgsFeatureRequest.GeometryNoCheck).setFilterFids(sel_ids)

        for i, feat in enumerate(layer.getFeatures(req)):
            if self._cancel: break
            if total: self.progress.emit(60 + int((i / total) * 35))
            orig = feat.geometry()
            new_geom = None  # left None means "no change needed / could not fix"

            if orig is not None and not orig.isEmpty() and orig.isGeosValid() and orig.isSimple():
                deduped = None
                had_dupes = False        # True only if removeDuplicateNodes() actually removed something

                try:
                    bb = orig.boundingBox()
                    diag = ((bb.width() ** 2) + (bb.height() ** 2)) ** 0.5
                except Exception:
                    diag = 0
                if not diag or diag <= 0:
                    diag = 1.0

                for scale in (1e-12, 5e-12, 1e-11, 5e-11, 1e-10, 5e-10,
                              1e-9, 5e-9, 1e-8, 5e-8, 1e-7, 5e-7, 1e-6):
                    tol = diag * scale
                    if tol <= 0:
                        continue
                    try:
                        candidate = QgsGeometry(orig)
                        changed = candidate.removeDuplicateNodes(tol, False)
                    except Exception:
                        continue
                    if not changed:
                        continue
                    try:
                        remaining = candidate.validateGeometry()
                    except Exception:
                        remaining = []
                    if not remaining:
                        deduped = candidate
                        had_dupes = True
                        break
                    if deduped is None:
                        deduped = candidate
                        had_dupes = True

                if not had_dupes or (deduped is not None and deduped.validateGeometry()):
                    try:
                        mv_src = deduped if (deduped is not None and not deduped.isEmpty()) else orig
                        mv = mv_src.makeValid()
                        if mv and not mv.isEmpty() and not mv.validateGeometry():
                            deduped = mv
                            # NOTE: deliberately does NOT set had_dupes. This path
                            # removed no vertices, and claiming otherwise is what made
                            # the log report "repaired by removing duplicate vertex(es)"
                            # for features that were already clean.
                    except Exception:
                        pass

                # A repair only counts if the geometry actually changed. Without this
                # guard the makeValid() fallback above reported every already-clean
                # feature as repaired — inflating "Fixed: n" and marking the layer
                # modified for nothing (re-running Repair without re-scanning did
                # exactly that, reporting Fixed: 3 on features fixed in the first pass).
                # NOTE: equals() alone is the wrong test here — it compares shape,
                # and deleting a duplicate vertex does not change the shape, so a
                # genuine dedup would look like a no-op. Treat it as unchanged only
                # when the shape AND the vertex count both match.
                candidate_geom = deduped if (deduped is not None and not deduped.isEmpty()) else None
                if candidate_geom is not None:
                    try:
                        same_shape = orig.equals(candidate_geom)
                        same_verts = (sum(1 for _ in orig.vertices())
                                      == sum(1 for _ in candidate_geom.vertices()))
                        if same_shape and same_verts:
                            candidate_geom = None
                    except Exception:
                        pass

                if candidate_geom is not None:
                    new_geom = candidate_geom
                    fixed += 1
                    if had_dupes:
                        self.log.emit(f"   FID {feat.id()} repaired by removing duplicate/near-duplicate vertex(es).")
                    else:
                        self.log.emit(f"   FID {feat.id()} repaired by makeValid() — no duplicate vertex was present.")
                else:
                    try:
                        v_errs = orig.validateGeometry()
                    except Exception:
                        v_errs = []
                    if not v_errs:
                        # Nothing is wrong with it any more — typically Repair was run
                        # a second time without re-running Check, so the table still
                        # lists rows that have already been fixed. Not a failure, and
                        # not something to send the operator off to fix by hand.
                        self.log.emit(f"   FID {feat.id()} is already valid — nothing to repair. "
                                      f"(Re-run Check Selected Layers to refresh the error list.)")
                    else:
                        copied += 1
                        self.log.emit(
                            f"   FID {feat.id()} could NOT be repaired automatically. "
                            f"Reason: {v_errs[0].what()}. There is no duplicate node to delete, and "
                            f"makeValid() leaves the geometry unchanged because GEOS already considers "
                            f"it valid. {MANUAL_HINT}")

                if new_geom is not None:
                    self.repaired_geometries[feat.id()] = new_geom
                    self.touched_fids.add(feat.id())
                continue

            co = self._clean(orig)
            if co is None or co.isEmpty():
                try: co = self._clean(orig.makeValid())
                except: co = None

            if co is None or co.isEmpty():
                qfix = self._qgis_fix_single_feature_fallback(layer, feat, ctx, fb)
                if qfix and not qfix.isEmpty():
                    new_geom = qfix; fixed += 1
                    self.log.emit(f"   FID {feat.id()} repaired using QGIS Fix Geometries fallback.")
                else:
                    raw_fit = self._raw_makevalid_last_resort(orig, layer.wkbType())
                    if raw_fit:
                        new_geom = raw_fit; fixed += 1
                        self.log.emit(f"   FID {feat.id()} repaired using raw makeValid() last-resort fallback.")
                    else:
                        copied += 1
                        self.log.emit(f"   FID {feat.id()} could NOT be repaired automatically. "
                                      f"Reason: {self._why_unfixable(orig)}. {MANUAL_HINT}")
            else:
                cands = []
                for cid in p_idx.intersects(co.boundingBox()):
                    pf = p_lookup.get(cid)
                    if not pf: continue
                    pg = pf.geometry()
                    if pg is None or pg.isEmpty(): continue
                    try:
                        if pg.intersects(co):
                            inter = pg.intersection(co)
                            if inter and not inter.isEmpty() and inter.area() > 0:
                                cands.append(inter)
                    except:
                        if pg.boundingBox().intersects(co.boundingBox()):
                            try:
                                clipped = pg.intersection(co)
                                cands.append(clipped if clipped and not clipped.isEmpty() else pg)
                            except:
                                cands.append(pg)

                if cands:
                    try:
                        ng = QgsGeometry.unaryUnion(cands)
                    except Exception:
                        ng = None
                    ng = self._finalize_fixed_geom(ng, layer.wkbType()) if ng else None
                    if ng and not ng.isEmpty():
                        new_geom = ng; fixed += 1
                    else:
                        fallback = self._finalize_fixed_geom(co, layer.wkbType())
                        if fallback and not fallback.isEmpty():
                            new_geom = fallback; fixed += 1
                            self.log.emit(f"   FID {feat.id()} polygonized union still invalid — used makeValid fallback.")
                        else:
                            qfix = self._qgis_fix_single_feature_fallback(layer, feat, ctx, fb)
                            if qfix and not qfix.isEmpty():
                                new_geom = qfix; fixed += 1
                                self.log.emit(f"   FID {feat.id()} repaired using QGIS Fix Geometries fallback.")
                            else:
                                raw_fit = self._raw_makevalid_last_resort(orig, layer.wkbType())
                                if raw_fit:
                                    new_geom = raw_fit; fixed += 1
                                    self.log.emit(f"   FID {feat.id()} repaired using raw makeValid() last-resort fallback.")
                                else:
                                    copied += 1
                                    # This was the only silent failure in the loop —
                                    # it produced "Fixed: 0  Left unchanged: n" with no
                                    # per-feature line, leaving nothing to diagnose.
                                    self.log.emit(f"   FID {feat.id()} could NOT be repaired automatically. "
                                                  f"Reason: {self._why_unfixable(orig)}. {MANUAL_HINT}")
                else:
                    fallback = self._finalize_fixed_geom(co, layer.wkbType())
                    if fallback and not fallback.isEmpty():
                        new_geom = fallback; fixed += 1
                        self.log.emit(f"   FID {feat.id()} no polygonized match — used makeValid fallback.")
                    else:
                        qfix = self._qgis_fix_single_feature_fallback(layer, feat, ctx, fb)
                        if qfix and not qfix.isEmpty():
                            new_geom = qfix; fixed += 1
                            self.log.emit(f"   FID {feat.id()} repaired using QGIS Fix Geometries fallback.")
                        else:
                            raw_fit = self._raw_makevalid_last_resort(orig, layer.wkbType())
                            if raw_fit:
                                new_geom = raw_fit; fixed += 1
                                self.log.emit(f"   FID {feat.id()} repaired using raw makeValid() last-resort fallback.")
                            else:
                                copied += 1
                                self.log.emit(f"   FID {feat.id()} could NOT be repaired automatically. "
                                              f"Reason: {self._why_unfixable(orig)}. {MANUAL_HINT}")

            if new_geom is not None:
                try:
                    if not new_geom.isEmpty() and not new_geom.isGeosValid():
                        spikefix = self._repair_micro_self_intersection_spike(new_geom, layer.wkbType())
                        if spikefix and not spikefix.isEmpty() and spikefix.isGeosValid():
                            new_geom = spikefix
                            self.log.emit(f"   FID {feat.id()} final validation repaired by micro-spike/self-intersection fallback.")
                        else:
                            qfix = self._qgis_fix_single_feature_fallback(layer, feat, ctx, fb)
                            if qfix and not qfix.isEmpty() and qfix.isGeosValid():
                                new_geom = qfix
                                self.log.emit(f"   FID {feat.id()} final validation repaired by QGIS Fix Geometries fallback.")
                except Exception:
                    pass

                self.repaired_geometries[feat.id()] = new_geom
                self.touched_fids.add(feat.id())

        self.progress.emit(100)
        self.log.emit(f"\nFinished. Fixed: {fixed}   Needs manual repair: {copied}")
        if copied:
            self.log.emit(f"   {copied} feature(s) could not be repaired automatically — see the "
                          f"'could NOT be repaired' line(s) above for the reason on each one.")
        if fixed:
            self.log.emit(f"   The {fixed} repaired feature(s) are UNSAVED. Use Layer > Save Layer Edits "
                          f"on '{layer.name()}' to keep them — Cancel Edits will discard every repair.")
        self.finished.emit(fixed, copied)


class NullFixerWorker(QThread):
    """Background worker thread recovering missing or null geometries from surrounding polygons."""
    log      = pyqtSignal(str)
    progress = pyqtSignal(int)
    finished = pyqtSignal(int, int, int)   # recovered, copied, manual

    def __init__(self, layer, selected_only, selected_ids=None):
        super().__init__()
        self.layer = layer; self.selected_only = selected_only; self.forced_selected_ids = set(selected_ids or []); self._cancel = False
        self.output_layer = None   # set to the source layer itself
        self.touched_fids = set()  # attribute tuples of rows this worker actually changed (not copied through)
        self.repaired_geometries = {}

    def cancel(self): self._cancel = True

    def _clean(self, geom):
        if geom is None or geom.isEmpty(): return None
        g = QgsGeometry(geom)
        try:
            if not g.isGeosValid(): g = g.makeValid()
        except: pass
        if QgsWkbTypes.geometryType(g.wkbType()) == QgsWkbTypes.PolygonGeometry: return g
        try:
            tmp = QgsGeometry(g)
            if tmp.convertGeometryCollectionToSubclass(QgsWkbTypes.PolygonGeometry): return tmp
        except: pass
        return None

    def _force_single(self, geom):
        if geom is None or geom.isEmpty(): return None
        g = QgsGeometry(geom)
        if not g.isMultipart(): return g
        parts = [p for p in g.asGeometryCollection()
                 if p and not p.isEmpty()
                 and QgsWkbTypes.geometryType(p.wkbType()) == QgsWkbTypes.PolygonGeometry]
        return max(parts, key=lambda x: x.area()) if parts else None

    def _match_type(self, geom, wkb):
        if geom is None or geom.isEmpty(): return None
        g = QgsGeometry(geom)
        SINGLE = (QgsWkbTypes.Polygon, QgsWkbTypes.Polygon25D,
                  QgsWkbTypes.PolygonZ, QgsWkbTypes.PolygonM, QgsWkbTypes.PolygonZM)
        if wkb in SINGLE or QgsWkbTypes.flatType(wkb) == QgsWkbTypes.Polygon:
            return self._force_single(g)
        try:
            if QgsWkbTypes.isMultiType(wkb) and not g.isMultipart():
                g.convertToMultiType()
        except Exception:
            pass
        return g

    def run(self):
        layer = self.layer
        ctx = QgsProcessingContext(); fb = QgsProcessingFeedback()
        sel_ids = set(self.forced_selected_ids) if self.forced_selected_ids else set(layer.selectedFeatureIds())

        if self.selected_only and not sel_ids:
            self.log.emit("No features selected."); self.finished.emit(0, 0, 0); return

        req = QgsFeatureRequest().setInvalidGeometryCheck(QgsFeatureRequest.GeometryNoCheck)
        missing_ids = []; valid_feats = []; valid_geoms = []

        self.log.emit("Scanning layer…")
        for feat in layer.getFeatures(req):
            if self._cancel: break
            geom = feat.geometry()
            is_miss = (geom is None or geom.isNull() or geom.isEmpty())
            if self.selected_only:
                if feat.id() in sel_ids and is_miss: missing_ids.append(feat.id())
                elif not is_miss:
                    cg = self._clean(geom)
                    if cg and not cg.isEmpty(): valid_feats.append((feat, cg)); valid_geoms.append(cg)
            else:
                if is_miss: missing_ids.append(feat.id())
                else:
                    cg = self._clean(geom)
                    if cg and not cg.isEmpty(): valid_feats.append((feat, cg)); valid_geoms.append(cg)

        self.log.emit(f"Missing Null/Empty: {len(missing_ids)}")
        if missing_ids:
            self.log.emit("Selected feature ID(s): " + ", ".join(str(fid) for fid in missing_ids))
        self.log.emit(f"Valid surrounding polygons: {len(valid_feats)}")

        if not missing_ids:
            self.log.emit("No Null/Empty features found."); self.finished.emit(0, 0, 0); return
        if not valid_feats:
            self.log.emit("No valid surrounding polygons found."); self.finished.emit(0, 0, 0); return

        self.progress.emit(10)
        valid_lyr = QgsVectorLayer(
            f"{QgsWkbTypes.displayString(layer.wkbType())}?crs={layer.crs().authid()}",
            "_valid_surround", "memory")
        valid_lyr.setCrs(layer.crs())
        valid_lyr.dataProvider().addAttributes(layer.fields()); valid_lyr.updateFields()
        vf = []
        for feat, cg in valid_feats:
            f = QgsFeature(layer.fields()); f.setAttributes(feat.attributes()); f.setGeometry(cg); vf.append(f)
        valid_lyr.dataProvider().addFeatures(vf); valid_lyr.updateExtents()

        union_geom = QgsGeometry.unaryUnion(valid_geoms); union_geom = self._clean(union_geom)
        if union_geom is None or union_geom.isEmpty():
            self.log.emit("Could not build union coverage."); self.finished.emit(0, 0, 0); return

        self.log.emit("Preparing surrounding boundaries…"); self.progress.emit(20)
        try:
            lr = processing.run("native:polygonstolines", {"INPUT":valid_lyr,"OUTPUT":"TEMPORARY_OUTPUT"},
                                context=ctx, feedback=fb, is_child_algorithm=False)
            ll = resolve_processing_output_layer(lr["OUTPUT"], ctx)
        except Exception as e:
            self.log.emit(f"Preparing selected feature boundaries failed: {e}"); self.finished.emit(0, 0, 0); return

        self.log.emit("Searching for recoverable missing areas…"); self.progress.emit(45)
        try:
            pr = processing.run("native:polygonize", {"INPUT":ll,"KEEP_FIELDS":False,"OUTPUT":"TEMPORARY_OUTPUT"},
                                context=ctx, feedback=fb, is_child_algorithm=False)
            pl = resolve_processing_output_layer(pr["OUTPUT"], ctx)
        except Exception as e:
            self.log.emit(f"Building repair candidates failed: {e}"); self.finished.emit(0, 0, 0); return

        if pl is None or pl.featureCount() == 0:
            self.log.emit("No repair candidate was created."); self.finished.emit(0, 0, 0); return
        self.log.emit(f"Recovery candidates created: {pl.featureCount()}")

        self.log.emit("Evaluating recovery candidates…"); self.progress.emit(65)
        cand_gaps = []
        for pf in pl.getFeatures():
            if self._cancel: break
            pg = self._clean(pf.geometry())
            if pg is None or pg.isEmpty() or pg.area() <= 0: continue
            try:
                inter = pg.intersection(union_geom)
                ia = inter.area() if inter and not inter.isEmpty() else 0.0
            except: ia = 0.0
            ratio = ia / pg.area() if pg.area() > 0 else 1.0
            if ratio < 0.01:
                cand_gaps.append(pg)
                self.log.emit(f"  Gap face: area={pg.area():,.4f}  ratio={ratio:.4f}")

        self.log.emit(f"Recoverable candidate areas: {len(cand_gaps)}"); self.progress.emit(80)

        recover_map = {}; gap_area = None
        method_txt = "Not recovered"; note_txt = ""

        if len(missing_ids) == 1 and len(cand_gaps) == 1:
            sg = self._match_type(cand_gaps[0], layer.wkbType())
            recover_map[missing_ids[0]] = sg; gap_area = sg.area()
            method_txt = "Polygonized missing face"
            note_txt   = "Exactly 1 missing + 1 gap face."
            self.log.emit(" Auto-recovered: 1 missing → 1 gap face.")
        elif len(missing_ids) == 1 and len(cand_gaps) > 1:
            sg = self._match_type(max(cand_gaps, key=lambda g: g.area()), layer.wkbType())
            recover_map[missing_ids[0]] = sg; gap_area = sg.area()
            method_txt = "Largest polygonized face"
            note_txt   = f"1 missing + {len(cand_gaps)} candidates → largest assigned. Review carefully."
            self.log.emit(f"Multiple candidates — assigned largest (area={gap_area:,.4f}).")
        else:
            note_txt = f"Missing: {len(missing_ids)}, candidates: {len(cand_gaps)}. Safe auto-match not possible."
            self.log.emit("Auto-recovery not applied — " + note_txt)

        self.output_layer = layer
        self.repaired_geometries = {}

        recovered = 0; copied = 0; manual = 0; total = len(missing_ids)
        for i, fid in enumerate(missing_ids):
            if self._cancel: break
            if total: self.progress.emit(80 + int((i / total) * 18))
            if fid in recover_map:
                self.repaired_geometries[fid] = recover_map[fid]
                recovered += 1
                self.touched_fids.add(fid)
                self.log.emit(f"FID {fid}: Recovered. Method: {method_txt}. Note: {note_txt}")
            else:
                manual += 1
                self.log.emit(f"FID {fid}: Manual review required. Method: Not recovered. Note: {note_txt}")

        self.progress.emit(100)
        self.log.emit(f"\nFinished.  Recovered: {recovered}   Manual: {manual}   "
                      f"(unsaved — edit {layer.name()} to keep, or Cancel Edits to discard)")
        self.finished.emit(recovered, copied, manual)


# =============================================================================
# TAB 2 — GEOMETRY FIXER UI  (single tab, mode switcher)
# =============================================================================

# Info text shown in the hint panel per mode
MODE_INFO = {
    0: (
        "Fix Mode: Polygon Fix\n\n"
        " Self-intersections / Bowties\n"
        " Ring self-intersection\n"
        " Duplicate vertices\n"
        " Spikes / slivers\n"
        " GeometryCollection to Polygon\n\n"
        " Null / Empty geometry\n"
        "   → switch to Null / Empty mode"
    ),
    1: (
        "Fix Mode: Null / Empty Fix\n\n"
        " Null Geometry  (record exists)\n"
        " Empty Geometry  (POLYGON EMPTY)\n"
        " Missing / Corrupted geometry\n\n"
        "Requires surrounding valid polygons\n"
        "to reconstruct the missing face.\n\n"
        "Adds recovery_status, recovery_method,\n"
        "recovery_note, candidate_gap_count,\n"
        "selected_gap_area fields to output.\n\n"
        " Deleted features (no record)\n"
        " Point / open LineString geometry"
    ),
}


class GeometryFixerTab(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6); root.setSpacing(8)

        # ── LEFT ──────────────────────────────────────────────────────
        left = QWidget(); left.setFixedWidth(290)
        ll = QVBoxLayout(left); ll.setContentsMargins(0, 0, 0, 0); ll.setSpacing(8)

        # Fix Mode selector
        mode_grp = QGroupBox("Fix Mode"); mode_grp.setStyleSheet(GRP_STYLE)
        mg = QVBoxLayout(mode_grp)
        self.radio_polygon  = QRadioButton("Polygon Fix  (Invalid Geometry)")
        self.radio_null     = QRadioButton("Null/Empty Fixer  (Missing Geometry)")
        self.radio_polygon.setChecked(True)
        self.mode_group = QButtonGroup()
        self.mode_group.addButton(self.radio_polygon, 0)
        self.mode_group.addButton(self.radio_null,    1)
        mg.addWidget(self.radio_polygon); mg.addWidget(self.radio_null)
        ll.addWidget(mode_grp)

        # Layer selector
        layer_grp = QGroupBox("Input Layer"); layer_grp.setStyleSheet(GRP_STYLE)
        lg = QVBoxLayout(layer_grp)
        lg.addWidget(QLabel("Polygon layer:"))
        self.layer_combo = QComboBox(); self._fill_combo()
        lg.addWidget(self.layer_combo)
        self.sel_only = QCheckBox("Selected Features Only")
        self.sel_only.setChecked(True)
        lg.addWidget(self.sel_only)
        ll.addWidget(layer_grp)

        # Dynamic hint panel
        hint_grp = QGroupBox("Info"); hint_grp.setStyleSheet(GRP_STYLE)
        hg = QVBoxLayout(hint_grp)
        self.hint_label = QLabel(MODE_INFO[0])
        self.hint_label.setStyleSheet("font-size:11px; color:#37474f;")
        self.hint_label.setWordWrap(True)
        hg.addWidget(self.hint_label)
        ll.addWidget(hint_grp)

        # Buttons
        self.run_btn    = QPushButton("Run");       self.run_btn.setFixedHeight(32);    self.run_btn.setStyleSheet(BTN_RUN)
        self.cancel_btn = QPushButton("Cancel");     self.cancel_btn.setFixedHeight(32); self.cancel_btn.setStyleSheet(BTN_CANCEL); self.cancel_btn.setEnabled(False)
        self.clear_btn  = QPushButton("Clear Log"); self.clear_btn.setFixedHeight(32);  self.clear_btn.setStyleSheet(BTN_CLEAR)
        r1 = QHBoxLayout(); r1.addWidget(self.run_btn); r1.addWidget(self.cancel_btn); ll.addLayout(r1)
        ll.addWidget(self.clear_btn)

        self.progress = make_progress(); ll.addWidget(self.progress)
        ll.addStretch()

        # ── RIGHT ─────────────────────────────────────────────────────
        right = QWidget(); rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(6)

        self.summary = QLabel("Ready.")
        self.summary.setStyleSheet("font-size:13px; font-weight:600; color:#37474f;")
        rl.addWidget(self.summary)

        self.log_box = QTextEdit(); self.log_box.setReadOnly(True)
        self.log_box.setStyleSheet(LOG_STYLE)
        self.log_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        rl.addWidget(self.log_box, stretch=1)

        root.addWidget(left); root.addWidget(right, stretch=1)

        # Signals
        self.run_btn.clicked.connect(self._run)
        self.cancel_btn.clicked.connect(self._cancel)
        self.clear_btn.clicked.connect(lambda: self.log_box.clear())
        self.mode_group.buttonToggled.connect(self._on_mode_changed)

    # ------------------------------------------------------------------
    def _fill_combo(self):
        self.layer_combo.clear(); self._lmap = {}
        for lid, lyr in get_polygon_layers().items():
            self.layer_combo.addItem(lyr.name(), lid); self._lmap[lid] = lyr

    def _current_mode(self):
        return self.mode_group.checkedId()   # 0 = Polygon Fix, 1 = Null/Empty

    def _on_mode_changed(self):
        mode = self._current_mode()
        self.hint_label.setText(MODE_INFO[mode])
        # Adjust checkbox label to match mode
        self.sel_only.setText(
            "Selected Null/Empty Features Only" if mode == 1
            else "Selected Features Only"
        )

    def _log(self, msg): self.log_box.append(msg)

    def _run(self):
        lid = self.layer_combo.currentData()
        if lid is None or lid not in self._lmap:
            return QMessageBox.warning(self, "No Layer", "Select a polygon layer.")
        layer = self._lmap[lid]
        self.log_box.clear(); self.progress.setValue(0); self.summary.setText("Running…")
        self.run_btn.setEnabled(False); self.cancel_btn.setEnabled(True)

        if self._current_mode() == 0:
            self.worker = PolygonFixerWorker(layer, self.sel_only.isChecked())
            self.worker.finished.connect(self._done_fixer)
        else:
            self.worker = NullFixerWorker(layer, self.sel_only.isChecked())
            self.worker.finished.connect(self._done_null)

        self.worker.log.connect(self._log)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.start()

    def _cancel(self):
        if self.worker: self.worker.cancel(); self._log("Cancelled.")
        self.run_btn.setEnabled(True); self.cancel_btn.setEnabled(False)

    def _done_fixer(self, fixed, copied):
        self.run_btn.setEnabled(True); self.cancel_btn.setEnabled(False)
        self.summary.setText(f"Done - Fixed: {fixed}   Copied: {copied}")

    def _done_null(self, recovered, copied, manual):
        self.run_btn.setEnabled(True); self.cancel_btn.setEnabled(False)
        self.summary.setText(f"Done - Recovered: {recovered}   Manual review: {manual}   Copied: {copied}")




# =============================================================================
# TAB 2 — HELP, TOOLTIP, AND DESCRIPTION
# =============================================================================

class HelpInfoTab(QWidget):
    """Embedded HTML documentation and reference guide tab for Geometry Repair Toolkit."""
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
              Geometry Repair Toolkit
            </h2>
            <div style="color: #4b5563; font-size: 12px;">
              Direct In-Place Topology Validation and Automated Polygon Geometry Reconstruction
            </div>
          </div>

          <!-- Overview & In-Place Editing -->
          <div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-left: 4px solid #4b5563; padding: 10px 14px; margin-bottom: 16px;">
            <b style="color: #111827;">In-Place Editing Mode:</b>
            <span style="color: #374151;">
              This tool checks polygon layers for geometry errors and repairs them directly on the <b>original layer</b>. Features are edited in-place inside QGIS's active editing mode (unsaved buffer marked with a pencil icon). No duplicate output layers are created. You can inspect changes on the map canvas and choose <b>Save Edits</b> to write to disk or <b>Cancel Edits</b> to discard and revert to the original state.
            </span>
          </div>

          <!-- Section 1: How to Use -->
          <h3 style="color: #111827; font-size: 14px; font-weight: bold; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; margin-top: 16px; margin-bottom: 10px;">
            How to Use
          </h3>
          <table width="100%" cellpadding="6" cellspacing="0" style="border-collapse: collapse; margin-bottom: 16px; border: 1px solid #e5e7eb; font-size: 11px;">
            <tr style="background-color: #ffffff;">
              <td width="65" style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">Step 1</td>
              <td style="border-bottom: 1px solid #f3f4f6;"><b>Select Input Layers:</b> Select one or more polygon layers from the <i>Input Layers</i> list.</td>
            </tr>
            <tr style="background-color: #f9fafb;">
              <td style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">Step 2</td>
              <td style="border-bottom: 1px solid #f3f4f6;"><b>Scan Layers:</b> Click <i>Scan Layers</i> to execute multi-threaded geometry checks across selected layers.</td>
            </tr>
            <tr style="background-color: #ffffff;">
              <td style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">Step 3</td>
              <td style="border-bottom: 1px solid #f3f4f6;"><b>Inspect Detected Errors:</b> Review issues in the results table. Double-click any row to zoom and highlight the defect on the map canvas with bounding outlines and vertex markers.</td>
            </tr>
            <tr style="background-color: #f9fafb;">
              <td style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">Step 4</td>
              <td style="border-bottom: 1px solid #f3f4f6;"><b>Select Errors to Repair:</b> Check individual rows or click the checkbox in the table header to select or clear all auto-fixable errors at once.</td>
            </tr>
            <tr style="background-color: #ffffff;">
              <td style="font-weight: bold; vertical-align: top; border-bottom: 1px solid #f3f4f6; color: #111827;">Step 5</td>
              <td style="border-bottom: 1px solid #f3f4f6;"><b>Repair Selected Features:</b> Click <i>Repair Selected Features</i>. The toolkit automatically routes each checked row to its specific repair mechanism directly on the source layer.</td>
            </tr>
            <tr style="background-color: #f9fafb;">
              <td style="font-weight: bold; vertical-align: top; color: #111827;">Step 6</td>
              <td><b>Verify & Commit:</b> Re-run <i>Scan Layers</i> to confirm all errors are resolved on the unsaved layer. Use QGIS's <b>Save Edits</b> to write changes to disk, or <b>Cancel Edits</b> to discard.</td>
            </tr>
          </table>

          <!-- Section 2: Error Types Reference Table -->
          <h3 style="color: #111827; font-size: 14px; font-weight: bold; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; margin-top: 16px; margin-bottom: 10px;">
            Error Types Reference
          </h3>
          <table width="100%" cellpadding="6" cellspacing="0" style="border-collapse: collapse; margin-bottom: 16px; border: 1px solid #d1d5db; font-size: 11px;">
            <thead>
              <tr style="background-color: #f3f4f6; color: #111827; text-align: left;">
                <th style="border: 1px solid #d1d5db; padding: 7px 10px; width: 170px;">Error Type</th>
                <th style="border: 1px solid #d1d5db; padding: 7px 10px;">Description</th>
                <th style="border: 1px solid #d1d5db; padding: 7px 10px; width: 220px;">Repair Mechanism</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">Null Geometry</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">The feature record exists, but there is no geometry object.</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Spatial gap recovery from surrounding polygons.</td>
              </tr>
              <tr style="background-color: #f9fafb;">
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">Empty/Missing Geometry</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">The feature exists, but its geometry has no usable shape or coordinates.</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Spatial void recovery from surrounding polygons.</td>
              </tr>
              <tr>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">Invalid Geometry</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">The polygon has geometry errors such as ring errors, spikes, or folded edges.</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Thorough polygon reconstruction.</td>
              </tr>
              <tr style="background-color: #f9fafb;">
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">Self Intersection</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">The polygon boundary crosses itself (e.g. bowtie or figure-8 loop).</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Thorough polygon reconstruction.</td>
              </tr>
              <tr>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">Wrong-type Geometry</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">The feature's geometry type does not match the layer's declared geometry type (e.g. a line or GeometryCollection stored in a polygon layer).</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Thorough polygon reconstruction.</td>
              </tr>
              <tr style="background-color: #f9fafb;">
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">Duplicate Vertex</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Commonly an accidental self-snap made while manually digitizing a polygon (a duplicate/near-duplicate vertex or zero-length segment). Reported only when QGIS's validator actually names a duplicate node.</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">Direct duplicate vertex removal via progressive tolerance sweep.</td>
              </tr>
              <tr>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; font-weight: bold;">Ring/Structure Error</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px;">GEOS accepts the geometry, but QGIS's internal validator objects to how its rings or parts are arranged &mdash; e.g. a hole (interior ring) that is not fully inside its outer ring, or a part nested inside another part.</td>
                <td style="border: 1px solid #e5e7eb; padding: 6px 10px; color: #b45309;"><b>No automatic repair.</b> There is no vertex to delete and makeValid() leaves it unchanged. Correct the ring manually with the Vertex Tool.</td>
              </tr>
            </tbody>
          </table>

          <!-- Section 3: Repair Mechanics & Original Layer Editing -->
          <h3 style="color: #111827; font-size: 14px; font-weight: bold; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; margin-top: 16px; margin-bottom: 10px;">
            Repair Selected Features & In-Place Processing
          </h3>
          <p style="margin: 0 0 10px 0;">
            Clicking <b>Repair Selected Features</b> inspects each checked error row and automatically routes it to the correct repair mechanism directly on the source layer:
          </p>
          <ul style="margin: 0 0 12px 0; padding-left: 20px;">
            <li style="margin-bottom: 4px;"><b>Invalid Geometry / Wrong-type Geometry / Self Intersection:</b> Thorough polygon reconstruction (ring decomposition, unary union planarization, face matching, and hole restoration).</li>
            <li style="margin-bottom: 4px;"><b>Duplicate Vertex:</b> Removes duplicate and near-duplicate vertices directly via progressive tolerance sweep ($10^{-12}$ to $10^{-6}$ bbox scale) and node-clustering deduplication.</li>
            <li style="margin-bottom: 4px;"><b>Null / Empty / Missing Geometry:</b> Recovers missing geometry from surrounding polygon spatial boundary context.</li>
            <li style="margin-bottom: 4px;"><b>Ring/Structure Error:</b> <span style="color: #b45309;">Not repaired automatically.</span> These rows stay greyed out with the checkbox disabled, because no automatic mechanism can fix them &mdash; they must be corrected by hand.</li>
          </ul>
          <p style="margin: 0 0 12px 0;">
            <b>When a feature cannot be repaired:</b> the log names the feature and states the reason &mdash; for example
            <i>"FID 12 could NOT be repaired automatically. Reason: it encloses no area &mdash; the outline collapses to a line&hellip;"</i>
            &mdash; followed by a prompt to check it manually. The run summary reports these as
            <b>Needs manual repair</b>, separately from the features it fixed. A feature that reports
            <i>"encloses no area"</i> has to be re-digitised or deleted; nothing can rebuild a polygon that has none.
          </p>
          <p style="margin: 0 0 10px 0;">
            <b>Multipart Resolution & Sliver Cleanup:</b> Polygon reconstruction can occasionally produce multiple parts when resolving a self-intersecting bowtie shape. The toolkit automatically drops negligible artifact slivers (< 0.1% area ratio) and keeps the union of real parts. Pre-existing legitimate multipart features that were not repaired are left completely untouched.
          </p>
          <p style="margin: 0 0 12px 0;">
            <b>Multiple Error Types on One Feature:</b> When a feature has multiple geometry defects (such as Invalid Geometry + Self Intersection), they are processed together or can be re-scanned and repaired in sequence.
          </p>

          <!-- Section 4: Review and Limitations -->
          <h3 style="color: #111827; font-size: 14px; font-weight: bold; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; margin-top: 16px; margin-bottom: 10px;">
            Review and Limitations
          </h3>
          <ul style="margin: 0 0 14px 0; padding-left: 20px;">
            <li style="margin-bottom: 4px;">Always visually inspect repaired features before saving edits to disk.</li>
            <li style="margin-bottom: 4px;">Re-run <b>Scan Layers</b> on the layer while still in edit mode to confirm all errors are resolved.</li>
            <li style="margin-bottom: 4px;">Completely deleted attribute records cannot be recovered by this tool.</li>
            <li style="margin-bottom: 4px;">Outer boundary edge polygons cannot be safely reconstructed when adjacent boundaries are unknown (return to LGU for corrected boundary geometry).</li>
            <li style="margin-bottom: 4px;"><b>CRS Reprojection:</b> Validity is evaluated in the layer's native CRS. Reprojecting a layer shifts vertices slightly and can alter geometry validity; always re-run Scan Layers after reprojection.</li>
          </ul>

          <!-- Section 5: Map Canvas & Table Controls -->
          <h3 style="color: #111827; font-size: 14px; font-weight: bold; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; margin-top: 16px; margin-bottom: 10px;">
            Map Canvas & Table Controls
          </h3>
          <table width="100%" cellpadding="6" cellspacing="0" style="border-collapse: collapse; margin-bottom: 16px; border: 1px solid #e5e7eb; font-size: 11px;">
            <tr style="background-color: #f9fafb;">
              <td width="160" style="font-weight: bold; border-bottom: 1px solid #e5e7eb;">Double-Click Error Row</td>
              <td style="border-bottom: 1px solid #e5e7eb;">Pans and zooms the map canvas to the feature and places a red outline and vertex marker at the error location.</td>
            </tr>
            <tr>
              <td style="font-weight: bold; border-bottom: 1px solid #e5e7eb;">Header Checkbox</td>
              <td style="border-bottom: 1px solid #e5e7eb;">One-click toggle in column 1 header to select all or clear all auto-fixable rows.</td>
            </tr>
            <tr style="background-color: #f9fafb;">
              <td style="font-weight: bold; border-bottom: 1px solid #e5e7eb;">Clear Button / Esc Key</td>
              <td style="border-bottom: 1px solid #e5e7eb;">Clears the results table and removes canvas rubber-band outlines and markers.</td>
            </tr>
            <tr>
              <td style="font-weight: bold;">Save / Cancel Edits</td>
              <td>Use QGIS's native editing toolbar to save in-place repairs permanently to disk or cancel edits to revert back to original geometry.</td>
            </tr>
          </table>

          <!-- Footer Section -->
          <div style="text-align: center; color: #4b5563; font-size: 11px; padding: 14px 0 6px 0; border-top: 1px solid #e5e7eb; margin-top: 16px;">
            <b>Geometry Repair Toolkit</b> &bull; Version 1.5.1<br>
            Philippine Statistics Authority &bull; Geospatial Management Division<br>
            Project 1MAP
          </div>

        </div>
        """)
        root.addWidget(self.text, stretch=1)


# =============================================================================
# MAIN DIALOG
# =============================================================================

class GeometryToolkit(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Geometry Repair Toolkit")
        self.resize(1100, 720)
        self._build()

    def closeEvent(self, event):
        # The checker tab can leave a red outline/X marker on the map canvas
        # (from double-clicking an error row) — make sure those are removed
        # when the dialog closes, not just when Clear is pressed.
        try:
            self.checker_tab._clear_error_highlight()
        except Exception:
            pass
        super().closeEvent(event)

    def reject(self):
        # Covers the Esc-key path, which doesn't always go through
        # closeEvent().
        try:
            self.checker_tab._clear_error_highlight()
        except Exception:
            pass
        super().reject()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10); root.setSpacing(6)

        title = QLabel("Geometry Repair Toolkit")
        title.setStyleSheet("font-size:16px; font-weight:700; padding:2px 0;")
        root.addWidget(title)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setStyleSheet("color:#bdbdbd;")
        root.addWidget(sep)

        tabs = QTabWidget()

        self.checker_tab = CheckerTab()
        self.help_tab = HelpInfoTab()

        tabs.addTab(self.checker_tab, "Geometry Fixer")
        tabs.addTab(self.help_tab, "Help and Information")

        root.addWidget(tabs, stretch=1)


if __name__ in ("__main__", "__console__"):
    try:
        dlg = GeometryToolkit()
        dlg.show()
    except Exception:
        pass