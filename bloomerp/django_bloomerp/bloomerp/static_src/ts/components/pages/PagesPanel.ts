import FloatingPanel from '../FloatingPanel';
import { getComponent } from '../BaseComponent';
import PageEditor from './PageEditor';
import htmx from 'htmx.org';
import { navigateAgentPage } from '@/utils/agent';
import { t as _ } from '@/utils/i18n';

/** Compact copy of the full editor using the agent panel's header history pattern. */
export default class PagesPanel extends FloatingPanel {
    private readonly lifecycle = new AbortController();
    private loading = false;

    /** Bind the existing floating shell, page navigation and grouped history controls. */
    public initialize(): void {
        // Capture fullscreen before the generic shell navigates, so autosave finishes first.
        this.element.addEventListener('click', this.controls, { capture: true, signal: this.lifecycle.signal });
        this.element.addEventListener('bloomerp:page-deleted', this.deleted, { signal: this.lifecycle.signal });
        this.initializeFloatingPanel(this.lifecycle.signal);
        if (this.panel && !this.panel.hidden) void this.load('');
    }

    /** Return the editor mounted inside this scratchpad, if it has been loaded. */
    private editor(): PageEditor | null {
        const root = this.element.querySelector<HTMLElement>('[bloomerp-component="bloomerp:page-editor"]');
        return root ? getComponent(root) as PageEditor : null;
    }

    /** Show the latest page while keeping existing unsaved scratchpad content mounted. */
    protected override open(): void {
        super.open();
        void this.openLatest();
    }

    /** Reopen the most recent page or focus the current draft if it cannot be saved. */
    private async openLatest(): Promise<void> {
        const editor = this.editor();
        if (!editor || await editor.flush()) await this.load('');
        else editor.focusBody();
    }

    /** Point fullscreen navigation at exactly the scratchpad's currently selected page. */
    protected override getFullscreenUrl(): URL {
        const url = super.getFullscreenUrl();
        const id = this.editor()?.element.dataset.pageId;
        if (id) url.searchParams.set('page', id);
        else url.searchParams.set('new', '1');
        return url;
    }

    /** Coordinate header actions and page history links with the same autosaving editor. */
    private controls = async (event: MouseEvent): Promise<void> => {
        const target = event.target as Element;
        const link = target.closest<HTMLAnchorElement>('[data-pages-link]');
        const fullscreen = target.closest('[data-floating-panel-action="fullscreen"]');
        const fresh = target.closest('[data-pages-new]');
        if (target.closest('[data-pages-history]')) {
            const history = this.element.querySelector<HTMLElement>('[data-pages-history-panel]')!;
            this.showHistory(history.hidden);
            if (history.hidden) {
                this.editor()?.focusBody();
            } else {
                const nav = history.querySelector<HTMLElement>('[data-pages-navigation]')!;
                await htmx.ajax('get', this.element.dataset.navigationUrl!, { target: nav, swap: 'innerHTML' });
            }
        } else if (link || fullscreen || fresh) {
            event.preventDefault();
            event.stopImmediatePropagation();
            if (this.editor() && !await this.editor()!.flush()) return;
            if (fullscreen) {
                const url = this.getFullscreenUrl();
                await navigateAgentPage(url.pathname + url.search);
                this.close(false);
            } else await this.load(fresh ? '?new=1' : new URL(link!.href).search);
        }
    };

    /** Toggle history in place just like the existing agent panel. */
    private showHistory(show: boolean): void {
        this.element.querySelector<HTMLElement>('[data-pages-history-panel]')!.hidden = !show;
        this.element.querySelector<HTMLElement>('[data-pages-content]')!.hidden = show;
    }

    /** Load the editor and focus it once visible unless the user has moved focus elsewhere. */
    private async load(search: string): Promise<void> {
        if (this.loading) return;
        const target = this.element.querySelector<HTMLElement>('[data-pages-content]')!;
        const previousFocus = document.activeElement;
        this.loading = true;
        try {
            await htmx.ajax('get', this.element.dataset.editorUrl! + search, { target, swap: 'innerHTML' });
            this.showHistory(false);
            if (document.activeElement === previousFocus || document.activeElement === document.body) {
                this.editor()?.focusBody();
            }
        } catch {
            if (!this.editor()) target.textContent = _('Could not load your pages.');
        } finally { this.loading = false; }
    }

    /** Select the latest remaining page after a confirmed deletion. */
    private deleted = (): void => { void this.load(''); };

    /** Release persistent shell listeners when the workspace is torn down. */
    public override destroy(): void { this.lifecycle.abort(); super.destroy(); }
}
