import BaseComponent, { getComponent } from '../BaseComponent';
import PageEditor from './PageEditor';
import htmx from 'htmx.org';
import { navigateAgentPage } from '@/utils/agent';

/** Keep the existing full-size layout while coordinating navigation and autosave. */
export default class PagesWorkspace extends BaseComponent {
    private readonly lifecycle = new AbortController();

    /** Bind page links and refresh grouped history after committed edits. */
    public initialize(): void {
        const options = { signal: this.lifecycle.signal };
        this.element.addEventListener('click', this.navigate, options);
        this.element.addEventListener('bloomerp:page-saved', this.saved, options);
        this.element.addEventListener('bloomerp:page-deleted', this.deleted, options);
        this.element.addEventListener('htmx:beforeCleanupElement', this.cleanup, options);
    }

    /** Resolve the single active editor for this workspace. */
    private editor(): PageEditor {
        return getComponent(this.element.querySelector<HTMLElement>('[bloomerp-component="bloomerp:page-editor"]')!) as PageEditor;
    }

    /** Save the current draft before switching to another page or an empty draft. */
    private navigate = async (event: MouseEvent): Promise<void> => {
        const link = (event.target as Element).closest<HTMLAnchorElement>('[data-pages-link]');
        if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return;
        event.preventDefault();
        if (await this.editor().flush()) await navigateAgentPage(link.pathname + link.search);
    };

    /** Keep the current URL and all history sections aligned without replacing the editor. */
    private saved = (event: Event): void => {
        const id = (event as CustomEvent<{ page: { id: string } }>).detail.page.id;
        const url = new URL(this.element.dataset.pagesUrl!, location.origin);
        url.searchParams.set('page', id);
        history.replaceState(history.state, '', url);
        const nav = this.element.querySelector<HTMLElement>('[data-pages-navigation]')!;
        void htmx.ajax('get', `${nav.dataset.navigationUrl}?page=${id}`, { target: nav, swap: 'innerHTML' });
    };

    /** Return to the last remaining edited page after explicit deletion. */
    private deleted = (): void => { void navigateAgentPage(this.element.dataset.pagesUrl!); };

    /** Release handlers when HTMX replaces the full workspace. */
    private cleanup = (event: Event): void => { if (event.target === this.element) this.destroy(); };

    /** Dispose listeners without altering the persisted page. */
    public override destroy(): void { this.lifecycle.abort(); super.destroy(); }
}
