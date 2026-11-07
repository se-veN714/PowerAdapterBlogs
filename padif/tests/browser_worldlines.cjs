const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

// Requires local preview plus Playwright; no manuscript is submitted by this test.
const base = process.env.PADIF_QA_BASE_URL || 'http://127.0.0.1:8771';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Browser acceptance is restricted to local services');
const password = process.env.PADIF_QA_PASSWORD;
if (!password) throw new Error('Set PADIF_QA_PASSWORD for the disposable local preview account');
const documentId = Number(process.env.PADIF_QA_DOCUMENT_ID || 2);
if (!Number.isSafeInteger(documentId) || documentId < 1) throw new Error('Invalid local QA document id');
const doc = `/padif/documents/${documentId}/`;
const output = path.resolve(process.cwd(), '.local/browser-qa/worldlines');
const results = [];
const report = { tool: 'Playwright ' + require('playwright/package.json').version,
  target: base + doc, browser: 'isolated Chromium', developmentToolbar: 'disabled in local runtime only', results };

async function login(context) {
  const response = await context.request.get(base + '/accounts/login/');
  const token = (await response.text()).match(/name="csrfmiddlewaretoken" value="([^"]+)"/)[1];
  const logged = await context.request.post(base + '/accounts/login/', {
    form: { username: process.env.PADIF_QA_USERNAME || 'branch_preview', password, csrfmiddlewaretoken: token, next: doc + '?branch=opening' },
    headers: { Referer: base + '/accounts/login/' }, maxRedirects: 0,
  });
  assert.equal(logged.status(), 302, 'local preview login');
}

async function geometry(page) {
  return page.evaluate(() => {
    const rect = selector => document.querySelector(selector).getBoundingClientRect().toJSON();
    const drawer = document.querySelector('[data-version-drawer]');
    const graph = document.querySelector('.worldline-graph');
    const graphBox = graph.getBoundingClientRect();
    return { width: innerWidth, height: innerHeight,
      pageOverflow: document.documentElement.scrollWidth - innerWidth,
      drawerOverflow: drawer.scrollWidth - drawer.clientWidth, scrollY,
      drawerStyle: {position:getComputedStyle(drawer).position,top:getComputedStyle(drawer).top,bottom:getComputedStyle(drawer).bottom,height:getComputedStyle(drawer).height,alignSelf:getComputedStyle(drawer).alignSelf},
      main: rect('.document-main'), drawer: drawer.hidden ? null : rect('[data-version-drawer]'),
      editor: rect('#padif-editor'),
      heads: [...graph.querySelectorAll('.worldline-head')].map(head => {
        const r = head.getBoundingClientRect();
        return { name: head.textContent.trim(), left: r.left - graphBox.left, right: r.right - graphBox.right, top: r.top - graphBox.top };
      }) };
  });
}

async function checkRetained(page, marker) {
  const state = await page.evaluate(() => {
    const saved = window.__padifAcceptance;
    const fileField = document.querySelector('.main-add-version__grid input[type=file]');
    return { sameEditor: saved.editor === document.getElementById('padif-editor'),
      sameEditable: saved.editable === document.querySelector('.toastui-editor-md-container [contenteditable=true]'),
      sameFile: saved.file === fileField.files[0], filename: fileField.files[0]?.name,
      text: saved.editable.innerText, message: document.querySelector('.main-add-version__meta input[name=commit_message]').value };
  });
  assert.equal(state.sameEditor, true, 'editor DOM survives drawer operations');
  assert.equal(state.sameEditable, true, 'editable DOM survives drawer operations');
  assert.equal(state.sameFile, true, 'selected File object survives drawer operations');
  assert.equal(state.filename, 'qa-unsaved.md');
  assert.ok(state.text.includes(marker), 'unsaved manuscript remains');
  assert.equal(state.message, 'QA unsaved upload note');
}

function assertGeometry(measurement, viewport) {
  assert.equal(measurement.width, viewport.width);
  assert.equal(measurement.height, viewport.height);
  assert.ok(measurement.pageOverflow <= 1, 'no page horizontal overflow: ' + measurement.pageOverflow);
  if (measurement.drawer) {
    assert.ok(measurement.drawer.left >= 0 && measurement.drawer.right <= viewport.width + 1, 'drawer fits viewport horizontally');
    assert.ok(measurement.drawer.top >= 0 && measurement.drawer.bottom <= viewport.height + 1, 'drawer fits viewport vertically');
    assert.ok(measurement.drawerOverflow <= 1, 'no drawer content clipping/overflow: ' + measurement.drawerOverflow);
    for (const head of measurement.heads) assert.ok(head.left >= -1 && head.right <= 1 && head.top >= 0, 'worldline label fits graph: ' + JSON.stringify(head));
  }
}

async function runViewport(browser, viewport) {
  const name = `${viewport.width}x${viewport.height}`;
  const result = { viewport, status: 'running', screenshots: [], pageErrors: [], checks: [] };
  results.push(result);
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  context.setDefaultTimeout(10000);
  context.setDefaultNavigationTimeout(15000);
  const page = await context.newPage();
  page.on('pageerror', error => result.pageErrors.push(error.stack || error.message));
  try {
    await login(context);
    await page.goto(base + doc + '?branch=opening');
    await page.waitForSelector('[data-drawer-close]:not([hidden])');
    assert.equal(await page.locator('[data-worldline-branch]').count(), 3);
    const initial = await geometry(page);
    result.initial = initial;
    assertGeometry(initial, viewport);
    await page.screenshot({ path: path.join(output, `${name}-open.png`) });
    result.screenshots.push(`${name}-open.png`);

    if (viewport.width <= 1400) await page.locator('[data-drawer-close]').click();
    await page.locator('.editor-panel > summary').click();
    const editable = page.locator('.toastui-editor-md-container [contenteditable=true]');
    await editable.waitFor({ state: 'visible' });
    await editable.click();
    await page.keyboard.press('Control+End');
    await page.keyboard.press('Enter');
    const marker = `QA_KEEP_DRAFT_${name}`;
    await page.keyboard.insertText(marker);
    await page.locator('.main-add-version__grid input[type=file]').setInputFiles({ name: 'qa-unsaved.md', mimeType: 'text/markdown', buffer: Buffer.from('# Temporary QA file\n') });
    await page.locator('.main-add-version__meta input[name=commit_message]').fill('QA unsaved upload note');
    await page.evaluate(() => {
      window.__padifAcceptance = { editor: document.getElementById('padif-editor'),
        editable: document.querySelector('.toastui-editor-md-container [contenteditable=true]'),
        file: document.querySelector('.main-add-version__grid input[type=file]').files[0] };
    });

    if (viewport.width <= 1400) await page.locator('[data-drawer-handle]').click();
    await page.locator('[data-drawer-close]').click();
    await page.waitForFunction(() => document.querySelector('[data-version-drawer]').hidden);
    assert.equal(await page.evaluate(() => document.activeElement === document.querySelector('[data-drawer-handle]')), true);
    await checkRetained(page, marker);
    const closed = await geometry(page);
    assertGeometry(closed, viewport);
    const gain = closed.main.width - initial.main.width;
    if (viewport.width > 1400) assert.ok(gain > 600, 'wide editor gains drawer width');
    else assert.ok(Math.abs(gain) <= 2, 'overlay drawer does not squeeze narrow editor');
    result.closed = closed;
    result.editorWidthGain = gain;
    await page.screenshot({ path: path.join(output, `${name}-closed-editing.png`) });
    result.screenshots.push(`${name}-closed-editing.png`);
    result.checks.push('collapse: hidden, editor width, focus on handle, manuscript and File object retained');

    await page.locator('[data-drawer-handle]').click();
    await page.waitForFunction(() => !document.querySelector('[data-version-drawer]').hidden);
    assert.equal(await page.evaluate(() => document.querySelector('[data-version-drawer]').contains(document.activeElement)), true);
    await checkRetained(page, marker);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('[data-version-drawer]').isHidden(), true);
    assert.equal(await page.evaluate(() => document.activeElement === document.querySelector('[data-drawer-handle]')), true);
    await page.locator('[data-drawer-handle]').click();
    const opening = page.locator('.worldline-head[href="?branch=opening"]');
    await opening.focus();
    await page.keyboard.press('Escape');
    await page.locator('[data-drawer-handle]').click();
    assert.equal(await opening.evaluate(el => el === document.activeElement), true, 'reopening restores branch-head focus');
    result.checks.push('reopen/Escape: remembered internal focus, no manuscript or file loss');

    const toggle = page.locator('[data-rail-toggle]');
    const oldUrl = page.url();
    await toggle.click();
    assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
    assert.equal(await toggle.evaluate(el => el === document.activeElement), true);
    assert.equal(page.url(), oldUrl);
    await checkRetained(page, marker);
    await toggle.click();
    assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
    await checkRetained(page, marker);
    result.checks.push('branch detail disclosure: in-place, focus and unsaved state retained');

    console.log(name, 'draft, width, Escape, and disclosure checks passed');
    // Navigate only after deliberately abandoning the disposable QA draft; never submit it.
    await page.goto(base + doc + '?branch=opening');
    if (viewport.width <= 1400) await page.locator('[data-drawer-close]').click();
    await page.locator('.editor-panel > summary').click();
    if (viewport.width <= 1400) await page.locator('[data-drawer-handle]').click();
    await page.evaluate(() => window.scrollTo(0, Math.min(300, document.documentElement.scrollHeight - innerHeight)));
    const ending = page.locator('.worldline-head[href="?branch=ending"]');
    await ending.scrollIntoViewIfNeeded();
    const beforeSwitch = await page.evaluate(() => ({ scrollY, rail: document.querySelector('[data-version-drawer]').scrollTop }));
    const focusKey = await ending.getAttribute('data-rail-focus');
    await ending.click();
    await page.waitForURL('**?branch=ending');
    await page.waitForFunction(key => document.activeElement?.dataset.railFocus === key, focusKey);
    const afterSwitch = await page.evaluate(() => ({ scrollY, rail: document.querySelector('[data-version-drawer]').scrollTop }));
    result.switchScroll = { before: beforeSwitch, after: afterSwitch };
    assert.ok(Math.abs(afterSwitch.scrollY - beforeSwitch.scrollY) <= 3, 'branch switch retains window scroll position');
    result.checks.push('switch branch: focus restored to selected head, page scroll retained');

    await page.locator('[data-drawer-close]').click();
    await page.reload();
    await page.waitForFunction(() => document.querySelector('[data-version-drawer]').hidden);
    assert.equal(await page.locator('[data-drawer-handle]').isVisible(), true);
    result.checks.push('reload: collapsed preference survives');
    await page.locator('[data-drawer-handle]').click();
    await page.evaluate(() => { window.scrollTo(0, 0); document.querySelector('[data-version-drawer]').scrollTop = 0; });
    result.final = await geometry(page);
    assertGeometry(result.final, viewport);
    assert.deepEqual(result.pageErrors, [], 'no JavaScript page errors on document pages');
    result.status = 'passed';
  } catch (error) {
    result.status = 'failed';
    result.error = error.stack;
    result.failureState = await page.evaluate(() => ({ active: document.activeElement.outerHTML.slice(0,500), scrollY, editorOpen: document.querySelector('.editor-panel')?.open, focusKeys: [...document.querySelectorAll('[data-rail-focus]')].map(el=>el.dataset.railFocus), storage: {...sessionStorage} })).catch(()=>null);
    await page.screenshot({ path: path.join(output, `${name}-failure.png`) }).catch(() => {});
    console.error(name, error.message);
  } finally { await context.close(); }
  console.log(name, result.status, JSON.stringify({ widthGain: result.editorWidthGain, switchScroll: result.switchScroll, errors: result.pageErrors }));
}

(async () => {
  delete process.env.SSLKEYLOGFILE;
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  try {
    for (const viewport of [{ width: 1198, height: 715 }, { width: 1920, height: 1080 }]) await runViewport(browser, viewport);
  } finally { await browser.close(); }
  await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  if (results.some(result => result.status !== 'passed')) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; });
