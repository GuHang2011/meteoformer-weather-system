<script setup lang="ts">
import { computed } from 'vue';
const props = defineProps<{ rows: any[] }>();
const low = computed(() => Math.floor(Math.min(...props.rows.map((r) => r.t2m)) - 2));
const high = computed(() => Math.ceil(Math.max(...props.rows.map((r) => r.t2m)) + 2));
const rainMax = computed(() => Math.max(5, ...props.rows.map((r) => r.precip)));
const line = computed(() =>
	props.rows.map((r, i) => `${48 + (i * 652) / 23},${170 - ((r.t2m - low.value) / (high.value - low.value)) * 140}`).join(' ')
);
const hour = (time: string) => new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', hour12: false, timeZone: 'Asia/Shanghai' }).format(new Date(time));
</script>
<template>
	<svg class="forecast-chart" viewBox="0 0 760 220" role="img" aria-label="未来24小时气温与降水曲线，完整数值见下方表格">
		<g v-for="i in 4" :key="i" class="chart-grid">
			<line x1="48" x2="700" :y1="30 + (i - 1) * 46.66" :y2="30 + (i - 1) * 46.66" />
			<text x="38" :y="34 + (i - 1) * 46.66" text-anchor="end">{{ (high - ((i - 1) * (high - low)) / 3).toFixed(0) }}°</text>
			<text x="710" :y="34 + (i - 1) * 46.66">{{ ((rainMax * (4 - i)) / 3).toFixed(1) }}</text>
		</g>
		<rect
			v-for="(row, i) in rows"
			:key="i"
			:x="41 + (i * 652) / 23"
			:y="170 - (row.precip / rainMax) * 140"
			width="14"
			:height="(row.precip / rainMax) * 140"
			fill="#b6d9e3"
			rx="3"
		/>
		<polyline :points="line" fill="none" stroke="#167d73" stroke-width="3" stroke-linejoin="round" />
		<g v-for="i in [0, 4, 8, 12, 16, 20, 23]" :key="i">
			<text :x="48 + (i * 652) / 23" y="196" text-anchor="middle" class="axis-label">{{ rows[i] ? hour(rows[i].time) : '' }}时</text>
		</g>
		<text x="48" y="16" class="axis-label">气温 °C</text>
		<text x="700" y="16" text-anchor="end" class="axis-label">降水 mm/h</text>
	</svg>
</template>
