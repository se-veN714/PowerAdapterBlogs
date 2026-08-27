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
        if (meta) {
            meta.textContent = message;
            meta.classList.toggle("is-error", Boolean(failed));
        }
        if (input) input.setCustomValidity(failed ? message : "");
    }

    function inspectFile() {
        var file = input && input.files && input.files[0];
        if (!file) {
            report("CLIENT PREFLIGHT READY · SERVER FFPROBE IS AUTHORITATIVE", false);
            return;
        }
        if (objectUrl) URL.revokeObjectURL(objectUrl);
        if (maxBytes && file.size > maxBytes) {
            report("REJECTED / 文件超过 " + Math.round(maxBytes / 1048576) + " MiB。", true);
            return;
        }
        objectUrl = URL.createObjectURL(file);
        if (preview) {
            preview.src = objectUrl;
            preview.hidden = false;
        }
        if (idle) idle.hidden = true;
        report("READING / " + file.name + " · " + (file.size / 1048576).toFixed(1) + " MiB", false);
        if (!preview) return;
        preview.onloadedmetadata = function () {
            var durationMs = preview.duration * 1000;
            var orientation = preview.videoHeight > preview.videoWidth ? "PORTRAIT 9:16" : "LANDSCAPE 16:9";
            if (maxDurationMs && durationMs > maxDurationMs + 250) {
                report("REJECTED / 视频超过 " + maxDurationMs / 1000 + " 秒。", true);
                return;
            }
            report(
                "PREFLIGHT OK / " + file.name + " · " + preview.videoWidth + "×" +
                preview.videoHeight + " · " + orientation + " · " + preview.duration.toFixed(2) + " SEC",
                false
            );
        };
        preview.onerror = function () {
            report("BROWSER PROBE UNAVAILABLE / 将由服务端 FFprobe 权威校验。", false);
        };
    }

    function receiveDrop(event) {
        event.preventDefault();
        if (drop) drop.classList.remove("is-dragging");
        var file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
        if (!file || !input) return;
        try {
            var transfer = new DataTransfer();
            transfer.items.add(file);
            input.files = transfer.files;
            inspectFile();
        } catch (error) {
            report("DROP UNSUPPORTED / 请点击区域选择文件。", true);
        }
    }

    if (input && window.URL && window.URL.createObjectURL) input.addEventListener("change", inspectFile);
    if (drop) {
        ["dragenter", "dragover"].forEach(function (name) {
            drop.addEventListener(name, function (event) {
                event.preventDefault();
                drop.classList.add("is-dragging");
            });
        });
        drop.addEventListener("dragleave", function () { drop.classList.remove("is-dragging"); });
        drop.addEventListener("drop", receiveDrop);
    }
    window.addEventListener("pagehide", function () { if (objectUrl) URL.revokeObjectURL(objectUrl); });

    var spot = document.getElementById("id_spot");
    var address = document.getElementById("id_spot_address");
    var longitude = document.getElementById("id_spot_longitude");
    var latitude = document.getElementById("id_spot_latitude");
    var mapNode = form.querySelector("[data-amap-map]");
    var mapStatus = form.querySelector("[data-amap-status]");
    var mapResult = form.querySelector("[data-amap-result]");

    function setMapStatus(message, failed) {
        if (mapStatus) {
            mapStatus.textContent = message;
            mapStatus.classList.toggle("is-error", Boolean(failed));
        }
    }

    function cleanAmapText(value) {
        if (value === null || value === undefined) return "";
        var parsed = new DOMParser().parseFromString(String(value), "text/html");
        return (parsed.body.textContent || "").replace(/\s+/g, " ").trim();
    }

    if (form.dataset.amapEnabled !== "true" || !form.dataset.amapKey || !spot || !mapNode) {
        setMapStatus("地图服务未启用，地点仍可手动填写。", false);
        return;
    }

    var serviceHost = form.dataset.amapServiceHost || "/_AMapService";
    try {
        serviceHost = new URL(serviceHost, window.location.origin).toString().replace(/\/$/, "");
    } catch (error) {
        serviceHost = window.location.origin + "/_AMapService";
    }
    window._AMapSecurityConfig = { serviceHost: serviceHost };

    var script = document.createElement("script");
    script.src = "https://webapi.amap.com/maps?v=2.0&key=" + encodeURIComponent(form.dataset.amapKey);
    script.async = true;
    script.onload = function () {
        AMap.plugin(
            ["AMap.AutoComplete", "AMap.PlaceSearch", "AMap.Geocoder", "AMap.ToolBar", "AMap.Scale"],
            function () {
                mapNode.replaceChildren();
                var map = new AMap.Map(mapNode, {
                    zoom: 11,
                    viewMode: "2D",
                    mapStyle: "amap://styles/dark",
                    resizeEnable: true,
                    dragEnable: true,
                    zoomEnable: true,
                    keyboardEnable: true,
                    doubleClickZoom: true
                });
                mapNode.classList.add("is-ready");
                map.addControl(new AMap.ToolBar({ position: "RB" }));
                map.addControl(new AMap.Scale());
                var marker = null;
                var geocoder = new AMap.Geocoder();
                var autoOptions = {
                    input: spot.id
                };
                var autocomplete = new AMap.AutoComplete(autoOptions);
                var placeSearch = new AMap.PlaceSearch({
                    map: map
                });

                function persistPoint(point, name, formattedAddress) {
                    var lng = Number(point.lng !== undefined ? point.lng : point[0]);
                    var lat = Number(point.lat !== undefined ? point.lat : point[1]);
                    longitude.value = lng.toFixed(6);
                    latitude.value = lat.toFixed(6);
                    if (name) spot.value = name;
                    if (formattedAddress !== undefined) address.value = formattedAddress;
                    if (mapResult) {
                        mapResult.textContent = (spot.value || "SELECTED POINT") + " / " +
                            (address.value || "地址待反向解析") + " / " + longitude.value + ", " + latitude.value;
                    }
                    setMapStatus("定位已记录；可拖动标记或点击地图继续微调。", false);
                }

                function reverseAddress(point) {
                    geocoder.getAddress(point, function (status, result) {
                        if (status === "complete" && result.regeocode) {
                            address.value = result.regeocode.formattedAddress || address.value;
                            persistPoint(point, spot.value, address.value);
                        }
                    });
                }

                function mark(point, options) {
                    options = options || {};
                    if (!marker) {
                        marker = new AMap.Marker({ position: point, draggable: true, cursor: "move" });
                        marker.on("dragend", function (event) {
                            persistPoint(event.lnglat, spot.value, "");
                            reverseAddress(event.lnglat);
                        });
                        map.add(marker);
                    } else {
                        marker.setPosition(point);
                    }
                    if (options.center !== false) map.setZoomAndCenter(16, point);
                    persistPoint(point, options.name || spot.value, options.address);
                    if (options.reverse) reverseAddress(point);
                }

                function usePoi(poi) {
                    if (!poi || !poi.location) return false;
                    var poiName = cleanAmapText(poi.name) || spot.value;
                    var poiAddress = [cleanAmapText(poi.district), cleanAmapText(poi.address)]
                        .filter(Boolean)
                        .join(" ");
                    mark(poi.location, { name: poiName, address: poiAddress });
                    return true;
                }

                function select(event) {
                    var poi = event.poi || {};
                    var keyword = cleanAmapText(poi.name) || spot.value.trim();
                    spot.value = keyword;
                    placeSearch.setCity(poi.adcode);
                    setMapStatus("SEARCHING / 正在查询地点…", false);
                    placeSearch.search(keyword, function (status, result) {
                        var pois = status === "complete" && result.poiList && result.poiList.pois;
                        if (!pois || !pois.length) {
                            setMapStatus("未找到可定位的地点，请换一个关键词或直接点击地图。", true);
                            return;
                        }
                        var selected = poi.location ? poi : pois[0];
                        usePoi(selected);
                        setMapStatus(
                            "找到 " + pois.length + " 个相关地点；已记录所选地点，可拖动红色标记微调。",
                            false
                        );
                    });
                }

                // 候选面板观察：inputtips 为异步请求，插件无请求回调。
                // - loading 态：输入时显示 spinner，面板渲染出条目（或超时兜底）后隐藏。
                // - 官方行为对齐：候选不因地图滚轮缩放/点击/失焦被插件收起——面板一旦被
                //   隐藏，只要关键词未清空且未处于"明确隐藏"状态即强制恢复可见。
                //   仅三种情况允许保持隐藏：清空关键词、选中候选、按 Esc。
                var searchPanel = form.querySelector("[data-amap-search-panel]");
                var restoreArmed = false;
                var tipsTimer = 0;

                function setSearching(searching) {
                    if (searchPanel) searchPanel.classList.toggle("is-searching", searching);
                    if (tipsTimer) {
                        window.clearTimeout(tipsTimer);
                        tipsTimer = 0;
                    }
                    if (searching) {
                        tipsTimer = window.setTimeout(function () { setSearching(false); }, 3000);
                    }
                }

                function watchSugPanel(panel) {
                    new MutationObserver(function () {
                        if (getComputedStyle(panel).visibility === "hidden") {
                            if (restoreArmed && spot.value.trim()) {
                                panel.style.visibility = "visible";
                                return;
                            }
                            setSearching(false);
                            return;
                        }
                        if (panel.children.length) setSearching(false);
                    }).observe(panel, {
                        childList: true,
                        subtree: true,
                        attributes: true,
                        attributeFilter: ["style", "class"]
                    });
                }

                autocomplete.on("select", function (event) {
                    // 选中候选属于明确意图：允许插件隐藏面板，不再恢复。
                    restoreArmed = false;
                    select(event);
                });

                if (typeof MutationObserver !== "undefined") {
                    var sugPanel = document.querySelector(".amap-sug-result");
                    if (sugPanel) {
                        watchSugPanel(sugPanel);
                    } else {
                        var sugAppeared = new MutationObserver(function () {
                            var panel = document.querySelector(".amap-sug-result");
                            if (panel) {
                                sugAppeared.disconnect();
                                watchSugPanel(panel);
                            }
                        });
                        sugAppeared.observe(document.body, { childList: true, subtree: true });
                    }
                }

                spot.addEventListener("input", function () {
                    restoreArmed = Boolean(spot.value.trim());
                    setSearching(restoreArmed);
                    // 用户直接改写关键词时，旧地点与旧坐标不再描述当前输入。
                    // 只有重新选择候选、点击地图或拖动 Marker 才会再次持久化。
                    address.value = "";
                    longitude.value = "";
                    latitude.value = "";
                    if (mapResult) mapResult.textContent = "NO GEO SIGNAL";
                    if (marker) {
                        map.remove(marker);
                        marker = null;
                    }
                });
                spot.addEventListener("blur", function () {
                    window.setTimeout(function () { setSearching(false); }, 150);
                });

                map.on("click", function (event) {
                    mark(event.lnglat, {
                        name: spot.value,
                        address: "",
                        reverse: true,
                        center: false
                    });
                });
                spot.addEventListener("keydown", function (event) {
                    if (event.key === "Enter") event.preventDefault();
                    // Esc 主动收起候选（IME 组合输入中的 Esc 取消候选字，不处理）。
                    if (event.key === "Escape" && !event.isComposing) {
                        var panel = document.querySelector(".amap-sug-result");
                        if (panel && getComputedStyle(panel).visibility !== "hidden") {
                            restoreArmed = false;
                            panel.style.visibility = "hidden";
                        }
                    }
                });

                if (longitude.value && latitude.value) {
                    mark([longitude.value, latitude.value], { name: spot.value, address: address.value });
                } else {
                    setMapStatus("地图已就绪：搜索地点，或点击地图选点。", false);
                }

            }
        );
    };
    script.onerror = function () {
        setMapStatus("地图加载失败，已降级为手动地点输入。", true);
    };
    document.head.appendChild(script);
})();
