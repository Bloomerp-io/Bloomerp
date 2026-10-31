import BaseComponent from "../BaseComponent";
import type { Modal } from "../Modal";
import htmx from "htmx.org";
import { getSdk } from "../../sdk/getSdk";
import { BloomerpHttpError } from "../../sdk/sdk";
import { t } from "../../utils/i18n";
import { createModalInstance } from "../../utils/modals";
import showMessage from "../../utils/messages";
import { MessageType } from "../UiMessage";
import PdfViewer from "./PdfViewer";
import "./PrepareSign.css";

interface FieldDefinition {
    key: string; label: string; icon: string; description: string;
    width: number; height: number; supportsOptions: boolean;
}
interface BuilderConfig {
    fileId: string; fileName: string; pdfUrl: string; preparationId: string | null; preparationUrl: string;
    canSave: boolean; fieldTypes: FieldDefinition[]; sendUrl: string; selfSignUrl: string;
    defaultLayoutUrl: string; documentTemplates: DocumentTemplateOption[];
    selectedDocumentTemplateId: string | null;
}
interface LayoutRevision {
    id: string; revision: number; is_default: boolean;
}
interface DocumentTemplateOption {
    id: string; name: string; defaultLayoutId: string | null; canSave: boolean;
    revisions: LayoutRevision[];
}
interface LayoutRole {
    key: string; label: string; default_signing_order: number;
}
interface LayoutField {
    key: string; role_key: string; field_type: string; required: boolean; page_number: number;
    x: number | string; y: number | string; width: number | string; height: number | string;
    settings: Record<string, unknown>;
}
interface LayoutSnapshot {
    id: string; name: string; revision: number; roles: LayoutRole[]; fields: LayoutField[];
}
interface DefaultLayoutResponse {
    document_template_id: string; can_save: boolean; layout: LayoutSnapshot | null;
    default_layout_id: string | null; revisions: LayoutRevision[];
}
interface PreparationSnapshot {
    id: string; revision: number; title: string; source_layout: string | null;
    roles: LayoutRole[]; fields: LayoutField[];
}
interface Signer {
    localId: string; roleKey: string; roleLabel: string; order: number; color: string;
}
interface PlacedField {
    localId: string; key: string; type: string; signerId: string;
    page: number; x: number; y: number; width: number; height: number;
    required: boolean; settings: Record<string, unknown>;
}
interface Gesture {
    field: PlacedField; element: HTMLElement; overlay: HTMLElement; resize: boolean;
    pointerId: number; startX: number; startY: number;
    x: number; y: number; width: number; height: number;
}

const COLORS = [
    "var(--color-primary)", "var(--color-success-dark)", "var(--color-warning-dark)",
    "var(--color-danger-dark)", "var(--color-secondary)", "var(--color-primary-700)",
];
const DRAG_TYPE = "application/x-bloomerp-sign-field";

/** Construct UI elements without interpreting filenames, labels, or signer details as HTML. */
function node<K extends keyof HTMLElementTagNameMap>(tag: K, className: string, text?: string): HTMLElementTagNameMap[K] {
    const element = document.createElement(tag);
    element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
}

/** Constrain normalized coordinates and keep values within the model's six decimal places. */
function coordinate(value: number, lower: number, upper: number): number {
    return Number(Math.max(lower, Math.min(upper, value)).toFixed(6));
}

/** Derive a stable palette color from a role identity so reloads and ordering preserve ownership cues. */
function signerColor(roleKey: string): string {
    let hash = 0;
    for (const character of roleKey) hash = ((hash * 31) + character.charCodeAt(0)) >>> 0;
    return COLORS[hash % COLORS.length];
}

/** Own a draft-only PDF field editor with SDK persistence and disposable PDF resources. */
export default class PrepareSign extends BaseComponent {
    private config: BuilderConfig;
    private lifecycle = new AbortController();
    private definitions = new Map<string, FieldDefinition>();
    private signers = new Map<string, Signer>();
    private fields = new Map<string, PlacedField>();
    private selectedSigner: string | null = null;
    private selectedField: string | null = null;
    private activeTool: string | null = null;
    private preparationRevision = 0;
    private newPreparationId = crypto.randomUUID();
    private pdfViewer: PdfViewer | null = null;
    private overlays = new Map<number, HTMLElement>();
    private ready = false;
    private saving = false;
    private dirty = false;
    private gesture: Gesture | null = null;
    private pendingLayout: LayoutSnapshot | null = null;
    private sourceLayoutId: string | null = null;
    private openingAction = false;
    private actionModal: Modal | null = null;

    /** Read the server catalog and attach one lifecycle-owned set of delegated listeners. */
    public initialize(): void {
        const data = this.element.querySelector<HTMLScriptElement>(`#${this.element.dataset.configId}`);
        if (!data) return;
        this.config = JSON.parse(data.textContent || "{}");
        for (const definition of this.config.fieldTypes) this.definitions.set(definition.key, definition);
        const options = { signal: this.lifecycle.signal };
        this.element.classList.add("is-loading");
        this.element.addEventListener("click", this.onClick, options);
        this.element.addEventListener("input", this.onInput, options);
        this.element.addEventListener("change", this.onChange, options);
        this.element.addEventListener("keydown", this.onKeyDown, options);
        this.element.addEventListener("dragstart", this.onDragStart, options);
        this.element.addEventListener("dragover", this.onDragOver, options);
        this.element.addEventListener("dragleave", this.onDragLeave, options);
        this.element.addEventListener("drop", this.onDrop, options);
        this.element.addEventListener("dragend", this.onDragEnd, options);
        this.element.addEventListener("pointerdown", this.onPointerDown, options);
        window.addEventListener("pointermove", this.onPointerMove, options);
        window.addEventListener("pointerup", this.onPointerUp, options);
        window.addEventListener("pointercancel", this.onPointerUp, options);
        document.addEventListener("htmx:beforeCleanupElement", this.onCleanup, options);
        this.query("[data-viewport]").addEventListener("scroll", this.onScroll, options);
        this.renderPalette();
        this.renderLayoutRevisions();
        this.updateStatus();
        void this.load();
    }

    /** Find an owned shell element while keeping selectors scoped to this component instance. */
    private query<T extends HTMLElement = HTMLElement>(selector: string): T {
        return this.element.querySelector<T>(selector)!;
    }

    /** Load PDF bytes and any existing draft before enabling edits. */
    private async load(): Promise<void> {
        try {
            await Promise.all([this.loadPdf(), this.loadDraft()]);
            if (this.lifecycle.signal.aborted) return;
            this.ready = true;
            this.renderLayoutRevisions();
            const template = this.selectedDocumentTemplate();
            if (!this.config.preparationId && template?.defaultLayoutId) {
                await this.loadLayoutRevision(template.defaultLayoutId, false);
            }
            if (this.lifecycle.signal.aborted) return;
            if (!this.signers.size) this.addSigner(false);
            this.renderSigners();
            this.renderFields();
            this.query("[data-loading]").hidden = true;
            if (!this.config.canSave) this.notify(t("You can prepare fields here, but you do not have permission to save signing preparations."), MessageType.WARNING);
        } catch (error) {
            if (!this.lifecycle.signal.aborted) {
                this.query("[data-loading]").hidden = true;
                this.notify(this.errorMessage(error, t("The document could not be loaded.")));
            }
        } finally {
            this.element.classList.remove("is-loading");
            this.updateStatus();
        }
    }

    /** Load the shared PDF viewer with field-placement overlays owned by this editor. */
    private async loadPdf(): Promise<void> {
        this.pdfViewer = new PdfViewer({
            viewport: this.query("[data-viewport]"), pages: this.query("[data-pages]"),
            zoom: this.query<HTMLSelectElement>("[data-zoom]"), pageClass: "sign-builder__page", padding: 64,
            onPage: this.onPdfPage, beforeLayout: this.beforePdfLayout, afterLayout: this.afterPdfLayout,
            onError: this.onPdfError, canResize: this.canResizePdf,
        });
        await this.pdfViewer.load(this.config.pdfUrl);
        if (this.lifecycle.signal.aborted) return;
        this.query("[data-page-count]").textContent = String(this.pdfViewer.pageCount);
        this.query<HTMLInputElement>("[data-current-page]").max = String(this.pdfViewer.pageCount);
    }

    /** Restore a role-based preparation through the session-authenticated SDK client. */
    private async loadDraft(): Promise<void> {
        if (!this.config.preparationId) return;
        const draft = await getSdk().client.request<PreparationSnapshot>(this.config.preparationUrl, {
            query: { preparation_id: this.config.preparationId }, signal: this.lifecycle.signal,
        });
        this.query<HTMLInputElement>("[data-draft-title]").value = draft.title;
        this.sourceLayoutId = draft.source_layout;
        this.preparationRevision = draft.revision;
        for (const role of draft.roles) this.restoreSigner(role);
        for (const field of draft.fields) this.restoreField(field);
    }

    /** Restore a generic role without introducing any real recipient identity. */
    private restoreSigner(record: LayoutRole): void {
        const signer: Signer = {
            localId: record.key, roleKey: record.key, roleLabel: record.label,
            order: record.default_signing_order, color: signerColor(record.key),
        };
        this.signers.set(signer.localId, signer);
        this.selectedSigner ??= signer.localId;
    }

    /** Restore resolved geometry without retaining a dependency on any reusable layout. */
    private restoreField(record: LayoutField): void {
        if (!this.signers.has(record.role_key) || !this.definitions.has(record.field_type)) throw new Error(t("Some fields could not be loaded. Check your draft permissions."));
        this.fields.set(record.key, {
            localId: record.key, key: record.key, type: record.field_type,
            signerId: record.role_key, page: record.page_number,
            x: Number(record.x), y: Number(record.y), width: Number(record.width), height: Number(record.height),
            required: record.required, settings: (record.settings || {}) as Record<string, unknown>,
        });
    }

    /** Drop stale overlay references before the viewer rebuilds its page surfaces. */
    private beforePdfLayout = (): void => { this.overlays.clear(); };

    /** Add the keyboard-accessible placement layer to a shared PDF page. */
    private onPdfPage = (number: number, surface: HTMLElement): void => {
        const overlay = node("div", "sign-builder__overlay");
        overlay.dataset.pageOverlay = String(number);
        overlay.tabIndex = 0;
        overlay.setAttribute("aria-label", `${t("Place a field on page")} ${number}`);
        surface.append(overlay);
        this.overlays.set(number, overlay);
    };

    /** Restore the editor's normalized field boxes after zoom or viewport reflow. */
    private afterPdfLayout = (): void => { this.renderFields(); };

    /** Keep viewport resizing from interrupting an active field move or resize. */
    private canResizePdf = (): boolean => this.gesture === null;

    /** Report page-render failures through the editor's existing plain-text toast path. */
    private onPdfError = (_error: unknown): void => { this.notify(t("A PDF page could not be rendered.")); };

    /** Render every tool from backend definitions rather than a second frontend field catalog. */
    private renderPalette(): void {
        const palette = this.query("[data-palette]");
        palette.replaceChildren();
        for (const definition of this.definitions.values()) {
            const active = this.activeTool === definition.key;
            const button = node("button", `sign-builder__tool btn btn-xs min-w-0 justify-start ${active ? "btn-primary" : "btn-secondary"}`);
            button.type = "button"; button.draggable = true;
            button.dataset.fieldTool = definition.key;
            button.title = definition.description;
            button.setAttribute("aria-pressed", String(active));
            button.append(node("i", `${definition.icon} w-4 shrink-0 text-center`), node("span", "truncate", definition.label));
            palette.append(button);
        }
    }

    /** Add an unpersisted signer placeholder and make its color active for new placements. */
    private addSigner(markDirty: boolean = true): void {
        const id = crypto.randomUUID();
        const index = this.signers.size + 1;
        const roleKey = `signer_${id.replace(/-/g, "")}`;
        this.signers.set(id, {
            localId: id, roleKey,
            roleLabel: `${t("Role")} ${index}`, order: 1,
            color: signerColor(roleKey),
        });
        this.selectedSigner = id;
        this.selectedField = null;
        this.renderFields();
        this.renderSigners();
        if (markDirty) this.changed();
    }

    /** Render role names and signing order using the shared BloomERP controls. */
    private renderSigners(): void {
        const container = this.query("[data-signers]");
        container.replaceChildren();
        for (const signer of this.signers.values()) {
            const card = node("div", "border-b border-gray-200 pb-2");
            card.style.setProperty("--signer-color", signer.color);
            const header = node("button", "btn btn-ghost btn-sm w-full justify-start text-left");
            header.classList.toggle("bg-primary/8", signer.localId === this.selectedSigner);
            header.type = "button"; header.dataset.selectSigner = signer.localId;
            header.setAttribute("aria-expanded", String(signer.localId === this.selectedSigner));
            const copy = node("span", "min-w-0 flex-1");
            const name = node("span", "block truncate font-medium", signer.roleLabel);
            name.dataset.signerHeading = signer.localId;
            const orderLabel = node("span", "block text-xs font-normal text-muted", `${t("Signing order")} ${signer.order}`);
            orderLabel.dataset.signerOrder = signer.localId;
            copy.append(name, orderLabel);
            const count = node("span", "badge badge-secondary badge-xs", String(this.countFields(signer.localId)));
            count.dataset.signerFieldCount = signer.localId;
            header.append(node("span", "sign-builder__signer-marker size-2 shrink-0 rounded-full"), copy, count);
            card.append(header);
            if (signer.localId === this.selectedSigner) {
                const form = node("div", "px-2");
                form.append(this.signerInput(signer));
                const bottom = node("div", "flex items-center justify-between gap-3");
                const order = node("label", "flex items-center gap-2 text-xs", t("Signing order"));
                const input = node("input", "input input-sm w-14");
                input.type = "number"; input.min = "1"; input.value = String(signer.order);
                input.dataset.signerProperty = "order"; input.dataset.signerId = signer.localId;
                order.append(input);
                const remove = node("button", "btn btn-ghost btn-xs");
                remove.type = "button"; remove.dataset.removeSigner = signer.localId;
                remove.title = t("Remove role and its fields");
                remove.setAttribute("aria-label", remove.title);
                remove.append(node("i", "fa-regular fa-trash-can"));
                bottom.append(order, remove); form.append(bottom); card.append(form);
            }
            container.append(card);
        }
        this.query("[data-signer-count]").textContent = String(this.signers.size);
        this.query("[data-active-signer]").textContent = this.signers.get(this.selectedSigner || "")?.roleLabel || "";
        this.renderPalette();
        this.renderInspector();
    }

    /** Build an editable role label without asking who will eventually sign it. */
    private signerInput(signer: Signer): HTMLLabelElement {
        const wrapper = node("label", "my-3 grid gap-1 text-xs", t("Role name"));
        const input = node("input", "input input-sm w-full");
        input.type = "text"; input.required = true; input.maxLength = 255;
        input.value = signer.roleLabel; input.placeholder = t("e.g. Director");
        input.dataset.signerProperty = "roleLabel"; input.dataset.signerId = signer.localId;
        wrapper.append(input);
        return wrapper;
    }

    /** Count fields assigned to a signer for sidebar and footer summaries. */
    private countFields(signerId: string): number {
        let count = 0;
        for (const field of this.fields.values()) if (field.signerId === signerId) count += 1;
        return count;
    }

    /** Repaint positioned overlays without changing the PDF or rasterized canvases. */
    private renderFields(): void {
        for (const overlay of this.overlays.values()) overlay.replaceChildren();
        for (const field of this.fields.values()) {
            const overlay = this.overlays.get(field.page);
            const signer = this.signers.get(field.signerId);
            const definition = this.definitions.get(field.type);
            if (!overlay || !signer || !definition) continue;
            const box = node("div", "sign-builder__field");
            box.dataset.placedField = field.localId;
            box.tabIndex = 0; box.setAttribute("role", "button");
            box.setAttribute("aria-label", `${String(field.settings.label || definition.label)} — ${signer.roleLabel}`);
            box.classList.toggle("is-selected", field.localId === this.selectedField);
            box.style.setProperty("--signer-color", signer.color);
            this.positionBox(box, field);
            box.append(node("i", `sign-builder__field-icon ${definition.icon}`), node("span", "sign-builder__field-text", String(field.settings.label || definition.label)));
            if (field.required) box.append(node("span", "sign-builder__field-required", "*"));
            const handle = node("span", "sign-builder__resize"); handle.dataset.resizeField = "";
            box.append(handle); overlay.append(box);
        }
        this.updateCounts();
    }

    /** Apply normalized geometry so each placement survives zoom changes. */
    private positionBox(box: HTMLElement, field: PlacedField): void {
        box.style.left = `${field.x * 100}%`; box.style.top = `${field.y * 100}%`;
        box.style.width = `${field.width * 100}%`; box.style.height = `${field.height * 100}%`;
    }

    /** Refresh field summaries without replacing the role label input while the user types. */
    private updateCounts(): void {
        this.query("[data-field-count]").textContent = `${this.fields.size} ${t("fields placed")} · ${this.signers.size} ${t("roles")}`;
        for (const label of this.element.querySelectorAll<HTMLElement>("[data-signer-field-count]")) label.textContent = String(this.countFields(label.dataset.signerFieldCount!));
    }

    /** Select an existing placement and show its editable properties. */
    private selectField(id: string | null): void {
        this.selectedField = id;
        const field = this.fields.get(id || "");
        if (field) this.selectedSigner = field.signerId;
        this.activeTool = null;
        this.element.classList.remove("is-placing");
        for (const box of this.element.querySelectorAll<HTMLElement>("[data-placed-field]")) box.classList.toggle("is-selected", box.dataset.placedField === id);
        this.renderSigners();
    }

    /** Populate field settings from the selected placement and its server-defined capabilities. */
    private renderInspector(): void {
        const field = this.fields.get(this.selectedField || "");
        const inspector = this.query("[data-field-inspector]");
        inspector.hidden = !field;
        if (!field) return;
        this.query<HTMLInputElement>("[data-field-property='label']").value = String(field.settings.label || this.definitions.get(field.type)!.label);
        this.query<HTMLInputElement>("[data-field-property='required']").checked = field.required;
        const choices = this.query<HTMLSelectElement>("[data-field-property='role']");
        choices.replaceChildren();
        for (const signer of this.signers.values()) {
            const option = node("option", "", signer.roleLabel);
            option.value = signer.localId; option.selected = signer.localId === field.signerId;
            choices.append(option);
        }
        this.query("[data-options-label]").hidden = !this.definitions.get(field.type)!.supportsOptions;
        const values = field.settings.options;
        this.query<HTMLTextAreaElement>("[data-field-property='options']").value = Array.isArray(values) ? values.join("\n") : "";
    }

    /** Create a local field centered on a page click or drop using catalog default dimensions. */
    private placeField(type: string, overlay: HTMLElement, clientX: number, clientY: number): void {
        if (!this.ready || this.saving || !this.selectedSigner || !this.definitions.has(type)) return;
        const definition = this.definitions.get(type)!;
        const bounds = overlay.getBoundingClientRect();
        const id = crypto.randomUUID();
        const field: PlacedField = {
            localId: id, key: `field_${id.replace(/-/g, "")}`, type,
            signerId: this.selectedSigner, page: Number(overlay.dataset.pageOverlay),
            width: definition.width, height: definition.height,
            x: coordinate((clientX - bounds.left) / bounds.width - definition.width / 2, 0, 1 - definition.width),
            y: coordinate((clientY - bounds.top) / bounds.height - definition.height / 2, 0, 1 - definition.height),
            required: true, settings: { label: definition.label },
        };
        this.fields.set(id, field);
        this.renderFields(); this.selectField(id); this.changed();
    }

    /** Resolve the selected template without guessing when the PDF has several references. */
    private selectedDocumentTemplate(): DocumentTemplateOption | null {
        const selector = this.element.querySelector<HTMLSelectElement>("[data-document-template]");
        const id = selector ? selector.value : this.config.selectedDocumentTemplateId;
        for (const template of this.config.documentTemplates) if (template.id === id) return template;
        return null;
    }

    /** List readable revisions and retain the source of an existing or edited draft. */
    private renderLayoutRevisions(): void {
        const select = this.element.querySelector<HTMLSelectElement>("[data-layout-revision]");
        if (!select) return;
        const template = this.selectedDocumentTemplate();
        const revisions = template?.revisions ?? [];
        select.replaceChildren();
        const selected = revisions.some((revision: LayoutRevision): boolean => revision.id === this.sourceLayoutId);
        if (!selected) {
            const label = !template ? t("Choose document template") : !revisions.length ? t("No saved revisions")
                : this.config.preparationId || this.dirty || this.fields.size ? t("Current draft") : t("Choose revision");
            const placeholder = node("option", "", label);
            placeholder.value = "";
            select.append(placeholder);
        }
        for (const revision of revisions) {
            const option = node("option", "", `${t("Revision")} ${revision.revision}${revision.is_default ? ` · ${t("Default")}` : ""}`);
            option.value = revision.id;
            select.append(option);
        }
        select.value = selected ? this.sourceLayoutId! : "";
    }

    /** Keep layout actions aligned with selection, local fields, and server permissions. */
    private updateLayoutControls(): void {
        if (!this.element.querySelector("[data-layout-controls]")) return;
        const template = this.selectedDocumentTemplate();
        const templateSelector = this.element.querySelector<HTMLSelectElement>("[data-document-template]");
        if (templateSelector) templateSelector.disabled = this.saving || !this.ready;
        const revisionSelector = this.element.querySelector<HTMLSelectElement>("[data-layout-revision]");
        if (revisionSelector) revisionSelector.disabled = this.saving || !this.ready || !template?.revisions.length;
        this.query<HTMLButtonElement>("[data-action='save-layout']").disabled = this.saving || !this.ready || !template?.canSave || !this.fields.size;
    }

    /** Load a template-owned revision and preserve existing edits until replacement is confirmed. */
    private async loadLayoutRevision(layoutId: string, confirmReplacement: boolean = true): Promise<void> {
        const template = this.selectedDocumentTemplate();
        if (!template || this.saving || !this.ready) return;
        this.pendingLayout = null;
        this.query("[data-layout-confirmation]").hidden = true;
        this.saving = true; this.element.classList.add("is-saving");
        this.updateStatus();
        try {
            const response = await getSdk().client.request<DefaultLayoutResponse>(this.config.defaultLayoutUrl, {
                query: { document_template_id: template.id, layout_id: layoutId }, signal: this.lifecycle.signal,
            });
            if (this.lifecycle.signal.aborted) return;
            template.defaultLayoutId = response.default_layout_id; template.canSave = response.can_save;
            template.revisions = response.revisions;
            this.renderLayoutRevisions();
            if (!response.layout) { this.notify(t("This layout revision is no longer available."), MessageType.WARNING); return; }
            const replace = confirmReplacement && (this.fields.size > 0 || this.dirty || Boolean(this.config.preparationId));
            if (replace) {
                this.pendingLayout = response.layout;
                this.query<HTMLSelectElement>("[data-layout-revision]").value = response.layout.id;
                this.query("[data-layout-confirmation]").hidden = false;
            } else this.applyDefaultLayout(response.layout, confirmReplacement);
        } catch (error) {
            this.renderLayoutRevisions();
            if (!this.lifecycle.signal.aborted) this.notify(this.errorMessage(error, t("The layout revision could not be loaded.")));
        } finally {
            this.saving = false; this.element.classList.remove("is-saving"); this.updateStatus();
        }
    }

    /** Copy a layout into the preparation and notify only when the user explicitly loads it. */
    private applyDefaultLayout(layout: LayoutSnapshot, notify: boolean = true): void {
        const signers = new Map<string, Signer>();
        const roles = new Map<string, string>();
        const fields = new Map<string, PlacedField>();
        for (const role of layout.roles) {
            let existing: Signer | undefined;
            for (const signer of this.signers.values()) if (signer.roleKey === role.key) existing = signer;
            const id = existing?.localId || crypto.randomUUID();
            signers.set(id, {
                localId: id, roleKey: role.key, roleLabel: role.label, order: role.default_signing_order,
                color: signerColor(role.key),
            });
            roles.set(role.key, id);
        }
        for (const record of layout.fields) {
            const signerId = roles.get(record.role_key);
            if (!signerId || !this.definitions.has(record.field_type) || !this.pdfViewer?.hasPage(record.page_number)) {
                this.notify(t("This layout contains fields that do not fit this PDF. Your current fields have been kept."), MessageType.WARNING);
                this.pendingLayout = null; this.query("[data-layout-confirmation]").hidden = true;
                this.renderLayoutRevisions();
                return;
            }
            const id = crypto.randomUUID();
            fields.set(id, {
                localId: id, key: record.key, type: record.field_type, signerId,
                page: record.page_number, x: Number(record.x), y: Number(record.y),
                width: Number(record.width), height: Number(record.height), required: record.required,
                settings: structuredClone(record.settings),
            });
        }
        this.signers = signers; this.fields = fields; this.sourceLayoutId = layout.id;
        this.renderLayoutRevisions();
        this.selectedSigner = signers.keys().next().value || null; this.selectedField = null; this.activeTool = null;
        this.element.classList.remove("is-placing"); this.pendingLayout = null;
        this.query("[data-layout-confirmation]").hidden = true;
        this.query("[data-placement-hint]").textContent = t("Select a field to get started");
        this.renderSigners(); this.renderFields(); this.changed();
        if (notify) this.notify(`${t("Loaded revision")} ${layout.revision}. ${t("Review the field positions before signing.")}`, MessageType.INFO);
    }

    /** Serialize role definitions and geometry for both preparation and default-layout saves. */
    private placementPayload(): { roles: LayoutRole[]; fields: LayoutField[] } {
        const roles: LayoutRole[] = [];
        const fields: LayoutField[] = [];
        for (const signer of this.signers.values()) roles.push({ key: signer.roleKey, label: signer.roleLabel.trim(), default_signing_order: signer.order });
        for (const field of this.fields.values()) fields.push({
            key: field.key, role_key: this.signers.get(field.signerId)!.roleKey, field_type: field.type,
            required: field.required, page_number: field.page, x: field.x, y: field.y,
            width: field.width, height: field.height, settings: structuredClone(field.settings),
        });
        return { roles, fields };
    }

    /** Save role placeholders and placements atomically without persisting recipient identities. */
    private async saveDefaultLayout(): Promise<void> {
        const template = this.selectedDocumentTemplate();
        if (!template?.canSave || this.saving || !this.ready || !this.fields.size || !this.validateRoles()) return;
        const { roles, fields } = this.placementPayload();
        this.saving = true; this.element.classList.add("is-saving");
        this.updateStatus();
        try {
            const response = await getSdk().client.request<DefaultLayoutResponse>(this.config.defaultLayoutUrl, {
                method: "POST", signal: this.lifecycle.signal,
                body: JSON.stringify({ document_template_id: template.id, expected_layout_id: template.defaultLayoutId, roles, fields }),
            });
            if (this.lifecycle.signal.aborted) return;
            template.defaultLayoutId = response.default_layout_id; template.canSave = response.can_save;
            template.revisions = response.revisions;
            this.sourceLayoutId = response.layout?.id || this.sourceLayoutId;
            this.renderLayoutRevisions();
            this.notify(`${t("Default layout saved")} · ${t("Revision")} ${response.layout?.revision}`, MessageType.SUCCESS);
            this.pendingLayout = null; this.query("[data-layout-confirmation]").hidden = true;
            this.changed();
        } catch (error) {
            if (!this.lifecycle.signal.aborted) this.notify(this.errorMessage(error, t("The default layout could not be saved.")));
        } finally {
            this.saving = false; this.element.classList.remove("is-saving"); this.updateStatus();
        }
    }

    /** Route toolbar, signer, palette, and selection actions through one delegated listener. */
    private onClick = (event: MouseEvent): void => {
        if (!(event.target instanceof Element) || this.saving || this.openingAction || !this.ready) return;
        const target = event.target;
        const send = target.closest<HTMLButtonElement>(`#${this.element.id}-send`);
        if (send) { void this.openActionModal(send, "send"); return; }
        const self = target.closest<HTMLButtonElement>(`#${this.element.id}-sign-myself`);
        if (self) { void this.openActionModal(self, "self"); return; }
        const signer = target.closest<HTMLElement>("[data-select-signer]");
        if (signer) {
            this.selectedSigner = signer.dataset.selectSigner!; this.selectedField = null;
            this.renderFields(); this.renderSigners(); return;
        }
        const remove = target.closest<HTMLElement>("[data-remove-signer]");
        if (remove) { this.removeSigner(remove.dataset.removeSigner!); return; }
        const tool = target.closest<HTMLElement>("[data-field-tool]");
        if (tool) {
            if (!this.selectedSigner) { this.notify(t("Add a role first.")); return; }
            this.activeTool = this.activeTool === tool.dataset.fieldTool ? null : tool.dataset.fieldTool!;
            this.element.classList.toggle("is-placing", Boolean(this.activeTool));
            this.renderPalette();
            this.query("[data-placement-hint]").textContent = this.activeTool ? t("Click a page to place the selected field") : t("Select a field to get started");
            return;
        }
        const action = target.closest<HTMLElement>("[data-action]")?.dataset.action;
        if (action === "save-layout") { void this.saveDefaultLayout(); return; }
        if (action === "confirm-layout" && this.pendingLayout) { this.applyDefaultLayout(this.pendingLayout); return; }
        if (action === "cancel-layout") { this.pendingLayout = null; this.query("[data-layout-confirmation]").hidden = true; this.renderLayoutRevisions(); return; }
        if (action === "add-signer") this.addSigner();
        if (action === "delete-field") this.removeField();
        if (action === "zoom-in" || action === "zoom-out") this.zoom((this.pdfViewer?.scale ?? 1) + (action === "zoom-in" ? .25 : -.25));
        if (action === "next-page" || action === "previous-page") this.goToPage(Number(this.query<HTMLInputElement>("[data-current-page]").value) + (action === "next-page" ? 1 : -1));
        const overlay = target.closest<HTMLElement>("[data-page-overlay]");
        if (overlay && !target.closest("[data-placed-field]")) {
            if (this.activeTool) this.placeField(this.activeTool, overlay, event.clientX, event.clientY);
            else this.selectField(null);
        }
    };

    /** Update role labels, order, and field settings without saving on every keystroke. */
    private onInput = (event: Event): void => {
        const input = event.target;
        if (!(input instanceof HTMLInputElement || input instanceof HTMLTextAreaElement) || this.saving || !this.ready) return;
        if (input.hasAttribute("data-draft-title")) { this.changed(); return; }
        const signer = this.signers.get(input.dataset.signerId || "");
        if (signer) {
            const property = input.dataset.signerProperty;
            if (property === "roleLabel") signer.roleLabel = input.value;
            if (property === "order") signer.order = Math.max(1, Math.trunc(Number(input.value) || 1));
            const heading = this.element.querySelector<HTMLElement>(`[data-signer-heading='${signer.localId}']`);
            if (heading) heading.textContent = signer.roleLabel;
            const orderLabel = this.element.querySelector<HTMLElement>(`[data-signer-order='${signer.localId}']`);
            if (orderLabel) orderLabel.textContent = `${t("Signing order")} ${signer.order}`;
            this.query("[data-active-signer]").textContent = signer.roleLabel;
            this.renderFields();
            this.renderInspector();
            this.changed();
        }
        const field = this.fields.get(this.selectedField || "");
        if (!field) return;
        if (input.dataset.fieldProperty === "label") field.settings.label = input.value;
        else if (input.dataset.fieldProperty === "options") {
            const choices: string[] = [];
            for (const line of input.value.split("\n")) if (line.trim()) choices.push(line.trim());
            field.settings.options = choices;
        } else return;
        this.renderFields(); this.changed();
    };

    /** Apply selected field ownership, required flags, zoom, and page navigation changes. */
    private onChange = (event: Event): void => {
        const input = event.target;
        if (!(input instanceof HTMLSelectElement || input instanceof HTMLInputElement) || this.saving || !this.ready) return;
        if (input.hasAttribute("data-document-template")) {
            this.pendingLayout = null;
            this.query("[data-layout-confirmation]").hidden = true;
            this.renderLayoutRevisions(); this.updateLayoutControls();
            const template = this.selectedDocumentTemplate();
            if (!this.config.preparationId && !this.dirty && !this.fields.size && template?.defaultLayoutId) {
                void this.loadLayoutRevision(template.defaultLayoutId, false);
            }
            return;
        }
        if (input.hasAttribute("data-layout-revision")) {
            if (input.value && input.value !== this.sourceLayoutId) void this.loadLayoutRevision(input.value);
            else {
                this.pendingLayout = null;
                this.query("[data-layout-confirmation]").hidden = true;
                this.renderLayoutRevisions();
            }
            return;
        }
        if (input.hasAttribute("data-zoom")) {
            if (input.value === "fit") this.pdfViewer?.fitToWidth();
            else this.pdfViewer?.zoom(Number(input.value));
            return;
        }
        if (input.hasAttribute("data-current-page")) { this.goToPage(Number(input.value)); return; }
        const field = this.fields.get(this.selectedField || "");
        if (!field) return;
        if (input.dataset.fieldProperty === "role" && this.signers.has(input.value)) {
            field.signerId = input.value; this.selectedSigner = input.value; this.renderSigners();
        } else if (input.dataset.fieldProperty === "required" && input instanceof HTMLInputElement) field.required = input.checked;
        else return;
        this.renderFields(); this.changed();
    };

    /** Begin native dragging for a server-defined palette item. */
    private onDragStart = (event: DragEvent): void => {
        const tool = (event.target as Element)?.closest<HTMLElement>("[data-field-tool]");
        if (!tool || !event.dataTransfer || !this.selectedSigner || this.saving || !this.ready) { event.preventDefault(); return; }
        event.dataTransfer.setData(DRAG_TYPE, tool.dataset.fieldTool!);
        event.dataTransfer.effectAllowed = "copy";
    };

    /** Mark PDF surfaces that can accept palette field drops. */
    private onDragOver = (event: DragEvent): void => {
        const overlay = (event.target as Element)?.closest<HTMLElement>("[data-page-overlay]");
        if (!overlay || !event.dataTransfer?.types.includes(DRAG_TYPE)) return;
        event.preventDefault(); event.dataTransfer.dropEffect = "copy";
        overlay.classList.add("is-drop-target");
    };

    /** Remove a hover treatment when dragging leaves a PDF surface. */
    private onDragLeave = (event: DragEvent): void => {
        const overlay = (event.target as Element)?.closest<HTMLElement>("[data-page-overlay]");
        if (overlay && !(event.relatedTarget instanceof Node && overlay.contains(event.relatedTarget))) overlay.classList.remove("is-drop-target");
    };

    /** Translate a palette drop into a signer-owned normalized placement. */
    private onDrop = (event: DragEvent): void => {
        const overlay = (event.target as Element)?.closest<HTMLElement>("[data-page-overlay]");
        const type = event.dataTransfer?.getData(DRAG_TYPE);
        if (!overlay || !type) return;
        event.preventDefault(); overlay.classList.remove("is-drop-target");
        this.placeField(type, overlay, event.clientX, event.clientY);
    };

    /** Clear all drag hover treatments when native dragging ends outside the builder. */
    private onDragEnd = (): void => {
        for (const overlay of this.overlays.values()) overlay.classList.remove("is-drop-target");
    };

    /** Capture an existing placement for moving or corner resizing without native PDF interactions. */
    private onPointerDown = (event: PointerEvent): void => {
        if (!(event.target instanceof Element) || event.button !== 0 || this.saving || !this.ready) return;
        const box = event.target.closest<HTMLElement>("[data-placed-field]");
        const field = this.fields.get(box?.dataset.placedField || "");
        if (!box || !field) return;
        event.preventDefault(); this.selectField(field.localId);
        box.focus({ preventScroll: true });
        this.gesture = {
            field, element: box, overlay: box.parentElement!, resize: Boolean(event.target.closest("[data-resize-field]")),
            pointerId: event.pointerId, startX: event.clientX, startY: event.clientY,
            x: field.x, y: field.y, width: field.width, height: field.height,
        };
        box.setPointerCapture(event.pointerId);
    };

    /** Move or resize one box directly so pointer capture survives the whole gesture. */
    private onPointerMove = (event: PointerEvent): void => {
        const gesture = this.gesture;
        if (!gesture || event.pointerId !== gesture.pointerId) return;
        const bounds = gesture.overlay.getBoundingClientRect();
        const dx = (event.clientX - gesture.startX) / bounds.width;
        const dy = (event.clientY - gesture.startY) / bounds.height;
        if (gesture.resize) {
            gesture.field.width = coordinate(gesture.width + dx, .015, 1 - gesture.field.x);
            gesture.field.height = coordinate(gesture.height + dy, .015, 1 - gesture.field.y);
        } else {
            gesture.field.x = coordinate(gesture.x + dx, 0, 1 - gesture.field.width);
            gesture.field.y = coordinate(gesture.y + dy, 0, 1 - gesture.field.height);
        }
        this.positionBox(gesture.element, gesture.field);
    };

    /** End a captured gesture and mark its normalized result as unsaved. */
    private onPointerUp = (event: PointerEvent): void => {
        if (!this.gesture || event.pointerId !== this.gesture.pointerId) return;
        const gesture = this.gesture;
        this.gesture = null;
        if (gesture.element.hasPointerCapture(event.pointerId)) gesture.element.releasePointerCapture(event.pointerId);
        if (gesture.x !== gesture.field.x || gesture.y !== gesture.field.y || gesture.width !== gesture.field.width || gesture.height !== gesture.field.height) this.changed();
    };

    /** Provide keyboard placement, arrow movement, and deletion outside text inputs. */
    private onKeyDown = (event: KeyboardEvent): void => {
        if (!this.ready || this.saving) return;
        if (event.key === "Escape") { this.activeTool = null; this.selectField(null); return; }
        if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement) return;
        const field = this.fields.get(this.selectedField || "");
        if (field && ["Delete", "Backspace"].includes(event.key)) { event.preventDefault(); this.removeField(); return; }
        if (field && event.key.startsWith("Arrow")) {
            event.preventDefault(); const step = event.shiftKey ? .02 : .005;
            if (event.key === "ArrowLeft") field.x = coordinate(field.x - step, 0, 1 - field.width);
            if (event.key === "ArrowRight") field.x = coordinate(field.x + step, 0, 1 - field.width);
            if (event.key === "ArrowUp") field.y = coordinate(field.y - step, 0, 1 - field.height);
            if (event.key === "ArrowDown") field.y = coordinate(field.y + step, 0, 1 - field.height);
            this.renderFields(); this.query<HTMLElement>(`[data-placed-field='${field.localId}']`)?.focus({ preventScroll: true }); this.changed(); return;
        }
        if (event.key === "Enter" && this.activeTool && event.target instanceof HTMLElement && event.target.hasAttribute("data-page-overlay")) {
            event.preventDefault(); const bounds = event.target.getBoundingClientRect();
            this.placeField(this.activeTool, event.target, bounds.left + bounds.width / 2, bounds.top + bounds.height / 2);
        }
    };

    /** Remove one local field; the complete preparation is reconciled on Save. */
    private removeField(): void {
        const field = this.fields.get(this.selectedField || "");
        if (!field) return;
        this.fields.delete(field.localId); this.selectedField = null;
        this.renderFields(); this.renderSigners(); this.changed();
    }

    /** Remove a generic role and its local placements before the next preparation save. */
    private removeSigner(id: string): void {
        const signer = this.signers.get(id);
        if (!signer) return;
        for (const field of this.fields.values()) if (field.signerId === id) {
            this.fields.delete(field.localId);
        }
        this.signers.delete(id); this.selectedSigner = this.signers.keys().next().value || null;
        this.selectedField = null;
        this.renderFields(); this.renderSigners(); this.changed();
    }

    /** Change display zoom through the shared viewer without changing saved field geometry. */
    private zoom(scale: number): void { this.pdfViewer?.zoom(scale); }

    /** Scroll to a bounded page number while preserving the current zoom. */
    private goToPage(number: number): void {
        const page = Math.max(1, Math.min(this.pdfViewer?.pageCount ?? 1, Math.round(number) || 1));
        this.overlays.get(page)?.parentElement?.scrollIntoView({ block: "start", behavior: "smooth" });
        this.query<HTMLInputElement>("[data-current-page]").value = String(page);
    }

    /** Keep page navigation aligned with the page nearest the viewport's upper section. */
    private onScroll = (): void => {
        const top = this.query("[data-viewport]").getBoundingClientRect().top + 80;
        let closest = 1; let distance = Infinity;
        for (const [number, overlay] of this.overlays) {
            const candidate = Math.abs(overlay.getBoundingClientRect().top - top);
            if (candidate < distance) { closest = number; distance = candidate; }
        }
        this.query<HTMLInputElement>("[data-current-page]").value = String(closest);
    };

    /** Require named roles without asking for the identities of future recipients. */
    private validateRoles(): boolean {
        if (!this.signers.size) { this.notify(t("Add at least one role.")); return false; }
        for (const signer of this.signers.values()) {
            if (!signer.roleLabel.trim()) {
                this.selectedSigner = signer.localId; this.renderSigners();
                this.notify(t("Give every signer role a name."));
                this.query<HTMLInputElement>(`[data-signer-id='${signer.localId}'][data-signer-property='roleLabel']`)?.focus();
                return false;
            }
        }
        return true;
    }

    /** Require a request title and named signer roles before continuing. */
    private validateDraft(): boolean {
        if (!this.query<HTMLInputElement>("[data-draft-title]").value.trim()) {
            this.notify(t("Give this signature request a title."));
            this.query<HTMLInputElement>("[data-draft-title]").focus();
            return false;
        }
        return this.validateRoles();
    }

    /** Save pending edits and expose the snapshot required by a containing wizard. */
    public async saveForWizard(): Promise<{ id: string; revision: number } | null> {
        if (!this.ready || this.saving || !this.validateDraft()) return null;
        if ((this.dirty || !this.config.preparationId) && !await this.saveDraft()) return null;
        return this.config.preparationId ? { id: this.config.preparationId, revision: this.preparationRevision } : null;
    }

    /** Persist one atomic preparation through the SDK without creating a signature request. */
    private async saveDraft(): Promise<boolean> {
        if (this.saving || !this.ready || !this.config.canSave || !this.validateDraft()) return false;
        this.saving = true; this.element.classList.add("is-saving");
        this.updateStatus();
        try {
            const title = this.query<HTMLInputElement>("[data-draft-title]").value.trim();
            const response = await getSdk().client.request<PreparationSnapshot>(this.config.preparationUrl, {
                method: "POST", signal: this.lifecycle.signal,
                body: JSON.stringify({
                    id: this.config.preparationId || this.newPreparationId, revision: this.preparationRevision,
                    title, source_layout: this.sourceLayoutId, ...this.placementPayload(),
                }),
            });
            if (this.lifecycle.signal.aborted) return false;
            this.config.preparationId = response.id;
            this.preparationRevision = response.revision;
            this.dirty = false;
            return true;
        } catch (error) {
            if (!this.lifecycle.signal.aborted) this.notify(this.errorMessage(error, t("The preparation could not be saved. Please try again.")));
            return false;
        } finally {
            this.saving = false; this.element.classList.remove("is-saving"); this.updateStatus();
        }
    }

    /** Save the preparation before opening the sender or self-signer in an owned modal. */
    private async openActionModal(opener: HTMLElement, mode: "send" | "self"): Promise<void> {
        if (this.openingAction || !this.validateDraft()) return;
        this.openingAction = true;
        this.updateStatus();
        const controller = new AbortController();
        /** Cancel the HTML request when either the builder or its child modal is closed. */
        const abortRequest = (): void => controller.abort();
        this.lifecycle.signal.addEventListener("abort", abortRequest, { once: true });
        try {
            if ((this.dirty || !this.config.preparationId) && !await this.saveDraft()) return;
            if (this.lifecycle.signal.aborted || !this.config.preparationId) return;
            const modal = createModalInstance("bloomerp-general-use-modal", opener);
            this.actionModal = modal;
            modal.setTitle(mode === "self" ? t("Sign document") : t("Send signature request"));
            modal.setSize(mode === "self" ? "xl" : "lg");
            modal.setPadding("p-4");
            modal.element.addEventListener("bloomerp:modal-closed", abortRequest, { once: true, signal: controller.signal });
            const body = modal.getBodyElement()!;
            const loading = node("div", "flex items-center gap-2 py-4 text-sm text-muted", t("Loading…"));
            loading.setAttribute("role", "status");
            body.replaceChildren(loading);
            modal.open();
            try {
                const html = await getSdk().client.request<string>(mode === "self" ? this.config.selfSignUrl : this.config.sendUrl, {
                    query: { preparation_id: this.config.preparationId },
                    headers: { Accept: "text/html" }, signal: controller.signal,
                });
                if (controller.signal.aborted || !body.isConnected) return;
                htmx.swap(body, html, { swapStyle: "innerHTML", swapDelay: 0, settleDelay: 0 });
            } catch (error) {
                if (!controller.signal.aborted && body.isConnected) {
                    modal.close();
                    this.notify(this.errorMessage(error, t("The signing form could not be loaded. Please try again.")));
                }
            }
        } catch (error) {
            if (!this.lifecycle.signal.aborted) this.notify(this.errorMessage(error, t("The signing form could not be opened.")));
        } finally {
            controller.abort();
            this.lifecycle.signal.removeEventListener("abort", abortRequest);
            this.openingAction = false;
            if (!this.lifecycle.signal.aborted) this.updateStatus();
        }
    }

    /** Mark local preparation changes without implying they have already reached the server. */
    private changed(): void { this.dirty = true; this.updateStatus(); }

    /** Keep document editing and signing actions aligned with loading and saving state. */
    private updateStatus(): void {
        this.query<HTMLInputElement>("[data-draft-title]").disabled = !this.ready || this.saving;
        for (const action of ["send", "sign-myself"]) {
            const button = this.element.querySelector<HTMLButtonElement>(`#${this.element.id}-${action}`);
            if (button) button.disabled = !this.ready || this.saving || this.openingAction
                || (!this.config.canSave && (this.dirty || !this.config.preparationId));
        }
        this.element.setAttribute("aria-busy", String(this.saving || this.openingAction || !this.ready));
        this.updateLayoutControls();
    }

    /** Show plain-text feedback through the shared toast utility without interpreting API text as HTML. */
    private notify(message: string, type: MessageType = MessageType.ERROR): void {
        showMessage(node("span", "", message).innerHTML, type);
    }

    /** Prefer actionable API error text while retaining a safe fallback for unknown failures. */
    private errorMessage(error: unknown, fallback: string): string {
        if (error instanceof BloomerpHttpError && error.status >= 500) return fallback;
        if (!(error instanceof Error) || /<!doctype|<html/i.test(error.message) || error.message.length > 400) return fallback;
        return error.message;
    }

    /** Release the PDF worker when HTMX removes this component or one of its ancestors. */
    private onCleanup = (event: Event): void => {
        const target = (event as CustomEvent<{ elt?: HTMLElement }>).detail?.elt;
        if (target?.contains(this.element)) this.destroy();
    };

    /** Cancel listeners, in-flight SDK work, rendering, observers, and the owned PDF worker. */
    public override destroy(): void {
        this.lifecycle.abort();
        this.actionModal?.destroy(); this.actionModal = null;
        this.pdfViewer?.destroy(); this.pdfViewer = null;
        this.overlays.clear(); this.gesture = null;
        super.destroy();
    }
}
