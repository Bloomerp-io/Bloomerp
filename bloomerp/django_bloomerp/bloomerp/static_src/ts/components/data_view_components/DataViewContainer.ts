import htmx from "htmx.org";
import BaseComponent, { getComponent, componentIdentifier } from "../BaseComponent";
import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";
import { getLocalStorageValue, setLocalStorageValue } from "@/utils/localStorage";
import FilterContainer from "../Filters";

export class DataViewContainer extends BaseComponent {
    private target:string = '#data-view-data-section'
    private baseUrl:string|null;
    private fullPath:string|null; // Includes query parameters
    private searchInput:HTMLInputElement|null = null;
    private contentTypeId:string|null = null;
    private splitViewEnabled:boolean = false;
    private syncUrl:boolean = false;
    private appliedFiltersHandler: ((event: Event) => void) | null = null;
    private afterSwapHandler: ((event: Event) => void) | null = null;
    private addButtonHandler: ((event: MouseEvent) => void) | null = null;

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
                
                console.log('Applying filters with args:', args);

                // Merge new filters with existing query params
                this.filter(args, false);
                this.resetFilterSection();
            });
        }

        // Handle applied filters clicks (remove / clear all)
        this.appliedFiltersHandler = (event: Event) => this.handleAppliedFiltersClick(event);
        this.element?.addEventListener('click', this.appliedFiltersHandler);

        this.addButtonHandler = (event: MouseEvent) => this.handleAddButtonClick(event);
        this.getAddButton()?.addEventListener('click', this.addButtonHandler, true);

        this.afterSwapHandler = (event: Event) => this.handleAfterSwap(event);
        this.element?.addEventListener('htmx:afterSwap', this.afterSwapHandler);

        this.installCellClickOverrides();
    }

    /**
     * Filter's the current data view
     */
    filter(
        args: Record<string, string | string[] | number | boolean | null | undefined> = {},
        resetParameters: boolean = false
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

        console.log('Target', this.target, 'Loading data view with URL:', this.fullPath);

        htmx.ajax('get', this.fullPath, {
            target: this.target,
            swap: 'innerHTML',
        });
    }

    private handleAppliedFiltersClick(event: Event): void {
        const target = event.target as HTMLElement | null;
        if (!target) return;

        const clearBtn = target.closest('[data-clear-filters]');
        if (clearBtn) {
            this.clearAllFilters();
            return;
        }

        const removeBtn = target.closest('[data-filter-remove]');
        if (!removeBtn) return;

        const badge = removeBtn.closest('[data-filter-key]') as HTMLElement | null;
        const key = badge?.getAttribute('data-filter-key') || '';
        if (!key) return;

        this.removeFilter(key);
    }

    private removeFilter(key: string): void {
        const url = this.getCurrentUrl();
        if (!url) return;

        url.searchParams.delete(key);
        url.searchParams.delete('page');
        this.applyUrl(url);
    }

    private clearAllFilters(): void {
        const url = this.getCurrentUrl();
        if (!url) return;

        Array.from(url.searchParams.keys()).forEach((key) => {
            if (DataViewContainer.RESERVED_FILTER_KEYS.has(key)) return;
            url.searchParams.delete(key);
        });
        url.searchParams.delete('page');

        this.applyUrl(url);
    }

    private applyUrl(url: URL): void {
        this.fullPath = url.toString();
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
            this.syncBrowserUrl(new URL(this.fullPath, window.location.origin));
        }

        this.installCellClickOverrides();
    }

    private handleAddButtonClick(event: MouseEvent): void {
        if (this.onAdd(event) === false) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
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

    private getAddButton(): HTMLElement | null {
        return this.element?.querySelector<HTMLElement>('[data-dataview-add-button]') ?? null;
    }

    private syncBrowserUrl(dataViewUrl: URL): void {
        const browserUrl = new URL(window.location.href);
        browserUrl.search = dataViewUrl.search;
        window.history.replaceState(window.history.state, '', `${browserUrl.pathname}${browserUrl.search}${browserUrl.hash}`);
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

    public destroy(): void {
        const addButton = this.getAddButton();
        if (addButton && this.addButtonHandler) {
            addButton.removeEventListener('click', this.addButtonHandler, true);
        }
        if (this.appliedFiltersHandler) {
            this.element?.removeEventListener('click', this.appliedFiltersHandler);
        }
        if (this.afterSwapHandler) {
            this.element?.removeEventListener('htmx:afterSwap', this.afterSwapHandler);
        }
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

    /**
     * Retrieves the list of filter keys from the applied filter section.
     * 
     * A filter key is stored in the `data-filter-key` attribute of the badge element. This method collects all badges and extracts their keys to return as a list.
     * 
     * @returns list of filter keys
     */
    public getFilterKeys(): string[] {
        const badges = this.element?.querySelectorAll<HTMLElement>('[data-filter-key]') ?? [];
        const keys: string[] = [];
        badges.forEach(badge => {
            const key = badge.getAttribute('data-filter-key');
            if (key) keys.push(key);
        });
        return keys;
    }

    
}
