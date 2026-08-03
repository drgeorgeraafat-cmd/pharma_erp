(() => {
    "use strict";

    function safeParse(value, fallback = {}) {
        try {
            return JSON.parse(value);
        } catch (error) {
            return fallback;
        }
    }

    function createElement(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined && text !== null) element.textContent = text;
        return element;
    }

    function empty(element) {
        element.replaceChildren();
    }

    function serverMessage(payload, fallback) {
        const messages = safeParse(payload?._server_messages, []);
        if (Array.isArray(messages) && messages.length) {
            const first = safeParse(messages[0], {});
            return first.message || messages[0] || fallback;
        }
        return payload?.message || fallback;
    }

    async function apiRequest(endpoint, options = {}) {
        const response = await fetch(endpoint, {
            credentials: "same-origin",
            method: options.method || "GET",
            headers: {
                Accept: "application/json",
                ...(options.body ? { "Content-Type": "application/json" } : {}),
                ...(options.csrf ? { "X-Frappe-CSRF-Token": options.csrf } : {}),
            },
            body: options.body ? JSON.stringify(options.body) : undefined,
        });
        const text = await response.text();
        const payload = safeParse(text, {});
        if (!response.ok) {
            const error = new Error(serverMessage(payload, `HTTP ${response.status}`));
            error.status = response.status;
            throw error;
        }
        return payload.message || {};
    }

    function showToast(root, message, type = "success") {
        const toast = document.getElementById("pharma-account-toast");
        if (!toast) return;
        toast.textContent = message;
        toast.className = `pharma-account__toast pharma-account__toast--${type}`;
        toast.hidden = false;
        window.clearTimeout(root._toastTimer);
        root._toastTimer = window.setTimeout(() => {
            toast.hidden = true;
        }, 3200);
    }

    function dateLabel(value) {
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
    }

    function setBusy(form, busy, label) {
        const button = form?.querySelector("button[type='submit']");
        if (!button) return;
        if (!button.dataset.originalLabel) button.dataset.originalLabel = button.textContent;
        button.disabled = busy;
        button.textContent = busy ? label : button.dataset.originalLabel;
    }

    document.addEventListener("DOMContentLoaded", () => {
        const root = document.getElementById("pharma-customer-account");
        if (!root || root.dataset.isGuest === "1") return;

        const csrf = root.dataset.csrf || "";
        const loading = document.getElementById("pharma-account-loading");
        const errorBox = document.getElementById("pharma-account-error");
        const activation = document.getElementById("pharma-account-activation");
        const activationForm = document.getElementById("pharma-account-activation-form");
        const content = document.getElementById("pharma-account-content");
        const profileForm = document.getElementById("pharma-account-profile-form");
        const addressesContainer = document.getElementById("pharma-account-addresses");
        const noAddresses = document.getElementById("pharma-account-no-addresses");
        const addressEditor = document.getElementById("pharma-account-address-editor");
        const addressForm = document.getElementById("pharma-account-address-form");
        const addressEditorTitle = document.getElementById("pharma-account-address-title");
        const ordersContainer = document.getElementById("pharma-account-orders");
        const noOrders = document.getElementById("pharma-account-no-orders");
        const loadMore = document.getElementById("pharma-account-load-more");
        const guestClaimForm = document.getElementById("pharma-account-guest-claim-form");
        let account = null;
        let nextStart = 0;

        function showError(message) {
            loading.hidden = true;
            errorBox.textContent = message;
            errorBox.hidden = false;
        }

        function clearError() {
            errorBox.hidden = true;
            errorBox.textContent = "";
        }

        function showAddressEditor(address = null) {
            addressForm.reset();
            addressForm.elements.country.value = address?.country || "Egypt";
            addressForm.elements.address_type.value = address?.address_type || "Shipping";
            addressForm.elements.name.value = address?.name || "";
            addressForm.elements.address_title.value = address?.address_title || "";
            addressForm.elements.address_line1.value = address?.address_line1 || "";
            addressForm.elements.address_line2.value = address?.address_line2 || "";
            addressForm.elements.city.value = address?.city || "";
            addressForm.elements.state.value = address?.state || "";
            addressForm.elements.pincode.value = address?.pincode || "";
            addressForm.elements.phone.value = address?.phone || account?.profile?.mobile_no || "";
            addressForm.elements.make_default.checked = Boolean(address?.is_default);
            addressEditorTitle.textContent = address ? "تعديل العنوان" : "إضافة عنوان جديد";
            addressEditor.hidden = false;
            addressEditor.scrollIntoView({ behavior: "smooth", block: "start" });
        }

        function hideAddressEditor() {
            addressEditor.hidden = true;
            addressForm.reset();
        }

        async function mutate(endpoint, body, successMessage) {
            clearError();
            const result = await apiRequest(endpoint, {
                method: "POST",
                csrf,
                body,
            });
            account = result;
            renderAccount(false);
            if (successMessage) showToast(root, successMessage);
            return result;
        }

        function addressCard(address) {
            const card = createElement("article", "pharma-account__address-card");
            const top = createElement("div", "pharma-account__address-top");
            const title = createElement("div");
            title.appendChild(createElement("strong", "", address.address_title || "عنوان محفوظ"));
            title.appendChild(createElement("span", "pharma-account__muted", address.address_type || ""));
            top.appendChild(title);
            if (address.is_default) top.appendChild(createElement("span", "pharma-account__badge pharma-account__badge--default", "الافتراضي"));
            card.appendChild(top);

            card.appendChild(createElement("p", "pharma-account__address-line", address.address_line1 || ""));
            if (address.address_line2) card.appendChild(createElement("p", "pharma-account__address-line", address.address_line2));
            card.appendChild(createElement("p", "pharma-account__address-line", [address.city, address.state, address.country].filter(Boolean).join("، ")));
            if (address.phone) card.appendChild(createElement("p", "pharma-account__address-line", `موبايل: ${address.phone}`));

            const actions = createElement("div", "pharma-account__card-actions");
            const edit = createElement("button", "pharma-account__small-button", "تعديل");
            edit.type = "button";
            edit.addEventListener("click", () => showAddressEditor(address));
            actions.appendChild(edit);

            if (!address.is_default) {
                const makeDefault = createElement("button", "pharma-account__small-button", "تعيين كافتراضي");
                makeDefault.type = "button";
                makeDefault.addEventListener("click", async () => {
                    makeDefault.disabled = true;
                    try {
                        await mutate(root.dataset.addressDefaultEndpoint, { address_name: address.name }, "تم تعيين العنوان الافتراضي.");
                    } catch (requestError) {
                        showToast(root, requestError.message || "تعذر تعيين العنوان الافتراضي.", "error");
                    } finally {
                        makeDefault.disabled = false;
                    }
                });
                actions.appendChild(makeDefault);
            }

            const archive = createElement("button", "pharma-account__small-button pharma-account__small-button--danger", "أرشفة");
            archive.type = "button";
            archive.addEventListener("click", async () => {
                if (!window.confirm("سيتم إخفاء العنوان من الاختيار مع الاحتفاظ به للسجل التاريخي. هل تريد المتابعة؟")) return;
                archive.disabled = true;
                try {
                    await mutate(root.dataset.addressArchiveEndpoint, { address_name: address.name }, "تمت أرشفة العنوان.");
                } catch (requestError) {
                    showToast(root, requestError.message || "تعذر أرشفة العنوان.", "error");
                } finally {
                    archive.disabled = false;
                }
            });
            actions.appendChild(archive);
            card.appendChild(actions);
            return card;
        }

        function orderCard(order) {
            const card = createElement("article", "pharma-account__order-card");
            const top = createElement("div", "pharma-account__order-top");
            const identity = createElement("div");
            identity.appendChild(createElement("strong", "pharma-account__order-number", order.online_order));
            identity.appendChild(createElement("span", "pharma-account__muted", dateLabel(order.placed_at)));
            top.appendChild(identity);
            top.appendChild(createElement("span", `pharma-account__status pharma-account__status--${order.status_key || "review"}`, order.status_label_ar));
            card.appendChild(top);

            const details = createElement("div", "pharma-account__order-details");
            const detailRows = [
                ["طريقة الاستلام", order.fulfilment_label_ar],
                ["حالة الدفع", order.payment_status_label_ar],
                ["عدد الأصناف", String(order.item_count || 0)],
                ["الإجمالي", order.grand_total_formatted],
            ];
            for (const [label, value] of detailRows) {
                const row = createElement("div");
                row.append(createElement("span", "", label), createElement("strong", "", value || "—"));
                details.appendChild(row);
            }
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
        }

        function renderAddresses() {
            empty(addressesContainer);
            const addresses = account?.addresses || [];
            noAddresses.hidden = addresses.length > 0;
            for (const address of addresses) addressesContainer.appendChild(addressCard(address));
        }

        function renderOrders(append = false) {
            if (!append) empty(ordersContainer);
            const orders = account?.orders || [];
            if (!append) noOrders.hidden = orders.length > 0;
            for (const order of orders) ordersContainer.appendChild(orderCard(order));
            nextStart = Number(account?.next_start || 0);
            loadMore.hidden = !account?.has_more;
        }

        function renderAccount(appendOrders = false) {
            loading.hidden = true;
            clearError();
            if (!account?.customer_linked) {
                content.hidden = true;
                activation.hidden = false;
                activationForm.elements.full_name.value = account?.profile?.full_name || "";
                activationForm.elements.mobile_no.value = account?.profile?.mobile_no || "";
                return;
            }

            activation.hidden = true;
            content.hidden = false;
            document.getElementById("pharma-account-customer-code").textContent = account.customer_code ? `كود العميل: ${account.customer_code}` : "";
            document.getElementById("pharma-account-email").value = account.profile?.email || "";
            document.getElementById("pharma-account-full-name").value = account.profile?.full_name || "";
            document.getElementById("pharma-account-mobile").value = account.profile?.mobile_no || "";
            renderAddresses();
            renderOrders(appendOrders);
        }

        async function loadAccount(start = 0, append = false) {
            clearError();
            if (!append) loading.hidden = false;
            try {
                const query = new URLSearchParams({ start: String(start), page_length: "20" });
                const result = await apiRequest(`${root.dataset.accountEndpoint}?${query.toString()}`);
                if (append) {
                    account = { ...account, ...result, orders: result.orders || [] };
                } else {
                    account = result;
                }
                renderAccount(append);
            } catch (requestError) {
                if (requestError.status === 403 || requestError.status === 401) {
                    window.location.assign("/login?redirect-to=%2Fpharmacy-account%2F");
                    return;
                }
                showError(requestError.message || "تعذر تحميل حساب العميل.");
            }
        }

        activationForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (!activationForm.reportValidity()) return;
            setBusy(activationForm, true, "جارٍ التفعيل…");
            try {
                const data = new FormData(activationForm);
                account = await apiRequest(root.dataset.activateEndpoint, {
                    method: "POST",
                    csrf,
                    body: { payload: { full_name: data.get("full_name"), mobile_no: data.get("mobile_no") } },
                });
                renderAccount(false);
                showToast(root, "تم تفعيل حساب العميل بنجاح.");
            } catch (requestError) {
                showToast(root, requestError.message || "تعذر تفعيل الحساب.", "error");
            } finally {
                setBusy(activationForm, false);
            }
        });

        profileForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (!profileForm.reportValidity()) return;
            setBusy(profileForm, true, "جارٍ الحفظ…");
            try {
                const data = new FormData(profileForm);
                await mutate(root.dataset.profileEndpoint, {
                    payload: { full_name: data.get("full_name"), mobile_no: data.get("mobile_no") },
                }, "تم حفظ بيانات الحساب.");
            } catch (requestError) {
                showToast(root, requestError.message || "تعذر حفظ بيانات الحساب.", "error");
            } finally {
                setBusy(profileForm, false);
            }
        });

        document.getElementById("pharma-account-add-address").addEventListener("click", () => showAddressEditor());
        document.getElementById("pharma-account-cancel-address").addEventListener("click", hideAddressEditor);

        addressForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (!addressForm.reportValidity()) return;
            setBusy(addressForm, true, "جارٍ حفظ العنوان…");
            try {
                const data = new FormData(addressForm);
                const payload = Object.fromEntries(data.entries());
                payload.make_default = data.get("make_default") ? 1 : 0;
                await mutate(root.dataset.addressSaveEndpoint, { payload }, "تم حفظ العنوان.");
                hideAddressEditor();
            } catch (requestError) {
                showToast(root, requestError.message || "تعذر حفظ العنوان.", "error");
            } finally {
                setBusy(addressForm, false);
            }
        });

        guestClaimForm?.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (!guestClaimForm.reportValidity()) return;
            setBusy(guestClaimForm, true, "جارٍ التحقق والربط…");
            try {
                const data = new FormData(guestClaimForm);
                account = await apiRequest(root.dataset.guestClaimEndpoint, {
                    method: "POST",
                    csrf,
                    body: {
                        payload: {
                            online_order: String(data.get("online_order") || "").trim(),
                            tracking_token: String(data.get("tracking_token") || "").trim(),
                            mobile_last4: String(data.get("mobile_last4") || "").trim(),
                        },
                    },
                });
                renderAccount(false);
                guestClaimForm.reset();
                showToast(root, "تم ربط الطلب بحسابك وظهر الآن داخل طلباتي.");
            } catch (requestError) {
                showToast(
                    root,
                    requestError.message || "تعذر ربط الطلب. راجع البيانات وحاول مرة أخرى.",
                    "error"
                );
            } finally {
                setBusy(guestClaimForm, false);
            }
        });

        loadMore.addEventListener("click", async () => {
            loadMore.disabled = true;
            try {
                await loadAccount(nextStart, true);
            } finally {
                loadMore.disabled = false;
            }
        });

        const logout = document.getElementById("pharma-account-logout");
        logout?.addEventListener("click", async (event) => {
            event.preventDefault();
            try {
                await fetch("/api/method/logout", { credentials: "same-origin" });
            } finally {
                window.location.assign("/pharmacy-account/");
            }
        });

        loadAccount();
    });
})();


// Step 4C — controlled customer notification preferences.
(() => {
    "use strict";

    async function notificationRequest(endpoint, options = {}) {
        const response = await fetch(endpoint, {
            credentials: "same-origin",
            method: options.method || "GET",
            headers: {
                Accept: "application/json",
                ...(options.body ? { "Content-Type": "application/json" } : {}),
                ...(options.csrf ? { "X-Frappe-CSRF-Token": options.csrf } : {}),
            },
            body: options.body ? JSON.stringify(options.body) : undefined,
        });
        let payload = {};
        try {
            payload = await response.json();
        } catch (error) {
            payload = {};
        }
        if (!response.ok) {
            throw new Error(payload?.message || "تعذر تنفيذ طلب تفضيلات الإشعارات.");
        }
        return payload?.message ?? payload;
    }

    function initNotificationPreferences() {
        const root = document.getElementById("pharma-customer-account");
        const form = document.getElementById("pharma-account-notification-form");
        const status = document.getElementById("pharma-account-notification-status");
        if (!root || !form || root.dataset.isGuest === "1") return;

        const loadEndpoint = root.dataset.notificationPreferencesEndpoint;
        const saveEndpoint = root.dataset.notificationPreferencesUpdateEndpoint;
        const csrf = root.dataset.csrf || "";
        if (!loadEndpoint || !saveEndpoint) return;

        const setStatus = (message, kind = "") => {
            status.textContent = message || "";
            status.dataset.kind = kind;
        };

        const applyPreferences = (preferences) => {
            form.elements.order_updates_enabled.checked = Boolean(
                preferences?.order_updates_enabled
            );
            form.elements.email_enabled.checked = Boolean(preferences?.email_enabled);
            form.elements.whatsapp_enabled.checked = false;
            form.elements.sms_enabled.checked = false;
        };

        const setBusy = (busy) => {
            for (const element of form.elements) {
                if (element.name === "whatsapp_enabled" || element.name === "sms_enabled") {
                    continue;
                }
                element.disabled = busy;
            }
        };

        async function loadPreferences() {
            setStatus("جارٍ تحميل التفضيلات…");
            try {
                const preferences = await notificationRequest(loadEndpoint);
                applyPreferences(preferences);
                setStatus(
                    preferences?.outbound_delivery_enabled
                        ? "الإرسال الخارجي مفعّل."
                        : "تم تحميل التفضيلات — الإرسال الخارجي مؤجل حاليًا.",
                    "success"
                );
            } catch (error) {
                setStatus(error.message || "تعذر تحميل تفضيلات الإشعارات.", "error");
            }
        }

        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            setBusy(true);
            setStatus("جارٍ حفظ التفضيلات…");
            try {
                const preferences = await notificationRequest(saveEndpoint, {
                    method: "POST",
                    csrf,
                    body: {
                        payload: {
                            order_updates_enabled:
                                form.elements.order_updates_enabled.checked ? 1 : 0,
                            email_enabled: form.elements.email_enabled.checked ? 1 : 0,
                            whatsapp_enabled: 0,
                            sms_enabled: 0,
                        },
                    },
                });
                applyPreferences(preferences);
                setStatus("تم حفظ تفضيلات الإشعارات.", "success");
            } catch (error) {
                setStatus(error.message || "تعذر حفظ تفضيلات الإشعارات.", "error");
            } finally {
                setBusy(false);
            }
        });

        loadPreferences();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initNotificationPreferences);
    } else {
        initNotificationPreferences();
    }
})();
