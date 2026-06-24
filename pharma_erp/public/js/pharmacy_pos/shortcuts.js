window.ShortcutManager = {
    initialized: false,

    init() {
        if (this.initialized) return;
        this.initialized = true;
        document.addEventListener("keydown", event => {
            if (event.key === "Escape") {
                document.querySelectorAll(".modal.show .btn-modal-close, .modal.show .close").forEach(button => button.click());
                ItemInfoManager?.close?.();
                return;
            }
            if (event.key === "F2") { event.preventDefault(); document.getElementById("item-search")?.focus(); }
            if (event.key === "F3") {
                event.preventDefault();
                (PharmacyPOS.state.orderType === "Corporate" ? document.getElementById("beneficiary-search") : document.getElementById("customer-name"))?.focus();
            }
            if (event.key === "F4") { event.preventDefault(); PaymentManager.open(); }
            if (event.key === "F5") { event.preventDefault(); HistoryManager.open(); }
            if (event.key === "F7") { event.preventDefault(); InvoiceManager.save(false, { hold: true, clearAfter: true }); }
            if (event.key === "F8") { event.preventDefault(); HoldManager.openRecall(); }
            if (event.key === "F10") { event.preventDefault(); ReturnsManager.open(); }
            if (event.key === "F12") { event.preventDefault(); InvoiceManager.save(true); }
            if (event.shiftKey && event.key.toLowerCase() === "n") { event.preventDefault(); InvoiceManager.clearInvoice(true); }
        });
    }
};
