const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const base = process.env.PADIF_EDITOR_QA_BASE || 'http://127.0.0.1:8781';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw Error('Local QA only');

(async () => {
  const fixture = JSON.parse(await fs.readFile('.local/editor-version-qa.json', 'utf8'));
  const output = await fs.mkdtemp(path.resolve('.local/browser-qa/cloud-drafts-'));
  const browser = await chromium.launch({headless: true});
  const report = {results: [], errors: []};
  const url = `${base}/padif/documents/${fixture.document_id}/?branch=writing`;
  const prepare = async page => {
    page.on('pageerror', error => {
      if (!String(error.stack).includes('mathjax')) report.errors.push(String(error.stack));
    });
    await page.goto(url);
    await page.locator('[data-cloud-draft-status]').waitFor({state:'attached'});
    const drawer = page.locator('[data-drawer-close]');
    if (await drawer.isVisible()) await drawer.click();
    const summary = page.locator('.editor-panel > summary');
    if (!await page.locator('[data-cloud-draft]').isVisible()) await summary.click();
    await page.locator('[data-cloud-draft-status]').filter({hasText: /云端草稿/}).waitFor();
    await page.locator('.toastui-editor-md-container .ProseMirror').waitFor();
  };
  const type = async (page, text) => {
    const editor = page.locator('.toastui-editor-md-container .ProseMirror');
    await editor.focus(); await page.keyboard.press('Control+End');
    await page.keyboard.press('Enter'); await page.keyboard.type(text);
  };
  try {
    for (const viewport of [{width:1915,height:930},{width:1198,height:715},{width:390,height:844}]) {
      let context = await browser.newContext({viewport});
      let page = await context.newPage();
      await page.goto(base + '/accounts/login/');
      await page.locator('[name=username]').fill(fixture.username);
      await page.locator('[name=password]').fill(fixture.password);
      await page.locator('button[type=submit]').first().click();
      await page.waitForURL(address => !address.pathname.includes('/login/'));
      await prepare(page);
      if (viewport.width <= 650) {
        await page.locator('[data-drawer-handle]').click();
        await page.locator('[data-version-drawer]').waitFor({state:'visible'});
        await page.locator('[data-drawer-close]').click();
        await page.locator('[data-version-drawer]').waitFor({state:'hidden'});
        const width = (await page.locator('.toastui-editor-md-container .toastui-editor').boundingBox()).width;
        const container = (await page.locator('.toastui-editor-md-container').boundingBox()).width;
        assert.ok(width >= container - 4, 'Mobile Markdown input fills the editor');
        assert.equal(await page.locator('.toastui-editor-md-preview').isVisible(), false);
      }
      assert.deepEqual(await page.locator('.padif-editor-tools__actions > button').allTextContents(),
        ['保存草稿', '全屏编辑', '全屏预览']);
      const originalWidth = (await page.locator('#padif-editor').boundingBox()).width;
      await page.locator('[data-editor-fullscreen]').click();
      await page.locator('#padif-editor-form.is-editor-fullscreen').waitFor();
      const expanded = await page.locator('#padif-editor').boundingBox();
      assert.ok(expanded.height > 200 && expanded.y + expanded.height <= viewport.height);
      if (viewport.width > 650) assert.ok(expanded.width > originalWidth);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth), 0);
      const text = `CLOUD PRIVATE ${viewport.width}`;
      await type(page, text);
      if (viewport.width <= 650) {
        await page.keyboard.press('Control+Home');
        await page.keyboard.insertText('# 手机目录\n\n');
      }
      // No commit message is required for a working draft.
      await page.locator('[data-cloud-draft-status]').filter({hasText:'云端草稿已保存'}).waitFor();
      await page.locator('[data-padif-preview]').click();
      await page.locator('#padif-preview-modal').waitFor({state:'visible'});
      assert.ok((await page.locator('#padif-preview-content').textContent()).includes(text));
      if (viewport.width <= 650) {
        for (const [mode, target] of [['toc', 'padif-preview-toc'], ['annotations', 'padif-preview-annotations']]) {
          const sheet = page.locator('#' + target);
          assert.equal(await sheet.isVisible(), false);
          await page.locator('[data-preview-sheet-open="' + mode + '"]').click();
          await sheet.waitFor({state:'visible'});
          if (mode === 'toc') await sheet.locator('a').first().click();
          else await sheet.locator('[data-preview-sheet-close]').click();
          await sheet.waitFor({state:'hidden'});
        }
        const sourceLines = await page.locator('#padif-preview-line-numbers > li').evaluateAll(lines =>
          lines.map(line => ({number:Number(line.dataset.line), top:parseFloat(line.style.top)})));
        assert.deepEqual(sourceLines.slice(0, 4).map(line => line.number), [1, 2, 3, 4]);
        assert.ok(sourceLines[1].top < sourceLines[2].top, 'Consecutive Markdown blank lines have distinct markers');
        await page.screenshot({path:path.join(output, 'mobile-preview.png')});
      }
      await page.keyboard.press('Escape');
      await page.locator('#padif-preview-modal').waitFor({state:'hidden'});
      assert.equal(await page.locator('#padif-editor-form').getAttribute('class'), 'is-editor-fullscreen');
      await page.screenshot({path:path.join(output, `fullscreen-${viewport.width}.png`)});
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('[data-editor-fullscreen]').getAttribute('aria-pressed'), 'false');
      assert.ok((await page.locator('.toastui-editor-md-container .ProseMirror').textContent()).includes(text));
      const auth = await context.storageState();
      await context.close();
      context = await browser.newContext({viewport, storageState:auth});
      page = await context.newPage(); await prepare(page);
      await page.locator('[data-cloud-draft-restore]').click();
      assert.ok((await page.locator('.toastui-editor-md-container .ProseMirror').textContent()).includes(text));
      const second = await context.newPage(); await prepare(second);
      await second.locator('[data-cloud-draft-restore]').click();
      await type(page, 'FIRST TAB');
      await page.locator('[data-cloud-draft-save]').click();
      await page.locator('[data-cloud-draft-status]').filter({hasText:'云端草稿已保存'}).waitFor();
      await type(second, 'SECOND TAB');
      await second.locator('[data-cloud-draft-save]').click();
      await second.locator('[data-cloud-draft-status]').filter({hasText:'其他标签页已更改'}).waitFor();
      assert.ok((await second.locator('.toastui-editor-md-container .ProseMirror').textContent()).includes('SECOND TAB'));
      await second.close();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
      assert.equal(overflow, 0);
      await page.screenshot({path:path.join(output, `draft-${viewport.width}.png`), fullPage:true});
      await page.locator('[data-cloud-draft-delete]').click();
      await page.locator('[data-cloud-draft-status]').filter({hasText:'云端草稿已删除'}).waitFor();
      await page.route('**/drafts/*/', route => route.request().method() === 'POST' ? route.abort() : route.continue());
      await type(page, 'NETWORK FAILED STILL IN EDITOR');
      await page.locator('[data-cloud-draft-save]').click();
      await page.locator('[data-cloud-draft-status]').filter({hasText:'云端保存失败'}).waitFor();
      assert.ok((await page.locator('.toastui-editor-md-container .ProseMirror').textContent()).includes('NETWORK FAILED'));
      if (viewport.width === 1915) {
        await page.unroute('**/drafts/*/');
        await type(page, 'FAST SWITCH FLUSH');
        await page.locator('[data-editor-version]').selectOption(String(fixture.old_id));
        await page.locator('[data-editor-leave=keep]').click();
        await page.waitForFunction(id => document.querySelector('#padif-editor-form')?.dataset.version === String(id), fixture.old_id);
        await page.locator('[data-cloud-draft-other] a').click();
        await page.waitForFunction(id => document.querySelector('#padif-editor-form')?.dataset.version === String(id), fixture.latest_id);
        await page.locator('[data-cloud-draft-restore]').click();
        assert.ok((await page.locator('.toastui-editor-md-container .ProseMirror').textContent()).includes('FAST SWITCH FLUSH'));
        await page.locator('[data-cloud-draft-delete]').click();
        await page.locator('[data-cloud-draft-status]').filter({hasText:'云端草稿已删除'}).waitFor();
      }
      if (viewport.width <= 650) {
        const retryPage = await context.newPage();
        await retryPage.route('**/drafts/*/', route => route.fulfill({status:403}));
        await prepare(retryPage);
        const status = retryPage.locator('[data-cloud-draft-status]');
        await status.filter({hasText:'服务器拒绝草稿请求'}).waitFor();
        await retryPage.unroute('**/drafts/*/');
        await retryPage.locator('[data-cloud-draft-retry]').click();
        await status.filter({hasText:'修改后自动保存'}).waitFor();
      }
      report.results.push({...viewport, overflow, crossSessionRestore:true, autoSave:true,
        explicitSave:true, concurrentTabRejected:true, failedSaveKeepsEditor:true,
        fullscreenEditPreviewAndExit:true,
        flushBeforeNavigation:viewport.width === 1915});
      await context.close();
    }
    assert.deepEqual(report.errors, []);
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({output, ...report}));
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
