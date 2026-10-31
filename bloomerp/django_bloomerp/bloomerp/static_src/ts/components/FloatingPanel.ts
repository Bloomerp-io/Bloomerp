import BaseComponent from './BaseComponent';

/** Shared floating shell; subclasses own the content and application state. */
export default class FloatingPanel extends BaseComponent {
    protected panel: HTMLElement | null = null;
    private previousFocus: HTMLElement | null = null;

    /** Bind persistent footer controls, panel switching and focus restoration. */
    protected initializeFloatingPanel(signal: AbortSignal): void {
        this.panel = this.element?.querySelector('[data-floating-panel]') ?? null;
        this.element?.addEventListener('click', this.onShellClick, { signal });
        document.addEventListener('keydown', this.onShellKeyDown, { signal });
        document.addEventListener('bloomerp:panel-opened', this.onPanelOpened, { signal });
        try { this.setPanelOpen(sessionStorage.getItem(`${this.panel?.dataset.launcherStorageKey || this.panel?.id}:open`) === 'true'); }
        catch { /* Visibility remains usable when storage is unavailable. */ }
    }

    /** Reveal the panel and focus the first visible content control. */
    protected open(): void {
        if (!this.panel) return;
        this.previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        this.setPanelOpen(true);
        Array.from(this.panel.querySelectorAll<HTMLElement>('[data-floating-panel-focus]'))
            .find(this.isVisibleControl)?.focus();
    }

    /** Hide the shell, optionally restoring focus when dismissal is explicit. */
    protected close(restoreFocus: boolean = true): void {
        if (!this.panel) return;
        this.setPanelOpen(false);
        if (!restoreFocus) return;
        const launcher = this.element?.querySelector<HTMLElement>('[data-floating-panel-launcher]');
        (this.previousFocus?.isConnected ? this.previousFocus : launcher)?.focus();
    }

    /** Synchronize shell visibility, accessibility and tab-local refresh persistence. */
    private setPanelOpen(open: boolean): void {
        if (!this.panel) return;
        this.panel.hidden = !open;
        const launcher = this.element?.querySelector<HTMLElement>('[data-floating-panel-launcher]');
        launcher?.setAttribute('aria-expanded', String(open));
        try { sessionStorage.setItem(`${this.panel.dataset.launcherStorageKey || this.panel.id}:open`, String(open)); }
        catch { /* Storage is optional; controls continue to work. */ }
        if (open) document.dispatchEvent(new CustomEvent('bloomerp:panel-opened', { detail: this.panel.id }));
    }

    /** Skip controls in hidden content views when opening the panel. */
    private isVisibleControl(control: HTMLElement): boolean {
        return control.getClientRects().length > 0;
    }

    /** Dispatch only shell actions, leaving content controls to subclasses. */
    private onShellClick = (event: MouseEvent): void => {
        const action = (event.target as Element).closest<HTMLElement>('[data-floating-panel-action]')?.dataset.floatingPanelAction;
        if (action === 'open') this.open();
        else if (action === 'toggle') {
            if (this.panel?.hidden) this.open();
            else this.close();
        }
        else if (action === 'close') this.close();
    };

    /** Close the other tool without stealing focus from the newly opened panel. */
    private onPanelOpened = (event: Event): void => {
        if (!(event instanceof CustomEvent) || event.detail === this.panel?.id || this.panel?.hidden !== false) return;
        this.close(false);
    };

    /** Dismiss the focused panel with Escape without closing another open panel. */
    private onShellKeyDown = (event: KeyboardEvent): void => {
        if (event.key !== 'Escape' || this.panel?.hidden !== false || !this.element?.contains(event.target as Node)) return;
        event.preventDefault();
        event.stopPropagation();
        this.close();
    };
}
