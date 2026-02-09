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
    private debounceTimer: number | null = null;

    public initialize(): void {
        if (!this.element) return;

        this.headerButton = this.element.querySelector('#global-search-btn') as HTMLElement | null;
        this.modalInput = this.element.querySelector('#global-search-modal-input') as HTMLInputElement | null;
        const modalEl = this.element.querySelector('#global-search-modal') as HTMLElement | null;
        if (modalEl) {
            this.searchModal = getComponent(modalEl) as Modal;
        }

        // Results container inside modal
        this.resultsContainer = this.element.querySelector('#global-search-results') as HTMLElement | null;

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
        }

        // Set shortcut label based on platform and listen for Cmd/Ctrl+K
        const isMac = typeof navigator !== 'undefined' && ((navigator.platform && navigator.platform.toUpperCase().includes('MAC')) || (navigator.userAgent && navigator.userAgent.includes('Mac')));
        this.shortcutLabelEl = this.element.querySelector('#global-search-shortcut') as HTMLElement | null;
        if (this.shortcutLabelEl) {
            this.shortcutLabelEl.textContent = isMac ? '⌘K' : 'Ctrl+K';
        }

        this.keyHandler = (e: KeyboardEvent) => {
            const key = (e.key || '').toLowerCase();
            if ((isMac && e.metaKey && key === 'k') || (!isMac && e.ctrlKey && key === 'k')) {
                e.preventDefault();
                if (this.searchModal) {
                    this.searchModal.open();
                    setTimeout(() => this.modalInput?.focus(), 80);
                }
            }
        };

        document.addEventListener('keydown', this.keyHandler);
        
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

        if (this.debounceTimer) {
            window.clearTimeout(this.debounceTimer);
            this.debounceTimer = null;
        }

        super.destroy();
    }
}