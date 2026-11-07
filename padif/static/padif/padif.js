(function () {
  "use strict";

  function initDropzone(zone) {
    var input = zone.querySelector('input[type="file"]');
    var label = zone.querySelector(".padif-dropzone__label");
    var filename = zone.querySelector("[data-padif-file-name]");
    if (!input || !label || !filename) return;

    function updateName(file) {
      filename.textContent = file ? file.name : "未选择文件";
      zone.classList.toggle("has-file", Boolean(file));
    }

    function acceptFiles(files) {
      if (!files || !files.length) return;
      var file = files[0];
      try {
        var transfer = new DataTransfer();
        transfer.items.add(file);
        input.files = transfer.files;
      } catch (error) {
        // Browsers that block programmatic file assignment still support click selection.
      }
      updateName(file);
    }

    input.addEventListener("change", function () {
      updateName(input.files && input.files[0]);
    });
    label.addEventListener("dragover", function (event) {
      event.preventDefault();
      zone.classList.add("is-dragging");
    });
    label.addEventListener("dragleave", function () {
      zone.classList.remove("is-dragging");
    });
    label.addEventListener("drop", function (event) {
      event.preventDefault();
      zone.classList.remove("is-dragging");
      acceptFiles(event.dataTransfer.files);
    });
  }

  function initWorldlineDrawer() {
    var layout = document.querySelector("[data-worldline-layout]");
    if (!layout) return;
    var drawer = layout.querySelector("[data-version-drawer]");
    var handle = layout.querySelector("[data-drawer-handle]");
    var closeButton = layout.querySelector("[data-drawer-close]");
    if (!drawer || !handle || !closeButton) return;
    var key = "padif.worldline-drawer." + window.location.pathname;
    var lastFocus = null;

    function setOpen(open, moveFocus) {
      if (!open && drawer.contains(document.activeElement)) lastFocus = document.activeElement;
      drawer.hidden = !open;
      handle.hidden = open;
      handle.setAttribute("aria-expanded", String(open));
      layout.classList.toggle("worldline-collapsed", !open);
      try { window.sessionStorage.setItem(key, open ? "open" : "closed"); } catch (error) { /* Optional preference only. */ }
      if (moveFocus) {
        var target = open ? (lastFocus && lastFocus.isConnected ? lastFocus : closeButton) : handle;
        target.focus({ preventScroll: true });
      }
      // The editor is never destroyed. Notify its layout engine after the grid changes.
      window.requestAnimationFrame(function () { window.dispatchEvent(new Event("resize")); });
    }

    layout.classList.toggle("drawer-enhanced", true);
    closeButton.hidden = false;
    handle.addEventListener("click", function () { setOpen(true, true); });
    closeButton.addEventListener("click", function () { setOpen(false, true); });
    drawer.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !drawer.hidden) {
        event.preventDefault();
        setOpen(false, true);
      }
    });
    var open = true;
    try { open = window.sessionStorage.getItem(key) !== "closed"; } catch (error) { /* Default open without storage. */ }
    setOpen(open, false);
  }

  function initVersionRail() {
    var rail = document.querySelector(".version-rail");
    if (!rail) return;
    rail.addEventListener("click", function (event) {
      var toggle = event.target.closest("[data-rail-toggle]");
      if (!toggle) return;
      var body = document.getElementById(toggle.getAttribute("aria-controls"));
      if (!body) return;
      var card = toggle.closest("[data-rail-branch]");
      var expanded = toggle.getAttribute("aria-expanded") !== "true";
      body.hidden = !expanded;
      card.dataset.expanded = String(expanded);
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.setAttribute("aria-label", (expanded ? "收起分支 " : "展开分支 ") + card.querySelector("strong").textContent);
      toggle.textContent = expanded ? "−" : "＋";
      var head = card.querySelector("[data-rail-head]");
      if (head) head.hidden = expanded;
      // Local disclosure keeps the manuscript, uploaded file and keyboard focus intact.
      toggle.focus({ preventScroll: true });
    });

    var navigationKey = "padif.rail.navigation";
    rail.addEventListener("click", function (event) {
      var link = event.target.closest("a[data-rail-navigation]");
      if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.defaultPrevented) return;
      var target = new URL(link.href, window.location.href);
      if (target.origin !== window.location.origin || target.pathname !== window.location.pathname) return;
      if (target.search === window.location.search) {
        event.preventDefault();
        return;
      }
      try {
        window.sessionStorage.setItem(navigationKey, JSON.stringify({
          path: target.pathname, search: target.search, focus: link.dataset.railFocus,
          top: link.getBoundingClientRect().top, scrollY: window.scrollY, railScrollTop: rail.scrollTop,
          editorOpen: Boolean(document.querySelector(".editor-panel") && document.querySelector(".editor-panel").open)
        }));
      } catch (error) { /* Navigation remains usable when browser storage is disabled. */ }
    });

    try {
      var saved = JSON.parse(window.sessionStorage.getItem(navigationKey) || "null");
      window.sessionStorage.removeItem(navigationKey);
      if (saved && saved.path === window.location.pathname && saved.search === window.location.search && Number.isFinite(saved.top)) {
        var editorPanel = document.querySelector(".editor-panel");
        if (editorPanel && typeof saved.editorOpen === "boolean") editorPanel.open = saved.editorOpen;
        window.requestAnimationFrame(function () {
          var target = Array.prototype.find.call(rail.querySelectorAll("[data-rail-focus]"), function (element) {
            return element.dataset.railFocus === saved.focus;
          }) || rail.querySelector('[data-rail-focus="main"]');
          if (target) {
            if (Number.isFinite(saved.scrollY)) window.scrollTo({ top: saved.scrollY, behavior: "instant" });
            if (Number.isFinite(saved.railScrollTop)) rail.scrollTop = saved.railScrollTop;
            target.focus({ preventScroll: true });
            if (rail.scrollHeight > rail.clientHeight) {
              rail.scrollTop += target.getBoundingClientRect().top - saved.top;
            } else window.scrollTo({ top: Math.max(0, window.scrollY + target.getBoundingClientRect().top - saved.top), behavior: "instant" });
          } else if (Number.isFinite(saved.scrollY)) window.scrollTo(0, saved.scrollY);
        });
      }
    } catch (error) { /* Ignore unavailable storage or stale state. */ }

  }

  document.addEventListener("DOMContentLoaded", function () {
    initWorldlineDrawer();
    initVersionRail();
    document.querySelectorAll("[data-padif-dropzone]").forEach(initDropzone);
    document.querySelectorAll(".message-stack .notice").forEach(function (notice) {
      window.setTimeout(function () {
        notice.classList.add("is-dismissed");
        window.setTimeout(function () { notice.remove(); }, 240);
      }, 4200);
    });

    document.body.addEventListener("htmx:afterRequest", function (event) {
      if (!event.detail || !event.detail.elt || !event.detail.elt.closest(".diff-controls")) return;
      window.setTimeout(function () {
        var result = document.getElementById("diff-result");
        var modal = document.getElementById("padif-preview-modal");
        var content = document.getElementById("padif-preview-content");
        var toc = document.getElementById("padif-preview-toc-list");
        if (!result || !result.innerHTML.trim() || !modal || !content) return;
        modal.classList.add("is-diff-preview");
        content.innerHTML = result.innerHTML;
        if (toc) toc.innerHTML = '<li class="padif-preview-toc__item"><span>差异结果</span></li>';
        modal.hidden = false;
        document.body.classList.add("padif-preview-open");
      }, 0);
    });
  });
}());
