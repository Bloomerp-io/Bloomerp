import htmx from "htmx.org";

import { componentIdentifier, getComponent, initComponents } from "../BaseComponent";
import BaseSectionedLayoutContainer, { type SectionedLayoutRowPayload } from "../layouts/BaseSectionedLayoutContainer";
import WorkspaceTile from "./WorkspaceTile";
import getGeneralModal from "@/utils/modals";
import BaseWizard from "../BaseWizard";
import { Drawer } from "../Drawer";
import FilterContainer, { FilterEntriesContainer, getFiltersFromUrl } from "../Filters";

export default class WorkspaceContainer extends BaseSectionedLayoutContainer<WorkspaceTile> {
    private workspaceApplyFiltersHandler: ((event: Event) => void) | null = null;
    private workspaceFilterParams = new URLSearchParams(window.location.search);

    public override initialize(): void {
        super.initialize();

        this.workspaceApplyFiltersHandler = (event: Event) => this.applyWorkspaceFilters(event);
        this.element
            ?.querySelector<HTMLElement>("[data-workspace-apply-filters]")
            ?.addEventListener("click", this.workspaceApplyFiltersHandler);

        this.renderWorkspaceFilters();
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
        this.reindexItems();
    }

    public override destroy(): void {
        if (this.workspaceApplyFiltersHandler) {
            this.element
                ?.querySelector<HTMLElement>("[data-workspace-apply-filters]")
                ?.removeEventListener("click", this.workspaceApplyFiltersHandler);
        }

        super.destroy();
    }

    private applyWorkspaceFilters(_event: Event): void {
        const filters = this.getWorkspaceFilterContainer()?.getFilters() || [];
        const nextParams = new URLSearchParams(this.workspaceFilterParams);
        
        filters.forEach((filter) => {
            if (!filter.value || !filter.operator) return;

            const key = `${filter.field}__${filter.operator}`;
            nextParams.delete(key);

            if (Array.isArray(filter.value)) {
                filter.value.forEach((value) => {
                    if (value !== "") {
                        nextParams.append(key, value);
                    }
                });
                return;
            }

            nextParams.append(key, filter.value.toString());
        });

        
        nextParams.delete("page");
        this.workspaceFilterParams = nextParams;
        this.syncWorkspaceUrl();
        this.renderWorkspaceFilters();
        void this.reloadWorkspaceTiles();
        this.resetWorkspaceFilterSection();
    }

    private renderWorkspaceFilters(): void {
        const filterSection = this.element?.querySelector<HTMLElement>("[data-layout-header-section-2]");
        if (!filterSection) return;

        const filters = getFiltersFromUrl(this.workspaceFilterParams);
        if (filters.length === 0) {
            filterSection.innerHTML = "";
            return;
        }

        const filterUIContainer = new FilterEntriesContainer(
            filterSection,
            (entry) => this.removeWorkspaceFilter(entry.getFilterKey())
        );
        filterUIContainer.setFilters(filters);
        filterUIContainer.render();
    }

    private removeWorkspaceFilter(filterKey: string): void {
        this.workspaceFilterParams.delete(filterKey);
        this.workspaceFilterParams.delete("page");
        this.syncWorkspaceUrl();
        this.renderWorkspaceFilters();
        void this.reloadWorkspaceTiles();
        this.resetWorkspaceFilterSection();
    }

    private async reloadWorkspaceTiles(): Promise<void> {
        if (!this.element) return;

        const renderUrl = this.element.dataset.layoutRenderItemUrl;
        if (!renderUrl) return;

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
                this.scheduleTileResize(item.element);
            }
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

        return values;
    }

    private syncWorkspaceUrl(): void {
        const browserUrl = new URL(window.location.href);
        browserUrl.search = this.workspaceFilterParams.toString();
        window.history.replaceState(window.history.state, "", `${browserUrl.pathname}${browserUrl.search}${browserUrl.hash}`);
    }

    private resetWorkspaceFilterSection(): void {
        const workspaceId = this.element?.dataset.workspaceId;
        if (!workspaceId) return;

        const target = document.getElementById(`workspace-filter-section-${workspaceId}`);
        if (!target) return;

        htmx.ajax("get", `/components/workspaces/${workspaceId}/filters/init/`, {
            target,
            swap: "innerHTML",
        });
    }

    private getWorkspaceFilterContainer(): FilterContainer | null {
        const workspaceId = this.element?.dataset.workspaceId;
        if (!workspaceId) return null;

        const el = document.getElementById(`workspace-filter-container-${workspaceId}`) as HTMLElement | null;
        
        if (!el) return null;

        return getComponent(el) as FilterContainer;
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
        const navigationKey = this.getFnNavigationKey(event);
        if (!navigationKey || event.altKey || event.ctrlKey) return;
        if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(navigationKey)) return;
        if (this.items.length === 0) return;

        event.preventDefault();

        const delta = navigationKey === "ArrowLeft" || navigationKey === "ArrowUp" ? -1 : 1;
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
