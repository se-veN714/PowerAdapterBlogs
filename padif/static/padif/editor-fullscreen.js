/* Enlarge the existing editor; never reinitialize or copy its working text. */
(() => {
  window.padifBindFullscreenEditor = (editor, form) => {
    const button = form.querySelector('[data-editor-fullscreen]');
    if (!button) return;
    let active = false, previousScroll = 0;
    function toggle() {
      active = !active;
      if (active) previousScroll = window.scrollY;
      form.classList.toggle('is-editor-fullscreen', active);
      document.body.classList.toggle('padif-editor-fullscreen-open', active);
      button.textContent = active ? '退出全屏编辑' : '全屏编辑';
      button.setAttribute('aria-pressed', String(active));
      if (active) {
        form.setAttribute('role', 'dialog');
        form.setAttribute('aria-modal', 'true');
        form.setAttribute('aria-label', '全屏编辑');
      } else {
        form.removeAttribute('role'); form.removeAttribute('aria-modal'); form.removeAttribute('aria-label');
      }
      editor.setHeight(active ? '100%' : '560px');
      if (!active) window.scrollTo(0, previousScroll);
      button.focus({preventScroll: true});
    }
    button.addEventListener('click', toggle);
    document.addEventListener('keydown', event => {
      if (!active || !document.getElementById('padif-preview-modal').hidden) return;
      if (event.key === 'Escape') { event.preventDefault(); toggle(); return; }
      if (event.key !== 'Tab') return;
      const items = [...form.querySelectorAll('button,input,select,textarea,a[href],[tabindex],[contenteditable=true]')]
        .filter(item => !item.disabled && item.tabIndex >= 0 && item.getClientRects().length && !item.closest('[inert]'));
      const first = items[0], last = items[items.length - 1];
      if (!first) return;
      if (event.shiftKey && (document.activeElement === first || !form.contains(document.activeElement))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !form.contains(document.activeElement))) {
        event.preventDefault(); first.focus();
      }
    });
  };
})();
