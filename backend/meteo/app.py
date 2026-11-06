import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from importlib.util import find_spec
from pathlib import Path
from typing import Literal

import numpy as np
import xarray as xr
from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .data import VARIABLES, demo_dataset, iso, prepare, read_grid, save_grid, summary
from .forecast import field_image, run_forecast
from .store import Store, now


class Login(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class Demo(BaseModel):
    name: str = Field(default='华东区域 · 合成演示数据', min_length=1, max_length=80)


class Training(BaseModel):
    dataset_id: str
    epochs: int = Field(default=3, ge=3, le=60)
    samples: int = Field(default=16, ge=2, le=128)


class Prediction(BaseModel):
    dataset_id: str
    engine: Literal['persistence', 'meteoformer'] = 'persistence'
    members: int = Field(default=1, ge=1, le=8)
    model_id: str | None = None


class Thresholds(BaseModel):
    precip: float = Field(ge=1, le=300, allow_inf_nan=False)
    wind: float = Field(ge=1, le=100, allow_inf_nan=False)
    temperature: float = Field(ge=20, le=60, allow_inf_nan=False)


def create_app(data_root=None, admin_password=None):
    root = Path(data_root or os.getenv('METEO_DATA_DIR', Path(__file__).resolve().parents[1] / 'data'))
    store = Store(root, recover_jobs=True)
    password = admin_password or os.getenv('METEO_ADMIN_PASSWORD')
    if not password:
        password_file = root / 'initial-admin-password.txt'
        if not password_file.exists():
            password_file.write_text(secrets.token_urlsafe(18), encoding='utf-8')
            try:
                password_file.chmod(0o600)
            except OSError:
                pass
        password = password_file.read_text(encoding='utf-8').strip()
    salt = secrets.token_bytes(16)
    password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 200_000)
    sessions, attempts = {}, defaultdict(deque)
    auth_lock, workload = threading.Lock(), threading.Lock()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='meteo-train')

    @asynccontextmanager
    async def lifespan(app):
        yield
        executor.shutdown(wait=True)

    app = FastAPI(title='MeteoFormer 区域气象预测系统', version='1.0.0', lifespan=lifespan)
    app.state.store = store

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=422, content={'detail': str(exc)})

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={'detail': '记录不存在或已失效'})

    def admin(meteo_session: str | None = Cookie(default=None)):
        with auth_lock:
            if sessions.get(meteo_session, 0) <= time.time():
                raise HTTPException(401, '请先进入管理员模式')
        return True

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'service': 'meteo', 'model_available': find_spec('torch') is not None,
                'storage': 'SQLite + Zarr', 'variables': VARIABLES, 'prototype': True}

    @app.post('/api/auth/login')
    def login(body: Login, request: Request, response: Response):
        address = request.client.host if request.client else 'local'
        with auth_lock:
            cutoff = time.time() - 300
            for key in list(attempts):
                while attempts[key] and attempts[key][0] < cutoff:
                    attempts[key].popleft()
                if not attempts[key]:
                    del attempts[key]
            if len(attempts[address]) >= 10:
                raise HTTPException(429, '尝试过于频繁，请 5 分钟后重试')
            attempts[address].append(time.time())
        digest = hashlib.pbkdf2_hmac('sha256', body.password.encode(), salt, 200_000)
        if not hmac.compare_digest(digest, password_hash):
            raise HTTPException(401, '管理员密码不正确')
        token = secrets.token_urlsafe(32)
        with auth_lock:
            for key in list(sessions):
                if sessions[key] < time.time():
                    del sessions[key]
            if len(sessions) >= 32:
                sessions.pop(next(iter(sessions)))
            sessions[token] = time.time() + 7200
            attempts.pop(address, None)
        response.set_cookie('meteo_session', token, httponly=True, samesite='strict', max_age=7200,
                            secure=os.getenv('METEO_SECURE_COOKIE', '0') == '1')
        return {'role': 'admin'}

    @app.get('/api/auth/session')
    def session(meteo_session: str | None = Cookie(default=None)):
        with auth_lock:
            return {'role': 'admin' if sessions.get(meteo_session, 0) > time.time() else 'viewer'}

    @app.post('/api/auth/logout')
    def logout(response: Response, meteo_session: str | None = Cookie(default=None)):
        with auth_lock:
            sessions.pop(meteo_session, None)
        response.delete_cookie('meteo_session')
        return {'role': 'viewer'}

    def ready_forecasts():
        return [f for f in store.list('forecast') if f['status'] == 'ready']

    @app.get('/api/overview')
    def overview():
        return {'datasets': store.list('dataset'), 'forecasts': ready_forecasts(), 'jobs': store.list('job'),
                'thresholds': store.get('thresholds'), 'server_time': now()}

    @app.get('/api/datasets')
    def datasets():
        return store.list('dataset')

    def add_dataset(ds, name, source, grid_size=None):
        if ds.attrs.get('source') == 'synthetic':
            source = 'synthetic'
        cleaned, notes = prepare(ds, grid_size)
        key = secrets.token_hex(16)
        save_grid(cleaned, root / 'datasets' / (key + '.zarr'))
        return store.add('dataset', {'name': name, 'source': source, **summary(cleaned, notes)}, key=key)

    @app.post('/api/datasets/demo', dependencies=[Depends(admin)])
    def demo(body: Demo):
        return add_dataset(demo_dataset(), body.name, 'synthetic')

    @app.post('/api/datasets/import', dependencies=[Depends(admin)])
    async def import_dataset(file: UploadFile = File(...), source: Literal['ERA5', 'GFS', 'other'] = Form('ERA5'),
                             grid_size: int = Form(16), hourly_precipitation: bool = Form(False)):
        if grid_size not in (16, 32, 64):
            raise HTTPException(422, '目标网格只能选择 16、32 或 64')
        if not hourly_precipitation:
            raise HTTPException(422, '请确认降水为逐小时增量；ERA5/GFS 累计降水须先解累计')
        if not file.filename or Path(file.filename).suffix.lower() not in ('.nc', '.netcdf'):
            raise HTTPException(422, '仅支持 NetCDF .nc/.netcdf 文件')
        target = root / 'incoming' / (secrets.token_hex(16) + '.nc')
        try:
            total = 0
            with target.open('wb') as output:
                while chunk := await file.read(1024 * 1024):
                    total += len(chunk)
                    if total > 100 * 1024 * 1024:
                        raise HTTPException(413, '文件不能超过 100 MB')
                    output.write(chunk)
            def process():
                try:
                    with xr.open_dataset(target) as ds:
                        return add_dataset(ds, Path(file.filename).name[:80], source, grid_size)
                except (OSError, TypeError) as exc:
                    raise ValueError('无法读取 NetCDF，请检查格式和变量维度') from exc
            return await run_in_threadpool(process)
        finally:
            target.unlink(missing_ok=True)
            await file.close()

    @app.get('/api/datasets/{key}/download')
    def dataset_download(key: str):
        store.get(key, 'dataset')
        with read_grid(root / 'datasets' / (key + '.zarr')) as ds:
            content = bytes(ds.to_netcdf(engine='scipy'))
        return Response(content, media_type='application/x-netcdf', headers={'Content-Disposition': f'attachment; filename="dataset-{key}.nc"'})

    @app.post('/api/train/start', dependencies=[Depends(admin)], status_code=202)
    def start_training(body: Training):
        dataset = store.get(body.dataset_id, 'dataset')
        if not find_spec('torch'):
            raise HTTPException(503, '尚未安装 PyTorch，请安装 requirements-model.txt 后重试')
        if not dataset['trainable']:
            raise HTTPException(422, '数据不足以构建独立训练、验证、测试窗口；建议至少 240 小时')
        if not workload.acquire(blocking=False):
            raise HTTPException(409, '正在训练或推理，请等待当前任务完成')
        try:
            job = store.add('job', {'dataset_id': dataset['id'], 'dataset_name': dataset['name'], 'source': dataset['source'],
                         'status': 'queued', 'epochs': body.epochs, 'samples': body.samples, 'epoch': 0,
                         'progress': 0, 'logs': [], 'message': '等待训练启动'})
            def task():
                try:
                    from .training import train
                    train(store, job['id'], dataset, body.epochs, body.samples)
                finally:
                    workload.release()
            executor.submit(task)
            return job
        except Exception:
            workload.release()
            raise

    @app.get('/api/train/status')
    def training_status(job_id: str | None = None):
        return store.get(job_id, 'job') if job_id else store.list('job')

    @app.post('/api/predict', dependencies=[Depends(admin)], status_code=201)
    def predict(body: Prediction):
        dataset = store.get(body.dataset_id, 'dataset')
        if body.engine == 'meteoformer':
            if not find_spec('torch'):
                raise HTTPException(503, '尚未安装 PyTorch')
            if not body.model_id:
                raise HTTPException(409, '请先训练模型并选择权重')
            job = store.get(body.model_id, 'job')
            if job['status'] != 'completed' or not (root / 'models' / (job['id'] + '.pt')).is_file():
                raise HTTPException(409, '模型权重缺失或尚未训练完成')
            from .training import validate_model_dataset
            validate_model_dataset(store, job, dataset)
        elif body.members != 1:
            raise HTTPException(422, '持续性基线只支持确定性预报，集合扰动仅适用于模型')
        if not workload.acquire(blocking=False):
            raise HTTPException(409, '正在训练或推理，请等待当前任务完成')
        try:
            return run_forecast(store, dataset, body.engine, body.members, body.model_id)
        finally:
            workload.release()

    def forecast_record(key=None, init_time=None):
        forecasts = ready_forecasts()
        if key:
            record = store.get(key, 'forecast')
            if record['status'] != 'ready':
                raise HTTPException(409, '预报尚未就绪')
            return record
        if init_time:
            import pandas as pd
            target = pd.Timestamp(init_time)
            target = target.tz_localize('UTC') if target.tzinfo is None else target.tz_convert('UTC')
            forecasts = [f for f in forecasts if pd.Timestamp(f['init_time']) == target]
        if not forecasts:
            raise HTTPException(404, '暂无匹配预报，请先生成预报')
        return forecasts[0]

    @app.get('/api/forecasts')
    def forecasts():
        return ready_forecasts()

    @app.get('/api/forecast/grid')
    def grid(forecast_id: str | None = None, variable: Literal['t2m', 'rh', 'precip', 'msl', 'wind'] = 't2m',
             lead: int = Query(1, ge=1, le=24)):
        item = forecast_record(forecast_id)
        with read_grid(root / 'forecasts' / (item['id'] + '.zarr')) as ds:
            layer = ds[variable].isel(time=lead-1)
            return {'forecast': item, 'variable': variable, 'unit': layer.attrs.get('units', ''),
                    'valid_time': iso(ds.time.values[lead-1]), 'lat': ds.lat.values.tolist(), 'lon': ds.lon.values.tolist(),
                    'values': layer.values.tolist(), 'min': float(layer.min()), 'max': float(layer.max()),
                    'scale_min': float(ds[variable].min()), 'scale_max': float(ds[variable].max())}

    @app.get('/api/point')
    def point(lon: float = Query(ge=-180, le=180, allow_inf_nan=False), lat: float = Query(ge=-90, le=90, allow_inf_nan=False),
              forecast_id: str | None = None, init_time: str | None = None):
        item = forecast_record(forecast_id, init_time)
        with read_grid(root / 'forecasts' / (item['id'] + '.zarr')) as ds:
            if not (float(ds.lon.min()) <= lon <= float(ds.lon.max()) and float(ds.lat.min()) <= lat <= float(ds.lat.max())):
                raise HTTPException(422, '查询点超出当前预报覆盖范围')
            pt = ds.sel(lon=lon, lat=lat, method='nearest')
            rows = [{'time': iso(t), 'lead': i + 1, **{k: round(float(pt[k].values[i]), 3) for k in ds.data_vars}}
                    for i, t in enumerate(ds.time.values)]
            return {'forecast': item, 'requested': {'lon': lon, 'lat': lat},
                    'grid_point': {'lon': float(pt.lon), 'lat': float(pt.lat)}, 'interpolation': 'nearest', 'hourly': rows}

    @app.get('/api/forecast/image')
    def image(forecast_id: str | None = None, variable: Literal['t2m', 'rh', 'precip', 'msl', 'wind'] = 't2m',
              lead: int = Query(1, ge=1, le=24)):
        item = forecast_record(forecast_id)
        with read_grid(root / 'forecasts' / (item['id'] + '.zarr')) as ds:
            content = field_image(ds, variable, lead)
        return Response(content, media_type='image/png', headers={'Content-Disposition': f'attachment; filename="{variable}-{lead}h.png"'})

    @app.get('/api/forecast/download')
    def download(forecast_id: str):
        item = forecast_record(forecast_id)
        with read_grid(root / 'forecasts' / (item['id'] + '.zarr')) as ds:
            content = bytes(ds.to_netcdf(engine='scipy'))
        return Response(content, media_type='application/x-netcdf', headers={'Content-Disposition': f'attachment; filename="forecast-{forecast_id}.nc"'})

    @app.get('/api/warning/list')
    def warnings(active_only: bool = True, forecast_id: str | None = None):
        ready_ids = {f['id'] for f in ready_forecasts()}
        items = [w for w in store.list('warning') if w['forecast_id'] in ready_ids]
        import pandas as pd
        for w in items:
            w['expired'] = pd.Timestamp(w['valid_end']) < pd.Timestamp.now(tz='UTC')
        return [w for w in items if (not active_only or not w['expired']) and (not forecast_id or w['forecast_id'] == forecast_id)]

    @app.post('/api/warning/{key}/acknowledge', dependencies=[Depends(admin)])
    def acknowledge(key: str):
        store.get(key, 'warning')
        return store.update(key, acknowledged=True)

    @app.get('/api/warning/thresholds')
    def thresholds():
        return store.get('thresholds')

    @app.put('/api/warning/thresholds', dependencies=[Depends(admin)])
    def save_thresholds(body: Thresholds):
        return store.update('thresholds', **body.model_dump())

    frontend = Path(__file__).resolve().parents[2] / 'frontend' / 'weather-dist'
    if frontend.is_dir():
        app.mount('/', StaticFiles(directory=frontend, html=True), name='frontend')
    return app


app = create_app()
