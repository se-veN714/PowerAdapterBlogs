(() => {
    document.querySelectorAll('[data-mfa-trust-countdown]').forEach(element => {
        const seconds = Number(element.dataset.remainingSeconds);
        if (!Number.isFinite(seconds) || seconds < 0) return;
        const deadline = Date.now() + seconds * 1000;
        let timer;
        const update = () => {
            const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
            if (remaining === 0) {
                element.textContent = '信任已到期，请在进入控制台时重新验证';
                if (timer) clearInterval(timer);
                return;
            }
            const days = Math.floor(remaining / 86400);
            const hours = Math.floor(remaining % 86400 / 3600);
            const minutes = Math.floor(remaining % 3600 / 60);
            const seconds = remaining % 60;
            const pad = value => String(value).padStart(2, '0');
            element.textContent = `${days}天 ${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
        };
        update();
        timer = setInterval(update, 1000);
        document.addEventListener('visibilitychange', update);
    });
})();
