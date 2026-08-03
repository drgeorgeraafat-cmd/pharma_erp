(() => {
    "use strict";

    const VERSION = "4B";
    const LIVE_REFRESH_SECONDS = 45;
    window.__pharmaCustomerOrdersVersion = VERSION;

    const safeParse = (value, fallback = {}) => {
        try {
            return JSON.parse(value);
        } catch (_error) {
            return fallback;
        }
    };

    const createElement = (tag, className, text) => {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined && text !== null) element.textContent = text;
        return element;
    };

    const serverMessage = (payload, fallback) => {
        const messages = safeParse(payload?._server_messages, []);
        if (Array.isArray(messages) && messages.length) {
            const first = safeParse(messages[0], {});
            return first.message || messages[0] || fallback;
        }
        return payload?.message || fallback;
    };

    const apiRequest = async (endpoint) => {
        const response = await fetch(endpoint, {
            credentials: "same-origin",
            cache: "no-store",
            headers: { Accept: "application/json" },
        });
        const text = await response.text();
        const payload = safeParse(text, {});
        if (!response.ok) {
            const error = new Error(serverMessage(payload, `HTTP ${response.status}`));
            error.status = response.status;
            throw error;
        }
        return payload.message || {};
    };

    const dateLabel = (value) => {
        if (!value) return "";
        const parsed = new Date(String(value).replace(" ", "T"));
        if (Number.isNaN(parsed.getTime())) return String(value);
        return new Intl.DateTimeFormat("ar-EG", {
            year: "numeric",
            month: "short",
            day: "numeric",
            hour: "numeric",
            minute: "2-digit",
        }).format(parsed);
    };

    const orderCard = (order) => {
        const card = createElement("article", "pharma-account__order-card");
        const top = createElement("div", "pharma-account__order-top");
        const identity = createElement("div");
        identity.appendChild(createElement("strong", "pharma-account__order-number", order.online_order));
        identity.appendChild(createElement("span", "pharma-account__muted", dateLabel(order.placed_at)));
        top.appendChild(identity);
        top.appendChild(createElement(
            "span",
            `pharma-account__status pharma-account__status--${order.status_key || "review"}`,
            order.status_label_ar || "قيد المراجعة"
        ));
        card.appendChild(top);

        const details = createElement("div", "pharma-account__order-details");
        [
            ["طريقة الاستلام", order.fulfilment_label_ar],
            ["حالة الدفع", order.payment_status_label_ar],
            ["عدد الأصناف", String(order.item_count || 0)],
            ["الإجمالي", order.grand_total_formatted],
        ].forEach(([label, value]) => {
            const row = createElement("div");
            row.append(createElement("span", "", label), createElement("strong", "", value || "—"));
            details.appendChild(row);
        });
        card.appendChild(details);

        const actions = createElement("div", "pharma-account__card-actions");
        if (order.tracking_url) {
            const track = createElement("a", "pharma-account__button pharma-account__button--primary", "تتبع الطلب");
            track.href = order.tracking_url;
            actions.appendChild(track);
        }
        const shop = createElement("a", "pharma-account__button pharma-account__button--link", "تسوق مرة أخرى");
        shop.href = "/pharmacy-shop/";
        actions.appendChild(shop);
        card.appendChild(actions);
        return card;
    };

    document.addEventListener("DOMContentLoaded", () => {
        const root = document.getElementById("pharma-customer-orders");
        if (!root || root.dataset.isGuest === "1") return;

        const loading = document.getElementById("pharma-orders-loading");
        const errorBox = document.getElementById("pharma-orders-error");
        const unlinked = document.getElementById("pharma-orders-unlinked");
        const content = document.getElementById("pharma-orders-content");
        const list = document.getElementById("pharma-orders-list");
        const emptyBox = document.getElementById("pharma-orders-empty");
        const loadMore = document.getElementById("pharma-orders-load-more");
        let nextStart = 0;

        const showError = (message) => {
            loading.hidden = true;
            errorBox.textContent = message;
            errorBox.hidden = false;
        };

        const render = (result, append = false) => {
            loading.hidden = true;
            errorBox.hidden = true;
            if (!result.customer_linked) {
                content.hidden = true;
                unlinked.hidden = false;
                return;
            }

            unlinked.hidden = true;
            content.hidden = false;
            const orders = result.orders || [];
            if (!append) list.replaceChildren();
            orders.forEach((order) => list.appendChild(orderCard(order)));
            emptyBox.hidden = list.children.length > 0;
            nextStart = Number(result.next_start || 0);
            loadMore.hidden = !result.has_more;
        };

        const loadOrders = async (start = 0, append = false) => {
            if (!append) loading.hidden = false;
            const query = new URLSearchParams({ start: String(start), page_length: "20" });
            try {
                const result = await apiRequest(`${root.dataset.accountEndpoint}?${query.toString()}`);
                render(result, append);
            } catch (error) {
                if (error.status === 401 || error.status === 403) {
                    window.location.assign("/login?redirect-to=%2Fpharmacy-orders%2F");
                    return;
                }
                showError(error.message || "تعذر تحميل طلباتك.");
            }
        };

        loadMore.addEventListener("click", async () => {
            loadMore.disabled = true;
            try {
                await loadOrders(nextStart, true);
            } finally {
                loadMore.disabled = false;
            }
        });

        loadOrders();

        const liveTimer = window.setInterval(() => {
            if (!document.hidden && !loadMore.disabled) loadOrders(0, false);
        }, LIVE_REFRESH_SECONDS * 1000);
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden) loadOrders(0, false);
        });
        window.addEventListener("beforeunload", () => window.clearInterval(liveTimer), { once: true });
    });
})();
