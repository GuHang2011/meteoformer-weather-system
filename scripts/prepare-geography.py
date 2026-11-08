"""Prepare attributed, offline geographic assets from reviewed public sources.

Requires Pillow. Use --download to fetch source files; otherwise reuse outputs/.
"""
from pathlib import Path
import argparse
import hashlib
import json
import urllib.request

from PIL import Image, ImageEnhance, ImageOps

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT / ('frontend' if (ROOT / 'frontend').exists() else 'frontend')
CACHE = ROOT / 'outputs'
TARGET = FRONT / 'weather-public/geography'
BOUNDS = [100, 15, 140, 45]  # west, south, east, north (EPSG:4326)
SOURCES = {
    'relief': 'https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=BlueMarble_ShadedRelief_Bathymetry&STYLES=&CRS=EPSG:4326&BBOX=15,100,45,140&WIDTH=2048&HEIGHT=1536&FORMAT=image/jpeg',
    'rivers': 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_rivers_lake_centerlines.geojson',
    'lakes': 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_lakes.geojson',
}
FILES = {'relief': 'material-east-asia-relief.jpg', 'rivers': 'material-rivers.geojson', 'lakes': 'material-lakes.geojson'}


def bounds(lines):
    points = [point for line in lines for point in line]
    xs, ys = zip(*points)
    return [min(xs), min(ys), max(xs), max(ys)]


def intersects(box):
    return box[2] >= BOUNDS[0] and box[0] <= BOUNDS[2] and box[3] >= BOUNDS[1] and box[1] <= BOUNDS[3]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    CACHE.mkdir(exist_ok=True)
    TARGET.mkdir(parents=True, exist_ok=True)
    if args.download:
        for key, url in SOURCES.items():
            with urllib.request.urlopen(url, timeout=60) as response:
                (CACHE / FILES[key]).write_bytes(response.read())

    # Fixed geographic crop: no weather observations, cloud overlay, or live data.
    with Image.open(CACHE / FILES['relief']) as image:
        assert image.size == (2048, 1536)
        grayscale = ImageEnhance.Contrast(ImageOps.grayscale(image)).enhance(1.35)
        dark = ImageOps.colorize(grayscale, '#10212e', '#8ea0a8')
        dark.save(TARGET / 'east-asia-relief.webp', quality=90, method=6)

    result = {'bounds': BOUNDS, 'rivers': [], 'lakes': []}
    for kind in ['rivers', 'lakes']:
        source = json.loads((CACHE / FILES[kind]).read_text('utf-8'))
        for feature in source['features']:
            geometry, props = feature['geometry'], feature['properties']
            if not geometry or props.get('scalerank', 99) > (6 if kind == 'rivers' else 5):
                continue
            coords, geo_type = geometry['coordinates'], geometry['type']
            if geo_type == 'LineString':
                groups = [[coords]]
            elif geo_type in ['MultiLineString', 'Polygon']:
                groups = [coords]
            elif geo_type == 'MultiPolygon':
                groups = coords
            else:
                continue
            for lines in groups:
                lines = [[[round(lon, 4), round(lat, 4)] for lon, lat, *_ in line] for line in lines if line]
                if not lines:
                    continue
                box = bounds(lines)
                if intersects(box):
                    result[kind].append({'name': props.get('name_en') or props.get('name', ''), 'bounds': box, 'lines': lines})
    (TARGET / 'east-asia-water.json').write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    manifest = {
        'bounds': BOUNDS, 'crs': 'EPSG:4326', 'retrieved': '2026-11-08',
        'imagery': {'source': 'NASA GIBS / Blue Marble Shaded Relief and Bathymetry',
                    'type': 'static geographic background; not current satellite weather imagery',
                    'processing': 'grayscale, contrast 1.35, dark blue-gray tint, WebP compression',
                    'usage_guidelines': 'https://www.nasa.gov/nasa-brand-center/images-and-media/'},
        'water': {'source': 'Natural Earth 1:10m rivers and lakes', 'license': 'Public domain',
                  'processing': 'East Asia feature selection; four-decimal coordinates; scale-rank filtering',
                  'terms': 'https://www.naturalearthdata.com/about/terms-of-use/'},
        'downloads': {key: {'url': url, 'sha256': hashlib.sha256((CACHE / FILES[key]).read_bytes()).hexdigest()} for key, url in SOURCES.items()},
    }
    (TARGET / 'sources.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({'rivers': len(result['rivers']), 'lakes': len(result['lakes']),
                      'assets': {p.name: p.stat().st_size for p in TARGET.iterdir()}}))


if __name__ == '__main__':
    main()
