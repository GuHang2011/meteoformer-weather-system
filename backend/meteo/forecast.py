from datetime import datetime, timezone
from io import BytesIO
from threading import Lock

import numpy as np
import pandas as pd
import xarray as xr

from .data import CHANNELS, VARIABLES, constrain, iso, read_grid, save_grid, tensor_data

plot_lock = Lock()


def run_forecast(store, dataset, engine, members, model_id=None):
    with read_grid(store.root / 'datasets' / (dataset['id'] + '.zarr')) as source:
        source = source.isel(time=slice(-12, None)).load()
    raw = tensor_data(source)
    if engine == 'meteoformer':
        from .training import infer
        ensemble = infer(store.root / 'models' / (model_id + '.pt'), raw, members)
        label = 'MeteoFormer 小型原型 + MOS'
    else:
        ensemble = np.repeat(raw[-1:][None], 24, axis=1)
        label = '持续性基线（保持最新观测值）'
    mean = constrain(ensemble.mean(axis=0))
    times = pd.date_range(pd.Timestamp(source.time.values[-1]) + pd.Timedelta(hours=1), periods=24, freq='h')
    ds = xr.Dataset({k: (('time', 'lat', 'lon'), mean[:, i]) for i, k in enumerate(CHANNELS)},
                    coords={'time': times, 'lat': source.lat, 'lon': source.lon})
    ds['wind'] = np.hypot(ds.u10, ds.v10)
    ds['wind_direction'] = (270 - np.rad2deg(np.arctan2(ds.v10, ds.u10))) % 360
    if ensemble.shape[0] > 1:
        ds['rain_probability'] = (('time', 'lat', 'lon'), (ensemble[:, :, 4] >= 1).mean(axis=0) * 100)
        ds['temperature_p10'] = (('time', 'lat', 'lon'), np.quantile(ensemble[:, :, 0], .1, axis=0))
        ds['temperature_p90'] = (('time', 'lat', 'lon'), np.quantile(ensemble[:, :, 0], .9, axis=0))
        ds['rain_probability'].attrs.update(units='%', description='Uncalibrated ensemble frequency of hourly precipitation >= 1 mm')
        ds['temperature_p10'].attrs['units'] = 'degC'
        ds['temperature_p90'].attrs['units'] = 'degC'
    for k, info in VARIABLES.items():
        ds[k].attrs['units'] = info['unit']
    ds['wind'].attrs['units'] = 'm/s'
    ds['wind_direction'].attrs['units'] = 'degree'
    ds.attrs.update(engine=engine, source=dataset['source'], init_time=iso(source.time.values[-1]),
                    note='Research prototype; not an official weather forecast', ensemble_members=ensemble.shape[0])
    item = store.add('forecast', {'dataset_id': dataset['id'], 'dataset_name': dataset['name'],
                                 'source': dataset['source'], 'engine': engine, 'engine_label': label,
                                 'model_id': model_id, 'members': ensemble.shape[0], 'init_time': ds.attrs['init_time'],
                                 'valid_start': iso(times[0]), 'valid_end': iso(times[-1]), 'hours': 24,
                                 'shape': [ds.sizes['lat'], ds.sizes['lon']], 'status': 'preparing',
                                 'bounds': dataset['bounds'],
                                 'summary': {'temperature_min': float(ds.t2m.min()), 'temperature_max': float(ds.t2m.max()),
                                             'rain_max': float(ds.precip.max()), 'wind_max': float(ds.wind.max())}})
    try:
        save_grid(ds, store.root / 'forecasts' / (item['id'] + '.zarr'))
        thresholds = store.get('thresholds')
        warnings = []
        for key, variable, title in [('precip', 'precip', '短时强降水'), ('wind', 'wind', '大风'), ('temperature', 't2m', '高温')]:
            values = ds[variable].values
            mask = values >= thresholds[key]
            if not mask.any():
                continue
            ti, yi, xi = np.unravel_index(np.argmax(values), values.shape)
            active_steps = np.where(mask.any(axis=(1, 2)))[0]
            warnings.append(store.add('warning', {'forecast_id': item['id'], 'type': key, 'title': title,
                         'source': dataset['source'], 'engine': engine, 'threshold': thresholds[key],
                         'peak': float(values[ti, yi, xi]), 'unit': 'mm/h' if key == 'precip' else 'm/s' if key == 'wind' else '°C',
                         'lon': float(ds.lon[xi]), 'lat': float(ds.lat[yi]), 'peak_time': iso(times[ti]),
                         'valid_start': iso(times[active_steps[0]]), 'valid_end': iso(times[active_steps[-1]]),
                         'affected_cells': int(mask.any(axis=0).sum()), 'acknowledged': False}))
        return store.update(item['id'], status='ready', warning_count=len(warnings))
    except Exception:
        store.update(item['id'], status='failed')
        raise


def field_image(ds, variable, lead):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    from matplotlib.colors import LinearSegmentedColormap
    palettes = {
        't2m': ['#344f91', '#358bad', '#67bcaf', '#b5cf83', '#e9cd6c', '#e69852', '#cb5651'],
        'precip': ['#153247', '#234d68', '#367e9c', '#4eb6b5', '#a7d6a0', '#e5d366', '#d17b52'],
        'wind': ['#273a66', '#4865a1', '#4ca3b0', '#7fc6ad', '#d7d18c', '#e39a65', '#c66480'],
        'rh': ['#4e3a49', '#8f6964', '#c5a68d', '#bfd3c1', '#6eadaf', '#357a9b', '#264b7d'],
        'msl': ['#405789', '#6b93ab', '#a0bfc3', '#e2dcc2', '#d5b58b', '#b68070', '#8b535e'],
    }
    with plot_lock:
        fig = Figure(figsize=(10, 6), dpi=130, facecolor='#f4f7f7')
        ax = fig.subplots()
        layer = ds[variable].isel(time=lead - 1)
        artist = ax.pcolormesh(ds.lon, ds.lat, layer, shading='auto',
                              cmap=LinearSegmentedColormap.from_list(variable, palettes[variable]),
                              vmin=float(ds[variable].min()), vmax=float(ds[variable].max()))
        ax.set(xlabel='Longitude (degrees E)', ylabel='Latitude (degrees N)',
               title=f'{variable} | +{lead:02d} h | {iso(ds.time.values[lead - 1])}\n{ds.attrs["engine"]} / {ds.attrs["source"]}')
        ax.grid(alpha=.2)
        fig.colorbar(artist, ax=ax, label=layer.attrs.get('units', ''))
        fig.tight_layout()
        stream = BytesIO()
        fig.savefig(stream, format='png')
        return stream.getvalue()
