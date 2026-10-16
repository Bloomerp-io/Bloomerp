import htmx from "htmx.org";
import BaseSectionedLayoutItem from "../layouts/BaseSectionedLayoutItem";
import getGeneralModal, { createModalInstance } from "@/utils/modals";
import type { Modal } from "../Modal";

export default class WorkspaceTile extends BaseSectionedLayoutItem {
    private icon = "";
    private title = "";
    private editButton: HTMLElement | null = null;
    private editButtonHandler: (() => void) | null = null;

    private expandedModal: Modal | null = null;
    private placeholder: HTMLElement | null = null;
    private expandButton: HTMLElement | null = null;
    private expandedLifecycle: AbortController | null = null;

    /** Initialize layout controls and the live tile expansion action. */
    public initialize(): void {
        super.initialize();
        if (!this.element) return;

        const tileId = this.element.dataset.tileId ?? "";
        if (tileId) {
            this.itemId = tileId;
        }

        this.editButton = this.element.querySelector<HTMLElement>('[data-layout-edit-item]');
        this.editButtonHandler = (): void => {
            const url = this.element?.dataset.layoutEditUrl;
            if (!url) return;
            const modal = getGeneralModal()
            modal.setSize('full')
            modal.setTitle('Update Tile')

            htmx.ajax(
                'get',
                url,
                {
                    target: modal.getBodyElement()
                }
            ).then(()=> {modal.open()})
        };
        this.editButton?.addEventListener('click', this.editButtonHandler);
        this.expandButton = this.element.querySelector('[data-tile-expand]');
        this.expandButton?.addEventListener('click', this.expand);
    }

    /** Restore live content before disposing the tile and its event handlers. */
    public override destroy(): void {
        this.restore();
        this.expandButton?.removeEventListener('click', this.expand);
        this.expandButton = null;
        if (this.editButton && this.editButtonHandler) {
            this.editButton.removeEventListener('click', this.editButtonHandler);
        }
        this.editButton = null;
        this.editButtonHandler = null;
        super.destroy();
    }

    /** Reuse rendered nodes in an isolated shared modal, preserving widget state and IDs. */
    private expand = (event: MouseEvent): void => {
        event.preventDefault();
        event.stopPropagation();
        if (!this.element?.isConnected || !this.expandButton || this.isEditMode || this.expandedModal) return;
        const modal = createModalInstance('bloomerp-general-use-modal', this.expandButton);
        const body = modal.getBodyElement();
        if (!body) {
            modal.destroy();
            return;
        }
        this.expandedModal = modal;
        this.placeholder = document.createElement('div');
        this.placeholder.style.gridColumn = this.element.style.gridColumn;
        this.placeholder.style.height = `${this.element.getBoundingClientRect().height}px`;
        this.element.before(this.placeholder);
        body.appendChild(this.element);
        this.element.classList.add('workspace-tile--expanded');
        modal.setTitle(this.element.querySelector('[data-detail-label]')?.textContent?.trim() || 'Tile');
        modal.setSize('lg');
        modal.toggleFullscreen();
        this.expandedLifecycle = new AbortController();
        const options = { signal: this.expandedLifecycle.signal };
        modal.element.addEventListener('bloomerp:modal-closed', this.restore, options);
        document.body.addEventListener('htmx:beforeHistorySave', this.restore, options);
        document.body.addEventListener('htmx:beforeSwap', this.handleTileSwap, options);
        document.body.addEventListener('htmx:beforeCleanupElement', this.handleSourceCleanup, { ...options, capture: true });
        modal.open();
    };

    /** Restore before whole-tile swaps so workspace reindexing includes the live tile. */
    private handleTileSwap = (event: Event): void => {
        const target = (event as CustomEvent<{ target?: HTMLElement }>).detail?.target;
        const workspace = this.placeholder?.closest('[bloomerp-component="workspace-container"]');
        if (target === this.element || (target?.matches('[bloomerp-component="workspace-tile"]') && workspace?.contains(target))) {
            this.restore();
        }
    };

    /** Return the tile before HTMX removes its workspace or replaces the expanded tile. */
    private handleSourceCleanup = (event: Event): void => {
        const removed = (event as CustomEvent<{ elt?: HTMLElement }>).detail?.elt;
        if (removed && (removed === this.element || (this.placeholder && removed.contains(this.placeholder)))) {
            this.restore();
        }
    };

    /** Put the same tile back before the disposable modal destroys its descendants. */
    private restore = (): void => {
        const modal = this.expandedModal;
        if (!modal) return;
        this.expandedModal = null;
        this.expandedLifecycle?.abort();
        this.expandedLifecycle = null;
        this.element?.classList.remove('workspace-tile--expanded');
        if (this.element && this.placeholder?.parentNode) this.placeholder.replaceWith(this.element);
        this.placeholder = null;
        modal.destroy();
        this.expandButton?.focus({ preventScroll: true });
    };

    public setIcon(icon: string): void {
        if (!this.element) return;

        this.icon = icon;
        const iconElement = this.element.querySelector<HTMLElement>("[data-tile-icon] i");
        if (iconElement) {
            iconElement.className = `fa ${icon}`;
        }
    }

    public setTitle(title: string): void {
        if (!this.element) return;

        this.title = title;
        const titleElement = this.element.querySelector<HTMLElement>("[data-tile-title]");
        if (titleElement) {
            titleElement.textContent = title;
        }
    }

    public getTileId(): string {
        return this.getLayoutItemId();
    }
}
