# <img src="/icons/repair_geom.svg" width="32" height="32" style="vertical-align: middle; display: inline-block; margin-right: 8px;" /> Geometry Repair Toolkit

The **Geometry Repair Toolkit** is a standalone dialog-based tool for validating, inspecting, and repairing polygon geometries. It provides a comprehensive interface for detecting and fixing common topology and geometry issues across polygon layers directly within QGIS.

## Access

- **Menu:** Gemma → Others → Geometry Repair Toolkit
- **Component Algorithm IDs:** `gmd_pipeline:scangeometryerrors`, `gmd_pipeline:repairpolygongeometries`
- This tool opens as a **separate dialog window** (not through the Processing Toolbox).

## When to Use

Use this tool when:

- You suspect polygon layers contain invalid, self-intersecting, or corrupted geometries.
- QGIS reports geometry errors during processing or spatial operations.
- You need to clean up and validate polygon layers before running other GMD tools (such as MBI Checker or Fill Polygon Gaps).
- You want to identify and fix duplicate vertices, null geometries, empty shapes, wrong geometry types, ring/structure errors, or duplicate features.

## Features & Tab Structure

The toolkit features a tabbed interface:
1. **Geometry Fixer (Tab 1)** — Scan layers, inspect detected issues in an interactive table, highlight error geometries on the map canvas, and run automated repairs.
2. **Help and Information (Tab 2)** — View reference tables for error types, repair mechanisms, layer edit behavior, and limitations.

## Error Types Reference

The toolkit scans polygon layers for the following topology and geometry issues:

| Error Type | Description | Repair Mechanism |
|------------|-------------|------------------|
| **Null Geometry** | The feature record exists, but there is no geometry object. | Auto-fixable (Recovery from surrounding polygons) |
| **Empty/Missing Geometry** | The feature exists, but its geometry has no usable shape or coordinates. | Auto-fixable (Recovery from surrounding polygons) |
| **Invalid Geometry** | The polygon has geometry errors such as ring errors, spikes, or folded edges. | Auto-fixable (Polygon reconstruction) |
| **Self Intersection** | The polygon boundary crosses itself (e.g. bowtie rings). | Auto-fixable (Polygon reconstruction) |
| **Invalid Geometry + Self Intersection** | Combined report when a feature exhibits both general invalidity and self-intersection. | Auto-fixable (Polygon reconstruction) |
| **Duplicate Vertex** | The ring contains a duplicate or near-duplicate vertex (or a zero-length segment). Reported only when QGIS's validator specifically detects duplicate nodes (e.g. accidental self-snaps during manual digitization). | Auto-fixable (Direct duplicate vertex removal via progressive tolerance sweep) |
| **Wrong-type Geometry** | The feature's geometry type does not match the layer's declared geometry type (e.g. a line or GeometryCollection stored in a polygon layer). | Auto-fixable (Polygon reconstruction) |
| **Ring/Structure Error** | GEOS accepts the geometry, but QGIS's internal validator objects to how rings or parts are arranged (e.g. interior hole ring not fully inside outer ring, or a part nested inside another part). | Requires manual review (No automatic repair; correct rings using the Vertex Tool) |
| **Duplicate Geometry** | Two or more features share the exact same geometry. | Requires manual review / deduplication |
| **Dangle (Loose End)** | A line endpoint doesn't connect to any other line. | Requires manual review |

## How to Use

1. Open the tool from **Gemma → Others → Geometry Repair Toolkit**.
2. Under **Input Layers**, select one or more polygon layers to check.
3. Click **Scan Layers** to initiate the background geometry scan.
4. Review the detected errors in the results table:
   - **White rows**: Auto-fixable issues with selectable checkboxes.
   - **Grey rows**: Issues requiring manual review (e.g. Ring/Structure Error, Duplicate Geometry, Dangles). Their checkboxes are disabled because they cannot be resolved automatically.
5. Double-click any row to zoom to the affected feature on the map. The toolkit places rubber-band outlines and vertex markers over problematic geometry locations.
6. Check the rows to repair (or click the checkbox in the first column header to select or clear all auto-fixable rows at once).
7. Click **Repair Selected Features**. The toolkit routes each checked row to its specific repair mechanism and applies changes directly in-place:
   - If checked rows have no automatic fix, a warning dialog alerts the operator and logs individual reasons.
   - Features that cannot be resolved automatically are logged with their specific diagnostic reason (such as collapsing to a line or missing geometry) and flagged for manual review with the Vertex Tool.
8. Review the summary log:
   - The execution summary reports `Finished. Fixed: <count> Needs manual repair: <count>`.
   - Repaired features are kept in active edit mode on the source layer.
9. Re-run **Scan Layers** on the layer while still in edit mode to verify all errors are resolved before saving.
10. Use QGIS's **Save Edits** to persist changes to disk, or **Cancel Edits** to discard all repairs and revert to the original state.

## Repair Mechanisms & In-Place Editing

### Repair Selected Features
When you click **Repair Selected Features**, the tool inspects each checked error row and automatically applies the appropriate repair mechanism directly to the original layer:
- **Duplicate Vertex**: Eliminates duplicate or near-duplicate vertices through a progressive tolerance sweep (scaled by bounding box diagonal from $10^{-12}$ to $10^{-6}$) verified against QGIS's internal validator, with a `makeValid()` fallback to resolve node-clustering defects without requiring full polygon reconstruction.
- **Invalid / Wrong-type / Self Intersection**: Reconstructs the polygon shape (ring decomposition, unary union planarization, face matching, and hole restoration) to resolve geometry errors and self-intersections.
- **Null / Empty / Missing Geometry**: Recovers missing shapes using spatial boundary context from surrounding polygons.

### Ring/Structure Errors & Manual Intervention
Certain topological defects cannot be resolved by automatic reconstruction or node deduplication:
- **Arrangement Defects**: When QGIS reports ring arrangement issues (such as an interior hole ring outside the exterior boundary or a polygon part nested inside another), GEOS already evaluates the underlying geometry as valid. Consequently, automated tools like `makeValid()` leave the geometry completely unchanged, and no duplicate vertex exists to delete.
- **Diagnostic Logging**: The repair engine evaluates each unfixable feature and logs a specific diagnostic explanation (e.g. `FID X could NOT be repaired automatically. Reason: it encloses no area — the outline collapses to a line...`) along with guidance to inspect and edit the feature manually using the QGIS Vertex Tool.
- **Clear Status Distinction**: Unfixable features are tracked as **Needs manual repair** in the summary log, preventing silent skips and giving operators immediate visibility into which features require manual redigitizing or cleanup.

### Multipart Resolution & Artifact Cleanup
Polygon reconstruction can occasionally leave a feature multipart even if it started as a single part (such as resolving a self-intersecting bowtie ring). When this occurs:
- Negligible fragment slivers resulting from reconstruction artifacts (< 0.1% area ratio) are automatically dropped.
- Genuine multi-part survivors sharing original feature attributes remain merged as a single multipart feature.
- Pre-existing legitimate multipart features (such as a barangay with offshore islands) that were not repaired remain completely untouched.

### In-Place Editing & Unsaved Changes Guard
- **Direct Layer Editing**: Repaired features are edited directly on the source layer in QGIS edit mode (indicated by a pencil icon and modified marker).
- **Safe Discard**: Changes remain unsaved in memory until you choose **Save Edits** or **Cancel Edits** from the QGIS Layer menu or editing toolbar.
- **Schema Preservation**: Attribute fields and schemas are preserved without adding unnecessary tracking columns. Recovery details, repair methods, and notes are logged in the execution console.

## Limitations & Review Best Practices

::: tip Recommended Workflow
Run the **Geometry Repair Toolkit** on your layers **before** using other processing tools like the MBI Checker or Fill Polygon Gaps. Invalid geometries can cause unexpected results in topological analysis.
:::

::: info In-Place Editing
The toolkit applies repairs directly to the layer in edit mode. Always use **Save Edits** to persist changes to disk or **Cancel Edits** to revert unwanted modifications.
:::

::: warning Limitations & Manual Review
- **Visual Inspection**: Always visually inspect repaired features before saving edits.
- **Re-Scan Verification**: Re-scan the layer with **Scan Layers** while still in edit mode to confirm no secondary errors remain.
- **Ring/Structure Errors**: Geometry ring placement defects (e.g. holes outside outer rings, nested parts) must be corrected manually using the QGIS Vertex Tool.
- **Zero-Area Geometries**: Features whose boundary collapses to a line enclose zero area and cannot be reconstructed into polygons; they must be redigitized or deleted manually.
- **Deleted Feature Records**: Completely deleted attribute records cannot be recovered by this tool.
- **Edge Polygons**: Edge polygons cannot be safely reconstructed when their outer boundary is unknown. If an edge polygon is missing, return it to the LGU for corrected boundary geometry.
- **CRS Sensitivity**: Validity is evaluated in the layer's native CRS. Because coordinate reprojection can shift vertices and alter geometry validity, re-run **Scan Layers** whenever a layer is reprojected.
- **Manual Review**: Complex topology issues such as Duplicate Geometry and Dangles require manual review and editing.
:::
