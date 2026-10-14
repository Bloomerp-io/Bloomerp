import htmx from "htmx.org";
import { Drawer } from "../Drawer";
import BaseComponent, { getComponent, componentIdentifier, initComponents } from "../BaseComponent";
import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";
import { DataViewDisplayOptions } from "./DisplayOptions";
import ObjectCRUDViewContainer from "../detail_view_components/ObjectCRUDViewContainer";
import { getModal } from "@/utils/modals";
import { insertSkeleton } from "@/utils/animations";
import { RenderedFilters } from '../filters/RenderedFilters';
import showMessage from '@/utils/messages';
import { MessageType } from '../UiMessage';

interface DataViewCreatedDetail {
    data_view_create_id: string;
    messages?: { text: string; type: MessageType }[];
}


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
    private bulkCheckboxChangeHandler: ((event: Event) => void) | null = null;
    private bulkAllClickHandler: ((event: Event) => void) | null = null;
    private bulkSelectionClickHandler: ((event: Event) => void) | null = null;
    private bulkActionCompleteHandler: ((event: Event) => void) | null = null;
    private addButtonClickHandler: ((event: MouseEvent) => void) | null = null;
    private selectedObjectIds: Set<string> = new Set();
    private createRequestId: string | null = null;
    private createModalId: string | null = null;
    private createFormUrl: string | null = null;

    /** Show save feedback immediately, close the owning dialog, and refresh its list. */
    private handleObjectCreated = (event: Event): void => {
        const detail = (event as CustomEvent<DataViewCreatedDetail>).detail;
        if (!this.createRequestId || detail?.data_view_create_id !== this.createRequestId) return;
        this.createRequestId = null;
        if (this.createModalId) getModal(this.createModalId)?.close();
        for (const message of detail.messages ?? []) {
            showMessage(message.text, message.type, 10);
        }
        this.refresh();
    };

    /** Bind data-view controls without stealing focus when loaded inside a workspace tile. */
    public initialize(): void {
        this.element?.addEventListener('bloomerp:filters-apply', this.unifiedFilterHandler);
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

        if (!this.element?.closest(`[${componentIdentifier}="workspace-tile"]`)) {
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

        this.setupAddButton();

        document.body.addEventListener('bloomerp:data-view-object-created', this.handleObjectCreated);

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

        const listPane = this.splitViewEnabled ? this.getSplitViewListPane() : null;
        const loadingTarget = listPane?.querySelector<HTMLElement>("[data-resizable-div-panel]") ?? listPane ?? this.target;
        insertSkeleton(loadingTarget);
        this.applyUrl(baseUrl, pushHistory);
    }

    /**
     * Refreshes the current data view, keeping the existing query parameters intact.
     */
    public refresh(): void {
        const url = this.getCurrentUrl();
        if (!url) return;

        this.applyUrl(url, false);
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
    private applyUrl(url: URL, pushHistory: boolean = true): void {
        this.fullPath = url.toString();
        if (this.element) this.element.dataset.url = this.fullPath;
        const historyUpdate = this.getHistoryUpdate(url, pushHistory);
        htmx.ajax('get', this.fullPath, {
            target: this.target,
            swap: 'innerHTML',
            ...historyUpdate,
        });
    }

    private getHistoryUpdate(url: URL, pushHistory: boolean): Pick<HtmxAjaxOptions, "push" | "replace"> {
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

    private handleAfterSwap(event: Event): void {
        if (!(event instanceof CustomEvent)) return;

        const target = event.detail?.target as HTMLElement | null | undefined;
        if (!target || target.id !== 'data-view-data-section') return;

        const responseUrl = event.detail?.xhr?.responseURL;
        if (!responseUrl) return;

        this.fullPath = new URL(responseUrl, window.location.origin).toString();
        if (this.element) this.element.dataset.url = this.fullPath;

        this.installCellClickOverrides();
        this.setupSplitViewFocusTargets();
        this.syncBulkCheckboxes();
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

    private setupAddButton(): void {
        const addButton = this.element?.querySelector<HTMLElement>('[data-dataview-create-button="true"]');
        if (!addButton) return;

        if (this.addButtonClickHandler) {
            addButton.removeEventListener('click', this.addButtonClickHandler);
        }

        this.addButtonClickHandler = (event: MouseEvent) => this.handleAddButtonClick(event);
        addButton.addEventListener('click', this.addButtonClickHandler);
    }

    /** Reuse this list's unfinished form or load a fresh form after successful creation. */
    private handleAddButtonClick(event: MouseEvent): void {
        event.preventDefault();

        if (this.onAdd(event)) return;

        const addButton = event.currentTarget as HTMLElement | null;
        const modalId = addButton?.dataset.modalId;
        const createUrl = addButton?.dataset.createUrl;
        const targetSelector = addButton?.dataset.target;
        const target = targetSelector ? document.querySelector<HTMLElement>(targetSelector) : null;
        const modal = modalId ? getModal(modalId) : null;

        if (addButton) modal?.setOpener(addButton);
        modal?.open();

        if (!createUrl || !target) return;

        const existingRequestId = target.querySelector<HTMLInputElement>('[name="data_view_create_id"]')?.value;
        if (this.createRequestId && existingRequestId === this.createRequestId && this.createFormUrl === createUrl) return;

        this.createRequestId = crypto.randomUUID();
        this.createModalId = modalId ?? null;
        this.createFormUrl = createUrl;
        const requestUrl = new URL(createUrl, window.location.origin);
        requestUrl.searchParams.set('data_view_create_id', this.createRequestId);

        insertSkeleton(target);

        void htmx.ajax('get', requestUrl.toString(), {
            target,
            swap: 'innerHTML',
        }).catch((error) => {
            console.error('Failed to load create object modal:', error);
        });
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
        const url = new URL(`/components/dataview/${this.contentTypeId}/bulk_actions/`, window.location.origin);
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

        displayOptionsComponent.setOptionChangedCallback(() => {
            this.bindDisplayOptionsCallback();
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
    }

    public onAfterSwap(): void {
        this.setDataviewTarget();
        this.setupAddButton();
        this.bindDisplayOptionsCallback();
    }

    /**
     * Sets the target element for the data view container. The target is the element where the data view content will be swapped in after an HTMX request. It looks for an element with the attribute `data-dataview-target` within the container's root element. If found, it sets `this.target` to that element; otherwise, it sets it to `null`.
     */
    private setDataviewTarget(): void {
        this.target = this.element?.querySelector<HTMLElement>('#data-view-data-section') ?? null;
    }

    /** Release the list controls and listeners owned by this container. */
    public destroy(): void {
        document.body.removeEventListener('bloomerp:data-view-object-created', this.handleObjectCreated);
        this.createRequestId = null;
        this.renderedFilters?.destroy();
        this.renderedFilters = undefined;
        this.element?.removeEventListener('bloomerp:filters-apply', this.unifiedFilterHandler);
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
        const addButton = this.element?.querySelector<HTMLElement>('[data-dataview-create-button="true"]');
        if (addButton && this.addButtonClickHandler) {
            addButton.removeEventListener('click', this.addButtonClickHandler);
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
