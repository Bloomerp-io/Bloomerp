import htmx from "htmx.org";

import { componentIdentifier, getComponent, initComponents } from "../BaseComponent";
import BaseSectionedLayoutContainer, { type SectionedLayoutRowPayload } from "../layouts/BaseSectionedLayoutContainer";
import WorkspaceTile from "./WorkspaceTile";
import getGeneralModal from "@/utils/modals";
import BaseWizard from "../BaseWizard";
import { Drawer } from "../Drawer";
import FilterContainer from "../filters/FilterContainer";
import type { Filter, FilterScope } from "../filters/definition";
import { RenderedFilters, type AppliedFilterIdentity } from '../filters/RenderedFilters';
import { insertSkeleton } from "@/utils/animations";

export default class WorkspaceContainer extends BaseSectionedLayoutContainer<WorkspaceTile> {
    private renderedFilters?: RenderedFilters;
    private workspaceApplyFiltersHandler: ((event: Event) => void) | null = null;
    private workspaceFilterParams = new URLSearchParams(window.location.search);
    private tileResizeObserver: ResizeObserver | null = null;

    public override initialize(): void {
        if (!this.element) return;
        super.initialize();

        this.workspaceApplyFiltersHandler = (event: Event) => this.applyWorkspaceFilters(event);
        this.element.addEventListener(FilterContainer.applyEvent, this.workspaceApplyFiltersHandler);
        const renderedRoot = this.element.querySelector<HTMLElement>('[data-rendered-filters][data-scope="workspace"]');
        if (renderedRoot) {
            this.renderedFilters = new RenderedFilters(renderedRoot, filters => {
                this.renderedFilters?.syncEditor(this.element!, filters);
                this.updateWorkspaceFilters(filters);
            });
            this.renderedFilters.restore(this.workspaceFilterParams.get('filter'));
        }
        this.setupTileResizeObserver();
        void this.reloadWorkspaceTiles();
        this.items.forEach((item) => {
            if (item.element) {
                this.observeTileResize(item.element);
                this.scheduleTileResize(item.element);
            }
        });
    }

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
            this.observeTileResize(existingElement);
            this.reindexItems();
            return;
        }

        await htmx.ajax("get", renderUrl, {
            target: targetGrid,
            swap: "beforeend",
            values: this.buildTileRenderValues({
                tile_id: itemId,
                colspan: rowItem?.colspan ?? 1,
                max_cols: row.columns,
            }),
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
        this.observeTileResize(renderedElement);
        this.reindexItems();
    }

    public override destroy(): void {
        this.renderedFilters?.destroy();
        this.renderedFilters = undefined;
        if (this.workspaceApplyFiltersHandler) {
            this.element?.removeEventListener(FilterContainer.applyEvent, this.workspaceApplyFiltersHandler);
            this.workspaceApplyFiltersHandler = null;
        }

        this.tileResizeObserver?.disconnect();
        this.tileResizeObserver = null;
        super.destroy();
    }

    private applyWorkspaceFilters(event: Event): void {
        const detail = (event as CustomEvent<FilterScope & AppliedFilterIdentity & { filters: Filter[] }>).detail;
        if (detail?.scope !== "workspace" || detail.id !== this.element?.dataset.workspaceId) return;

        event.stopPropagation();
        this.renderedFilters?.setFilters(detail.filters, detail);
        this.updateWorkspaceFilters(detail.filters);
    }

    private updateWorkspaceFilters(filters: Filter[]): void {
        if (filters.length) {
            this.workspaceFilterParams.set("filter", JSON.stringify(filters));
        } else {
            this.workspaceFilterParams.set("filter", "[]");
        }
        this.workspaceFilterParams.delete("page");
        this.syncWorkspaceUrl();
        void this.reloadWorkspaceTiles();
    }

    private async reloadWorkspaceTiles(): Promise<void> {
        if (!this.element) return;

        const renderUrl = this.element.dataset.layoutRenderItemUrl;
        if (!renderUrl) return;

        this.showTileSkeletons();

        for (let rowIndex = 0; rowIndex < this.layoutRows.length; rowIndex += 1) {
            const row = this.layoutRows[rowIndex];
            const rowEl = this.rowElements[rowIndex];
            const targetGrid = rowEl?.querySelector<HTMLElement>("[data-layout-grid]");
            if (!targetGrid) continue;

            for (const item of row.items) {
                const tileElement = Array.from(targetGrid.querySelectorAll<HTMLElement>(this.getItemSelector()))
                    .find((element) => this.normalizeLayoutItemId(element.dataset.layoutItemId) === item.id);

                if (!tileElement) continue;

                // eslint-disable-next-line no-await-in-loop
                await htmx.ajax("get", renderUrl, {
                    target: tileElement,
                    swap: "outerHTML",
                    values: this.buildTileRenderValues({
                        tile_id: item.id,
                        colspan: item.colspan ?? 1,
                        max_cols: row.columns,
                    }),
                });
            }

            initComponents(targetGrid);
        }

        this.reindexItems();
        this.items.forEach((item) => {
            if (item.element) {
                this.observeTileResize(item.element);
                this.scheduleTileResize(item.element);
            }
        });
    }

    private showTileSkeletons(): void {
        this.element?.querySelectorAll<HTMLElement>(this.getItemSelector()).forEach((tileElement) => {
            const tileBody = tileElement.querySelector<HTMLElement>(":scope > [data-layout-item-body]");
            if (tileBody) insertSkeleton(tileBody);
        });
    }

    private buildTileRenderValues(
        baseValues: Record<string, string | number | boolean | string[]>,
    ): Record<string, string | number | boolean | string[]> {
        const values = { ...baseValues };
        this.workspaceFilterParams.forEach((value, key) => {
            const existingValue = values[key];
            if (Array.isArray(existingValue)) {
                existingValue.push(value);
                return;
            }

            if (existingValue !== undefined) {
                values[key] = [String(existingValue), value];
                return;
            }

            values[key] = value;
        });

        values.workspace_id = this.element?.dataset.workspaceId ?? "";
        return values;
    }

    private syncWorkspaceUrl(): void {
        const browserUrl = new URL(window.location.href);
        browserUrl.search = this.workspaceFilterParams.toString();
        window.history.replaceState(window.history.state, "", `${browserUrl.pathname}${browserUrl.search}${browserUrl.hash}`);
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
        const navigationKey = this.getItemNavigationKey(event);
        if (!navigationKey) return;
        if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(navigationKey)) return;
        if (this.items.length === 0) return;

        event.preventDefault();

        const delta = navigationKey === "ArrowLeft" || navigationKey === "ArrowUp" ? -1 : 1;
        this.focusItemByIndex(this.focusedItemIndex + delta);
    }

    private scheduleTileResize(tileElement: HTMLElement): void {
        const resizePlots = (): void => {
            const plotElements = Array.from(tileElement.querySelectorAll<HTMLElement>(".js-plotly-plot"));
            const plotly = (window as typeof window & {
                Plotly?: {
                    relayout?: (
                        element: HTMLElement,
                        layout: { width: number; height: number },
                    ) => Promise<void>;
                };
            }).Plotly;

            plotElements.forEach((plotElement) => {
                if (plotElement.clientWidth === 0 || plotElement.clientHeight === 0) return;
                void plotly?.relayout?.(plotElement, {
                    width: plotElement.clientWidth,
                    height: plotElement.clientHeight,
                });
            });
        };

        const resizeOnNextFrame = (passesRemaining: number): void => {
            requestAnimationFrame(() => {
                resizePlots();
                if (passesRemaining > 1) {
                    resizeOnNextFrame(passesRemaining - 1);
                }
            });
        };

        resizeOnNextFrame(3);
    }

    private setupTileResizeObserver(): void {
        if (typeof ResizeObserver === "undefined") return;

        this.tileResizeObserver = new ResizeObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.target instanceof HTMLElement) {
                    this.scheduleTileResize(entry.target);
                }
            });
        });
    }

    private observeTileResize(tileElement: HTMLElement): void {
        this.tileResizeObserver?.observe(tileElement);
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
