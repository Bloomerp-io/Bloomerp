import BaseComponent, { getComponent } from "./BaseComponent";
import FilterContainer from "./Filters";
import PermissionCheckboxes from "./inputs/PermissionCheckboxes";
import { Modal } from "./Modal";
import htmx from "htmx.org";

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
    private contentTypeId: string;
    private addRowPolicyBtn: HTMLElement | null = null;

    // 
    private rowPolicyFilter: FilterContainer | null = null;

    // Permission checkboxes
    private globalPermissionComp : PermissionCheckboxes;
    private rowPermissionComp : PermissionCheckboxes;
    private fieldPermissionComp : PermissionCheckboxes;

    // Modals
    private rowPolicyModal: Modal | null = null;
    private fieldPolicyModal: Modal | null = null;


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

        // Initialize PermissionCheckboxes components
        this.globalPermissionComp = getComponent(document.getElementById(`global-permissions-${this.contentTypeId}`)) as PermissionCheckboxes;
        this.rowPermissionComp = getComponent(document.getElementById(`row-policy-permissions-${this.contentTypeId}`)) as PermissionCheckboxes;
        this.fieldPermissionComp = getComponent(document.getElementById(`field-policy-permissions-${this.contentTypeId}`)) as PermissionCheckboxes;

        // Initialize Modals
        this.rowPolicyModal = getComponent(document.getElementById('row-policy-modal')) as Modal;
        this.fieldPolicyModal = getComponent(document.getElementById('field-policy-modal')) as Modal;
    }

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
    }

    /**
     * The scope of the permission checkboxes
     * @param scope 
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
        let permissions = this.getPermissionValues(PermissionScope.ROW)        

        // Get filters
        let filters = this.rowPolicyFilter.getFilters()

        console.log("Adding Row Policy with permissions:", permissions, "and filters:", filters)

        // Reset checkboxes
        this.rowPermissionComp.reset();

        // Close modal
        this.rowPolicyModal?.close();
    }
}