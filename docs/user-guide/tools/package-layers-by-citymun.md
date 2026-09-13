# <img src="/icons/package_layers.svg" width="32" height="32" style="vertical-align: middle; display: inline-block; margin-right: 8px;" /> Package Layers by City/Mun

The **Package Layers by City/Mun** tool splits four reference layers — MBI cases, building points, province PSA boundaries, and province LGU boundaries — into one self-contained GeoPackage (`.gpkg`) per city or municipality, each placed in its own dedicated directory. It is engineered for generating local government presentation packages: instead of distributing a single large, province-wide dataset to every recipient, each LGU receives a clean, compact package containing exclusively its own administrative features.

## Access

- **Menu:** Gemma → Others → Package Layers by City/Mun
- **Processing Toolbox:** GMD Pipeline → 1Map → Package Layers by City/Mun
- **Algorithm ID:** `gmd_pipeline:package_layers_by_citymun`

The tool is inherently interactive (allowing layer selection, field confirmation, and output folder browsing), so launching it from either entry point opens the same dialog.

## When to Use

Use this tool when:
- Preparing municipal-level deliverables for LGU presentations, local boundary harmonization meetings, or data handoffs.
- Splitting province-wide reference datasets (cases, building points, PSA boundaries, and LGU boundaries) into standardized per-city/mun packages.
- Automatically loading and grouping packaged layers in the QGIS Layers panel for immediate quality inspection with official QML styles applied.
- Cleaning duplicate layers or standardized display names across repeated packaging sessions.

## Naming Convention

| Item | Pattern | Example |
|------|---------|---------|
| **Output Folder** | `pppmm_CITYMUN/` | `01317_Iriga/` |
| **GeoPackage** | `pppmm_CITYMUN/pppmm_CITYMUN.gpkg` | `01317_Iriga/01317_Iriga.gpkg` |

- `ppp` = 3-digit province code, `mm` = 2-digit city/mun code — combined, the first 5 characters of the geocode field.
- `CITYMUN` is the city/municipality name sanitized for filesystem compatibility (spaces replaced with underscores, special characters stripped).

Inside each GeoPackage, the four reference datasets are written into dedicated tables:

| Role | Output Table Name | Geometry Type |
|------|-------------------|---------------|
| **Cases Layer** | `ref_mbi_cases` | Polygon / MultiPolygon |
| **Building Points Layer** | `ref_{citymun}_bldg_point` | Point / MultiPoint |
| **Province PSA Layer** | `ref_{citymun}_psa` | Polygon / MultiPolygon |
| **Province LGU Layer** | `ref_{citymun}_lgu` | Polygon / MultiPolygon |

## Parameters

### Inputs

| Parameter | Type | Description |
|-----------|------|-------------|
| **Cases layer** | Vector Layer (Polygon) | The reference MBI cases layer (`ref_mbi_cases`) to split. Auto-detected from project layers matching `mbi_cases`. |
| **Building points layer** | Vector Layer (Point) | Province-wide building points layer to split. Auto-detected from project layers matching `bldg_point` or `bldgpts`. |
| **Province PSA layer** | Vector Layer (Polygon) | Province-wide PSA boundary polygon layer to split. Auto-detected from layers matching `province_psa` or `_psa`. |
| **Province LGU layer** | Vector Layer (Polygon) | Province-wide LGU boundary polygon layer to split. Auto-detected from layers matching `province_lgu` or `_lgu`. |
| **Geocode field name** | Field Name | Attribute field on all four layers whose first 5 characters identify the city/mun code (`pppmm`). Auto-detected from `geocode` or `sa_geocode`. |
| **City/Mun name field** | Field Name | Attribute field providing the human-readable city/mun name used to generate folder and table names. Auto-detected from `city_mun` or `citymun`. |
| **Output folder** | Directory Path | Destination root directory where municipal subfolders (`pppmm_CITYMUN/`) will be generated. |
| **Load packaged layers into QGIS after Run** | Boolean | When enabled, automatically loads exported layers into QGIS under the `Packaged Layers` group upon completion. Default is disabled for large national runs to preserve performance. |
| **Add Google Satellite basemap below the layers** | Boolean | Enabled when *Load packaged layers* is checked. Automatically adds the Google Satellite XYZ tile layer at the base of the layer tree. Requires the HCMGIS plugin. |

### Outputs

| Output | Type | Description |
|--------|------|-------------|
| **Municipal GeoPackages** | Directory & `.gpkg` Files | Individual GeoPackage databases written to `pppmm_CITYMUN/pppmm_CITYMUN.gpkg` containing filtered subsets of all four reference layers. |
| **Packaged Layers Group** | Layer Tree Group | (Optional) Auto-expanded group hierarchy in the QGIS Layers panel containing municipal subgroups and styled vector layers. |

## How It Works

1. **City/Municipality Code Scanning**:
   - The tool extracts unique combinations of the 5-digit city/mun code and name across all four input layers combined.
   - Scanning all four layers guarantees that a municipality present in only one input (e.g. LGU boundary without building points) is still packaged without data omission.

2. **Attribute Query & Geometric Export**:
   - Iterates through each detected municipal code and executes an attribute filter:
     $$\text{left}(\text{to\_string}(\text{geocode}), 5) = \text{'pppmm'}$$
   - Matching features from all four reference layers are written into the corresponding tables inside `pppmm_CITYMUN.gpkg`.

3. **Field Cleanup on Export**:
   - System and temporary attributes (`fid`, `layer`, `path`) are automatically omitted during vector export.
   - Removing existing `fid` values allows GeoPackage to assign clean, contiguous primary keys per table, preventing unique constraint violations.
   - Leftover merge provenance fields (`layer`, `path`) are stripped to produce pristine deliverables.

4. **Automated Layer Tree Organization**:
   - When *Load packaged layers* is checked, tables are loaded into the project under `Packaged Layers → {pppmm_CITYMUN}`.
   - Applies matching QML styles from the plugin's bundled style library (`ref_mbi_cases.qml`, `ref_province_psa.qml`, `ref_province_lgu.qml`, `1. Base Layer Building Points.qml`).
   - Automatically expands the group tree so results are immediately visible for verification.

5. **Session-Wide Auto-Organize**:
   - Once the tool runs during a QGIS session, a project listener automatically organizes any layer subsequently added from a packaged GeoPackage (via *Add Vector Layer* or the Browser panel) into its municipal group.
   - Cleans the default `<file> — <table>` prefix applied by QGIS back to the clean table name.
   - Replacing identical tables automatically avoids cluttering the project with duplicate layers.

6. **Duplicate Cleanup Utility**:
   - Provides a dedicated **Clean Up Duplicates** button that scans the `Packaged Layers` hierarchy, identifies duplicate layers referencing identical GeoPackage tables, and removes redundant instances while preserving the newest copy.

## Supported Geometry Types

- **Polygon** and **MultiPolygon** (MBI cases, PSA boundaries, LGU boundaries)
- **Point** and **MultiPoint** (Building points)

::: tip Geocode Attribute Data Type
Ensure the geocode attribute field is formatted as **String/Text** rather than an Integer. Numeric fields strip leading zeros (e.g. `01317` becomes `1317`), which corrupts the 5-character municipal prefix extraction.
:::

::: tip Verification via Run Log
The interactive execution log reports the exact feature count exported for each layer per municipality. If the feature count for a layer remains identical across all municipalities, verify that the selected geocode field actually differentiates municipal units.
:::

::: info Headless Execution
The algorithm (`gmd_pipeline:package_layers_by_citymun`) is interactive. Running headlessly (e.g. via `qgis_process`) logs an informational notice that QGIS Desktop GUI is required rather than halting with an unhandled exception.
:::
