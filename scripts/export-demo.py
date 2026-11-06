"""Export one reviewed synthetic forecast for the public, read-only demo.

Uses read-only HTTP endpoints; never copies databases, credentials or model files.
Run while the local FastAPI service is running.
"""
import argparse
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import urllib.request

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--forecast-id', required=True)
    parser.add_argument('--api', default='http://127.0.0.1:8016/api')
    parser.add_argument('--output', type=Path, default=ROOT / 'frontend/demo-public/demo')
    args = parser.parse_args()
    def get(path):
        with urllib.request.urlopen(args.api + path, timeout=60) as response:
            return response.read()
    def read(path):
        return json.loads(get(path))
    overview = read('/overview')
    forecast = next(f for f in overview['forecasts'] if f['id'] == args.forecast_id)
    dataset = next(d for d in overview['datasets'] if d['id'] == forecast['dataset_id'])
    jobs = [j for j in overview['jobs'] if j['id'] == forecast['model_id']]
    if any(x['source'] != 'synthetic' for x in [forecast, dataset, *jobs]):
        raise RuntimeError('Only synthetic data may be exported by this public-demo script.')
    if any(j['status'] != 'completed' for j in jobs):
        raise RuntimeError('Only completed training records may be exported.')
    out = args.output
    (out / 'images').mkdir(parents=True, exist_ok=True)
    content = get('/forecast/download?forecast_id=' + forecast['id'])
    (out / 'forecast.nc').write_bytes(content)
    (out / 'dataset.nc').write_bytes(get('/datasets/' + dataset['id'] + '/download'))
    with xr.open_dataset(BytesIO(content), engine='scipy') as ds:
        fields = {k: np.round(v.values.astype(float), 6).tolist() for k, v in ds.data_vars.items()}
        data = {'lat': ds.lat.values.tolist(), 'lon': ds.lon.values.tolist(),
            'times': [np.datetime_as_string(t, unit='s') + 'Z' for t in ds.time.values],
            'fields': fields, 'units': {k: v.attrs.get('units', '') for k, v in ds.data_vars.items()},
            'scales': {k: [float(v.min()), float(v.max())] for k, v in ds.data_vars.items()}}
    overview.update(datasets=[dataset], forecasts=[forecast], jobs=jobs)
    warnings = read('/warning/list?active_only=false&forecast_id=' + forecast['id'])
    snapshot = {'version': 1, 'kind': 'synthetic-read-only',
        'exported_at': datetime.now(timezone.utc).isoformat(),
        'overview': overview, 'health': read('/health'), 'warnings': warnings, 'data': data}
    # Keep only public health fields, excluding potential local runtime details.
    snapshot['health'] = {k: snapshot['health'][k] for k in ['variables', 'model_available']}
    (out / 'snapshot.json').write_text(json.dumps(snapshot, ensure_ascii=False, allow_nan=False, separators=(',', ':')), encoding='utf-8')
    for variable in ['t2m', 'precip', 'wind', 'rh', 'msl']:
        for lead in range(1, 25):
            image = get(f'/forecast/image?forecast_id={forecast["id"]}&variable={variable}&lead={lead}')
            (out / 'images' / f'{variable}-{lead}h.png').write_bytes(image)
        print(f'Exported 24 {variable} images', flush=True)
    print(json.dumps({'forecast': forecast['id'], 'files': len(list(out.rglob('*'))),
        'bytes': sum(p.stat().st_size for p in out.rglob('*') if p.is_file())}))

if __name__ == '__main__':
    main()
