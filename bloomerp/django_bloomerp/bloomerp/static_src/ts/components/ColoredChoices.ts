import BaseComponent from './BaseComponent';

/** Keep the selected choice's color visible after user and programmatic changes. */
export default class ColoredChoices extends BaseComponent {
    private lifecycle: AbortController | null = null;

    /** Initialize the current select and bind listeners once per lifecycle. */
    public initialize(): void {
        if (!(this.element instanceof HTMLSelectElement)) return;
        this.lifecycle?.abort();
        this.lifecycle = new AbortController();
        this.element.addEventListener('change', this.updateColor, { signal: this.lifecycle.signal });
        this.updateColor();
    }

    /** Apply only validated hex colors from the currently selected option. */
    private updateColor = (): void => {
        if (!(this.element instanceof HTMLSelectElement)) return;
        const color: string = this.element.selectedOptions[0]?.dataset.choiceColor ?? '';
        this.element.style.borderLeft = /^#[0-9a-fA-F]{6}$/.test(color) ? `6px solid ${color}` : '';
    };

    /** Reconcile a select whose options were replaced by an HTMX swap. */
    public override onAfterSwap(): void {
        this.updateColor();
    }

    /** Release change listeners when the component is removed. */
    public override destroy(): void {
        this.lifecycle?.abort();
        this.lifecycle = null;
        super.destroy();
    }
}
