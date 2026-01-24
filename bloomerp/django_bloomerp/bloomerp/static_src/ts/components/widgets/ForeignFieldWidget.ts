import renderDataView from "@/utils/dataview";
import BaseComponent, { getComponent } from "../BaseComponent";
import { Modal } from "../Modal";
import { BaseDataViewCell } from "@/components/data_view_components/BaseDataViewCell";
import htmx from "htmx.org";

export default class ForeignFieldWidget extends BaseComponent {
    private input: HTMLInputElement | null = null;
    private dropdown: HTMLElement | null = null;
    private resultsList: HTMLUListElement | null = null;
    private selectedContainer: HTMLElement | null = null;
    private debounceTimer: number | null = null;
    private isM2M: boolean = false;
    private contentTypeId: string | null = null;
    private fieldName: string | null = null;
    private outsideClickHandler: (e: MouseEvent) => void;
    private boundOnInput: any = null;
    private boundOnResultClick: any = null;
    private boundCreateClick: any = null;
    private boundAdvancedClick: any = null;
    private boundOnKeyDown: any = null;
    private currentIndex: number = -1;
    private boundOnFocus: any = null;


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

        if (!this.input || !this.resultsList || !this.selectedContainer || !this.fieldName || !this.contentTypeId) {
            return;
        }

        this.boundOnInput = this.onInput.bind(this);
        this.boundOnResultClick = this.onResultClick.bind(this);
        this.boundOnFocus = this.onFocus.bind(this);
        this.boundOnKeyDown = this.onKeyDown.bind(this);
        this.input.addEventListener('input', this.boundOnInput);
        this.input.addEventListener('focus', this.boundOnFocus);
        this.input.addEventListener('keydown', this.boundOnKeyDown);
        this.resultsList.addEventListener('click', this.boundOnResultClick);

        // wire create / advanced controls inside dropdown (if present)
        this.createControlEl = this.element.querySelector('.foreign-field-dropdown [data-action="create-new"]') as HTMLElement | null;
        this.advancedControlEl = this.element.querySelector('.foreign-field-dropdown [data-action="advanced-query"]') as HTMLElement | null;

        // Add event listeners for create and advanced controls
        if (this.createControlEl) {
            this.boundCreateClick = (e: Event) => this.handleCreateClick(e);
            this.createControlEl.addEventListener('click', (e) => this.handleCreateClick(e));
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
        document.removeEventListener('click', this.outsideClickHandler);
        if (this.debounceTimer) window.clearTimeout(this.debounceTimer);
    }

    private onFocus(e: Event) {
        if (!this.input) return;
        const q = this.input.value.trim();
        // Fetch initial results (empty query will return first 10)
        this.fetchResults(q);
    }

    // Click handlers
    private handleCreateClick(e: Event) {
        e.preventDefault();
        // 1. Open the modal
        let modal = getComponent(document.querySelector('#create-object-modal')) as Modal;

        htmx.ajax('get', `/components/create-object/${this.contentTypeId}/`, {
            target: modal.getBodyElement(),
            swap: 'innerHTML',
        }).then(() => {
            modal.open();
        });

        // 2. Listen for object created event
        
    
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
                        if (objectId) {
                            this.selectObject(String(objectId), String(label || objectId));
                            modal.close();
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

    private renderResults(objects: Array<{id:number, string_representation:string}>) {
        if (!this.resultsList || !this.dropdown) return;
        this.resultsList.innerHTML = '';
        if (!objects.length) {
            const li = document.createElement('li');
            li.textContent = 'No results';
            li.className = 'px-3 py-2 text-sm text-gray-500';
            this.resultsList.appendChild(li);
            this.showDropdown();
            return;
        }

        for (const obj of objects) {
            const li = document.createElement('li');
            li.dataset.id = String(obj.id);
            li.dataset.label = obj.string_representation;
            li.className = 'px-3 py-2 hover:bg-gray-100 cursor-pointer text-sm';
            li.textContent = obj.string_representation;
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
        this.selectObject(id, label);
    }

    private selectObject(id: string, label: string) {
        if (!this.fieldName || !this.selectedContainer) return;

        if (this.isM2M) {
            // prevent duplicates
            if (this.selectedContainer.querySelector(`[data-id="${id}"]`)) {
                this.input && (this.input.value = '');
                this.hideDropdown();
                return;
            }
            const badge = this.createBadge(id, label);
            this.selectedContainer.appendChild(badge);

            // create hidden input for this value
            const hidden = document.createElement('input');
            hidden.type = 'hidden';
            hidden.name = this.fieldName;
            hidden.value = id;
            hidden.dataset.generated = 'true';
            this.element.appendChild(hidden);
            if (this.input) this.input.value = '';
        } else {
            // single value: remove previous generated hidden inputs
            const prev = this.element.querySelectorAll(`input[type=hidden][name="${this.fieldName}"]`);
            prev.forEach((n) => n.remove());
            this.selectedContainer.innerHTML = '';
            const badge = this.createBadge(id, label);
            this.selectedContainer.appendChild(badge);
            const hidden = document.createElement('input');
            hidden.type = 'hidden';
            hidden.name = this.fieldName;
            hidden.value = id;
            hidden.dataset.generated = 'true';
            this.element.appendChild(hidden);
            if (this.input) this.input.value = label;
        }

        this.hideDropdown();
    }

    private createBadge(id: string, label: string): HTMLElement {
        const span = document.createElement('span');
        span.className = 'foreign-field-badge bg-primary text-sm text-white px-3 py-1 rounded-full cursor-pointer inline-block mr-2 mt-2';
        span.dataset.id = id;
        span.setAttribute('role', 'button');
        span.textContent = label + ' ×';
        span.addEventListener('click', (ev) => {
            ev.preventDefault();
            this.removeSelection(id);
        });
        return span;
    }

    private removeSelection(id: string) {
        if (!this.fieldName) return;
        // remove badge
        const badge = this.selectedContainer && this.selectedContainer.querySelector(`[data-id="${id}"]`);
        if (badge && badge.parentElement) badge.parentElement.removeChild(badge);
        // remove hidden input(s)
        const inputs = Array.from(this.element.querySelectorAll(`input[type=hidden][name="${this.fieldName}"]`)) as HTMLInputElement[];
        for (const inp of inputs) {
            if (inp.value === id) inp.remove();
        }
        // if single select, clear visible input
        if (!this.isM2M && this.input) this.input.value = '';
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

    

}