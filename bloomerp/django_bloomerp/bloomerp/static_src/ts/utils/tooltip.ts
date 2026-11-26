type TooltipPosition = "top" | "bottom" | "left" | "right";

type AddTooltipOptions = {
    title?: string;
    text: string;
    position?: TooltipPosition;
    portal?: boolean;
};

type CleanupFn = () => void;

export const TOOLTIP_SHOW_DELAY_MS = 500;

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
                <div class="absolute top-full left-1/2 mt-1 -translate-x-1/2 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs leading-none text-gray-900 opacity-0 invisible transition-all duration-150 z-50 w-max max-w-64 whitespace-normal break-words text-left pointer-events-none shadow-sm">
                    ${content}
                    <div class="absolute left-1/2 top-0 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rotate-45 border-t border-l border-gray-200 bg-white"></div>
                </div>
            `;
        case "left":
            return `
                <div class="absolute right-full top-1/2 mr-1 -translate-y-1/2 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs leading-none text-gray-900 opacity-0 invisible transition-all duration-150 z-50 w-max max-w-64 whitespace-normal break-words text-left pointer-events-none shadow-sm">
                    ${content}
                    <div class="absolute right-0 top-1/2 h-2 w-2 translate-x-1/2 -translate-y-1/2 rotate-45 border-t border-r border-gray-200 bg-white"></div>
                </div>
            `;
        case "right":
            return `
                <div class="absolute left-full top-1/2 ml-1 -translate-y-1/2 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs leading-none text-gray-900 opacity-0 invisible transition-all duration-150 z-50 w-max max-w-64 whitespace-normal break-words text-left pointer-events-none shadow-sm">
                    ${content}
                    <div class="absolute left-0 top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rotate-45 border-b border-l border-gray-200 bg-white"></div>
                </div>
            `;
        case "top":
        default:
            return `
                <div class="absolute bottom-full left-1/2 mb-1 -translate-x-1/2 rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs leading-none text-gray-900 opacity-0 invisible transition-all duration-150 z-50 w-max max-w-64 whitespace-normal break-words text-left pointer-events-none shadow-sm">
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

/** Position a tooltip near its anchor and optionally find a side with more room. */
export function positionTooltip(
    element: HTMLElement,
    tooltip: HTMLElement,
    preferredPosition: TooltipPosition,
    flip: boolean = false,
): TooltipPosition {
    const anchor = element.getBoundingClientRect();
    const bounds = tooltip.getBoundingClientRect();
    const gap = 6;
    const padding = 4;
    let position = preferredPosition;
    if (flip) {
        const room = {
            top: anchor.top,
            bottom: window.innerHeight - anchor.bottom,
            left: anchor.left,
            right: window.innerWidth - anchor.right,
        };
        const opposite = { top: "bottom", bottom: "top", left: "right", right: "left" } as const;
        const order: TooltipPosition[] = preferredPosition === "top" || preferredPosition === "bottom"
            ? [preferredPosition, opposite[preferredPosition], "right", "left"]
            : [preferredPosition, opposite[preferredPosition], "bottom", "top"];
        /** Check whether the tooltip fits next to the anchor on this side. */
        function fits(side: TooltipPosition): boolean {
            const size = side === "top" || side === "bottom" ? bounds.height : bounds.width;
            return room[side] >= size + gap + padding;
        }
        position = order.find(fits) ?? preferredPosition;
    }
    let left = anchor.left + (anchor.width - bounds.width) / 2;
    let top = position === "bottom" ? anchor.bottom + gap : anchor.top - bounds.height - gap;
    if (position === "left" || position === "right") {
        left = position === "left" ? anchor.left - bounds.width - gap : anchor.right + gap;
        top = anchor.top + (anchor.height - bounds.height) / 2;
    }
    left = Math.max(padding, Math.min(left, window.innerWidth - bounds.width - padding));
    top = Math.max(padding, Math.min(top, window.innerHeight - bounds.height - padding));
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
    tooltip.style.setProperty("--tooltip-anchor-x", `${anchor.left + anchor.width / 2 - left}px`);
    tooltip.style.setProperty("--tooltip-anchor-y", `${anchor.top + anchor.height / 2 - top}px`);
    return position;
}

/** Lift an open tooltip above native popovers and return it to the page when closed. */
export function setTooltipTopLayer(tooltip: HTMLElement, open: boolean): void {
    if (typeof tooltip.showPopover !== "function") return;
    if (open) {
        if (!tooltip.hasAttribute("popover")) tooltip.setAttribute("popover", "manual");
        if (!tooltip.matches(":popover-open")) tooltip.showPopover();
    } else if (tooltip.hasAttribute("popover")) {
        if (tooltip.matches(":popover-open")) tooltip.hidePopover();
        tooltip.removeAttribute("popover");
    }
}

/** Attach a shared tooltip, optionally escaping scroll containers through the top layer. */
export function addTooltip(element: HTMLElement, options: AddTooltipOptions): CleanupFn {
    const tooltipTitle = (options.title || "").trim();
    const tooltipText = options.text.trim();

    element.querySelector(":scope > [data-inline-tooltip]")?.remove();

    if (!tooltipTitle && !tooltipText) {
        /** No resources were created for an empty hint. */
        return (): void => {};
    }

    const position = options.position || "top";
    const template = document.createElement("template");
    template.innerHTML = getTooltipMarkup(tooltipTitle, tooltipText, position);
    const tooltip = template.content.firstElementChild as HTMLElement;
    if (options.portal) return attachPortalTooltip(element, tooltip, position);
    tooltip.dataset.inlineTooltip = "";
    tooltip.style.setProperty("--tooltip-show-delay", `${TOOLTIP_SHOW_DELAY_MS}ms`);
    tooltip.setAttribute("role", "tooltip");
    element.appendChild(tooltip);

    /** Remove only tooltip markup owned by this element. */
    return (): void => {
        tooltip.remove();
    };
}

/** Keep the existing tooltip design visible above clipped toolbars and open popovers. */
function attachPortalTooltip(element: HTMLElement, tooltip: HTMLElement, position: TooltipPosition): CleanupFn {
    const lifecycle = new AbortController();
    let ownerPopover: HTMLElement | null = null;
    let showTimer: number | undefined;
    tooltip.dataset.dynamicTooltip = "true";
    tooltip.setAttribute("role", "tooltip");
    tooltip.id = `tooltip-${crypto.randomUUID()}`;
    tooltip.style.cssText = "position:fixed;inset:auto;margin:0;transform:none;translate:none;overflow:visible;transition-property:opacity;opacity:0;visibility:hidden;z-index:2147483647";
    tooltip.hidden = true;
    const describedBy = element.getAttribute("aria-describedby");
    element.setAttribute("aria-describedby", [describedBy, tooltip.id].filter(Boolean).join(" "));
    document.body.appendChild(tooltip);

    /** Dismiss hints immediately when the owning control or viewport changes. */
    function hide(): void {
        window.clearTimeout(showTimer);
        showTimer = undefined;
        ownerPopover?.removeEventListener("beforetoggle", onOwnerToggle);
        ownerPopover = null;
        setTooltipTopLayer(tooltip, false);
        tooltip.hidden = true;
        tooltip.style.opacity = "0";
        tooltip.style.visibility = "hidden";
    }

    /** Close a portaled hint together with its selection toolbar or parent popover. */
    function onOwnerToggle(event: Event): void {
        if ((event as ToggleEvent).newState === "closed") hide();
    }

    /** Reveal and position the tooltip once the trigger has stayed active. */
    function show(): void {
        showTimer = undefined;
        if (!element.isConnected || !element.getClientRects().length) {
            hide();
            return;
        }
        tooltip.hidden = false;
        setTooltipTopLayer(tooltip, true);
        positionTooltip(element, tooltip, position);
        tooltip.style.visibility = "visible";
        tooltip.style.opacity = "1";
    }

    /** Start the reveal delay and watch for the parent popover closing during it. */
    function scheduleShow(): void {
        if (showTimer !== undefined || !tooltip.hidden) return;

        ownerPopover = element.closest<HTMLElement>("[popover]");
        ownerPopover?.addEventListener("beforetoggle", onOwnerToggle);
        showTimer = window.setTimeout(show, TOOLTIP_SHOW_DELAY_MS);
    }

    element.addEventListener("mouseenter", scheduleShow, { signal: lifecycle.signal });
    element.addEventListener("mouseleave", hide, { signal: lifecycle.signal });
    element.addEventListener("focus", scheduleShow, { signal: lifecycle.signal });
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
