const $ = (id) => document.getElementById(id);
let lastLogs = [];

function setState(id, text, tone) {
  const element = $(id);
  element.textContent = text;
  element.className = `state ${tone || 'unknown'}`;
}

function render(payload) {
  const status = payload.status || payload;
  const tunnel = status.tunnel?.listening;
  const proxies = (status.proxy_ports || []).filter((item) => item.listening).map((item) => item.port);
  setState('state', status.state === 'ready' ? '就绪' : status.state === 'degraded' ? '部分就绪' : status.state === 'stopped' ? '已停止' : '未知', status.state);
  $('detail').textContent = status.detail || '—';
  const contractOk = status.wstunnel_contract === 'ok';
  setState('tunnel', contractOk ? 'ACTIVE' : status.wstunnel_contract === 'mismatch' ? '契约异常' : (tunnel ? '未核验' : 'DOWN'), contractOk ? 'ready' : 'stopped');
  setState('proxy', proxies.length ? proxies.join(' / ') : 'DOWN', proxies.length ? 'ready' : 'stopped');
  $('processes').innerHTML = (status.processes || []).length ? status.processes.map((p) => `${p.name} <small>PID ${p.pid}</small>`).join('<br>') : '无目标进程';
  if (payload.logs) { lastLogs = payload.logs; $('logs').textContent = lastLogs.join('\n') || '暂无日志'; }
  $('refresh').dataset.checked = status.checked_at || '';
}

async function refresh() {
  const [status, logs] = await Promise.all([fetch('/api/status').then((r) => r.json()), fetch('/api/logs?lines=200').then((r) => r.json())]);
  render({ status, logs: logs.lines });
}

async function action(name) {
  const buttons = [...document.querySelectorAll('button')]; buttons.forEach((button) => { button.disabled = true; });
  try {
    const response = await fetch(`/api/actions/${name}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ restart_clash: $('restart-clash').checked }) });
    const body = await response.json();
    $('action-message').textContent = body.message || body.detail || '操作完成';
  } catch (error) { $('action-message').textContent = `操作失败：${error}`; }
  finally { buttons.forEach((button) => { button.disabled = false; }); await refresh(); }
}

async function generate() {
  $('generate').disabled = true; $('profile-result').textContent = '正在校验端口契约并生成…';
  try {
    const response = await fetch('/api/profile', { method: 'POST' }); const body = await response.json();
    if (!response.ok) throw new Error(body.detail || '生成失败');
    $('profile-result').innerHTML = `已生成 <code>${body.filename}</code><br>${Object.values(body.contract).join(' · ')}<br><a href="${body.download_url}">下载 YAML</a>`;
  } catch (error) { $('profile-result').textContent = `生成失败：${error.message}`; }
  finally { $('generate').disabled = false; }
}

$('refresh').addEventListener('click', refresh); $('start').addEventListener('click', () => action('start')); $('restart').addEventListener('click', () => action('restart')); $('stop').addEventListener('click', () => action('stop')); $('generate').addEventListener('click', generate); $('clear-log').addEventListener('click', () => { lastLogs = []; $('logs').textContent = '已清空显示（磁盘日志未删除）'; });
refresh().catch((error) => { $('detail').textContent = `API 未连接：${error}`; });
setInterval(() => refresh().catch(() => {}), 3000);
const stream = new EventSource('/api/stream'); stream.addEventListener('state', (event) => { try { render(JSON.parse(event.data)); } catch (_) {} });
