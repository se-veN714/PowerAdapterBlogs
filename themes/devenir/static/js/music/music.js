/* Music 页面交互增强（纯前端，不发起请求、不生成整页）。
   - Archive 行内展开：button 切换摘要说明区域，同步 aria-expanded。
     详情不假装存在后端路由；展开区域仅说明归档状态。
   尊重 prefers-reduced-motion（过渡在 CSS 中关闭）。 */
(function () {
    "use strict";

    var links = Array.prototype.slice.call(document.querySelectorAll(".music-archive__link"));
    links.forEach(function (link) {
        link.addEventListener("click", function () {
            var row = link.closest(".music-archive__row");
            if (!row) return;
            var note = row.querySelector(".music-archive__note");
            if (!note) return;
            note.hidden = !note.hidden;
            link.setAttribute("aria-expanded", note.hidden ? "false" : "true");
        });
    });
})();
