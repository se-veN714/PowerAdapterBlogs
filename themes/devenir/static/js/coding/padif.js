/* Padif — LOCAL BROWSER WORKSPACE
   纯浏览器本地运行：不发起任何网络请求（无 fetch / XHR / HTMX / beacon），
   无 token / CSRF / 服务器持久化。文档与版本仅存 localStorage。
   安全：用户文本一律 textContent / createElement，绝不 innerHTML。
   参考 .local/padif/web 的概念（文档列表 / 版本 / 句子级差异），不引用其后端调用。 */
(function () {
    "use strict";

    var STORE_KEY = "padif.local.workspace.v1";
    var CHAR_DIFF_LIMIT = 500; /* 超过该长度的改写句退化为整句 del/ins，避免 O(n*m) 卡顿 */
    var SENTENCE_LCS_CELL_LIMIT = 250000;
    var MAX_IMPORT_BYTES = 5 * 1024 * 1024;
    var MAX_DOCS = 200;
    var MAX_VERSIONS_PER_DOC = 200;
    var MAX_VERSION_CHARS = 1000000;
    var MAX_TOTAL_CHARS = 3000000;

    /* ---------- 存储层 ---------- */

    function emptyStore() { return { v: 1, docs: [] }; }

    function loadStore() {
        try {
            var raw = window.localStorage.getItem(STORE_KEY);
            if (!raw) return emptyStore();
            var data = JSON.parse(raw);
            if (!data || data.v !== 1 || !Array.isArray(data.docs)) return emptyStore();
            return data;
        } catch (e) {
            return emptyStore();
        }
    }

    function saveStore(store) {
        try {
            window.localStorage.setItem(STORE_KEY, JSON.stringify(store));
            return true;
        } catch (e) {
            showStatus("写入 localStorage 失败（可能处于隐私模式或存储已满）。当前改动未保存，请先导出 JSON 备份。", true);
            return false;
        }
    }

    function uid(prefix) {
        return prefix + "-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8);
    }

    function fmtTime(iso) {
        var d = new Date(iso);
        if (isNaN(d.getTime())) return "—";
        function p(n) { return (n < 10 ? "0" : "") + n; }
        return d.getFullYear() + "." + p(d.getMonth() + 1) + "." + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
    }

    /* ---------- 状态 ---------- */

    var store = loadStore();
    var currentDocId = null;
    var pendingImportData = null;
    var els = {};

    function $(id) { return document.getElementById(id); }

    function currentDoc() {
        for (var i = 0; i < store.docs.length; i++) {
            if (store.docs[i].id === currentDocId) return store.docs[i];
        }
        return null;
    }

    /* ---------- DOM 构建（全部 createElement + textContent） ---------- */

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function clearChildren(node) {
        while (node.firstChild) node.removeChild(node.firstChild);
    }

    function showStatus(message, isError) {
        if (!els.status) return;
        els.status.textContent = message;
        els.status.classList.toggle("is-error", !!isError);
        els.status.hidden = false;
    }

    /* ---------- 渲染：文档列表 ---------- */

    function renderDocList() {
        clearChildren(els.doclist);
        els.docCount.textContent = String(store.docs.length);
        els.doclistEmpty.hidden = store.docs.length > 0;
        store.docs.forEach(function (doc) {
            var li = document.createElement("li");
            var btn = el("button", doc.id === currentDocId ? "is-active" : "", null);
            btn.type = "button";
            btn.appendChild(el("span", "", doc.title));
            btn.appendChild(el("span", "pd-doclist__meta", doc.versions.length + " 版"));
            btn.addEventListener("click", function () { selectDoc(doc.id); });
            li.appendChild(btn);
            els.doclist.appendChild(li);
        });
    }

    /* ---------- 渲染：当前文档 ---------- */

    function renderCurrent() {
        var doc = currentDoc();
        var has = !!doc;
        els.editorPanel.hidden = !has;
        els.versionsPanel.hidden = !has;
        els.rightEmpty.hidden = has;
        if (!has) {
            els.diffPanel.hidden = true;
            return;
        }
        els.currentTitle.textContent = doc.title;
        var latest = doc.versions[doc.versions.length - 1];
        els.editorBody.value = latest ? latest.content : "";
        renderVersions(doc);
    }

    function renderVersions(doc) {
        clearChildren(els.verlist);
        els.versionCount.textContent = String(doc.versions.length);
        for (var i = doc.versions.length - 1; i >= 0; i--) {
            (function (ver, idx) {
                var li = document.createElement("li");
                var label = document.createElement("label");
                var box = document.createElement("input");
                box.type = "checkbox";
                box.value = ver.vid;
                box.addEventListener("change", updateDiffButton);
                label.appendChild(box);
                label.appendChild(el("span", "", "v" + (idx + 1) + " " + ver.message));
                label.appendChild(el("span", "pd-ver__kind", ver.kind));
                label.appendChild(el("span", "pd-ver__time", fmtTime(ver.createdAt)));
                li.appendChild(label);
                els.verlist.appendChild(li);
            })(doc.versions[i], i);
        }
        updateDiffButton();
    }

    function selectedVersionIds() {
        var boxes = els.verlist.querySelectorAll("input[type=checkbox]:checked");
        var ids = [];
        boxes.forEach(function (b) { ids.push(b.value); });
        return ids;
    }

    function updateDiffButton() {
        els.diffBtn.disabled = selectedVersionIds().length !== 2;
    }

    /* ---------- 操作 ---------- */

    function selectDoc(id) {
        currentDocId = id;
        els.diffPanel.hidden = true;
        renderDocList();
        renderCurrent();
    }

    function createDoc() {
        var title = els.newDocTitle.value.trim();
        var body = els.newDocBody.value;
        if (!title) { els.newDocTitle.focus(); return; }
        if (store.docs.length >= MAX_DOCS) {
            showStatus("本地工作区最多保存 " + MAX_DOCS + " 篇文档，请先导出并清理旧文档。", true);
            return;
        }
        if (body.length > MAX_VERSION_CHARS) {
            showStatus("单个版本最多允许 " + MAX_VERSION_CHARS + " 个字符。", true);
            return;
        }
        var now = new Date().toISOString();
        var doc = {
            id: uid("doc"),
            title: title,
            createdAt: now,
            versions: [{ vid: uid("ver"), message: "建档 · 首版快照", kind: "major", content: body, createdAt: now }]
        };
        store.docs.push(doc);
        if (!saveStore(store)) return;
        els.newDocTitle.value = "";
        els.newDocBody.value = "";
        selectDoc(doc.id);
    }

    function commitVersion() {
        var doc = currentDoc();
        if (!doc) return;
        var msg = els.commitMsg.value.trim();
        if (!msg) { els.commitMsg.focus(); return; }
        if (doc.versions.length >= MAX_VERSIONS_PER_DOC) {
            showStatus("单篇文档最多保存 " + MAX_VERSIONS_PER_DOC + " 个版本，请先导出备份。", true);
            return;
        }
        if (els.editorBody.value.length > MAX_VERSION_CHARS) {
            showStatus("单个版本最多允许 " + MAX_VERSION_CHARS + " 个字符。", true);
            return;
        }
        doc.versions.push({
            vid: uid("ver"),
            message: msg,
            kind: els.commitKind.value,
            content: els.editorBody.value,
            createdAt: new Date().toISOString()
        });
        if (!saveStore(store)) { doc.versions.pop(); return; }
        els.commitMsg.value = "";
        renderDocList();
        renderCurrent();
    }

    /* 删除文档：两步 in-page 确认（绝不 window.confirm） */
    var deleteArmTimer = null;
    function deleteDoc() {
        var doc = currentDoc();
        if (!doc) return;
        if (els.deleteDocBtn.dataset.armed !== "1") {
            els.deleteDocBtn.dataset.armed = "1";
            els.deleteDocBtn.textContent = "再次点击确认删除";
            clearTimeout(deleteArmTimer);
            deleteArmTimer = setTimeout(disarmDelete, 5000);
            return;
        }
        disarmDelete();
        store.docs = store.docs.filter(function (d) { return d.id !== doc.id; });
        if (!saveStore(store)) return;
        currentDocId = null;
        renderDocList();
        renderCurrent();
    }
    function disarmDelete() {
        clearTimeout(deleteArmTimer);
        delete els.deleteDocBtn.dataset.armed;
        els.deleteDocBtn.textContent = "删除本文档";
    }

    /* ---------- 句子级 diff ---------- */

    function splitSentences(text) {
        var lines = String(text).split("\n");
        var out = [];
        lines.forEach(function (line, li) {
            /* 句末标点后切分（捕获式，兼容无 lookbehind 环境） */
            var parts = line.split(/([。！？；.!?;]+)/);
            var buf = "";
            parts.forEach(function (p, pi) {
                buf += p;
                if (pi % 2 === 1 || pi === parts.length - 1) {
                    if (buf !== "") out.push(buf);
                    buf = "";
                }
            });
            if (li < lines.length - 1) out.push("\n"); /* 行界参与对齐 */
        });
        if (out.length && out[out.length - 1] === "\n") out.pop();
        return out;
    }

    function lcsOps(a, b) {
        var n = a.length, m = b.length;
        var dp = [];
        var i, j;
        for (i = 0; i <= n; i++) { dp.push(new Array(m + 1).fill(0)); }
        for (i = n - 1; i >= 0; i--) {
            for (j = m - 1; j >= 0; j--) {
                dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
            }
        }
        var ops = [];
        i = 0; j = 0;
        while (i < n && j < m) {
            if (a[i] === b[j]) { ops.push({ t: "eq", text: a[i] }); i++; j++; }
            else if (dp[i + 1][j] >= dp[i][j + 1]) { ops.push({ t: "del", text: a[i] }); i++; }
            else { ops.push({ t: "ins", text: b[j] }); j++; }
        }
        while (i < n) { ops.push({ t: "del", text: a[i] }); i++; }
        while (j < m) { ops.push({ t: "ins", text: b[j] }); j++; }
        return ops;
    }

    /* 连续 del + ins 段配对为 rep（改写） */
    function pairRep(ops) {
        var out = [];
        var i = 0;
        while (i < ops.length) {
            if (ops[i].t === "del" || ops[i].t === "ins") {
                var dels = [], inss = [];
                while (i < ops.length && ops[i].t === "del") { dels.push(ops[i]); i++; }
                while (i < ops.length && ops[i].t === "ins") { inss.push(ops[i]); i++; }
                var pairCount = Math.min(dels.length, inss.length);
                for (var k = 0; k < pairCount; k++) {
                    if (dels[k].text === "\n" || inss[k].text === "\n") {
                        out.push(dels[k]); out.push(inss[k]);
                    } else {
                        out.push({ t: "rep", oldText: dels[k].text, newText: inss[k].text });
                    }
                }
                for (var d = pairCount; d < dels.length; d++) out.push(dels[d]);
                for (var s = pairCount; s < inss.length; s++) out.push(inss[s]);
            } else {
                out.push(ops[i]); i++;
            }
        }
        return out;
    }

    /* rep 内部：字级高亮（长句退化整句处理） */
    function appendRepBody(container, oldText, newText) {
        if (oldText.length > CHAR_DIFF_LIMIT || newText.length > CHAR_DIFF_LIMIT) {
            container.appendChild(el("span", "del", oldText));
            container.appendChild(el("span", "ins", newText));
            return;
        }
        var ops = lcsOps(oldText.split(""), newText.split(""));
        ops.forEach(function (op) {
            if (op.t === "eq") container.appendChild(document.createTextNode(op.text));
            else container.appendChild(el("span", op.t, op.text));
        });
    }

    function renderDiff() {
        var doc = currentDoc();
        if (!doc) return;
        var ids = selectedVersionIds();
        if (ids.length !== 2) return;
        var vers = [];
        doc.versions.forEach(function (v, idx) {
            if (ids.indexOf(v.vid) !== -1) vers.push({ v: v, num: idx + 1 });
        });
        if (vers.length !== 2) return;
        /* 早版本在左（旧→新） */
        vers.sort(function (a, b) { return a.num - b.num; });
        var oldV = vers[0], newV = vers[1];

        var oldSentences = splitSentences(oldV.v.content);
        var newSentences = splitSentences(newV.v.content);
        var coarse = oldSentences.length * newSentences.length > SENTENCE_LCS_CELL_LIMIT;
        var ops = coarse
            ? [{ t: "rep", oldText: oldV.v.content, newText: newV.v.content }]
            : pairRep(lcsOps(oldSentences, newSentences));
        clearChildren(els.diffBody);
        var stats = { ins: 0, del: 0, rep: 0, eq: 0 };
        ops.forEach(function (op) {
            if (op.text === "\n" && op.t !== "rep") {
                els.diffBody.appendChild(document.createElement("br"));
                return;
            }
            stats[op.t] += 1;
            if (op.t === "rep") {
                var span = el("span", "rep", null);
                appendRepBody(span, op.oldText, op.newText);
                els.diffBody.appendChild(span);
            } else {
                els.diffBody.appendChild(el("span", op.t, op.text));
            }
        });
        els.diffLabel.textContent = "v" + oldV.num + " → v" + newV.num;
        els.diffStats.textContent =
            (coarse ? "文档规模超过精细差异上限，已退化为整版改写视图 · " : "") +
            "+" + stats.ins + " 新增 · -" + stats.del + " 删除 · ~" + stats.rep + " 改写 · =" + stats.eq + " 未变";
        els.diffPanel.hidden = false;
        els.diffPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    /* ---------- 导出 / 导入 ---------- */

    function exportJson() {
        var payload = JSON.stringify(store, null, 2);
        var blob = new Blob([payload], { type: "application/json" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = "padif-local-workspace-" + new Date().toISOString().slice(0, 10) + ".json";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function importJson(file) {
        if (file.size > MAX_IMPORT_BYTES) {
            showStatus("导入失败：JSON 文件不能超过 5 MB。", true);
            return;
        }
        var reader = new FileReader();
        reader.onload = function () {
            var data;
            try {
                data = JSON.parse(String(reader.result));
            } catch (e) {
                showStatus("导入失败：文件不是合法 JSON。", true);
                return;
            }
            if (!data || data.v !== 1 || !Array.isArray(data.docs)) {
                showStatus("导入失败：结构不符合 Padif 本地工作区格式（需要 v:1 + docs 数组）。", true);
                return;
            }
            var docIds = Object.create(null);
            var totalChars = 0;
            var valid = data.docs.length <= MAX_DOCS && data.docs.every(function (d) {
                if (!d || typeof d.id !== "string" || !d.id || docIds[d.id] ||
                    typeof d.title !== "string" || d.title.length > 120 ||
                    !Array.isArray(d.versions) || d.versions.length > MAX_VERSIONS_PER_DOC) {
                    return false;
                }
                docIds[d.id] = true;
                var versionIds = Object.create(null);
                return d.versions.every(function (v) {
                    if (!v || typeof v.vid !== "string" || !v.vid || versionIds[v.vid] ||
                        typeof v.content !== "string" || v.content.length > MAX_VERSION_CHARS ||
                        (v.message !== undefined && (typeof v.message !== "string" || v.message.length > 200)) ||
                        (v.kind !== undefined && ["patch", "minor", "major"].indexOf(v.kind) === -1) ||
                        (v.createdAt !== undefined && typeof v.createdAt !== "string")) {
                        return false;
                    }
                    versionIds[v.vid] = true;
                    totalChars += v.content.length;
                    return totalChars <= MAX_TOTAL_CHARS;
                });
            });
            if (!valid) {
                showStatus("导入失败：数据重复、字段不完整，或超过 200 篇文档、每篇 200 个版本、总计 300 万字符的安全上限。", true);
                return;
            }
            pendingImportData = data;
            if (store.docs.length > 0) {
                els.importSummary.textContent =
                    "当前 " + store.docs.length + " 篇文档将被导入文件中的 " + data.docs.length + " 篇文档完全替换。";
                els.importConfirm.hidden = false;
                els.importConfirmBtn.focus();
                return;
            }
            applyPendingImport();
        };
        reader.readAsText(file);
    }

    function applyPendingImport() {
        if (!pendingImportData) return;
        var previousStore = store;
        store = pendingImportData;
        if (!saveStore(store)) {
            store = previousStore;
            return;
        }
        var importedCount = store.docs.length;
        pendingImportData = null;
        els.importConfirm.hidden = true;
        currentDocId = null;
        renderDocList();
        renderCurrent();
        showStatus("导入完成：已载入 " + importedCount + " 篇本地文档。", false);
    }

    function cancelPendingImport() {
        pendingImportData = null;
        els.importConfirm.hidden = true;
        showStatus("已取消导入，当前本地文档未发生变化。", false);
        els.importLabel.focus();
    }

    /* ---------- 启动 ---------- */

    function init() {
        els = {
            doclist: $("pd-doclist"), doclistEmpty: $("pd-doclist-empty"), docCount: $("pd-doc-count"),
            newDocTitle: $("pd-new-doc-title"), newDocBody: $("pd-new-doc-body"),
            editorPanel: $("pd-editor-panel"), currentTitle: $("pd-current-title"),
            editorBody: $("pd-editor-body"), commitMsg: $("pd-commit-msg"), commitKind: $("pd-commit-kind"),
            versionsPanel: $("pd-versions-panel"), verlist: $("pd-verlist"), versionCount: $("pd-version-count"),
            diffBtn: $("pd-diff-btn"), deleteDocBtn: $("pd-delete-doc"),
            diffPanel: $("pd-diff-panel"), diffLabel: $("pd-diff-label"),
            diffStats: $("pd-diff-stats"), diffBody: $("pd-diff-body"),
            rightEmpty: $("pd-right-empty"), status: $("pd-status"),
            importLabel: $("pd-import-label"), importConfirm: $("pd-import-confirm"),
            importSummary: $("pd-import-summary"), importConfirmBtn: $("pd-import-confirm-btn"),
            importCancelBtn: $("pd-import-cancel-btn")
        };
        if (!els.doclist) return; /* 非本页 */

        $("pd-create-doc").addEventListener("click", createDoc);
        $("pd-commit-btn").addEventListener("click", commitVersion);
        els.diffBtn.addEventListener("click", renderDiff);
        els.deleteDocBtn.addEventListener("click", deleteDoc);
        $("pd-export").addEventListener("click", exportJson);
        els.importLabel.addEventListener("keydown", function (event) {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                $("pd-import").click();
            }
        });
        $("pd-import").addEventListener("change", function (e) {
            if (e.target.files && e.target.files[0]) importJson(e.target.files[0]);
            e.target.value = "";
        });
        els.importConfirmBtn.addEventListener("click", applyPendingImport);
        els.importCancelBtn.addEventListener("click", cancelPendingImport);

        renderDocList();
        renderCurrent();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
