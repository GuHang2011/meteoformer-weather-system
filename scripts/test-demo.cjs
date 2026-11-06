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
    assert((await page.locator('.demo-banner').innerText()).includes('只读快照'));
    assert.equal(await page.getByRole('button', { name: /管理员登录/ }).count(), 0);
    assert((await page.locator('.sidebar-status').innerText()).includes('演示快照已加载'));
    report.checks.push('public demo label; no login; snapshot status');
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
    for (const [width, height] of [[1600,1100], [1440,1000], [768,1000], [390,844], [320,740]]) {
      await page.setViewportSize({ width, height });
      await page.evaluate(() => window.scrollTo(0, 0));
      assert(!(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)), `overflow: ${width}`);
      await page.screenshot({ path: path.join(out, `workspace-${width}.png`), fullPage: width < 500 });
    }
    report.checks.push('responsive at 320/390/768/1440/1600 px');
    await page.setViewportSize({ width: 1440, height: 1000 });
    for (const name of ['气象数据', '模型实验室', '天气告警']) {
      await page.getByRole('button', { name, exact: true }).click();
      await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: true });
      if (name === '气象数据') await download(page.getByRole('button', { name: '导出', exact: true }), 'dataset.nc', Buffer.from('CDF'));
      if (name === '模型实验室') {
        assert((await page.locator('main').innerText()).includes('90,926'));
        assert.equal(await page.getByRole('button', { name: '开始训练' }).count(), 0);
      }
    }
    await page.reload({ waitUntil: 'networkidle' });
    assert.equal(await page.locator('h1').innerText(), '天气告警');
    assert.deepEqual(apiRequests, []); assert.deepEqual(errors, []); assert.deepEqual(failedResponses, []);
    report.checks.push('all pages and hash refresh; no backend requests, HTTP failures or runtime errors');
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
