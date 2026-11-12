<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue';
import {
	Cloudy,
	Odometer,
	DataLine,
	FolderOpened,
	Cpu,
	Bell,
	ArrowRight,
	ArrowLeft,
	Download,
	Refresh,
	Location,
	Lock,
	Close,
	WindPower,
	Sunny,
	Drizzling,
	CircleCheck,
	Warning,
} from '@element-plus/icons-vue';
import WeatherMap from './SynopticMap.vue';
import ForecastChart from './ForecastChart.vue';
import { api, post, date, number, sourceName } from './api';
import { isDemo, repositoryUrl } from './demo';
import { useDownload } from './useDownload';
import './weather.css';
import './synoptic.css';

const navigation = [
	{ id: 'overview', label: '预报工作台', icon: Odometer, subtitle: '区域天气分布与未来 24 小时趋势' },
	{ id: 'forecast', label: '预报与查询', icon: DataLine, subtitle: '选择预报批次，查看要素与格点数据' },
	{ id: 'data', label: '气象数据', icon: FolderOpened, subtitle: '数据来源与质量' },
	{ id: 'training', label: '训练记录', icon: Cpu, subtitle: '训练任务与评估结果' },
	{ id: 'warnings', label: '阈值告警', icon: Bell, subtitle: '查看达到阈值的天气过程' },
];
const initialPage = location.hash.slice(1);
const page = ref(navigation.some((n) => n.id === initialPage) ? initialPage : 'overview');
const currentPage = computed(() => navigation.find((n) => n.id === page.value)!);
const pageHeading = ref<HTMLElement>();
const loginDialog = ref<HTMLDialogElement>();
const hourlyHeading = ref<HTMLElement>();
const { state: downloadState, filename: downloadFilename, message: downloadMessage, active: downloading,
	percent: downloadPercent, size: downloadSize, title: downloadTitle, start: download,
	cancel: cancelDownload, close: closeDownload, retry: retryDownload } = useDownload();
const admin = ref(false),
	loginOpen = ref(false),
	password = ref('');
const error = ref(''),
	notice = ref(''),
	busy = ref(''),
	connected = ref(false),
	loading = ref(true);
const loadError = ref(''), mapError = ref(''), pointError = ref('');
const mapLoading = ref(false), pointLoading = ref(false);
const overview = ref<any>({ datasets: [], forecasts: [], jobs: [], thresholds: { precip: 20, wind: 17, temperature: 35 } });
const health = ref<any>({}),
	warnings = ref<any[]>([]),
	selected = ref(''),
	grid = ref<any>(null),
	pointResult = ref<any>(null);
const variable = ref('t2m'),
	lead = ref(1),
	point = ref({ lon: 120.5, lat: 31.5 });
const variables = [
	{ id: 't2m', label: '气温', fullLabel: '2 米气温', unit: '°C' },
	{ id: 'precip', label: '降水', fullLabel: '小时降水', unit: 'mm/h' },
	{ id: 'wind', label: '风速', fullLabel: '10 米风速', unit: 'm/s' },
	{ id: 'rh', label: '湿度', fullLabel: '相对湿度', unit: '%' },
	{ id: 'msl', label: '气压', fullLabel: '海平面气压', unit: 'hPa' },
];
const currentVariable = computed(() => variables.find(v => v.id === variable.value)!);
const datasetId = ref(''),
	engine = ref('persistence'),
	modelId = ref(''),
	members = ref(1),
	epochs = ref(3),
	samples = ref(16);
const importSource = ref('ERA5'),
	gridSize = ref(16),
	hourly = ref(false),
	uploadFile = ref<File | null>(null);
const thresholds = ref({ precip: 20, wind: 17, temperature: 35 }),
	showExpired = ref(isDemo);
const forecast = computed(() => overview.value.forecasts.find((f: any) => f.id === selected.value));
const models = computed(() =>
	overview.value.jobs.filter((j: any) => {
		const trained = overview.value.datasets.find((d: any) => d.id === j.dataset_id);
		const current = overview.value.datasets.find((d: any) => d.id === datasetId.value);
		return (
			j.status === 'completed' &&
			trained &&
			current &&
			trained.source === current.source &&
			JSON.stringify(trained.shape) === JSON.stringify(current.shape) &&
			JSON.stringify(trained.bounds) === JSON.stringify(current.bounds)
		);
	})
);
const activeWarnings = computed(() => warnings.value.filter((w) => !w.expired));
const visibleWarnings = computed(() => (showExpired.value ? warnings.value : activeWarnings.value));
const running = computed(() => overview.value.jobs.some((j: any) => ['queued', 'running'].includes(j.status)));
const isBusy = computed(() => Boolean(busy.value));
const selectedDataset = computed(() => overview.value.datasets.find((d: any) => d.id === datasetId.value));
let interval: ReturnType<typeof setInterval> | undefined;
let polling = false;
let mapRequest = 0,
	pointRequest = 0;
const hashChanged = () => {
	const value = location.hash.slice(1);
	if (navigation.some((n) => n.id === value)) page.value = value;
};
watch(page, async (v) => {
	location.hash = v;
	error.value = '';
	notice.value = '';
	document.title = `${currentPage.value.label} · MeteoFormer`;
	await nextTick();
	window.scrollTo({ top: 0, behavior: 'auto' });
	pageHeading.value?.focus({ preventScroll: true });
});
watch(loginOpen, async (open) => {
	if (open) {
		error.value = '';
		await nextTick();
		loginDialog.value?.showModal();
	} else {
		loginDialog.value?.close();
		password.value = '';
	}
});
watch(datasetId, () => {
	modelId.value = '';
});
watch(engine, (v) => {
	if (v === 'persistence') members.value = 1;
});

async function action(label: string, task: () => Promise<void>) {
	if (isBusy.value) return;
	busy.value = label;
	error.value = '';
	notice.value = '';
	try {
		await task();
	} catch (e: any) {
		error.value = e.message || '操作失败，请重试';
	} finally {
		busy.value = '';
	}
}
async function refresh() {
	try {
		const [data, alerts, session, status] = await Promise.all([
			api('/overview'),
			api('/warning/list?active_only=false'),
			api('/auth/session'),
			api('/health'),
		]);
		overview.value = data;
		warnings.value = alerts;
		admin.value = session.role === 'admin';
		health.value = status;
		connected.value = true;
		loadError.value = '';
		if (!datasetId.value && data.datasets.length) datasetId.value = data.datasets[0].id;
		if (!data.forecasts.some((f: any) => f.id === selected.value)) selected.value = data.forecasts[0]?.id || '';
	} catch (e) {
		connected.value = false;
		throw e;
	}
}
async function connect() {
	loading.value = true;
	loadError.value = '';
	try {
		await refresh();
		thresholds.value = { ...overview.value.thresholds };
	}
	catch (e: any) { loadError.value = e.message || '连接失败，请稍后重试。'; }
	finally { loading.value = false; }
}
async function reloadData() {
	if (loadError.value) return connect();
	const previous = selected.value;
	await refresh();
	if (previous === selected.value) await Promise.all([loadMap(), queryPoint()]);
}
async function loadMap() {
	const sequence = ++mapRequest;
	mapError.value = '';
	mapLoading.value = Boolean(selected.value);
	if (!selected.value) {
		grid.value = null;
		return;
	}
	try {
		const result = await api(`/forecast/grid?forecast_id=${selected.value}&variable=${variable.value}&lead=${lead.value}`);
		if (sequence === mapRequest) grid.value = result;
	} catch (e: any) {
		if (sequence === mapRequest) {
			grid.value = null;
			mapError.value = e.message || '请检查连接后重试。';
		}
	} finally {
		if (sequence === mapRequest) mapLoading.value = false;
	}
}
async function queryPoint() {
	const sequence = ++pointRequest;
	pointResult.value = null;
	pointError.value = '';
	pointLoading.value = Boolean(selected.value);
	if (!selected.value) return;
	try {
		const result = await api(`/point?forecast_id=${selected.value}&lon=${point.value.lon}&lat=${point.value.lat}`);
		if (sequence === pointRequest) pointResult.value = result;
	} catch (e: any) {
		if (sequence === pointRequest) pointError.value = e.message;
	} finally {
		if (sequence === pointRequest) pointLoading.value = false;
	}
}
watch([selected, variable, lead], loadMap);
watch(selected, () => {
	pointResult.value = null;
	if (forecast.value) {
		const b = forecast.value.bounds;
		point.value = { lon: (b[0] + b[2]) / 2, lat: (b[1] + b[3]) / 2 };
		queryPoint();
	}
});
async function mapPoint(value: { lon: number; lat: number }) {
	const [west, south, east, north] = forecast.value.bounds;
	// Keep rounded edge coordinates within the actual grid domain.
	point.value = { lon: Math.max(west, Math.min(east, Number(value.lon.toFixed(4)))), lat: Math.max(south, Math.min(north, Number(value.lat.toFixed(4)))) };
	error.value = '';
	await queryPoint();
}
async function login() {
	await action('正在验证', async () => {
		await post('/auth/login', { password: password.value });
		password.value = '';
		loginOpen.value = false;
		await refresh();
		notice.value = '已进入管理员模式，有效期 2 小时。';
	});
}
async function logout() {
	await action('正在退出', async () => {
		await post('/auth/logout');
		admin.value = false;
		notice.value = '已切换为访客浏览。';
	});
}
async function createDemo() {
	await action('正在准备演示数据', async () => {
		const d = await post('/datasets/demo');
		await refresh();
		datasetId.value = d.id;
		notice.value = '已创建 480 小时合成演示数据，可用于验证训练和预报流程。';
	});
}
async function importData() {
	if (!uploadFile.value || !hourly.value) return;
	await action('正在校验并导入', async () => {
		const body = new FormData();
		body.append('file', uploadFile.value!);
		body.append('source', importSource.value);
		body.append('grid_size', String(gridSize.value));
		body.append('hourly_precipitation', 'true');
		const d = await api('/datasets/import', { method: 'POST', body });
		await refresh();
		datasetId.value = d.id;
		notice.value = '数据已完成校验、空间重采样与持久化。';
	});
}
async function predict() {
	await action('正在生成 24 小时预报', async () => {
		const f = await post('/predict', { dataset_id: datasetId.value, engine: engine.value, members: members.value, model_id: modelId.value || null });
		await refresh();
		selected.value = f.id;
		page.value = 'forecast';
		notice.value = '预报已保存，告警阈值检查已完成。';
	});
}
async function train() {
	await action('正在启动训练', async () => {
		await post('/train/start', { dataset_id: datasetId.value, epochs: epochs.value, samples: samples.value });
		await refresh();
		notice.value = '训练已启动，页面将自动更新进度。';
	});
}
async function saveThresholds() {
	await action('正在保存阈值', async () => {
		await api('/warning/thresholds', { method: 'PUT', body: JSON.stringify(thresholds.value) });
		await refresh();
		notice.value = '阈值已保存，将应用于后续生成的预报。历史告警保持原阈值。';
	});
}
async function acknowledge(key: string) {
	await action('正在确认告警', async () => {
		await post(`/warning/${key}/acknowledge`);
		await refresh();
	});
}
function viewHourly() {
	hourlyHeading.value?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
	hourlyHeading.value?.focus({ preventScroll: true });
}
const statuses: Record<string, string> = { queued: '排队中', running: '训练中', completed: '已完成', failed: '失败', interrupted: '已中断' };
onMounted(async () => {
	window.addEventListener('hashchange', hashChanged);
	document.title = `${currentPage.value.label} · MeteoFormer`;
	await connect();
	interval = setInterval(async () => {
		if (running.value && !isBusy.value && !polling) {
			polling = true;
			try {
				await refresh();
			} catch (e: any) {
				error.value = e.message;
			} finally {
				polling = false;
			}
		}
	}, 4000);
});
onUnmounted(() => {
	clearInterval(interval);
	window.removeEventListener('hashchange', hashChanged);
});
</script>

<template>
	<div class="meteo-shell">
		<a class="skip-link" href="#main-content" @click.prevent="pageHeading?.focus()">跳转到主要内容</a>
		<aside class="sidebar">
			<a class="brand" href="#overview"
				><span class="brand-icon"><Cloudy /></span><span>MeteoFormer<small>区域气象预测系统</small></span></a
			>
			<div class="nav-caption">业务导航</div>
			<nav aria-label="主导航">
				<button
					v-for="item in navigation"
					:key="item.id"
					:aria-label="item.label"
					:class="{ active: page === item.id }"
					:aria-current="page === item.id ? 'page' : undefined"
					@click="page = item.id"
				>
					<component :is="item.icon" /><span>{{ item.label }}</span
					><span class="nav-count" v-if="item.id === 'warnings' && activeWarnings.length">{{ activeWarnings.length }}</span
					>
				</button>
			</nav>
			<div class="sidebar-note">
				<strong>预报窗口</strong>
				<p>输入 12 小时 · 预报 24 小时</p>
			</div>
			<div class="sidebar-status">
				<i :class="{ online: connected }" /><span>{{ isDemo ? (connected ? '演示快照已加载' : loading ? '正在加载演示' : '演示快照未加载') : (connected ? '气象服务已连接' : '气象服务未连接') }}</span>
			</div>
		</aside>
		<div class="workspace">
			<header class="topbar">
				<div class="breadcrumb">
					<span class="desktop-context">区域气象预测</span><span class="mobile-brand">MeteoFormer</span><span class="breadcrumb-divider">/</span><strong>{{ currentPage.label }}</strong>
				</div>
				<div class="topbar-actions">
					<span class="timezone">北京时间 UTC+8</span
					><button class="icon-button" aria-label="刷新数据" title="刷新数据" :disabled="isBusy || loading" @click="action('正在刷新', reloadData)"><Refresh /></button
					><button v-if="!isDemo" class="user-button" @click="admin ? logout() : (loginOpen = true)" :disabled="isBusy">
						<span class="avatar">{{ admin ? '管' : '访' }}</span
						>{{ admin ? '管理员 · 退出' : '访客 · 管理员登录' }}
					</button>
				</div>
			</header>
			<main id="main-content" :class="{ 'forecast-main': page === 'overview' || page === 'forecast' }">
				<div class="page-heading">
					<div>
						<h1 ref="pageHeading" tabindex="-1">{{ currentPage.label }}</h1>
						<p>{{ currentPage.subtitle }}</p>
					</div>
					<span class="page-date" v-if="forecast && (page === 'overview' || page === 'forecast')">起报 {{ date(forecast.init_time) }}<small>北京时间 · 预报至 +24 h</small></span>
					<span class="page-date" v-else>{{ date(overview.server_time) }}<small>{{ isDemo ? '快照时间 · 北京时间' : '服务时间 · 北京时间' }}</small></span>
				</div>
				<div v-if="isDemo" class="demo-banner" role="note">
					<span class="demo-badge">合成数据演示</span><span>只读快照 · 非实时预报</span>
					<span class="demo-snapshot-date" v-if="overview.server_time">快照 {{ overview.server_time.slice(0, 10) }}</span>
				</div>
				<div v-if="error" class="notice error" role="alert">
					<Warning /><span>{{ error }}</span
					><button aria-label="关闭错误提示" @click="error = ''">×</button>
				</div>
				<div v-if="notice" class="notice success" role="status">
					<CircleCheck /><span>{{ notice }}</span
					><button aria-label="关闭提示" @click="notice = ''">×</button>
				</div>
				<div v-if="busy" class="notice busy" role="status"><span class="spinner" />{{ busy }}…</div>
				<div v-if="loading" class="empty panel" role="status"><span class="spinner" />{{ isDemo ? '正在加载演示快照…' : '正在连接气象服务…' }}</div>
				<div v-else-if="loadError" class="empty panel connection-error" role="alert">
					<Warning /><h2>{{ isDemo ? '演示快照暂时无法加载' : '暂时无法连接气象服务' }}</h2>
					<p>{{ loadError }}</p><button class="primary" @click="connect"><Refresh />重新连接</button>
				</div>

				<template v-else-if="page === 'overview' || page === 'forecast'">
					<section class="panel forecast-controls">
						<div class="control-row">
							<label class="grow"
								><span class="control-label">当前预报</span><select aria-label="已发布预报" v-model="selected" :disabled="!overview.forecasts.length">
									<option value="" disabled>暂无预报</option>
									<option v-for="f in overview.forecasts" :key="f.id" :value="f.id">
										{{ date(f.init_time) }} · {{ f.engine_label }} · {{ sourceName(f.source) }}
									</option>
								</select></label
							><button class="secondary" aria-label="NetCDF 下载" :disabled="!forecast || isBusy || downloading" @click="download(`/forecast/download?forecast_id=${selected}`)">
								<Download /><span>NetCDF</span>
							</button>
						</div>
						<details v-if="admin || !overview.forecasts.length" class="generate-details" :open="!overview.forecasts.length">
							<summary>
								生成 24 小时预报 <span>{{ admin ? '选择数据与预测方式' : '需管理员登录' }}</span>
							</summary>
							<form class="control-row generate-form" @submit.prevent="predict">
								<label class="grow"
									>数据集<select v-model="datasetId" required>
										<option value="" disabled>选择数据集</option>
										<option v-for="d in overview.datasets" :key="d.id" :value="d.id">{{ d.name }} · {{ sourceName(d.source) }}</option>
									</select></label
								><label
									>预测方式<select v-model="engine" aria-label="预测方式">
										<option value="persistence">持续性基线</option>
										<option value="meteoformer">MeteoFormer 原型</option>
									</select></label
								><label v-if="engine === 'meteoformer'"
									>模型权重<select v-model="modelId" required aria-label="模型权重">
										<option value="" disabled>选择已完成训练</option>
										<option v-for="m in models" :key="m.id" :value="m.id">{{ date(m.created_at) }} · {{ m.id.slice(0, 6) }}</option>
									</select></label
								><label v-if="engine === 'meteoformer'">集合成员<input type="number" v-model.number="members" min="1" max="8" required /></label
								><button class="primary" :disabled="!admin || !datasetId || isBusy || running">生成预报 <ArrowRight /></button>
							</form>
							<p class="help">持续性基线将最新观测保持 24 小时，用于比较；MeteoFormer 需先完成模型训练。集合概率为扰动样本频率，尚未经概率校准。</p>
						</details>
					</section>
					<div v-if="!forecast" class="empty panel">
						<Cloudy />
						<h2>从第一份气象数据开始</h2>
						<p>导入逐小时网格数据，或创建合成数据体验完整流程。</p>
						<button class="primary" @click="page = 'data'">前往气象数据 <ArrowRight /></button>
					</div>
					<template v-else>
						<div class="forecast-layout">
							<section class="panel field-panel">
								<div class="section-heading">
									<div>
										<h2>区域气象场</h2>
										<p>{{ sourceName(forecast.source) }}<template v-if="grid"> · {{ grid.lon.length }} × {{ grid.lat.length }} 网格</template></p>
									</div>
									<button
										class="secondary image-download"
										aria-label="下载当前气象图片"
										:disabled="isBusy || downloading || mapLoading || !!mapError"
										@click="download(`/forecast/image?forecast_id=${selected}&variable=${variable}&lead=${lead}`)"
									>
										<Download /><span>导出图片</span>
									</button>
								</div>
								<div class="variable-tabs" role="group" aria-label="气象要素">
									<button
										v-for="v in variables"
										:key="v.id"
										:class="{ selected: variable === v.id }"
										:aria-pressed="variable === v.id"
										@click="variable = v.id"
									>
										{{ v.label }}<small>{{ v.unit }}</small>
									</button>
								</div>
								<div class="field-viewport" :aria-busy="mapLoading">
									<WeatherMap v-if="grid" :grid="grid" :point="point" @select="mapPoint" />
									<div v-else-if="mapError" class="empty map-error" role="alert">
										<Warning /><h3>气象场未能加载</h3><p>{{ mapError }}</p><button class="secondary" @click="loadMap"><Refresh />重试地图</button>
									</div>
									<div v-else class="empty" role="status"><span class="spinner" />气象场加载中…</div>
									<div v-if="mapLoading && grid" class="map-loading" role="status"><span class="spinner" />正在更新气象场…</div>
								</div>
								<div class="timeline">
									<button class="step-button" aria-label="上一小时" title="上一小时" :disabled="lead <= 1" @click="lead--"><ArrowLeft /></button>
									<div class="timeline-track"><input aria-label="预报时效" :aria-valuetext="`起报后 ${lead} 小时`" type="range" min="1" max="24" v-model.number="lead" /><div class="timeline-ticks" aria-hidden="true"><span>+1 h</span><span>+6 h</span><span>+12 h</span><span>+18 h</span><span>+24 h</span></div></div>
									<button class="step-button" aria-label="下一小时" title="下一小时" :disabled="lead >= 24" @click="lead++"><ArrowRight /></button>
									<strong><span>预报时效</span>+{{ String(lead).padStart(2, '0') }} h</strong>
								</div>
								<p class="map-footnote">色标在同一批次内保持一致；海岸线为地理参照，不代表行政区界。</p>
							</section>
							<section class="panel point-panel">
								<div class="section-heading">
									<div>
										<h2>单点预报</h2>
										<p>点击地图，或输入经纬度</p>
									</div>
									<Location class="section-icon" />
								</div>
								<form @submit.prevent="action('正在查询', queryPoint)" class="point-form">
									<label>经度 °E<input aria-label="经度" type="number" v-model.number="point.lon" min="-180" max="180" step="any" required /></label
									><label>纬度 °N<input aria-label="纬度" type="number" v-model.number="point.lat" min="-90" max="90" step="any" required /></label
									><button class="primary" :disabled="isBusy || pointLoading">查询预报 <ArrowRight /></button>
								</form>
								<p v-if="pointLoading" class="point-status" role="status">正在读取格点预报…</p>
								<p v-else-if="pointError" class="point-status point-error" role="alert">{{ pointError }}</p>
								<template v-if="pointResult"
									><div class="point-weather">
										<span class="point-temp-label">{{ currentVariable.fullLabel }}</span><strong>{{ number(pointResult.hourly[lead - 1][variable]) }}<small>{{ currentVariable.unit }}</small></strong
										><span>{{ date(pointResult.hourly[lead - 1].time) }} · +{{ lead }} h</span>
									</div>
									<dl class="point-facts">
										<div v-if="variable !== 't2m'"><dt>2 米气温</dt><dd>{{ number(pointResult.hourly[lead - 1].t2m) }} °C</dd></div>
										<div>
											<dt>{{ variable === 'wind' ? '风向' : '风速 / 风向' }}</dt>
											<dd><template v-if="variable !== 'wind'">{{ number(pointResult.hourly[lead - 1].wind) }} m/s · </template>{{ number(pointResult.hourly[lead - 1].wind_direction, 0) }}°</dd>
										</div>
										<div v-if="variable !== 'rh'">
											<dt>相对湿度</dt>
											<dd>{{ number(pointResult.hourly[lead - 1].rh) }} %</dd>
										</div>
										<div v-if="variable !== 'precip'">
											<dt>小时降水</dt>
											<dd>{{ number(pointResult.hourly[lead - 1].precip) }} mm</dd>
										</div>
										<div v-if="variable !== 'msl'">
											<dt>海平面气压</dt>
											<dd>{{ number(pointResult.hourly[lead - 1].msl) }} hPa</dd>
										</div>
										<div v-if="pointResult.hourly[lead - 1].rain_probability !== undefined">
											<dt>降水频率 <small>≥1 mm</small></dt>
											<dd>{{ number(pointResult.hourly[lead - 1].rain_probability) }} %</dd>
										</div>
										<div v-if="pointResult.hourly[lead - 1].temperature_p10 !== undefined">
											<dt>温度 P10–P90</dt>
											<dd>
												{{ number(pointResult.hourly[lead - 1].temperature_p10) }}–{{ number(pointResult.hourly[lead - 1].temperature_p90) }} °C
											</dd>
										</div>
									</dl>
									<p class="help">
										最近格点：{{ number(pointResult.grid_point.lon, 3) }}°E / {{ number(pointResult.grid_point.lat, 3) }}°N<br />风向表示来向，正北为
										0°。
									</p><button class="text-button trend-link" @click="viewHourly">查看 24 小时趋势 <ArrowRight /></button></template
								>
							</section>
						</div>
					<div class="metric-grid" v-if="forecast">
						<article class="metric">
							<span><Sunny />区域气温范围</span
							><strong
								>{{ number(forecast.summary.temperature_min) }}<em>—</em>{{ number(forecast.summary.temperature_max) }}<small>°C</small></strong
							>
							<p>未来 24 小时 · 全部网格</p>
						</article>
						<article class="metric">
							<span><Drizzling />最大小时降水</span><strong>{{ number(forecast.summary.rain_max) }}<small>mm/h</small></strong>
							<p>区域单格点峰值</p>
						</article>
						<article class="metric">
							<span><WindPower />最大近地风速</span><strong>{{ number(forecast.summary.wind_max) }}<small>m/s</small></strong>
							<p>10 米高度 · 区域格点峰值</p>
						</article>
						<article class="metric alert-metric">
							<span><Bell />本次预报告警</span><strong>{{ forecast.warning_count }}<small>类天气过程</small></strong
							><button @click="page = 'warnings'">查看告警记录 <ArrowRight /></button>
						</article>
					</div>

						<section v-if="pointResult" class="panel hourly-panel">
							<div class="section-heading">
								<div>
									<h2 ref="hourlyHeading" tabindex="-1">格点逐小时预报</h2>
									<p>气温与逐小时降水 · 北京时间</p>
								</div>
								<span class="chart-key">● 气温 <span>▰ 降水</span></span>
							</div>
							<ForecastChart :rows="pointResult.hourly" />
							<details>
								<summary>查看全部逐小时数值</summary>
								<div class="table-scroll">
									<table>
										<thead>
											<tr>
												<th>预报时间</th>
												<th>气温 °C</th>
												<th>风速 m/s</th>
												<th>风向 °</th>
												<th>湿度 %</th>
												<th>降水 mm</th>
												<th>气压 hPa</th>
											</tr>
										</thead>
										<tbody>
											<tr v-for="r in pointResult.hourly" :key="r.time">
												<td>{{ date(r.time) }}</td>
												<td>{{ number(r.t2m) }}</td>
												<td>{{ number(r.wind) }}</td>
												<td>{{ number(r.wind_direction, 0) }}</td>
												<td>{{ number(r.rh) }}</td>
												<td>{{ number(r.precip) }}</td>
												<td>{{ number(r.msl) }}</td>
											</tr>
										</tbody>
									</table>
								</div>
							</details>
						</section>
					</template>
				</template>

				<template v-else-if="page === 'data'">
					<div class="two-columns">
						<section class="panel">
							<div class="section-heading">
								<div>
									<h2>{{ isDemo ? '演示数据' : '导入气象数据' }}</h2>
									<p>NetCDF 格式 · 最大 100 MB</p>
								</div>
								<FolderOpened class="section-icon" />
							</div>
							<div v-if="isDemo" class="demo-feature-note">
								<strong>合成数据下载</strong>
								<p>480 小时合成资料，可在下方下载 NetCDF 并在本地复现。实际资料导入需运行完整系统。</p>
								<a :href="`${repositoryUrl}#本地运行完整系统`" target="_blank" rel="noopener noreferrer">查看安装与导入说明 ↗</a>
							</div>
							<form v-else @submit.prevent="importData" class="stack-form">
								<label
									>选择文件<input
										type="file"
										accept=".nc,.netcdf"
										@change="uploadFile = ($event.target as HTMLInputElement).files?.[0] || null"
										required
										:disabled="!admin"
								/></label>
								<div class="control-row">
									<label class="grow"
										>来源<select v-model="importSource">
											<option>ERA5</option>
											<option>GFS</option>
											<option value="other">其他网格资料</option>
										</select></label
									><label class="grow"
										>目标网格<select v-model.number="gridSize">
											<option :value="16">16 × 16 · 快速验证</option>
											<option :value="32">32 × 32</option>
											<option :value="64">64 × 64</option>
										</select></label
									>
								</div>
								<label class="checkbox"><input type="checkbox" v-model="hourly" required />确认降水已转换为逐小时增量，非累计降水</label
								><button class="primary" :disabled="!admin || !uploadFile || !hourly || isBusy">校验并导入 <ArrowRight /></button>
							</form>
							<p class="help">
								支持 t2m、u10、v10、rh、precip、msl 六个变量，以及 time / lat / lon 坐标。识别 ERA5 常用别名和 K、Pa、m
								单位。须先在数据源下载并裁剪目标区域。
							</p>
						</section>
						<section class="panel data-guide">
							<h2>导入校验规则</h2>
							<ul>
								<li>逐小时连续时间，至少 12 小时</li>
								<li>缺失不超过 5%，仅填充短时内部缺口</li>
								<li>按时间划分：训练 70% · 验证 15% · 测试 15%</li>
								<li>标准化参数只从训练分区计算</li>
							</ul>
							<button v-if="!isDemo" class="secondary" :disabled="!admin || isBusy" @click="createDemo">创建合成演示数据</button>
							<p class="help">演示数据为 480 小时、16 × 16 网格，仅验证软件功能，不用于证明预报精度。</p>
						</section>
					</div>
					<section class="panel">
						<div class="section-heading">
							<div>
								<h2>
									数据集目录 <span class="count">{{ overview.datasets.length }}</span>
								</h2>
								<p>{{ isDemo ? '合成实验资料 · 下载后可在本地复现' : '查看时间范围、网格覆盖与数据质量' }}</p>
							</div>
						</div>
						<div v-if="!overview.datasets.length" class="empty">还没有数据集。管理员可在上方导入或创建演示数据。</div>
						<div class="dataset-card" v-for="d in overview.datasets" :key="d.id">
							<div class="dataset-icon"><FolderOpened /></div>
							<div class="dataset-info">
								<h3>
									{{ d.name }} <span class="tag" :class="{ synthetic: d.source === 'synthetic' }">{{ sourceName(d.source) }}</span>
								</h3>
								<p>{{ date(d.start) }} — {{ date(d.end) }} · {{ d.hours }} 小时 · {{ d.shape.join(' × ') }} 网格</p>
								<p>
									经度 {{ number(d.bounds[0], 2) }}° 至 {{ number(d.bounds[2], 2) }}° · 纬度 {{ number(d.bounds[1], 2) }}° 至 {{ number(d.bounds[3], 2) }}° ·
									{{ d.trainable ? '可构建 24 小时训练窗口' : '仅满足推理，训练时长不足' }}
								</p>
								<div class="dataset-notes" v-if="d.notes.length">{{ d.notes.join('；') }}</div>
							</div>
							<button class="secondary" :disabled="isBusy || downloading" @click="download(`/datasets/${d.id}/download`)"><Download />导出</button>
						</div>
					</section>
				</template>

				<template v-else-if="page === 'training'">
					<section class="panel">
						<div class="section-heading">
							<div>
								<h2>{{ isDemo ? '训练记录与评估' : '启动模型训练' }}</h2>
								<p>Swin Transformer / ConvLSTM · 逐小时网格预测</p>
							</div>
							<span class="tag">{{ isDemo ? '记录快照' : (health.model_available ? '运行环境已就绪' : '需安装 PyTorch') }}</span>
						</div>
						<div v-if="isDemo" class="demo-feature-note">
							<strong>合成数据训练记录</strong>
							<p>展示已完成的训练日志与独立测试分区指标。新建训练任务需运行本地完整系统。</p>
							<a :href="`${repositoryUrl}#本地运行完整系统`" target="_blank" rel="noopener noreferrer">查看复现方法 ↗</a>
						</div>
						<form v-else class="control-row" @submit.prevent="train">
							<label class="grow"
								>训练数据集<select required v-model="datasetId">
									<option value="" disabled>选择数据集</option>
									<option v-for="d in overview.datasets" :key="d.id" :value="d.id">{{ d.name }}</option>
								</select></label
							><label>训练轮数<input type="number" min="3" max="60" v-model.number="epochs" required /></label
							><label>每轮训练窗口上限<input type="number" min="2" max="128" v-model.number="samples" required /></label
							><button class="primary" :disabled="!admin || !selectedDataset?.trainable || !health.model_available || running || isBusy">
								{{ running ? '训练进行中' : '开始训练' }} <ArrowRight />
							</button>
						</form>
						<details class="method-details"><summary>训练方法与适用范围</summary><p class="help">按 1 → 6 → 24 小时进行课程学习，使用 AdamW、梯度裁剪和验证集早停。窗口在各时间分区内构造，并按上限等间隔抽取；结果仅代表当前数据集。</p></details>
						<p class="help" v-if="!admin && !isDemo">需管理员登录后启动训练。</p>
					</section>
					<section class="panel" v-for="job in overview.jobs" :key="job.id">
						<div class="section-heading">
							<div>
								<h2>{{ job.dataset_name }}</h2>
								<p>{{ date(job.created_at) }} · {{ sourceName(job.source) }} · 任务 {{ job.id.slice(0, 8) }}</p>
							</div>
							<span class="tag" :class="{ failed: job.status === 'failed' }">{{ statuses[job.status] }}</span>
						</div>
						<div class="training-progress">
							<progress :value="job.progress" max="100" /><strong>{{ job.progress }}%</strong>
						</div>
						<p class="help">{{ job.message }}</p>
						<div v-if="job.logs.length" class="table-scroll">
							<table>
								<thead>
									<tr>
										<th>轮次</th>
										<th>预测时效</th>
										<th>训练损失</th>
										<th>验证损失</th>
										<th>累计用时</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="log in job.logs" :key="log.epoch">
										<td>{{ log.epoch }}</td>
										<td>{{ log.horizon }} h</td>
										<td>{{ number(log.loss, 5) }}</td>
										<td>{{ number(log.validation_loss, 5) }}</td>
										<td>{{ number(log.elapsed_seconds) }} s</td>
									</tr>
								</tbody>
							</table>
						</div>
						<template v-if="job.metrics"
							><div class="evaluation-heading">
								<h3>测试分区评估 · 模型 vs 持续性基线</h3>
								<p>{{ job.metrics.test_windows }} 个固定测试窗口 · {{ job.parameters.toLocaleString() }} 参数 · 仅代表当前数据集</p>
							</div>
							<div class="table-scroll">
								<table>
									<thead>
										<tr>
											<th>要素</th>
											<th>模型 RMSE</th>
											<th>基线 RMSE</th>
											<th>模型 MAE</th>
											<th>模型 ACC</th>
										</tr>
									</thead>
									<tbody>
										<tr v-for="(v, key) in health.variables" :key="key">
											<td>{{ v.label }} ({{ v.unit }})</td>
											<td>{{ number(job.metrics.model[key].rmse, 3) }}</td>
											<td>{{ number(job.metrics.persistence[key].rmse, 3) }}</td>
											<td>{{ number(job.metrics.model[key].mae, 3) }}</td>
											<td>{{ number(job.metrics.model[key].acc, 3) }}</td>
										</tr>
									</tbody>
								</table>
							</div>
							<p class="help">RMSE、MAE 衡量预测误差，越小越好；ACC 衡量距平相关性，越接近 1 越好。</p>
							<p class="help">
								≥1 mm 降水：CSI {{ number(job.metrics.model.precipitation.csi, 3) }} / POD {{ number(job.metrics.model.precipitation.pod, 3) }} / FAR
								{{ number(job.metrics.model.precipitation.far, 3) }}。{{ job.metrics.crps_note }}。
							</p></template
						>
					</section>
					<div v-if="!overview.jobs.length" class="panel empty">
						<Cpu />
						<h2>还没有训练任务</h2>
						<p>准备至少 240 小时数据，开始第一轮课程学习实验。</p>
					</div>
				</template>

				<template v-else-if="page === 'warnings'">
					<section class="panel">
						<div class="section-heading">
							<div>
								<h2>告警阈值</h2>
								<p>区域任意格点达到阈值，即生成对应天气过程记录</p>
							</div>
							<span class="tag">阈值记录</span>
						</div>
						<dl v-if="isDemo" class="threshold-summary"><div><dt>短时强降水</dt><dd>{{ thresholds.precip }} <small>mm/h</small></dd></div><div><dt>大风</dt><dd>{{ thresholds.wind }} <small>m/s</small></dd></div><div><dt>高温</dt><dd>{{ thresholds.temperature }} <small>°C</small></dd></div></dl>
						<form v-else class="control-row" @submit.prevent="saveThresholds">
							<label class="grow"
								>短时强降水 (mm/h)<input
									type="number"
									min="1"
									max="300"
									step="0.1"
									v-model.number="thresholds.precip"
									required
									:disabled="!admin" /></label
							><label class="grow"
								>大风 (m/s)<input type="number" min="1" max="100" step="0.1" v-model.number="thresholds.wind" required :disabled="!admin" /></label
							><label class="grow"
								>高温 (°C)<input
									type="number"
									min="20"
									max="60"
									step="0.1"
									v-model.number="thresholds.temperature"
									required
									:disabled="!admin" /></label
							><button v-if="!isDemo" class="primary" :disabled="!admin || isBusy">保存阈值</button>
						</form>
						<p class="help">{{ isDemo ? '快照中的阈值设置。在线演示不生成或发布告警。' : '修改仅影响后续预报。这里的告警不采用官方预警等级，不对外自动发布通知。' }}</p>
					</section>
					<section class="panel">
						<div class="section-heading">
							<div>
								<h2>
									天气过程记录 <span class="count">{{ visibleWarnings.length }}</span>
								</h2>
								<p>同一次预报按天气类型归并，并记录峰值与影响范围</p>
							</div>
							<label class="checkbox"><input type="checkbox" v-model="showExpired" />包含已过期</label>
						</div>
						<div v-if="!visibleWarnings.length" class="empty">
							<CircleCheck />
							<h2>{{ isDemo ? '本次快照无告警记录' : '当前没有有效告警' }}</h2>
							<p>{{ isDemo ? '本次合成预报未达到设置的阈值，不代表现实天气状况。' : '生成新预报后，系统会自动检查每个格点。' }}</p>
						</div>
						<article class="warning-card" v-for="w in visibleWarnings" :key="w.id">
							<div class="warning-icon"><Warning /></div>
							<div>
								<h3>
									{{ w.title }} <span class="tag" :class="{ synthetic: w.source === 'synthetic' }">{{ sourceName(w.source) }}</span>
									<span class="tag" v-if="w.expired">已过期</span>
								</h3>
								<p>{{ date(w.valid_start) }} — {{ date(w.valid_end) }} · {{ w.affected_cells }} 个格点</p>
								<p>峰值 {{ number(w.peak) }} {{ w.unit }} / 阈值 {{ number(w.threshold) }} {{ w.unit }}</p>
								<p class="help">
									峰值位置 {{ number(w.lon, 2) }}°E，{{ number(w.lat, 2) }}°N · {{ w.engine === 'persistence' ? '持续性基线' : 'MeteoFormer 原型' }} ·
									预报 {{ w.forecast_id.slice(0, 8) }}
								</p>
							</div>
							<button v-if="!isDemo" class="secondary" :disabled="!admin || w.acknowledged || isBusy" @click="acknowledge(w.id)">
								{{ w.acknowledged ? '已确认' : '确认已读' }}
							</button>
						</article>
					</section>
				</template>
				<footer class="workspace-footer"><span>MeteoFormer · 实验预报不作为官方气象预警</span><span v-if="isDemo" class="footer-links"><a :href="repositoryUrl" target="_blank" rel="noopener noreferrer">GitHub 源码</a><a :href="`${repositoryUrl}#本地运行完整系统`" target="_blank" rel="noopener noreferrer">本地运行</a></span></footer>
			</main>
		</div>
		<aside v-if="downloadState !== 'idle'" class="download-tray" aria-label="文件下载">
			<div class="download-heading"><Download /><strong role="status">{{ downloadTitle }}</strong><button v-if="!downloading" class="icon-button" aria-label="关闭下载提示" @click="closeDownload"><Close /></button></div>
			<p class="download-filename">{{ downloadFilename }}</p>
			<template v-if="downloading"><progress aria-label="文件下载进度" :value="downloadPercent" max="100" /><div class="download-details"><span>{{ downloadSize }}<template v-if="downloadPercent !== undefined"> · {{ downloadPercent }}%</template></span><button class="text-button" @click="cancelDownload">取消下载</button></div></template>
			<p v-if="downloadMessage" class="download-error" role="alert">{{ downloadMessage }}</p>
			<button v-if="downloadState === 'error' || downloadState === 'cancelled'" class="text-button" @click="retryDownload"><Refresh />重新下载</button>
		</aside>
		<dialog v-if="!isDemo" ref="loginDialog" class="login-modal" aria-labelledby="login-title" @close="loginOpen = false" @cancel="loginOpen = false">
				<button class="modal-close icon-button" aria-label="关闭登录" @click="loginOpen = false"><Close /></button>
				<div class="login-symbol"><Lock /></div>
				<h2 id="login-title">进入管理员模式</h2>
				<p>管理气象数据、训练模型与告警阈值</p>
				<form @submit.prevent="login">
					<label>管理员密码<input type="password" v-model="password" autocomplete="current-password" required autofocus /></label>
					<p class="modal-error" v-if="error" role="alert">{{ error }}</p>
					<button class="primary" :disabled="isBusy">{{ isBusy ? '正在验证…' : '登录' }}</button>
				</form>
				<p class="help">首次启动生成的密码位于后端数据目录。部署时可通过 METEO_ADMIN_PASSWORD 配置。</p>
		</dialog>
	</div>
</template>
