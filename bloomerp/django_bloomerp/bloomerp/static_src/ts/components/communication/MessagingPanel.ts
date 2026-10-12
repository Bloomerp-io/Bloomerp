import { getComponent } from '../BaseComponent';
import FloatingPanel from '../FloatingPanel';

/** Own the floating messaging shell while conversation fragments remain reusable. */
export default class MessagingPanel extends FloatingPanel {
    private lifecycle = new AbortController();

    /** Bind navigation once and reuse the draggable launcher behavior. */
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
    }

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
            this.find('[data-list-view]').hidden = chatting;
            this.find('[data-action="back"]').hidden = !chatting;
            this.find('[data-load-error]').hidden = true;
            if (chatting) {
                const host = this.find('#im-conversation-host');
                for (const component of host.querySelectorAll<HTMLElement>('[bloomerp-component]')) getComponent(component)?.destroy();
                host.replaceChildren();
            }
            this.find(chatting ? '[data-action="back"]' : '[data-search]').focus();
        }
    };

    /** Reveal a successfully created conversation and dismiss the standard dropdown. */
    private onConversationOpened = (): void => {
        this.find('[data-chat-view]').hidden = false;
        this.find('[data-list-view]').hidden = true;
        this.find('[data-action="back"]').hidden = false;
        this.find('[data-load-error]').hidden = true;
        this.element.querySelector('[bloomerp-component="dropdown-keyboard"]')?.dispatchEvent(new CustomEvent('dropdown-dismiss', { bubbles: true }));
        this.find('[data-action="back"]').focus();
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
        const rows = Array.from(this.element.querySelectorAll<HTMLButtonElement>('#im-conversations .im-conversation'))
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

    /** Update the orb count after an unfiltered conversation list is loaded. */
    public override onAfterSwap(): void {
        const total = this.element.querySelector<HTMLElement>('[data-unread-total]');
        if (!total) return;
        const unread = Number(total.dataset.unreadTotal || 0);
        this.find('[data-count]').textContent = String(unread);
        this.find('[data-count]').hidden = unread === 0;
    }

    /** Release shell listeners and drag resources. */
    public override destroy(): void {
        this.lifecycle.abort();
        super.destroy();
    }
}
