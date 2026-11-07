const {chromium} = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const base = 'http://127.0.0.1:8775';
  const fixture = JSON.parse(await fs.readFile('.local/collaboration-qa.json', 'utf8'));
  const output = await fs.mkdtemp(path.resolve('.local/browser-qa/collaboration-'));
  const report = {checks: [], viewports: [], errors: [], baselineErrors: []};
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width:1915,height:930}});
    page.on('pageerror', error => {
      if (error.stack?.includes('mathjax@3/es5/startup.js') && error.message.includes('Cannot set property Package')) report.baselineErrors.push(error.message);
      else report.errors.push(error.message);
    });
    await page.goto(base+'/accounts/login/');
    await page.locator('[name=username]').fill(fixture.users.owner);
    await page.locator('[name=password]').fill(fixture.password);
    await Promise.all([page.waitForURL(url => !url.pathname.includes('/login/')), page.locator('button[type=submit]').first().click()]);
    const documentUrl=base+`/padif/documents/${fixture.document_id}/`;
    await page.goto(documentUrl);
    assert.match(await page.locator('.document-access-status').textContent(),/PAdif Agent 已开通.*本文 AI\+ 待审核/s);
    await page.getByRole('link',{name:'管理协作',exact:true}).click();
    const search=page.getByRole('combobox',{name:'选择已有账号'});
    await Promise.all([
      page.waitForResponse(response => response.url().includes('accounts=1') && new URL(response.url()).searchParams.get('q')===fixture.users.friend),
      search.fill(fixture.users.friend)
    ]);
    await page.waitForFunction(() => document.querySelector('.account-picker-status').textContent.startsWith('找到 1 个账号'));
    await page.locator('#collaboration-account-options').getByRole('option').filter({hasText:fixture.users.friend}).waitFor();
    assert.equal(await page.locator('#collaboration-account-options').getByRole('option').count(),1);
    await Promise.all([
      page.waitForResponse(response => response.url().includes('accounts=1') && new URL(response.url()).searchParams.get('q')===String(fixture.friend_id)),
      search.fill(String(fixture.friend_id))
    ]);
    await page.waitForFunction(() => document.querySelector('.account-picker-status').textContent.startsWith('找到 1 个账号'));
    await page.locator('#collaboration-account-options').getByRole('option').filter({hasText:fixture.users.friend}).waitFor();
    const colors=await page.locator('#collaboration-account-options').getByRole('option').first().evaluate(row => [...row.children].map(el => getComputedStyle(el).color));
    assert.notEqual(colors[0],colors[1]);
    for (const viewport of [{width:1915,height:930},{width:1198,height:715},{width:390,height:844}]) {
      await page.setViewportSize(viewport);
      const overflow=await page.evaluate(() => document.documentElement.scrollWidth-innerWidth);
      assert.ok(overflow<=1,`Collaboration overflow ${viewport.width}: ${overflow}`);
      await page.screenshot({path:path.join(output,`collaboration-${viewport.width}.png`),fullPage:true});
      report.viewports.push({page:'collaboration',...viewport,overflow});
    }
    await search.press('ArrowDown');
    await search.press('Enter');
    assert.equal(await page.locator('[data-account-native]').inputValue(),fixture.users.friend);
    assert.equal(await search.getAttribute('aria-expanded'),'false');
    assert.equal(await search.evaluate(el => el===document.activeElement),true);
    await page.locator('.collaboration-member-add [name=role]').selectOption('collaborator');
    await page.getByRole('button',{name:'添加 / 更新成员',exact:true}).click();
    const member=page.locator(`[data-human-member="${fixture.users.friend}"]`);
    assert.match(await member.textContent(),/协作者.*本文 AI\+ 未授权/s);
    report.checks.push('Owner-only name/ID search, gray ID, keyboard selection and focus, human collaboration does not implicitly enable AI+');
    await page.goto(base+'/accounts/security/agents/');
    const review=page.locator(`[data-owned-ai-request="${fixture.request_id}"]`);
    await review.waitFor();
    const skin=await review.evaluate(el => ({link:getComputedStyle(el.querySelector('a')).color, secondary:getComputedStyle(el.querySelector('[value=reject]')).backgroundColor}));
    assert.notEqual(skin.link,'rgb(0, 0, 238)');
    assert.notEqual(skin.secondary,'rgb(239, 239, 239)');
    for (const viewport of [{width:1915,height:930},{width:1198,height:715},{width:390,height:844}]) {
      await page.setViewportSize(viewport);
      const overflow=await page.evaluate(() => document.documentElement.scrollWidth-innerWidth);
      assert.ok(overflow<=1,`Personal inbox overflow ${viewport.width}: ${overflow}`);
      await page.screenshot({path:path.join(output,`owner-inbox-${viewport.width}.png`),fullPage:true});
      report.viewports.push({page:'owner inbox',...viewport,overflow});
    }
    await review.locator('[name=note]').fill('本人确认在此文章启用 AI 写作辅助。');
    await review.getByRole('button',{name:'批准本文 AI+',exact:true}).click();
    await page.waitForURL(url => url.hash==='#owned-ai-review');
    assert.equal(await review.count(),0);
    await page.goto(documentUrl);
    assert.match(await page.locator('.document-access-status').textContent(),/本文 AI\+ 已生效/);
    for (const viewport of [{width:1915,height:930},{width:1198,height:715},{width:390,height:844}]) {
      await page.setViewportSize(viewport);
      const handle=page.locator('[data-drawer-handle]');
      if (await handle.isVisible()) await handle.click();
      await page.waitForFunction(() => document.querySelector('[data-version-drawer]').getBoundingClientRect().right<=innerWidth+1);
      const overflow=await page.evaluate(() => document.documentElement.scrollWidth-innerWidth);
      assert.ok(overflow<=1,`Document header with drawer overflow ${viewport.width}: ${overflow}`);
      await page.locator('[data-drawer-close]').click();
      await page.screenshot({path:path.join(output,`document-${viewport.width}.png`),fullPage:true});
      report.viewports.push({page:'document header and drawer',...viewport,overflow});
    }
    report.checks.push('Non-dashboard owner approves own request on personal Agent page; document status updates to effective');
    assert.deepEqual(report.errors,[]);
    await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
    console.log('Collaboration and personal owner-inbox browser acceptance passed: '+output);
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
