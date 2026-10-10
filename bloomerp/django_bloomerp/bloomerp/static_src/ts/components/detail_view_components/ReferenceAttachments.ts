import htmx from "htmx.org";
import BaseComponent, { getComponent } from "../BaseComponent";
import { BloomerpTextEditor } from "../text_editor/BloomerpTextEditor";
import type { ReferenceTarget } from "../text_editor/nodes/ReferenceNode";
import { uploadReferenceFile } from "../text_editor/utils/referencePicker";
import { getSdk } from "@/sdk/getSdk";
import { attachObjectPreviewTooltip } from "@/utils/objectPreviewTooltip";
import { t } from "@/utils/i18n";

/** Own manual attachment drafts and occurrence chips for exactly one CRUD form. */
export default class ReferenceAttachments extends BaseComponent {
    private readonly lifecycle = new AbortController();
    private readonly searches = new Map<string, AbortController>();
    private readonly timers = new Map<string, ReturnType<typeof setTimeout>>();
    private previewCleanups: Array<() => void> = [];
    private form: HTMLFormElement | null = null;
    private entries: ReferenceTarget[] = [];
    private initialManual: ReferenceTarget[] = [];
    private input: HTMLInputElement | null = null;
    private canChange = false;
    private avatarFiles: File[] = [];
    private readonly referenceFields = new Set<number>();

    /** Load saved state and subscribe only to this form's editor changes. */
    public initialize(): void {
        this.form = this.element.closest("form");
        this.canChange = this.element.dataset.canChange === "true";
        const script = this.element.querySelector<HTMLScriptElement>("script[type='application/json']");
        this.entries = JSON.parse(script?.textContent ?? "[]") as ReferenceTarget[];
        this.initialManual = this.entries.filter(this.isManual);
        this.input = this.element.querySelector<HTMLInputElement>('[name="object_references"]');
        this.form?.addEventListener("bloomerp:references-changed", this.onEditorChange, { signal: this.lifecycle.signal });
        this.form?.addEventListener("click", this.onClick, { signal: this.lifecycle.signal });
        this.form?.addEventListener("submit", this.onSubmit, { signal: this.lifecycle.signal });
        this.form?.addEventListener("focusin", this.onSearchFocus, { signal: this.lifecycle.signal });
        this.form?.addEventListener("input", this.onSearchInput, { signal: this.lifecycle.signal });
        const avatar = this.form?.querySelector<HTMLElement>("[data-reference-avatar]");
        if (avatar) avatar.hidden = !this.form?.querySelector('input[type="file"][name="avatar"]:not(:disabled)');
        this.form?.querySelector<HTMLInputElement>("[data-reference-avatar-input]")?.addEventListener("change", this.onAvatarChange, { signal: this.lifecycle.signal });
        this.synchronizeEditors();
    }
    /** Distinguish explicit attachments from editor occurrences. */
    private isManual = (entry: ReferenceTarget): boolean => !entry.field_id && !entry.occurrence_id;
    /** Submit explicit attachments and complete occurrence state for displayed editable fields. */
    private serialize(): void {
        const fields: Record<string, ReferenceTarget[]> = {};
        for (const fieldId of this.referenceFields) fields[String(fieldId)] = this.entries.filter(this.inField.bind(this, fieldId));
        if (this.input) this.input.value = JSON.stringify({ manual: this.entries.filter(this.isManual), fields });
    }
    /** Match occurrences to one explicitly submitted field scope. */
    private inField(fieldId: number, entry: ReferenceTarget): boolean { return entry.field_id === fieldId; }
    /** Refresh occurrence chips only for editors actually present in this form. */
    private synchronizeEditors(): void {
        this.referenceFields.clear();
        for (const host of this.form?.querySelectorAll<HTMLElement>('[bloomerp-component="bloomerp-text-editor"]') ?? []) {
            if (host.closest("form") !== this.form) continue;
            const fieldId = Number(host.dataset.applicationFieldId || host.closest<HTMLElement>("[data-application-field-id]")?.dataset.applicationFieldId);
            if (!fieldId) continue;
            if (host.dataset.disabled === "true") continue;
            const editor = getComponent(host);
            if (!(editor instanceof BloomerpTextEditor)) continue;
            this.referenceFields.add(fieldId);
            const references = editor.getReferences().map<ReferenceTarget>(this.withPresentation.bind(this));
            this.entries = this.entries.filter(this.notInField.bind(this, fieldId));
            for (const reference of references) this.entries.push({ ...reference, field_id: fieldId });
        }
        this.serialize();
        this.render();
    }
    /** Retain server-provided presentation when an editor restores identity-only HTML. */
    private withPresentation(reference: ReferenceTarget): ReferenceTarget {
        const existing = this.entries.find(this.matchesTarget.bind(this, reference));
        return { ...reference, icon: reference.icon ?? existing?.icon, url: reference.url ?? existing?.url };
    }
    /** Match object identities independently of their manual or inline occurrence. */
    private matchesTarget(reference: ReferenceTarget, entry: ReferenceTarget): boolean {
        return reference.kind === entry.kind && reference.target_id === entry.target_id && reference.content_type_id === entry.content_type_id;
    }
    /** Release previews before replacing their anchors or destroying this component. */
    private clearPreviews(): void {
        for (const cleanup of this.previewCleanups) cleanup();
        this.previewCleanups = [];
    }
    /** Preserve references from fields outside the currently displayed editor. */
    private notInField(fieldId: number, entry: ReferenceTarget): boolean { return entry.field_id !== fieldId; }
    /** Ignore events emitted by separate comment or nested-object forms. */
    private onEditorChange = (event: Event): void => {
        if ((event.target as HTMLElement).closest("form") === this.form) this.synchronizeEditors();
    };
    /** Recompute the current payload immediately before HTMX collects the form. */
    private onSubmit = (): void => { this.synchronizeEditors(); };
    /** Route attachment controls and chip removal within the owning form. */
    private onClick = (event: MouseEvent): void => {
        const target = event.target as HTMLElement;
        if (target.closest("form") !== this.form) return;
        const preview = target.closest<HTMLElement>("[data-reference-file-preview]");
        if (preview) this.closeDropdown(preview);
        if (!this.canChange) return;
        if (target.closest("[data-reference-avatar]")) this.uploadAvatar();
        if (target.closest("[data-reference-upload]")) { this.closeDropdown(target); this.upload(); }
        if (target.closest("[data-reference-create-label]")) {
            const input = target.closest("[data-reference-search-panel]")?.querySelector<HTMLInputElement>("[data-reference-search]");
            if (input?.value.trim()) { this.closeDropdown(target); void this.createLabel(input.value.trim()); }
        }
        const remove = target.closest<HTMLElement>("[data-reference-remove]");
        if (remove) { event.preventDefault(); this.remove(Number(remove.dataset.referenceRemove)); }
        if (target.closest("#object-crud-container-reset-button")) {
            this.entries = [...this.entries.filter(this.isInline), ...structuredClone(this.initialManual)];
            this.synchronizeEditors();
            this.changed();
        }
    };
    /** Identify editor-owned entries when restoring manual attachments. */
    private isInline = (entry: ReferenceTarget): boolean => Boolean(entry.field_id);
    /** Load a submenu's available targets when its search field receives focus. */
    private onSearchFocus = (event: FocusEvent): void => {
        const input = event.target;
        if (input instanceof HTMLInputElement && input.dataset.referenceSearch && input.closest("form") === this.form && this.canChange) void this.loadDropdown(input);
    };
    /** Debounce target searches while retaining the existing dropdown interaction. */
    private onSearchInput = (event: Event): void => {
        const input = event.target;
        if (!(input instanceof HTMLInputElement) || !input.dataset.referenceSearch || input.closest("form") !== this.form || !this.canChange) return;
        const kind = input.dataset.referenceSearch;
        clearTimeout(this.timers.get(kind));
        this.searches.get(kind)?.abort();
        this.timers.set(kind, setTimeout(this.loadDropdown.bind(this, input), 200));
    };
    /** Render readable search results and discard requests superseded by newer input. */
    private async loadDropdown(input: HTMLInputElement): Promise<void> {
        const kind = input.dataset.referenceSearch!;
        const panel = input.closest("[data-reference-search-panel]");
        const results = panel?.querySelector<HTMLElement>("[data-reference-results]");
        if (!results || this.lifecycle.signal.aborted) return;
        this.searches.get(kind)?.abort();
        const controller = new AbortController();
        this.searches.set(kind, controller);
        this.showSearchStatus(results, t("Loading…"));
        const create = panel?.querySelector<HTMLButtonElement>("[data-reference-create-label]");
        if (create) { create.hidden = !input.value.trim(); create.textContent = `${t("Create label")}: ${input.value.trim()}`; }
        try {
            const result = await getSdk().client.request<{ items: ReferenceTarget[] }>(this.element.dataset.referenceSearchUrl!, { query: { kind, q: input.value }, signal: controller.signal });
            if (controller.signal.aborted) return;
            results.replaceChildren();
            let previousModel: number | undefined;
            for (const target of result.items) {
                if (kind === "object" && target.content_type_id !== previousModel) {
                    const heading = document.createElement("div");
                    heading.className = "border-t border-gray-200 px-4 py-2 text-xs font-semibold text-gray-500";
                    heading.textContent = target.model_label ?? t("Objects");
                    results.append(heading);
                    previousModel = target.content_type_id;
                }
                const button = document.createElement("button");
                button.type = "button";
                button.setAttribute("role", "menuitem");
                button.className = "w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-100 focus:bg-gray-100";
                if (target.icon) {
                    const icon = document.createElement("i");
                    icon.className = `${target.icon} mr-2`;
                    icon.setAttribute("aria-hidden", "true");
                    button.append(icon);
                }
                button.append(document.createTextNode(target.label));
                button.addEventListener("click", this.chooseDropdownTarget.bind(this, button, target), { signal: this.lifecycle.signal });
                results.append(button);
            }
            if (!result.items.length) this.showSearchStatus(results, t("No results"));
        } catch (error) {
            if (!controller.signal.aborted) this.showSearchStatus(results, t("Search could not be loaded"));
        }
    }
    /** Give loading, empty, and error states consistent muted menu styling. */
    private showSearchStatus(results: HTMLElement, message: string): void {
        const status = document.createElement("div");
        status.className = "px-4 py-2 text-sm text-gray-500";
        status.setAttribute("role", "status");
        status.textContent = message;
        results.replaceChildren(status);
    }
    /** Track uploads from an avatar control outside the visible field layout. */
    private onAvatarChange = (event: Event): void => {
        const input = event.target as HTMLInputElement;
        const previous = [...this.avatarFiles];
        this.avatarFiles = Array.from(input.files ?? []);
        const component = this;
        /** Restore the previous avatar selection through the shared form undo history. */
        function undoAvatar(): void {
            const transfer = new DataTransfer();
            for (const file of previous) transfer.items.add(file);
            input.files = transfer.files;
            component.avatarFiles = [...previous];
            component.changed();
        }
        this.form?.dispatchEvent(new CustomEvent("bloomerp:attachments-changed", { bubbles: true, detail: { dirty: this.isDirty(), undo: undoAvatar } }));
    };
    /** Include pending avatar selections in the attachment save-button state. */
    private isDirty(): boolean {
        return this.avatarFiles.length > 0 || JSON.stringify(this.entries.filter(this.isManual)) !== JSON.stringify(this.initialManual);
    }
    /** Attach a selected target and close its owning dropdown and submenus. */
    private chooseDropdownTarget(button: HTMLButtonElement, target: ReferenceTarget): void {
        this.add(target);
        this.closeDropdown(button);
    }
    /** Use the shared dropdown's dismissal event after an attachment action. */
    private closeDropdown(target: HTMLElement): void {
        target.dispatchEvent(new CustomEvent("dropdown-close", { bubbles: true }));
    }
    /** Keep manual attachments unique while retaining separate inline occurrences. */
    private add(target: ReferenceTarget): void {
        if (this.entries.some(this.sameManualTarget.bind(this, target))) return;
        const previous = structuredClone(this.entries.filter(this.isManual));
        this.entries.push({ ...target, field_id: undefined, occurrence_id: undefined });
        this.serialize(); this.render(); this.changed(previous);
    }
    /** Compare explicit attachment identity without conflating editor occurrences. */
    private sameManualTarget(target: ReferenceTarget, entry: ReferenceTarget): boolean { return this.isManual(entry) && entry.kind === target.kind && entry.target_id === target.target_id && (target.kind !== "object" || entry.content_type_id === target.content_type_id); }
    /** Remove an explicit attachment or request removal of one matching editor occurrence. */
    private remove(index: number): void {
        const entry = this.entries[index];
        if (!entry) return;
        if (entry.occurrence_id) {
            for (const host of this.form?.querySelectorAll<HTMLElement>('[bloomerp-component="bloomerp-text-editor"]') ?? []) {
                const fieldId = Number(host.dataset.applicationFieldId || host.closest<HTMLElement>("[data-application-field-id]")?.dataset.applicationFieldId);
                if (fieldId !== entry.field_id || host.closest("form") !== this.form) continue;
                const editor = getComponent(host);
                if (editor instanceof BloomerpTextEditor) editor.removeReferenceOccurrence(entry.occurrence_id);
            }
            this.synchronizeEditors();
        } else {
            const previous = structuredClone(this.entries.filter(this.isManual));
            this.entries.splice(index, 1); this.serialize(); this.render();
            this.changed(previous);
            return;
        }
        this.changed();
    }
    /** Mark manual edits as pending so the existing save controls remain available. */
    private changed(previous?: ReferenceTarget[]): void {
        const component = this;
        /** Restore manual state through the CRUD container's shared undo history. */
        function undoAttachments(): void {
            component.entries = [...component.entries.filter(component.isInline), ...structuredClone(previous ?? [])];
            component.synchronizeEditors();
            component.changed();
        }
        this.form?.dispatchEvent(new CustomEvent("bloomerp:attachments-changed", { bubbles: true, detail: { dirty: this.isDirty(), undo: previous ? undoAttachments : undefined } }));
    }
    /** Render reference chips and one compact dropdown for all attached files. */
    private render(): void {
        this.element.hidden = this.entries.length === 0;
        const section = this.element.closest<HTMLElement>("[data-layout-header-section-2]");
        if (section) section.hidden = this.entries.length === 0;
        const chips = this.element.querySelector<HTMLElement>("[data-reference-chips]");
        if (!chips) return;
        this.clearPreviews();
        chips.replaceChildren();
        for (const [index, entry] of this.entries.entries()) {
            if (entry.kind === "file") continue;
            const chip = document.createElement("span");
            chip.className = "badge badge-secondary gap-2";
            const label = document.createElement(entry.kind === "object" && entry.url ? "a" : "span");
            label.className = "inline-flex items-center gap-2";
            if (entry.kind === "object") {
                const icon = document.createElement("i");
                icon.className = entry.icon ?? "fa-solid fa-cube";
                icon.setAttribute("aria-hidden", "true");
                label.append(icon);
                if (label instanceof HTMLAnchorElement) label.href = entry.url!;
                if (entry.content_type_id) {
                    this.previewCleanups.push(attachObjectPreviewTooltip({
                        element: label,
                        objectId: entry.target_id,
                        contentTypeId: String(entry.content_type_id),
                    }));
                }
            }
            label.append(document.createTextNode(entry.label));
            chip.append(label);
            chip.title = entry.field_id ? `${t("Field reference")} ${entry.field_id}` : t("Attachment");
            const remove = this.createRemovalButton(entry, index);
            if (remove) chip.append(remove);
            chips.append(chip);
        }
        this.renderFiles();
    }
    /** Build a removal control only when this record and reference field are editable. */
    private createRemovalButton(entry: ReferenceTarget, index: number): HTMLButtonElement | null {
        const host = this.form?.querySelector<HTMLElement>(`[bloomerp-component="bloomerp-text-editor"][data-application-field-id="${entry.field_id}"]`);
        if (!this.canChange || (entry.field_id && (!host || host.dataset.disabled === "true"))) return null;
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = "×";
        button.dataset.referenceRemove = String(index);
        button.setAttribute("aria-label", `${t("Remove")} ${entry.label}`);
        return button;
    }
    /** Populate the persistent shared dropdown with preview links and per-file removal. */
    private renderFiles(): void {
        const group = this.element.querySelector<HTMLElement>("[data-reference-files-group]");
        const list = group?.querySelector<HTMLElement>("[data-reference-file-list]");
        const count = group?.querySelector<HTMLElement>("[data-reference-files-count]");
        if (!group || !list || !count) return;
        list.replaceChildren();
        let total = 0;
        for (const [index, entry] of this.entries.entries()) {
            if (entry.kind !== "file") continue;
            total += 1;
            const row = document.createElement("div");
            row.className = "flex items-center gap-2 px-3 py-2 text-sm";
            const link = document.createElement("a");
            link.className = "link min-w-0 flex-1 truncate";
            link.textContent = entry.label;
            link.title = entry.label;
            link.setAttribute("role", "menuitem");
            link.href = this.element.dataset.referencePreviewUrl!.replace("__file_id__", encodeURIComponent(entry.target_id));
            link.setAttribute("hx-get", link.getAttribute("href")!);
            link.setAttribute("hx-target", "#bloomerp-general-use-drawer-body");
            link.setAttribute("hx-swap", "innerHTML");
            link.setAttribute("hx-push-url", "false");
            link.setAttribute("bloomerp-open-drawer", "bloomerp-general-use-drawer");
            link.dataset.referenceFilePreview = "";
            row.append(link);
            const remove = this.createRemovalButton(entry, index);
            if (remove) {
                remove.className = "btn btn-sm btn-ghost shrink-0";
                row.append(remove);
            }
            list.append(row);
        }
        count.textContent = `${t("Files")} (${total})`;
        group.hidden = total === 0;
        if (!total) group.querySelector('[bloomerp-component="dropdown-keyboard"]')?.dispatchEvent(new CustomEvent("dropdown-dismiss"));
        htmx.process(list);
    }
    /** Reuse the existing avatar field and its ordinary form validation. */
    private uploadAvatar = (): void => { this.form?.querySelector<HTMLInputElement>('input[type="file"][name="avatar"]:not(:disabled)')?.click(); };

    /** Choose a new file for the explicit attachments without saving the parent yet. */
    private upload = (): void => {
        const input = document.createElement("input"); input.type = "file";
        input.addEventListener("change", this.uploadSelection.bind(this, input), { once: true, signal: this.lifecycle.signal }); input.click();
    };
    /** Upload the selected draft and add its identity to pending attachments. */
    private async uploadSelection(input: HTMLInputElement): Promise<void> {
        const file = input.files?.[0]; if (!file) return;
        try { this.add(await uploadReferenceFile(this.element, file, this.lifecycle.signal)); }
        catch (error) { if (!this.lifecycle.signal.aborted) window.alert(String(error)); }
    }
    /** Create a shared label and select it without saving the parent object. */
    private async createLabel(name: string): Promise<void> {
        const data = new FormData(); data.append("name", name);
        const csrf = this.form?.querySelector<HTMLInputElement>('[name="csrfmiddlewaretoken"]')?.value ?? "";
        const response = await fetch(this.element.dataset.referenceLabelsUrl!, { method: "POST", body: data, headers: { "X-CSRFToken": csrf }, signal: this.lifecycle.signal });
        if (!response.ok) { window.alert(t("Label could not be created")); return; }
        this.add(await response.json() as ReferenceTarget);
    }
    /** Release scoped subscriptions and asynchronous menu work on HTMX replacement. */
    public override destroy(): void {
        this.clearPreviews();
        this.lifecycle.abort();
        for (const controller of this.searches.values()) controller.abort();
        for (const timer of this.timers.values()) clearTimeout(timer);
        super.destroy();
    }
}
