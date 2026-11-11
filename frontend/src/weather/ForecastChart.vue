<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue';
const props = defineProps<{ rows: any[] }>();
const container = ref<HTMLElement | null>(null);
const width = ref(760);
let observer: ResizeObserver | undefined;
onMounted(() => {
	if (!container.value) return;
	observer = new ResizeObserver(([entry]) => { width.value = Math.max(1, entry.contentRect.width); });
	observer.observe(container.value);
});
onUnmounted(() => observer?.disconnect());
const validRows = computed(() => props.rows.filter((row) => Number.isFinite(row.t2m) && Number.isFinite(row.precip)));
const low = computed(() => Math.floor(Math.min(...validRows.value.map((row) => row.t2m)) - 2));
const high = computed(() => Math.ceil(Math.max(...validRows.value.map((row) => row.t2m)) + 2));
const rainMax = computed(() => Math.max(5, ...validRows.value.map((row) => row.precip)));
const plot = computed(() => ({ left: 36, right: width.value - 50, top: 34, bottom: 178 }));
const x = (index: number) => plot.value.left + index * (plot.value.right - plot.value.left) / Math.max(1, props.rows.length - 1);
const y = (temperature: number) => plot.value.bottom - (temperature - low.value) / (high.value - low.value) * (plot.value.bottom - plot.value.top);
const rainHeight = (rain: number) => rain / rainMax.value * (plot.value.bottom - plot.value.top);
const barWidth = computed(() => Math.max(2, Math.min(20, (plot.value.right - plot.value.left) / Math.max(1, props.rows.length) * 0.55)));
// Keep missing hours as gaps instead of connecting across them.
const line = computed(() => {
	let previousValid = false;
	return props.rows.map((row, index) => {
		if (!Number.isFinite(row.t2m)) { previousValid = false; return ''; }
		const command = previousValid ? 'L' : 'M';
		previousValid = true;
		return `${command}${x(index)},${y(row.t2m)}`;
	}).join(' ');
});
const tickIndices = computed(() => {
	const last = props.rows.length - 1;
	if (last < 0) return [];
	const step = width.value < 480 ? 8 : 4;
	return [...new Set([...Array.from({ length: Math.floor(last / step) + 1 }, (_, i) => i * step), last])];
});
const hour = (time: string) => new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', hour12: false, timeZone: 'Asia/Shanghai' }).format(new Date(time));
</script>

<template>
	<div class="forecast-chart-wrap" ref="container">
		<svg v-if="validRows.length" class="forecast-chart" :viewBox="`0 0 ${width} 224`" role="img" aria-label="未来24小时气温与降水曲线，完整数值见下方表格">
			<g v-for="i in 4" :key="i" class="chart-grid">
				<line :x1="plot.left" :x2="plot.right" :y1="plot.top + (i - 1) * 48" :y2="plot.top + (i - 1) * 48" />
				<text :x="plot.left - 8" :y="plot.top + (i - 1) * 48 + 4" text-anchor="end">{{ (high - (i - 1) * (high - low) / 3).toFixed(0) }}°</text>
				<text :x="plot.right + 8" :y="plot.top + (i - 1) * 48 + 4">{{ (rainMax * (4 - i) / 3).toFixed(1) }}</text>
			</g>
			<template v-for="(row, index) in rows" :key="row.time || index">
				<rect v-if="Number.isFinite(row.precip)" class="chart-rain" :x="x(index) - barWidth / 2" :y="plot.bottom - rainHeight(row.precip)" :width="barWidth" :height="rainHeight(row.precip)" rx="2">
					<title>{{ hour(row.time) }}时降水 {{ row.precip.toFixed(1) }} mm</title>
				</rect>
			</template>
			<path :d="line" class="chart-temperature" fill="none" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" />
			<g v-for="index in tickIndices" :key="index">
				<text :x="x(index)" y="204" text-anchor="middle" class="axis-label">{{ hour(rows[index].time) }}时</text>
			</g>
			<text :x="plot.left" y="16" class="axis-label">气温 °C</text>
			<text :x="plot.right" y="16" text-anchor="end" class="axis-label">降水 mm/h</text>
		</svg>
		<p v-else class="chart-empty">暂无逐小时预报数据</p>
	</div>
</template>
