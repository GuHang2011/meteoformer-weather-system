/** Bound read requests so a dropped connection can recover without reloading the app. */
export async function fetchJson(url: string, options: RequestInit = {}) {
	const controller = new AbortController();
	const abort = () => controller.abort();
	if (options.signal?.aborted) abort();
	options.signal?.addEventListener('abort', abort, { once: true });
	let timedOut = false;
	// Mutations can include model inference; a timeout would not undo server-side work.
	const timeout = (!options.method || options.method.toUpperCase() === 'GET')
		? setTimeout(() => { timedOut = true; controller.abort(); }, 30000) : undefined;
	try {
		const response = await fetch(url, { ...options, signal: controller.signal });
		if (!response.ok) {
			let message = `服务暂时无法响应（${response.status}），请稍后重试。`;
			try {
				const data = await response.json();
				message = Array.isArray(data.detail) ? data.detail.map((item: any) => item.msg).join('；') : data.detail || message;
			} catch { /* A proxy may return an HTML error page. */ }
			throw new Error(message);
		}
		return await response.json();
	} catch (error) {
		if (timedOut) throw new Error('连接超时，请检查网络后重试。');
		if (error instanceof TypeError) throw new Error('网络连接失败，请检查网络后重试。');
		if (error instanceof SyntaxError) throw new Error('数据未完整加载，请重试。');
		throw error;
	} finally {
		clearTimeout(timeout);
		options.signal?.removeEventListener('abort', abort);
	}
}
