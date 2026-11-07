const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
(async () => {
    const base = 'http://127.0.0.1:8773';
    const fixture = JSON.parse(await fs.readFile('.local/mfa-trust-browser-fixture.json', 'utf8'));
    assert.ok(process.env.MFA_TRUST_QA_PASSWORD);
    const output = await fs.mkdtemp(path.resolve('.local/browser-qa/mfa-trust-'));
    const report = {checks: [], viewports: [], errors: [], baselineErrors: []};
    const browser = await chromium.launch({headless: true});
    function observe(page) {
        page.on('pageerror', error => {
            const text = error.stack || error.message;
            if (text.includes('mathjax@3/es5/startup.js') && text.includes('Cannot set property Package')) report.baselineErrors.push(text);
            else report.errors.push(text);
        });
    }
    async function passwordLogin(page) {
        await page.goto(base + '/accounts/login/?next=/dashboard/');
        await page.locator('[name=username]').fill(fixture.username);
        await page.locator('[name=password]').fill(process.env.MFA_TRUST_QA_PASSWORD);
        await Promise.all([page.waitForURL(url => !url.pathname.includes('/login/')), page.locator('button[type=submit]').first().click()]);
    }
    try {
        let context = await browser.newContext({viewport: {width:1198,height:715}});
        let page = await context.newPage(); observe(page);
        await passwordLogin(page);
        assert.ok(page.url().includes('/mfa/challenge/'));
        await page.locator('[name=remember_dashboard]').check();
        const otp = execFileSync('.venv/Scripts/python.exe', ['-c', "import pyotp,json; print(pyotp.TOTP(json.load(open('.local/mfa-trust-browser-fixture.json'))['secret']).now())"], {encoding:'utf8'}).trim();
        await page.locator('[name=code]').fill(otp);
        await Promise.all([page.waitForURL(url => url.pathname === '/dashboard/'), page.getByRole('button',{name:'验证并进入',exact:true}).click()]);
        const cookies = await context.cookies();
        const trust = cookies.find(cookie => cookie.name === 'pa_dashboard_trust');
        assert.ok(trust && trust.expires > Date.now()/1000 && trust.httpOnly);
        assert.equal(trust.sameSite,'Lax');
        const initialExpiry = trust.expires;
        report.checks.push('Real local password + TOTP + checked remember issues persistent HttpOnly Lax browser cookie');
        // Model browser closure without retaining the login session.
        const persistent = cookies.filter(cookie => cookie.name !== 'sessionid' && cookie.expires > 0);
        await context.close();
        context = await browser.newContext({viewport:{width:1198,height:715}});
        await context.addCookies(persistent);
        page = await context.newPage(); observe(page);
        await passwordLogin(page);
        assert.equal(new URL(page.url()).pathname,'/dashboard/');
        assert.equal((await context.cookies()).find(cookie => cookie.name==='pa_dashboard_trust').expires,initialExpiry);
        assert.equal(await page.locator('[data-mfa-trust-countdown]').count(),1);
        report.checks.push('New browser context, discarded login cookie: correct password enters dashboard without TOTP, expiry unchanged');
        await page.clock.install();
        await page.goto(base+'/accounts/security/mfa/');
        const timer=page.locator('[data-mfa-trust-countdown]');
        const before=await timer.textContent();
        await page.clock.fastForward(3000);
        const after=await timer.textContent();
        assert.notEqual(before,after);
        for(const viewport of [{width:1915,height:930},{width:1198,height:715},{width:390,height:844}]) {
            await page.setViewportSize(viewport);
            const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth);
            assert.ok(overflow<=1);
            await page.screenshot({path:path.join(output,`settings-${viewport.width}.png`),fullPage:true});
            report.viewports.push({...viewport,overflow});
        }
        await page.clock.fastForward(7*86400*1000);
        assert.match(await timer.textContent(),/信任已到期/);
        report.checks.push('Countdown decreases and reaches expiry text under accelerated UI clock; server expiry tested independently');
        await page.clock.resume();
        await page.goto(base+'/super_admin/');
        assert.ok(page.url().includes('/mfa/challenge/'));
        assert.equal(await page.locator('[name=remember_dashboard]').count(),0);
        report.checks.push('Remembered browser does not create a fresh super-admin session or offer trust on that challenge');
        assert.deepEqual(report.errors,[]);
    } finally {
        await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));
        await browser.close();
        console.log(output);
    }
})().catch(error=>{console.error(error);process.exitCode=1;});
