const { chromium } = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = 'http://127.0.0.1:8772';

(async () => {
  const fixture = JSON.parse(await fs.readFile('.local/review-browser-fixture.json', 'utf8'));
  const password = process.env.PADIF_REVIEW_QA_PASSWORD;
  if (!password) throw new Error('Set PADIF_REVIEW_QA_PASSWORD for local disposable accounts');
  const output = await fs.mkdtemp(path.resolve('.local/browser-qa/agent-review-'));
  const browser = await chromium.launch({ headless: true });
  async function login(user) {
    const context = await browser.newContext({ viewport: { width: 1198, height: 715 } });
    const page = await context.newPage();
    await page.goto(base + '/accounts/login/');
    await page.locator('[name=username]').fill(user);
    await page.locator('[name=password]').fill(password);
    await page.locator('button[type=submit]').first().click();
    return page;
  }
  const results = [];
  try {
    const applicant = await login(fixture.username);
    await applicant.goto(base + '/accounts/security/agents/');
    assert.match(await applicant.locator('#agent-qualification-title').textContent(), /未开通/);
    for (const viewport of [{ width: 1198, height: 715 }, { width: 390, height: 844 }]) {
      await applicant.setViewportSize(viewport);
      const overflow = await applicant.evaluate(() => document.documentElement.scrollWidth - innerWidth);
      assert.ok(overflow <= 1);
      await applicant.screenshot({ path: path.join(output, `application-${viewport.width}.png`), fullPage: true });
      results.push({ page: 'application', ...viewport, overflow });
    }
    await applicant.getByRole('button', { name: '申请开通 PAdif Agent', exact: true }).click();
    assert.match(await applicant.locator('#agent-qualification-title').textContent(), /待审核/);
    const denied = await applicant.context().request.get(base + '/dashboard/agents/');
    assert.equal(denied.status(), 403);
    const reviewer = await login(fixture.reviewer);
    await reviewer.goto(base + '/dashboard/');
    const entry = reviewer.locator('.dashboard-nav a[href="/dashboard/agents/"]');
    await entry.click();
    const row = reviewer.locator('.agent-review-row').filter({ hasText: fixture.username }).filter({ has: reviewer.locator('[name=request_id]') });
    await row.locator('textarea').fill('Approved by the local browser acceptance reviewer.');
    for (const viewport of [{ width: 1198, height: 715 }, { width: 390, height: 844 }]) {
      await reviewer.setViewportSize(viewport);
      const overflow = await reviewer.evaluate(() => document.documentElement.scrollWidth - innerWidth);
      assert.ok(overflow <= 1);
      await reviewer.screenshot({ path: path.join(output, `dashboard-${viewport.width}.png`), fullPage: true });
      results.push({ page: 'dashboard', ...viewport, overflow });
    }
    await row.getByRole('button', { name: '批准开通', exact: true }).click();
    await applicant.reload();
    assert.match(await applicant.locator('#agent-qualification-title').textContent(), /已开通/);
    await reviewer.goto(base + '/dashboard/agents/?status=approved');
    const approved = reviewer.locator('.agent-review-row').filter({ hasText: fixture.username }).filter({ has: reviewer.locator('[name=user_id]') });
    await approved.locator('textarea').fill('Local QA finished; revoke eligibility.');
    await approved.getByRole('button', { name: '撤销开通资格', exact: true }).click();
    await applicant.reload();
    assert.match(await applicant.locator('#agent-qualification-title').textContent(), /已撤销/);
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify({ results, status: 'passed', workflow: 'apply, dashboard entry, approve, revoke, own-account boundary' }, null, 2));
    console.log('Agent eligibility browser acceptance passed: ' + output);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
