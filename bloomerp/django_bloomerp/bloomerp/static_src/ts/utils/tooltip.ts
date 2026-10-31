type TooltipPosition = "top" | "bottom" | "left" | "right";

type AddTooltipOptions = {
    title?: string;
    text: string;
    position?: TooltipPosition;
    portal?: boolean;
};

type CleanupFn = () => void;

/** Render the shared tooltip appearance for inline and portaled hints. */
function getTooltipMarkup(title: string, text: string, position: TooltipPosition): string {
    title = escapeTooltipText(title);
    text = escapeTooltipText(text);
    const content = `
        ${title ? `<div class="font-medium">${title}</div>` : ""}
        ${text ? `<div>${text}</div>` : ""}
    `;

    switch (position) {
        case "bottom":
            return `
                <div class="absolute top-full left-1/2 mt-1 -translate-x-1/2 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs leading-none text-gray-900 opacity-0 invisible transition-all duration-150 group-hover:opacity-100 group-hover:visible z-50 w-max max-w-64 whitespace-normal break-words text-left pointer-events-none shadow-sm">
                    ${content}
                    <div class="absolute left-1/2 top-0 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rotate-45 border-t border-l border-gray-200 bg-white"></div>
                </div>
            `;
        case "left":
            return `
                <div class="absolute right-full top-1/2 mr-1 -translate-y-1/2 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs leading-none text-gray-900 opacity-0 invisible transition-all duration-150 group-hover:opacity-100 group-hover:visible z-50 w-max max-w-64 whitespace-normal break-words text-left pointer-events-none shadow-sm">
                    ${content}
                    <div class="absolute right-0 top-1/2 h-2 w-2 translate-x-1/2 -translate-y-1/2 rotate-45 border-t border-r border-gray-200 bg-white"></div>
                </div>
            `;
        case "right":
            return `
                <div class="absolute left-full top-1/2 ml-1 -translate-y-1/2 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs leading-none text-gray-900 opacity-0 invisible transition-all duration-150 group-hover:opacity-100 group-hover:visible z-50 w-max max-w-64 whitespace-normal break-words text-left pointer-events-none shadow-sm">
                    ${content}
                    <div class="absolute left-0 top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rotate-45 border-b border-l border-gray-200 bg-white"></div>
                </div>
            `;
        case "top":
        default:
            return `
                <div class="absolute bottom-full left-1/2 mb-1 -translate-x-1/2 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs leading-none text-gray-900 opacity-0 invisible transition-all duration-150 group-hover:opacity-100 group-hover:visible z-50 w-max max-w-64 whitespace-normal break-words text-left pointer-events-none shadow-sm">
                    ${content}
                    <div class="absolute bottom-0 left-1/2 h-2 w-2 -translate-x-1/2 translate-y-1/2 rotate-45 border-b border-r border-gray-200 bg-white"></div>
                </div>
            `;
    }
}

/** Treat labels and shortcut hints as text when composing the shared markup. */
function escapeTooltipText(value: string): string {
    const text = document.createElement("span");
    text.textContent = value;
    return text.innerHTML;
}

/** Attach a shared tooltip, optionally escaping scroll containers through the top layer. */
export function addTooltip(element: HTMLElement, options: AddTooltipOptions): CleanupFn {
    const tooltipTitle = (options.title || "").trim();
    const tooltipText = options.text.trim();

    element.querySelectorAll<HTMLElement>("[data-dynamic-tooltip='true']").forEach((node) => node.remove());

    if (!tooltipTitle && !tooltipText) {
        /** No resources were created for an empty hint. */
        return (): void => {};
    }

    element.classList.add("relative", "group");

    const tooltip = document.createElement("div");
    tooltip.dataset.dynamicTooltip = "true";
    tooltip.innerHTML = getTooltipMarkup(tooltipTitle, tooltipText, options.position || "top");
    if (options.portal) return attachPortalTooltip(element, tooltip.firstElementChild as HTMLElement, options.position || "top");
    element.appendChild(tooltip);

    /** Remove only tooltip markup owned by this element. */
    return (): void => {
        element.querySelectorAll<HTMLElement>("[data-dynamic-tooltip='true']").forEach((node) => node.remove());
    };
}

/** Keep the existing tooltip design visible above clipped toolbars and open popovers. */
function attachPortalTooltip(element: HTMLElement, tooltip: HTMLElement, position: TooltipPosition): CleanupFn {
    const lifecycle = new AbortController();
    let ownerPopover: HTMLElement | null = null;
    tooltip.dataset.dynamicTooltip = "true";
    tooltip.setAttribute("role", "tooltip");
    tooltip.id = `tooltip-${crypto.randomUUID()}`;
    tooltip.style.cssText = "position:fixed;inset:auto;margin:0;transform:none;translate:none;overflow:visible;transition-property:opacity;opacity:0;visibility:hidden;z-index:2147483647";
    tooltip.hidden = true;
    if (typeof tooltip.showPopover === "function") tooltip.setAttribute("popover", "manual");
    const describedBy = element.getAttribute("aria-describedby");
    element.setAttribute("aria-describedby", [describedBy, tooltip.id].filter(Boolean).join(" "));
    document.body.appendChild(tooltip);

    /** Position relative to the trigger while keeping the hint inside the viewport. */
    function place(): void {
        const anchor = element.getBoundingClientRect();
        const bounds = tooltip.getBoundingClientRect();
        let left = anchor.left + (anchor.width - bounds.width) / 2;
        let top = position === "bottom" ? anchor.bottom + 6 : anchor.top - bounds.height - 6;
        if (position === "left" || position === "right") {
            left = position === "left" ? anchor.left - bounds.width - 6 : anchor.right + 6;
            top = anchor.top + (anchor.height - bounds.height) / 2;
        }
        tooltip.style.left = `${Math.max(4, Math.min(left, window.innerWidth - bounds.width - 4))}px`;
        tooltip.style.top = `${Math.max(4, Math.min(top, window.innerHeight - bounds.height - 4))}px`;
    }

    /** Dismiss hints immediately when the owning control or viewport changes. */
    function hide(): void {
        ownerPopover?.removeEventListener("beforetoggle", onOwnerToggle);
        ownerPopover = null;
        if (tooltip.hasAttribute("popover") && tooltip.matches(":popover-open")) tooltip.hidePopover();
        tooltip.hidden = true;
        tooltip.style.opacity = "0";
        tooltip.style.visibility = "hidden";
    }

    /** Close a portaled hint together with its selection toolbar or parent popover. */
    function onOwnerToggle(event: Event): void {
        if ((event as ToggleEvent).newState === "closed") hide();
    }

    /** Reveal the shared tooltip on pointer hover or keyboard focus. */
    function show(): void {
        if (!element.isConnected || !element.getClientRects().length) return;
        ownerPopover = element.closest<HTMLElement>("[popover]");
        ownerPopover?.addEventListener("beforetoggle", onOwnerToggle);
        tooltip.hidden = false;
        if (tooltip.hasAttribute("popover") && !tooltip.matches(":popover-open")) tooltip.showPopover();
        place();
        tooltip.style.visibility = "visible";
        tooltip.style.opacity = "1";
    }

    element.addEventListener("mouseenter", show, { signal: lifecycle.signal });
    element.addEventListener("mouseleave", hide, { signal: lifecycle.signal });
    element.addEventListener("focus", show, { signal: lifecycle.signal });
    element.addEventListener("blur", hide, { signal: lifecycle.signal });
    element.addEventListener("pointerdown", hide, { signal: lifecycle.signal });
    window.addEventListener("scroll", hide, { capture: true, signal: lifecycle.signal });
    window.addEventListener("resize", hide, { signal: lifecycle.signal });
    /** Release listeners, top-layer markup, and the trigger's accessibility reference. */
    function cleanup(): void {
        hide();
        lifecycle.abort();
        tooltip.remove();
        if (describedBy) element.setAttribute("aria-describedby", describedBy);
        else element.removeAttribute("aria-describedby");
    }
    return cleanup;
}
