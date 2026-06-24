window.SearchManager = {
    input: null,
    resultBox: null,
    timer: null,
    rows: [],
    activeIndex: -1,

    init() {
        this.input = document.getElementById("item-search");
        this.resultBox = document.getElementById("search-results");
        if (!this.input || this.input.dataset.initialized === "1") return;
        this.input.dataset.initialized = "1";
        this.bindEvents();
    },

    bindEvents() {
        this.input.addEventListener("keydown", event => {
            if (event.key === "ArrowDown") { event.preventDefault(); this.move(1); return; }
            if (event.key === "ArrowUp") { event.preventDefault(); this.move(-1); return; }
            if (event.key === "Enter") { event.preventDefault(); this.selectActive(); return; }
            if (event.key === "Escape") this.clearResults();
        });
        this.input.addEventListener("input", () => {
            clearTimeout(this.timer);
            this.timer = setTimeout(() => this.search(this.input.value), 250);
        });
    },

    async search(keyword) {
        keyword = (keyword || "").trim();
        if (!keyword) { this.clearResults(); return; }
        try {
            const warehouse = PharmacyPOS.state.settings.default_warehouse || "";
            const rows = await PharmacyAPI.searchItems(keyword, warehouse) || [];
            const feeItem = PharmacyPOS.state.settings.delivery_fee_item || "";
            this.rows = rows.filter(row => (row.item_code || row.name) !== feeItem);
            this.activeIndex = this.rows.length ? 0 : -1;
            this.render();
        } catch (error) { console.error(error); }
    },

    render() {
        if (!this.rows.length) {
            this.resultBox.innerHTML = '<div class="search-empty">No items found</div>';
            return;
        }

        this.resultBox.innerHTML = this.rows.map((item, index) => {
            const title = item.item_name || item.item_code;
            const subtitle = item.item_name_ar || item.ingredient_summary || item.item_code || item.name;
            const image = item.image ? `<img src="${frappe.utils.escape_html(item.image)}" alt="">` : '<span class="search-image-placeholder">💊</span>';
            return `<button type="button" class="search-item item-hover-target ${index === this.activeIndex ? "is-active" : ""}" data-index="${index}">
                <div class="search-item-image">${image}</div>
                <div class="search-item-text">
                    <strong>${frappe.utils.escape_html(title)}</strong>
                    <small>${frappe.utils.escape_html(subtitle)}</small>
                    ${item.ingredient_summary && item.item_name_ar ? `<small class="ingredient-line">${frappe.utils.escape_html(item.ingredient_summary)}</small>` : ""}
                </div>
                <div class="search-item-meta">
                    <span>Stock: ${flt(item.actual_qty || 0, 2)}</span>
                    <span>${format_currency(item.customer_price || 0)}</span>
                </div>
            </button>`;
        }).join("");

        this.resultBox.querySelectorAll("[data-index]").forEach(button => {
            const index = cint(button.dataset.index);
            button.addEventListener("click", () => { this.activeIndex = index; this.selectActive(); });
            ItemHoverManager.bind(button, this.rows[index]);
        });
    },

    move(direction) {
        if (!this.rows.length) return;
        this.activeIndex = (this.activeIndex + direction + this.rows.length) % this.rows.length;
        this.render();
        this.resultBox.querySelector(".is-active")?.scrollIntoView({ block: "nearest" });
    },

    async selectActive() {
        if (this.activeIndex < 0 || !this.rows[this.activeIndex]) return;
        const item = this.rows[this.activeIndex];
        await InvoiceManager.addItem(item.item_code || item.name);
        this.clear();
    },

    clearResults() {
        this.rows = [];
        this.activeIndex = -1;
        this.resultBox.innerHTML = "";
        ItemHoverManager.hide();
    },

    clear() {
        this.input.value = "";
        this.clearResults();
        this.input.focus();
    }
};
