from io import BytesIO
import time

import numpy as np
import pytest
import xarray as xr
from fastapi.testclient import TestClient

from meteo.app import create_app
from meteo.data import demo_dataset, prepare, read_grid, save_grid, split_info
from meteo.store import Store


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, admin_password='test-password')) as client:
        yield client


def login(client):
    response = client.post('/api/auth/login', json={'password': 'test-password'})
    assert response.status_code == 200
    assert 'HttpOnly' in response.headers['set-cookie']


def demo(client):
    response = client.post('/api/datasets/demo', json={})
    assert response.status_code == 200, response.text
    return response.json()


def test_permissions_and_logout(client):
    assert client.get('/api/health').json()['status'] == 'ok'
    assert client.post('/api/datasets/demo', json={}).status_code == 401
    assert client.post('/api/train/start', json={'dataset_id': 'none'}).status_code == 401
    assert client.post('/api/auth/login', json={'password': 'wrong'}).status_code == 401
    login(client)
    assert client.get('/api/auth/session').json()['role'] == 'admin'
    client.post('/api/auth/logout')
    assert client.put('/api/warning/thresholds', json={'precip': 20, 'wind': 17, 'temperature': 35}).status_code == 401


def test_full_persistence_workflow(client):
    login(client)
    data = demo(client)
    assert data['source'] == 'synthetic'
    assert data['trainable'] and data['hours'] == 480
    # Inclusive thresholds should trigger all three weather types.
    path = client.app.state.store.root / 'datasets' / (data['id'] + '.zarr')
    with read_grid(path) as original:
        ds = original.load().copy(deep=True)
    ds.t2m.values[-1] = 35
    ds.u10.values[-1] = 17
    ds.v10.values[-1] = 0
    ds.precip.values[-1] = 20
    save_grid(ds, path)
    response = client.post('/api/predict', json={'dataset_id': data['id']})
    assert response.status_code == 201, response.text
    forecast = response.json()
    assert forecast['hours'] == 24 and forecast['warning_count'] == 3
    point = client.get('/api/point', params={'lon': 120.5, 'lat': 31.5, 'forecast_id': forecast['id']}).json()
    assert len(point['hourly']) == 24
    assert point['hourly'][0]['t2m'] == point['hourly'][-1]['t2m']
    assert 'rain_probability' not in point['hourly'][0]
    assert client.get('/api/point', params={'lon': 0, 'lat': 0}).status_code == 422
    assert client.get('/api/point', params={'lon': 'nan', 'lat': 30}).status_code == 422
    assert client.get('/api/point', params={'lon': 120, 'lat': 30, 'init_time': forecast['init_time']}).status_code == 200
    assert client.get('/api/point', params={'lon': 120, 'lat': 30, 'init_time': '2000-01-01'}).status_code == 404
    assert client.get('/api/forecast/grid', params={'lead': 25}).status_code == 422
    grid = client.get('/api/forecast/grid', params={'forecast_id': forecast['id'], 'variable': 'wind', 'lead': 24}).json()
    assert len(grid['values']) == 16
    assert grid['unit'] == 'm/s'
    warnings = client.get('/api/warning/list').json()
    assert len(warnings) == 3
    assert client.post(f'/api/warning/{warnings[0]["id"]}/acknowledge').json()['acknowledged']
    image = client.get('/api/forecast/image', params={'forecast_id': forecast['id']})
    assert image.status_code == 200 and image.content.startswith(b'\x89PNG')
    exported = client.get('/api/forecast/download', params={'forecast_id': forecast['id']})
    with xr.open_dataset(BytesIO(exported.content), engine='scipy') as nc:
        assert nc.sizes['time'] == 24
        assert nc.attrs['source'] == 'synthetic'
        assert set(['t2m', 'wind', 'msl', 'precip']).issubset(nc.data_vars)
    exported = client.get(f'/api/datasets/{data["id"]}/download')
    with xr.open_dataset(BytesIO(exported.content), engine='scipy') as nc:
        assert nc.sizes['time'] == 480
    assert client.get('/api/forecast/download', params={'forecast_id': '../anywhere'}).status_code == 404
    missing = client.post('/api/predict', json={'dataset_id': data['id'], 'engine': 'meteoformer'})
    assert missing.status_code in (409, 503)
    assert client.post('/api/predict', json={'dataset_id': data['id'], 'members': 2}).status_code == 422


def test_import_and_bad_input(client):
    login(client)
    ds = demo_dataset(hours=240)
    ds.t2m.values[:] += 273.15
    ds.t2m.attrs['units'] = 'K'
    nc = bytes(ds.to_netcdf(engine='scipy'))
    options = {'source': 'ERA5', 'grid_size': 16, 'hourly_precipitation': 'true'}
    response = client.post('/api/datasets/import', files={'file': ('weather.nc', nc)}, data=options)
    assert response.status_code == 200, response.text
    assert any('K' in n for n in response.json()['notes'])
    assert response.json()['trainable']
    bad = client.post('/api/datasets/import', files={'file': ('weather.nc', nc)})
    assert bad.status_code == 422
    bad = client.post('/api/datasets/import', files={'file': ('bad.nc', b'not-netcdf')}, data=options)
    assert bad.status_code == 422
    assert not list((client.app.state.store.root / 'incoming').iterdir())


def test_missing_value_filling_and_time_integrity():
    ds = demo_dataset(hours=240)
    ds.t2m.values[20, 0, 0] = np.nan
    result, notes = prepare(ds)
    assert np.isfinite(result.t2m).all()
    assert notes
    # Interpolation must never cross the training/validation boundary.
    ds.t2m.values[168, 0, 0] = np.nan
    with pytest.raises(ValueError, match='缺失'):
        prepare(ds)
    bad = demo_dataset(hours=24)
    bad = bad.assign_coords(time=np.arange(24))
    with pytest.raises(ValueError, match='time'):
        prepare(bad)
    bad = demo_dataset(hours=24).isel(time=[0, 0] + list(range(2, 24)))
    with pytest.raises(ValueError, match='时间'):
        prepare(bad)
    bad = demo_dataset(hours=24)
    bad.rh.values[:] = 200
    with pytest.raises(ValueError, match='范围'):
        prepare(bad)


def test_restart_marks_jobs_interrupted(tmp_path):
    store = Store(tmp_path)
    job = store.add('job', {'status': 'running'})
    restarted = Store(tmp_path, recover_jobs=True)
    assert restarted.get(job['id'])['status'] == 'interrupted'


def test_real_model_training_and_inference(client):
    pytest.importorskip('torch')
    login(client)
    data = demo(client)
    response = client.post('/api/train/start', json={'dataset_id': data['id'], 'epochs': 3, 'samples': 2})
    assert response.status_code == 202, response.text
    job_id = response.json()['id']
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        job = client.get('/api/train/status', params={'job_id': job_id}).json()
        if job['status'] not in ('queued', 'running'):
            break
        time.sleep(.2)
    assert job['status'] == 'completed', job
    assert [log['horizon'] for log in job['logs']] == [1, 6, 24]
    assert job['metrics']['test_windows'] == 4
    for start in job['metrics']['test_starts']:
        assert start >= split_info(480)['test'][0] and start + 36 <= 480
    assert (client.app.state.store.root / 'models' / (job_id + '.pt')).is_file()
    response = client.post('/api/predict', json={'dataset_id': data['id'], 'engine': 'meteoformer', 'model_id': job_id, 'members': 2})
    assert response.status_code == 201, response.text
    forecast = response.json()
    point = client.get('/api/point', params={'lon': 120, 'lat': 30, 'forecast_id': forecast['id']}).json()
    assert len(point['hourly']) == 24
    assert all(0 <= r['rain_probability'] <= 100 and 0 <= r['rh'] <= 100 and r['precip'] >= 0 for r in point['hourly'])
    assert all(r['temperature_p10'] <= r['temperature_p90'] for r in point['hourly'])
    # A trained model should also forecast newly supplied initial fields on its exact grid.
    recent = demo_dataset(hours=12)
    recent = recent.assign_coords(time=recent.time.values + np.timedelta64(48, 'h'))
    options = {'source': 'other', 'grid_size': 16, 'hourly_precipitation': 'true'}
    imported = client.post('/api/datasets/import', files={'file': ('recent.nc', bytes(recent.to_netcdf(engine='scipy')))}, data=options)
    assert imported.status_code == 200, imported.text
    assert imported.json()['source'] == 'synthetic'
    predicted = client.post('/api/predict', json={'dataset_id': imported.json()['id'], 'engine': 'meteoformer', 'model_id': job_id})
    assert predicted.status_code == 201, predicted.text
    recent = recent.assign_coords(lon=recent.lon + 1)
    shifted = client.post('/api/datasets/import', files={'file': ('shifted.nc', bytes(recent.to_netcdf(engine='scipy')))}, data=options).json()
    rejected = client.post('/api/predict', json={'dataset_id': shifted['id'], 'engine': 'meteoformer', 'model_id': job_id})
    assert rejected.status_code == 422
