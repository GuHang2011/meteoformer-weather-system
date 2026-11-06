// Per-variable continuous palettes. Values are mapped using one forecast-wide scale.
export const palettes: Record<string, string[]> = {
	t2m: ['#344f91', '#358bad', '#67bcaf', '#b5cf83', '#e9cd6c', '#e69852', '#cb5651'],
	precip: ['#153247', '#234d68', '#367e9c', '#4eb6b5', '#a7d6a0', '#e5d366', '#d17b52'],
	wind: ['#273a66', '#4865a1', '#4ca3b0', '#7fc6ad', '#d7d18c', '#e39a65', '#c66480'],
	rh: ['#4e3a49', '#8f6964', '#c5a68d', '#bfd3c1', '#6eadaf', '#357a9b', '#264b7d'],
	msl: ['#405789', '#6b93ab', '#a0bfc3', '#e2dcc2', '#d5b58b', '#b68070', '#8b535e'],
};

export function rgbAt(value: number, min: number, max: number, variable: string) {
	const colors = palettes[variable] || palettes.t2m;
	const p = Math.max(0, Math.min(1, (value - min) / (max - min || 1))) * (colors.length - 1);
	const lower = Math.floor(p),
		upper = Math.min(colors.length - 1, lower + 1),
		ratio = p - lower;
	const parts = (color: string) => [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
	const a = parts(colors[lower]),
		b = parts(colors[upper]);
	return a.map((c, i) => Math.round(c + (b[i] - c) * ratio));
}
