(function () {
    "use strict";

    function setValue(form, name, value) {
        var field = form.querySelector("[name='" + name + "']");
        if (!field || value === undefined) return;
        field.value = value;
        field.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function report(form, message) {
        var status = form.querySelector("[data-preset-status]");
        if (!status) return;
        status.textContent = message;
        status.classList.add("is-applied");
    }

    function periodTitle(form) {
        var provider = form.dataset.musicProvider === "apple" ? "Apple Music" : "Spotify Wrapped";
        var year = form.querySelector("[name='year']");
        var month = form.querySelector("[name='month']");
        var scope = form.querySelector("[name='scope']");
        if (!year || !year.value) return "";
        if (scope && scope.value === "monthly" && month && month.value) {
            return provider + " " + year.value + "." + String(month.value).padStart(2, "0");
        }
        return provider + " " + year.value;
    }

    var musicForm = document.querySelector("[data-music-record-form]");
    if (musicForm) {
        var musicPresets = {
            total: { kind: "total", label: "TOTAL MINUTES", unit: "MIN", display_order: 0 },
            top_artist: { kind: "top_artist", label: "", unit: "MIN", rank: 1, display_order: 1 },
            top_track: { kind: "top_track", label: "", unit: "", rank: 1, display_order: 1 },
            tag: { kind: "tag", label: "", value: "", unit: "", display_order: 1 },
            unique_artists: { scope: "yearly", month: "", kind: "unique_artists", label: "UNIQUE ARTISTS", unit: "", display_order: 90 },
            unique_tracks: { scope: "yearly", month: "", kind: "unique_tracks", label: "UNIQUE TRACKS", unit: "", display_order: 91 },
            core_artist: { scope: "yearly", month: "", kind: "core_artist", label: "", rank: 1, display_order: 1 },
            cross_scale: { scope: "yearly", month: "", kind: "cross_scale", label: "", display_order: 1 },
            companion: { scope: "yearly", month: "", kind: "companion", label: "", display_order: 10 },
            period_artist: { scope: "monthly", kind: "period_artist", label: "", rank: 1, display_order: 1 },
            gravity: { scope: "monthly", kind: "gravity", label: "", display_order: 10 }
        };
        var musicSelect = musicForm.querySelector("[data-music-preset]");
        musicSelect.addEventListener("change", function () {
            var preset = musicPresets[musicSelect.value];
            if (!preset) return;
            Object.keys(preset).forEach(function (name) {
                setValue(musicForm, name, preset[name]);
            });
            var title = musicForm.querySelector("[name='title']");
            if (title && !title.value.trim()) title.value = periodTitle(musicForm);
            report(musicForm, "PRESET APPLIED / 已填写建议值，请确认标题、内容与排名。");
        });
    }

    var codingForm = document.querySelector("[data-coding-project-form]");
    if (codingForm) {
        var codingPresets = {
            django_htmx: {
                project_type: "github",
                stack: "Python / Django / HTMX",
                status: "active"
            },
            local_browser: {
                project_type: "local_tool",
                stack: "HTML / CSS / JavaScript / LocalStorage",
                status: "active"
            },
            external: { project_type: "external", status: "active" },
            archived_github: { project_type: "github", status: "archived" }
        };
        var codingSelect = codingForm.querySelector("[data-coding-preset]");
        codingSelect.addEventListener("change", function () {
            var preset = codingPresets[codingSelect.value];
            if (!preset) return;
            Object.keys(preset).forEach(function (name) {
                setValue(codingForm, name, preset[name]);
            });
            report(codingForm, "PRESET APPLIED / 已填写项目类型、技术栈与状态，请继续完善内容。");
        });
    }

    var skateForm = document.querySelector("[data-skate-form]");
    if (skateForm) {
        var skatePresets = {
            landed_clip: {
                clip_format: "clip",
                category: "rotation",
                status: "landed",
                hud_type: "arc",
                hud_label: "ROTATION",
                is_public: true
            },
            unfinished_clip: {
                clip_format: "clip",
                category: "rotation",
                status: "unfinished",
                hud_type: "arc",
                hud_label: "ROTATION",
                is_public: false
            },
            line: {
                clip_format: "line",
                category: "displacement",
                status: "wip",
                hud_type: "speed",
                hud_label: "LINE",
                is_public: false
            },
            b_roll: {
                clip_format: "b_roll",
                category: "",
                status: "landed",
                hud_type: "measure",
                hud_label: "SPOT",
                is_public: true
            }
        };
        var skateSelect = skateForm.querySelector("[data-skate-preset]");
        skateSelect.addEventListener("change", function () {
            var preset = skatePresets[skateSelect.value];
            if (!preset) return;
            Object.keys(preset).forEach(function (name) {
                var field = skateForm.querySelector("[name='" + name + "']");
                if (field && field.type === "checkbox") {
                    field.checked = preset[name];
                    field.dispatchEvent(new Event("change", { bubbles: true }));
                    return;
                }
                setValue(skateForm, name, preset[name]);
            });
            report(skateForm, "PRESET APPLIED / 已填写展示建议值，请继续确认动作与地点信息。");
        });
    }
}());
