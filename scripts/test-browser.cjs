const { chromium } = require('../frontend/node_modules/playwright');
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const base = process.env.APP_URL || 'http://127.0.0.1:8016';

(async()=>{
  const root=path.resolve(__dirname,'..');
  const output=path.join(root,'outputs','browser');fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const report={checks:[],screenshots:[]};
  const check=(name)=>report.checks.push(name);
  try {
    await page.goto(base, {waitUntil:'networkidle'});
    await page.getByRole('heading',{name:'预报工作台',exact:true}).waitFor();
    assert(!await page.getByText('协作聊天',{exact:true}).count());
    assert(!await page.getByText('电子盖章',{exact:true}).count());
    check('weather-only navigation');
    await page.getByRole('button',{name:'访客 · 管理员登录'}).click();
    assert(await page.getByLabel('管理员密码',{exact:true}).evaluate(el=>el===document.activeElement));
    await page.keyboard.press('Escape');
    assert(await page.getByRole('button',{name:'访客 · 管理员登录'}).evaluate(el=>el===document.activeElement));
    await page.getByRole('button',{name:'访客 · 管理员登录'}).click();
    await page.getByLabel('管理员密码',{exact:true}).fill(fs.readFileSync(path.join(process.env.METEO_DATA_DIR || path.join(root,'backend/data'),'initial-admin-password.txt'),'utf8').trim());
    await page.getByRole('button',{name:'登录',exact:true}).click();
    await page.getByRole('button',{name:'管理员 · 退出'}).waitFor();
    check('administrator login');
    await page.getByRole('button',{name:'气象数据',exact:true}).click();
    if(!await page.locator('.dataset-card').count()) {
      await page.getByRole('button',{name:'创建合成演示数据'}).click();
      await page.locator('.dataset-card').first().waitFor();
    }
    check('demo dataset creation');
    await page.getByRole('button',{name:'预报与查询',exact:true}).click();
    if(!await page.locator('.generate-form').isVisible())await page.locator('.generate-details summary').click();
    await Promise.all([
      page.waitForResponse(r=>r.url().endsWith('/api/predict')&&r.status()===201),
      page.getByRole('button',{name:'生成预报',exact:true}).click(),
    ]);
    await page.locator('.notice.busy').waitFor({state:'hidden'});
    await page.locator('.point-weather strong').waitFor();
    await page.locator('.weather-map image').first().waitFor();
    check('forecast generation and point query');
    await Promise.all([page.waitForResponse(r=>r.url().includes('/forecast/grid')&&r.url().includes('precip')&&r.status()===200),page.getByRole('button',{name:'降水 mm/h',exact:true}).click()]);
    await Promise.all([page.waitForResponse(r=>r.url().includes('/forecast/grid')&&r.url().includes('lead=12')&&r.status()===200),page.getByRole('slider',{name:'预报时效'}).fill('12')]);
    check('weather variable and lead switching');
    await page.route('**/api/forecast/grid?**', route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'临时不可用'})}));
    await page.getByRole('button',{name:'下一小时',exact:true}).click();
    await page.getByRole('button',{name:'重试地图',exact:true}).waitFor();
    await page.unroute('**/api/forecast/grid?**');
    await page.getByRole('button',{name:'重试地图',exact:true}).click();
    await page.locator('.weather-map').waitFor();
    check('map HTTP failure and retry');
    await page.getByLabel('经度',{exact:true}).fill('0');
    await page.getByRole('button',{name:'查询预报',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'超出'}).waitFor();
    await page.getByLabel('经度',{exact:true}).fill('120.5');
    await page.getByRole('button',{name:'查询预报',exact:true}).click();
    await page.locator('.point-weather').waitFor();
    check('out-of-region error and recovery');
    const netcdf=page.waitForEvent('download');
    await page.getByRole('button',{name:'NetCDF 下载'}).click();
    await (await netcdf).saveAs(path.join(output,'forecast.nc'));
    const png=page.waitForEvent('download');
    await page.getByRole('button',{name:'下载当前气象图片'}).click();
    await (await png).saveAs(path.join(output,'field.png'));
    await page.getByRole('button',{name:'关闭下载提示',exact:true}).click();
    check('NetCDF and PNG downloads');
    await page.getByRole('button',{name:'预报工作台',exact:true}).click();
    await page.evaluate(()=>window.scrollTo(0,0));
    assert(await page.locator('.sidebar').evaluate(el=>getComputedStyle(el).position==='fixed'));
    check('fixed navigation on full-height pages');
    await page.screenshot({path:path.join(output,'desktop.png'),fullPage:true});report.screenshots.push('desktop.png');
    await page.screenshot({path:path.join(output,'desktop-viewport.png')});
    for(const width of [390,320]) {
      await page.setViewportSize({width,height:844});
      for(const nav of ['预报工作台','气象数据','训练记录','阈值告警']) {
        await page.getByRole('button',{name:nav,exact:true}).click();
        const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1);
        assert(!overflow, `${nav} horizontal overflow at ${width}px`);
      }
      await page.getByRole('button',{name:'预报工作台',exact:true}).click();
      await page.evaluate(()=>window.scrollTo(0,0));
      await page.screenshot({path:path.join(output,`mobile-${width}.png`),fullPage:true});report.screenshots.push(`mobile-${width}.png`);
    }
    check('320px and 390px responsive layouts');

    // Exercise training polling without starting a real training task or changing stored thresholds.
    const overview = await (await page.request.get(new URL('/api/overview', base).href)).json();
    const pollingContext = await browser.newContext({storageState:await page.context().storageState(),viewport:{width:1440,height:1000}});
    const pollingPage = await pollingContext.newPage();
    pollingPage.on('pageerror', error=>errors.push(`polling: ${error.message}`));
    const clockStart = Date.UTC(2026, 10, 13);
    await pollingPage.clock.install({time:clockStart});
    let overviewRequests=0, mapRequests=0, pointRequests=0, activePolls=0, peakPolls=0;
    let holdPoll=false, releasePoll, onHeldPoll;
    pollingPage.on('request', request=>{
      const pathname=new URL(request.url()).pathname;
      if(pathname==='/api/forecast/grid')mapRequests++;
      if(pathname==='/api/point')pointRequests++;
    });
    const pollTime = count => `08:${String(count).padStart(2,'0')}`;
    await pollingPage.route('**/api/overview', async route=>{
      const count=++overviewRequests;
      activePolls++;peakPolls=Math.max(peakPolls,activePolls);
      try {
        if(holdPoll) {
          const gate=new Promise(resolve=>{releasePoll=resolve;});
          onHeldPoll?.();
          await gate;
        }
        await route.fulfill({json:{...overview,
          server_time:new Date(clockStart+count*60000).toISOString(),
          jobs:[...overview.jobs,{id:'browser-polling-regression',status:'running',progress:count,
            dataset_id:overview.datasets[0].id,dataset_name:'浏览器轮询检查',source:'synthetic',
            created_at:new Date(clockStart).toISOString(),message:'测试中的训练任务',logs:[]}],
        }});
      } finally {activePolls--;}
    });
    try {
      await pollingPage.goto(base,{waitUntil:'networkidle'});
      await pollingPage.locator('.point-weather strong').waitFor();
      await pollingPage.locator('.weather-map').waitFor();
      // Pausing fires the existing interval once; let that refresh finish before editing.
      const pausedRefresh=pollingPage.waitForResponse(response=>new URL(response.url()).pathname==='/api/overview');
      await pollingPage.clock.pauseAt(clockStart+60000);
      await (await pausedRefresh).finished();
      await pollingPage.getByRole('button',{name:'阈值告警',exact:true}).click();
      await pollingPage.locator('.page-date').filter({hasText:pollTime(overviewRequests)}).waitFor();
      const edits=[['短时强降水 (mm/h)','42.6'],['大风 (m/s)','23.4'],['高温 (°C)','38.2']];
      for(const [label,value] of edits)await pollingPage.getByLabel(label,{exact:true}).fill(value);
      const queryCounts={map:mapRequests,point:pointRequests};
      const nextCount=overviewRequests+1;
      const updated=pollingPage.waitForResponse(response=>new URL(response.url()).pathname==='/api/overview');
      await pollingPage.clock.runFor(4000);
      await (await updated).finished();
      await pollingPage.locator('.page-date').filter({hasText:pollTime(nextCount)}).waitFor();
      for(const [label,value] of edits)assert.equal(await pollingPage.getByLabel(label,{exact:true}).inputValue(),value,`${label} was overwritten by training polling`);
      await pollingPage.waitForTimeout(100);
      assert.deepEqual({map:mapRequests,point:pointRequests},queryCounts,'training polling reloaded unchanged map/point results');
      check('training polling preserves unsaved thresholds and existing map/point results');

      holdPoll=true;
      const beforeSlow=overviewRequests;
      const held=new Promise(resolve=>{onHeldPoll=resolve;});
      const slowResponse=pollingPage.waitForResponse(response=>new URL(response.url()).pathname==='/api/overview');
      await pollingPage.clock.runFor(4000);
      await held;
      // Keep the request pending across three more intervals, below the GET timeout.
      await pollingPage.clock.runFor(12000);
      await pollingPage.waitForTimeout(100);
      assert.equal(overviewRequests,beforeSlow+1,'slow training poll overlapped a subsequent poll');
      assert.equal(peakPolls,1,'more than one overview request was in flight');
      holdPoll=false;releasePoll();releasePoll=undefined;
      await (await slowResponse).finished();
      await pollingPage.locator('.page-date').filter({hasText:pollTime(beforeSlow+1)}).waitFor();
      const resumed=pollingPage.waitForResponse(response=>new URL(response.url()).pathname==='/api/overview');
      await pollingPage.clock.runFor(4000);
      await (await resumed).finished();
      await pollingPage.locator('.page-date').filter({hasText:pollTime(beforeSlow+2)}).waitFor();
      for(const [label,value] of edits)assert.equal(await pollingPage.getByLabel(label,{exact:true}).inputValue(),value);
      assert.deepEqual({map:mapRequests,point:pointRequests},queryCounts);
      check('slow training polling does not overlap and resumes after the pending response');
    } finally {
      holdPoll=false;releasePoll?.();
      await pollingPage.clock.resume();
      await pollingContext.close();
    }
    await page.getByRole('button',{name:'管理员 · 退出'}).click();
    await page.getByRole('button',{name:'访客 · 管理员登录'}).waitFor();
    check('logout and viewer mode');
    assert.equal(errors.length,0,errors.join('\n'));
    check('no browser runtime errors');
    report.status='passed';
    console.log(JSON.stringify(report,null,2));
  } catch(error) {
    report.status='failed';report.error=error.message;report.runtimeErrors=errors;
    await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});
    throw error;
  } finally {
    fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));
    await browser.close();
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
