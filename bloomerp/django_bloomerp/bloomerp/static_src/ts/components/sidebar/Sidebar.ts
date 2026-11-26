import htmx from "htmx.org";

import BaseComponent from "../BaseComponent";
import { getCsrfToken } from "@/utils/cookies";
import showMessage from "@/utils/messages";
import { MessageType } from "../UiMessage";

type SidebarDropzone = HTMLElement;
type SidebarDropValues = {
    parent_item_id: string;
    position: string;
};

type GapDropzoneSize = 'resting' | 'dragging' | 'active';

const PREVIEW_EDGE_WIDTH = 6;
const PREVIEW_OPEN_DELAY_MS = 250;
const PREVIEW_CLOSE_DELAY_MS = 140;

/**
 * Sidebar component to manage the behavior of the sidebar
 * in the Bloomerp application. The sidebar can be opened,
 * closed, and toggled, and its state can be queried.
 * 
 * The state of the sidebar is also stored in localStorage
 * to persist user preferences across sessions.
 */
export class Sidebar extends BaseComponent {
    private mainElement: HTMLElement | null;
    private overlayElement: HTMLElement | null;
    private controlListeners: AbortController | null = null;
    private _isOpen: boolean;
    private readonly storageKey = 'bloomerp_sidebar_state';
    private readonly desktopViewport = window.matchMedia('(min-width: 64rem)');
    private previewWanted = false;
    private previewOpen = false;
    private previewTimer: number | undefined;
    private addendumResizeObserver: ResizeObserver | null = null;
    private activeDraggedItemId: string | null = null;
    private activeDraggedItemElement: HTMLElement | null = null;
    private activeDropzone: SidebarDropzone | null = null;

    /** Restore the sidebar preference and attach its controls and item handlers. */
    public override initialize(): void {
        this.mainElement = document.getElementById('main');
        this.overlayElement = document.getElementById('sidebar-overlay');
        this.addendumResizeObserver = new ResizeObserver(this.updateHeaderGeometry);

        const storedState = localStorage.getItem(this.storageKey);
        this._isOpen = storedState === null ? this.desktopViewport.matches : storedState === 'true';
        this.updateUI();

        this.setupEventListeners();
        this.setupDragAndDrop();
    }

    /** Release the sidebar's event listeners and pending preview. */
    public override destroy(): void {
        this.controlListeners?.abort();
        this.addendumResizeObserver?.disconnect();
        this.clearPreview();
        if (!this.element) return;

        document.removeEventListener('dragover', this.onDocumentDragOver);
        document.removeEventListener('dragend', this.onDocumentDragEnd);
        document.removeEventListener('drop', this.onDocumentDrop);

        this.element.removeEventListener('dragstart', this.onDragStart);
        this.element.removeEventListener('dragend', this.onDragEnd);
        this.element.removeEventListener('dragover', this.onDragOver);
        this.element.removeEventListener('drop', this.onDrop);
    }

    /** Reconnect sidebar header alignment after an out-of-band addendum swap. */
    public override onAfterSwap(): void {
        this.syncHeader();
    }

    /** Reconcile the cached header with the live sidebar state after navigation. */
    public override onHistoryRestore(): void {
        this.syncHeader();
    }

    /** Show a hover preview over the workspace and shift it only when pinned open. */
    private updateUI(): void {
        if (!this.element) return;

        const visible = this.isOpen();
        // Keep the preview inset while it slides out.
        if (visible) this.element.toggleAttribute('data-preview-layout', this.previewOpen);
        this.element.classList.toggle('-translate-x-full', !visible);
        this.element.inert = !visible;
        this.overlayElement?.classList.toggle('hidden', !this._isOpen);
        this.mainElement?.classList.toggle('lg:ml-64', this._isOpen);
        this.syncHeader();
    }

    /** Sync the toggle and observe the addendum while the sidebar is visible. */
    private readonly syncHeader = (): void => {
        this.updateHeaderToggle();
        this.addendumResizeObserver?.disconnect();
        if (!this.isOpen()) return;

        const addendum = this.mainElement?.querySelector('#htmx-addendum');
        if (addendum) this.addendumResizeObserver?.observe(addendum, {box: 'border-box'});
        this.updateHeaderGeometry();
    };

    /** Align the pinned logo to the addendum center or the hover panel to its lower edge. */
    private readonly updateHeaderGeometry = (): void => {
        const sidebar = this.element;
        const main = this.mainElement;
        if (!sidebar || !main || !this.isOpen()) return;

        const addendum = main.querySelector('#htmx-addendum')?.getBoundingClientRect();
        if (this.previewOpen || !addendum) sidebar.style.removeProperty('--sidebar-brand-height');

        if (this.previewOpen) {
            const top = Math.max(0, addendum?.bottom ?? 0);
            sidebar.style.setProperty('--sidebar-preview-top', `${top}px`);
            return;
        }

        const brand = sidebar.querySelector('[data-sidebar-brand]');
        if (!addendum || !brand) return;

        // The pinned logo stays with the sidebar when the workspace content scrolls.
        const contentScroll = main.querySelector('#main-content')?.scrollTop ?? 0;
        const center = addendum.top + addendum.height / 2 + main.scrollTop + contentScroll;
        const brandHeight = Math.max(0, 2 * (center - brand.getBoundingClientRect().top));
        sidebar.style.setProperty('--sidebar-brand-height', `${brandHeight}px`);
    };

    /** Track the addendum on scroll while the hover panel is open. */
    private readonly onWorkspaceScroll = (): void => {
        if (this.previewOpen) this.updateHeaderGeometry();
    }

    /** Find the current header button since HTMX replaces it during navigation. */
    private getHeaderToggle(): HTMLButtonElement | null {
        return this.mainElement?.querySelector<HTMLButtonElement>('#sidebar-toggle') ?? null;
    }

    /** Keep the current button's accessible label and icon in sync. */
    private readonly updateHeaderToggle = (): void => {
        const toggle = this.getHeaderToggle();
        if (!toggle) return;

        toggle.setAttribute('aria-expanded', String(this.isOpen()));
        const stateLabel = this._isOpen ? toggle.dataset.hideLabel : toggle.dataset.showLabel;
        const label = this.previewOpen ? toggle.dataset.pinLabel : stateLabel;
        if (label) toggle.setAttribute('aria-label', label);
    };

    /** Route clicks from the current toolbar button to the persistent sidebar. */
    private readonly onHeaderClick = (event: MouseEvent): void => {
        if (event.target instanceof Element && event.target.closest('#sidebar-toggle')) {
            this.toggle();
        }
    };

    /** Dismiss the mobile sidebar and return focus to the header button. */
    private readonly onDismiss = (): void => {
        this.close();
        this.getHeaderToggle()?.focus({preventScroll: true});
    };

    /** Bind sidebar controls, fragment updates, and desktop hover preview events. */
    private setupEventListeners(): void {
        this.controlListeners?.abort();
        this.controlListeners = new AbortController();
        const {signal} = this.controlListeners;

        this.overlayElement?.addEventListener('click', this.onDismiss, {signal});
        this.element?.querySelector('[data-sidebar-close]')?.addEventListener('click', this.onDismiss, {signal});
        this.mainElement?.addEventListener('click', this.onHeaderClick, {signal});
        this.mainElement?.addEventListener('htmx:afterSwap', this.syncHeader, {signal});
        this.mainElement?.addEventListener('scroll', this.onWorkspaceScroll, {capture: true, passive: true, signal});
        window.addEventListener('resize', this.updateHeaderGeometry, {passive: true, signal});
        document.addEventListener('pointermove', this.onPreviewPointerMove, {passive: true, signal});
        document.documentElement.addEventListener('pointerleave', this.onPreviewPointerLeave, {signal});
        window.addEventListener('blur', this.onPreviewPointerLeave, {signal});
        this.desktopViewport.addEventListener('change', this.onPreviewPointerLeave, {signal});
    }

    /** Follow the mouse across the left edge, toggle, and open preview panel. */
    private readonly onPreviewPointerMove = (event: PointerEvent): void => {
        if (event.pointerType !== 'mouse' || this._isOpen || !this.desktopViewport.matches) return;

        const target = event.target;
        const overSidebar = target instanceof Element && (
            target.closest('#sidebar-toggle') || (this.previewOpen && this.element?.contains(target))
        );
        this.setPreviewIntent(event.clientX < PREVIEW_EDGE_WIDTH || Boolean(overSidebar));
    };

    /** Cancel hover intent when the pointer leaves the page or the preview loses its viewport. */
    private readonly onPreviewPointerLeave = (): void => {
        this.setPreviewIntent(false);
    };

    /** Wait for steady hover and allow the mouse to cross from the toggle into the panel. */
    private setPreviewIntent(wanted: boolean): void {
        if (wanted === this.previewWanted) return;

        this.previewWanted = wanted;
        window.clearTimeout(this.previewTimer);
        this.previewTimer = undefined;
        if (wanted === this.previewOpen) return;

        this.previewTimer = window.setTimeout(
            this.applyPreviewIntent,
            wanted ? PREVIEW_OPEN_DELAY_MS : PREVIEW_CLOSE_DELAY_MS,
        );
    }

    /** Apply the temporary state without changing the saved sidebar preference. */
    private readonly applyPreviewIntent = (): void => {
        this.previewTimer = undefined;
        const focusWasInside = this.element?.contains(document.activeElement);
        this.previewOpen = this.previewWanted;
        this.updateUI();
        if (!this.previewOpen && focusWasInside) this.getHeaderToggle()?.focus({preventScroll: true});
    };

    /** Clear the preview and its timer before pinning the sidebar or releasing the component. */
    private clearPreview(): void {
        window.clearTimeout(this.previewTimer);
        this.previewTimer = undefined;
        this.previewWanted = false;
        this.previewOpen = false;
    }

    private setupDragAndDrop(): void {
        if (!this.element) return;

        this.element.addEventListener('dragstart', this.onDragStart);
        this.element.addEventListener('dragend', this.onDragEnd);
        this.element.addEventListener('dragover', this.onDragOver);
        this.element.addEventListener('drop', this.onDrop);

        document.addEventListener('dragover', this.onDocumentDragOver);
        document.addEventListener('dragend', this.onDocumentDragEnd);
        document.addEventListener('drop', this.onDocumentDrop);
    }

    /** Switch the sidebar between its expanded and collapsed states. */
    public toggle(): void {
        if (this._isOpen) this.close();
        else this.open();
    }

    /** Pin the sidebar open and focus its dismiss button on mobile. */
    public open(): void {
        if (this._isOpen) return;
        this._isOpen = true;
        this.clearPreview();
        this.saveState();
        this.updateUI();
        this.element?.querySelector<HTMLButtonElement>('[data-sidebar-close]')?.focus({preventScroll: true});
    }

    /** Close the sidebar and return any focus inside it to the workspace. */
    public close(): void {
        if (!this._isOpen) return;
        const focusWasInside = this.element?.contains(document.activeElement);
        this._isOpen = false;
        this.saveState();
        this.updateUI();
        if (focusWasInside) this.getHeaderToggle()?.focus({preventScroll: true});
    }

    /** Return whether the sidebar is visible, including during a hover preview. */
    public isOpen(): boolean {
        return this._isOpen || this.previewOpen;
    }

    private saveState(): void {
        localStorage.setItem(this.storageKey, String(this._isOpen));
    }

    private readonly onDragStart = (event: DragEvent): void => {
        if (!this.element) return;

        const target = event.target as HTMLElement | null;
        const draggable = target?.closest<HTMLElement>('[data-sidebar-item-draggable]');
        if (!draggable || !this.element.contains(draggable)) return;

        const itemId = draggable.dataset.sidebarItemId ?? '';
        const itemRoot = draggable.closest<HTMLElement>('[data-sidebar-item-root]');
        if (!itemId || !itemRoot) return;

        this.activeDraggedItemId = itemId;
        this.activeDraggedItemElement = itemRoot;
        draggable.classList.add('opacity-60');
        this.setSidebarDragActive(true);

        if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('application/x-bloomerp-sidebar-item', itemId);
        }
    };

    private readonly onDragEnd = (): void => {
        this.resetDragState();
    };

    private readonly onDocumentDragEnd = (): void => {
        this.resetDragState();
    };

    private readonly onDocumentDragOver = (event: DragEvent): void => {
        if (!this.element) return;

        const dragKind = this.getDragKind(event.dataTransfer);
        const isInsideSidebar = event.target instanceof HTMLElement && this.element.contains(event.target);

        this.setSidebarDragActive(Boolean(dragKind && isInsideSidebar));
        if (!isInsideSidebar) {
            this.clearActiveDropzone();
        }
    };

    private readonly onDocumentDrop = (): void => {
        window.setTimeout(() => {
            this.clearActiveDropzone();
            this.setSidebarDragActive(false);
        }, 0);
    };

    private readonly onDragOver = (event: DragEvent): void => {
        const dragKind = this.getDragKind(event.dataTransfer);
        this.setSidebarDragActive(Boolean(dragKind));

        const dropzone = this.resolveDropzone(event.target);

        if (!dropzone || !dragKind || !this.canDropOnZone(dropzone, dragKind)) {
            this.clearActiveDropzone();
            return;
        }

        event.preventDefault();
        if (event.dataTransfer) {
            event.dataTransfer.dropEffect = dragKind === 'item' ? 'move' : 'copy';
        }
        this.setActiveDropzone(dropzone);
    };

    private readonly onDrop = async (event: DragEvent): Promise<void> => {
        const dropzone = this.resolveDropzone(event.target);
        const dragKind = this.getDragKind(event.dataTransfer);

        if (!dropzone || !dragKind || !this.canDropOnZone(dropzone, dragKind)) {
            this.resetDragState();
            return;
        }

        event.preventDefault();

        if (dragKind === 'item') {
            await this.moveDraggedItem(dropzone);
        } else {
            await this.createDroppedLink(event.dataTransfer, dropzone);
        }

        this.resetDragState();
    };

    private getSidebarContentElement(): HTMLElement | null {
        return this.element?.querySelector<HTMLElement>('[data-sidebar-content]') ?? null;
    }

    private getSidebarContentDataset(): DOMStringMap | null {
        return this.getSidebarContentElement()?.dataset ?? null;
    }

    private resolveDropzone(target: EventTarget | null): SidebarDropzone | null {
        if (!this.element || !(target instanceof HTMLElement)) return null;

        const dropzone = target.closest<HTMLElement>('[data-sidebar-dropzone], [data-sidebar-folder-dropzone]');
        if (!dropzone || !this.element.contains(dropzone)) return null;
        return dropzone;
    }

    private getDragKind(dataTransfer: DataTransfer | null): 'item' | 'url' | null {
        if (this.activeDraggedItemId) {
            return 'item';
        }

        if (!dataTransfer) return null;

        const types = Array.from(dataTransfer.types ?? []);
        if (types.includes('text/uri-list') || types.includes('text/html')) {
            return 'url';
        }

        return types.includes('text/plain') ? 'url' : null;
    }

    private canDropOnZone(dropzone: SidebarDropzone, dragKind: 'item' | 'url'): boolean {
        if (dragKind === 'url') {
            return true;
        }

        if (!this.activeDraggedItemId || !this.activeDraggedItemElement) {
            return false;
        }

        const targetParentId = dropzone.dataset.dropParentId ?? '';
        if (targetParentId && targetParentId === this.activeDraggedItemId) {
            return false;
        }

        return !this.activeDraggedItemElement.contains(dropzone);
    }

    private setActiveDropzone(dropzone: SidebarDropzone): void {
        if (this.activeDropzone === dropzone) return;

        this.clearActiveDropzone();
        this.activeDropzone = dropzone;

        if (dropzone.hasAttribute('data-sidebar-folder-dropzone')) {
            dropzone.classList.add('ring-2', 'ring-primary/30', 'bg-primary/5');
            return;
        }

        this.applyGapDropzoneSize(dropzone, 'active');
        dropzone.classList.add('sidebar-dropzone-active', 'border-primary/40', 'bg-primary/5');
    }

    private setSidebarDragActive(isActive: boolean): void {
        const contentElement = this.getSidebarContentElement();
        contentElement?.classList.toggle('sidebar-drag-active', isActive);

        contentElement
            ?.querySelectorAll<HTMLElement>('[data-sidebar-gap-dropzone]')
            .forEach((dropzone) => {
                if (dropzone === this.activeDropzone) return;
                this.applyGapDropzoneSize(dropzone, isActive ? 'dragging' : 'resting');
            });
    }

    private clearActiveDropzone(): void {
        if (!this.activeDropzone) return;

        if (this.activeDropzone.hasAttribute('data-sidebar-gap-dropzone')) {
            this.applyGapDropzoneSize(
                this.activeDropzone,
                this.getSidebarContentElement()?.classList.contains('sidebar-drag-active') ? 'dragging' : 'resting',
            );
        }

        this.activeDropzone.classList.remove(
            'sidebar-dropzone-active',
            'ring-2',
            'ring-primary/30',
            'bg-primary/5',
            'border-primary/40',
        );
        this.activeDropzone = null;
    }

    private resetDragState(): void {
        const draggable = this.activeDraggedItemElement?.querySelector<HTMLElement>('[data-sidebar-item-draggable]');
        draggable?.classList.remove('opacity-60');

        this.activeDraggedItemId = null;
        this.activeDraggedItemElement = null;
        this.clearActiveDropzone();
        this.setSidebarDragActive(false);
    }

    private applyGapDropzoneSize(dropzone: HTMLElement, size: GapDropzoneSize): void {
        dropzone.classList.remove('h-1', 'my-0', 'h-4', 'my-1', 'h-10', 'my-2');

        if (size === 'active') {
            dropzone.classList.add('h-10', 'my-2');
            return;
        }

        if (size === 'dragging') {
            dropzone.classList.add('h-4', 'my-1');
            return;
        }

        dropzone.classList.add('h-1', 'my-0');
    }

    private getDropValues(dropzone: SidebarDropzone): SidebarDropValues {
        return {
            parent_item_id: dropzone.dataset.dropParentId ?? '',
            position: dropzone.dataset.dropPosition ?? '0',
        };
    }

    private async moveDraggedItem(dropzone: SidebarDropzone): Promise<void> {
        const dataset = this.getSidebarContentDataset();
        const moveUrl = dataset?.sidebarMoveUrl;
        if (!moveUrl || !this.activeDraggedItemId) return;

        const result = await this.postSidebarAction(moveUrl, {
            item_id: this.activeDraggedItemId,
            ...this.getDropValues(dropzone),
        });

        if (!result.ok) {
            showMessage(result.message, MessageType.ERROR);
            return;
        }

        await this.refreshSidebarContent();
    }

    private async createDroppedLink(dataTransfer: DataTransfer | null, dropzone: SidebarDropzone): Promise<void> {
        const dataset = this.getSidebarContentDataset();
        const createUrl = dataset?.sidebarDropLinkUrl;
        if (!createUrl || !dataTransfer) return;

        const droppedLink = this.extractDroppedLink(dataTransfer);
        if (!droppedLink) return;

        const result = await this.postSidebarAction(createUrl, {
            name: droppedLink.name,
            url: droppedLink.url,
            ...this.getDropValues(dropzone),
        });

        if (!result.ok) {
            showMessage(result.message, MessageType.ERROR);
            return;
        }

        await this.refreshSidebarContent();
        showMessage(result.message, MessageType.SUCCESS);
    }

    private async postSidebarAction(
        url: string,
        values: Record<string, string>,
    ): Promise<{ ok: boolean; message: string }> {
        const csrfToken = getCsrfToken() || '';
        const body = new URLSearchParams({
            ...values,
            csrfmiddlewaretoken: csrfToken,
        });

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
                },
                body,
            });

            const data = await response.json();
            return {
                ok: Boolean(response.ok && data.ok),
                message: data.message || 'Unable to update the sidebar.',
            };
        } catch (error) {
            console.error('Sidebar drag-and-drop request failed', error);
            return {
                ok: false,
                message: 'Unable to update the sidebar.',
            };
        }
    }

    private async refreshSidebarContent(): Promise<void> {
        const refreshUrl = this.getSidebarContentDataset()?.sidebarRefreshUrl;
        if (!refreshUrl) return;

        await htmx.ajax('get', refreshUrl, {
            target: '#sidebar-content',
            swap: 'outerHTML',
        });
    }

    private extractDroppedLink(dataTransfer: DataTransfer): { url: string; name: string } | null {
        const rawUrl = this.extractUrlFromTransfer(dataTransfer);
        if (!rawUrl) return null;

        const normalizedUrl = this.normalizeDroppedUrl(rawUrl);
        const name = this.extractDroppedLinkName(dataTransfer, normalizedUrl);
        return { url: normalizedUrl, name };
    }

    private extractUrlFromTransfer(dataTransfer: DataTransfer): string | null {
        const uriList = dataTransfer.getData('text/uri-list');
        if (uriList) {
            const firstUrl = uriList
                .split('\n')
                .map((entry) => entry.trim())
                .find((entry) => entry && !entry.startsWith('#'));
            if (firstUrl) {
                return firstUrl;
            }
        }

        const html = dataTransfer.getData('text/html');
        if (html) {
            const parsedDocument = new DOMParser().parseFromString(html, 'text/html');
            const anchorHref = parsedDocument.querySelector('a')?.getAttribute('href')?.trim();
            if (anchorHref) {
                return anchorHref;
            }
        }

        const plainText = dataTransfer.getData('text/plain').trim();
        if (this.looksLikeUrl(plainText)) {
            return plainText;
        }

        return null;
    }

    private normalizeDroppedUrl(rawUrl: string): string {
        try {
            const parsed = new URL(rawUrl, window.location.origin);
            if (parsed.origin === window.location.origin) {
                return `${parsed.pathname}${parsed.search}${parsed.hash}`;
            }
            return parsed.href;
        } catch {
            return rawUrl.trim();
        }
    }

    private extractDroppedLinkName(dataTransfer: DataTransfer, normalizedUrl: string): string {
        const html = dataTransfer.getData('text/html');
        if (html) {
            const parsedDocument = new DOMParser().parseFromString(html, 'text/html');
            const anchorText = parsedDocument.querySelector('a')?.textContent?.trim();
            if (anchorText) {
                return anchorText;
            }
        }

        const plainText = dataTransfer.getData('text/plain').trim();
        if (plainText && plainText !== normalizedUrl && !this.looksLikeUrl(plainText)) {
            return plainText;
        }

        return this.humanizeUrl(normalizedUrl);
    }

    private looksLikeUrl(value: string): boolean {
        if (!value) return false;
        if (value.startsWith('/')) return true;

        try {
            const parsed = new URL(value);
            return parsed.protocol === 'http:' || parsed.protocol === 'https:';
        } catch {
            return false;
        }
    }

    private humanizeUrl(url: string): string {
        try {
            const parsed = new URL(url, window.location.origin);
            const candidate = parsed.origin === window.location.origin
                ? parsed.pathname.split('/').filter(Boolean).pop() || 'home'
                : parsed.hostname.replace(/^www\./, '').split('.')[0];

            return candidate
                .replace(/[-_]+/g, ' ')
                .split(' ')
                .filter(Boolean)
                .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
                .join(' ') || 'New link';
        } catch {
            return 'New link';
        }
    }
}
