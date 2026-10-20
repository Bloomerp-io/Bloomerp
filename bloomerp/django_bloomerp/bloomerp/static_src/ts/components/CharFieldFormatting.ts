import BaseComponent from './BaseComponent';

/** Apply layout-configured case and whitespace rules as a text input is edited. */
export default class CharFieldFormatting extends BaseComponent {
    private lifecycle: AbortController | null = null;

    /** Bind input normalization before bubbling form behavior listeners run. */
    public initialize(): void {
        if (!(this.element instanceof HTMLInputElement)) return;
        this.lifecycle?.abort();
        this.lifecycle = new AbortController();
        const options: AddEventListenerOptions = { signal: this.lifecycle.signal, capture: true };
        this.element.addEventListener('input', this.onInput, options);
        this.element.addEventListener('compositionend', this.onInput, options);
    }

    /** Normalize a string using only supported settings from this input. */
    private normalize(value: string): string {
        if (this.element.dataset.formatting === 'uppercase') value = value.toUpperCase();
        if (this.element.dataset.formatting === 'lowercase') value = value.toLowerCase();
        switch (this.element.dataset.spaces) {
            case 'dash': return value.replace(/\s/g, '-');
            case 'underscore': return value.replace(/\s/g, '_');
            case 'remove': return value.replace(/\s/g, '');
            default: return value;
        }
    }

    /** Transform typed or pasted text while preserving the caret and IME input. */
    private onInput = (event: Event): void => {
        if (!(this.element instanceof HTMLInputElement)) return;
        if (event instanceof InputEvent && event.isComposing) return;
        const input: HTMLInputElement = this.element;
        const original: string = input.value;
        const normalized: string = this.normalize(original);
        if (normalized === original) return;
        const start: number | null = input.selectionStart;
        const end: number | null = input.selectionEnd;
        const direction: 'forward' | 'backward' | 'none' | null = input.selectionDirection;
        input.value = normalized;
        if (start !== null && end !== null) {
            input.setSelectionRange(
                this.normalize(original.slice(0, start)).length,
                this.normalize(original.slice(0, end)).length,
                direction,
            );
        }
    };

    /** Release listeners before disposing of the component. */
    public override destroy(): void {
        this.lifecycle?.abort();
        this.lifecycle = null;
        super.destroy();
    }
}
