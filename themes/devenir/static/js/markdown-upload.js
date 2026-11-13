(() => {
  const form = document.getElementById('markdown-file-form');
  if (!form) return;
  const status = document.getElementById('markdown-file-state');
  const button = form.querySelector('button');
  const hash = async bytes => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), value => value.toString(16).padStart(2, '0')).join('');
  async function send(data) {
    const response = await fetch(location.pathname, {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': form.querySelector('[name=csrfmiddlewaretoken]').value}, body: JSON.stringify(data)});
    const result = await response.json();
    if (!response.ok || result.error) throw new Error(result.error || 'UPLOAD_FAILED');
    return result;
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    button.disabled = true;
    try {
      const file = document.getElementById('markdown-file').files[0];
      if (!file || !file.size || file.size > 2097152 || !/\.(md|markdown)$/i.test(file.name)) throw new Error('请选择不超过 2 MiB 的 Markdown 文件。');
      const bytes = new Uint8Array(await file.arrayBuffer());
      await send({action: 'manifest', file_name: file.name, file_size: bytes.length, file_sha256: await hash(bytes)});
      for (let start = 0, index = 0; start < bytes.length; start += 16384, index++) {
        const block = bytes.slice(start, start + 16384);
        const data = btoa(Array.from(block, value => String.fromCharCode(value)).join(''));
        await send({action: 'chunk', chunk_index: index, chunk_sha256: await hash(block), data_base64: data,
          request_id: `web-${form.dataset.uploadId}-${index}`});
        status.textContent = `已接收 ${Math.min(start + block.length, bytes.length)} / ${bytes.length} 字节`;
      }
      status.textContent = '文件接收完成。请回到 Agent 校验文件后提交；尚未创建版本。';
    } catch (error) {
      status.textContent = `上传未完成：${error.message}。请核对任务状态；不要绕过正常授权。`;
    } finally { button.disabled = false; }
  });
})();
