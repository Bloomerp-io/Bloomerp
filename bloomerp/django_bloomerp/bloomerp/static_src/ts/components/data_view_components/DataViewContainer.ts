import htmx from "htmx.org";
import BaseComponent, { getComponent, componentIdentifier } from "../BaseComponent";
import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { getLocalStorageValue, setLocalStorageValue } from "@/utils/localStorage";

export class DataViewContainer extends BaseComponent {
    private target:string = '#data-view-data-section'
    private baseUrl:string|null;
    private fullPath:string|null; // Includes query parameters
    private searchInput:HTMLInputElement|null = null;
    private contentTypeId:string|null = null;
    private splitViewEnabled:boolean = false;

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
    }

    /**
     * Filter's the current data view
     */
    filter(
        args: Record<string, string | number | boolean | null | undefined> = {},
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
            baseUrl.searchParams.set(key, String(value));
        });

        this.fullPath = baseUrl.toString();

        htmx.ajax('get', this.fullPath, {
            target: this.target,
            swap: 'innerHTML',
        });
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
}
