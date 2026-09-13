from typing import Any
from qgis.PyQt.QtCore import QCoreApplication, QThread, QVariant
from qgis.core import QgsField

_TOTAL_PHASES = 8
_PHASE_LABELS = [
    "Phase 1/8: Initializing",
    "Phase 2/8: Scanning Candidates & Matching Buildings",
    "Phase 3/8: Indexing Roads & Rivers",
    "Phase 4/8: Loading EAs",
    "Phase 5/8: Splitting EAs",
    "Phase 6/8: Merging EAs",
    "Phase 7/8: Compliance Sweep",
    "Phase 8/8: Writing Output",
]

# Resolution of field types compatible with both older QGIS (< 3.38) and newer QGIS (>= 3.38 / 3.40 / Qt 6)
try:
    from qgis.PyQt.QtCore import QMetaType
    _meta_cls = getattr(QMetaType, "Type", None)
    if _meta_cls is not None:
        FIELD_TYPE_STRING = getattr(_meta_cls, "QString", None)
        FIELD_TYPE_INT = getattr(_meta_cls, "Int", None)
        FIELD_TYPE_DOUBLE = getattr(_meta_cls, "Double", None)
    else:
        FIELD_TYPE_STRING = None
        FIELD_TYPE_INT = None
        FIELD_TYPE_DOUBLE = None
except Exception:
    FIELD_TYPE_STRING = None
    FIELD_TYPE_INT = None
    FIELD_TYPE_DOUBLE = None

if FIELD_TYPE_STRING is None or FIELD_TYPE_INT is None or FIELD_TYPE_DOUBLE is None:
    FIELD_TYPE_STRING = getattr(QVariant, "String", 10)
    FIELD_TYPE_INT = getattr(QVariant, "Int", 2)
    FIELD_TYPE_DOUBLE = getattr(QVariant, "Double", 6)

_QVARIANT_MAP = {
    QVariant.String: FIELD_TYPE_STRING,
    QVariant.Int: FIELD_TYPE_INT,
    QVariant.Double: FIELD_TYPE_DOUBLE,
}
for _v_name, _m_name in (
    ("LongLong", "LongLong"),
    ("Bool", "Bool"),
    ("Date", "QDate"),
    ("DateTime", "QDateTime"),
):
    _v_val = getattr(QVariant, _v_name, None)
    if _v_val is not None:
        try:
            from qgis.PyQt.QtCore import QMetaType
            _m_val = getattr(getattr(QMetaType, "Type", None), _m_name, None)
            if _m_val is not None:
                _QVARIANT_MAP[_v_val] = _m_val
        except Exception:
            pass


def create_qgs_field(name: str = "", ftype: Any = None, *args, **kwargs) -> QgsField:
    """Safely constructs a QgsField without triggering DeprecationWarning on QGIS >= 3.38 / Qt 6.

    Automatically maps legacy QVariant.Type constants to modern QMetaType.Type enums
    while preserving backward compatibility with older QGIS versions.
    """
    if ftype is not None:
        ftype = _QVARIANT_MAP.get(ftype, ftype)
        return QgsField(name, ftype, *args, **kwargs)
    return QgsField(name, *args, **kwargs)


def yield_to_ui(counter: int, interval: int = 250) -> None:
    """Yield to Qt event loop periodically so GUI remains responsive."""
    if counter % interval == 0:
        try:
            if hasattr(QThread, "currentThread") and hasattr(QCoreApplication, "instance"):
                inst = QCoreApplication.instance()
                if inst and hasattr(inst, "thread") and QThread.currentThread() == inst.thread():
                    if hasattr(QCoreApplication, "processEvents"):
                        QCoreApplication.processEvents()
        except Exception:
            pass
