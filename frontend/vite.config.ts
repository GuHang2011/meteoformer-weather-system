import vue from '@vitejs/plugin-vue';
import { defineConfig } from 'vite';
import { resolve } from 'path';
export default defineConfig(({ mode }) => ({
	plugins: [vue()],
	base: mode === 'demo' ? '/meteoformer-weather-system/' : '/',
	publicDir: mode === 'demo' ? 'demo-public' : 'weather-public',
	resolve: { alias: { '/@': resolve(__dirname, 'src') } },
	server: {
		host: '127.0.0.1',
		port: 5173,
		strictPort: true,
		open: false,
		proxy: { '/api': { target: 'http://127.0.0.1:8016', changeOrigin: true } },
	},
	build: { outDir: mode === 'demo' ? 'demo-dist' : 'weather-dist', target: ['chrome90', 'edge90', 'firefox90', 'safari15.4'] },
}));
