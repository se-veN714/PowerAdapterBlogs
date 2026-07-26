document.addEventListener('DOMContentLoaded', function () {
    const consolePanel = document.querySelector('[data-credential-console]');
    if (!consolePanel) return;

    const password = document.getElementById('id_new_password1');
    const confirmation = document.getElementById('id_new_password2');
    const strengthLabel = consolePanel.querySelector('[data-strength-label]');
    const bars = Array.from(consolePanel.querySelectorAll('.entropy-bars i'));
    const matchStatus = consolePanel.querySelector('[data-match-status]');
    const form = consolePanel.querySelector('[data-rotation-form]');
    const submit = consolePanel.querySelector('[data-rotation-submit]');
    const countdown = consolePanel.querySelector('[data-verification-countdown]');
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const rules = {
        length: function (value) { return value.length >= 12; },
        case: function (value) { return /[a-z]/.test(value) && /[A-Z]/.test(value); },
        number: function (value) { return /\d/.test(value); },
        symbol: function (value) { return /[^A-Za-z0-9]/.test(value); }
    };
    const labels = ['STANDBY', 'WEAK', 'ACCEPTABLE', 'STRONG', 'HARDENED'];

    function renderCredentialSignal() {
        const value = password ? password.value : '';
        const passed = Object.keys(rules).filter(function (name) {
            const ok = rules[name](value);
            const node = consolePanel.querySelector('[data-rule="' + name + '"]');
            if (node) node.classList.toggle('is-passed', ok);
            return ok;
        }).length;

        bars.forEach(function (bar, index) {
            bar.classList.toggle('is-active', Boolean(value) && index < passed);
        });
        strengthLabel.textContent = value ? labels[passed] : labels[0];
        strengthLabel.dataset.level = String(value ? passed : 0);

        if (!confirmation || !confirmation.value) {
            matchStatus.textContent = 'CONFIRMATION WAITING';
            matchStatus.className = 'credential-match';
        } else if (confirmation.value === value) {
            matchStatus.textContent = 'KEY STREAMS MATCH';
            matchStatus.className = 'credential-match is-match';
        } else {
            matchStatus.textContent = 'KEY STREAMS MISMATCH';
            matchStatus.className = 'credential-match is-mismatch';
        }
    }

    if (password && confirmation) {
        password.addEventListener('input', renderCredentialSignal);
        confirmation.addEventListener('input', renderCredentialSignal);
        renderCredentialSignal();
    }

    let remaining = Number.parseInt(consolePanel.dataset.verificationSeconds || '0', 10);
    function renderCountdown() {
        const minutes = Math.floor(Math.max(remaining, 0) / 60);
        const seconds = Math.max(remaining, 0) % 60;
        countdown.textContent = String(minutes).padStart(2, '0') + ':' + String(seconds).padStart(2, '0');
        if (remaining <= 60) consolePanel.classList.add('verification-expiring');
        remaining -= 1;
    }
    renderCountdown();
    const countdownTimer = window.setInterval(function () {
        renderCountdown();
        if (remaining < 0) window.clearInterval(countdownTimer);
    }, 1000);

    form.addEventListener('submit', function () {
        submit.classList.add('is-rotating');
        submit.querySelector('span').textContent = 'ROTATING...';
        if (!reduceMotion) consolePanel.classList.add('rotation-committing');
    });
});
