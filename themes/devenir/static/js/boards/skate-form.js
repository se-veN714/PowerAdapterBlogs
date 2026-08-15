(function () {
    "use strict";
    var form = document.querySelector("[data-skate-form]");
    if (!form) return;

    var input = form.querySelector("input[type=file]");
    var drop = form.querySelector("[data-skate-drop]");
    var idle = form.querySelector("[data-skate-drop-idle]");
    var preview = form.querySelector("[data-skate-local-preview]");
    var meta = form.querySelector("[data-skate-file-meta]");
    var objectUrl = "";
    var maxBytes = Number(form.dataset.skateMaxBytes || 0);
    var maxDurationMs = Number(form.dataset.skateMaxDurationMs || 0);

    function report(message, failed) {
        if (meta) meta.textContent = message;
        if (meta) meta.classList.toggle("is-error", !!failed);
        if (input) input.setCustomValidity(failed ? message : "");
    }
    function inspectFile() {
        var file = input && input.files && input.files[0];
        if (!file) return;
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        if (file.size > maxBytes) {
            report("REJECTED / 文件超过 " + Math.round(maxBytes / 1048576) + " MiB。", true);
            return;
        }
        objectUrl = URL.createObjectURL(file);
        preview.src = objectUrl;
        preview.hidden = false;
        idle.hidden = true;
        report("READING / " + file.name + " · " + (file.size / 1048576).toFixed(1) + " MiB", false);
        preview.onloadedmetadata = function () {
            var durationMs = preview.duration * 1000;
            var orientation = preview.videoHeight > preview.videoWidth ? "PORTRAIT 9:16" : "LANDSCAPE 16:9";
            if (durationMs > maxDurationMs + 250) {
                report("REJECTED / 视频超过 " + maxDurationMs / 1000 + " 秒。", true);
                return;
            }
            report("PREFLIGHT OK / " + file.name + " · " + preview.videoWidth + "×" + preview.videoHeight + " · " + orientation + " · " + preview.duration.toFixed(2) + " SEC", false);
        };
        preview.onerror = function () {
            report("BROWSER PROBE UNAVAILABLE / 将由服务端 FFprobe 权威校验。", false);
        };
    }
    if (input && window.URL) input.addEventListener("change", inspectFile);
    ["dragenter", "dragover"].forEach(function (name) { drop.addEventListener(name, function () { drop.classList.add("is-dragging"); }); });
    ["dragleave", "drop"].forEach(function (name) { drop.addEventListener(name, function () { drop.classList.remove("is-dragging"); }); });
    window.addEventListener("pagehide", function () { if (objectUrl) URL.revokeObjectURL(objectUrl); });

    var spot = document.getElementById("id_spot");
    var address = document.getElementById("id_spot_address");
    var longitude = document.getElementById("id_spot_longitude");
    var latitude = document.getElementById("id_spot_latitude");
    var mapNode = form.querySelector("[data-amap-map]");
    var mapStatus = form.querySelector("[data-amap-status]");
    if (form.dataset.amapEnabled !== "true" || !form.dataset.amapKey || !spot || !mapNode) {
        if (mapStatus) mapStatus.textContent = "地图服务未启用，地点仍可手动填写。";
        return;
    }

    window._AMapSecurityConfig = { serviceHost: form.dataset.amapServiceHost || "/_AMapService" };
    var script = document.createElement("script");
    script.src = "https://webapi.amap.com/maps?v=2.0&key=" + encodeURIComponent(form.dataset.amapKey) + "&plugin=AMap.AutoComplete";
    script.async = true;
    script.onload = function () {
        var map = new AMap.Map(mapNode, { zoom: 11, viewMode: "2D", mapStyle: "amap://styles/dark" });
        var marker = null;
        function mark(lng, lat) {
            var point = [Number(lng), Number(lat)];
            if (!marker) marker = new AMap.Marker({ position: point }); else marker.setPosition(point);
            map.add(marker); map.setZoomAndCenter(15, point);
        }
        if (longitude.value && latitude.value) mark(longitude.value, latitude.value);
        var autocomplete = new AMap.AutoComplete({ input: spot.id });
        autocomplete.on("select", function (event) {
            var poi = event.poi || {};
            if (!poi.location) return;
            spot.value = poi.name || spot.value;
            address.value = [poi.district, poi.address].filter(Boolean).join(" ");
            longitude.value = Number(poi.location.lng).toFixed(6);
            latitude.value = Number(poi.location.lat).toFixed(6);
            mark(longitude.value, latitude.value);
            if (mapStatus) mapStatus.textContent = address.value || "地点坐标已记录。";
        });
        if (mapStatus) mapStatus.textContent = "高德地点候选已就绪；选择候选后会保存坐标。";
    };
    script.onerror = function () {
        if (mapStatus) mapStatus.textContent = "地图加载失败，已降级为手动地点输入。";
    };
    document.head.appendChild(script);
})();
