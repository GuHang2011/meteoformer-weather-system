import { fetchJson } from './request';
// Public snapshots are produced by scripts/export-demo.py from synthetic runs.
export const isDemo = import.meta.env.MODE === 'demo';
export const repositoryUrl = 'https://github.com/GuHang2011/meteoformer-weather-system';
let snapshotPromise: Promise<any> | undefined;
export function snapshot(): Promise<any> {
	if (!snapshotPromise) {
		snapshotPromise = fetchJson(`${import.meta.env.BASE_URL}demo/snapshot.json`)
			.catch((error) => { snapshotPromise = undefined; throw error; });
	}
	return snapshotPromise;
}

export async function demoApi(path: string, options: RequestInit = {}): Promise<any> {
	if (options.method && options.method.toUpperCase() !== 'GET') throw new Error('在线演示只读，请在本地运行完整系统。');
	const url = new URL(path, 'https://demo.invalid');
	const s = await snapshot(), data = s.data, forecast = s.overview.forecasts[0];
	const id = url.searchParams.get('forecast_id');
	if (id && id !== forecast.id) throw new Error('演示中没有该预报。');
	if (url.pathname === '/overview') return s.overview;
	if (url.pathname === '/health') return s.health;
	if (url.pathname === '/auth/session') return { role: 'viewer' };
	if (url.pathname === '/warning/list') {
		const warnings = s.warnings.map((w: any) => ({ ...w, expired: Date.parse(w.valid_end) < Date.now() }));
		return url.searchParams.get('active_only') === 'false' ? warnings : warnings.filter((w: any) => !w.expired);
	}
	if (url.pathname === '/forecast/grid') {
		const variable = url.searchParams.get('variable') || 't2m', lead = Number(url.searchParams.get('lead') || 1);
		if (!['t2m', 'precip', 'wind', 'rh', 'msl'].includes(variable) || !Number.isInteger(lead) || lead < 1 || lead > 24)
			throw new Error('无效的要素或预报时效。');
		const values = data.fields[variable][lead - 1];
		return { forecast, variable, unit: data.units[variable], valid_time: data.times[lead - 1],
			lat: data.lat, lon: data.lon, values, min: Math.min(...values.flat()), max: Math.max(...values.flat()),
			scale_min: data.scales[variable][0], scale_max: data.scales[variable][1] };
	}
	if (url.pathname === '/point') {
		const lon = Number(url.searchParams.get('lon')), lat = Number(url.searchParams.get('lat'));
		const [west, south, east, north] = forecast.bounds;
		if (!Number.isFinite(lon) || !Number.isFinite(lat) || lon < west || lon > east || lat < south || lat > north)
			throw new Error('查询点超出当前预报覆盖范围');
		// Pandas/xarray nearest coordinates prefer the larger coordinate on ties.
		const nearest = (coords: number[], value: number) => coords.reduce((best, x, i) => Math.abs(x - value) <= Math.abs(coords[best] - value) ? i : best, 0);
		const x = nearest(data.lon, lon), y = nearest(data.lat, lat);
		return { forecast, requested: { lon, lat }, grid_point: { lon: data.lon[x], lat: data.lat[y] }, interpolation: 'nearest',
			hourly: data.times.map((time: string, i: number) => ({ time, lead: i + 1,
				...Object.fromEntries(Object.entries(data.fields).map(([k, values]: [string, any]) => [k, Number(values[i][y][x].toFixed(3))])) })) };
	}
	throw new Error('此操作需要运行本地完整系统。');
}

export async function demoDownload(path: string): Promise<{ url: string; filename: string }> {
	const url = new URL(path, 'https://demo.invalid'), s = await snapshot();
	let file: string;
	if (url.pathname === '/forecast/download' && url.searchParams.get('forecast_id') === s.overview.forecasts[0].id) file = 'forecast.nc';
	else if (url.pathname === `/datasets/${s.overview.datasets[0].id}/download`) file = 'dataset.nc';
	else if (url.pathname === '/forecast/image') {
		await demoApi(path.replace('/forecast/image', '/forecast/grid'));
		file = `images/${url.searchParams.get('variable') || 't2m'}-${url.searchParams.get('lead') || 1}h.png`;
	} else throw new Error('演示中没有该下载文件。');
	return { url: `${import.meta.env.BASE_URL}demo/${file}`, filename: file.split('/').pop()! };
}
