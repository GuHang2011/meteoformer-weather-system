import { computed, onUnmounted, ref } from 'vue';
import { demoDownload, isDemo } from './demo';

export function useDownload() {
	const state = ref<'idle' | 'loading' | 'saved' | 'error' | 'cancelled'>('idle');
	const filename = ref('');
	const received = ref(0);
	const total = ref(0);
	const message = ref('');
	let controller: AbortController | undefined;
	let lastPath = '';
	const active = computed(() => state.value === 'loading');
	const percent = computed(() => total.value ? Math.min(100, Math.round(received.value / total.value * 100)) : undefined);
	const bytes = (value: number) => value < 1024 * 1024 ? `${(value / 1024).toFixed(0)} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`;
	const size = computed(() => total.value ? `${bytes(received.value)} / ${bytes(total.value)}` : `${bytes(received.value)} 已接收`);
	const title = computed(() => ({ idle: '', loading: '正在下载', saved: '文件已交给浏览器保存', error: '下载未完成', cancelled: '下载已取消' }[state.value]));

	async function start(path: string) {
		if (active.value) return;
		lastPath = path;
		const current = new AbortController();
		controller = current;
		state.value = 'loading';
		filename.value = path.includes('/image') ? '预报图片.png' : path.startsWith('/datasets/') ? 'dataset.nc' : 'forecast.nc';
		received.value = 0;
		total.value = 0;
		message.value = '';
		let timeout: ReturnType<typeof setTimeout> | undefined;
		let stalled = false;
		const heartbeat = () => {
			clearTimeout(timeout);
			timeout = setTimeout(() => { stalled = true; current.abort(); }, 30000);
		};
		try {
			heartbeat();
			const file = isDemo ? await demoDownload(path) : null;
			if (current.signal.aborted) throw new DOMException('Cancelled', 'AbortError');
			const response = await fetch(file?.url || `/api${path}`, { signal: current.signal, credentials: 'same-origin' });
			if (!response.ok) throw new Error(`服务器暂时无法提供文件（${response.status}），请重试。`);
			filename.value = (file?.filename || response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] || filename.value).replace(/[\\/\r\n]/g, '_');
			const length = Number(response.headers.get('Content-Length'));
			// Encoded responses report wire length, not the decoded stream length.
			total.value = !response.headers.get('Content-Encoding') && Number.isFinite(length) && length > 0 ? length : 0;
			const reader = response.body?.getReader();
			let blob: Blob;
			if (reader) {
				const chunks: Uint8Array[] = [];
				try {
					while (true) {
						const { done, value } = await reader.read();
						if (done) break;
						chunks.push(value);
						received.value += value.byteLength;
						heartbeat();
					}
				} finally { reader.releaseLock(); }
				blob = new Blob(chunks, { type: response.headers.get('Content-Type') || 'application/octet-stream' });
			} else {
				blob = await response.blob();
				received.value = blob.size;
			}
			if (current.signal.aborted) throw new DOMException('Cancelled', 'AbortError');
			if (!blob.size || (total.value && blob.size !== total.value)) throw new Error('收到的文件不完整，请重新下载。');
			const objectUrl = URL.createObjectURL(blob);
			const anchor = document.createElement('a');
			anchor.href = objectUrl;
			anchor.download = filename.value;
			document.body.append(anchor);
			anchor.click();
			anchor.remove();
			setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
			state.value = 'saved';
		} catch (error) {
			if (controller !== current) return;
			if (current.signal.aborted && !stalled) state.value = 'cancelled';
			else {
				state.value = 'error';
				message.value = stalled ? '30 秒未收到新数据，请检查网络后重试。' : error instanceof TypeError ? '网络连接中断，请检查网络后重试。' : error instanceof Error ? error.message : '下载失败，请重试。';
			}
		} finally {
			clearTimeout(timeout);
			if (controller === current) controller = undefined;
		}
	}
	function cancel() { controller?.abort(); }
	function close() { if (!active.value) state.value = 'idle'; }
	onUnmounted(() => controller?.abort());
	return { state, filename, received, total, message, active, percent, size, title, start, cancel, close, retry: () => start(lastPath) };
}
