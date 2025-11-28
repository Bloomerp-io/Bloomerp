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

import type { DataViewConfig, DataViewContextTrigger, ContextMenuPosition } from '../types/bloomerp';


/**
 * DataView class handles all dataview interactions
 */
export class DataView {
    private containerId: string;
    private container: HTMLElement | null = null;
    private viewType: string = 'table';
    private contentTypeId: string | null = null;
    private splitView: boolean = false;
    
    // Table specific properties
    private table: HTMLElement | null = null;
    private contextMenu: HTMLElement | null = null;
    private currentTrigger: DataViewContextTrigger | null = null;
    private selectedRowIndex: number = -1;
    private globalKeydownListener: ((e: KeyboardEvent) => void) | null = null;

    // Kanban specific properties
    private kanbanBoard: HTMLElement | null = null;
    private draggedCard: HTMLElement | null = null;
    private draggedCardPlaceholder: HTMLElement | null = null;

    constructor(config: DataViewConfig) {
        this.containerId = config.containerId;
        this.initialize();
    }

    /**
     * Initialize the dataview
     */
    private initialize(): void {
        console.log(`Initializing DataView: ${this.viewType}`);
        this.container = document.getElementById(this.containerId);

        if (!this.container) {
            console.warn(`DataView: Container with ID "${this.containerId}" not found`);
            return;
        }

        this.contentTypeId = this.container.dataset.contentTypeId || null;
        this.viewType = this.container.dataset.viewType || 'table';

        if (this.viewType === 'table') {
            this.initializeTableView();
        } else if (this.viewType === 'kanban') {
            this.initializeKanbanView();
        } else if (this.viewType === 'calendar') {
            // Future calendar view initialization
            this.inializeCalendarView();
        }

        // Initialize context menu for all view types
        this.setupContextMenu();
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

        this.setupKeyboardNavigation();
        this.setupGlobalKeyboardListener();
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

        console.log('Initializing Kanban View with drag-and-drop');
        this.setupKanbanDragAndDrop();
    }

    /**
     * Initialize calendar view specific logic
     */
    private inializeCalendarView() : void {
        // Future calendar view initialization
        const calendarElement:HTMLElement | null = this.container?.querySelector('[calendar]');

        console.log(calendarElement);
        if (!calendarElement) {
            console.warn('Calendar element not found');
            return;
        }
        
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

        const objectId = e.dataTransfer?.getData('text/plain');
        const newColumnValue = dropzone.dataset.columnValue;
        const oldColumnValue = this.draggedCard.closest('[data-kanban-dropzone]')?.getAttribute('data-column-value');

        // Insert the card at the placeholder position
        if (this.draggedCardPlaceholder && this.draggedCardPlaceholder.parentNode === dropzone) {
            dropzone.insertBefore(this.draggedCard, this.draggedCardPlaceholder);
        } else {
            dropzone.appendChild(this.draggedCard);
        }

        // Remove placeholder
        if (this.draggedCardPlaceholder && this.draggedCardPlaceholder.parentNode) {
            this.draggedCardPlaceholder.parentNode.removeChild(this.draggedCardPlaceholder);
        }

        // Update column counts
        this.updateColumnCounts();

        // Log the move (saving is not implemented yet as per requirements)
        console.log('Card moved:', {
            objectId,
            from: oldColumnValue,
            to: newColumnValue
        });

        // Show a message that saving is not yet implemented
        if (oldColumnValue !== newColumnValue) {
            this.showMessage('Card moved (changes not saved to server yet)', 'info');
        }
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
        if (!this.contentTypeId) return;
        
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
                    this.showContextMenu(trigger, e);
                }
            });
        }

        // Hide context menu on any click
        document.addEventListener('click', () => {
            this.hideContextMenu();
        });

        // Set up context menu actions
        this.setupContextMenuActions();
    }

    /**
     * Show context menu at mouse position
     */
    private showContextMenu(trigger: DataViewContextTrigger, event: MouseEvent): void {
        if (!this.contextMenu) return;

        this.currentTrigger = trigger;

        // Update menu items based on view type
        this.updateContextMenuItems();

        // Position menu at mouse coordinates (fixed positioning)
        const position = this.calculateContextMenuPosition(event);

        // Position and display the menu
        this.contextMenu.style.left = `${position.x}px`;
        this.contextMenu.style.top = `${position.y}px`;
        this.contextMenu.classList.remove('hidden');

        // Show/hide filter option based on trigger attributes
        this.toggleFilterOption(trigger);
    }

    /**
     * Update context menu items based on view type
     */
    private updateContextMenuItems(): void {
        if (!this.contentTypeId) return;
        const prefix = `data-table-${this.contentTypeId}-context-menu`;

        const deleteBtn = document.getElementById(`${prefix}-delete-row`);
        const copyBtn = document.getElementById(`${prefix}-copy-value`);
        
        if (deleteBtn) {
            if (this.viewType === 'kanban') {
                deleteBtn.innerHTML = '<i class="bi bi-trash"></i> Delete Card';
            } else {
                deleteBtn.innerHTML = '<i class="bi bi-trash"></i> Delete Row';
            }
        }

        if (copyBtn) {
             if (this.viewType === 'kanban') {
                copyBtn.innerHTML = '<i class="bi bi-clipboard"></i> Copy Title';
            } else {
                copyBtn.innerHTML = '<i class="bi bi-clipboard"></i> Copy Cell';
            }
        }
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
    }

    /**
     * Set up context menu action handlers
     */
    private setupContextMenuActions(): void {
        if (!this.contentTypeId) return;
        const prefix = `data-table-${this.contentTypeId}-context-menu`;

        // Copy value action
        const copyButton = document.getElementById(`${prefix}-copy-value`);
        if (copyButton) {
            copyButton.addEventListener('click', (e: Event) => {
                e.preventDefault();
                this.copyCurrentTriggerValue();
            });
        }

        // Filter value action
        const filterButton = document.getElementById(`${prefix}-filter-value`);
        if (filterButton) {
            filterButton.addEventListener('click', (e: Event) => {
                e.preventDefault();
                this.filterByCurrentTrigger();
            });
        }

        // Edit cell action
        const editButton = document.getElementById(`${prefix}-edit-value`);
        if (editButton) {
            editButton.addEventListener('click', (e: Event) => {
                e.preventDefault();
                this.editCurrentTrigger();
            });
        }

        // Delete row action
        const deleteButton = document.getElementById(`${prefix}-delete-row`);
        if (deleteButton) {
            deleteButton.addEventListener('click', (e: Event) => {
                e.preventDefault();
                this.deleteCurrentItem();
            });
        }

        // Close menu on Escape key
        document.addEventListener('keydown', (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                this.hideContextMenu();
            }
        });
    }

    /**
     * Copy current trigger value to clipboard
     */
    private async copyCurrentTriggerValue(): Promise<void> {
        if (!this.currentTrigger) return;

        try {
            const text = this.currentTrigger.textContent || '';
            await navigator.clipboard.writeText(text);
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
        if (!this.currentTrigger) return;

        this.showMessage('Edit functionality coming soon', 'info');
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
        // Clean up existing listeners if needed
        if (this.globalKeydownListener) {
            document.removeEventListener('keydown', this.globalKeydownListener);
            this.globalKeydownListener = null;
        }

        // Clean up kanban state
        this.draggedCard = null;
        this.draggedCardPlaceholder = null;
        this.kanbanBoard = null;

        // Re-run initialization logic
        this.initialize();
    }

    /**
     * Set up keyboard navigation for the table
     */
    private setupKeyboardNavigation(): void {
        if (!this.table) return;

        this.table.addEventListener('keydown', (e: KeyboardEvent) => {
            if (['ArrowUp', 'ArrowDown', 'Enter'].includes(e.key)) {
                e.preventDefault();
                
                switch (e.key) {
                    case 'ArrowDown':
                        this.moveSelection(1);
                        break;
                    case 'ArrowUp':
                        this.moveSelection(-1);
                        break;
                    case 'Enter':
                        this.handleEnterKey();
                        break;
                }
            }
        });
    }

    /**
     * Move row selection by direction
     */
    private moveSelection(direction: number): void {
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
    }

    /**
     * Handle Enter key press on selected row
     */
    private handleEnterKey(): void {
        if (this.selectedRowIndex === -1 || !this.table) return;
        
        const rows = this.table.querySelectorAll('tbody tr');
        if (this.selectedRowIndex < rows.length) {
            const row = rows[this.selectedRowIndex] as HTMLElement;
            row.click();
        }
    }

    /**
     * Set up global keyboard listener for table activation
     */
    private setupGlobalKeyboardListener(): void {
        if (this.globalKeydownListener) {
            document.removeEventListener('keydown', this.globalKeydownListener);
        }

        this.globalKeydownListener = (e: KeyboardEvent) => {
            // Only allow global keyboard navigation in table view
            if (this.viewType !== 'table') return;

            // Refresh table reference if needed (e.g. after HTMX swap)
            if (!this.table || !document.body.contains(this.table)) {
                this.table = this.container?.querySelector('table') as HTMLElement;
                if (this.table) {
                    this.table.setAttribute('tabindex', '0');
                    this.setupKeyboardNavigation();
                    this.setupRowClickHandlers();
                }
            }

            if (!this.table || !document.body.contains(this.table)) {
                if (this.globalKeydownListener) {
                    document.removeEventListener('keydown', this.globalKeydownListener);
                }
                return;
            }

            if (e.target instanceof HTMLInputElement || 
                e.target instanceof HTMLTextAreaElement || 
                e.target instanceof HTMLSelectElement) {
                return;
            }

            if (e.key === 'ArrowDown' && document.activeElement !== this.table) {
                e.preventDefault();
                this.table.focus();
                
                if (this.selectedRowIndex === -1) {
                    this.moveSelection(1);
                }
            }
        };

        document.addEventListener('keydown', this.globalKeydownListener);
    }

    /**
     * Set up click handlers for rows to prevent propagation from buttons
     */
    private setupRowClickHandlers(): void {
        if (!this.table) return;

        // Use event delegation for interactive elements within the table
        this.table.addEventListener('click', (e: Event) => {
            const target = e.target as HTMLElement;
            const interactiveElement = target.closest('button, a, input');
            
            if (interactiveElement) {
                e.stopPropagation();
            }
        });

        this.table.addEventListener('keydown', (e: Event) => {
            const keyEvent = e as KeyboardEvent;
            const target = e.target as HTMLElement;
            const interactiveElement = target.closest('button, a, input');

            if (interactiveElement && keyEvent.key === 'Enter') {
                e.stopPropagation();
            }
        });
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
