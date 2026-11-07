const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');

(async () => {
  const base = process.env.PADIF_MCP_QA_BASE || 'http://127.0.0.1:8772';
  assert.ok(['localhost', '127.0.0.1'].includes(new URL(base).hostname));
  const password = process.env.PADIF_CONCEPT_QA_PASSWORD;
  assert.ok(password, 'Set disposable local fixture password');
  const fixture = JSON.parse(await fs.readFile('.local/agent-concept-fixture.json', 'utf8'));
  const output = await fs.mkdtemp(path.resolve('.local/browser-qa/access-concept-'));
  const browser = await chromium.launch({ headless: true });
  const report = { checks: [], viewports: [], errors: [], baselineErrors: [] };
  try {
    const context = await browser.newContext({ viewport: { width: 1198, height: 715 } });
    const page = await context.newPage();
    page.on('pageerror', error => {
      const stack = error.stack || error.message;
      if (stack.includes('mathjax@3/es5/startup.js') && stack.includes('Cannot set property Package')) report.baselineErrors.push(stack);
      else report.errors.push(stack);
    });
    async function capture(name) {
      for (const viewport of [{ width: 1198, height: 715 }, { width: 390, height: 844 }]) {
        await page.setViewportSize(viewport);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
        assert.ok(overflow <= 1, `${name} overflow ${overflow}`);
        await page.evaluate(async () => { scrollTo(0, 0); await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame); });
        await page.screenshot({ path: path.join(output, `${name}-${viewport.width}.png`), fullPage: true });
        report.viewports.push({ page: name, ...viewport, overflow });
      }
    }
    await page.goto(base + '/accounts/login/');
    await page.locator('[name=username]').fill(fixture.username);
    await page.locator('[name=password]').fill(password);
    await page.locator('button[type=submit]').first().click();
    await page.goto(base + '/accounts/security/agents/');
    assert.match(await page.locator('.agent-access-counts').textContent(), /已授权\s*1\s*篇/);
    assert.match(await page.locator('.agent-access-counts').textContent(), /待审核\s*3\s*篇/);
    assert.equal(await page.locator('.agent-article-table tbody tr').count(), 4);
    assert.equal(await page.locator('#agent-module').isDisabled(), true);
    assert.equal(await page.locator('[name=role]').count(), 0);
    assert.equal(await page.locator('a[href$="/collaboration/"]').count(), 0);
    assert.equal(await page.locator('#article-ai-reason').count(), 0);
    await page.locator('#article-application > summary').click();
    assert.match(await page.locator('#article-application').textContent(), /暂无可申请项目/);
    await page.locator('#article-application > summary').click();
    await capture('management');
    report.checks.push('Management separates 1 granted/3 pending; no creator controls; empty request form stays out of view');
    const params = new URLSearchParams({ client_id: fixture.client_id, redirect_uri: 'http://127.0.0.1:9919/callback',
      response_type: 'code', state: crypto.randomBytes(12).toString('hex'),
      code_challenge: crypto.createHash('sha256').update('a'.repeat(64)).digest('base64url'), code_challenge_method: 'S256',
      resource: base + '/padif/mcp/', scope: 'padif:read padif:annotate padif:version' });
    await page.goto(base + '/accounts/agent/oauth/authorize/?' + params);
    assert.equal(await page.locator('.agent-consent-coverage li').count(), 1);
    assert.match(await page.locator('.agent-consent-coverage').textContent(), /已授权\s*1\s*篇/);
    assert.match(await page.locator('.agent-consent-coverage').textContent(), /待审\s*3\s*篇暂不可访问/);
    assert.match(await page.locator('.agent-role-notice').textContent(), /已授权文章均为只读/);
    assert.match(await page.locator('.agent-scope-help').textContent(), /操作类型，不是文章数量/);
    assert.equal(await page.locator('[name=approved_scope]').count(), 3);
    for (const scope of ['padif:read', 'padif:annotate', 'padif:version']) {
      const box = page.locator(`[name=approved_scope][value="${scope}"]`);
      assert.equal(await box.isChecked(), scope === 'padif:read');
      assert.equal(await box.isDisabled(), false);
    }
    await capture('consent');
    report.checks.push('OAuth displays one AI+ article separately from three scopes; viewer explanation; read-only default; no automatic writes');
    assert.deepEqual(report.errors, []);
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ output, checks: report.checks, viewports: report.viewports, errors: report.errors }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
