"""Simplify public-domain Natural Earth land geometry for the local SVG map."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = json.loads((root / 'outputs/natural-earth-land.geojson').read_text('utf-8'))
polygons = []
for feature in source['features']:
    geom = feature['geometry']
    rings = [geom['coordinates']] if geom['type'] == 'Polygon' else geom['coordinates']
    for polygon in rings:
        # Three decimal places preserve much more detail than the prototype's grid.
        exterior = [[round(lon, 3), round(lat, 3)] for lon, lat, *_ in polygon[0]]
        xs, ys = zip(*exterior)
        polygons.append({'bounds': [min(xs), min(ys), max(xs), max(ys)], 'ring': exterior})
result = {'source': 'Natural Earth 1:50m land', 'license': 'Public domain',
          'url': 'https://www.naturalearthdata.com/about/terms-of-use/', 'polygons': polygons}
target = root / 'frontend/weather-public/land-50m.json'
target.write_text(json.dumps(result, separators=(',', ':')), encoding='utf-8')
print(f'{len(polygons)} polygons; {target.stat().st_size} bytes')
