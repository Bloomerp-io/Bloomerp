import type { TemplateSelection } from "../text_editor/utils/templatePicker";
import { EmailRecipients } from "./EmailRecipients";
import BaseComponent, { getComponent, initComponents } from "../BaseComponent";
import { BloomerpTextEditor } from "../text_editor/BloomerpTextEditor";
import { getSdk } from "../../sdk/getSdk";
import { BloomerpHttpError, type EmailDraftUpdate } from "../../sdk/sdk";
import { t as _ } from "../../utils/i18n";

interface TemplateResponse {
    body: string;
    form_html: string;
}

/** Compose, preview, autosave, and send emails from an inbox or object modal. */
export class EmailEditor extends BaseComponent {
    private editor: BloomerpTextEditor | null = null;
    private form: HTMLFormElement | null = null;
    private lifecycle = new AbortController();
    private templateRequest: AbortController | null = null;
    private saveTimer: ReturnType<typeof setTimeout> | null = null;
    private saving: Promise<void> | null = null;
    private dirty = false;
    private sending = false;
    private sent = false;
    private loadingTemplate = false;
    private templateIds = new Set<string>();
    private revision = 0;
    private recipients: EmailRecipients[] = [];

    /** Initialize instance-local controls and preserve the existing reply form. */
    public initialize(): void {
        if (!this.element) return;
        this.form = this.element.querySelector("form");
        for (const input of this.element.querySelectorAll<HTMLInputElement>("[data-recipient-input]")) {
            this.recipients.push(new EmailRecipients(input, this.lifecycle.signal, this.element!.dataset.recipientSearchUrl));
        }
        this.form?.addEventListener("submit", this.validateRecipients, { capture: true, signal: this.lifecycle.signal });
        this.setupEditor();
        this.element.addEventListener("click", this.onClick, { signal: this.lifecycle.signal });
        if (!this.element.dataset.sendUrl || !this.form) return;
        this.form.addEventListener("submit", this.onSubmit, { signal: this.lifecycle.signal });
        this.form.addEventListener("input", this.onInput, { signal: this.lifecycle.signal });
        this.form.addEventListener("bloomerp:template-selected", this.onTemplateSelected, { signal: this.lifecycle.signal });
        this.form.addEventListener("change", this.onInput, { signal: this.lifecycle.signal });
        this.form.addEventListener("bloomerp:widget-change", this.onInput, { signal: this.lifecycle.signal });
        document.body.addEventListener("htmx:beforeCleanupElement", this.onCleanup, { signal: this.lifecycle.signal });
    }

    /** Resolve the registered rich-text widget after its field initialization. */
    public setupEditor(): void {
        const element = this.element?.querySelector<HTMLElement>('[bloomerp-component="bloomerp-text-editor"]');
        this.editor = element ? getComponent(element) as BloomerpTextEditor : null;
        this.editor?.editor?.focus();
    }

    /** Toggle optional recipient fields or request a resolved message preview. */
    private onClick = (event: MouseEvent): void => {
        const target = event.target instanceof Element ? event.target : null;
        if (target?.closest("[data-show-cc]")) this.element?.querySelector("[data-cc-field]")?.classList.toggle("hidden");
        if (target?.closest("[data-show-bcc]")) this.element?.querySelector("[data-bcc-field]")?.classList.toggle("hidden");
        if (target?.closest("[data-preview-email]")) void this.preview();
    };

    /** Reject invalid chips before either SDK or HTMX submits the message. */
    private validateRecipients = (event: SubmitEvent): void => {
        for (const recipients of this.recipients) {
            if (!recipients.validate()) {
                event.preventDefault();
                event.stopImmediatePropagation();
                return;
            }
        }
    };

    /** Record ordinary edits for autosave without reloading template content. */
    private onInput = (_event: Event): void => {
        this.markChanged();
    };

    /** Take ownership of template insertion to prepare email variables first. */
    private onTemplateSelected = (event: Event): void => {
        event.preventDefault();
        void this.loadTemplate((event as CustomEvent<TemplateSelection>).detail);
    };

    /** Mark the snapshot dirty and invalidate any preview of earlier content. */
    private markChanged(): void {
        if (this.sent) return;
        this.dirty = true;
        this.setStatus(_("Saving draft…"));
        this.revision += 1;
        const preview = this.element?.querySelector<HTMLElement>("[data-email-preview]");
        if (preview) preview.hidden = true;
        if (this.saveTimer) clearTimeout(this.saveTimer);
        this.saveTimer = setTimeout(this.autosave, 700);
    }

    /** Save queued edits while showing failures without discarding the composer. */
    private autosave = (): void => {
        this.saveTimer = null;
        if (this.sending || this.loadingTemplate || this.sent) return;
        void this.flushDraft().catch(this.showError);
    };

    /** Capture current editor HTML, including edits before its next change event. */
    private formData(): FormData {
        const data = new FormData(this.form!);
        data.set("body", this.editor?.getValue() ?? String(data.get("body") ?? ""));
        return data;
    }

    /** Serialize saves so draft creation completes before subsequent updates. */
    private async flushDraft(): Promise<void> {
        if (this.saving) return this.saving;
        if (!this.dirty || this.sent) return;
        this.saving = this.saveQueuedDrafts();
        try {
            await this.saving;
        } finally {
            this.saving = null;
        }

    }

    /** Drain edits received during an in-flight save before allowing sending. */
    private async saveQueuedDrafts(): Promise<void> {
        while (this.dirty && !this.sent) await this.saveDraft();
    }

    /** Encode an attachment for the JSON draft snapshot without changing its bytes. */
    private async draftAttachment(file: File): Promise<{ filename: string; content_type: string; content_base64: string }> {
        const bytes = new Uint8Array(await file.arrayBuffer());
        let binary = "";
        for (let offset = 0; offset < bytes.length; offset += 8192) {
            binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
        }
        return { filename: file.name, content_type: file.type || "application/octet-stream", content_base64: btoa(binary) };
    }

    /** Persist an incomplete snapshot through the generated draft create/update API. */
    private async saveDraft(): Promise<void> {
        const revision = this.revision;
        const data = this.formData();
        const attachments: File[] = [];
        const args: Record<string, string[]> = {};
        let attachmentSize = 0;
        for (const [key, value] of data) {
            if (key.startsWith("template_args-")) args[key] = data.getAll(key).map(String);
            if (key === "attachments" && value instanceof File && value.name) {
                attachments.push(value);
                attachmentSize += value.size;
            }
        }
        if (attachmentSize > 20 * 1024 * 1024) {
            throw new RangeError(_("Draft attachments cannot exceed 20 MB in total."));
        }
        const payload: Record<string, unknown> = {
            document_template_ids: [...new Set(data.getAll("document_template_id").map(String).filter(Boolean))],
            arguments: args,
            attachments: await Promise.all(attachments.map(this.draftAttachment)),
        };
        for (const key of ["to", "cc", "bcc", "subject", "body"]) payload[key] = String(data.get(key) ?? "");
        const snapshot: EmailDraftUpdate = {
            email_account: String(data.get("email_account_id") || "") || null,
            content_type: data.get("content_type_id") ? Number(data.get("content_type_id")) : null,
            object_id: String(data.get("object_id") ?? ""),
            payload,
        };
        const field = this.form!.elements.namedItem("draft_id") as HTMLInputElement;
        if (field.value) {
            await getSdk().emailDrafts.partialUpdate(field.value, snapshot);
        } else {
            const result = await getSdk().emailDrafts.create({
                ...snapshot, user: Number(this.element!.dataset.draftUserId),
            });
            field.value = result.id;
        }
        this.dirty = revision !== this.revision;
        if (!this.dirty && !this.sending) this.setStatus(_("Draft saved."));
    }

    /** Prepare email variables before inserting a template at the saved editor selection. */
    private async loadTemplate(selection: TemplateSelection): Promise<void> {
        const selected = selection.template.id;
        this.templateRequest?.abort();
        this.templateRequest = new AbortController();
        const controller = this.templateRequest;
        this.loadingTemplate = true;
        this.setBusy(true);
        try {
            const data = this.formData();
            data.set("document_template_id", selected);
            const result = await getSdk().client.request<TemplateResponse>(this.element!.dataset.templateUrl!, {
                method: "POST", body: data, signal: controller.signal,
            });
            if (controller.signal.aborted) return;
            const argumentsPanel = this.element!.querySelector<HTMLElement>("[data-template-arguments]")!;
            const fragment = document.createElement("template");
            fragment.innerHTML = result.form_html;
            let fields = argumentsPanel.querySelector<HTMLElement>("[data-template-fields]");
            if (!fields) {
                argumentsPanel.append(fragment.content);
                fields = argumentsPanel.querySelector<HTMLElement>("[data-template-fields]");
            } else {
                const existing = new Set<string>();
                for (const field of fields.querySelectorAll<HTMLElement>("[data-template-field]")) {
                    existing.add(field.dataset.templateField!);
                }
                for (const field of fragment.content.querySelectorAll<HTMLElement>("[data-template-field]")) {
                    if (!existing.has(field.dataset.templateField!)) fields.append(field);
                }
            }
            initComponents(argumentsPanel);
            argumentsPanel.hidden = !fields;
            if (!this.templateIds.has(selected)) {
                const input = document.createElement("input");
                input.type = "hidden";
                input.name = "document_template_id";
                input.value = selected;
                this.form!.append(input);
                this.templateIds.add(selected);
            }
            selection.insert(result.body);
            this.markChanged();
            this.setStatus("");
        } catch (error: unknown) {
            if (!controller.signal.aborted) {
                this.showError(error);
            }
        } finally {
            if (this.templateRequest === controller) {
                this.loadingTemplate = false;
                this.setBusy(false);
            }
        }
    }

    /** Display resolved HTML in a scriptless preview isolated from the app. */
    private async preview(): Promise<void> {
        if (this.loadingTemplate || this.sending) return;
        const revision = this.revision;
        try {
            const data = this.formData();
            data.set("preview", "true");
            const result = await getSdk().client.request<{ html: string }>(this.element!.dataset.templateUrl!, {
                method: "POST", body: data,
            });
            if (revision !== this.revision || this.sent) return;
            this.element!.querySelector<HTMLIFrameElement>("[data-email-preview-frame]")!.srcdoc = result.html;
            this.element!.querySelector<HTMLElement>("[data-email-preview]")!.hidden = false;
            this.setStatus("");
        } catch (error: unknown) {
            this.showError(error);
        }
    }

    /** Prevent duplicate submissions and let the component own sending. */
    private onSubmit = (event: SubmitEvent): void => {
        event.preventDefault();
        if (!this.sending && !this.loadingTemplate && !this.sent) void this.send();
    };

    /** Finish autosave before sending and retain entered values on failure. */
    private async send(): Promise<void> {
        this.sending = true;
        this.setBusy(true);
        if (this.saveTimer) clearTimeout(this.saveTimer);
        this.setStatus(_("Sending email…"));
        try {
            await this.flushDraft();
            const result = await getSdk().client.request<{ message: string }>(this.element!.dataset.sendUrl!, {
                method: "POST", body: this.formData(), headers: { Accept: "application/json" },
            });
            this.sent = true;
            this.dirty = false;
            this.form!.hidden = true;
            const message = document.createElement("p");
            message.className = "p-5 text-success-dark";
            message.setAttribute("role", "status");
            message.textContent = result.message;
            this.element!.append(message);
        } catch (error: unknown) {
            this.showError(error);
        } finally {
            this.sending = false;
            this.setBusy(this.sent);
        }
    }

    /** Disable submission during operations and show sending activity. */
    private setBusy(busy: boolean): void {
        const send = this.form?.querySelector<HTMLButtonElement>('button[type="submit"]');
        if (send) send.disabled = busy;
        this.form?.setAttribute("aria-busy", String(busy));
        if (this.form) this.form.inert = busy;
        const icon = this.element?.querySelector<HTMLElement>("[data-send-icon]");
        if (icon) icon.className = this.sending ? "fa fa-spinner fa-spin" : "fa fa-paper-plane";
    }

    /** Show API validation messages as text, retaining all message inputs. */
    private showError = (error: unknown): void => {
        const payload = error instanceof BloomerpHttpError ? error.body : null;
        const errors = payload && typeof payload === "object" && "errors" in payload ? payload.errors : null;
        this.setStatus(error instanceof RangeError ? error.message : Array.isArray(errors) ? errors.join(" ") : _("Email operation failed. Your edits are still here; please try again."), true);
    };

    /** Update the accessible status without exposing provider internals. */
    private setStatus(message: string, error: boolean = false): void {
        const status = this.element?.querySelector<HTMLElement>("[data-email-status]");
        if (!status) return;
        status.textContent = message;
        status.classList.toggle("text-danger-dark", error);
    }

    /** Flush edits when HTMX removes this composer or its container. */
    private onCleanup = (event: Event): void => {
        const removed = (event as CustomEvent<{ elt: Element }>).detail?.elt;
        if (removed && this.element && (removed === this.element || removed.contains(this.element))) this.destroy();
    };

    /** Release handlers and pending loads while letting a started save finish. */
    public destroy(): void {
        this.lifecycle.abort();
        this.templateRequest?.abort();
        if (this.saveTimer) clearTimeout(this.saveTimer);
        this.saveTimer = null;
        if (this.dirty && !this.sending && !this.loadingTemplate && !this.sent) void this.flushDraft().catch(this.showError);
        super.destroy();
    }
}
