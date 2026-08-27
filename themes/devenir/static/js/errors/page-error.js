(() => {
    "use strict";

    const page = document.querySelector(".error-page");
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

    if (!page || reducedMotion.matches) {
        return;
    }

    const scheduleGlitch = () => {
        const quietDelay = 4200 + Math.random() * 5200;

        window.setTimeout(() => {
            page.classList.add("is-glitching");

            window.setTimeout(() => {
                page.classList.remove("is-glitching");
                scheduleGlitch();
            }, 60 + Math.random() * 80);
        }, quietDelay);
    };

    scheduleGlitch();
})();
