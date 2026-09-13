# <img src="/icons/projection_finder.svg" width="32" height="32" style="vertical-align: middle; display: inline-block; margin-right: 8px;" /> Know Your Projection!

The **Know Your Projection!** tool provides a comprehensive coordinate diagnostics, automated Philippine Coordinate Reference System (CRS) candidate detection, and 2D affine georeferencing environment for vector datasets with missing, misidentified, or arbitrary local coordinate systems.

## Access

- **Menu:** Gemma → Updating of Boundaries → Know Your Projection!
- **Processing Toolbox:** GMD Pipeline → 1Map → Know Your Projection!
- **Algorithm ID:** `gmd_pipeline:projection_finder`

When executed inside QGIS Desktop, the algorithm opens the interactive Know Your Projection! toolkit dialog. When run headlessly (e.g. via `qgis_process`), it performs a non-interactive coordinate diagnostic audit on the input vector layer and logs extent metrics and candidate CRS matches.

## When to Use

Use this tool when:
- Vector shapefiles or GeoPackages have missing `.prj` definition files, invalid CRS tags, or unassigned projections.
- Boundary layers digitized in local CAD units (~0 to ~100,000) or legacy millimeter coordinates need to be georeferenced to standard Philippine CRS grids.
- Layer boundaries fail to overlay correctly onto satellite basemaps due to datum offsets between WGS 84, PRS92, and Luzon 1911.
- You need to audit coordinate bounding boxes and classify CRS regimes across municipal vector datasets prior to boundary harmonization.

## Parameters

### Inputs

| Parameter | Type | Description |
|-----------|------|-------------|
| **Input vector layer to diagnose (optional)** | Feature Source (Any Geometry) | Optional vector layer to audit or diagnose. If omitted in Desktop mode, the interactive tool opens for workspace layer selection. |

### Outputs

| Output | Type | Description |
|--------|------|-------------|
| **Diagnostic summary** | String | Detailed coordinate classification, extent metrics, and candidate CRS matches logged during processing. |

## How It Works

1. **Coordinate Extent Diagnosis**:
   - Classifies bounding box magnitudes and spans into four distinct coordinate regimes:
     - **Geographic Coordinates (Degrees):** Coordinates within $[-180^\circ, 180^\circ]$ longitude and $[-90^\circ, 90^\circ]$ latitude. Suggests EPSG:4326 (WGS 84), EPSG:4683 (PRS92), or EPSG:4253 (Luzon 1911).
     - **Projected Grid (Metres):** Coordinates within $[100,000, 1,000,000]$ Easting and $[300,000, 2,700,000]$ Northing, matching Philippine Transverse Mercator (PTM) or Universal Transverse Mercator (UTM) zones.
     - **Web Mercator (EPSG:3857):** Coordinates within $[12,000,000, 14,500,000]$ Easting.
     - **Local / Arbitrary Grid:** Non-georeferenced coordinates digitized from CAD drawings, millimeter tablet digitizers, or uncalibrated local surveys.

2. **Automated Philippine CRS Candidate Scanning**:
   - Tests layer extents across 23 national and regional coordinate definitions:
     - **WGS 84:** Geographic (EPSG:4326), UTM Zone 51N (EPSG:32651), UTM Zone 50N (EPSG:32650), UTM Zone 52N (EPSG:32652), Web Mercator (EPSG:3857).
     - **PRS92:** Geographic (EPSG:4683), PTM Zones 1–5 (EPSG:3121–3125), and UTM Zones 50N–52N (ESRI:102456–102458).
     - **Luzon 1911:** Geographic (EPSG:4253), PTM Zones I–V (EPSG:25391–25395), and UTM Zones 50N–52N (ESRI:102453–102455).
   - Identifies candidate systems that place the layer boundaries fully within the Philippine terrestrial extent ($116.0^\circ\text{E} - 127.5^\circ\text{E}$, $4.0^\circ\text{N} - 21.5^\circ\text{N}$).

3. **2D 6-Parameter Affine Georeferencing**:
   - When layers exist in arbitrary CAD coordinates, the tool calculates a 2D affine transformation matrix via Ordinary Least Squares (OLS) between digitized local coordinate pairs $(x, y)$ and verified reference control point coordinates $(X, Y)$:
     $$\begin{aligned} X &= a \cdot x + b \cdot y + c \\ Y &= d \cdot x + e \cdot y + f \end{aligned}$$
   - Solves for translation $(c, f)$, independent $X$ and $Y$ scale factors, rotation angles, and shear anisotropy to absorb non-uniform digitizing distortion.
   - Evaluates root-mean-square (RMS) residuals in metres across all control points to verify positional accuracy before applying changes.

4. **Visual Basemap Inspection**:
   - Automatically loads Google Satellite or Google Hybrid XYZ tile basemaps at the base of the layer tree.
   - Enables immediate visual verification of boundary alignment against real-world road networks, coastlines, and physical topography.

5. **Direct Layer Reprojection & Export**:
   - Allows users to reassign the confirmed CRS to the active layer or export georeferenced features into a standardized new GeoPackage in the target CRS (e.g. WGS 84 / UTM Zone 51N).

## Supported Coordinate Systems Matrix

| CRS Identifier | Name / Grid System | Typical Area of Use |
|----------------|-------------------|---------------------|
| **EPSG:4326** | WGS 84 (Geographic) | Global GPS default, web portals, interchange |
| **EPSG:4683** | PRS92 (Geographic) | National standard Philippine geographic datum |
| **EPSG:4253** | Luzon 1911 (Geographic) | Historical Philippine geographic datum |
| **EPSG:32651** | WGS 84 / UTM Zone 51N | Nationwide projected default in metres (Central Philippines) |
| **EPSG:32650** | WGS 84 / UTM Zone 50N | Western Philippines (Palawan, Kalayaan) |
| **EPSG:32652** | WGS 84 / UTM Zone 52N | Eastern Philippines (Eastern Mindanao, Siargao) |
| **ESRI:102457** | PRS92 / UTM Zone 51N | National PRS92 projected coverage on UTM grid |
| **ESRI:102456** | PRS92 / UTM Zone 50N | Western PRS92 UTM coverage |
| **ESRI:102458** | PRS92 / UTM Zone 52N | Eastern PRS92 UTM coverage |
| **ESRI:102454** | Luzon 1911 / UTM Zone 51N | Historical cadastral datasets on UTM grid |
| **ESRI:102453** | Luzon 1911 / UTM Zone 50N | Historical Palawan cadastral datasets |
| **ESRI:102455** | Luzon 1911 / UTM Zone 52N | Historical Eastern Mindanao cadastral datasets |
| **EPSG:3121 – 3125** | PRS92 / Philippines Zones 1 – 5 | Official national PTM municipal survey grids |
| **EPSG:25391 – 25395** | Luzon 1911 / Philippines Zones I – V | Historical cadastral and NAMRIA topographic maps |
| **EPSG:3857** | WGS 84 / Pseudo-Mercator | Web tiling, OpenStreetMap, and Google basemaps |

## Supported Geometry Types

- **Point** and **MultiPoint**
- **LineString** and **MultiLineString**
- **Polygon** and **MultiPolygon**

::: tip Recommended Production Projection
For municipal boundary updating and spatial analysis, **EPSG:32651** (WGS 84 / UTM Zone 51N) or the appropriate local PTM zone (EPSG:3121–3125) is recommended. Metric planar coordinates allow accurate area calculations, buffer generation, and geometric topology operations without ellipsoidal distortion.
:::

::: info Headless Diagnostics
When run headlessly without a GUI (such as via Python scripts or `qgis_process run gmd_pipeline:projection_finder`), the tool performs automated bounding box diagnosis and logs candidate systems directly to the processing console without opening the interactive dialog.
:::
