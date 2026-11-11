<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue';
import { Aim, Plus, Minus, RefreshLeft } from '@element-plus/icons-vue';
import { date, number } from './api';
import { palettes, rgbAt } from './mapColors';
const props = defineProps<{ grid: any; point: { lon: number; lat: number } }>();
const emit = defineEmits<{ (e: 'select', value: { lon: number; lat: number }): void }>();
const canvasElement = ref<HTMLElement | null>(null);
const canvasSize = ref({ width: 1000, height: 600 });
const viewWidth = 1000;
const viewHeight = computed(() => viewWidth * canvasSize.value.height / canvasSize.value.width);
const renderScale = computed(() => canvasSize.value.width / viewWidth);
let sizeObserver: ResizeObserver | undefined;
const mapLabelStyle = computed(() => ({
	'--map-label-size': `${12 / renderScale.value}px`,
	'--map-coordinate-size': `${11 / renderScale.value}px`,
}));
const fieldNames: Record<string, string> = { t2m: '2 米气温', precip: '小时降水', wind: '10 米风速', rh: '相对湿度', msl: '海平面气压' };
const land = ref<any[]>([]),
	landError = ref(false),
	water = ref<{ rivers: WaterFeature[]; lakes: WaterFeature[] }>({ rivers: [], lakes: [] }),
	waterError = ref(false),
	basemap = ref('relief'),
	reliefLoaded = ref(false),
	reliefError = ref(false),
	smooth = ref(true),
	zoom = ref(1);
type WaterFeature = { name: string; bounds: number[]; lines: number[][][] };
const reliefBounds = [100, 15, 140, 45];
const reliefUrl = `${import.meta.env.BASE_URL}geography/east-asia-relief.webp`;
const hover = ref<{ lon: number; lat: number; value: number } | null>(null);
const colors = computed(() => palettes[props.grid.variable] || palettes.t2m);
const scale = computed(() => ({ min: props.grid.scale_min ?? props.grid.min, max: props.grid.scale_max ?? props.grid.max }));
const region = computed(() => ({
	west: props.grid.lon[0],
	east: props.grid.lon[props.grid.lon.length - 1],
	south: props.grid.lat[0],
	north: props.grid.lat[props.grid.lat.length - 1],
}));
const camera = computed(() => {
	const r = region.value,
		cy = (r.south + r.north) / 2,
		cx = (r.east + r.west) / 2;
	const cos = Math.max(0.15, Math.cos((cy * Math.PI) / 180));
	// Match the geographic extent to the actual canvas, with padding on both axes.
	// At reset, every edge of the forecast domain remains visible without stretching.
	const aspect = canvasSize.value.height / canvasSize.value.width;
	const height = Math.max((r.north - r.south) * 1.2, (r.east - r.west) * cos * aspect * 1.2) / zoom.value;
	const width = height / aspect / cos;
	return { west: cx - width / 2, east: cx + width / 2, south: cy - height / 2, north: cy + height / 2 };
});
const x = (lon: number) => ((lon - camera.value.west) / (camera.value.east - camera.value.west)) * viewWidth;
const y = (lat: number) => ((camera.value.north - lat) / (camera.value.north - camera.value.south)) * viewHeight.value;
const reliefAvailable = computed(() => region.value.west >= reliefBounds[0] && region.value.east <= reliefBounds[2] && region.value.south >= reliefBounds[1] && region.value.north <= reliefBounds[3]);
const showRelief = computed(() => basemap.value === 'relief' && reliefAvailable.value && !reliefError.value);
const waterPaths = (features: WaterFeature[], closed: boolean) => features
	.filter((f) => f.bounds[2] >= camera.value.west && f.bounds[0] <= camera.value.east && f.bounds[3] >= camera.value.south && f.bounds[1] <= camera.value.north)
	.map((f) => f.lines.map((line) => line.map(([lon, lat], i) => `${i ? 'L' : 'M'}${x(lon).toFixed(2)},${y(lat).toFixed(2)}`).join('') + (closed ? 'Z' : '')).join(''));
const rivers = computed(() => waterPaths(water.value.rivers, false));
const lakes = computed(() => waterPaths(water.value.lakes, true));
const coverage = computed(() => ({
	x: x(region.value.west),
	y: y(region.value.north),
	width: x(region.value.east) - x(region.value.west),
	height: y(region.value.south) - y(region.value.north),
}));
const landPaths = computed(() =>
	land.value
		.filter(
			(p) =>
				p.bounds[2] >= camera.value.west && p.bounds[0] <= camera.value.east && p.bounds[3] >= camera.value.south && p.bounds[1] <= camera.value.north
		)
		.map((p) => p.ring.map(([lon, lat]: number[], i: number) => `${i ? 'L' : 'M'}${x(lon).toFixed(2)},${y(lat).toFixed(2)}`).join('') + 'Z')
);
const cities = [
	{ name: '上海', lon: 121.4737, lat: 31.2304 },
	{ name: '杭州', lon: 120.1551, lat: 30.2741 },
	{ name: '南京', lon: 118.7969, lat: 32.0603 },
	{ name: '合肥', lon: 117.2272, lat: 31.8206 },
	{ name: '宁波', lon: 121.5503, lat: 29.8746 },
	{ name: '温州', lon: 120.6994, lat: 27.9949 },
	{ name: '南昌', lon: 115.8582, lat: 28.6829 },
	{ name: '武汉', lon: 114.3054, lat: 30.5931 },
	{ name: '济南', lon: 117.1201, lat: 36.6512 },
	{ name: '青岛', lon: 120.3826, lat: 36.0671 },
	{ name: '福州', lon: 119.2965, lat: 26.0745 },
	{ name: '台北', lon: 121.5654, lat: 25.033 },
	{ name: '北京', lon: 116.4074, lat: 39.9042 },
	{ name: '广州', lon: 113.2644, lat: 23.1291 },
	{ name: '成都', lon: 104.0665, lat: 30.5723 },
];
const labels = computed(() => cities.filter((c) => {
	const padding = 18 / renderScale.value;
	return x(c.lon) > padding && x(c.lon) < viewWidth - 42 / renderScale.value
		&& y(c.lat) > padding && y(c.lat) < viewHeight.value - 26 / renderScale.value;
}));
const longitudeLines = computed(() =>
	Array.from({ length: 7 }, (_, i) => camera.value.west + ((camera.value.east - camera.value.west) * (i + 1)) / 8)
);
const latitudeLines = computed(() =>
	Array.from({ length: 5 }, (_, i) => camera.value.south + ((camera.value.north - camera.value.south) * (i + 1)) / 6)
);
const marker = computed(() => ({ x: x(props.point.lon), y: y(props.point.lat) }));
const nearest = (values: number[], value: number) =>
	values.reduce((best, v, i) => (Math.abs(v - value) < Math.abs(values[best] - value) ? i : best), 0);
const raster = computed(() => {
	const g = props.grid,
		rows = g.lat.length,
		cols = g.lon.length;
	const canvas = document.createElement('canvas');
	canvas.width = smooth.value ? 480 : cols;
	canvas.height = smooth.value ? 480 : rows;
	const ctx = canvas.getContext('2d');
	if (!ctx) return '';
	const image = ctx.createImageData(canvas.width, canvas.height);
	for (let py = 0; py < canvas.height; py++)
		for (let px = 0; px < canvas.width; px++) {
			const gx = (px / (canvas.width - 1)) * (cols - 1),
				gy = (1 - py / (canvas.height - 1)) * (rows - 1);
			const xi = Math.floor(gx),
				yi = Math.floor(gy),
				xa = Math.min(cols - 1, xi + 1),
				ya = Math.min(rows - 1, yi + 1);
			const fx = gx - xi,
				fy = gy - yi;
			const value = (g.values[yi][xi] * (1 - fx) + g.values[yi][xa] * fx) * (1 - fy) + (g.values[ya][xi] * (1 - fx) + g.values[ya][xa] * fx) * fy;
			const rgb = rgbAt(value, scale.value.min, scale.value.max, g.variable),
				i = (py * canvas.width + px) * 4;
			image.data[i] = rgb[0];
			image.data[i + 1] = rgb[1];
			image.data[i + 2] = rgb[2];
			image.data[i + 3] = 205;
		}
	ctx.putImageData(image, 0, 0);
	return canvas.toDataURL();
});
function position(event: MouseEvent) {
	const svg = event.currentTarget as SVGSVGElement,
		matrix = svg.getScreenCTM();
	if (!matrix) return null;
	const point = svg.createSVGPoint();
	point.x = event.clientX;
	point.y = event.clientY;
	const p = point.matrixTransform(matrix.inverse()),
		c = camera.value;
	const lon = c.west + (p.x / viewWidth) * (c.east - c.west),
		lat = c.north - (p.y / viewHeight.value) * (c.north - c.south),
		r = region.value;
	if (lon < r.west || lon > r.east || lat < r.south || lat > r.north) return null;
	const xi = nearest(props.grid.lon, lon),
		yi = nearest(props.grid.lat, lat);
	return { lon: props.grid.lon[xi], lat: props.grid.lat[yi], value: props.grid.values[yi][xi] };
}
function select(event: MouseEvent) {
	const p = position(event);
	if (p) emit('select', { lon: p.lon, lat: p.lat });
}
onMounted(async () => {
	if (canvasElement.value) {
		sizeObserver = new ResizeObserver(([entry]) => {
			if (entry.contentRect.width > 0 && entry.contentRect.height > 0) {
				canvasSize.value = { width: entry.contentRect.width, height: entry.contentRect.height };
				hover.value = null;
			}
		});
		sizeObserver.observe(canvasElement.value);
	}
	const loadLand = async () => { try {
		const response = await fetch(`${import.meta.env.BASE_URL}land-50m.json`);
		if (!response.ok) throw new Error('map');
		land.value = (await response.json()).polygons;
	} catch {
		landError.value = true;
	} };
	const loadWater = async () => { try {
		const response = await fetch(`${import.meta.env.BASE_URL}geography/east-asia-water.json`);
		if (!response.ok) throw new Error('water');
		water.value = await response.json();
	} catch {
		waterError.value = true;
	} };
	await Promise.all([loadLand(), loadWater()]);
});
onUnmounted(() => sizeObserver?.disconnect());
</script>

<template>
	<div class="weather-map synoptic-map">
		<div class="map-topline">
			<span class="map-product"
				><i />{{ grid.forecast.source === 'synthetic' ? '合成数据演示' : '区域预报'
				}}<b
					>+{{
						String(Math.round((new Date(grid.valid_time).getTime() - new Date(grid.forecast.init_time).getTime()) / 3600000)).padStart(2, '0')
					}}
					H</b
				></span
			><span class="map-valid-time">有效时间 {{ date(grid.valid_time) }}</span>
		</div>
		<div class="map-canvas" ref="canvasElement" :style="mapLabelStyle">
		<svg
			:viewBox="`0 0 ${viewWidth} ${viewHeight}`"
			preserveAspectRatio="xMidYMid meet"
			role="img"
			aria-label="气象预报地图，显示真实海岸线和区域预报覆盖范围，可使用经纬度表单查询单点"
			@click="select"
			@mousemove="hover = position($event)"
			@mouseleave="hover = null"
		>
			<defs>
				<clipPath id="map-boundary"><rect :width="viewWidth" :height="viewHeight" rx="0" /></clipPath>
			</defs>
			<g clip-path="url(#map-boundary)">
				<rect :width="viewWidth" :height="viewHeight" fill="#101e2b" />
				<path v-for="(path, i) in landPaths" :key="`land-${i}`" :d="path" class="map-land" />
				<image v-if="showRelief" class="map-relief" :href="reliefUrl" :x="x(reliefBounds[0])" :y="y(reliefBounds[3])"
					:width="x(reliefBounds[2]) - x(reliefBounds[0])" :height="y(reliefBounds[1]) - y(reliefBounds[3])"
					preserveAspectRatio="none" @load="reliefLoaded = true" @error="reliefError = true" />
				<path v-for="(path, i) in lakes" :key="`lake-${i}`" :d="path" class="map-lake" fill-rule="evenodd" />
				<g class="coordinate-grid">
					<line v-for="lon in longitudeLines" :key="lon" :x1="x(lon)" :x2="x(lon)" y1="0" :y2="viewHeight" />
					<line v-for="lat in latitudeLines" :key="lat" x1="0" :x2="viewWidth" :y1="y(lat)" :y2="y(lat)" />
				</g>
				<image
					:href="raster"
					:x="coverage.x"
					:y="coverage.y"
					:width="coverage.width"
					:height="coverage.height"
					preserveAspectRatio="none"
					:style="{ imageRendering: smooth ? 'auto' : 'pixelated' }"
				/>
				<path v-for="(path, i) in landPaths" :key="`coast-${i}`" :d="path" class="map-coast" />
				<path v-for="(path, i) in rivers" :key="`river-${i}`" :d="path" class="map-river" />
				<rect :x="coverage.x" :y="coverage.y" :width="coverage.width" :height="coverage.height" class="coverage-boundary" />
				<text :x="coverage.x + 8 / renderScale" :y="coverage.y + 17 / renderScale" class="coverage-label">预报覆盖范围 · {{ grid.lat.length }} × {{ grid.lon.length }}</text>
				<g v-for="city in labels" :key="city.name" :transform="`translate(${x(city.lon)},${y(city.lat)})`" class="city-label">
					<circle :r="2 / renderScale" />
					<text :x="7 / renderScale" :y="4 / renderScale">{{ city.name }}</text>
				</g>
				<g class="coordinate-labels">
					<text v-for="lon in longitudeLines" :key="lon" :x="x(lon)" :y="viewHeight - 10 / renderScale" text-anchor="middle">{{ number(lon, 1) }}°E</text>
					<text v-for="lat in latitudeLines" :key="lat" :x="12 / renderScale" :y="y(lat) - 5 / renderScale">{{ number(lat, 1) }}°N</text>
				</g>
				<g
					v-if="marker.x >= 0 && marker.x <= viewWidth && marker.y >= 0 && marker.y <= viewHeight"
					:transform="`translate(${marker.x},${marker.y}) scale(${1 / renderScale})`"
					class="map-point"
				>
					<circle r="16" />
					<circle r="5" />
					<path d="M-23 0h8M15 0h8M0-23v8M0 15v8" />
				</g>
			</g>
		</svg>
		<div class="map-tools" role="group" aria-label="地图缩放">
			<button aria-label="放大地图" :disabled="zoom >= 2" @click="zoom = Math.min(2, zoom + 0.25)"><Plus /></button
			><button aria-label="缩小地图" :disabled="zoom <= 0.75" @click="zoom = Math.max(0.75, zoom - 0.25)"><Minus /></button
			><button aria-label="重置地图" @click="zoom = 1"><RefreshLeft /></button>
		</div>
		<span v-if="reliefError || waterError" class="map-material-status" role="status">{{ reliefError ? '地形加载失败，已显示简图' : '水系资料加载失败' }}</span>
		<div class="map-probe">
			<Aim /><span v-if="hover"
				>{{ number(hover.lon, 2) }}°E / {{ number(hover.lat, 2) }}°N <strong>{{ number(hover.value, 2) }} {{ grid.unit }}</strong></span
			><span v-else>点击覆盖区域，查看逐小时预报</span>
		</div>
		</div>
		<div class="map-control-strip">
			<div class="map-view-options">
				<div class="map-basemap" role="group" aria-label="地理底图">
					<span>底图</span><button :aria-pressed="showRelief" :class="{ active: showRelief }" :disabled="!reliefAvailable || reliefError" @click="basemap = 'relief'">地形</button>
					<button :aria-pressed="!showRelief" :class="{ active: !showRelief }" @click="basemap = 'plain'">简图</button>
				</div>
				<div class="map-display-mode" role="group" aria-label="气象场显示方式">
					<button :aria-pressed="smooth" :class="{ active: smooth }" @click="smooth = true">连续显示</button>
					<button :aria-pressed="!smooth" :class="{ active: !smooth }" @click="smooth = false">原始网格</button>
				</div>
			</div>
		<div class="map-scale">
			<div class="scale-heading">
				<span
					>{{ fieldNames[grid.variable] || grid.variable.toUpperCase() }} <b>{{ grid.unit }}</b></span
				><span>同批次固定色标</span>
			</div>
			<div class="scale-ramp" :style="{ background: `linear-gradient(90deg,${colors.join(',')})` }" />
			<div class="scale-ticks">
				<span v-for="n in 5" :key="n">{{
					number(scale.min + ((scale.max - scale.min) * (n - 1)) / 4, Math.abs(scale.max - scale.min) < 1 ? 2 : 1)
				}}</span>
			</div>
		</div>
		</div>
		<div class="map-attribution">
			<span><a v-if="showRelief && reliefLoaded" href="https://www.earthdata.nasa.gov/centers/gibs" target="_blank" rel="noopener noreferrer">NASA Blue Marble · 静态地形</a><template v-if="showRelief && reliefLoaded"> / </template><a href="https://www.naturalearthdata.com/about/terms-of-use/" target="_blank" rel="noopener noreferrer">Natural Earth</a>{{ landError ? ' · 海岸线加载失败' : '' }}</span>
			<span>{{ smooth ? '连续显示为插值渲染，查询使用原始格点' : '原始网格显示' }}</span>
		</div>
	</div>
</template>
