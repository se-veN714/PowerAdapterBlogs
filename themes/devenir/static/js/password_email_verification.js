document.addEventListener('DOMContentLoaded', function () {
    const timer = document.querySelector('[data-email-code-timer]');
    if (!timer) return;

    const button = timer.querySelector('[data-send-code]');
    const label = timer.querySelector('[data-send-label]');
    const resendCountdown = timer.querySelector('[data-resend-countdown]');
    const validity = timer.querySelector('[data-code-validity]');
    const codeCountdown = timer.querySelector('[data-code-countdown]');
    let resendRemaining = Number.parseInt(timer.dataset.resendSeconds || '0', 10);
    let codeRemaining = Number.parseInt(timer.dataset.codeSeconds || '0', 10);

    function formatClock(seconds) {
        const minutes = Math.floor(seconds / 60);
        const remainder = seconds % 60;
        return String(minutes).padStart(2, '0') + ':' + String(remainder).padStart(2, '0');
    }

    function render() {
        if (resendRemaining > 0) {
            button.disabled = true;
            label.textContent = '重新发送验证码';
            resendCountdown.hidden = false;
            resendCountdown.textContent = resendRemaining + 's 后可重发';
        } else {
            button.disabled = false;
            resendCountdown.hidden = true;
            label.textContent = codeRemaining > 0 ? '重新发送验证码' : '发送验证码';
        }

        if (codeRemaining > 0) {
            validity.hidden = false;
            validity.classList.toggle('is-expiring', codeRemaining <= 60);
            validity.classList.remove('is-expired');
            codeCountdown.textContent = formatClock(codeRemaining);
        } else if (!validity.hidden) {
            validity.classList.remove('is-expiring');
            validity.classList.add('is-expired');
            validity.firstChild.textContent = '验证码已过期，请重新发送 ';
            codeCountdown.textContent = '00:00';
        }
    }

    render();
    const interval = window.setInterval(function () {
        if (resendRemaining > 0) resendRemaining -= 1;
        if (codeRemaining > 0) codeRemaining -= 1;
        render();
        if (resendRemaining <= 0 && codeRemaining <= 0) window.clearInterval(interval);
    }, 1000);

    timer.addEventListener('submit', function () {
        button.disabled = true;
        label.textContent = '正在发送...';
        resendCountdown.hidden = true;
    });
});
