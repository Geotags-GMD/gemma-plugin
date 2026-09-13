# Getting Started

## What is GEMMA?

**GEMMA** stands for **GIS Extension for Map Management and Analysis**. It is a QGIS processing plugin developed by the **Geospatial Management Division (GMD)** of the **Philippine Statistics Authority (PSA)**.

The plugin provides a comprehensive suite of GIS tools for official boundary management, topology checking, geometry repair, PSGC metadata standardization, enumeration area delineation, and mobile field data collection packaging.

## Requirements

| Requirement | Minimum Version | Recommended Version |
|-------------|-----------------|---------------------|
| QGIS        | 3.0 or later    | QGIS 3.40 LTR       |
| Python      | 3.x (bundled with QGIS) | Python 3.9+ |
| OS          | Windows, macOS, or Linux | Windows 10/11 |

## Installation

### Method 1: QGIS Plugin Repository (Recommended)

Installing via custom repository allows QGIS to automatically detect and notify you of plugin updates:

1. Open **QGIS**.
2. Go to **Plugins → Manage and Install Plugins**.
3. Select the **Settings** tab.
4. Click **Add…** to add a repository.
5. Set Name to `GEMMA Repository` and URL to:
   ```
   https://gemma-plugin.vercel.app/gemma.xml
   ```
6. Click **OK**, then click **Reload All Repositories**.
7. Go to the **All** tab, search for **GEMMA**, and click **Install Plugin**.

### Method 2: Install from ZIP

1. Download the latest release from the [GitHub Releases page](https://github.com/GMD-Repository/gemma-plugin/releases/latest).
2. Open **QGIS**.
3. Go to **Plugins → Manage and Install Plugins**.
4. Select the **Install from ZIP** tab.
5. Click **Browse** and select the downloaded `gemma-plugin-v*.zip` file.
6. Click **Install Plugin**.

## User Interface & Menu Overview

After installation, GEMMA tools can be accessed through three interfaces in QGIS: the **Gemma Menu**, the **Gemma Toolbar**, and the **Processing Toolbox**.

### Gemma Menu Bar

The **Gemma** menu is added to the top menu bar in QGIS, structured into logical submenus:

| Submenu | Action / Tool | Shortcut | Description |
|---------|---------------|----------|-------------|
| **Updating of Boundaries** | [Check and Update](/tools/check-and-update) | — | 3-Phase dialog for georeferencing navigation, error scanning/repair, and PSGC metadata updating |
| **Updating of Boundaries** | [PSA - LGU Comparison Review](/tools/psa-lgu-comparison#comparison-review-panel) | — | Opens the comparison dock panel to review matched PSA and LGU boundary layers side-by-side |
| **Updating of Boundaries** | [Know Your Projection!](/tools/know-your-projection) | — | Coordinate diagnosis, Philippine CRS auto-detection, and 2D affine georeferencing |
| **Updating of Boundaries** | [Package Style Loader](/tools/package-style-loader) | — | Interactive dialog to organize layer hierarchies and apply QML symbology and labeling |
| **EA Delineation** | [EA Delineation and Merging](/tools/ea-delineation-and-merging) | — | Launcher dialog for pre-processing, gap filling, delineation, and merging of enumeration areas |
| **EA Delineation** | [Package for QField](/tools/package-qfield) | `Ctrl+Alt+Q` | Offline project packaging dialog for field data collection with QField |
| **Others** | [Geometry Repair Toolkit](/tools/geometry-repair-toolkit) | — | Standalone dialog for scanning, canvas highlighting, and in-place polygon geometry repairs |
| **Others** | [Package Layers by City/Mun](/tools/package-layers-by-citymun) | — | Split reference layers into municipal GeoPackages placed in individual city/mun folders |

### Gemma Toolbar

The **Gemma Toolbar** provides immediate one-click access to core interactive dialog workflows:

| Icon | Tool | Access | Description |
|------|------|--------|-------------|
| <img src="/icons/check_and_update.svg" width="20" height="20" style="vertical-align: middle; display: inline-block;" /> | [Check and Update](/tools/check-and-update) | Toolbar Button | Open the 3-Phase boundary management dialog |
| <img src="/icons/create_ea.svg" width="20" height="20" style="vertical-align: middle; display: inline-block;" /> | [EA Delineation and Merging](/tools/ea-delineation-and-merging) | Toolbar Button | Open the Enumeration Area delineation launcher |
| <img src="/icons/packager.svg" width="20" height="20" style="vertical-align: middle; display: inline-block;" /> | [Package for QField](/tools/package-qfield) | Toolbar Button | Package layers for mobile field data collection (`Ctrl+Alt+Q`) |

### Processing Toolbox — GMD Pipeline

All batch processing algorithms are integrated into the QGIS Processing framework under the **GMD Pipeline** provider:

1. Open the Processing Toolbox by clicking **Processing → Toolbox** or pressing `Ctrl+Alt+T`.
2. Expand the **GMD Pipeline** provider tree to access individual processing algorithms.

## Tool Directory

GEMMA tools are organized into three primary functional suites matching the documentation guides:

### 1Map Tools

Tools designed for LGU boundary management, 1Map data harmonization, topology auditing, and official PSGC metadata standardization:

| Tool | Access | Description |
|------|--------|-------------|
| [MBI Checker](/tools/mbi-checker) | Processing Toolbox | Detect gaps and overlaps between barangay polygon boundaries with building point validation and reference case exclusion |
| [MBI Validator](/tools/mbi-validator) | Processing Toolbox | Cross-check Reference MBI layers against Checker GAP/OVERLAP layers to audit status mismatches |
| [Run Analysis](/tools/run-analysis) | Processing Toolbox | Perform boundary discrepancy detection across polygon layers and building points, generating reference MBI case layers |
| [Fill Polygon Gaps](/tools/fill-polygon-gaps) | Processing Toolbox | Automatically fill gaps between polygons and assign them to neighboring barangays |
| [Export Preliminary Polygons](/tools/export-preliminary-polygons) | Processing Toolbox | Merge and export resolved boundary layers into consolidated GeoPackages for 1Map submission |
| [Update Metadata](/tools/update-metadata) | Processing Toolbox | Standardize LGU boundary layers with PSGC geocodes, cascading administrative filters, and GPKG export |
| [Update Metadata (by Geocode)](/tools/update-metadata-by-geocode) | Processing Toolbox | Perform direct PSGC left-join on LGU boundary layers using geocodes, auto-populating 15-attribute schemas |
| [Fix LGU CRS / Geometry](/tools/fix-lgu-crs) | Processing Toolbox | Batch-correct local arbitrary grid coordinates (~0 to ~100,000) to standard WGS 84 (EPSG:4326) |
| [Join Barangay Attributes](/tools/join-barangay-attributes) | Processing Toolbox | Match vector attributes with official PSGC tables via fuzzy matching and Roman numeral normalization |
| [Check and Update](/tools/check-and-update) | Menu & Toolbar | Interactive 3-Phase dialog workflow for georeferencing, geometry error scanning/repair, and metadata updating |
| [PSA - LGU Boundary Comparison](/tools/psa-lgu-comparison) | Processing Toolbox | Audit PSA reference boundaries against LGU-submitted polygons using geocodes, alignment models, and building point validation |
| [Know Your Projection!](/tools/know-your-projection) | Menu & Processing Toolbox | Diagnose CRS, auto-detect Philippine candidates, and georeference local CAD grids |
| [Package Layers by City/Mun](/tools/package-layers-by-citymun) | Menu & Processing Toolbox | Split reference layers into municipal GeoPackages placed in individual city/mun folders |
| [Package Style Loader](/tools/package-style-loader) | Gemma Menu | Interactive dialog to organize layer hierarchies and apply QML symbology and labeling |

### Geometry & Repair

Tools for validating, diagnosing, and repairing vector polygon geometry defects:

| Tool | Access | Description |
|------|--------|-------------|
| [Geometry Repair Toolkit](/tools/geometry-repair-toolkit) | Gemma → Others | Standalone interactive dialog to scan, highlight on map canvas, and repair invalid geometries in-place |
| [Scan Geometry Errors](/tools/scan-geometry-errors) | Processing Toolbox | Scan vector polygon layers for specific geometry and topology defects and generate a Point Error Layer |
| [Repair Polygon Geometries](/tools/repair-polygon-geometries) | Processing Toolbox | Reconstruct invalid polygon geometries and recover missing shapes into a clean vector output layer |
| [Clip Project Layers by Extent](/tools/clip-project-layers) | Processing Toolbox | Batch clip multiple vector layers to a target administrative polygon boundary with optional buffer |

### QField & Enumeration

Tools for field data collection packaging and census Enumeration Area delineation:

| Tool | Access | Description |
|------|--------|-------------|
| [Package for QField](/tools/package-qfield) | Menu & Toolbar (`Ctrl+Alt+Q`) | Package QGIS project layers for mobile offline field data collection with QField |
| [EA Delineation and Merging](/tools/ea-delineation-and-merging) | Menu & Toolbar | Unified module for pre-processing, gap filling, delineation (splitting), and merging of Enumeration Area boundaries |

## Updating the Plugin

- **Repository Install**: QGIS automatically checks for updates on launch. Navigate to **Plugins → Manage and Install Plugins → Upgrade All**.
- **ZIP Install**: Download the latest ZIP and re-install via **Install from ZIP** to overwrite the previous version.

## Changelog

For version history and detailed release notes, check our dedicated [Changelog Page](/changelog) or visit [GitHub Releases](https://github.com/GMD-Repository/gemma-plugin/releases).

## Support

For bug reports and feature requests, please use the [GitHub Issues](https://github.com/GMD-Repository/gemma-plugin/issues) page.

For direct support, contact the GMD team at **gmd.support@psa.gov.ph**.
