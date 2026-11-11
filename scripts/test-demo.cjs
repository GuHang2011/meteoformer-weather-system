const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const frontend = fs.existsSync(path.join(root, 'frontend')) ? 'frontend' : 'frontend';
const { chromium } = require(path.join(root, frontend, 'node_modules/playwright'));
const base = process.env.DEMO_URL || 'http://127.0.0.1:4176/meteoformer-weather-system/';
(async () => {
  const out = path.join(root, 'outputs/online-demo'); fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
  const errors = [], apiRequests = [], failedResponses = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => { if (new URL(r.url()).pathname.startsWith('/api')) apiRequests.push(r.url()); });
  page.on('response', r => { if (r.status() >= 400) failedResponses.push(`${r.status()} ${r.url()}`); });
  const report = { url: base, checks: [], status: 'running' };
  try {
    await page.goto(base, { waitUntil: 'networkidle' });
    await page.locator('.map-coast').first().waitFor();
    await page.locator('.point-weather strong').waitFor();
    await page.evaluate(() => document.fonts.ready);
    assert((await page.locator('.demo-banner').innerText()).includes('只读快照'));
    assert.equal(await page.getByRole('button', { name: /管理员登录/ }).count(), 0);
    assert((await page.locator('.sidebar-status').innerText()).includes('演示快照已加载'));
    report.checks.push('public demo label; no login; snapshot status');
    await page.getByRole('link', { name: 'NASA Blue Marble · 静态地形', exact: true }).waitFor();
    assert(await page.locator('.map-river').count() > 0);
    assert(await page.locator('.map-lake').count() > 0);
    await page.getByRole('button', { name: '简图', exact: true }).click();
    assert.equal(await page.locator('.map-relief').count(), 0);
    await page.getByRole('button', { name: '地形', exact: true }).click();
    await page.locator('.map-relief').waitFor();
    report.checks.push('local NASA terrain, Natural Earth rivers/lakes, attribution and basemap switching');
    for (const label of ['降水', '风速', '湿度', '气压', '气温']) {
      await page.getByRole('button', { name: new RegExp('^' + label) }).click();
      await page.waitForTimeout(80);
      assert.equal(await page.locator('.notice.error').count(), 0);
    }
    const scale = await page.locator('.scale-ticks').innerText();
    const first = await page.locator('.point-weather strong').innerText();
    await page.getByRole('slider', { name: '预报时效' }).fill('24');
    await page.waitForTimeout(100);
    assert.equal(await page.locator('.scale-ticks').innerText(), scale);
    assert.notEqual(await page.locator('.point-weather strong').innerText(), first);
    await page.getByRole('button', { name: '原始网格', exact: true }).click();
    assert.equal(await page.getByRole('button', { name: '原始网格', exact: true }).getAttribute('aria-pressed'), 'true');
    await page.getByRole('button', { name: '连续显示', exact: true }).click();
    await page.getByRole('button', { name: '放大地图', exact: true }).click();
    await page.getByRole('button', { name: '重置地图', exact: true }).click();
    report.checks.push('five fields; 24h changing forecast; fixed color scale; raw/smooth and zoom');
    await page.getByRole('spinbutton', { name: '经度', exact: true }).fill('120.5');
    await page.getByRole('spinbutton', { name: '纬度', exact: true }).fill('31.5');
    await page.getByRole('button', { name: '查询预报', exact: true }).click();
    await page.locator('.point-weather strong').waitFor();
    const snapshot = await (await page.request.get(base + 'demo/snapshot.json')).json();
    const nearest = (coords, value) => coords.reduce((best, x, i) => Math.abs(x-value) <= Math.abs(coords[best]-value) ? i : best, 0);
    const x = nearest(snapshot.data.lon, 120.5), y = nearest(snapshot.data.lat, 31.5);
    const expected = snapshot.data.fields.t2m[23][y][x].toFixed(1);
    assert((await page.locator('.point-weather strong').innerText()).startsWith(expected));
    await page.getByRole('spinbutton', { name: '经度', exact: true }).fill('100');
    await page.getByRole('button', { name: '查询预报', exact: true }).click();
    await page.getByText('查询点超出当前预报覆盖范围', { exact: true }).waitFor();
    await page.getByRole('spinbutton', { name: '经度', exact: true }).fill('120.5');
    await page.getByRole('button', { name: '查询预报', exact: true }).click();
    await page.locator('.point-weather strong').waitFor();
    assert.equal(await page.locator('.notice.error').count(), 0);
    report.checks.push('nearest grid point matches snapshot; out-of-bounds error recovers');
    async function download(button, filename, signature) {
      const [file] = await Promise.all([page.waitForEvent('download'), button.click()]);
      assert.equal(file.suggestedFilename(), filename);
      const destination = path.join(out, filename); await file.saveAs(destination);
      const bytes = fs.readFileSync(destination); assert(bytes.subarray(0, signature.length).equals(signature));
    }
    await download(page.getByRole('button', { name: 'NetCDF 下载' }), 'forecast.nc', Buffer.from('CDF'));
    await download(page.getByRole('button', { name: '下载当前气象图片' }), 't2m-24h.png', Buffer.from([137,80,78,71]));
    report.checks.push('valid NetCDF and selected-lead PNG download');
    await page.getByRole('slider', { name: '预报时效' }).fill('1');
    await page.waitForTimeout(100);
    for (const [width, height] of [[1600,1100], [1440,900], [1024,900], [768,1000], [390,844], [320,740]]) {
      await page.setViewportSize({ width, height });
      await page.waitForTimeout(120);
      await page.evaluate(() => window.scrollTo(0, 0));
      assert(!(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)), `overflow: ${width}`);
      const canvas = await page.locator('.map-canvas').boundingBox();
      const coverage = await page.locator('.coverage-boundary').boundingBox();
      assert(coverage.x >= canvas.x - 1 && coverage.y >= canvas.y - 1 && coverage.x + coverage.width <= canvas.x + canvas.width + 1 && coverage.y + coverage.height <= canvas.y + canvas.height + 1, `forecast coverage clipped: ${width}`);
      if (width === 1440 || width === 390) {
        await page.locator('.map-canvas').scrollIntoViewIfNeeded();
        const target = await page.locator('.coverage-boundary').boundingBox();
        await page.mouse.click(target.x + target.width * 0.35, target.y + target.height * 0.35);
        const lon = snapshot.data.lon[0] + (snapshot.data.lon.at(-1) - snapshot.data.lon[0]) * 0.35;
        const lat = snapshot.data.lat.at(-1) - (snapshot.data.lat.at(-1) - snapshot.data.lat[0]) * 0.35;
        assert.equal(Number(await page.getByRole('spinbutton', { name: '经度', exact: true }).inputValue()), snapshot.data.lon[nearest(snapshot.data.lon, lon)]);
        assert.equal(Number(await page.getByRole('spinbutton', { name: '纬度', exact: true }).inputValue()), snapshot.data.lat[nearest(snapshot.data.lat, lat)]);
        await page.locator('.point-weather strong').waitFor();
        await page.evaluate(() => window.scrollTo(0, 0));
      }
      if (width >= 1440) {
        const timeline = await page.locator('.timeline').boundingBox();
        assert(timeline.y + timeline.height <= height, `forecast timeline below viewport: ${width}`);
      }
      await page.screenshot({ path: path.join(out, `workspace-${width}.png`), fullPage: width < 500 });
    }
    report.checks.push('responsive at 320/390/768/1024/1440/1600 px; full forecast coverage remains visible');
    await page.setViewportSize({ width: 1440, height: 1000 });
    for (const name of ['气象数据', '训练记录', '阈值告警']) {
      await page.getByRole('button', { name, exact: true }).click();
      await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: true });
      if (name === '气象数据') await download(page.getByRole('button', { name: '导出', exact: true }), 'dataset.nc', Buffer.from('CDF'));
      if (name === '训练记录') {
        assert((await page.locator('main').innerText()).includes('90,926'));
        assert.equal(await page.getByRole('button', { name: '开始训练' }).count(), 0);
      }
    }
    await page.reload({ waitUntil: 'networkidle' });
    assert.equal(await page.locator('h1').innerText(), '阈值告警');
    assert.deepEqual(apiRequests, []); assert.deepEqual(errors, []); assert.deepEqual(failedResponses, []);
    report.checks.push('all pages and hash refresh; no backend requests, HTTP failures or runtime errors');
    const fallback = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await fallback.route('**/geography/east-asia-relief.webp', route => route.abort());
    await fallback.goto(base, { waitUntil: 'networkidle' });
    await fallback.getByText('地形加载失败，已显示简图', { exact: true }).waitFor();
    assert.equal(await fallback.getByRole('button', { name: '简图', exact: true }).getAttribute('aria-pressed'), 'true');
    assert(await fallback.locator('.map-coast').count() > 0);
    await fallback.locator('.point-weather strong').waitFor();
    await fallback.close();
    report.checks.push('terrain download failure falls back to a usable geographic map');
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed'; report.error = error.message;
    await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true });
    throw error;
  } finally {
    fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2)); await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
