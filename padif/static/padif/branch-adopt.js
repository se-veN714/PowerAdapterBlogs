(() => {
  const dialog = document.querySelector('[data-adopt-dialog]');
  if (!dialog?.showModal) return;
  const content = dialog.querySelector('[data-adopt-content]');
  const status = dialog.querySelector('[data-adopt-status]');
  const close = dialog.querySelector('[data-adopt-close]');
  let trigger = null;
  let busy = false;

  async function load(url, body = null) {
    if (busy) return;
    busy = true;
    close.disabled = Boolean(body);
    content.inert = true;
    status.hidden = false;
    status.textContent = body ? '正在保存版本…' : '正在读取版本…';
    try {
      const response = await fetch(url, {
        headers: {'X-PAdif-Adopt-Dialog': '1'},
        method: body ? 'POST' : 'GET',
        body,
        cache: 'no-store',
      });
      if (body && response.ok && response.headers.get('Content-Type')?.includes('application/json')) {
        const {url: destination} = await response.json();
        if (document.dispatchEvent(new CustomEvent('padif:adopt-complete', {cancelable: true, detail: destination}))) {
          window.location.assign(destination);
        }
        return;
      }
      if (response.headers.get('X-PAdif-Adopt-Dialog') !== '1') {
        if (response.status === 409) throw new Error('目标分支已归档或无法采用。');
        throw new Error('无法读取或提交版本，请检查登录状态与编辑权限后重试。');
      }
      content.innerHTML = await response.text();
      status.hidden = true;
      dialog.scrollTop = 0;
    } catch (error) {
      status.textContent = error instanceof TypeError ? '网络请求失败，请重试。' : error.message;
    } finally {
      busy = false;
      close.disabled = false;
      content.inert = false;
      if (dialog.open) {
        (content.querySelector('[data-adopt-review-again], #adopt-diff, select') || close).focus({preventScroll: true});
      }
    }
  }

  document.addEventListener('click', event => {
    const link = event.target.closest('[data-adopt-open]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (busy) return;
    trigger = link;
    content.replaceChildren();
    dialog.showModal();
    load(link.href);
  }, true);
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('cancel', event => { if (close.disabled) event.preventDefault(); });
  dialog.addEventListener('close', () => trigger?.focus({preventScroll: true}));
  dialog.addEventListener('click', event => {
    const link = event.target.closest('[data-adopt-review-again]');
    if (!link) return;
    event.preventDefault();
    load(new URL(link.dataset.adoptReviewAgain, trigger.href));
  });
  dialog.addEventListener('submit', event => {
    const form = event.target;
    event.preventDefault();
    const values = new FormData(form);
    if (form.matches('[data-adopt-compare]')) {
      const url = new URL(form.action);
      url.search = new URLSearchParams(values);
      load(url);
    } else if (form.matches('[data-adopt-confirm]')) {
      const submit = () => load(form.action, values);
      if (document.dispatchEvent(new CustomEvent('padif:adopt-confirm', {cancelable: true, detail: submit}))) submit();
    }
  });
})();
