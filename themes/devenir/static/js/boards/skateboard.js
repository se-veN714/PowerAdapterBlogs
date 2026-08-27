/* ============================================================
   Devenir — Board Index: Skateboard（仅展示层）
   1. 选中状态完全由前端控制（不依赖数据库 is_active 字段）：
      - 默认首个节点 active；点击切换 active 视觉态。
      - 与 htmx 共存：htmx 加载 Selected Line 内容，JS 同时更新 active 态。
   2. 视频离屏暂停（IntersectionObserver），htmx 交换后重新绑定。
   3. 移动端初始将 Active 节点滚动到可视区中央。
   4. 关系图谱：节点圆心连线 + 拖拽；选中节点持久高亮关联边。
   ============================================================ */

document.addEventListener('DOMContentLoaded', function () {
    'use strict';

    var constellation = document.querySelector('.sk-constellation');
    var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

    /* ---------- 0. glitch 颜色注入（与 main.js editorial-visual 同一模式） ----------
       覆盖本页所有带 data-glitch-color 的区块（hero / 星图 / clips /
       公开文章区 .bd-posts / 参与 CTA .bd-cta） */
    document.querySelectorAll('[data-glitch-color]').forEach(function (el) {
        el.style.setProperty('--glitch-c', el.dataset.glitchColor);
    });

    if (constellation) {
        var nodes = Array.prototype.slice.call(
            constellation.querySelectorAll('.sk-node:not(.sk-node--open)')
        );
        var liveSvg = constellation.querySelector('.sk-links--live');
        var dragMedia = window.matchMedia('(min-width: 768px)');

        /* ---------- 1. 关系图谱：节点圆心连线 + 拖拽（桌面 ≥768px） ---------- */
        // 渐进增强：节点仍是原生 button，连线只是展示层；拖拽位置以百分比写回，
        // 视口缩放后构图保持。连线直接走圆心（圆会盖住线中段），无需边界锚定。
        // 不作用力导向模拟（reduced-motion 与构图约束）。
        var edges = [];
        var lines = [];
        var highlightActiveEdges = function () {};

        if (liveSvg && nodes.length) {
            edges = (constellation.dataset.edges || '')
                .split(',')
                .map(function (pair) { return pair.split(':').map(Number); })
                .filter(function (e) { return e.length === 2 && nodes[e[0]] && nodes[e[1]]; });

            // 节点用 transform: translate(-50%,-50%) 定位，layout 的 offsetLeft/Top 是
            // 未偏移前的盒子角，不能直接 +width/2（会得到右下角）。改用真实圆
            // （.sk-node-frame）的 getBoundingClientRect 相对 SVG 计算视觉圆心，
            // 这样不受 translate 与下方 label 高度影响。
            function nodeCenter(el) {
                var frame = el.querySelector('.sk-node-frame') || el;
                var fc = frame.getBoundingClientRect();
                var sc = liveSvg.getBoundingClientRect();
                return {
                    x: fc.left + fc.width / 2 - sc.left,
                    y: fc.top + fc.height / 2 - sc.top
                };
            }

            function updateLines() {
                if (!dragMedia.matches) return;
                lines.forEach(function (l) {
                    var a = nodeCenter(l.a);
                    var b = nodeCenter(l.b);
                    l.el.setAttribute('x1', a.x);
                    l.el.setAttribute('y1', a.y);
                    l.el.setAttribute('x2', b.x);
                    l.el.setAttribute('y2', b.y);
                });
            }

            highlightActiveEdges = function () {
                var active = nodes.find(function (n) { return n.classList.contains('is-active'); });
                lines.forEach(function (l) {
                    l.el.classList.remove('is-active-edge');
                    if (active && (l.a === active || l.b === active)) {
                        l.el.classList.add('is-active-edge');
                    }
                });
            };

            if (edges.length) {
                edges.forEach(function (e) {
                    var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                    liveSvg.appendChild(line);
                    lines.push({ el: line, a: nodes[e[0]], b: nodes[e[1]] });
                });
                updateLines();
                highlightActiveEdges();
            }

            var resizeTimer = null;
            window.addEventListener('resize', function () {
                window.clearTimeout(resizeTimer);
                resizeTimer = window.setTimeout(updateLines, 120);
            });
            if (dragMedia.addEventListener) dragMedia.addEventListener('change', updateLines);

            // hover + 选中高亮相连边（Obsidian 式）
            nodes.forEach(function (node) {
                node.addEventListener('mouseenter', function () {
                    lines.forEach(function (l) {
                        if (l.a === node || l.b === node) l.el.classList.add('is-lit');
                    });
                });
                node.addEventListener('mouseleave', function () {
                    lines.forEach(function (l) { l.el.classList.remove('is-lit'); });
                });
            });

            // 拖拽：>4px 判定为拖动，松开后抑制 click（mock 切换与未来 hx-get 均不误触发）
            var dragState = null;
            nodes.forEach(function (node) {
                node.addEventListener('pointerdown', function (ev) {
                    if (!dragMedia.matches || ev.button !== 0) return;
                    var rect = constellation.getBoundingClientRect();
                    dragState = {
                        node: node,
                        startX: ev.clientX,
                        startY: ev.clientY,
                        baseL: parseFloat(node.style.left) || ((node.offsetLeft) / rect.width) * 100,
                        baseT: parseFloat(node.style.top) || ((node.offsetTop) / rect.height) * 100,
                        moved: false
                    };
                    node.setPointerCapture(ev.pointerId);
                });
                node.addEventListener('pointermove', function (ev) {
                    if (!dragState || dragState.node !== node) return;
                    var dx = ev.clientX - dragState.startX;
                    var dy = ev.clientY - dragState.startY;
                    if (!dragState.moved && Math.hypot(dx, dy) > 4) {
                        dragState.moved = true;
                        node.classList.add('is-dragging');
                    }
                    if (!dragState.moved) return;
                    var rect = constellation.getBoundingClientRect();
                    var pctL = Math.min(94, Math.max(6, dragState.baseL + (dx / rect.width) * 100));
                    var pctT = Math.min(94, Math.max(6, dragState.baseT + (dy / rect.height) * 100));
                    node.style.left = pctL + '%';
                    node.style.top = pctT + '%';
                    updateLines();
                });
                function endDrag() {
                    if (!dragState || dragState.node !== node) return;
                    if (dragState.moved) constellation.dataset.skDragged = '1';
                    node.classList.remove('is-dragging');
                    dragState = null;
                }
                node.addEventListener('pointerup', endDrag);
                node.addEventListener('pointercancel', endDrag);
            });

            // 捕获阶段抑制拖拽后的 click（覆盖节点上的 mock 处理器与未来 hx-get）
            constellation.addEventListener('click', function (ev) {
                if (constellation.dataset.skDragged === '1') {
                    delete constellation.dataset.skDragged;
                    ev.preventDefault();
                    ev.stopPropagation();
                }
            }, true);
        }

        /* ---------- 2. Active 切换（前端完全控制，与 htmx 共存） ---------- */

        if (nodes.length) {
            var kicker = document.getElementById('sk-kicker-index');
            var selectedName = document.getElementById('sk-selected-name');

            // 初始：若无 active 则将首个节点设为 active（assembler 不再设置 state）
            if (!constellation.querySelector('.sk-node.is-active')) {
                var firstNode = nodes[0];
                firstNode.classList.add('is-active');
                firstNode.setAttribute('aria-pressed', 'true');
                var firstLabel = firstNode.querySelector('.sk-node-label');
                if (firstLabel && !firstNode.querySelector('.sk-node-state:not(.sk-node-state--role)')) {
                    var firstStateEl = document.createElement('span');
                    firstStateEl.className = 'sk-node-state';
                    firstStateEl.textContent = '[ ACTIVE NODE ]';
                    firstLabel.insertBefore(firstStateEl, firstLabel.querySelector('.sk-node-meta'));
                }
            }

            nodes.forEach(function (node) {
                node.addEventListener('click', function () {
                    if (node.classList.contains('is-active')) return;

                    nodes.forEach(function (other) {
                        other.classList.remove('is-active');
                        other.setAttribute('aria-pressed', 'false');
                        var state = other.querySelector('.sk-node-state:not(.sk-node-state--role)');
                        if (state) state.remove();
                    });

                    node.classList.add('is-active');
                    node.setAttribute('aria-pressed', 'true');
                    var label = node.querySelector('.sk-node-label');
                    if (label && !node.querySelector('.sk-node-state:not(.sk-node-state--role)')) {
                        var stateEl = document.createElement('span');
                        stateEl.className = 'sk-node-state';
                        stateEl.textContent = '[ ACTIVE NODE ]';
                        label.insertBefore(stateEl, label.querySelector('.sk-node-meta'));
                    }

                    // 静态头（MOCK 模式才存在；数据驱动模式下为 no-op）
                    if (kicker) kicker.textContent = node.dataset.nodeIndex || '--';
                    if (selectedName) selectedName.textContent = node.dataset.nodeName || '';
                    highlightActiveEdges();
                });
            });
        }

        /* ---------- 3. 移动端：Active 节点居中 ---------- */

        var mobileQuery = window.matchMedia('(max-width: 767px)');
        if (mobileQuery.matches) {
            var active = constellation.querySelector('.sk-node.is-active');
            if (active && active.scrollIntoView) {
                active.scrollIntoView({
                    block: 'nearest',
                    inline: 'center',
                    behavior: reduceMotion.matches ? 'auto' : 'smooth'
                });
            }
        }
    }

    /* ---------- 4. 视频可见即播：红黑 preview 进入视口/focus 自动播放，离屏暂停 ----------
       卡片 <video> 的 src 初始为主片（preload=metadata），一旦可见就把 source
       换成 preview.webm 并循环播放；正式观看走 WATCH CLIP 对话框的独立 video。
       触发双通道：IntersectionObserver + rAF 节流的 scroll/resize 兜底（任一生效即可，
       防个别环境下 IO 回调不派发）。reduced-motion 与无 hover 的触摸设备只展示
       poster；用户仍可主动打开 WATCH CLIP 播放正式视频。 */
    var observed = [];
    var previewAllowed = window.matchMedia('(hover: hover) and (pointer: fine)');

    function previewMedia(video) {
        return video.closest('[data-skate-preview]');
    }

    function playClipPreview(video) {
        if (reduceMotion.matches || !previewAllowed.matches) return;
        var media = previewMedia(video);
        if (media && video.dataset.skatePreviewLoaded !== '1') {
            var source = video.querySelector('source');
            if (source && media.dataset.skatePreview) {
                source.src = media.dataset.skatePreview;
                video.load();
                video.dataset.skatePreviewLoaded = '1';
            }
        }
        if (video.paused) video.play().catch(function () {});
    }

    function refreshVideoState(video) {
        var rect = video.getBoundingClientRect();
        if (rect.height === 0) return;
        var visible = rect.bottom > 0 && rect.top < window.innerHeight &&
            (Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0)) >= rect.height * 0.15;
        if (visible && previewMedia(video) && !reduceMotion.matches && previewAllowed.matches) {
            playClipPreview(video);
        } else if (!visible && !video.paused) {
            video.pause();
        }
    }

    var refreshQueued = false;
    function scheduleRefresh() {
        if (refreshQueued) return;
        refreshQueued = true;
        window.requestAnimationFrame(function () {
            refreshQueued = false;
            observed.forEach(refreshVideoState);
        });
    }

    function bindVideoObserver() {
        var videos = document.querySelectorAll('.sk-clip-media video, .sk-archive-media video');
        if (!videos.length) return;

        if ('IntersectionObserver' in window) {
            var observer = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        playClipPreview(entry.target);
                    } else if (!entry.target.paused) {
                        entry.target.pause();
                    }
                });
            }, { threshold: 0.15 });

            videos.forEach(function (video) {
                if (observed.indexOf(video) === -1) {
                    observer.observe(video);
                    observed.push(video);
                }
            });
        }

        // focus / hover 作为补充触发（键盘可达；hover 仅在有 hover 能力的设备上生效）
        videos.forEach(function (video) {
            var media = video.closest('.sk-clip-media, .sk-archive-media');
            if (!media || !media.dataset.skatePreview || media.dataset.skatePreviewBound) return;
            media.dataset.skatePreviewBound = '1';
            media.addEventListener('focusin', function () { playClipPreview(video); });
            media.addEventListener('mouseenter', function () { playClipPreview(video); });
        });

        scheduleRefresh();
    }

    window.addEventListener('scroll', scheduleRefresh, { passive: true });
    window.addEventListener('resize', scheduleRefresh, { passive: true });

    bindVideoObserver();

    /* ---------- 6. WATCH CLIP：在不离开 Index 的对话框中播放 ---------- */

    var player = document.querySelector('[data-skate-player]');
    var playerVideo = player && player.querySelector('[data-skate-player-video]');
    var lastPlayerTrigger = null;
    var playerMap = null;
    var amapPromise = null;

    function setPlayerText(name, value) {
        var node = player && player.querySelector('[data-skate-player-' + name + ']');
        if (node) node.textContent = value || '—';
    }

    function loadPlayerMap(media) {
        var node = player && player.querySelector('[data-skate-player-map]');
        var lng = Number(media.dataset.skateLongitude);
        var lat = Number(media.dataset.skateLatitude);
        if (!node || !Number.isFinite(lng) || !Number.isFinite(lat)) return;
        if (player.dataset.amapEnabled !== 'true' || !player.dataset.amapKey) {
            node.innerHTML = '<span>GEO ' + lat.toFixed(4) + ' / ' + lng.toFixed(4) + '</span>';
            return;
        }
        if (!amapPromise) {
            window._AMapSecurityConfig = { serviceHost: player.dataset.amapServiceHost || '/_AMapService' };
            amapPromise = new Promise(function (resolve, reject) {
                if (window.AMap) { resolve(window.AMap); return; }
                var script = document.createElement('script');
                script.src = 'https://webapi.amap.com/maps?v=2.0&key=' + encodeURIComponent(player.dataset.amapKey);
                script.onload = function () { resolve(window.AMap); };
                script.onerror = reject;
                document.head.appendChild(script);
            });
        }
        amapPromise.then(function (AMap) {
            if (!playerMap) playerMap = new AMap.Map(node, { zoom: 14, viewMode: '2D', mapStyle: 'amap://styles/dark' });
            playerMap.clearMap();
            playerMap.add(new AMap.Marker({ position: [lng, lat] }));
            playerMap.setZoomAndCenter(15, [lng, lat]);
        }).catch(function () {
            node.innerHTML = '<span>MAP UNAVAILABLE / ' + lat.toFixed(4) + ', ' + lng.toFixed(4) + '</span>';
        });
    }

    function openPlayer(media, trigger) {
        if (!player || !playerVideo) return;
        lastPlayerTrigger = trigger;
        playerVideo.src = media.dataset.skateMain;
        setPlayerText('title', media.dataset.skateTitle);
        setPlayerText('format', media.dataset.skateFormat);
        setPlayerText('category', media.dataset.skateCategory ? '/ ' + media.dataset.skateCategory : '');
        ['spot', 'filmed', 'duration', 'status', 'notes', 'address'].forEach(function (name) {
            setPlayerText(name, media.dataset['skate' + name.charAt(0).toUpperCase() + name.slice(1)]);
        });
        player.showModal();
        playerVideo.play().catch(function () {});
        loadPlayerMap(media);
    }

    function bindWatchButtons() {
        document.querySelectorAll('[data-skate-watch]').forEach(function (button) {
            if (button.dataset.skateWatchBound) return;
            button.dataset.skateWatchBound = '1';
            button.addEventListener('click', function () {
                var media = document.getElementById(button.dataset.skateWatch);
                if (media && media.dataset.skateMain) openPlayer(media, button);
            });
        });
    }

    /* 媒体卡片本身可点击：click / Enter / Space 直接打开 WATCH 对话框（与 WATCH CLIP 按钮同源） */
    function bindMediaClick() {
        document.querySelectorAll('.sk-clip-media[data-skate-main], .sk-archive-media[data-skate-main]').forEach(function (media) {
            if (media.dataset.skateClickBound) return;
            media.dataset.skateClickBound = '1';
            function activate() {
                if (!media.dataset.skateMain) return;
                var video = media.querySelector('video');
                if (video && !video.paused) video.pause(); // 对话框内播主片，先暂停背后预览
                openPlayer(media, media);
            }
            media.addEventListener('click', activate);
            media.addEventListener('keydown', function (event) {
                if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar') {
                    event.preventDefault();
                    activate();
                }
            });
        });
    }

    function closePlayer() {
        if (!player || !player.open) return;
        playerVideo.pause();
        playerVideo.removeAttribute('src');
        playerVideo.load();
        player.close();
        if (lastPlayerTrigger) {
            // 触发源是媒体卡片时，恢复其红黑预览循环（打开对话框时被暂停）
            var card = lastPlayerTrigger.closest && lastPlayerTrigger.closest('.sk-clip-media, .sk-archive-media');
            var preview = card && card.querySelector('video');
            if (preview && preview.dataset.skatePreviewLoaded === '1') preview.play().catch(function () {});
            lastPlayerTrigger.focus({ preventScroll: true });
        }
    }
    if (player) {
        player.querySelector('[data-skate-player-close]').addEventListener('click', closePlayer);
        player.addEventListener('click', function (event) { if (event.target === player) closePlayer(); });
        player.addEventListener('cancel', function (event) { event.preventDefault(); closePlayer(); });
        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && player.open) {
                event.preventDefault();
                closePlayer();
            }
        });
    }

    bindWatchButtons();
    bindMediaClick();

    // htmx 交换 Selected Line 后，旧视频随 DOM 移除，新视频重新绑定
    document.body.addEventListener('htmx:afterSwap', function (event) {
        if (event.detail.target && event.detail.target.id === 'selected-line') {
            // htmx 交换后的新 .reveal 元素未被 main.js 的 IntersectionObserver 观察，
            // 手动添加 .visible 使其立即可见（用户已主动点击，无需滚动触发动画）
            event.detail.target.querySelectorAll('.reveal').forEach(function (el) {
                el.classList.add('visible');
            });
            observed = observed.filter(function (video) { return document.contains(video); });
            bindVideoObserver();
            bindWatchButtons();
            bindMediaClick();
        }
    });
});
