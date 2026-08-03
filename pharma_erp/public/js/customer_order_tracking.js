(() => {
    "use strict";

    const VERSION = "4B";
    const STORAGE_KEY = "pharma_customer_tracking_token_v1";
    const TOKEN_PATTERN = /^TRK1\.[A-Za-z0-9_-]{32}\.[A-Za-z0-9_-]{43}$/;
    const LIVE_REFRESH_SECONDS = 20;
    window.__pharmaCustomerTrackingVersion = VERSION;

    function safeParse(value, fallback = {}) {
        try {
            return JSON.parse(value);
        } catch (_error) {
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
        const query = new URLSearchParams({ token, _: String(Date.now()) });
        const response = await fetch(`${endpoint}?${query.toString()}`, {
            method: "GET",
            credentials: "same-origin",
            cache: "no-store",
            referrerPolicy: "no-referrer",
            headers: { Accept: "application/json" },
        });
        const body = await response.text();
        const payload = safeParse(body, {});
        if (!response.ok) {
            throw new Error("تعذر تحديث حالة الطلب. تأكد من أن رابط التتبع ما زال صالحًا.");
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
        if (!list) return;
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

    function renderActivity(rows) {
        const card = document.getElementById("pharma-tracking-activity-card");
        const list = document.getElementById("pharma-tracking-activity");
        if (!card || !list) return;
        list.replaceChildren();
        for (const row of rows || []) {
            const item = createElement("li", "pharma-tracking__activity-item");
            const body = createElement("div");
            body.appendChild(createElement("strong", "", row.label_ar || "تحديث الطلب"));
            if (row.message_ar) body.appendChild(createElement("p", "", row.message_ar));
            item.append(body, createElement("time", "", formatDate(row.at)));
            list.appendChild(item);
        }
        card.hidden = !list.children.length;
    }

    function renderItems(rows) {
        const container = document.getElementById("pharma-tracking-items");
        if (!container) return;
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

    function renderTracking(data, previousRevision = "") {
        text("pharma-tracking-order", data.online_order);
        text("pharma-tracking-date", formatDate(data.placed_at));
        text("pharma-tracking-status", data.customer_status?.label_ar || "قيد المراجعة");
        text("pharma-tracking-status-message", data.customer_status?.message_ar || "");
        text("pharma-tracking-fulfilment", data.fulfilment_label_ar || "—");
        text("pharma-tracking-total", data.grand_total_formatted || "—");
        text("pharma-tracking-payment", data.payment_status_label_ar || "—");
        text("pharma-tracking-payment-method", data.payment_method_label_ar || "—");
        text("pharma-tracking-last-update", formatDate(data.last_status_update_at));

        const paymentMethodRow = document.getElementById("pharma-tracking-payment-method-row");
        if (paymentMethodRow) paymentMethodRow.hidden = !data.payment_method_label_ar;

        const driverCard = document.getElementById("pharma-tracking-driver-card");
        if (driverCard && data.driver_name) {
            text("pharma-tracking-driver", data.driver_name);
            driverCard.hidden = false;
            const estimateRow = document.getElementById("pharma-tracking-estimate-row");
            if (Number(data.estimated_delivery_time_mins || 0) > 0) {
                text("pharma-tracking-estimate", `${data.estimated_delivery_time_mins} دقيقة تقريبًا`);
                if (estimateRow) estimateRow.hidden = false;
            } else if (estimateRow) {
                estimateRow.hidden = true;
            }
        } else if (driverCard) {
            driverCard.hidden = true;
        }

        renderTimeline(data.timeline);
        renderActivity(data.status_activity);
        renderItems(data.items);

        const revision = String(data.status_revision || "");
        const announcement = document.getElementById("pharma-tracking-live-announcement");
        if (previousRevision && revision && previousRevision !== revision && announcement) {
            announcement.textContent = `تم تحديث حالة الطلب: ${data.customer_status?.label_ar || "تم تحديث الطلب"}`;
            announcement.hidden = false;
            window.setTimeout(() => { announcement.hidden = true; }, 5000);
        }
        return revision;
    }

    async function initialise() {
        const root = document.getElementById("pharma-customer-order-tracking");
        if (!root) return;
        const loading = document.getElementById("pharma-tracking-loading");
        const error = document.getElementById("pharma-tracking-error");
        const content = document.getElementById("pharma-tracking-content");
        const liveState = document.getElementById("pharma-tracking-live-state");
        const token = trackingToken();
        let currentRevision = "";
        let refreshing = false;
        let timer = null;

        if (!token) {
            loading.hidden = true;
            error.textContent = "رابط التتبع غير مكتمل. افتح الرابط الكامل الذي استلمته مع الطلب.";
            error.hidden = false;
            return;
        }

        const refresh = async (initial = false) => {
            if (refreshing || document.hidden) return;
            refreshing = true;
            if (liveState) liveState.textContent = initial ? "جارٍ تحميل الحالة…" : "جارٍ التحديث…";
            try {
                const data = await apiRequest(root.dataset.endpoint, token);
                currentRevision = renderTracking(data, currentRevision);
                loading.hidden = true;
                error.hidden = true;
                content.hidden = false;
                if (liveState) liveState.textContent = "تحديث مباشر مفعل";
            } catch (requestError) {
                if (initial) {
                    loading.hidden = true;
                    error.textContent = requestError.message || "تعذر تحميل حالة الطلب.";
                    error.hidden = false;
                }
                if (liveState) liveState.textContent = "تعذر التحديث الآن — ستتم المحاولة تلقائيًا";
            } finally {
                refreshing = false;
            }
        };

        await refresh(true);
        timer = window.setInterval(() => refresh(false), LIVE_REFRESH_SECONDS * 1000);
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden) refresh(false);
        });
        window.addEventListener("beforeunload", () => window.clearInterval(timer), { once: true });
    }

    document.addEventListener("DOMContentLoaded", initialise);
})();
