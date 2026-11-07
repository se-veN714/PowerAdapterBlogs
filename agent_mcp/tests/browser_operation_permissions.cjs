const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');

(async () => {
  const base = process.env.PADIF_MCP_QA_BASE || 'http://127.0.0.1:8772';
  assert.ok(['localhost', '127.0.0.1'].includes(new URL(base).hostname));
  const fixture = JSON.parse(await fs.readFile('.local/v22-browser-fixture.json', 'utf8'));
  assert.ok(process.env.PADIF_V22_QA_PASSWORD);
  const output = await fs.mkdtemp(path.resolve('.local/browser-qa/operations-'));
  const report = {spec: 'v2.2', checks: [], viewports: [], errors: [], baselineErrors: []};
  const browser = await chromium.launch({headless: true});
  async function login(role) {
    const context = await browser.newContext({viewport: {width:1198, height:715}});
    const page = await context.newPage();
    page.on('pageerror', error => {
      const text = error.stack || error.message;
      if (text.includes('mathjax@3/es5/startup.js') && text.includes('Cannot set property Package')) report.baselineErrors.push(text);
      else report.errors.push(text);
    });
    await page.goto(base+'/accounts/login/');
    await page.locator('[name=username]').fill(fixture.users[role]);
    await page.locator('[name=password]').fill(process.env.PADIF_V22_QA_PASSWORD);
    await Promise.all([page.waitForURL(url => !url.pathname.includes('/login/')), page.locator('button[type=submit]').first().click()]);
    return page;
  }
  const portal=base+'/accounts/security/agents/';
  const rowSelector=`[data-article-id="${fixture.document_id}"]`;
  async function capture(page, name, drawer=false) {
    for (const viewport of [{width:1915,height:930},{width:1198,height:715},{width:390,height:844}]) {
      await page.setViewportSize(viewport);
      await page.evaluate(() => new Promise(requestAnimationFrame));
      const geometry = await page.evaluate(() => {
        const dialog=document.querySelector('#agent-permission-drawer');
        const select=document.querySelector('#agent-module');
        const rect=select?.getBoundingClientRect();
        return {overflow:document.documentElement.scrollWidth-innerWidth,
          select:rect ? {width:rect.width,height:rect.height}:null,
          tableFont:document.querySelector('.agent-article-table') ? getComputedStyle(document.querySelector('.agent-article-table')).fontSize:null,
          dialog:dialog?.open ? {width:dialog.getBoundingClientRect().width,left:dialog.getBoundingClientRect().left,overflow:dialog.scrollWidth-dialog.clientWidth}:null};
      });
      assert.ok(geometry.overflow<=1,`${name} document overflow`);
      if (geometry.select) {assert.equal(geometry.select.height,36); assert.equal(geometry.tableFont,'15px');}
      if (drawer) {
        assert.ok(geometry.dialog.overflow<=1);
        assert.ok(geometry.dialog.left>=-1);
        assert.equal(geometry.dialog.width,viewport.width<720?viewport.width:420);
      }
      await page.screenshot({path:path.join(output,`${name}-${viewport.width}.png`),fullPage:!drawer});
      report.viewports.push({name,...viewport,...geometry});
    }
    await page.setViewportSize({width:1198,height:715});
  }
  try {
    const page=await login('writer');
    await page.goto(portal);
    assert.equal(await page.locator('.agent-module-status').textContent(),'已开通');
    await capture(page,'management');
    const drawer=page.locator('#agent-permission-drawer');
    const button=()=>page.locator(rowSelector+' [data-permission-drawer]');
    await button().click();
    assert.equal(await drawer.locator('[name=operations][value="padif:annotate"]').isChecked(),true);
    await capture(page,'drawer',true);
    await page.keyboard.press('Escape');
    assert.equal(await button().evaluate(el=>el===document.activeElement),true);
    await button().click();
    // Modal keyboard focus must not escape.
    for(let i=0;i<12;i++) { await page.keyboard.press('Tab'); assert.equal(await drawer.evaluate(el=>el.contains(document.activeElement)),true); }
    const note=drawer.locator('[name=note]');
    await drawer.locator('[value="padif:annotate"]').uncheck();
    await drawer.locator('[value="padif:version"]').uncheck();
    assert.equal(await drawer.locator('[data-drawer-submit]').textContent(),'立即减少权限');
    await note.fill('Local downgrade to reading');
    await drawer.locator('[data-drawer-submit]').click();
    await page.waitForFunction(()=>!document.querySelector('#agent-permission-drawer').open);
    assert.equal(await button().evaluate(el=>el===document.activeElement),true);
    assert.match(await page.locator(rowSelector+' .agent-operation-summary').textContent(),/批注 —/);
    report.checks.push('Immediate downgrade updates row without navigation; modal tab/escape and trigger focus preserved');
    await button().click();
    await drawer.locator('[value="padif:annotate"]').check();
    assert.equal(await drawer.locator('[data-drawer-submit]').textContent(),'提交提权申请');
    await note.fill('Request annotation review');
    await drawer.locator('[data-drawer-submit]').click();
    await page.waitForFunction(()=>!document.querySelector('#agent-permission-drawer').open);
    assert.match(await page.locator(rowSelector).textContent(),/提权待审核/);
    assert.match(await page.locator(rowSelector+' .agent-operation-summary').textContent(),/批注 —/);
    assert.equal(await page.locator('[data-granted-count]').textContent(),'1');
    assert.equal(await page.locator('[data-pending-count]').textContent(),'1');
    await button().click();
    await capture(page,'pending-drawer',true);
    await page.keyboard.press('Escape');
    const owner=await login('owner');
    await owner.goto(base+`/padif/documents/${fixture.document_id}/collaboration/`);
    const review=owner.locator('.ai-review-item').filter({has:owner.locator('[name=request_id]')});
    assert.match(await review.textContent(),/阅读 \/ 批注/);
    await review.locator('[name=note]').fill('Approve only requested annotation');
    await review.getByRole('button',{name:'批准本文 AI+',exact:true}).click();
    await page.reload();
    assert.match(await page.locator(rowSelector+' .agent-operation-summary').textContent(),/批注 ✓/);
    assert.match(await page.locator(rowSelector+' .agent-operation-summary').textContent(),/分支写作 —/);
    report.checks.push('Upgrade stays pending with existing reading, creator approves exact target on article page');
    const viewer=await login('viewer');
    await viewer.goto(portal);
    await viewer.locator(rowSelector+' [data-permission-drawer]').click();
    assert.equal(await viewer.locator('#agent-permission-drawer [value="padif:annotate"]').isDisabled(),true);
    assert.equal(await viewer.locator('#agent-permission-drawer [value="padif:version"]').isDisabled(),true);
    report.checks.push('Viewer cannot select writing and role explanation is visible');
    await viewer.keyboard.press('Escape');
    // Stale revision errors retain the input and keep the drawer open.
    await button().click();
    await drawer.locator('[value="padif:annotate"]').uncheck();
    await note.fill('Keep this explanation');
    await drawer.locator('[name=revision]').evaluate(el=>el.value='0');
    await drawer.locator('[data-drawer-submit]').click();
    await page.waitForFunction(()=>document.querySelector('[data-drawer-error]').textContent.length>0);
    assert.equal(await note.inputValue(),'Keep this explanation');
    assert.equal(await drawer.evaluate(el=>el.open),true);
    await page.keyboard.press('Escape');
    report.checks.push('Stale revision failure preserves draft explanation and makes no permission changes');
    const params=new URLSearchParams({client_id:fixture.client_id,redirect_uri:'http://127.0.0.1:9919/callback',response_type:'code',state:crypto.randomBytes(12).toString('hex'),code_challenge:crypto.createHash('sha256').update('a'.repeat(64)).digest('base64url'),code_challenge_method:'S256',resource:base+'/padif/mcp/',scope:'padif:read padif:annotate padif:version'});
    await page.goto(base+'/accounts/agent/oauth/authorize/?'+params);
    assert.match(await page.locator('.agent-role-notice').textContent(),/AI\+ 操作集合/);
    assert.equal(await page.locator('[name=approved_scope]').count(),3);
    await capture(page,'consent');
    report.checks.push('OAuth shows per-article operation summary; scope boxes still describe client actions');
    assert.deepEqual(report.errors,[]);
  } finally {
    await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
    await browser.close();
    console.log(output);
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
