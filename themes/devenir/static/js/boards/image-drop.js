(function () {
    "use strict";

    var allowedTypes = ["image/jpeg", "image/png", "image/gif", "image/webp"];

    document.querySelectorAll("[data-board-image-drop]").forEach(function (drop) {
        var input = drop.querySelector("[data-board-image-input]");
        var preview = drop.querySelector("[data-board-image-preview]");
        var idle = drop.querySelector("[data-board-image-idle]");
        var meta = drop.querySelector("[data-board-image-meta]");
        var objectUrl = "";

        if (!input) return;

        function report(message, failed) {
            if (meta) {
                meta.textContent = message;
                meta.classList.toggle("is-error", Boolean(failed));
            }
            input.setCustomValidity(failed ? message : "");
        }

        function inspectFile() {
            var file = input.files && input.files[0];
            if (!file) return;
            var maxBytes = Number(input.dataset.boardImageMaxBytes || 0);
            if (maxBytes && file.size > maxBytes) {
                report("REJECTED / 图片超过 " + Math.round(maxBytes / 1048576) + " MiB。", true);
                return;
            }
            if (file.type && allowedTypes.indexOf(file.type.toLowerCase()) === -1) {
                report("REJECTED / 仅支持 JPEG、PNG、GIF 或 WEBP。", true);
                return;
            }
            if (objectUrl) URL.revokeObjectURL(objectUrl);
            objectUrl = URL.createObjectURL(file);
            if (preview) {
                preview.src = objectUrl;
                preview.hidden = false;
                preview.onload = function () {
                    report(
                        "PREVIEW OK / " + file.name + " · " + preview.naturalWidth + "×" +
                        preview.naturalHeight + " · " + (file.size / 1048576).toFixed(2) + " MiB",
                        false
                    );
                };
                preview.onerror = function () {
                    report("BROWSER PREVIEW UNAVAILABLE / 将由服务端校验图片。", false);
                };
            }
            if (idle) idle.hidden = true;
            report("READING / " + file.name, false);
        }

        function receiveDrop(event) {
            event.preventDefault();
            drop.classList.remove("is-dragging");
            var file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
            if (!file) return;
            try {
                var transfer = new DataTransfer();
                transfer.items.add(file);
                input.files = transfer.files;
                inspectFile();
            } catch (error) {
                report("DROP UNSUPPORTED / 请点击区域选择图片。", true);
            }
        }

        input.addEventListener("change", inspectFile);
        ["dragenter", "dragover"].forEach(function (name) {
            drop.addEventListener(name, function (event) {
                event.preventDefault();
                drop.classList.add("is-dragging");
            });
        });
        drop.addEventListener("dragleave", function () {
            drop.classList.remove("is-dragging");
        });
        drop.addEventListener("drop", receiveDrop);
        window.addEventListener("pagehide", function () {
            if (objectUrl) URL.revokeObjectURL(objectUrl);
        });
    });
}());
