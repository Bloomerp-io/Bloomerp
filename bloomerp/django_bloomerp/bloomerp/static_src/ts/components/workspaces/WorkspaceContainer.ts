import htmx from "htmx.org";

import { componentIdentifier, getComponent, initComponents } from "../BaseComponent";
import BaseSectionedLayoutContainer, { type SectionedLayoutRowPayload } from "../layouts/BaseSectionedLayoutContainer";
import WorkspaceTile from "./WorkspaceTile";
import getGeneralModal from "@/utils/modals";
import BaseWizard from "../BaseWizard";
import { Drawer } from "../Drawer";

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
            const seenIds = new Set<string>();

            Array.from(targetGrid.querySelectorAll<HTMLElement>(this.getItemSelector())).forEach((element) => {
                const itemId = this.normalizeLayoutItemId(element.dataset.layoutItemId);
                if (!itemId) {
                    element.remove();
                    return;
                }
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

    protected async renderItem(itemId: string, rowIndex: number, position?: number): Promise<void> {
        if (!this.element) return;

        const row = this.layoutRows[rowIndex];
        const rowItem = row?.items.find((item) => item.id === itemId);
        const rowEl = this.rowElements[rowIndex];
        const targetGrid = rowEl?.querySelector<HTMLElement>("[data-layout-grid]");
        const renderUrl = this.element.dataset.layoutRenderItemUrl;
        if (!row || !targetGrid || !renderUrl) return;

        const existingElement = Array.from(targetGrid.querySelectorAll<HTMLElement>(this.getItemSelector()))
            .find((element) => this.normalizeLayoutItemId(element.dataset.layoutItemId) === itemId);
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
        const renderedElement = renderedElements.find((element) => this.normalizeLayoutItemId(element.dataset.layoutItemId) === itemId)
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

    protected override getSavePayload(): { layout: { rows: SectionedLayoutRowPayload[] }; workspace_id: string | null } {
        return {
            workspace_id: this.normalizeLayoutItemId(this.element?.dataset.workspaceId),
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

    public toggleEditMode(): void {
        super.toggleEditMode()

        const btn = this.element.querySelector('[data-create-tile-btn]')
        btn.classList.toggle('hidden')
        
        // TODO: use relative url
        const url = '/create-tile/?reset_wizard=true'

        btn.addEventListener('click', ()=> {
            const modal = getGeneralModal()
            modal.setSize('full')
            modal.setTitle('Create tile')

            const drawer = getComponent(document.getElementById('layout-drawer-items')) as Drawer

            htmx.ajax(
                'get',
                url,
                {
                    target: modal.getBodyElement(),
                    push: 'false',
                    swap: 'innerHTML'
                }
                
            ).then(()=>{
                modal.open()                
                const component = getComponent(modal.getBodyElement().querySelector('[bloomerp-component="base-wizard"]')) as BaseWizard
                component.setOnDone((wizard)=>{
                    // In the case of an analytics tile
                    if (wizard.getCurrentStepIndex() === 0) {return}
                    
                    // Close modal
                    modal.close()
                    
                    this.loadAvailableItems().then(()=>{drawer.open()})
                })
                
                

            })
            

        })

        
    }
}
