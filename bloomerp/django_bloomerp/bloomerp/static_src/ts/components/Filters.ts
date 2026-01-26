import BaseComponent from "./BaseComponent";
import htmx from "htmx.org";

// Types for filter entries returned by getFilters()
interface FilterEntry {
    field: string;
    applicationFieldId: string;
    operator: string | null;
    value: string | string[] | null;
}

export default class FilterContainer extends BaseComponent {
    private contentTypeId: string;
    private fieldChangeHandler: ((event: Event) => void) | null = null;
    private lookupChangeHandler: ((event: Event) => void) | null = null;
    private htmxSwapHandler: ((event: Event) => void) | null = null;

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
    }

    /**
     * Handles field selector change - loads lookup operators
     */
    private onFieldSelected(event: Event): void {
        const select = event.target as HTMLSelectElement;
        const applicationFieldId = select.value;

        if (!applicationFieldId) {
            // Clear lookup and value sections if no field selected
            this.clearLookupOperators();
            this.clearValueInput();
            return;
        }

        // Load lookup operators via HTMX AJAX
        const url = `/components/filters/${this.contentTypeId}/lookup-operators/${applicationFieldId}/?application_field_id=${applicationFieldId}`;

        htmx.ajax('get', url, {
            target: '#lookup-operator-section',
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
        if (this.getLookupOperatorInput()) {
            this.attachLookupOperatorListener();
        }
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
            const hiddenInput = document.querySelector('#field-selector-section input.selected-field-id') as HTMLInputElement | null;
            applicationFieldId = hiddenInput?.value;
        }

        if (!applicationFieldId || !lookupValue) {
            this.clearValueInput();
            return;
        }

        // Load value input via HTMX AJAX
        const url = `/components/filters/${this.contentTypeId}/value-input/${applicationFieldId}/?lookup_value=${encodeURIComponent(lookupValue)}`;

        htmx.ajax('get', url, {
            target: '#value-input-section',
            swap: 'innerHTML',
        });
    }

    /**
     * Clears lookup operators section
     */
    private clearLookupOperators(): void {
        const section = document.getElementById('lookup-operator-section');
        if (section) {
            section.innerHTML = '';
        }
    }

    /**
     * Clears value input section
     */
    private clearValueInput(): void {
        const section = document.getElementById('value-input-section');
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
            const operator = operatorSelect ? operatorSelect.value : null;

            // Find applicationFieldId for this filter row
            const applicationFieldId = this.findApplicationFieldIdForField(field) || '';

            filters.push({ field: name, applicationFieldId, operator, value });
        });

        return filters;
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
            const selector = `#lookup-operator-section select[data-field="${escaped}"]`;
            const byData = document.querySelector(selector) as HTMLSelectElement | null;
            if (byData) {
                return byData;
            }
        }

        // If there's only one operator select, return it
        const operatorSelects = Array.from(document.querySelectorAll<HTMLSelectElement>('#lookup-operator-section select'));
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
        const hiddenInput = document.querySelector('#field-selector-section input.selected-field-id') as HTMLInputElement | null;
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
    }

    private getFieldSelectorInput(): HTMLElement | null {
        return document.getElementById("field-selector-section")?.querySelector("select") || null;
    }

    private getLookupOperatorInput(): HTMLElement | null {
        return document.getElementById("lookup-operator-section")?.querySelector("select") || null;
    }

    private getValueInputSection(): HTMLElement | null {
        return document.getElementById("value-input-section") || null;
    }
}