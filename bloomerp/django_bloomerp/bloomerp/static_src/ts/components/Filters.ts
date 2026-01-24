import BaseComponent from "./BaseComponent";
import htmx from "htmx.org";

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
        const lookupSelect = this.getLookupOperatorInput();
        
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
        const fieldSelector = this.getFieldSelectorInput() as HTMLSelectElement;
        
        if (fieldSelector) {
            applicationFieldId = fieldSelector.value;
        } else {
            // In pre-selected field case, get from hidden input
            const hiddenInput = document.querySelector('#field-selector-section input.selected-field-id') as HTMLInputElement;
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
     * Returns the filters as a mapping.
     */
    public getFilters(): Map<string, any> {
        const filters = new Map<string, any>();

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

            if (field instanceof HTMLInputElement) {
                if (field.type === 'checkbox') {
                    if (field.checked) {
                        filters.set(name, field.value);
                    }
                    return;
                }

                if (field.type === 'radio') {
                    if (field.checked) {
                        filters.set(name, field.value);
                    }
                    return;
                }

                if (field.value !== '') {
                    filters.set(name, field.value);
                }
                return;
            }

            if (field instanceof HTMLSelectElement) {
                if (field.multiple) {
                    const selectedValues = Array.from(field.selectedOptions).map((option) => option.value);
                    if (selectedValues.length > 0) {
                        filters.set(name, selectedValues);
                    }
                    return;
                }

                if (field.value !== '') {
                    filters.set(name, field.value);
                }
                return;
            }

            if (field.value !== '') {
                filters.set(name, field.value);
            }
        });

        return filters;
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