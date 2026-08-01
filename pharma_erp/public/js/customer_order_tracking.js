(() => {
    "use strict";

    const STORAGE_KEY = "pharma_customer_tracking_token_v1";
    const TOKEN_PATTERN = /^TRK1\.[A-Za-z0-9_-]{32}\.[A-Za-z0-9_-]{43}$/;

    function safeParse(value, fallback = {}) {
        try {
            return JSON.parse(value);
        } catch (error) {
            return fallback;
        }
    }

    function text(id, value) {
        const element = document.getElementById(id);
        if (element) element.textContent = value == null ? "" : String(value);
    }

    function createElement(tag, className, value) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (value !== undefined && value !== null) element.textContent = String(value);
        return element;
    }

    function trackingToken() {
        const params = new URLSearchParams(window.location.search);
        const fromUrl = String(params.get("token") || "").trim();
        if (TOKEN_PATTERN.test(fromUrl)) {
            window.sessionStorage.setItem(STORAGE_KEY, fromUrl);
            window.history.replaceState({}, document.title, window.location.pathname);
            return fromUrl;
        }
        const stored = String(window.sessionStorage.getItem(STORAGE_KEY) || "").trim();
        return TOKEN_PATTERN.test(stored) ? stored : "";
    }

    async function apiRequest(endpoint, token) {
        const query = new URLSearchParams({ token });
        const response = await fetch(`${endpoint}?${query.toString()}`, {
            method: "GET",
            credentials: "same-origin",
            cache: "no-store",
            referrerPolicy: "no-referrer",
            headers: { "Accept": "application/json" },
        });
        const body = await response.text();
        const payload = safeParse(body, {});
        if (!response.ok) {
            throw new Error("تعذر فتح رابط التتبع. تأكد من استخدام الرابط الكامل المرسل لك.");
        }
        return payload.message || {};
    }

    function formatDate(value) {
        if (!value) return "—";
        const parsed = new Date(String(value).replace(" ", "T"));
        if (Number.isNaN(parsed.getTime())) return String(value);
        return new Intl.DateTimeFormat("ar-EG", {
            year: "numeric",
            month: "short",
            day: "numeric",
            hour: "numeric",
            minute: "2-digit",
        }).format(parsed);
    }

    function renderTimeline(rows) {
        const list = document.getElementById("pharma-tracking-timeline");
        list.replaceChildren();
        for (const row of rows || []) {
            const item = createElement("li", `is-${row.state || "upcoming"}`);
            item.appendChild(createElement("span", "pharma-tracking__timeline-marker"));
            const content = createElement("div");
            content.appendChild(createElement("div", "pharma-tracking__timeline-title", row.label_ar));
            if (row.at) {
                content.appendChild(createElement("time", "pharma-tracking__timeline-time", formatDate(row.at)));
            }
            item.appendChild(content);
            list.appendChild(item);
        }
    }

    function renderItems(rows) {
        const container = document.getElementById("pharma-tracking-items");
        container.replaceChildren();
        for (const row of rows || []) {
            const item = createElement("div", "pharma-tracking__item");
            const title = createElement("strong", "", row.item_name || "منتج");
            if (row.requires_prescription) {
                title.appendChild(createElement("small", "pharma-tracking__rx", "يتطلب روشتة"));
            }
            item.append(title, createElement("span", "", `الكمية: ${row.qty}`));
            container.appendChild(item);
        }
        if (!container.children.length) {
            container.appendChild(createElement("p", "", "لا توجد أصناف معروضة."));
        }
    }

    function renderTracking(data) {
        text("pharma-tracking-order", data.online_order);
        text("pharma-tracking-date", formatDate(data.placed_at));
        text("pharma-tracking-status", data.customer_status?.label_ar || "قيد المراجعة");
        text("pharma-tracking-status-message", data.customer_status?.message_ar || "");
        text("pharma-tracking-fulfilment", data.fulfilment_label_ar || "—");
        text("pharma-tracking-total", data.grand_total_formatted || "—");
        text("pharma-tracking-payment", data.payment_status_label_ar || "—");
        text("pharma-tracking-payment-method", data.payment_method_label_ar || "—");

        const paymentMethodRow = document.getElementById("pharma-tracking-payment-method-row");
        if (paymentMethodRow) paymentMethodRow.hidden = !data.payment_method_label_ar;

        const driverCard = document.getElementById("pharma-tracking-driver-card");
        if (data.driver_name) {
            text("pharma-tracking-driver", data.driver_name);
            driverCard.hidden = false;
            if (Number(data.estimated_delivery_time_mins || 0) > 0) {
                text("pharma-tracking-estimate", `${data.estimated_delivery_time_mins} دقيقة تقريبًا`);
                document.getElementById("pharma-tracking-estimate-row").hidden = false;
            }
        } else {
            driverCard.hidden = true;
        }

        renderTimeline(data.timeline);
        renderItems(data.items);
    }

    async function initialise() {
        const root = document.getElementById("pharma-customer-order-tracking");
        if (!root) return;
        const loading = document.getElementById("pharma-tracking-loading");
        const error = document.getElementById("pharma-tracking-error");
        const content = document.getElementById("pharma-tracking-content");
        const token = trackingToken();

        if (!token) {
            loading.hidden = true;
            error.textContent = "رابط التتبع غير مكتمل. افتح الرابط الكامل الذي استلمته مع الطلب.";
            error.hidden = false;
            return;
        }

        try {
            const data = await apiRequest(root.dataset.endpoint, token);
            renderTracking(data);
            loading.hidden = true;
            content.hidden = false;
        } catch (requestError) {
            loading.hidden = true;
            error.textContent = requestError.message || "تعذر تحميل حالة الطلب.";
            error.hidden = false;
        }
    }

    document.addEventListener("DOMContentLoaded", initialise);
})();
