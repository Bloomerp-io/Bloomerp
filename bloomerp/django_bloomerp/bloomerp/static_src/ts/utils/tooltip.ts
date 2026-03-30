type TooltipPosition = "top" | "bottom" | "left" | "right";

type AddTooltipOptions = {
    title?: string;
    text: string;
    position?: TooltipPosition;
};

type CleanupFn = () => void;

function getTooltipMarkup(title: string, text: string, position: TooltipPosition): string {
    const content = `
        ${title ? `<div class="font-semibold mb-1">${title}</div>` : ""}
        ${text ? `<div>${text}</div>` : ""}
    `;

    switch (position) {
        case "bottom":
            return `
                <div class="absolute top-full left-1/2 mt-1 -translate-x-1/2 rounded-md border border-gray-200 bg-white px-3 py-2 text-xs text-gray-800 opacity-0 invisible transition-all duration-150 group-hover:opacity-100 group-hover:visible z-50 w-max max-w-64 whitespace-normal break-words text-left pointer-events-none shadow-sm">
                    ${content}
                    <div class="absolute left-1/2 top-0 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rotate-45 border-t border-l border-gray-200 bg-white"></div>
                </div>
            `;
        case "left":
            return `
                <div class="absolute right-full top-1/2 mr-1 -translate-y-1/2 rounded-md border border-gray-200 bg-white px-3 py-2 text-xs text-gray-800 opacity-0 invisible transition-all duration-150 group-hover:opacity-100 group-hover:visible z-50 w-max max-w-64 whitespace-normal break-words text-left pointer-events-none shadow-sm">
                    ${content}
                    <div class="absolute right-0 top-1/2 h-2 w-2 translate-x-1/2 -translate-y-1/2 rotate-45 border-t border-r border-gray-200 bg-white"></div>
                </div>
            `;
        case "right":
            return `
                <div class="absolute left-full top-1/2 ml-1 -translate-y-1/2 rounded-md border border-gray-200 bg-white px-3 py-2 text-xs text-gray-800 opacity-0 invisible transition-all duration-150 group-hover:opacity-100 group-hover:visible z-50 w-max max-w-64 whitespace-normal break-words text-left pointer-events-none shadow-sm">
                    ${content}
                    <div class="absolute left-0 top-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rotate-45 border-b border-l border-gray-200 bg-white"></div>
                </div>
            `;
        case "top":
        default:
            return `
                <div class="absolute bottom-full left-1/2 mb-1 -translate-x-1/2 rounded-md border border-gray-200 bg-white px-3 py-2 text-xs text-gray-800 opacity-0 invisible transition-all duration-150 group-hover:opacity-100 group-hover:visible z-50 w-max max-w-64 whitespace-normal break-words text-left pointer-events-none shadow-sm">
                    ${content}
                    <div class="absolute bottom-0 left-1/2 h-2 w-2 -translate-x-1/2 translate-y-1/2 rotate-45 border-b border-r border-gray-200 bg-white"></div>
                </div>
            `;
    }
}

export function addTooltip(element: HTMLElement, options: AddTooltipOptions): CleanupFn {
    const tooltipTitle = (options.title || "").trim();
    const tooltipText = options.text.trim();

    element.querySelectorAll<HTMLElement>("[data-dynamic-tooltip='true']").forEach((node) => node.remove());

    if (!tooltipTitle && !tooltipText) {
        return () => {};
    }

    element.classList.add("relative", "group");

    const tooltip = document.createElement("div");
    tooltip.dataset.dynamicTooltip = "true";
    tooltip.innerHTML = getTooltipMarkup(tooltipTitle, tooltipText, options.position || "top");
    element.appendChild(tooltip);

    return () => {
        element.querySelectorAll<HTMLElement>("[data-dynamic-tooltip='true']").forEach((node) => node.remove());
    };
}
