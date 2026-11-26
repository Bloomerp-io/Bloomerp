import htmx, { type HtmxAjaxHelperContext } from "htmx.org";
import { Drawer } from "../Drawer";
import BaseComponent, { getComponent, componentIdentifier } from "../BaseComponent";
import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";
import { DataViewDisplayOptions } from "./DisplayOptions";
import ObjectCRUDViewContainer from "../detail_view_components/ObjectCRUDViewContainer";
import { insertSkeleton } from "@/utils/animations";
import { RenderedFilters } from '../filters/RenderedFilters';

export const DATAVIEW_ROOT = '[data-base-url][data-content-type-id]';
const DATAVIEW_RECORD = '[data-dataview-record]';
const RECORD_CHECKBOX = 'input[data-bulk-checkbox]';
const ITEM_CHECKBOX = `${RECORD_CHECKBOX}[data-object-id]`;
const SELECTION_PRESENTATION_PARAMS = [
    'page', 'calendar_page', 'calendar_view_mode', 'calendar_unit', 'calendar_unit_offset',
    'gant_page', 'gant_unscheduled_page', 'kanban_page', 'kanban_column', 'kanban_loaded_ids',
];

export class DataViewContainer extends BaseComponent {
    private renderedFilters?: RenderedFilters;

    private unifiedFilterHandler = (event: Event): void => {
        const detail = (event as CustomEvent).detail;
        if (detail?.scope !== 'model' || String(detail.id) !== this.contentTypeId) return;
        event.stopPropagation();
        this.renderedFilters?.setFilters(detail.filters, detail);
        this.filter({ filter: JSON.stringify(detail.filters) }, false);
    };

    private target:HTMLElement|null = null;
    private baseUrl:string|null;
    private fullPath:string|null; // Includes query parameters
    private searchInput:HTMLInputElement|null = null;
    private contentTypeId:string|null = null;
    private syncUrl:boolean = false;
    
    // Split view related properties
    private splitViewEnabled:boolean = false;
    private splitViewFocusOnListPane:boolean = true;

    private afterSwapHandler: ((event: Event) => void) | null = null;
    private splitViewPaneShortcutHandler: ((event: KeyboardEvent) => void) | null = null;
    private readonly selectedObjectIds = new Set<string>();
    private selectionContentType: string | null = null;

    /** Bind data-view controls without stealing focus from an owning tile or detail tab. */
    public initialize(): void {
        this.element?.addEventListener('bloomerp:filters-apply', this.unifiedFilterHandler);
        this.element?.addEventListener('htmx:beforeCleanupElement', this.handleCleanup);
        this.baseUrl = this.element?.dataset.baseUrl;
        this.fullPath = this.element?.dataset.url;
        this.contentTypeId = this.element?.dataset.contentTypeId ?? null;
        const renderedRoot = this.element?.querySelector<HTMLElement>('[data-rendered-filters]');
        if (renderedRoot) {
            this.renderedFilters = new RenderedFilters(renderedRoot, filters => {
                if (this.element) this.renderedFilters?.syncEditor(this.element, filters);
                this.filter({ filter: JSON.stringify(filters) }, false);
            });
            this.renderedFilters.restore(new URL(this.fullPath || this.baseUrl || location.href, location.origin).searchParams.get('filter'));
        }
        this.searchInput = this.element?.querySelector(`#data-view-search-input-${this.contentTypeId}`) ?? null;
        this.splitViewEnabled = this.element?.dataset.splitViewEnabled === 'True';
        this.syncUrl = this.element?.dataset.syncUrl === 'true';

        // Setup target
        this.setDataviewTarget();

        const detail = this.element?.closest('[data-detail-view-grid]');
        const focusedTabStrip = document.activeElement?.closest('[data-tab-strip]');
        if (!this.element?.closest(`[${componentIdentifier}="workspace-tile"]`)
            && !(focusedTabStrip && detail?.contains(focusedTabStrip))) {
            this.focusSearchInput();
        }

        
        this.setupKeydownListeners();

        this.setupSplitViewFocusTargets();

        // Setup search
        this.element.querySelector(`#data-view-search-input-${this.contentTypeId}`)?.addEventListener('input', (event) => {
            const target = event.target as HTMLInputElement;
            const query = target.value;
            this.search(query);
        });
        
        this.afterSwapHandler = (event: Event) => this.handleAfterSwap(event);
        this.element?.addEventListener('htmx:afterSwap', this.afterSwapHandler);

        this.installCellClickOverrides();

        this.bindDisplayOptionsCallback();

        this.element.addEventListener('change', this.handleRecordCheckboxChange);
        document.body.addEventListener('bloomerp:dataview-refresh', this.handleRefreshRequest);
        document.body.addEventListener('bloomerp:dataview-record-refresh', this.handleRecordRefreshRequest);
        this.syncRecordSelection();
    }

    /**
     * FILTERING, SEARCHING, AND REFRESHING
     */

    /** Filter the view while retaining its signed layout and permissions when resetting the query. */
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

        const listPane = this.splitViewEnabled ? this.getSplitViewListPane() : null;
        const loadingTarget = listPane?.querySelector<HTMLElement>("[data-resizable-div-panel]") ?? listPane ?? this.target;
        insertSkeleton(loadingTarget);
        this.applyUrl(baseUrl, pushHistory);
    }

    /** Reload the current results, optionally retaining the browser URL exactly as it is. */
    public refresh(updateHistory: boolean = true): void {
        const url = this.getCurrentUrl();
        if (!url) return;

        this.applyUrl(url, false, updateHistory);
    }

    public override onHistoryRestore(): void {
        if (!this.syncUrl) {
            this.refresh();
            return;
        }

        this.reloadCurrentBrowserQuery();
    }

    private reloadCurrentBrowserQuery(): void {
        const requestUrl = new URL(
            this.baseUrl ?? this.fullPath ?? window.location.href,
            window.location.origin,
        );
        requestUrl.search = window.location.search;
        this.applyUrl(requestUrl, false);
    }

    /** Request the updated list section with the appropriate browser history update. */
    /** Request results with an HTMX request queue owned by this view. */
    private applyUrl(url: URL, pushHistory: boolean = true, updateHistory: boolean = true): void {
        if (!this.target) return;
        this.resetSelectionOnQueryChange(url);
        this.fullPath = url.toString();
        if (this.element) this.element.dataset.url = this.fullPath;
        const historyUpdate = updateHistory ? this.getHistoryUpdate(url, pushHistory) : { push: 'false', replace: 'false' };
        htmx.ajax('get', this.fullPath, {
            source: this.element,
            target: this.target,
            swap: 'innerHTML',
            ...historyUpdate,
        });
    }

    /** Choose the HTMX history update for a data view request. */
    private getHistoryUpdate(url: URL, pushHistory: boolean): Pick<HtmxAjaxHelperContext, "push" | "replace"> {
        if (!this.syncUrl) return {};

        const browserUrl = new URL(window.location.href);
        browserUrl.search = url.search;
        const nextUrl = `${browserUrl.pathname}${browserUrl.search}${browserUrl.hash}`;
        const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;

        if (pushHistory && nextUrl !== currentUrl) {
            return { push: nextUrl };
        }

        return { replace: nextUrl };
    }

    /** Track the results URL for this view when its main data section is replaced. */
    private handleAfterSwap(event: Event): void {
        if (!(event instanceof CustomEvent)) return;

        const target = event.detail?.target as HTMLElement | null | undefined;
        if (!target || target !== this.target) return;

        const responseUrl = event.detail?.xhr?.responseURL;
        if (!responseUrl) return;

        const url = new URL(responseUrl, window.location.origin);
        this.resetSelectionOnQueryChange(url);
        this.fullPath = url.toString();
        if (this.element) this.element.dataset.url = this.fullPath;

        this.installCellClickOverrides();
        this.setupSplitViewFocusTargets();
        this.syncRecordSelection();
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
    
    protected onCellClick(_cell: BaseDataViewCell): boolean {
        this.splitViewFocusOnListPane = false;
        return false;
    }

    private getCurrentUrl(): URL | null {
        const base = this.fullPath ?? this.baseUrl;
        if (!base) return null;
        return new URL(base, window.location.origin);
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

    /** Find elements owned by this view, excluding elements in nested DataViews. */
    private getOwnedElements<T extends HTMLElement>(selector: string): T[] {
        return Array.from(this.element.querySelectorAll<T>(selector))
            .filter((control: T): boolean => control.closest(DATAVIEW_ROOT) === this.element);
    }

    /** Reset checked records when the collection changes and retain them across presentation changes. */
    private resetSelectionOnQueryChange(next: URL): void {
        const current = this.getCurrentUrl();
        if (!current || this.selectedObjectIds.size === 0) return;
        const currentQuery = current.searchParams;
        const nextQuery = new URLSearchParams(next.search);
        for (const key of SELECTION_PRESENTATION_PARAMS) {
            currentQuery.delete(key);
            nextQuery.delete(key);
        }
        currentQuery.sort();
        nextQuery.sort();
        if (current.pathname === next.pathname && currentQuery.toString() === nextQuery.toString()) return;
        this.selectedObjectIds.clear();
        this.syncRecordSelection();
    }

    /** Identify selectable records only when an available action targets their model. */
    private getRenderedRecordType(): string | null {
        if (!this.element.hasAttribute('data-dataview-selection-enabled')) return null;
        if (this.target?.firstElementChild?.hasAttribute('data-record-selection-disabled')) return null;
        const recordType = this.getDisplayedContentType();
        return recordType === this.contentTypeId ? recordType : null;
    }

    /** Read the represented model when a renderer displays a different type from its host. */
    private getDisplayedContentType(): string | null {
        const [override] = this.getOwnedElements<HTMLElement>('[data-dataview-record-type]');
        return override?.dataset.dataviewRecordType || this.contentTypeId;
    }

    /** Return selected IDs only when the action targets the same model as the checkboxes. */
    public getActionSelection(): string[] {
        return this.contentTypeId && this.getRenderedRecordType() === this.contentTypeId
            ? Array.from(this.selectedObjectIds)
            : [];
    }

    /** Apply the same checked state to one record or all records shown in the view. */
    private setRecordsChecked(checkboxes: HTMLInputElement[], checked: boolean): void {
        for (const checkbox of checkboxes) {
            const id = checkbox.dataset.objectId;
            if (!id) continue;
            if (checked) this.selectedObjectIds.add(id);
            else this.selectedObjectIds.delete(id);
        }
        this.syncRecordSelection();
    }

    /** Translate individual and select-all checkbox changes into record selection. */
    private handleRecordCheckboxChange = (event: Event): void => {
        const checkbox = event.target;
        if (!(checkbox instanceof HTMLInputElement) || !checkbox.matches(RECORD_CHECKBOX)) return;
        if (checkbox.closest(DATAVIEW_ROOT) !== this.element || !this.getRenderedRecordType()) return;
        const records = checkbox.hasAttribute('data-all')
            ? this.getOwnedElements<HTMLInputElement>(ITEM_CHECKBOX)
            : [checkbox];
        this.setRecordsChecked(records, checkbox.checked);
    };

    /** Restore checkboxes, duplicate renderings, and toolbar controls from the owning view's state. */
    private syncRecordSelection(): void {
        const recordType = this.getRenderedRecordType();
        if (recordType !== this.selectionContentType) {
            this.selectedObjectIds.clear();
            this.selectionContentType = recordType;
        }
        const checkboxes = this.getOwnedElements<HTMLInputElement>(RECORD_CHECKBOX);
        let shown = 0;
        let checked = 0;
        for (const checkbox of checkboxes) {
            checkbox.hidden = !recordType;
            const id = checkbox.dataset.objectId;
            if (!id) continue;
            const selected = Boolean(recordType && this.selectedObjectIds.has(id));
            checkbox.checked = selected;
            checkbox.closest('[data-dataview-record]')?.toggleAttribute('data-dataview-record-selected', selected);
            shown++;
            if (selected) checked++;
        }
        const allChecked = shown > 0 && checked === shown;
        for (const checkbox of checkboxes) {
            if (!checkbox.hasAttribute('data-all')) continue;
            checkbox.checked = allChecked;
            checkbox.indeterminate = checked > 0 && !allChecked;
            checkbox.disabled = shown === 0;
        }
        const count = recordType ? this.selectedObjectIds.size : 0;
        const [status] = this.getOwnedElements<HTMLElement>('[data-selection-count]');
        const [bar] = this.getOwnedElements<HTMLElement>('[data-dataview-selection-bar]');
        const [actions] = this.getOwnedElements<HTMLElement>('[data-dataview-selection-actions]');
        if (bar) bar.hidden = count === 0;
        if (actions) actions.hidden = count === 0 || recordType !== this.contentTypeId;
        if (status) {
            const label = count ? status.dataset.label?.replace('%(count)s', String(count)) ?? '' : '';
            if (status.textContent !== label) status.textContent = label;
        }
    }

    /** Reload the current results for model changes and view-scoped refresh requests. */
    private handleRefreshRequest = (event: Event): void => {
        const { renderId, result, contentTypeId, originOnly } = (event as CustomEvent<{
            renderId?: string;
            result?: string;
            contentTypeId?: number | string;
            originOnly?: boolean;
        }>).detail ?? {};
        if (renderId) {
            if (renderId !== this.element.dataset.renderId) return;
            if (this.getRenderedRecordType() === this.contentTypeId) this.selectedObjectIds.clear();
            this.syncRecordSelection();
        } else if (contentTypeId != null && !originOnly) {
            const typeId = String(contentTypeId);
            if (typeId !== this.contentTypeId && typeId !== this.getDisplayedContentType()) return;
        } else if ((!originOnly && result !== 'saved') || !(event.target instanceof Element) ||
            event.target.closest(DATAVIEW_ROOT) !== this.element) {
            return;
        }
        this.refresh(false);
    };

    /** Replace each matching occurrence with a fragment from its own DataView. */
    private handleRecordRefreshRequest = (event: Event): void => {
        const { contentTypeId, objectId, originOnly } = (event as CustomEvent<{
            contentTypeId?: number | string;
            objectId?: number | string;
            originOnly?: boolean;
        }>).detail ?? {};
        if (contentTypeId == null || objectId == null) return;
        const source = event.target instanceof Element ? event.target : null;
        const isOrigin = source?.closest(DATAVIEW_ROOT) === this.element;
        if (originOnly && !isOrigin) return;
        const sourceRecord = isOrigin ? source?.closest<HTMLElement>(DATAVIEW_RECORD) : null;
        const displayedType = this.getDisplayedContentType();
        const typeId = String(contentTypeId);
        const recordId = String(objectId);
        const targets = new Map<HTMLElement, string>();
        for (const record of this.getOwnedElements<HTMLElement>(DATAVIEW_RECORD)) {
            const matches = record.dataset.objectId === recordId &&
                (record.dataset.dataviewRecordContentTypeId || displayedType) === typeId;
            const fromAction = originOnly && record === sourceRecord;
            if (!matches && !fromAction) continue;
            const url = record.dataset.dataviewItemUrl;
            if (!url) {
                this.refresh(false);
                return;
            }
            targets.set(record, url);
        }
        if (originOnly && !targets.size) {
            this.refresh(false);
            return;
        }
        for (const [record, url] of targets) {
            void htmx.ajax('get', url, {
                source: record,
                target: record,
                swap: 'outerHTML',
                headers: {
                    'X-Bloomerp-Dataview-Item-Index': record.dataset.dataviewItemIndex || '0',
                    'X-Bloomerp-Dataview-Item-Placement': record.dataset.dataviewItemPlacement || '',
                },
            });
        }
    };




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

    /** Refresh list presentation after the selected display preference changes. */
    private bindDisplayOptionsCallback(): void {
        const displayOptionsElement = this.element?.querySelector<HTMLElement>(
            '[bloomerp-component="dataview-display-options"]'
        );
        if (!displayOptionsElement) return;

        if (displayOptionsElement.dataset.viewType && this.element) {
            this.element.dataset.viewType = displayOptionsElement.dataset.viewType;
        }
        if (this.element) {
            this.element.dataset.viewMode = displayOptionsElement.dataset.viewMode ?? 'normal';
            if (this.element.dataset.viewMode !== 'drawer') {
                this.element.querySelector<HTMLElement>('[data-detail-drawer-trigger]')?.classList.add('hidden');
                const drawer = this.element.querySelector<HTMLElement>('[data-dataview-detail-drawer]');
                if (drawer && !drawer.classList.contains('hidden')) (getComponent(drawer) as Drawer)?.close();
                const pane = drawer?.querySelector<HTMLElement>('[data-drawer-detail-pane]');
                if (pane?.firstElementChild) htmx.swap(pane, '', { swapStyle: 'innerHTML', swapDelay: 0, settleDelay: 0 });
            }
        }
        if (displayOptionsElement.dataset.splitViewEnabled && this.element) {
            this.element.dataset.splitViewEnabled = displayOptionsElement.dataset.splitViewEnabled;
            this.splitViewEnabled = displayOptionsElement.dataset.splitViewEnabled === "True";
        }

        const displayOptionsComponent = getComponent(displayOptionsElement) as DataViewDisplayOptions | null;
        if (!displayOptionsComponent) return;

        displayOptionsComponent.setOptionChangedCallback(this.refreshAfterDisplayOptions);
    }

    /** Reload the container when the new layout selects a different controller. */
    private refreshAfterDisplayOptions = (): void => {
        const element = this.element;
        const url = this.getCurrentUrl();
        const nextComponentId = element?.querySelector<HTMLElement>('[data-dataview-component-id]')
            ?.dataset.dataviewComponentId;
        if (element && url && nextComponentId && nextComponentId !== element.getAttribute(componentIdentifier)) {
            void htmx.ajax('get', url.toString(), {
                source: element,
                target: element,
                swap: 'outerHTML',
                push: 'false',
                headers: { 'X-Bloomerp-Sync-Url': String(this.syncUrl) },
            });
            return;
        }

        this.bindDisplayOptionsCallback();
        this.refresh();
    };

    /** Refresh controls after pagination, renderer changes, or an individual record swap. */
    public override onAfterSwap(): void {
        this.setDataviewTarget();
        this.bindDisplayOptionsCallback();
        this.installCellClickOverrides();
        this.syncRecordSelection();
    }

    /**
     * Sets the target element for the data view container. The target is the element where the data view content will be swapped in after an HTMX request. It looks for an element with the attribute `data-dataview-target` within the container's root element. If found, it sets `this.target` to that element; otherwise, it sets it to `null`.
     */
    private setDataviewTarget(): void {
        this.target = this.element?.querySelector<HTMLElement>('#data-view-data-section') ?? null;
    }

    /** Release the old data view when a preference switch replaces its root. */
    private handleCleanup = (event: Event): void => {
        if (event.target === this.element) this.destroy();
    };

    /** Release the list controls and listeners owned by this container. */
    public destroy(): void {
        this.renderedFilters?.destroy();
        this.renderedFilters = undefined;
        this.element?.removeEventListener('bloomerp:filters-apply', this.unifiedFilterHandler);
        this.element?.removeEventListener('htmx:beforeCleanupElement', this.handleCleanup);
        if (this.afterSwapHandler) {
            this.element?.removeEventListener('htmx:afterSwap', this.afterSwapHandler);
        }
        if (this.splitViewPaneShortcutHandler) {
            this.element?.removeEventListener('keydown', this.splitViewPaneShortcutHandler);
        }
        this.element?.removeEventListener('change', this.handleRecordCheckboxChange);
        document.body.removeEventListener('bloomerp:dataview-refresh', this.handleRefreshRequest);
        document.body.removeEventListener('bloomerp:dataview-record-refresh', this.handleRecordRefreshRequest);
    }    
}
