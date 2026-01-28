import BaseComponent, { getComponent } from "./BaseComponent";
import FilterContainer from "./Filters";
import PermissionCheckboxes from "./inputs/PermissionCheckboxes";
import { Modal } from "./Modal";
import htmx from "htmx.org";
import { getCsrfToken } from "../utils/cookies";

interface FieldData {
    id: string;
    name: string;
}

enum PermissionScope {
    GLOBAL = 'global',
    ROW = 'row',
    FIELD = 'column',
}

export class PermissionsTable extends BaseComponent {
    private draggableFields: NodeListOf<HTMLElement> | null = null;
    private rowDropZones: NodeListOf<HTMLElement> | null = null;
    private columnDropZones: NodeListOf<HTMLElement> | null = null;
    private currentDraggedField: FieldData | null = null;
    private draggedElement: HTMLElement | null = null;
    private currentDroppedField: FieldData | null = null;
    private currentDroppedApplicationFieldId: string | null = null;
    private contentTypeId: string;
    private addRowPolicyBtn: HTMLElement | null = null;

    private rowPolicyFilter: FilterContainer | null = null;

    // Inputs
    private rowPolicyNameInput: HTMLInputElement | null = null;
    private fieldPolicyNameInput: HTMLInputElement | null = null;
    private policyNameInput: HTMLInputElement | null = null;
    private policyDescriptionInput: HTMLTextAreaElement | null = null;

    // Permission checkboxes
    private globalPermissionComp : PermissionCheckboxes;
    private rowPermissionComp : PermissionCheckboxes;
    private fieldPermissionComp : PermissionCheckboxes;

    // Modals
    private rowPolicyModal: Modal | null = null;
    private fieldPolicyModal: Modal | null = null;

    // Save button
    private saveBtn: HTMLElement | null = null;

    // Event handlers
    private fieldRemovedHandler: ((event: Event) => void) | null = null;

    // State 
    private rowPolicyRules: Array<{ rule: Record<string, any>; permissions: string[] }> = [];
    private fieldPolicies: Record<string, string[]> = {};

    public initialize(): void {
        if (!this.element) return;
        
        // Extract content type ID from data attribute
        this.contentTypeId = this.element.dataset.contentTypeId || '';

        this.setupDraggableFields();
        this.setupDropZones();

        // Add Row Policy Button
        this.addRowPolicyBtn = this.element.querySelector('#add-row-policy-btn');
        this.addRowPolicyBtn.addEventListener('click', ()=>{
            this.addRowPolicy()
        })

        // Add Field Policy Button
        const addFieldPolicyBtn = this.element.querySelector('#add-field-policy-btn');
        addFieldPolicyBtn?.addEventListener('click', ()=>{
            this.addFieldPolicy()
        })

        // Initialize PermissionCheckboxes components
        this.globalPermissionComp = getComponent(document.getElementById(`global-permissions-${this.contentTypeId}`)) as PermissionCheckboxes;
        this.rowPermissionComp = getComponent(document.getElementById(`row-policy-permissions-${this.contentTypeId}`)) as PermissionCheckboxes;
        this.fieldPermissionComp = getComponent(document.getElementById(`field-policy-permissions-${this.contentTypeId}`)) as PermissionCheckboxes;

        // Initialize Modals
        this.rowPolicyModal = getComponent(document.getElementById('row-policy-modal')) as Modal;
        this.fieldPolicyModal = getComponent(document.getElementById('field-policy-modal')) as Modal;

        // Save button
        this.saveBtn = this.element.querySelector('#save-policy-btn');
        if (this.saveBtn) {
            this.saveBtn.addEventListener('click', () => {
                this.save();
            });
        }

        // Handle field removals to keep state in sync
        this.fieldRemovedHandler = (event: Event) => this.handleFieldRemoved(event as CustomEvent);
        this.element.addEventListener('permissions-field-removed', this.fieldRemovedHandler);

        // Inputs
        this.rowPolicyNameInput = this.element.querySelector('#row-policy-name-input') as HTMLInputElement;
        this.fieldPolicyNameInput = this.element.querySelector('#field-policy-name-input') as HTMLInputElement;
        this.policyNameInput = this.element.querySelector('#policy-name-input') as HTMLInputElement;
        this.policyDescriptionInput = this.element.querySelector('#policy-description-input') as HTMLTextAreaElement;
    }

    /*
    --------------------------------
    Drag and Drop Functionality
    --------------------------------
    */
    private setupDraggableFields(): void {
        if (!this.element) return;

        this.draggableFields = this.element.querySelectorAll('[data-field-draggable]');
        
        this.draggableFields.forEach((field) => {
            field.addEventListener('dragstart', this.handleDragStart.bind(this));
            field.addEventListener('dragend', this.handleDragEnd.bind(this));
        });
    }

    private setupDropZones(): void {
        if (!this.element) return;

        // Setup row drop zones (left side / row policy)
        this.rowDropZones = this.element.querySelectorAll('[data-drop-zone="row"]');
        this.rowDropZones.forEach((zone) => {
            this.setupDropZone(zone);
        });

        // Setup column drop zones (top / field policy)
        this.columnDropZones = this.element.querySelectorAll('[data-drop-zone="column"]');
        this.columnDropZones.forEach((zone) => {
            this.setupDropZone(zone);
        });
    }

    private setupDropZone(zone: HTMLElement): void {
        zone.addEventListener('dragover', this.handleDragOver.bind(this));
        zone.addEventListener('dragleave', this.handleDragLeave.bind(this));
        zone.addEventListener('drop', this.handleDrop.bind(this));
    }

    private handleDragStart(event: DragEvent): void {
        const target = event.currentTarget as HTMLElement;
        this.draggedElement = target;

        // Extract field data
        this.currentDraggedField = {
            id: target.dataset.fieldId || '',
            name: target.dataset.fieldName || target.textContent?.trim() || ''
        };

        // Set drag data
        if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('application/json', JSON.stringify(this.currentDraggedField));
        }

        // Add visual feedback
        target.classList.add('opacity-50');

        // Highlight all drop zones
        this.highlightAllDropZones(true);
    }

    private handleDragEnd(event: DragEvent): void {
        const target = event.currentTarget as HTMLElement;
        
        // Remove visual feedback
        target.classList.remove('opacity-50');

        // Remove highlight from all drop zones
        this.highlightAllDropZones(false);

        this.currentDraggedField = null;
        this.draggedElement = null;
    }

    private handleDragOver(event: DragEvent): void {
        event.preventDefault();
        
        const target = event.currentTarget as HTMLElement;
        
        if (event.dataTransfer) {
            event.dataTransfer.dropEffect = 'move';
        }

        // Add highlight class
        target.classList.add('drop-zone-active');
    }

    private handleDragLeave(event: DragEvent): void {
        const target = event.currentTarget as HTMLElement;
        
        // Only remove highlight if we're actually leaving the drop zone
        // (not just moving to a child element)
        const relatedTarget = event.relatedTarget as HTMLElement;
        if (!target.contains(relatedTarget)) {
            target.classList.remove('drop-zone-active');
        }
    }

    private handleDrop(event: DragEvent): void {
        event.preventDefault();
        event.stopPropagation();

        const target = event.currentTarget as HTMLElement;
        target.classList.remove('drop-zone-active');

        if (!this.currentDraggedField) return;

        // Determine drop zone type and index
        const dropZoneType = target.dataset.dropZone as 'row' | 'column';
        const dropZoneIndex = parseInt(target.dataset.dropIndex || '0', 10);

        // Dispatch custom event with drop data
        const dropEvent = new CustomEvent('permissions-field-dropped', {
            detail: {
                field: this.currentDraggedField,
                dropZoneType: dropZoneType,
                dropZoneIndex: dropZoneIndex,
                dropZoneElement: target
            },
            bubbles: true
        });

        this.element?.dispatchEvent(dropEvent);

        // Store the dropped field so addRowPolicy/addFieldPolicy can access it later
        this.currentDroppedField = this.currentDraggedField;
        this.currentDroppedApplicationFieldId = this.currentDraggedField?.id || null;

        // Visual feedback: clone the field into the drop zone
        this.addFieldToDropZone(target, this.currentDraggedField, dropZoneType);

        if (dropZoneType === 'row') {
            const modal = getComponent(document.getElementById('row-policy-modal')) as Modal;
            modal?.open();

            const fieldId = this.currentDraggedField.id;
            htmx.ajax(
                'get',
                `/components/filters/${this.contentTypeId}/init/?application_field_id=${fieldId}`,
                {
                    target: '#permissions-modal-filter-target',
                    swap: 'innerHTML'
                }
            ).then(() => {
                this.rowPolicyFilter = getComponent(document.getElementById(`filter-container-${this.contentTypeId}`)) as FilterContainer;
            });
        }

        if (dropZoneType === 'column') {
            const modal = getComponent(document.getElementById('field-policy-modal')) as Modal;
            modal?.open();
        }
    }

    private highlightAllDropZones(highlight: boolean): void {
        const allDropZones = this.element?.querySelectorAll('[data-drop-zone]');
        
        allDropZones?.forEach((zone) => {
            if (highlight) {
                zone.classList.add('drop-zone-available');
            } else {
                zone.classList.remove('drop-zone-available', 'drop-zone-active');
            }
        });
    }

    private addFieldToDropZone(dropZone: HTMLElement, field: FieldData, type: 'row' | 'column'): void {
        // Check if field is already in this drop zone
        const existing = dropZone.querySelector(`[data-field-id="${field.id}"]`);
        if (existing) {
            // Flash animation to show it's already there
            existing.classList.add('animate-pulse');
            setTimeout(() => existing.classList.remove('animate-pulse'), 500);
            return;
        }

        // Create field badge
        const badge = document.createElement('span');
        badge.className = 'inline-flex items-center gap-1 px-2 py-1 text-xs bg-primary-100 text-primary-900 rounded-md border border-primary-200';
        badge.dataset.fieldId = field.id;
        badge.textContent = field.name;

        // Add remove button
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'ml-1 hover:text-red-600 transition-colors';
        removeBtn.innerHTML = '×';
        removeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            badge.remove();
            
            // Dispatch remove event
            const removeEvent = new CustomEvent('permissions-field-removed', {
                detail: {
                    field: field,
                    dropZoneType: type,
                    dropZoneElement: dropZone
                },
                bubbles: true
            });
            this.element?.dispatchEvent(removeEvent);
        });

        badge.appendChild(removeBtn);
        dropZone.appendChild(badge);

        // Entrance animation
        badge.classList.add('scale-0');
        requestAnimationFrame(() => {
            badge.classList.remove('scale-0');
            badge.classList.add('transition-transform', 'duration-200');
        });
    }

    public destroy(): void {
        // Clean up event listeners
        this.draggableFields?.forEach((field) => {
            field.removeEventListener('dragstart', this.handleDragStart.bind(this));
            field.removeEventListener('dragend', this.handleDragEnd.bind(this));
        });

        const allDropZones = this.element?.querySelectorAll('[data-drop-zone]');
        allDropZones?.forEach((zone) => {
            zone.removeEventListener('dragover', this.handleDragOver.bind(this));
            zone.removeEventListener('dragleave', this.handleDragLeave.bind(this));
            zone.removeEventListener('drop', this.handleDrop.bind(this));
        });

        if (this.fieldRemovedHandler && this.element) {
            this.element.removeEventListener('permissions-field-removed', this.fieldRemovedHandler);
        }
    }

    private handleFieldRemoved(event: CustomEvent): void {
        const detail = event.detail || {};
        const dropZoneType = detail.dropZoneType as 'row' | 'column' | undefined;
        const fieldId = detail.field?.id as string | undefined;

        if (dropZoneType === 'column' && fieldId) {
            delete this.fieldPolicies[fieldId];
        }
    }

    /**
     * The scope of the permission checkboxes
     * @param scope the scope
     */
    public getPermissionValues(scope:PermissionScope) {
        switch (scope) {
            case PermissionScope.GLOBAL:
                return this.globalPermissionComp.getValues();
            case PermissionScope.ROW:
                return this.rowPermissionComp.getValues();
            case PermissionScope.FIELD:
                return this.fieldPermissionComp.getValues();
            default:
                return [];
        }
    } 

    /**
     * Adds a row policy based on selected filters and permissions.
     */
    private addRowPolicy() : void {
        // Get permissions
        let permissions = this.getPermissionValues(PermissionScope.ROW);

        if (permissions.length === 0) {
            alert("Please select at least one permission for the row policy.");
            return;
        }

        // Get filters
        const filters = this.rowPolicyFilter?.getFilters() || [];
        if (filters.length === 0) {
            alert("Please add at least one condition for the row policy.");
            return;
        }

        filters.forEach((filter) => {
            const rule = {
                field: filter.field,
                operator: filter.operator,
                value: filter.value,
                application_field_id: filter.applicationFieldId || this.currentDroppedApplicationFieldId
            };

            this.rowPolicyRules.push({
                permissions: permissions,
                rule: rule
            });
        });


        // Reset checkboxes
        this.rowPermissionComp.reset();

        // Close modal
        this.rowPolicyModal?.close();
    }

    /**
     * Adds a field 
     */
    private addFieldPolicy() : void {
        // Get permissions
        let permissions = this.getPermissionValues(PermissionScope.FIELD);

        if (permissions.length === 0) {
            alert("Please select at least one permission for the field policy.");
            return;
        }

        const applicationFieldId = this.currentDroppedApplicationFieldId;
        if (!applicationFieldId) {
            alert("Please drop a field before adding a field policy.");
            return;
        }

        this.fieldPolicies[applicationFieldId] = permissions;

        // Reset checkboxes
        this.fieldPermissionComp.reset();

        // Close modal
        this.fieldPolicyModal?.close();
    }

    /**
     * Constructs the row policy object from state
     */
    private getRowPolicy() : Record<string, any> {
        return {
            name: this.rowPolicyNameInput?.value || 'Row Policy',
            rules: this.rowPolicyRules
        }
    }

    /**
     * Contructs the field policy object from the state
     */
    private getFieldPolicy() : Record<string, any> {
        return {
            name: this.fieldPolicyNameInput?.value || 'Field Policy',
            rules: this.fieldPolicies
        }
    }


    /**
     * Saves the permission using the state
     */
    private async save() : Promise<void> {
        const name = this.policyNameInput?.value?.trim() || `Permissions for ContentType ${this.contentTypeId}`;
        const description = this.policyDescriptionInput?.value?.trim() || '';
        const globalPermissions = this.getPermissionValues(PermissionScope.GLOBAL);
        const payload = {
            name: name,
            description: description,
            content_type_id: this.contentTypeId,
            global_permissions: globalPermissions,
            row_policy: this.getRowPolicy(),
            field_policy: this.getFieldPolicy(),
        };

        const csrfToken = getCsrfToken();

        console.log("Saving policy with payload:", payload);

        try {
            const response = await fetch('/api/access_control_policies/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {})
                },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                let errorMessage = 'Failed to create policy.';
                try {
                    const errorData = await response.json();
                    errorMessage = errorData?.detail || JSON.stringify(errorData);
                } catch {
                    // ignore json parse errors
                }
                alert(errorMessage);
                return;
            }

            alert('Policy created successfully.');
        } catch (error) {
            console.error(error);
            alert('Failed to create policy. Please try again.');
        }
    }
}