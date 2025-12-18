import BaseComponent from "./BaseComponent";
import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { DataTableCell } from "./DataTableCell";
import { getComponent } from "./BaseComponent";

export class DataTable extends BaseDataViewComponent {
    protected cellClass = DataTableCell;

    private abortController: AbortController | null = null;

    public initialize(): void {
        if (!this.element) return;

        this.abortController = new AbortController();

        // Make table focusable for keyboard navigation
        this.element.setAttribute('tabindex', '0');

        this.setupEventListeners();
    }

    public destroy(): void {
        if (this.abortController) {
            this.abortController.abort();
            this.abortController = null;
        }

        if (this.currentCell) {
            this.currentCell.unhighlight();
        }
    }

    public setupEventListeners(): void {
        if (!this.element || !this.abortController) return;

        // Only ArrowUp/ArrowDown/ArrowLeft/ArrowRight are migrated in this step
        this.element.addEventListener(
            'keydown',
            (event: KeyboardEvent) => this.handleArrowKey(event),
            { signal: this.abortController.signal }
        );
    }
    
    public keydown(): void {
        this.moveCurrentCell(1, 0);
    }

    public keyup(): void {
        this.moveCurrentCell(-1, 0);
    }

    public keyright(): void {
        this.moveCurrentCell(0, 1);
    }

    public keyleft(): void {
        this.moveCurrentCell(0, -1);
    }

    private moveCurrentCell(rowDelta: number, colDelta: number): void {
        if (!this.element) return;

        // If we don't have a current cell yet, initialize to first available cell.
        if (!this.currentCell) {
            const firstCellEl = this.element.querySelector(
                'tbody td[bloomerp-component="datatable-cell"]'
            ) as HTMLElement | null;

            const firstCell = firstCellEl ? (getComponent(firstCellEl) as DataTableCell | null) : null;
            this.focus(firstCell);
            return;
        }

        const currentEl = this.currentCell.element;
        if (!currentEl) return;

        const currentRow = currentEl.closest('tr') as HTMLElement | null;
        const tbody = currentRow?.parentElement as HTMLElement | null;
        if (!currentRow || !tbody) return;

        const rows = Array.from(tbody.querySelectorAll('tr')) as HTMLElement[];
        const rowIndex = rows.indexOf(currentRow);
        if (rowIndex === -1) return;

        const currentRowCells = Array.from(
            currentRow.querySelectorAll('td[bloomerp-component="datatable-cell"]')
        ) as HTMLElement[];
        const colIndex = currentRowCells.indexOf(currentEl);
        if (colIndex === -1) return;

        let nextRowIndex = rowIndex + rowDelta;
        if (nextRowIndex < 0) nextRowIndex = 0;
        if (nextRowIndex >= rows.length) nextRowIndex = rows.length - 1;

        const targetRow = rows[nextRowIndex];
        const targetRowCells = Array.from(
            targetRow.querySelectorAll('td[bloomerp-component="datatable-cell"]')
        ) as HTMLElement[];
        if (targetRowCells.length === 0) return;

        let nextColIndex = colIndex + colDelta;
        if (nextColIndex < 0) nextColIndex = 0;
        if (nextColIndex >= targetRowCells.length) nextColIndex = targetRowCells.length - 1;

        const nextCellEl = targetRowCells[nextColIndex] ?? null;
        const nextCell = nextCellEl ? (getComponent(nextCellEl) as DataTableCell | null) : null;
        if (!nextCell) return;

        this.focus(nextCell);
    }

}