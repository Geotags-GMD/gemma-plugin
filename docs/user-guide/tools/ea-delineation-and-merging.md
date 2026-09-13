# <img src="/icons/create_ea.svg" width="32" height="32" style="vertical-align: middle; display: inline-block; margin-right: 8px;" /> EA Delineation and Merging

The **EA Delineation and Merging** module automates the pre-processing, spatial aggregation, delineation (splitting), and merging of census Enumeration Areas (EAs) based on building household load, spatial contiguity, administrative barangay boundaries, and linear feature alignment (roads and rivers).

It combines two core processing tabs in a single integrated launcher dialog:

1. **Tab 1: EA Preprocessing** &mdash; Enforces spatial coverage rules, clips EAs extending outside Barangay boundaries, and fills uncovered coverage gaps within parent Barangays.
2. **Tab 2: EA Delineation & Merging** &mdash; Executes building point household aggregation, candidate classification, single-pass splitting for overpopulated EAs (>300 HH), and iterative spatial merging for underpopulated EAs (<=100 HH).

## Access

- **Processing Toolbox:** GMD Pipeline → 1Map → EA Delineation and Merging
- **Algorithm ID:** `gmd_pipeline:createea`
- **Menu:** Gemma → EA Delineation → EA Delineation and Merging
- **Toolbar:** Gemma Toolbar → EA Delineation and Merging icon

## When to Use

Use this module when:

- Cleaning and preparing starting EA polygon layers prior to census field operations.
- Enforcing 100% complete polygon coverage within Barangay administrative boundaries (no uncovered gaps).
- Re-balancing EA boundaries to ensure enumerator workloads fall within a target household range (default 100 to 300 households).
- Delineating overpopulated EAs (>300 households) using building point spatial clustering and road/river network centrelines.
- Merging underpopulated EAs (<=100 households) with adjacent contiguous neighbors within the same barangay boundary.

## Module Interface & Features

The **EA Delineation and Merging** launcher dialog provides an interactive workflow prior to executing processing routines:

- **Dual-Tab Processing Launcher:** Switch seamlessly between **EA Preprocessing** (Tab 1) and **EA Delineation & Merging** (Tab 2).
- **Auto-Detect Project Layers:** Automatically scans open layers in the QGIS project and populates input dropdowns based on standard layer naming conventions (`_bgy`, `_ea`, `_bldgpts`, `road`, `river`).
- **Auto Arrange Layers:** One-click utility inside **Input Layers** on **Tab 1 (EA Preprocessing)** that restructures project layer tree nodes into `<PSGC>_<City_Mun>_MBI` and `<PSGC>_<City_Mun>_baselayers` groups, re-orders layers (Points → Lines → Polygons → Rasters), renames gaps/overlaps (`<PSGC>_gaps`, `<PSGC>_overlaps`), and applies official GEMMA QML style templates (`1. Base Layer Building Points.qml`, `2. Base Layer Landmark.qml`, etc.).
- **Fill Missing Household Counts:** Built-in utility to compute missing household counts (`hh_count`) directly from building points within each EA polygon before running delineation algorithms.
- **KPI Summary Cards & Candidate Preview:** Renders dynamic statistics and color-coded candidate tables for Delineation (>300 HH) and Merging (<=100 HH) candidates before execution.

---

## Tab 1 — EA Preprocessing

The **EA Preprocessing** tab prepares starting EA boundaries before running delineation algorithms by enforcing two fundamental spatial rules:

1. **Rule 1 (Clip to Barangay)**: Every EA polygon must be completely within its parent Barangay boundary.
2. **Rule 2 (Gap Filling)**: Every Barangay must be fully covered by its constituent EAs with zero uncovered coverage gaps remaining.

### Parameters & Options

| Parameter | Type | Description |
|-----------|------|-------------|
| **Barangay Layer** | Vector (Polygon) | Administrative barangay polygon boundaries. Must contain a `geocode` field used to assign parent barangay codes. Required. |
| **EA Layer** | Vector (Polygon) | Starting EA polygon boundaries to be pre-processed. Optional; if left unselected, a new EA layer is automatically created based on the Barangay layer input. |
| **Designated Output Folder** | Folder Path | Directory where the output `.gpkg` GeoPackage file will be saved. Defaults to standard PSA-GIS / Project 1MAP preprocessing subfolder (`1_Reset EAs` or `2_Adjusted EAs`). Required. |
| **Gap Area Tolerance (m²)** | Double | Minimum area threshold (default: `1.0 m²`) for a gap to be processed; smaller gaps are treated as geometry precision slivers and skipped. |
| **Clip EA to Barangay Boundary** | Boolean | When enabled (default: `True`), clips any portion of an EA extending outside its parent Barangay boundary. |
| **Detect Uncovered Barangay Areas** | Boolean | When enabled (default: `True`), identifies uncovered gaps within each Barangay after clipping. |
| **Assign Gaps to Contiguous EA** | Boolean | When enabled (default: `True`), assigns each detected gap to the adjacent EA sharing the longest boundary edge. |

### Designated Output Folder & Permanent GeoPackage (.gpkg) Export

Tab 1 allows you to designate the target destination directory before running:
- **Auto-Populated Default Directory**: Automatically detects the drive and province to populate:
  `<drive>:\PSA-GIS\<province name>\Project 1MAP\3_EA Delineation and Merging\2_Pre-Processing\<1_Reset EAs or 2_Adjusted EAs>`
- **Directory Browser**: Click the `...` folder picker button to designate or browse to any custom folder on any drive.
- **Permanent Export**: When **Run** is executed, the preprocessed layer is saved directly into the designated folder as `<pppmm>_ea2026_preprocessed.gpkg` using QGIS Processing (`native:savefeatures`), and the permanent layer is loaded onto your QGIS canvas.

### EA Preprocessing Output & Attribute Fields

| Output / Field Name | Type | Description |
|---------------------|------|-------------|
| **Pre-Processed EA Layer** | Vector (Polygon / GeoPackage) | Saved GeoPackage polygon layer (`<5-digit geocode>_ea2026_preprocessed.gpkg`) inside designated sub-folder (`1_Reset EAs` or `2_Adjusted EAs`) containing aligned and gap-filled EAs. |
| **hhcount** | Double | Household count for the EA polygon. |
| **bldgcount** | Integer | Building count for the EA polygon. |
| **original_area** | Double | Original surface area of the starting EA polygon in square metres. |
| **corrected_area** | Double | Corrected surface area of the EA polygon after boundary clipping and gap assignment in square metres. |
| **area_change** | Double | Net area change (square metres) computed as `corrected_area - original_area`. |
| **pre_action** | String | Pre-processing action applied (`No Change`, `Clipped`, `Gap Assigned`, `Geometry Fixed`, or `Unresolved`). |
| **pre_status** | String | Validation status (`Valid`, `Corrected`, `Unresolved`, or `Error`). |

---

## Tab 2 — Create Enumeration Areas

The **Create Enumeration Areas** tab executes spatial aggregation, proposed boundary cut line generation for overpopulated EAs without destructively splitting EA polygons, and iterative merging for underpopulated EAs.

To provide a clean and focused workflow, Tab 2 is split into two dedicated sub-tabs with **completely separated Live Preview tables, Execution Log consoles, and Action Run Buttons**:

1. **Proposed Delineation Sub-Tab**: Focused on overpopulated EAs (`> 300 HH`). Features delineation threshold settings, road/river boundary snapping parameters, an isolated **Delineation Candidates Preview** table with KPI counter card, a dedicated delineation execution log console, and two action buttons:
   - **Extract Delineation Candidate**: Generates and loads candidate layers (`<geocode>_delineated_ea2026.gpkg`, `<geocode>_delineation_candidates`, `<geocode>_extracted_bldgpts`, `<geocode>_eadel_update.gpkg`).
   - **Run Delineation**: Opens a dedicated modal pop-up to split EA polygons with proposed cut lines in-place and recalculate building and household counts.
2. **Proposed Merging Sub-Tab**: Focused on underpopulated EAs (`<= 100 HH`). Features merging threshold settings, under-threshold candidate-to-candidate merging toggles, an isolated **Merge Candidates Preview** table with KPI counter card, a dedicated merging execution log console, and two action buttons:
   - **Extract Merge Candidate**: Generates and loads candidate layers (`<geocode>_merged_ea2026.gpkg`, `<geocode>_extracted_bldgpts`).
   - **Unmerge EA**: Opens a dedicated modal pop-up to unmerge recently merged EA polygons back into their constituent original geometries based on the EA previous layer, updating the merged layer in-place and recalculating `hh_count` (from building points `est_hhcount`) and `bldg_count` for each restored EA.
3. **Merge Preview Tab (Individual EA Merging & Threshold Gating)**:
   - Dedicated preview tab evaluating candidate EAs from the **Merged EA Layer** against potential contiguous absorptive partners in the **Previous EA Layer**.
   - Structured with an 8-column layout: `Geocode`, `Barangay`, `EA Name`, `Household Count`, `Role / Status`, `Merge Partner (EAN)`, `Total HH Count`, and `Action`.
   - **Maximum Threshold Gating**: Evaluates candidates against the maximum household threshold limit. If combined candidate EA and partner EA households exceed the maximum threshold (`max_hh`), that partner is excluded. If no partner meets the threshold criteria (or candidate EA alone exceeds the maximum threshold), the `Merge Partner (EAN)` dropdown is empty and disabled, and the `Action` button is disabled.
   - **Individual EA Merging**: Allows granular, on-demand merging row-by-row via the green `[Merge]` action button. Clicking `[Merge]` unites candidate and partner geometries (`combine().buffer(0).makeValid()`), aggregates combined household counts, registers the merged polygon into `<geocode>_merged_ea2026` (and exports to `.gpkg` if an output folder is defined), updates the row status to `Merged ✓`, and locks the row against re-merging.

> [!TIP]
> **Two-Way Synchronization**: Selecting input layers, designating output directories, updating search filters, or adjusting shared threshold parameters in either sub-tab automatically synchronizes the corresponding controls across both sub-tabs in real time. Running either action button automatically discards temporary in-memory outputs belonging to the opposite sub-tab mode.

### Parameters & Options

| Parameter | Type | Description |
|-----------|------|-------------|
| **Barangay Layer** | Vector (Polygon) | Administrative barangay boundaries (`geocode` field required). Synchronized across both sub-tabs. Required. |
| **Building Point Layer** | Vector (Point) | Structure/building point data with an `hhcount` field representing households per building. Synchronized across both sub-tabs. Required. |
| **Previous EA Layer** | Vector (Polygon) | Starting EA boundaries from previous census round (or pre-processed output from Tab 1). Synchronized across both sub-tabs. Required. |
| **Road Layer** | Vector (Line) | Road network lines used to snap EA split boundaries to road centrelines (Delineation sub-tab). Optional. |
| **River Layer** | Vector (Line) | River and waterway centrelines used for split line snapping (Delineation sub-tab). Optional. |
| **Minimum Household Count per EA** | Integer | Minimum target household threshold per EA (default: `100`). EAs below this limit are classified as merge candidates. |
| **Maximum Household Count per EA** | Integer | Maximum target household threshold per EA (default: `300`). EAs above this limit generate proposed delineation cut lines. |
| **Splitting Rule (>300 Houses)** | Enumeration | Controls splitting rule: `Follow Roads & Rivers (Recommended)`, `Strict Minimum 100 Houses`, or `Do Not Split`. |
| **Boundary Cut Method** | Enumeration | Selects line tool for splitting: `Auto (Roads First, then Houses)`, `Roads & Rivers Only`, `House Groups Only`, `Straight Line Only`, or `Do Not Split`. |
| **Optimize for Compactness** | Boolean | Prefers spatially compact EA shapes over purely household-balanced splits (default: `True`). |
| **Allow Merging Candidate EAs** | Boolean | Allows candidate EAs (<=100 HH) to merge with each other when no reference EAs exist (default: `True`). |
| **Sliver Polygon Area Threshold** | Enumeration | Threshold for identifying and dissolving remnant sliver polygons into neighboring EAs. |
| **Snapping Tolerance (metres)** | Double | Maximum search distance for snapping proposed split lines to road or river centrelines (default: `15.0 m`). |
| **Target CRS** | CRS | Output Coordinate Reference System (default: `EPSG:4326`). Synchronized across both sub-tabs. |

### Outputs & QML Symbology Styles

| Output Layer | Sub-Tab Mode | Type | Style File (.qml) | Description |
|--------------|--------------|------|-------------------|-------------|
| **Extracted Building Points** | Delineation & Merging | Vector (Point) | `extracted_bldgpts.qml` | Extracted building points with aggregated household counts (`<geocode>_extracted_bldgpts`). Styled with brown symbology for distinct visibility during feature selection. |
| **Delineated EAs Layer** | Delineation | Vector (Polygon) | `ea_output.qml` | Permanent GeoPackage layer containing candidate EAs evaluated for delineation (`<geocode>_delineated_ea2026.gpkg`). |
| **Proposed Boundary Cut Lines** | Delineation | Vector (Line) | `eadel_update_lines.qml` | Permanent GeoPackage line layer (`<geocode>_eadel_update.gpkg`) representing proposed boundary cut lines generated from road/river/cluster splits. |
| **Candidate for Delineation Layer** | Delineation | Vector (Polygon) | `delineation_candidates.qml` | Layer containing EAs identified as candidates for delineation (>300 HH). Styled with amber highlight. |
| **Merged EAs Layer** | Merging | Vector (Polygon) | `ea_output.qml` | Permanent GeoPackage layer containing EAs generated from merging underpopulated EAs (`<geocode>_merged_ea2026.gpkg`). |
### Final Output Attribute Schema (`delineated_ea2026`, `merge_ea2026`)

The output layers `<geocode>_delineated_ea2026` and `<geocode>_merged_ea2026` share the following 18 standard attributes:

| Field Name | Type | Description |
|------------|------|-------------|
| **fid** | Integer | Feature Identifier (primary key). |
| **map_uuid** | String | Unique UUID assigned to the map sheet or starting EA polygon. |
| **geocode** | String | Full 9–14 digit PSGC administrative geocode for the EA polygon. |
| **region** | String | Region administrative code or name. |
| **province** | String | Province administrative code or name. |
| **city_mun** | String | City / Municipality administrative code or name. |
| **barangay** | String | Barangay administrative code or name. |
| **code** | String | PSGC administrative code / reference suffix. |
| **name** | String | Formatted Enumeration Area display label (e.g. `EA 001000`). |
| **ean** | String | Original starting Enumeration Area Number prior to processing. |
| **hhcount** | Double | Original household count from the starting EA input layer. |
| **bldgcount** | Integer | Original building count from the starting EA input layer. |
| **sy** | String / Integer | Survey Year / Census round identifier (e.g. `2026`). |
| **new_ean** | String | Newly assigned post-delineation 6-digit EA sequence number code (e.g. `001000`). |
| **hh_count** | Integer | New total household count aggregated from building points assigned to this polygon (whole number). |
| **bldg_count** | Integer | New total building point count contained in this polygon. |
| **ea_type** | String | EA classification and transformation type (`DELINEATED`, `MERGED`, or `RETAINED`). |
| **remarks** | String | Processing note detailing action or split strategy (e.g. `Split along road network`, `Merged EA`). |

In addition, the **`merge_ea2026`** (`<geocode>_merged_ea2026`) output layer includes the following 3 additional fields:

| Field Name | Type | Description |
|------------|------|-------------|
| **indicator** | String | Verification status indicator (e.g. `0` = Not Verified, `1` = Verified, Accessible, `2` = Verified, Not Accessible). |
| **gps** | String | Distance metric to GNSS/GPS position coordinates evaluated against minimum bounding circle. |
| **min_circle** | String | Minimum bounding circle radius calculated from geometry for QField verification checks. |

---

## Tab 3 — Enumeration Area Merge

The **Enumeration Area Merge** tab updates an existing previous EA layer using one or more replacement polygon layers containing replacement EA geometries.

Replacement polygons take precedence over the previous EA layer: any overlapping portions of the existing EA layer underneath the replacement geometries are removed, and the replacement geometries are inserted to produce a consolidated `<5-digit geocode>_ea2026` output layer and an exact Excel attribute table export (`<5-digit geocode>_earf_<citymun>.xlsx`).

### Parameters & Inputs

| Parameter | Type | Description |
|-----------|------|-------------|
| **Previous EA Layer** | Vector (Polygon) | Previous EA polygon layer (e.g. `<geocode>_ea`, `<geocode>_ea2024`, `<geocode>_ea2026_preprocessed`). Attributes and fields are preserved. Required. |
| **Replacement Polygon Layers — Multi Input** | Vector (Polygon, Multi) | One or more vector polygon layers selected from the project. Every layer name must contain **exactly 8 numeric digits** (e.g. `01001000`). Required. |

### Tab 3 Validation Checklist

- **Polygon layers**: All selected replacement layers must be vector polygon geometries.
- **8-digit layer names**: Layer names must follow the `########` 8-digit numeric pattern.
- **Valid geometries**: Checks for valid, non-empty geometries and reconciles CRS differences via on-the-fly transformations.
- **Geographic code & City/Municipality**: Automatically extracts the 5-digit geocode and single City/Municipality name from the Previous EA Layer for output naming.

### Outputs

| Output | Format | Description |
|--------|--------|-------------|
| **Consolidated EA Layer** | QGIS Layer (Polygon) | `<5-digit geocode>_ea2026` memory layer added to current project containing updated geometries with original EA attributes. |
| **Consolidated Excel Table** | File (`.xlsx`) | `<5-digit geocode>_earf_<citymun>.xlsx` attribute table export with structured 4-level hierarchy (Province, Municipality, Barangay, EA) and deduplicated baseline statistics. |

### EARF Excel Workbook Format & Layout

The generated EARF workbook follows official PSA census reporting structure across 14 columns (A–N):

- **4-Level Hierarchical Aggregation**:
  - **Level 1 (Province Summary)**: Formatted with dark header fill (`#4F81BD`) and bold text.
  - **Level 2 (City/Municipality Summary)**: Formatted with medium header fill (`#D9E1F2`) and bold text.
  - **Level 3 (Barangay Summary)**: Formatted with light header fill (`#DCE6F1`) and bold text.
  - **Level 4 (EA Feature Rows)**: Individual EA feature rows with respective attributes.
- **Column Layout (14 Columns)**:
  - **Col A–D (Geographic Identification)**: `Prov`, `Mun`, `Brgy`, `EA`.
  - **Col E–F (2024 EARF Baseline)**: `Number of EAs`, `Province, City, Municipality, Barangay, and EA`.
  - **Col G–H (2024 Estimated Counts)**: `Number of Households`, `Number of Buildings`.
  - **Col I–N (2026 Preliminary EA)**: `New Enumeration Area Code`, `Household Count`, `Building Count`, `EA Type`, `Source Year`, `Remarks`.
- **Baseline Deduplication**: For delineated child parts belonging to the same parent EA, 2024 baseline statistics are displayed exclusively on the first child row, leaving subsequent child rows blank in Columns E, G, and H to prevent inflated summary calculations while keeping parent EA references in Column D.

## How It Works

1. **Pre-Processing Alignment (Tab 1)**:
   - Validates geometries and clips EAs extending outside parent Barangay boundaries.
   - Identifies uncovered gaps within parent Barangays and dissolves gap polygons into adjacent EAs sharing the longest boundary edge (`buffer(0.0, 3)` cleanups).

2. **Building Point Spatial Join & Aggregation (Tab 2)**:
   - Spatially joins building points to starting EAs and sums building counts (`bldgcount`) and household load (`hhcount`).

3. **Single-Pass EA Delineation (Splitting)**:
   - Overpopulated EAs (>300 HH) are split using weighted K-Means clustering and principal component point alignment verification on building points.
   - For clustered points in small areas, point alignment analysis calculates covariance matrices and aligns cut planes perpendicular to the principal cluster axis.
   - Generated cut lines are buffered and snapped to nearest road or river centrelines within snapping tolerance.
   - Strict threshold bounds check ensures that no resulting sub-polygon falls below `min_household` (100 HH) or increases above `max_household` (300 HH).

4. **Iterative Spatial Merging & Compliance Sweep**:
   - Underpopulated EAs (<=100 HH) undergo spatial adjacency merging strictly within the same parent Barangay.
   - Phase 7 global compliance sweep iterates over all post-delineation and post-merge EAs to enforce threshold bounds (`min_household <= hh_count <= max_household`).

5. **Enumeration Area Merge (Tab 3)**:
   - Takes previous EA layer and multiple 8-digit replacement polygon layers.
   - Reconciles coordinate reference systems across projected and geographic (EPSG:4326) layers, ensuring unreplaced EAs are properly retained.
   - Performs geometric difference on existing EAs against combined replacement polygons.
   - Inserts replacement geometries and builds `<5-digit geocode>_ea2026` layer.
   - Dynamically exports attribute table to `<5-digit geocode>_earf_<citymun>.xlsx` with the 4-level hierarchy and styling.

## Supported Geometry Types

- **Polygon** and **MultiPolygon**
- **Point** (Building points)
- **LineString** (Roads and rivers)

::: tip Complete Module Workflow
In the **EA Delineation and Merging** launcher dialog:
1. Run **Tab 1: EA Preprocessing** to create the `<pppmm>_ea2026_preprocessed` layer.
2. Switch to **Tab 2: Create Enumeration Areas** to balance household counts and delineate/merge zones.
3. Switch to **Tab 3: Enumeration Area Merge** to apply specific 8-digit replacement polygon layers and export the consolidated Excel attribute table (`.xlsx`).
:::
