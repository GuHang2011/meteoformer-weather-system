import { isDemo, demoApi } from './demo';
export async function api(path: string, options: RequestInit = {}) {
	if (isDemo) return demoApi(path, options);
	const response = await fetch(`/api${path}`, {
		credentials: 'same-origin',
		...options,
		headers: { ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...options.headers },
	});
	if (!response.ok) {
		let message = `请求失败（${response.status}）`;
		try {
			const data = await response.json();
			message = Array.isArray(data.detail) ? data.detail.map((item: any) => item.msg).join('；') : data.detail || message;
		} catch {
			/* The proxy may return a non-JSON error page. */
		}
		throw new Error(message);
	}
	return response.json();
}

export const post = (path: string, body = {}) => api(path, { method: 'POST', body: JSON.stringify(body) });
export const date = (value: string) =>
	value
		? new Intl.DateTimeFormat('zh-CN', {
				timeZone: 'Asia/Shanghai',
				month: '2-digit',
				day: '2-digit',
				hour: '2-digit',
				minute: '2-digit',
				hour12: false,
		  }).format(new Date(value))
		: '—';
export const number = (value: number | null | undefined, digits = 1) =>
	typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
export const sourceName = (source: string) => (source === 'synthetic' ? '合成演示' : source === 'other' ? '用户导入' : source);
