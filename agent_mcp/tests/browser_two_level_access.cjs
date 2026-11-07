const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const base = process.env.PADIF_MCP_QA_BASE || 'http://127.0.0.1:8772';
  assert.ok(['localhost', '127.0.0.1'].includes(new URL(base).hostname));
  const password = process.env.PADIF_V2_QA_PASSWORD;
  assert.ok(password, 'Set local disposable account password');
  const fixture = JSON.parse(await fs.readFile('.local/v2-browser-fixture.json', 'utf8'));
  const [first, second, hidden] = fixture.documents;
  const output = await fs.mkdtemp(path.resolve('.local/browser-qa/two-level-'));
  const browser = await chromium.launch({ headless: true });
  const report = { spec: 'v2.1', checks: [], viewports: [], errors: [], baselineErrors: [] };
  const portal = base + '/accounts/security/agents/';
  async function login(role) {
    const context = await browser.newContext({ viewport: { width: 1198, height: 715 } });
    const page = await context.newPage();
    page.on('pageerror', error => {
      const stack = error.stack || error.message;
      if (stack.includes('mathjax@3/es5/startup.js') && stack.includes('Cannot set property Package')) report.baselineErrors.push(stack);
      else report.errors.push(stack);
    });
    await page.goto(base + '/accounts/login/');
    await page.locator('[name=username]').fill(fixture.users[role]);
    await page.locator('[name=password]').fill(password);
    await page.locator('button[type=submit]').first().click();
    return page;
  }
  async function capture(page, name) {
    for (const viewport of [{ width: 1198, height: 715 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
      assert.ok(overflow <= 1, `${name}: overflow ${overflow}`);
      await page.screenshot({ path: path.join(output, `${name}-${viewport.width}.png`), fullPage: true });
      report.viewports.push({ page: name, ...viewport, overflow });
    }
    await page.setViewportSize({ width: 1198, height: 715 });
  }
  async function applyBoard(page) {
    assert.equal(await page.locator('#agent-module').isDisabled(), true);
    assert.equal(await page.locator('#agent-module').inputValue(), 'padif');
    assert.equal(await page.locator('#agent-module option').count(), 1);
    assert.equal(await page.locator('#agent-access-reason').count(), 0);
    await page.getByRole('button', { name: '申请开通 PAdif Agent', exact: true }).click();
  }
  async function approveBoard(page) {
    await page.goto(base + '/dashboard/agents/?status=pending');
    const row = page.locator('.agent-review-row').filter({ hasText: fixture.users.applicant }).filter({ has: page.locator('[name=request_id]') });
    await row.locator('[name=note]').fill('Approved for local v2 acceptance');
    await row.getByRole('button', { name: '批准开通', exact: true }).click();
  }
  async function applyArticles(page, docs) {
    const application = page.locator('#article-application');
    if (!(await application.getAttribute('open') !== null)) await application.locator('summary').click();
    for (const doc of docs) await page.locator(`#ai-doc-${doc.id}`).check();
    await page.locator('#article-ai-reason').fill('Read these local acceptance drafts');
    await page.getByRole('button', { name: '申请所选文章 AI+', exact: true }).click();
  }
  try {
    const applicant = await login('applicant');
    await applicant.goto(portal);
    assert.match(await applicant.locator('#agent-qualification-title').textContent(), /未开通/);
    assert.equal(await applicant.getByText(hidden.title, { exact: true }).count(), 0);
    await capture(applicant, 'module-application');
    await applyBoard(applicant);
    await applicant.locator('.agent-request-history').first().locator('summary').click();
    await applicant.getByRole('button', { name: '撤回板块申请', exact: true }).click();
    await applyBoard(applicant);
    report.checks.push('Fixed disabled PAdif option, no module purpose field, active application button, withdrawal and reapplication');
    const reviewer = await login('reviewer');
    await reviewer.goto(base + '/dashboard/agents/?status=pending');
    await capture(reviewer, 'module-review');
    await approveBoard(reviewer);
    await applicant.goto(portal);
    assert.match(await applicant.locator('.agent-zero-access').textContent(), /尚无可访问文章/);
    assert.equal(await applicant.locator('[name=document_ids]').count(), 2);
    await capture(applicant, 'article-application');
    await applyArticles(applicant, [first, second]);
    await applicant.locator(`[data-article-id="${second.id}"]`).getByRole('button', { name: '撤回本文申请' }).click();
    await applyArticles(applicant, [second]);
    report.checks.push('Visible-only batch submission and article withdrawal/reapplication');
    const owner = await login('owner');
    await owner.goto(portal);
    assert.equal(await owner.locator('a[href$="/collaboration/"]').count(), 0);
    assert.equal(await owner.locator('[name=role]').count(), 0);
    assert.equal(await owner.locator('button[value=approve-ai]').count(), 0);
    await capture(owner, 'owner-agent-portal');
    await owner.goto(base + `/padif/documents/${first.id}/collaboration/`);
    assert.equal(await owner.getByRole('heading', { name: '人类协作成员', exact: true }).count(), 1);
    assert.equal(await owner.getByRole('heading', { name: '本文 ✦ AI+ 授权', exact: true }).count(), 1);
    const noteBox = await owner.locator('.ai-review-item textarea').first().boundingBox();
    assert.ok(noteBox.height <= 140, 'Approval note must not inherit manuscript height');
    await capture(owner, 'article-review');
    const firstRequest = owner.locator('.ai-review-item').filter({ has: owner.locator('button[value=approve-ai]') });
    await firstRequest.locator('[name=note]').fill('Approved read-only access');
    await firstRequest.getByRole('button', { name: '批准本文 AI+', exact: true }).click();
    await owner.goto(base + `/padif/documents/${second.id}/collaboration/`);
    const secondRequest = owner.locator('.ai-review-item').filter({ has: owner.locator('button[value=reject-ai]') });
    await secondRequest.locator('[name=note]').fill('This draft is not ready');
    await secondRequest.getByRole('button', { name: '驳回申请', exact: true }).click();
    await applicant.goto(portal);
    assert.match(await applicant.locator(`[data-article-id="${first.id}"]`).textContent(), /已授权/);
    assert.match(await applicant.locator(`[data-article-id="${second.id}"]`).textContent(), /未授权/);
    await applicant.locator('#article-access .agent-request-history summary').click();
    assert.match(await applicant.locator('#article-access').textContent(), /已驳回/);
    await capture(applicant, 'partial-results');
    report.checks.push('Agent portal has no creator management; article page separates human members and AI+; partial approvals remain independent');
    const live = applicant.locator(`[data-article-id="${first.id}"]`);
    await live.locator('.agent-relinquish summary').click();
    await live.locator('[name=note]').fill('Local task finished');
    await live.getByRole('button', { name: '放弃本文 AI+', exact: true }).click();
    await applyArticles(applicant, [first]);
    await reviewer.goto(base + '/dashboard/agents/?status=approved');
    const qualification = reviewer.locator('.agent-review-row').filter({ hasText: fixture.users.applicant }).filter({ has: reviewer.locator('[name=user_id]') });
    await qualification.locator('[name=note]').fill('Revoke local PAdif eligibility');
    await qualification.getByRole('button', { name: '撤销开通资格', exact: true }).click();
    await applicant.goto(portal);
    assert.match(await applicant.locator('#agent-qualification-title').textContent(), /已撤销/);
    await applicant.locator('#article-access .agent-request-history summary').click();
    assert.match(await applicant.locator('#article-access').textContent(), /已失效/);
    await capture(applicant, 'revoked');
    await applyBoard(applicant);
    await approveBoard(reviewer);
    await applicant.goto(portal);
    assert.match(await applicant.locator('.agent-zero-access').textContent(), /尚无可访问文章/);
    assert.match(await applicant.locator(`[data-article-id="${first.id}"]`).textContent(), /已撤销/);
    assert.equal((await applicant.context().request.get(base + `/padif/documents/${hidden.id}/`)).status(), 404);
    report.checks.push('Self relinquishment, module revocation, pending invalidation, reapproval without restoring old AI+');
    assert.deepEqual(report.errors, []);
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ output, checks: report.checks, viewports: report.viewports, errors: report.errors }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
