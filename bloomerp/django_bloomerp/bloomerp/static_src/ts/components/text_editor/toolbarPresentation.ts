import { addTooltip } from "../../utils/tooltip.ts";

/** Give an editor button or link the shared icon, accessible label, and tooltip. */
export function decorateToolbarControl(
    control: HTMLButtonElement | HTMLAnchorElement,
    label: string,
    icon: string,
    shortcutHint: string = "",
): () => void {
    control.classList.add("text-editor-action-button");
    control.setAttribute("aria-label", label);
    const image = document.createElement("i");
    image.className = icon;
    image.setAttribute("aria-hidden", "true");
    control.appendChild(image);
    return addTooltip(control, {
        title: shortcutHint ? label : undefined,
        text: shortcutHint || label,
        position: "top",
        portal: true,
    });
}

/** Center a visible toolbar above its anchor, moving below when space is tight. */
export function placeFloatingToolbar(element: HTMLElement, anchor: DOMRect): void {
    const bounds = element.getBoundingClientRect();
    const left = anchor.left + (anchor.width - bounds.width) / 2;
    const top = anchor.top - bounds.height - 8;
    element.style.left = `${Math.max(8, Math.min(left, window.innerWidth - bounds.width - 8))}px`;
    element.style.top = `${Math.max(8, Math.min(top >= 8 ? top : anchor.bottom + 8, window.innerHeight - bounds.height - 8))}px`;
}
