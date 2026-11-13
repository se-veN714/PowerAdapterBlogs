/* Private cloud working text. Saving never advances a version or branch. */
(() => {
  window.padifBindCloudDraft = (editor, form) => {
    const panel = document.querySelector('[data-cloud-draft]');
    if (!panel) return;
    const status = panel.querySelector('[data-cloud-draft-status]');
    const restore = panel.querySelector('[data-cloud-draft-restore]');
    const remove = panel.querySelector('[data-cloud-draft-delete]');
    const saveButton = form.querySelector('[data-cloud-draft-save]');
    const other = panel.querySelector('[data-cloud-draft-other]');
    const message = form.querySelector('[name=commit_message]');
    const kind = form.querySelector('[name=version_kind]');
    const token = form.querySelector('[name=draft_revision]');
    const editable = form.dataset.editable === 'true';
    let revision = '', saved = null, lastSaved = '', ready = false, paused = false, busy = false;
    let timer, loading = null, suppress = false, deleted = false;
    const snapshot = () => ({content: editor.getMarkdown(), commit_message: message ? message.value : '',
      version_kind: kind ? kind.value : 'patch'});
    const fingerprint = value => JSON.stringify(value);
    const initial = fingerprint(snapshot());
    const controls = () => {
      restore.hidden = !saved || (!paused && editable);
      remove.hidden = !saved || !editable;
      if (saveButton) saveButton.disabled = busy || paused;
    };
    const show = text => { status.textContent = text; controls(); form.dispatchEvent(new Event('padif:cloud-draft-state')); };
    async function load() {
      ready = false; show('正在检查云端草稿…');
      try {
        const response = await fetch(panel.dataset.url, {headers: {Accept: 'application/json'}, cache: 'no-store'});
        if (!response.ok) throw new Error();
        const data = await response.json();
        saved = data.draft;
        revision = saved ? saved.revision : '';
        token.value = revision;
        paused = Boolean(saved);
        ready = true;
        other.replaceChildren();
        for (const draft of data.other_drafts) {
          const link = document.createElement('a');
          const url = new URL(location.href);
          url.searchParams.set('branch', form.dataset.branch);
          url.searchParams.set('version', draft.base_version_id);
          link.href = url.pathname + url.search;
          link.textContent = `基础版本 #${draft.base_version_id} 的草稿`;
          other.append(link);
        }
        show(saved ? `发现云端草稿 · ${new Date(saved.updated_at).toLocaleString()} · 请先恢复或删除`
          : '云端草稿 · 修改后自动保存，不生成版本');
        if (!saved && fingerprint(snapshot()) !== initial) schedule();
      } catch (_) { show('无法读取云端草稿；请检查网络后重试，当前内容仍在编辑器中。'); }
    }
    async function save() {
      clearTimeout(timer);
      if (!ready) { await ensureLoaded(); if (!ready || paused) return false; }
      if (!editable || paused || busy) return false;
      const value = snapshot();
      busy = true; show('正在保存云端草稿…');
      try {
        const response = await fetch(panel.dataset.url, {method: 'POST', headers: {
          'Content-Type': 'application/json', 'X-CSRFToken': form.querySelector('[name=csrfmiddlewaretoken]').value
        }, body: JSON.stringify({action: 'save', revision, ...value})});
        if (response.status === 409) {
          paused = true;
          show('其他标签页已更改云端草稿；当前内容已保留，请复制或导出后刷新比较。');
          return false;
        }
        if (!response.ok) throw new Error();
        saved = (await response.json()).draft;
        revision = saved.revision; token.value = revision; lastSaved = fingerprint(value);
        show(`云端草稿已保存 · ${new Date(saved.updated_at).toLocaleString()} · 尚未提交版本`);
        if (fingerprint(snapshot()) !== lastSaved) schedule();
        return true;
      } catch (_) {
        show('云端保存失败；当前内容仍在编辑器中，请重试或复制备份。');
        return false;
      } finally { busy = false; controls(); }
    }
    function schedule() {
      clearTimeout(timer);
      if (suppress || !editable || !ready || paused) return;
      deleted = false;
      status.textContent = '修改尚未保存到云端…';
      timer = setTimeout(save, 1500);
    }
    restore.addEventListener('click', () => {
      if (!saved) return;
      suppress = true;
      editor.setMarkdown(saved.content);
      if (message) message.value = saved.commit_message;
      if (kind) kind.value = saved.version_kind;
      lastSaved = fingerprint(snapshot()); paused = false; suppress = false;
      restore.hidden = true;
      show(editable ? '已恢复云端草稿 · 继续编辑会自动保存，尚未提交版本'
        : '历史基础草稿 · 仅供预览与复制，不覆盖分支最新版本');
      restore.hidden = true;
      form.dispatchEvent(new Event('input', {bubbles: true}));
      clearTimeout(timer);
    });
    remove.addEventListener('click', async () => {
      if (busy || !saved) return;
      clearTimeout(timer); busy = true; controls();
      try {
        const response = await fetch(panel.dataset.url, {method: 'POST', headers: {
          'Content-Type': 'application/json', 'X-CSRFToken': form.querySelector('[name=csrfmiddlewaretoken]').value
        }, body: JSON.stringify({action: 'delete', revision})});
        if (!response.ok) throw new Error();
        saved = null; revision = ''; token.value = ''; lastSaved = ''; paused = false; deleted = true;
        show('云端草稿已删除；当前编辑内容保留，继续编辑后会重新保存。');
      } catch (_) { paused = true; show('删除失败或草稿已变化，请保留当前内容后刷新核对。'); }
      finally { busy = false; controls(); }
    });
    if (saveButton) saveButton.addEventListener('click', save);
    editor.on('change', schedule);
    form.addEventListener('input', schedule);
    form.addEventListener('change', schedule);
    document.addEventListener('visibilitychange', () => {
      if (document.hidden && !deleted && fingerprint(snapshot()) !== lastSaved && fingerprint(snapshot()) !== initial) save();
    });
    const controller = {isSaved: () => ready && !paused && fingerprint(snapshot()) === lastSaved,
      available: () => ready, save};
    function ensureLoaded() {
      if (!loading) loading = load().finally(() => { loading = null; });
      return loading;
    }
    ensureLoaded();
    return controller;
  };
})();
