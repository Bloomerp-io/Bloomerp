import BaseComponent, { getComponent } from "./BaseComponent";
import htmx from "htmx.org";
import { formatFilterLabel, formatFilterTooltip } from "@/utils/filterLabels";

export interface FilterEntryData {
    field: string;
    applicationFieldId: string | null;
    operator: string | null;
    value: string | string[] | null;
    key?: string | null;
}

export class FilterEntry implements FilterEntryData {
    public field: string;
    public applicationFieldId: string | null;
    public operator: string | null;
    public value: string | string[] | null;
    public key: string | null;

    public constructor({ field, applicationFieldId, operator, value, key = null }: FilterEntryData) {
        this.field = field;
        this.applicationFieldId = applicationFieldId;
        this.operator = operator;
        this.value = value;
        this.key = key;
    }

    public static from(entry: FilterEntry | FilterEntryData): FilterEntry {
        return entry instanceof FilterEntry ? entry : new FilterEntry(entry);
    }

    public getFilterKey(): string {
        if (this.key) {
            return this.key;
        }

        if (this.operator) {
            return `${this.field}__${this.operator}`;
        }

        return this.field;
    }

    public stringifyValue(): string {
        if (Array.isArray(this.value)) {
            return this.value.join(", ");
        }

        return String(this.value ?? "");
    }

}

export type FilterBoxRemoveHandler = (filter: FilterEntry, filterBox: FilterBox) => void;

export class FilterBox {
    public filter: FilterEntry;
    private removeHandler: FilterBoxRemoveHandler | null;
    private element: HTMLElement | null = null;

    public constructor(filter: FilterEntry | FilterEntryData, removeHandler: FilterBoxRemoveHandler | null = null) {
        this.filter = FilterEntry.from(filter);
        this.removeHandler = removeHandler;
    }

    public setHandleRemove(removeHandler: FilterBoxRemoveHandler): void {
        this.removeHandler = removeHandler;
    }

    public render(): HTMLElement {
        const filterKey = this.filter.getFilterKey();
        const badge = document.createElement("span");
        badge.className = "badge badge-primary";
        badge.dataset.filterKey = filterKey;
        badge.title = this.filter.key
            ? `${filterKey} = ${this.filter.stringifyValue()}`
            : formatFilterTooltip(this.filter.field, this.filter.operator, this.filter.value);

        const removeButton = document.createElement("button");
        removeButton.type = "button";
        removeButton.className = "badge-remove";
        removeButton.dataset.filterRemove = "true";
        removeButton.setAttribute("aria-label", "Remove filter");
        removeButton.innerHTML = '<i class="fa fa-x"></i>';
        removeButton.addEventListener("click", (event) => this.handleRemove(event));

        const label = document.createElement("span");
        label.textContent = formatFilterLabel(this.filter.field, this.filter.operator, this.filter.value);

        badge.appendChild(removeButton);
        badge.appendChild(label);
        this.element = badge;
        return badge;
    }

    public handleRemove(event?: Event): void {
        event?.preventDefault();
        event?.stopPropagation();
        if (this.removeHandler) {
            this.removeHandler(this.filter, this);
            return;
        }

        this.remove();
    }

    public remove(): void {
        if (this.element) {
            this.element.remove();
            this.element = null;
        }
    }
}

type FilterEntryLike = FilterEntry | FilterEntryData;

export const LOOKUP_LABELS : Map<string, string> = new Map([
    ["exact", "is"],
    ["equals", "is"],
    ["icontains", "contains"],
    ["contains", "contains"],
    ["startswith", "starts with"],
    ["endswith", "ends with"],
    ["gte", "≥"],
    ["lte", "≤"],
    ["gt", ">"],
    ["lt", "<"],
    ["isnull", "is empty"],
    ["in", "in"],
    ["year", "year is"],
    ["month", "month is"],
    ["day", "day is"],
    ["week", "week is"],
    ["today", "is today"],
    ["yesterday", "was yesterday"],
    ["this_week", "is in this week"],
    ["last_week", "is in last week"],
    ["this_month", "is in this month"],
    ["last_month", "is in last month"],
    ["this_quarter", "is in this quarter"],
    ["last_quarter", "is in last quarter"],
    ["this_year", "is in this year"],
    ["last_year", "is in last year"],
])

const RESERVED_FILTER_KEYS = new Set([
    "q",
    "page",
    "calendar_page",
    "sort",
    "direction",
    "_component_id",
]);

export default class FilterContainer extends BaseComponent {
    private static readonly MAX_ADVANCED_RELATION_DEPTH = 2;
    private contentTypeId: string;
    private fieldChangeHandler: ((event: Event) => void) | null = null;
    private lookupChangeHandler: ((event: Event) => void) | null = null;
    private htmxSwapHandler: ((event: Event) => void) | null = null;
    private advancedChangeHandler: ((event: Event) => void) | null = null;

    // Get filter results element
    private filterResultsElement:HTMLElement=null;

    public initialize(): void {
        
        // Get content_type_id from data attribute
        this.contentTypeId = this.element.getAttribute('data-content-type-id') || '';

        if (!this.contentTypeId) {
            console.warn('FilterContainer: content_type_id not found');
            return;
        }

        // Setup field selector change handler
        this.fieldChangeHandler = (event: Event) => this.onFieldSelected(event);
        const fieldSelector = this.getFieldSelectorInput();
        if (fieldSelector) {
            fieldSelector.addEventListener('change', this.fieldChangeHandler);
        }

        // If lookup operators are already rendered (pre-selected field case), attach listener
        if (this.getLookupOperatorInput()) {
            this.attachLookupOperatorListener();
        }

        // Listen for HTMX afterSwap events to re-attach listeners
        this.htmxSwapHandler = () => this.onAfterSwap();
        this.element.addEventListener('htmx:afterSwap', this.htmxSwapHandler);

        
        this.filterResultsElement = document.querySelector(this.element.dataset.filterResultElement)
    }

    /**
     * Handles field selector change - loads lookup operators
     */
    private onFieldSelected(event: Event): void {
        const select = event.target as HTMLSelectElement;
        const applicationFieldId = select.value;

        this.clearValueInput();

        if (!applicationFieldId) {
            // Clear lookup and value sections if no field selected
            this.clearLookupOperators();
            return;
        }

        // Load lookup operators via HTMX AJAX
        const url = this.buildLookupOperatorsUrl(applicationFieldId);
        const lookupSection = this.getLookupOperatorSection();
        if (!lookupSection) {
            return;
        }

        htmx.ajax('get', url, {
            target: lookupSection,
            swap: 'innerHTML',
        });


    }

    /**
     * Attaches change listener to the newly loaded lookup operator select
     */
    private attachLookupOperatorListener(): void {
        const lookupSelect = this.getLookupOperatorInput() as HTMLSelectElement | null;

        if (lookupSelect && this.lookupChangeHandler) {
            // Remove old listener if it exists
            lookupSelect.removeEventListener('change', this.lookupChangeHandler);
        }

        // Create and attach new listener
        this.lookupChangeHandler = (event: Event) => this.onLookupOperatorSelected(event);
        if (lookupSelect) {
            lookupSelect.addEventListener('change', this.lookupChangeHandler);
        }
    }

    /**
     * Called after HTMX swap to attach listeners to newly loaded elements
     */
    public onAfterSwap(): void {
        // Check if lookup operators were just swapped in
        const lookupInput = this.getLookupOperatorInput() as HTMLSelectElement | null;
        if (lookupInput) {
            this.attachLookupOperatorListener();
            if (!lookupInput.value) {
                this.clearValueInput();
            }
        }

        this.attachAdvancedLookupListener();
    }

    /**
     * Handles lookup operator selection - loads value input
     */
    private onLookupOperatorSelected(event: Event): void {
        const select = event.target as HTMLSelectElement;
        const lookupValue = select.value;

        // Get application field ID from select (dynamic case) or hidden input (pre-selected case)
        let applicationFieldId: string | undefined;
        const fieldSelector = this.getFieldSelectorInput() as HTMLSelectElement | null;

        if (fieldSelector) {
            applicationFieldId = fieldSelector.value;
        } else {
            // In pre-selected field case, get from hidden input
            const hiddenInput = this.element.querySelector('#field-selector-section input.selected-field-id') as HTMLInputElement | null;
            applicationFieldId = hiddenInput?.value;
        }

        if (!applicationFieldId || !lookupValue) {
            this.clearValueInput();
            return;
        }

        void this.loadValueInput(applicationFieldId, lookupValue);
    }

    /**
     * Clears lookup operators section
     */
    private clearLookupOperators(): void {
        const section = this.element.querySelector('#lookup-operator-section');
        if (section) {
            section.innerHTML = '';
        }
    }

    /**
     * Clears value input section
     */
    private clearValueInput(): void {
        const section = this.element.querySelector('#value-input-section');
        if (section) {
            section.innerHTML = '';
        }
    }

    /**
     * Removes a filter row
     */
    public addRow(): void {

    }

    public removeRow(): void {

    }

    public async setFilter(filter: FilterEntryLike): Promise<void> {
        const filterEntry = FilterEntry.from(filter);
        const operatorSelect = this.getLookupOperatorInput() as HTMLSelectElement | null;
        if (!operatorSelect || !filterEntry.applicationFieldId || !filterEntry.operator) {
            return;
        }

        if (filterEntry.field.includes("__")) {
            const restoredAdvancedFilter = await this.setAdvancedFilter(filterEntry, operatorSelect);
            if (restoredAdvancedFilter) {
                return;
            }
        }

        const matchingOption = Array.from(operatorSelect.options).find((option) => {
            return option.value === filterEntry.operator
                || option.getAttribute('data-lookup-django') === filterEntry.operator;
        });

        if (!matchingOption) {
            return;
        }

        operatorSelect.value = matchingOption.value;
        await this.loadValueInput(filterEntry.applicationFieldId, matchingOption.value, filterEntry.value);
        this.setValueInput(filterEntry.value);
    }

    private async setAdvancedFilter(filter: FilterEntryLike, operatorSelect: HTMLSelectElement): Promise<boolean> {
        const filterEntry = FilterEntry.from(filter);
        if (!filterEntry.applicationFieldId) {
            return false;
        }

        const advancedOption = Array.from(operatorSelect.options).find((option) => option.value === "foreign_advanced");
        if (!advancedOption) {
            return false;
        }

        const pathParts = filterEntry.field.split("__").filter((part) => part !== "");
        if (pathParts.length < 2) {
            return false;
        }

        operatorSelect.value = advancedOption.value;
        await this.loadValueInput(filterEntry.applicationFieldId, advancedOption.value);

        const valueSection = this.getValueInputSection();
        const builder = valueSection?.querySelector<HTMLElement>("[data-advanced-builder]");
        if (!builder) {
            return false;
        }

        let currentBuilder = builder;
        let pathPrefix = currentBuilder.getAttribute("data-base-field") || pathParts[0];
        const baseParts = pathPrefix.split("__").filter((part) => part !== "");
        const remainingPathParts = pathParts.slice(baseParts.length);
        let terminalOperatorSelect: HTMLSelectElement | null = null;

        for (const fieldName of remainingPathParts) {
            const relatedSelect = this.findAdvancedRelatedSelect(currentBuilder, pathPrefix);
            if (!relatedSelect) {
                return false;
            }

            const matchingFieldOption = Array.from(relatedSelect.options).find((option) => {
                return option.getAttribute("data-field-name") === fieldName;
            });
            if (!matchingFieldOption) {
                return false;
            }

            relatedSelect.value = matchingFieldOption.value;
            await this.onAdvancedRelatedFieldSelected(relatedSelect);
            const currentPath = `${pathPrefix}__${fieldName}`;

            if (currentPath === filterEntry.field) {
                terminalOperatorSelect = this.findAdvancedOperatorSelect(currentBuilder, currentPath);
                break;
            }

            const nextRelatedSelect = this.findAdvancedRelatedSelect(currentBuilder, currentPath);
            if (nextRelatedSelect) {
                pathPrefix = currentPath;
                continue;
            }

            const nestedAdvancedOperatorSelect = this.findAdvancedOperatorSelect(currentBuilder, currentPath);
            if (!nestedAdvancedOperatorSelect) {
                return false;
            }

            const nestedAdvancedOption = Array.from(nestedAdvancedOperatorSelect.options).find((option) => {
                return option.value === "foreign_advanced";
            });
            if (!nestedAdvancedOption) {
                return false;
            }

            nestedAdvancedOperatorSelect.value = nestedAdvancedOption.value;
            await this.onAdvancedOperatorSelected(nestedAdvancedOperatorSelect);

            const nestedBuilder = this.findNestedAdvancedBuilder(currentBuilder, currentPath);
            if (!nestedBuilder) {
                return false;
            }

            currentBuilder = nestedBuilder;
            pathPrefix = currentPath;
        }

        const advancedOperatorSelect = terminalOperatorSelect || this.findAdvancedOperatorSelect(currentBuilder, filterEntry.field);
        if (!advancedOperatorSelect) {
            return false;
        }

        const matchingOperatorOption = Array.from(advancedOperatorSelect.options).find((option) => {
            return option.value === filterEntry.operator
                || option.getAttribute("data-lookup-django") === filterEntry.operator;
        });
        if (!matchingOperatorOption) {
            return false;
        }

        advancedOperatorSelect.value = matchingOperatorOption.value;
        await this.onAdvancedOperatorSelected(advancedOperatorSelect);
        this.setValueInput(filterEntry.value);
        return true;
    }

    private findAdvancedOperatorSelect(builder: HTMLElement, fieldPath: string): HTMLSelectElement | null {
        const selects = Array.from(builder.querySelectorAll<HTMLSelectElement>("select[data-advanced-operator-select]"));
        return selects.find((select) => select.getAttribute("data-field") === fieldPath) || null;
    }

    private findNestedAdvancedBuilder(builder: HTMLElement, basePath: string): HTMLElement | null {
        const builders = Array.from(builder.querySelectorAll<HTMLElement>("[data-advanced-builder]"));
        return builders.find((nestedBuilder) => {
            return nestedBuilder !== builder && nestedBuilder.getAttribute("data-base-field") === basePath;
        }) || null;
    }

    private findAdvancedRelatedSelect(builder: HTMLElement, pathPrefix: string): HTMLSelectElement | null {
        const selects = Array.from(builder.querySelectorAll<HTMLSelectElement>("select[data-advanced-related-select]"));
        return selects.find((select) => select.getAttribute("data-path-prefix") === pathPrefix) || null;
    }

    /**
     * Returns the filters as a list of FilterEntry objects.
     */
    public getFilters(): FilterEntry[] {
        const filters: FilterEntry[] = [];

        const valueSection = this.getValueInputSection();
        if (!valueSection) {
            return filters;
        }

        const fields = valueSection.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
            'input[name], select[name], textarea[name]'
        );

        fields.forEach((field) => {
            const name = field.getAttribute('name');
            if (!name) {
                return;
            }

            // Determine value
            let value: string | string[] | null = null;

            if (field instanceof HTMLInputElement) {
                if (field.type === 'checkbox' || field.type === 'radio') {
                    if (!field.checked) {
                        return;
                    }
                    value = field.value;
                } else {
                    if (field.value === '') {
                        return;
                    }
                    value = field.value;
                }
            } else if (field instanceof HTMLSelectElement) {
                if (field.multiple) {
                    const selectedValues = Array.from(field.selectedOptions).map((option) => option.value);
                    if (selectedValues.length === 0) {
                        return;
                    }
                    value = selectedValues;
                } else {
                    if (field.value === '') {
                        return;
                    }
                    value = field.value;
                }
            } else {
                if ((field as HTMLTextAreaElement).value === '') {
                    return;
                }
                value = (field as HTMLTextAreaElement).value;
            }

            // Find corresponding operator for this field
            const operatorSelect = this.findOperatorForField(field);
            let operator: string | null = null;
            if (operatorSelect) {
                const selectedOption = operatorSelect.selectedOptions[0];
                const djangoLookup = selectedOption?.getAttribute('data-lookup-django') || '';
                operator = djangoLookup || operatorSelect.value;
            }

            // Find applicationFieldId for this filter row
            const applicationFieldId = this.findApplicationFieldIdForField(field);

            filters.push(new FilterEntry({ field: name, applicationFieldId, operator, value }));
        });

        if (filters.length === 0) {
            const widgetFilter = this.getCustomWidgetFilter(valueSection);
            if (widgetFilter) {
                filters.push(widgetFilter);
            }
        }

        return filters;
    }


    private getCustomWidgetFilter(valueSection: HTMLElement): FilterEntry | null {
        const widgetElement = valueSection.querySelector<HTMLElement>("[bloomerp-component='foreign-field-widget']");
        if (!widgetElement) {
            return null;
        }

        const fieldName = widgetElement.dataset.fieldName || "";
        if (!fieldName) {
            return null;
        }

        const widget = getComponent(widgetElement) as { getValue?: () => unknown } | null;
        const rawValue = widget?.getValue ? widget.getValue() : widgetElement.dataset.value || null;
        const value = Array.isArray(rawValue)
            ? rawValue.map((item) => String(item)).filter((item) => item !== "")
            : rawValue === null || rawValue === undefined || String(rawValue) === ""
                ? null
                : String(rawValue);

        if (value === null || (Array.isArray(value) && value.length === 0)) {
            return null;
        }

        const operatorSelect = this.findOperatorForField(widgetElement);
        const selectedOption = operatorSelect?.selectedOptions[0];
        const djangoLookup = selectedOption?.getAttribute('data-lookup-django') || '';
        const operator = operatorSelect ? (djangoLookup || operatorSelect.value) : null;
        const applicationFieldId = this.findApplicationFieldIdForField(widgetElement);

        return new FilterEntry({
            field: fieldName,
            applicationFieldId,
            operator,
            value,
        });
    }


    /**
     * Try to find the lookup/operator select associated with a given field element.
     * Strategy:
     *  - Look for a select in the lookup operator section with data-field matching the field name
     *  - If not found, return the single operator select if only one exists
     *  - Otherwise return the first operator select as a best-effort fallback
     */
    private findOperatorForField(field: Element): HTMLSelectElement | null {
        const name = field.getAttribute('name') || '';

        // Prefer a select tagged with data-field equal to the input's name
        if (name) {
            const escaped = typeof (CSS as any)?.escape === 'function' ? (CSS as any).escape(name) : name;
            const selector = `select[data-field="${escaped}"]`;
            const byData = this.element.querySelector(selector) as HTMLSelectElement | null;
            if (byData) {
                return byData;
            }
        }

        // If there's only one operator select, return it
        const operatorSelects = Array.from(this.element.querySelectorAll<HTMLSelectElement>('#lookup-operator-section select'));
        if (operatorSelects.length === 1) {
            return operatorSelects[0];
        }

        // Best effort: try to find the closest select in the component's root
        const nearest = (field as HTMLElement).closest ? (field as HTMLElement).closest('div,section,form') : null;
        if (nearest) {
            const localSelect = nearest.querySelector('#lookup-operator-section select') as HTMLSelectElement | null;
            if (localSelect) {
                return localSelect;
            }
        }

        // Fallback to first operator select
        return operatorSelects[0] || null;
    }

    /**
     * Attempt to find the application field id for the given field element.
     */
    private findApplicationFieldIdForField(field: Element): string | null {
        // Try operator select first
        const operatorSelect = this.findOperatorForField(field);
        if (operatorSelect) {
            const attrKeys = ['data-application-field-id', 'data-application_field_id', 'data-field', 'data-application-field'];
            for (const k of attrKeys) {
                const v = operatorSelect.getAttribute(k);
                if (v) {
                    return v;
                }
            }

            // also check dataset
            const ds = (operatorSelect as any).dataset || {};
            if (ds.applicationFieldId) return ds.applicationFieldId;
            if (ds.application_field_id) return ds.application_field_id;
            if (ds.field) return ds.field;
        }

        // Hidden selected-field-id input (pre-selected field case)
        const hiddenInput = this.element.querySelector('#field-selector-section input.selected-field-id') as HTMLInputElement | null;
        if (hiddenInput && hiddenInput.value) {
            return hiddenInput.value;
        }

        // Global field selector (dynamic case)
        const fieldSelector = this.getFieldSelectorInput() as HTMLSelectElement | null;
        if (fieldSelector && fieldSelector.value) {
            return fieldSelector.value;
        }

        return null;
    }

    /**
     * Cleanup on component destruction
     */
    public destroy(): void {
        const fieldSelector = this.getFieldSelectorInput();
        if (fieldSelector && this.fieldChangeHandler) {
            fieldSelector.removeEventListener('change', this.fieldChangeHandler);
        }

        const lookupSelect = this.getLookupOperatorInput();
        if (lookupSelect && this.lookupChangeHandler) {
            lookupSelect.removeEventListener('change', this.lookupChangeHandler);
        }

        if (this.htmxSwapHandler) {
            this.element.removeEventListener('htmx:afterSwap', this.htmxSwapHandler);
        }

        if (this.advancedChangeHandler) {
            const valueSection = this.getValueInputSection();
            if (valueSection) {
                valueSection.removeEventListener('change', this.advancedChangeHandler);
            }
        }
    }

    private getFieldSelectorInput(): HTMLElement | null {
        return this.element.querySelector("#field-selector-section select");
    }

    private getLookupOperatorInput(): HTMLElement | null {
        return this.element.querySelector("#lookup-operator-section select");
    }

    private getLookupOperatorSection(): HTMLElement | null {
        return this.element.querySelector("#lookup-operator-section");
    }

    private getValueInputSection(): HTMLElement | null {
        return this.element.querySelector("#value-input-section");
    }

    private attachAdvancedLookupListener(): void {
        const valueSection = this.getValueInputSection();
        if (!valueSection) return;

        if (this.advancedChangeHandler) {
            valueSection.removeEventListener('change', this.advancedChangeHandler);
        }

        this.advancedChangeHandler = (event: Event) => {
            const target = event.target as HTMLElement | null;
            if (!target) return;

            if (target.matches('select[data-advanced-related-select]')) {
                void this.onAdvancedRelatedFieldSelected(target as HTMLSelectElement);
            } else if (target.matches('select[data-advanced-operator-select]')) {
                void this.onAdvancedOperatorSelected(target as HTMLSelectElement);
            }
        };

        valueSection.addEventListener('change', this.advancedChangeHandler);
    }

    private async onAdvancedRelatedFieldSelected(select: HTMLSelectElement): Promise<void> {
        const builder = select.closest('[data-advanced-builder]') as HTMLElement | null;
        if (!builder) return;

        const selectedOption = select.selectedOptions[0];
        if (!selectedOption) return;

        const fieldName = selectedOption.getAttribute('data-field-name') || '';
        const relatedContentTypeId = selectedOption.getAttribute('data-related-content-type-id') || '';
        const applicationFieldId = select.value;

        if (!fieldName) {
            return;
        }

        const level = parseInt(select.getAttribute('data-level') || '1', 10);
        const pathPrefix = select.getAttribute('data-path-prefix') || builder.getAttribute('data-base-field') || '';
        const currentPath = pathPrefix ? `${pathPrefix}__${fieldName}` : fieldName;

        // Clear deeper selects and operator/value sections
        const selectsContainer = builder.querySelector('[data-advanced-selects]') as HTMLElement | null;
        if (selectsContainer) {
            const deeper = selectsContainer.querySelectorAll('[data-advanced-level]');
            deeper.forEach((node) => {
                const nodeLevel = parseInt((node as HTMLElement).getAttribute('data-advanced-level') || '0', 10);
                if (nodeLevel > level) {
                    node.remove();
                }
            });
        }

        const operatorSection = builder.querySelector('[data-advanced-operator]') as HTMLElement | null;
        const valueSection = builder.querySelector('[data-advanced-value]') as HTMLElement | null;
        if (operatorSection) operatorSection.innerHTML = '';
        if (valueSection) valueSection.innerHTML = '';

        this.updateAdvancedPathLabel(builder);

        if (relatedContentTypeId && level < FilterContainer.MAX_ADVANCED_RELATION_DEPTH) {
            const nextLevel = level + 1;
            const url = this.buildRelatedFieldsUrl(relatedContentTypeId, nextLevel, currentPath);
            const selectsTarget = builder.querySelector('[data-advanced-selects]') as HTMLElement | null;
            if (selectsTarget) {
                await htmx.ajax('get', url, {
                    target: selectsTarget,
                    swap: 'beforeend',
                });
            }
            return;
        }

        if (!applicationFieldId) {
            return;
        }

        // Load lookup operators for the terminal field
        const baseFieldId = builder.getAttribute('data-base-field-id') || '';
        const url = this.buildLookupOperatorsUrl(
            applicationFieldId,
            new URLSearchParams({
                field_path: currentPath,
                base_application_field_id: baseFieldId,
            }),
        );
        if (operatorSection) {
            await htmx.ajax('get', url, {
                target: operatorSection,
                swap: 'innerHTML',
            });
        }
    }

    private async onAdvancedOperatorSelected(select: HTMLSelectElement): Promise<void> {
        const builder = select.closest('[data-advanced-builder]') as HTMLElement | null;
        if (!builder) return;

        const lookupValue = select.value;
        const fieldPath = select.getAttribute('data-field') || select.getAttribute('data-field-path') || '';
        const baseApplicationFieldId = select.getAttribute('data-application-field-id') || '';
        const applicationFieldId =
            select.getAttribute('data-lookup-application-field-id')
            || baseApplicationFieldId
            || '';

        if (!lookupValue || !fieldPath || !applicationFieldId) {
            return;
        }

        const valueSection = builder.querySelector('[data-advanced-value]') as HTMLElement | null;
        if (!valueSection) return;

        const params = new URLSearchParams({
            lookup_value: lookupValue,
            field_path: fieldPath,
        });
        if (baseApplicationFieldId) {
            params.set('base_application_field_id', baseApplicationFieldId);
        }

        const url = this.buildValueInputUrl(applicationFieldId, params);
        await htmx.ajax('get', url, {
            target: valueSection,
            swap: 'innerHTML',
        });
    }

    private updateAdvancedPathLabel(builder: HTMLElement): void {
        const baseLabel = builder.getAttribute('data-base-label') || '';
        const selects = Array.from(builder.querySelectorAll<HTMLSelectElement>('select[data-advanced-related-select]'));
        const labels = [baseLabel];
        selects.forEach((select) => {
            const option = select.selectedOptions[0];
            if (option && option.value) {
                labels.push(option.textContent?.trim() || '');
            }
        });
        const pathEl = builder.querySelector('[data-advanced-path]') as HTMLElement | null;
        if (pathEl) {
            pathEl.textContent = labels.filter(Boolean).join(' \u2192 ');
        }
    }

    private async loadValueInput(
        applicationFieldId: string,
        lookupValue: string,
        currentValue: string | string[] | null = null,
    ): Promise<void> {
        const params = new URLSearchParams({ lookup_value: lookupValue });
        if (currentValue !== null) {
            const value = Array.isArray(currentValue) ? currentValue[0] : currentValue;
            if (value !== undefined && value !== null && String(value) !== '') {
                params.set('current_value', String(value));
            }
        }
        const url = this.buildValueInputUrl(applicationFieldId, params);
        const valueSection = this.getValueInputSection();
        if (!valueSection) {
            return;
        }

        await htmx.ajax('get', url, {
            target: valueSection,
            swap: 'innerHTML',
        });
    }

    private setValueInput(value: string | string[] | null): void {
        const valueSection = this.getValueInputSection();
        if (!valueSection || value === null) {
            return;
        }

        const customWidget = valueSection.querySelector<HTMLElement>("[bloomerp-component='foreign-field-widget']");
        if (customWidget) {
            const widget = getComponent(customWidget) as { setValue?: (value: unknown) => void } | null;
            widget?.setValue?.(value);
        }

        const fields = Array.from(
            valueSection.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
                'input[name], select[name], textarea[name]'
            )
        );

        if (fields.length === 0) {
            return;
        }

        const values = Array.isArray(value) ? value.map(String) : [String(value)];

        fields.forEach((field) => {
            if (field instanceof HTMLInputElement) {
                if (field.type === 'checkbox' || field.type === 'radio') {
                    field.checked = values.includes(field.value);
                    return;
                }

                field.value = values[0] || '';
                return;
            }

            if (field instanceof HTMLSelectElement) {
                if (field.multiple) {
                    Array.from(field.options).forEach((option) => {
                        option.selected = values.includes(option.value);
                    });
                    return;
                }

                field.value = values[0] || '';
                return;
            }

            field.value = values[0] || '';
        });
    }

    // TODO: Technical debt
    private buildLookupOperatorsUrl(applicationFieldId: string, params: URLSearchParams | null = null): string {
        const queryParams = params ?? new URLSearchParams({ application_field_id: applicationFieldId });
        const scope = this.element.getAttribute('data-filter-scope') || 'application-field';

        if (scope === 'workspace') {
            return `/components/workspaces/${this.contentTypeId}/filters/lookup-operators/${encodeURIComponent(applicationFieldId)}/?${queryParams.toString()}`;
        }

        return `/components/filters/${this.contentTypeId}/lookup-operators/${applicationFieldId}/?${queryParams.toString()}`;
    }

    private buildValueInputUrl(applicationFieldId: string, params: URLSearchParams): string {
        const scope = this.element.getAttribute('data-filter-scope') || 'application-field';

        if (scope === 'workspace') {
            return `/components/workspaces/${this.contentTypeId}/filters/value-input/${encodeURIComponent(applicationFieldId)}/?${params.toString()}`;
        }

        return `/components/filters/${this.contentTypeId}/value-input/${applicationFieldId}/?${params.toString()}`;
    }

    private buildRelatedFieldsUrl(contentTypeId: string, level: number, pathPrefix: string): string {
        return `/components/filters/${contentTypeId}/related-fields/?level=${level}&path_prefix=${encodeURIComponent(pathPrefix)}`;
    }

}

/**
 * Function that parses the filters from the
 * @returns list of filter entries
 */
export function getFiltersFromUrl(params = new URLSearchParams(window.location.search)) : FilterEntry[] {
    const filters: FilterEntry[] = [];
    const processedKeys = new Set<string>();

    params.forEach((_value, key) => {
        if (processedKeys.has(key)) {
            return;
        }
        processedKeys.add(key);
        if (RESERVED_FILTER_KEYS.has(key) || key.startsWith("_arg_")) {
            return;
        }

        const keyParts = key.split("__").filter((part) => part !== "");
        if (keyParts.length === 0) {
            return;
        }

        const finalPart = keyParts[keyParts.length - 1];
        const hasExplicitOperator = keyParts.length > 1 && LOOKUP_LABELS.has(finalPart);
        const operator = hasExplicitOperator ? finalPart : "exact";
        if (!LOOKUP_LABELS.has(operator)) {
            return;
        }

        const values = params.getAll(key).filter((value) => value !== "");
        if (values.length === 0) {
            return;
        }

        filters.push(new FilterEntry({
            field: (hasExplicitOperator ? keyParts.slice(0, -1) : keyParts).join("__"),
            applicationFieldId: null,
            operator,
            value: values.length === 1 ? values[0] : values,
            key,
        }));
    });

    return filters;
}
