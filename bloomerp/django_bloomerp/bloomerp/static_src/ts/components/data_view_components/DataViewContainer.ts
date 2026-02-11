import htmx from "htmx.org";
import BaseComponent, { getComponent, componentIdentifier } from "../BaseComponent";
import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { getLocalStorageValue, setLocalStorageValue } from "@/utils/localStorage";
import { get } from "http";
import FilterContainer from "../Filters";

export class DataViewContainer extends BaseComponent {
    private target:string = '#data-view-data-section'
    private baseUrl:string|null;
    private fullPath:string|null; // Includes query parameters
    private searchInput:HTMLInputElement|null = null;
    private contentTypeId:string|null = null;
    private splitViewEnabled:boolean = false;
    private appliedFiltersHandler: ((event: Event) => void) | null = null;

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
            if (value === null || value === undefined || value === '') return;

            if (Array.isArray(value)) {
                value.forEach((item) => {
                    if (item === null || item === undefined || item === '') return;
                    if (resetParameters) {
                        baseUrl.searchParams.append(key, String(item));
                    } else {
                        baseUrl.searchParams.append(key, String(item));
                    }
                });
                return;
            }

            if (resetParameters) {
                baseUrl.searchParams.set(key, String(value));
            } else {
                baseUrl.searchParams.append(key, String(value));
            }
        });

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
        if (this.appliedFiltersHandler) {
            this.element?.removeEventListener('click', this.appliedFiltersHandler);
        }
    }
}
