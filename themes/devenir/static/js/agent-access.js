document.addEventListener('click', async event => {
    const button = event.target.closest('[data-copy-target]');
    if (!button) return;
    const element = document.getElementById(button.dataset.copyTarget);
    const status = document.querySelector('.agent-copy-status');
    try {
        await navigator.clipboard.writeText(element.value || element.textContent.trim());
        status.textContent = '已复制，请回到 Agent 客户端继续。';
    } catch {
        if (element.select) element.select();
        status.textContent = '无法自动复制，请选中文字手动复制。';
    }
});


(() => {
    const drawer = document.getElementById('agent-permission-drawer');
    if (!drawer) return;
    const form = drawer.querySelector('form');
    const checks = [...form.querySelectorAll('[name="operations"]')];
    const labels = {'padif:read': '阅读', 'padif:annotate': '批注', 'padif:version': '分支写作'};
    const submit = drawer.querySelector('[data-drawer-submit]');
    const error = drawer.querySelector('[data-drawer-error]');
    const summary = values => values.map(key => labels[key]).join(' / ') || '无';
    let trigger, current = [], pending = false, qualified = false, writable = false, busy = false;
    const selected = () => checks.filter(input => input.checked).map(input => input.value);
    function update() {
        const target = selected();
        const removed = current.filter(key => !target.includes(key));
        const added = target.filter(key => !current.includes(key));
        const read = target.includes('padif:read');
        checks.forEach(input => {
            input.disabled = busy || (input.value !== 'padif:read' && (!writable || !read));
        });
        const increasing = added.length > 0;
        submit.disabled = busy || (!removed.length && !added.length) || (increasing && (!qualified || pending));
        submit.textContent = added.length && removed.length ? '减少并申请新增权限' : added.length ? '提交提权申请' : '立即减少权限';
        drawer.querySelector('[data-drawer-effect]').textContent = [
            removed.length ? '提交后立即移除：' + summary(removed) + '。' : '',
            added.length ? '待创建者批准：' + summary(added) + '；现有保留项继续有效。' : '',
            increasing && pending ? '已有待审申请，请先撤回再申请新增操作。' : '',
            increasing && !qualified ? '板块资格当前不可用，仍可减少自己的权限。' : ''
        ].filter(Boolean).join(' ');
    }
    document.addEventListener('click', event => {
        const button = event.target.closest('[data-permission-drawer]');
        if (!button) return;
        trigger = button;
        current = button.dataset.allowed.split(',').filter(Boolean);
        pending = Boolean(button.dataset.pending);
        qualified = button.dataset.qualified === 'true';
        writable = ['owner', 'collaborator'].includes(button.dataset.role);
        form.action = button.dataset.action;
        form.elements.revision.value = button.dataset.revision;
        form.elements.note.value = '';
        checks.forEach(input => { input.checked = current.includes(input.value); });
        drawer.querySelector('[data-drawer-document]').textContent = button.dataset.title;
        drawer.querySelector('[data-drawer-role]').textContent = '本人角色：' + button.dataset.roleLabel;
        drawer.querySelector('[data-drawer-current]').textContent = '当前已授予：' + summary(current);
        drawer.querySelector('[data-drawer-pending]').textContent = pending ? '待审目标：' + button.dataset.pendingLabel : '暂无待审申请。';
        drawer.querySelector('[data-drawer-restriction]').textContent = writable ? '关闭阅读将放弃本文全部 AI+；新增操作需审批。' : '批注和分支写作需文章协作者角色；此处不能提升人类角色。';
        error.textContent = '';
        busy = false;
        update();
        drawer.showModal();
        checks[0].focus();
    });
    checks.forEach(input => input.addEventListener('change', () => {
        if (input.value === 'padif:read' && !input.checked) checks.forEach(check => { check.checked = false; });
        update();
    }));
    drawer.querySelectorAll('[data-drawer-close]').forEach(button => button.addEventListener('click', () => { if (!busy) drawer.close(); }));
    drawer.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
    drawer.addEventListener('keydown', event => {
        if (event.key !== 'Tab') return;
        const focusable = [...drawer.querySelectorAll('button:not(:disabled), input:not(:disabled):not([type=hidden]), textarea:not(:disabled), a[href]')].filter(element => element.getClientRects().length);
        if (!focusable.length) { event.preventDefault(); return; }
        const index = focusable.indexOf(document.activeElement);
        const next = (index + (event.shiftKey ? -1 : 1) + focusable.length) % focusable.length;
        event.preventDefault();
        focusable[next].focus();
    });
    drawer.addEventListener('close', () => {
        if (trigger) (document.querySelector(`[data-article-id="${trigger.dataset.documentId}"] [data-permission-drawer]`) || document.getElementById('agent-permission-feedback')).focus();
    });
    form.addEventListener('submit', async event => {
        event.preventDefault();
        if (busy || submit.disabled || !form.reportValidity()) return;
        // Capture enabled inputs before disabling the controls for the request.
        const data = new FormData(form);
        busy = true;
        error.textContent = '';
        update();
        try {
            const response = await fetch(form.action, {method: 'POST', body: data, headers: {'Accept': 'application/json'}, credentials: 'same-origin'});
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || '提交失败，请刷新后重试。');
            const row = document.querySelector(`[data-article-id="${trigger.dataset.documentId}"]`);
            row.outerHTML = payload.row_html;
            document.querySelector('[data-granted-count]').textContent = payload.granted_count;
            document.querySelector('[data-pending-count]').textContent = payload.pending_count;
            document.getElementById('agent-permission-feedback').textContent = payload.message;
            drawer.close();
        } catch (failure) {
            error.textContent = failure instanceof SyntaxError ? '会话已变化或服务器异常，请重新登录后重试。' : failure.message;
        } finally {
            busy = false;
            update();
        }
    });
})();
