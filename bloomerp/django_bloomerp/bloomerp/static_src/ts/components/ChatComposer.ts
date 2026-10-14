import BaseComponent from './BaseComponent';

/** Share keyboard submission and editor accessibility without owning transport. */
export default class ChatComposer extends BaseComponent {
    private lifecycle = new AbortController();
    /** Bind the editor shortcut within this composer only. */
    public initialize(): void {
        const editor = this.element.querySelector<HTMLElement>('[contenteditable]');
        editor?.setAttribute('role', 'textbox');
        editor?.setAttribute('aria-multiline', 'true');
        editor?.setAttribute('aria-label', this.element.dataset.editorLabel!);
        this.element.addEventListener('keydown', this.onKeyDown.bind(this), { signal: this.lifecycle.signal });
        this.element.addEventListener('htmx:beforeCleanupElement', this.onCleanup.bind(this), { signal: this.lifecycle.signal });
    }
    /** Submit through the owning form, leaving ordinary Enter to the rich-text editor. */
    private onKeyDown(event: KeyboardEvent): void {
        if (event.key !== 'Enter' || !(event.metaKey || event.ctrlKey) || event.isComposing) return;
        event.preventDefault();
        const button = this.element.querySelector<HTMLButtonElement>('[data-chat-send]');
        if (!event.repeat && button && !button.disabled) this.element.closest('form')?.requestSubmit(button);
    }
    /** Release listeners when HTMX replaces this composer after successful submission. */
    private onCleanup(event: Event): void {
        if (event.target === this.element) this.destroy();
    }
    /** Release only composer-owned event listeners. */
    public override destroy(): void {
        this.lifecycle.abort();
        super.destroy();
    }
}
