import renderDataView from "@/utils/dataview";
import { getComponent } from "../BaseComponent";
import { Modal } from "../Modal";
import { BaseDataViewCell } from "@/components/data_view_components/BaseDataViewCell";
import htmx from "htmx.org";
import { attachObjectPreviewTooltip, hideObjectPreviewTooltip } from "@/utils/objectPreviewTooltip";
import { BaseWidget, type BaseWidgetSerializableState } from "./BaseWidget";

type ForeignFieldWidgetSerializableState = BaseWidgetSerializableState & {
    inputValue: string;
    selections: Array<{ id: string; label: string; url: string }>;
};

export default class ForeignFieldWidget extends BaseWidget {
    private readonly maxVisibleSelections = 4;
    private readonly createSuccessEventName = 'bloomerp:foreign-field-object-created';
    private input: HTMLInputElement | null = null;
    private dropdown: HTMLElement | null = null;
    private resultsList: HTMLUListElement | null = null;
    private selectedContainer: HTMLElement | null = null;
    private debounceTimer: number | null = null;
    private isM2M: boolean = false;
    private contentTypeId: string | null = null;
    private fieldName: string | null = null;
    private isDisabled: boolean = false;
    private outsideClickHandler: (e: MouseEvent) => void;
    private boundOnInput: any = null;
    private boundOnResultClick: any = null;
    private boundCreateClick: any = null;
    private boundAdvancedClick: any = null;
    private boundOnKeyDown: any = null;
    private currentIndex: number = -1;
    private boundOnFocus: any = null;
    private boundOnFocusOut: any = null;
    private previewCleanupFns: Array<() => void> = [];
    private widgetInstanceId: string = '';
    private createSuccessHandler: ((event: Event) => void) | null = null;

    private createControlEl: HTMLElement | null = null;
    private advancedControlEl: HTMLElement | null = null;
    

    public initialize(): void {
        this.outsideClickHandler = this.handleOutsideClick.bind(this);

        this.input = this.element.querySelector('input[type="text"]') as HTMLInputElement;
        this.dropdown = this.element.querySelector('.foreign-field-dropdown') as HTMLElement;
        this.resultsList = this.element.querySelector('.foreign-field-results') as HTMLUListElement;
        this.selectedContainer = this.element.querySelector('.foreign-field-selected') as HTMLElement;

        this.isM2M = this.element.dataset.isM2m === 'true';
        this.contentTypeId = this.element.dataset.contentTypeId || null;
        this.fieldName = this.element.dataset.fieldName || null;
        this.isDisabled = this.element.dataset.disabled === 'true';
        this.widgetInstanceId = this.ensureWidgetInstanceId();

        if (!this.input || !this.resultsList || !this.selectedContainer || !this.fieldName || !this.contentTypeId) {
            return;
        }

        this.applyInitialSelections();

        this.boundOnInput = this.onInput.bind(this);
        this.boundOnResultClick = this.onResultClick.bind(this);
        this.boundOnFocus = this.onFocus.bind(this);
        this.boundOnFocusOut = this.onFocusOut.bind(this);
        this.boundOnKeyDown = this.onKeyDown.bind(this);
        this.input.addEventListener('input', this.boundOnInput);
        this.input.addEventListener('focus', this.boundOnFocus);
        this.input.addEventListener('keydown', this.boundOnKeyDown);
        this.element.addEventListener('focusout', this.boundOnFocusOut);
        this.resultsList.addEventListener('click', this.boundOnResultClick);

        // wire create / advanced controls inside dropdown (if present)
        this.createControlEl = this.element.querySelector('.foreign-field-dropdown [data-action="create-new"]') as HTMLElement | null;
        this.advancedControlEl = this.element.querySelector('.foreign-field-dropdown [data-action="advanced-query"]') as HTMLElement | null;

        // Add event listeners for create and advanced controls
        if (this.createControlEl) {
            this.boundCreateClick = (e: Event) => this.handleCreateClick(e);
            this.createControlEl.addEventListener('click', this.boundCreateClick);
        }
        if (this.advancedControlEl) {
            this.boundAdvancedClick = (e: Event) => this.handleAdvancedClick(e);
            this.advancedControlEl.addEventListener('click', this.boundAdvancedClick);
        }
        document.addEventListener('click', this.outsideClickHandler);
    }

    public destroy(): void {
        if (this.input && this.boundOnInput) this.input.removeEventListener('input', this.boundOnInput);
        if (this.input && this.boundOnFocus) this.input.removeEventListener('focus', this.boundOnFocus);
        if (this.input && this.boundOnKeyDown) this.input.removeEventListener('keydown', this.boundOnKeyDown);
        if (this.resultsList && this.boundOnResultClick) this.resultsList.removeEventListener('click', this.boundOnResultClick);
        if (this.createControlEl && this.boundCreateClick) this.createControlEl.removeEventListener('click', this.boundCreateClick);
        if (this.advancedControlEl && this.boundAdvancedClick) this.advancedControlEl.removeEventListener('click', this.boundAdvancedClick);
        if (this.boundOnFocusOut) this.element.removeEventListener('focusout', this.boundOnFocusOut);
        document.removeEventListener('click', this.outsideClickHandler);
        if (this.debounceTimer) window.clearTimeout(this.debounceTimer);
        this.cleanupPreviewHandlers();
        this.teardownCreateSuccessListener();
    }

    private onFocus(e: Event) {
        if (!this.input) return;
        const q = this.input.value.trim();
        // Fetch initial results (empty query will return first 10)
        this.fetchResults(q);
    }

    private onFocusOut(e: FocusEvent): void {
        const nextTarget = e.relatedTarget as HTMLElement | null;
        if (nextTarget && this.element.contains(nextTarget)) return;
        this.hideDropdown();
    }

    private applyInitialSelections(): void {
        const ids = this.parseDataArray(this.element.dataset.selectedIds);
        if (!ids.length) return;

        const labels = this.parseDataArray(this.element.dataset.selectedLabels);
        const urls = this.parseDataArray(this.element.dataset.selectedUrls);
        const labelFallback = (index: number) => labels[index] ?? ids[index] ?? '';
        const urlFallback = (index: number) => urls[index] ?? '';

        if (this.isM2M) {
            ids.forEach((id, index) => {
                if (!id) return;
                this.selectObject(id, labelFallback(index), urlFallback(index), false);
            });
        } else {
            this.selectObject(ids[0], labelFallback(0), urlFallback(0), false);
        }
    }

    private parseDataArray(value?: string): string[] {
        if (!value) return [];
        try {
            const parsed = JSON.parse(value);
            if (Array.isArray(parsed)) {
                return parsed
                    .map((item) => String(item).trim())
                    .filter((item) => item.length > 0);
            }
        } catch {
            // fall back to CSV parsing
        }
        return value
            .split(',')
            .map((item) => item.trim())
            .filter((item) => item.length > 0);
    }

    // Click handlers
    private handleCreateClick(e: Event) {
        e.preventDefault();
        let modal = getComponent(document.querySelector('#create-object-modal')) as Modal;
        if (!modal || !this.contentTypeId) return;

        this.setupCreateSuccessListener(modal);

        htmx.ajax('get', `/components/create-object/${this.contentTypeId}/?foreign_field_widget_id=${encodeURIComponent(this.widgetInstanceId)}`, {
            target: modal.getBodyElement(),
            swap: 'innerHTML',
        }).then(() => {
            modal.open();
        });
    }

    private async handleAdvancedClick(e: Event) {
        e.preventDefault();
        // 1. Get the modal
        let modal = getComponent(document.querySelector('#advanced-query-modal')) as Modal;
        modal.open();

        // 2. Populate the modal with the 
        // 3. Render the data view into the modal body and wait for the container instance
        try {
            const dataViewContainer = await renderDataView(modal.getBodyElement(), Number(this.contentTypeId));

            // 4. Get the actual data view component (table/kanban/calendar) inside the container
            const dataView = dataViewContainer.getDataViewComponent();

            // 5. Install click overrides on each cell so clicking selects the object
            if (dataView) {
                const cells = dataView.getCells();
                for (const cellComp of cells) {
                    (cellComp as BaseDataViewCell).onClickOverride = (cell) => {
                        const objectId = cell.objectId;
                        const label = cell.objectString;
                        const detailUrl = cell.element?.dataset.detailUrl || '';
                        if (objectId) {
                            this.selectObject(String(objectId), String(label || objectId), detailUrl);
                            if (!this.isM2M) {
                                modal.close();
                            }
                        }
                    };
                }
            }

            console.log('DataViewContainer:', dataViewContainer, 'Inner data view:', dataView);
        } catch (err) {
            // handle render/init errors gracefully
            console.error('Error rendering data view:', err);
        }

    }

    private onKeyDown(e: KeyboardEvent) {
        if (!this.dropdown || this.dropdown.classList.contains('hidden')) return;
        const items = this.getSelectableItems();
        if (!items.length) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            this.currentIndex = (this.currentIndex + 1) % items.length;
            this.highlightItem(items, this.currentIndex);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            this.currentIndex = (this.currentIndex - 1 + items.length) % items.length;
            this.highlightItem(items, this.currentIndex);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (this.currentIndex >= 0 && items[this.currentIndex]) {
                // trigger click on the currently highlighted item
                const el = items[this.currentIndex];
                el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
            }
        } else if (e.key === 'Escape') {
            e.preventDefault();
            this.hideDropdown();
        }
    }

    private getSelectableItems(): HTMLElement[] {
        const arr: HTMLElement[] = [];
        if (this.resultsList) {
            const lis = Array.from(this.resultsList.querySelectorAll('li')) as HTMLElement[];
            for (const li of lis) arr.push(li);
        }
        if (this.createControlEl) arr.push(this.createControlEl);
        if (this.advancedControlEl) arr.push(this.advancedControlEl);
        return arr;
    }

    private highlightItem(items: HTMLElement[], index: number) {
        // remove existing highlights
        items.forEach((it) => it.classList.remove('bg-gray-100'));
        const el = items[index];
        if (!el) return;
        el.classList.add('bg-gray-100');
        // ensure visible
        if (typeof (el as any).scrollIntoView === 'function') {
            (el as HTMLElement).scrollIntoView({ block: 'nearest' });
        }
    }

    private handleOutsideClick(e: MouseEvent) {
        if (!this.element.contains(e.target as Node)) {
            this.hideDropdown();
            this.closeOverflowMenus();
            hideObjectPreviewTooltip();
        }
    }

    private onInput(): void {
        if (!this.input) return;
        const q = this.input.value.trim();
        if (this.debounceTimer) window.clearTimeout(this.debounceTimer);
        this.debounceTimer = window.setTimeout(() => {
            if (q.length === 0) {
                this.clearResults();
                return;
            }
            this.fetchResults(q);
        }, 250);
    }

    private async fetchResults(query: string) {
        if (!this.contentTypeId) return;
        const url = `/components/search-objects/${this.contentTypeId}/?fk_search_results_query=${encodeURIComponent(query)}`;
        try {
            const resp = await fetch(url, { credentials: 'same-origin' });
            if (!resp.ok) return;
            const data = await resp.json();
            this.renderResults(data.objects || []);
        } catch (err) {
            // swallow errors silently
            console.error('ForeignFieldWidget fetch error', err);
        }
    }

    private renderResults(objects: Array<{id:number, string_representation:string, detail_url?: string}>) {
        if (!this.resultsList || !this.dropdown) return;
        this.resultsList.innerHTML = '';
        if (!objects.length) {
            const li = document.createElement('li');
            li.textContent = 'No results';
            li.className = 'px-3 py-2 text-sm text-gray-500';
            li.tabIndex = 0;
            this.resultsList.appendChild(li);
            this.showDropdown();
            return;
        }

        for (const obj of objects) {
            const li = document.createElement('li');
            li.dataset.id = String(obj.id);
            li.dataset.label = obj.string_representation;
            li.dataset.url = obj.detail_url || '';
            li.className = 'px-3 py-2 hover:bg-gray-100 cursor-pointer text-sm';
            li.textContent = obj.string_representation;
            li.tabIndex = 0;
            this.resultsList.appendChild(li);
        }
        this.showDropdown();
    }

    private onResultClick(e: Event) {
        const target = e.target as HTMLElement;
        const li = target.closest('li');
        if (!li || !li.dataset.id) return;
        const id = li.dataset.id;
        const label = li.dataset.label || li.textContent || id;
        const url = li.dataset.url || '';
        this.selectObject(id, label, url);
        this.clearResults();
        if (e instanceof MouseEvent && e.detail > 0) {
            this.input?.blur();
        }
    }

    private selectObject(id: string, label: string, url: string = '', emitChange: boolean = true) {
        if (!this.fieldName || !this.selectedContainer) return;

        const previousValue = this.getValue();

        if (this.isM2M) {
            // prevent duplicates
            if (this.getSelectionInputs().some((input) => input.value === id)) {
                this.input && (this.input.value = '');
                this.hideDropdown();
                return;
            }
            const hidden = document.createElement('input');
            hidden.type = 'hidden';
            hidden.name = this.fieldName;
            hidden.value = id;
            hidden.dataset.generated = 'true';
            hidden.dataset.label = label;
            hidden.dataset.url = url;
            hidden.disabled = this.isDisabled;
            this.element.appendChild(hidden);
            if (this.input) this.input.value = '';
        } else {
            // single value: remove previous generated hidden inputs
            this.getSelectionInputs().forEach((input) => input.remove());
            const hidden = document.createElement('input');
            hidden.type = 'hidden';
            hidden.name = this.fieldName;
            hidden.value = id;
            hidden.dataset.generated = 'true';
            hidden.dataset.label = label;
            hidden.dataset.url = url;
            hidden.disabled = this.isDisabled;
            this.element.appendChild(hidden);
            if (this.input) this.input.value = label;
        }

        this.renderSelectedState();
        this.hideDropdown();

        if (emitChange && !this.valuesEqual(previousValue, this.getValue())) {
            this.onChange();
        }
    }


    /**
     * Creates badge element for a selected object with click handler to remove selection
     * @param id the id of the selected object
     * @param label the label of the selected element
     * @returns the badge
     */
    private createBadge(id: string, label: string, url: string = ''): HTMLElement {
        const badge = document.createElement('span');
        badge.className = 'foreign-field-badge inline-flex items-center gap-1 rounded-full bg-primary px-2 py-1 text-xs text-white mr-2';
        badge.dataset.id = id;

        const content = document.createElement(url ? 'a' : 'span');
        content.className = url
            ? 'max-w-56 truncate rounded-full px-1 hover:underline focus:outline-none focus:underline'
            : 'max-w-56 truncate px-1';
        content.textContent = label;
        this.attachPreview(content, id);
        if (url) {
            content.setAttribute('href', url);
        }
        badge.appendChild(content);

        if (this.isDisabled) {
            badge.setAttribute('aria-disabled', 'true');
            badge.classList.add('opacity-60');
        } else {
            const removeButton = document.createElement('button');
            removeButton.type = 'button';
            removeButton.className = 'rounded-full px-1 leading-none hover:bg-white/20 focus:outline-none';
            removeButton.setAttribute('aria-label', `Remove ${label}`);
            removeButton.textContent = '×';
            removeButton.addEventListener('click', (ev) => {
                ev.preventDefault();
                ev.stopPropagation();
                this.removeSelection(id);
            });
            badge.appendChild(removeButton);
        }
        return badge;
    }

    private removeSelection(id: string) {
        if (this.isDisabled) return;
        if (!this.fieldName) return;
        const previousValue = this.getValue();
        // remove hidden input(s)
        const inputs = this.getSelectionInputs();
        for (const inp of inputs) {
            if (inp.value === id) inp.remove();
        }
        // if single select, clear visible input
        if (!this.isM2M && this.input) this.input.value = '';
        this.renderSelectedState();

        if (!this.valuesEqual(previousValue, this.getValue())) {
            this.onChange();
        }
    }

    private getSelectionInputs(): HTMLInputElement[] {
        if (!this.fieldName) return [];
        return Array.from(
            this.element.querySelectorAll(`input[type=hidden][name="${this.fieldName}"][data-generated="true"]`)
        ) as HTMLInputElement[];
    }

    private getSelections(): Array<{ id: string; label: string; url: string }> {
        return this.getSelectionInputs()
            .filter((input) => input.value.trim().length > 0)
            .map((input) => ({
                id: input.value,
                label: input.dataset.label || input.value,
                url: input.dataset.url || '',
            }));
    }

    private renderSelectedState(): void {
        if (!this.selectedContainer) return;

        this.cleanupPreviewHandlers();
        hideObjectPreviewTooltip();
        this.selectedContainer.innerHTML = '';

        const selections = this.getSelections();
        if (!selections.length) {
            return;
        }

        const visibleSelections = selections.slice(0, this.maxVisibleSelections);
        const overflowSelections = selections.slice(this.maxVisibleSelections);

        for (const selection of visibleSelections) {
            this.selectedContainer.appendChild(this.createBadge(selection.id, selection.label, selection.url));
        }

        if (overflowSelections.length) {
            this.selectedContainer.appendChild(this.createOverflowMenu(overflowSelections));
        }
    }

    private createOverflowMenu(selections: Array<{ id: string; label: string; url: string }>): HTMLElement {
        const wrapper = document.createElement('div');
        wrapper.className = 'foreign-field-overflow relative inline-block align-top';

        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'foreign-field-overflow-toggle inline-flex items-center rounded-full border border-gray-300 bg-white px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50';
        toggle.textContent = '...';
        toggle.setAttribute('aria-label', `Show ${selections.length} more selected values`);
        if (this.isDisabled) {
            toggle.disabled = true;
        }

        const menu = document.createElement('div');
        menu.className = 'foreign-field-overflow-menu hidden absolute left-0 top-full z-50 mt-2 min-w-72 rounded-xl border border-gray-200 bg-white p-2 shadow-lg';

        selections.forEach((selection) => {
            menu.appendChild(this.createOverflowItem(selection.id, selection.label, selection.url));
        });

        toggle.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            const isOpen = !menu.classList.contains('hidden');
            this.closeOverflowMenus();
            if (!isOpen) {
                menu.classList.remove('hidden');
            }
        });

        wrapper.appendChild(toggle);
        wrapper.appendChild(menu);
        return wrapper;
    }

    private createOverflowItem(id: string, label: string, url: string): HTMLElement {
        const row = document.createElement('div');
        row.className = 'flex items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm hover:bg-gray-50';

        const labelEl = document.createElement(url ? 'a' : 'span');
        labelEl.className = 'min-w-0 flex-1 truncate text-gray-700';
        labelEl.textContent = label;
        if (url) {
            labelEl.setAttribute('href', url);
            labelEl.classList.add('hover:underline');
            this.attachPreview(labelEl, id);
        }
        row.appendChild(labelEl);

        if (!this.isDisabled) {
            const deleteButton = document.createElement('button');
            deleteButton.type = 'button';
            deleteButton.className = 'shrink-0 rounded-md px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50';
            deleteButton.textContent = 'Delete';
            deleteButton.addEventListener('click', (event) => {
                event.preventDefault();
                event.stopPropagation();
                this.removeSelection(id);
            });
            row.appendChild(deleteButton);
        }

        return row;
    }

    private closeOverflowMenus(): void {
        const menus = this.element.querySelectorAll('.foreign-field-overflow-menu');
        menus.forEach((menu) => menu.classList.add('hidden'));
    }

    private ensureWidgetInstanceId(): string {
        if (this.element.dataset.widgetInstanceId) {
            return this.element.dataset.widgetInstanceId;
        }

        const widgetId = `foreign-field-widget-${Math.random().toString(36).slice(2, 11)}`;
        this.element.dataset.widgetInstanceId = widgetId;
        return widgetId;
    }

    private setupCreateSuccessListener(modal: Modal): void {
        this.teardownCreateSuccessListener();
        this.createSuccessHandler = (event: Event) => {
            const detail = (event as CustomEvent).detail || {};
            if (detail.foreign_field_widget_id !== this.widgetInstanceId) return;
            if (String(detail.content_type_id || '') !== String(this.contentTypeId || '')) return;
            if (!detail.object_id) return;

            this.selectObject(
                String(detail.object_id),
                String(detail.object_label || detail.object_id),
                String(detail.object_detail_url || ''),
            );
            modal.close();
            this.teardownCreateSuccessListener();
        };
        document.body.addEventListener(this.createSuccessEventName, this.createSuccessHandler);
    }

    private teardownCreateSuccessListener(): void {
        if (!this.createSuccessHandler) return;
        document.body.removeEventListener(this.createSuccessEventName, this.createSuccessHandler);
        this.createSuccessHandler = null;
    }

    private attachPreview(element: HTMLElement, objectId: string): void {
        if (!this.contentTypeId) return;
        this.previewCleanupFns.push(
            attachObjectPreviewTooltip({
                element,
                objectId,
                contentTypeId: this.contentTypeId,
            })
        );
    }

    private cleanupPreviewHandlers(): void {
        this.previewCleanupFns.forEach((cleanup) => cleanup());
        this.previewCleanupFns = [];
    }

    public getValue(): string | string[] {
        const values = this.getSelectionInputs().map((input) => input.value);
        return this.isM2M ? values : (values[0] || '');
    }

    public setValue(value: unknown, emitChange: boolean = false): void {
        const previousValue = this.getValue();
        const nextValues = Array.isArray(value)
            ? value.map((item) => String(item))
            : (typeof value === "string" && value ? [value] : []);
        const existingSelections = this.getSelections();

        this.getSelectionInputs().forEach((input) => input.remove());

        if (!this.fieldName) {
            return;
        }

        nextValues.forEach((id) => {
            const existingSelection = existingSelections.find((selection) => selection.id === id);
            const hidden = document.createElement("input");
            hidden.type = "hidden";
            hidden.name = this.fieldName;
            hidden.value = id;
            hidden.dataset.generated = "true";
            hidden.dataset.label = existingSelection?.label || id;
            hidden.dataset.url = existingSelection?.url || "";
            hidden.disabled = this.isDisabled;
            this.element.appendChild(hidden);
        });

        if (this.input) {
            this.input.value = this.isM2M ? "" : (nextValues[0] ? existingSelections.find((selection) => selection.id === nextValues[0])?.label || nextValues[0] : "");
        }

        this.renderSelectedState();
        this.hideDropdown();

        if (emitChange && !this.valuesEqual(previousValue, this.getValue())) {
            this.onChange();
        }
    }

    public override getSerializableState(): ForeignFieldWidgetSerializableState {
        return {
            value: this.getValue(),
            inputValue: this.input?.value || "",
            selections: this.getSelections().map((selection) => ({ ...selection })),
        };
    }

    public override setSerializableState(state: BaseWidgetSerializableState, emitChange: boolean = false): void {
        const previousValue = this.getValue();
        const nextState = state as ForeignFieldWidgetSerializableState;
        const nextSelections = Array.isArray(nextState.selections) ? nextState.selections : [];

        this.getSelectionInputs().forEach((input) => input.remove());

        if (!this.fieldName) {
            return;
        }

        nextSelections.forEach((selection) => {
            const hidden = document.createElement("input");
            hidden.type = "hidden";
            hidden.name = this.fieldName;
            hidden.value = selection.id;
            hidden.dataset.generated = "true";
            hidden.dataset.label = selection.label;
            hidden.dataset.url = selection.url;
            hidden.disabled = this.isDisabled;
            this.element.appendChild(hidden);
        });

        if (this.input) {
            this.input.value = nextState.inputValue || "";
        }

        this.renderSelectedState();
        this.hideDropdown();

        if (emitChange && !this.valuesEqual(previousValue, this.getValue())) {
            this.onChange();
        }
    }

    private clearResults() {
        if (this.resultsList) this.resultsList.innerHTML = '';
        this.hideDropdown();
    }

    private showDropdown() {
        if (this.dropdown) this.dropdown.classList.remove('hidden');
    }

    private hideDropdown() {
        if (this.dropdown) this.dropdown.classList.add('hidden');
    }

    private valuesEqual(left: string | string[], right: string | string[]): boolean {
        if (Array.isArray(left) || Array.isArray(right)) {
            if (!Array.isArray(left) || !Array.isArray(right)) {
                return false;
            }

            if (left.length !== right.length) {
                return false;
            }

            return left.every((value, index) => value === right[index]);
        }

        return left === right;
    }
}
