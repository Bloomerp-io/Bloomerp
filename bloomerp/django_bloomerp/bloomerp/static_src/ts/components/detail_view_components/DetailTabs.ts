import htmx from 'htmx.org';

import BaseComponent from '../BaseComponent';
import { getCsrfToken } from '../../utils/cookies';
import { getContextMenu, type ContextMenuItem } from '../../utils/contextMenu';
import getGeneralModal from '../../utils/modals';

type TabMeta = {
    id: string;
    name: string;
    url: string;
    active?: boolean;
};

type TabItemPayload = {
    id: string;
    name: string;
    url: string | null;
    parent_id: string | null;
    position: number;
};

type TabItemSavedDetail = {
    mode: 'create' | 'edit';
    item_type: 'folder' | 'url';
    item_id: string;
    name: string;
    url: string;
};

export default class DetailTabs extends BaseComponent {
    private stripContainer: HTMLElement | null = null;
    private stripList: HTMLElement | null = null;
    private canManage = false;
    private activeId: string | null = null;
    private saveTimer: number | null = null;

    private draggedTopLevel: HTMLElement | null = null;
    private draggedFolderTab: HTMLElement | null = null;
    private draggedFolderSource: HTMLElement | null = null;

    private readonly clickHandler = (event: Event) => this.onClick(event);
    private readonly contextMenuHandler = (event: MouseEvent) => this.onContextMenu(event);
    private readonly dragStartHandler = (event: DragEvent) => this.onDragStart(event);
    private readonly dragEndHandler = () => this.clearDragState();
    private readonly dragOverHandler = (event: DragEvent) => this.onDragOver(event);
    private readonly dropHandler = (event: DragEvent) => this.onDrop(event);
    private readonly documentClickHandler = (event: MouseEvent) => this.onDocumentClick(event);
    private readonly keydownHandler = (event: KeyboardEvent) => this.onKeyDown(event);
    private readonly modalSavedHandler = (event: Event) => this.onModalSaved(event as CustomEvent<TabItemSavedDetail>);
    private readonly modalInputHandler = (event: Event) => this.onModalInput(event);

    public initialize(): void {
        if (!this.element) return;

        this.stripContainer = this.element.querySelector('[data-tabs-strip-container]');
        this.stripList = this.element.querySelector('[data-tabs-strip]');
        if (!this.stripContainer || !this.stripList) return;

        this.canManage = this.element.dataset.canManage === 'true';
        this.activeId = this.findActiveId();
        this.element.addEventListener('click', this.clickHandler);
        document.addEventListener('click', this.documentClickHandler);
        document.addEventListener('keydown', this.keydownHandler);

        if (this.canManage) {
            this.setDraggableState();
            this.stripContainer.addEventListener('contextmenu', this.contextMenuHandler);
            this.element.addEventListener('dragstart', this.dragStartHandler);
            this.element.addEventListener('dragend', this.dragEndHandler);
            this.stripContainer.addEventListener('dragover', this.dragOverHandler);
            this.stripContainer.addEventListener('drop', this.dropHandler);

            document.addEventListener('detail-tabs-item-saved', this.modalSavedHandler);
            const modalBody = document.getElementById('bloomerp-general-use-modal-body');
            modalBody?.addEventListener('input', this.modalInputHandler);
        }

        this.applyActiveStyles();
    }

    public destroy(): void {
        this.element?.removeEventListener('click', this.clickHandler);
        this.stripContainer?.removeEventListener('contextmenu', this.contextMenuHandler);
        this.element?.removeEventListener('dragstart', this.dragStartHandler);
        this.element?.removeEventListener('dragend', this.dragEndHandler);
        this.stripContainer?.removeEventListener('dragover', this.dragOverHandler);
        this.stripContainer?.removeEventListener('drop', this.dropHandler);
        document.removeEventListener('click', this.documentClickHandler);
        document.removeEventListener('keydown', this.keydownHandler);

        const modalBody = document.getElementById('bloomerp-general-use-modal-body');
        document.removeEventListener('detail-tabs-item-saved', this.modalSavedHandler);
        modalBody?.removeEventListener('input', this.modalInputHandler);

        if (this.saveTimer) window.clearTimeout(this.saveTimer);
        this.saveTimer = null;
        this.clearDragState();
    }

    private setDraggableState(): void {
        this.getTopLevelItems().forEach((item) => item.setAttribute('draggable', 'true'));
        this.getFolderItems().forEach((folder) => {
            this.getFolderTabs(folder).forEach((tab) => tab.setAttribute('draggable', 'true'));
        });
    }

    private onClick(event: Event): void {
        const target = event.target as HTMLElement | null;
        if (!target) return;

        const folderToggle = target.closest<HTMLElement>('[data-folder-toggle]');
        if (folderToggle) {
            event.preventDefault();
            const folder = folderToggle.closest<HTMLElement>('[data-tab-type="folder"]');
            if (folder) this.toggleFolder(folder);
            return;
        }

        const tab = target.closest<HTMLElement>('[data-tab-link], [data-folder-tab-item]');
        if (tab) {
            const item = tab.closest<HTMLElement>('[data-tab-item]');
            this.activeId = tab.dataset.itemId || item?.dataset.itemId || null;
            this.applyActiveStyles();
            this.closeFolders();
        }
    }

    private onContextMenu(event: MouseEvent): void {
        event.preventDefault();
        const target = event.target as HTMLElement;
        const folderTab = target.closest<HTMLElement>('[data-folder-tab-item]');
        const topLevelItem = target.closest<HTMLElement>('[data-tab-item]');

        if (folderTab) {
            event.stopPropagation();
            this.showTabMenu(event, folderTab);
            return;
        }

        if (topLevelItem) {
            event.stopPropagation();
            if (topLevelItem.dataset.tabType === 'folder') {
                this.showFolderMenu(event, topLevelItem);
            } else {
                this.showTabMenu(event, topLevelItem);
            }
            return;
        }

        const menu: ContextMenuItem[] = [
            { label: 'Create folder', onClick: () => this.openItemModal('folder', 'create') },
            { label: 'Create URL', onClick: () => this.openItemModal('url', 'create') },
        ];
        getContextMenu('detail-tabs-strip-menu').show(event, this.stripContainer as HTMLElement, menu);
    }

    private showFolderMenu(event: MouseEvent, folder: HTMLElement): void {
        getContextMenu('detail-tabs-folder-menu').show(event, folder, [
            {
                label: 'Edit',
                onClick: () => this.openItemModal('folder', 'edit', {
                    id: folder.dataset.itemId || '',
                    name: folder.dataset.itemName || '',
                    url: '',
                }),
            },
            { label: 'Delete', onClick: () => this.deleteFolder(folder) },
        ]);
    }

    private showTabMenu(event: MouseEvent, tab: HTMLElement): void {
        const meta = this.extractTabMeta(tab);
        if (!meta) return;

        const menu: ContextMenuItem[] = [
            { label: 'Edit', onClick: () => this.openItemModal('url', 'edit', meta) },
            { label: 'Delete', onClick: () => this.deleteTab(tab) },
        ];
        for (const folder of this.getFolderItems()) {
            if (tab.closest('[data-tab-type="folder"]') === folder) continue;
            menu.push({
                label: `Move to "${folder.dataset.itemName || 'Folder'}"`,
                onClick: () => this.moveTabIntoFolder(tab, folder),
            });
        }
        getContextMenu('detail-tabs-tab-menu').show(event, tab, menu);
    }

    private onDragStart(event: DragEvent): void {
        const target = event.target as HTMLElement;
        const folderTab = target.closest<HTMLElement>('[data-folder-tab-item]');
        if (folderTab) {
            this.draggedFolderTab = folderTab;
            this.draggedFolderSource = folderTab.closest('[data-tab-type="folder"]');
            folderTab.classList.add('opacity-50');
        } else {
            this.draggedTopLevel = target.closest<HTMLElement>('[data-tab-item]');
            this.draggedTopLevel?.classList.add('opacity-50');
        }
        if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
    }

    private onDragOver(event: DragEvent): void {
        const target = event.target as HTMLElement;
        const folder = target.closest<HTMLElement>('[data-tab-type="folder"]');
        const hasExternalLink = this.hasExternalLinkDrag(event.dataTransfer);

        if (folder && (this.draggedFolderTab || this.draggedTopLevel?.dataset.tabType === 'tab' || hasExternalLink)) {
            event.preventDefault();
            folder.classList.add('ring-2', 'ring-primary/40');

            if (this.draggedFolderTab && target.closest('[data-folder-tabs]')) {
                const panel = this.getFolderPanel(folder);
                const after = panel ? this.getVerticalDragAfterElement(panel, event.clientY) : null;
                if (panel) panel.insertBefore(this.draggedFolderTab, after);
            }
            return;
        }

        if (this.draggedTopLevel) {
            event.preventDefault();
            const after = this.getHorizontalDragAfterElement(event.clientX);
            this.stripList?.insertBefore(this.draggedTopLevel, after);
            return;
        }

        if (this.draggedFolderTab || hasExternalLink) event.preventDefault();
    }

    private onDrop(event: DragEvent): void {
        event.preventDefault();
        const target = event.target as HTMLElement;
        const folder = target.closest<HTMLElement>('[data-tab-type="folder"]');

        if (folder && this.draggedTopLevel?.dataset.tabType === 'tab') {
            this.moveTabIntoFolder(this.draggedTopLevel, folder);
        } else if (folder && this.draggedFolderTab) {
            this.moveTabIntoFolder(this.draggedFolderTab, folder);
        } else if (this.draggedFolderTab) {
            this.moveFolderTabToTopLevel(this.draggedFolderTab, event.clientX);
        } else if (!this.draggedTopLevel) {
            const dropped = this.getDroppedLink(event.dataTransfer);
            if (dropped) {
                const tab = this.createTopLevelTab(dropped);
                const after = this.getHorizontalDragAfterElement(event.clientX);
                this.stripList?.insertBefore(tab, after);
            }
        }

        this.clearDragState();
        this.updateAllFolderEmptyStates();
        this.scheduleSave();
    }

    private moveTabIntoFolder(tab: HTMLElement, folder: HTMLElement): void {
        const meta = this.extractTabMeta(tab);
        const panel = this.getFolderPanel(folder);
        if (!meta || !panel) return;

        if (tab.matches('[data-folder-tab-item]')) {
            panel.appendChild(tab);
        } else {
            const folderTab = this.createTabLink(meta, true);
            panel.appendChild(folderTab);
            tab.remove();
            htmx.process(folderTab);
        }
        this.closeFolders();
        this.updateAllFolderEmptyStates();
        this.scheduleSave();
    }

    private moveFolderTabToTopLevel(tab: HTMLElement, clientX: number): void {
        const meta = this.extractTabMeta(tab);
        if (!meta) return;
        const item = this.createTopLevelTab(meta);
        const after = this.getHorizontalDragAfterElement(clientX);
        this.stripList?.insertBefore(item, after);
        tab.remove();
        htmx.process(item);
    }

    private deleteTab(tab: HTMLElement): void {
        tab.closest('[data-tab-item]')?.matches('[data-tab-type="tab"]')
            ? tab.closest('[data-tab-item]')?.remove()
            : tab.remove();
        this.updateAllFolderEmptyStates();
        this.scheduleSave();
    }

    private deleteFolder(folder: HTMLElement): void {
        const anchor = folder.nextSibling;
        for (const tab of this.getFolderTabs(folder)) {
            const meta = this.extractTabMeta(tab);
            if (!meta) continue;
            const item = this.createTopLevelTab(meta);
            this.stripList?.insertBefore(item, anchor);
            htmx.process(item);
        }
        folder.remove();
        this.closeFolders();
        this.scheduleSave();
    }

    private openItemModal(
        itemType: 'folder' | 'url',
        mode: 'create' | 'edit',
        item?: TabMeta,
    ): void {
        if (!this.element) return;
        const url = this.element.dataset.itemModalUrl;
        const contentTypeId = this.element.dataset.contentTypeId;
        if (!url || !contentTypeId) return;

        const modal = getGeneralModal();
        modal.setTitle(`${mode === 'edit' ? 'Edit' : 'Create'} ${itemType === 'folder' ? 'Folder' : 'URL'}`);
        htmx.ajax('get', url, {
            target: modal.getBodyElement(),
            swap: 'innerHTML',
            push: 'false',
            values: {
                content_type_id: contentTypeId,
                item_type: itemType,
                mode,
                item_id: item?.id || '',
                name: item?.name || '',
                url: item?.url || '',
            },
        }).then(() => modal.open());
    }

    private onModalInput(event: Event): void {
        const urlInput = (event.target as HTMLElement).closest<HTMLInputElement>('[data-detail-tab-url-input]');
        if (!urlInput) return;
        const modalBody = document.getElementById('bloomerp-general-use-modal-body');
        const nameInput = modalBody?.querySelector<HTMLInputElement>('[data-detail-tab-name-input]');
        const options = modalBody?.querySelectorAll<HTMLOptionElement>('datalist option') || [];
        const match = Array.from(options).find((option) => option.value === urlInput.value);
        if (match && nameInput) nameInput.value = match.dataset.name || match.textContent || '';
    }

    private onModalSaved(event: CustomEvent<TabItemSavedDetail>): void {
        const { mode, item_type: type, name, url } = event.detail;
        const id = event.detail.item_id || this.generateId();

        if (mode === 'edit') {
            const item = this.findItem(id);
            if (item && type === 'folder') this.updateFolder(item, name);
            if (item && type === 'url') this.updateTab(item, { id, name, url });
        } else if (type === 'folder') {
            this.stripList?.appendChild(this.createFolder(id, name));
        } else if (type === 'url') {
            const item = this.createTopLevelTab({ id, name, url });
            this.stripList?.appendChild(item);
            htmx.process(item);
        }

        this.setDraggableState();
        this.scheduleSave();
        getGeneralModal().close();
    }

    private createFolder(id: string, name: string): HTMLElement {
        const folder = document.createElement('li');
        folder.dataset.tabItem = '';
        folder.dataset.tabType = 'folder';
        folder.dataset.itemId = id;
        folder.dataset.itemName = name;
        folder.className = 'relative shrink-0 cursor-pointer select-none border-b-2 border-transparent';
        folder.innerHTML = `
            <button type="button" data-folder-toggle class="h-full w-full px-4 py-2 text-sm whitespace-nowrap focus:outline-none focus:ring-2 focus:ring-primary-500 hover:bg-gray-50"></button>
            <div data-folder-tabs class="absolute left-0 top-full z-50 mt-1 hidden min-w-56 rounded-xl border border-gray-200 bg-white shadow-xs"></div>
        `;
        const toggle = folder.querySelector<HTMLElement>('[data-folder-toggle]');
        if (toggle) toggle.textContent = name;
        this.updateFolderEmptyState(folder);
        return folder;
    }

    private createTopLevelTab(meta: TabMeta): HTMLElement {
        const item = document.createElement('li');
        item.dataset.tabItem = '';
        item.dataset.tabType = 'tab';
        item.dataset.itemId = meta.id;
        item.dataset.itemName = meta.name;
        item.dataset.itemUrl = meta.url;
        item.dataset.tabActive = meta.active ? 'true' : 'false';
        item.className = 'shrink-0 cursor-pointer select-none border-b-2 border-transparent';
        item.appendChild(this.createTabLink(meta, false));
        item.setAttribute('draggable', 'true');
        return item;
    }

    private createTabLink(meta: TabMeta, inFolder: boolean): HTMLAnchorElement {
        const link = document.createElement('a');
        link.href = this.resolveUrl(meta.url);
        link.dataset.itemId = meta.id;
        link.dataset.itemName = meta.name;
        link.dataset.itemUrl = meta.url;
        link.dataset.tabActive = meta.active ? 'true' : 'false';
        link.textContent = meta.name;

        if (inFolder) {
            link.dataset.folderTabItem = '';
            link.className = 'block w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-primary-500';
            link.setAttribute('draggable', 'true');
        } else {
            link.dataset.tabLink = '';
            link.setAttribute('role', 'tab');
            link.className = 'block h-full w-full px-4 py-2 text-sm whitespace-nowrap hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-primary-500';
        }

        this.applyHtmxNavigation(link);
        return link;
    }

    private updateFolder(folder: HTMLElement, name: string): void {
        folder.dataset.itemName = name;
        const toggle = folder.querySelector<HTMLElement>('[data-folder-toggle]');
        if (toggle) toggle.textContent = name;
    }

    private updateTab(item: HTMLElement, meta: TabMeta): void {
        const tab = item.matches('[data-folder-tab-item]')
            ? item
            : item.querySelector<HTMLElement>('[data-tab-link]');
        if (!tab) return;

        item.dataset.itemName = meta.name;
        item.dataset.itemUrl = meta.url;
        tab.dataset.itemName = meta.name;
        tab.dataset.itemUrl = meta.url;
        tab.textContent = meta.name;
        tab.setAttribute('href', this.resolveUrl(meta.url));
        this.applyHtmxNavigation(tab as HTMLAnchorElement);
        htmx.process(tab);
    }

    /** Keep newly created and edited tabs scoped to their enclosing detail frame. */
    private applyHtmxNavigation(link: HTMLAnchorElement): void {
        if (this.isInternalUrl(link.getAttribute('href') || '')) {
            link.setAttribute('hx-get', link.getAttribute('href') || '');
            link.setAttribute('hx-swap', 'innerHTML');
            link.setAttribute('hx-target', this.element.dataset.detailContentTarget || '#detail-view-content');
            link.setAttribute('hx-push-url', this.element.dataset.detailPushUrl || 'true');
        } else {
            for (const attribute of ['hx-get', 'hx-swap', 'hx-target', 'hx-push-url']) {
                link.removeAttribute(attribute);
            }
        }
    }

    private extractTabMeta(source: HTMLElement): TabMeta | null {
        const tab = source.matches('[data-folder-tab-item], [data-tab-link]')
            ? source
            : source.querySelector<HTMLElement>('[data-tab-link]');
        const id = tab?.dataset.itemId || source.dataset.itemId || '';
        const name = tab?.dataset.itemName || source.dataset.itemName || tab?.textContent?.trim() || '';
        const url = tab?.dataset.itemUrl || source.dataset.itemUrl || '';
        if (!id || !name || !url) return null;
        return { id, name, url, active: tab?.dataset.tabActive === 'true' };
    }

    private toggleFolder(folder: HTMLElement): void {
        const panel = this.getFolderPanel(folder);
        if (!panel) return;
        const open = !panel.classList.contains('hidden');
        this.closeFolders();
        if (open) return;

        const rect = folder.getBoundingClientRect();
        panel.classList.add('fixed');
        panel.style.left = `${Math.round(rect.left)}px`;
        panel.style.top = `${Math.round(rect.bottom + 4)}px`;
        panel.style.minWidth = `${Math.max(Math.round(rect.width), 224)}px`;
        panel.classList.remove('hidden');
    }

    private closeFolders(): void {
        for (const folder of this.getFolderItems()) {
            const panel = this.getFolderPanel(folder);
            panel?.classList.add('hidden');
            panel?.classList.remove('fixed');
            if (panel) panel.removeAttribute('style');
        }
    }

    private onDocumentClick(event: MouseEvent): void {
        const target = event.target as Node | null;
        if (target && this.element?.contains(target)) return;
        this.closeFolders();
    }

    private onKeyDown(event: KeyboardEvent): void {
        if (!this.element) return;
        const target = event.target as HTMLElement | null;
        if (event.altKey && event.code === 'KeyT' && !this.isTypingTarget(target)) {
            event.preventDefault();
            this.findItem(this.activeId || '')?.querySelector<HTMLElement>('[data-tab-link], [data-folder-toggle]')?.focus();
        }
        if (event.key === 'Escape') this.closeFolders();
    }

    private findActiveId(): string | null {
        const active = this.element?.querySelector<HTMLElement>('[data-tab-active="true"]');
        return active?.dataset.itemId || active?.closest<HTMLElement>('[data-tab-item]')?.dataset.itemId || null;
    }

    private applyActiveStyles(): void {
        for (const item of this.getTopLevelItems()) {
            const folderActive = item.dataset.tabType === 'folder'
                && this.getFolderTabs(item).some((tab) => tab.dataset.itemId === this.activeId);
            const active = item.dataset.itemId === this.activeId || folderActive;
            item.classList.toggle('border-primary', active);
            item.classList.toggle('bg-primary/5', active);
            item.classList.toggle('text-primary', active);
            item.classList.toggle('font-medium', active);
            item.classList.toggle('border-transparent', !active);
            item.classList.toggle('text-gray-700', !active);
        }
        this.element?.querySelectorAll<HTMLElement>('[data-folder-tab-item]').forEach((tab) => {
            const active = tab.dataset.itemId === this.activeId;
            tab.classList.toggle('bg-primary/5', active);
            tab.classList.toggle('text-primary', active);
            tab.classList.toggle('font-medium', active);
        });
    }

    private getHorizontalDragAfterElement(clientX: number): HTMLElement | null {
        let result: { offset: number; element: HTMLElement | null } = {
            offset: Number.NEGATIVE_INFINITY,
            element: null,
        };
        for (const item of this.getTopLevelItems().filter((entry) => entry !== this.draggedTopLevel)) {
            const box = item.getBoundingClientRect();
            const offset = clientX - box.left - box.width / 2;
            if (offset < 0 && offset > result.offset) result = { offset, element: item };
        }
        return result.element;
    }

    private getVerticalDragAfterElement(panel: HTMLElement, clientY: number): HTMLElement | null {
        let result: { offset: number; element: HTMLElement | null } = {
            offset: Number.NEGATIVE_INFINITY,
            element: null,
        };
        const tabs = Array.from(panel.querySelectorAll<HTMLElement>('[data-folder-tab-item]'))
            .filter((tab) => tab !== this.draggedFolderTab);
        for (const tab of tabs) {
            const box = tab.getBoundingClientRect();
            const offset = clientY - box.top - box.height / 2;
            if (offset < 0 && offset > result.offset) result = { offset, element: tab };
        }
        return result.element;
    }

    private hasExternalLinkDrag(dataTransfer: DataTransfer | null): boolean {
        if (!dataTransfer || this.draggedTopLevel || this.draggedFolderTab) return false;
        return dataTransfer.types.includes('text/uri-list') || dataTransfer.types.includes('text/plain');
    }

    private getDroppedLink(dataTransfer: DataTransfer | null): TabMeta | null {
        if (!dataTransfer) return null;
        const uriList = dataTransfer.getData('text/uri-list')
            .split('\n')
            .map((value) => value.trim())
            .find((value) => value && !value.startsWith('#'));
        const url = uriList || dataTransfer.getData('text/plain').trim();
        if (!url || (!this.isInternalUrl(url) && !/^https?:\/\//i.test(url))) return null;

        let name = url;
        const html = dataTransfer.getData('text/html');
        if (html) {
            const documentFragment = new DOMParser().parseFromString(html, 'text/html');
            name = documentFragment.querySelector('a')?.textContent?.trim() || url;
        }
        return { id: this.generateId(), name, url };
    }

    private updateFolderEmptyState(folder: HTMLElement): void {
        const panel = this.getFolderPanel(folder);
        if (!panel) return;
        panel.querySelector('[data-folder-empty]')?.remove();
        if (this.getFolderTabs(folder).length > 0) return;

        const empty = document.createElement('div');
        empty.dataset.folderEmpty = '';
        empty.className = 'px-4 py-2 text-sm text-gray-500';
        empty.textContent = 'No tabs in folder';
        panel.appendChild(empty);
    }

    private updateAllFolderEmptyStates(): void {
        this.getFolderItems().forEach((folder) => this.updateFolderEmptyState(folder));
    }

    private getTopLevelItems(): HTMLElement[] {
        return this.stripList
            ? Array.from(this.stripList.querySelectorAll<HTMLElement>(':scope > [data-tab-item]'))
            : [];
    }

    private getFolderItems(): HTMLElement[] {
        return this.getTopLevelItems().filter((item) => item.dataset.tabType === 'folder');
    }

    private getFolderTabs(folder: HTMLElement): HTMLElement[] {
        return Array.from(folder.querySelectorAll<HTMLElement>('[data-folder-tabs] > [data-folder-tab-item]'));
    }

    private getFolderPanel(folder: HTMLElement): HTMLElement | null {
        return folder.querySelector('[data-folder-tabs]');
    }

    private findItem(id: string): HTMLElement | null {
        return this.element?.querySelector<HTMLElement>(`[data-item-id="${CSS.escape(id)}"]`) || null;
    }

    private resolveUrl(url: string): string {
        return url.split('{{pk}}').join(this.element?.dataset.objectPk || '');
    }

    private isInternalUrl(url: string): boolean {
        try {
            const parsed = new URL(url, window.location.origin);
            return parsed.origin === window.location.origin;
        } catch {
            return false;
        }
    }

    private isTypingTarget(target: HTMLElement | null): boolean {
        return Boolean(target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
    }

    private generateId(): string {
        if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (character) => {
            const random = Math.floor(Math.random() * 16);
            const value = character === 'x' ? random : (random & 0x3) | 0x8;
            return value.toString(16);
        });
    }

    private clearDragState(): void {
        this.draggedTopLevel = null;
        this.draggedFolderTab = null;
        this.draggedFolderSource = null;
        this.element?.querySelectorAll<HTMLElement>('.opacity-50').forEach((item) => item.classList.remove('opacity-50'));
        this.getFolderItems().forEach((folder) => folder.classList.remove('ring-2', 'ring-primary/40'));
    }

    private scheduleSave(): void {
        if (!this.canManage) return;
        if (this.saveTimer) window.clearTimeout(this.saveTimer);
        this.saveTimer = window.setTimeout(() => void this.save(), 200);
    }

    private buildPayload(): TabItemPayload[] {
        const payload: TabItemPayload[] = [];
        this.getTopLevelItems().forEach((item, position) => {
            const id = item.dataset.itemId || '';
            const name = item.dataset.itemName || '';
            if (item.dataset.tabType === 'folder') {
                payload.push({ id, name, url: null, parent_id: null, position });
                this.getFolderTabs(item).forEach((tab, childPosition) => {
                    payload.push({
                        id: tab.dataset.itemId || '',
                        name: tab.dataset.itemName || '',
                        url: tab.dataset.itemUrl || '',
                        parent_id: id,
                        position: childPosition,
                    });
                });
            } else {
                payload.push({ id, name, url: item.dataset.itemUrl || '', parent_id: null, position });
            }
        });
        return payload;
    }

    private async save(): Promise<void> {
        if (!this.element) return;
        const saveUrl = this.element.dataset.saveUrl;
        const contentTypeId = this.element.dataset.contentTypeId;
        if (!saveUrl || !contentTypeId) return;

        const form = new FormData();
        form.append('content_type_id', contentTypeId);
        form.append('items', JSON.stringify(this.buildPayload()));
        const csrfToken = getCsrfToken();
        const response = await fetch(saveUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: csrfToken ? { 'X-CSRFToken': csrfToken } : {},
            body: form,
        });
        if (!response.ok) throw new Error('Unable to save tabs preference.');
    }
}
