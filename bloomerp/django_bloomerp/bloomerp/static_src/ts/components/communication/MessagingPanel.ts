import { getComponent } from '../BaseComponent';
import FloatingPanel from '../FloatingPanel';
import Conversation from './Conversation';

/** Own the floating messaging shell while conversation fragments remain reusable. */
export default class MessagingPanel extends FloatingPanel {
    private lifecycle = new AbortController();

    /** Bind navigation once and connect the persistent Chat footer control. */
    public initialize(): void {
        this.lifecycle.abort();
        this.lifecycle = new AbortController();
        const signal = this.lifecycle.signal;
        this.initializeFloatingPanel(signal);
        this.element.addEventListener('click', this.onClick, { signal });
        this.element.addEventListener('im:conversation-opened', this.onConversationOpened, { signal });
        this.element.addEventListener('im:selection-opened', this.onConversationOpened, { signal });
        this.element.addEventListener('keydown', this.onKeyDown, { signal });
        this.element.addEventListener('voip:incoming', this.onIncomingCall, { signal });
        this.element.addEventListener('htmx:responseError', this.onError, { signal });
        this.element.addEventListener('htmx:sendError', this.onError, { signal });
        this.element.addEventListener('input', this.onDraftChanged, { signal });
        this.element.addEventListener('bloomerp:references-changed', this.onDraftChanged, { signal });
        this.element.addEventListener('im:message-sent', this.onDraftChanged, { signal });
        document.addEventListener('htmx:beforeCleanupElement', this.onCleanup, { signal });
    }

    /** Carry the selected transcript, thread, rich-text draft and list search into the page. */
    protected override getFullscreenUrl(): URL {
        const url = super.getFullscreenUrl();
        const node = this.element.querySelector<HTMLElement>('[bloomerp-component="bloomerp:im-conversation"]');
        const conversation = node ? getComponent(node) : null;
        if (node?.dataset.conversationId) url.searchParams.set('conversation', node.dataset.conversationId);
        if (node?.dataset.threadId) url.searchParams.set('thread', node.dataset.threadId);
        const draft = conversation instanceof Conversation ? conversation.getDraft() : '';
        if (draft) url.searchParams.set('query', draft);
        const search = this.find<HTMLInputElement>('[data-search]').value;
        if (search) url.searchParams.set('q', search);
        return url;
    }

    /** Save page edits after the shared editor has synchronized its HTML. */
    private onDraftChanged = (): void => {
        if (!this.element.querySelector('[bloomerp-component="bloomerp:im-conversation"]')
            && new URL(window.location.href).searchParams.has('conversation')) return;
        this.syncPageUrl();
    };

    /** Reveal incoming-call controls even when the messaging panel was closed. */
    private onIncomingCall = (): void => { this.open(); };

    /** Resolve shell markup without reaching into another component instance. */
    private find<T extends HTMLElement = HTMLElement>(selector: string): T {
        return this.element.querySelector<T>(selector)!;
    }

    /** Switch between the conversation list and the selected chat. */
    private onClick = (event: MouseEvent): void => {
        const action = (event.target as HTMLElement).closest<HTMLElement>('[data-action]')?.dataset.action;
        if (action === 'chat' || action === 'back') {
            const chatting = action === 'chat';
            this.find('[data-chat-view]').hidden = !chatting;
            this.find('[data-list-view]').hidden = chatting && !this.isPage;
            this.find('[data-action="back"]').hidden = !chatting || this.isPage;
            this.find('[data-load-error]').hidden = true;
            if (chatting) {
                const host = this.find('[data-conversation-host]');
                for (const component of host.querySelectorAll<HTMLElement>('[bloomerp-component]')) getComponent(component)?.destroy();
                host.replaceChildren();
            }
            if (!this.isPage) this.find(chatting ? '[data-action="back"]' : '[data-search]').focus();
        }
    };

    /** Reveal a successfully created conversation and dismiss the header dropdowns. */
    private onConversationOpened = (): void => {
        this.find('[data-chat-view]').hidden = false;
        this.find('[data-list-view]').hidden = !this.isPage;
        this.find('[data-action="back"]').hidden = this.isPage;
        this.find('[data-load-error]').hidden = true;
        for (const dropdown of this.element.querySelectorAll('[bloomerp-component="dropdown-keyboard"]')) {
            dropdown.dispatchEvent(new CustomEvent('dropdown-dismiss', { bubbles: true }));
        }
        if (!this.isPage) this.find('[data-action="back"]').focus();
    };

    /** Keep errors visible without injecting an error response into the thread. */
    private onError = (): void => {
        this.find('[data-load-error]').hidden = false;
    };

    /** Follow inbox focus navigation and activate rows separately. */
    private onKeyDown = (event: KeyboardEvent): void => {
        const target = event.target as HTMLElement | null;
        const row = target?.closest<HTMLButtonElement>('.im-conversation');
        const fromSearch = target === this.find('[data-search]');
        if ((!row && !fromSearch) || this.find('[data-list-view]').hidden) return;
        if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
        const rows = Array.from(this.element.querySelectorAll<HTMLButtonElement>('[data-conversation-list] .im-conversation'))
            .filter(this.isVisibleRow);
        if (!rows.length) return;
        const index = row ? rows.indexOf(row) : -1;
        let next = index;
        if (event.key === 'ArrowDown') next = Math.min(index + 1, rows.length - 1);
        else if (event.key === 'ArrowUp' && row) next = Math.max(index - 1, 0);
        else if (event.key === 'Home' && row) next = 0;
        else if (event.key === 'End' && row) next = rows.length - 1;
        else return;
        event.preventDefault();
        rows[next]?.focus();
    };

    /** Exclude conversation rows outside the visible list, as inbox navigation does. */
    private isVisibleRow(element: HTMLElement): boolean {
        return element.getClientRects().length > 0;
    }

    /** Update the footer unread count after a conversation list is loaded. */
    public override onAfterSwap(): void {
        const total = this.element.querySelector<HTMLElement>('[data-unread-total]');
        const count = this.find('[data-count]');
        if (total && count) {
            const unread = Number(total.dataset.unreadTotal || 0);
            count.textContent = String(unread);
            count.hidden = unread === 0;
        }
        const selected = this.element.querySelector<HTMLElement>('[bloomerp-component="bloomerp:im-conversation"]');
        if (selected) {
            this.syncPageUrl();
            for (const row of this.element.querySelectorAll<HTMLElement>('.im-conversation')) {
                if (row.dataset.conversationId === selected.dataset.conversationId) row.setAttribute('aria-current', 'true');
                else row.removeAttribute('aria-current');
            }
        }
    }

    /** Release page listeners when HTMX removes this host or its containing page. */
    private onCleanup = (event: Event): void => {
        const removed = (event as CustomEvent<{elt?: Element}>).detail?.elt;
        if (removed?.contains(this.element)) this.destroy();
    };

    /** Release panel navigation and shared footer listeners. */
    public override destroy(): void {
        this.lifecycle.abort();
        super.destroy();
    }
}
