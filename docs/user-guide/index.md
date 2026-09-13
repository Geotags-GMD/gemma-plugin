---
layout: home

hero:
  name: "GEMMA"
  text: "GIS Extension for Map Management & Analysis"
  tagline: Standardized & harmonized GIS tools and processing pipeline for GMD activities
  image:
    src: /icons/gemma.svg
    alt: GEMMA Logo
  actions:
    - theme: brand
      text: Get Started
      link: /getting-started
    - theme: alt
      text: Download
      link: https://github.com/GMD-Repository/gemma-plugin/releases/download/v1.0.4/gemma-plugin-v1.0.4.zip

features:
  - icon:
      src: /icons/overlap.svg
    title: MBI Checker
    details: Detect overlaps and gaps between barangay polygon boundaries with building point validation and reference disputed case exclusion.
    link: /tools/mbi-checker
  - icon:
      src: /icons/mbi_validator.svg
    title: MBI Validator
    details: Cross-check Reference MBI layers against Checker GAP/OVERLAP layers to flag status mismatches and audit boundary resolutions.
    link: /tools/mbi-validator
  - icon:
      src: /icons/run_analysis.svg
    title: Run Analysis
    details: Perform boundary discrepancy detection across polygon layers and building points, consolidating findings into reference MBI case layers.
    link: /tools/run-analysis
  - icon:
      src: /icons/fill.svg
    title: Fill Polygon Gaps
    details: Automatically fill gaps between polygons by assigning them to the correct neighboring barangay with a preview-before-apply workflow.
    link: /tools/fill-polygon-gaps
  - icon:
      src: /icons/export.svg
    title: Export Preliminary Polygons
    details: Merge and export resolved barangay boundary layers into a consolidated preliminary output for 1Map submission.
    link: /tools/export-preliminary-polygons
  - icon:
      src: /icons/update.svg
    title: Update Metadata
    details: Standardize LGU polygon layers with PSGC geocodes, cascading administrative filters, and permanent GeoPackage export.
    link: /tools/update-metadata
  - icon:
      src: /icons/update.svg
    title: Update Metadata (by Geocode)
    details: Perform a direct PSGC left-join on LGU boundary layers using geocodes, auto-populating standard 15-attribute schemas and exporting GeoPackages.
    link: /tools/update-metadata-by-geocode
  - icon:
      src: /icons/crs.svg
    title: Fix LGU CRS
    details: Batch-correct or reposition vector layers digitized in local arbitrary grid coordinates (~0 to ~100,000) to standard WGS 84 (EPSG:4326) using 2D Affine OLS transformation.
    link: /tools/fix-lgu-crs
  - icon:
      src: /icons/upload.svg
    title: Join Barangay Attributes
    details: Perform enhanced attribute joins between LGU vector layers and PSGC reference tables using fuzzy matching and Roman numeral normalization.
    link: /tools/join-barangay-attributes
  - icon:
      src: /icons/repair_geom.svg
    title: Geometry Repair Toolkit
    details: Validate and repair polygon geometries — detect duplicates, null geometries, invalid shapes, and wrong-type features with auto-fix capabilities.
    link: /tools/geometry-repair-toolkit
  - icon:
      src: /icons/scan_errors.svg
    title: Scan Geometry Errors
    details: Scan vector polygon layers for specific geometry and topology defects and generate a Point Vector Sink with audit metadata.
    link: /tools/scan-geometry-errors
  - icon:
      src: /icons/repair_geom.svg
    title: Repair Polygon Geometries
    details: Reconstruct invalid polygon geometries and recover missing shapes into a clean vector output layer with selection support.
    link: /tools/repair-polygon-geometries
  - icon:
      src: /icons/check_and_update.svg
    title: Check and Update
    details: Interactive 3-Phase dialog workflow for georeferencing, targeted geometry error scanning/repair, and metadata updating.
    link: /tools/check-and-update
  - icon:
      src: /icons/compare_boundaries.svg
    title: PSA - LGU Boundary Comparison
    details: Audit PSA reference boundaries against LGU-submitted polygons using geocodes, global alignment models, and building point validation.
    link: /tools/psa-lgu-comparison
  - icon:
      src: /icons/projection_finder.svg
    title: Know Your Projection!
    details: Diagnose unknown coordinate systems, auto-detect Philippine CRS candidates, and georeference local CAD grids via 2D affine transformations.
    link: /tools/know-your-projection
  - icon:
      src: /icons/packager.svg
    title: Package for QField
    details: Package your QGIS project for field data collection using QField with drag-and-drop layer management.
    link: /tools/package-qfield
  - icon:
      src: /icons/create_ea.svg
    title: EA Delineation and Merging
    details: Integrated module for pre-processing, gap filling, delineation (splitting), and merging of enumeration area boundaries.
    link: /tools/ea-delineation-and-merging
  - icon:
      src: /icons/clip_layers.svg
    title: Clip Project Layers by Extent
    details: Batch clip multiple vector layers to administrative boundary polygons with optional buffer margins.
    link: /tools/clip-project-layers
  - icon:
      src: /icons/package_style_loader.svg
    title: Package Style Loader
    details: Interactive dialog to organize layer hierarchies, assign functional roles, and apply QML symbology and labeling.
    link: /tools/package-style-loader
  - icon:
      src: /icons/package_layers.svg
    title: Package Layers by City/Mun
    details: Split reference boundary layers and building points into clean, self-contained GeoPackage deliverables per city or municipality.
    link: /tools/package-layers-by-citymun
---

