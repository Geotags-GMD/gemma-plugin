from qgis.core import (
    QgsProcessingProvider,
    QgsApplication,
    QgsMessageLog,
    QgsProcessingAlgorithm
)
from qgis.PyQt.QtGui import QIcon
import os
import importlib
import inspect

#Edit this everytime we add or remove a function
#format is .folder_script.filename_script import algorithm_name
from .gmd_scripts.gaps_overlaps_checker import GapsOverlaps
from .gmd_scripts.export_preliminary_polygons import ExportPreliminaryPolygons
from .gmd_scripts.fill_polygon_gaps import FillPolygonGapsAlgorithm
from .gmd_scripts.update_metadata import UpdateLguPsgcMetadataAlgorithm
from .gmd_scripts.update_metadata_by_geocode import UpdateLguByGeocodeAlgorithm
from .gmd_scripts.lgu_fix_processing import FixLGUCRSAlgorithm
from .gmd_scripts.join_barangay_attributes import JoinBarangayAttributes
from .gmd_scripts.scan_geometry_errors import ScanGeometryErrorsAlgorithm
from .gmd_scripts.repair_geometry_errors import RepairGeometryErrorsAlgorithm
from .gmd_scripts.clip_project_layers import ClipProjectLayersAlgorithm
from .gmd_scripts.apply_qml_styles import ApplyQmlStylesAlgorithm
from .gmd_scripts.mbi_validator import MbiValidatorAlgorithm
from .gmd_scripts.mbi_run_analysis import RunAnalysisAlgorithm
from .gmd_scripts.psa_lgu_map_comparison import PsaLguComparisonAlgorithm
from .gmd_scripts.package_layers_by_citymun import PackageLayersAlgorithm
from .references.create_enumeration_area.algorithm import CreateEAAlgorithm
#from .gmd_scripts.gsheet_csv import

class GmdPipelineProvider(QgsProcessingProvider):

    def __init__(self):
        QgsProcessingProvider.__init__(self)


    def initGui(self):
        """Required by QGIS, even if empty for provider-only plugins."""
        pass
    
    def unload(self):
        """
        Unloads the provider. Any tear-down steps required by the provider
        should be implemented here.
        """
        pass

# Edit this everytime we add or remove a function
    def loadAlgorithms(self):
        self.addAlgorithm(GapsOverlaps())
        self.addAlgorithm(ExportPreliminaryPolygons())
        self.addAlgorithm(FillPolygonGapsAlgorithm())
        self.addAlgorithm(UpdateLguPsgcMetadataAlgorithm())
        self.addAlgorithm(UpdateLguByGeocodeAlgorithm())
        self.addAlgorithm(FixLGUCRSAlgorithm())
        self.addAlgorithm(JoinBarangayAttributes())
        self.addAlgorithm(MbiValidatorAlgorithm())
        self.addAlgorithm(RunAnalysisAlgorithm())
        self.addAlgorithm(PsaLguComparisonAlgorithm())
        self.addAlgorithm(PackageLayersAlgorithm())
        self.addAlgorithm(CreateEAAlgorithm())
        self.addAlgorithm(ScanGeometryErrorsAlgorithm())
        self.addAlgorithm(RepairGeometryErrorsAlgorithm())
        self.addAlgorithm(ClipProjectLayersAlgorithm())
        self.addAlgorithm(ApplyQmlStylesAlgorithm())

    def id(self):
        return 'gmd_pipeline'

    def name(self):
        return 'GMD Pipeline'

    def icon(self):
        return QIcon(os.path.dirname(__file__) + '/icons/icon.png')

    def longName(self):
        """
        Returns the a longer version of the provider name, which can include
        extra details such as version numbers. E.g. "Lastools LIDAR tools
        (version 2.2.1)". This string should be localised. The default
        implementation returns the same string as name().
        """
        return self.name()

    def algorithms(self):
        """Returns the list of loaded algorithms."""
        return QgsProcessingProvider.algorithms(self)