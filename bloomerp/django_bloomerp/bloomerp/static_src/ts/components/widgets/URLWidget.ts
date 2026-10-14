import { BaseWidget } from "./BaseWidget";

/** Editable URL field whose view action always uses the current input value. */
export default class URLWidget extends BaseWidget {
    private readonly handleClick = this.openURL.bind(this);
    private readonly handleInput = this.inputChanged.bind(this);

    /** Bind once to the wrapper so replaced inputs also work after an HTMX swap. */
    public initialize(): void {
        this.destroy();
        this.element?.addEventListener("click", this.handleClick);
        this.element?.addEventListener("input", this.handleInput);
        this.element?.addEventListener("change", this.handleInput);
        this.updateButton();
    }

    /** Remove all listeners when the component is discarded. */
    public destroy(): void {
        this.element?.removeEventListener("click", this.handleClick);
        this.element?.removeEventListener("input", this.handleInput);
        this.element?.removeEventListener("change", this.handleInput);
    }

    /** Reconcile the action after a partial render replaces the input. */
    public onAfterSwap(): void {
        this.updateButton();
    }

    /** Reconcile live values restored by browser history. */
    public onHistoryRestore(): void {
        this.updateButton();
    }

    /** Read the native input without keeping a stale copy of its value. */
    private input(): HTMLInputElement | null {
        return this.element?.querySelector<HTMLInputElement>('input[type="url"]') ?? null;
    }

    /** Return the raw scalar value used by form history and field behaviors. */
    public getValue(): string {
        return this.input()?.value ?? "";
    }

    /** Apply programmatic values and optionally notify the form change pipeline. */
    public setValue(value: unknown, emitChange: boolean = false): void {
        const input = this.input();
        if (!input) return;
        const previous = input.value;
        input.value = value == null ? "" : String(value);
        this.updateButton();
        if (emitChange && previous !== input.value) this.onChange();
    }

    /** Accept only absolute URL schemes supported by Django's URL validator. */
    private destination(): string | null {
        const input = this.input();
        if (!input || input.matches(":disabled")) return null;
        const value = input.value.trim();
        if (!value || !input.validity.valid) return null;
        try {
            const url = new URL(value);
            return ["http:", "https:", "ftp:", "ftps:"].includes(url.protocol) && url.hostname
                ? url.href : null;
        } catch {
            return null;
        }
    }

    /** Keep the native button keyboard-accessible only for a usable destination. */
    private updateButton(): void {
        const button = this.element?.querySelector<HTMLButtonElement>("[data-open-url]");
        if (button) button.disabled = this.destination() === null;
    }

    /** Refresh the action and report edits through the standard widget event. */
    private inputChanged(event: Event): void {
        if (event.target !== this.input()) return;
        this.updateButton();
        this.onChange();
    }

    /** Open the latest safe value without submitting the form or exposing an opener. */
    private openURL(event: MouseEvent): void {
        const target = event.target as Element | null;
        if (!target?.closest("[data-open-url]")) return;
        event.preventDefault();
        const destination = this.destination();
        this.updateButton();
        if (destination) window.open(destination, "_blank", "noopener,noreferrer");
    }
}
