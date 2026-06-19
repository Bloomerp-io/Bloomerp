import htmx from "htmx.org";
import BaseComponent, { getComponent, componentIdentifier, initComponents } from "../BaseComponent";
import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";
import { getLocalStorageValue, setLocalStorageValue } from "@/utils/localStorage";
import FilterContainer, { FilterEntriesContainer, FilterEntry, getFiltersFromUrl } from "../Filters";
import { getCsrfToken } from "@/utils/cookies";
import { DataViewDisplayOptions } from "./DisplayOptions";
import ObjectCRUDViewContainer from "../detail_view_components/ObjectCRUDViewContainer";
import { getModal } from "@/utils/modals";
import { insertSkeleton } from "@/utils/animations";



export class DataViewContainer extends BaseComponent {

    private target:string = '#data-view-data-section'
    private baseUrl:string|null;
    private fullPath:string|null; // Includes query parameters
    private searchInput:HTMLInputElement|null = null;
    private contentTypeId:string|null = null;
    private syncUrl:boolean = false;
    private defaultFilters: FilterEntry[] = [];
    private pendingHistoryMode: "push" | "replace" | null = null;
    
    // Split view related properties
    private splitViewEnabled:boolean = false;
    private splitViewFocusOnListPane:boolean = true;

    private afterSwapHandler: ((event: Event) => void) | null = null;
    private splitViewPaneShortcutHandler: ((event: KeyboardEvent) => void) | null = null;
    private bulkCheckboxChangeHandler: ((event: Event) => void) | null = null;
    private bulkAllClickHandler: ((event: Event) => void) | null = null;
    private bulkSelectionClickHandler: ((event: Event) => void) | null = null;
    private bulkActionCompleteHandler: ((event: Event) => void) | null = null;
    private selectedObjectIds: Set<string> = new Set();

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

        this.setupSplitViewFocusTargets();
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

        // Setup bulk checkbox listeners
        this.addBulkListeners();

        this.bulkActionCompleteHandler = (event: Event) => this.handleBulkActionComplete(event);
        document.body.addEventListener('bloomerp:bulk-action-complete', this.bulkActionCompleteHandler);
    }

    /**
     * FILTERING, SEARCHING, AND REFRESHING
     */

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

        insertSkeleton(document.querySelector(this.target) as HTMLElement);

        htmx.ajax('get', this.fullPath, {
            target: this.target,
            swap: 'innerHTML',
        })
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
        this.setupSplitViewFocusTargets();
        this.setupSplitViewResize();
        this.renderAppliedFilters();
        this.syncBulkCheckboxes();
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
            cell.dataViewClickOverride = (clickedCell) => this.onCellClick(clickedCell);
        }
    }
    
    protected onAdd(_event: MouseEvent): boolean {
        return false;
    }

    protected onCellClick(_cell: BaseDataViewCell): boolean {
        this.splitViewFocusOnListPane = false;
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
        this.searchInput?.addEventListener('keydown', (event: KeyboardEvent) => {

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

        this.splitViewPaneShortcutHandler = (event: KeyboardEvent) => this.handleSplitViewPaneShortcut(event);
        this.element?.addEventListener('keydown', this.splitViewPaneShortcutHandler);
    }

    public search(query: string) : void {
        this.filter({ q: query }, false, false);
    }

    /**
     * BUTTON CONTROLS
     */
    public showButton(key:string) {
        this.element?.querySelector<HTMLElement>(`[data-data-view-button="${key}"]`)?.classList.remove('hidden');
    }

    public hideButton(key:string) {
        this.element?.querySelector<HTMLElement>(`[data-data-view-button="${key}"]`)?.classList.add('hidden');
    }


    /**
     * BULK CONTROLS
     */
    private getBulkCheckboxes(): NodeListOf<HTMLInputElement> {
        return this.element?.querySelectorAll<HTMLInputElement>('input[data-bulk-checkbox]') ?? document.querySelectorAll<HTMLInputElement>('input[data-bulk-checkbox]:not(*)');
    }

    private addBulkListeners() : void {
        const openModalForAllBtn = this.element?.querySelector<HTMLElement>('#bulk-actions-all-btn');
        const openModalForSelectionBtn = this.element?.querySelector<HTMLElement>('#bulk-actions-selection-btn');

        if (openModalForAllBtn) {
            this.bulkAllClickHandler = () => this.openBulkActionsModal(false);
            openModalForAllBtn.addEventListener('click', this.bulkAllClickHandler);
        }

        if (openModalForSelectionBtn) {
            this.bulkSelectionClickHandler = () => this.openBulkActionsModal(true);
            openModalForSelectionBtn.addEventListener('click', this.bulkSelectionClickHandler);
        }

        this.bulkCheckboxChangeHandler = (event: Event) => this.handleBulkCheckboxChange(event);
        this.element?.addEventListener('change', this.bulkCheckboxChangeHandler);
        this.syncBulkCheckboxes();
    }

    private getBulkRowCheckboxes(): HTMLInputElement[] {
        return Array.from(this.getBulkCheckboxes()).filter((checkbox) => checkbox.dataset.all !== 'true');
    }

    private handleBulkCheckboxChange(event: Event): void {
        const checkbox = event.target as HTMLInputElement | null;
        if (!checkbox?.matches('input[data-bulk-checkbox]')) return;

        if (checkbox.dataset.all === 'true') {
            this.getBulkRowCheckboxes().forEach((rowCheckbox) => {
                rowCheckbox.checked = checkbox.checked;
                const objectId = rowCheckbox.dataset.objectId;
                if (!objectId) return;
                if (checkbox.checked) {
                    this.selectedObjectIds.add(objectId);
                } else {
                    this.selectedObjectIds.delete(objectId);
                }
            });
            this.syncBulkCheckboxes();
            return;
        }

        const objectId = checkbox.dataset.objectId;
        if (objectId) {
            if (checkbox.checked) {
                this.selectedObjectIds.add(objectId);
            } else {
                this.selectedObjectIds.delete(objectId);
            }
        }

        this.syncBulkCheckboxes();
    }

    private syncBulkCheckboxes(): void {
        const rowCheckboxes = this.getBulkRowCheckboxes();
        rowCheckboxes.forEach((checkbox) => {
            const objectId = checkbox.dataset.objectId;
            checkbox.checked = Boolean(objectId && this.selectedObjectIds.has(objectId));
        });

        const masterCheckbox = this.element?.querySelector<HTMLInputElement>('input[data-bulk-checkbox][data-all="true"]');
        const allChecked = rowCheckboxes.length > 0 && rowCheckboxes.every((checkbox) => checkbox.checked);
        const anyChecked = rowCheckboxes.some((checkbox) => checkbox.checked);
        if (masterCheckbox) {
            masterCheckbox.checked = allChecked;
            masterCheckbox.indeterminate = !allChecked && anyChecked;
        }
    }

    private buildBulkActionsUrl(useSelection: boolean): string | null {
        if (!this.contentTypeId) return null;

        const currentUrl = this.getCurrentUrl();
        const url = new URL(`/components/data_view/${this.contentTypeId}/bulk_actions/`, window.location.origin);
        url.searchParams.set('selection', useSelection ? 'selected' : 'filtered');
        currentUrl?.searchParams.forEach((value, key) => {
            if (key === 'page') return;
            if (key === 'selection') return;
            url.searchParams.append(key, value);
        });

        if (useSelection) {
            this.selectedObjectIds.forEach((objectId) => {
                url.searchParams.append('object_ids', objectId);
            });
        }

        return url.toString();
    }

    private openBulkActionsModal(useSelection: boolean): void {
        const url = this.buildBulkActionsUrl(useSelection);
        const modal = getModal('bulk-actions-modal');
        if (!url || !modal) return;

        htmx.ajax('get', url, {
            target: '#bulk-actions-modal-body',
            swap: 'innerHTML',
        });

        modal.open();
    }

    private handleBulkActionComplete(event: Event): void {
        const customEvent = event as CustomEvent<{ contentTypeId?: string }>;
        if (customEvent.detail?.contentTypeId !== this.contentTypeId) return;

        this.selectedObjectIds.clear();
        this.refresh();
    }




    /**
     * SPLIT VIEW CONTROLS
     */
    private handleSplitViewPaneShortcut(event: KeyboardEvent): void {
        if (!this.isSplitViewPaneShortcut(event)) return;

        event.preventDefault();
        event.stopPropagation();

        // Handle the focus toggle between the list pane and the detail pane
        const listPane = this.getSplitViewListPane();
        const detailPane = this.getSplitViewDetailPane();
        if (!listPane || !detailPane) return;
        
        if (this.splitViewFocusOnListPane && detailPane) {
            detailPane.focusFirstItemInRow(0);
            this.splitViewFocusOnListPane = false;
            return;
        }

        this.focusSplitViewListPane(listPane);
        this.splitViewFocusOnListPane = true;
    }

    private isSplitViewPaneShortcut(event: KeyboardEvent): boolean {
        if (!this.splitViewEnabled) return false;
        if (event.ctrlKey || event.metaKey) return false;

        const isMac = navigator.platform.toLowerCase().includes('mac');

        if (isMac) {
            return event.altKey && event.key === 'Tab';
        }

        return event.altKey && event.key === '.';
    }

    private setupSplitViewFocusTargets(): void {
        if (!this.splitViewEnabled || !this.element) return;

        const listPane = this.getSplitViewListPane();

        listPane?.setAttribute('tabindex', '-1');
    }

    private focusSplitViewListPane(listPane: HTMLElement): void {
        try {
            const dataView = this.getDataViewComponent();
            if (!dataView.currentCell) {
                dataView.initFocus();
                return;
            }

            dataView.element?.focus();
            return;
        } catch {
            listPane.focus();
        }
    }

    private getSplitViewListPane(): HTMLElement | null {
        return this.element?.querySelector<HTMLElement>('[data-split-view-list-pane]') ?? null;
    }

    private getSplitViewDetailPane(): ObjectCRUDViewContainer | null {
        let el = this.element?.querySelector<HTMLElement>('[bloomerp-component="object-crud-view-container"]') ?? null;
        if (!el) return null;

        return getComponent(el) as ObjectCRUDViewContainer | null;
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
        if (this.splitViewPaneShortcutHandler) {
            this.element?.removeEventListener('keydown', this.splitViewPaneShortcutHandler);
        }
        if (this.bulkCheckboxChangeHandler) {
            this.element?.removeEventListener('change', this.bulkCheckboxChangeHandler);
        }
        if (this.bulkActionCompleteHandler) {
            document.body.removeEventListener('bloomerp:bulk-action-complete', this.bulkActionCompleteHandler);
        }
        const openModalForAllBtn = this.element?.querySelector<HTMLElement>('#bulk-actions-all-btn');
        const openModalForSelectionBtn = this.element?.querySelector<HTMLElement>('#bulk-actions-selection-btn');
        if (openModalForAllBtn && this.bulkAllClickHandler) {
            openModalForAllBtn.removeEventListener('click', this.bulkAllClickHandler);
        }
        if (openModalForSelectionBtn && this.bulkSelectionClickHandler) {
            openModalForSelectionBtn.removeEventListener('click', this.bulkSelectionClickHandler);
        }
    }    
}
