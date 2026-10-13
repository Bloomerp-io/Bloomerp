import { BaseWidget } from './BaseWidget';

type MailboxValue = [string, boolean, boolean, string];

/** Edit mailbox presentation while keeping an unset color distinct from a picker default. */
export default class MailboxSettings extends BaseWidget {
    private lifecycle: AbortController | null = null;

    /** Synchronize the native color picker and register local change handlers. */
    public initialize(): void {
        this.lifecycle?.abort();
        this.lifecycle = new AbortController();
        this.refreshColor();
        this.element?.addEventListener('input', this.handleColorInput, { signal: this.lifecycle.signal });
        this.element?.addEventListener('click', this.handleClearColor, { signal: this.lifecycle.signal });
    }

    /** Return values in Django's compound-field order. */
    public getValue(): MailboxValue {
        return [
            this.input('[data-mailbox-label]')?.value || '',
            this.input('[data-mailbox-sent]')?.checked || false,
            this.input('[data-mailbox-main]')?.checked || false,
            this.input('[data-mailbox-color-value]')?.value || '',
        ];
    }

    /** Restore saved settings and update the picker without assigning a default color. */
    public setValue(value: unknown, emitChange: boolean = false): void {
        const settings = value && typeof value === 'object' ? value as Record<string, unknown> : {};
        const values = Array.isArray(value) ? value : [settings.label, settings.sent_folder, settings.main_folder, settings.color];
        const label = this.input('[data-mailbox-label]');
        const sent = this.input('[data-mailbox-sent]');
        const main = this.input('[data-mailbox-main]');
        const color = this.input('[data-mailbox-color-value]');
        if (label) label.value = String(values[0] ?? '');
        if (sent) sent.checked = Boolean(values[1]);
        if (main) main.checked = Boolean(values[2]);
        if (color) color.value = String(values[3] ?? '');
        this.refreshColor();
        if (emitChange) this.onChange();
    }

    /** Resolve one native input owned by this widget. */
    private input(selector: string): HTMLInputElement | null {
        return this.element?.querySelector<HTMLInputElement>(selector) || null;
    }

    /** Display the saved color or a neutral default and expose whether it can be cleared. */
    private refreshColor(): void {
        const color = this.input('[data-mailbox-color-value]')?.value || '';
        const picker = this.input('[data-mailbox-color-picker]');
        if (picker) picker.value = color || '#4154f1';
        const clear = this.element?.querySelector<HTMLButtonElement>('[data-mailbox-color-clear]');
        if (clear) clear.disabled = !color;
    }

    /** Store picked colors for ordinary form submission and mapping state snapshots. */
    private handleColorInput = (event: Event): void => {
        if (!(event.target instanceof HTMLInputElement) || !event.target.hasAttribute('data-mailbox-color-picker')) return;
        const stored = this.input('[data-mailbox-color-value]');
        if (stored) stored.value = event.target.value;
        this.refreshColor();
        this.onChange();
    };

    /** Remove the optional color without clearing the mailbox label or roles. */
    private handleClearColor = (event: MouseEvent): void => {
        const trigger = (event.target as HTMLElement | null)?.closest('[data-mailbox-color-clear]');
        if (!trigger) return;
        event.preventDefault();
        const stored = this.input('[data-mailbox-color-value]');
        if (stored) stored.value = '';
        this.refreshColor();
        this.onChange();
    };

    /** Release all listeners when the mailbox mapping is replaced. */
    public override destroy(): void {
        this.lifecycle?.abort();
        this.lifecycle = null;
        super.destroy();
    }
}
