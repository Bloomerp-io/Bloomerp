import BaseComponent, { getComponent } from "./BaseComponent";
import { Modal } from "./Modal";
import htmx from "htmx.org";

export default class GlobalSearch extends BaseComponent {
    private headerButton: HTMLElement | null = null;
    private modalInput: HTMLInputElement | null = null;
    private resultsContainer: HTMLElement | null = null;
    private searchModal: Modal | null = null;
    private shortcutLabelEl: HTMLElement | null = null;
    private keyHandler: ((e: KeyboardEvent) => void) | null = null;
    private inputHandler: ((e: InputEvent) => void) | null = null;
    private inputKeyHandler: ((e: KeyboardEvent) => void) | null = null;
    private afterSwapHandler: ((e: Event) => void) | null = null;
    private resultsClickHandler: ((e: MouseEvent) => void) | null = null;
    private debounceTimer: number | null = null;
    private resultItems: HTMLElement[] = [];
    private activeIndex: number = -1;

    public initialize(): void {
        if (!this.element) return;

        this.headerButton = this.element.querySelector('#global-search-btn') as HTMLElement | null;
        this.modalInput = (this.element.querySelector('#global-search-modal-input') as HTMLInputElement | null)
            || (document.getElementById('global-search-modal-input') as HTMLInputElement | null);
        const modalEl = (this.element.querySelector('#global-search-modal') as HTMLElement | null)
            || (document.getElementById('global-search-modal') as HTMLElement | null);
        if (modalEl) {
            this.searchModal = getComponent(modalEl) as Modal;
        }

        // Results container inside modal
        this.resultsContainer = (this.element.querySelector('#global-search-results') as HTMLElement | null)
            || (document.getElementById('global-search-results') as HTMLElement | null);

        if (this.headerButton) {
            this.headerButton.addEventListener('click', (e) => {
                e.preventDefault();
                if (this.searchModal) {
                    this.searchModal.open();

                    // Focus the input after modal opens (give animation a moment)
                    setTimeout(() => {
                        if (this.modalInput) {
                            this.modalInput.focus();
                        }
                    }, 80);
                }
            });
        }

        // If an input inside the header (rare) is focused, open the modal too
        const headerInput = this.element.querySelector('#global-search-header-input') as HTMLInputElement | null;
        if (headerInput) {
            headerInput.addEventListener('focus', () => {
                if (this.searchModal) {
                    this.searchModal.open();
                    setTimeout(() => this.modalInput?.focus(), 80);
                }
            });
        }

        // Listen for typing in the modal input and query backend via HTMX (debounced)
        if (this.modalInput) {
            this.inputHandler = (e: InputEvent) => {
                if (!this.modalInput) return;
                const query = this.modalInput.value || '';

                if (this.debounceTimer) {
                    window.clearTimeout(this.debounceTimer);
                }

                this.debounceTimer = window.setTimeout(() => {
                    const url = '/components/global_search/';

                    htmx.ajax('get', url, { target: this.resultsContainer || undefined, swap: 'innerHTML', values: { q: query } });
                }, 300);
            };

            this.modalInput.addEventListener('input', this.inputHandler);

            this.inputKeyHandler = (e: KeyboardEvent) => {
                if (!this.resultsContainer) return;

                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    this.moveSelection(1);
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    this.moveSelection(-1);
                } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                    const activeItem = this.getActiveItem();
                    if (!activeItem) return;

                    const toggled = this.toggleSubmenuForItem(activeItem);
                    if (toggled) {
                        e.preventDefault();
                    }
                } else if (e.key === 'Enter') {
                    const activeItem = this.getActiveItem();
                    if (activeItem) {
                        e.preventDefault();
                        activeItem.click();
                        this.searchModal?.close();
                    }
                }
            };

            this.modalInput.addEventListener('keydown', this.inputKeyHandler);
        }

        // Set shortcut label based on platform and listen for Cmd/Ctrl+K
        const isMac = typeof navigator !== 'undefined' && ((navigator.platform && navigator.platform.toUpperCase().includes('MAC')) || (navigator.userAgent && navigator.userAgent.includes('Mac')));
        this.shortcutLabelEl = this.element.querySelector('#global-search-shortcut') as HTMLElement | null;
        if (this.shortcutLabelEl) {
            this.shortcutLabelEl.textContent = isMac ? '⌘K' : 'Ctrl+K';
        }

        this.keyHandler = (e: KeyboardEvent) => {
            const key = (e.key || '').toLowerCase();
            const openRouteSearch = ((isMac && e.metaKey) || (!isMac && e.ctrlKey)) && e.shiftKey && key === 'k';
            const openSearch = ((isMac && e.metaKey) || (!isMac && e.ctrlKey)) && !e.shiftKey && key === 'k';

            if (openRouteSearch) {
                e.preventDefault();
                this.openSearchModal('>');
                return;
            }

            if (openSearch) {
                e.preventDefault();
                this.openSearchModal();
            }
        };

        document.addEventListener('keydown', this.keyHandler);

        if (this.resultsContainer) {
            this.resultsClickHandler = (event: MouseEvent) => {
                const target = event.target as HTMLElement | null;
                const toggleButton = target?.closest<HTMLElement>('[data-global-search-toggle]');
                if (toggleButton) {
                    event.preventDefault();
                    event.stopPropagation();
                    this.toggleSubmenu(toggleButton, true);
                    return;
                }

                const clickedItem = target?.closest<HTMLElement>('[data-global-search-item]');
                if (clickedItem) {
                    this.searchModal?.close();
                }
            };

            this.resultsContainer.addEventListener('click', this.resultsClickHandler);
        }

        this.afterSwapHandler = (event: Event) => {
            const detail = (event as CustomEvent).detail;
            if (!detail || !this.resultsContainer) return;
            if (detail.target !== this.resultsContainer) return;
            this.refreshResultItems();
        };

        document.addEventListener('htmx:afterSwap', this.afterSwapHandler);
        
    }

    public destroy(): void {
        if (this.keyHandler) {
            document.removeEventListener('keydown', this.keyHandler);
            this.keyHandler = null;
        }

        if (this.inputHandler && this.modalInput) {
            this.modalInput.removeEventListener('input', this.inputHandler);
            this.inputHandler = null;
        }

        if (this.inputKeyHandler && this.modalInput) {
            this.modalInput.removeEventListener('keydown', this.inputKeyHandler);
            this.inputKeyHandler = null;
        }

        if (this.debounceTimer) {
            window.clearTimeout(this.debounceTimer);
            this.debounceTimer = null;
        }

        if (this.afterSwapHandler) {
            document.removeEventListener('htmx:afterSwap', this.afterSwapHandler);
            this.afterSwapHandler = null;
        }

        if (this.resultsClickHandler && this.resultsContainer) {
            this.resultsContainer.removeEventListener('click', this.resultsClickHandler);
            this.resultsClickHandler = null;
        }

        super.destroy();
    }

    private refreshResultItems(): void {
        if (!this.resultsContainer) return;

        this.resultItems = Array.from(
            this.resultsContainer.querySelectorAll<HTMLElement>('[data-global-search-item]')
        ).filter((item) => this.isItemVisible(item));
        this.activeIndex = this.resultItems.length > 0 ? 0 : -1;
        this.updateActiveStyles();
    }

    private moveSelection(delta: number): void {
        if (this.resultItems.length === 0) return;

        const nextIndex = (this.activeIndex + delta + this.resultItems.length) % this.resultItems.length;
        this.activeIndex = nextIndex;
        this.updateActiveStyles();
        this.scrollActiveItemIntoView();
    }

    private updateActiveStyles(): void {
        this.resultItems.forEach((item, index) => {
            const row = item.closest('[data-global-search-row]') as HTMLElement | null;
            if (!row) return;
            if (index === this.activeIndex) {
                row.classList.add('bg-primary-50', 'text-primary-900', 'ring-1', 'ring-primary-200');
                row.classList.remove('hover:bg-gray-50');
            } else {
                row.classList.remove('bg-primary-50', 'text-primary-900', 'ring-1', 'ring-primary-200');
                row.classList.add('hover:bg-gray-50');
            }
        });
    }

    private getActiveItem(): HTMLElement | null {
        if (this.activeIndex < 0 || this.activeIndex >= this.resultItems.length) {
            return null;
        }
        return this.resultItems[this.activeIndex];
    }

    private scrollActiveItemIntoView(): void {
        const activeItem = this.getActiveItem();
        if (!activeItem) return;
        const row = activeItem.closest('[data-global-search-row]') as HTMLElement | null;
        row?.scrollIntoView({ block: 'nearest' });
    }

    private openSearchModal(initialValue?: string): void {
        if (!this.searchModal) return;

        this.searchModal.open();
        setTimeout(() => {
            if (!this.modalInput) return;

            if (typeof initialValue === 'string') {
                this.modalInput.value = initialValue;
                this.modalInput.dispatchEvent(new InputEvent('input', { bubbles: true }));
            }

            this.modalInput.focus();
            const cursorPosition = this.modalInput.value.length;
            this.modalInput.setSelectionRange(cursorPosition, cursorPosition);
        }, 80);
    }

    private isItemVisible(item: HTMLElement): boolean {
        return !item.closest('.hidden');
    }

    private toggleSubmenuForItem(item: HTMLElement): boolean {
        const parentItem = item.closest<HTMLElement>('[data-global-search-parent-item]');
        if (!parentItem) return false;

        const row = parentItem.closest('[data-global-search-row]') as HTMLElement | null;
        const toggleButton = row?.querySelector<HTMLElement>('[data-global-search-toggle]') || null;
        if (!toggleButton) return false;

        return this.toggleSubmenu(toggleButton, true);
    }

    private toggleSubmenu(toggleButton: HTMLElement, focusFirstChild: boolean): boolean {
        if (!this.resultsContainer) return false;

        const submenuId = toggleButton.dataset.globalSearchSubmenuId;
        if (!submenuId) return false;

        const submenu = this.resultsContainer.querySelector<HTMLElement>(`#${submenuId}`);
        if (!submenu) return false;

        const submenuItems = Array.from(
            submenu.querySelectorAll<HTMLElement>('[data-global-search-item]')
        );
        if (submenuItems.length === 0) return false;

        const isExpanded = toggleButton.getAttribute('aria-expanded') === 'true';
        const nextExpanded = !isExpanded;

        toggleButton.setAttribute('aria-expanded', nextExpanded ? 'true' : 'false');
        submenu.classList.toggle('hidden', !nextExpanded);

        const toggleIcon = toggleButton.querySelector<HTMLElement>('[data-global-search-toggle-icon]');
        toggleIcon?.classList.toggle('rotate-180', nextExpanded);

        const parentItem = toggleButton
            .closest('[data-global-search-row]')
            ?.querySelector<HTMLElement>('[data-global-search-parent-item]') || null;

        this.resultItems = Array.from(
            this.resultsContainer.querySelectorAll<HTMLElement>('[data-global-search-item]')
        ).filter((item) => this.isItemVisible(item));

        if (nextExpanded && focusFirstChild) {
            this.activeIndex = this.resultItems.findIndex((item) => item === submenuItems[0]);
        } else if (parentItem) {
            this.activeIndex = this.resultItems.findIndex((item) => item === parentItem);
        }

        if (this.activeIndex < 0 && this.resultItems.length > 0) {
            this.activeIndex = 0;
        }

        this.updateActiveStyles();
        this.scrollActiveItemIntoView();
        return true;
    }
}