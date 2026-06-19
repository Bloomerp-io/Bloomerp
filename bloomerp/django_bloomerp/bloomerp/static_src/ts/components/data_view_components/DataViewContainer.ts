import htmx from "htmx.org";
import BaseComponent, { getComponent, componentIdentifier, initComponents } from "../BaseComponent";
import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";
import { getLocalStorageValue, setLocalStorageValue } from "@/utils/localStorage";
import FilterContainer, { FilterEntriesContainer, FilterEntry, getFiltersFromUrl } from "../Filters";
import { getCsrfToken } from "@/utils/cookies";
import { DataViewDisplayOptions } from "./DisplayOptions";





export class DataViewContainer extends BaseComponent {

    private target:string = '#data-view-data-section'
    private baseUrl:string|null;
    private fullPath:string|null; // Includes query parameters
    private searchInput:HTMLInputElement|null = null;
    private contentTypeId:string|null = null;
    private splitViewEnabled:boolean = false;
    private syncUrl:boolean = false;
    private defaultFilters: FilterEntry[] = [];
    private pendingHistoryMode: "push" | "replace" | null = null;
    

    private afterSwapHandler: ((event: Event) => void) | null = null;

    private static readonly RESERVED_FILTER_KEYS = new Set<string>([
        "q",
        "page",
        "calendar_page",
    ]);

    public initialize(): void {
        this.baseUrl = this.element?.dataset.baseUrl;
        this.fullPath = this.element?.dataset.url;
        this.contentTypeId = this.element?.dataset.contentTypeId ?? null;
        this.searchInput = this.element?.querySelector(`#data-view-search-input-${this.contentTypeId}`) ?? null;
        this.splitViewEnabled = this.element?.dataset.splitViewEnabled === 'True';
        this.syncUrl = this.element?.dataset.syncUrl === 'true';

        this.focusSearchInput();

        // Focus on search input
        this.setupKeydownListeners();

        this.setupSplitViewResize();

        // Get the default filters
        const defaultFiltersJson = this.element?.dataset.defaultFilters ?? '{}';
        try {
            const parsed = JSON.parse(defaultFiltersJson);
            this.defaultFilters = getFiltersFromUrl(new URLSearchParams(parsed));
        } catch (error) {
            console.error('Failed to parse default filters JSON:', error);
            this.defaultFilters = [];
        }

        // Make sure the filtering mechanism is working
        const filterButton = this.element?.querySelector('#apply-filters-button');
        if (filterButton) {
            filterButton.addEventListener('click', () => {
                const filters = this.getFilterContainer()?.getFilters() || [];
                
                // construct arguments -> arg {first_name__contains: "John"}
                const args: Record<string, string | string[]> = {};
                filters.forEach(filter => {
                    if (filter.value) {
                        const key = `${filter.field}__${filter.operator}`;
                        if (Array.isArray(filter.value)) {
                            args[key] = filter.value;
                        } else {
                            args[key] = filter.value.toString();
                        }
                    }
                });
                
                // Merge new filters with existing query params
                this.filter(args, false);
                this.resetFilterSection();
            });
        }

        // Setup search
        this.element.querySelector(`#data-view-search-input-${this.contentTypeId}`)?.addEventListener('input', (event) => {
            const target = event.target as HTMLInputElement;
            const query = target.value;
            this.search(query);
        });
        
        this.afterSwapHandler = (event: Event) => this.handleAfterSwap(event);
        this.element?.addEventListener('htmx:afterSwap', this.afterSwapHandler);

        this.installCellClickOverrides();

        // Render filters based on the current URL parameters
        this.renderAppliedFilters();
        this.renderDefaultFilters();

        this.bindDisplayOptionsCallback();
    }

    /**
     * Filter's the current data view
     */
    public filter(
        args: Record<string, string | string[] | number | boolean | null | undefined> = {},
        resetParameters: boolean = false,
        pushHistory: boolean = true
    ): void {
        const base = resetParameters ? this.baseUrl : this.fullPath ?? this.baseUrl;
        if (!base) return;

        const baseUrl = new URL(base, window.location.origin);

        if (!resetParameters && this.fullPath) {
            const currentUrl = new URL(this.fullPath, window.location.origin);
            currentUrl.searchParams.forEach((value, key) => baseUrl.searchParams.set(key, value));
        }

        Object.entries(args).forEach(([key, value]) => {
            baseUrl.searchParams.delete(key);

            if (value === null || value === undefined || value === '') return;

            if (Array.isArray(value)) {
                value.forEach((item) => {
                    if (item === null || item === undefined || item === '') return;
                    baseUrl.searchParams.append(key, String(item));
                });
                return;
            }

            if (resetParameters) {
                baseUrl.searchParams.set(key, String(value));
            } else {
                baseUrl.searchParams.append(key, String(value));
            }
        });

        baseUrl.searchParams.delete('page');

        this.fullPath = baseUrl.toString();

        if (this.syncUrl) {
            this.pendingHistoryMode = pushHistory ? "push" : "replace";
        }

        htmx.ajax('get', this.fullPath, {
            target: this.target,
            swap: 'innerHTML',
        });

    }

    /**
     * Refreshes the current data view, keeping the existing query parameters intact.
     */
    public refresh(): void {
        const url = this.getCurrentUrl();
        if (!url) return;

        this.applyUrl(url, false);
    }

    /**
     * Removes a filter from the current data view
     * @param key The key of the filter to remove
     * @param isDefaultFilter Whether the filter is a default filter
     * @returns void
     */
    private removeFilter(key: string, isDefaultFilter:boolean=false): void {
        if (isDefaultFilter) {
            // Remove the filter from the default filters list
            this.defaultFilters = this.defaultFilters.filter(filter => filter.getFilterKey() !== key);
            this.saveFilterState(this.defaultFilters);
            return;
        }

        const url = this.getCurrentUrl();
        if (!url) return;

        url.searchParams.delete(key);
        url.searchParams.delete('page');
        this.applyUrl(url);
    }

    /**
     * Removes all filters from the current data view
     * @param isDefaultFilter Whether the filters to clear are default filters. 
     * @returns void
     */
    private clearAllFilters(isDefaultFilter: boolean = false): void {
        if (isDefaultFilter) {
            this.saveFilterState([])
        }

        const url = this.getCurrentUrl();
        if (!url) return;

        Array.from(url.searchParams.keys()).forEach((key) => {
            if (DataViewContainer.RESERVED_FILTER_KEYS.has(key)) return;
            url.searchParams.delete(key);
        });
        url.searchParams.delete('page');

        this.applyUrl(url);
    }

    private applyUrl(url: URL, pushHistory: boolean = true): void {
        this.fullPath = url.toString();
        if (this.syncUrl) {
            this.pendingHistoryMode = pushHistory ? "push" : "replace";
        }

        htmx.ajax('get', this.fullPath, {
            target: this.target,
            swap: 'innerHTML',
        });
    }

    private handleAfterSwap(event: Event): void {
        if (!(event instanceof CustomEvent)) return;

        const target = event.detail?.target as HTMLElement | null | undefined;
        if (!target || target.id !== 'data-view-data-section') return;

        const responseUrl = event.detail?.xhr?.responseURL;
        if (!responseUrl) return;

        this.fullPath = new URL(responseUrl, window.location.origin).toString();

        if (this.syncUrl) {
            this.syncBrowserUrl(
                new URL(this.fullPath, window.location.origin),
                this.pendingHistoryMode ?? "replace",
            );
            this.pendingHistoryMode = null;
        }

        this.installCellClickOverrides();
        this.setupSplitViewResize();
        this.renderAppliedFilters();
    }

    private renderAppliedFilters(): void {
        if (!this.contentTypeId) return;

        const target = this.element?.querySelector<HTMLElement>(`#applied-filters-${this.contentTypeId}`);
        if (!target) return;

        const url = this.getCurrentUrl();
        const defaultFilterKeys = new Set(
            this.defaultFilters.map((filter) => filter.getFilterKey())
        );
        const filters = (url ? getFiltersFromUrl(url.searchParams) : []).filter(
            (filter) => !defaultFilterKeys.has(filter.getFilterKey())
        );
        const filterList = new FilterEntriesContainer(
            target,
            (entry) => this.removeFilter(entry.getFilterKey()),
            this.clearAllFilters.bind(this)
        );

        // Set default filters to be non-removable
        this.defaultFilters.forEach(filter => filter.setRemovable(false));

        filterList.setFilters(this.defaultFilters.concat(filters));
        filterList.setClearable(filters.length > 0);
        filterList.setSavable(filters.length > 0);
        filterList.setSaveHandler(this.saveFilterState.bind(this));
        filterList.render();
    }

    private renderDefaultFilters(): void {
        if (!this.contentTypeId) return;
        let target = this.element?.querySelector<HTMLElement>(`#default-filters-${this.contentTypeId}`);
        if (!target) return;

        const filterList = new FilterEntriesContainer(
            target,
            (entry) => {this.removeFilter(entry.getFilterKey(), true)}, 
            (entry) => {this.clearAllFilters(true)},  
        );

        filterList.setFilters(this.defaultFilters);
        filterList.setRemovable(true);
        filterList.render();
    }

    private async saveFilterState(entries: FilterEntry[]): Promise<void> {
        if (!this.contentTypeId) return;

        const defaultFilters: Record<string, string | string[]> = {};
        entries.forEach((entry) => {
            const key = entry.getFilterKey();
            if (!key || DataViewContainer.RESERVED_FILTER_KEYS.has(key) || key.startsWith("_arg_")) {
                return;
            }

            if (entry.value === null || entry.value === "") {
                return;
            }

            defaultFilters[key] = entry.value;
        });

        const csrfToken = getCsrfToken();
        const formData = new FormData();
        formData.set("default_filters", JSON.stringify(defaultFilters));
        if (csrfToken) {
            formData.set("csrfmiddlewaretoken", csrfToken);
        }

        const response = await fetch(`/components/change_data_view_preference/${this.contentTypeId}/`, {
            method: "POST",
            body: formData,
            credentials: "same-origin",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
                ...(csrfToken ? { "X-CSRFToken": csrfToken } : {}),
            },
        });

        if (!response.ok) {
            console.error("Failed to save default filters:", response.statusText);
            return;
        }

        this.defaultFilters = entries;
        this.renderAppliedFilters();

        const html = await response.text();
        this.replaceDisplayOptions(html);
        this.refresh();
    }
    
    private installCellClickOverrides(): void {
        let dataView: BaseDataViewComponent;

        try {
            dataView = this.getDataViewComponent();
        } catch {
            return;
        }

        const cells = dataView.getCells();
        for (const cell of cells) {
            cell.onClickOverride = (clickedCell) => this.onCellClick(clickedCell);
        }
    }

    protected onAdd(_event: MouseEvent): boolean {
        return false;
    }

    protected onCellClick(_cell: BaseDataViewCell): boolean {
        return false;
    }

    protected navigateTo(url: string, target: string | HTMLElement = '#main-content', pushUrl: boolean = true): void {
        htmx.ajax('get', url, {
            target,
            swap: 'innerHTML',
            push: pushUrl ? 'true' : 'false',
        });
    }

    private syncBrowserUrl(dataViewUrl: URL, historyMode: "push" | "replace" = "replace"): void {
        const browserUrl = new URL(window.location.href);
        browserUrl.search = dataViewUrl.search;
        const nextUrl = `${browserUrl.pathname}${browserUrl.search}${browserUrl.hash}`;
        if (historyMode === "push" && nextUrl !== `${window.location.pathname}${window.location.search}${window.location.hash}`) {
            window.history.pushState(window.history.state, '', nextUrl);
            return;
        }

        window.history.replaceState(window.history.state, '', nextUrl);
    }

    private getCurrentUrl(): URL | null {
        const base = this.fullPath ?? this.baseUrl;
        if (!base) return null;
        return new URL(base, window.location.origin);
    }

    private resetFilterSection(): void {
        if (!this.contentTypeId) return;

        const target = document.getElementById(`filter-section-${this.contentTypeId}`);
        if (!target) return;

        htmx.ajax(
            'get',
            `/components/filters/${this.contentTypeId}/init/`,
            {
                target: target,
                swap: 'innerHTML',
            }
        );
    }

    private getFilterContainer(): FilterContainer | null {
        if (!this.contentTypeId) return null;
        const el = document.getElementById(`filter-container-${this.contentTypeId}`) as HTMLElement | null;
        if (!el) return null;
        return getComponent(el) as FilterContainer;
    }
    
    public getDataViewComponent() : BaseDataViewComponent {
        if (!this.element) throw new Error('DataViewContainer element not found');

        const candidates = Array.from(
            this.element.querySelectorAll<HTMLElement>(`[${componentIdentifier}]`)
        );

        for (const el of candidates) {
            const comp = getComponent(el);
            if (!comp) continue;
            if (comp instanceof BaseDataViewComponent) return comp as BaseDataViewComponent;
        }

        throw new Error('No DataView component found inside DataViewContainer');
    }

    /** 
     * Search related methods
    */
    public focusSearchInput(): void {
        if (this.searchInput) {
            this.searchInput.focus();
        }
    }

    public unfocusSearchInput(): void {
        if (this.searchInput) {
            this.searchInput.blur();
        }
    }

    public isFocusOnSearchInput(): boolean {
        if (this.searchInput) {
            return document.activeElement === this.searchInput;
        }
        return false;
    }

    public setupKeydownListeners(): void {
        if (!this.searchInput) return;

        this.searchInput.addEventListener('keydown', (event: KeyboardEvent) => {

            if (event.key === 'ArrowDown' && this.isFocusOnSearchInput()) {
                event.preventDefault();
                this.unfocusSearchInput();
                const dataView = this.getDataViewComponent();
                dataView.initFocus();
            }
        });

        this.element?.addEventListener('keydown', (event: KeyboardEvent) => {

            if ((event.ctrlKey || event.metaKey) && event.key === 'f') {
                event.preventDefault();
                this.focusSearchInput();

                this.getDataViewComponent().clearSelection();
            }
        });
    }

    public search(query: string) : void {
        this.filter({ q: query }, false, false);
    }


    private setupSplitViewResize(): void {
        if (!this.splitViewEnabled || !this.element) return;

        const container = this.element.querySelector<HTMLElement>('[data-split-view-container]');
        const listPane = this.element.querySelector<HTMLElement>('[data-split-view-list-pane]');
        const divider = this.element.querySelector<HTMLElement>('[data-split-view-divider]');

        if (!container || !listPane || !divider) return;

        const storageKey = `bloomerp_dataview_split_width_${this.contentTypeId ?? "default"}`;
        const minWidth = 260;

        const clampWidth = (width: number): number => {
            const maxWidth = Math.max(minWidth, container.clientWidth - minWidth);
            return Math.min(Math.max(width, minWidth), maxWidth);
        };

        const applyWidth = (width: number, store: boolean = false): void => {
            const clamped = clampWidth(width);
            listPane.style.width = `${clamped}px`;
            listPane.style.flexBasis = `${clamped}px`;
            if (store) {
                setLocalStorageValue(storageKey, clamped);
            }
        };

        const storedWidth = getLocalStorageValue<number | null>(storageKey, null);
        if (storedWidth !== null) {
            applyWidth(storedWidth);
        }

        divider.addEventListener("pointerdown", (event: PointerEvent) => {
            event.preventDefault();
            const startX = event.clientX;
            const startWidth = listPane.getBoundingClientRect().width;

            const onMove = (moveEvent: PointerEvent): void => {
                const delta = moveEvent.clientX - startX;
                applyWidth(startWidth + delta);
            };

            const onUp = (): void => {
                document.removeEventListener("pointermove", onMove);
                document.removeEventListener("pointerup", onUp);
                const finalWidth = listPane.getBoundingClientRect().width;
                setLocalStorageValue(storageKey, clampWidth(finalWidth));
            };

            document.addEventListener("pointermove", onMove);
            document.addEventListener("pointerup", onUp);
        });
    }
    


    /**
     * Hides the filtered badge from the applied filter section.
     * 
     * If all filters are removed, the clear all button will also be hidden. This is done by checking if there are any visible badges left after hiding the specified one, and if not, hiding the clear all button as well.
     * 
     * @param key The key of the filter to hide
     */
    public hideFilter(key:string): void {
        const badge = this.element?.querySelector(`[data-filter-key="${key}"]`) as HTMLElement | null;
        if (badge) {
            badge.style.display = 'none';
        }
    }

    private bindDisplayOptionsCallback(): void {
        const displayOptionsElement = this.element?.querySelector<HTMLElement>(
            '[bloomerp-component="dataview-display-options"]'
        );
        if (!displayOptionsElement) return;

        if (displayOptionsElement.dataset.viewType && this.element) {
            this.element.dataset.viewType = displayOptionsElement.dataset.viewType;
        }
        if (displayOptionsElement.dataset.splitViewEnabled && this.element) {
            this.element.dataset.splitViewEnabled = displayOptionsElement.dataset.splitViewEnabled;
            this.splitViewEnabled = displayOptionsElement.dataset.splitViewEnabled === "True";
        }

        const displayOptionsComponent = getComponent(displayOptionsElement) as DataViewDisplayOptions | null;
        if (!displayOptionsComponent) return;

        displayOptionsComponent.setOptionChangedCallback(() => {
            this.bindDisplayOptionsCallback();
            this.renderDefaultFilters();
            this.refresh();
        });
    }

    private replaceDisplayOptions(html: string): void {
        const displayOptionsElement = this.element?.querySelector<HTMLElement>(
            '[bloomerp-component="dataview-display-options"]'
        );
        if (!displayOptionsElement || !displayOptionsElement.parentElement) return;

        const template = document.createElement("template");
        template.innerHTML = html.trim();
        const replacement = template.content.firstElementChild as HTMLElement | null;
        if (!replacement) return;

        const parent = displayOptionsElement.parentElement;
        displayOptionsElement.replaceWith(replacement);
        initComponents(parent);
        this.bindDisplayOptionsCallback();
        this.renderDefaultFilters();
    }

    public onAfterSwap(): void {
        this.bindDisplayOptionsCallback();
        this.renderDefaultFilters();
    }

    
    public destroy(): void {
        if (this.afterSwapHandler) {
            this.element?.removeEventListener('htmx:afterSwap', this.afterSwapHandler);
        }
    }    
}
