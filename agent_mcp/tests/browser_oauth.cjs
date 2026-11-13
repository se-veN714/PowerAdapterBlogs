const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { spawn } = require('node:child_process');
const http = require('node:http');
const { createHash } = require('node:crypto');

const base = process.env.PADIF_MCP_QA_BASE || 'http://127.0.0.1:8772';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Local QA hosts only');
const password = process.env.PADIF_MCP_QA_PASSWORD;
if (!password) throw new Error('Set PADIF_MCP_QA_PASSWORD for the disposable local account');

async function waitJson(file) {
  for (let i = 0; i < 450; i++) {
    try { return JSON.parse(await fs.readFile(file, 'utf8')); } catch (error) {
      if (error.code !== 'ENOENT' && !(error instanceof SyntaxError)) throw error;
    }
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error('Timed out waiting for ' + path.basename(file));
}

(async () => {
  const output = await fs.mkdtemp(path.resolve('.local/browser-qa/mcp-'));
  const callbackServer = http.createServer(async (request, response) => {
    const url = new URL(request.url, 'http://127.0.0.1:9919');
    if (url.pathname !== '/callback' || !url.searchParams.get('code')) {
      response.writeHead(400); response.end('Missing authorization code'); return;
    }
    await fs.writeFile(path.join(output, 'callback.json'), JSON.stringify({ code: url.searchParams.get('code'), state: url.searchParams.get('state') }));
    response.writeHead(200, { 'Content-Type': 'text/html' });
    response.end('<p>Local OAuth callback complete. Return to PAdif.</p>');
  });
  await new Promise(resolve => callbackServer.listen(9919, '127.0.0.1', resolve));
  const child = spawn(path.resolve('.venv/Scripts/python.exe'), ['agent_mcp/tests/e2e_client.py'], {
    env: { ...process.env, PADIF_MCP_QA_BASE: base, PADIF_MCP_QA_EXCHANGE_DIR: output }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let clientLog = '';
  child.stdout.on('data', chunk => { clientLog += chunk; });
  child.stderr.on('data', chunk => { clientLog += chunk; });
  const finished = new Promise(resolve => child.on('exit', code => resolve(code)));
  const browser = await chromium.launch({ headless: true });
  const report = { browser: 'isolated Chromium', client: 'official Python MCP SDK', registration: process.env.PADIF_MCP_QA_DCR === '1' ? 'dynamic' : 'pre-registered', viewports: [], errors: [], baselineErrors: [] };
  try {
    const context = await browser.newContext({ viewport: { width: 1198, height: 715 } });
    const page = await context.newPage();
    page.on('pageerror', error => {
      const stack = error.stack || error.message;
      // Independently reproduced on the existing login page: base.html loads
      // both the MathJax bundle and startup.js. Preserve evidence, not silence it.
      if (stack.includes('https://cdn.jsdelivr.net/npm/mathjax@3/es5/startup.js') && stack.includes('Cannot set property Package')) report.baselineErrors.push(stack);
      else report.errors.push(stack);
    });
    await page.goto(base + '/accounts/login/');
    await page.locator('input[name=username]').fill(process.env.PADIF_MCP_QA_USERNAME || 'mcp_preview');
    await page.locator('input[name=password]').fill(password);
    await page.locator('button[type=submit]').first().click();
    await page.goto(base + '/accounts/security/agents/');
    for (const viewport of [{ width: 1198, height: 715 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      await page.locator('#mcp-url').waitFor();
      await page.getByText('连接帮助', { exact: true }).click();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
      assert.ok(overflow <= 1, 'Guide has horizontal overflow: ' + overflow);
      await page.evaluate(async () => { scrollTo(0, 0); await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame); });
      await page.screenshot({ path: path.join(output, `guide-${viewport.width}.png`), fullPage: true });
      await page.getByText('连接帮助', { exact: true }).click();
      report.viewports.push({ ...viewport, overflow });
    }
    const authorization = await waitJson(path.join(output, 'authorize.json'));
    assert.equal(new URL(authorization.url).origin, new URL(base).origin);
    await page.goto(authorization.url);
    const read = page.locator('[name=approved_scope][value="padif:read"]');
    await read.waitFor();
    assert.ok(await read.isChecked());
    assert.equal(await page.locator('[name=approved_scope][value="padif:version"]').isChecked(), false);
    for (const viewport of [{ width: 1198, height: 715 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await page.evaluate(async () => { scrollTo(0, 0); await new Promise(requestAnimationFrame); await new Promise(requestAnimationFrame); });
      await page.screenshot({ path: path.join(output, `consent-${viewport.width}.png`), fullPage: true });
    }
    await page.locator('[name=approved_scope][value="padif:version"]').check();
    await page.locator('[name=approved_scope][value="padif:annotate"]').check();
    await page.getByRole('button', { name: '允许连接', exact: true }).click();
    if (process.env.PADIF_MCP_QA_UPLOAD === '1') {
      report.uploads = [];
      for (let index = 0; index < 7; index++) {
        const task = await waitJson(path.join(output, `upload-${index}.json`));
        const paragraph = '这是一段用于验收的稿件：“中文引号”、反斜线\\与表情🙂都需要原样保留。\n\n';
        const text = `# 稿件 ${index + 1}\n\n` + paragraph.repeat(Math.ceil((9000+index*1200)/Array.from(paragraph).length)) +
          '```html\n<script>window.uploadXss = true</script>\n```\n\n![不应请求](http://127.0.0.1:9/private-resource)\n\n';
        const raw = Buffer.from((index % 2 ? '\ufeff' : '') + text.replace(/\n/g, index % 2 ? '\r\n' : '\n'), 'utf8');
        const filename = path.join(output, `manuscript-${index}.md`);
        await fs.writeFile(filename, raw);
        await page.goto(task.url);
        for (const viewport of [{width: 1198, height: 715}, {width: 390, height: 844}]) {
          await page.setViewportSize(viewport);
          assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
          if (index === 0) await page.screenshot({path: path.join(output, `upload-${viewport.width}.png`), fullPage: true});
        }
        await page.locator('#markdown-file').setInputFiles(filename);
        await page.getByRole('button', {name: '上传至私有暂存', exact: true}).click();
        await page.getByRole('status').filter({hasText: '文件接收完成'}).waitFor({timeout: 60000});
        assert.equal(await page.evaluate(() => window.uploadXss), undefined);
        const expected = {file_sha256: createHash('sha256').update(raw).digest('hex'),
          content_sha256: createHash('sha256').update(Buffer.from(text)).digest('hex'), bytes: raw.length};
        await fs.writeFile(path.join(output, `uploaded-${index}.json`), JSON.stringify(expected));
        report.uploads.push({index, bytes: raw.length, codepoints: Array.from(text).length, canonicalHash: expected.content_sha256});
      }
    }
    await waitJson(path.join(output, 'ready-to-revoke.json'));
    await page.goto(base + '/accounts/security/agents/');
    const live = page.locator('article.agent-token-item').filter({ has: page.getByRole('button', { name: '撤销连接', exact: true }) });
    await live.first().waitFor();
    await page.screenshot({ path: path.join(output, 'connected-390.png'), fullPage: true });
    await live.first().getByRole('button', { name: '撤销连接', exact: true }).click();
    await fs.writeFile(path.join(output, 'revoked.json'), '{}');
    assert.equal(await finished, 0, clientLog);
    assert.deepEqual(report.errors, []);
    report.result = 'OAuth browser approval, official SDK writing workflow, refresh and browser revocation passed';
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(clientLog.trim());
    console.log('Browser acceptance report: ' + output);
  } finally {
    await fs.writeFile(path.join(output, 'client.log'), clientLog);
    await fs.writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    child.kill();
    await browser.close();
    callbackServer.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
