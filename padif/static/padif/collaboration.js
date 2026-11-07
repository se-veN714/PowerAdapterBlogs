/* Owner-only account picker. Native select remains usable without JavaScript. */
(() => {
  const picker = document.querySelector('[data-account-picker]');
  if (!picker) return;
  const native = picker.querySelector('[data-account-native]');
  const input = document.createElement('input');
  input.id = 'collaboration-account-search';
  input.type = 'search';
  input.placeholder = '搜索账号名称或 ID';
  input.autocomplete = 'off';
  input.required = true;
  input.setAttribute('role', 'combobox');
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-expanded', 'false');
  input.setAttribute('aria-controls', 'collaboration-account-options');
  const list = document.createElement('div');
  list.id = 'collaboration-account-options';
  list.className = 'account-picker-options';
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', '账号搜索结果');
  list.hidden = true;
  const status = document.createElement('p');
  status.className = 'account-picker-status muted';
  status.setAttribute('aria-live', 'polite');
  picker.querySelector('label').htmlFor = input.id;
  native.hidden = true;
  native.required = false;
  native.before(input, list, status);
  let choices = [...native.options].filter(option => option.value).map(option => ({username: option.value, id: Number(option.dataset.id)}));
  let active = -1, timer, controller, requestId = 0;
  function cancelSearch() { clearTimeout(timer); controller?.abort(); requestId++; }
  function close() {
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    active = -1;
  }
  function select(account) {
    cancelSearch();
    if (![...native.options].some(option => option.value === account.username)) {
      native.add(new Option(account.username, account.username));
    }
    native.value = account.username;
    input.value = account.username;
    input.setCustomValidity('');
    status.textContent = `已选择 ${account.username} · ID ${account.id}`;
    close();
    input.focus();
  }
  function render() {
    list.replaceChildren();
    active = -1;
    input.removeAttribute('aria-activedescendant');
    choices.forEach((account, index) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.id = `collaboration-account-option-${index}`;
      row.tabIndex = -1;
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', 'false');
      const name = document.createElement('span'), id = document.createElement('span');
      name.textContent = account.username;
      id.textContent = `ID ${account.id}`;
      id.className = 'access-account-id';
      row.append(name, id);
      row.addEventListener('mousedown', event => event.preventDefault());
      row.addEventListener('click', () => select(account));
      list.append(row);
    });
    if (!choices.length) {
      const empty = document.createElement('p');
      empty.textContent = '没有符合条件的账号';
      list.append(empty);
    }
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  }
  async function search() {
    const id = ++requestId;
    controller?.abort();
    controller = new AbortController();
    const url = new URL(picker.dataset.url, location.origin);
    url.searchParams.set('accounts', '1');
    url.searchParams.set('q', input.value.trim());
    status.textContent = '正在搜索…';
    try {
      const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('Search unavailable');
      const data = await response.json();
      if (id !== requestId) return;
      choices = data.accounts;
      status.textContent = choices.length ? `找到 ${choices.length} 个账号，按方向键选择` : '没有符合条件的账号';
      if (document.activeElement === input) render();
    } catch (error) {
      if (error.name === 'AbortError' || id !== requestId) return;
      status.textContent = '搜索暂不可用，请使用下方账号列表或稍后重试。';
      close();
      native.hidden = false;
      native.required = true;
      input.required = false;
      input.setCustomValidity('');
    }
  }
  input.addEventListener('focus', () => { render(); });
  input.addEventListener('input', () => {
    native.value = '';
    input.setCustomValidity('请从搜索结果中选择账号。');
    controller?.abort();
    requestId++;
    clearTimeout(timer);
    close();
    timer = setTimeout(search, 180);
  });
  input.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); cancelSearch(); close(); return; }
    if (event.key === 'Enter' && active >= 0 && !list.hidden) {
      event.preventDefault(); select(choices[active]); return;
    }
    if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
    event.preventDefault();
    if (list.hidden) render();
    if (!choices.length) return;
    active = (active + (event.key === 'ArrowDown' ? 1 : -1) + choices.length) % choices.length;
    [...list.querySelectorAll('[role=option]')].forEach((row, index) => row.setAttribute('aria-selected', String(index === active)));
    const row = list.querySelectorAll('[role=option]')[active];
    input.setAttribute('aria-activedescendant', row.id);
    row.scrollIntoView({block: 'nearest'});
  });
  picker.addEventListener('focusout', () => setTimeout(() => { if (!picker.contains(document.activeElement)) close(); }, 0));
  document.addEventListener('click', event => { if (!picker.contains(event.target)) close(); });
  native.addEventListener('change', () => {
    input.value = native.value;
    input.setCustomValidity('');
  });
  picker.closest('form').addEventListener('submit', event => {
    if (!native.value) {
      event.preventDefault(); input.setCustomValidity('请从搜索结果中选择账号。'); input.reportValidity();
    }
  });
})();
