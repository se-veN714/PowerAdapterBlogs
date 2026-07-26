/* Music 页面交互增强（纯前端，不发起请求、不生成整页）。
   - Recent Stream：点击 track 切换 active 并同步详情面板。
   - Period Archive：拦截占位链接，切换行内说明。
   尊重 prefers-reduced-motion（过渡在 CSS 中关闭）。 */
(function () {
    "use strict";

    var data = window.MUSIC_PAGE_DATA || { recentTracks: [] };
    var tracks = Array.prototype.slice.call(document.querySelectorAll(".music-track"));
    var detail = document.getElementById("music-stream-detail");
    if (!tracks.length) return;

    var dIdx = detail && detail.querySelector(".music-stream__detail-idx");
    var dTitle = detail && detail.querySelector(".music-stream__detail-title");
    var dArtist = detail && detail.querySelector(".music-stream__detail-artist");
    var dMeta = detail ? detail.querySelectorAll(".music-stream__detail-meta dd") : [];

    function pad(n) { return (n < 10 ? "0" : "") + n; }

    function select(el) {
        tracks.forEach(function (t) {
            var on = t === el;
            t.classList.toggle("is-active", on);
            t.setAttribute("aria-pressed", on ? "true" : "false");
        });
        var i = parseInt(el.getAttribute("data-idx"), 10);
        var rec = data.recentTracks[i];
        if (!rec) return;
        if (dIdx) dIdx.textContent = "#" + pad(rec.idx);
        if (dTitle) dTitle.textContent = rec.title;
        if (dArtist) dArtist.textContent = rec.artist;
        if (dMeta && dMeta.length >= 3) {
            dMeta[0].textContent = rec.time;
            dMeta[1].textContent = rec.dur;
            dMeta[2].textContent = rec.source;
        }
    }

    tracks.forEach(function (t) {
        t.addEventListener("click", function () { select(t); });
    });

    var links = Array.prototype.slice.call(document.querySelectorAll(".music-archive__link"));
    links.forEach(function (link) {
        link.addEventListener("click", function (e) {
            e.preventDefault();
            var row = link.closest(".music-archive__row");
            if (!row) return;
            var note = row.querySelector(".music-archive__note");
            if (note) note.hidden = !note.hidden;
        });
    });
})();
