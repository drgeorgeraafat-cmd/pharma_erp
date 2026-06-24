window.ScreenManager = {
    init() {
        this.button = document.getElementById("btn-fullscreen");
        document.body.classList.add("pharmacy-pos-page-active");
        document.getElementById("pharmacy-pos")?.closest(".page-container")?.classList.add("pharmacy-pos-page-container");
        this.button?.addEventListener("click", () => this.toggle());
        document.addEventListener("fullscreenchange", () => this.sync());
        this.sync();
    },

    async toggle() {
        try {
            if (!document.fullscreenElement) {
                await document.documentElement.requestFullscreen();
            } else {
                await document.exitFullscreen();
            }
        } catch (error) {
            console.error(error);
            frappe.show_alert({ message: __("Fullscreen is not available in this browser."), indicator: "orange" });
        }
    },

    sync() {
        const active = Boolean(document.fullscreenElement);
        PharmacyPOS.state.fullscreen = active;
        document.body.classList.toggle("pharmacy-pos-fullscreen", active);
        if (this.button) this.button.textContent = active ? "⛶ Exit Full Screen" : "⛶ Full Screen";
    }
};
