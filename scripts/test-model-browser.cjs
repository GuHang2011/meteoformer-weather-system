const {chromium}=require('../frontend/node_modules/playwright');
const fs=require('fs');
const path=require('path');
const assert=require('assert/strict');

(async()=>{
  const root=path.resolve(__dirname,'..');
  const output=path.join(root,'outputs','model-verification');fs.mkdirSync(output,{recursive:true});
  const browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  try {
    await page.goto('http://127.0.0.1:8016',{waitUntil:'networkidle'});
    await page.getByRole('button',{name:'访客 · 管理员登录'}).click();
    await page.getByLabel('管理员密码',{exact:true}).fill(fs.readFileSync(path.join(root,'backend/data/initial-admin-password.txt'),'utf8').trim());
    await page.getByRole('button',{name:'登录',exact:true}).click();
    await page.getByRole('button',{name:'管理员 · 退出'}).waitFor();
    await page.getByRole('button',{name:'模型实验室',exact:true}).click();
    const [response]=await Promise.all([
      page.waitForResponse(r=>r.url().endsWith('/api/train/start')&&r.status()===202),
      page.getByRole('button',{name:'开始训练'}).click(),
    ]);
    const job=await response.json();
    const jobPanel=page.locator('section.panel').filter({hasText:job.id.slice(0,8)});
    await jobPanel.getByText('已完成',{exact:true}).waitFor({timeout:120000});
    await jobPanel.getByRole('heading',{name:'测试分区评估 · 模型 vs 持续性基线'}).waitFor();
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:path.join(output,'training.png'),fullPage:true});
    await page.getByRole('button',{name:'预报与查询',exact:true}).click();
    if(!await page.locator('.generate-form').isVisible()) await page.locator('.generate-details summary').click();
    await page.getByLabel('预测方式',{exact:true}).selectOption('meteoformer');
    await page.getByLabel('模型权重',{exact:true}).selectOption(job.id);
    await page.getByLabel('集合成员',{exact:true}).fill('4');
    const [forecastResponse]=await Promise.all([
      page.waitForResponse(r=>r.url().endsWith('/api/predict')&&r.status()===201),
      page.getByRole('button',{name:'生成预报',exact:true}).click(),
    ]);
    const forecast=await forecastResponse.json();
    await page.locator('.notice.busy').waitFor({state:'hidden'});
    await page.getByText('温度 P10–P90',{exact:true}).waitFor();
    await page.getByRole('button',{name:'预报工作台',exact:true}).click();
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:path.join(output,'model-forecast.png'),fullPage:true});
    const status=await page.request.get(`http://127.0.0.1:8016/api/train/status?job_id=${job.id}`);
    const details=await status.json();
    assert.equal(details.status,'completed');
    assert.equal(forecast.members,4);
    assert.equal(errors.length,0,errors.join('\n'));
    await page.getByRole('button',{name:'管理员 · 退出'}).click();
    const report={status:'passed',job_id:job.id,forecast_id:forecast.id,parameters:details.parameters,
      elapsed_seconds:details.elapsed_seconds,epochs:details.logs,metrics:details.metrics,members:forecast.members,
      provenance:'synthetic demonstration data; this is software validation, not evidence of operational forecast skill'};
    fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify({status:report.status,parameters:report.parameters,elapsed_seconds:report.elapsed_seconds,members:report.members}));
  } catch(e) {await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw e;}
  finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
