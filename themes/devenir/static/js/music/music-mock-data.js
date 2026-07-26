/* Music 页面 v2 Mock 数据（双栏版本 Phase 1 静态原型）。
   仅作为前端数据容器占位；核心内容已在模板中静态预渲染。 */
window.MUSIC_PAGE_DATA = {
    version: "v2",
    concept: "boards-music-sa.png",
    currentPeriod: {
        month: "2026.07",
        theme: "RETURN TO LONG-FORM LISTENING",
        artists: ["World's End Girlfriend", "TE'", "About Tess", "Roughsketch"]
    },
    yearly: {
        year: 2025,
        minutes: 32481,
        coreArtists: ["World's End Girlfriend", "TE'", "About Tess", "Roughsketch", "Haiku Salut"],
        tags: ["LONG FORM", "HIGH REPEAT", "POST-ROCK"]
    },
    monthly: {
        currentMonth: "2026.07",
        minutes: 22476,
        months: [
            { label: "JAN", minutes: 18412 },
            { label: "FEB", minutes: 15291 },
            { label: "MAR", minutes: 17850 },
            { label: "APR", minutes: 20114 },
            { label: "MAY", minutes: 19387 },
            { label: "JUN", minutes: 15220 },
            { label: "JUL", minutes: 22476 }
        ]
    },
    archives: {
        yearly: [2025, 2024, 2023],
        monthly: ["2026.07", "2026.06", "2026.05"]
    }
};
