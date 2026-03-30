import htmx from "htmx.org";

import BaseComponent, { getComponent } from "./BaseComponent";
import FilterContainer from "./Filters";
import { Modal } from "./Modal";
import PermissionCheckboxes from "./inputs/PermissionCheckboxes";
import { clearInlineAlert, renderInlineAlert } from "../utils/alerts";
import { getCsrfToken } from "../utils/cookies";
import { formatFilterLabel, formatFilterTooltip } from "../utils/filterLabels";
import { addTooltip } from "../utils/tooltip";

interface FieldData {
    id: string;
    name: string;
    label: string;
}

interface RowPolicyRuleState {
    rule: {
        field?: string;
        operator?: string | null;
        value?: string | string[] | null;
        application_field_id?: string | null;
    };
    permissions: string[];
}

type ComponentMode = "default" | "wizard";

enum PermissionScope {
    GLOBAL = "global",
    ROW = "row",
    FIELD = "column",
}

export class PermissionsTable extends BaseComponent {
    private contentTypeId = "";
    private mode: ComponentMode = "default";
    private rowPolicyFilter: FilterContainer | null = null;
    private currentDroppedField: FieldData | null = null;
    private editingRowPolicyIndex: number | null = null;
    private editingFieldPolicyId: string | null = null;
    private previewTarget: HTMLElement | null = null;

    private draggableFields: HTMLElement[] = [];
    private dropZones: HTMLElement[] = [];
    private fieldLookup = new Map<string, FieldData>();

    private rowPolicyNameInput: HTMLInputElement | null = null;
    private fieldPolicyNameInput: HTMLInputElement | null = null;
    private policyNameInput: HTMLInputElement | null = null;
    private policyDescriptionInput: HTMLTextAreaElement | null = null;
    private rowPolicyNameHiddenInput: HTMLInputElement | null = null;
    private fieldPolicyNameHiddenInput: HTMLInputElement | null = null;
    private rowPolicyRulesJsonInput: HTMLInputElement | null = null;
    private fieldPoliciesJsonInput: HTMLInputElement | null = null;
    private rowPolicyAlert: HTMLElement | null = null;
    private fieldPolicyAlert: HTMLElement | null = null;
    private rowPolicyPreview: HTMLElement | null = null;
    private fieldPolicyPreview: HTMLElement | null = null;

    private addRowPolicyBtn: HTMLElement | null = null;
    private addFieldPolicyBtn: HTMLElement | null = null;
    private saveBtn: HTMLElement | null = null;

    private globalPermissionComp: PermissionCheckboxes | null = null;
    private rowPermissionComp: PermissionCheckboxes | null = null;
    private fieldPermissionComp: PermissionCheckboxes | null = null;
    private previewRequestController: AbortController | null = null;
    private permissionLabelLookup = new Map<string, string>();

    private rowPolicyModal: Modal | null = null;
    private fieldPolicyModal: Modal | null = null;

    private rowPolicyRules: RowPolicyRuleState[] = [];
    private fieldPolicies: Record<string, string[]> = {};

    private readonly onDragStart = (event: DragEvent) => this.handleDragStart(event);
    private readonly onDragEnd = (event: DragEvent) => this.handleDragEnd(event);
    private readonly onDragOver = (event: DragEvent) => this.handleDragOver(event);
    private readonly onDragLeave = (event: DragEvent) => this.handleDragLeave(event);
    private readonly onDrop = (event: DragEvent) => this.handleDrop(event);
    private readonly onRowPolicyNameInput = () => this.syncWizardInputs();
    private readonly onFieldPolicyNameInput = () => this.syncWizardInputs();
    private readonly onAddRowPolicy = () => this.addRowPolicy();
    private readonly onAddFieldPolicy = () => this.addFieldPolicy();
    private readonly onSave = () => void this.save();

    public initialize(): void {
        if (!this.element) {
            return;
        }

        this.contentTypeId = this.element.dataset.contentTypeId || "";
        this.mode = this.element.dataset.mode === "wizard" ? "wizard" : "default";

        this.initializeDomReferences();
        this.initializeFieldLookup();
        this.initializePermissionComponents();
        this.initializePermissionLabelLookup();
        this.initializeModals();
        this.restoreStateFromHiddenInputs();
        this.bindInteractiveElements();
        this.renderPreviews();
        this.syncWizardInputs();
        void this.renderPermissionsPreview();
    }

    public destroy(): void {
        this.draggableFields.forEach((field) => {
            field.removeEventListener("dragstart", this.onDragStart);
            field.removeEventListener("dragend", this.onDragEnd);
        });

        this.dropZones.forEach((zone) => {
            zone.removeEventListener("dragover", this.onDragOver);
            zone.removeEventListener("dragleave", this.onDragLeave);
            zone.removeEventListener("drop", this.onDrop);
        });

        this.addRowPolicyBtn?.removeEventListener("click", this.onAddRowPolicy);
        this.addFieldPolicyBtn?.removeEventListener("click", this.onAddFieldPolicy);
        this.saveBtn?.removeEventListener("click", this.onSave);
        this.rowPolicyNameInput?.removeEventListener("input", this.onRowPolicyNameInput);
        this.fieldPolicyNameInput?.removeEventListener("input", this.onFieldPolicyNameInput);
    }

    private initializeDomReferences(): void {
        if (!this.element) {
            return;
        }

        this.draggableFields = Array.from(this.element.querySelectorAll<HTMLElement>("[data-field-draggable]"));
        this.dropZones = Array.from(this.element.querySelectorAll<HTMLElement>("[data-drop-zone]"));

        this.rowPolicyNameInput = this.element.querySelector<HTMLInputElement>("#row-policy-name-input");
        this.fieldPolicyNameInput = this.element.querySelector<HTMLInputElement>("#field-policy-name-input");
        this.policyNameInput = this.element.querySelector<HTMLInputElement>("#policy-name-input");
        this.policyDescriptionInput = this.element.querySelector<HTMLTextAreaElement>("#policy-description-input");
        this.rowPolicyNameHiddenInput = this.element.querySelector<HTMLInputElement>("#row-policy-name-hidden");
        this.fieldPolicyNameHiddenInput = this.element.querySelector<HTMLInputElement>("#field-policy-name-hidden");
        this.rowPolicyRulesJsonInput = this.element.querySelector<HTMLInputElement>("#row-policy-rules-json");
        this.fieldPoliciesJsonInput = this.element.querySelector<HTMLInputElement>("#field-policies-json");
        this.rowPolicyAlert = this.element.querySelector<HTMLElement>("#row-policy-alert");
        this.fieldPolicyAlert = this.element.querySelector<HTMLElement>("#field-policy-alert");
        this.rowPolicyPreview = this.element.querySelector<HTMLElement>("[data-row-policy-preview]");
        this.fieldPolicyPreview = this.element.querySelector<HTMLElement>("[data-field-policy-preview]");
        this.previewTarget = this.element.querySelector<HTMLElement>("#permissions-table-preview");

        this.addRowPolicyBtn = this.element.querySelector("#add-row-policy-btn");
        this.addFieldPolicyBtn = this.element.querySelector("#add-field-policy-btn");
        this.saveBtn = this.element.querySelector("#save-policy-btn");
    }

    private initializeFieldLookup(): void {
        this.fieldLookup.clear();

        this.draggableFields.forEach((field) => {
            const id = field.dataset.fieldId || "";
            if (!id) {
                return;
            }

            this.fieldLookup.set(id, {
                id,
                name: field.dataset.fieldName || "",
                label: field.dataset.fieldLabel || field.textContent?.trim() || field.dataset.fieldName || id,
            });
        });
    }

    private initializePermissionComponents(): void {
        this.globalPermissionComp = this.getPermissionCheckboxComponent(`global-permissions-${this.contentTypeId}`);
        this.rowPermissionComp = this.getPermissionCheckboxComponent(`row-policy-permissions-${this.contentTypeId}`);
        this.fieldPermissionComp = this.getPermissionCheckboxComponent(`field-policy-permissions-${this.contentTypeId}`);
    }

    private initializeModals(): void {
        this.rowPolicyModal = this.getModalComponent("row-policy-modal");
        this.fieldPolicyModal = this.getModalComponent("field-policy-modal");
    }

    private initializePermissionLabelLookup(): void {
        this.permissionLabelLookup.clear();

        if (!this.element) {
            return;
        }

        this.element.querySelectorAll<HTMLLabelElement>("label").forEach((label) => {
            const input = label.querySelector<HTMLInputElement>("input[type='checkbox']");
            const text = label.querySelector<HTMLElement>("span")?.textContent?.trim() || "";

            if (!input?.value || !text || input.value === "__all__") {
                return;
            }

            this.permissionLabelLookup.set(input.value, text);
        });
    }

    private bindInteractiveElements(): void {
        this.draggableFields.forEach((field) => {
            field.addEventListener("dragstart", this.onDragStart);
            field.addEventListener("dragend", this.onDragEnd);
        });

        this.dropZones.forEach((zone) => {
            zone.addEventListener("dragover", this.onDragOver);
            zone.addEventListener("dragleave", this.onDragLeave);
            zone.addEventListener("drop", this.onDrop);
        });

        this.addRowPolicyBtn?.addEventListener("click", this.onAddRowPolicy);
        this.addFieldPolicyBtn?.addEventListener("click", this.onAddFieldPolicy);

        if (this.mode !== "wizard") {
            this.saveBtn?.addEventListener("click", this.onSave);
        }

        this.rowPolicyNameInput?.addEventListener("input", this.onRowPolicyNameInput);
        this.fieldPolicyNameInput?.addEventListener("input", this.onFieldPolicyNameInput);
    }

    private getPermissionCheckboxComponent(id: string): PermissionCheckboxes | null {
        const element = document.getElementById(id);
        return element ? (getComponent(element) as PermissionCheckboxes | null) : null;
    }

    private getModalComponent(id: string): Modal | null {
        const element = document.getElementById(id);
        return element ? (getComponent(element) as Modal | null) : null;
    }

    private getPermissionValues(scope: PermissionScope): string[] {
        const component = this.getPermissionComponent(scope);
        return component ? component.getValues() : [];
    }

    private getPermissionComponent(scope: PermissionScope): PermissionCheckboxes | null {
        switch (scope) {
            case PermissionScope.GLOBAL:
                return this.globalPermissionComp;
            case PermissionScope.ROW:
                return this.rowPermissionComp;
            case PermissionScope.FIELD:
                return this.fieldPermissionComp;
            default:
                return null;
        }
    }

    private handleDragStart(event: DragEvent): void {
        const target = event.currentTarget as HTMLElement | null;
        if (!target) {
            return;
        }

        const fieldId = target.dataset.fieldId || "";
        this.currentDroppedField = this.fieldLookup.get(fieldId) || {
            id: fieldId,
            name: target.dataset.fieldName || "",
            label: target.dataset.fieldLabel || target.textContent?.trim() || fieldId,
        };

        if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("application/json", JSON.stringify(this.currentDroppedField));
        }

        target.classList.add("opacity-50");
        this.highlightAllDropZones(true);
    }

    private handleDragEnd(event: DragEvent): void {
        const target = event.currentTarget as HTMLElement | null;
        target?.classList.remove("opacity-50");
        this.highlightAllDropZones(false);
    }

    private handleDragOver(event: DragEvent): void {
        event.preventDefault();
        if (event.dataTransfer) {
            event.dataTransfer.dropEffect = "move";
        }
        (event.currentTarget as HTMLElement | null)?.classList.add("drop-zone-active");
    }

    private handleDragLeave(event: DragEvent): void {
        const target = event.currentTarget as HTMLElement | null;
        if (!target) {
            return;
        }

        const relatedTarget = event.relatedTarget as HTMLElement | null;
        if (!relatedTarget || !target.contains(relatedTarget)) {
            target.classList.remove("drop-zone-active");
        }
    }

    private handleDrop(event: DragEvent): void {
        event.preventDefault();
        event.stopPropagation();

        const dropZone = event.currentTarget as HTMLElement | null;
        const field = this.currentDroppedField;
        if (!dropZone || !field) {
            return;
        }

        const dropZoneType = dropZone.dataset.dropZone;
        dropZone.classList.remove("drop-zone-active");

        if (dropZoneType === "row") {
            void this.openRowPolicyModal(field);
            return;
        }

        if (dropZoneType === "column") {
            this.openFieldPolicyModal(field);
        }
    }

    private async openRowPolicyModal(field: FieldData, index: number | null = null): Promise<void> {
        this.currentDroppedField = field;
        this.editingRowPolicyIndex = index;
        clearInlineAlert(this.rowPolicyAlert);
        this.rowPolicyModal?.open();

        const filterTarget = document.getElementById("permissions-modal-filter-target");
        if (field.id === "__all__") {
            if (filterTarget) {
                filterTarget.innerHTML = `
                    <div class="rounded-md border border-dashed border-gray-300 bg-gray-50 px-4 py-3 text-sm text-gray-500">
                        This rule grants the selected permissions on all objects.
                    </div>
                `;
            }
            this.rowPolicyFilter = null;
        } else {
            await htmx.ajax("get", `/components/filters/${this.contentTypeId}/init/?application_field_id=${field.id}`, {
                target: "#permissions-modal-filter-target",
                swap: "innerHTML",
            });

            const filterElement = document.getElementById(`filter-container-${this.contentTypeId}`);
            this.rowPolicyFilter = filterElement ? (getComponent(filterElement) as FilterContainer | null) : null;
        }

        if (index === null) {
            this.rowPermissionComp?.reset();
            return;
        }

        const existingRule = this.rowPolicyRules[index];
        if (!existingRule) {
            return;
        }

        this.rowPermissionComp?.setValues(existingRule.permissions);
        if (field.id === "__all__") {
            return;
        }

        await this.rowPolicyFilter?.setFilter({
            field: String(existingRule.rule.field || ""),
            applicationFieldId: String(existingRule.rule.application_field_id || field.id),
            operator: String(existingRule.rule.operator || ""),
            value: (existingRule.rule.value as string | string[] | null) ?? null,
        });
    }

    private openFieldPolicyModal(field: FieldData): void {
        this.currentDroppedField = field;
        this.editingFieldPolicyId = field.id;
        clearInlineAlert(this.fieldPolicyAlert);
        this.fieldPermissionComp?.setValues(this.getExistingFieldPolicyValues(field.id));
        this.fieldPolicyModal?.open();
    }

    private highlightAllDropZones(highlight: boolean): void {
        this.dropZones.forEach((zone) => {
            if (highlight) {
                zone.classList.add("drop-zone-available");
                return;
            }

            zone.classList.remove("drop-zone-available", "drop-zone-active");
        });
    }

    private addRowPolicy(): void {
        const permissions = this.getPermissionValues(PermissionScope.ROW);
        if (permissions.length === 0) {
            renderInlineAlert(this.rowPolicyAlert, "Please select at least one permission for the row policy.", "Permission required");
            return;
        }

        if (this.currentDroppedField?.id === "__all__") {
            clearInlineAlert(this.rowPolicyAlert);

            const nextRule = {
                permissions,
                rule: {
                    field: "__all__",
                    application_field_id: "__all__",
                },
            };

            if (this.editingRowPolicyIndex !== null) {
                this.rowPolicyRules.splice(this.editingRowPolicyIndex, 1, nextRule);
            } else {
                this.rowPolicyRules.push(nextRule);
            }

            this.editingRowPolicyIndex = null;
            this.rowPermissionComp?.reset();
            this.rowPolicyModal?.close();
            this.renderRowPolicyPreview();
            this.syncWizardInputs();
            void this.renderPermissionsPreview();
            return;
        }

        const filters = this.rowPolicyFilter?.getFilters() || [];
        if (filters.length === 0) {
            renderInlineAlert(this.rowPolicyAlert, "Please add at least one condition for the row policy.", "Condition required");
            return;
        }

        clearInlineAlert(this.rowPolicyAlert);

        const nextRules = filters.map((filter) => ({
            permissions,
            rule: {
                field: filter.field,
                operator: filter.operator,
                value: filter.value,
                application_field_id: filter.applicationFieldId || this.currentDroppedField?.id || null,
            },
        }));

        if (this.editingRowPolicyIndex !== null) {
            this.rowPolicyRules.splice(this.editingRowPolicyIndex, 1, ...nextRules);
        } else {
            this.rowPolicyRules.push(...nextRules);
        }

        this.editingRowPolicyIndex = null;
        this.rowPermissionComp?.reset();
        this.rowPolicyModal?.close();
        this.renderRowPolicyPreview();
        this.syncWizardInputs();
        void this.renderPermissionsPreview();
    }

    private addFieldPolicy(): void {
        const permissions = this.getPermissionValues(PermissionScope.FIELD);
        if (permissions.length === 0) {
            renderInlineAlert(this.fieldPolicyAlert, "Please select at least one permission for the field policy.", "Permission required");
            return;
        }

        if (!this.currentDroppedField) {
            renderInlineAlert(this.fieldPolicyAlert, "Please choose a field before adding a field policy.", "Field required");
            return;
        }

        clearInlineAlert(this.fieldPolicyAlert);

        this.applyFieldPolicyPermissions(this.currentDroppedField.id, permissions);
        this.editingFieldPolicyId = null;
        this.fieldPermissionComp?.reset();
        this.fieldPolicyModal?.close();
        this.renderFieldPolicyPreview();
        this.syncWizardInputs();
        void this.renderPermissionsPreview();
    }

    private renderPreviews(): void {
        this.renderRowPolicyPreview();
        this.renderFieldPolicyPreview();
        this.updateUsedFieldIndicators();
    }

    private renderRowPolicyPreview(): void {
        if (!this.rowPolicyPreview) {
            return;
        }

        this.rowPolicyPreview.innerHTML = "";

        this.rowPolicyRules.forEach((rowPolicyRule, index) => {
            const badge = document.createElement("span");
            badge.className = "badge badge-primary cursor-pointer";
            badge.dataset.rowPolicyIndex = String(index);
            badge.title = formatFilterTooltip(
                String(rowPolicyRule.rule.field || ""),
                (rowPolicyRule.rule.operator as string | null) ?? null,
                (rowPolicyRule.rule.value as string | string[] | null) ?? null
            );

            const removeButton = document.createElement("button");
            removeButton.type = "button";
            removeButton.className = "badge-remove";
            removeButton.setAttribute("aria-label", "Remove row policy");
            removeButton.innerHTML = '<i class="fa fa-x"></i>';
            removeButton.addEventListener("click", (event) => {
                event.stopPropagation();
                this.rowPolicyRules.splice(index, 1);
                this.renderRowPolicyPreview();
                this.renderFieldPolicyPreview();
                this.syncWizardInputs();
                void this.renderPermissionsPreview();
            });

            const text = document.createElement("span");
            if (rowPolicyRule.rule.field === "__all__" || rowPolicyRule.rule.application_field_id === "__all__") {
                text.textContent = "All objects";
            } else {
                text.textContent = formatFilterLabel(
                    String(rowPolicyRule.rule.field || ""),
                    (rowPolicyRule.rule.operator as string | null) ?? null,
                    (rowPolicyRule.rule.value as string | string[] | null) ?? null
                );
            }

            badge.appendChild(removeButton);
            badge.appendChild(text);
            badge.addEventListener("click", () => {
                const fieldId = String(
                    rowPolicyRule.rule.application_field_id
                    || (rowPolicyRule.rule.field === "__all__" ? "__all__" : "")
                );
                const field = this.fieldLookup.get(fieldId);
                if (!field) {
                    return;
                }

                void this.openRowPolicyModal(field, index);
            });

            this.rowPolicyPreview?.appendChild(badge);
        });

        this.updateUsedFieldIndicators();
    }

    private renderFieldPolicyPreview(): void {
        if (!this.fieldPolicyPreview) {
            return;
        }

        this.fieldPolicyPreview.innerHTML = "";

        Object.keys(this.fieldPolicies).forEach((fieldId) => {
            const field = this.fieldLookup.get(fieldId);
            if (!field) {
                return;
            }

            const badge = document.createElement("span");
            badge.className = "badge badge-primary cursor-pointer";
            badge.dataset.fieldId = fieldId;

            const removeButton = document.createElement("button");
            removeButton.type = "button";
            removeButton.className = "badge-remove";
            removeButton.setAttribute("aria-label", "Remove field policy");
            removeButton.innerHTML = '<i class="fa fa-x"></i>';
            removeButton.addEventListener("click", (event) => {
                event.stopPropagation();
                delete this.fieldPolicies[fieldId];
                this.renderFieldPolicyPreview();
                this.syncWizardInputs();
                void this.renderPermissionsPreview();
            });

            const text = document.createElement("span");
            text.textContent = field.label;

            badge.appendChild(removeButton);
            badge.appendChild(text);
            addTooltip(badge, {
                text: this.getPermissionTooltipTitle(this.fieldPolicies[fieldId]),
                position: "top",
            });
            badge.addEventListener("click", () => {
                this.openFieldPolicyModal(field);
            });
            this.fieldPolicyPreview?.appendChild(badge);
        });

        this.updateUsedFieldIndicators();
    }

    private updateUsedFieldIndicators(): void {
        const fieldPolicyIds = new Set<string>(Object.keys(this.fieldPolicies));
        const rowPolicyIds = new Set<string>(
            this.rowPolicyRules
                .map((rowPolicyRule) => String(rowPolicyRule.rule.application_field_id || ""))
                .filter((fieldId) => Boolean(fieldId) && fieldId !== "__all__")
        );

        this.draggableFields.forEach((field) => {
            const fieldId = field.dataset.fieldId || "";
            const usedInFieldPolicy = fieldPolicyIds.has(fieldId);
            const usedInRowPolicy = rowPolicyIds.has(fieldId);
            const usageCount = Number(usedInFieldPolicy) + Number(usedInRowPolicy);

            field.dataset.fieldUsed = usageCount > 0 ? "true" : "false";
            field.classList.remove(
                "bg-white",
                "text-gray-700",
                "border-base",
                "bg-gray-100",
                "text-gray-500",
                "border-gray-300",
                "bg-gray-300",
                "text-gray-700",
                "border-gray-400"
            );

            if (usageCount === 0) {
                field.classList.add("bg-white", "text-gray-700", "border-base");
            } else if (usageCount === 1) {
                field.classList.add("bg-gray-100", "text-gray-500", "border-gray-300");
            } else {
                field.classList.add("bg-gray-300", "text-gray-700", "border-gray-400");
            }

            const baseTitle = field.dataset.fieldLabel || field.textContent?.trim() || "";
            if (usageCount === 2) {
                field.title = `${baseTitle} used in both row and field policies`;
            } else if (usedInFieldPolicy) {
                field.title = `${baseTitle} used in a field policy`;
            } else if (usedInRowPolicy) {
                field.title = `${baseTitle} used in a row policy`;
            } else {
                field.title = "";
            }
        });
    }

    private getRowPolicy(): Record<string, unknown> {
        return {
            name: this.rowPolicyNameInput?.value || "Row Policy",
            rules: this.rowPolicyRules,
        };
    }

    private getFieldPolicy(): Record<string, unknown> {
        return {
            name: this.fieldPolicyNameInput?.value || "Field Policy",
            rules: this.fieldPolicies,
        };
    }

    private async save(): Promise<void> {
        const csrfToken = getCsrfToken();
        const payload = {
            name: this.policyNameInput?.value?.trim() || `Permissions for ContentType ${this.contentTypeId}`,
            description: this.policyDescriptionInput?.value?.trim() || "",
            content_type_id: this.contentTypeId,
            global_permissions: this.getPermissionValues(PermissionScope.GLOBAL),
            row_policy: this.getRowPolicy(),
            field_policy: this.getFieldPolicy(),
        };

        try {
            const response = await fetch("/api/access_control_policies/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(csrfToken ? { "X-CSRFToken": csrfToken } : {}),
                },
                body: JSON.stringify(payload),
            });

            if (!response.ok) {
                let errorMessage = "Failed to create policy.";
                try {
                    const errorData = await response.json();
                    errorMessage = errorData?.detail || JSON.stringify(errorData);
                } catch {
                    // Ignore invalid error bodies and keep the default message.
                }
                alert(errorMessage);
                return;
            }

            alert("Policy created successfully.");
        } catch (error) {
            console.error(error);
            alert("Failed to create policy. Please try again.");
        }
    }

    private restoreStateFromHiddenInputs(): void {
        this.rowPolicyRules = this.parseJsonInputValue<RowPolicyRuleState[]>(this.rowPolicyRulesJsonInput?.value, []);
        this.fieldPolicies = this.parseJsonInputValue<Record<string, string[]>>(this.fieldPoliciesJsonInput?.value, {});
        this.normalizeAllFieldPolicies();
    }

    private parseJsonInputValue<T>(rawValue: string | undefined, fallback: T): T {
        if (!rawValue) {
            return fallback;
        }

        try {
            return JSON.parse(rawValue) as T;
        } catch {
            return fallback;
        }
    }

    private syncWizardInputs(): void {
        if (this.mode !== "wizard") {
            return;
        }

        if (this.rowPolicyNameHiddenInput) {
            this.rowPolicyNameHiddenInput.value = this.rowPolicyNameInput?.value || "";
        }

        if (this.fieldPolicyNameHiddenInput) {
            this.fieldPolicyNameHiddenInput.value = this.fieldPolicyNameInput?.value || "";
        }

        if (this.rowPolicyRulesJsonInput) {
            this.rowPolicyRulesJsonInput.value = JSON.stringify(this.rowPolicyRules);
        }

        if (this.fieldPoliciesJsonInput) {
            this.fieldPoliciesJsonInput.value = JSON.stringify(this.fieldPolicies);
        }
    }

    private getConcreteFieldIds(): string[] {
        return Array.from(this.fieldLookup.keys()).filter((fieldId) => fieldId !== "__all__");
    }

    private getExistingFieldPolicyValues(fieldId: string): string[] {
        if (fieldId === "__all__") {
            const concreteFieldIds = this.getConcreteFieldIds();
            const firstDefinedPolicy = concreteFieldIds
                .map((id) => this.fieldPolicies[id])
                .find((permissions) => Array.isArray(permissions) && permissions.length > 0);

            return firstDefinedPolicy ? [...firstDefinedPolicy] : [];
        }

        return this.fieldPolicies[fieldId] ? [...this.fieldPolicies[fieldId]] : [];
    }

    private getPermissionDisplayLabel(permissionValue: string): string {
        return this.permissionLabelLookup.get(permissionValue) || permissionValue;
    }

    private getPermissionTooltipTitle(permissions: string[]): string {
        const labels = permissions.map((permission) => this.getPermissionDisplayLabel(permission));
        return labels.join(", ");
    }

    private applyFieldPolicyPermissions(fieldId: string, permissions: string[]): void {
        const nextPermissions = [...permissions];
        const targetFieldIds = fieldId === "__all__" ? this.getConcreteFieldIds() : [fieldId];

        targetFieldIds.forEach((targetFieldId) => {
            this.fieldPolicies[targetFieldId] = [...nextPermissions];
        });

        delete this.fieldPolicies.__all__;
    }

    private normalizeAllFieldPolicies(): void {
        const allPermissions = this.fieldPolicies.__all__;
        if (!Array.isArray(allPermissions) || allPermissions.length === 0) {
            delete this.fieldPolicies.__all__;
            return;
        }

        this.applyFieldPolicyPermissions("__all__", allPermissions);
    }

    private async renderPermissionsPreview(page = 1): Promise<void> {
        if (!this.previewTarget) {
            return;
        }

        this.previewRequestController?.abort();
        this.previewRequestController = new AbortController();

        this.previewTarget.innerHTML = `
            <div class="min-h-[60px] text-xs text-gray-400 flex items-center justify-center">
                Loading preview...
            </div>
        `;

        try {
            const csrfToken = getCsrfToken();
            const response = await fetch(`/components/access-control/preview-permissions-table/${this.contentTypeId}/`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    ...(csrfToken ? { "X-CSRFToken": csrfToken } : {}),
                },
                body: new URLSearchParams({
                    page: String(page),
                    global_permissions_json: JSON.stringify(this.getSelectedGlobalPermissions()),
                    row_policy_rules_json: JSON.stringify(this.rowPolicyRules),
                    field_policies_json: JSON.stringify(this.fieldPolicies),
                }),
                signal: this.previewRequestController.signal,
            });

            if (!response.ok) {
                this.previewTarget.innerHTML = `
                    <div class="rounded-lg border border-dashed border-red-200 bg-red-50 px-4 py-6 text-sm text-red-600">
                        Unable to load preview.
                    </div>
                `;
                return;
            }

            this.previewTarget.innerHTML = await response.text();
            this.bindPreviewPagination();
        } catch (error) {
            if (error instanceof DOMException && error.name === "AbortError") {
                return;
            }

            this.previewTarget.innerHTML = `
                <div class="rounded-lg border border-dashed border-red-200 bg-red-50 px-4 py-6 text-sm text-red-600">
                    Unable to load preview.
                </div>
            `;
        }
    }

    private bindPreviewPagination(): void {
        if (!this.previewTarget) {
            return;
        }

        const buttons = this.previewTarget.querySelectorAll<HTMLElement>("[data-preview-page]");
        buttons.forEach((button) => {
            button.addEventListener("click", () => {
                const page = parseInt(button.dataset.previewPage || "1", 10);
                void this.renderPermissionsPreview(page);
            });
        });
    }

    private getSelectedGlobalPermissions(): string[] {
        if (this.mode !== "wizard") {
            return this.getPermissionValues(PermissionScope.GLOBAL);
        }

        return this.parseJsonInputValue<string[]>(
            this.element?.dataset.globalPermissionsJson,
            []
        );
    }
}
