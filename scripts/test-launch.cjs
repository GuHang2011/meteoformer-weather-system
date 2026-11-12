// Browser regressions for recoverable network failures and launch interactions.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const front = fs.existsSync(path.join(root, 'frontend')) ? 'frontend' : 'frontend';
const { chromium } = require(path.join(root, front, 'node_modules/playwright'));
const base = process.env.DEMO_URL || 'http://127.0.0.1:4176/meteoformer-weather-system/';
const output = path.join(root, 'outputs/launch');
const file = fs.readFileSync(path.join(root, front, 'demo-public/demo/forecast.nc'));

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const report = { checks: [], status: 'running' };
  let transferMode = 'partial';
  // A real chunked transfer exercises progress and cancellation through fetch.
  const server = http.createServer((req, res) => {
    res.writeHead(200, { 'Access-Control-Allow-Origin': '*', 'Content-Type': 'application/x-netcdf', 'Content-Length': file.length });
    res.write(file.subarray(0, 65536));
    if (transferMode === 'complete') res.end(file.subarray(65536));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const streamUrl = `http://127.0.0.1:${server.address().port}/forecast.nc`;
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [], downloads = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('download', d => downloads.push(d));
  try {
    await page.route('**/demo/snapshot.json', route => route.fulfill({ status: 503, body: 'Unavailable' }));
    await page.goto(base);
    await page.getByRole('button', { name: '重新连接', exact: true }).waitFor();
    assert.equal(await page.getByText('从第一份气象数据开始', { exact: true }).count(), 0);
    assert((await page.locator('.sidebar-status').innerText()).includes('未加载'));
    await page.unroute('**/demo/snapshot.json');
    await page.getByRole('button', { name: '重新连接', exact: true }).click();
    await page.locator('.point-weather strong').waitFor();
    report.checks.push('snapshot HTTP failure has retry; retry recovers without page reload');

    const snapshot = await (await page.request.get(base + 'demo/snapshot.json')).json();
    for (const [label, field, fullLabel] of [['气温', 't2m', '2 米气温'], ['降水', 'precip', '小时降水'], ['风速', 'wind', '10 米风速'], ['湿度', 'rh', '相对湿度'], ['气压', 'msl', '海平面气压']]) {
      await page.getByRole('button', { name: new RegExp('^' + label) }).click();
      assert.equal(await page.locator('.point-temp-label').innerText(), fullLabel);
      const coords = await page.locator('.point-panel > .help').innerText();
      const [lon, lat] = coords.match(/[\d.]+/g).map(Number);
      const nearest = (values, value) => values.reduce((b, v, i) => Math.abs(v-value) < Math.abs(values[b]-value) ? i : b, 0);
      const expected = Number(snapshot.data.fields[field][0][nearest(snapshot.data.lat, lat)][nearest(snapshot.data.lon, lon)].toFixed(3)).toFixed(1);
      assert((await page.locator('.point-weather strong').innerText()).startsWith(expected), `${field} point reading`);
    }
    assert(await page.getByRole('button', { name: '上一小时', exact: true }).isDisabled());
    await page.getByRole('button', { name: '下一小时', exact: true }).click();
    assert.equal(await page.getByRole('slider', { name: '预报时效' }).inputValue(), '2');
    await page.getByRole('slider', { name: '预报时效' }).fill('24');
    assert(await page.getByRole('button', { name: '下一小时', exact: true }).isDisabled());
    await page.getByRole('button', { name: '查看 24 小时趋势', exact: true }).click();
    await page.waitForFunction(() => document.activeElement.textContent === '格点逐小时预报');
    await page.getByRole('button', { name: '气象数据', exact: true }).click();
    await page.waitForFunction(() => window.scrollY === 0 && document.activeElement.tagName === 'H1');
    assert.equal(await page.title(), '气象数据 · MeteoFormer');
    report.checks.push('all point headline fields match source values; hour boundaries; trend focus and navigation reset');

    await page.getByRole('button', { name: '预报工作台', exact: true }).click();
    await page.route('**/demo/forecast.nc', route => route.fulfill({ status: 307, headers: { location: streamUrl } }));
    await page.getByRole('button', { name: 'NetCDF 下载', exact: true }).click();
    await page.waitForFunction(() => { const p = document.querySelector('.download-tray progress'); return p && p.value > 0 && p.value < 100; });
    assert(await page.getByRole('button', { name: 'NetCDF 下载', exact: true }).isDisabled());
    await page.getByRole('button', { name: '气象数据', exact: true }).click();
    await page.getByRole('heading', { name: '气象数据', exact: true }).waitFor();
    assert(await page.getByRole('button', { name: '导出', exact: true }).isDisabled());
    await page.setViewportSize({ width: 390, height: 844 });
    const tray = await page.locator('.download-tray').boundingBox();
    const nav = await page.locator('.sidebar').boundingBox();
    assert(tray.y + tray.height < nav.y && tray.x >= 0 && tray.x + tray.width <= 390);
    await page.getByRole('button', { name: '取消下载', exact: true }).click();
    await page.getByText('下载已取消', { exact: true }).waitFor();
    assert.equal(downloads.length, 0);
    transferMode = 'complete';
    const nextDownload = page.waitForEvent('download');
    await page.getByRole('button', { name: '重新下载', exact: true }).click();
    const downloaded = await nextDownload;
    await downloaded.saveAs(path.join(output, 'retried-forecast.nc'));
    assert(fs.readFileSync(path.join(output, 'retried-forecast.nc')).equals(file));
    await page.getByRole('button', { name: '关闭下载提示', exact: true }).click();
    report.checks.push('real transfer progress; cancel saves no file; browsing remains usable; retry preserves file bytes; mobile tray clears navigation');

    await page.getByRole('button', { name: '预报工作台', exact: true }).click();
    transferMode = 'partial';
    await page.clock.install();
    await page.getByRole('button', { name: 'NetCDF 下载', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.download-tray progress')?.value > 0);
    await page.clock.fastForward(31000);
    await page.getByText('30 秒未收到新数据，请检查网络后重试。', { exact: true }).waitFor();
    assert.equal(downloads.length, 1);
    await page.getByRole('button', { name: '关闭下载提示', exact: true }).click();
    await page.clock.resume();
    await page.unroute('**/demo/forecast.nc');
    await page.route('**/demo/forecast.nc', route => route.fulfill({ status: 503, body: 'Unavailable' }));
    await page.getByRole('button', { name: 'NetCDF 下载', exact: true }).click();
    await page.getByText('下载未完成', { exact: true }).waitFor();
    assert((await page.locator('.download-error').innerText()).includes('503'));
    await page.unroute('**/demo/forecast.nc');
    const recovered = page.waitForEvent('download');
    await page.getByRole('button', { name: '重新下载', exact: true }).click();
    await (await recovered).saveAs(path.join(output, 'recovered-forecast.nc'));
    assert(fs.readFileSync(path.join(output, 'recovered-forecast.nc')).equals(file));
    report.checks.push('stalled transfer timeout; HTTP failure and retry recover with correct bytes');
    assert.deepEqual(errors, []);
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed'; report.error = error.message;
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true });
    throw error;
  } finally {
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
    await browser.close();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
