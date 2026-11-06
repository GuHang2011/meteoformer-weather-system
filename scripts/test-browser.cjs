const { chromium } = require('../frontend/node_modules/playwright');
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');

(async()=>{
  const root=path.resolve(__dirname,'..');
  const output=path.join(root,'outputs','browser');fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const report={checks:[],screenshots:[]};
  const check=(name)=>report.checks.push(name);
  try {
    await page.goto('http://127.0.0.1:8016', {waitUntil:'networkidle'});
    await page.getByRole('heading',{name:'预报工作台',exact:true}).waitFor();
    assert(!await page.getByText('协作聊天',{exact:true}).count());
    assert(!await page.getByText('电子盖章',{exact:true}).count());
    check('weather-only navigation');
    await page.getByRole('button',{name:'访客 · 管理员登录'}).click();
    await page.getByLabel('管理员密码',{exact:true}).fill(fs.readFileSync(path.join(root,'backend/data/initial-admin-password.txt'),'utf8').trim());
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
    await page.locator('.weather-map image').waitFor();
    check('forecast generation and point query');
    await Promise.all([page.waitForResponse(r=>r.url().includes('/forecast/grid')&&r.url().includes('precip')&&r.status()===200),page.getByRole('button',{name:'降水 mm/h',exact:true}).click()]);
    await Promise.all([page.waitForResponse(r=>r.url().includes('/forecast/grid')&&r.url().includes('lead=12')&&r.status()===200),page.getByRole('slider',{name:'预报时效'}).fill('12')]);
    check('weather variable and lead switching');
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
    check('NetCDF and PNG downloads');
    await page.getByRole('button',{name:'预报工作台',exact:true}).click();
    await page.evaluate(()=>window.scrollTo(0,0));
    assert(await page.locator('.meteo-shell').evaluate(el=>getComputedStyle(el).backgroundImage.includes('linear-gradient')));
    check('continuous sidebar background on full-height pages');
    await page.screenshot({path:path.join(output,'desktop.png'),fullPage:true});report.screenshots.push('desktop.png');
    await page.screenshot({path:path.join(output,'desktop-viewport.png')});
    for(const width of [390,320]) {
      await page.setViewportSize({width,height:844});
      for(const nav of ['预报工作台','气象数据','模型实验室','天气告警']) {
        await page.getByRole('button',{name:nav,exact:true}).click();
        const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1);
        assert(!overflow, `${nav} horizontal overflow at ${width}px`);
      }
      await page.getByRole('button',{name:'预报工作台',exact:true}).click();
      await page.evaluate(()=>window.scrollTo(0,0));
      await page.screenshot({path:path.join(output,`mobile-${width}.png`),fullPage:true});report.screenshots.push(`mobile-${width}.png`);
    }
    check('320px and 390px responsive layouts');
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
