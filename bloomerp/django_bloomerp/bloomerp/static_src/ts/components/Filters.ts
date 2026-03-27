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
    private static readonly MAX_ADVANCED_RELATION_DEPTH = 2;
    private contentTypeId: string;
    private fieldChangeHandler: ((event: Event) => void) | null = null;
    private lookupChangeHandler: ((event: Event) => void) | null = null;
    private htmxSwapHandler: ((event: Event) => void) | null = null;
    private advancedChangeHandler: ((event: Event) => void) | null = null;

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

        this.clearValueInput();

        if (!applicationFieldId) {
            // Clear lookup and value sections if no field selected
            this.clearLookupOperators();
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
            const hiddenInput = document.querySelector('#field-selector-section input.selected-field-id') as HTMLInputElement | null;
            applicationFieldId = hiddenInput?.value;
        }

        if (!applicationFieldId || !lookupValue) {
            this.clearValueInput();
            return;
        }

        if (lookupValue === 'foreign_advanced') {
            const url = `/components/filters/${this.contentTypeId}/value-input/${applicationFieldId}/?lookup_value=${encodeURIComponent(lookupValue)}`;
            htmx.ajax('get', url, {
                target: '#value-input-section',
                swap: 'innerHTML',
            });
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
            const selector = `select[data-field="${escaped}"]`;
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
                this.onAdvancedRelatedFieldSelected(target as HTMLSelectElement);
            } else if (target.matches('select[data-advanced-operator-select]')) {
                this.onAdvancedOperatorSelected(target as HTMLSelectElement);
            }
        };

        valueSection.addEventListener('change', this.advancedChangeHandler);
    }

    private onAdvancedRelatedFieldSelected(select: HTMLSelectElement): void {
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
            const url = `/components/filters/${relatedContentTypeId}/related-fields/?level=${nextLevel}&path_prefix=${encodeURIComponent(currentPath)}`;
            const selectsTarget = builder.querySelector('[data-advanced-selects]') as HTMLElement | null;
            if (selectsTarget) {
                htmx.ajax('get', url, {
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
        const url = `/components/filters/${this.contentTypeId}/lookup-operators/${applicationFieldId}/?field_path=${encodeURIComponent(currentPath)}&base_application_field_id=${encodeURIComponent(baseFieldId)}`;
        if (operatorSection) {
            htmx.ajax('get', url, {
                target: operatorSection,
                swap: 'innerHTML',
            });
        }
    }

    private onAdvancedOperatorSelected(select: HTMLSelectElement): void {
        const builder = select.closest('[data-advanced-builder]') as HTMLElement | null;
        if (!builder) return;

        const lookupValue = select.value;
        const fieldPath = select.getAttribute('data-field') || select.getAttribute('data-field-path') || '';
        const applicationFieldId =
            select.getAttribute('data-lookup-application-field-id')
            || select.getAttribute('data-application-field-id')
            || '';

        if (!lookupValue || !fieldPath || !applicationFieldId) {
            return;
        }

        const valueSection = builder.querySelector('[data-advanced-value]') as HTMLElement | null;
        if (!valueSection) return;

        const url = `/components/filters/${this.contentTypeId}/value-input/${applicationFieldId}/?lookup_value=${encodeURIComponent(lookupValue)}&field_path=${encodeURIComponent(fieldPath)}`;
        htmx.ajax('get', url, {
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

}
