import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";
import { componentIdentifier, getComponent } from "../BaseComponent";
import { ContextMenuItem } from "@/utils/contextMenu";

export class CardViewCard extends BaseDataViewCell {
    public initialize(): void {
        super.initialize();
    }
}

type CardGridPosition = {
    row: number;
    col: number;
};

export class CardView extends BaseDataViewComponent {
    protected cellClass = CardViewCard;
    private gridRows: CardViewCard[][] = [];
    private gridPositions: Map<CardViewCard, CardGridPosition> = new Map();
    private resizeObserver: ResizeObserver | null = null;

    public initialize(): void {
        super.initialize();
        this.refreshGrid();
        this.setupResizeObserver();
    }

    public override destroy(): void {
        super.destroy();
        if (this.resizeObserver) {
            this.resizeObserver.disconnect();
            this.resizeObserver = null;
        }
    }

    public override onAfterSwap(): void {
        this.refreshGrid();
    }

    public moveCellUp(): BaseDataViewCell {
        return this.moveVertical(-1);
    }

    public moveCellDown(): BaseDataViewCell {
        return this.moveVertical(1);
    }

    public moveCellLeft(): BaseDataViewCell {
        return this.moveHorizontal(-1);
    }

    public moveCellRight(): BaseDataViewCell {
        return this.moveHorizontal(1);
    }

    private setupResizeObserver(): void {
        if (!this.element) return;

        const abortController = this.ensureAbortController();

        if (typeof ResizeObserver !== "undefined") {
            this.resizeObserver = new ResizeObserver(() => {
                this.refreshGrid();
            });
            this.resizeObserver.observe(this.element);
        } else {
            window.addEventListener("resize", this.handleResize, { signal: abortController.signal });
        }
    }

    private handleResize = (): void => {
        this.refreshGrid();
    };

    private refreshGrid(): void {
        if (!this.element) return;

        const cardElements = Array.from(
            this.element.querySelectorAll<HTMLElement>(`[${componentIdentifier}="card-view-card"]`)
        );

        if (cardElements.length === 0) {
            this.gridRows = [];
            this.gridPositions.clear();
            return;
        }

        const entries = cardElements
            .map((element) => ({
                element,
                rect: element.getBoundingClientRect(),
            }))
            .sort((a, b) => {
                if (a.rect.top === b.rect.top) {
                    return a.rect.left - b.rect.left;
                }
                return a.rect.top - b.rect.top;
            });

        const rows: CardViewCard[][] = [];
        const rowTops: number[] = [];
        const positions = new Map<CardViewCard, CardGridPosition>();
        const rowTolerance = 4;

        for (const entry of entries) {
            const component = getComponent(entry.element) as CardViewCard | null;
            if (!component) continue;

            let rowIndex = rowTops.findIndex((top) => Math.abs(top - entry.rect.top) <= rowTolerance);
            if (rowIndex === -1) {
                rowIndex = rows.length;
                rowTops.push(entry.rect.top);
                rows.push([]);
            }

            const row = rows[rowIndex];
            const colIndex = row.length;
            row.push(component);

            positions.set(component, { row: rowIndex, col: colIndex });
            entry.element.dataset.rowIndex = String(rowIndex);
            entry.element.dataset.columnIndex = String(colIndex);
        }

        this.gridRows = rows;
        this.gridPositions = positions;
    }

    private moveHorizontal(delta: number): BaseDataViewCell {
        const current = this.currentCell as CardViewCard | null;
        if (!current) return current as BaseDataViewCell;

        this.refreshGrid();

        const position = this.gridPositions.get(current);
        if (!position) return current;

        const row = this.gridRows[position.row];
        if (!row || row.length === 0) return current;

        let nextCol = position.col + delta;
        if (nextCol < 0) nextCol = 0;
        if (nextCol >= row.length) nextCol = row.length - 1;

        return row[nextCol] ?? current;
    }

    private moveVertical(delta: number): BaseDataViewCell {
        const current = this.currentCell as CardViewCard | null;
        if (!current) return current as BaseDataViewCell;

        this.refreshGrid();

        const position = this.gridPositions.get(current);
        if (!position) return current;

        let nextRow = position.row + delta;
        if (nextRow < 0) nextRow = 0;
        if (nextRow >= this.gridRows.length) nextRow = this.gridRows.length - 1;

        const row = this.gridRows[nextRow];
        if (!row || row.length === 0) return current;

        const nextCol = Math.min(position.col, row.length - 1);
        return row[nextCol] ?? current;
    }

    public constructContextMenu(): ContextMenuItem[] {
            let contextMenu: ContextMenuItem[] = [
                {
                    label: 'Navigate',
                    icon: 'fa-solid fa-arrow-right',
                    onClick: async () => {
                        this.currentCell.click()
                    },
                },
            ]
            return contextMenu;
        }
}
