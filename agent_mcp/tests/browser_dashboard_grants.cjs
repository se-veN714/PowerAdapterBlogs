const { chromium } = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const base = 'http://127.0.0.1:8774';
  const fixture = JSON.parse(await fs.readFile('.local/dashboard-grants-qa.json', 'utf8'));
  const output = await fs.mkdtemp(path.resolve('.local/browser-qa/dashboard-grants-'));
  const browser = await chromium.launch({ headless: true });
  const report = { checks: [], viewports: [], errors: [], baselineErrors: [] };
  try {
    const page = await browser.newPage({ viewport: { width:1198, height:715 } });
    page.on('pageerror', error => {
      if (error.stack?.includes('mathjax@3/es5/startup.js') && error.message.includes('Cannot set property Package')) report.baselineErrors.push(error.message);
      else report.errors.push(error.message);
    });
    await page.goto(base+'/accounts/login/');
    await page.locator('[name=username]').fill(fixture.admin);
    await page.locator('[name=password]').fill(fixture.password);
    await Promise.all([page.waitForURL(url => !url.pathname.includes('/login/')), page.locator('button[type=submit]').first().click()]);
    await page.goto(base+'/dashboard/agents/');
    await page.locator('[name=q]').first().fill(fixture.friend);
    await page.getByRole('button', { name:'搜索账号', exact:true }).click();
    const account = page.locator(`[data-agent-account="${fixture.friend_id}"]`);
    await account.locator('[name=note]').fill('Disposable browser QA direct grant');
    await account.getByRole('button', { name:'直接开通 PAdif Agent', exact:true }).click();
    const grant = page.locator(`[data-agent-grant="${fixture.friend_id}"]`);
    await assert.equal(await grant.count(),1);
    for (const viewport of [{width:1915,height:930},{width:1198,height:715},{width:390,height:844}]) {
      await page.setViewportSize(viewport);
      if (viewport.width <= 980) {
        await page.waitForFunction(() => document.querySelector('#dashboard-sidebar').getBoundingClientRect().right <= 0);
      }
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth-innerWidth);
      assert.ok(overflow<=1, `Overflow at ${viewport.width}: ${overflow}`);
      await page.screenshot({path:path.join(output,`grants-${viewport.width}.png`),fullPage:true});
      report.viewports.push({...viewport,overflow});
    }
    const edit = grant.locator('details').filter({has:page.locator('[name=action][value=update]')});
    await edit.locator('summary').click();
    await edit.locator('[name=note]').fill('Updated browser QA management note');
    await edit.getByRole('button',{name:'保存说明',exact:true}).click();
    assert.match(await grant.textContent(),/Updated browser QA management note/);
    const revoke = grant.locator('details').filter({has:page.locator('[name=action][value=revoke]')});
    await revoke.locator('summary').click();
    await revoke.locator('[name=note]').fill('Browser QA revoke');
    await revoke.getByRole('button',{name:'撤销开通资格',exact:true}).click();
    assert.match(await grant.locator('header').textContent(),/已撤销/);
    const reopen = grant.locator('details').filter({has:page.locator('[name=action][value=grant]')});
    await reopen.locator('summary').click();
    await reopen.locator('[name=note]').fill('Browser QA reopen');
    await reopen.getByRole('button',{name:'重新开通',exact:true}).click();
    assert.match(await grant.locator('header').textContent(),/已开通/);
    report.checks.push('Real local login, account search, direct grant, note edit, revoke and reopen via CSRF-protected forms');
    assert.deepEqual(report.errors,[]);
    await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
    console.log('Dashboard grant browser acceptance passed: '+output);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode=1; });
