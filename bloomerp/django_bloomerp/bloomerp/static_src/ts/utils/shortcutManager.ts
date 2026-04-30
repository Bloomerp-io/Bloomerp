import { matchesShortcut, normalizeKeyboardEventKey, type ShortcutDefinition } from "./shortcuts";

type ShortcutRegistration = {
    rootElement: HTMLElement;
    shortcut: ShortcutDefinition;
    showHint: () => void;
    hideHint: () => void;
    performAction: () => void;
};

function isEditableTarget(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) return false;

    if (target.isContentEditable) return true;

    const editableAncestor = target.closest("input, textarea, select, [contenteditable=''], [contenteditable='true']");
    return editableAncestor instanceof HTMLElement;
}

function shouldIgnoreShortcutInEditableTarget(event: KeyboardEvent): boolean {
    if (!isEditableTarget(event.target)) return false;

    // Allow explicit app shortcuts with Cmd/Ctrl to continue working while typing.
    // Plain character entry and Alt-only combinations should stay with the field.
    return !event.metaKey && !event.ctrlKey;
}

function isVisible(element: HTMLElement): boolean {
    if (!element.isConnected) return false;
    if (element.getClientRects().length === 0) return false;

    const style = window.getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden";
}

function isDisabled(element: HTMLElement): boolean {
    return element.hasAttribute("disabled") || element.getAttribute("aria-disabled") === "true";
}

class ShortcutManager {
    private registrations = new Set<ShortcutRegistration>();
    private initialized = false;
    private revealModeActive = false;

    public register(registration: ShortcutRegistration): () => void {
        this.initialize();
        this.registrations.add(registration);

        return () => {
            registration.hideHint();
            this.registrations.delete(registration);
        };
    }

    public isRevealModeActive(): boolean {
        return this.revealModeActive;
    }

    private initialize(): void {
        if (this.initialized || typeof document === "undefined") return;

        document.addEventListener("keydown", (event: KeyboardEvent) => this.onKeyDown(event));
        document.addEventListener("keyup", (event: KeyboardEvent) => this.onKeyUp(event));
        window.addEventListener("blur", () => this.setRevealMode(false));
        document.addEventListener("visibilitychange", () => {
            if (document.visibilityState !== "visible") {
                this.setRevealMode(false);
            }
        });

        this.initialized = true;
    }

    private onKeyDown(event: KeyboardEvent): void {
        this.pruneDisconnected();

        if (this.isRevealKeyEvent(event)) {
            event.preventDefault();
            this.setRevealMode(true);
            return;
        }

        if (normalizeKeyboardEventKey(event) === "escape") {
            this.setRevealMode(false);
            return;
        }

        if (shouldIgnoreShortcutInEditableTarget(event)) return;

        const match = Array.from(this.registrations).find((registration) => this.matchesRegistration(registration, event));
        if (!match) return;

        event.preventDefault();
        match.performAction();
    }

    private onKeyUp(event: KeyboardEvent): void {
        if (!this.revealModeActive) return;
        if (!this.isRevealKeyEvent(event)) return;

        this.setRevealMode(false);
    }

    private setRevealMode(active: boolean): void {
        if (this.revealModeActive === active) return;

        this.revealModeActive = active;

        this.pruneDisconnected();

        for (const registration of this.registrations) {
            if (active && this.isRegistrationActive(registration)) {
                registration.showHint();
            } else {
                registration.hideHint();
            }
        }
    }

    private matchesRegistration(registration: ShortcutRegistration, event: KeyboardEvent): boolean {
        return this.isRegistrationActive(registration) && matchesShortcut(registration.shortcut, event);
    }

    private isRegistrationActive(registration: ShortcutRegistration): boolean {
        return isVisible(registration.rootElement) && !isDisabled(registration.rootElement);
    }

    private pruneDisconnected(): void {
        for (const registration of Array.from(this.registrations)) {
            if (registration.rootElement.isConnected) continue;
            registration.hideHint();
            this.registrations.delete(registration);
        }
    }

    private isRevealKeyEvent(event: KeyboardEvent): boolean {
        return (
            normalizeKeyboardEventKey(event) === "alt" &&
            !event.ctrlKey &&
            !event.metaKey &&
            !event.shiftKey
        );
    }
}

let shortcutManager: ShortcutManager | null = null;

export function getShortcutManager(): ShortcutManager {
    if (!shortcutManager) {
        shortcutManager = new ShortcutManager();
    }

    return shortcutManager;
}
