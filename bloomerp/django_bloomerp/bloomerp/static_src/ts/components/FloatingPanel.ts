import BaseComponent from './BaseComponent';
import FloatingPanelLauncher from '../utils/FloatingPanelLauncher';

/** Shared floating shell; subclasses own the content and application state. */
export default class FloatingPanel extends BaseComponent {
    protected panel: HTMLElement | null = null;
    private previousFocus: HTMLElement | null = null;

    /** Bind shared opening, dismissal, focus restoration and draggable positioning. */
    protected initializeFloatingPanel(signal: AbortSignal): void {
        this.panel = this.element?.querySelector('[data-floating-panel]') ?? null;
        const launcher = this.element?.querySelector<HTMLButtonElement>('[data-floating-panel-launcher]');
        if (launcher && this.panel) new FloatingPanelLauncher(launcher, this.panel.dataset.launcherStorageKey || this.panel.id, signal);
        this.element?.addEventListener('click', this.onShellClick, { signal });
        document.addEventListener('keydown', this.onShellKeyDown, { signal });
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

    /** Hide the shell without discarding content and restore the user's focus. */
    protected close(): void {
        if (!this.panel) return;
        this.setPanelOpen(false);
        const launcher = this.element?.querySelector<HTMLElement>('[data-floating-panel-launcher]');
        (this.previousFocus?.isConnected ? this.previousFocus : launcher)?.focus();
    }

    /** Synchronize shell visibility, accessibility and tab-local refresh persistence. */
    private setPanelOpen(open: boolean): void {
        if (!this.panel) return;
        this.panel.hidden = !open;
        const launcher = this.element?.querySelector<HTMLElement>('[data-floating-panel-launcher]');
        if (launcher) { launcher.hidden = open; launcher.setAttribute('aria-expanded', String(open)); }
        try { sessionStorage.setItem(`${this.panel.dataset.launcherStorageKey || this.panel.id}:open`, String(open)); }
        catch { /* Storage is optional; controls continue to work. */ }
    }

    /** Skip controls in hidden content views when opening the panel. */
    private isVisibleControl(control: HTMLElement): boolean {
        return control.getClientRects().length > 0;
    }

    /** Dispatch only shell actions, leaving content controls to subclasses. */
    private onShellClick = (event: MouseEvent): void => {
        const action = (event.target as Element).closest<HTMLElement>('[data-floating-panel-action]')?.dataset.floatingPanelAction;
        if (action === 'open') this.open();
        else if (action === 'close') this.close();
    };

    /** Dismiss the focused panel with Escape without closing another open panel. */
    private onShellKeyDown = (event: KeyboardEvent): void => {
        if (event.key !== 'Escape' || this.panel?.hidden !== false || !this.element?.contains(event.target as Node)) return;
        event.preventDefault();
        event.stopPropagation();
        this.close();
    };
}
