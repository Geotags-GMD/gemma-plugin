# -*- coding: utf-8 -*-
"""
Mock implementation of qgis.core, qgis.gui, qgis.PyQt, PyQt5, and processing classes
for non-QGIS Python test execution environments.
Allows unit tests to run in standard Python CLI without throwing ModuleNotFoundError.
"""

import sys
import types
import os
import math

# Ensure Qt offscreen platform plugin is used in headless/CI environments
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import shapely
    import shapely.ops
    from shapely.geometry import (
        Polygon as ShapelyPolygon,
        MultiPolygon as ShapelyMultiPolygon,
        Point as ShapelyPoint,
        box as shapely_box,
    )
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False


class DynamicMockModule(types.ModuleType):
    """Module proxy that returns MockGenericClass for any unassigned attribute."""
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return MockGenericClass


class MockMetaClass(type):
    def __getattr__(cls, name):
        if name in ("HLine", "VLine", "Horizontal", "Vertical"):
            return 1
        return MockGenericClass

    def __or__(cls, other): return cls
    def __ror__(cls, other): return cls
    def __and__(cls, other): return cls
    def __rand__(cls, other): return cls


class MockGenericClass(metaclass=MockMetaClass):
    HLine = 1
    VLine = 2
    Horizontal = 1
    Vertical = 2

    def __init__(self, *args, **kwargs):
        pass

    def setWindowTitle(self, title): pass
    def setLayout(self, layout): pass
    def exec_(self): return 1
    def exec(self): return 1
    def show(self): pass
    def hide(self): pass
    def connect(self, *args): pass
    def count(self): return 0

    def __int__(self): return 0
    def __index__(self): return 0
    def __len__(self): return 0
    def __bool__(self): return True
    def __gt__(self, other): return False
    def __ge__(self, other): return False
    def __lt__(self, other): return False
    def __le__(self, other): return False
    def __eq__(self, other): return False
    def __ne__(self, other): return True
    def __or__(self, other): return self
    def __ror__(self, other): return self
    def __and__(self, other): return self
    def __rand__(self, other): return self

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return MockGenericClass

    def __call__(self, *args, **kwargs):
        return MockGenericClass()


class QgsMapLayerComboBox(MockGenericClass):
    def __init__(self, parent=None):
        self._layer = None
        self.layerChanged = MockSignal()

    def setLayer(self, layer):
        self._layer = layer
        self.layerChanged.emit(layer)

    def currentLayer(self):
        return self._layer

    def setFilters(self, filters):
        pass

    def setMinimumHeight(self, h):
        pass

    def setFixedHeight(self, h):
        pass


class QgsPointXY:
    def __init__(self, x=0.0, y=0.0):
        self._x = float(x)
        self._y = float(y)

    def x(self): return self._x
    def y(self): return self._y

    def distance(self, other):
        ox = other.x() if hasattr(other, 'x') else other[0]
        oy = other.y() if hasattr(other, 'y') else other[1]
        return math.hypot(self._x - ox, self._y - oy)

    def sqrDist(self, other):
        ox = other.x() if hasattr(other, 'x') else other[0]
        oy = other.y() if hasattr(other, 'y') else other[1]
        dx, dy = self._x - ox, self._y - oy
        return dx * dx + dy * dy

    def __repr__(self):
        return f"QgsPointXY({self._x}, {self._y})"


class QgsPolygon:
    def __init__(self):
        self._points = []


class QgsRectangle:
    def __init__(self, xmin=0.0, ymin=0.0, xmax=0.0, ymax=0.0):
        if isinstance(xmin, QgsRectangle):
            other = xmin
            self._xmin = float(other.xMinimum())
            self._ymin = float(other.yMinimum())
            self._xmax = float(other.xMaximum())
            self._ymax = float(other.yMaximum())
        elif hasattr(xmin, 'x') and hasattr(ymin, 'x'):
            p1, p2 = xmin, ymin
            self._xmin = min(float(p1.x()), float(p2.x()))
            self._xmax = max(float(p1.x()), float(p2.x()))
            self._ymin = min(float(p1.y()), float(p2.y()))
            self._ymax = max(float(p1.y()), float(p2.y()))
        else:
            try:
                self._xmin = float(xmin)
                self._ymin = float(ymin)
                self._xmax = float(xmax)
                self._ymax = float(ymax)
            except (TypeError, ValueError):
                self._xmin = 0.0
                self._ymin = 0.0
                self._xmax = 0.0
                self._ymax = 0.0

    def xMinimum(self): return self._xmin
    def yMinimum(self): return self._ymin
    def xMaximum(self): return self._xmax
    def yMaximum(self): return self._ymax
    def width(self): return max(0.0, self._xmax - self._xmin)
    def height(self): return max(0.0, self._ymax - self._ymin)
    def isEmpty(self): return self.width() <= 0.0 or self.height() <= 0.0
    def isNull(self): return self.isEmpty()
    def center(self): return QgsPointXY(self._xmin + self.width() / 2.0, self._ymin + self.height() / 2.0)
    def setMinimal(self):
        self._xmin = float('inf')
        self._ymin = float('inf')
        self._xmax = float('-inf')
        self._ymax = float('-inf')
    def combineExtentWith(self, other):
        if hasattr(other, 'xMinimum'):
            self._xmin = min(self._xmin, other.xMinimum())
            self._ymin = min(self._ymin, other.yMinimum())
            self._xmax = max(self._xmax, other.xMaximum())
            self._ymax = max(self._ymax, other.yMaximum())
    def intersects(self, other):
        if hasattr(other, 'xMinimum'):
            return not (self._xmax < other.xMinimum() or self._xmin > other.xMaximum() or
                        self._ymax < other.yMinimum() or self._ymin > other.yMaximum())
        return False
    def contains(self, other):
        if hasattr(other, 'xMinimum'):
            return (self._xmin <= other.xMinimum() and self._xmax >= other.xMaximum() and
                    self._ymin <= other.yMinimum() and self._ymax >= other.yMaximum())
        elif hasattr(other, 'x'):
            return (self._xmin <= other.x() <= self._xmax and self._ymin <= other.y() <= self._ymax)
        return False
    def __repr__(self):
        return f"QgsRectangle({self._xmin}, {self._ymin}, {self._xmax}, {self._ymax})"


class QgsGeometry:
    def __init__(self, geom_type="Polygon", polygons=None):
        if isinstance(geom_type, QgsGeometry):
            other = geom_type
            self.geom_type = other.geom_type
            self.polygons = [list(p) for p in other.polygons] if other.polygons else []
            self._point = getattr(other, '_point', None)
            self._polyline = getattr(other, '_polyline', None)
        else:
            self.geom_type = geom_type
            self.polygons = polygons or []
            self._point = None
            self._polyline = None

    @staticmethod
    def fromPointXY(point):
        g = QgsGeometry("Point")
        g._point = point
        return g

    @staticmethod
    def fromPolylineXY(polyline):
        g = QgsGeometry("LineString")
        g._polyline = polyline
        return g

    @staticmethod
    def fromPolygonXY(polygons):
        return QgsGeometry("Polygon", polygons=polygons)

    @staticmethod
    def fromWkt(wkt):
        return QgsGeometry("Polygon", polygons=[[QgsPointXY(0, 0), QgsPointXY(1, 0), QgsPointXY(1, 1), QgsPointXY(0, 1), QgsPointXY(0, 0)]])

    @staticmethod
    def collectGeometry(geoms):
        return QgsGeometry("MultiLineString")

    @staticmethod
    def unaryUnion(geoms):
        if not geoms:
            return QgsGeometry("Polygon", [])
        if HAS_SHAPELY:
            sgeoms = [g._to_shapely() for g in geoms if g and not g.isEmpty()]
            sgeoms = [sg for sg in sgeoms if sg is not None and not sg.is_empty]
            if sgeoms:
                u = shapely.ops.unary_union(sgeoms)
                return QgsGeometry._from_shapely(u)
        polys = []
        for g in geoms:
            if hasattr(g, 'polygons') and g.polygons:
                polys.extend(g.polygons)
        return QgsGeometry("Polygon", polys if polys else [[QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)]])

    def _to_shapely(self):
        if not HAS_SHAPELY:
            return None
        try:
            # Points carry their coordinate in _point, not in polygons --
            # without this they fell through to the bounding-box fallback
            # below and came back as a 10x10 box, so every point/polygon
            # predicate (contains, intersects, distance) answered nonsense.
            if getattr(self, '_point', None) is not None:
                return ShapelyPoint(self._point.x(), self._point.y())
            if hasattr(self, 'polygons') and self.polygons:
                spolys = []
                for poly_rings in self.polygons:
                    if not poly_rings:
                        continue
                    if isinstance(poly_rings[0], QgsPointXY):
                        shell = [(p.x(), p.y()) for p in poly_rings]
                        spolys.append(ShapelyPolygon(shell))
                    elif isinstance(poly_rings[0], list):
                        shell = [(p.x(), p.y()) for p in poly_rings[0]]
                        holes = [[(p.x(), p.y()) for p in ring] for ring in poly_rings[1:]]
                        spolys.append(ShapelyPolygon(shell, holes))
                if len(spolys) == 1:
                    return spolys[0]
                elif len(spolys) > 1:
                    return ShapelyMultiPolygon(spolys)
            bbox = self.boundingBox()
            if bbox:
                return shapely_box(bbox.xMinimum(), bbox.yMinimum(), bbox.xMaximum(), bbox.yMaximum())
        except Exception:
            pass
        return None

    @staticmethod
    def _from_shapely(sg):
        if not HAS_SHAPELY or sg is None or sg.is_empty:
            return QgsGeometry("Polygon", [])
        stype = sg.geom_type
        if stype == "Polygon":
            shell = [QgsPointXY(x, y) for x, y in sg.exterior.coords]
            holes = [[QgsPointXY(x, y) for x, y in ring.coords] for ring in sg.interiors]
            return QgsGeometry("Polygon", [[shell] + holes] if holes else [[shell]])
        elif stype == "MultiPolygon":
            mpolys = []
            for p in sg.geoms:
                shell = [QgsPointXY(x, y) for x, y in p.exterior.coords]
                holes = [[QgsPointXY(x, y) for x, y in ring.coords] for ring in p.interiors]
                mpolys.append([shell] + holes if holes else [shell])
            return QgsGeometry("MultiPolygon", mpolys)
        elif stype in ("LineString", "MultiLineString"):
            return QgsGeometry("LineString")
        elif stype == "Point":
            return QgsGeometry.fromPointXY(QgsPointXY(sg.x, sg.y))
        elif stype == "GeometryCollection":
            for geom in sg.geoms:
                if geom.geom_type in ("Polygon", "MultiPolygon"):
                    return QgsGeometry._from_shapely(geom)
        return QgsGeometry("Polygon", [])

    @staticmethod
    def fromMultiPolygonXY(multipoly):
        polys = [p[0] for p in multipoly if p]
        return QgsGeometry("MultiPolygon", polys)

    @staticmethod
    def fromMultiPolylineXY(multipoly):
        return QgsGeometry("MultiLineString")

    @staticmethod
    def fromMultiPointXY(multipoint):
        return QgsGeometry("MultiPoint")

    @staticmethod
    def fromRect(rect):
        if hasattr(rect, 'xMinimum'):
            xmin, ymin, xmax, ymax = rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()
            return QgsGeometry.fromPolygonXY([[
                QgsPointXY(xmin, ymin),
                QgsPointXY(xmax, ymin),
                QgsPointXY(xmax, ymax),
                QgsPointXY(xmin, ymax),
                QgsPointXY(xmin, ymin),
            ]])
        return QgsGeometry("Polygon", [])

    def type(self):
        if self.geom_type == "Point": return 0
        elif self.geom_type in ("LineString", "Line", "MultiLineString"): return 1
        return 2  # PolygonGeometry

    def wkbType(self):
        if self.geom_type in ("LineString", "Line"): return 2
        elif self.geom_type == "MultiLineString": return 5
        elif self.geom_type == "Point": return 1
        elif self.geom_type == "MultiPolygon": return 6
        return 3  # Polygon

    def isNull(self): return False
    def isEmpty(self): return not bool(self.polygons) if self.geom_type in ("Polygon", "MultiPolygon") else False
    def isSimple(self): return True
    def isValid(self): return True
    def isGeosValid(self): return True
    def isMultipart(self): return self.geom_type.startswith("Multi") or (len(self.polygons or []) > 1)
    def makeValid(self): return self
    def touches(self, other): return True
    def distance(self, other):
        if HAS_SHAPELY:
            s1 = self._to_shapely()
            s2 = other._to_shapely() if hasattr(other, '_to_shapely') else None
            if s1 and s2:
                return float(s1.distance(s2))
        b1 = self.boundingBox()
        b2 = other.boundingBox()
        dx = max(0.0, max(b1.xMinimum() - b2.xMaximum(), b2.xMinimum() - b1.xMaximum()))
        dy = max(0.0, max(b1.yMinimum() - b2.yMaximum(), b2.yMinimum() - b1.yMaximum()))
        return math.hypot(dx, dy)
    def contains(self, other):
        if HAS_SHAPELY:
            s1 = self._to_shapely()
            s2 = other._to_shapely() if hasattr(other, '_to_shapely') else None
            if s1 and s2:
                return bool(s1.contains(s2))
        if hasattr(other, 'geom_type') and other.geom_type == "Point":
            pt = other.asPoint()
            bbox = self.boundingBox()
            return (bbox.xMinimum() <= pt.x() <= bbox.xMaximum() and bbox.yMinimum() <= pt.y() <= bbox.yMaximum())
        return True
    def intersects(self, other):
        if HAS_SHAPELY:
            s1 = self._to_shapely()
            s2 = other._to_shapely() if hasattr(other, '_to_shapely') else None
            if s1 and s2:
                return bool(s1.intersects(s2))
        if hasattr(other, 'geom_type') and other.geom_type == "Point":
            return self.contains(other)
        b1 = self.boundingBox()
        b2 = other.boundingBox() if hasattr(other, 'boundingBox') else None
        if b2:
            return not (b1.xMaximum() < b2.xMinimum() or b1.xMinimum() > b2.xMaximum() or
                        b1.yMaximum() < b2.yMinimum() or b1.yMinimum() > b2.yMaximum())
        return True
    def intersection(self, other):
        if HAS_SHAPELY:
            s1 = self._to_shapely()
            s2 = other._to_shapely() if hasattr(other, '_to_shapely') else None
            if s1 and s2:
                res = s1.intersection(s2)
                return QgsGeometry._from_shapely(res)
        if self.geom_type in ("Polygon", "MultiPolygon") and hasattr(other, 'geom_type') and other.geom_type in ("Polygon", "MultiPolygon"):
            p1 = self.polygons
            p2 = getattr(other, 'polygons', [])
            if not p1: return QgsGeometry("Polygon", p2)
            if not p2: return QgsGeometry("Polygon", p1)
            b1 = self.boundingBox()
            b2 = other.boundingBox()
            area1 = b1.width() * b1.height()
            area2 = b2.width() * b2.height()
            return QgsGeometry("Polygon", p1 if area1 <= area2 else p2)
        return QgsGeometry("LineString")
    def difference(self, other):
        if HAS_SHAPELY:
            s1 = self._to_shapely()
            s2 = other._to_shapely() if hasattr(other, '_to_shapely') else None
            if s1 and s2:
                res = s1.difference(s2)
                return QgsGeometry._from_shapely(res)
        if hasattr(self, 'polygons') and self.polygons:
            other_polys = getattr(other, 'polygons', [])
            diff_rings = [p for p in self.polygons if p not in other_polys]
            if other_polys and diff_rings == self.polygons:
                diff_rings = [[QgsPointXY(p.x() + 1.0, p.y() + 1.0) for p in self.polygons[0]]]
            if diff_rings:
                gtype = "MultiPolygon" if len(diff_rings) > 1 else "Polygon"
                res = QgsGeometry(gtype, diff_rings)
                res._mock_area = 60.0
                return res
        return QgsGeometry("Polygon", [[QgsPointXY(80, 0), QgsPointXY(120, 0), QgsPointXY(120, 100), QgsPointXY(80, 100), QgsPointXY(80, 0)]])
    def mergeLines(self): return QgsGeometry("LineString")
    def simplify(self, tol): return self
    def convertToType(self, dest_type, destructively=False): return QgsGeometry("LineString")
    def convertToMultiType(self): return True
    def constParts(self):
        if self.polygons:
            return [QgsGeometry("Polygon", [p]) for p in self.polygons]
        return [self]
    def asGeometryCollection(self): return [self]
    def asPolyline(self): return getattr(self, '_polyline', [QgsPointXY(0.0, 0.0), QgsPointXY(10.0, 0.0)])
    def asPolygon(self):
        if self.polygons: return self.polygons
        return [[QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)]]
    def asMultiPolygon(self):
        if self.polygons: return [self.polygons]
        return [[[QgsPointXY(0, 0), QgsPointXY(10, 0), QgsPointXY(10, 10), QgsPointXY(0, 10), QgsPointXY(0, 0)]]]
    def clone(self): return QgsGeometry(self.geom_type, self.polygons)
    def transform(self, ct): pass
    def combine(self, other):
        if HAS_SHAPELY:
            s1 = self._to_shapely()
            s2 = other._to_shapely() if hasattr(other, '_to_shapely') else None
            if s1 and s2:
                res = s1.union(s2)
                return QgsGeometry._from_shapely(res)
        p1 = self.polygons or []
        p2 = getattr(other, 'polygons', []) or []
        combined = p1 + p2
        gtype = "MultiPolygon" if len(combined) > 1 else "Polygon"
        return QgsGeometry(gtype, combined)
    def buffer(self, distance, segments=3):
        if HAS_SHAPELY:
            s1 = self._to_shapely()
            if s1:
                res = s1.buffer(distance, resolution=segments)
                return QgsGeometry._from_shapely(res)
        return QgsGeometry("Polygon", self.polygons)
    def area(self):
        if self.geom_type in ("LineString", "Line", "MultiLineString", "Point", "MultiPoint"):
            return 0.0
        if HAS_SHAPELY:
            s1 = self._to_shapely()
            if s1:
                return float(s1.area)
        return getattr(self, '_mock_area', 100.0)
    def length(self):
        if HAS_SHAPELY:
            s1 = self._to_shapely()
            if s1:
                return float(s1.length)
        return 40.0

    def splitGeometry(self, split_line, preserve_input=False):
        bbox = self.boundingBox()
        mid_x = (bbox.xMinimum() + bbox.xMaximum()) / 2.0
        self.polygons = [[
            QgsPointXY(bbox.xMinimum(), bbox.yMinimum()),
            QgsPointXY(mid_x, bbox.yMinimum()),
            QgsPointXY(mid_x, bbox.yMaximum()),
            QgsPointXY(bbox.xMinimum(), bbox.yMaximum()),
            QgsPointXY(bbox.xMinimum(), bbox.yMinimum()),
        ]]
        p2 = QgsGeometry.fromPolygonXY([[
            QgsPointXY(mid_x, bbox.yMinimum()),
            QgsPointXY(bbox.xMaximum(), bbox.yMinimum()),
            QgsPointXY(bbox.xMaximum(), bbox.yMaximum()),
            QgsPointXY(mid_x, bbox.yMaximum()),
            QgsPointXY(mid_x, bbox.yMinimum()),
        ]])
        return 0, [p2], []

    def voronoiDiagram(self, extent=None):
        return QgsGeometry("MultiPolygon")

    def centroid(self):
        c = self.boundingBox().center()
        return QgsGeometry.fromPointXY(c)
    def asPoint(self): return getattr(self, '_point', QgsPointXY(0.0, 0.0))

    def boundingBox(self):
        if getattr(self, '_point', None) is not None:
            pt = self._point
            xs = [pt.x()]
            ys = [pt.y()]
        elif self.polygons:
            pts = []
            def _extract_pts(obj):
                if hasattr(obj, 'x') and hasattr(obj, 'y'):
                    pts.append(obj)
                elif isinstance(obj, (list, tuple)):
                    for item in obj:
                        _extract_pts(item)
            _extract_pts(self.polygons)
            if pts:
                xs = [p.x() for p in pts]
                ys = [p.y() for p in pts]
            else:
                xs = ys = None
        else:
            xs = ys = None
        if xs:
            xmin, xmax = min(xs), max(xs)
            ymin, ymax = min(ys), max(ys)
            class MockBox:
                def __init__(self, x0, x1, y0, y1):
                    self._x0, self._x1, self._y0, self._y1 = x0, x1, y0, y1
                def xMinimum(self): return self._x0
                def xMaximum(self): return self._x1
                def yMinimum(self): return self._y0
                def yMaximum(self): return self._y1
                def width(self): return self._x1 - self._x0
                def height(self): return self._y1 - self._y0
                def center(self): return QgsPointXY((self._x0+self._x1)/2, (self._y0+self._y1)/2)
                def buffered(self, b): return self
                def scale(self, factor): pass
                def contains(self, pt):
                    px = pt.x() if hasattr(pt, 'x') else pt[0]
                    py = pt.y() if hasattr(pt, 'y') else pt[1]
                    return self._x0 <= px <= self._x1 and self._y0 <= py <= self._y1
            return MockBox(xmin, xmax, ymin, ymax)
        class MockBox:
            def xMinimum(self): return 0.0
            def xMaximum(self): return 10.0
            def yMinimum(self): return 0.0
            def yMaximum(self): return 10.0
            def width(self): return 10.0
            def height(self): return 10.0
            def center(self): return QgsPointXY(5.0, 5.0)
            def buffered(self, b): return self
            def scale(self, factor): pass
            def contains(self, pt): return True
        return MockBox()

    def __repr__(self):
        return f"<QgsGeometry {self.geom_type}>"


class QgsField:
    def __init__(self, name="", field_type=None, typeName="", len=0, prec=0, comment="", subType=None, length=0, precision=0, **kwargs):
        self._name = name
        self._type = field_type
        self._typeName = typeName
        self._length = len or length
        self._precision = prec or precision
        self._comment = comment

    def name(self): return self._name
    def type(self): return self._type
    def typeName(self): return self._typeName
    def length(self): return self._length
    def precision(self): return self._precision
    def comment(self): return self._comment


class QgsFields:
    def __init__(self, fields=None):
        if fields is None:
            self._fields = []
        elif isinstance(fields, QgsFields):
            self._fields = list(fields._fields)
        else:
            self._fields = list(fields)

    def append(self, field):
        self._fields.append(field)

    def remove(self, i):
        if 0 <= i < len(self._fields):
            self._fields.pop(i)

    def at(self, i):
        return self._fields[i] if 0 <= i < len(self._fields) else None

    def names(self):
        return [f.name() for f in self._fields]

    def indexOf(self, name):
        names = self.names()
        return names.index(name) if name in names else -1

    def count(self):
        return len(self._fields)

    def isEmpty(self):
        return len(self._fields) == 0

    def __iter__(self):
        return iter(self._fields)

    def __len__(self):
        return len(self._fields)


class QgsFeature:
    def __init__(self, fields=None):
        if isinstance(fields, QgsFeature):
            self._attributes = list(fields._attributes)
            self._geometry = fields._geometry
            self._id = fields._id
            self._fields = fields._fields
        else:
            self._attributes = []
            self._geometry = None
            self._id = 0
            self._fields = fields

    def isValid(self):
        return True

    def hasGeometry(self):
        return self._geometry is not None

    def setAttributes(self, attrs):
        self._attributes = list(attrs)

    def setId(self, fid):
        self._id = fid

    def id(self):
        return self._id

    def attributes(self):
        return self._attributes

    def setFields(self, fields):
        self._fields = fields

    def fields(self):
        return self._fields

    def setAttribute(self, field, value):
        if isinstance(field, int):
            while len(self._attributes) <= field:
                self._attributes.append(None)
            self._attributes[field] = value
        elif self._fields and hasattr(self._fields, "indexOf"):
            idx = self._fields.indexOf(field)
            if idx != -1:
                while len(self._attributes) <= idx:
                    self._attributes.append(None)
                self._attributes[idx] = value

    def attribute(self, field):
        if isinstance(field, int):
            if 0 <= field < len(self._attributes):
                return self._attributes[field]
            return None
        elif isinstance(field, str):
            if self._fields and hasattr(self._fields, "indexOf"):
                idx = self._fields.indexOf(field)
                if idx != -1 and 0 <= idx < len(self._attributes):
                    return self._attributes[idx]
            return None
        return None

    def setGeometry(self, geom):
        self._geometry = geom

    def geometry(self):
        return self._geometry

    def id(self):
        return self._id

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._attributes[key]
        if self._fields and hasattr(self._fields, "names"):
            names = self._fields.names()
            if key in names:
                return self._attributes[names.index(key)]
        return None


class QgsVectorDataProvider:
    def __init__(self, layer):
        self._layer = layer

    def addAttributes(self, fields):
        for f in fields:
            self._layer._fields.append(f)
        return True

    def addFeatures(self, features):
        for feat in features:
            if getattr(feat, '_id', 0) == 0:
                feat.setId(len(self._layer._features) + 1)
            self._layer._features.append(feat)
        return True, features

    def deleteFeatures(self, fids):
        fids_set = set(fids)
        self._layer._features = [f for f in self._layer._features if f.id() not in fids_set]
        return True

    def fields(self):
        return self._layer._fields


class MockSignal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        if slot not in self._slots:
            self._slots.append(slot)

    def disconnect(self, slot=None):
        if slot is None:
            self._slots.clear()
        elif slot in self._slots:
            self._slots.remove(slot)

    def emit(self, *args, **kwargs):
        for slot in list(self._slots):
            try:
                slot(*args, **kwargs)
            except Exception:
                pass


_MOCK_LAYER_CACHE = {}


class QgsVectorLayer:
    def __init__(self, path="Polygon?crs=EPSG:4326", name="MockLayer", provider="memory"):
        self._path = path
        self._name = name
        self._provider = provider
        self._fields = QgsFields()
        self._features = []
        self._selected_fids = set()
        self.selectionChanged = MockSignal()
        raw_path = str(path).split("|")[0].replace("\\", "/")
        if raw_path in _MOCK_LAYER_CACHE:
            cached_fields, cached_feats = _MOCK_LAYER_CACHE[raw_path]
            for f in cached_fields:
                self._fields.append(QgsField(f.name(), f.type()))
            for feat in cached_feats:
                cf = QgsFeature(self._fields)
                cf.setGeometry(feat.geometry())
                cf.setAttributes(list(feat.attributes()))
                cf.setId(feat.id())
        self._custom_properties = {}
        self._subset_string = ""

    def name(self): return self._name
    def setName(self, name): self._name = name
    def isValid(self): return True
    def isEditable(self): return False
    def rollBack(self): return True
    def featureCount(self): return len(self._features)
    def fields(self): return self._fields
    def setFields(self, fields): self._fields = fields
    def setFeatures(self, features): self._features = features
    def dataProvider(self): return QgsVectorDataProvider(self)
    def addFeatures(self, features): return self.dataProvider().addFeatures(features)
    def deleteFeatures(self, fids): return self.dataProvider().deleteFeatures(fids)
    def updateFields(self): pass
    def updateExtents(self): pass
    def extent(self): return MockGenericClass()
    def sourceExtent(self): return self.extent()
    def getFeatures(self, request=None): return iter(self._features)
    def crs(self): return MockGenericClass()
    def sourceCrs(self): return self.crs()
    def wkbType(self): return 3  # Polygon
    def geometryType(self): return 2  # PolygonGeometry
    def id(self): return f"layer_{self._name}"
    def setSubsetString(self, string):
        self._subset_string = string
        return True
    def subsetString(self): return self._subset_string
    def setCustomProperty(self, key, value): self._custom_properties[key] = value
    def customProperty(self, key, default_val=None): return self._custom_properties.get(key, default_val)
    def selectByExpression(self, expr): pass
    def selectByIds(self, fids):
        self._selected_fids = set(fids)
        self.selectionChanged.emit()
    def removeSelection(self):
        self._selected_fids = set()
        self.selectionChanged.emit()
    def selectAll(self):
        self._selected_fids = set(f.id() for f in self._features)
        self.selectionChanged.emit()
    def selectedFeatureIds(self):
        return list(self._selected_fids)
    def selectedFeatures(self):
        return [f for f in self._features if f.id() in self._selected_fids]
    def selectedFeatureCount(self):
        return len(self._selected_fids)
    def triggerRepaint(self): pass
    def isEditable(self): return getattr(self, '_is_editable', False)
    def startEditing(self):
        self._is_editable = True
        return True
    def commitChanges(self):
        self._is_editable = False
        return True
    def rollBack(self):
        self._is_editable = False
        return True
    def getFeature(self, fid):
        for feat in self._features:
            if feat.id() == fid:
                return feat
        return QgsFeature(self._fields)
    def changeAttributeValue(self, fid, field_idx, value):
        for feat in self._features:
            if feat.id() == fid:
                feat.setAttribute(field_idx, value)
                return True
        return False
    def setEditorWidgetSetup(self, field_idx, setup):
        if not hasattr(self, '_editor_widget_setups'):
            self._editor_widget_setups = {}
        self._editor_widget_setups[field_idx] = setup
    def editorWidgetSetup(self, field_idx):
        if not hasattr(self, '_editor_widget_setups'):
            self._editor_widget_setups = {}
        return self._editor_widget_setups.get(field_idx, QgsEditorWidgetSetup())
    def editFormConfig(self):
        if not hasattr(self, '_edit_form_config') or self._edit_form_config is None:
            self._edit_form_config = QgsEditFormConfig()
        return self._edit_form_config
    def setEditFormConfig(self, config):
        self._edit_form_config = config
    def loadNamedStyle(self, uri, categories=None):
        return ("Success", True)
    def emitStyleChanged(self):
        pass
    def setReadOnly(self, readonly=True):
        self._layer_readonly = readonly
    def isReadOnly(self):
        return getattr(self, '_layer_readonly', False)


class QgsEditFormConfig:
    def __init__(self):
        self._read_only = {}

    def setReadOnly(self, field_idx, read_only=True):
        self._read_only[field_idx] = read_only

    def readOnly(self, field_idx):
        return self._read_only.get(field_idx, False)


class QgsEditorWidgetSetup:
    def __init__(self, widget_type="", config=None):
        self._type = widget_type
        self._config = config or {}

    def type(self):
        return self._type

    def config(self):
        return self._config


class QgsProcessingFeedback:
    def isCanceled(self): return False
    def setProgress(self, progress): pass
    def pushInfo(self, msg): pass
    def pushWarning(self, msg): pass
    def reportError(self, msg): pass


class QgsProcessingContext:
    class LayerDetails:
        def __init__(self, name="", project=None, output_name="", **kwargs):
            self.name = name
            self.project = project
            self.output_name = output_name
            self.outputName = output_name

    def __init__(self):
        self._layers_to_load = {}

    def project(self):
        return QgsProject.instance()

    def transformContext(self):
        return MockGenericClass()

    def addLayerToLoadOnCompletion(self, layer_id, details=None):
        if details is None:
            details = QgsProcessingContext.LayerDetails()
        self._layers_to_load[str(layer_id)] = details

    def layersToLoadOnCompletion(self):
        return self._layers_to_load

    def setLayersToLoadOnCompletion(self, layers):
        self._layers_to_load = dict(layers)

    def willLoadLayerOnCompletion(self, layer_id):
        return str(layer_id) in self._layers_to_load

    def layerToLoadOnCompletionDetails(self, layer_id):
        return self._layers_to_load.get(str(layer_id))


try:
    import qgis.core
    if hasattr(qgis.core, "QgsProcessingContext"):
        QgsProcessingContext = qgis.core.QgsProcessingContext
    if hasattr(qgis.core, "QgsProcessingFeedback"):
        QgsProcessingFeedback = qgis.core.QgsProcessingFeedback
    if hasattr(qgis.core, "QgsVectorLayer"):
        QgsVectorLayer = qgis.core.QgsVectorLayer
    if hasattr(qgis.core, "QgsEditorWidgetSetup"):
        QgsEditorWidgetSetup = qgis.core.QgsEditorWidgetSetup
except Exception:
    pass


class QgsProcessingException(Exception):
    pass


class QgsSpatialIndex:
    def __init__(self, *args, **kwargs):
        self._features = {}
        if args and hasattr(args[0], "__iter__"):
            self.addFeatures(args[0])

    def addFeature(self, feature):
        if hasattr(feature, "id"):
            fid = feature.id() if callable(feature.id) else getattr(feature, "_id", 0)
            self._features[fid] = feature

    def addFeatures(self, features):
        for f in features:
            self.addFeature(f)

    def intersects(self, bbox):
        return list(self._features.keys())


class QgsProject:
    _instance = None

    def __init__(self):
        self._layers = {}

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = QgsProject()
        return cls._instance

    def fileName(self):
        return ""

    def homePath(self):
        return ""

    def transformContext(self):
        return MockGenericClass()

    def mapLayersByName(self, name):
        return [lyr for lyr in self._layers.values() if hasattr(lyr, "name") and lyr.name() == name]

    def addMapLayer(self, layer):
        if layer and hasattr(layer, "id"):
            self._layers[layer.id()] = layer
        return layer

    def removeMapLayer(self, layer_id):
        self._layers.pop(layer_id, None)


class QgsVectorFileWriter:
    NoError = 0
    ErrCreateDataSource = 1
    CreateOrOverwriteFile = 0
    CreateOrOverwriteLayer = 1

    class SaveVectorOptions:
        def __init__(self):
            self.driverName = "GPKG"
            self.layerName = ""
            self.fileEncoding = "UTF-8"
            self.actionOnExistingFile = 0

    @classmethod
    def writeAsVectorFormatV3(cls, layer, file_path, ctx, options):
        try:
            import os
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "wb") as f:
                f.write(b"mock_gpkg_data")
            norm_path = str(file_path).replace("\\", "/")
            _MOCK_LAYER_CACHE[norm_path] = (layer.fields(), list(layer.getFeatures()))
        except Exception:
            pass
        return (0, "")

    @classmethod
    def writeAsVectorFormatV2(cls, layer, file_path, ctx, options):
        try:
            import os
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "wb") as f:
                f.write(b"mock_gpkg_data")
            norm_path = str(file_path).replace("\\", "/")
            _MOCK_LAYER_CACHE[norm_path] = (layer.fields(), list(layer.getFeatures()))
        except Exception:
            pass
        return (0, "")



class QgsProcessingParameterDefinition:
    def __init__(self, name="", description="", *args, **kwargs):
        self._name = str(name)
        self._description = str(description)

    def name(self):
        return self._name

    def description(self):
        return self._description


class QgsProcessingParameterMultipleLayers(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterEnum(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterVectorLayer(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterFeatureSink(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterFile(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterString(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterBoolean(QgsProcessingParameterDefinition):
    pass


class QgsProcessingParameterNumber(QgsProcessingParameterDefinition):
    pass


class QgsProcessingAlgorithm:
    def __init__(self, *args, **kwargs):
        self._parameters = {}

    @classmethod
    def flags(cls): return 0
    @classmethod
    def group(cls): return "GMD Pipeline"
    @classmethod
    def groupId(cls): return "gmd_pipeline"

    def addParameter(self, param, *args, **kwargs):
        if not hasattr(self, "_parameters"):
            self._parameters = {}
        if hasattr(param, "name") and callable(param.name):
            try:
                name = param.name()
                if isinstance(name, str):
                    self._parameters[name] = param
            except Exception:
                pass
        return param

    def parameterDefinition(self, name):
        if not hasattr(self, "_parameters"):
            self._parameters = {}
        return self._parameters.get(name, None)


    def parameterAsLayerList(self, parameters, name, context):
        val = parameters.get(name, [])
        if isinstance(val, list):
            return val
        return [val]

    def parameterAsSource(self, parameters, name, context):
        val = parameters.get(name, None)
        if isinstance(val, QgsVectorLayer):
            return val
        return QgsVectorLayer(name="MockMaskSource")

    def parameterAsVectorLayer(self, parameters, name, context):
        val = parameters.get(name, None)
        if isinstance(val, QgsVectorLayer):
            return val
        return QgsVectorLayer(name="MockVectorLayer")

    def parameterAsInt(self, parameters, name, context):
        return int(parameters.get(name, 0))

    def parameterAsEnum(self, parameters, name, context):
        return int(parameters.get(name, 0))

    def parameterAsDouble(self, parameters, name, context):
        return float(parameters.get(name, 0.0))

    def parameterAsString(self, parameters, name, context):
        return str(parameters.get(name, ""))

    def parameterAsFile(self, parameters, name, context):
        return str(parameters.get(name, "") or "")

    def parameterAsFileOutput(self, parameters, name, context):
        return str(parameters.get(name, "") or "")

    def parameterAsBool(self, parameters, name, context):
        return bool(parameters.get(name, False))

    def parameterAsBoolean(self, parameters, name, context):
        return self.parameterAsBool(parameters, name, context)

    def parameterAsExtent(self, parameters, name, context, crs=None):
        class MockRect:
            def isEmpty(self): return False
            def combineExtentWith(self, rect): pass
        return MockRect()

    def parameterAsSink(self, parameters, name, context, fields, wkbType, crs):
        class MockSink:
            def addFeature(self, *args, **kwargs): pass
            def addFeatures(self, *args, **kwargs): return (True, [])
        return (MockSink(), "mock_dest_id")



class QgsProject:
    _instance = None

    def __init__(self):
        self._layers = {}

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = QgsProject()
        return cls._instance

    def homePath(self):
        return ""

    def fileName(self):
        return ""

    def addMapLayer(self, layer, addToLegend=True):
        if layer:
            lid = layer.id() if hasattr(layer, "id") else str(id(layer))
            self._layers[lid] = layer
        return layer

    def addMapLayers(self, layers, addToLegend=True):
        for l in layers:
            self.addMapLayer(l)
        return layers

    def mapLayers(self):
        return self._layers

    def mapLayer(self, layer_id):
        return self._layers.get(layer_id)

    def removeMapLayer(self, layer_id):
        self._layers.pop(layer_id, None)

    def removeAllMapLayers(self):
        self._layers.clear()

    def __getattr__(self, name): return MockGenericClass()


class QgsApplication:
    _instance = None

    def __init__(self, *args, **kwargs):
        QgsApplication._instance = self

    @classmethod
    def instance(cls):
        return cls._instance

    def initQgis(self): pass
    def exitQgis(self): pass

    @staticmethod
    def processingRegistry():
        class MockRegistry:
            def addProvider(self, provider): pass
            def algorithmById(self, id): return None
        return MockRegistry()


class QgsWkbTypes:
    Point = 1
    LineString = 2
    Polygon = 3
    MultiPoint = 4
    MultiLineString = 5
    MultiPolygon = 6
    GeometryCollection = 7

    PointGeometry = 0
    LineGeometry = 1
    PolygonGeometry = 2

    @staticmethod
    def displayString(wkb_type): return "Polygon"

    @staticmethod
    def geometryType(wkb_type):
        if wkb_type in (1, 4): return 0
        elif wkb_type in (2, 5): return 1
        return 2  # PolygonGeometry

    @staticmethod
    def multiType(wkb_type): return 6

    @staticmethod
    def flatType(wkb_type): return wkb_type


class MockQVariant:
    String = 1
    Int = 2
    Double = 3
    LongLong = 4
    DateTime = 5
    Date = 6
    Bool = 7

    def __init__(self, val=None): self.val = val


class MockQt(metaclass=MockMetaClass):
    Unchecked = 0
    Checked = 2
    CustomContextMenu = 1
    UserRole = 32
    Horizontal = 1
    Vertical = 2


class MockQCoreApplication:
    @staticmethod
    def translate(context, sourceText, disambiguation=None, n=-1):
        return sourceText

    @staticmethod
    def processEvents(*args, **kwargs):
        pass

    @staticmethod
    def instance(*args, **kwargs):
        return MockGenericClass()


class MockQThread:
    @staticmethod
    def idealThreadCount():
        return 4

    @staticmethod
    def currentThread():
        return 1
class MockQObject:
    def __init__(self, parent=None): pass
    def tr(self, s, *args, **kwargs): return s
    def blockSignals(self, b): pass
    def setProperty(self, name, val): pass
    def property(self, name): return None


class MockQWidget(MockGenericClass):
    def __init__(self, parent=None): super().__init__()


class MockQDialog(MockQWidget): pass
class MockUiForm(metaclass=MockMetaClass): pass


class MockProcessing:
    @staticmethod
    def run(name, parameters, context=None, feedback=None, is_child_algorithm=False):
        # Return mock layer or dictionary depending on operation
        out_target = parameters.get("OUTPUT", "memory:")
        mock_layer = QgsVectorLayer(name=f"Result_{name}")
        return {
            "OUTPUT": out_target if out_target != "memory:" else mock_layer,
            "OUTPUT_LAYER": mock_layer
        }


_NATIVE_QGS_APP = None


def setup_qgis_mock_if_needed():
    """
    Checks for native QGIS installation. If real PyQGIS is available, initializes native
    QgsApplication and Processing framework. Otherwise, installs headless mock proxies.
    Also provides a transparent PyQt5 -> qgis.PyQt compatibility bridge for Qt6 builds.
    """
    import os
    global _NATIVE_QGS_APP

    # Map PyQt5 imports to qgis.PyQt for Qt6 QGIS environments (e.g. qgis/qgis:3.40)
    try:
        import PyQt5
    except ImportError:
        try:
            import qgis.PyQt
            sys.modules["PyQt5"] = qgis.PyQt
            if hasattr(qgis.PyQt, "QtCore"):
                sys.modules["PyQt5.QtCore"] = qgis.PyQt.QtCore
            if hasattr(qgis.PyQt, "QtWidgets"):
                sys.modules["PyQt5.QtWidgets"] = qgis.PyQt.QtWidgets
            if hasattr(qgis.PyQt, "QtGui"):
                sys.modules["PyQt5.QtGui"] = qgis.PyQt.QtGui
        except ImportError:
            pass

    # Polyfill Qt6enum changes (e.g. QFrame.Shape.HLine) for Qt5 code compatibility
    try:
        from qgis.PyQt.QtWidgets import QFrame
        if hasattr(QFrame, "Shape") and not hasattr(QFrame, "HLine"):
            QFrame.HLine = QFrame.Shape.HLine
            QFrame.VLine = QFrame.Shape.VLine
        if hasattr(QFrame, "Shadow") and not hasattr(QFrame, "Sunken"):
            QFrame.Sunken = QFrame.Shadow.Sunken
            QFrame.Plain = QFrame.Shadow.Plain
            QFrame.Raised = QFrame.Shadow.Raised
    except Exception:
        pass

    try:
        import qgis.core
        if not hasattr(qgis.core, "MockGenericClass"):
            # Real PyQGIS detected — locate plugins directory if needed
            # Add system QGIS plugin search paths for processing module
            for plugin_path in [
                "/usr/share/qgis/python/plugins",
                "/usr/share/qgis/python",
                "/usr/local/share/qgis/python/plugins",
                "/usr/local/share/qgis/python",
            ]:
                if os.path.exists(plugin_path) and plugin_path not in sys.path:
                    sys.path.insert(0, plugin_path)

            if hasattr(qgis.core, "__file__") and qgis.core.__file__:
                core_file = os.path.abspath(qgis.core.__file__)
                qgis_python_dir = os.path.dirname(os.path.dirname(os.path.dirname(core_file)))
                plugins_dir = os.path.join(qgis_python_dir, "plugins")
                if os.path.exists(plugins_dir) and plugins_dir not in sys.path:
                    sys.path.insert(0, plugins_dir)

            if hasattr(qgis.core, "QgsApplication"):
                if qgis.core.QgsApplication.instance() is None:
                    if "QGIS_PREFIX_PATH" in os.environ:
                        qgis_prefix = os.environ["QGIS_PREFIX_PATH"]
                    elif os.path.exists("/usr/share/qgis/resources/srs.db"):
                        qgis_prefix = "/usr"
                    elif os.path.exists("/usr/local/share/qgis/resources/srs.db"):
                        qgis_prefix = "/usr/local"
                    elif hasattr(qgis.core, "__file__") and qgis.core.__file__:
                        qgis_prefix = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(qgis.core.__file__))))
                    else:
                        qgis_prefix = "/usr"

                    qgis.core.QgsApplication.setPrefixPath(qgis_prefix, True)
                    argv = [a.encode("utf-8") if isinstance(a, str) else a for a in sys.argv]
                    try:
                        _NATIVE_QGS_APP = qgis.core.QgsApplication(argv, True)
                    except TypeError:
                        try:
                            _NATIVE_QGS_APP = qgis.core.QgsApplication(sys.argv, True)
                        except TypeError:
                            _NATIVE_QGS_APP = qgis.core.QgsApplication([], True)

                    _NATIVE_QGS_APP.initQgis()

                    try:
                        import qgis.gui
                        if hasattr(qgis.gui, "QgsGui"):
                            qgis.gui.QgsGui.init()
                    except Exception:
                        pass

                try:
                    import processing
                    from processing.core.Processing import Processing
                    Processing.initialize()
                except Exception as e:
                    print(f"[QGIS Native Init Warning]: {e}")

            global QgsProcessingContext, QgsProcessingFeedback, QgsVectorLayer, QgsGeometry, QgsFeature, QgsFields, QgsPointXY, QgsWkbTypes, QgsProject, QgsFeatureSink, QgsSpatialIndex, QgsFeatureRequest, QgsProcessingException, QgsProcessingUtils, QVariant
            for attr_name in [
                "QgsProcessingContext", "QgsProcessingFeedback", "QgsVectorLayer",
                "QgsGeometry", "QgsFeature", "QgsFields", "QgsField", "QgsPointXY",
                "QgsWkbTypes", "QgsProject", "QgsFeatureSink", "QgsSpatialIndex",
                "QgsFeatureRequest", "QgsProcessingException", "QgsProcessingUtils",
                "QVariant"
            ]:
                if hasattr(qgis.core, attr_name):
                    val = getattr(qgis.core, attr_name)
                    globals()[attr_name] = val
                    setattr(sys.modules[__name__], attr_name, val)
            return
    except ImportError:
        pass

    # Create dynamic mock modules for non-QGIS Python environment
    qgis_mod = DynamicMockModule("qgis")
    core_mod = DynamicMockModule("qgis.core")
    gui_mod = DynamicMockModule("qgis.gui")
    utils_mod = DynamicMockModule("qgis.utils")
    analysis_mod = DynamicMockModule("qgis.analysis")
    pyqt_mod = DynamicMockModule("qgis.PyQt")
    qtcore_mod = DynamicMockModule("qgis.PyQt.QtCore")
    qtgui_mod = DynamicMockModule("qgis.PyQt.QtWidgets")
    qtwidgets_mod = DynamicMockModule("qgis.PyQt.QtGui")

    # Explicit Core attributes
    core_mod.QgsPointXY = QgsPointXY
    core_mod.QgsRectangle = QgsRectangle
    core_mod.QgsPolygon = QgsPolygon
    core_mod.QgsGeometry = QgsGeometry
    core_mod.QgsField = QgsField
    core_mod.QgsFields = QgsFields
    core_mod.QgsFeature = QgsFeature
    core_mod.QgsVectorLayer = QgsVectorLayer
    core_mod.QgsSpatialIndex = QgsSpatialIndex
    core_mod.QgsProcessingFeedback = QgsProcessingFeedback
    core_mod.QgsProcessingContext = QgsProcessingContext
    core_mod.QgsProcessingException = QgsProcessingException
    core_mod.QgsProcessingAlgorithm = QgsProcessingAlgorithm
    core_mod.QgsProcessingLayerPostProcessorInterface = MockGenericClass
    core_mod.QgsProject = QgsProject
    core_mod.QgsApplication = QgsApplication
    core_mod.QgsWkbTypes = QgsWkbTypes
    core_mod.QgsVectorFileWriter = QgsVectorFileWriter
    core_mod.QgsEditorWidgetSetup = QgsEditorWidgetSetup
    core_mod.QgsEditFormConfig = QgsEditFormConfig
    core_mod.QgsProcessingParameterDefinition = QgsProcessingParameterDefinition
    core_mod.QgsProcessingParameterMultipleLayers = QgsProcessingParameterMultipleLayers
    core_mod.QgsProcessingParameterEnum = QgsProcessingParameterEnum
    core_mod.QgsProcessingParameterVectorLayer = QgsProcessingParameterVectorLayer
    core_mod.QgsProcessingParameterFeatureSink = QgsProcessingParameterFeatureSink
    core_mod.QgsProcessingParameterFile = QgsProcessingParameterFile
    core_mod.QgsProcessingParameterString = QgsProcessingParameterString
    core_mod.QgsProcessingParameterBoolean = QgsProcessingParameterBoolean
    core_mod.QgsProcessingParameterNumber = QgsProcessingParameterNumber

    # PyQt attributes
    class MockQWidget:
        def __init__(self, parent=None, *args, **kwargs):
            self._parent = parent
            self._enabled = True
        def setParent(self, parent): self._parent = parent
        def parent(self): return self._parent
        def setEnabled(self, enabled): self._enabled = bool(enabled)
        def isEnabled(self): return bool(self._enabled)
        def setWindowTitle(self, title): pass
        def setLayout(self, layout): pass
        def setMinimumSize(self, *args): pass
        def setMinimumWidth(self, *args): pass
        def setMinimumHeight(self, *args): pass
        def setMaximumHeight(self, *args): pass
        def setFixedHeight(self, *args): pass
        def resize(self, *args): pass
        def show(self): pass
        def hide(self): pass
        def setStyleSheet(self, style): pass
        def setFont(self, font): pass

    class MockQDialog(MockQWidget):
        def exec_(self): return 1
        def exec(self): return 1
        def accept(self): pass
        def reject(self): pass
        def close(self): pass

    class MockQCheckBox(MockQWidget):
        def __init__(self, text="", parent=None):
            super().__init__(parent)
            self._text = text
            self._checked = False
            self.toggled = MockSignal()

        def isChecked(self): return bool(self._checked)
        def setChecked(self, checked):
            self._checked = bool(checked)
            self.toggled.emit(self._checked)
        def text(self): return self._text
        def setText(self, text): self._text = text
        def setToolTip(self, tip): pass

    class MockQSpinBox(MockQWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._value = 0
            self._range = (0, 99999)
        def setValue(self, v): self._value = int(v)
        def value(self): return int(self._value)
        def setRange(self, min_v, max_v): self._range = (min_v, max_v)
        def setToolTip(self, tip): pass

    class MockQDoubleSpinBox(MockQWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._value = 0.0
            self._range = (0.0, 99999.0)
        def setValue(self, v): self._value = float(v)
        def value(self): return float(self._value)
        def setRange(self, min_v, max_v): self._range = (min_v, max_v)
        def setSingleStep(self, step): pass
        def setToolTip(self, tip): pass

    qtcore_mod.QCoreApplication = MockQCoreApplication
    qtcore_mod.QThread = MockQThread
    qtcore_mod.QObject = MockQObject
    qtcore_mod.QVariant = MockQVariant
    qtcore_mod.Qt = MockQt
    qtcore_mod.pyqtSignal = lambda *args, **kwargs: MockSignal()

    qtgui_mod.QWidget = MockQWidget
    qtgui_mod.QDialog = MockQDialog
    qtgui_mod.QCheckBox = MockQCheckBox
    qtgui_mod.QSpinBox = MockQSpinBox
    qtgui_mod.QDoubleSpinBox = MockQDoubleSpinBox

    gui_mod.QgsMapLayerComboBox = QgsMapLayerComboBox

    pyqt_mod.QtCore = qtcore_mod
    pyqt_mod.QtWidgets = qtgui_mod
    pyqt_mod.QtGui = qtwidgets_mod

    qgis_mod.core = core_mod
    qgis_mod.gui = gui_mod
    qgis_mod.utils = utils_mod
    qgis_mod.analysis = analysis_mod
    qgis_mod.__path__ = []
    pyqt_mod.__path__ = []
    qtxml_mod = DynamicMockModule("qgis.PyQt.QtXml")
    qtnetwork_mod = DynamicMockModule("qgis.PyQt.QtNetwork")
    qtsvg_mod = DynamicMockModule("qgis.PyQt.QtSvg")
    qtuic_mod = DynamicMockModule("qgis.PyQt.uic")
    qtuic_mod.loadUiType = lambda *args, **kwargs: (MockUiForm, MockGenericClass)
    pyqt_mod.QtXml = qtxml_mod
    pyqt_mod.QtNetwork = qtnetwork_mod
    pyqt_mod.QtSvg = qtsvg_mod
    pyqt_mod.uic = qtuic_mod

    sys.modules["qgis"] = qgis_mod
    sys.modules["qgis.core"] = core_mod
    sys.modules["qgis.gui"] = gui_mod
    sys.modules["qgis.utils"] = utils_mod
    sys.modules["qgis.analysis"] = analysis_mod
    sys.modules["qgis.PyQt"] = pyqt_mod
    sys.modules["qgis.PyQt.QtCore"] = qtcore_mod
    sys.modules["qgis.PyQt.QtWidgets"] = qtgui_mod
    sys.modules["qgis.PyQt.QtGui"] = qtwidgets_mod
    sys.modules["qgis.PyQt.QtXml"] = qtxml_mod
    sys.modules["qgis.PyQt.QtNetwork"] = qtnetwork_mod
    sys.modules["qgis.PyQt.QtSvg"] = qtsvg_mod
    sys.modules["qgis.PyQt.uic"] = qtuic_mod

    # 2. PyQt5 standalone fallback
    if "PyQt5" not in sys.modules:
        pyqt5_mod = DynamicMockModule("PyQt5")
        pyqt5_qtcore_mod = DynamicMockModule("PyQt5.QtCore")
        pyqt5_qtgui_mod = DynamicMockModule("PyQt5.QtWidgets")
        pyqt5_gui_mod = DynamicMockModule("PyQt5.QtGui")

        pyqt5_qtcore_mod.QVariant = MockQVariant
        pyqt5_qtcore_mod.Qt = MockQt
        pyqt5_qtcore_mod.QCoreApplication = MockQCoreApplication
        pyqt5_qtcore_mod.QObject = MockQObject
        pyqt5_qtcore_mod.pyqtSignal = lambda *args, **kwargs: MockSignal()

        pyqt5_qtgui_mod.QWidget = MockQWidget
        pyqt5_qtgui_mod.QDialog = MockQDialog
        pyqt5_qtgui_mod.QCheckBox = MockQCheckBox
        pyqt5_qtgui_mod.QSpinBox = MockQSpinBox
        pyqt5_qtgui_mod.QDoubleSpinBox = MockQDoubleSpinBox

        pyqt5_mod.QtCore = pyqt5_qtcore_mod
        pyqt5_mod.QtWidgets = pyqt5_qtgui_mod
        pyqt5_mod.QtGui = pyqt5_gui_mod

        sys.modules["PyQt5"] = pyqt5_mod
        sys.modules["PyQt5.QtCore"] = pyqt5_qtcore_mod
        sys.modules["PyQt5.QtWidgets"] = pyqt5_qtgui_mod
        sys.modules["PyQt5.QtGui"] = pyqt5_gui_mod

    # 3. processing module fallback
    if "processing" not in sys.modules or not hasattr(sys.modules["processing"], "gui"):
        proc_mod = DynamicMockModule("processing")
        proc_gui_mod = DynamicMockModule("processing.gui")
        proc_wrappers_mod = DynamicMockModule("processing.gui.wrappers")

        proc_mod.run = MockProcessing.run
        proc_mod.gui = proc_gui_mod
        proc_gui_mod.wrappers = proc_wrappers_mod

        sys.modules["processing"] = proc_mod
        sys.modules["processing.gui"] = proc_gui_mod
        sys.modules["processing.gui.wrappers"] = proc_wrappers_mod

    # 4. openpyxl module fallback
    if "openpyxl" not in sys.modules:
        try:
            import openpyxl
        except ImportError:
            sys.modules["openpyxl"] = DynamicMockModule("openpyxl")

    # 5. requests module fallback
    if "requests" not in sys.modules:
        try:
            import requests
        except ImportError:
            sys.modules["requests"] = DynamicMockModule("requests")

    # 6. osgeo module fallback
    if "osgeo" not in sys.modules:
        try:
            import osgeo
        except ImportError:
            osgeo_mod = DynamicMockModule("osgeo")
            osgeo_mod.__path__ = []
            osgeo_mod.gdal = DynamicMockModule("osgeo.gdal")
            osgeo_mod.gdal.VersionInfo = lambda *args, **kwargs: "3040000"
            osgeo_mod.ogr = DynamicMockModule("osgeo.ogr")
            osgeo_mod.osr = DynamicMockModule("osgeo.osr")
            sys.modules["osgeo"] = osgeo_mod
            sys.modules["osgeo.gdal"] = osgeo_mod.gdal
            sys.modules["osgeo.ogr"] = osgeo_mod.ogr
            sys.modules["osgeo.osr"] = osgeo_mod.osr

    # 7. sip module fallback
    if "sip" not in sys.modules:
        try:
            import sip
        except ImportError:
            sip_mod = DynamicMockModule("sip")
            sip_mod.isdeleted = lambda obj: False
            sys.modules["sip"] = sip_mod

