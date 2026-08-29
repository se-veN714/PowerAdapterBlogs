(() => {
    const drop = document.querySelector("[data-avatar-drop]");
    const input = drop?.querySelector('input[type="file"]');
    const preview = document.querySelector("[data-avatar-preview]");
    if (!drop || !input || !preview) return;

    const showFile = (file) => {
        if (!file || !file.type.startsWith("image/")) return;
        preview.src = URL.createObjectURL(file);
        drop.classList.add("has-file");
    };

    input.addEventListener("change", () => showFile(input.files?.[0]));
    ["dragenter", "dragover"].forEach((name) =>
        drop.addEventListener(name, (event) => {
            event.preventDefault();
            drop.classList.add("is-dragging");
        })
    );
    ["dragleave", "drop"].forEach((name) =>
        drop.addEventListener(name, (event) => {
            event.preventDefault();
            drop.classList.remove("is-dragging");
        })
    );
    drop.addEventListener("drop", (event) => {
        const file = event.dataTransfer?.files?.[0];
        if (!file) return;
        const transfer = new DataTransfer();
        transfer.items.add(file);
        input.files = transfer.files;
        showFile(file);
    });
})();
