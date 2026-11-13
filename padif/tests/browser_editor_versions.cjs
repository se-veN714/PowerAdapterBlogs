const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

const base = process.env.PADIF_EDITOR_QA_BASE || 'http://127.0.0.1:8779';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Local QA only');

(async () => {
  const fixture = JSON.parse(await fs.readFile('.local/editor-version-qa.json', 'utf8'));
  const output = await fs.mkdtemp(path.resolve('.local/browser-qa/editor-versions-'));
  const browser = await chromium.launch({headless: true});
  const report = {target: base, documentId: fixture.document_id, results: [], errors: [], baselineErrors: []};
  const doc = `/padif/documents/${fixture.document_id}/`;
  try {
    for (const viewport of [{width:1915,height:930}, {width:1198,height:715}, {width:390,height:844}]) {
      const context = await browser.newContext({viewport});
      const page = await context.newPage();
      page.on('pageerror', error => {
        const stack = error.stack || error.message;
        if (stack.includes('https://cdn.jsdelivr.net/npm/mathjax@3/es5/startup.js') && stack.includes('Cannot set property Package')) report.baselineErrors.push(stack);
        else report.errors.push(stack);
      });
      await page.goto(base+'/accounts/login/');
      await page.locator('[name=username]').fill(fixture.username);
      await page.locator('[name=password]').fill(fixture.password);
      await page.locator('button[type=submit]').first().click();
      await page.goto(base+doc+'?branch=writing');
      const version = page.locator('[data-editor-version]');
      const branch = page.locator('[data-editor-branch]');
      const editor = page.locator('.toastui-editor-md-container .ProseMirror');
      const state = page.locator('[data-editor-dirty-state]');
      const dialog = page.locator('[data-editor-leave-dialog]');
      const choose = async value => {
        await version.selectOption(String(value));
        await page.waitForFunction(id => document.querySelector('#padif-editor-form').dataset.version === String(id), value);
        await editor.waitFor();
      };
      await editor.waitFor({state:'attached'});
      await page.locator('[data-drawer-close]').click();
      await page.locator('.editor-panel > summary').click();
      assert.equal(await version.inputValue(), String(fixture.latest_id));
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      await editor.focus();
      await page.keyboard.press('Control+End');
      await page.keyboard.press('Enter');
      await page.keyboard.type('LOCAL UNSAVED DRAFT', {delay:15});
      assert.ok((await editor.textContent()).includes('LOCAL UNSAVED DRAFT'), 'Native editor input before navigation');
      await page.locator('#padif-editor-form [name=commit_message]').fill('Draft explanation');
      await page.locator('#padif-editor-form [name=version_kind]').selectOption('minor');
      await page.waitForFunction(() => document.querySelector('[data-editor-dirty-state]').textContent === '未保存修改');
      await version.selectOption(String(fixture.old_id));
      await dialog.waitFor({state:'visible'});
      await page.locator('[data-editor-leave=cancel]').click();
      assert.equal(await version.inputValue(), String(fixture.latest_id));
      assert.ok((await editor.textContent()).includes('LOCAL UNSAVED DRAFT'));
      await version.selectOption(String(fixture.old_id));
      await page.locator('[data-editor-leave=keep]').click();
      await page.waitForFunction(id => document.querySelector('#padif-editor-form').dataset.version === String(id), fixture.old_id);
      await editor.waitFor();
      assert.ok((await editor.textContent()).includes('Earlier paragraph'));
      await page.waitForFunction(() => document.activeElement === document.querySelector('[data-editor-version]'));
      assert.equal(await page.locator('#padif-editor[inert]').count(), 1);
      assert.equal(await page.getByRole('button',{name:'保存新版本',exact:true}).count(), 0);
      assert.equal(await page.locator('.editor-panel').getAttribute('open'), '');
      assert.equal(await page.locator('[data-version-drawer]').isVisible(), false);
      await page.locator('[data-padif-preview]').click();
      await page.locator('#padif-preview-modal').waitFor({state:'visible'});
      assert.ok((await page.locator('#padif-preview-content').textContent()).includes('Earlier paragraph'));
      assert.ok((await page.locator('#padif-preview-toc-list').textContent()).includes('Earlier'));
      assert.ok((await page.locator('[data-padif-annotation-list]').textContent()).includes('Earlier version note'));
      await page.locator('[data-padif-preview-close]').click();
      if (viewport.width === 1915) {
        await page.evaluate(({user, doc, old}) => sessionStorage.setItem(`padif.editor.draft:${user}:${doc}:writing:${old}`,
          JSON.stringify({content:'# Preserved historical draft', message:'Historical explanation', kind:'minor', created:Date.now()})),
          {user:await page.locator('#padif-editor-form').getAttribute('data-user'),doc:fixture.document_id,old:fixture.old_id});
        await page.reload();
        await editor.waitFor({state:'attached'});
        if (!(await page.locator('.editor-panel').getAttribute('open'))) await page.locator('.editor-panel > summary').click();
        await page.locator('[data-editor-draft-restore]').click();
        assert.ok((await editor.textContent()).includes('Preserved historical draft'));
        assert.equal(await page.locator('#padif-editor[inert]').count(), 1);
        await page.locator('[data-editor-latest]').click();
        await page.locator('[data-editor-leave=discard]').click();
      } else await page.locator('[data-editor-latest]').click();
      await page.locator('[data-editor-draft-restore]').waitFor({state:'visible'});
      await page.locator('[data-editor-draft-restore]').click();
      assert.ok((await editor.textContent()).includes('LOCAL UNSAVED DRAFT'));
      assert.equal(await page.locator('#padif-editor-form [name=commit_message]').inputValue(), 'Draft explanation');
      assert.equal(await page.locator('#padif-editor-form [name=version_kind]').inputValue(), 'minor');
      await branch.selectOption('other');
      await page.locator('[data-editor-leave=discard]').click();
      await page.waitForFunction(id => document.querySelector('#padif-editor-form').dataset.version === String(id), fixture.other_id);
      await editor.waitFor();
      await branch.selectOption('writing');
      await page.waitForFunction(id => document.querySelector('#padif-editor-form').dataset.version === String(id), fixture.latest_id);
      await editor.waitFor();
      assert.equal(await page.locator('[data-editor-draft-notice]').isVisible(), false);
      assert.ok(!(await editor.textContent()).includes('LOCAL UNSAVED DRAFT'));
      await page.locator('[data-editor-locate]').click();
      assert.equal(await page.locator('[data-version-drawer]').isVisible(), true);
      await page.locator(`[data-worldline-version="${fixture.old_id}"]`).click();
      await page.waitForFunction(id => document.querySelector('#padif-editor-form').dataset.version === String(id), fixture.old_id);
      await editor.waitFor();
      assert.equal(await page.locator(`[data-worldline-version="${fixture.old_id}"].is-current`).count(), 1);
      assert.equal(await page.locator(`[data-worldline-version="${fixture.latest_id}"].is-head`).count(), 1);
      await page.screenshot({path:path.join(output, `historical-drawer-${viewport.width}.png`), fullPage:true});
      await page.locator('[data-drawer-close]').click();
      await page.screenshot({path:path.join(output, `historical-${viewport.width}.png`), fullPage:true});
      await choose(fixture.latest_id);
      await editor.focus();
      await page.keyboard.press('Control+End');
      await page.keyboard.press('Enter');
      await page.keyboard.type('STORAGE FAILURE DRAFT', {delay:15});
      await page.waitForFunction(() => document.querySelector('[data-editor-dirty-state]').textContent === '未保存修改');
      await page.evaluate(() => { window.qaSetItem = Storage.prototype.setItem; Storage.prototype.setItem = () => { throw new Error('QA quota'); }; });
      await version.selectOption(String(fixture.old_id));
      await page.locator('[data-editor-leave=keep]').click();
      assert.equal(await page.locator('[data-editor-storage-error]').isVisible(), true);
      assert.equal(await version.inputValue(), String(fixture.latest_id));
      await page.locator('[data-editor-leave=cancel]').click();
      await page.evaluate(() => { Storage.prototype.setItem = window.qaSetItem; });
      let unloadPrompt = false;
      page.once('dialog', async native => { unloadPrompt = native.type() === 'beforeunload'; await native.dismiss(); });
      await page.reload({timeout:3000, waitUntil:'domcontentloaded'}).catch(error => {
        if (!error.message.includes('ERR_ABORTED') && !(unloadPrompt && error.name === 'TimeoutError')) throw error;
      });
      assert.equal(unloadPrompt, true);
      assert.ok((await editor.textContent()).includes('STORAGE FAILURE DRAFT'), 'Dismissed unload keeps the unsaved manuscript');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
      assert.ok(overflow <= 1, 'Page overflow '+overflow);
      report.results.push({...viewport, overflow, draftKeepRestoreDiscardCancel:true, storageFailureBlocked:true,
        nativeUnloadProtected:true, nodeAndDropdownNavigation:true, drawerAndEditorState:true});
      await context.close();
    }
    assert.deepEqual(report.errors, []);
    console.log(JSON.stringify({output, results:report.results}));
  } finally {
    await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
