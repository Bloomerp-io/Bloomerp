import getGeneralModal from "@/utils/modals";
import BaseComponent, { componentIdentifier, getComponent, initComponents } from "../BaseComponent";
import WorkspaceTile from "./WorkspaceTile";
import htmx from "htmx.org";


const TILE_ENDPOINT = "/components/render_workspace_tile/";

export default class WorkspaceContainer extends BaseComponent {
    private cols: number = 4;
    private tiles: Array<WorkspaceTile> = [];
    private tileSection: HTMLElement | null = null;
    private tileIds: Array<number> = [];
    private editWorkspaceBtn: HTMLElement | null = null;
    private editMode: boolean = false;
    private focusedTileIndex: number = 0;
    private draggedTile: HTMLElement | null = null;
    private rows: Array<{ divider: boolean; cols: number; height?: string }> = [];
    private rowElements: HTMLElement[] = [];
    private focusedRowIndex: number = 0;
    private isRowFocused: boolean = false;
    private draggedRow: HTMLElement | null = null;
    private addTileBtn: HTMLElement | null = null;

    public initialize(): void {
        if (!this.element) return;

        this.tileSection = this.element.querySelector("#workspace-tiles-section");
        this.editWorkspaceBtn = this.element.querySelector("#edit-workspaces-btn");

        const colsString = this.element.getAttribute("data-cols") || "4";
        this.setCols(Number.parseInt(colsString, 10) || 4);

        this.rows = this.parseRowsConfig();

        const tileIdsString = this.element.getAttribute("data-tile-ids") || "";
        this.tileIds = tileIdsString
            .split(",")
            .map((id) => id.trim())
            .filter((id) => id.length > 0)
            .map((id) => Number.parseInt(id, 10))
            .filter((id) => !Number.isNaN(id));

        this.tileSection?.setAttribute('tabindex', '0');
        this.tileSection?.classList.add('outline-none');

        this.renderRows();
        this.renderTilesInOrder(this.tileIds);

        this.editWorkspaceBtn?.addEventListener("click", () => this.toggleEditMode());
        this.tileSection?.addEventListener('click', (event: MouseEvent) => this.onTileClick(event));
        this.tileSection?.addEventListener('keydown', (event: KeyboardEvent) => this.onKeyDown(event));
        this.tileSection?.addEventListener('workspace:tile-colspan-change', () => this.onTileColspanChange());

        this.setupDnDForSection();

        // Add listener to add tile button
        this.addTileBtn = this.element.querySelector("#add-tile-btn");
        this.addTileBtn?.addEventListener("click", () => {
            const modal = getGeneralModal();
            modal.setTitle("Add Tile");
            
            htmx.ajax("get",
                "/create-tile/",
                {
                    target: modal.getBodyElement(),
                    swap: "innerHTML",
                }
            ).then(()=> {
                modal.open();
            })
        
        });


    }

    public setCols(cols: number): void {
        this.cols = Math.max(1, Math.round(cols));

        this.tiles.forEach((tile) => tile.setMaxCols(this.cols));
    }

    private removeTile(tile: WorkspaceTile): void {
        if (!tile.element || !this.tileSection) return;

        const tileId = tile.getTileId();
        tile.element.classList.add('scale-95', 'opacity-0');

        window.setTimeout(() => {
            tile.element?.remove();
            this.tiles = this.tiles.filter((current) => current !== tile);
            this.tileIds = this.tileIds.filter((id) => id !== tileId);
            this.reindexTiles();
            this.save();
        }, 180);
    }

    private addTile(tileId: number, position?: number, rowIndex?: number): Promise<void> {
        if (!this.tileSection) return Promise.resolve();

        const targetRow = typeof rowIndex === 'number' ? this.rowElements[rowIndex] : null;
        const tileTarget = targetRow?.querySelector<HTMLElement>('[data-row-grid]') ?? this.tileSection;

        return (htmx.ajax("get", TILE_ENDPOINT, {
            target: tileTarget,
            swap: "beforeend",
            values: { tile_id: tileId },
        }) as unknown as Promise<void>).then(() => {
            if (!this.tileSection) return;

            initComponents(this.tileSection);

            const tileElements = Array.from(
                tileTarget.querySelectorAll<HTMLElement>(`[${componentIdentifier}="workspace-tile"]`),
            );
            const matchingTileElement = tileElements.find((el) => Number.parseInt(el.dataset.tileId ?? '-1', 10) === tileId)
                ?? tileElements[tileElements.length - 1];

            if (!matchingTileElement) return;

            const tile = getComponent(matchingTileElement) as WorkspaceTile | null;
            if (!tile) return;

            const rowCols = this.getRowColsForElement(targetRow);
            tile.setMaxCols(rowCols);
            tile.setEditMode(this.editMode);

            if (!this.tiles.includes(tile)) {
                if (typeof position === 'number' && position >= 0 && position < this.tiles.length) {
                    this.tiles.splice(position, 0, tile);
                    const anchorTile = this.tiles[position + 1];
                    if (anchorTile?.element) {
                        this.tileSection.insertBefore(matchingTileElement, anchorTile.element);
                    }
                } else {
                    this.tiles.push(tile);
                }
            }

            if (!this.tileIds.includes(tileId)) {
                this.tileIds.push(tileId);
            }

            this.bindTile(tile);
            this.reindexTiles();
            this.save();
            this.triggerLayoutResize();
        });
    }

    private renderTilesInOrder(tileIds: number[]): void {
        if (tileIds.length === 0) return;
        void this.addTilesSequentially(tileIds);
    }

    private async addTilesSequentially(tileIds: number[]): Promise<void> {
        let rowIndex = 0;
        const rowUsage = this.rows.map(() => 0);

        for (const tileId of tileIds) {
            const targetRowIndex = Math.min(rowIndex, Math.max(0, this.rows.length - 1));
            await this.addTile(tileId, undefined, targetRowIndex);

            const row = this.rows[targetRowIndex];
            const lastTile = this.tiles[this.tiles.length - 1];
            const colspan = lastTile?.getColspan?.() ?? 1;
            const cols = row?.cols ?? this.cols;
            const nextUsage = rowUsage[targetRowIndex] + colspan;

            if (nextUsage > cols && targetRowIndex < this.rows.length - 1 && rowUsage[targetRowIndex] > 0) {
                rowIndex = targetRowIndex + 1;
                rowUsage[rowIndex] = 0;
                if (lastTile?.element) {
                    const nextRowGrid = this.rowElements[rowIndex]?.querySelector<HTMLElement>('[data-row-grid]');
                    nextRowGrid?.appendChild(lastTile.element);
                    lastTile.setMaxCols(this.rows[rowIndex]?.cols ?? this.cols);
                    this.reindexTiles();
                }
                rowUsage[rowIndex] += lastTile?.getColspan?.() ?? 1;
            } else {
                rowUsage[targetRowIndex] = Math.min(cols, nextUsage);
            }
        }
    }

    private toggleEditMode(): void {
        if (!this.element || !this.tileSection) return;

        this.editMode = !this.editMode;

        this.element.classList.toggle('workspace-edit-mode', this.editMode);
        this.tileSection.classList.toggle('workspace-edit-grid', this.editMode);

        this.tiles.forEach((tile) => tile.setEditMode(this.editMode));
        this.updateRowControlVisibility();

        if (this.editMode) {
            this.focusTileByIndex(this.focusedTileIndex);
        }
    }

    private save(): void {
        this.tileIds = this.tiles.map((tile) => tile.getTileId());
        this.element?.setAttribute('data-tile-ids', this.tileIds.join(','));
        this.element?.setAttribute('data-rows', JSON.stringify(this.rows));
    }

    private onTileColspanChange(): void {
        this.save();
        this.triggerLayoutResize();
    }

    private triggerLayoutResize(): void {
        // Plotly listens to window resize events; emit after DOM/layout settles.
        window.requestAnimationFrame(() => {
            window.requestAnimationFrame(() => {
                window.dispatchEvent(new Event('resize'));
            });
        });
    }

    private bindTile(tile: WorkspaceTile): void {
        if (!tile.element) return;

        const removeButton = tile.element.querySelector<HTMLElement>('[data-remove-tile]');
        if (removeButton && !removeButton.dataset.bound) {
            removeButton.dataset.bound = 'true';
            removeButton.addEventListener('click', () => this.removeTile(tile));
        }

        tile.element.dataset.tileIndex = String(this.tiles.indexOf(tile));
        tile.element.classList.add('transition-all', 'duration-200', 'ease-out');

        if (!tile.element.dataset.dragBound) {
            tile.element.dataset.dragBound = 'true';
            tile.element.addEventListener('dragstart', (event: DragEvent) => this.onDragStart(event));
            tile.element.addEventListener('dragend', () => this.onDragEnd());
        }
    }

    private reindexTiles(): void {
        this.tiles = this.collectTiles();
        this.tiles.forEach((tile, index) => {
            if (!tile.element) return;
            tile.element.dataset.tileIndex = String(index);
        });

        this.focusedTileIndex = Math.min(Math.max(0, this.focusedTileIndex), Math.max(0, this.tiles.length - 1));
    }

    private collectTiles(): WorkspaceTile[] {
        if (!this.tileSection) return [];

        const elements = Array.from(
            this.tileSection.querySelectorAll<HTMLElement>(`[${componentIdentifier}="workspace-tile"]`),
        );

        const result: WorkspaceTile[] = [];
        for (const el of elements) {
            const component = getComponent(el);
            if (component instanceof WorkspaceTile) {
                const row = el.closest<HTMLElement>('[data-workspace-row]');
                component.setMaxCols(this.getRowColsForElement(row));
                result.push(component);
            }
        }

        return result;
    }

    private setupDnDForSection(): void {
        if (!this.tileSection) return;

        this.tileSection.addEventListener('dragover', (event: DragEvent) => {
            if (!this.editMode || !this.tileSection) return;
            event.preventDefault();

            if (this.draggedRow) {
                const afterRow = this.getRowAfterElement(event.clientY);
                if (!afterRow) {
                    this.tileSection.appendChild(this.draggedRow);
                } else {
                    this.tileSection.insertBefore(this.draggedRow, afterRow);
                }
                return;
            }

            if (!this.draggedTile) return;
            const rowTarget = this.getRowForPoint(event.clientY);
            const rowGrid = rowTarget?.querySelector<HTMLElement>('[data-row-grid]');
            if (!rowGrid) return;
            const afterElement = this.getTileAfterElement(rowGrid, event.clientX, event.clientY);
            if (!afterElement) {
                rowGrid.appendChild(this.draggedTile);
            } else {
                rowGrid.insertBefore(this.draggedTile, afterElement);
            }
        });

        this.tileSection.addEventListener('drop', (event: DragEvent) => {
            if (!this.editMode) return;
            event.preventDefault();
            if (this.draggedRow) {
                const draggedRow = this.draggedRow;
                this.draggedRow.classList.remove('workspace-row--dragging');
                this.draggedRow = null;
                this.reindexRows();
                const newIndex = this.rowElements.indexOf(draggedRow);
                if (newIndex >= 0) {
                    this.focusRowByIndex(newIndex);
                }
                this.save();
                return;
            }
            this.draggedTile?.classList.remove('workspace-tile--dragging');
            this.reindexTiles();
            this.updateDraggedTileMaxCols();
            this.save();
            this.triggerLayoutResize();
        });
    }

    private onDragStart(event: DragEvent): void {
        if (!this.editMode) {
            event.preventDefault();
            return;
        }

        const target = event.currentTarget as HTMLElement | null;
        if (!target) return;

        const tileTarget = target.closest<HTMLElement>(`[${componentIdentifier}="workspace-tile"]`);
        if (tileTarget) {
            this.draggedTile = tileTarget;
            tileTarget.classList.add('workspace-tile--dragging');
            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', tileTarget.dataset.tileId ?? '');
            }
            return;
        }

        const rowHandle = target.closest<HTMLElement>('[data-row-drag-handle]');
        const rowTarget = rowHandle?.closest<HTMLElement>('[data-workspace-row]')
            ?? target.closest<HTMLElement>('[data-workspace-row]');

        if (rowTarget) {
            if (!this.editMode || !this.isRowFocused) {
                event.preventDefault();
                return;
            }
            this.draggedRow = rowTarget;
            rowTarget.classList.add('workspace-row--dragging');
            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', rowTarget.dataset.rowIndex ?? '');
                try {
                    const offsetX = Math.min(40, Math.max(10, Math.round(rowTarget.clientWidth * 0.1)));
                    const offsetY = Math.min(40, Math.max(10, Math.round(rowTarget.clientHeight * 0.1)));
                    event.dataTransfer.setDragImage(rowTarget, offsetX, offsetY);
                } catch {
                    // Ignore drag image errors (e.g. browser restrictions)
                }
            }
            return;
        }

    }

    private onDragEnd(): void {
        const draggedTile = this.draggedTile;
        this.draggedTile?.classList.remove('workspace-tile--dragging');
        this.draggedTile = null;
        if (this.draggedRow) {
            this.draggedRow.classList.remove('workspace-row--dragging');
            this.draggedRow = null;
        }
        this.reindexTiles();
        this.updateDraggedTileMaxCols(draggedTile);
        this.save();
    }

    private getTileAfterElement(container: HTMLElement, x: number, y: number): HTMLElement | null {
        const tiles = Array.from(
            container.querySelectorAll<HTMLElement>(`[${componentIdentifier}="workspace-tile"]:not(.workspace-tile--dragging)`),
        );

        if (tiles.length === 0) return null;

        let closest: { offset: number; element: HTMLElement | null } = { offset: Number.POSITIVE_INFINITY, element: null };

        for (const tile of tiles) {
            const box = tile.getBoundingClientRect();
            const centerX = box.left + box.width / 2;
            const centerY = box.top + box.height / 2;
            const offset = Math.hypot(centerX - x, centerY - y);

            if (offset < closest.offset) {
                closest = { offset, element: tile };
            }
        }

        return closest.element;
    }

    private getRowAfterElement(y: number): HTMLElement | null {
        if (!this.tileSection) return null;
        const rows = Array.from(
            this.tileSection.querySelectorAll<HTMLElement>('[data-workspace-row]:not(.workspace-row--dragging)'),
        );
        if (rows.length === 0) return null;

        let closest: { offset: number; element: HTMLElement | null } = { offset: Number.NEGATIVE_INFINITY, element: null };

        for (const row of rows) {
            const box = row.getBoundingClientRect();
            const offset = y - (box.top + box.height / 2);
            if (offset < 0 && offset > closest.offset) {
                closest = { offset, element: row };
            }
        }

        return closest.element;
    }

    private getRowForPoint(y: number): HTMLElement | null {
        if (this.rowElements.length === 0) return null;
        let closest: { offset: number; element: HTMLElement | null } = { offset: Number.POSITIVE_INFINITY, element: null };
        for (const row of this.rowElements) {
            const box = row.getBoundingClientRect();
            const centerY = box.top + box.height / 2;
            const offset = Math.abs(centerY - y);
            if (offset < closest.offset) {
                closest = { offset, element: row };
            }
        }
        return closest.element;
    }

    private onTileClick(event: MouseEvent): void {
        const target = event.target as HTMLElement | null;
        const rowElement = target?.closest<HTMLElement>('[data-workspace-row]');

        if (this.editMode && rowElement && !target?.closest(`[${componentIdentifier}="workspace-tile"]`)) {
            const rowIndex = Number.parseInt(rowElement.dataset.rowIndex ?? '0', 10);
            this.focusRowByIndex(rowIndex);
            return;
        }

        const tileElement = target?.closest(`[${componentIdentifier}="workspace-tile"]`) as HTMLElement | null;
        if (!tileElement) return;

        const index = Number.parseInt(tileElement.dataset.tileIndex ?? '0', 10);
        this.focusTileByIndex(index);
    }

    private onKeyDown(event: KeyboardEvent): void {
        if (!this.editMode || this.tiles.length === 0) return;

        const withAltShiftResize = event.altKey && event.shiftKey && (event.key === 'ArrowLeft' || event.key === 'ArrowRight');
        if (withAltShiftResize) {
            event.preventDefault();
            if (this.isRowFocused) {
                const delta = event.key === 'ArrowRight' ? 1 : -1;
                const nextCols = this.clampRowCols((this.rows[this.focusedRowIndex]?.cols ?? this.cols) + delta);
                this.updateRowCols(this.focusedRowIndex, nextCols);
                return;
            }
            const focused = this.tiles[this.focusedTileIndex];
            if (!focused) return;
            const delta = event.key === 'ArrowRight' ? 1 : -1;
            focused.setColspan(focused.getColspan() + delta);
            this.save();
            return;
        }

        const withAltMove = event.altKey && !event.metaKey && !event.shiftKey && [
            'ArrowLeft',
            'ArrowRight',
            'ArrowUp',
            'ArrowDown',
        ].includes(event.key);

        if (withAltMove) {
            event.preventDefault();
            if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
                if (this.isRowFocused) {
                    const delta = event.key === 'ArrowDown' ? 1 : -1;
                    this.moveRow(this.focusedRowIndex, this.focusedRowIndex + delta);
                    return;
                }
                const delta = event.key === 'ArrowDown' ? 1 : -1;
                this.moveTileBetweenRows(this.focusedTileIndex, delta);
                return;
            }
            if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
                if (this.isRowFocused) return;
                const delta = event.key === 'ArrowRight' ? 1 : -1;
                this.moveTileWithinRow(this.focusedTileIndex, delta);
                return;
            }
            return;
        }

        if (event.altKey || event.metaKey || event.shiftKey) return;

        if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
            event.preventDefault();
            if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
                if (!this.isRowFocused) {
                    const rowIndex = this.getRowIndexForTile(this.tiles[this.focusedTileIndex]);
                    this.focusRowByIndex(rowIndex);
                    return;
                }
                const direction = event.key === 'ArrowDown' ? 1 : -1;
                const nextRowIndex = Math.max(0, Math.min(this.rows.length - 1, this.focusedRowIndex + direction));
                this.focusRowByIndex(nextRowIndex);
                return;
            }
            this.focusTileByIndex(this.getAdjacentIndex(this.focusedTileIndex, event.key));
        }
    }

    private focusTileByIndex(index: number): void {
        const boundedIndex = Math.max(0, Math.min(index, this.tiles.length - 1));

        this.tiles.forEach((tile, idx) => {
            tile.element?.classList.toggle('workspace-tile--focused', idx === boundedIndex);
            if (tile.element) {
                tile.element.tabIndex = idx === boundedIndex ? 0 : -1;
            }
        });

        this.focusedTileIndex = boundedIndex;
        const focusedTile = this.tiles[boundedIndex];
        focusedTile?.element?.focus();

        if (focusedTile?.element) {
            const rowIndex = this.getRowIndexForTile(focusedTile);
            this.focusedRowIndex = rowIndex;
        }
        this.isRowFocused = false;
        this.updateRowControlVisibility();
    }

    private getAdjacentIndex(currentIndex: number, key: string): number {
        if (this.tiles.length === 0) return 0;

        switch (key) {
            case 'ArrowLeft':
                return Math.max(0, currentIndex - 1);
            case 'ArrowRight':
                return Math.min(this.tiles.length - 1, currentIndex + 1);
            case 'ArrowUp':
                return Math.max(0, currentIndex - this.cols);
            case 'ArrowDown':
                return Math.min(this.tiles.length - 1, currentIndex + this.cols);
            default:
                return currentIndex;
        }
    }

    private moveTile(fromIndex: number, toIndex: number): void {
        if (!this.tileSection) return;
        if (fromIndex === toIndex) return;

        const boundedFrom = Math.max(0, Math.min(fromIndex, this.tiles.length - 1));
        const boundedTo = Math.max(0, Math.min(toIndex, this.tiles.length - 1));

        const movingTile = this.tiles[boundedFrom];
        if (!movingTile?.element) return;

        const newTiles = [...this.tiles];
        const [moved] = newTiles.splice(boundedFrom, 1);
        newTiles.splice(boundedTo, 0, moved);
        this.tiles = newTiles;

        const anchor = this.tiles[boundedTo + 1]?.element ?? null;
        anchor?.parentElement?.insertBefore(movingTile.element, anchor);

        this.reindexTiles();
        this.focusTileByIndex(boundedTo);
        this.save();
    }

    private moveTileWithinRow(tileIndex: number, delta: number): void {
        const tile = this.tiles[tileIndex];
        if (!tile?.element) return;
        const rowEl = tile.element.closest<HTMLElement>('[data-workspace-row]');
        if (!rowEl) return;
        const rowTiles = Array.from(
            rowEl.querySelectorAll<HTMLElement>(`[${componentIdentifier}="workspace-tile"]`),
        );
        const currentIndex = rowTiles.indexOf(tile.element);
        if (currentIndex === -1) return;
        const nextIndex = currentIndex + delta;
        if (nextIndex < 0 || nextIndex >= rowTiles.length) return;
        const anchor = rowTiles[delta > 0 ? nextIndex + 1 : nextIndex] ?? null;
        const grid = rowEl.querySelector<HTMLElement>('[data-row-grid]');
        if (!grid) return;
        if (anchor) {
            grid.insertBefore(tile.element, anchor);
        } else {
            grid.appendChild(tile.element);
        }
        this.reindexTiles();
        this.focusTileByIndex(this.tiles.indexOf(tile));
        this.save();
    }

    private moveTileBetweenRows(tileIndex: number, deltaRows: number): void {
        const tile = this.tiles[tileIndex];
        if (!tile?.element) return;
        const rowEl = tile.element.closest<HTMLElement>('[data-workspace-row]');
        if (!rowEl) return;
        const fromRowIndex = Number.parseInt(rowEl.dataset.rowIndex ?? '0', 10);
        const toRowIndex = Math.max(0, Math.min(this.rows.length - 1, fromRowIndex + deltaRows));
        if (toRowIndex === fromRowIndex) return;

        const targetRowEl = this.rowElements[toRowIndex];
        const targetGrid = targetRowEl?.querySelector<HTMLElement>('[data-row-grid]');
        if (!targetGrid) return;

        const currentRowTiles = Array.from(
            rowEl.querySelectorAll<HTMLElement>(`[${componentIdentifier}="workspace-tile"]`),
        );
        const insertIndex = currentRowTiles.indexOf(tile.element);
        const targetRowTiles = Array.from(
            targetGrid.querySelectorAll<HTMLElement>(`[${componentIdentifier}="workspace-tile"]`),
        );
        const anchor = targetRowTiles[insertIndex] ?? null;
        if (anchor) {
            targetGrid.insertBefore(tile.element, anchor);
        } else {
            targetGrid.appendChild(tile.element);
        }
        tile.setMaxCols(this.rows[toRowIndex]?.cols ?? this.cols);
        this.reindexTiles();
        this.focusTileByIndex(this.tiles.indexOf(tile));
        this.save();
        this.triggerLayoutResize();
    }

    private updateDraggedTileMaxCols(tileEl?: HTMLElement | null): void {
        const target = tileEl ?? this.draggedTile;
        if (!target) return;
        const rowEl = target.closest<HTMLElement>('[data-workspace-row]');
        const rowIndex = Number.parseInt(rowEl?.dataset.rowIndex ?? '-1', 10);
        if (!Number.isFinite(rowIndex) || !this.rows[rowIndex]) return;
        const comp = getComponent(target);
        if (comp instanceof WorkspaceTile) {
            comp.setMaxCols(this.rows[rowIndex].cols);
        }
    }

    private parseRowsConfig(): Array<{ divider: boolean; cols: number; height?: string }> {
        const raw = this.element?.getAttribute('data-rows');
        if (!raw) {
            return [{ divider: false, cols: this.cols }];
        }

        try {
            const parsed = JSON.parse(raw);
            if (!Array.isArray(parsed)) {
                return [{ divider: false, cols: this.cols }];
            }
            return parsed.map((row) => ({
                divider: Boolean(row?.divider),
                cols: this.clampRowCols(Number.parseInt(String(row?.cols ?? this.cols), 10)),
                height: typeof row?.height === 'string' ? row.height : undefined,
            }));
        } catch {
            return [{ divider: false, cols: this.cols }];
        }
    }

    private renderRows(): void {
        if (!this.tileSection) return;
        this.tileSection.innerHTML = '';
        this.rowElements = [];

        this.rows.forEach((row, index) => {
            const rowEl = document.createElement('div');
            rowEl.dataset.workspaceRow = 'true';
            rowEl.dataset.rowIndex = String(index);
            if (row.height) {
                rowEl.dataset.rowHeight = row.height;
            }
            rowEl.className = 'workspace-row';
            rowEl.tabIndex = -1;

            rowEl.innerHTML = `
                <div class="workspace-row__header" data-row-header>
                    <div class="workspace-row__controls" data-row-controls>
                        <input
                            data-row-cols-input
                            type="number"
                            min="1"
                            max="12"
                            value="${row.cols}"
                            class="workspace-row__input"
                            title="Row columns"
                        />
                        </button>
                        <button
                            data-remove-row
                            type="button"
                            class="workspace-row__remove"
                            title="Remove row"
                        >
                            <i class="fa fa-xmark"></i>
                        </button>
                    </div>
                </div>
                <div class="workspace-row__grid" data-row-grid></div>
            `;

            const grid = rowEl.querySelector<HTMLElement>('[data-row-grid]');
            if (grid) {
                grid.style.gridTemplateColumns = `repeat(${row.cols}, minmax(0, 1fr))`;
            }

            const dragHandle = rowEl.querySelector<HTMLElement>('[data-row-drag-handle]');
            dragHandle?.addEventListener('dragstart', (event: DragEvent) => this.onDragStart(event));
            dragHandle?.addEventListener('dragend', () => this.onDragEnd());
            const header = rowEl.querySelector<HTMLElement>('[data-row-header]');
            if (header) {
                header.setAttribute('draggable', 'true');
            }
            header?.addEventListener('dragstart', (event: DragEvent) => this.onDragStart(event));
            header?.addEventListener('dragend', () => this.onDragEnd());

            const colsInput = rowEl.querySelector<HTMLInputElement>('[data-row-cols-input]');
            colsInput?.addEventListener('change', () => {
                const next = this.clampRowCols(Number.parseInt(colsInput.value, 10));
                colsInput.value = String(next);
                this.updateRowCols(index, next);
            });

            const removeButton = rowEl.querySelector<HTMLElement>('[data-remove-row]');
            removeButton?.addEventListener('click', () => this.removeRow(index));

            this.tileSection?.appendChild(rowEl);
            this.rowElements.push(rowEl);
        });

        this.updateRowControlVisibility();
    }

    private updateRowControlVisibility(): void {
        this.element?.classList.toggle('workspace-row-selection', this.isRowFocused);
        this.rowElements.forEach((rowEl, index) => {
            const isFocused = this.isRowFocused && index === this.focusedRowIndex;
            rowEl.classList.toggle('workspace-row--focused', isFocused);
            rowEl.tabIndex = isFocused ? 0 : -1;
            const handle = rowEl.querySelector<HTMLElement>('[data-row-drag-handle]');
            if (handle) {
                handle.setAttribute('draggable', this.editMode ? 'true' : 'false');
            }
        });
    }

    private focusRowByIndex(index: number): void {
        const boundedIndex = Math.max(0, Math.min(index, this.rowElements.length - 1));
        this.focusedRowIndex = boundedIndex;
        this.isRowFocused = true;
        this.tiles.forEach((tile) => {
            tile.element?.classList.remove('workspace-tile--focused');
            if (tile.element) {
                tile.element.tabIndex = -1;
            }
        });
        this.updateRowControlVisibility();
        this.rowElements[boundedIndex]?.focus?.();
    }

    private focusFirstTileInRow(rowIndex: number): void {
        const rowEl = this.rowElements[rowIndex];
        if (!rowEl) return;
        const tileEl = rowEl.querySelector<HTMLElement>(`[${componentIdentifier}="workspace-tile"]`);
        if (!tileEl) return;
        const index = Number.parseInt(tileEl.dataset.tileIndex ?? '0', 10);
        this.focusTileByIndex(index);
    }

    private getRowIndexForTile(tile?: WorkspaceTile): number {
        const element = tile?.element;
        if (!element) return this.focusedRowIndex;
        const rowEl = element.closest<HTMLElement>('[data-workspace-row]');
        const index = Number.parseInt(rowEl?.dataset.rowIndex ?? `${this.focusedRowIndex}`, 10);
        return Number.isFinite(index) ? index : this.focusedRowIndex;
    }

    private getRowColsForElement(rowEl: HTMLElement | null): number {
        const index = Number.parseInt(rowEl?.dataset.rowIndex ?? '', 10);
        if (Number.isFinite(index) && this.rows[index]) {
            return this.rows[index].cols;
        }
        return this.cols;
    }

    private updateRowCols(rowIndex: number, cols: number): void {
        const row = this.rows[rowIndex];
        if (!row) return;
        row.cols = cols;
        const rowEl = this.rowElements[rowIndex];
        const grid = rowEl?.querySelector<HTMLElement>('[data-row-grid]');
        if (grid) {
            grid.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
        }
        const input = rowEl?.querySelector<HTMLInputElement>('[data-row-cols-input]');
        if (input) {
            input.value = String(cols);
        }
        const tiles = Array.from(rowEl?.querySelectorAll<HTMLElement>(`[${componentIdentifier}="workspace-tile"]`) ?? []);
        tiles.forEach((el) => {
            const comp = getComponent(el);
            if (comp instanceof WorkspaceTile) {
                comp.setMaxCols(cols);
            }
        });
        this.save();
        this.triggerLayoutResize();
    }

    private removeRow(rowIndex: number): void {
        if (this.rows.length <= 1) return;
        const rowEl = this.rowElements[rowIndex];
        const nextRow = this.rowElements[rowIndex + 1] ?? this.rowElements[rowIndex - 1];
        const nextGrid = nextRow?.querySelector<HTMLElement>('[data-row-grid]');
        if (rowEl && nextGrid) {
            const tiles = Array.from(rowEl.querySelectorAll<HTMLElement>(`[${componentIdentifier}="workspace-tile"]`));
            tiles.forEach((tile) => nextGrid.appendChild(tile));
        }
        rowEl?.remove();
        this.rows.splice(rowIndex, 1);
        this.rowElements.splice(rowIndex, 1);
        this.reindexRows();
        this.save();
    }

    private reindexRows(): void {
        this.rowElements = Array.from(
            this.tileSection?.querySelectorAll<HTMLElement>('[data-workspace-row]') ?? [],
        );
        this.rowElements.forEach((row, index) => {
            row.dataset.rowIndex = String(index);
        });
        this.rows = this.rowElements.map((rowEl) => {
            const input = rowEl.querySelector<HTMLInputElement>('[data-row-cols-input]');
            const cols = this.clampRowCols(Number.parseInt(input?.value ?? `${this.cols}`, 10));
            const height = rowEl.dataset.rowHeight || undefined;
            return { divider: false, cols, height };
        });
        this.focusedRowIndex = Math.min(Math.max(0, this.focusedRowIndex), Math.max(0, this.rows.length - 1));
        this.updateRowControlVisibility();
    }

    private moveRow(fromIndex: number, toIndex: number): void {
        if (!this.tileSection) return;
        if (fromIndex === toIndex) return;
        const boundedFrom = Math.max(0, Math.min(fromIndex, this.rows.length - 1));
        const boundedTo = Math.max(0, Math.min(toIndex, this.rows.length - 1));
        const movingRow = this.rowElements[boundedFrom];
        if (!movingRow) return;
        if (boundedTo > boundedFrom) {
            const anchor = this.rowElements[boundedTo + 1] ?? null;
            this.tileSection.insertBefore(movingRow, anchor);
        } else {
            const anchor = this.rowElements[boundedTo] ?? null;
            this.tileSection.insertBefore(movingRow, anchor);
        }
        this.reindexRows();
        this.focusRowByIndex(boundedTo);
        this.save();
    }

    private clampRowCols(value: number): number {
        if (!Number.isFinite(value)) return Math.min(12, Math.max(1, this.cols));
        return Math.min(12, Math.max(1, Math.round(value)));
    }
}
