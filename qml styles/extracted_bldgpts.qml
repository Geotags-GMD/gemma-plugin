<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis simplifyLocal="1" simplifyDrawingTol="1" styleCategories="AllStyleCategories" labelsEnabled="1" minScale="100000000" hasScaleBasedVisibilityFlag="0" simplifyAlgorithm="0" maxScale="100000" simplifyDrawingHints="0" simplifyMaxScale="1" symbologyReferenceScale="-1" readOnly="1" version="3.22.16-Białowieża">
  <flags>
    <Identifiable>0</Identifiable>
    <Removable>1</Removable>
    <Searchable>0</Searchable>
    <Private>0</Private>
  </flags>
  <temporal limitMode="0" endExpression="" durationField="" accumulate="0" endField="" fixedDuration="0" enabled="0" mode="0" startExpression="" startField="" durationUnit="min">
    <fixedRange>
      <start></start>
      <end></end>
    </fixedRange>
  </temporal>
  <renderer-v2 symbollevels="0" referencescale="-1" enableorderby="0" type="RuleRenderer" forceraster="0">
    <rules key="{4a56af3b-e788-49f2-92d9-2c87b4eaeb61}">
      <rule label="Extracted Building Points" key="{0d24ea02-8652-4a01-9d83-6fddd4d9fc7f}" symbol="0">
        <rule label="Extracted Buildings (Large)" scalemaxdenom="2500" key="{2bbf305b-0c0c-4ba2-bb72-96c6892b5028}" symbol="1"/>
        <rule label="Extracted Buildings (Medium)" scalemaxdenom="5000" key="{ea87621e-59cd-4fa3-a749-86abbb2ea9d3}" symbol="2" scalemindenom="2500"/>
        <rule label="Extracted Buildings (Small)" scalemaxdenom="250000" key="{67b19425-fce8-4f1f-b71c-2869773a415c}" symbol="3" scalemindenom="5000"/>
      </rule>
    </rules>
    <symbols>
      <symbol force_rhr="0" clip_to_extent="1" type="marker" name="0" alpha="0">
        <data_defined_properties>
          <Option type="Map">
            <Option value="" type="QString" name="name"/>
            <Option name="properties"/>
            <Option value="collection" type="QString" name="type"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleMarker" locked="0" enabled="1" pass="0">
          <Option type="Map">
            <Option value="0" type="QString" name="angle"/>
            <Option value="square" type="QString" name="cap_style"/>
            <Option value="145,82,45,255" type="QString" name="color"/>
            <Option value="1" type="QString" name="horizontal_anchor_point"/>
            <Option value="bevel" type="QString" name="joinstyle"/>
            <Option value="circle" type="QString" name="name"/>
            <Option value="0,0" type="QString" name="offset"/>
            <Option value="3x:0,0,0,0,0,0" type="QString" name="offset_map_unit_scale"/>
            <Option value="MM" type="QString" name="offset_unit"/>
            <Option value="35,35,35,255" type="QString" name="outline_color"/>
            <Option value="solid" type="QString" name="outline_style"/>
            <Option value="0" type="QString" name="outline_width"/>
            <Option value="3x:0,0,0,0,0,0" type="QString" name="outline_width_map_unit_scale"/>
            <Option value="MM" type="QString" name="outline_width_unit"/>
            <Option value="diameter" type="QString" name="scale_method"/>
            <Option value="2" type="QString" name="size"/>
            <Option value="3x:0,0,0,0,0,0" type="QString" name="size_map_unit_scale"/>
            <Option value="MM" type="QString" name="size_unit"/>
            <Option value="1" type="QString" name="vertical_anchor_point"/>
          </Option>
          <prop k="angle" v="0"/>
          <prop k="cap_style" v="square"/>
          <prop k="color" v="145,82,45,255"/>
          <prop k="horizontal_anchor_point" v="1"/>
          <prop k="joinstyle" v="bevel"/>
          <prop k="name" v="circle"/>
          <prop k="offset" v="0,0"/>
          <prop k="offset_map_unit_scale" v="3x:0,0,0,0,0,0"/>
          <prop k="offset_unit" v="MM"/>
          <prop k="outline_color" v="35,35,35,255"/>
          <prop k="outline_style" v="solid"/>
          <prop k="outline_width" v="0"/>
          <prop k="outline_width_map_unit_scale" v="3x:0,0,0,0,0,0"/>
          <prop k="outline_width_unit" v="MM"/>
          <prop k="scale_method" v="diameter"/>
          <prop k="size" v="2"/>
          <prop k="size_map_unit_scale" v="3x:0,0,0,0,0,0"/>
          <prop k="size_unit" v="MM"/>
          <prop k="vertical_anchor_point" v="1"/>
          <data_defined_properties>
            <Option type="Map">
              <Option value="" type="QString" name="name"/>
              <Option name="properties"/>
              <Option value="collection" type="QString" name="type"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol force_rhr="0" clip_to_extent="1" type="marker" name="1" alpha="1">
        <data_defined_properties>
          <Option type="Map">
            <Option value="" type="QString" name="name"/>
            <Option name="properties"/>
            <Option value="collection" type="QString" name="type"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleMarker" locked="0" enabled="1" pass="0">
          <Option type="Map">
            <Option value="0" type="QString" name="angle"/>
            <Option value="square" type="QString" name="cap_style"/>
            <Option value="145,82,45,255" type="QString" name="color"/>
            <Option value="1" type="QString" name="horizontal_anchor_point"/>
            <Option value="bevel" type="QString" name="joinstyle"/>
            <Option value="circle" type="QString" name="name"/>
            <Option value="0,0" type="QString" name="offset"/>
            <Option value="3x:0,0,0,0,0,0" type="QString" name="offset_map_unit_scale"/>
            <Option value="MM" type="QString" name="offset_unit"/>
            <Option value="0,0,0,253" type="QString" name="outline_color"/>
            <Option value="solid" type="QString" name="outline_style"/>
            <Option value="0.2" type="QString" name="outline_width"/>
            <Option value="3x:0,0,0,0,0,0" type="QString" name="outline_width_map_unit_scale"/>
            <Option value="MM" type="QString" name="outline_width_unit"/>
            <Option value="diameter" type="QString" name="scale_method"/>
            <Option value="3.4" type="QString" name="size"/>
            <Option value="3x:0,0,0,0,0,0" type="QString" name="size_map_unit_scale"/>
            <Option value="MM" type="QString" name="size_unit"/>
            <Option value="1" type="QString" name="vertical_anchor_point"/>
          </Option>
          <prop k="angle" v="0"/>
          <prop k="cap_style" v="square"/>
          <prop k="color" v="145,82,45,255"/>
          <prop k="horizontal_anchor_point" v="1"/>
          <prop k="joinstyle" v="bevel"/>
          <prop k="name" v="circle"/>
          <prop k="offset" v="0,0"/>
          <prop k="offset_map_unit_scale" v="3x:0,0,0,0,0,0"/>
          <prop k="offset_unit" v="MM"/>
          <prop k="outline_color" v="0,0,0,253"/>
          <prop k="outline_style" v="solid"/>
          <prop k="outline_width" v="0.2"/>
          <prop k="outline_width_map_unit_scale" v="3x:0,0,0,0,0,0"/>
          <prop k="outline_width_unit" v="MM"/>
          <prop k="scale_method" v="diameter"/>
          <prop k="size" v="3.4"/>
          <prop k="size_map_unit_scale" v="3x:0,0,0,0,0,0"/>
          <prop k="size_unit" v="MM"/>
          <prop k="vertical_anchor_point" v="1"/>
          <data_defined_properties>
            <Option type="Map">
              <Option value="" type="QString" name="name"/>
              <Option name="properties"/>
              <Option value="collection" type="QString" name="type"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol force_rhr="0" clip_to_extent="1" type="marker" name="2" alpha="1">
        <data_defined_properties>
          <Option type="Map">
            <Option value="" type="QString" name="name"/>
            <Option name="properties"/>
            <Option value="collection" type="QString" name="type"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleMarker" locked="0" enabled="1" pass="0">
          <Option type="Map">
            <Option value="0" type="QString" name="angle"/>
            <Option value="square" type="QString" name="cap_style"/>
            <Option value="145,82,45,255" type="QString" name="color"/>
            <Option value="1" type="QString" name="horizontal_anchor_point"/>
            <Option value="bevel" type="QString" name="joinstyle"/>
            <Option value="circle" type="QString" name="name"/>
            <Option value="0,0" type="QString" name="offset"/>
            <Option value="3x:0,0,0,0,0,0" type="QString" name="offset_map_unit_scale"/>
            <Option value="MM" type="QString" name="offset_unit"/>
            <Option value="0,0,0,255" type="QString" name="outline_color"/>
            <Option value="solid" type="QString" name="outline_style"/>
            <Option value="0.2" type="QString" name="outline_width"/>
            <Option value="3x:0,0,0,0,0,0" type="QString" name="outline_width_map_unit_scale"/>
            <Option value="MM" type="QString" name="outline_width_unit"/>
            <Option value="diameter" type="QString" name="scale_method"/>
            <Option value="3" type="QString" name="size"/>
            <Option value="3x:0,0,0,0,0,0" type="QString" name="size_map_unit_scale"/>
            <Option value="MM" type="QString" name="size_unit"/>
            <Option value="1" type="QString" name="vertical_anchor_point"/>
          </Option>
          <prop k="angle" v="0"/>
          <prop k="cap_style" v="square"/>
          <prop k="color" v="145,82,45,255"/>
          <prop k="horizontal_anchor_point" v="1"/>
          <prop k="joinstyle" v="bevel"/>
          <prop k="name" v="circle"/>
          <prop k="offset" v="0,0"/>
          <prop k="offset_map_unit_scale" v="3x:0,0,0,0,0,0"/>
          <prop k="offset_unit" v="MM"/>
          <prop k="outline_color" v="0,0,0,255"/>
          <prop k="outline_style" v="solid"/>
          <prop k="outline_width" v="0.2"/>
          <prop k="outline_width_map_unit_scale" v="3x:0,0,0,0,0,0"/>
          <prop k="outline_width_unit" v="MM"/>
          <prop k="scale_method" v="diameter"/>
          <prop k="size" v="3"/>
          <prop k="size_map_unit_scale" v="3x:0,0,0,0,0,0"/>
          <prop k="size_unit" v="MM"/>
          <prop k="vertical_anchor_point" v="1"/>
          <data_defined_properties>
            <Option type="Map">
              <Option value="" type="QString" name="name"/>
              <Option name="properties"/>
              <Option value="collection" type="QString" name="type"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
      <symbol force_rhr="0" clip_to_extent="1" type="marker" name="3" alpha="1">
        <data_defined_properties>
          <Option type="Map">
            <Option value="" type="QString" name="name"/>
            <Option name="properties"/>
            <Option value="collection" type="QString" name="type"/>
          </Option>
        </data_defined_properties>
        <layer class="SimpleMarker" locked="0" enabled="1" pass="0">
          <Option type="Map">
            <Option value="0" type="QString" name="angle"/>
            <Option value="square" type="QString" name="cap_style"/>
            <Option value="145,82,45,255" type="QString" name="color"/>
            <Option value="1" type="QString" name="horizontal_anchor_point"/>
            <Option value="bevel" type="QString" name="joinstyle"/>
            <Option value="circle" type="QString" name="name"/>
            <Option value="0,0" type="QString" name="offset"/>
            <Option value="3x:0,0,0,0,0,0" type="QString" name="offset_map_unit_scale"/>
            <Option value="MM" type="QString" name="offset_unit"/>
            <Option value="0,0,0,255" type="QString" name="outline_color"/>
            <Option value="solid" type="QString" name="outline_style"/>
            <Option value="0.2" type="QString" name="outline_width"/>
            <Option value="3x:0,0,0,0,0,0" type="QString" name="outline_width_map_unit_scale"/>
            <Option value="MM" type="QString" name="outline_width_unit"/>
            <Option value="diameter" type="QString" name="scale_method"/>
            <Option value="2" type="QString" name="size"/>
            <Option value="3x:0,0,0,0,0,0" type="QString" name="size_map_unit_scale"/>
            <Option value="MM" type="QString" name="size_unit"/>
            <Option value="1" type="QString" name="vertical_anchor_point"/>
          </Option>
          <prop k="angle" v="0"/>
          <prop k="cap_style" v="square"/>
          <prop k="color" v="145,82,45,255"/>
          <prop k="horizontal_anchor_point" v="1"/>
          <prop k="joinstyle" v="bevel"/>
          <prop k="name" v="circle"/>
          <prop k="offset" v="0,0"/>
          <prop k="offset_map_unit_scale" v="3x:0,0,0,0,0,0"/>
          <prop k="offset_unit" v="MM"/>
          <prop k="outline_color" v="0,0,0,255"/>
          <prop k="outline_style" v="solid"/>
          <prop k="outline_width" v="0.2"/>
          <prop k="outline_width_map_unit_scale" v="3x:0,0,0,0,0,0"/>
          <prop k="outline_width_unit" v="MM"/>
          <prop k="scale_method" v="diameter"/>
          <prop k="size" v="2"/>
          <prop k="size_map_unit_scale" v="3x:0,0,0,0,0,0"/>
          <prop k="size_unit" v="MM"/>
          <prop k="vertical_anchor_point" v="1"/>
          <data_defined_properties>
            <Option type="Map">
              <Option value="" type="QString" name="name"/>
              <Option name="properties"/>
              <Option value="collection" type="QString" name="type"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <labeling type="simple">
    <settings calloutType="simple">
      <text-style useSubstitutions="0" capitalization="0" fontSizeMapUnitScale="3x:0,0,0,0,0,0" legendString="Aa" fontKerning="1" fontSize="8" fontWordSpacing="0" allowHtml="0" namedStyle="Bold" previewBkgrdColor="255,255,255,255" fieldName="BSN" blendMode="0" fontLetterSpacing="0" isExpression="0" fontWeight="75" textColor="255,255,255,255" fontItalic="0" fontSizeUnit="Point" fontFamily="MS Shell Dlg 2" fontStrikeout="0" multilineHeight="1" textOpacity="1" fontUnderline="0" textOrientation="horizontal">
        <families/>
        <text-buffer bufferSize="0.40000000000000002" bufferColor="0,0,0,255" bufferJoinStyle="128" bufferSizeMapUnitScale="3x:0,0,0,0,0,0" bufferDraw="1" bufferNoFill="0" bufferOpacity="1" bufferSizeUnits="MM" bufferBlendMode="0"/>
        <text-mask maskJoinStyle="128" maskEnabled="0" maskSizeMapUnitScale="3x:0,0,0,0,0,0" maskSize="0" maskSizeUnits="MM" maskType="0" maskOpacity="1" maskedSymbolLayers=""/>
        <background shapeType="0" shapeRadiiY="0" shapeRadiiMapUnitScale="3x:0,0,0,0,0,0" shapeSizeY="0" shapeOpacity="1" shapeJoinStyle="64" shapeRadiiX="0" shapeDraw="0" shapeRotation="0" shapeBorderColor="128,128,128,255" shapeFillColor="255,255,255,255" shapeOffsetMapUnitScale="3x:0,0,0,0,0,0" shapeBorderWidthMapUnitScale="3x:0,0,0,0,0,0" shapeOffsetX="0" shapeOffsetY="0" shapeBorderWidth="0" shapeOffsetUnit="MM" shapeBlendMode="0" shapeSizeMapUnitScale="3x:0,0,0,0,0,0" shapeRotationType="0" shapeSizeType="0" shapeSizeX="0" shapeRadiiUnit="MM" shapeSVGFile="" shapeSizeUnit="MM" shapeBorderWidthUnit="MM">
          <symbol force_rhr="0" clip_to_extent="1" type="marker" name="markerSymbol" alpha="1">
            <data_defined_properties>
              <Option type="Map">
                <Option value="" type="QString" name="name"/>
                <Option name="properties"/>
                <Option value="collection" type="QString" name="type"/>
              </Option>
            </data_defined_properties>
            <layer class="SimpleMarker" locked="0" enabled="1" pass="0">
              <Option type="Map">
                <Option value="0" type="QString" name="angle"/>
                <Option value="square" type="QString" name="cap_style"/>
                <Option value="125,139,143,255" type="QString" name="color"/>
                <Option value="1" type="QString" name="horizontal_anchor_point"/>
                <Option value="bevel" type="QString" name="joinstyle"/>
                <Option value="circle" type="QString" name="name"/>
                <Option value="0,0" type="QString" name="offset"/>
                <Option value="3x:0,0,0,0,0,0" type="QString" name="offset_map_unit_scale"/>
                <Option value="MM" type="QString" name="offset_unit"/>
                <Option value="35,35,35,255" type="QString" name="outline_color"/>
                <Option value="solid" type="QString" name="outline_style"/>
                <Option value="0" type="QString" name="outline_width"/>
                <Option value="3x:0,0,0,0,0,0" type="QString" name="outline_width_map_unit_scale"/>
                <Option value="MM" type="QString" name="outline_width_unit"/>
                <Option value="diameter" type="QString" name="scale_method"/>
                <Option value="2" type="QString" name="size"/>
                <Option value="3x:0,0,0,0,0,0" type="QString" name="size_map_unit_scale"/>
                <Option value="MM" type="QString" name="size_unit"/>
                <Option value="1" type="QString" name="vertical_anchor_point"/>
              </Option>
              <prop k="angle" v="0"/>
              <prop k="cap_style" v="square"/>
              <prop k="color" v="125,139,143,255"/>
              <prop k="horizontal_anchor_point" v="1"/>
              <prop k="joinstyle" v="bevel"/>
              <prop k="name" v="circle"/>
              <prop k="offset" v="0,0"/>
              <prop k="offset_map_unit_scale" v="3x:0,0,0,0,0,0"/>
              <prop k="offset_unit" v="MM"/>
              <prop k="outline_color" v="35,35,35,255"/>
              <prop k="outline_style" v="solid"/>
              <prop k="outline_width" v="0"/>
              <prop k="outline_width_map_unit_scale" v="3x:0,0,0,0,0,0"/>
              <prop k="outline_width_unit" v="MM"/>
              <prop k="scale_method" v="diameter"/>
              <prop k="size" v="2"/>
              <prop k="size_map_unit_scale" v="3x:0,0,0,0,0,0"/>
              <prop k="size_unit" v="MM"/>
              <prop k="vertical_anchor_point" v="1"/>
              <data_defined_properties>
                <Option type="Map">
                  <Option value="" type="QString" name="name"/>
                  <Option name="properties"/>
                  <Option value="collection" type="QString" name="type"/>
                </Option>
              </data_defined_properties>
            </layer>
          </symbol>
          <symbol force_rhr="0" clip_to_extent="1" type="fill" name="fillSymbol" alpha="1">
            <data_defined_properties>
              <Option type="Map">
                <Option value="" type="QString" name="name"/>
                <Option name="properties"/>
                <Option value="collection" type="QString" name="type"/>
              </Option>
            </data_defined_properties>
            <layer class="SimpleFill" locked="0" enabled="1" pass="0">
              <Option type="Map">
                <Option value="3x:0,0,0,0,0,0" type="QString" name="border_width_map_unit_scale"/>
                <Option value="255,255,255,255" type="QString" name="color"/>
                <Option value="bevel" type="QString" name="joinstyle"/>
                <Option value="0,0" type="QString" name="offset"/>
                <Option value="3x:0,0,0,0,0,0" type="QString" name="offset_map_unit_scale"/>
                <Option value="MM" type="QString" name="offset_unit"/>
                <Option value="128,128,128,255" type="QString" name="outline_color"/>
                <Option value="no" type="QString" name="outline_style"/>
                <Option value="0" type="QString" name="outline_width"/>
                <Option value="Point" type="QString" name="outline_width_unit"/>
                <Option value="solid" type="QString" name="style"/>
              </Option>
              <prop k="border_width_map_unit_scale" v="3x:0,0,0,0,0,0"/>
              <prop k="color" v="255,255,255,255"/>
              <prop k="joinstyle" v="bevel"/>
              <prop k="offset" v="0,0"/>
              <prop k="offset_map_unit_scale" v="3x:0,0,0,0,0,0"/>
              <prop k="offset_unit" v="MM"/>
              <prop k="outline_color" v="128,128,128,255"/>
              <prop k="outline_style" v="no"/>
              <prop k="outline_width" v="0"/>
              <prop k="outline_width_unit" v="Point"/>
              <prop k="style" v="solid"/>
              <data_defined_properties>
                <Option type="Map">
                  <Option value="" type="QString" name="name"/>
                  <Option name="properties"/>
                  <Option value="collection" type="QString" name="type"/>
                </Option>
              </data_defined_properties>
            </layer>
          </symbol>
        </background>
        <shadow shadowUnder="0" shadowOffsetDist="1" shadowRadiusUnit="MM" shadowScale="100" shadowRadiusMapUnitScale="3x:0,0,0,0,0,0" shadowColor="0,0,0,255" shadowOffsetAngle="135" shadowOffsetMapUnitScale="3x:0,0,0,0,0,0" shadowRadiusAlphaOnly="0" shadowDraw="0" shadowOffsetGlobal="1" shadowBlendMode="6" shadowOpacity="0.69999999999999996" shadowOffsetUnit="MM" shadowRadius="1.5"/>
        <dd_properties>
          <Option type="Map">
            <Option value="" type="QString" name="name"/>
            <Option name="properties"/>
            <Option value="collection" type="QString" name="type"/>
          </Option>
        </dd_properties>
        <substitutions/>
      </text-style>
      <text-format autoWrapLength="0" rightDirectionSymbol=">" useMaxLineLengthForAutoWrap="0" placeDirectionSymbol="0" decimals="3" multilineAlign="3" leftDirectionSymbol="&lt;" plussign="0" addDirectionSymbol="0" reverseDirectionSymbol="0" wrapChar="" formatNumbers="0"/>
      <placement geometryGenerator="" predefinedPositionOrder="TR,TL,BR,BL,R,L,TSR,BSR" labelOffsetMapUnitScale="3x:0,0,0,0,0,0" layerType="PointGeometry" rotationAngle="0" repeatDistance="0" overrunDistanceMapUnitScale="3x:0,0,0,0,0,0" lineAnchorClipping="0" distMapUnitScale="3x:0,0,0,0,0,0" offsetUnits="MM" lineAnchorType="0" offsetType="0" yOffset="-3" distUnits="MM" maxCurvedCharAngleIn="25" lineAnchorPercent="0.5" geometryGeneratorType="PointGeometry" placement="1" priority="5" centroidInside="0" rotationUnit="AngleDegrees" repeatDistanceMapUnitScale="3x:0,0,0,0,0,0" geometryGeneratorEnabled="0" preserveRotation="1" dist="0" overrunDistanceUnit="MM" xOffset="0" polygonPlacementFlags="2" placementFlags="10" centroidWhole="0" quadOffset="1" repeatDistanceUnits="MM" fitInPolygonOnly="0" maxCurvedCharAngleOut="-25" overrunDistance="0"/>
      <rendering scaleVisibility="1" fontMinPixelSize="3" obstacleFactor="1" unplacedVisibility="0" fontMaxPixelSize="10000" zIndex="0" minFeatureSize="0" drawLabels="1" limitNumLabels="0" labelPerPart="0" maxNumLabels="2000" obstacle="0" scaleMax="5000" scaleMin="1" displayAll="0" upsidedownLabels="0" mergeLines="0" obstacleType="0" fontLimitPixelSize="0"/>
      <dd_properties>
        <Option type="Map">
          <Option value="" type="QString" name="name"/>
          <Option type="Map" name="properties">
            <Option type="Map" name="MultiLineWrapChar">
              <Option value="true" type="bool" name="active"/>
              <Option value="CASE WHEN length(&quot;NAME&quot;) &lt; 19  THEN '' ELSE ' ' END" type="QString" name="expression"/>
              <Option value="3" type="int" name="type"/>
            </Option>
            <Option type="Map" name="Show">
              <Option value="false" type="bool" name="active"/>
              <Option value="in_mask(4326)" type="QString" name="expression"/>
              <Option value="3" type="int" name="type"/>
            </Option>
          </Option>
          <Option value="collection" type="QString" name="type"/>
        </Option>
      </dd_properties>
      <callout type="simple">
        <Option type="Map">
          <Option value="pole_of_inaccessibility" type="QString" name="anchorPoint"/>
          <Option value="0" type="int" name="blendMode"/>
          <Option type="Map" name="ddProperties">
            <Option value="" type="QString" name="name"/>
            <Option name="properties"/>
            <Option value="collection" type="QString" name="type"/>
          </Option>
          <Option value="false" type="bool" name="drawToAllParts"/>
          <Option value="0" type="QString" name="enabled"/>
          <Option value="point_on_exterior" type="QString" name="labelAnchorPoint"/>
          <Option value="&lt;symbol force_rhr=&quot;0&quot; clip_to_extent=&quot;1&quot; type=&quot;line&quot; name=&quot;symbol&quot; alpha=&quot;1&quot;>&lt;data_defined_properties>&lt;Option type=&quot;Map&quot;>&lt;Option value=&quot;&quot; type=&quot;QString&quot; name=&quot;name&quot;/>&lt;Option name=&quot;properties&quot;/>&lt;Option value=&quot;collection&quot; type=&quot;QString&quot; name=&quot;type&quot;/>&lt;/Option>&lt;/data_defined_properties>&lt;layer class=&quot;SimpleLine&quot; locked=&quot;0&quot; enabled=&quot;1&quot; pass=&quot;0&quot;>&lt;Option type=&quot;Map&quot;>&lt;Option value=&quot;0&quot; type=&quot;QString&quot; name=&quot;align_dash_pattern&quot;/>&lt;Option value=&quot;square&quot; type=&quot;QString&quot; name=&quot;capstyle&quot;/>&lt;Option value=&quot;5;2&quot; type=&quot;QString&quot; name=&quot;customdash&quot;/>&lt;Option value=&quot;3x:0,0,0,0,0,0&quot; type=&quot;QString&quot; name=&quot;customdash_map_unit_scale&quot;/>&lt;Option value=&quot;MM&quot; type=&quot;QString&quot; name=&quot;customdash_unit&quot;/>&lt;Option value=&quot;0&quot; type=&quot;QString&quot; name=&quot;dash_pattern_offset&quot;/>&lt;Option value=&quot;3x:0,0,0,0,0,0&quot; type=&quot;QString&quot; name=&quot;dash_pattern_offset_map_unit_scale&quot;/>&lt;Option value=&quot;MM&quot; type=&quot;QString&quot; name=&quot;dash_pattern_offset_unit&quot;/>&lt;Option value=&quot;0&quot; type=&quot;QString&quot; name=&quot;draw_inside_polygon&quot;/>&lt;Option value=&quot;bevel&quot; type=&quot;QString&quot; name=&quot;joinstyle&quot;/>&lt;Option value=&quot;60,60,60,255&quot; type=&quot;QString&quot; name=&quot;line_color&quot;/>&lt;Option value=&quot;solid&quot; type=&quot;QString&quot; name=&quot;line_style&quot;/>&lt;Option value=&quot;0.3&quot; type=&quot;QString&quot; name=&quot;line_width&quot;/>&lt;Option value=&quot;MM&quot; type=&quot;QString&quot; name=&quot;line_width_unit&quot;/>&lt;Option value=&quot;0&quot; type=&quot;QString&quot; name=&quot;offset&quot;/>&lt;Option value=&quot;3x:0,0,0,0,0,0&quot; type=&quot;QString&quot; name=&quot;offset_map_unit_scale&quot;/>&lt;Option value=&quot;MM&quot; type=&quot;QString&quot; name=&quot;offset_unit&quot;/>&lt;Option value=&quot;0&quot; type=&quot;QString&quot; name=&quot;ring_filter&quot;/>&lt;Option value=&quot;0&quot; type=&quot;QString&quot; name=&quot;trim_distance_end&quot;/>&lt;Option value=&quot;3x:0,0,0,0,0,0&quot; type=&quot;QString&quot; name=&quot;trim_distance_end_map_unit_scale&quot;/>&lt;Option value=&quot;MM&quot; type=&quot;QString&quot; name=&quot;trim_distance_end_unit&quot;/>&lt;Option value=&quot;0&quot; type=&quot;QString&quot; name=&quot;trim_distance_start&quot;/>&lt;Option value=&quot;3x:0,0,0,0,0,0&quot; type=&quot;QString&quot; name=&quot;trim_distance_start_map_unit_scale&quot;/>&lt;Option value=&quot;MM&quot; type=&quot;QString&quot; name=&quot;trim_distance_start_unit&quot;/>&lt;Option value=&quot;0&quot; type=&quot;QString&quot; name=&quot;tweak_dash_pattern_on_corners&quot;/>&lt;Option value=&quot;0&quot; type=&quot;QString&quot; name=&quot;use_custom_dash&quot;/>&lt;Option value=&quot;3x:0,0,0,0,0,0&quot; type=&quot;QString&quot; name=&quot;width_map_unit_scale&quot;/>&lt;/Option>&lt;prop k=&quot;align_dash_pattern&quot; v=&quot;0&quot;/>&lt;prop k=&quot;capstyle&quot; v=&quot;square&quot;/>&lt;prop k=&quot;customdash&quot; v=&quot;5;2&quot;/>&lt;prop k=&quot;customdash_map_unit_scale&quot; v=&quot;3x:0,0,0,0,0,0&quot;/>&lt;prop k=&quot;customdash_unit&quot; v=&quot;MM&quot;/>&lt;prop k=&quot;dash_pattern_offset&quot; v=&quot;0&quot;/>&lt;prop k=&quot;dash_pattern_offset_map_unit_scale&quot; v=&quot;3x:0,0,0,0,0,0&quot;/>&lt;prop k=&quot;dash_pattern_offset_unit&quot; v=&quot;MM&quot;/>&lt;prop k=&quot;draw_inside_polygon&quot; v=&quot;0&quot;/>&lt;prop k=&quot;joinstyle&quot; v=&quot;bevel&quot;/>&lt;prop k=&quot;line_color&quot; v=&quot;60,60,60,255&quot;/>&lt;prop k=&quot;line_style&quot; v=&quot;solid&quot;/>&lt;prop k=&quot;line_width&quot; v=&quot;0.3&quot;/>&lt;prop k=&quot;line_width_unit&quot; v=&quot;MM&quot;/>&lt;prop k=&quot;offset&quot; v=&quot;0&quot;/>&lt;prop k=&quot;offset_map_unit_scale&quot; v=&quot;3x:0,0,0,0,0,0&quot;/>&lt;prop k=&quot;offset_unit&quot; v=&quot;MM&quot;/>&lt;prop k=&quot;ring_filter&quot; v=&quot;0&quot;/>&lt;prop k=&quot;trim_distance_end&quot; v=&quot;0&quot;/>&lt;prop k=&quot;trim_distance_end_map_unit_scale&quot; v=&quot;3x:0,0,0,0,0,0&quot;/>&lt;prop k=&quot;trim_distance_end_unit&quot; v=&quot;MM&quot;/>&lt;prop k=&quot;trim_distance_start&quot; v=&quot;0&quot;/>&lt;prop k=&quot;trim_distance_start_map_unit_scale&quot; v=&quot;3x:0,0,0,0,0,0&quot;/>&lt;prop k=&quot;trim_distance_start_unit&quot; v=&quot;MM&quot;/>&lt;prop k=&quot;tweak_dash_pattern_on_corners&quot; v=&quot;0&quot;/>&lt;prop k=&quot;use_custom_dash&quot; v=&quot;0&quot;/>&lt;prop k=&quot;width_map_unit_scale&quot; v=&quot;3x:0,0,0,0,0,0&quot;/>&lt;data_defined_properties>&lt;Option type=&quot;Map&quot;>&lt;Option value=&quot;&quot; type=&quot;QString&quot; name=&quot;name&quot;/>&lt;Option name=&quot;properties&quot;/>&lt;Option value=&quot;collection&quot; type=&quot;QString&quot; name=&quot;type&quot;/>&lt;/Option>&lt;/data_defined_properties>&lt;/layer>&lt;/symbol>" type="QString" name="lineSymbol"/>
          <Option value="0" type="double" name="minLength"/>
          <Option value="3x:0,0,0,0,0,0" type="QString" name="minLengthMapUnitScale"/>
          <Option value="MM" type="QString" name="minLengthUnit"/>
          <Option value="0" type="double" name="offsetFromAnchor"/>
          <Option value="3x:0,0,0,0,0,0" type="QString" name="offsetFromAnchorMapUnitScale"/>
          <Option value="MM" type="QString" name="offsetFromAnchorUnit"/>
          <Option value="0" type="double" name="offsetFromLabel"/>
          <Option value="3x:0,0,0,0,0,0" type="QString" name="offsetFromLabelMapUnitScale"/>
          <Option value="MM" type="QString" name="offsetFromLabelUnit"/>
        </Option>
      </callout>
    </settings>
  </labeling>
  <customproperties>
    <Option type="Map">
      <Option value="offline" type="QString" name="QFieldSync/action"/>
      <Option value="{}" type="QString" name="QFieldSync/attachment_naming"/>
      <Option value="offline" type="QString" name="QFieldSync/cloud_action"/>
      <Option value="" type="QString" name="QFieldSync/geometry_locked_expression"/>
      <Option value="{}" type="QString" name="QFieldSync/photo_naming"/>
      <Option value="{}" type="QString" name="QFieldSync/relationship_maximum_visible"/>
      <Option value="81300082029000_bldgpts_268bac5b_d065_4428_aadd_955a79f5c26b" type="QString" name="QFieldSync/remoteLayerId"/>
      <Option value="" type="QString" name="QFieldSync/sourceDataPrimaryKeys"/>
      <Option type="List" name="dualview/previewExpressions">
        <Option value="COALESCE(&quot;Bldg Name&quot;, '&lt;NULL>')" type="QString"/>
      </Option>
      <Option value="0" type="QString" name="embeddedWidgets/count"/>
      <Option value="true" type="bool" name="isOfflineEditable"/>
      <Option value="" type="QString" name="layerNameSuffix"/>
      <Option value="81300082029000_bldgpts_268bac5b_d065_4428_aadd_955a79f5c26b" type="QString" name="remoteLayerId"/>
      <Option value="ogr" type="QString" name="remoteProvider"/>
      <Option value="C:/PSA-GIS/Temporary files/Mini-Pretest/New folder/81300082029000_bldgpts.shp" type="QString" name="remoteSource"/>
      <Option name="variableNames"/>
      <Option name="variableValues"/>
    </Option>
  </customproperties>
  <blendMode>0</blendMode>
  <featureBlendMode>0</featureBlendMode>
  <layerOpacity>1</layerOpacity>
  <SingleCategoryDiagramRenderer attributeLegend="1" diagramType="Histogram">
    <DiagramCategory opacity="1" backgroundColor="#ffffff" barWidth="5" lineSizeScale="3x:0,0,0,0,0,0" spacing="0" scaleBasedVisibility="0" height="15" labelPlacementMethod="XHeight" minimumSize="0" penAlpha="255" penWidth="0" sizeType="MM" width="15" maxScaleDenominator="1e+08" spacingUnit="MM" rotationOffset="270" enabled="0" lineSizeType="MM" spacingUnitScale="3x:0,0,0,0,0,0" backgroundAlpha="255" penColor="#000000" showAxis="0" direction="1" scaleDependency="Area" diagramOrientation="Up" sizeScale="3x:0,0,0,0,0,0" minScaleDenominator="100000">
      <fontProperties style="" description="MS Shell Dlg 2,7.5,-1,5,50,0,0,0,0,0"/>
      <attribute label="" color="#000000" field="" colorOpacity="1"/>
      <axisSymbol>
        <symbol force_rhr="0" clip_to_extent="1" type="line" name="" alpha="1">
          <data_defined_properties>
            <Option type="Map">
              <Option value="" type="QString" name="name"/>
              <Option name="properties"/>
              <Option value="collection" type="QString" name="type"/>
            </Option>
          </data_defined_properties>
          <layer class="SimpleLine" locked="0" enabled="1" pass="0">
            <Option type="Map">
              <Option value="0" type="QString" name="align_dash_pattern"/>
              <Option value="square" type="QString" name="capstyle"/>
              <Option value="5;2" type="QString" name="customdash"/>
              <Option value="3x:0,0,0,0,0,0" type="QString" name="customdash_map_unit_scale"/>
              <Option value="MM" type="QString" name="customdash_unit"/>
              <Option value="0" type="QString" name="dash_pattern_offset"/>
              <Option value="3x:0,0,0,0,0,0" type="QString" name="dash_pattern_offset_map_unit_scale"/>
              <Option value="MM" type="QString" name="dash_pattern_offset_unit"/>
              <Option value="0" type="QString" name="draw_inside_polygon"/>
              <Option value="bevel" type="QString" name="joinstyle"/>
              <Option value="35,35,35,255" type="QString" name="line_color"/>
              <Option value="solid" type="QString" name="line_style"/>
              <Option value="0.26" type="QString" name="line_width"/>
              <Option value="MM" type="QString" name="line_width_unit"/>
              <Option value="0" type="QString" name="offset"/>
              <Option value="3x:0,0,0,0,0,0" type="QString" name="offset_map_unit_scale"/>
              <Option value="MM" type="QString" name="offset_unit"/>
              <Option value="0" type="QString" name="ring_filter"/>
              <Option value="0" type="QString" name="trim_distance_end"/>
              <Option value="3x:0,0,0,0,0,0" type="QString" name="trim_distance_end_map_unit_scale"/>
              <Option value="MM" type="QString" name="trim_distance_end_unit"/>
              <Option value="0" type="QString" name="trim_distance_start"/>
              <Option value="3x:0,0,0,0,0,0" type="QString" name="trim_distance_start_map_unit_scale"/>
              <Option value="MM" type="QString" name="trim_distance_start_unit"/>
              <Option value="0" type="QString" name="tweak_dash_pattern_on_corners"/>
              <Option value="0" type="QString" name="use_custom_dash"/>
              <Option value="3x:0,0,0,0,0,0" type="QString" name="width_map_unit_scale"/>
            </Option>
            <prop k="align_dash_pattern" v="0"/>
            <prop k="capstyle" v="square"/>
            <prop k="customdash" v="5;2"/>
            <prop k="customdash_map_unit_scale" v="3x:0,0,0,0,0,0"/>
            <prop k="customdash_unit" v="MM"/>
            <prop k="dash_pattern_offset" v="0"/>
            <prop k="dash_pattern_offset_map_unit_scale" v="3x:0,0,0,0,0,0"/>
            <prop k="dash_pattern_offset_unit" v="MM"/>
            <prop k="draw_inside_polygon" v="0"/>
            <prop k="joinstyle" v="bevel"/>
            <prop k="line_color" v="35,35,35,255"/>
            <prop k="line_style" v="solid"/>
            <prop k="line_width" v="0.26"/>
            <prop k="line_width_unit" v="MM"/>
            <prop k="offset" v="0"/>
            <prop k="offset_map_unit_scale" v="3x:0,0,0,0,0,0"/>
            <prop k="offset_unit" v="MM"/>
            <prop k="ring_filter" v="0"/>
            <prop k="trim_distance_end" v="0"/>
            <prop k="trim_distance_end_map_unit_scale" v="3x:0,0,0,0,0,0"/>
            <prop k="trim_distance_end_unit" v="MM"/>
            <prop k="trim_distance_start" v="0"/>
            <prop k="trim_distance_start_map_unit_scale" v="3x:0,0,0,0,0,0"/>
            <prop k="trim_distance_start_unit" v="MM"/>
            <prop k="tweak_dash_pattern_on_corners" v="0"/>
            <prop k="use_custom_dash" v="0"/>
            <prop k="width_map_unit_scale" v="3x:0,0,0,0,0,0"/>
            <data_defined_properties>
              <Option type="Map">
                <Option value="" type="QString" name="name"/>
                <Option name="properties"/>
                <Option value="collection" type="QString" name="type"/>
              </Option>
            </data_defined_properties>
          </layer>
        </symbol>
      </axisSymbol>
    </DiagramCategory>
  </SingleCategoryDiagramRenderer>
  <DiagramLayerSettings obstacle="0" zIndex="0" priority="0" showAll="1" placement="0" dist="0" linePlacementFlags="2">
    <properties>
      <Option type="Map">
        <Option value="" type="QString" name="name"/>
        <Option name="properties"/>
        <Option value="collection" type="QString" name="type"/>
      </Option>
    </properties>
  </DiagramLayerSettings>
  <geometryOptions removeDuplicateNodes="0" geometryPrecision="0">
    <activeChecks/>
    <checkConfiguration/>
  </geometryOptions>
  <legend type="default-vector" showLabelLegend="0"/>
  <referencedLayers/>
  <fieldConfiguration>
    <field configurationFlags="None" name="fid_1">
      <editWidget type="Hidden">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="fid">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="Address">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="Bldg Name">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="Bldg Type">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="Bldg Form">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="No of Flr">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="Roof Type">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="Wall Type">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="Popcen BSN">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="HH Head">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="IS Ind">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="Remarks">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="Bldg Image">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="Geoid">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="Geocode">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="GeoBSN">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="coord">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="update">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="valid_ind">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="comments">
      <editWidget type="TextEdit">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="None" name="BSN">
      <editWidget type="TextEdit">
        <config>
          <Option type="Map">
            <Option value="false" type="bool" name="IsMultiline"/>
            <Option value="false" type="bool" name="UseHtml"/>
          </Option>
        </config>
      </editWidget>
    </field>
  </fieldConfiguration>
  <aliases>
    <alias index="0" name="" field="fid_1"/>
    <alias index="1" name="" field="fid"/>
    <alias index="2" name="" field="Address"/>
    <alias index="3" name="" field="Bldg Name"/>
    <alias index="4" name="" field="Bldg Type"/>
    <alias index="5" name="" field="Bldg Form"/>
    <alias index="6" name="" field="No of Flr"/>
    <alias index="7" name="" field="Roof Type"/>
    <alias index="8" name="" field="Wall Type"/>
    <alias index="9" name="" field="Popcen BSN"/>
    <alias index="10" name="" field="HH Head"/>
    <alias index="11" name="" field="IS Ind"/>
    <alias index="12" name="" field="Remarks"/>
    <alias index="13" name="" field="Bldg Image"/>
    <alias index="14" name="" field="Geoid"/>
    <alias index="15" name="" field="Geocode"/>
    <alias index="16" name="" field="GeoBSN"/>
    <alias index="17" name="" field="coord"/>
    <alias index="18" name="" field="update"/>
    <alias index="19" name="" field="valid_ind"/>
    <alias index="20" name="" field="comments"/>
    <alias index="21" name="" field="BSN"/>
  </aliases>
  <defaults>
    <default expression="" applyOnUpdate="0" field="fid_1"/>
    <default expression="" applyOnUpdate="0" field="fid"/>
    <default expression="" applyOnUpdate="0" field="Address"/>
    <default expression="" applyOnUpdate="0" field="Bldg Name"/>
    <default expression="" applyOnUpdate="0" field="Bldg Type"/>
    <default expression="" applyOnUpdate="0" field="Bldg Form"/>
    <default expression="" applyOnUpdate="0" field="No of Flr"/>
    <default expression="" applyOnUpdate="0" field="Roof Type"/>
    <default expression="" applyOnUpdate="0" field="Wall Type"/>
    <default expression="" applyOnUpdate="0" field="Popcen BSN"/>
    <default expression="" applyOnUpdate="0" field="HH Head"/>
    <default expression="" applyOnUpdate="0" field="IS Ind"/>
    <default expression="" applyOnUpdate="0" field="Remarks"/>
    <default expression="" applyOnUpdate="0" field="Bldg Image"/>
    <default expression="" applyOnUpdate="0" field="Geoid"/>
    <default expression="" applyOnUpdate="0" field="Geocode"/>
    <default expression="" applyOnUpdate="0" field="GeoBSN"/>
    <default expression="" applyOnUpdate="0" field="coord"/>
    <default expression="" applyOnUpdate="0" field="update"/>
    <default expression="" applyOnUpdate="0" field="valid_ind"/>
    <default expression="" applyOnUpdate="0" field="comments"/>
    <default expression="" applyOnUpdate="0" field="BSN"/>
  </defaults>
  <constraints>
    <constraint constraints="3" notnull_strength="1" unique_strength="1" exp_strength="0" field="fid_1"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="fid"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="Address"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="Bldg Name"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="Bldg Type"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="Bldg Form"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="No of Flr"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="Roof Type"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="Wall Type"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="Popcen BSN"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="HH Head"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="IS Ind"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="Remarks"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="Bldg Image"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="Geoid"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="Geocode"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="GeoBSN"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="coord"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="update"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="valid_ind"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="comments"/>
    <constraint constraints="0" notnull_strength="0" unique_strength="0" exp_strength="0" field="BSN"/>
  </constraints>
  <constraintExpressions>
    <constraint desc="" exp="" field="fid_1"/>
    <constraint desc="" exp="" field="fid"/>
    <constraint desc="" exp="" field="Address"/>
    <constraint desc="" exp="" field="Bldg Name"/>
    <constraint desc="" exp="" field="Bldg Type"/>
    <constraint desc="" exp="" field="Bldg Form"/>
    <constraint desc="" exp="" field="No of Flr"/>
    <constraint desc="" exp="" field="Roof Type"/>
    <constraint desc="" exp="" field="Wall Type"/>
    <constraint desc="" exp="" field="Popcen BSN"/>
    <constraint desc="" exp="" field="HH Head"/>
    <constraint desc="" exp="" field="IS Ind"/>
    <constraint desc="" exp="" field="Remarks"/>
    <constraint desc="" exp="" field="Bldg Image"/>
    <constraint desc="" exp="" field="Geoid"/>
    <constraint desc="" exp="" field="Geocode"/>
    <constraint desc="" exp="" field="GeoBSN"/>
    <constraint desc="" exp="" field="coord"/>
    <constraint desc="" exp="" field="update"/>
    <constraint desc="" exp="" field="valid_ind"/>
    <constraint desc="" exp="" field="comments"/>
    <constraint desc="" exp="" field="BSN"/>
  </constraintExpressions>
  <expressionfields/>
  <attributeactions>
    <defaultAction key="Canvas" value="{00000000-0000-0000-0000-000000000000}"/>
  </attributeactions>
  <attributetableconfig sortOrder="0" actionWidgetStyle="dropDown" sortExpression="&quot;BSN&quot;">
    <columns>
      <column type="field" name="BSN" hidden="0" width="-1"/>
      <column type="actions" hidden="1" width="-1"/>
      <column type="field" name="Geocode" hidden="0" width="-1"/>
      <column type="field" name="Roof Type" hidden="0" width="-1"/>
      <column type="field" name="Wall Type" hidden="0" width="-1"/>
      <column type="field" name="Popcen BSN" hidden="0" width="-1"/>
      <column type="field" name="HH Head" hidden="0" width="-1"/>
      <column type="field" name="IS Ind" hidden="0" width="-1"/>
      <column type="field" name="Remarks" hidden="0" width="-1"/>
      <column type="field" name="Bldg Image" hidden="0" width="-1"/>
      <column type="field" name="Geoid" hidden="0" width="-1"/>
      <column type="field" name="GeoBSN" hidden="0" width="-1"/>
      <column type="field" name="coord" hidden="0" width="-1"/>
      <column type="field" name="update" hidden="0" width="-1"/>
      <column type="field" name="valid_ind" hidden="0" width="-1"/>
      <column type="field" name="fid_1" hidden="0" width="-1"/>
      <column type="field" name="fid" hidden="0" width="-1"/>
      <column type="field" name="Address" hidden="0" width="-1"/>
      <column type="field" name="Bldg Name" hidden="0" width="-1"/>
      <column type="field" name="Bldg Type" hidden="0" width="-1"/>
      <column type="field" name="Bldg Form" hidden="0" width="-1"/>
      <column type="field" name="No of Flr" hidden="0" width="-1"/>
      <column type="field" name="comments" hidden="0" width="-1"/>
    </columns>
  </attributetableconfig>
  <conditionalstyles>
    <rowstyles/>
    <fieldstyles/>
  </conditionalstyles>
  <storedexpressions/>
  <editform tolerant="1">D:/Documents/GMD files/Manuals/2024 Compilation of process/PSA-GIS/Province/CBMS/2024/2. Qfield Projects/Province/CBMS/2024/Form 2/2024 Compilation of process/PSA-GIS/Province/Users/CBarrientos/Documents</editform>
  <editforminit/>
  <editforminitcodesource>0</editforminitcodesource>
  <editforminitfilepath>D:/Documents/GMD files/Manuals/2024 Compilation of process/PSA-GIS/Province/CBMS/2024/2. Qfield Projects/Province/CBMS/2024/Form 2/2024 Compilation of process/PSA-GIS/Province/Users/CBarrientos/Documents</editforminitfilepath>
  <editforminitcode><![CDATA[# -*- coding: utf-8 -*-
"""
QGIS forms can have a Python function that is called when the form is
opened.

Use this function to add extra logic to your forms.

Enter the name of the function in the "Python Init function"
field.
An example follows:
"""
from qgis.PyQt.QtWidgets import QWidget

def my_form_open(dialog, layer, feature):
	geom = feature.geometry()
	control = dialog.findChild(QWidget, "MyLineEdit")
]]></editforminitcode>
  <featformsuppress>0</featformsuppress>
  <editorlayout>generatedlayout</editorlayout>
  <editable>
    <field editable="1" name="Address"/>
    <field editable="1" name="BSN"/>
    <field editable="1" name="Bldg Form"/>
    <field editable="1" name="Bldg Image"/>
    <field editable="1" name="Bldg Name"/>
    <field editable="1" name="Bldg Type"/>
    <field editable="1" name="GeoBSN"/>
    <field editable="1" name="Geocode"/>
    <field editable="1" name="Geoid"/>
    <field editable="1" name="HH Head"/>
    <field editable="1" name="IS Ind"/>
    <field editable="1" name="No of Flr"/>
    <field editable="1" name="Popcen BSN"/>
    <field editable="1" name="Remarks"/>
    <field editable="1" name="Roof Type"/>
    <field editable="1" name="Wall Type"/>
    <field editable="1" name="comments"/>
    <field editable="1" name="coord"/>
    <field editable="1" name="fid"/>
    <field editable="1" name="fid_1"/>
    <field editable="1" name="update"/>
    <field editable="1" name="valid_ind"/>
  </editable>
  <labelOnTop>
    <field labelOnTop="0" name="Address"/>
    <field labelOnTop="0" name="BSN"/>
    <field labelOnTop="0" name="Bldg Form"/>
    <field labelOnTop="0" name="Bldg Image"/>
    <field labelOnTop="0" name="Bldg Name"/>
    <field labelOnTop="0" name="Bldg Type"/>
    <field labelOnTop="0" name="GeoBSN"/>
    <field labelOnTop="0" name="Geocode"/>
    <field labelOnTop="0" name="Geoid"/>
    <field labelOnTop="0" name="HH Head"/>
    <field labelOnTop="0" name="IS Ind"/>
    <field labelOnTop="0" name="No of Flr"/>
    <field labelOnTop="0" name="Popcen BSN"/>
    <field labelOnTop="0" name="Remarks"/>
    <field labelOnTop="0" name="Roof Type"/>
    <field labelOnTop="0" name="Wall Type"/>
    <field labelOnTop="0" name="comments"/>
    <field labelOnTop="0" name="coord"/>
    <field labelOnTop="0" name="fid"/>
    <field labelOnTop="0" name="fid_1"/>
    <field labelOnTop="0" name="update"/>
    <field labelOnTop="0" name="valid_ind"/>
  </labelOnTop>
  <reuseLastValue>
    <field reuseLastValue="0" name="Address"/>
    <field reuseLastValue="0" name="BSN"/>
    <field reuseLastValue="0" name="Bldg Form"/>
    <field reuseLastValue="0" name="Bldg Image"/>
    <field reuseLastValue="0" name="Bldg Name"/>
    <field reuseLastValue="0" name="Bldg Type"/>
    <field reuseLastValue="0" name="GeoBSN"/>
    <field reuseLastValue="0" name="Geocode"/>
    <field reuseLastValue="0" name="Geoid"/>
    <field reuseLastValue="0" name="HH Head"/>
    <field reuseLastValue="0" name="IS Ind"/>
    <field reuseLastValue="0" name="No of Flr"/>
    <field reuseLastValue="0" name="Popcen BSN"/>
    <field reuseLastValue="0" name="Remarks"/>
    <field reuseLastValue="0" name="Roof Type"/>
    <field reuseLastValue="0" name="Wall Type"/>
    <field reuseLastValue="0" name="comments"/>
    <field reuseLastValue="0" name="coord"/>
    <field reuseLastValue="0" name="fid"/>
    <field reuseLastValue="0" name="fid_1"/>
    <field reuseLastValue="0" name="update"/>
    <field reuseLastValue="0" name="valid_ind"/>
  </reuseLastValue>
  <dataDefinedFieldProperties/>
  <widgets/>
  <previewExpression>COALESCE("Bldg Name", '&lt;NULL>')</previewExpression>
  <mapTip></mapTip>
  <layerGeometryType>0</layerGeometryType>
</qgis>
