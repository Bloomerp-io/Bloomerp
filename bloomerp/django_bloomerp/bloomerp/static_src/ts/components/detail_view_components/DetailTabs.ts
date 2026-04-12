import BaseComponent from '../BaseComponent';
import { getCsrfToken } from '../../utils/cookies';
import { getContextMenu, type ContextMenuItem } from '../../utils/contextMenu';
import getGeneralModal from '../../utils/modals';
import htmx from 'htmx.org';

type FolderStatePayload = {
    id: string;
    name: string;
    tab_order: string[];
};

type TabStatePayload = {
    version: 2;
    top_level_order: string[];
    folders: FolderStatePayload[];
    active: string | null;
};

type TabMeta = {
    key: string;
    name: string;
    url: string;
    requiresPk: boolean;
    isActive: boolean;
    hxGet: string;
    elementId: string;
};

export default class DetailTabs extends BaseComponent {
    private stripContainer: HTMLElement | null = null;
    private stripList: HTMLElement | null = null;

    private keydownHandler: ((event: KeyboardEvent) => void) | null = null;
    private contextMenuHandler: ((event: MouseEvent) => void) | null = null;
    private documentClickHandler: ((event: MouseEvent) => void) | null = null;
    private modalAfterSwapHandler: ((event: Event) => void) | null = null;

    private draggedItem: HTMLElement | null = null;
    private draggedFolderTabButton: HTMLButtonElement | null = null;
    private draggedFolderSource: HTMLElement | null = null;
    private activeFolderPanelOwner: HTMLElement | null = null;
    private activeKey: string | null = null;
    private saveTimer: number | null = null;

    public initialize(): void {
        if (!this.element) return;

        this.stripContainer = this.element.querySelector<HTMLElement>('[data-tabs-strip-container]');
        this.stripList = this.element.querySelector<HTMLElement>('[data-tabs-strip]');
        if (!this.stripContainer || !this.stripList) return;

        this.initializeActiveKey();
        this.bindAllTopLevelItems();
        this.bindStripDnD();
        this.bindStripContextMenu();
        this.bindFolderPanelClickAway();
        this.bindFolderModalSuccess();

        this.keydownHandler = (event: KeyboardEvent) => this.onKeyDown(event);
        document.addEventListener('keydown', this.keydownHandler);

        this.applyActiveStyles();
    }

    public destroy(): void {
        if (this.keydownHandler) {
            document.removeEventListener('keydown', this.keydownHandler);
            this.keydownHandler = null;
        }

        if (this.contextMenuHandler && this.stripContainer) {
            this.stripContainer.removeEventListener('contextmenu', this.contextMenuHandler);
            this.contextMenuHandler = null;
        }

        if (this.documentClickHandler) {
            document.removeEventListener('click', this.documentClickHandler);
            this.documentClickHandler = null;
        }

        if (this.modalAfterSwapHandler) {
            const modalBody = document.getElementById('bloomerp-general-use-modal-body');
            modalBody?.removeEventListener('htmx:afterSwap', this.modalAfterSwapHandler);
            this.modalAfterSwapHandler = null;
        }

        if (this.saveTimer) {
            window.clearTimeout(this.saveTimer);
            this.saveTimer = null;
        }

        this.draggedItem = null;
        this.draggedFolderTabButton = null;
        this.draggedFolderSource = null;
        this.activeFolderPanelOwner = null;
    }

    private initializeActiveKey(): void {
        const activeTopLevel = this.getTopLevelItems().find((item) => item.dataset.tabActive === 'true');
        if (activeTopLevel) {
            this.activeKey = activeTopLevel.dataset.tabKey || null;
            return;
        }

        for (const folder of this.getFolderItems()) {
            const folderTabs = this.getFolderTabButtons(folder);
            const activeFolderTab = folderTabs.find((button) => button.dataset.tabActive === 'true');
            if (activeFolderTab) {
                this.activeKey = activeFolderTab.dataset.tabKey || null;
                return;
            }
        }

        this.activeKey = this.getTopLevelTabItems()[0]?.dataset.tabKey || null;
    }

    private bindAllTopLevelItems(): void {
        this.getTopLevelItems().forEach((item) => this.bindTopLevelItem(item));
    }

    private bindTopLevelItem(item: HTMLElement): void {
        item.setAttribute('draggable', 'true');

        item.addEventListener('dragstart', (event: DragEvent) => {
            this.draggedItem = item;
            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/tab-item-type', item.dataset.tabType || '');
                event.dataTransfer.setData('text/tab-key', item.dataset.tabKey || '');
                event.dataTransfer.setData('text/folder-id', item.dataset.folderId || '');
            }
            item.classList.add('opacity-50');
        });

        item.addEventListener('dragend', () => {
            this.clearDragState();
            this.scheduleSave();
        });

        const tabType = item.dataset.tabType;
        if (tabType === 'folder') {
            this.bindFolderItem(item);
        } else {
            this.bindTabItem(item);
        }
    }

    private bindTabItem(item: HTMLElement): void {
        const link = item.querySelector<HTMLElement>('[data-tab-link]');
        if (!link) return;

        item.addEventListener('click', (event: MouseEvent) => {
            if (event.target instanceof HTMLElement && event.target.closest('[data-tab-link]')) return;
            link.click();
        });

        link.addEventListener('click', () => {
            const key = item.dataset.tabKey || null;
            this.setActiveKey(key);
            this.closeAllFolderPanels();
            this.scheduleSave();
        });

        item.addEventListener('contextmenu', (event: MouseEvent) => {
            event.preventDefault();
            event.stopPropagation();
            const key = item.dataset.tabKey;
            if (!key) return;
            const menuItems = this.getMoveToFolderMenuItems(key);
            if (menuItems.length === 0) return;
            getContextMenu('detail-tabs-tab-menu').show(event, item, menuItems);
        });
    }

    private bindFolderItem(folderItem: HTMLElement): void {
        const toggle = folderItem.querySelector<HTMLElement>('[data-folder-toggle]');
        if (!toggle) return;

        folderItem.addEventListener('click', (event: MouseEvent) => {
            if (!(event.target instanceof HTMLElement)) return;
            if (event.target.closest('[data-folder-toggle]')) return;
            if (event.target.closest('[data-folder-tabs]')) return;
            toggle.click();
        });

        toggle.addEventListener('keydown', (event: KeyboardEvent) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                this.openFolderPanelAndFocusFirst(folderItem);
                return;
            }

            if (event.key === 'ArrowDown') {
                event.preventDefault();
                this.openFolderPanelAndFocusFirst(folderItem);
                return;
            }

            if (event.key === 'Escape') {
                event.preventDefault();
                this.closeAllFolderPanels();
            }
        });

        toggle.addEventListener('click', (event: MouseEvent) => {
            event.preventDefault();
            event.stopPropagation();
            this.toggleFolderPanel(folderItem);
        });

        folderItem.addEventListener('contextmenu', (event: MouseEvent) => {
            event.preventDefault();
            event.stopPropagation();

            const folderId = folderItem.dataset.folderId || '';
            const folderName = folderItem.dataset.folderName || '';
            getContextMenu('detail-tabs-folder-actions').show(event, folderItem, [
                {
                    label: 'Rename folder',
                    onClick: () => {
                        if (!folderId) return;
                        this.openFolderModal('rename', folderId, folderName);
                    },
                },
                {
                    label: 'Create folder',
                    onClick: () => this.openFolderModal('create'),
                },
                {
                    label: 'Delete folder',
                    onClick: () => {
                        if (!folderId) return;
                        this.deleteFolder(folderId);
                    },
                },
            ]);
        });

        folderItem.addEventListener('dragover', (event: DragEvent) => {
            const hasTopLevelTabDrag = this.draggedItem?.dataset.tabType === 'tab';
            const hasFolderTabDrag = Boolean(this.draggedFolderTabButton);
            if (!hasTopLevelTabDrag && !hasFolderTabDrag) return;
            event.preventDefault();
            folderItem.classList.add('ring-2', 'ring-primary/40');
        });

        folderItem.addEventListener('dragleave', () => {
            folderItem.classList.remove('ring-2', 'ring-primary/40');
        });

        folderItem.addEventListener('drop', (event: DragEvent) => {
            event.preventDefault();
            folderItem.classList.remove('ring-2', 'ring-primary/40');
            if (this.draggedItem && this.draggedItem.dataset.tabType === 'tab') {
                const draggedTab = this.draggedItem;
                const folderId = folderItem.dataset.folderId;
                if (!folderId) return;
                this.moveTopLevelTabToFolder(draggedTab, folderId);
                this.clearDragState();
                return;
            }

            if (this.draggedFolderTabButton && this.draggedFolderSource) {
                const targetFolderId = folderItem.dataset.folderId || '';
                if (!targetFolderId) return;
                this.moveFolderTabToFolder(this.draggedFolderSource, folderItem, this.draggedFolderTabButton.dataset.tabKey || '');
                this.clearDragState();
            }
        });

        this.getFolderTabButtons(folderItem).forEach((button) => this.bindFolderTabButton(button));
    }

    private bindStripContextMenu(): void {
        if (!this.stripContainer) return;

        this.contextMenuHandler = (event: MouseEvent) => {
            event.preventDefault();
            const items: ContextMenuItem[] = [
                {
                    label: 'Create folder',
                    onClick: () => {
                        this.openFolderModal('create');
                    },
                },
            ];
            getContextMenu('detail-tabs-strip-menu').show(event, this.stripContainer as HTMLElement, items);
        };

        this.stripContainer.addEventListener('contextmenu', this.contextMenuHandler);
    }

    private bindFolderPanelClickAway(): void {
        this.documentClickHandler = (event: MouseEvent) => {
            if (!this.element) return;
            const target = event.target as HTMLElement | null;
            if (target && this.element.contains(target)) {
                return;
            }
            this.closeAllFolderPanels();
        };

        document.addEventListener('click', this.documentClickHandler);
    }

    private bindFolderModalSuccess(): void {
        const modalBody = document.getElementById('bloomerp-general-use-modal-body');
        if (!modalBody) return;

        this.modalAfterSwapHandler = () => {
            const modalState = modalBody.querySelector<HTMLElement>('[data-detail-tabs-folder-modal]');
            if (!modalState || modalState.dataset.success !== 'true') return;

            const mode = modalState.dataset.mode === 'rename' ? 'rename' : 'create';
            const folderName = (modalState.dataset.folderName || '').trim();
            if (!folderName) return;

            if (mode === 'rename') {
                const folderId = modalState.dataset.folderId || '';
                this.renameFolder(folderId, folderName);
            } else {
                this.createFolderFromModal(folderName);
            }

            this.scheduleSave();
            getGeneralModal().close();
        };

        modalBody.addEventListener('htmx:afterSwap', this.modalAfterSwapHandler);
    }

    private bindStripDnD(): void {
        if (!this.stripList) return;

        this.stripList.addEventListener('dragover', (event: DragEvent) => {
            if (this.draggedFolderTabButton && this.draggedFolderSource) {
                event.preventDefault();
                return;
            }

            if (!this.draggedItem) return;
            event.preventDefault();

            const afterElement = this.getDragAfterElement(this.stripList as HTMLElement, event.clientX);
            if (!afterElement) {
                this.stripList?.appendChild(this.draggedItem);
            } else {
                this.stripList?.insertBefore(this.draggedItem, afterElement);
            }
        });

        this.stripList.addEventListener('drop', (event: DragEvent) => {
            if (this.draggedFolderTabButton && this.draggedFolderSource) {
                event.preventDefault();
                const tabKey = this.draggedFolderTabButton.dataset.tabKey || '';
                if (tabKey) {
                    this.moveFolderTabToTopLevel(this.draggedFolderSource, tabKey, event.clientX);
                }
                this.clearDragState();
                return;
            }

            event.preventDefault();
            this.clearDragState();
            this.scheduleSave();
        });
    }

    private getDragAfterElement(list: HTMLElement, clientX: number): HTMLElement | null {
        const draggableElements = [...list.querySelectorAll<HTMLElement>('[data-tab-item]:not(.opacity-50)')];
        let closest: { offset: number; element: HTMLElement | null } = {
            offset: Number.NEGATIVE_INFINITY,
            element: null,
        };

        draggableElements.forEach((child) => {
            const box = child.getBoundingClientRect();
            const offset = clientX - box.left - box.width / 2;

            if (offset < 0 && offset > closest.offset) {
                closest = { offset, element: child };
            }
        });

        return closest.element;
    }

    private setActiveKey(key: string | null): void {
        this.activeKey = key;
        this.applyActiveStyles();
    }

    private applyActiveStyles(): void {
        this.getTopLevelTabItems().forEach((item) => {
            const isActive = item.dataset.tabKey === this.activeKey;
            item.dataset.tabActive = isActive ? 'true' : 'false';
            item.classList.toggle('border-primary', isActive);
            item.classList.toggle('bg-primary/5', isActive);
            item.classList.toggle('text-primary', isActive);
            item.classList.toggle('font-medium', isActive);

            item.classList.toggle('border-transparent', !isActive);
            item.classList.toggle('text-gray-700', !isActive);

            const link = item.querySelector<HTMLElement>('[data-tab-link]');
            if (link) {
                link.setAttribute('aria-selected', isActive ? 'true' : 'false');
            }
        });

        this.getFolderItems().forEach((folder) => {
            const folderHasActive = this.getFolderTabButtons(folder).some(
                (button) => button.dataset.tabKey === this.activeKey
            );

            folder.classList.toggle('border-primary', folderHasActive);
            folder.classList.toggle('bg-primary/5', folderHasActive);
            folder.classList.toggle('font-medium', folderHasActive);

            folder.classList.toggle('border-transparent', !folderHasActive);

            const toggle = folder.querySelector<HTMLElement>('[data-folder-toggle]');
            if (toggle) {
                toggle.classList.toggle('text-primary', folderHasActive);
                toggle.classList.toggle('text-gray-700', !folderHasActive);
            }

            this.getFolderTabButtons(folder).forEach((button) => {
                const isActive = button.dataset.tabKey === this.activeKey;
                button.dataset.tabActive = isActive ? 'true' : 'false';
                button.classList.toggle('bg-primary/5', isActive);
                button.classList.toggle('font-medium', isActive);
                button.classList.toggle('text-primary', isActive);
                button.classList.toggle('text-gray-700', !isActive);
            });
        });
    }

    private toggleFolderPanel(folderItem: HTMLElement): void {
        const panel = this.getFolderPanel(folderItem);
        if (!panel) return;

        const isOpen = !panel.classList.contains('hidden');
        this.closeAllFolderPanels();

        if (!isOpen) {
            const rect = folderItem.getBoundingClientRect();
            panel.classList.add('fixed');
            panel.style.left = `${Math.round(rect.left)}px`;
            panel.style.top = `${Math.round(rect.bottom + 4)}px`;
            panel.style.minWidth = `${Math.max(Math.round(rect.width), 224)}px`;
            panel.classList.remove('hidden');
            this.activeFolderPanelOwner = folderItem;
        } else {
            this.activeFolderPanelOwner = null;
        }
    }

    private openFolderPanelAndFocusFirst(folderItem: HTMLElement): void {
        this.toggleFolderPanel(folderItem);
        const panel = this.getFolderPanel(folderItem);
        if (!panel || panel.classList.contains('hidden')) return;
        this.getFolderTabButtons(folderItem)[0]?.focus();
    }

    private closeAllFolderPanels(exceptFolderItem: HTMLElement | null = null): void {
        this.getFolderItems().forEach((folderItem) => {
            if (exceptFolderItem && folderItem === exceptFolderItem) return;
            const panel = this.getFolderPanel(folderItem);
            if (!panel) return;
            panel.classList.add('hidden');
            panel.classList.remove('fixed');
            panel.style.left = '';
            panel.style.top = '';
            panel.style.minWidth = '';
        });
        if (!exceptFolderItem) {
            this.activeFolderPanelOwner = null;
        }
    }

    private getMoveToFolderMenuItems(tabKey: string): ContextMenuItem[] {
        return this.getFolderItems().map((folderItem) => {
            const folderId = folderItem.dataset.folderId || '';
            const folderName = folderItem.dataset.folderName || 'Folder';
            return {
                label: `Move to \"${folderName}\"`,
                onClick: () => {
                    const tabItem = this.getTopLevelTabItems().find((item) => item.dataset.tabKey === tabKey);
                    if (!tabItem || !folderId) return;
                    this.moveTopLevelTabToFolder(tabItem, folderId);
                },
            };
        });
    }

    private moveTopLevelTabToFolder(tabItem: HTMLElement, folderId: string): void {
        const folderItem = this.getFolderItems().find((folder) => folder.dataset.folderId === folderId);
        if (!folderItem) return;

        const folderTabsContainer = folderItem.querySelector<HTMLElement>('[data-folder-tabs]');
        if (!folderTabsContainer) return;

        const tabMeta = this.extractTabMetaFromTopLevelItem(tabItem);
        if (!tabMeta) return;

        const existing = this.getFolderTabButtons(folderItem).find((button) => button.dataset.tabKey === tabMeta.key);
        if (!existing) {
            const newButton = this.createFolderTabButton(tabMeta);
            folderTabsContainer.appendChild(newButton);
            this.bindFolderTabButton(newButton);
            htmx.process(newButton);
        }

        tabItem.remove();
        this.updateFolderEmptyState(folderItem);
        this.closeAllFolderPanels();
        this.applyActiveStyles();
        this.scheduleSave();
    }

    private moveFolderTabToTopLevel(folderItem: HTMLElement, tabKey: string, clientX?: number): void {
        if (!this.stripList) return;

        const folderTabsContainer = folderItem.querySelector<HTMLElement>('[data-folder-tabs]');
        if (!folderTabsContainer) return;

        const folderTabButton = this.getFolderTabButtons(folderItem).find((button) => button.dataset.tabKey === tabKey);
        if (!folderTabButton) return;

        const meta = this.extractTabMetaFromFolderButton(folderTabButton);
        if (!meta) return;

        const topLevelItem = this.createTopLevelTabItem(meta);
        if (typeof clientX === 'number') {
            const afterElement = this.getDragAfterElement(this.stripList, clientX);
            if (afterElement) {
                this.stripList.insertBefore(topLevelItem, afterElement);
            } else {
                this.stripList.appendChild(topLevelItem);
            }
        } else {
            this.stripList.insertBefore(topLevelItem, folderItem.nextSibling);
        }
        htmx.process(topLevelItem);

        folderTabButton.remove();
        this.updateFolderEmptyState(folderItem);
        this.closeAllFolderPanels();
        this.applyActiveStyles();
        this.scheduleSave();
    }

    private moveFolderTabToFolder(sourceFolder: HTMLElement, targetFolder: HTMLElement, tabKey: string): void {
        if (!tabKey) return;
        if (sourceFolder === targetFolder) return;

        const sourceButtons = this.getFolderTabButtons(sourceFolder);
        const sourceButton = sourceButtons.find((button) => button.dataset.tabKey === tabKey);
        if (!sourceButton) return;

        const targetPanel = this.getFolderPanel(targetFolder);
        if (!targetPanel) return;

        const existing = this.getFolderTabButtons(targetFolder).find((button) => button.dataset.tabKey === tabKey);
        if (existing) {
            sourceButton.remove();
        } else {
            targetPanel.appendChild(sourceButton);
            htmx.process(sourceButton);
        }

        this.updateFolderEmptyState(sourceFolder);
        this.updateFolderEmptyState(targetFolder);
        this.applyActiveStyles();
        this.scheduleSave();
    }

    private deleteFolder(folderId: string): void {
        if (!this.stripList) return;

        const folderItem = this.getFolderItems().find((folder) => folder.dataset.folderId === folderId);
        if (!folderItem) return;

        const folderButtons = this.getFolderTabButtons(folderItem);
        const insertionAnchor = folderItem.nextSibling;

        for (const button of folderButtons) {
            const meta = this.extractTabMetaFromFolderButton(button);
            if (!meta) continue;
            const topLevelItem = this.createTopLevelTabItem(meta);
            if (insertionAnchor) {
                this.stripList.insertBefore(topLevelItem, insertionAnchor);
            } else {
                this.stripList.appendChild(topLevelItem);
            }
            htmx.process(topLevelItem);
        }

        folderItem.remove();
        this.closeAllFolderPanels();
        this.applyActiveStyles();
        this.scheduleSave();
    }

    private openFolderModal(mode: 'create' | 'rename', folderId = '', folderName = ''): void {
        if (!this.element) return;

        const modalUrl = this.element.getAttribute('data-folder-modal-url');
        const contentTypeId = this.element.getAttribute('data-content-type-id');
        if (!modalUrl || !contentTypeId) return;

        const modal = getGeneralModal();
        modal.setTitle(mode === 'rename' ? 'Rename Folder' : 'Create Folder');

        htmx
            .ajax('get', modalUrl, {
                target: modal.getBodyElement(),
                swap: 'innerHTML',
                push: 'false',
                values: {
                    mode,
                    content_type_id: contentTypeId,
                    folder_id: folderId,
                    folder_name: folderName,
                },
            })
            .then(() => {
                modal.open();
            })
            .catch(() => {
                // no-op
            });
    }

    private createFolderFromModal(folderName: string): void {
        const name = folderName.trim();
        if (!name) return;

        const folderId = this.generateFolderId();
        const folderItem = this.createFolderItem(folderId, name);
        this.stripList?.appendChild(folderItem);
        this.bindTopLevelItem(folderItem);
        htmx.process(folderItem);
    }

    private renameFolder(folderId: string, folderName: string): void {
        const item = this.getFolderItems().find((folder) => folder.dataset.folderId === folderId);
        if (!item) return;

        const name = folderName.trim();
        if (!name) return;

        item.dataset.folderName = name;
        const toggle = item.querySelector<HTMLElement>('[data-folder-toggle]');
        if (toggle) {
            toggle.textContent = name;
        }
    }

    private generateFolderId(): string {
        return `folder_${Date.now()}_${Math.floor(Math.random() * 10000)}`;
    }

    private createFolderItem(folderId: string, folderName: string): HTMLElement {
        const li = document.createElement('li');
        li.setAttribute('data-tab-item', '');
        li.setAttribute('data-tab-type', 'folder');
        li.setAttribute('data-folder-id', folderId);
        li.setAttribute('data-folder-name', folderName);
        li.setAttribute('draggable', 'true');
        li.className = 'shrink-0 border-b-2 border-transparent hover:bg-gray-50 cursor-pointer select-none';

        const button = document.createElement('button');
        button.type = 'button';
        button.setAttribute('data-folder-toggle', '');
        button.className = 'w-full h-full px-4 py-1.5 text-sm whitespace-nowrap text-gray-700';
        button.textContent = folderName;

        const tabsContainer = document.createElement('div');
        tabsContainer.className = 'hidden absolute left-0 top-full mt-1 min-w-56 rounded-md border border-gray-200 bg-white z-50 shadow-lg';
        tabsContainer.setAttribute('data-folder-tabs', '');

        const emptyState = document.createElement('div');
        emptyState.className = 'px-3 py-2 text-sm text-gray-500';
        emptyState.setAttribute('data-folder-empty', '');
        emptyState.textContent = 'No tabs in folder';
        tabsContainer.appendChild(emptyState);

        li.appendChild(button);
        li.appendChild(tabsContainer);
        return li;
    }

    private updateFolderEmptyState(folderItem: HTMLElement): void {
        const panel = this.getFolderPanel(folderItem);
        if (!panel) return;

        let emptyState = panel.querySelector<HTMLElement>('[data-folder-empty]');
        const tabCount = this.getFolderTabButtons(folderItem).length;

        if (tabCount === 0) {
            if (!emptyState) {
                emptyState = document.createElement('div');
                emptyState.className = 'px-3 py-2 text-sm text-gray-500';
                emptyState.setAttribute('data-folder-empty', '');
                emptyState.textContent = 'No tabs in folder';
                panel.appendChild(emptyState);
            }
            return;
        }

        emptyState?.remove();
    }

    private createTopLevelTabItem(meta: TabMeta): HTMLElement {
        const li = document.createElement('li');
        li.setAttribute('data-tab-item', '');
        li.setAttribute('data-tab-type', 'tab');
        li.setAttribute('data-tab-key', meta.key);
        li.setAttribute('data-tab-name', meta.name);
        li.setAttribute('data-tab-url', meta.url);
        li.setAttribute('data-tab-requires-pk', meta.requiresPk ? 'true' : 'false');
        li.setAttribute('data-tab-active', meta.isActive ? 'true' : 'false');
        li.setAttribute('draggable', 'true');
        li.className = 'shrink-0 border-b-2 border-transparent hover:bg-gray-50 cursor-pointer select-none';

        const button = document.createElement('button');
        button.type = 'button';
        button.setAttribute('data-tab-link', '');
        button.setAttribute('role', 'tab');
        button.setAttribute('aria-selected', meta.isActive ? 'true' : 'false');
        button.setAttribute('hx-get', meta.hxGet);
        button.setAttribute('hx-swap', 'innerHTML');
        button.setAttribute('hx-trigger', 'click');
        button.setAttribute('hx-target', '#detail-view-content');
        button.setAttribute('hx-push-url', 'true');
        button.id = meta.elementId;
        button.className = 'w-full h-full px-4 py-1.5 text-sm whitespace-nowrap focus:outline-none focus:ring-2 focus:ring-primary-500';
        button.textContent = meta.name;

        li.appendChild(button);
        this.bindTopLevelItem(li);
        return li;
    }

    private createFolderTabButton(meta: TabMeta): HTMLButtonElement {
        const button = document.createElement('button');
        button.type = 'button';
        button.setAttribute('data-folder-tab-item', '');
        button.setAttribute('data-tab-key', meta.key);
        button.setAttribute('data-tab-name', meta.name);
        button.setAttribute('data-tab-url', meta.url);
        button.setAttribute('data-tab-requires-pk', meta.requiresPk ? 'true' : 'false');
        button.setAttribute('data-tab-active', meta.isActive ? 'true' : 'false');
        button.setAttribute('hx-get', meta.hxGet);
        button.setAttribute('hx-swap', 'innerHTML');
        button.setAttribute('hx-trigger', 'click');
        button.setAttribute('hx-target', '#detail-view-content');
        button.setAttribute('hx-push-url', 'true');
        button.className = 'block w-full text-left px-3 py-2 text-sm hover:bg-gray-50 text-gray-700 focus:outline-none focus:ring-2 focus:ring-primary-500';
        button.textContent = meta.name;

        return button;
    }

    private bindFolderTabButton(button: HTMLButtonElement): void {
        if (button.dataset.boundDetailTabs === 'true') return;
        button.dataset.boundDetailTabs = 'true';
        button.setAttribute('draggable', 'true');

        button.addEventListener('dragstart', (event: DragEvent) => {
            const ownerFolder = button.closest<HTMLElement>('[data-tab-type="folder"]');
            if (!ownerFolder) return;

            this.draggedFolderTabButton = button;
            this.draggedFolderSource = ownerFolder;
            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/tab-item-type', 'folder-tab');
                event.dataTransfer.setData('text/tab-key', button.dataset.tabKey || '');
                event.dataTransfer.setData('text/folder-id', ownerFolder.dataset.folderId || '');
            }
            button.classList.add('opacity-50');
        });

        button.addEventListener('dragend', () => {
            this.clearDragState();
        });

        button.addEventListener('keydown', (event: KeyboardEvent) => {
            const ownerFolder = button.closest<HTMLElement>('[data-tab-type="folder"]');
            if (!ownerFolder) return;

            const folderButtons = this.getFolderTabButtons(ownerFolder);
            const currentIndex = folderButtons.indexOf(button);

            if (event.key === 'Escape') {
                event.preventDefault();
                this.closeAllFolderPanels();
                ownerFolder.querySelector<HTMLElement>('[data-folder-toggle]')?.focus();
                return;
            }

            if (event.key === 'ArrowDown') {
                event.preventDefault();
                const next = folderButtons[(currentIndex + 1) % folderButtons.length];
                next?.focus();
                return;
            }

            if (event.key === 'ArrowUp') {
                event.preventDefault();
                const next = folderButtons[(currentIndex - 1 + folderButtons.length) % folderButtons.length];
                next?.focus();
                return;
            }
        });

        button.addEventListener('click', () => {
            const key = button.dataset.tabKey || null;
            this.setActiveKey(key);
            this.closeAllFolderPanels();
            this.scheduleSave();
        });
    }

    private extractTabMetaFromTopLevelItem(tabItem: HTMLElement): TabMeta | null {
        const button = tabItem.querySelector<HTMLElement>('[data-tab-link]');
        const key = tabItem.dataset.tabKey || '';
        const name = tabItem.dataset.tabName || button?.textContent?.trim() || '';
        const url = tabItem.dataset.tabUrl || '';
        const requiresPk = tabItem.dataset.tabRequiresPk === 'true';
        const hxGet = button?.getAttribute('hx-get') || '';
        const elementId = button?.id || hxGet;

        if (!key || !name || !url || !hxGet) return null;

        return {
            key,
            name,
            url,
            requiresPk,
            isActive: tabItem.dataset.tabActive === 'true',
            hxGet,
            elementId,
        };
    }

    private extractTabMetaFromFolderButton(button: HTMLElement): TabMeta | null {
        const key = button.dataset.tabKey || '';
        const name = button.dataset.tabName || button.textContent?.trim() || '';
        const url = button.dataset.tabUrl || '';
        const requiresPk = button.dataset.tabRequiresPk === 'true';
        const hxGet = button.getAttribute('hx-get') || '';
        const elementId = hxGet;

        if (!key || !name || !url || !hxGet) return null;

        return {
            key,
            name,
            url,
            requiresPk,
            isActive: button.dataset.tabActive === 'true',
            hxGet,
            elementId,
        };
    }

    private onKeyDown(event: KeyboardEvent): void {
        if (!this.element) return;

        const target = event.target as HTMLElement | null;

        if (event.altKey && event.code === 'KeyT') {
            if (this.isTypingTarget(target)) return;
            event.preventDefault();
            this.focusActiveTab();
            return;
        }

        if (event.key === 'Escape') {
            const active = document.activeElement as HTMLElement | null;
            if (active && this.element.contains(active) && this.activeFolderPanelOwner) {
                event.preventDefault();
                const owner = this.activeFolderPanelOwner;
                this.closeAllFolderPanels();
                owner.querySelector<HTMLElement>('[data-folder-toggle]')?.focus();
                return;
            }
        }

        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;

        const focusedTarget = document.activeElement as HTMLElement | null;
        if (!focusedTarget || !this.element.contains(focusedTarget)) return;

        const navigationTargets = this.getTopLevelNavigationTargets();
        if (navigationTargets.length === 0) return;

        const currentIndex = navigationTargets.indexOf(focusedTarget);
        if (currentIndex === -1) return;

        event.preventDefault();
        const direction = event.key === 'ArrowRight' ? 1 : -1;
        const nextIndex = (currentIndex + direction + navigationTargets.length) % navigationTargets.length;
        navigationTargets[nextIndex]?.focus();
    }

    private isTypingTarget(target: HTMLElement | null): boolean {
        if (!target) return false;
        const tag = target.tagName.toLowerCase();
        return tag === 'input' || tag === 'textarea' || tag === 'select' || target.isContentEditable;
    }

    private focusActiveTab(): void {
        const activeTopLevel = this.getTopLevelTabItems().find((item) => item.dataset.tabKey === this.activeKey);
        if (activeTopLevel) {
            activeTopLevel.querySelector<HTMLElement>('[data-tab-link]')?.focus();
            return;
        }

        const activeFolder = this.getFolderItems().find((folder) =>
            this.getFolderTabButtons(folder).some((button) => button.dataset.tabKey === this.activeKey)
        );

        if (activeFolder) {
            activeFolder.querySelector<HTMLElement>('[data-folder-toggle]')?.focus();
        }
    }

    private getTopLevelItems(): HTMLElement[] {
        if (!this.stripList) return [];
        return Array.from(this.stripList.querySelectorAll<HTMLElement>(':scope > [data-tab-item]'));
    }

    private getTopLevelTabItems(): HTMLElement[] {
        return this.getTopLevelItems().filter((item) => item.dataset.tabType === 'tab');
    }

    private getFolderItems(): HTMLElement[] {
        return this.getTopLevelItems().filter((item) => item.dataset.tabType === 'folder');
    }

    private getFolderTabButtons(folderItem: HTMLElement): HTMLButtonElement[] {
        return Array.from(folderItem.querySelectorAll<HTMLButtonElement>('[data-folder-tabs] [data-folder-tab-item]'));
    }

    private getFolderPanel(folderItem: HTMLElement): HTMLElement | null {
        return folderItem.querySelector<HTMLElement>('[data-folder-tabs]');
    }

    private getTopLevelNavigationTargets(): HTMLElement[] {
        if (!this.stripList) return [];
        return Array.from(this.stripList.querySelectorAll<HTMLElement>('[data-tab-link], [data-folder-toggle]'));
    }

    private clearDragState(): void {
        this.draggedItem = null;
        this.draggedFolderTabButton = null;
        this.draggedFolderSource = null;

        this.getTopLevelItems().forEach((item) => {
            item.classList.remove('opacity-50');
            item.classList.remove('ring-2', 'ring-primary/40');
        });

        this.getFolderItems().forEach((folder) => {
            this.getFolderTabButtons(folder).forEach((button) => {
                button.classList.remove('opacity-50');
            });
        });
    }

    private scheduleSave(): void {
        if (this.saveTimer) {
            window.clearTimeout(this.saveTimer);
        }

        this.saveTimer = window.setTimeout(() => {
            this.saveTabState().catch(() => {
                // no-op
            });
        }, 200);
    }

    private buildStatePayload(): TabStatePayload {
        const topLevelOrder: string[] = [];
        const folders: FolderStatePayload[] = [];

        for (const item of this.getTopLevelItems()) {
            if (item.dataset.tabType === 'tab') {
                const key = item.dataset.tabKey;
                if (key) topLevelOrder.push(key);
                continue;
            }

            if (item.dataset.tabType === 'folder') {
                const folderId = item.dataset.folderId;
                const folderName = item.dataset.folderName || item.querySelector('[data-folder-toggle]')?.textContent?.trim() || 'Folder';
                if (!folderId) continue;

                const tabOrder = this.getFolderTabButtons(item)
                    .map((button) => button.dataset.tabKey || '')
                    .filter((value) => Boolean(value));

                folders.push({
                    id: folderId,
                    name: folderName,
                    tab_order: tabOrder,
                });
            }
        }

        return {
            version: 2,
            top_level_order: topLevelOrder,
            folders,
            active: this.activeKey,
        };
    }

    private async saveTabState(): Promise<void> {
        if (!this.element) return;

        const saveUrl = this.element.getAttribute('data-save-url');
        const contentTypeId = this.element.getAttribute('data-content-type-id');
        if (!saveUrl || !contentTypeId) return;

        const state = this.buildStatePayload();
        const formData = new FormData();
        formData.append('content_type_id', contentTypeId);
        formData.append('state', JSON.stringify(state));

        const csrfToken = getCsrfToken();

        await fetch(saveUrl, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
                'HX-Request': 'true',
            },
            body: formData,
        });
    }
}
