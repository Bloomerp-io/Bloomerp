import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { getComponent } from "./BaseComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";
import { getContextMenu } from "../../utils/contextMenu";

export class DataTableCell extends BaseDataViewCell {
    public columnIndex: number = -1;
    public rowIndex: number = -1;

    public initialize(): void {
        super.initialize();
        if (!this.element) return;

        // Column/row indices are provided by the template via data attributes
        const colAttr = this.element.getAttribute('data-column-index');
        const col = colAttr ? Number.parseInt(colAttr, 10) : NaN;
        this.columnIndex = Number.isFinite(col) ? col : -1;

        const rowAttr = this.element.getAttribute('data-row-index');
        const rowIndex = rowAttr ? Number.parseInt(rowAttr, 10) : NaN;
        this.rowIndex = Number.isFinite(rowIndex) ? rowIndex : -1;

    }

    /**
     * Happens on rightclick of the cell
     */
    public override rightClick(event: MouseEvent | PointerEvent): void {
        if (!this.element) return;

        const mouseEvent = event as MouseEvent;

        // Prefer the existing per-dataview menu container if present.
        const tableEl = this.element.closest('table[id^="data-table-"]') as HTMLElement | null;
        const contentTypeId = tableEl?.id?.startsWith('data-table-')
            ? tableEl.id.replace('data-table-', '')
            : null;
        const menuId = contentTypeId ? `data-table-${contentTypeId}-context-menu` : 'bloomerp-context-menu';

        const menu = getContextMenu(menuId);
        const value = this.element.getAttribute('data-value') ?? this.element.textContent ?? '';

        menu.show(mouseEvent, this.element, [
            {
                label: 'Copy value',
                disabled: value.length === 0,
                onClick: async () => {
                    try {
                        await navigator.clipboard.writeText(value);
                    } catch {
                        // Best-effort fallback
                        const textarea = document.createElement('textarea');
                        textarea.value = value;
                        textarea.style.position = 'fixed';
                        textarea.style.left = '-9999px';
                        document.body.appendChild(textarea);
                        textarea.select();
                        document.execCommand('copy');
                        document.body.removeChild(textarea);
                    }
                },
            },
        ]);
    }

    /**
     * Happens on clicking a cell
     */
    public click() {
        
    }
}

export class DataTable extends BaseDataViewComponent {
    protected cellClass = DataTableCell;
    
    public initialize(): void {
        if (!this.element) return;

        // Make table focusable for keyboard navigation
        this.element.setAttribute('tabindex', '0');

        this.setupEventListeners();
    }

    public destroy(): void {
        super.destroy();
    }

    public setupEventListeners(): void {
        if (!this.element) return;

        const abortController = this.ensureAbortController();

        // Only ArrowUp/ArrowDown/ArrowLeft/ArrowRight are migrated in this step
        this.element.addEventListener(
            'keydown',
            (event: KeyboardEvent) => this.handleKeyDown(event),
            { signal: abortController.signal }
        );

        // Right-click delegation: ensures context menu behavior works even if cell components
        // are not yet instantiated (e.g. right-click before any getComponent call).
        this.element.addEventListener(
            'contextmenu',
            (event: MouseEvent) => {
                const anyEvent = event as unknown as { _bloomerpCellHandled?: boolean };
                if (anyEvent._bloomerpCellHandled) return;

                const target = event.target as HTMLElement | null;
                const cellEl = target?.closest('td[bloomerp-component="datatable-cell"]') as HTMLElement | null;
                if (!cellEl) return;

                anyEvent._bloomerpCellHandled = true;
                event.preventDefault();

                const cell = getComponent(cellEl) as DataTableCell | null;
                if (!cell) return;
                this.focus(cell);
                cell.rightClick(event);
            },
            { signal: abortController.signal, capture: true }
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

    public override cmndUp(): void {
        this.focus(this.getFirstVerticalCell());
    }

    public override cmndDown(): void {
        this.focus(this.getLastVerticalCell());
    }

    public override cmndLeft(): void {
        this.focus(this.getFirstHorizontalCell());
    }

    public override cmndRight(): void {
        this.focus(this.getLastHorizontalCell());
    }

    private getFirstVerticalCell(): DataTableCell | null {
        return this.getCellAtEdge('first', 'vertical');
    }

    private getLastVerticalCell(): DataTableCell | null {
        return this.getCellAtEdge('last', 'vertical');
    }

    private getFirstHorizontalCell(): DataTableCell | null {
        return this.getCellAtEdge('first', 'horizontal');
    }

    private getLastHorizontalCell(): DataTableCell | null {
        return this.getCellAtEdge('last', 'horizontal');
    }

    private getCellAtEdge(
        which: 'first' | 'last',
        axis: 'vertical' | 'horizontal'
    ): DataTableCell | null {
        if (!this.element) return null;

        const currentEl = this.currentCell?.element;
        if (!currentEl) {
            const firstCellEl = this.element.querySelector(
                'tbody td[bloomerp-component="datatable-cell"]'
            ) as HTMLElement | null;
            return firstCellEl ? (getComponent(firstCellEl) as DataTableCell | null) : null;
        }

        const currentRow = currentEl.closest('tr') as HTMLElement | null;
        const tbody = currentRow?.parentElement as HTMLElement | null;
        if (!currentRow || !tbody) return null;

        const rows = Array.from(tbody.querySelectorAll('tr')) as HTMLElement[];
        const rowIndex = rows.indexOf(currentRow);
        if (rowIndex === -1) return null;

        const currentRowCells = Array.from(
            currentRow.querySelectorAll('td[bloomerp-component="datatable-cell"]')
        ) as HTMLElement[];
        const colIndex = currentRowCells.indexOf(currentEl);
        if (colIndex === -1) return null;

        const targetRowIndex =
            axis === 'vertical'
                ? which === 'first'
                    ? 0
                    : rows.length - 1
                : rowIndex;

        const targetRow = rows[targetRowIndex] ?? null;
        if (!targetRow) return null;

        const targetRowCells = Array.from(
            targetRow.querySelectorAll('td[bloomerp-component="datatable-cell"]')
        ) as HTMLElement[];
        if (targetRowCells.length === 0) return null;

        const targetColIndex =
            axis === 'horizontal'
                ? which === 'first'
                    ? 0
                    : targetRowCells.length - 1
                : Math.min(colIndex, targetRowCells.length - 1);

        const targetEl = targetRowCells[targetColIndex] ?? null;
        return targetEl ? (getComponent(targetEl) as DataTableCell | null) : null;
    }
}