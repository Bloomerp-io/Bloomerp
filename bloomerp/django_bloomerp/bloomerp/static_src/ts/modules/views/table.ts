/**
 * Table View Module
 * 
 * Handles all table-specific functionality including:
 * - Row and cell navigation
 * - Cell selection and highlighting
 * - Context menu on cells
 */

import { BaseView, ViewConfig, NAVIGATION_KEYS } from './base';

/**
 * TableView handles table-specific interactions
 */
export class TableView extends BaseView {
    readonly viewType = 'table';
    
    private table: HTMLElement | null = null;
    private selectedRowIndex: number = -1;
    private selectedCellIndex: number = -1;
    private cellNavigationMode: boolean = false;
    
    constructor(config: ViewConfig) {
        super(config);
    }
    
    /**
     * Initialize the table view
     */
    initialize(): void {
        this.table = document.getElementById(`data-table-${this.contentTypeId}`);
        
        if (!this.table) {
            // Try finding table inside container if ID construction fails
            this.table = this.container.querySelector('table') as HTMLElement;
        }
        
        if (!this.table) {
            console.warn('TableView: Table element not found');
            return;
        }
        
        // Make table focusable for keyboard navigation
        this.table.setAttribute('tabindex', '0');
    }
    
    /**
     * Cleanup the table view
     */
    cleanup(): void {
        this.selectedRowIndex = -1;
        this.selectedCellIndex = -1;
        this.cellNavigationMode = false;
        this.navigationMode = false;
        
        // Remove cell highlights
        if (this.table) {
            this.table.querySelectorAll('td.cell-selected').forEach(cell => {
                cell.classList.remove('cell-selected');
            });
            this.table.querySelectorAll('tbody tr.bg-gray-100').forEach(row => {
                row.classList.remove('bg-gray-100');
            });
        }
    }
    
    /**
     * Get the navigable element (the table)
     */
    getNavigableElement(): HTMLElement | null {
        return this.table;
    }
    
    /**
     * Refresh element references
     */
    refreshElements(): void {
        this.table = this.container.querySelector('table') as HTMLElement;
        if (this.table) {
            this.table.setAttribute('tabindex', '0');
        }
    }
    
    /**
     * Handle navigation key press
     */
    handleNavigation(key: string, hasModifier: boolean): void {
        // Handle context menu with modifier key + MOVE_DOWN
        if (key === NAVIGATION_KEYS.MOVE_DOWN && hasModifier) {
            this.openContextMenuOnSelected();
            return;
        }
        
        switch (key) {
            case NAVIGATION_KEYS.MOVE_DOWN:
                this.moveRowSelection(1);
                break;
            case NAVIGATION_KEYS.MOVE_UP:
                this.moveRowSelection(-1);
                break;
            case NAVIGATION_KEYS.SELECT:
                this.handleSelect();
                break;
            case NAVIGATION_KEYS.MOVE_RIGHT:
                this.handleArrowRight();
                break;
            case NAVIGATION_KEYS.MOVE_LEFT:
                this.handleArrowLeft();
                break;
            case NAVIGATION_KEYS.EXIT_NAVIGATION:
                this.exitNavigationMode();
                break;
        }
    }
    
    /**
     * Handle Enter/Select key
     */
    handleSelect(): void {
        if (this.selectedRowIndex === -1 || !this.table) return;
        
        const rows = this.table.querySelectorAll('tbody tr');
        if (this.selectedRowIndex < rows.length) {
            const row = rows[this.selectedRowIndex] as HTMLElement;
            row.click();
        }
    }
    
    /**
     * Enter navigation mode
     */
    enterNavigationMode(): void {
        this.navigationMode = true;
        
        if (this.selectedRowIndex === -1) {
            this.moveRowSelection(1);
        }
    }
    
    /**
     * Exit navigation mode
     */
    exitNavigationMode(): void {
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
     * Open context menu on the currently selected element
     */
    openContextMenuOnSelected(): void {
        // If in cell navigation mode, open on selected cell
        // Otherwise, open on the first cell of the selected row
        if (this.cellNavigationMode) {
            this.openContextMenuOnSelectedCell();
        } else if (this.selectedRowIndex >= 0) {
            // Enter cell navigation mode and open on first cell
            this.selectedCellIndex = 0;
            this.cellNavigationMode = true;
            this.highlightSelectedCell();
            this.openContextMenuOnSelectedCell();
        }
    }
    
    /**
     * Move row selection by direction
     */
    private moveRowSelection(direction: number): void {
        const rows = this.table?.querySelectorAll('tbody tr');
        if (!rows || rows.length === 0) return;
        
        // Remove previous selection
        if (this.selectedRowIndex >= 0 && this.selectedRowIndex < rows.length) {
            rows[this.selectedRowIndex].classList.remove('bg-gray-100');
        }
        
        this.selectedRowIndex += direction;
        
        // Clamp to valid range
        if (this.selectedRowIndex < 0) {
            this.selectedRowIndex = 0;
        } else if (this.selectedRowIndex >= rows.length) {
            this.selectedRowIndex = rows.length - 1;
        }
        
        // Highlight new row
        const newRow = rows[this.selectedRowIndex] as HTMLElement;
        newRow.classList.add('bg-gray-100');
        newRow.scrollIntoView({ block: 'nearest' });
        
        // If in cell navigation mode, update cell highlight for new row
        if (this.cellNavigationMode) {
            this.highlightSelectedCell();
        }
    }
    
    /**
     * Handle right arrow - enter cell navigation or move right
     */
    private handleArrowRight(): void {
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
        
        this.highlightSelectedCell();
    }
    
    /**
     * Handle left arrow - enter cell navigation or move left
     */
    private handleArrowLeft(): void {
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
        
        this.highlightSelectedCell();
    }
    
    /**
     * Highlight the currently selected cell
     */
    private highlightSelectedCell(): void {
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
     * Open context menu on the currently selected cell
     */
    private openContextMenuOnSelectedCell(): void {
        if (!this.table || this.selectedRowIndex === -1 || this.selectedCellIndex === -1) return;
        
        const rows = this.table.querySelectorAll('tbody tr');
        if (this.selectedRowIndex >= rows.length) return;
        
        const currentRow = rows[this.selectedRowIndex];
        const cells = currentRow.querySelectorAll('td');
        
        if (this.selectedCellIndex >= cells.length) return;
        
        const cell = cells[this.selectedCellIndex] as HTMLElement;
        this.onContextMenuRequest(cell, true);
    }
    
    /**
     * Get the currently selected row index
     */
    getSelectedRowIndex(): number {
        return this.selectedRowIndex;
    }
    
    /**
     * Get the currently selected cell index
     */
    getSelectedCellIndex(): number {
        return this.selectedCellIndex;
    }
    
    /**
     * Check if in cell navigation mode
     */
    isInCellNavigationMode(): boolean {
        return this.cellNavigationMode;
    }
}
