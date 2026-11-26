import { isMacPlatform, isShortcutSequence, matchesShortcut, normalizeKeyboardEventKey, type ShortcutBinding } from "./shortcuts";
import { getTopModal } from "./modals";

const SHORTCUT_REVEAL_DELAY_MS = 500;
const SHORTCUT_SEQUENCE_TIMEOUT_MS = 1000;
const SEQUENCE_EDITABLE_SELECTOR = [
    "input", "textarea", "select", "[contenteditable='']", "[contenteditable='true' i]",
    "[contenteditable='plaintext-only' i]", "[role~='textbox']", "[role~='searchbox']", "[role~='combobox']",
].join(", ");

type ShortcutRegistration = {
    rootElement: HTMLElement;
    shortcut: ShortcutBinding;
    capture?: boolean;
    showHint: () => void;
    hideHint: () => void;
    performAction: () => void;
};

type PendingSequence = {
    candidates: ShortcutRegistration[];
    stepIndex: number;
    modal: ReturnType<typeof getTopModal>;
    timer: number;
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

/** Detect editors and custom text controls, including those inside an open shadow root. */
function isSequenceTypingContext(event: Event): boolean {
    if (document.designMode === "on") return true;

    for (const target of event.composedPath()) {
        if (target instanceof Element && target.matches(SEQUENCE_EDITABLE_SELECTOR)) return true;
    }
    return false;
}

function isVisible(element: HTMLElement): boolean {
    if (!element.isConnected) return false;
    if (element.getClientRects().length === 0) return false;

    const style = window.getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden";
}

/** Exclude disabled controls, including native controls in a disabled fieldset. */
function isDisabled(element: HTMLElement): boolean {
    return element.hasAttribute("disabled") || element.matches(":disabled") || element.getAttribute("aria-disabled") === "true";
}

class ShortcutManager {
    private registrations = new Set<ShortcutRegistration>();
    private initialized = false;
    private revealModeActive = false;
    private revealTimer: number | undefined;
    private pendingSequence: PendingSequence | null = null;

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

    /** Listen for keyboard input and clear state when the interaction context changes. */
    private initialize(): void {
        if (this.initialized || typeof document === "undefined") return;

        document.addEventListener("keydown", this.cancelSequenceOnEscape, true);
        document.addEventListener("keydown", this.onCapturedKeyDown, true);
        document.addEventListener("keydown", (event: KeyboardEvent) => this.onKeyDown(event));
        document.addEventListener("keyup", (event: KeyboardEvent) => this.onKeyUp(event));
        document.addEventListener("focusin", this.cancelSequenceInEditor, true);
        document.addEventListener("pointerdown", this.cancelPendingSequence.bind(this), true);
        document.addEventListener("compositionstart", this.cancelPendingSequence.bind(this), true);
        window.addEventListener("blur", this.resetKeyboardState.bind(this));
        document.addEventListener("visibilitychange", this.onVisibilityChange.bind(this));

        this.initialized = true;
    }

    /** Dispatch opted-in modifier shortcuts before focused controls handle the key. */
    private onCapturedKeyDown = (event: KeyboardEvent): void => {
        if (event.defaultPrevented || event.isComposing || (!event.metaKey && !event.ctrlKey)) return;
        this.handleImmediateShortcut(event, true);
    };

    /** Preserve immediate shortcuts and advance sequences on eligible key presses. */
    private onKeyDown(event: KeyboardEvent): void {
        this.pruneDisconnected();

        if (this.isRevealKeyEvent(event)) {
            if (!event.altKey && !event.shiftKey && !(event.metaKey && event.ctrlKey)) {
                event.preventDefault();
                if (!event.repeat && !this.revealModeActive && this.revealTimer === undefined) {
                    this.revealTimer = window.setTimeout(this.setRevealMode.bind(this, true), SHORTCUT_REVEAL_DELAY_MS);
                }
            }
            return;
        }

        this.cancelPendingReveal();

        if (normalizeKeyboardEventKey(event) === "escape") {
            this.resetKeyboardState();
            return;
        }

        if (!this.handleImmediateShortcut(event, false)) this.handleSequenceKey(event);
    }

    /** Run the first active standalone shortcut registered for this event phase. */
    private handleImmediateShortcut(event: KeyboardEvent, capture: boolean): boolean {
        if (shouldIgnoreShortcutInEditableTarget(event)) return false;

        for (const registration of this.registrations) {
            if (Boolean(registration.capture) !== capture || !this.matchesRegistration(registration, event)) continue;

            this.cancelPendingSequence();
            event.preventDefault();
            if (capture) {
                this.cancelPendingReveal();
                event.stopPropagation();
            }
            if (!capture || !event.repeat) registration.performAction();
            return true;
        }
        return false;
    }

    /** End a pending or active reveal when the platform modifier is released. */
    private onKeyUp(event: KeyboardEvent): void {
        if (!this.isRevealKeyEvent(event)) return;

        this.setRevealMode(false);
    }

    /** Continue a pending sequence, or try the current key as a fresh prefix. */
    private handleSequenceKey(event: KeyboardEvent): void {
        if (event.defaultPrevented || event.isComposing || isSequenceTypingContext(event)) {
            this.cancelPendingSequence();
            return;
        }
        if (event.repeat || ["Alt", "AltGraph", "Control", "Meta", "Shift"].includes(event.key)) return;

        const pending = this.pendingSequence;
        if (pending && pending.modal === getTopModal()
            && this.advanceSequence(pending.candidates, pending.stepIndex, event)) return;

        this.cancelPendingSequence();
        this.advanceSequence(this.registrations, 0, event);
    }

    /** Complete a matching sequence or retain the eligible registrations for its next step. */
    private advanceSequence(registrations: Iterable<ShortcutRegistration>, stepIndex: number, event: KeyboardEvent): boolean {
        const candidates: ShortcutRegistration[] = [];
        for (const registration of registrations) {
            const { shortcut } = registration;
            if (!isShortcutSequence(shortcut) || !matchesShortcut(shortcut[stepIndex], event)
                || !this.registrations.has(registration) || !this.isRegistrationActive(registration)) continue;

            if (stepIndex === shortcut.length - 1) {
                this.cancelPendingSequence();
                event.preventDefault();
                registration.performAction();
                return true;
            }
            candidates.push(registration);
        }

        if (!candidates.length) return false;

        this.cancelPendingSequence();
        this.pendingSequence = {
            candidates,
            stepIndex: stepIndex + 1,
            modal: getTopModal(),
            timer: window.setTimeout(this.cancelPendingSequence.bind(this), SHORTCUT_SEQUENCE_TIMEOUT_MS),
        };
        event.preventDefault();
        return true;
    }

    /** Discard the pending steps and their timeout. */
    private cancelPendingSequence(): void {
        if (!this.pendingSequence) return;
        window.clearTimeout(this.pendingSequence.timer);
        this.pendingSequence = null;
    }

    /** Cancel an in-progress sequence even if a control handles Escape locally. */
    private cancelSequenceOnEscape = (event: KeyboardEvent): void => {
        if (event.key === "Escape") this.cancelPendingSequence();
    };

    /** Cancel the sequence as soon as focus enters a typing context. */
    private cancelSequenceInEditor = (event: FocusEvent): void => {
        if (this.pendingSequence && isSequenceTypingContext(event)) this.cancelPendingSequence();
    };

    /** Dismiss pending keyboard work when the document is no longer visible. */
    private onVisibilityChange(): void {
        if (document.visibilityState !== "visible") this.resetKeyboardState();
    }

    /** Clear keyboard state when the user cancels or leaves the window. */
    private resetKeyboardState(): void {
        this.cancelPendingSequence();
        this.setRevealMode(false);
    }

    /** Cancel a scheduled hint reveal before it becomes visible. */
    private cancelPendingReveal(): void {
        window.clearTimeout(this.revealTimer);
        this.revealTimer = undefined;
    }

    /** Update visible shortcut hints and clear any pending reveal. */
    private setRevealMode(active: boolean): void {
        this.cancelPendingReveal();
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

    /** Match a standalone shortcut in the current interaction scope. */
    private matchesRegistration(registration: ShortcutRegistration, event: KeyboardEvent): boolean {
        return !isShortcutSequence(registration.shortcut) && matchesShortcut(registration.shortcut, event)
            && this.isRegistrationActive(registration);
    }

    /** Restrict shortcuts to the active dialog so hidden parent forms cannot submit. */
    private isRegistrationActive(registration: ShortcutRegistration): boolean {
        const modal = getTopModal();
        return (!modal || modal.element.contains(registration.rootElement))
            && !registration.rootElement.closest('[inert]')
            && isVisible(registration.rootElement)
            && !isDisabled(registration.rootElement);
    }

    private pruneDisconnected(): void {
        for (const registration of Array.from(this.registrations)) {
            if (registration.rootElement.isConnected) continue;
            registration.hideHint();
            this.registrations.delete(registration);
        }
    }

    /** Identify the modifier used by shortcut chords on the current platform. */
    private isRevealKeyEvent(event: KeyboardEvent): boolean {
        return normalizeKeyboardEventKey(event) === (isMacPlatform() ? "meta" : "control");
    }
}

let shortcutManager: ShortcutManager | null = null;

export function getShortcutManager(): ShortcutManager {
    if (!shortcutManager) {
        shortcutManager = new ShortcutManager();
    }

    return shortcutManager;
}
