# <img src="/icons/overlap.svg" width="32" height="32" style="vertical-align: middle; display: inline-block; margin-right: 8px;" /> MBI Checker

The **MBI Checker** (Map Boundary Issues Checker) is the core quality assurance processing algorithm for detecting **gaps** and **overlaps** in barangay polygon boundaries. It cross-references boundary polygons against building point layers to compute structure counts within conflict zones and subtracts previously registered disputed cases from reference MBI layers to prevent false gap detection.

## Access

- **Processing Toolbox:** GMD Pipeline → 1Map → MBI Checker
- **Algorithm ID:** `gmd_pipeline:mbi_checker_for_GEOTAGS` (also accessible as `gmd_pipeline:gaps_overlaps_checker`)

## When to Use

Use this tool when you need to:
- Verify that adjacent barangay boundary polygons have zero overlapping territory.
- Check for uncovered gaps or sliver polygons along shared barangay administrative borders.
- Exclude previously filed disputed areas from gap detection using a reference MBI cases layer.
- Count the number of building points located within each boundary issue to assess population impact.
- Classify boundary conflict severity across administrative hierarchy levels (Inter-Region, Inter-Province, Inter-City/Municipality, Inter-Barangay, or Within-Barangay).
- Generate clean in-memory report layers (`Overlaps` and `Gaps`) for downstream processing with [Fill Polygon Gaps](/tools/fill-polygon-gaps), [Export Preliminary Polygons](/tools/export-preliminary-polygons), and [MBI Validator](/tools/mbi-validator).

## Parameters

### Inputs

| Parameter | Type | Description |
|-----------|------|-------------|
| **Select Polygon Layer(s)** (`INPUT1`) | Multiple Vector Layers (Polygon) | One or more barangay boundary polygon layers (e.g. LGU-submitted and PSA reference boundaries) to validate. Required. |
| **Select Building Point Layer(s)** (`INPUT2`) | Multiple Vector Layers (Point) | One or more building point layers used to calculate building structure counts (`num_bldg_pts`) falling within issue geometries. Required. |
| **Reference MBI Cases Layer (ref_mbi_cases)** (`REF_MBI_CASES`) | Multiple Vector Layers (Polygon) | One or more polygon layers containing previously identified MBI cases. Features whose `mbi_type` contains **Disputed** (e.g. `3_Disputed`) are unioned and subtracted from the gap layer so existing disputes are not re-reported as gaps. Required. |
| **Analysis to Run** (`RUN_MODE`) | Enum (Dropdown) | Select the processing mode: `Gaps and Overlaps` (default), `Overlaps Only`, or `Gaps Only`. |

### Outputs

| Output | Type | Description |
|--------|------|-------------|
| **Overlaps** (`OVERLAPS`) | Vector Layer (Polygon, In-Memory) | Output polygon layer containing areas where two or more barangay polygons overlap. Generated in `Gaps and Overlaps` and `Overlaps Only` modes. |
| **Gaps** (`GAPS`) | Vector Layer (Polygon, In-Memory) | Output polygon layer containing uncovered boundary slivers and coverage gaps between polygons, with disputed reference cases subtracted. Generated in `Gaps and Overlaps` and `Gaps Only` modes. |

## Output Attribute Schema

Both output layers share a standardized schema designed for administrative reporting and downstream validation:

| Field | Type | Description |
|-------|------|-------------|
| **case_uuid** | String | Unique identifier (UUIDv4) generated for each detected boundary issue. |
| **geocode** | String | PSGC geocode of the primary/reference barangay polygon. |
| **region** | String | Administrative region name. |
| **province** | String | Province name. |
| **city_mun** | String | City or Municipality name. |
| **barangay** | String | Barangay name. |
| **source** | String | Source tag of the primary polygon (`LGU` or `PSA`; `NULL` for gaps). |
| **mbi_level** | String | Administrative conflict hierarchy level: `1_Inter-Region`, `2_Inter-Province`, `3_Inter-City/Municipality`, `4_Inter-Barangay`, or `5_Within-Barangay`. |
| **involved_areas** | String | Comma-separated list of PSGC geocodes for all barangays involved in the issue. |
| **involved_bgys** | String | Semicolon-separated list of barangay and city/municipality names involved in the issue. |
| **count_involved_areas** | Integer | Total number of distinct barangay administrative units participating in the issue. |
| **mbi_type** | String | Issue classification: `1_Gap` for gaps or `2_Overlap` for overlaps. |
| **num_bldg_pts** | Integer | Count of building points contained within or intersecting the finding geometry. |

## Analysis Modes

### Gaps and Overlaps (Default)
Runs both overlap detection and gap detection in a single pass. Disputed boundaries and reference MBI disputed cases are excluded from the gap dissolve and differenced from the gap geometry.

### Overlaps Only
Scans all polygon pairs for intersecting territory. Useful when boundary gaps have already been resolved or when focusing exclusively on overlapping polygon claims.

### Gaps Only
Analyzes boundary coverage completeness to detect uncovered voids between polygons, taking into account reference disputed cases. Useful when overlaps have already been cleared.

## Reference MBI Cases and Disputed Area Handling

In administrative boundary harmonization, areas between adjacent local government units may represent formal, legally recognized boundary disputes rather than unintentional digitization coverage gaps.

1. **Disputed Case Extraction**:
   - The algorithm scans the layer(s) supplied in **Reference MBI Cases Layer (ref_mbi_cases)**.
   - Features whose `mbi_type` attribute contains `disputed` (case-insensitive, e.g. `3_Disputed`) are extracted.
   - Any polygon from the input boundary layers whose `boundary` attribute is marked as `Contested` is also extracted.

2. **Geometric Difference Subtraction**:
   - All qualifying disputed geometries are projected to Web Mercator (`EPSG:3857`) and combined into a single geometric union:
     $$\text{Disputed}_{\text{union}} = \bigcup_{i} \text{DisputedFeature}_i$$
   - During gap detection, this union is subtracted from the uncovered polygon voids:
     $$\text{Gap}_{\text{final}} = \text{Gap}_{\text{uncovered}} \setminus \text{Disputed}_{\text{union}}$$
   - Any area already filed as a disputed boundary case is thereby eliminated from the gap results, ensuring it is not reported again as a gap.

::: tip
The reference MBI cases layer must carry an `mbi_type` attribute field for disputed cases to be identified. If a selected layer lacks this field, the algorithm outputs a warning in the execution log and continues processing without disputed-case exclusion for that layer.
:::

## How It Works

1. **Input Preprocessing and Normalization**:
   - Selected polygon layers and building point layers are refactored to harmonize schemas, merged into unified datasets, and reprojected to planar metric coordinates (`EPSG:3857`).
   - Geometries are validated and repaired using `native:fixgeometries` and converted to singlepart polygons (`native:multiparttosingleparts`).

2. **Spatial Index Construction**:
   - R-tree spatial indexes (`QgsSpatialIndex`) are created for polygons and building points to enable high-speed bounding-box collision detection.
   - Input polygons are partitioned into non-disputed and contested subsets based on the `boundary` attribute.

3. **Overlap Processing**:
   - For every candidate polygon pair whose bounding boxes intersect, the exact geometric intersection is calculated:
     $$\text{Overlap}_{\text{geom}} = \text{Geom}_A \cap \text{Geom}_B$$
   - Intersection geometries are split into singlepart components, and slivers with area $\le 0.10\text{ m}^2$ are pruned.
   - Participating barangays are identified, administrative hierarchy levels (`mbi_level`) are evaluated, intersecting building points are tallied, a unique `case_uuid` is generated, and features are marked as `2_Overlap`.

4. **Gap Processing**:
   - Non-disputed boundary polygons are dissolved into a single unified coverage polygon (`native:dissolve`).
   - Interior voids and doughnut holes are deleted (`native:deleteholes`), creating a bounding envelope.
   - The difference between the envelope and the dissolved polygons yields raw internal gap slivers:
     $$\text{Gap}_{\text{raw}} = \text{Envelope} \setminus \text{Dissolved}$$
   - Raw gaps are exploded to singleparts, cleaned, and differenced against the `Disputed` geometric union.
   - Gaps with area $> 0.10\text{ m}^2$ are buffered by $0.50\text{ m}$ to identify adjacent barangays and count intersecting building points, and are assigned `mbi_type = 1_Gap`.

5. **Coordinate Reprojection and Map Layer Loading**:
   - Output geometries are reprojected from `EPSG:3857` back to standard geographic coordinates (`EPSG:4326`).
   - The generated `Overlaps` and `Gaps` layers are loaded directly into the active QGIS project memory layer store for immediate visualization and subsequent workflows.

## Supported Geometry Types

- **Polygon** and **MultiPolygon** (for Barangay Polygon Layers and Reference MBI Cases)
- **Point** and **MultiPoint** (for Building Point Layers)

## Best Practices

1. **Load All Reference Layers First**: Ensure all relevant barangay polygon layers, building point layers, and baseline reference MBI cases (`ref_mbi_cases`) are loaded in your QGIS project before opening the algorithm dialog.
2. **Ensure `mbi_type` Exists in Reference Cases**: Verify that your reference MBI case layer includes the `mbi_type` column (with values such as `3_Disputed`) so that previously recorded disputes are properly recognized and excluded from gap results.
3. **Resolve Overlaps Before Gaps**: When fixing boundary defects, resolve overlapping areas first. Adjusting polygon edges to eliminate overlaps frequently changes shared boundary lines and can automatically resolve adjacent gaps.
4. **Integration with Downstream Tools**:
   - Use [Fill Polygon Gaps](/tools/fill-polygon-gaps) to preview and merge resolved gap slivers into neighboring barangay polygons.
   - Use [Export Preliminary Polygons](/tools/export-preliminary-polygons) to consolidate clean, topology-verified boundary layers into submission GeoPackages.
   - Run [MBI Validator](/tools/mbi-validator) to cross-audit updated boundaries against baseline reference MBI datasets and confirm resolved statuses.
