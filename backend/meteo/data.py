from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

VARIABLES = {
    't2m': {'label': '2 米气温', 'unit': '°C', 'limits': [-90, 60]},
    'u10': {'label': '东西风分量', 'unit': 'm/s', 'limits': [-100, 100]},
    'v10': {'label': '南北风分量', 'unit': 'm/s', 'limits': [-100, 100]},
    'rh': {'label': '相对湿度', 'unit': '%', 'limits': [0, 100]},
    'precip': {'label': '小时降水', 'unit': 'mm', 'limits': [0, 300]},
    'msl': {'label': '海平面气压', 'unit': 'hPa', 'limits': [850, 1100]},
}
CHANNELS = list(VARIABLES)
HISTORY = 12
HORIZON = 24


def iso(value):
    return pd.Timestamp(value).isoformat() + 'Z'


def demo_dataset(hours=480, size=16):
    """Synthetic weather for software verification, never observational evidence."""
    now = pd.Timestamp(datetime.now(timezone.utc)).tz_localize(None).floor('h')
    time = pd.date_range(end=now, periods=hours, freq='h')
    lat = np.linspace(27, 35, size)
    lon = np.linspace(116, 124, size)
    t, y, x = np.meshgrid(np.arange(hours), lat, lon, indexing='ij')
    phase = 2 * np.pi * t / 24
    rain = 30 * np.exp(-((x - 119.5 - 1.4 * np.sin(t / 20)) ** 2 + (y - 31) ** 2) / 1.8)
    rain *= (0.5 + 0.5 * np.sin(t / 13)) ** 3
    values = [29 + 6 * np.sin(phase - 1) - .45 * (y - 30) + np.sin(x),
              6 + 7 * np.sin(t / 30 + y / 3), 5 + 7 * np.cos(t / 25 + x / 4),
              65 - 12 * np.sin(phase) + rain / 2,
              rain, 1011 + 6 * np.cos(t / 40) - rain / 5 + (x - 120) * .5]
    ds = xr.Dataset({k: (('time', 'lat', 'lon'), v.astype('float32')) for k, v in zip(CHANNELS, values)},
                    coords={'time': time, 'lat': lat, 'lon': lon})
    for k, spec in VARIABLES.items():
        ds[k].attrs['units'] = spec['unit']
    ds.attrs.update(source='synthetic', note='人工合成数据，仅用于软件流程验证，不代表真实观测或业务预报')
    return ds


def prepare(ds: xr.Dataset, grid_size=None):
    ds = ds.rename({a: b for a, b in {'latitude': 'lat', 'longitude': 'lon', 'valid_time': 'time',
                                     'tp': 'precip', 'r': 'rh', 'mslp': 'msl'}.items()
                    if a in ds and b not in ds})
    missing = [k for k in CHANNELS + ['time', 'lat', 'lon'] if k not in ds]
    if missing:
        raise ValueError('缺少变量或坐标：' + ', '.join(missing))
    if any(ds[k].dims != (k,) for k in ('time', 'lat', 'lon')):
        raise ValueError('time、lat、lon 必须是一维规则网格坐标')
    if any(set(ds[k].dims) != {'time', 'lat', 'lon'} for k in CHANNELS):
        raise ValueError('每个气象变量必须且仅具有 time、lat、lon 三个维度')
    if ds.sizes['time'] < HISTORY or not all(4 <= ds.sizes[k] <= 512 for k in ('lat', 'lon')):
        raise ValueError('至少需要 12 个逐小时时刻；经纬度网格边长须为 4–512')
    if ds.sizes['time'] * ds.sizes['lat'] * ds.sizes['lon'] * 6 > 30_000_000:
        raise ValueError('原型单批最多 3000 万个数值，请先裁剪区域或时间')
    if not np.issubdtype(ds.time.dtype, np.datetime64):
        raise ValueError('time 必须为可解码的日期时间，不能是普通数字')
    ds = ds[CHANNELS].sortby(['time', 'lat', 'lon']).transpose('time', 'lat', 'lon').load()
    for coord in ('lat', 'lon'):
        axis = ds[coord].values
        if not np.isfinite(axis).all() or np.any(np.diff(axis) <= 0):
            raise ValueError('经纬度坐标必须有限且不重复')
    if float(ds.lat.min()) < -90 or float(ds.lat.max()) > 90 or float(ds.lon.min()) < -180 or float(ds.lon.max()) > 180:
        raise ValueError('坐标范围须为纬度 -90–90、经度 -180–180；请先转换 0–360 经度')
    if np.isnat(ds.time.values).any() or not np.all(np.diff(ds.time.values) == np.timedelta64(1, 'h')):
        raise ValueError('时间必须无重复且连续逐小时；请先补齐缺失时刻并以 NaN 标记')
    notes = []
    for k in CHANNELS:
        unit = str(ds[k].attrs.get('units', '')).strip().lower()
        v = ds[k].astype('float32')
        if k == 't2m' and unit in ('k', 'kelvin'):
            v = v - 273.15
            notes.append('温度 K → °C')
        elif k == 'msl' and unit in ('pa', 'pascal'):
            v = v / 100
            notes.append('气压 Pa → hPa')
        elif k == 'precip' and unit in ('m', 'meter', 'metres'):
            v = v * 1000
            notes.append('逐小时降水 m → mm；输入须已解累计')
        elif k == 'rh' and unit in ('1', 'fraction'):
            v = v * 100
        accepted = {'t2m': ('°c', 'c', 'degc', 'celsius', 'k', 'kelvin'),
                    'u10': ('m/s', 'm s-1', 'm s**-1'), 'v10': ('m/s', 'm s-1', 'm s**-1'),
                    'rh': ('%', 'percent', '1', 'fraction'), 'precip': ('mm', 'm', 'meter', 'metres'),
                    'msl': ('hpa', 'pa', 'pascal', 'mbar')}
        if unit not in accepted[k]:
            raise ValueError(f'{k} 的 units 缺失或不支持：{unit}；请使用 {VARIABLES[k]["unit"]}')
        if np.isinf(v.values).any():
            raise ValueError(f'{k} 包含无穷值')
        fraction = float(v.isnull().mean())
        if fraction > .05:
            raise ValueError(f'{k} 缺失比例 {fraction:.1%} 超过 5%，拒绝自动填充')
        if fraction:
            # Split before filling to avoid leaking validation/test observations.
            n = len(v.time)
            boundaries = (0, int(n * .7), int(n * .85), n)
            parts = [v.isel(time=slice(a, b)).interpolate_na(dim='time', method='linear', max_gap=np.timedelta64(4, 'h'))
                     for a, b in zip(boundaries[:-1], boundaries[1:])]
            v = xr.concat(parts, dim='time')
            if bool(v.isnull().any()):
                raise ValueError(f'{k} 存在边界缺失或连续缺失超过 3 小时，无法可靠填充')
            notes.append(f'{k} 分区内插值填充 {fraction:.2%} 缺失值')
        lo, hi = VARIABLES[k]['limits']
        if bool(((v < lo) | (v > hi)).any()):
            raise ValueError(f'{k} 超出原型支持范围 [{lo}, {hi}]，请核对单位及累计方式')
        ds[k] = v
        ds[k].attrs['units'] = VARIABLES[k]['unit']
    if grid_size:
        ds = ds.interp(lat=np.linspace(float(ds.lat.min()), float(ds.lat.max()), grid_size),
                       lon=np.linspace(float(ds.lon.min()), float(ds.lon.max()), grid_size))
        notes.append(f'双线性空间重采样至 {grid_size} × {grid_size}')
    return ds.astype('float32'), notes


def tensor_data(ds):
    return np.stack([ds[k].values for k in CHANNELS], axis=1).astype('float32')


def split_info(n):
    a, b = int(n * .7), int(n * .85)
    return {'train': [0, a], 'validation': [a, b], 'test': [b, n]}


def summary(ds, notes):
    return {'hours': ds.sizes['time'], 'shape': [ds.sizes['lat'], ds.sizes['lon']],
            'start': iso(ds.time.values[0]), 'end': iso(ds.time.values[-1]),
            'bounds': [float(ds.lon.min()), float(ds.lat.min()), float(ds.lon.max()), float(ds.lat.max())],
            'variables': CHANNELS, 'notes': notes, 'splits': split_info(ds.sizes['time']),
            'trainable': min(b - a for a, b in split_info(ds.sizes['time']).values()) >= HISTORY + HORIZON}


def constrain(values):
    out = np.array(values, copy=True)
    for i, spec in enumerate(VARIABLES.values()):
        out[..., i, :, :] = np.clip(out[..., i, :, :], *spec['limits'])
    if not np.isfinite(out).all():
        raise ValueError('模型产生非有限数值，预报未发布')
    return out


def save_grid(ds, path: Path):
    ds = ds.drop_encoding()
    ds.to_zarr(path, mode='w', encoding={k: {'chunks': (min(24, ds.sizes['time']), ds.sizes['lat'], ds.sizes['lon'])}
                                       for k in ds.data_vars if ds[k].dims == ('time', 'lat', 'lon')})


def read_grid(path: Path):
    return xr.open_zarr(path, chunks=None)
