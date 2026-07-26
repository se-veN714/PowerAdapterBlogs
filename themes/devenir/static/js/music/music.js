/* Music 页面 v2 交互增强（纯前端，不发起请求、不生成整页）。
   - Archive 占位链接：拦截默认跳转，切换行内 TODO 说明。
   尊重 prefers-reduced-motion（过渡在 CSS 中关闭）。 */
(function () {
    "use strict";

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
