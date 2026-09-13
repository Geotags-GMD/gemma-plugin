__author__ = 'Geospatial Management Division'
__date__ = '2025-12-5'
__copyright__ = '(C) 2025, Geospatial Management Division'


import os
import sys
import inspect
import pathlib
import shutil
import datetime
import processing

from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsProcessingProvider, QgsOfflineEditing, QgsProject
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import QCoreApplication, Qt

from qgis.PyQt.QtCore import QVariant
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtWidgets import QMessageBox
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolButton
from qgis.utils import iface
from .gmd_pipeline_provider import GmdPipelineProvider

# Legacy plugin folder names whose functionality has been merged into GEMMA.
# If these folders are found in the plugins directory they will be automatically
# moved to a quarantine folder so they no longer conflict with GEMMA.
_LEGACY_PLUGINS = {
    'gmd_pipeline': 'GMD Pipeline',
    'qfieldmod':    'QFieldMod',
}


class GMDPipeline(object):

    def __init__(self, iface):
        self.iface = iface
        self.gema_menu = None
        self.updating_boundaries_menu = None
        self.ea_delineation_menu = None
        self.others_menu = None
        self.provider = None
        self.toolbar = None
        self.geometry_toolkit_dlg = None
        self.geometry_legacy_dlg = None
        self.package_layers_dlg = None
        self.check_update_dlg = None
        self.push_dlg = None
        self.check_and_update_action = None
        self.comparison_panel_action = None
        self.projection_finder_action = None
        self.projection_finder_dlg = None
        self.create_ea_action = None
        self.ea_dlg = None
        self.offline_editing = None
        self.ea_provider = None
        self.package_style_loader_action = None
        self.package_style_loader_dlg = None

    def gema_add_submenu(self, submenu, icon):
        if self.gema_menu != None:
            submenu.setIcon(QIcon(icon))
            self.gema_menu.addMenu(submenu)
        else:
            self.iface.addPluginToMenu("&Gemma", submenu.menuAction())


    def initProcessing(self):
        self.provider = GmdPipelineProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)


    def _quarantine_legacy_plugins(self):
        """
        Detect old plugin folders that conflict with GEMMA and move them into
        <gemma-plugin>/_legacy_trash/<timestamp>/<folder>/ so QGIS no longer
        loads them after the next restart.

        Returns a list of display names that were moved, or an empty list if
        nothing needed to be done.
        """
        plugins_dir  = pathlib.Path(__file__).parent.parent   # .../plugins/
        gemma_dir    = pathlib.Path(__file__).parent           # .../gemma-plugin/
        trash_root   = gemma_dir / '_legacy_trash'
        timestamp    = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        trash_target = trash_root / timestamp

        moved = []
        for folder_name, display_name in _LEGACY_PLUGINS.items():
            src = plugins_dir / folder_name
            if src.is_dir():
                trash_target.mkdir(parents=True, exist_ok=True)
                dst = trash_target / folder_name
                try:
                    shutil.move(str(src), str(dst))
                    moved.append(display_name)
                    QgsMessageLog.logMessage(
                        f'GEMMA: moved legacy plugin "{folder_name}" '
                        f'to {dst}',
                        'GEMMA',
                        level=1,  # Qgis.Warning
                    )
                except Exception as exc:
                    QgsMessageLog.logMessage(
                        f'GEMMA: could not move legacy plugin "{folder_name}": {exc}',
                        'GEMMA',
                        level=2,  # Qgis.Critical
                    )
        return moved

    def initGui(self):
        # ── Quarantine legacy plugins ────────────────────────────────────────
        moved = self._quarantine_legacy_plugins()
        if moved:
            names = ', '.join(moved)
            QMessageBox.information(
                self.iface.mainWindow(),
                'GEMMA — Legacy Plugins Removed',
                f'The following old plugin(s) have been automatically moved '
                f'to the trash folder inside GEMMA and will no longer load:\n\n'
                f'  • {chr(10).join(moved)}\n\n'
                f'Their functionality is already built into GEMMA.\n'
                f'Please restart QGIS to complete the cleanup.',
            )
            return  # Let user restart; avoid loading alongside half-unloaded providers
        # ────────────────────────────────────────────────────────────────────

        # ── Ensure plugin dependencies are installed / up-to-date ────────
        from qgis.core import QgsSettings
        import pathlib
        from .dependency_checker import ensure_plugin_dependencies, REQUIRED_PLUGINS
        
        settings = QgsSettings()
        gemma_dir = pathlib.Path(__file__).parent
        metadata_path = gemma_dir / 'metadata.txt'
        
        current_version = 'unknown'
        if metadata_path.exists():
            try:
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith('version='):
                            current_version = line.strip().split('=', 1)[1]
                            break
            except Exception:
                pass
                
        last_checked_version = settings.value("GEMMA/dependencies_checked_version", "")
        
        # Always verify that all required plugins are actually present on disk.
        # The version gate only controls whether we already ran the full
        # repository-fetch + update flow for this GEMMA version; if any
        # dependency is missing we must re-run regardless.
        plugins_dir = gemma_dir.parent  # .../plugins/
        all_present = all(
            (plugins_dir / dep['key']).is_dir()
            for dep in REQUIRED_PLUGINS
        )
        
        if not all_present or last_checked_version != current_version:
            results = ensure_plugin_dependencies()
            # Only record the version as "checked" when every dependency
            # was successfully resolved (already present or just installed).
            still_missing = [
                dep['display_name']
                for dep in REQUIRED_PLUGINS
                if not (plugins_dir / dep['key']).is_dir()
            ]
            if not still_missing:
                settings.setValue("GEMMA/dependencies_checked_version", current_version)
                settings.sync()
            else:
                QgsMessageLog.logMessage(
                    f'Some dependencies are still missing after install attempt: '
                    f'{", ".join(still_missing)}. Will retry on next QGIS startup.',
                    'GEMMA',
                    level=Qgis.Warning,
                )
        # ────────────────────────────────────────────────────────────────────

        self.initProcessing()

        self.gema_menu = QMenu("Gemma")
        self.iface.mainWindow().menuBar().insertMenu(self.iface.firstRightStandardMenu().menuAction(), self.gema_menu)

        packager_icon = QIcon(os.path.dirname(__file__) + "/icons/packager.svg")
        create_ea_icon = QIcon(os.path.dirname(__file__) + "/icons/create_ea.svg")
        geom_toolkit_icon = QIcon(os.path.dirname(__file__) + "/icons/repair_geom.svg")
        others_icon = QIcon(os.path.dirname(__file__) + "/icons/others.svg")
        updating_boundaries_icon = QIcon(os.path.dirname(__file__) + "/icons/updating_boundaries.svg")
        check_and_update_icon = QIcon(os.path.dirname(__file__) + "/icons/check_and_update.svg")
        compare_boundaries_icon = QIcon(os.path.dirname(__file__) + "/icons/compare_boundaries.svg")
        projection_finder_icon = QIcon(os.path.dirname(__file__) + "/icons/projection_finder.svg")
        package_layers_icon = QIcon(os.path.dirname(__file__) + "/icons/package_layers.svg")

        # 1. Updating of Boundaries Submenu
        self.updating_boundaries_menu = QMenu(u'Updating of Boundaries')
        self.gema_add_submenu(self.updating_boundaries_menu, updating_boundaries_icon)

        self.check_and_update_action = QAction(check_and_update_icon, "Check and Update", self.iface.mainWindow())
        self.check_and_update_action.triggered.connect(self.show_check_and_update_dialog)
        self.updating_boundaries_menu.addAction(self.check_and_update_action)

        self.comparison_panel_action = QAction(
            compare_boundaries_icon, "PSA - LGU Comparison Review", self.iface.mainWindow()
        )
        self.comparison_panel_action.triggered.connect(self.show_comparison_panel)
        self.updating_boundaries_menu.addAction(self.comparison_panel_action)

        self.projection_finder_action = QAction(
            projection_finder_icon, "Know Your Projection!", self.iface.mainWindow()
        )
        self.projection_finder_action.triggered.connect(self.show_projection_finder)
        self.updating_boundaries_menu.addAction(self.projection_finder_action)

        package_style_loader_icon = QIcon(os.path.dirname(__file__) + "/icons/package_style_loader.svg")
        self.package_style_loader_action = QAction(
            package_style_loader_icon, "Package Style Loader", self.iface.mainWindow()
        )
        self.package_style_loader_action.triggered.connect(self.show_package_style_loader_dialog)
        self.updating_boundaries_menu.addAction(self.package_style_loader_action)

        # 2. EA Delineation Submenu
        self.ea_delineation_menu = QMenu(u'EA Delineation')
        self.gema_add_submenu(self.ea_delineation_menu, create_ea_icon)

        self.create_ea_action = QAction(create_ea_icon, "EA Delineation and Merging", self.iface.mainWindow())
        self.create_ea_action.triggered.connect(self.show_create_ea_dialog)
        self.ea_delineation_menu.addAction(self.create_ea_action)

        self.package_qfield_action = QAction(packager_icon, "Package for QField", self.iface.mainWindow())
        self.package_qfield_action.triggered.connect(self.show_package_dialog)
        self.package_qfield_action.setShortcut("Ctrl+Alt+Q")
        self.ea_delineation_menu.addAction(self.package_qfield_action)

        # 3. Others Submenu
        self.others_menu = QMenu(u'Others')
        self.gema_add_submenu(self.others_menu, others_icon)

        self.geometry_legacy_action = QAction(geom_toolkit_icon, "Geometry Check & Repair (Legacy)", self.iface.mainWindow())
        self.geometry_legacy_action.triggered.connect(self.show_geometry_legacy)
        self.others_menu.addAction(self.geometry_legacy_action)

        self.package_layers_action = QAction(package_layers_icon, "Package Layers by City/Mun", self.iface.mainWindow())
        self.package_layers_action.triggered.connect(self.show_package_layers_dialog)
        self.others_menu.addAction(self.package_layers_action)

        # Gemma Toolbar (Ordered Chronologically: Check and Update -> Create EAs -> Package for QField)
        self.toolbar = self.iface.addToolBar("Gemma Toolbar")
        self.toolbar.setObjectName("Gemma Toolbar")

        # 1. Check and Update
        self.check_and_update_toolbar_action = QAction(
            check_and_update_icon, "Check and Update", self.iface.mainWindow()
        )
        self.check_and_update_toolbar_action.triggered.connect(self.show_check_and_update_dialog)
        self.toolbar.addAction(self.check_and_update_toolbar_action)

        # 2. EA Delineation and Merging
        self.create_ea_toolbar_action = QAction(
            create_ea_icon, "EA Delineation and Merging", self.iface.mainWindow()
        )
        self.create_ea_toolbar_action.triggered.connect(self.show_create_ea_dialog)
        self.toolbar.addAction(self.create_ea_toolbar_action)

        # 3. Package for QField
        self.package_qfield_toolbar_action = QAction(
            packager_icon, "Package for QField", self.iface.mainWindow()
        )
        self.package_qfield_toolbar_action.triggered.connect(self.show_package_dialog)
        self.toolbar.addAction(self.package_qfield_toolbar_action)

        # Initialize offline editing for QField packaging
        self.offline_editing = QgsOfflineEditing()


    def unload(self):
        # Every addDockWidget needs a matching removal, or a stale panel is
        # left behind in the main window after the plugin is unloaded.
        try:
            from .gmd_scripts.psa_lgu_comparison_panel import close_comparison_panel
            close_comparison_panel(self.iface)
        except Exception:
            pass

        if self.gema_menu is not None:
            self.iface.mainWindow().menuBar().removeAction(self.gema_menu.menuAction())

        if self.projection_finder_dlg is not None:
            try:
                self.projection_finder_dlg.close()
            except Exception:
                pass
            self.projection_finder_dlg = None

        if self.package_style_loader_dlg is not None:
            try:
                self.package_style_loader_dlg.close()
            except Exception:
                pass
            self.package_style_loader_dlg = None

        if self.toolbar:
            del self.toolbar
            self.toolbar = None

        if self.provider:
            try:
                QgsApplication.processingRegistry().removeProvider(self.provider)
            except Exception as e:
                QgsApplication.instance().messageLog().logMessage(
                    f"Error removing GMD Pipeline provider: {e}",
                    'GMD')
            finally:
                del self.provider
                self.provider = None

    def show_geometry_legacy(self):
        """Open the Geometry Check & Repair (Legacy) dialog."""
        from .gmd_scripts.geom_check_repair_legacy import GeometryCheckRepairLegacyDialog

        if self.geometry_legacy_dlg is None:
            self.geometry_legacy_dlg = GeometryCheckRepairLegacyDialog(self.iface)

        self.geometry_legacy_dlg.show()
        self.geometry_legacy_dlg.raise_()
        self.geometry_legacy_dlg.activateWindow()

    def show_package_layers_dialog(self):
        """Open the Package Layers by City/Mun dialog."""
        from .gmd_scripts.package_layers_by_citymun import PackageLayersDialog

        # Guard against a stale C++ wrapper from a previously closed dialog
        try:
            if self.package_layers_dlg is not None:
                self.package_layers_dlg.isVisible()
        except RuntimeError:
            self.package_layers_dlg = None

        if self.package_layers_dlg is None:
            self.package_layers_dlg = PackageLayersDialog(self.iface)

        self.package_layers_dlg.show()
        self.package_layers_dlg.raise_()
        self.package_layers_dlg.activateWindow()

    def show_package_dialog(self):
        """
        Package to QField
        """
        from .gmd_scripts.package_qfield import show_package_dialog
        
        # --- COMMENTED OUT PASSWORD FEATURE ---
        #import hashlib
        #from qgis.PyQt.QtWidgets import QInputDialog, QLineEdit, QMessageBox
        
        #SUPERVISOR_PASSWORD = "bf315bbc2404a161fafeb42995c6197ca17d689b33e7082bfbf2aae386ab755b"
        
        #password, ok = QInputDialog.getText(
        #    self.iface.mainWindow(), 
        #    "Supervisor Access Required", 
        #    "Please enter the supervisor password to access Package for QField:", 
        #    QLineEdit.Password
        #)
        
        #if ok and hashlib.sha256(password.encode()).hexdigest() == SUPERVISOR_PASSWORD:
        #    self.push_dlg = show_package_dialog(
        #        self.iface, 
        #        self.offline_editing, 
        #        self.push_dialog_finished
        #    )
        #elif ok:
        #    QMessageBox.warning(self.iface.mainWindow(), "Access Denied", "Incorrect password.")
        #--------------------------------------

        # Directly open the dialog (original behavior)
        self.push_dlg = show_package_dialog(
            self.iface, 
            self.offline_editing, 
            self.push_dialog_finished
        )

    def show_check_and_update_dialog(self):
        """Open the Check and Update boundary management dialog."""
        from .gmd_scripts.check_and_update_dialog import CheckAndUpdateDialog

        if self.check_update_dlg is None:
            self.check_update_dlg = CheckAndUpdateDialog(self.iface)

        self.check_update_dlg.showNormal()
        self.check_update_dlg.show()
        self.check_update_dlg.raise_()
        self.check_update_dlg.activateWindow()

    def show_comparison_panel(self):
        """Reopen the PSA - LGU comparison review panel for Matched layers
        that are already loaded, without re-running the algorithm."""
        from .gmd_scripts.psa_lgu_comparison_panel import show_comparison_panel

        if show_comparison_panel(self.iface) is None:
            QMessageBox.information(
                self.iface.mainWindow(),
                "PSA - LGU Comparison Review",
                "No comparison output layers were found in this project.\n\n"
                "Run the 'PSA - LGU Boundary Comparison' tool from the Processing "
                "Toolbox first -- the panel opens automatically when it finishes.",
            )

    def show_create_ea_dialog(self):
        """Open the Create Enumeration Areas dialog."""
        from .references.create_enumeration_area.dialog import EALauncherDialog

        # Guard against stale C++ wrapper from a previously closed dialog
        try:
            if self.ea_dlg is not None:
                self.ea_dlg.isVisible()
        except RuntimeError:
            self.ea_dlg = None

        if self.ea_dlg is None:
            self.ea_dlg = EALauncherDialog(self.iface.mainWindow())
        else:
            self.ea_dlg.refresh_all()

        self.ea_dlg.showNormal()
        self.ea_dlg.show()
        self.ea_dlg.raise_()
        self.ea_dlg.activateWindow()

    def show_projection_finder(self):
        """Open the Know Your Projection! (Projection Finder) dialog."""
        from .gmd_scripts.projection_finder import ProjectionToolkit

        try:
            if self.projection_finder_dlg is not None:
                self.projection_finder_dlg.isVisible()
        except RuntimeError:
            self.projection_finder_dlg = None

        if self.projection_finder_dlg is None:
            self.projection_finder_dlg = ProjectionToolkit(self.iface)

        self.projection_finder_dlg.showNormal()
        self.projection_finder_dlg.show()
        self.projection_finder_dlg.raise_()
        self.projection_finder_dlg.activateWindow()

    def push_dialog_finished(self):
        """
        When the push dialog is closed, make sure it's no longer
        enabled before cleanup.
        """
        try:
            self.push_dlg.setEnabled(False)
        except RuntimeError:
            pass

    def show_package_style_loader_dialog(self):
        """Open the Package Style Loader dialog."""
        from .gmd_scripts.package_style_loader import show_package_style_loader_dialog

        try:
            if self.package_style_loader_dlg is not None:
                self.package_style_loader_dlg.isVisible()
        except RuntimeError:
            self.package_style_loader_dlg = None

        if self.package_style_loader_dlg is None:
            self.package_style_loader_dlg = show_package_style_loader_dialog(self.iface)
        else:
            self.package_style_loader_dlg.showNormal()
            self.package_style_loader_dlg.show()
            self.package_style_loader_dlg.raise_()
            self.package_style_loader_dlg.activateWindow()

    # Alias for backward compatibility
    show_layer_groups_styles_dialog = show_package_style_loader_dialog