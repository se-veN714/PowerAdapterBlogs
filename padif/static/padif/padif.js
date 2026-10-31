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

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-padif-dropzone]").forEach(initDropzone);
  });
}());
