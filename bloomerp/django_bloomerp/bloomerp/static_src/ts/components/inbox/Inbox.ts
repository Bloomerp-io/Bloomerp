import htmx from "htmx.org";
import BaseComponent from "../BaseComponent";
import { InboxItem } from "./InboxItem";
import getGeneralModal from "@/utils/modals";
import { insertSkeleton } from "@/utils/animations";
import { getCsrfToken } from "@/utils/cookies";

export class Inbox extends BaseComponent {
    private selectedItemId: string | null = null;
    private searchInput: HTMLInputElement | null = null;
    private searchInputHandler: (() => void) | null = null;
    private searchDebounceTimer: number | null = null;
    private inboxActionClickHandler: ((event: Event) => void) | null = null;
    private subfolderClickHandler: ((event: Event) => void) | null = null;
    private activeMailboxFilters = new Map<string, string>();
    private keyboardController: AbortController | null = null;
    private filterClickHandler: ((event: Event) => void) | null = null;

    /** Load the inbox and attach its local interaction handlers. */
    public initialize(): void {
        if (!this.element) return;

        // Initialy load inbox items
        this.queryInbox();

        // Setup event listeners
        this.setupAddFolderBtnListener();
        this.setupSelectFolderListener();
        this.setupSubfolderFilterListener();
        this.setupFilterListener();
        this.setupSearchInputListener();
        this.setupInboxActionListener();
        this.setupKeyboardNavigation();
        this.searchInput?.focus();
        
    }

    /** Navigate visible message rows without fetching a preview until activation. */
    private setupKeyboardNavigation(): void {
        this.keyboardController?.abort();
        this.keyboardController = new AbortController();
        this.element?.addEventListener('keydown', this.handleListKeydown, {
            signal: this.keyboardController.signal,
        });
        this.element?.addEventListener('focusin', this.handleRowFocus, {
            signal: this.keyboardController.signal,
        });
        this.element?.addEventListener('toggle', this.handleConversationToggle, {
            capture: true,
            signal: this.keyboardController.signal,
        });
    }

    /** Keep the root message's expanded state accessible after pointer or keyboard toggles. */
    private handleConversationToggle = (event: Event): void => {
        const conversation = event.target;
        if (!(conversation instanceof HTMLDetailsElement) || !conversation.hasAttribute('data-inbox-conversation')) return;
        conversation.querySelector('[data-inbox-row-button]')?.setAttribute('aria-expanded', String(conversation.open));
    };

    /** Move focus with arrows/Home/End; Enter opens a message and Space toggles its conversation. */
    private handleListKeydown = (event: KeyboardEvent): void => {
        const target = event.target as HTMLElement | null;
        const row = target?.closest<HTMLElement>('[data-inbox-row-button]');
        const fromSearch = target === this.searchInput;
        if (!row && !fromSearch) return;
        if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
        if (row && event.key === ' ') {
            event.preventDefault();
            const conversation = row.closest<HTMLDetailsElement>('[data-inbox-conversation]');
            if (!event.repeat && conversation?.querySelector('summary')?.contains(row)) {
                conversation.open = !conversation.open;
            }
            return;
        }
        const rows = Array.from(this.element?.querySelectorAll<HTMLElement>('#inbox-items [data-inbox-row-button]') || [])
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

    /** Exclude message bodies hidden by a collapsed conversation, even when they retain layout boxes. */
    private isVisibleRow(element: HTMLElement): boolean {
        const conversation = element.closest<HTMLDetailsElement>('[data-inbox-conversation]');
        if (conversation && !conversation.open && !conversation.querySelector('summary')?.contains(element)) {
            return false;
        }
        return element.getClientRects().length > 0;
    }

    /** Track the focused message so selection survives read-status fragment replacements. */
    private handleRowFocus = (event: FocusEvent): void => {
        const row = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-inbox-row-button]');
        if (!row) return;
        this.selectedItemId = row.closest<HTMLElement>('[data-inbox-item-id]')?.dataset.inboxItemId || null;
        this.updateRowSelection();
    };

    /** Highlight the complete selected row, including the conversation toggle. */
    private updateRowSelection(): void {
        for (const row of this.element?.querySelectorAll<HTMLElement>('[data-inbox-selection-row]') || []) {
            const item = row.querySelector<HTMLElement>('[data-inbox-item-id]');
            row.toggleAttribute('data-inbox-selected', !!this.selectedItemId && item?.dataset.inboxItemId === this.selectedItemId);
        }
    }

    /** Avoid repeating expanded conversations when their anchors cross pagination boundaries. */
    public override onAfterSwap(): void {
        this.updateRowSelection();
        const seen = new Set<string>();
        for (const group of this.element?.querySelectorAll<HTMLElement>('[data-inbox-group-id]') || []) {
            const key = group.dataset.inboxGroupId || '';
            if (seen.has(key)) group.remove();
            else seen.add(key);
        }
        for (const conversation of this.element?.querySelectorAll<HTMLDetailsElement>('[data-inbox-conversation]') || []) {
            conversation.querySelector('[data-inbox-row-button]')?.setAttribute('aria-expanded', String(conversation.open));
        }
    }

    /** Query the current account while retaining an explicitly selected mailbox. */
    private queryInbox(query?: Map<string, string>, folderId?: string): void {
        query = new Map([...this.activeMailboxFilters, ...(query || new Map<string, string>())]);
        folderId = folderId || this.getDataAttribute('inboxFolderId') || '';
        if (!folderId) return;
        const target = this.element?.querySelector('#inbox-items');
        insertSkeleton(target as HTMLElement);

        htmx.ajax(
            'get',
            this.getRenderInboxItemsUrl(folderId, query),
            {
                target: '#inbox-items'
            }
        ).then(() => {
            this.setupDeepSearchListener();
        })
    }

    private getInboxItems() : InboxItem[] {
        return []
    }


    private setupAddFolderBtnListener() {
        if (!this.element) return;

        const  addFolderBtn = this.element.querySelector('#add-folder-btn');

        if (addFolderBtn) {
            addFolderBtn.addEventListener('click', () => {
                const modal = getGeneralModal();

                htmx.ajax('get', this.getDataAttribute('addFolderComponentUrl'), {
                    target: modal.getBodyElement(),
                })

                modal.open()

            });
        }
    }

    private setupSelectFolderListener() {
        if (!this.element) return;

        // Get the select folder dropdown element
        const selectFolderDropdown = this.element.querySelector('#select-folder-dropdown');

        // Get all the items in the dropdown that start with select-folder-<folder_id>
        const folderItems = selectFolderDropdown?.querySelectorAll('[id^="select-folder-"]');

        // Add click event listeners to each folder item
        folderItems?.forEach((item) => {
            item.addEventListener('click', () => {
                const folderId = item.id.replace('select-folder-', '');
                const url = (this.getDataAttribute('selectInboxFolderUrl') || '')
                    .replace('REPLACE_WITH_ID', encodeURIComponent(folderId));
                if (!url) return;

                const values: Record<string, string> = {};
                const csrfToken = getCsrfToken();
                if (csrfToken) {
                    values.csrfmiddlewaretoken = csrfToken;
                }
                htmx.ajax('post', url, { values });
            });
        });
    }

    private setupSearchInputListener() {
        if (!this.element) return;

        this.searchInput = this.element.querySelector('#inbox-search-input') as HTMLInputElement;
        
        if (this.searchInput) {
            this.searchInputHandler = () => {
                if (this.searchDebounceTimer) {
                    window.clearTimeout(this.searchDebounceTimer);
                }

                this.searchDebounceTimer = window.setTimeout(() => {
                    const query = this.searchInput?.value.trim() || '';
                    const queryMap = new Map<string, string>();
                    if (query) {
                        queryMap.set('q', query);
                    }
                    this.queryInbox(queryMap);
                }, 250);
            };

            this.searchInput.addEventListener('input', this.searchInputHandler);
        }
    }

    private setupFilterListener() {
        if (!this.element) return;

        this.filterClickHandler = (event: Event) => {
            const trigger = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-inbox-filter-key]');
            if (!trigger || !this.element?.contains(trigger)) return;

            event.preventDefault();
            const rawFilters = trigger.dataset.inboxFilterFilters || '{}';
            let filters: Record<string, unknown>;
            try {
                filters = JSON.parse(rawFilters);
            } catch {
                return;
            }

            const queryMap = new Map<string, string>();
            Object.entries(filters).forEach(([key, value]) => {
                if (value !== null && value !== undefined) {
                    queryMap.set(key, String(value));
                }
            });
            this.queryInbox(queryMap);
        };

        this.element.addEventListener('click', this.filterClickHandler);
    }

    /** Keep subsequent searches scoped to the explicitly selected account and mailbox. */
    private setupSubfolderFilterListener(): void {
        if (!this.element) return;

        this.subfolderClickHandler = (event: Event): void => {
            const trigger = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-inbox-subfolder]');
            if (!trigger || !this.element?.contains(trigger)) return;

            event.preventDefault();
            const rawFilters = trigger.dataset.inboxSubfolderFilters || '{}';
            let filters: Record<string, string> = {};
            try {
                filters = JSON.parse(rawFilters);
            } catch {
                filters = {};
            }

            this.activeMailboxFilters = new Map(Object.entries(filters));
            const folderId = trigger.dataset.inboxSubfolderFolderId;
            if (folderId && this.element) this.element.dataset.inboxFolderId = folderId;
            this.queryInbox(this.activeMailboxFilters, folderId);
        };

        this.element.addEventListener('click', this.subfolderClickHandler);
    }

    private setupDeepSearchListener() {
        if (!this.element) return;

        const deepSearchBtn = this.element.querySelector('#deep-search-btn');

        if (deepSearchBtn) {
            deepSearchBtn.addEventListener('click', () => {
                const query = this.searchInput?.value.trim() || '';
                const queryMap = new Map<string, string>();
                if (query) {
                    queryMap.set('q', query);
                }
                queryMap.set('deep_search', 'true');
                this.queryInbox(queryMap);
            });
        }
    }

    private setupInboxActionListener() {
        if (!this.element) return;

        this.inboxActionClickHandler = (event: Event) => {
            const trigger = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-inbox-action]');
            if (!trigger || !this.element?.contains(trigger)) return;
            if (trigger.dataset.inboxActionLevel !== 'folder') return;

            event.preventDefault();
            this.executeInboxAction(trigger);
        };

        this.element.addEventListener('click', this.inboxActionClickHandler);
    }

    private executeInboxAction(trigger: HTMLElement) {
        const level = trigger.dataset.inboxActionLevel || '';
        const itemId = trigger.dataset.inboxActionItemId || '';
        const actionKey = trigger.dataset.inboxActionKey || '';
        const method = trigger.dataset.inboxActionMethod === 'post' ? 'post' : 'get';
        const target = this.resolveInboxActionTarget(trigger);
        const url = this.getExecuteInboxActionUrl(level, itemId, actionKey);
        

        if (!url || !target) return;

        const values: Record<string, string> | undefined = method === 'post' ? {} : undefined;
        const csrfToken = getCsrfToken();
        if (values && csrfToken) {
            values.csrfmiddlewaretoken = csrfToken;
        }

        htmx.ajax(method, url, {
            target,
            swap: 'innerHTML',
            values,
        });
    }

    private resolveInboxActionTarget(trigger: HTMLElement): HTMLElement | string | null {
        const target = trigger.dataset.inboxActionTarget;

        switch (target) {
            case 'modal': {
                const modal = getGeneralModal();
                modal.open();
                return modal.getBodyElement();
            }
            case 'items':
                return '#inbox-items';
            case 'message':
                return '#inbox-message-target';
            case 'render-item':
                return this.getDataAttribute('renderInboxItemTarget') || '#inbox-item-render-target';
            default:
                return '#inbox-message-target';
        }
    }

    private getExecuteInboxActionUrl(level: string, itemId: string, actionKey: string): string {
        const url = this.getDataAttribute('executeInboxActionUrl') || '';
        if (!url || !level || !itemId || !actionKey) return '';

        return url
            .replace('REPLACE_LEVEL', encodeURIComponent(level))
            .replace('REPLACE_WITH_ID', encodeURIComponent(itemId))
            .replace('REPLACE_ACTION_KEY', encodeURIComponent(actionKey));
    }

    /**
     * Returns the URL for rendering the inbox items for a specific folder.
     * @param folderId the ID of the folder for which to render inbox items.
     * @param query optional query parameters to append to the render URL.
     * @returns the URL for rendering the inbox items for the specified folder.
     */
    private getRenderInboxItemsUrl(folderId: string, query?: Map<string, string>): string {
        const url = this.getDataAttribute('inboxFolderItemsComponentUrl')?.replace('REPLACE_WITH_ID', folderId) || '';
        if (!query || query.size === 0) return url;

        const params = new URLSearchParams();
        query.forEach((value, key) => {
            if (value) {
                params.set(key, value);
            }
        });

        const queryString = params.toString();
        if (!queryString) return url;

        return `${url}${url.includes('?') ? '&' : '?'}${queryString}`;
    }


    /** Release listeners and timers owned by this inbox instance. */
    public destroy(): void {
        this.keyboardController?.abort();
        this.keyboardController = null;
        if (this.element && this.inboxActionClickHandler) {
            this.element.removeEventListener('click', this.inboxActionClickHandler);
        }
        if (this.element && this.subfolderClickHandler) {
            this.element.removeEventListener('click', this.subfolderClickHandler);
        }
        if (this.element && this.filterClickHandler) {
            this.element.removeEventListener('click', this.filterClickHandler);
        }
        if (this.searchInput && this.searchInputHandler) {
            this.searchInput.removeEventListener('input', this.searchInputHandler);
        }
        if (this.searchDebounceTimer) {
            window.clearTimeout(this.searchDebounceTimer);
        }
        this.searchInput = null;
        this.searchInputHandler = null;
        this.searchDebounceTimer = null;
        this.inboxActionClickHandler = null;
        this.subfolderClickHandler = null;
        this.filterClickHandler = null;
    }
}
