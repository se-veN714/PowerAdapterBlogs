(() => {
    const button = document.querySelector("[data-dashboard-menu]");
    const sidebar = document.querySelector("#dashboard-sidebar");
    const overlay = document.querySelector("[data-dashboard-overlay]");
    if (!button || !sidebar || !overlay) return;

    const mobile = window.matchMedia("(max-width: 980px)");

    const setOpen = (open, { restoreFocus = false } = {}) => {
        const mobileOpen = mobile.matches && open;
        sidebar.classList.toggle("is-open", open);
        sidebar.toggleAttribute("inert", mobile.matches && !mobileOpen);
        sidebar.setAttribute("aria-hidden", String(mobile.matches && !mobileOpen));
        button.setAttribute("aria-expanded", String(mobileOpen));
        overlay.hidden = !mobileOpen;
        document.body.style.overflow = mobileOpen ? "hidden" : "";
        if (mobileOpen) {
            sidebar.querySelector("a")?.focus();
        } else if (restoreFocus) {
            button.focus();
        }
    };
    button.addEventListener("click", () => setOpen(button.getAttribute("aria-expanded") !== "true"));
    overlay.addEventListener("click", () => setOpen(false, { restoreFocus: true }));
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && button.getAttribute("aria-expanded") === "true") {
            setOpen(false, { restoreFocus: true });
        }
    });
    mobile.addEventListener("change", () => setOpen(false));
    setOpen(false);
})();
