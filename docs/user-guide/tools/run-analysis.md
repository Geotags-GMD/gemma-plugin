# <img src="/icons/run_analysis.svg" width="32" height="32" style="vertical-align: middle; display: inline-block; margin-right: 8px;" /> Run Analysis

The **Run Analysis** tool performs comprehensive boundary topology and discrepancy detection across LGU polygon layers and building points, consolidating all findings into a unified Reference MBI layer named `ref_mbi_cases`. It identifies boundary gaps, overlaps, and disputed territories, assigning standardized administrative metadata, geocodes, and attribute editor widgets.

## Access

- **Processing Toolbox:** GMD Pipeline → 1Map → Run Analysis
- **Algorithm ID:** `gmd_pipeline:run_analysis`

## When to Use

Use this tool when:
- Establishing the baseline Reference MBI cases layer (`ref_mbi_cases`) for a municipality or province.
- Generating the required reference input layer consumed by the [MBI Validator](/tools/mbi-validator) tool.
- Detecting sliver gaps between adjacent barangay polygons while automatically excluding already-recorded disputed territories.
- Identifying boundary overlaps across different administrative levels (Inter-Region, Inter-Province, Inter-City/Municipality, Inter-Barangay, or Within-Barangay).
- Extracting contested boundary claims tagged as disputed in LGU datasets.
- Setting up pre-configured attribute table dropdown widgets (`ValueMap` for `mbi_status`) for provincial field validation.

## Parameters

### Inputs

| Parameter | Type | Description |
|-----------|------|-------------|
| **Select Polygon Layer(s)** | Multiple Layers (Polygon) | One or more vector polygon layers representing barangay boundaries from LGU and PSA datasets. Required. |
| **Select Building Point Layer(s)** | Multiple Layers (Point) | One or more point layers representing structures/buildings used to count intersecting points within each finding. Required. |

::: info Fixed Analysis Execution
All three boundary analyses (**Gaps**, **Overlaps**, and **Disputed Areas**) execute automatically as mandatory procedures. No manual analysis mode parameter is required.
:::

### Outputs

| Output | Type | Description |
|--------|------|-------------|
| **ref_mbi_cases** | Feature Sink (Polygon) | A consolidated polygon layer in EPSG:4326 containing all detected boundary findings categorized by `mbi_type`. Formatted with pre-configured attribute table editor widgets. |

## Output Layer Schema

The resulting `ref_mbi_cases` layer contains the following standardized attributes:

| Field Name | Type | Access | Description |
|------------|------|--------|-------------|
| **case_uuid** | String | Read-Only | Unique UUID string assigned to each individual finding. |
| **geocode** | String | Editable | 9-digit PSGC geocode associated with the primary reference polygon. |
| **region** | String | Read-Only | Region name or code. |
| **province** | String | Read-Only | Province name. |
| **city_mun** | String | Editable | City or municipality name. |
| **barangay** | String | Editable | Barangay name. |
| **source** | String | Read-Only | Data source provenance label (e.g. LGU or PSA; NULL for gaps). |
| **mbi_level** | String | Read-Only | Administrative boundary hierarchy level: *Inter-Region*, *Inter-Province*, *Inter-City/Municipality*, *Inter-Barangay*, or *Within-Barangay*. |
| **involved_areas** | String | Read-Only | Comma-separated list of all involved PSGC geocodes. |
| **involved_bgys** | String | Read-Only | Semicolon-separated list of all involved barangay and city/municipality names. |
| **count_involved_areas** | Integer | Read-Only | Total count of distinct administrative units participating in the finding. |
| **mbi_type** | String | Read-Only | Classification category: `1_Gap`, `2_Overlap`, or `3_Disputed`. |
| **num_bldg_pts** | Integer | Read-Only | Count of intersecting building points falling within the finding polygon. |
| **mbi_status** | String | Editable | Status field equipped with a QGIS ValueMap dropdown widget: `1_Updated` or `2_Pending`. |
| **mbi_remarks** | String | Read-Only | System remarks populated automatically when an overlap touches a disputed polygon (`For Review - Involves Disputed Area`). |
| **pso_remarks** | String | Editable | Text field reserved for notes entered by Provincial Statistical Offices. |
| **lgu_bgy_name** | String | Editable | LGU-declared barangay name populated specifically for Disputed records (NULL for gaps/overlaps). |

## How It Works

1. **Layer Pre-Processing and Coordinate Normalization**:
   - Multiple input polygon and building point layers are refactored, merged, and projected to Web Mercator (`EPSG:3857`) for accurate metric area calculations and geometric topological operations.
   - Geometries are validated and repaired using geometry fixing algorithms, and multipart geometries are exploded into single parts.

2. **Spatial Indexing & Attribute Extraction**:
   - Spatial bounding box indexes (`QgsSpatialIndex`) and cached feature lookups are constructed for both polygon boundaries and building points.
   - Core administrative attributes (`geocode`, `region`, `province`, `city_mun`, `barangay`, `boundary`, `source`) are normalized into structured lookup records.

3. **Disputed Territory Identification**:
   - Polygons tagged with `boundary = Contested` or disputed markers are isolated.
   - Each contested area is converted to `3_Disputed` in the output schema and its footprint is unioned in memory.

4. **Overlap Detection Engine**:
   - Pairs of intersecting polygons are detected using the spatial index.
   - The geometric intersection is computed, filtered to retain polygons with areas greater than 0.10 square meters, and tagged with administrative level hierarchy (`mbi_level`).
   - If either overlapping polygon is marked as disputed, `mbi_remarks` is automatically populated with `For Review - Involves Disputed Area`.
   - Intersecting building points within the overlap polygon are tallied into `num_bldg_pts`.

5. **Gap Detection Engine**:
   - Non-disputed boundary polygons are dissolved into a unified regional coverage.
   - Holes within the dissolved polygon coverage are filled, and a symmetric difference is computed between the filled coverage and the original dissolved coverage to extract internal void slivers.
   - The unioned footprint of all Disputed territories is subtracted from the candidate gap geometries, ensuring that contested territories are never duplicated as gaps.
   - Qualifying gap slivers are linked to adjacent participating barangays and assigned `mbi_type` = `1_Gap`.

6. **Output Layer Generation, Styling & Editor Widget Application**:
   - All findings are transformed to WGS 84 (`EPSG:4326`) and added to the consolidated `ref_mbi_cases` layer.
   - The layer post-processor (`FieldWidgetPostProcessor`) automatically loads and applies the embedded categorized QML style (`ref_mbi_cases.qml`), displaying distinct symbology and labeling for `1_Gap`, `2_Overlap`, and `3_Disputed` cases.
   - Attaches `ValueMap` editor widgets to `mbi_status` (`1_Updated`, `2_Pending`) and text input setups to remarks fields directly upon loading into QGIS.
   - Sets computed reference attributes to **Read-Only** (`case_uuid`, `region`, `province`, `source`, `mbi_level`, `involved_areas`, `involved_bgys`, `count_involved_areas`, `mbi_type`, `num_bldg_pts`, and `mbi_remarks`) to prevent accidental edits while keeping reviewer fields (`geocode`, `city_mun`, `barangay`, `mbi_status`, `pso_remarks`, and `lgu_bgy_name`) fully **Editable**.

## Supported Geometry Types

- **Polygon** and **MultiPolygon** (Vector boundary layers)
- **Point** and **MultiPoint** (Building point layers)

::: tip Reference Layer Downstream Compatibility
The output layer `ref_mbi_cases` is engineered to feed directly into the **MBI Validator** tool. When opening MBI Validator, it will automatically detect and pre-select `ref_mbi_cases` as the Reference layer input.
:::
