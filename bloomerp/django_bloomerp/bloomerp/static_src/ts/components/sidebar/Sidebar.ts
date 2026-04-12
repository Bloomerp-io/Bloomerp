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

/**
 * Sidebar component to manage the behavior of the sidebar
 * in the Bloomerp application. The sidebar can be opened,
 * closed, and toggled, and its state can be queried.
 * 
 * The state of the sidebar is also stored in localStorage
 * to persist user preferences across sessions.
 */
export class Sidebar extends BaseComponent {
    private mainElement : HTMLElement | null;
    private overlayElement : HTMLElement | null;
    private sidebarButton : HTMLElement | null;
    private floatingButton : HTMLElement | null;
	private _isOpen : boolean;
	private readonly storageKey = 'bloomerp_sidebar_state';
    private hoverTimer: number | null = null;
    private activeDraggedItemId: string | null = null;
    private activeDraggedItemElement: HTMLElement | null = null;
    private activeDropzone: SidebarDropzone | null = null;

    // Buttons
    private selectSidebarBtn : HTMLButtonElement | null = null;
    private createSidebarBtn : HTMLButtonElement | null = null;
    

	public initialize(): void {
		this.mainElement = document.getElementById('main');
		this.overlayElement = document.getElementById('sidebar-overlay');
        this.sidebarButton = document.getElementById('sidebar-toggle')
        this.floatingButton = document.getElementById('sidebar-toggle-floating');

		// Get state
		const storedState = localStorage.getItem(this.storageKey);

		if (storedState !== null) {
            this._isOpen = storedState === 'true';
        } else {
            // Default: open on large screens (>= 1024px), closed on small
            this._isOpen = window.innerWidth >= 1024;
        }

		// Apply initial state
        this.updateUI();

        // Setup event listeners
        this.setupEventListeners();
        this.setupDragAndDrop();

        // Bind visibility handlers for the floating button (mouse/touch)
        this.bindFloatingVisibilityHandlers();
        
	}

    public override destroy(): void {
        if (!this.element) return;

        window.removeEventListener('mousemove', this.onWindowMouseMove);
        window.removeEventListener('touchstart', this.onWindowTouchStart);
        document.removeEventListener('dragover', this.onDocumentDragOver);
        document.removeEventListener('dragend', this.onDocumentDragEnd);
        document.removeEventListener('drop', this.onDocumentDrop);

        this.element.removeEventListener('dragstart', this.onDragStart);
        this.element.removeEventListener('dragend', this.onDragEnd);
        this.element.removeEventListener('dragover', this.onDragOver);
        this.element.removeEventListener('drop', this.onDrop);
    }

	private updateUI(): void {
        if (!this.element) return;

        if (this._isOpen) {
            // Open state: remove translate-x-full to show sidebar
            this.element.classList.remove('-translate-x-full');
            
            // Show overlay on mobile
            if (this.overlayElement) {
                this.overlayElement.classList.remove('hidden');
            }

            // Adjust main content margin
            if (this.mainElement) {
                this.mainElement.classList.add('lg:ml-64');
                this.mainElement.classList.remove('ml-2');
            }

            if (this.floatingButton) {
                this.floatingButton.classList.add('hidden');
            }
        } else {
            // Closed state: add translate-x-full to hide sidebar
            this.element.classList.add('-translate-x-full');
            
            // Hide overlay
            if (this.overlayElement) {
                this.overlayElement.classList.add('hidden');
            }

            // Adjust main content margin
            if (this.mainElement) {
                this.mainElement.classList.remove('lg:ml-64');
                this.mainElement.classList.add('ml-2');
            }

            if (this.floatingButton) {
                // Keep the floating button hidden by default when sidebar is closed;
                // visibility will be controlled by pointer/touch handlers.
                this.floatingButton.classList.add('hidden');
            }
        }
    }

    private bindFloatingVisibilityHandlers(): void {
        window.addEventListener('mousemove', this.onWindowMouseMove);
        window.addEventListener('touchstart', this.onWindowTouchStart, {passive:true});
    }

    private handlePointer(clientX: number, clientY: number): void {
        if (this._isOpen) return; // don't show floating when sidebar is open

        const nearLeft = clientX < 80 && clientY < 120;

        if (nearLeft) {
            if (this.hoverTimer) {
                window.clearTimeout(this.hoverTimer);
                this.hoverTimer = null;
            }
            this.showFloating();
        } else {
            if (!this.hoverTimer) {
                this.hoverTimer = window.setTimeout(() => {
                    this.hideFloating();
                    this.hoverTimer = null;
                }, 600);
            }
        }
    }

    private showFloating(): void {
        if (!this.floatingButton) return;
        this.floatingButton.classList.remove('hidden');
    }

    private hideFloating(): void {
        if (!this.floatingButton) return;
        this.floatingButton.classList.add('hidden');
    }

    private toggleFloatingByTouch(): void {
        if (!this.floatingButton) return;
        if (this.floatingButton.classList.contains('hidden')) {
            this.showFloating();
        } else {
            this.hideFloating();
        }
    }

	private setupEventListeners(): void {
        // Close on overlay click
        if (this.overlayElement) {
            this.overlayElement.addEventListener('click', () => {
                this.close();
            });
        }

        if (this.sidebarButton) {
			this.sidebarButton.addEventListener('click', () => {
				this.toggle()
			})
		}

        if (this.floatingButton) {
            this.floatingButton.addEventListener('click', () => {
                this.toggle()
            })
        }
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

    public toggle(): void {
        this._isOpen = !this._isOpen;
        this.saveState();
        this.updateUI();
    }

    public open(): void {
        if (this._isOpen) return;
        this._isOpen = true;
        this.saveState();
        this.updateUI();
    }

    public close(): void {
        if (!this._isOpen) return;
        this._isOpen = false;
        this.saveState();
        this.updateUI();
    }

    public isOpen(): boolean {
        return this._isOpen;
    }

    private saveState(): void {
        localStorage.setItem(this.storageKey, String(this._isOpen));
    }

    private readonly onWindowMouseMove = (event: MouseEvent): void => {
        this.handlePointer(event.clientX, event.clientY);
    };

    private readonly onWindowTouchStart = (): void => {
        this.toggleFloatingByTouch();
    };

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
