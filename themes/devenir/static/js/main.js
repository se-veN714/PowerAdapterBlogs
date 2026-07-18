// ============================================
// Devenir Theme — Global Interactions
// Sidebar toggle / Scroll reveal / Glitch entrance
// ============================================

document.addEventListener('DOMContentLoaded', function () {

    // ===== Sidebar Toggle =====
    const menuToggle = document.getElementById('menuToggle');
    const sidebar = document.getElementById('sidebar');
    const sidebarOverlay = document.getElementById('sidebarOverlay');
    const sidebarClose = document.getElementById('sidebarClose');

    if (menuToggle && sidebar && sidebarOverlay && sidebarClose) {
        function openSidebar() {
            sidebar.classList.add('open');
            sidebarOverlay.classList.add('open');
            document.body.style.overflow = 'hidden';
        }
        function closeSidebar() {
            sidebar.classList.remove('open');
            sidebarOverlay.classList.remove('open');
            document.body.style.overflow = '';
        }

        menuToggle.addEventListener('click', openSidebar);
        sidebarClose.addEventListener('click', closeSidebar);
        sidebarOverlay.addEventListener('click', closeSidebar);

        sidebar.querySelectorAll('a').forEach(function (link) {
            link.addEventListener('click', closeSidebar);
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && sidebar.classList.contains('open')) {
                closeSidebar();
            }
        });
    }

    // ===== Scroll Reveal =====
    const revealObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
            }
        });
    }, { threshold: 0.15, rootMargin: '0px 0px -50px 0px' });

    document.querySelectorAll('.reveal').forEach(function (el) {
        revealObserver.observe(el);
    });

    // ============================================
    // Glitch Entrance System
    // ============================================

    // Per-section scramble character sets
    const scrambleSets = {
        skate: '\u221E\u00B1\u2248\u00D7\u00F7\u0394\u2207\u25CA\u25CB\u25CF\u25D0\u25D1\u25E3\u25A4\u25A5\u25A6\u25A7\u25A8\u25A9\u25B2\u25B3\u25BC\u25BD\u25E2\u25E3\u25E5\u25E6\u2295\u2297\u2299\u2318\u2394\u23DA\u23CE\u23CF\u2591\u2592\u2593',
        music: '\u2669\u266A\u266B\u266C\u266D\u266E\u266F\u266E\uD834\uDD2A\uD834\uDD2B\u2016\uD834\uDD00\uD834\uDD01\uD834\uDD02\uD834\uDD03\uD834\uDD04\uD834\uDD05\uD834\uDD06\uD834\uDD07\uD834\uDD08\u223F\u224B\u2248~\u00B7\u2022\u2025\u2026\u00B0\u2032\u2033\u2034\u3003',
        code: '{}[]()<>;:=!&|/\\\\#@$%^*+-_0123456789abcdef<>?\`~'
    };

    function scrambleText(el) {
        const originalText = el.dataset.original || el.textContent;
        if (!el.dataset.original) {
            el.dataset.original = originalText;
        }

        const section = el.closest('[data-scramble-set]');
        const setName = section ? section.dataset.scrambleSet : 'code';
        const charPool = scrambleSets[setName] || scrambleSets.code;

        const chars = originalText.split('');
        el.innerHTML = chars.map(function (ch, i) {
            if (ch === ' ' || ch === '\n') return ch;
            const randomChar = charPool[Math.floor(Math.random() * charPool.length)];
            return '<span class="scramble-char scramble-corrupted" data-index="' + i + '" data-original="' + ch.replace(/"/g, '&quot;') + '">' + randomChar + '</span>';
        }).join('');

        const spans = el.querySelectorAll('.scramble-char');
        spans.forEach(function (span, i) {
            const delay = 40 + Math.random() * 200 + i * 12;
            setTimeout(function () {
                span.textContent = span.dataset.original;
                span.classList.remove('scramble-corrupted');
                span.classList.add('scramble-resolved');
            }, delay);
        });
    }

    // ===== Editorial Section Glitch Observer =====
    const editorialObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
            if (entry.isIntersecting) {
                const section = entry.target;
                section.classList.add('editorial-entering');

                setTimeout(function () {
                    section.classList.remove('editorial-entering');
                    section.classList.add('editorial-entered');
                }, 300);

                const scrambleTargets = section.querySelectorAll('[data-scramble-text]');
                scrambleTargets.forEach(function (el, idx) {
                    setTimeout(function () { scrambleText(el); }, 400 + idx * 150);
                });

                editorialObserver.unobserve(section);
            }
        });
    }, { threshold: 0.2, rootMargin: '0px 0px -10% 0px' });

    document.querySelectorAll('.editorial-glitch').forEach(function (section) {
        editorialObserver.observe(section);
    });

    // ===== Glitch Color Hover (boards) =====
    // 将 data-glitch-color 注入 CSS 变量 --glitch-c，
    // 供 editorial-visual::after 的伪元素叠加使用。
    document.querySelectorAll('.editorial-visual[data-glitch-color]').forEach(function (visual) {
        visual.style.setProperty('--glitch-c', visual.dataset.glitchColor);
    });

    // ===== Music spectrum =====
    // Correlated frequency motion: bass carries the beat, mids stay active,
    // and highs decay. Transforms run below the outer glitch layer.
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const spectrumStates = [];

    document.querySelectorAll('[data-spectrum]').forEach(function (spectrum) {
        const barCount = 44;
        const bars = [];

        for (let i = 0; i < barCount; i++) {
            const bin = document.createElement('span');
            const bar = document.createElement('span');
            bin.className = 'spectrum-bin';
            bar.className = 'spectrum-bar';
            bin.appendChild(bar);
            spectrum.appendChild(bin);
            bars.push(bar);
        }

        spectrumStates.push({ element: spectrum, bars: bars, active: true });
    });

    if (spectrumStates.length) {
        const spectrumObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                const state = spectrumStates.find(function (item) { return item.element === entry.target; });
                if (state) state.active = entry.isIntersecting;
            });
        }, { threshold: 0.05 });

        spectrumStates.forEach(function (state) { spectrumObserver.observe(state.element); });

        function renderSpectrum(time) {
            spectrumStates.forEach(function (state) {
                if (!state.active || document.hidden) return;

                state.bars.forEach(function (bar, index) {
                    const x = index / (state.bars.length - 1);
                    const envelope = 0.18 + 0.82 * Math.pow(1 - x, 0.62);
                    const beat = Math.pow((Math.sin(time * 0.0032) + 1) / 2, 7) * 0.28 * (1 - x);
                    const bass = Math.sin(time * 0.0041 + index * 0.52) * 0.16;
                    const mid = Math.sin(time * 0.0067 + index * 1.13) * 0.10;
                    const detail = Math.sin(time * 0.0109 + index * 0.29) * 0.055;
                    const level = Math.max(0.07, Math.min(1, envelope * (0.55 + bass + mid + detail) + beat));
                    bar.style.transform = 'scaleY(' + level.toFixed(3) + ')';
                });
            });

            if (!reduceMotion) window.requestAnimationFrame(renderSpectrum);
        }

        renderSpectrum(reduceMotion ? 900 : performance.now());
    }

    // ===== Seamless Python code scroll =====
    document.querySelectorAll('.code-scroll-track').forEach(function (track) {
        const loop = track.querySelector('.code-loop');
        if (!loop || reduceMotion) return;

        const clone = loop.cloneNode(true);
        clone.setAttribute('aria-hidden', 'true');
        track.appendChild(clone);
        window.requestAnimationFrame(function () { track.classList.add('is-ready'); });
    });

});
