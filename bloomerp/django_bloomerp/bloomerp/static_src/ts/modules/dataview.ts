/**
 * DataView Module with HTMX Integration
 * 
 * Provides functionality for:
 * - Dynamic view reloading via HTMX
 * - Support for multiple view types (Table, Kanban, etc.)
 * - Context menu on table cells (Table view)
 * - Cell value copying (Table view)
 * - Dynamic filtering
 */

import htmx from 'htmx.org';
import type { DataViewConfig, DataViewContextTrigger, ContextMenuPosition } from '../types/bloomerp';

// Navigation key constants - can be customized for user preferences
const NAVIGATION_KEYS = {
    // Global navigation
    ENTER_NAVIGATION: 'ArrowDown',      // Key to enter navigation mode
    EXIT_NAVIGATION: 'Escape',           // Key to exit navigation mode
    
    // Movement keys
    MOVE_UP: 'ArrowUp',
    MOVE_DOWN: 'ArrowDown',
    MOVE_LEFT: 'ArrowLeft',
    MOVE_RIGHT: 'ArrowRight',
    
    // Action keys
    SELECT: 'Enter',
    
    // Modifier keys (these are KeyboardEvent property names)
    CONTEXT_MENU_MODIFIER: 'shiftKey',   // Modifier + MOVE_DOWN to open context menu
    MOVE_ITEM_MODIFIER: 'shiftKey',      // Modifier + MOVE_LEFT/RIGHT to move item (kanban)
} as const;

/**
 * TODO : Split the DataView class into separate classes per view type
 * whereby the DataView acts as the orchestrator
 */
class Table {
    currentRowIndex: number = -1;
    currentCellIndex: number = -1;


    copyCellValue(): void {

    }
}

class Kanban {
    currentColumnIndex: number = -1;
    currentCardIndex: number = -1;
}

class Calendar {
    currentDateIndex: number = -1;
}


/**
 * DataView class handles all dataview interactions
 */
export class DataView {
    private containerId: string;
    private container: HTMLElement | null = null;
    private viewType: string = 'table';
    private contentTypeId: string | null = null;
    private splitView: boolean = false;
    
    // Initialization tracking
    private currentRenderId: string | null = null;
    private abortController: AbortController | null = null;
    
    // Common navigation properties
    private navigationMode: boolean = false;
    private contextMenu: HTMLElement | null = null;
    private currentTrigger: DataViewContextTrigger | null = null;
    
    // Context menu navigation properties
    private contextMenuOpen: boolean = false;
    private contextMenuItemIndex: number = -1;
    private contextMenuAbortController: AbortController | null = null;
    private contextMenuOpenedViaKeyboard: boolean = false;

    // Table specific properties
    private table: HTMLElement | null = null;
    private selectedRowIndex: number = -1;
    private selectedCellIndex: number = -1;
    private cellNavigationMode: boolean = false;

    // Kanban specific properties
    private kanbanBoard: HTMLElement | null = null;
    private draggedCard: HTMLElement | null = null;
    private draggedCardPlaceholder: HTMLElement | null = null;
    private selectedColumnIndex: number = -1;
    private selectedCardIndex: number = -1;

    // Calendar specific properties
    private calendarElement: HTMLElement | null = null;
    private selectedDateIndex: number = -1;
    private selectedEventIndex: number = -1;

    constructor(config: DataViewConfig) {
        this.containerId = config.containerId;
        this.initialize();
    }

    /**
     * Initialize the dataview
     */
    private initialize(): void {
        this.container = document.getElementById(this.containerId);

        if (!this.container) {
            console.warn(`DataView: Container with ID "${this.containerId}" not found`);
            return;
        }

        // Check if this is a new render or the same one
        const newRenderId = this.container.dataset.renderId || null;
        if (newRenderId && newRenderId === this.currentRenderId) {
            console.log(`DataView: Already initialized for render ${newRenderId}, skipping`);
            return;
        }
        
        // Cleanup previous initialization if any
        this.cleanup();
        
        // Store the new render ID and create new AbortController
        this.currentRenderId = newRenderId;
        this.abortController = new AbortController();
        
        console.log(`Initializing DataView: ${this.containerId} (render: ${newRenderId})`);

        this.contentTypeId = this.container.dataset.contentTypeId || null;
        this.viewType = this.container.dataset.viewType || 'table';

        // Initialize view-specific elements
        if (this.viewType === 'table') {
            this.initializeTableView();
        } else if (this.viewType === 'kanban') {
            this.initializeKanbanView();
        } else if (this.viewType === 'calendar') {
            this.initializeCalendarView();
        }

        // Initialize context menu for all view types
        this.setupContextMenu();

        // Setup keyboard navigation for all view types
        this.setupGlobalKeyboardListener();
        this.setupKeyboardNavigation();
    }
    
    /**
     * Cleanup all event listeners and state
     */
    private cleanup(): void {
        // Abort all event listeners registered with the current AbortController
        if (this.abortController) {
            this.abortController.abort();
            this.abortController = null;
        }
        
        // Cleanup context menu listeners
        if (this.contextMenuAbortController) {
            this.contextMenuAbortController.abort();
            this.contextMenuAbortController = null;
        }
        
        // Reset state
        this.contextMenuOpen = false;
        this.contextMenuItemIndex = -1;
        this.navigationMode = false;
        this.cellNavigationMode = false;
        this.selectedRowIndex = -1;
        this.selectedCellIndex = -1;
        this.selectedColumnIndex = -1;
        this.selectedCardIndex = -1;
        this.draggedCard = null;
        this.draggedCardPlaceholder = null;
    }

    /**
     * Initialize Table View specific logic
     */
    private initializeTableView(): void {
        if (!this.contentTypeId) return;

        this.table = document.getElementById(`data-table-${this.contentTypeId}`);
        
        if (!this.table) {
            // Try finding table inside container if ID construction fails
            this.table = this.container?.querySelector('table') as HTMLElement;
        }

        if (!this.table) return;

        // Make table focusable for keyboard navigation
        this.table.setAttribute('tabindex', '0');
        this.setupRowClickHandlers();
    }

    /**
     * Initialize Kanban View specific logic
     */
    private initializeKanbanView(): void {
        if (!this.contentTypeId) return;

        this.kanbanBoard = document.getElementById(`kanban-board-${this.contentTypeId}`);
        
        if (!this.kanbanBoard) {
            // Try finding kanban board inside container
            this.kanbanBoard = this.container?.querySelector('[data-kanban]') as HTMLElement;
        }

        if (!this.kanbanBoard) {
            console.warn('Kanban board not found');
            return;
        }

        // Make kanban board focusable for keyboard navigation
        this.kanbanBoard.setAttribute('tabindex', '0');
        
        this.setupKanbanDragAndDrop();
    }

    /**
     * Initialize calendar view specific logic
     */
    private initializeCalendarView(): void {
        this.calendarElement = this.container?.querySelector('[data-calendar]') as HTMLElement;

        if (!this.calendarElement) {
            console.warn('Calendar element not found');
            return;
        }

        // Make calendar focusable for keyboard navigation
        this.calendarElement.setAttribute('tabindex', '0');
    }
    
    /**
     * Set up drag and drop for kanban cards
     */
    private setupKanbanDragAndDrop(): void {
        if (!this.kanbanBoard) return;

        const cards = this.kanbanBoard.querySelectorAll('[data-kanban-card]');
        const dropzones = this.kanbanBoard.querySelectorAll('[data-kanban-dropzone]');

        // Set up drag events for cards
        cards.forEach(card => {
            const cardElement = card as HTMLElement;
            
            cardElement.addEventListener('dragstart', (e: DragEvent) => {
                this.handleDragStart(e, cardElement);
            });

            cardElement.addEventListener('dragend', (e: DragEvent) => {
                this.handleDragEnd(e, cardElement);
            });
        });

        // Set up drop events for columns
        dropzones.forEach(dropzone => {
            const dropzoneElement = dropzone as HTMLElement;

            dropzoneElement.addEventListener('dragover', (e: DragEvent) => {
                this.handleDragOver(e, dropzoneElement);
            });

            dropzoneElement.addEventListener('dragenter', (e: DragEvent) => {
                this.handleDragEnter(e, dropzoneElement);
            });

            dropzoneElement.addEventListener('dragleave', (e: DragEvent) => {
                this.handleDragLeave(e, dropzoneElement);
            });

            dropzoneElement.addEventListener('drop', (e: DragEvent) => {
                this.handleDrop(e, dropzoneElement);
            });
        });
    }

    /**
     * Handle drag start event
     */
    private handleDragStart(e: DragEvent, card: HTMLElement): void {
        this.draggedCard = card;
        
        // Set drag data
        if (e.dataTransfer) {
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', card.dataset.objectId || '');
        }

        // Add dragging class after a small delay to prevent immediate opacity change
        requestAnimationFrame(() => {
            card.classList.add('dragging');
        });

        // Create a placeholder
        this.draggedCardPlaceholder = document.createElement('div');
        this.draggedCardPlaceholder.className = 'kanban-card-placeholder bg-blue-100 border-2 border-dashed border-blue-300 rounded-lg';
        this.draggedCardPlaceholder.style.height = `${card.offsetHeight}px`;
        this.draggedCardPlaceholder.style.minHeight = '60px';
    }

    /**
     * Handle drag end event
     */
    private handleDragEnd(e: DragEvent, card: HTMLElement): void {
        card.classList.remove('dragging');
        
        // Remove placeholder if it exists
        if (this.draggedCardPlaceholder && this.draggedCardPlaceholder.parentNode) {
            this.draggedCardPlaceholder.parentNode.removeChild(this.draggedCardPlaceholder);
        }

        // Remove drag-over class from all dropzones
        const dropzones = this.kanbanBoard?.querySelectorAll('[data-kanban-dropzone]');
        dropzones?.forEach(dz => {
            dz.classList.remove('drag-over');
        });

        this.draggedCard = null;
        this.draggedCardPlaceholder = null;
    }

    /**
     * Handle drag over event
     */
    private handleDragOver(e: DragEvent, dropzone: HTMLElement): void {
        e.preventDefault();
        
        if (e.dataTransfer) {
            e.dataTransfer.dropEffect = 'move';
        }

        // Find the card we're hovering over to insert placeholder
        if (this.draggedCard && this.draggedCardPlaceholder) {
            const cards = Array.from(dropzone.querySelectorAll('[data-kanban-card]:not(.dragging)'));
            const mouseY = e.clientY;

            // Find the card after which to insert the placeholder
            let insertBefore: Element | null = null;
            for (const card of cards) {
                const rect = card.getBoundingClientRect();
                const cardMiddle = rect.top + rect.height / 2;
                
                if (mouseY < cardMiddle) {
                    insertBefore = card;
                    break;
                }
            }

            // Insert or move placeholder
            if (insertBefore) {
                if (this.draggedCardPlaceholder.nextSibling !== insertBefore) {
                    dropzone.insertBefore(this.draggedCardPlaceholder, insertBefore);
                }
            } else {
                // Append at the end if no card found
                if (this.draggedCardPlaceholder.parentNode !== dropzone || 
                    this.draggedCardPlaceholder.nextSibling !== null) {
                    dropzone.appendChild(this.draggedCardPlaceholder);
                }
            }
        }
    }

    /**
     * Handle drag enter event
     */
    private handleDragEnter(e: DragEvent, dropzone: HTMLElement): void {
        e.preventDefault();
        dropzone.classList.add('drag-over');
    }

    /**
     * Handle drag leave event
     */
    private handleDragLeave(e: DragEvent, dropzone: HTMLElement): void {
        // Only remove class if we're actually leaving the dropzone
        const relatedTarget = e.relatedTarget as HTMLElement;
        if (!dropzone.contains(relatedTarget)) {
            dropzone.classList.remove('drag-over');
        }
    }

    /**
     * Handle drop event
     */
    private handleDrop(e: DragEvent, dropzone: HTMLElement): void {
        e.preventDefault();
        dropzone.classList.remove('drag-over');

        if (!this.draggedCard) return;

        const objectId = this.draggedCard.dataset.objectId || '';
        const newColumnValue = dropzone.dataset.columnValue || '';
        const oldColumnValue = this.draggedCard.closest('[data-kanban-dropzone]')?.getAttribute('data-column-value') || '';

        // Determine insert position based on placeholder
        let insertBeforeCard: HTMLElement | null = null;
        if (this.draggedCardPlaceholder && this.draggedCardPlaceholder.parentNode === dropzone) {
            // Get the card after the placeholder (if any)
            const nextSibling = this.draggedCardPlaceholder.nextElementSibling;
            if (nextSibling && nextSibling.hasAttribute('data-kanban-card')) {
                insertBeforeCard = nextSibling as HTMLElement;
            }
        }

        // Remove placeholder
        if (this.draggedCardPlaceholder && this.draggedCardPlaceholder.parentNode) {
            this.draggedCardPlaceholder.parentNode.removeChild(this.draggedCardPlaceholder);
        }

        // Use shared move logic
        this.moveKanbanCard(this.draggedCard, dropzone, insertBeforeCard, objectId, oldColumnValue, newColumnValue);
    }

    /**
     * Update the item counts in column headers
     */
    private updateColumnCounts(): void {
        if (!this.kanbanBoard) return;

        const columns = this.kanbanBoard.querySelectorAll('[data-kanban-column]');
        columns.forEach(column => {
            const dropzone = column.querySelector('[data-kanban-dropzone]');
            const countBadge = column.querySelector('.kanban-column-header span');
            
            if (dropzone && countBadge) {
                const cardCount = dropzone.querySelectorAll('[data-kanban-card]').length;
                countBadge.textContent = cardCount.toString();
            }
        });
    }

    /**
     * Get the dataview URL from hidden input
     * Note: This might need adjustment based on where the URL is stored in the new structure
     */
    private getDataViewUrl(): string {
        // Assuming the URL input might still be named similarly or we use the current URL
        // For now, let's look for the input with the old ID pattern or a new one
        const urlInput = document.getElementById(`data-table-${this.contentTypeId}-url`) as HTMLInputElement;
        return urlInput?.value || '';
    }

    /**
     * Reload the dataview with optional query parameters
     */
    public reload(requestParams?: string): void {
        // Target the data section for reload
        const targetId = `data-table-data-section`; // Or dynamic based on content type?
        // In data_table.html, the target is often #data-table-data-section (which is inside the view)
        // But HTMX usually handles this via attributes on elements.
        // If we need manual reload:
        
        const url = this.getDataViewUrl();
        if (!url) return;

        const fullUrl = requestParams ? `${url}?${requestParams}` : url;
        // We might want to target the container or a specific part
        window.htmx.ajax('GET', fullUrl, `#${this.containerId}`); 
    }

    /**
     * Set up context menu on table cells and other triggers
     */
    private setupContextMenu(): void {
        if (!this.contentTypeId || !this.abortController) return;
        
        // Initialize context menu element
        this.contextMenu = document.getElementById(`data-table-${this.contentTypeId}-context-menu`);
        if (!this.contextMenu) return;

        // Use event delegation on the container
        if (this.container) {
            this.container.addEventListener('contextmenu', (e: MouseEvent) => {
                const target = e.target as HTMLElement;
                const trigger = target.closest('td[allow-context-menu], [data-context-menu-trigger]') as DataViewContextTrigger;
                
                if (trigger) {
                    e.preventDefault();
                    this.showContextMenu(trigger, e, false);
                }
            }, { signal: this.abortController.signal });
        }

        // Hide context menu on any click outside the menu
        document.addEventListener('click', (e: MouseEvent) => {
            if (this.contextMenu && !this.contextMenu.contains(e.target as Node)) {
                this.hideContextMenu();
            }
        }, { signal: this.abortController.signal });
    }

    /**
     * Show context menu at mouse position
     */
    private showContextMenu(trigger: DataViewContextTrigger, event: MouseEvent, openedViaKeyboard: boolean = false): void {
        if (!this.contextMenu) return;

        this.currentTrigger = trigger;
        this.contextMenuOpen = true;
        this.contextMenuItemIndex = -1;
        this.contextMenuOpenedViaKeyboard = openedViaKeyboard;

        // Update menu items based on view type
        this.updateContextMenuItems(trigger.dataset.applicationFieldId);

        // Position menu at mouse coordinates (fixed positioning)
        const position = this.calculateContextMenuPosition(event);

        // Position and display the menu
        this.contextMenu.style.left = `${position.x}px`;
        this.contextMenu.style.top = `${position.y}px`;
        this.contextMenu.classList.remove('hidden');

        // Set up context menu keyboard navigation
        this.setupContextMenuKeyboardNavigation();
    }

    /**
     * Update context menu items based on view type
     */
    private updateContextMenuItems(applicationFieldId?:string): void {
        if (!this.contentTypeId) return;
        const target = `#data-table-${this.contentTypeId}-context-menu`;
        let baseUrl = `/components/dataview_context_menu/${this.viewType}/`;
        
        // Add application field ID get parameter if provided
        if (applicationFieldId) {
            baseUrl += `?application_field_id=${applicationFieldId}`;
        }

        htmx.ajax(
            'get',
            baseUrl,
            {
                target: target,
                swap: 'innerHTML'
            }
        ).then(() => {
            // After HTMX renders the menu, set up action handlers and focus
            this.setupContextMenuActionHandlers();
            
            // If opened via keyboard, focus on first item
            if (this.contextMenuOpenedViaKeyboard) {
                this.focusFirstContextMenuItem();
            }
        });
    }

    /**
     * Set up action handlers for context menu items after HTMX render
     */
    private setupContextMenuActionHandlers(): void {
        if (!this.contextMenu) return;
        
        const buttons = this.contextMenu.querySelectorAll('button[data-action]');
        buttons.forEach((button) => {
            button.addEventListener('click', (e: Event) => {
                e.preventDefault();
                e.stopPropagation(); // Prevent the document click handler from hiding the menu before action executes
                const action = (button as HTMLElement).dataset.action;
                if (action) {
                    this.handleContextMenuAction(action);
                }
            });
        });
    }

    /**
     * Handle context menu action
     */
    private handleContextMenuAction(action: string): void {
        if (!this.currentTrigger) {
            this.hideContextMenu();
            return;
        }

        const applicationFieldId = this.currentTrigger.dataset.applicationFieldId;
        const element = this.currentTrigger;

        switch (action) {
            case 'copy':
                this.copyCurrentTriggerValue();
                break;
            case 'edit':
                this.editCurrentTrigger();
                break;
            case 'filter':
                this.filterByCurrentTrigger();
                break;
            case 'goto':
                this.gotoCurrentTrigger();
                break;
            case 'download':
                this.downloadCurrentTrigger();
                break;
            default:
                console.warn(`Unknown context menu action: ${action}`);
        }
    }

    /**
     * Focus on the first context menu item
     */
    private focusFirstContextMenuItem(): void {
        const menuItems = this.getVisibleContextMenuItems();
        if (menuItems.length > 0) {
            this.contextMenuItemIndex = 0;
            const firstItem = menuItems[0] as HTMLElement;
            firstItem.classList.add('bg-gray-100');
            firstItem.focus();
        }
    }

    /**
     * Navigate to the current trigger's object
     */
    private gotoCurrentTrigger(): void {
        if (!this.currentTrigger) return;
        
        const objectId = this.currentTrigger.dataset.objectId;
        if (!objectId || !this.contentTypeId) return;
        
        // Try to find a link within the row to navigate
        const row = this.currentTrigger.closest('tr');
        if (row) {
            const link = row.querySelector('a[hx-get]') as HTMLAnchorElement;
            if (link) {
                link.click();
                this.hideContextMenu();
                return;
            }
        }
        
        // Fallback: construct URL based on content type and object ID
        this.showMessage('Navigation coming soon', 'info');
        this.hideContextMenu();
    }

    /**
     * Download related to the current trigger
     */
    private downloadCurrentTrigger(): void {
        if (!this.currentTrigger) return;
        
        this.showMessage('Download coming soon', 'info');
        this.hideContextMenu();
    }

    /**
     * Calculate context menu position to avoid overflow
     */
    private calculateContextMenuPosition(event: MouseEvent): ContextMenuPosition {
        if (!this.contextMenu) return { x: 0, y: 0 };

        // Use pageX/pageY for absolute positioning relative to document
        let x = event.pageX;
        let y = event.pageY;

        const menuWidth = this.contextMenu.offsetWidth || 160;
        const menuHeight = this.contextMenu.offsetHeight || 200;

        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;

        // Adjust if menu would go off right edge
        if (event.clientX + menuWidth > viewportWidth) {
            x = event.pageX - menuWidth;
        }

        // Adjust if menu would go off bottom edge
        if (event.clientY + menuHeight > viewportHeight) {
            y = event.pageY - menuHeight;
        }

        return { x, y };
    }

    /**
     * Toggle filter option visibility based on trigger attributes
     */
    private toggleFilterOption(trigger: DataViewContextTrigger): void {
        if (!this.contentTypeId) return;
        const filterListItem = document.getElementById(`data-table-${this.contentTypeId}-context-menu-filter-value-list-item`);

        if (filterListItem) {
            filterListItem.style.display = trigger.dataset.contextMenuFilterValue ? 'block' : 'none';
        }
    }

    /**
     * Hide context menu
     */
    private hideContextMenu(): void {
        if (this.contextMenu) {
            this.contextMenu.classList.add('hidden');
        }
        
        // Clean up context menu navigation state
        this.contextMenuOpen = false;
        this.contextMenuItemIndex = -1;
        this.removeContextMenuHighlight();
        
        // Abort context menu keyboard listeners
        if (this.contextMenuAbortController) {
            this.contextMenuAbortController.abort();
            this.contextMenuAbortController = null;
        }
    }

    /**
     * Set up keyboard navigation for the context menu
     */
    private setupContextMenuKeyboardNavigation(): void {
        // Abort previous context menu listeners if any
        if (this.contextMenuAbortController) {
            this.contextMenuAbortController.abort();
        }
        
        // Create new AbortController for context menu listeners
        this.contextMenuAbortController = new AbortController();
        
        // Use capture phase to intercept events before other handlers
        document.addEventListener('keydown', (e: KeyboardEvent) => {
            if (!this.contextMenuOpen) return;
            
            switch (e.key) {
                case NAVIGATION_KEYS.MOVE_DOWN:
                    e.preventDefault();
                    e.stopPropagation();
                    this.navigateContextMenu(1);
                    break;
                case NAVIGATION_KEYS.MOVE_UP:
                    e.preventDefault();
                    e.stopPropagation();
                    this.navigateContextMenu(-1);
                    break;
                case NAVIGATION_KEYS.SELECT:
                    e.preventDefault();
                    e.stopPropagation();
                    this.selectContextMenuItem();
                    break;
                case NAVIGATION_KEYS.EXIT_NAVIGATION:
                    e.preventDefault();
                    e.stopPropagation();
                    this.closeContextMenuAndReturnFocus();
                    break;
            }
        }, { capture: true, signal: this.contextMenuAbortController.signal });
    }

    /**
     * Navigate through context menu items
     */
    private navigateContextMenu(direction: number): void {
        const menuItems = this.getVisibleContextMenuItems();
        if (menuItems.length === 0) return;
        
        // Remove previous highlight
        this.removeContextMenuHighlight();
        
        // Update index
        const newIndex = this.contextMenuItemIndex + direction;
        
        // If going down past the end, close menu and return to view
        if (newIndex >= menuItems.length) {
            this.closeContextMenuAndReturnFocus();
            return;
        }
        
        // If going up past the beginning, close menu and return to view
        if (newIndex < 0) {
            this.closeContextMenuAndReturnFocus();
            return;
        }
        
        this.contextMenuItemIndex = newIndex;
        
        // Highlight new item
        const currentItem = menuItems[this.contextMenuItemIndex] as HTMLElement;
        currentItem.classList.add('bg-gray-100');
        currentItem.focus();
    }

    /**
     * Get visible context menu items (buttons that are not hidden)
     */
    private getVisibleContextMenuItems(): HTMLButtonElement[] {
        if (!this.contextMenu) return [];
        
        const allButtons = this.contextMenu.querySelectorAll('button');
        const visibleButtons: HTMLButtonElement[] = [];
        
        allButtons.forEach(button => {
            const listItem = button.closest('li');
            // Check if the button's parent li is visible
            if (!listItem || listItem.style.display !== 'none') {
                visibleButtons.push(button);
            }
        });
        
        return visibleButtons;
    }

    /**
     * Remove highlight from context menu items
     */
    private removeContextMenuHighlight(): void {
        if (!this.contextMenu) return;
        
        const buttons = this.contextMenu.querySelectorAll('button');
        buttons.forEach(button => {
            button.classList.remove('bg-gray-100');
        });
    }

    /**
     * Select the currently highlighted context menu item
     */
    private selectContextMenuItem(): void {
        const menuItems = this.getVisibleContextMenuItems();
        if (this.contextMenuItemIndex >= 0 && this.contextMenuItemIndex < menuItems.length) {
            const currentItem = menuItems[this.contextMenuItemIndex];
            currentItem.click();
        }
    }

    /**
     * Close context menu and return focus to the data view
     */
    private closeContextMenuAndReturnFocus(): void {
        this.hideContextMenu();
        
        // Return focus to the navigable element
        const navigableElement = this.getNavigableElement();
        if (navigableElement) {
            navigableElement.focus();
        }
    }

    /**
     * Copy current trigger value to clipboard
     */
    private async copyCurrentTriggerValue(): Promise<void> {
        if (!this.currentTrigger) return;

        try {
            const text = this.currentTrigger.textContent || '';
            // strip leading/trailing whitespace
            const trimmedText = text.trim();
            await navigator.clipboard.writeText(trimmedText);
            this.hideContextMenu();
            this.showMessage('Value copied to clipboard', 'info');
        } catch (err) {
            console.error('Failed to copy text:', err);
            this.showMessage('Failed to copy value', 'error');
        }
    }

    /**
     * Filter dataview by current trigger value
     */
    private filterByCurrentTrigger(): void {
        if (!this.currentTrigger) return;

        const filterValue = this.currentTrigger.dataset.contextMenuFilterValue;
        if (!filterValue) return;

        // Prevent duplicate filters
        if (this.currentTrigger.classList.contains('filtered')) {
            this.hideContextMenu();
            return;
        }

        this.applyFilter(filterValue);
        this.currentTrigger.classList.add('filtered');
        this.hideContextMenu();
    }

    /**
     * Apply filter to dataview
     */
    private applyFilter(filterParam: string): void {
        const url = this.getDataViewUrl();
        if (!url) return;

        // Check if URL already has params
        const separator = url.includes('?') ? '&' : '?';
        const fullUrl = `${url}${separator}${filterParam}`;

        window.htmx.ajax('GET', fullUrl, `#${this.containerId}`);
        
        this.showMessage('Dataview filtered', 'info');
    }

    /**
     * Edit current trigger
     */
    private editCurrentTrigger(): void {
        if (!this.currentTrigger || !this.contentTypeId) {
            this.hideContextMenu();
            return;
        }

        const applicationFieldId = this.currentTrigger.dataset.applicationFieldId;
        const objectId = this.currentTrigger.dataset.objectId;
        
        if (!applicationFieldId) {
            this.showMessage('No field selected for editing', 'warning');
            this.hideContextMenu();
            return;
        }

        // Fetch the inline edit component
        const editUrl = `/components/data_view_edit_field/${this.contentTypeId}/${applicationFieldId}/?object_id=${objectId}`;
        
        htmx.ajax(
            'get',
            editUrl,
            {
                target: this.currentTrigger,
                swap: 'innerHTML'
            }
        ).then(() => {
            // Focus on the input after it's rendered
            const input = this.currentTrigger?.querySelector('input, select, textarea') as HTMLElement;
            if (input) {
                input.focus();
            }
        });

        this.hideContextMenu();
    }

    /**
     * Delete current item (row or card)
     */
    private deleteCurrentItem(): void {
        if (!this.currentTrigger) return;

        const objectId = this.currentTrigger.dataset.objectId;

        if (!objectId) return;

        const itemType = this.viewType === 'kanban' ? 'card' : 'row';
        const confirmed = confirm(`Are you sure you want to delete this ${itemType}?`);
        if (!confirmed) {
            this.hideContextMenu();
            return;
        }

        console.log(`Delete ${itemType}:`, objectId);
        this.showMessage('Delete functionality coming soon', 'warning');
        this.hideContextMenu();
    }

    /**
     * Show a message to the user
     */
    private showMessage(message: string, type: 'success' | 'info' | 'warning' | 'error'): void {
        if (typeof (window as any).showMessage === 'function') {
            (window as any).showMessage(message, type);
        } else {
            console.log(`[${type.toUpperCase()}] ${message}`);
        }
    }

    /**
     * Reinitialize the dataview after HTMX updates
     */
    public reinitialize(): void {
        // Check if the container still exists
        const container = document.getElementById(this.containerId);
        if (!container) {
            console.warn(`DataView: Container "${this.containerId}" no longer exists`);
            return;
        }
        
        // Check if the render ID has changed (i.e., content was actually re-rendered)
        const newRenderId = container.dataset.renderId || null;
        if (newRenderId && newRenderId === this.currentRenderId) {
            console.log(`DataView: Same render ID ${newRenderId}, skipping reinitialization`);
            return;
        }
        
        // Force reinitialization by clearing the current render ID
        this.currentRenderId = null;
        this.initialize();
    }

    /**
     * Set up keyboard navigation based on view type
     */
    private setupKeyboardNavigation(): void {
        const navigableElement = this.getNavigableElement();
        if (!navigableElement || !this.abortController) return;

        navigableElement.addEventListener('keydown', (e: KeyboardEvent) => {
            // Don't handle navigation if context menu is open (handled separately)
            if (this.contextMenuOpen) return;
            
            // Only handle navigation keys
            const handledKeys = [
                NAVIGATION_KEYS.MOVE_UP,
                NAVIGATION_KEYS.MOVE_DOWN,
                NAVIGATION_KEYS.MOVE_LEFT,
                NAVIGATION_KEYS.MOVE_RIGHT,
                NAVIGATION_KEYS.SELECT,
                NAVIGATION_KEYS.EXIT_NAVIGATION
            ];

            if (!handledKeys.includes(e.key as any)) return;
            
            e.preventDefault();

            // Check for modifier key combinations
            const hasContextMenuModifier = e[NAVIGATION_KEYS.CONTEXT_MENU_MODIFIER];
            const hasMoveItemModifier = e[NAVIGATION_KEYS.MOVE_ITEM_MODIFIER];

            // Handle context menu with modifier key + MOVE_DOWN
            if (e.key === NAVIGATION_KEYS.MOVE_DOWN && hasContextMenuModifier) {
                this.handleOpenContextMenu();
                return;
            }

            // Handle kanban card movement with modifier key + MOVE_LEFT/RIGHT
            if (this.viewType === 'kanban' && hasMoveItemModifier) {
                if (e.key === NAVIGATION_KEYS.MOVE_LEFT) {
                    this.moveKanbanCardToColumn(-1);
                    return;
                } else if (e.key === NAVIGATION_KEYS.MOVE_RIGHT) {
                    this.moveKanbanCardToColumn(1);
                    return;
                }
            }

            // Dispatch to view-specific handlers
            this.handleNavigationKey(e.key);
        }, { signal: this.abortController.signal });
    }

    /**
     * Get the navigable element for the current view type
     */
    private getNavigableElement(): HTMLElement | null {
        switch (this.viewType) {
            case 'table':
                return this.table;
            case 'kanban':
                return this.kanbanBoard;
            case 'calendar':
                return this.calendarElement;
            default:
                return null;
        }
    }

    /**
     * Handle navigation key press - dispatches to view-specific logic
     */
    private handleNavigationKey(key: string): void {
        switch (this.viewType) {
            case 'table':
                this.handleTableNavigation(key);
                break;
            case 'kanban':
                this.handleKanbanNavigation(key);
                break;
            case 'calendar':
                this.handleCalendarNavigation(key);
                break;
        }
    }

    /**
     * Handle opening context menu via keyboard
     */
    private handleOpenContextMenu(): void {
        switch (this.viewType) {
            case 'table':
                // If in cell navigation mode, open on selected cell
                // Otherwise, open on the first cell of the selected row
                if (this.cellNavigationMode) {
                    this.openContextMenuOnSelectedCell();
                } else if (this.selectedRowIndex >= 0) {
                    // Enter cell navigation mode and open on first cell
                    this.selectedCellIndex = 0;
                    this.cellNavigationMode = true;
                    this.highlightTableSelectedCell();
                    this.openContextMenuOnSelectedCell();
                }
                break;
            case 'kanban':
                this.openContextMenuOnSelectedCard();
                break;
            case 'calendar':
                this.openContextMenuOnSelectedEvent();
                break;
        }
    }

    // ==================== TABLE NAVIGATION ====================

    /**
     * Handle table-specific navigation
     */
    private handleTableNavigation(key: string): void {
        switch (key) {
            case NAVIGATION_KEYS.MOVE_DOWN:
                this.moveTableSelection(1);
                break;
            case NAVIGATION_KEYS.MOVE_UP:
                this.moveTableSelection(-1);
                break;
            case NAVIGATION_KEYS.SELECT:
                this.handleTableEnterKey();
                break;
            case NAVIGATION_KEYS.MOVE_RIGHT:
                this.handleTableArrowRight();
                break;
            case NAVIGATION_KEYS.MOVE_LEFT:
                this.handleTableArrowLeft();
                break;
            case NAVIGATION_KEYS.EXIT_NAVIGATION:
                this.exitTableNavigationMode();
                break;
        }
    }

    /**
     * Move table row selection by direction
     */
    private moveTableSelection(direction: number): void {
        const rows = this.table?.querySelectorAll('tbody tr');
        if (!rows || rows.length === 0) return;

        if (this.selectedRowIndex >= 0 && this.selectedRowIndex < rows.length) {
            rows[this.selectedRowIndex].classList.remove('bg-gray-100');
        }

        this.selectedRowIndex += direction;

        if (this.selectedRowIndex < 0) {
            this.selectedRowIndex = 0;
        } else if (this.selectedRowIndex >= rows.length) {
            this.selectedRowIndex = rows.length - 1;
        }

        const newRow = rows[this.selectedRowIndex] as HTMLElement;
        newRow.classList.add('bg-gray-100');
        newRow.scrollIntoView({ block: 'nearest' });
        
        // If in cell navigation mode, update cell highlight for new row
        if (this.cellNavigationMode) {
            this.highlightTableSelectedCell();
        }
    }

    /**
     * Handle Enter key press on selected table row
     */
    private handleTableEnterKey(): void {
        if (this.selectedRowIndex === -1 || !this.table) return;
        
        const rows = this.table.querySelectorAll('tbody tr');
        if (this.selectedRowIndex < rows.length) {
            const row = rows[this.selectedRowIndex] as HTMLElement;
            row.click();
        }
    }

    /**
     * Handle right arrow in table - enter cell navigation or move right
     */
    private handleTableArrowRight(): void {
        if (this.selectedRowIndex === -1 || !this.table) return;
        
        const rows = this.table.querySelectorAll('tbody tr');
        if (this.selectedRowIndex >= rows.length) return;
        
        const currentRow = rows[this.selectedRowIndex];
        const cells = currentRow.querySelectorAll('td');
        
        if (cells.length === 0) return;
        
        // Enter cell navigation mode if not already in it
        if (!this.cellNavigationMode) {
            this.cellNavigationMode = true;
            this.selectedCellIndex = 0;
        } else {
            // Move to next cell
            if (this.selectedCellIndex < cells.length - 1) {
                this.selectedCellIndex++;
            }
        }
        
        this.highlightTableSelectedCell();
    }

    /**
     * Handle left arrow in table - enter cell navigation or move left
     */
    private handleTableArrowLeft(): void {
        if (this.selectedRowIndex === -1 || !this.table) return;
        
        const rows = this.table.querySelectorAll('tbody tr');
        if (this.selectedRowIndex >= rows.length) return;
        
        const currentRow = rows[this.selectedRowIndex];
        const cells = currentRow.querySelectorAll('td');
        
        if (cells.length === 0) return;
        
        // Enter cell navigation mode if not already in it
        if (!this.cellNavigationMode) {
            this.cellNavigationMode = true;
            this.selectedCellIndex = cells.length - 1; // Start from rightmost cell
        } else {
            // Move to previous cell
            if (this.selectedCellIndex > 0) {
                this.selectedCellIndex--;
            }
        }
        
        this.highlightTableSelectedCell();
    }

    /**
     * Highlight the currently selected table cell with a border
     */
    private highlightTableSelectedCell(): void {
        if (!this.table) return;
        
        // Remove highlight from all cells
        this.table.querySelectorAll('td.cell-selected').forEach(cell => {
            cell.classList.remove('cell-selected');
        });
        
        if (this.selectedRowIndex === -1 || this.selectedCellIndex === -1) return;
        
        const rows = this.table.querySelectorAll('tbody tr');
        if (this.selectedRowIndex >= rows.length) return;
        
        const currentRow = rows[this.selectedRowIndex];
        const cells = currentRow.querySelectorAll('td');
        
        if (this.selectedCellIndex < cells.length) {
            const cell = cells[this.selectedCellIndex] as HTMLElement;
            cell.classList.add('cell-selected');
        }
    }

    /**
     * Exit table cell navigation mode
     */
    private exitTableNavigationMode(): void {
        this.cellNavigationMode = false;
        this.selectedCellIndex = -1;
        this.navigationMode = false;
        
        // Remove cell highlight
        if (this.table) {
            this.table.querySelectorAll('td.cell-selected').forEach(cell => {
                cell.classList.remove('cell-selected');
            });
        }
    }

    /**
     * Open context menu on the currently selected table cell
     */
    private openContextMenuOnSelectedCell(): void {
        if (!this.table || this.selectedRowIndex === -1 || this.selectedCellIndex === -1) return;
        
        const rows = this.table.querySelectorAll('tbody tr');
        if (this.selectedRowIndex >= rows.length) return;
        
        const currentRow = rows[this.selectedRowIndex];
        const cells = currentRow.querySelectorAll('td');
        
        if (this.selectedCellIndex >= cells.length) return;
        
        const cell = cells[this.selectedCellIndex] as HTMLElement;
        this.openContextMenuOnElement(cell, true);
    }

    // ==================== KANBAN NAVIGATION ====================

    /**
     * Handle kanban-specific navigation
     */
    private handleKanbanNavigation(key: string): void {
        switch (key) {
            case NAVIGATION_KEYS.MOVE_DOWN:
                this.moveKanbanCardSelection(1);
                break;
            case NAVIGATION_KEYS.MOVE_UP:
                this.moveKanbanCardSelection(-1);
                break;
            case NAVIGATION_KEYS.MOVE_RIGHT:
                this.moveKanbanColumnSelection(1);
                break;
            case NAVIGATION_KEYS.MOVE_LEFT:
                this.moveKanbanColumnSelection(-1);
                break;
            case NAVIGATION_KEYS.SELECT:
                this.handleKanbanEnterKey();
                break;
            case NAVIGATION_KEYS.EXIT_NAVIGATION:
                this.exitKanbanNavigationMode();
                break;
        }
    }

    /**
     * Get the currently selected kanban card element
     */
    private getSelectedKanbanCard(): HTMLElement | null {
        if (!this.kanbanBoard || this.selectedColumnIndex === -1 || this.selectedCardIndex === -1) {
            return null;
        }
        
        const columns = this.kanbanBoard.querySelectorAll('[data-kanban-dropzone]');
        if (this.selectedColumnIndex >= columns.length) return null;
        
        const currentColumn = columns[this.selectedColumnIndex];
        const cards = currentColumn.querySelectorAll('[data-kanban-card]');
        
        if (this.selectedCardIndex >= cards.length) return null;
        
        return cards[this.selectedCardIndex] as HTMLElement;
    }

    /**
     * Highlight the selected kanban card
     */
    private highlightKanbanCard(card: HTMLElement): void {
        card.classList.add('ring-2', 'ring-primary');
        card.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }

    /**
     * Remove highlight from a kanban card
     */
    private unhighlightKanbanCard(card: HTMLElement): void {
        card.classList.remove('ring-2', 'ring-primary');
    }

    /**
     * Move kanban card selection within a column (up/down)
     */
    private moveKanbanCardSelection(direction: number): void {
        if (!this.kanbanBoard) return;
        
        const columns = this.kanbanBoard.querySelectorAll('[data-kanban-dropzone]');
        if (columns.length === 0) return;
        
        // If no column selected, select the first one
        if (this.selectedColumnIndex === -1) {
            this.selectedColumnIndex = 0;
            this.selectedCardIndex = -1;
        }
        
        const currentColumn = columns[this.selectedColumnIndex];
        const cards = currentColumn.querySelectorAll('[data-kanban-card]');
        
        if (cards.length === 0) return;
        
        // Remove previous selection
        const previousCard = this.getSelectedKanbanCard();
        if (previousCard) {
            this.unhighlightKanbanCard(previousCard);
        }
        
        // Update selection index
        if (this.selectedCardIndex === -1) {
            // First time selecting in this column
            this.selectedCardIndex = direction > 0 ? 0 : cards.length - 1;
        } else {
            this.selectedCardIndex += direction;
        }
        
        // Clamp to valid range
        if (this.selectedCardIndex < 0) {
            this.selectedCardIndex = 0;
        } else if (this.selectedCardIndex >= cards.length) {
            this.selectedCardIndex = cards.length - 1;
        }
        
        // Highlight new selection
        const selectedCard = cards[this.selectedCardIndex] as HTMLElement;
        this.highlightKanbanCard(selectedCard);
    }

    /**
     * Move kanban column selection (left/right navigation)
     */
    private moveKanbanColumnSelection(direction: number): void {
        if (!this.kanbanBoard) return;
        
        const columns = this.kanbanBoard.querySelectorAll('[data-kanban-dropzone]');
        if (columns.length === 0) return;
        
        // Remove previous card selection
        const previousCard = this.getSelectedKanbanCard();
        if (previousCard) {
            this.unhighlightKanbanCard(previousCard);
        }
        
        // Update column index
        if (this.selectedColumnIndex === -1) {
            this.selectedColumnIndex = direction > 0 ? 0 : columns.length - 1;
        } else {
            this.selectedColumnIndex += direction;
        }
        
        // Clamp to valid range
        if (this.selectedColumnIndex < 0) {
            this.selectedColumnIndex = 0;
        } else if (this.selectedColumnIndex >= columns.length) {
            this.selectedColumnIndex = columns.length - 1;
        }
        
        // Try to maintain card position, or select first card
        const currentColumn = columns[this.selectedColumnIndex];
        const cards = currentColumn.querySelectorAll('[data-kanban-card]');
        
        if (cards.length > 0) {
            // Try to maintain same position, otherwise clamp
            if (this.selectedCardIndex === -1 || this.selectedCardIndex >= cards.length) {
                this.selectedCardIndex = Math.min(this.selectedCardIndex, cards.length - 1);
                if (this.selectedCardIndex < 0) this.selectedCardIndex = 0;
            }
            
            const selectedCard = cards[this.selectedCardIndex] as HTMLElement;
            this.highlightKanbanCard(selectedCard);
        } else {
            // No cards in this column
            this.selectedCardIndex = -1;
        }
    }

    /**
     * Move the currently selected kanban card to an adjacent column
     * @param direction -1 for left, 1 for right
     */
    private moveKanbanCardToColumn(direction: number): void {
        if (!this.kanbanBoard) return;
        
        const card = this.getSelectedKanbanCard();
        if (!card) {
            this.showMessage('No card selected', 'warning');
            return;
        }
        
        const columns = this.kanbanBoard.querySelectorAll('[data-kanban-dropzone]');
        const targetColumnIndex = this.selectedColumnIndex + direction;
        
        // Check bounds
        if (targetColumnIndex < 0 || targetColumnIndex >= columns.length) {
            this.showMessage('Cannot move card further in this direction', 'info');
            return;
        }
        
        const sourceColumn = columns[this.selectedColumnIndex];
        const targetColumn = columns[targetColumnIndex] as HTMLElement;
        
        // Get column values for logging
        const oldColumnValue = sourceColumn.getAttribute('data-column-value') || '';
        const newColumnValue = targetColumn.getAttribute('data-column-value') || '';
        const objectId = card.dataset.objectId || '';
        
        // Remove highlight before moving
        this.unhighlightKanbanCard(card);
        
        // Determine insert position - try to maintain similar position
        const targetCards = targetColumn.querySelectorAll('[data-kanban-card]');
        let insertBeforeCard: HTMLElement | null = null;
        if (this.selectedCardIndex < targetCards.length) {
            insertBeforeCard = targetCards[this.selectedCardIndex] as HTMLElement;
        }
        
        // Use shared move logic
        this.moveKanbanCard(card, targetColumn, insertBeforeCard, objectId, oldColumnValue, newColumnValue);
        
        // Update selection to follow the card
        this.selectedColumnIndex = targetColumnIndex;
        
        // Adjust card index if needed (new column might have fewer cards above)
        const newCards = targetColumn.querySelectorAll('[data-kanban-card]');
        const cardIndex = Array.from(newCards).indexOf(card);
        if (cardIndex !== -1) {
            this.selectedCardIndex = cardIndex;
        }
        
        // Re-highlight the card
        this.highlightKanbanCard(card);
    }

    /**
     * Shared method to move a kanban card to a target column
     * Used by both keyboard navigation and mouse drag-and-drop
     */
    private moveKanbanCard(
        card: HTMLElement,
        targetColumn: HTMLElement,
        insertBeforeCard: HTMLElement | null,
        objectId: string,
        oldColumnValue: string,
        newColumnValue: string
    ): void {
        // Insert the card at the specified position
        if (insertBeforeCard) {
            targetColumn.insertBefore(card, insertBeforeCard);
        } else {
            targetColumn.appendChild(card);
        }
        
        // Update column counts
        this.updateColumnCounts();
        
        // Log the move
        console.log('Card moved:', {
            objectId,
            from: oldColumnValue,
            to: newColumnValue
        });
        
        // Show feedback if column changed
        if (oldColumnValue !== newColumnValue) {
            this.showMessage(`Card moved to ${newColumnValue || 'new column'}`, 'info');
        }
    }

    /**
     * Handle Enter key on selected kanban card
     */
    private handleKanbanEnterKey(): void {
        const card = this.getSelectedKanbanCard();
        if (card) {
            card.click();
        }
    }

    /**
     * Exit kanban navigation mode
     */
    private exitKanbanNavigationMode(): void {
        if (!this.kanbanBoard) return;
        
        // Remove all selection highlights
        this.kanbanBoard.querySelectorAll('[data-kanban-card].ring-2').forEach(card => {
            card.classList.remove('ring-2', 'ring-primary');
        });
        
        this.selectedColumnIndex = -1;
        this.selectedCardIndex = -1;
        this.navigationMode = false;
    }

    /**
     * Open context menu on selected kanban card
     */
    private openContextMenuOnSelectedCard(): void {
        const card = this.getSelectedKanbanCard();
        if (card) {
            this.openContextMenuOnElement(card, true);
        }
    }

    // ==================== CALENDAR NAVIGATION ====================

    /**
     * Handle calendar-specific navigation (placeholder)
     */
    private handleCalendarNavigation(key: string): void {
        // TODO: Implement calendar navigation
        switch (key) {
            case NAVIGATION_KEYS.MOVE_DOWN:
                this.moveCalendarSelection('down');
                break;
            case NAVIGATION_KEYS.MOVE_UP:
                this.moveCalendarSelection('up');
                break;
            case NAVIGATION_KEYS.MOVE_RIGHT:
                this.moveCalendarSelection('right');
                break;
            case NAVIGATION_KEYS.MOVE_LEFT:
                this.moveCalendarSelection('left');
                break;
            case NAVIGATION_KEYS.SELECT:
                this.handleCalendarEnterKey();
                break;
            case NAVIGATION_KEYS.EXIT_NAVIGATION:
                this.exitCalendarNavigationMode();
                break;
        }
    }

    /**
     * Move calendar selection (placeholder)
     */
    private moveCalendarSelection(direction: 'up' | 'down' | 'left' | 'right'): void {
        // TODO: Implement calendar date/event navigation
        console.log(`Calendar navigation: ${direction}`);
    }

    /**
     * Handle Enter key on calendar (placeholder)
     */
    private handleCalendarEnterKey(): void {
        // TODO: Implement calendar select action
        console.log('Calendar enter key pressed');
    }

    /**
     * Exit calendar navigation mode (placeholder)
     */
    private exitCalendarNavigationMode(): void {
        this.selectedDateIndex = -1;
        this.selectedEventIndex = -1;
        this.navigationMode = false;
    }

    /**
     * Open context menu on selected calendar event (placeholder)
     */
    private openContextMenuOnSelectedEvent(): void {
        // TODO: Implement calendar context menu
        console.log('Calendar context menu requested');
    }

    // ==================== SHARED NAVIGATION HELPERS ====================

    /**
     * Open context menu on an element
     */
    private openContextMenuOnElement(element: HTMLElement, openedViaKeyboard: boolean = false): void {
        const rect = element.getBoundingClientRect();
        const syntheticEvent = {
            clientX: rect.left + rect.width / 2,
            clientY: rect.top + rect.height / 2,
            pageX: rect.left + rect.width / 2 + window.scrollX,
            pageY: rect.top + rect.height / 2 + window.scrollY
        } as MouseEvent;
        
        this.currentTrigger = element as DataViewContextTrigger;
        this.showContextMenu(element as DataViewContextTrigger, syntheticEvent, openedViaKeyboard);
    }

    /**
     * Set up global keyboard listener to enter navigation mode
     */
    private setupGlobalKeyboardListener(): void {
        if (!this.abortController) return;

        document.addEventListener('keydown', (e: KeyboardEvent) => {
            // Get navigable element, refreshing reference if needed
            let navigableElement = this.getNavigableElement();
            
            // Try to refresh element reference if it's stale (e.g. after HTMX swap)
            if (!navigableElement || !document.body.contains(navigableElement)) {
                this.refreshNavigableElement();
                navigableElement = this.getNavigableElement();
            }

            if (!navigableElement || !document.body.contains(navigableElement)) {
                return;
            }

            // Don't capture events from form inputs
            if (e.target instanceof HTMLInputElement || 
                e.target instanceof HTMLTextAreaElement || 
                e.target instanceof HTMLSelectElement) {
                return;
            }

            // Enter navigation mode on ENTER_NAVIGATION key press
            if (e.key === NAVIGATION_KEYS.ENTER_NAVIGATION && document.activeElement !== navigableElement) {
                e.preventDefault();
                this.enterNavigationMode();
            }
        }, { signal: this.abortController.signal });
    }

    /**
     * Refresh the navigable element reference (e.g. after HTMX swap)
     */
    private refreshNavigableElement(): void {
        switch (this.viewType) {
            case 'table':
                this.table = this.container?.querySelector('table') as HTMLElement;
                if (this.table) {
                    this.table.setAttribute('tabindex', '0');
                }
                break;
            case 'kanban':
                this.kanbanBoard = this.container?.querySelector('[data-kanban]') as HTMLElement;
                if (this.kanbanBoard) {
                    this.kanbanBoard.setAttribute('tabindex', '0');
                }
                break;
            case 'calendar':
                this.calendarElement = this.container?.querySelector('[data-calendar]') as HTMLElement;
                if (this.calendarElement) {
                    this.calendarElement.setAttribute('tabindex', '0');
                }
                break;
        }
    }

    /**
     * Enter navigation mode for the current view type
     */
    private enterNavigationMode(): void {
        const navigableElement = this.getNavigableElement();
        if (!navigableElement) return;

        this.navigationMode = true;
        navigableElement.focus();

        // Initialize selection based on view type
        switch (this.viewType) {
            case 'table':
                if (this.selectedRowIndex === -1) {
                    this.moveTableSelection(1);
                }
                break;
            case 'kanban':
                if (this.selectedColumnIndex === -1) {
                    this.moveKanbanColumnSelection(1);
                }
                break;
            case 'calendar':
                // TODO: Initialize calendar selection
                break;
        }
    }

    /**
     * Set up click handlers for rows to prevent propagation from buttons
     */
    private setupRowClickHandlers(): void {
        if (!this.table) return;


    }
}

/**
 * Initialize a dataview
 */
export function initDataView(config: DataViewConfig): DataView {
    return new DataView(config);
}

/**
 * Find and initialize all dataviews on the page
 */
export function initAllDataViews(): Map<string, DataView> {
    const dataViews = new Map<string, DataView>();
    const views = document.querySelectorAll('[data-dataview]');

    views.forEach(view => {
        if (view.id) {
            const dataView = new DataView({ containerId: view.id });
            dataViews.set(view.id, dataView);
        }
    });

    return dataViews;
}
