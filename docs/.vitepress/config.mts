import { defineConfig } from 'vitepress'

// https://vitepress.dev/reference/site-config
export default defineConfig({
  base: '/',
  srcDir: "user-guide",

  title: "GEMMA Plugin",
  description: "GIS Extension for Map Management and Analysis — A QGIS processing plugin by the Geospatial Management Division (GMD) of the Philippine Statistics Authority.",

  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/icons/gemma.svg' }],
    ['meta', { name: 'author', content: 'Geospatial Management Division — Philippine Statistics Authority' }],
    ['meta', { name: 'keywords', content: 'QGIS, GIS, plugin, GEMMA, GMD, PSA, 1Map, QField, geometry, overlaps, gaps' }],
  ],

  markdown: {
    math: true
  },

  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    logo: '/icons/gemma.svg',
    siteTitle: 'GEMMA Plugin',

    nav: [
      { text: 'Home', link: '/' },
      { text: 'Getting Started', link: '/getting-started' },
      {
        text: 'Tools',
        items: [
          {
            text: '1Map Tools',
            items: [
              { text: 'MBI Checker', link: '/tools/mbi-checker' },
              { text: 'MBI Validator', link: '/tools/mbi-validator' },
              { text: 'Run Analysis', link: '/tools/run-analysis' },
              { text: 'Fill Polygon Gaps', link: '/tools/fill-polygon-gaps' },
              { text: 'Export Preliminary Polygons', link: '/tools/export-preliminary-polygons' },
              { text: 'Update Metadata', link: '/tools/update-metadata' },
              { text: 'Update Metadata (by Geocode)', link: '/tools/update-metadata-by-geocode' },
              { text: 'Fix LGU CRS / Geometry', link: '/tools/fix-lgu-crs' },
              { text: 'Join Barangay Attributes', link: '/tools/join-barangay-attributes' },
              { text: 'Check and Update', link: '/tools/check-and-update' },
              { text: 'PSA - LGU Boundary Comparison', link: '/tools/psa-lgu-comparison' },
              { text: 'Know Your Projection!', link: '/tools/know-your-projection' },
              { text: 'Package Layers by City/Mun', link: '/tools/package-layers-by-citymun' },
              { text: 'Package Style Loader', link: '/tools/package-style-loader' },
            ]
          },
          {
            text: 'Geometry & Repair',
            items: [
              { text: 'Geometry Repair Toolkit', link: '/tools/geometry-repair-toolkit' },
              { text: 'Scan Geometry Errors', link: '/tools/scan-geometry-errors' },
              { text: 'Repair Polygon Geometries', link: '/tools/repair-polygon-geometries' },
              { text: 'Clip Project Layers by Extent', link: '/tools/clip-project-layers' },
            ]
          },
          {
            text: 'QField & Enumeration',
            items: [
              { text: 'Package for QField', link: '/tools/package-qfield' },
              { text: 'EA Delineation and Merging', link: '/tools/ea-delineation-and-merging' },
            ]
          }
        ]
      },
      {
        text: 'v1.0.4',
        items: [
          { text: 'Changelog', link: '/changelog' },
          { text: 'Download Latest', link: 'https://github.com/GMD-Repository/gemma-plugin/releases/latest' },
          { text: 'GitHub Releases', link: 'https://github.com/GMD-Repository/gemma-plugin/releases' }
        ]
      }
    ],

    sidebar: [
      {
        text: 'Introduction',
        items: [
          { text: 'Getting Started', link: '/getting-started' },
          { text: 'Changelog', link: '/changelog' },
        ]
      },
      {
        text: '1Map Tools',
        collapsed: false,
        items: [
          { text: 'MBI Checker', link: '/tools/mbi-checker' },
          { text: 'MBI Validator', link: '/tools/mbi-validator' },
          { text: 'Run Analysis', link: '/tools/run-analysis' },
          { text: 'Fill Polygon Gaps', link: '/tools/fill-polygon-gaps' },
          { text: 'Export Preliminary Polygons', link: '/tools/export-preliminary-polygons' },
          { text: 'Update Metadata', link: '/tools/update-metadata' },
          { text: 'Update Metadata (by Geocode)', link: '/tools/update-metadata-by-geocode' },
          { text: 'Fix LGU CRS / Geometry', link: '/tools/fix-lgu-crs' },
          { text: 'Join Barangay Attributes', link: '/tools/join-barangay-attributes' },
          { text: 'Check and Update', link: '/tools/check-and-update' },
          { text: 'PSA - LGU Boundary Comparison', link: '/tools/psa-lgu-comparison' },
          { text: 'Know Your Projection!', link: '/tools/know-your-projection' },
          { text: 'Package Layers by City/Mun', link: '/tools/package-layers-by-citymun' },
          { text: 'Package Style Loader', link: '/tools/package-style-loader' },
        ]
      },
      {
        text: 'Geometry & Repair',
        collapsed: false,
        items: [
          { text: 'Geometry Repair Toolkit', link: '/tools/geometry-repair-toolkit' },
          { text: 'Scan Geometry Errors', link: '/tools/scan-geometry-errors' },
          { text: 'Repair Polygon Geometries', link: '/tools/repair-polygon-geometries' },
          { text: 'Clip Project Layers by Extent', link: '/tools/clip-project-layers' },
        ]
      },
      {
        text: 'QField & Enumeration',
        collapsed: false,
        items: [
          { text: 'Package for QField', link: '/tools/package-qfield' },
          { text: 'EA Delineation and Merging', link: '/tools/ea-delineation-and-merging' },
        ]
      },
    ],

    socialLinks: [
      { icon: 'github', link: 'https://github.com/GMD-Repository/gemma-plugin' }
    ],

    footer: {
      message: 'Developed by the Geospatial Management Division',
      copyright: '© 2025–2026 Philippine Statistics Authority'
    },

    search: {
      provider: 'local'
    },

    editLink: {
      pattern: 'https://github.com/GMD-Repository/gemma-plugin/edit/main/docs/user-guide/:path',
      text: 'Edit this page on GitHub'
    },
  }
})
