window.ItemHoverManager = {
    timer: null,
    card: null,

    init() {
        this.card = document.getElementById("item-hover-card");
        document.addEventListener("scroll", () => this.hide(), true);
    },

    bind(element, item) {
        if (!element || !item) return;
        element.addEventListener("mouseenter", () => {
            clearTimeout(this.timer);
            this.timer = setTimeout(() => this.show(element, item), 350);
        });
        element.addEventListener("mouseleave", () => {
            clearTimeout(this.timer);
            this.timer = setTimeout(() => this.hide(), 120);
        });
    },

    show(element, item) {
        if (!this.card || !element) return;
        const image = item.image
            ? `<img src="${frappe.utils.escape_html(item.image)}" alt="${frappe.utils.escape_html(item.item_name || item.item_code || "")}">`
            : '<div class="hover-image-placeholder">💊</div>';
        this.card.innerHTML = `
            <div class="item-hover-image">${image}</div>
            <div class="item-hover-content">
                <strong>${frappe.utils.escape_html(item.item_name || item.item_code || item.name || "")}</strong>
                ${item.item_name_ar ? `<div class="item-hover-ar">${frappe.utils.escape_html(item.item_name_ar)}</div>` : ""}
                <small>${frappe.utils.escape_html(item.item_code || item.name || "")}</small>
                ${item.ingredient_summary ? `<div class="item-hover-ingredient">${frappe.utils.escape_html(item.ingredient_summary)}</div>` : ""}
                <div class="item-hover-stats">
                    <span>Stock: <b>${flt(item.actual_qty || 0, 2)}</b></span>
                    <span>Price: <b>${format_currency(item.customer_price || item.price_list_rate || item.rate || 0)}</b></span>
                </div>
            </div>`;
        const rect = element.getBoundingClientRect();
        this.card.classList.remove("is-hidden");
        const cardRect = this.card.getBoundingClientRect();
        let left = rect.right + 10;
        let top = rect.top;
        if (left + cardRect.width > window.innerWidth - 10) left = Math.max(10, rect.left - cardRect.width - 10);
        if (top + cardRect.height > window.innerHeight - 10) top = Math.max(10, window.innerHeight - cardRect.height - 10);
        this.card.style.left = `${left}px`;
        this.card.style.top = `${top}px`;
    },

    hide() {
        clearTimeout(this.timer);
        this.card?.classList.add("is-hidden");
    }
};
