(() => {
    "use strict";

    const STORAGE_KEY = "pharma_controlled_cart_v1";
    const TOKEN_KEY = "pharma_controlled_checkout_token_v1";
    const MAX_LINE_QTY = 99;

    function safeParse(value, fallback) {
        try {
            return JSON.parse(value);
        } catch (error) {
            return fallback;
        }
    }

    function cleanItem(raw) {
        if (!raw || typeof raw !== "object") return null;
        const itemCode = String(raw.item_code || "").trim();
        if (!itemCode) return null;
        const qty = Math.max(1, Math.min(MAX_LINE_QTY, Number.parseInt(raw.qty, 10) || 1));
        return {
            item_code: itemCode,
            item_name: String(raw.item_name || itemCode),
            image: String(raw.image || ""),
            category: String(raw.category || ""),
            price_formatted: String(raw.price_formatted || ""),
            requires_prescription: raw.requires_prescription ? 1 : 0,
            availability: String(raw.availability || "Available"),
            qty,
        };
    }

    function loadCart() {
        const parsed = safeParse(window.localStorage.getItem(STORAGE_KEY), []);
        if (!Array.isArray(parsed)) return [];
        return parsed.map(cleanItem).filter(Boolean).slice(0, 25);
    }

    function saveCart(items) {
        const cleaned = items.map(cleanItem).filter(Boolean).slice(0, 25);
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cleaned));
        window.dispatchEvent(new CustomEvent("pharma:cart-updated", { detail: { items: cleaned } }));
        return cleaned;
    }

    function cartCount(items = loadCart()) {
        return items.reduce((total, item) => total + (Number(item.qty) || 0), 0);
    }

    function createElement(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined && text !== null) element.textContent = text;
        return element;
    }

    function showToast(message, type = "success") {
        let container = document.getElementById("pharma-cart-toast-container");
        if (!container) {
            container = createElement("div", "pharma-cart-toast-container");
            container.id = "pharma-cart-toast-container";
            container.setAttribute("aria-live", "polite");
            document.body.appendChild(container);
        }
        const toast = createElement("div", `pharma-cart-toast pharma-cart-toast--${type}`, message);
        container.appendChild(toast);
        window.setTimeout(() => toast.remove(), 2600);
    }

    function ensureFloatingCart() {
        let link = document.getElementById("pharma-floating-cart");
        if (!link) {
            link = createElement("a", "pharma-floating-cart");
            link.id = "pharma-floating-cart";
            link.href = "/pharmacy-cart/";
            link.setAttribute("aria-label", "فتح سلة المشتريات");
            link.appendChild(createElement("span", "pharma-floating-cart__label", "السلة"));
            const count = createElement("span", "pharma-floating-cart__count", "0");
            count.id = "pharma-floating-cart-count";
            link.appendChild(count);
            document.body.appendChild(link);
        }
        updateCartIndicators();
    }

    function updateCartIndicators() {
        const count = cartCount();
        document.querySelectorAll("[data-pharma-cart-count]").forEach((element) => {
            element.textContent = String(count);
        });
        const floating = document.getElementById("pharma-floating-cart-count");
        if (floating) floating.textContent = String(count);
    }

    function addProduct(product) {
        const item = cleanItem({ ...product, qty: 1 });
        if (!item) {
            showToast("تعذر إضافة المنتج إلى السلة.", "error");
            return false;
        }
        if (item.availability !== "Available") {
            showToast("هذا المنتج غير متاح للطلب حاليًا.", "error");
            return false;
        }

        const items = loadCart();
        const existing = items.find((row) => row.item_code === item.item_code);
        if (existing) {
            existing.qty = Math.min(MAX_LINE_QTY, existing.qty + 1);
        } else {
            items.push(item);
        }
        saveCart(items);
        showToast(`تمت إضافة ${item.item_name} إلى السلة.`);
        return true;
    }

    function updateQty(itemCode, qty) {
        const items = loadCart();
        const item = items.find((row) => row.item_code === itemCode);
        if (!item) return;
        item.qty = Math.max(1, Math.min(MAX_LINE_QTY, Number.parseInt(qty, 10) || 1));
        saveCart(items);
    }

    function removeItem(itemCode) {
        saveCart(loadCart().filter((item) => item.item_code !== itemCode));
    }

    function clearCart() {
        saveCart([]);
    }

    function checkoutToken() {
        let token = window.sessionStorage.getItem(TOKEN_KEY);
        if (token && /^WEB-[A-Za-z0-9_-]{16,96}$/.test(token)) return token;
        const random = window.crypto?.randomUUID
            ? window.crypto.randomUUID().replaceAll("-", "")
            : `${Date.now()}${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`;
        token = `WEB-${random}`;
        window.sessionStorage.setItem(TOKEN_KEY, token);
        return token;
    }

    function resetCheckoutToken() {
        window.sessionStorage.removeItem(TOKEN_KEY);
    }

    async function apiRequest(endpoint, options = {}) {
        const response = await fetch(endpoint, {
            credentials: "same-origin",
            headers: {
                "Accept": "application/json",
                ...(options.body ? { "Content-Type": "application/json" } : {}),
                ...(options.csrf ? { "X-Frappe-CSRF-Token": options.csrf } : {}),
            },
            method: options.method || "GET",
            body: options.body ? JSON.stringify(options.body) : undefined,
        });

        const text = await response.text();
        const payload = safeParse(text, {});
        if (!response.ok) {
            const serverMessages = safeParse(payload._server_messages, []);
            let message = payload.message || `HTTP ${response.status}`;
            if (Array.isArray(serverMessages) && serverMessages.length) {
                const parsed = safeParse(serverMessages[0], {});
                message = parsed.message || message;
            }
            const error = new Error(message);
            error.status = response.status;
            error.payload = payload;
            throw error;
        }
        return payload.message || {};
    }

    function cartPayload() {
        return loadCart().map((item) => ({ item_code: item.item_code, qty: item.qty }));
    }

    function addProductButtonHandler(button) {
        const product = button.dataset.product
            ? safeParse(button.dataset.product, {})
            : {
                item_code: button.dataset.itemCode,
                item_name: button.dataset.itemName,
                image: button.dataset.image,
                category: button.dataset.category,
                price_formatted: button.dataset.priceFormatted,
                requires_prescription: button.dataset.requiresPrescription === "1" ? 1 : 0,
                availability: button.dataset.availability || "Available",
            };
        button.addEventListener("click", () => addProduct(product));
    }

    function initialiseStaticAddButtons() {
        document.querySelectorAll("[data-pharma-add-to-cart]").forEach((button) => {
            if (button.dataset.pharmaBound === "1") return;
            button.dataset.pharmaBound = "1";
            addProductButtonHandler(button);
        });
    }

    function emptyNode(element) {
        element.replaceChildren();
    }

    function buildCartRow(item, onChange) {
        const row = createElement("article", "pharma-cart-row");
        const media = createElement("div", "pharma-cart-row__media");
        if (item.image) {
            const image = document.createElement("img");
            image.src = item.image;
            image.alt = item.item_name;
            media.appendChild(image);
        } else {
            media.appendChild(createElement("span", "", "لا توجد صورة"));
        }
        row.appendChild(media);

        const content = createElement("div", "pharma-cart-row__content");
        content.appendChild(createElement("strong", "pharma-cart-row__title", item.item_name));
        content.appendChild(createElement("span", "pharma-cart-row__code", `كود: ${item.item_code}`));
        if (item.requires_prescription) {
            content.appendChild(createElement("span", "pharma-cart-row__rx", "يتطلب روشتة"));
        }
        row.appendChild(content);

        const controls = createElement("div", "pharma-cart-row__controls");
        const minus = createElement("button", "pharma-cart-qty-button", "−");
        minus.type = "button";
        const qty = document.createElement("input");
        qty.className = "pharma-cart-qty-input";
        qty.type = "number";
        qty.min = "1";
        qty.max = String(MAX_LINE_QTY);
        qty.step = "1";
        qty.value = String(item.qty);
        qty.setAttribute("aria-label", `كمية ${item.item_name}`);
        const plus = createElement("button", "pharma-cart-qty-button", "+");
        plus.type = "button";
        const remove = createElement("button", "pharma-cart-remove", "حذف");
        remove.type = "button";

        minus.addEventListener("click", () => {
            updateQty(item.item_code, Math.max(1, item.qty - 1));
            onChange();
        });
        plus.addEventListener("click", () => {
            updateQty(item.item_code, Math.min(MAX_LINE_QTY, item.qty + 1));
            onChange();
        });
        qty.addEventListener("change", () => {
            updateQty(item.item_code, qty.value);
            onChange();
        });
        remove.addEventListener("click", () => {
            removeItem(item.item_code);
            onChange();
        });

        controls.append(minus, qty, plus, remove);
        row.appendChild(controls);
        return row;
    }

    async function initialiseCartPage(root) {
        const list = document.getElementById("pharma-cart-items");
        const empty = document.getElementById("pharma-cart-empty");
        const loading = document.getElementById("pharma-cart-loading");
        const error = document.getElementById("pharma-cart-error");
        const subtotal = document.getElementById("pharma-cart-subtotal");
        const total = document.getElementById("pharma-cart-total");
        const checkout = document.getElementById("pharma-cart-checkout");
        const clear = document.getElementById("pharma-cart-clear");
        const csrf = root.dataset.csrf || "";
        let rendering = false;

        async function render() {
            if (rendering) return;
            rendering = true;
            error.hidden = true;
            loading.hidden = false;
            checkout.classList.add("is-disabled");
            emptyNode(list);
            const items = loadCart();
            empty.hidden = Boolean(items.length);

            if (!items.length) {
                loading.hidden = true;
                subtotal.textContent = "0.00 EGP";
                total.textContent = "0.00 EGP";
                rendering = false;
                return;
            }

            for (const item of items) list.appendChild(buildCartRow(item, render));

            try {
                const result = await apiRequest(root.dataset.validateEndpoint, {
                    method: "POST",
                    csrf,
                    body: { items: cartPayload() },
                });
                subtotal.textContent = result.products_subtotal_formatted || "";
                total.textContent = result.grand_total_formatted || "";
                checkout.classList.remove("is-disabled");
            } catch (requestError) {
                error.textContent = requestError.message || "تعذر التحقق من السلة.";
                error.hidden = false;
            } finally {
                loading.hidden = true;
                rendering = false;
            }
        }

        clear.addEventListener("click", () => {
            clearCart();
            render();
        });
        checkout.addEventListener("click", (event) => {
            if (checkout.classList.contains("is-disabled")) event.preventDefault();
        });
        window.addEventListener("pharma:cart-updated", render);
        await render();
    }

    function toggleDeliveryFields(root) {
        const fulfilment = root.querySelector("[name='fulfilment_method']:checked")?.value || "Home Delivery";
        const deliveryFields = root.querySelector("[data-delivery-fields]");
        const required = fulfilment === "Home Delivery";
        deliveryFields.hidden = !required;
        deliveryFields.querySelectorAll("[data-delivery-required]").forEach((input) => {
            input.required = required;
        });
        const note = document.getElementById("pharma-checkout-delivery-note");
        if (note) {
            note.textContent = required
                ? "رسوم التوصيل تُراجع داخليًا بعد استلام الطلب ولن تُحصّل في هذه الخطوة."
                : "سيتم الاستلام والدفع داخل الصيدلية بعد تجهيز الطلب.";
        }
    }

    async function initialiseCheckoutPage(root) {
        const form = document.getElementById("pharma-checkout-form");
        const itemsContainer = document.getElementById("pharma-checkout-items");
        const summaryError = document.getElementById("pharma-checkout-summary-error");
        const submitError = document.getElementById("pharma-checkout-submit-error");
        const submit = document.getElementById("pharma-checkout-submit");
        const subtotal = document.getElementById("pharma-checkout-subtotal");
        const total = document.getElementById("pharma-checkout-total");
        const csrf = root.dataset.csrf || "";
        const accountPanel = document.getElementById("pharma-checkout-account-panel");
        const savedAddressWrap = document.getElementById("pharma-saved-address-wrap");
        const savedAddressSelect = document.getElementById("pharma-saved-address");
        const paymentOption = document.getElementById("pharma-checkout-payment-option");
        const paymentNote = document.getElementById("pharma-checkout-payment-note");
        const prepaidFields = document.getElementById("pharma-checkout-prepaid-fields");
        const declaredPaid = document.getElementById("pharma-checkout-declared-paid");
        const transactionReference = document.getElementById("pharma-checkout-transaction-reference");
        let validated = null;
        let checkoutIdentity = null;
        let paymentOptions = [];

        const items = loadCart();
        if (!items.length) {
            window.location.replace("/pharmacy-cart/");
            return;
        }

        async function loadPaymentOptions() {
            const fulfilment = root.querySelector("[name='fulfilment_method']:checked")?.value || "Home Delivery";
            const result = await apiRequest(
                `${root.dataset.paymentOptionsEndpoint}?fulfilment_method=${encodeURIComponent(fulfilment)}`,
                { method: "GET" },
            );
            paymentOptions = result.options || [];
            emptyNode(paymentOption);
            for (const optionRow of paymentOptions) {
                const option = document.createElement("option");
                option.value = optionRow.name;
                option.textContent = optionRow.label_ar || optionRow.name;
                option.dataset.prepaid = String(Number(optionRow.prepaid || 0));
                paymentOption.appendChild(option);
            }
            refreshPaymentFields();
            paymentNote.textContent = result.delivery_fee_pending_review
                ? "الدفع المسبق للتوصيل المنزلي يُختار بعد اعتماد منطقة ورسوم التوصيل. المتاح الآن هو الدفع عند الاستلام."
                : "الدفع المسبق عند الاستلام من الصيدلية يحتاج مرجع تحويل، ولا ينشئ Payment Entry تلقائيًا.";
        }

        function refreshPaymentFields() {
            const selected = paymentOptions.find((row) => row.name === paymentOption.value) || {};
            const prepaid = Number(selected.prepaid || 0) === 1;
            prepaidFields.hidden = !prepaid;
            transactionReference.required = prepaid;
            if (prepaid && validated) {
                declaredPaid.value = Number(validated.grand_total || 0).toFixed(2);
            } else if (!prepaid) {
                declaredPaid.value = "0.00";
                transactionReference.value = "";
            }
        }

        paymentOption.addEventListener("change", refreshPaymentFields);
        root.querySelectorAll("[name='fulfilment_method']").forEach((input) => {
            input.addEventListener("change", async () => {
                toggleDeliveryFields(root);
                try {
                    await loadPaymentOptions();
                } catch (paymentError) {
                    submitError.textContent = paymentError.message || "تعذر تحميل طرق الدفع.";
                    submitError.hidden = false;
                    submit.disabled = true;
                }
            });
        });
        toggleDeliveryFields(root);

        function fillAddress(address) {
            const fieldMap = {
                address_line1: "address_line1",
                address_line2: "address_line2",
                city: "city",
                state: "state",
                country: "country",
            };
            for (const [key, name] of Object.entries(fieldMap)) {
                const input = form.elements[name];
                if (input) input.value = address?.[key] || (name === "country" ? "Egypt" : "");
            }
        }

        try {
            checkoutIdentity = await apiRequest(root.dataset.identityEndpoint, { method: "GET" });
            if (checkoutIdentity.authenticated && accountPanel) {
                accountPanel.hidden = false;
                if (checkoutIdentity.customer_linked) {
                    const customer = checkoutIdentity.customer || {};
                    accountPanel.textContent = `تم ربط حساب الموقع بكود العميل ${customer.customer_code || customer.customer || ""}. يمكنك اختيار عنوان محفوظ.`;
                    const nameInput = form.elements.customer_name;
                    const mobileInput = form.elements.mobile_no;
                    const emailInput = form.elements.email_id;
                    if (nameInput && customer.customer_name) nameInput.value = customer.customer_name;
                    if (mobileInput && customer.mobile_no) mobileInput.value = customer.mobile_no;
                    if (emailInput && customer.email_id) emailInput.value = customer.email_id;
                    const addresses = checkoutIdentity.addresses || [];
                    if (addresses.length && savedAddressWrap && savedAddressSelect) {
                        savedAddressWrap.hidden = false;
                        for (const address of addresses) {
                            const option = document.createElement("option");
                            option.value = address.name;
                            option.textContent = address.label || address.address_title || address.name;
                            option.dataset.address = JSON.stringify(address);
                            savedAddressSelect.appendChild(option);
                        }
                        savedAddressSelect.addEventListener("change", () => {
                            const option = savedAddressSelect.options[savedAddressSelect.selectedIndex];
                            const address = option?.dataset.address ? JSON.parse(option.dataset.address) : null;
                            fillAddress(address);
                        });
                    }
                } else if (checkoutIdentity.ambiguous_customer_links) {
                    accountPanel.textContent = "حساب الموقع مرتبط بأكثر من كود عميل. سيتم إيقاف الربط التلقائي وإرسال الطلب للمراجعة الداخلية.";
                } else {
                    accountPanel.textContent = "حساب الموقع غير مربوط بعد بكود عميل داخل الصيدلية. سيتم اقتراح المطابقة أثناء مراجعة الطلب.";
                }
            }
        } catch (identityError) {
            if (accountPanel) {
                accountPanel.hidden = false;
                accountPanel.textContent = "تعذر تحميل بيانات حساب العميل المحفوظة. يمكنك استكمال الطلب يدويًا.";
            }
        }

        try {
            validated = await apiRequest(root.dataset.validateEndpoint, {
                method: "POST",
                csrf,
                body: { items: cartPayload() },
            });
            emptyNode(itemsContainer);
            for (const item of validated.items || []) {
                const row = createElement("div", "pharma-checkout-item");
                const label = createElement("span", "", `${item.item_name} × ${item.qty}`);
                const amount = createElement("strong", "", item.amount_formatted);
                row.append(label, amount);
                itemsContainer.appendChild(row);
            }
            subtotal.textContent = validated.products_subtotal_formatted;
            total.textContent = validated.grand_total_formatted;
            await loadPaymentOptions();
            refreshPaymentFields();
            if (validated.prescription_required) {
                document.getElementById("pharma-checkout-rx-note").hidden = false;
            }
            submit.disabled = false;
        } catch (requestError) {
            summaryError.textContent = requestError.message || "تعذر التحقق من السلة.";
            summaryError.hidden = false;
        }

        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            submitError.hidden = true;
            if (!validated || !form.reportValidity()) return;
            submit.disabled = true;
            submit.textContent = "جارٍ إنشاء الطلب…";

            const data = new FormData(form);
            const payload = {
                checkout_token: checkoutToken(),
                items: cartPayload(),
                customer_name: data.get("customer_name"),
                mobile_no: data.get("mobile_no"),
                email_id: data.get("email_id"),
                customer_address: data.get("customer_address"),
                fulfilment_method: data.get("fulfilment_method"),
                address_line1: data.get("address_line1"),
                address_line2: data.get("address_line2"),
                city: data.get("city"),
                state: data.get("state"),
                country: data.get("country"),
                delivery_instructions: data.get("delivery_instructions"),
                payment_option: data.get("payment_option"),
                declared_paid_amount: data.get("declared_paid_amount"),
                transaction_reference: data.get("transaction_reference"),
            };

            try {
                const result = await apiRequest(root.dataset.createEndpoint, {
                    method: "POST",
                    csrf,
                    body: { payload },
                });
                clearCart();
                resetCheckoutToken();
                const params = new URLSearchParams({
                    order: result.online_order,
                    token: result.checkout_token,
                });
                window.location.assign(`/pharmacy-order-success/?${params.toString()}`);
            } catch (requestError) {
                submitError.textContent = requestError.message || "تعذر إنشاء الطلب.";
                submitError.hidden = false;
                submit.disabled = false;
                submit.textContent = "تأكيد وإرسال الطلب للمراجعة";
            }
        });
    }

    async function initialiseSuccessPage(root) {
        const params = new URLSearchParams(window.location.search);
        const onlineOrder = params.get("order") || "";
        const token = params.get("token") || "";
        const loading = document.getElementById("pharma-success-loading");
        const error = document.getElementById("pharma-success-error");
        const content = document.getElementById("pharma-success-content");
        const items = document.getElementById("pharma-success-items");

        if (!onlineOrder || !token) {
            loading.hidden = true;
            error.textContent = "بيانات تأكيد الطلب غير مكتملة.";
            error.hidden = false;
            return;
        }

        try {
            const query = new URLSearchParams({ online_order: onlineOrder, checkout_token: token });
            const receipt = await apiRequest(`${root.dataset.receiptEndpoint}?${query.toString()}`);
            document.getElementById("pharma-success-order").textContent = receipt.online_order;
            document.getElementById("pharma-success-status").textContent = receipt.status;
            document.getElementById("pharma-success-mobile").textContent = receipt.mobile_no_masked;
            document.getElementById("pharma-success-fulfilment").textContent = receipt.fulfilment_method;
            document.getElementById("pharma-success-total").textContent = receipt.grand_total_formatted;
            document.getElementById("pharma-success-payment").textContent = receipt.payment_status;
            const trackingLink = document.getElementById("pharma-success-track");
            const trackingNote = document.getElementById("pharma-success-tracking-note");
            if (trackingLink && receipt.tracking_url) {
                trackingLink.href = receipt.tracking_url;
                trackingLink.hidden = false;
                if (trackingNote) trackingNote.hidden = false;
            }
            if (receipt.delivery_fee_pending_review) {
                document.getElementById("pharma-success-delivery-note").hidden = false;
            }
            if (receipt.prescription_required) {
                document.getElementById("pharma-success-rx-note").hidden = false;
            }
            emptyNode(items);
            for (const item of receipt.items || []) {
                const row = createElement("div", "pharma-checkout-item");
                row.append(
                    createElement("span", "", `${item.item_name} × ${item.qty}`),
                    createElement("strong", "", item.amount_formatted)
                );
                items.appendChild(row);
            }
            loading.hidden = true;
            content.hidden = false;
        } catch (requestError) {
            loading.hidden = true;
            error.textContent = requestError.message || "تعذر تحميل تأكيد الطلب.";
            error.hidden = false;
        }
    }

    window.PharmaControlledCart = {
        addProduct,
        clearCart,
        count: () => cartCount(),
        getItems: loadCart,
        removeItem,
        updateQty,
        refreshIndicators: updateCartIndicators,
    };

    document.addEventListener("DOMContentLoaded", () => {
        ensureFloatingCart();
        initialiseStaticAddButtons();
        const cartRoot = document.getElementById("pharma-controlled-cart-page");
        const checkoutRoot = document.getElementById("pharma-controlled-checkout-page");
        const successRoot = document.getElementById("pharma-controlled-order-success");
        if (cartRoot) initialiseCartPage(cartRoot);
        if (checkoutRoot) initialiseCheckoutPage(checkoutRoot);
        if (successRoot) initialiseSuccessPage(successRoot);
    });

    window.addEventListener("pharma:cart-updated", updateCartIndicators);
})();
