// 安全地创建编辑器实例
const editors = new WeakMap();

// 获取CSRF令牌的标准方法
function getCSRFToken() {
    // 方法1: 从cookie获取（推荐）
    const cookieValue = document.cookie.match(
        '(^|;)\\s*csrftoken\\s*=\\s*([^;]+)'
    );
    if (cookieValue) return cookieValue.pop();

    // 方法2: 从meta标签获取（Django模板常用）
    return document.querySelector('meta[name="csrf-token"]')?.content || '';
}

// 初始化编辑器
document.addEventListener('DOMContentLoaded', function () {
    const editorElement = document.querySelector('#tui-editor');
    if (!editorElement) return;

    const editor = new toastui.Editor({
        el: editorElement,
        height: '600px',
        initialEditType: 'markdown',
        previewStyle: 'vertical',
        theme: 'dark',
        initialValue: document.getElementById('id_content')?.value || '',
    });

    // 保存编辑器引用（避免全局变量冲突）
    editors.set(editorElement, editor);

    // 移除默认图片处理
    editor.eventManager.removeEventHandler('addImageBlobHook');

    // 配置自定义上传逻辑
    editor.eventManager.listen('addImageBlobHook', (blob, callback) => {
        // 1. 创建上传UI反馈
        const progressMessage = '![上传中...]()';
        const placeholderCallback = callback(progressMessage);

        // 2. 准备表单数据
        const formData = new FormData();
        formData.append('image', blob);
        formData.append('csrfmiddlewaretoken', getCSRFToken());

        // 3. 发送请求
        fetch('/upload_image/', {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest',  // 标识AJAX请求
            }
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`上传失败: ${response.status} ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.url) {
                    // 替换占位符为真实URL
                    placeholderCallback(
                        data.url,
                        '图片描述',  // 允许用户编辑
                        `![${blob.name || '图片'}](${data.url})`
                    );

                    // 成功提示
                    editor.addHook('addImageBlobHook', () => {
                    });
                    editor.insertText(' ![上传成功] ');
                    editor.eventManager.removeEventHandler('addImageBlobHook');
                } else {
                    throw new Error('服务器未返回图片URL');
                }
            })
            .catch(error => {
                console.error('上传出错:', error);

                // 错误提示
                placeholderCallback(null);
                editor.insertText(` [图片上传失败: ${error.message}] `);

                // 可选：显示错误通知
                toastui.Editor.setMarkdownAfter(editor, '⚠️ 图片上传失败');
            });

        return false;  // 阻止默认行为
    });
});

// 表单提交处理（优化版）
function submitPostForm() {
    const editorElement = document.querySelector('#tui-editor');
    const editor = editors.get(editorElement);
    const contentField = document.getElementById('id_content');

    if (editor && contentField) {
        contentField.value = editor.getMarkdown();
    }

    // 添加提交前检查
    const images = contentField.value.match(/!\[[^\]]*\]\([^)]+\)/g) || [];
    if (images.some(img => img.includes('上传中'))) {
        const confirmation = confirm('有图片正在上传中，继续提交可能导致图片缺失。确定要提交吗？');
        if (!confirmation) return false;
    }
}
