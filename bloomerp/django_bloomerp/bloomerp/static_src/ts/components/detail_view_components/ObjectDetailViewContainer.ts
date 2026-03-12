import htmx from "htmx.org";

import { type ContextMenuItem, getContextMenu } from "../../utils/contextMenu";
import { componentIdentifier, getComponent, initComponents } from "../BaseComponent";
import BaseSectionedLayoutContainer, { type SectionedLayoutRowPayload } from "../layouts/BaseSectionedLayoutContainer";
import { DetailViewCell } from "./DetailViewCell";

type RowInfo = {
    element: HTMLElement;
    columns: number;
    items: DetailViewCell[];
};

export default class ObjectDetailViewContainer extends BaseSectionedLayoutContainer<DetailViewCell> {
    private currentItem: DetailViewCell | null = null;
    private focusInHandler: ((event: FocusEvent) => void) | null = null;

    protected getItemSelector(): string {
        return `[${componentIdentifier}="detail-view-value"]`;
    }

    protected getItemComponent(element: HTMLElement): DetailViewCell | null {
        const component = getComponent(element);
        return component instanceof DetailViewCell ? component : null;
    }

    protected override shouldApplyFocusedItemClass(): boolean {
        return this.editMode;
    }

    protected override onInitialItemFocus(item: DetailViewCell): void {
        this.currentItem = item;
    }

    public override initialize(): void {
        super.initialize();
        this.items.forEach((item) => {
            if (!item.element || item.element.hasAttribute("tabindex")) return;
            item.element.setAttribute("tabindex", "0");
        });

        this.focusInHandler = (event: FocusEvent) => {
            const target = event.target as HTMLElement | null;
            if (!target) return;
            const itemEl = target.closest<HTMLElement>(this.getItemSelector());
            if (!itemEl) return;

            const component = this.getItemComponent(itemEl);
            if (component) {
                this.currentItem = component;
            }
        };
        this.element?.addEventListener("focusin", this.focusInHandler);
    }

    public override destroy(): void {
        if (this.focusInHandler && this.element) {
            this.element.removeEventListener("focusin", this.focusInHandler);
        }
        this.focusInHandler = null;
    }

    public override onAfterSwap(): void {
        this.items.forEach((item) => {
            if (!item.element || item.element.hasAttribute("tabindex")) return;
            item.element.setAttribute("tabindex", "0");
        });
    }

    protected async renderItem(itemId: number, rowIndex: number, position?: number): Promise<void> {
        if (!this.element) return;

        const rowEl = this.rowElements[rowIndex];
        const targetGrid = rowEl?.querySelector<HTMLElement>("[data-layout-grid]");
        const renderUrl = this.element.dataset.layoutRenderItemUrl;
        const contentTypeId = this.element.dataset.contentTypeId;
        const objectId = this.element.dataset.objectId;
        if (!targetGrid || !renderUrl || !contentTypeId || !objectId) return;

        await htmx.ajax("get", renderUrl, {
            target: targetGrid,
            swap: "beforeend",
            values: {
                content_type_id: contentTypeId,
                object_id: objectId,
                field_id: itemId,
            },
        });

        initComponents(targetGrid);
        if (typeof position === "number") {
            const renderedElements = Array.from(targetGrid.querySelectorAll<HTMLElement>(this.getItemSelector()));
            const renderedElement = renderedElements.find((element) => Number.parseInt(element.dataset.layoutItemId ?? "-1", 10) === itemId)
                ?? renderedElements[renderedElements.length - 1];
            const anchor = renderedElements[position] ?? null;
            if (renderedElement && anchor && anchor !== renderedElement) {
                targetGrid.insertBefore(renderedElement, anchor);
            }
        }

        this.reindexItems();
    }

    protected getSavePayload(): { layout: { rows: SectionedLayoutRowPayload[] }; content_type_id: number | null } {
        return {
            content_type_id: Number.parseInt(this.element?.dataset.contentTypeId ?? "", 10) || null,
            layout: {
                rows: this.serializeRows(),
            },
        };
    }

    protected override handleReadModeKeyDown(event: KeyboardEvent): void {
        const key = event.key;
        const isMeta = event.metaKey || event.ctrlKey;
        const isAlt = event.altKey;
        const isShift = event.shiftKey;

        if (isShift && this.isArrowKey(key)) {
            event.preventDefault();

            const allItems = this.getAllItems();
            if (allItems.length === 0) return;

            if (!this.currentItem || !allItems.includes(this.currentItem)) {
                this.currentItem = key === "ArrowLeft" || key === "ArrowUp"
                    ? allItems[allItems.length - 1]
                    : allItems[0];
            }

            const next = isMeta ? this.getEdgeItem(key) : this.findNextItem(key);
            if (!next) return;

            this.focusReadModeItem(next);
            this.currentItem = next;
            return;
        }

        if (isAlt && key === "ArrowDown") {
            event.preventDefault();
            this.openContextMenu();
        }
    }

    protected override onClick(event: MouseEvent): void {
        super.onClick(event);
        const target = event.target as HTMLElement | null;
        const itemEl = target?.closest<HTMLElement>(this.getItemSelector());
        if (!itemEl) return;

        const component = this.getItemComponent(itemEl);
        if (component) {
            this.currentItem = component;
        }
    }

    private getRows(): RowInfo[] {
        return this.rowElements.map((rowEl) => {
            const columns = Number.parseInt(rowEl.dataset.rowColumns ?? "1", 10) || 1;
            const items = Array.from(rowEl.querySelectorAll<HTMLElement>(this.getItemSelector()))
                .map((itemEl) => this.getItemComponent(itemEl))
                .filter((item): item is DetailViewCell => item instanceof DetailViewCell);
            return {
                element: rowEl,
                columns,
                items,
            };
        });
    }

    private getAllItems(): DetailViewCell[] {
        return this.getRows().flatMap((row) => row.items);
    }

    private isArrowKey(key: string): boolean {
        return key === "ArrowUp" || key === "ArrowDown" || key === "ArrowLeft" || key === "ArrowRight";
    }

    private focusReadModeItem(item: DetailViewCell): void {
        item.focusReadModeTarget();
        if (this.currentItem && this.currentItem !== item) {
            this.currentItem.unhighlight();
        }
    }

    private getCurrentPosition(): { row: RowInfo; index: number } | null {
        if (!this.currentItem) return null;

        for (const row of this.getRows()) {
            const index = row.items.indexOf(this.currentItem);
            if (index !== -1) {
                return { row, index };
            }
        }

        return null;
    }

    private findNextItem(key: string): DetailViewCell | null {
        const position = this.getCurrentPosition();
        if (!position) return null;

        const { row, index } = position;
        switch (key) {
            case "ArrowLeft":
                return this.moveLeft(row, index);
            case "ArrowRight":
                return this.moveRight(row, index);
            case "ArrowUp":
                return this.moveUp(row, index);
            case "ArrowDown":
                return this.moveDown(row, index);
            default:
                return null;
        }
    }

    private moveLeft(row: RowInfo, index: number): DetailViewCell | null {
        const column = index % row.columns;
        if (column > 0) {
            return row.items[index - 1] ?? null;
        }
        return null;
    }

    private moveRight(row: RowInfo, index: number): DetailViewCell | null {
        const column = index % row.columns;
        if (column < row.columns - 1 && index + 1 < row.items.length) {
            return row.items[index + 1] ?? null;
        }
        return null;
    }

    private moveUp(row: RowInfo, index: number): DetailViewCell | null {
        const targetIndex = index - row.columns;
        if (targetIndex >= 0) {
            return row.items[targetIndex] ?? null;
        }

        const rows = this.getRows();
        const rowIndex = rows.findIndex((currentRow) => currentRow.element === row.element);
        if (rowIndex > 0) {
            const previousRow = rows[rowIndex - 1];
            return previousRow.items[previousRow.items.length - 1] ?? null;
        }

        return null;
    }

    private moveDown(row: RowInfo, index: number): DetailViewCell | null {
        const targetIndex = index + row.columns;
        if (targetIndex < row.items.length) {
            return row.items[targetIndex] ?? null;
        }

        const rows = this.getRows();
        const rowIndex = rows.findIndex((currentRow) => currentRow.element === row.element);
        if (rowIndex < rows.length - 1) {
            return rows[rowIndex + 1]?.items[0] ?? null;
        }

        return null;
    }

    private getEdgeItem(key: string): DetailViewCell | null {
        const position = this.getCurrentPosition();
        if (!position) return null;

        const { row, index } = position;
        switch (key) {
            case "ArrowLeft":
                return row.items[Math.floor(index / row.columns) * row.columns] ?? null;
            case "ArrowRight": {
                const rowStart = Math.floor(index / row.columns) * row.columns;
                const rowEnd = Math.min(rowStart + row.columns - 1, row.items.length - 1);
                return row.items[rowEnd] ?? null;
            }
            case "ArrowUp":
                return row.items[index % row.columns] ?? row.items[0] ?? null;
            case "ArrowDown": {
                const column = index % row.columns;
                const totalRows = Math.ceil(row.items.length / row.columns);
                const lastRowStart = (totalRows - 1) * row.columns;
                return row.items[lastRowStart + column] ?? row.items[row.items.length - 1] ?? null;
            }
            default:
                return null;
        }
    }

    private openContextMenu(): void {
        if (!this.currentItem?.element) return;

        const items = this.constructContextMenu();
        if (items.length === 0) {
            this.currentItem.constructContextMenu();
            return;
        }

        const rect = this.currentItem.element.getBoundingClientRect();
        const synthetic = new MouseEvent("contextmenu", {
            bubbles: true,
            cancelable: true,
            clientX: Math.round(rect.left + Math.min(24, rect.width / 2)),
            clientY: Math.round(rect.bottom - 4),
        });

        getContextMenu().show(synthetic, this.currentItem.element, items);
    }

    protected constructContextMenu(): ContextMenuItem[] {
        return [];
    }
}
