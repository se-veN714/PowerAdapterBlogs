// Isolated local-only acceptance. Fixture IDs are supplied separately; no tokens saved.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const base = process.env.PADIF_MCP_QA_BASE || 'http://127.0.0.1:8772';
  assert.ok(['127.0.0.1', 'localhost'].includes(new URL(base).hostname));
  const password = process.env.PADIF_ACL_QA_PASSWORD;
  assert.ok(password, 'Set PADIF_ACL_QA_PASSWORD for disposable local users');
  const fixture = JSON.parse(await fs.readFile('.local/acl-browser-fixture.json', 'utf8'));
  const output = await fs.mkdtemp(path.resolve('.local/browser-qa/collaboration-'));
  const browser = await chromium.launch({ headless: true });
  const report = { viewports: [], checks: [], errors: [], baselineErrors: [] };
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
      assert.ok(overflow <= 1, `${name}: horizontal overflow ${overflow}`);
      await page.screenshot({ path: path.join(output, `${name}-${viewport.width}.png`), fullPage: true });
      report.viewports.push({ page: name, ...viewport, overflow });
    }
    await page.setViewportSize({ width: 1198, height: 715 });
  }
  const url = base + `/padif/documents/${fixture.document_id}/`;
  try {
    const owner = await login('owner');
    await owner.goto(url);
    await owner.getByRole('link', { name: '管理协作授权', exact: true }).click();
    await capture(owner, 'owner-collaboration');
    const member = owner.locator(`[data-ai-member="${fixture.users.viewer}"]`);
    const human = owner.locator(`[data-human-member="${fixture.users.viewer}"]`);
    const ai = member.locator('[name=enabled]');
    assert.equal(await ai.isChecked(), false);
    await ai.check();
    await member.locator('[name=note]').fill('Local explicit AI+ grant');
    await member.getByRole('button', { name: '保存 AI+ 授权', exact: true }).click();
    assert.equal(await ai.isChecked(), true);
    report.checks.push('Owner explicitly enables per-document viewer AI+ through CSRF-protected form');
    await human.locator('[name=role]').selectOption('collaborator');
    await human.getByRole('button', { name: '更新角色', exact: true }).click();
    const changed = owner.locator(`[data-human-member="${fixture.users.viewer}"]`);
    assert.equal(await member.locator('[name=enabled]').isChecked(), false);
    await changed.locator('[name=role]').selectOption('viewer');
    await changed.getByRole('button', { name: '更新角色', exact: true }).click();
    report.checks.push('Role change resets AI+; restoring role does not restore grant');

    const viewer = await login('viewer');
    await viewer.goto(url);
    assert.equal(await viewer.locator('.main-add-version').count(), 0);
    assert.equal(await viewer.getByRole('link', { name: '管理协作授权' }).count(), 0);
    assert.equal(await viewer.locator('#padif-editor').getAttribute('inert'), '');
    assert.equal(await viewer.locator('[data-padif-annotation-form]').count(), 0);
    const closeDrawer = viewer.locator('[data-drawer-close]');
    if (await closeDrawer.isVisible()) await closeDrawer.click();
    await viewer.locator('.editor-panel > summary').click();
    await viewer.getByRole('button', { name: '全屏预览', exact: true }).click();
    await viewer.locator('#padif-preview-modal').waitFor({ state: 'visible' });
    assert.match(await viewer.locator('#padif-preview-content').textContent(), /First paragraph/);
    assert.ok(await viewer.locator('#padif-preview-line-numbers li').count() >= 5);
    await capture(viewer, 'viewer-preview');
    await viewer.getByRole('button', { name: '关闭预览', exact: true }).click();
    assert.equal((await viewer.context().request.get(url + 'collaboration/')).status(), 403);
    report.checks.push('Viewer has working fullscreen preview/source lines but no edit, annotation or management controls');

    const writer = await login('writer');
    await writer.goto(url);
    assert.equal(await writer.locator('.main-add-version').count(), 0); // main is owner-only
    assert.ok(await writer.locator('.branch-fork').count() > 0);
    assert.equal(await writer.locator('[data-padif-annotation-form]').count(), 1);
    report.checks.push('Collaborator can fork and annotate; main remains owner-only');

    const stranger = await login('stranger');
    await stranger.goto(base + '/padif/');
    assert.equal(await stranger.getByText('ACL local browser acceptance', { exact: true }).count(), 0);
    assert.equal((await stranger.context().request.get(url)).status(), 404);
    report.checks.push('Unshared user cannot discover or directly read document');
    await owner.goto(url + 'collaboration/');
    const removed = owner.locator(`[data-human-member="${fixture.users.viewer}"]`);
    await removed.getByRole('button', { name: '移除成员', exact: true }).click();
    assert.equal((await viewer.context().request.get(url)).status(), 404);
    report.checks.push('Removal immediately blocks existing authenticated session');
    assert.deepEqual(report.errors, []);
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ output, ...report }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
