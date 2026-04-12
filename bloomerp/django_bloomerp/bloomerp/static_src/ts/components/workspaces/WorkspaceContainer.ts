import htmx from "htmx.org";

import { componentIdentifier, getComponent, initComponents } from "../BaseComponent";
import BaseSectionedLayoutContainer, { type SectionedLayoutRowPayload } from "../layouts/BaseSectionedLayoutContainer";
import WorkspaceTile from "./WorkspaceTile";

export default class WorkspaceContainer extends BaseSectionedLayoutContainer<WorkspaceTile> {
    protected override shouldApplyFocusedItemClass(): boolean {
        return true;
    }

    protected getItemSelector(): string {
        return `[${componentIdentifier}="workspace-tile"]`;
    }

    protected getItemComponent(element: HTMLElement): WorkspaceTile | null {
        const component = getComponent(element);
        return component instanceof WorkspaceTile ? component : null;
    }

    protected override async loadInitialItems(): Promise<void> {
        for (let rowIndex = 0; rowIndex < this.layoutRows.length; rowIndex += 1) {
            const row = this.layoutRows[rowIndex];
            const rowEl = this.rowElements[rowIndex];
            const targetGrid = rowEl?.querySelector<HTMLElement>("[data-layout-grid]");
            if (!targetGrid) continue;

            const expectedIds = new Set(row.items.map((item) => item.id));
            const seenIds = new Set<number>();

            Array.from(targetGrid.querySelectorAll<HTMLElement>(this.getItemSelector())).forEach((element) => {
                const itemId = Number.parseInt(element.dataset.layoutItemId ?? "-1", 10);
                if (!expectedIds.has(itemId) || seenIds.has(itemId)) {
                    element.remove();
                    return;
                }

                seenIds.add(itemId);
                const component = this.getItemComponent(element);
                component?.setMaxCols(row.columns);
            });

            for (const item of row.items) {
                if (seenIds.has(item.id)) {
                    continue;
                }
                // eslint-disable-next-line no-await-in-loop
                await this.renderItem(item.id, rowIndex);
                seenIds.add(item.id);
            }
        }
    }

    protected async renderItem(itemId: number, rowIndex: number, position?: number): Promise<void> {
        if (!this.element) return;

        const row = this.layoutRows[rowIndex];
        const rowItem = row?.items.find((item) => item.id === itemId);
        const rowEl = this.rowElements[rowIndex];
        const targetGrid = rowEl?.querySelector<HTMLElement>("[data-layout-grid]");
        const renderUrl = this.element.dataset.layoutRenderItemUrl;
        if (!row || !targetGrid || !renderUrl) return;

        const existingElement = Array.from(targetGrid.querySelectorAll<HTMLElement>(this.getItemSelector()))
            .find((element) => Number.parseInt(element.dataset.layoutItemId ?? "-1", 10) === itemId);
        if (existingElement) {
            const existingItem = this.getItemComponent(existingElement);
            existingItem?.setMaxCols(row.columns);

            if (typeof position === "number") {
                const siblings = Array.from(targetGrid.querySelectorAll<HTMLElement>(this.getItemSelector()));
                const anchor = siblings[position] ?? null;
                if (anchor && anchor !== existingElement) {
                    targetGrid.insertBefore(existingElement, anchor);
                }
            }

            this.scheduleTileResize(existingElement);
            this.reindexItems();
            return;
        }

        await htmx.ajax("get", renderUrl, {
            target: targetGrid,
            swap: "beforeend",
            values: {
                tile_id: itemId,
                colspan: rowItem?.colspan ?? 1,
                max_cols: row.columns,
            },
        });

        initComponents(targetGrid);
        const renderedElements = Array.from(targetGrid.querySelectorAll<HTMLElement>(this.getItemSelector()));
        const renderedElement = renderedElements.find((element) => Number.parseInt(element.dataset.layoutItemId ?? "-1", 10) === itemId)
            ?? renderedElements[renderedElements.length - 1];

        if (!renderedElement) return;

        const item = this.getItemComponent(renderedElement);
        item?.setMaxCols(row.columns);

        if (typeof position === "number") {
            const siblings = Array.from(targetGrid.querySelectorAll<HTMLElement>(this.getItemSelector()));
            const anchor = siblings[position] ?? null;
            if (anchor && anchor !== renderedElement) {
                targetGrid.insertBefore(renderedElement, anchor);
            }
        }

        this.scheduleTileResize(renderedElement);
        this.reindexItems();
    }

    protected getSavePayload(): { layout: { rows: SectionedLayoutRowPayload[] }; workspace_id: number | null } {
        return {
            workspace_id: Number.parseInt(this.element?.dataset.workspaceId ?? "", 10) || null,
            layout: {
                rows: this.serializeRows(),
            },
        };
    }

    protected override handleReadModeKeyDown(event: KeyboardEvent): void {
        if (!event.shiftKey || event.altKey || event.ctrlKey) return;
        if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
        if (this.items.length === 0) return;

        event.preventDefault();

        if (event.key === "Home") {
            this.focusItemByIndex(0);
            return;
        }

        if (event.key === "End") {
            this.focusItemByIndex(this.items.length - 1);
            return;
        }

        const delta = event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1;
        this.focusItemByIndex(this.focusedItemIndex + delta);
    }

    private scheduleTileResize(tileElement: HTMLElement): void {
        const resizePlots = (): void => {
            const plotElements = Array.from(tileElement.querySelectorAll<HTMLElement>(".js-plotly-plot"));
            const plotly = (window as typeof window & { Plotly?: { Plots?: { resize: (element: HTMLElement) => void } } }).Plotly;

            plotElements.forEach((plotElement) => {
                plotly?.Plots?.resize?.(plotElement);
            });
            window.dispatchEvent(new Event("resize"));
        };

        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                resizePlots();
            });
        });
    }
}
