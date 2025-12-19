import { BaseDataViewCell } from "./BaseDataViewCell";
import BaseComponent, { componentIdentifier, getComponent } from "../BaseComponent";
import { getContextMenu, type ContextMenuItem } from "../../utils/contextMenu";

export abstract class BaseDataViewComponent extends BaseComponent {
    protected abortController: AbortController | null = null;

    // Selected cell is the current cell
    public currentCell: BaseDataViewCell | null = null;

    // Each dataview must define what its unit cell component is
    protected abstract cellClass: typeof BaseDataViewCell;

    // Excel-like selection state
    private selectionAnchor: BaseDataViewCell | null = null;
    private selectedCells: Set<BaseDataViewCell> = new Set();

    // Used for fallback selection expansion when we can't infer a rectangular range.
    private selectionLastAxis: "x" | "y" | null = null;
    private selectionLastFirst: boolean | null = null;

    // Abstract methods -> need to be initialized
    abstract moveCellUp(): BaseDataViewCell;
    abstract moveCellDown(): BaseDataViewCell;
    abstract moveCellRight(): BaseDataViewCell;
    abstract moveCellLeft(): BaseDataViewCell;

    public initialize(): void {
        if (!this.element) return;

        const abortController = this.ensureAbortController();

        // Ensure the dataview itself can receive keyboard focus.
        if (!this.element.hasAttribute('tabindex')) {
            this.element.setAttribute('tabindex', '0');
        }

        this.eventListeners(abortController);
    }

    /**
     * Opens the context menu for the current cell
     */
    protected openContextMenuForCurrentCell(): void {
        const cell = this.currentCell;
        const el = cell?.element;
        if (!cell || !el) return;

        const rect = el.getBoundingClientRect();
        const clientX = Math.round(rect.left + Math.min(24, rect.width / 2));
        const clientY = Math.round(rect.bottom - 4);

        // Call the existing rightClick implementation so each cell type can
        // populate the correct menu.
        const synthetic = new MouseEvent('contextmenu', {
            bubbles: true,
            cancelable: true,
            clientX,
            clientY,
        });

        const hasCustomMenu =
            this.constructContextMenu !== BaseDataViewComponent.prototype.constructContextMenu;

        // Prefer the dataview-level implementation if provided.
        if (hasCustomMenu) {
            const items = this.constructContextMenu();
            if (items.length > 0) {
                getContextMenu().show(synthetic, el, items);
            }
            return;
        }

        // Back-compat fallback: delegate to cell.
        cell.rightClick(synthetic);
    }

    /**
     * Override in subclasses to provide context menu items for this dataview.
     * The base class handles actually showing the menu.
     */
    public constructContextMenu(): ContextMenuItem[] {
        return [];
    }


    /**
     * Initializes focus onto the data view component.
     */
    protected initFocus(): void {
        if (!this.element) return;

        // Find the first child component element within this dataview
        const candidates = this.element.querySelectorAll<HTMLElement>(`[${componentIdentifier}]`);

        for (const el of Array.from(candidates)) {
            const component = getComponent(el);

            if (component && component instanceof this.cellClass) {
                this.focus(component);
                this.collapseSelectionToActive();
                return;
            }
        }
    }

    /**
     * Focus a cell: unhighlight previous, set new, highlight.
     */
    protected focus(cell: BaseDataViewCell | null): void {
        if (this.currentCell) {
            this.currentCell.unhighlight();
        }

        this.currentCell = cell;

        if (this.currentCell) {
            this.currentCell.highlight();

            const el = this.currentCell.element;
            if (el) {
                el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
            }
        }
    }

    protected clearSelection(): void {
        for (const cell of this.selectedCells) {
            cell.unselect();
        }

        this.selectedCells.clear();
    }

    protected setSelection(cells: Iterable<BaseDataViewCell>): void {
        const next = new Set<BaseDataViewCell>();
        for (const cell of cells) next.add(cell);

        for (const cell of this.selectedCells) {
            if (!next.has(cell)) cell.unselect();
        }

        for (const cell of next) {
            if (!this.selectedCells.has(cell)) cell.select();
        }

        this.selectedCells = next;
    }

    protected collapseSelectionToActive(): void {
        if (!this.currentCell) return;
        this.selectionAnchor = this.currentCell;
        this.setSelection([this.currentCell]);
    }

    protected extendSelectionToActive(): void {
        if (!this.currentCell || !this.selectionAnchor) return;

        // Prefer Excel-like rectangular selection if cells provide row/col coordinates.
        const anchorCoords = this.getCellCoords(this.selectionAnchor);
        const activeCoords = this.getCellCoords(this.currentCell);

        if (anchorCoords && activeCoords) {
            const minRow = Math.min(anchorCoords.row, activeCoords.row);
            const maxRow = Math.max(anchorCoords.row, activeCoords.row);
            const minCol = Math.min(anchorCoords.col, activeCoords.col);
            const maxCol = Math.max(anchorCoords.col, activeCoords.col);

            const inRange: BaseDataViewCell[] = [];
            for (const cell of this.getAllCells()) {
                const coords = this.getCellCoords(cell);
                if (!coords) continue;
                if (
                    coords.row >= minRow && coords.row <= maxRow &&
                    coords.col >= minCol && coords.col <= maxCol
                ) {
                    inRange.push(cell);
                }
            }

            // If we found at least something meaningful, apply it.
            if (inRange.length > 0) {
                this.setSelection(inRange);
                return;
            }
        }

        // Fallback: select a linear run from anchor toward active along the last movement axis.
        if (this.selectionLastAxis && this.selectionLastFirst !== null) {
            const cells: BaseDataViewCell[] = [];
            let cell: BaseDataViewCell = this.selectionAnchor;

            const visited = new Set<BaseDataViewCell>();
            visited.add(cell);
            cells.push(cell);

            const maxSteps = 5000;
            let steps = 0;

            while (cell !== this.currentCell && steps++ < maxSteps) {
                const next = this.moveFromCell(cell, this.selectionLastAxis, this.selectionLastFirst);
                if (!next || next === cell || visited.has(next)) break;
                cell = next;
                visited.add(cell);
                cells.push(cell);
            }

            if (cells[cells.length - 1] !== this.currentCell) {
                cells.push(this.currentCell);
            }

            this.setSelection(cells);
            return;
        }

        // Minimal fallback: just anchor + active.
        this.setSelection([this.selectionAnchor, this.currentCell]);
    }

    private getAllCells(): BaseDataViewCell[] {
        if (!this.element) return [];

        const cells: BaseDataViewCell[] = [];
        const candidates = this.element.querySelectorAll<HTMLElement>(`[${componentIdentifier}]`);

        for (const el of Array.from(candidates)) {
            const component = getComponent(el);
            if (component && component instanceof this.cellClass) {
                cells.push(component);
            }
        }

        return cells;
    }

    private getCellCoords(cell: BaseDataViewCell): { row: number; col: number } | null {
        const el = cell.element;
        if (!el) return null;

        // Bloomerp datatables expose indices via these attributes.
        const rowRaw = el.dataset.rowIndex ?? el.getAttribute("data-row-index");
        const colRaw = el.dataset.columnIndex ?? el.getAttribute("data-column-index");

        if (rowRaw == null || colRaw == null) return null;

        const row = Number(rowRaw);
        const col = Number(colRaw);

        if (!Number.isFinite(row) || !Number.isFinite(col)) return null;
        return { row, col };
    }

    protected ensureAbortController(): AbortController {
        if (!this.abortController) {
            this.abortController = new AbortController();
        }

        return this.abortController;
    }

    public override destroy(): void {
        if (this.abortController) {
            this.abortController.abort();
            this.abortController = null;
        }

        if (this.currentCell) {
            this.currentCell.unhighlight();
        }

        this.clearSelection();
        this.selectionAnchor = null;
    }
    
    eventListeners(abortController: AbortController) {
        // Right-click: delegate to the dataview to build & show a menu.
        this.element.addEventListener(
            'contextmenu',
            (event: MouseEvent) => {
                const anyEvent = event as unknown as { _bloomerpCellHandled?: boolean };
                if (anyEvent._bloomerpCellHandled) return;
                anyEvent._bloomerpCellHandled = true;

                const target = event.target as HTMLElement | null;
                const cellEl = target?.closest(`[${componentIdentifier}]`) as HTMLElement | null;
                if (!cellEl) return;

                const cell = getComponent(cellEl);
                if (!(cell instanceof this.cellClass)) return;

                event.preventDefault();

                this.focus(cell);
                this.collapseSelectionToActive();

                const hasCustomMenu =
                    this.constructContextMenu !== BaseDataViewComponent.prototype.constructContextMenu;

                if (hasCustomMenu) {
                    const items = this.constructContextMenu();
                    if (items.length > 0) {
                        getContextMenu().show(event, cellEl, items);
                    }
                    return;
                }

                // Back-compat fallback: allow cell-level context menu if present.
                (cell as BaseDataViewCell).rightClick(event);
            },
            { signal: abortController.signal, capture: true },
        );

        this.element.addEventListener(
            'keydown',
            (event: KeyboardEvent) => {
                // Normal key press
                if (!event.metaKey && !event.shiftKey && !event.altKey) {
                    switch (event.key) {
                        // Arrow keys
                        case 'ArrowDown':
                            event.preventDefault();

                            if (!this.currentCell) {
                                this.initFocus();
                                return
                            }

                            this.focus(this.moveCellDown());
                            this.collapseSelectionToActive();
                            return;

                        case 'ArrowUp':
                            event.preventDefault();
                            if (!this.currentCell) {
                                this.initFocus();
                                return;
                            }
                            this.focus(this.moveCellUp());
                            this.collapseSelectionToActive();
                            return;

                        case 'ArrowLeft':
                            event.preventDefault();
                            if (!this.currentCell) {
                                this.initFocus();
                                return;
                            }
                            this.focus(this.moveCellLeft());
                            this.collapseSelectionToActive();
                            return;

                        case 'ArrowRight':
                            event.preventDefault();
                            if (!this.currentCell) {
                                this.initFocus();
                                return;
                            }
                            this.focus(this.moveCellRight());
                            this.collapseSelectionToActive();
                            return;

                        case 'Enter':
                            event.preventDefault();
                            this.currentCell.click();
                            return
                    }
                }

                // Following is for meta keys

                // Shift + arrow key
                if (event.shiftKey) {
                    switch (event.key) {
                        case 'ArrowDown': {
                            event.preventDefault();
                            if (!this.currentCell) { this.initFocus(); return; }

                            if (!this.selectionAnchor) this.selectionAnchor = this.currentCell;
                            this.selectionLastAxis = "y";
                            this.selectionLastFirst = false;

                            const next = event.metaKey
                                ? (this.getEdgeCell("y", false) ?? this.currentCell)
                                : this.moveCellDown();

                            this.focus(next);
                            this.extendSelectionToActive();
                            return;
                        }
                        case 'ArrowUp': {
                            event.preventDefault();
                            if (!this.currentCell) { this.initFocus(); return; }

                            if (!this.selectionAnchor) this.selectionAnchor = this.currentCell;
                            this.selectionLastAxis = "y";
                            this.selectionLastFirst = true;

                            const next = event.metaKey
                                ? (this.getEdgeCell("y", true) ?? this.currentCell)
                                : this.moveCellUp();

                            this.focus(next);
                            this.extendSelectionToActive();
                            return;
                        }
                        case 'ArrowLeft': {
                            event.preventDefault();
                            if (!this.currentCell) { this.initFocus(); return; }

                            if (!this.selectionAnchor) this.selectionAnchor = this.currentCell;
                            this.selectionLastAxis = "x";
                            this.selectionLastFirst = true;

                            const next = event.metaKey
                                ? (this.getEdgeCell("x", true) ?? this.currentCell)
                                : this.moveCellLeft();

                            this.focus(next);
                            this.extendSelectionToActive();
                            return;
                        }
                        case 'ArrowRight': {
                            event.preventDefault();
                            if (!this.currentCell) { this.initFocus(); return; }

                            if (!this.selectionAnchor) this.selectionAnchor = this.currentCell;
                            this.selectionLastAxis = "x";
                            this.selectionLastFirst = false;

                            const next = event.metaKey
                                ? (this.getEdgeCell("x", false) ?? this.currentCell)
                                : this.moveCellRight();

                            this.focus(next);
                            this.extendSelectionToActive();
                            return;
                        }
                    }
                }

                // Cmnd + arrow key
                if (event.metaKey) {
                    switch (event.key) {
                        case 'ArrowDown':
                            event.preventDefault();
                            if (!this.currentCell) { this.initFocus(); return; }
                            this.focus(this.getEdgeCell("y", false));
                            this.collapseSelectionToActive();
                            return;

                        case 'ArrowUp':
                            event.preventDefault();
                            if (!this.currentCell) { this.initFocus(); return; }
                            this.focus(this.getEdgeCell("y", true));
                            this.collapseSelectionToActive();
                            return;

                        case 'ArrowLeft':
                            event.preventDefault();
                            if (!this.currentCell) { this.initFocus(); return; }
                            this.focus(this.getEdgeCell("x", true));
                            this.collapseSelectionToActive();
                            return;

                        case 'ArrowRight':
                            event.preventDefault();
                            if (!this.currentCell) { this.initFocus(); return; }
                            this.focus(this.getEdgeCell("x", false));
                            this.collapseSelectionToActive();
                            return;
                    }
                }

                // Alt/option + arrow key
                if (event.altKey) {
                    switch (event.key) {
                        case 'ArrowDown':
                            event.preventDefault();
                            this.openContextMenuForCurrentCell()
                            return
                    }

                }

            },
            { signal: abortController.signal },
        )
    }

    /**
     * Computes the next cell from an arbitrary starting cell along an axis.
     *
     * Note: subclass `moveCell*()` implementations typically rely on `this.currentCell`,
     * so this temporarily swaps `currentCell` to `from` while computing the move, then
     * restores it (no highlight/selection side-effects).
     *
     * @param from - Cell to treat as the current position for this movement step.
     * @param axis - 'x' for left/right, 'y' for up/down.
     * @param first - When true, moves toward the first cell on that axis (left/up); otherwise toward last (right/down).
     * @returns The next cell according to the subclass movement rules.
     */
    private moveFromCell(
        from: BaseDataViewCell,
        axis: "x" | "y",
        first: boolean,
    ): BaseDataViewCell {
        // Subclass moveCell* methods likely depend on this.currentCell, so swap it temporarily.
        const prev = this.currentCell;
        this.currentCell = from;
        try {
            if (axis === "x") return first ? this.moveCellLeft() : this.moveCellRight();
            return first ? this.moveCellUp() : this.moveCellDown();
        } finally {
            this.currentCell = prev;
        }
    }

    /**
     * Walks along an axis from the active cell until the first/last reachable cell is found.
     *
     * This repeatedly applies `moveFromCell` until movement no longer changes the cell or
     * a cycle is detected, returning the furthest reachable cell in that direction.
     *
     * @param axis - 'x' for left/right, 'y' for up/down.
     * @param first - When true, finds the first cell on that axis (left/up); otherwise finds the last (right/down).
     * @returns The edge cell, or null if there is no current cell.
     */
    private getEdgeCell(axis: "x" | "y", first: boolean): BaseDataViewCell | null {
        const start = this.currentCell;
        if (!start) return null;

        let cell: BaseDataViewCell = start;
        const visited = new Set<BaseDataViewCell>([cell]);

        while (true) {
            const next = this.moveFromCell(cell, axis, first);

            // Stop if we can't move further, or movement cycles.
            if (!next || next === cell || visited.has(next)) break;

            cell = next;
            visited.add(cell);
        }

        return cell;
    }

    /**
     * ------------------------------
     * PUBLIC UTILITY FUNCTIONS
     * ------------------------------
     */

    /**
     * Checks whether there are multiple cells selected
     * @returns boolean
     */
    public hasMultipleSelection(): boolean {
        return this.selectedCells.size > 1;
    }

}