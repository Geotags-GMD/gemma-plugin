from __future__ import absolute_import

__author__ = 'Geospatial Management Division'
__date__ = '2025-07-01'
__copyright__ = '(C) 2026, Geospatial Management Division'

import pathlib
import sys

# Add libqfieldsync wheel to sys.path before any imports that need it
src_dir = pathlib.Path(__file__).parent.resolve()
unzipped_whl = src_dir / "references" / "package_qfield" / "unzipped_whl"
libqfieldsync_whl = src_dir / "references" / "package_qfield" / "libqfieldsync.whl"
if unzipped_whl.exists() and str(unzipped_whl) not in sys.path:
    sys.path.insert(0, str(unzipped_whl))
elif libqfieldsync_whl.exists() and str(libqfieldsync_whl) not in sys.path:
    sys.path.append(str(libqfieldsync_whl))


def classFactory(iface):
    """
    Returns an instance of the plugin class.
    This function is required by QGIS.
    """
    from .gmd_pipeline import GMDPipeline
    return GMDPipeline(iface)
