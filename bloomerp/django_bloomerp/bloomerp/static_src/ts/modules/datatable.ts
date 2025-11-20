/**
 * DataTable Module with HTMX Integration
 * 
 * Provides functionality for:
 * - Dynamic table reloading via HTMX
 * - Context menu on table cells
 * - Cell value copying
 * - Dynamic filtering
 * 
 * This module demonstrates TypeScript usage with HTMX event listeners
 * and works with dynamically loaded content.
 */

import type { DataTableConfig, DataTableCell, ContextMenuPosition } from '../types/bloomerp';


/**
 * DataTable class handles all datatable interactions
 */
export class DataTable {
    private tableId: string;
    private table: HTMLElement | null = null;
    private contextMenu: HTMLElement | null = null;
    private currentCell: DataTableCell | null = null;
    private contentTypeId: string | null = null;
    private selectedRowIndex: number = -1;
    private globalKeydownListener: ((e: KeyboardEvent) => void) | null = null;

    constructor(config: DataTableConfig) {
        this.tableId = config.tableId;
        this.initialize();
    }

    /**
     * Initialize the datatable
     */
    private initialize(): void {
        this.table = document.getElementById(this.tableId);
        this.contextMenu = document.getElementById(`${this.tableId}-context-menu`);

        if (!this.table) {
            console.warn(`DataTable: Table with ID "${this.tableId}" not found`);
            return;
        }

        // Make table focusable for keyboard navigation
        this.table.setAttribute('tabindex', '0');

        this.setupContextMenu();
        this.setupKeyboardNavigation();
        this.setupGlobalKeyboardListener();
        this.setupRowClickHandlers();
    }

    /**
     * Get the datatable URL from hidden input
     */
    private getDataTableUrl(): string {
        const urlInput = document.getElementById(`${this.tableId}-datatable-url`) as HTMLInputElement;
        return urlInput?.value || '';
    }

    /**
     * Reload the datatable with optional query parameters
     */
    public reload(requestParams?: string): void {
        const url = this.getDataTableUrl();
        if (!url) {
            console.error('DataTable: No URL found for table reload');
            return;
        }

        const fullUrl = requestParams ? `${url}?${requestParams}` : url;
        window.htmx.ajax('GET', fullUrl, `#${this.tableId}`);
    }

    /**
     * Set up context menu on table cells
     */
    private setupContextMenu(): void {
        if (!this.table || !this.contextMenu) return;

        const cells = this.table.querySelectorAll<DataTableCell>('td[allow-context-menu]');

        cells.forEach(cell => {
            cell.addEventListener('contextmenu', (e: MouseEvent) => {
                e.preventDefault();
                this.showContextMenu(cell, e);
            });
        });

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
    private showContextMenu(cell: DataTableCell, event: MouseEvent): void {
        if (!this.contextMenu) return;

        this.currentCell = cell;

        // Position menu at mouse coordinates (fixed positioning)
        const position = this.calculateContextMenuPosition(event);

        // Position and display the menu
        this.contextMenu.style.left = `${position.x}px`;
        this.contextMenu.style.top = `${position.y}px`;
        this.contextMenu.classList.remove('hidden');

        // Show/hide filter option based on cell attributes
        this.toggleFilterOption(cell);
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
        const scrollX = window.pageXOffset;
        const scrollY = window.pageYOffset;

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
     * Toggle filter option visibility based on cell attributes
     */
    private toggleFilterOption(cell: DataTableCell): void {
        const filterListItem = document.getElementById(`${this.tableId}-context-menu-filter-value-list-item`);

        if (filterListItem) {
            filterListItem.style.display = cell.dataset.contextMenuFilterValue ? 'block' : 'none';
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
        // Copy value action
        const copyButton = document.getElementById(`${this.tableId}-context-menu-copy-value`);
        if (copyButton) {
            copyButton.addEventListener('click', (e: Event) => {
                e.preventDefault();
                this.copyCurrentCellValue();
            });
        }

        // Filter value action
        const filterButton = document.getElementById(`${this.tableId}-context-menu-filter-value`);
        if (filterButton) {
            filterButton.addEventListener('click', (e: Event) => {
                e.preventDefault();
                this.filterByCurrentCell();
            });
        }

        // Edit cell action
        const editButton = document.getElementById(`${this.tableId}-context-menu-edit-value`);
        if (editButton) {
            editButton.addEventListener('click', (e: Event) => {
                e.preventDefault();
                this.editCurrentCell();
            });
        }

        // Delete row action
        const deleteButton = document.getElementById(`${this.tableId}-context-menu-delete-row`);
        if (deleteButton) {
            deleteButton.addEventListener('click', (e: Event) => {
                e.preventDefault();
                this.deleteCurrentRow();
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
     * Copy current cell value to clipboard
     */
    private async copyCurrentCellValue(): Promise<void> {
        if (!this.currentCell) return;

        try {
            const text = this.currentCell.textContent || '';
            await navigator.clipboard.writeText(text);
            this.hideContextMenu();
            this.showMessage('Value copied to clipboard', 'info');
        } catch (err) {
            console.error('Failed to copy text:', err);
            this.showMessage('Failed to copy value', 'error');
        }
    }

    /**
     * Filter datatable by current cell value
     */
    private filterByCurrentCell(): void {
        if (!this.currentCell) return;

        const filterValue = this.currentCell.dataset.contextMenuFilterValue;
        if (!filterValue) return;

        // Prevent duplicate filters
        if (this.currentCell.classList.contains('filtered')) {
            this.hideContextMenu();
            return;
        }

        this.filter(filterValue);
        this.currentCell.classList.add('filtered');
        this.hideContextMenu();
    }

    /**
     * Apply filter to datatable
     */
    public filter(filterParams: string): void {
        const url = this.getDataTableUrl();
        if (!url) return;

        window.htmx.ajax('GET', `${url}&${filterParams}`, `#${this.tableId}`);
        this.showMessage('Datatable filtered', 'info');
    }

    /**
     * Edit current cell
     */
    private editCurrentCell(): void {
        if (!this.currentCell) return;

        const objectId = this.currentCell.dataset.objectId;
        const column = this.currentCell.dataset.column;
        const value = this.currentCell.dataset.value;
        const element = this.currentCell

        this.showMessage('Edit functionality coming soon', 'info');
        this.hideContextMenu();
    }

    /**
     * Delete current row
     */
    private deleteCurrentRow(): void {
        if (!this.currentCell) return;

        const objectId = this.currentCell.dataset.objectId;

        if (!objectId) return;

        const confirmed = confirm('Are you sure you want to delete this row?');
        if (!confirmed) {
            this.hideContextMenu();
            return;
        }

        console.log('Delete row:', objectId);
        this.showMessage('Delete functionality coming soon', 'warning');
        this.hideContextMenu();

        // TODO: Implement delete via HTMX
        // Example:
        // window.htmx.ajax('DELETE', `/api/delete/${objectId}`, {
        //   target: `#${this.tableId}`,
        //   swap: 'outerHTML'
        // });
    }

    /**
     * Show a message to the user
     * This calls a global function that should be available
     */
    private showMessage(message: string, type: 'success' | 'info' | 'warning' | 'error'): void {
        // Call global showMessage function if it exists
        if (typeof (window as any).showMessage === 'function') {
            (window as any).showMessage(message, type);
        } else {
            console.log(`[${type.toUpperCase()}] ${message}`);
        }
    }

    /**
     * Reinitialize the datatable (useful after HTMX swaps)
     */
    public reinitialize(): void {
        this.initialize();
    }

    /**
     * Set up keyboard navigation for the table
     */
    private setupKeyboardNavigation(): void {
        if (!this.table) return;

        this.table.addEventListener('keydown', (e: KeyboardEvent) => {
            // Only handle navigation if the table itself is focused or we are navigating within it
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

        // Remove highlight from current row
        if (this.selectedRowIndex >= 0 && this.selectedRowIndex < rows.length) {
            rows[this.selectedRowIndex].classList.remove('bg-gray-100');
        }

        // Update index
        this.selectedRowIndex += direction;

        // Clamp index
        if (this.selectedRowIndex < 0) {
            this.selectedRowIndex = 0;
        } else if (this.selectedRowIndex >= rows.length) {
            this.selectedRowIndex = rows.length - 1;
        }

        // Add highlight to new row
        const newRow = rows[this.selectedRowIndex] as HTMLElement;
        newRow.classList.add('bg-gray-100');
        
        // Ensure row is visible
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
        // Remove existing listener if any
        if (this.globalKeydownListener) {
            document.removeEventListener('keydown', this.globalKeydownListener);
        }

        this.globalKeydownListener = (e: KeyboardEvent) => {
            // Check if table is still in DOM
            if (!this.table || !document.body.contains(this.table)) {
                // Clean up self
                if (this.globalKeydownListener) {
                    document.removeEventListener('keydown', this.globalKeydownListener);
                }
                return;
            }

            // Ignore if user is typing in an input
            if (e.target instanceof HTMLInputElement || 
                e.target instanceof HTMLTextAreaElement || 
                e.target instanceof HTMLSelectElement) {
                return;
            }

            // If ArrowDown is pressed and table is not focused, focus it and select first row
            if (e.key === 'ArrowDown' && document.activeElement !== this.table) {
                e.preventDefault();
                this.table.focus();
                
                // If no row selected, select the first one
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

        // Find all buttons and links inside the table body
        const interactiveElements = this.table.querySelectorAll('tbody button, tbody a, tbody input');
        
        interactiveElements.forEach(el => {
            el.addEventListener('click', (e: Event) => {
                e.stopPropagation();
            });
            
            // Also prevent Enter key on these elements from triggering row click if they handle it
            el.addEventListener('keydown', (e: Event) => {
                const keyEvent = e as KeyboardEvent;
                if (keyEvent.key === 'Enter') {
                    e.stopPropagation();
                }
            });
        });
    }
}

/**
 * Initialize a datatable
 */
export function initDataTable(config: DataTableConfig): DataTable {
    return new DataTable(config);
}

/**
 * Find and initialize all datatables on the page
 */
export function initAllDataTables(): Map<string, DataTable> {
    const dataTables = new Map<string, DataTable>();
    const tables = document.querySelectorAll('[data-datatable]');

    tables.forEach(table => {
        if (table.id) {
            const dataTable = new DataTable({ tableId: table.id });
            dataTables.set(table.id, dataTable);
        }
    });

    return dataTables;
}

// Export legacy function names for backward compatibility
export function reloadDataTable(dataTableId: string): void {
    const dataTable = new DataTable({ tableId: dataTableId });
    dataTable.reload();
}

export function filterDataTable(filter: string, datatableId: string): void {
    const dataTable = new DataTable({ tableId: datatableId });
    dataTable.filter(filter);
}
