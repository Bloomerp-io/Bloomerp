export type BehaviorFieldStateUpdate = {
    visible: boolean | null;
    disabled: boolean;
};

export type BehaviorFieldStateSnapshot = {
    hidden: boolean;
    ariaHidden: string | null;
    inert: boolean;
    ariaDisabled: string | null;
    behaviorDisabled: string | null;
};

/** Capture every element state changed by a behavior state update. */
export function captureBehaviorFieldState(element: HTMLElement): BehaviorFieldStateSnapshot {
    return {
        hidden: element.classList.contains("hidden"),
        ariaHidden: element.getAttribute("aria-hidden"),
        inert: element.inert,
        ariaDisabled: element.getAttribute("aria-disabled"),
        behaviorDisabled: element.getAttribute("data-behavior-disabled"),
    };
}

/** Apply visibility and an inert interaction lock without disabling form controls. */
export function applyBehaviorFieldState(
    element: HTMLElement,
    update: BehaviorFieldStateUpdate,
): void {
    if (update.visible !== null) {
        element.classList.toggle("hidden", !update.visible);
        element.toggleAttribute("data-behavior-hidden", !update.visible);
        element.setAttribute("aria-hidden", String(!update.visible));
    }
    element.inert = update.disabled;
    element.toggleAttribute("data-behavior-disabled", update.disabled);
    element.setAttribute("aria-disabled", String(update.disabled));
}

/** Restore the original interaction and accessibility state after form reset. */
export function restoreBehaviorFieldState(
    element: HTMLElement,
    snapshot: BehaviorFieldStateSnapshot,
): void {
    element.classList.toggle("hidden", snapshot.hidden);
    element.removeAttribute("data-behavior-hidden");
    if (snapshot.ariaHidden === null) element.removeAttribute("aria-hidden");
    else element.setAttribute("aria-hidden", snapshot.ariaHidden);
    element.inert = snapshot.inert;
    if (snapshot.ariaDisabled === null) element.removeAttribute("aria-disabled");
    else element.setAttribute("aria-disabled", snapshot.ariaDisabled);
    if (snapshot.behaviorDisabled === null) element.removeAttribute("data-behavior-disabled");
    else element.setAttribute("data-behavior-disabled", snapshot.behaviorDisabled);
}
