const {chromium}=require('../frontend/node_modules/playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
(async()=>{
 const out=path.resolve(__dirname,'../outputs/redesign');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true});
 const page=await browser.newPage({viewport:{width:1600,height:1100}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const report={checks:[],status:'running'};
 try{
  await page.goto('http://127.0.0.1:8016',{waitUntil:'networkidle'});
  await page.locator('.map-coast').first().waitFor();
  assert(await page.locator('.city-label').count()>0);
  assert.equal(await page.locator('.welcome-panel').count(),0);
  const mapBox=await page.locator('.synoptic-map').boundingBox();assert(mapBox.y<500,'Map must be visible in the first viewport');
  report.checks.push('map first viewport; real coastline and city labels; no promotional banner');
  const before=await page.locator('.coverage-boundary').getAttribute('width');
  await page.getByRole('button',{name:'放大地图',exact:true}).click();
  const after=await page.locator('.coverage-boundary').getAttribute('width');assert(Number(after)>Number(before));
  await page.getByRole('button',{name:'重置地图',exact:true}).click();
  await page.getByRole('button',{name:'原始网格',exact:true}).click();
  assert.equal(await page.getByRole('button',{name:'原始网格',exact:true}).getAttribute('aria-pressed'),'true');
  await page.getByRole('button',{name:'连续显示',exact:true}).click();
  report.checks.push('map zoom/reset and raw/smooth display');
  const ticks=await page.locator('.scale-ticks').innerText();
  await Promise.all([page.waitForResponse(r=>r.url().includes('/forecast/grid')&&r.url().includes('lead=18')&&r.status()===200),page.getByRole('slider',{name:'预报时效'}).fill('18')]);
  assert.equal(await page.locator('.scale-ticks').innerText(),ticks);
  report.checks.push('forecast-wide fixed color scale across lead times');
  for(const [width,height] of [[1600,1100],[1440,1000],[1024,900],[768,1000],[390,844],[320,740]]){
   await page.setViewportSize({width,height});
   await page.evaluate(()=>window.scrollTo(0,0));
   assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1)),`overflow ${width}`);
   await page.screenshot({path:path.join(out,`workspace-${width}.png`),fullPage:true});
   if(width===1600)await page.screenshot({path:path.join(out,'desktop-viewport.png')});
  }
  report.checks.push('320 / 390 / 768 / 1024 / 1440 / 1600 widths without horizontal overflow');
  await page.setViewportSize({width:1440,height:1000});
  for(const nav of ['气象数据','模型实验室','天气告警']){
   await page.getByRole('button',{name:nav,exact:true}).click();
   await page.evaluate(()=>window.scrollTo(0,0));
   await page.screenshot({path:path.join(out,nav+'.png'),fullPage:true});
  }
  assert.equal(errors.length,0,errors.join('\n'));report.checks.push('all secondary pages render; no browser runtime errors');report.status='passed';
 }catch(e){report.status='failed';report.error=e.message;await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});throw e;}
 finally{fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
