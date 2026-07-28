// 获取表单和提交按钮
const commentForm = document.getElementById('comment-form');
const submitButton = document.getElementById('submit-button');
const buttonText = document.getElementById('button-text');

// 监听表单提交事件。匿名页面不渲染表单，必须允许脚本安全退出。
commentForm?.addEventListener('submit', async function (event) {
    // 1. 阻止表单默认的提交行为
    event.preventDefault();

    // 2. 准备AJAX提交
    const formData = new FormData(commentForm);

    // 3. 禁用提交按钮并显示加载状态
    submitButton.classList.add('is-loading');
    submitButton.disabled = true;
    buttonText.textContent = '提交中...';

    try {
        // 4. 发送AJAX请求
        const response = await fetch(commentForm.action, {
            method: 'POST',
            body: formData,
            headers: {
                // 可选：通知Django这是AJAX请求
                'X-Requested-With': 'XMLHttpRequest'
            }
        });

        // 5. 解析服务器响应
        const data = await response.json();

        // 6. 根据响应结果进行不同处理
        if (data.success) {
            //清空表单
            this.reset()
            // 成功时的Toast提示
            Toastify({
                text: data.message,
                duration: 3000,
                close: true,
                gravity: "top",
                position: "right",
                backgroundColor: "linear-gradient(to right, #00d1b2, #3273dc)",
                className: "toast-success",
            }).showToast();

            //将新评论置顶
            const commentsContainer = document.getElementById('comments-container');
            commentsContainer.insertAdjacentHTML('afterbegin', data.html);

            // 可选：刷新评论列表或显示新评论
            // refreshComments();
        } else {
            // 失败时的Toast提示
            Toastify({
                text: "⚠️ " + data.message,
                duration: 5000,
                close: true,
                gravity: "top",
                position: "right",
                backgroundColor: "linear-gradient(to right, #ff3860, #ffdd57)",
                className: "toast-error",
            }).showToast();

            // 7. 处理表单错误
            if (data.errors) {
                // 隐藏所有错误信息
                document.querySelectorAll('.help.is-danger').forEach(el => {
                    el.style.display = 'none';
                });
                document.querySelectorAll('.is-danger').forEach(el => el.classList.remove('is-danger'));

                // 显示新错误
                for (const field in data.errors) {
                    const errors = data.errors[field];
                    // 找出错误消息的容器（相邻的.help元素）
                    const inputEl = document.querySelector(`[name="${field}"]`);
                    if (inputEl) {
                        inputEl.classList.add('is-danger');
                        const errorContainer = inputEl.closest('.field').querySelector('.help');
                        if (errorContainer) {
                            errorContainer.textContent = errors.join(', ');
                            errorContainer.style.display = 'block';
                        }
                    }
                }
            }
        }
    } catch (error) {
        console.error("AJAX 请求失败：", error);
        // 8. 捕获网络错误

        Toastify({
            text: "❌ 网络错误，请检查连接并重试",
            duration: 5000,
            close: true,
            gravity: "top",
            position: "right",
            backgroundColor: "linear-gradient(to right, #ff3860, #ff7b29)",
            className: "toast-error",
        }).showToast();
    } finally {
        // 9. 恢复提交按钮状态
        submitButton.classList.remove('is-loading');
        submitButton.disabled = false;
        buttonText.textContent = '写好了！';
    }
});

document.getElementById('comments-container')?.addEventListener('click', async function (event) {
    const button = event.target.closest('.comment-delete');
    if (!button) return;
    button.disabled = true;
    try {
        const csrfToken = document.querySelector('#comment-form [name="csrfmiddlewaretoken"]')?.value;
        const response = await fetch(button.dataset.deleteUrl, {
            method: 'POST',
            headers: {'X-CSRFToken': csrfToken, 'X-Requested-With': 'XMLHttpRequest'}
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.message || '删除失败');
        button.closest('.comment-item')?.remove();
    } catch (error) {
        button.disabled = false;
        Toastify({text: `⚠️ ${error.message}`, duration: 4000, gravity: 'top', position: 'right'}).showToast();
    }
});
