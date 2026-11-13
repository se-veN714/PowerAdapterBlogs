/* Version navigation never rewrites a branch head; draft storage is explicit and tab-local. */
(() => {
  window.padifBindVersionEditor = (editor, form) => {
    const bar = document.querySelector('[data-editor-version-bar]');
    if (!bar) return;
    const branch = bar.querySelector('[data-editor-branch]');
    const version = bar.querySelector('[data-editor-version]');
    const state = bar.querySelector('[data-editor-dirty-state]');
    const dialog = document.querySelector('[data-editor-leave-dialog]');
    const error = dialog.querySelector('[data-editor-storage-error]');
    const notice = document.querySelector('[data-editor-draft-notice]');
    const message = form.querySelector('[name=commit_message]');
    const kind = form.querySelector('[name=version_kind]');
    const baseline = {content: editor.getMarkdown(), message: message ? message.value : '', kind: kind ? kind.value : ''};
    let serverDirty = form.dataset.boundDraft === 'true';
    let leaving = false;
    let submitting = false;
    let pending = null;
    let priorFocus = null;
    const key = ['padif.editor.draft', form.dataset.user, form.dataset.document, form.dataset.branch, form.dataset.version].join(':');
    const navigationKey = 'padif.editor.navigation';
    function dirty() {
      return serverDirty || (form.dataset.editable === 'true' && (editor.getMarkdown() !== baseline.content ||
        (message && message.value !== baseline.message) || (kind && kind.value !== baseline.kind)));
    }
    function refreshState() { state.textContent = dirty() ? '未保存修改' : '未修改'; }
    function stashNavigation(url) {
      try { sessionStorage.setItem(navigationKey, JSON.stringify({target: url.pathname + url.search,
        open: form.closest('details').open, y: window.scrollY, top: bar.getBoundingClientRect().top})); } catch (_) { /* Preference only. */ }
    }
    function go(url) { stashNavigation(url); leaving = true; window.location.assign(url.href); }
    function request(action) {
      if (!dirty()) { action(); return; }
      pending = action;
      priorFocus = document.activeElement;
      error.hidden = true;
      dialog.showModal();
      dialog.querySelector('[data-editor-leave=cancel]').focus();
    }
    function close() {
      dialog.close(); pending = null;
      if (priorFocus && priorFocus.isConnected) priorFocus.focus({preventScroll: true});
    }
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    dialog.addEventListener('click', event => {
      const button = event.target.closest('[data-editor-leave]');
      if (!button) return;
      const choice = button.dataset.editorLeave;
      if (choice === 'cancel') { close(); return; }
      try {
        if (choice === 'keep') {
          sessionStorage.setItem(key, JSON.stringify({content: editor.getMarkdown(), message: message ? message.value : (saved ? saved.message : ''),
            kind: kind ? kind.value : (saved ? saved.kind : ''), created: Date.now()}));
        } else sessionStorage.removeItem(key);
      } catch (_) {
        if (choice === 'keep') { error.hidden = false; return; }
      }
      const action = pending;
      dialog.close(); pending = null; leaving = true;
      if (action) action();
    });
    document.addEventListener('click', event => {
      const link = event.target.closest('a[href]');
      if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || link.target === '_blank' || link.hasAttribute('download')) return;
      const url = new URL(link.href, location.href);
      if (!['http:', 'https:'].includes(url.protocol)) return;
      if (url.origin === location.origin && url.pathname === location.pathname && url.search === location.search) return;
      if (link.dataset.worldlineVersion === form.dataset.version) { event.preventDefault(); locate(); return; }
      if (dirty() || (url.origin === location.origin && url.pathname === location.pathname)) {
        event.preventDefault(); event.stopImmediatePropagation(); request(() => go(url));
      }
    }, true);
    function switchTo(select, makeURL) {
      const chosen = select.value;
      select.value = select === branch ? form.dataset.branch : form.dataset.version;
      request(() => go(makeURL(chosen)));
    }
    branch.addEventListener('change', () => switchTo(branch, chosen => {
      const url = new URL(location.href); url.searchParams.set('branch', chosen); url.searchParams.delete('version'); url.hash = ''; return url;
    }));
    version.addEventListener('change', () => switchTo(version, chosen => {
      const url = new URL(location.href); url.searchParams.set('branch', form.dataset.branch); url.searchParams.set('version', chosen); url.hash = ''; return url;
    }));
    function locate() {
      const handle = document.querySelector('[data-drawer-handle]');
      if (handle && !handle.hidden) handle.click();
      const node = document.getElementById('version-' + form.dataset.version) || document.getElementById('worldline-inspector');
      if (node) { node.scrollIntoView({block: 'center', inline: 'nearest'}); node.focus({preventScroll: true}); }
    }
    bar.querySelector('[data-editor-locate]').addEventListener('click', locate);
    document.addEventListener('submit', event => {
      if (event.target === form) { submitting = true; return; }
      if (event.target.matches('.diff-controls[hx-get][hx-target="#diff-result"]')) return;
      if (leaving || !dirty()) return;
      event.preventDefault(); event.stopImmediatePropagation();
      const target = event.target;
      const submitter = event.submitter;
      request(() => { leaving = true; target.requestSubmit(submitter); });
    }, true);
    window.addEventListener('beforeunload', event => {
      if (dirty() && !leaving && !submitting) { event.preventDefault(); event.returnValue = ''; }
    });
    editor.on('change', refreshState);
    form.addEventListener('input', refreshState);
    form.addEventListener('change', refreshState);
    let saved = null;
    try {
      saved = JSON.parse(sessionStorage.getItem(key) || 'null');
      if (saved && (!Number.isFinite(saved.created) || Date.now() - saved.created > 86400000)) { sessionStorage.removeItem(key); saved = null; }
    } catch (_) { /* No draft available. */ }
    if (saved) {
      notice.hidden = false;
      if (form.dataset.editable !== 'true') notice.querySelector('[data-editor-draft-restore]').textContent = '查看保留草稿';
      notice.querySelector('[data-editor-draft-restore]').addEventListener('click', () => {
        editor.setMarkdown(saved.content);
        if (message) message.value = saved.message || '';
        if (kind && ['patch', 'minor', 'major'].includes(saved.kind)) kind.value = saved.kind;
        if (form.dataset.editable === 'true') notice.hidden = true;
        else {
          serverDirty = true;
          const description = notice.querySelector('[data-editor-draft-description]');
          if (description) description.textContent = '已载入草稿供预览与复制，原版本未改写。修改说明：' + (saved.message || '无');
        }
        refreshState();
      });
      notice.querySelector('[data-editor-draft-delete]').addEventListener('click', () => {
        try { sessionStorage.removeItem(key); } catch (_) { /* Removal unavailable. */ }
        if (form.dataset.editable !== 'true') { editor.setMarkdown(baseline.content); serverDirty = false; refreshState(); }
        notice.hidden = true;
      });
    }
    try {
      const previous = JSON.parse(sessionStorage.getItem(navigationKey) || 'null');
      sessionStorage.removeItem(navigationKey);
      if (previous && previous.target === location.pathname + location.search) {
        form.closest('details').open = previous.open;
        requestAnimationFrame(() => requestAnimationFrame(() => {
          const top = Number.isFinite(previous.top) ? window.scrollY + bar.getBoundingClientRect().top - previous.top : previous.y;
          window.scrollTo(0, Math.max(0, top)); version.focus({preventScroll: true});
        }));
      }
    } catch (_) { /* Navigation remains available without preference storage. */ }
    refreshState();
  };
})();
