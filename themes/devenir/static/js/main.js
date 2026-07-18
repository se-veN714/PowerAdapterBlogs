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

    // ===== Glitch Color (boards) =====
    // 将 data-glitch-color 注入 CSS 变量 --glitch-c，
    // 供 editorial-visual::after 的伪元素叠加使用。
    document.querySelectorAll('.editorial-visual[data-glitch-color]').forEach(function (visual) {
        visual.style.setProperty('--glitch-c', visual.dataset.glitchColor);
    });

    // Touch screens have no reliable :hover state. Trigger the same glitch
    // once when each board visual enters the viewport, then release the class.
    const isTouchViewport = window.matchMedia('(hover: none), (pointer: coarse)').matches;
    if (isTouchViewport) {
        const touchGlitchObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;

                const visual = entry.target;
                visual.classList.remove('is-glitching');
                void visual.offsetWidth;
                visual.classList.add('is-glitching');

                window.setTimeout(function () {
                    visual.classList.remove('is-glitching');
                }, 650);

                touchGlitchObserver.unobserve(visual);
            });
        }, { threshold: 0.3, rootMargin: '0px 0px -8% 0px' });

        document.querySelectorAll('.editorial-visual').forEach(function (visual) {
            touchGlitchObserver.observe(visual);
        });
    }

    // ===== Music spectrum =====
    // Each frequency region follows its own physical character: sub-bass swells,
    // bass punches, mids breathe, presence bands flicker, and treble shimmers.
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

        spectrumStates.push({
            element: spectrum,
            bars: bars,
            levels: new Array(barCount).fill(0.08),
            active: true
        });
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
                    const seconds = time / 1000;
                    const kick = Math.pow((Math.sin(seconds * 3.35) + 1) / 2, 9);
                    const pulse = Math.pow((Math.sin(seconds * 6.7 + 0.7) + 1) / 2, 12);
                    let target;

                    if (x < 0.12) {
                        // Sub-bass: slow, heavy and coherent.
                        target = 0.20 + kick * 0.62 + Math.sin(seconds * 1.8 + index * 0.18) * 0.08;
                    } else if (x < 0.32) {
                        // Bass: rhythmic punch with a short secondary pulse.
                        target = 0.18 + kick * 0.48 + pulse * 0.20
                            + Math.sin(seconds * 3.6 + index * 0.42) * 0.10;
                    } else if (x < 0.58) {
                        // Low mids: broader, vocal-like movement.
                        target = 0.16 + (Math.sin(seconds * 2.4 + index * 0.47) + 1) * 0.16
                            + kick * 0.12;
                    } else if (x < 0.80) {
                        // Presence: faster consonant and instrument transients.
                        target = 0.10 + (Math.sin(seconds * 7.4 + index * 0.91) + 1) * 0.12
                            + pulse * 0.18;
                    } else {
                        // Treble: fine-grained shimmer with lower total energy.
                        target = 0.07 + (Math.sin(seconds * 12.8 + index * 1.63) + 1) * 0.065
                            + pulse * 0.08;
                    }

                    const ripple = Math.sin(seconds * 1.35 - index * 0.23) * 0.035;
                    target = Math.max(0.055, Math.min(1, target + ripple));

                    const smoothing = target > state.levels[index] ? 0.34 : 0.12;
                    state.levels[index] += (target - state.levels[index]) * smoothing;
                    bar.style.transform = 'scaleY(' + state.levels[index].toFixed(3) + ')';
                });
            });

            window.requestAnimationFrame(renderSpectrum);
        }

        window.requestAnimationFrame(renderSpectrum);
    }

});
