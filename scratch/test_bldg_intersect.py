from qgis.core import (
    QgsApplication, QgsVectorLayer, QgsField, QgsFeature,
    QgsGeometry, QgsPointXY, QgsFeatureRequest
)
from PyQt5.QtCore import QVariant

qgs = QgsApplication([], False)
qgs.initQgis()

# EA polygon: (0,0) to (2,2)
poly_vl = QgsVectorLayer('Polygon?crs=EPSG:4326', 'ea', 'memory')
poly = QgsGeometry.fromWkt('POLYGON((0 0, 0 2, 2 2, 2 0, 0 0))')

# Building points:
# Point 1: (0.5, 0.5) inside, est_hhcount = 2
# Point 2: (1.5, 1.5) inside, est_hhcount = 3
# Point 3: (3.0, 3.0) outside, est_hhcount = 5
bldg_vl = QgsVectorLayer('Point?crs=EPSG:4326', 'bldg', 'memory')
pr = bldg_vl.dataProvider()
pr.addAttributes([QgsField('est_hhcount', QVariant.Double)])
bldg_vl.updateFields()

f1 = QgsFeature(bldg_vl.fields())
f1.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(0.5, 0.5)))
f1.setAttribute('est_hhcount', 2.0)

f2 = QgsFeature(bldg_vl.fields())
f2.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(1.5, 1.5)))
f2.setAttribute('est_hhcount', 3.0)

f3 = QgsFeature(bldg_vl.fields())
f3.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(3.0, 3.0)))
f3.setAttribute('est_hhcount', 5.0)

pr.addFeatures([f1, f2, f3])

req = QgsFeatureRequest().setFilterRect(poly.boundingBox())
b_cnt = 0
b_hh = 0.0
bldg_hh_idx = bldg_vl.fields().indexOf('est_hhcount')
for bf in bldg_vl.getFeatures(req):
    geom = bf.geometry()
    if geom and not geom.isEmpty() and poly.intersects(geom):
        b_cnt += 1
        b_hh += float(bf.attribute(bldg_hh_idx))

print(f"Building points inside: count={b_cnt}, hh={b_hh}")
assert b_cnt == 2
assert b_hh == 5.0
print("PASSED!")

qgs.exitQgis()
