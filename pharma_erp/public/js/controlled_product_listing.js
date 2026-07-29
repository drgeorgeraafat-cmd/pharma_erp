(() => {
    "use strict";

    const root = document.getElementById("pharma-controlled-catalog");
    if (!root) return;

    const endpoint = root.dataset.endpoint;
    const pageLength = 24;
    const state = {
        start: 0,
        loading: false,
        hasMore: false,
        categoriesLoaded: false,
        requestId: 0,
    };

    const elements = {
        search: document.getElementById("pharma-catalog-search"),
        category: document.getElementById("pharma-catalog-category"),
        availability: document.getElementById("pharma-catalog-availability"),
        featured: document.getElementById("pharma-catalog-featured"),
        clear: document.getElementById("pharma-catalog-clear"),
        count: document.getElementById("pharma-catalog-result-count"),
        grid: document.getElementById("pharma-catalog-grid"),
        empty: document.getElementById("pharma-catalog-empty"),
        error: document.getElementById("pharma-catalog-error"),
        loading: document.getElementById("pharma-catalog-loading"),
        loadMore: document.getElementById("pharma-catalog-load-more"),
    };

    const availabilityLabels = {
        "Available": "متاح",
        "Temporarily Unavailable": "غير متاح مؤقتًا",
        "Coming Soon": "قريبًا",
    };

    function debounce(fn, wait) {
        let timeout;
        return (...args) => {
            window.clearTimeout(timeout);
            timeout = window.setTimeout(() => fn(...args), wait);
        };
    }

    function createElement(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined && text !== null) element.textContent = text;
        return element;
    }

    function createBadge(text, modifier = "") {
        return createElement("span", `pharma-badge${modifier ? ` ${modifier}` : ""}`, text);
    }

    function buildCard(product) {
        const card = createElement("article", "pharma-product-card");
        const link = createElement("a", "pharma-product-card__media");
        link.href = product.product_url;
        link.setAttribute("aria-label", product.item_name);

        if (product.image) {
            const image = document.createElement("img");
            image.src = product.image;
            image.alt = product.item_name;
            image.loading = "lazy";
            link.appendChild(image);
        } else {
            link.appendChild(createElement("div", "pharma-product-card__placeholder", "لا توجد صورة"));
        }

        const badges = createElement("div", "pharma-product-card__badges");
        if (product.featured) badges.appendChild(createBadge("مميز", "pharma-badge--featured"));
        if (product.requires_prescription) badges.appendChild(createBadge("Rx", "pharma-badge--rx"));
        link.appendChild(badges);
        card.appendChild(link);

        const body = createElement("div", "pharma-product-card__body");
        if (product.category) body.appendChild(createElement("p", "pharma-product-card__category", product.category));

        const titleLink = createElement("a", "pharma-product-card__title", product.item_name);
        titleLink.href = product.product_url;
        body.appendChild(titleLink);
        body.appendChild(createElement("p", "pharma-product-card__code", `كود: ${product.item_code}`));

        if (product.summary) body.appendChild(createElement("p", "pharma-product-card__summary", product.summary));

        const footer = createElement("div", "pharma-product-card__footer");
        footer.appendChild(createElement("strong", "pharma-product-card__price", product.price_formatted));
        const availability = createBadge(
            availabilityLabels[product.availability] || product.availability,
            "pharma-badge--availability"
        );
        availability.dataset.availability = product.availability;
        footer.appendChild(availability);
        body.appendChild(footer);

        const actions = createElement("div", "pharma-product-card__cart-actions");
        const addButton = createElement(
            "button",
            "pharma-cart-add-button",
            product.availability === "Available" ? "أضف للسلة" : "غير متاح للطلب"
        );
        addButton.type = "button";
        addButton.disabled = product.availability !== "Available";
        addButton.addEventListener("click", () => {
            if (!window.PharmaControlledCart) return;
            window.PharmaControlledCart.addProduct(product);
        });

        const details = createElement("a", "pharma-product-card__details", "التفاصيل");
        details.href = product.product_url;
        actions.append(addButton, details);
        body.appendChild(actions);
        card.appendChild(body);
        return card;
    }

    function populateCategories(categories) {
        if (state.categoriesLoaded) return;
        for (const category of categories || []) {
            const option = document.createElement("option");
            option.value = category;
            option.textContent = category;
            elements.category.appendChild(option);
        }
        state.categoriesLoaded = true;
    }

    function setLoading(isLoading, append) {
        state.loading = isLoading;
        elements.loading.hidden = !isLoading || append;
        elements.loadMore.disabled = isLoading;
        root.classList.toggle("is-loading-more", isLoading && append);
    }

    function clearMessages() {
        elements.error.hidden = true;
        elements.empty.hidden = true;
    }

    function filters() {
        return {
            search: elements.search.value.trim(),
            category: elements.category.value,
            availability: elements.availability.value,
            featured: elements.featured.checked ? "1" : "0",
        };
    }

    async function loadProducts({ append = false } = {}) {
        if (state.loading) return;
        const requestId = ++state.requestId;
        clearMessages();

        if (!append) {
            state.start = 0;
            elements.grid.replaceChildren();
        }

        setLoading(true, append);
        const params = new URLSearchParams({
            ...filters(),
            start: String(state.start),
            page_length: String(pageLength),
        });

        try {
            const response = await fetch(`${endpoint}?${params.toString()}`, {
                method: "GET",
                headers: { "Accept": "application/json" },
                credentials: "same-origin",
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const payload = await response.json();
            if (requestId !== state.requestId) return;
            const result = payload.message || {};
            const items = Array.isArray(result.items) ? result.items : [];

            populateCategories(result.categories);
            for (const product of items) elements.grid.appendChild(buildCard(product));

            state.start += items.length;
            state.hasMore = Boolean(result.has_more);
            elements.loadMore.hidden = !state.hasMore;
            elements.count.textContent = `${result.total_count || 0} منتج`;
            elements.empty.hidden = Boolean(items.length || append);
        } catch (error) {
            console.error("Controlled catalog loading failed", error);
            elements.error.textContent = "تعذر تحميل المنتجات حاليًا. أعد المحاولة بعد لحظات.";
            elements.error.hidden = false;
            elements.count.textContent = "تعذر تحميل النتائج";
            elements.loadMore.hidden = true;
        } finally {
            if (requestId === state.requestId) setLoading(false, append);
        }
    }

    const reload = () => loadProducts({ append: false });
    elements.search.addEventListener("input", debounce(reload, 320));
    elements.category.addEventListener("change", reload);
    elements.availability.addEventListener("change", reload);
    elements.featured.addEventListener("change", reload);
    elements.loadMore.addEventListener("click", () => loadProducts({ append: true }));
    elements.clear.addEventListener("click", () => {
        elements.search.value = "";
        elements.category.value = "";
        elements.availability.value = "";
        elements.featured.checked = false;
        reload();
    });

    loadProducts();
})();
