/** Keep a body-mounted menu above the trigger's panel and ancestor layers. */
export function getContextMenuLayer(trigger: HTMLElement | null): number {
    let layer = 50;
    for (let element = trigger; element; element = element.parentElement) {
        const view = element.ownerDocument.defaultView;
        const value = Number.parseInt(view?.getComputedStyle(element).zIndex ?? '', 10);
        if (Number.isFinite(value)) layer = Math.max(layer, value);
    }
    return layer + 1;
}
