(() => {
    "use strict";

    const VERSION = "4A.2-R7";
    const ACCOUNT_ROUTE = "/pharmacy-account/";
    const ORDERS_ROUTE = "/pharmacy-orders/";
    const ACCOUNT_LABEL = "حساب الصيدلية";
    const ORDERS_LABEL = "طلباتي";
    const STANDARD_ACCOUNT_PATHS = new Set(["/me", "/my-account", "/account"]);
    const NEWSLETTER_PATHS = new Set(["/newsletter", "/newsletters"]);
    const ROW_SELECTOR = [
        "li",
        ".sidebar-item",
        ".portal-menu-item",
        ".nav-item",
        ".web-sidebar-item",
        ".sidebar-link",
        ".list-group-item",
        ".list-unstyled-item",
    ].join(", ");

    window.__pharmaPortalNavigationVersion = VERSION;

    const normaliseText = (value) => String(value || "").replace(/\s+/g, " ").trim().toLowerCase();

    const pathAndHash = (anchor) => {
        try {
            const url = new URL(anchor.getAttribute("href") || "", window.location.origin);
            return {
                pathname: url.pathname.replace(/\/+$/, "") || "/",
                hash: url.hash || "",
            };
        } catch (_error) {
            return { pathname: "", hash: "" };
        }
    };

    const allAnchors = (root = document) => Array.from(root.querySelectorAll("a[href]"));

    const replaceAnchorText = (anchor, label) => {
        if (normaliseText(anchor.textContent) === normaliseText(label)) return;

        const textNodes = Array.from(anchor.childNodes).filter((node) => node.nodeType === Node.TEXT_NODE);
        const textNode = textNodes.find((node) => String(node.textContent || "").trim());
        if (textNode) {
            textNode.textContent = label;
            return;
        }

        const labelNode = anchor.querySelector(".item-link-text, .sidebar-item-label, span");
        if (labelNode) {
            labelNode.textContent = label;
            return;
        }

        anchor.textContent = label;
    };

    const isStandardAccountLink = (anchor) => {
        const { pathname } = pathAndHash(anchor);
        const label = normaliseText(anchor.textContent);
        return STANDARD_ACCOUNT_PATHS.has(pathname) || ["my account", "حسابي", "my profile"].includes(label);
    };

    const isCanonicalAccountLink = (anchor) => {
        const { pathname, hash } = pathAndHash(anchor);
        const label = normaliseText(anchor.textContent);
        return (
            (pathname === "/pharmacy-account" && !hash) ||
            label === normaliseText(ACCOUNT_LABEL) ||
            anchor.dataset.pharmaStandardAccountRewritten === "1"
        );
    };

    const isOrdersLink = (anchor) => {
        const { pathname, hash } = pathAndHash(anchor);
        const label = normaliseText(anchor.textContent);
        return (
            pathname === "/pharmacy-orders" ||
            (pathname === "/pharmacy-account" && hash === "#my-orders") ||
            label === normaliseText(ORDERS_LABEL)
        );
    };

    const isNewsletterLink = (anchor) => {
        const { pathname } = pathAndHash(anchor);
        const label = normaliseText(anchor.textContent);
        return NEWSLETTER_PATHS.has(pathname) || ["newsletter", "newsletters", "النشرة البريدية"].includes(label);
    };

    const rowFor = (anchor) => {
        const knownRow = anchor.closest(ROW_SELECTOR);
        if (knownRow) return knownRow;

        const parent = anchor.parentElement;
        if (parent && parent.querySelectorAll("a[href]").length === 1) return parent;
        return anchor;
    };

    const groupFor = (anchor) => {
        const row = rowFor(anchor);
        return row.parentElement || anchor.parentElement || document.body;
    };

    const isPortalNavigationContext = () => {
        const anchors = allAnchors();
        return anchors.some((anchor) => isStandardAccountLink(anchor) || isCanonicalAccountLink(anchor) || isOrdersLink(anchor));
    };

    // DIRECT_NEWSLETTER_ANCHOR_SCAN:
    // R7 also upgrades legacy /pharmacy-account/#my-orders links to /pharmacy-orders/.
    // The Frappe v15 portal sidebar markup does not consistently expose the same wrapper classes.
    // Scan anchors directly, then remove only the closest link row.
    const removeNewsletterEntriesGlobally = () => {
        if (!isPortalNavigationContext()) return;
        allAnchors()
            .filter(isNewsletterLink)
            .forEach((anchor) => {
                const row = rowFor(anchor);
                row.remove();
            });
    };

    const rewriteStandardAccountEntries = () => {
        allAnchors().forEach((anchor) => {
            if (!isStandardAccountLink(anchor) && !isCanonicalAccountLink(anchor)) return;

            const { pathname, hash } = pathAndHash(anchor);
            if (pathname !== "/pharmacy-account" || hash) anchor.href = ACCOUNT_ROUTE;
            anchor.dataset.pharmaStandardAccountRewritten = "1";
            replaceAnchorText(anchor, ACCOUNT_LABEL);
        });
    };

    const normaliseOrdersEntries = () => {
        allAnchors().forEach((anchor) => {
            if (!isOrdersLink(anchor)) return;
            if (anchor.getAttribute("href") !== ORDERS_ROUTE) anchor.href = ORDERS_ROUTE;
            replaceAnchorText(anchor, ORDERS_LABEL);
        });
    };

    const deduplicateWithinNavigationGroups = () => {
        const groups = new Map();
        allAnchors()
            .filter((anchor) => isCanonicalAccountLink(anchor) || isOrdersLink(anchor))
            .forEach((anchor) => {
                const group = groupFor(anchor);
                if (!groups.has(group)) groups.set(group, []);
                groups.get(group).push(anchor);
            });

        groups.forEach((anchors) => {
            const accounts = anchors.filter(isCanonicalAccountLink);
            const orders = anchors.filter(isOrdersLink);
            accounts.slice(1).forEach((anchor) => rowFor(anchor).remove());
            orders.slice(1).forEach((anchor) => rowFor(anchor).remove());
        });
    };

    const ensureAccountBeforeOrdersDirectly = () => {
        const accounts = allAnchors().filter(isCanonicalAccountLink);
        const orders = allAnchors().filter(isOrdersLink);

        orders.forEach((ordersAnchor) => {
            const ordersRow = rowFor(ordersAnchor);
            const ordersParent = ordersRow.parentElement;
            if (!ordersParent) return;

            const accountAnchor = accounts.find((candidate) => rowFor(candidate).parentElement === ordersParent);
            if (!accountAnchor) return;

            const accountRow = rowFor(accountAnchor);
            const accountAfterOrders = Boolean(
                accountRow.compareDocumentPosition(ordersRow) & Node.DOCUMENT_POSITION_PRECEDING
            );
            if (accountAfterOrders) ordersParent.insertBefore(accountRow, ordersRow);
        });
    };

    const addUserMenuLinks = () => {
        allAnchors().filter((anchor) => {
            const href = anchor.getAttribute("href") || "";
            return href.includes("/api/method/logout") || href === "/logout";
        }).forEach((logoutLink) => {
            const menu = logoutLink.closest(".dropdown-menu");
            if (!menu) return;

            const makeLink = (label, href, key) => {
                const link = document.createElement("a");
                link.className = logoutLink.classList.contains("dropdown-item") ? "dropdown-item" : logoutLink.className;
                link.href = href;
                link.textContent = label;
                link.dataset.pharmaUserMenu = key;
                return link;
            };

            if (!menu.querySelector('[data-pharma-user-menu="account"]')) {
                menu.insertBefore(makeLink(ACCOUNT_LABEL, ACCOUNT_ROUTE, "account"), logoutLink);
            }
            if (!menu.querySelector('[data-pharma-user-menu="orders"]')) {
                menu.insertBefore(makeLink(ORDERS_LABEL, ORDERS_ROUTE, "orders"), logoutLink);
            }
        });
    };

    const applyNavigation = () => {
        rewriteStandardAccountEntries();
        normaliseOrdersEntries();
        removeNewsletterEntriesGlobally();
        deduplicateWithinNavigationGroups();
        ensureAccountBeforeOrdersDirectly();
        addUserMenuLinks();
    };

    let scheduled = false;
    const scheduleNavigation = () => {
        if (scheduled) return;
        scheduled = true;
        window.requestAnimationFrame(() => {
            scheduled = false;
            applyNavigation();
        });
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", scheduleNavigation, { once: true });
    } else {
        scheduleNavigation();
    }

    window.addEventListener("pageshow", scheduleNavigation);
    window.setTimeout(scheduleNavigation, 250);
    window.setTimeout(scheduleNavigation, 1000);

    const observer = new MutationObserver(scheduleNavigation);
    observer.observe(document.documentElement, { childList: true, subtree: true });
})();
