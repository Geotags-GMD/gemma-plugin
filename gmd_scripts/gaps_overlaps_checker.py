# ----------------------------------------------------------------------
# MBI Gaps / Overlaps / Disputed Areas Checker
# Last updated: 2026-09-03
# Version: v12
#
# Changelog:
#   v1 - Initial Gaps/Overlaps detection between LGU and PSA polygons.
#   v2 - Added Disputed Areas extraction based on 'boundary' field
#        ('Contested' vs 'Barangay').
#   v3 - Added lgu_bgy_name field to Disputed Areas output.
#   v4 - Changed mbi_status ValueMap dropdown options to
#        '1_Updated' / '2_Pending'.
#   v5 - Renamed output field 'map_uuid' to 'case_uuid'.
#   v6 - Added 'Disputed Areas Only' to the Analysis-to-Run dropdown
#        (now: Overlaps, Gaps, and Disputed Areas / Overlaps Only /
#        Gaps Only / Disputed Areas Only); Disputed Areas output
#        generation is now gated by run_mode instead of always running;
#        re-applied case_uuid rename on top of user's latest label edits.
#   v7 - Removed 'mbi_status', 'mbi_remarks', and 'pso_remarks' fields
#        (and their editor-widget setup / post-processor) from all
#        output layers.
#   v8 - Removed 'Disputed Areas Only' option from the Analysis-to-Run
#        dropdown (now: Overlaps, Gaps, and Disputed Areas / Overlaps
#        Only / Gaps Only); Disputed Areas output now only generates
#        when the combined mode is selected.
#   v9 - Renamed the combined dropdown option from 'Overlaps, Gaps, and
#        Disputed Areas' to 'Gaps and Overlaps' (label only — the
#        combined mode still also generates the Disputed Areas layer).
#   v10 - The 'Gaps and Overlaps' mode no longer generates the Disputed
#         Areas output layer at all; run_disputed is now always False.
#         (Disputed-polygon exclusion logic used internally by Gap
#         detection is unaffected.)
#   v11 - Reference MBI cases are now taken into account during Gap
#         detection. Features whose 'mbi_type' contains 'Disputed' are
#         unioned and subtracted from gap geometries, so an already-filed
#         Disputed case is never re-reported as a Gap.
#         The source layer(s) are chosen via the required
#         'Reference MBI Cases Layer (ref_mbi_cases)' parameter. An
#         auto-detection fallback (any loaded polygon layer carrying an
#         'mbi_type' field, excluding the input layers) is retained for
#         programmatic callers, but is unreachable from the dialog now that
#         the parameter is required.
#   v12 - Fixed overlaps being silently dropped when the two overlapping
#         polygons belong to the SAME barangay (e.g. adjacent EAs inside one
#         barangay) or carry no barangay/city_mun attributes at all.
#         get_involved() grouped participants by barangay label, so such a
#         pair collapsed into one entry and failed the 'len(involved) < 2'
#         test. Overlap detection now groups by feature (by_feature=True),
#         so each polygon counts separately. Gap detection keeps the
#         original per-barangay grouping.
# ----------------------------------------------------------------------

__author__ = 'Geospatial Management Division'
__date__ = '2026-06-15'
__copyright__ = '(C) 2026, Geospatial Management Division'

import os
import uuid as _uuid
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QIcon
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingContext,
    QgsProcessingParameterMultipleLayers,
    QgsProcessingParameterEnum,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsVectorLayer,
    QgsFeature,
    QgsFeatureRequest,
    QgsFields,
    QgsField,
    QgsGeometry,
    QgsSpatialIndex,
    QgsWkbTypes,
)
import processing


class GapsOverlaps(QgsProcessingAlgorithm):

    INPUT1        = 'INPUT1'
    INPUT2        = 'INPUT2'
    REF_MBI_CASES = 'REF_MBI_CASES'
    RUN_MODE      = 'RUN_MODE'

    # Field that marks a layer as a reference MBI cases layer during
    # auto-detection, and the value fragment that flags a disputed case.
    REF_CASE_FIELD    = 'mbi_type'
    REF_DISPUTED_FLAG = 'disputed'

    def __init__(self):
        super().__init__()
        self._keep_alive = []

    def name(self):
        return 'mbi_checker_for_GEOTAGS'

    def displayName(self):
        return 'MBI Checker'

    def group(self):
        return '1Map'

    def groupId(self):
        return '1map'

    def createInstance(self):
        return GapsOverlaps()

    def icon(self):
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons', 'overlap.svg')
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return QIcon(":/images/themes/default/mActionFilter.svg")

    def shortHelpString(self):
        return (
            "<p>Detects boundary findings (gaps, overlaps, and disputed boundaries) "
            "of LGU polygon layers.</p>"
            "<h3>Output Layers</h3>"
            "<ul>"
            "<li><b>Gaps</b> — Empty slivers between polygons. Disputed polygons are "
            "excluded from the dissolve, and their footprint is subtracted from the "
            "result, so a Disputed area never duplicates as a gap. "
            "<i>mbi_type</i> = <b>1_Gap</b>.</li>"
            "<li><b>Overlaps</b> — Intersecting polygon pairs. "
            "<i>mbi_type</i> = <b>2_Overlap</b>.</li>"
            "</ul>"
            "<h3>Reference MBI Cases</h3>"
            "<p>Previously filed MBI cases are excluded from Gap detection: any "
            "feature whose <i>mbi_type</i> reads as <b>Disputed</b> (e.g. "
            "<b>3_Disputed</b>) has its footprint subtracted from the gap result, so "
            "an area already recorded as disputed is not reported again as a Gap. "
            "Features with any other <i>mbi_type</i> are ignored.</p>"
            "<p>Select the case layer(s) in <b>Reference MBI Cases Layer "
            "(ref_mbi_cases)</b>. This input is required — the layer must carry an "
            "<i>mbi_type</i> field for its Disputed cases to be picked up; a layer "
            "without that field is accepted but contributes nothing, and a warning is "
            "written to the log.</p>"
            "<h3>Output Fields</h3>"
            "<ul>"
            "<li><b>case_uuid</b> — UUID per finding</li>"
            "<li><b>geocode / region / province / city_mun / barangay</b></li>"
            "<li><b>source</b> — LGU/PSA label (NULL for gaps)</li>"
            "<li><b>mbi_level</b> — Inter-Region / Inter-Province / "
            "Inter-City/Municipality / Inter-Barangay / Within-Barangay</li>"
            "<li><b>involved_areas</b> — Comma-separated geocodes</li>"
            "<li><b>involved_bgys</b> — Semicolon-separated barangay+city names</li>"
            "<li><b>count_involved_areas</b></li>"
            "<li><b>mbi_type</b> — 1_Gap / 2_Overlap / 3_Disputed</li>"
            "<li><b>num_bldg_pts</b></li>"
            "</ul>"
           
        )

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterMultipleLayers(
                self.INPUT1,
                'Select Polygon Layer(s)',
                QgsProcessing.TypeVectorPolygon
            )
        )
        self.addParameter(
            QgsProcessingParameterMultipleLayers(
                self.INPUT2,
                'Select Building Point Layer(s)',
                QgsProcessing.TypeVectorPoint
            )
        )
        self.addParameter(
            QgsProcessingParameterMultipleLayers(
                self.REF_MBI_CASES,
                'Reference MBI Cases Layer (ref_mbi_cases)',
                QgsProcessing.TypeVectorPolygon,
                optional=True
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.RUN_MODE,
                'Analysis to Run',
                options=[
                    'Gaps and Overlaps',
                    'Overlaps Only',
                    'Gaps Only',
                ],
                defaultValue=0
            )
        )

    def processAlgorithm(self, parameters, context, feedback: QgsProcessingFeedback):
        self._keep_alive = []

        def keep_layer(layer):
            if layer is not None:
                self._keep_alive.append(layer)
            return layer

        polygon_layers = self.parameterAsLayerList(parameters, self.INPUT1, context)
        building_layers = self.parameterAsLayerList(parameters, self.INPUT2, context)
        ref_case_selected = self.parameterAsLayerList(parameters, self.REF_MBI_CASES, context) or []
        run_mode = self.parameterAsEnum(parameters, self.RUN_MODE, context)

        if not polygon_layers:
            raise QgsProcessingException("PSA and LGU polygon layer(s) must be selected.")
        if not building_layers:
            raise QgsProcessingException("Building point layer(s) must be selected.")

        run_overlaps = run_mode in (0, 1)
        run_gaps     = run_mode in (0, 2)
        run_disputed = False

        target_crs       = QgsCoordinateReferenceSystem("EPSG:3857")
        output_crs       = QgsCoordinateReferenceSystem("EPSG:4326")
        transform_to_out = QgsCoordinateTransform(target_crs, output_crs, QgsProject.instance())

        feedback.pushInfo(
            "Processing... Mode: " + [
                'Gaps and Overlaps',
                'Overlaps Only',
                'Gaps Only',
            ][run_mode]
        )

        # ------------------------------------------------------------------
        # Helpers
        # ------------------------------------------------------------------
        def get_attr(feat, names):
            if isinstance(names, str):
                names = [names]
            lower_map = {f.name().lower(): f.name() for f in feat.fields()}
            for name in names:
                real = lower_map.get(name.lower())
                if real:
                    try:
                        v = feat[real]
                        if v is not None:
                            return v
                    except Exception:
                        pass
            return None

        def txt(v):
            if v is None:
                return ''
            s = str(v).strip()
            if s.upper() == 'NULL':
                return ''
            return s

        def safe_area(geom):
            if geom is None or geom.isEmpty():
                return 0.0
            try:
                return float(geom.area())
            except Exception:
                return 0.0

        def label_from_info(info):
            brgy = txt(info.get('barangay'))
            city = txt(info.get('city_mun'))
            if brgy and city:
                return f"{brgy}, {city}"
            return brgy or city or 'Unknown'

        def refactor_layer(layer):
            mapping = []
            for f in layer.fields():
                mapping.append({
                    'alias': '', 'comment': '',
                    'expression': f'"{f.name()}"',
                    'length': f.length(), 'name': f.name(),
                    'precision': f.precision(), 'sub_type': 0,
                    'type': f.type(), 'type_name': f.typeName()
                })
            return keep_layer(processing.run(
                'native:refactorfields',
                {'INPUT': layer, 'FIELDS_MAPPING': mapping, 'OUTPUT': 'memory:'},
                context=context, feedback=feedback
            )['OUTPUT'])

        def merge_layers(layers, crs):
            refs = [refactor_layer(l) for l in layers]
            return keep_layer(processing.run(
                'native:mergevectorlayers',
                {'LAYERS': refs, 'CRS': crs, 'OUTPUT': 'memory:'},
                context=context, feedback=feedback
            )['OUTPUT'])

        def reproject_fix(layer):
            reproj = keep_layer(processing.run(
                'native:reprojectlayer',
                {'INPUT': layer, 'TARGET_CRS': target_crs,
                 'CONVERT_CURVED_GEOMETRIES': False, 'OUTPUT': 'memory:'},
                context=context, feedback=feedback
            )['OUTPUT'])
            return keep_layer(processing.run(
                'native:fixgeometries',
                {'INPUT': reproj, 'METHOD': 1, 'OUTPUT': 'memory:'},
                context=context, feedback=feedback
            )['OUTPUT'])

        def singleparts(layer):
            single = keep_layer(processing.run(
                'native:multiparttosingleparts',
                {'INPUT': layer, 'OUTPUT': 'memory:'},
                context=context, feedback=feedback
            )['OUTPUT'])
            return keep_layer(processing.run(
                'native:fixgeometries',
                {'INPUT': single, 'METHOD': 1, 'OUTPUT': 'memory:'},
                context=context, feedback=feedback
            )['OUTPUT'])

        def resolve_ref_case_layers():
            """
            Return the reference MBI cases layer(s) to scan, plus a label
            describing where they came from (for the log).

            Layers explicitly chosen in the 'Reference MBI Cases Layer(s)'
            parameter always win. Only when that is left blank does the
            project get auto-scanned.
            """
            if ref_case_selected:
                # An explicit choice is honoured as-is, but flag any layer that
                # cannot contribute because it has no 'mbi_type' field.
                for lyr in ref_case_selected:
                    names = {f.name().lower() for f in lyr.fields()}
                    if self.REF_CASE_FIELD.lower() not in names:
                        feedback.pushInfo(
                            f"  WARNING: selected layer '{lyr.name()}' has no "
                            f"'{self.REF_CASE_FIELD}' field — it contributes no "
                            f"Disputed areas."
                        )
                return ref_case_selected, 'selected'
            return detect_ref_case_layers(), 'auto-detected'

        def detect_ref_case_layers():
            """
            Auto-detect reference MBI cases layer(s) from the current project.

            A layer qualifies when it is a valid polygon vector layer carrying
            an 'mbi_type' field (case-insensitive) and was not one of the
            layers picked as an input for this run.
            """
            input_ids = {
                l.id() for l in list(polygon_layers) + list(building_layers)
                if l is not None
            }
            found = []
            for lyr in QgsProject.instance().mapLayers().values():
                if not isinstance(lyr, QgsVectorLayer) or not lyr.isValid():
                    continue
                if lyr.id() in input_ids:
                    continue
                if lyr.geometryType() != QgsWkbTypes.PolygonGeometry:
                    continue
                names = {f.name().lower() for f in lyr.fields()}
                if self.REF_CASE_FIELD.lower() not in names:
                    continue
                found.append(lyr)
            found.sort(key=lambda l: l.name())
            return found

        # ------------------------------------------------------------------
        # Output layer schema
        # Fields: case_uuid, geocode, region, province, city_mun, barangay,
        #         source, mbi_level, involved_areas, involved_bgys,
        #         count_involved_areas, mbi_type, num_bldg_pts
        # ------------------------------------------------------------------
        def output_layer(name, extra_fields=None):
            fields = QgsFields()
            fields.append(QgsField('case_uuid',             QVariant.String))
            fields.append(QgsField('geocode',              QVariant.String))
            fields.append(QgsField('region',               QVariant.String))
            fields.append(QgsField('province',             QVariant.String))
            fields.append(QgsField('city_mun',             QVariant.String))
            fields.append(QgsField('barangay',             QVariant.String))
            fields.append(QgsField('source',               QVariant.String))
            fields.append(QgsField('mbi_level',            QVariant.String))
            fields.append(QgsField('involved_areas',       QVariant.String))
            fields.append(QgsField('involved_bgys',        QVariant.String))
            fields.append(QgsField('count_involved_areas', QVariant.Int))
            fields.append(QgsField('mbi_type',             QVariant.String))
            fields.append(QgsField('num_bldg_pts',         QVariant.Int))
            # Layer-specific extra fields appended at the end (e.g. Disputed
            # Areas gets 'lgu_bgy_name').
            for f in (extra_fields or []):
                fields.append(f)
            layer = QgsVectorLayer('Polygon?crs=EPSG:4326', name, 'memory')
            layer.dataProvider().addAttributes(fields)
            layer.updateFields()
            return keep_layer(layer)

        def load_layer(layer, name):
            if layer is None:
                return None
            layer.setName(name)
            details = QgsProcessingContext.LayerDetails(name, context.project(), 'OUTPUT')
            context.temporaryLayerStore().addMapLayer(layer)
            context.addLayerToLoadOnCompletion(layer.id(), details)
            return layer.id()

        # ------------------------------------------------------------------
        # Prepare input layers
        # ------------------------------------------------------------------
        feedback.pushInfo("Merging and fixing polygon layers...")
        feedback.setProgress(2)
        merged_poly = merge_layers(polygon_layers, polygon_layers[0].crs())
        fixed_poly  = reproject_fix(merged_poly)
        poly_layer  = singleparts(fixed_poly)

        feedback.pushInfo("Merging and fixing building point layers...")
        feedback.setProgress(8)
        merged_bldg = merge_layers(building_layers, building_layers[0].crs())
        bldg_layer  = reproject_fix(merged_bldg)

        # ------------------------------------------------------------------
        # Build caches and spatial indexes
        # ------------------------------------------------------------------
        feedback.pushInfo("Building spatial indexes...")
        feedback.setProgress(12)

        polygon_infos = {}
        polygon_index = QgsSpatialIndex()

        for feat in poly_layer.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            info = {
                'fid':        feat.id(),
                'geometry':   QgsGeometry(geom),
                'whole_area': safe_area(geom),
                'geocode':    get_attr(feat, ['geocode',  'GEOCODE']),
                'region':     get_attr(feat, ['region',   'REGION',   'Region']),
                'province':   get_attr(feat, ['province', 'PROVINCE', 'Province']),
                'city_mun':   get_attr(feat, ['city_mun', 'CITY_MUN', 'city/mun']),
                'barangay':   get_attr(feat, ['barangay', 'BARANGAY', 'brgy', 'BRGY']),
                'source':     get_attr(feat, ['source',   'SOURCE',   'Source']),
                'boundary':   get_attr(feat, ['boundary', 'BOUNDARY', 'Boundary']),
                'lgu_bgy_name': get_attr(feat, ['lgu_bgy_name', 'LGU_BGY_NAME', 'lgu_bgy_nam']),
            }
            polygon_infos[feat.id()] = info
            polygon_index.addFeature(feat)

        bldg_geoms = {}
        bldg_index = QgsSpatialIndex()
        for feat in bldg_layer.getFeatures():
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            bldg_geoms[feat.id()] = QgsGeometry(geom)
            bldg_index.addFeature(feat)

        if not polygon_infos:
            raise QgsProcessingException("No valid polygon features found.")

        # Partition fids: Disputed (boundary = 'Contested') vs normal
        disputed_fids      = {
            fid for fid, info in polygon_infos.items()
            if txt(info.get('boundary')).strip().lower() == 'contested'
        }
        non_disputed_fids  = set(polygon_infos.keys()) - disputed_fids

        feedback.pushInfo(
            f"  {len(disputed_fids)} Disputed polygon(s) found; "
            f"{len(non_disputed_fids)} non-Disputed polygon(s)."
        )

        # ------------------------------------------------------------------
        # Spatial helpers
        # ------------------------------------------------------------------
        def count_points(poly_geom):
            cnt = 0
            for fid in bldg_index.intersects(poly_geom.boundingBox()):
                pt = bldg_geoms.get(fid)
                if pt is None or pt.isEmpty():
                    continue
                try:
                    if poly_geom.intersects(pt) or poly_geom.contains(pt):
                        cnt += 1
                except Exception:
                    pass
            return cnt

        def get_involved(finding_geom, gap_mode=False, by_feature=False):
            """
            List the polygons that take part in a finding.

            by_feature=False groups them by barangay label, so one barangay
            counts once no matter how many of its polygons touch the finding.
            by_feature=True keeps every polygon as its own entry — required for
            overlaps, where two polygons of the SAME barangay (e.g. adjacent
            EAs, or polygons with no barangay attributes at all) share a label
            and would otherwise collapse into a single entry and be discarded.
            """
            search_geom = finding_geom.buffer(0.50, 5) if gap_mode else finding_geom
            grouped = {}
            for fid in polygon_index.intersects(search_geom.boundingBox()):
                info = polygon_infos.get(fid)
                if not info:
                    continue
                poly_geom = info['geometry']
                try:
                    if gap_mode:
                        if not search_geom.intersects(poly_geom):
                            continue
                        covered = 0.0
                    else:
                        if not finding_geom.intersects(poly_geom):
                            continue
                        inter   = finding_geom.intersection(poly_geom)
                        covered = safe_area(inter)
                        if covered <= 0.01:
                            continue
                except Exception:
                    continue
                label = label_from_info(info)
                key   = fid if by_feature else label
                if key not in grouped:
                    grouped[key] = {'info': info, 'label': label, 'covered_area': 0.0}
                grouped[key]['covered_area'] += covered

            if gap_mode and grouped:
                share = safe_area(finding_geom) / len(grouped)
                for key in grouped:
                    grouped[key]['covered_area'] = share

            out = [
                {'label': data['label'], 'info': data['info'],
                 'covered_area': data['covered_area']}
                for data in grouped.values()
            ]
            out.sort(key=lambda x: x['label'])
            return out

        def derive_mbi_level(involved):
            regions   = set(txt(x['info'].get('region'))   for x in involved)
            provinces = set(txt(x['info'].get('province'))  for x in involved)
            cities    = set(txt(x['info'].get('city_mun'))  for x in involved)
            brgys     = set(txt(x['info'].get('barangay'))  for x in involved)
            if len(regions)   > 1: return '1_Inter-Region'
            if len(provinces) > 1: return '2_Inter-Province'
            if len(cities)    > 1: return '3_Inter-City/Municipality'
            if len(brgys)     > 1: return '4_Inter-Barangay'
            return '5_Within-Barangay'

        def choose_overlap_reference(info1, info2):
            s1 = txt(info1.get('source')).upper()
            s2 = txt(info2.get('source')).upper()
            if 'LGU' in s1 and 'PSA' in s2: return info1
            if 'LGU' in s2 and 'PSA' in s1: return info2
            if s1 and not s2: return info1
            if s2 and not s1: return info2
            return info2

        def build_feature(geom_3857, involved, kind, out_fields,
                          reference_info=None, map_uuid=None, extra_attrs=None):
            """
            Build a single QgsFeature for the output layer.

            kind:
                'Overlap'  -> mbi_type 2_Overlap
                'Gap'      -> mbi_type 1_Gap
                'Disputed' -> mbi_type 3_Disputed
            """
            if not involved:
                return None

            geom_out = QgsGeometry(geom_3857)
            try:
                geom_out.transform(transform_to_out)
            except Exception:
                pass

            ref = (reference_info if reference_info is not None
                   else max(involved, key=lambda x: x['covered_area'])['info'])

            # --- mbi_type ---
            if kind == 'Gap':
                mbi_type    = '1_Gap'
                source_val  = txt(ref.get('source')) or None

            elif kind == 'Disputed':
                mbi_type    = '3_Disputed'
                source_val  = txt(ref.get('source')) or None

            else:
                # Overlap — mbi_type is now a fixed label; the
                # minor/major/full mismatch-percentage computation has
                # been removed since it is no longer needed.
                mbi_type   = '2_Overlap'
                source_val = txt(ref.get('source')) or None

            involved_areas = ','.join(txt(x['info'].get('geocode')) for x in involved)
            involved_bgys  = ';'.join(x['label'] for x in involved)
            count_inv      = len(involved)
            mbi_level      = derive_mbi_level(involved)
            bldg_count     = count_points(geom_3857)
            uuid_val       = map_uuid if map_uuid else str(_uuid.uuid4())

            feat = QgsFeature(out_fields)
            feat.setGeometry(geom_out)
            feat.setAttributes([
                uuid_val,                    # case_uuid
                txt(ref.get('geocode')),     # geocode
                txt(ref.get('region')),      # region
                txt(ref.get('province')),    # province
                txt(ref.get('city_mun')),    # city_mun
                txt(ref.get('barangay')),    # barangay
                source_val,                  # source
                mbi_level,                   # mbi_level
                involved_areas,              # involved_areas
                involved_bgys,               # involved_bgys
                count_inv,                   # count_involved_areas
                mbi_type,                    # mbi_type
                bldg_count,                  # num_bldg_pts
            ] + list(extra_attrs or []))
            return feat

        results = {}

        # ==================================================================
        # DISPUTED AREAS OUTPUT
        # Runs only when run_mode is 'Gaps and Overlaps'.
        # (disputed_fids/non_disputed_fids above are still always computed
        # since Gaps/Overlaps rely on them.)
        # Polygons with boundary = 'Contested' -> mbi_type = '3_Disputed'
        # ==================================================================
        if run_disputed:
            feedback.pushInfo("Extracting Disputed Areas...")
            feedback.setProgress(15)

            out_disp        = output_layer(
                'Disputed Areas',
                extra_fields=[QgsField('lgu_bgy_name', QVariant.String)]
            )
            out_disp_fields = out_disp.fields()
            disp_feats      = []

            for fid in disputed_fids:
                info = polygon_infos[fid]
                geom = info['geometry']
                if geom is None or geom.isEmpty():
                    continue

                self_involved = [{
                    'label':        label_from_info(info),
                    'info':         info,
                    'covered_area': info['whole_area'],
                }]
                lgu_bgy_val = txt(info.get('lgu_bgy_name')) or label_from_info(info)
                out_feat = build_feature(
                    geom, self_involved, 'Disputed', out_disp_fields,
                    reference_info=info, extra_attrs=[lgu_bgy_val]
                )
                if out_feat:
                    disp_feats.append(out_feat)

            if disp_feats:
                out_disp.dataProvider().addFeatures(disp_feats)
                out_disp.updateExtents()
                results['DISPUTED'] = load_layer(out_disp, 'Disputed Areas')
                feedback.pushInfo(f"  {len(disp_feats)} Disputed feature(s) written.")
            else:
                feedback.pushInfo("No Disputed features found.")
                results['DISPUTED'] = None
        else:
            results['DISPUTED'] = None

        # ==================================================================
        # OVERLAP DETECTION
        # Scans ALL polygons (including Disputed) so that overlaps between a
        # matched Barangay and a Disputed polygon are captured.
        # ==================================================================
        if run_overlaps:
            feedback.pushInfo("Detecting overlaps...")
            feedback.setProgress(20)

            out_ovl        = output_layer('Overlaps')
            out_ovl_fields = out_ovl.fields()
            ovl_feats      = []

            checked_pairs = set()
            ids   = list(polygon_infos.keys())
            total = len(ids)

            for i, fid1 in enumerate(ids):
                if feedback.isCanceled():
                    return {}

                info1 = polygon_infos[fid1]
                geom1 = info1['geometry']

                for fid2 in polygon_index.intersects(geom1.boundingBox()):
                    if fid1 == fid2:
                        continue
                    pair_key = tuple(sorted((fid1, fid2)))
                    if pair_key in checked_pairs:
                        continue
                    checked_pairs.add(pair_key)

                    info2 = polygon_infos.get(fid2)
                    if not info2:
                        continue
                    geom2 = info2['geometry']

                    try:
                        if not geom1.intersects(geom2):
                            continue
                        inter = geom1.intersection(geom2)
                        if inter is None or inter.isEmpty():
                            continue

                        parts = []
                        if QgsWkbTypes.geometryType(inter.wkbType()) == QgsWkbTypes.PolygonGeometry:
                            parts = inter.asGeometryCollection() if inter.isMultipart() else [inter]
                        elif inter.isMultipart():
                            parts = [
                                p for p in inter.asGeometryCollection()
                                if QgsWkbTypes.geometryType(p.wkbType()) == QgsWkbTypes.PolygonGeometry
                            ]

                        for part in parts:
                            if part is None or part.isEmpty():
                                continue
                            if safe_area(part) <= 0.10:
                                continue

                            involved = get_involved(part, gap_mode=False, by_feature=True)
                            if len(involved) < 2:
                                continue

                            ref_for_output = choose_overlap_reference(info1, info2)
                            out_feat = build_feature(
                                part, involved, 'Overlap', out_ovl_fields,
                                reference_info=ref_for_output
                            )
                            if out_feat:
                                ovl_feats.append(out_feat)

                    except Exception:
                        continue

                if total:
                    feedback.setProgress(20 + int((i / total) * 35))

            if ovl_feats:
                out_ovl.dataProvider().addFeatures(ovl_feats)
                out_ovl.updateExtents()
                results['OVERLAPS'] = load_layer(out_ovl, 'Overlaps')
                feedback.pushInfo(f"  {len(ovl_feats)} overlap feature(s) written.")
            else:
                feedback.pushInfo("No overlaps detected.")
                results['OVERLAPS'] = None

            feedback.setProgress(55 if run_gaps else 100)

        # ==================================================================
        # GAP DETECTION
        # Disputed polygons are EXCLUDED from the dissolve so their footprint
        # also registers as a geographic gap — complementing the Disputed
        # Areas output layer.
        # ==================================================================
        if run_gaps:
            feedback.pushInfo(
                "Detecting gaps (Disputed polygons excluded from dissolve)..."
            )
            feedback.setProgress(60)

            # Build a filtered memory layer with only non-Disputed polygons
            non_disp_layer = QgsVectorLayer(
                f'Polygon?crs={target_crs.authid()}', 'non_disputed', 'memory'
            )
            non_disp_layer.dataProvider().addAttributes(poly_layer.fields().toList())
            non_disp_layer.updateFields()
            non_disp_feats = [
                f for f in poly_layer.getFeatures()
                if f.id() in non_disputed_fids
            ]
            non_disp_layer.dataProvider().addFeatures(non_disp_feats)
            non_disp_layer.updateExtents()
            keep_layer(non_disp_layer)

            dissolved = keep_layer(processing.run(
                'native:dissolve',
                {'INPUT': non_disp_layer, 'FIELD': [],
                 'SEPARATE_DISJOINT': False, 'OUTPUT': 'memory:'},
                context=context, feedback=feedback
            )['OUTPUT'])

            no_holes = keep_layer(processing.run(
                'native:deleteholes',
                {'INPUT': dissolved, 'MIN_AREA': 0, 'OUTPUT': 'memory:'},
                context=context, feedback=feedback
            )['OUTPUT'])

            cleaned = keep_layer(processing.run(
                'native:dissolve',
                {'INPUT': no_holes, 'FIELD': [],
                 'SEPARATE_DISJOINT': False, 'OUTPUT': 'memory:'},
                context=context, feedback=feedback
            )['OUTPUT'])

            gap_diff = keep_layer(processing.run(
                'native:difference',
                {'INPUT': cleaned, 'OVERLAY': dissolved,
                 'GRID_SIZE': None, 'OUTPUT': 'memory:'},
                context=context, feedback=feedback
            )['OUTPUT'])

            gap_single = keep_layer(processing.run(
                'native:multiparttosingleparts',
                {'INPUT': gap_diff, 'OUTPUT': 'memory:'},
                context=context, feedback=feedback
            )['OUTPUT'])

            gap_fixed = keep_layer(processing.run(
                'native:fixgeometries',
                {'INPUT': gap_single, 'METHOD': 1, 'OUTPUT': 'memory:'},
                context=context, feedback=feedback
            )['OUTPUT'])

            out_gap        = output_layer('Gaps')
            out_gap_fields = out_gap.fields()
            gap_feats      = []

            # Build a unified EPSG:3857 geometry of all Disputed polygons so
            # their footprint can be subtracted from gap geometries — preventing
            # duplicate coverage between the Gaps and Disputed Areas layers.
            # NOTE: polygon_infos geometries are stored in EPSG:3857 (target_crs),
            # which matches the gap_fixed layer CRS — so NO transform is applied here.
            disputed_geom_union = None
            for fid in disputed_fids:
                info = polygon_infos[fid]
                d_geom = info['geometry']
                if d_geom is None or d_geom.isEmpty():
                    continue
                d_geom_3857 = QgsGeometry(d_geom)   # already in EPSG:3857
                if disputed_geom_union is None:
                    disputed_geom_union = d_geom_3857
                else:
                    disputed_geom_union = disputed_geom_union.combine(d_geom_3857)

            # Reference MBI cases: any feature whose 'mbi_type' reads as
            # Disputed (e.g. '3_Disputed') marks an area that has already been
            # filed as a dispute, so it must not be re-reported as a Gap. Its
            # footprint is merged into the same subtraction union above.
            ref_case_layers, ref_source = resolve_ref_case_layers()
            if ref_case_layers:
                feedback.pushInfo(
                    f"Using {len(ref_case_layers)} {ref_source} reference MBI cases "
                    f"layer(s): " + ', '.join(l.name() for l in ref_case_layers)
                )
                ref_merged = merge_layers(ref_case_layers, ref_case_layers[0].crs())
                ref_fixed  = reproject_fix(ref_merged)   # -> EPSG:3857

                ref_disputed_count = 0
                for feat in ref_fixed.getFeatures():
                    if self.REF_DISPUTED_FLAG not in txt(
                        get_attr(feat, [self.REF_CASE_FIELD])
                    ).lower():
                        continue
                    r_geom = feat.geometry()
                    if r_geom is None or r_geom.isEmpty():
                        continue
                    ref_disputed_count += 1
                    r_geom_3857 = QgsGeometry(r_geom)   # already in EPSG:3857
                    if disputed_geom_union is None:
                        disputed_geom_union = r_geom_3857
                    else:
                        disputed_geom_union = disputed_geom_union.combine(r_geom_3857)

                feedback.pushInfo(
                    f"  {ref_disputed_count} Disputed reference case(s) excluded "
                    f"from Gap detection."
                )
            else:
                feedback.pushInfo(
                    "No reference MBI cases layer selected or detected in the "
                    f"project (auto-detection needs a polygon layer with an "
                    f"'{self.REF_CASE_FIELD}' field). Continuing without "
                    f"Disputed-case exclusion."
                )

            for feat in gap_fixed.getFeatures():
                geom = feat.geometry()
                if geom is None or geom.isEmpty():
                    continue
                if safe_area(geom) <= 0.10:
                    continue

                # Subtract Disputed polygon footprints from this gap geometry
                # so Gaps and Disputed Areas layers do not overlap.
                if disputed_geom_union is not None and not disputed_geom_union.isEmpty():
                    try:
                        geom = geom.difference(disputed_geom_union)
                        if geom is None or geom.isEmpty():
                            continue
                    except Exception:
                        pass

                # Explode multipart results from the subtraction into single parts
                parts = geom.asGeometryCollection() if geom.isMultipart() else [geom]

                for part in parts:
                    if part is None or part.isEmpty():
                        continue
                    if safe_area(part) <= 0.10:
                        continue

                    involved = get_involved(part, gap_mode=True)
                    if not involved:
                        continue

                    out_feat = build_feature(part, involved, 'Gap', out_gap_fields)
                    if out_feat:
                        gap_feats.append(out_feat)

            if gap_feats:
                out_gap.dataProvider().addFeatures(gap_feats)
                out_gap.updateExtents()
                results['GAPS'] = load_layer(out_gap, 'Gaps')
                feedback.pushInfo(f"  {len(gap_feats)} gap feature(s) written.")
            else:
                feedback.pushInfo("No gaps detected.")
                results['GAPS'] = None

            feedback.setProgress(100)

        feedback.pushInfo("Finished LGU vs PSA Boundary Gap and Overlap Checker v12.")
        return results