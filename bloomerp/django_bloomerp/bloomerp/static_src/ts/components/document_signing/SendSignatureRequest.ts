import BaseComponent, { getComponent } from "../BaseComponent";
import type { Modal } from "../Modal";
import { EmailRecipients } from "../inbox/EmailRecipients";
import { getSdk } from "../../sdk/getSdk";
import { BloomerpHttpError } from "../../sdk/sdk";
import { t } from "../../utils/i18n";

/** Collect server validation messages without displaying response markup or internal traces. */
function validationMessages(value: unknown): string[] {
    if (typeof value === "string") return /<html|<!doctype/i.test(value) ? [] : [value];
    if (Array.isArray(value)) return value.flatMap(validationMessages);
    if (value && typeof value === "object") return Object.values(value).flatMap(validationMessages);
    return [];
}

/** Initialize the shared recipient pickers in an independently owned sending modal. */
export default class SendSignatureRequest extends BaseComponent {
    private lifecycle = new AbortController();
    private recipients: EmailRecipients[] = [];
    private emailPreference = true;
    private initialized = false;
    private busy = false;
    private submitted = false;

    /** Attach one recipient lookup per role and bind the explicit request dispatch action. */
    public initialize(): void {
        if (!this.element || this.initialized) return;
        this.initialized = true;
        const options = { signal: this.lifecycle.signal };
        for (const source of this.element.querySelectorAll<HTMLInputElement>("[data-recipient-input]")) {
            const users = source.closest("[data-signature-recipient]")?.querySelector<HTMLInputElement>("[data-recipient-users]");
            this.recipients.push(new EmailRecipients(source, this.lifecycle.signal, this.element.dataset.recipientSearchUrl, users ?? undefined, true));
            const entry = source.parentElement?.querySelector<HTMLInputElement>('[role="combobox"]');
            if (entry) {
                entry.id = `${source.id}-entry`;
                this.element.querySelector<HTMLLabelElement>(`label[for="${source.id}"]`)?.setAttribute("for", entry.id);
            }
        }
        const content = this.element.querySelector<HTMLElement>("[data-email-content] [contenteditable]");
        content?.setAttribute("role", "textbox");
        content?.setAttribute("aria-multiline", "true");
        content?.setAttribute("aria-labelledby", `${this.element.id}-content-label`);
        this.element.addEventListener("submit", this.onSubmit, options);
        this.element.addEventListener("click", this.onClick, options);
        this.element.addEventListener("input", this.onRecipientsChanged, options);
        this.element.addEventListener("change", this.onRecipientsChanged, options);
        document.addEventListener("htmx:beforeCleanupElement", this.onCleanup, options);
        this.emailPreference = this.element.querySelector<HTMLInputElement>("[data-send-email]")?.checked ?? true;
        this.updateEmailOptions();
    }

    /** Refresh delivery requirements for current recipients after a child fragment changes. */
    public override onAfterSwap(): void {
        this.updateEmailOptions();
    }

    /** Retain the internal-only choice while forcing email for any external recipient. */
    private updateEmailOptions(): void {
        if (this.busy || this.submitted) return;
        const checkbox = this.element.querySelector<HTMLInputElement>("[data-send-email]");
        if (!checkbox) return;
        let required = false;
        for (const recipients of this.recipients) required ||= recipients.hasExternalRecipients();
        checkbox.disabled = required;
        checkbox.checked = required || this.emailPreference;
        const mirror = this.element.querySelector<HTMLInputElement>("[data-send-email-value]");
        if (mirror) mirror.disabled = !required;
        const explanation = this.element.querySelector<HTMLElement>("[data-email-required]");
        if (explanation) explanation.hidden = !required;
        const sender = this.element.querySelector<HTMLSelectElement>("[data-email-sender]");
        if (sender) {
            sender.required = checkbox.checked;
            sender.disabled = !checkbox.checked;
        }
        for (const section of this.element.querySelectorAll<HTMLElement>("[data-email-options], [data-email-content]")) {
            section.hidden = !checkbox.checked;
        }
    }

    /** Reconcile typed addresses, explicit user selections, removals, and the email preference. */
    private onRecipientsChanged = (event: Event): void => {
        if (event.target instanceof HTMLInputElement && event.target.matches("[data-send-email]")) {
            this.emailPreference = event.target.checked;
        }
        this.updateEmailOptions();
    };

    /** Validate every role before submitting one stable request snapshot. */
    private onSubmit = (event: Event): void => {
        event.preventDefault();
        if (this.busy || this.submitted) return;
        for (const recipient of this.recipients) if (!recipient.validate()) return;
        this.updateEmailOptions();
        if (!(this.element as HTMLFormElement).reportValidity()) return;
        void this.send();
    };

    /** Send once and preserve the submission key when a network failure requires a retry. */
    private async send(): Promise<void> {
        const form = this.element as HTMLFormElement;
        const data = new FormData(form);
        const notice = form.querySelector<HTMLElement>("[data-send-status]")!;
        const controls = Array.from(form.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLButtonElement>("input, select, button"));
        const disabled = new Map<HTMLInputElement | HTMLSelectElement | HTMLButtonElement, boolean>();
        for (const control of controls) disabled.set(control, control.disabled);
        const editors = new Map<HTMLElement, string>();
        for (const editor of form.querySelectorAll<HTMLElement>("[contenteditable]")) {
            editors.set(editor, editor.contentEditable);
            editor.contentEditable = "false";
        }
        this.busy = true;
        form.setAttribute("aria-busy", "true");
        for (const control of controls) if (!control.matches("[data-action='cancel']")) control.disabled = true;
        notice.hidden = false;
        notice.textContent = this.element.dataset.assignOnly === "true"
            ? t("Assigning recipients…") : t("Sending signature requests…");
        try {
            const result = await getSdk().client.request<{ status: string; request_id: string }>(form.getAttribute("action")!, {
                method: "POST", body: data, signal: this.lifecycle.signal,
            });
            this.submitted = true;
            notice.textContent = result.status === "assigned" ? t("Recipients assigned.") : result.status === "accepted"
                ? t("Signature invitations accepted for email delivery.")
                : result.status === "created" ? t("Signature request created without email.")
                : t("The request was created, but some emails could not be confirmed. Check Sent Items before sending again.");
            for (const editor of form.querySelectorAll<HTMLElement>("[contenteditable]")) editor.contentEditable = "false";
            this.element.dispatchEvent(new CustomEvent("bloomerp:signing-complete", { bubbles: true, detail: result }));
            if (this.element.dataset.reloadOnComplete === "true") window.location.reload();
        } catch (error) {
            if (!this.lifecycle.signal.aborted) {
                const messages = error instanceof BloomerpHttpError && error.status < 500
                    ? validationMessages(error.body) : [];
                notice.textContent = messages.length ? messages.join(" ").slice(0, 700)
                    : t("Sending could not be confirmed. Retry with the same recipients and message.");
            }
        } finally {
            if (!this.lifecycle.signal.aborted) {
                this.busy = false;
                form.setAttribute("aria-busy", "false");
                if (!this.submitted) {
                    for (const control of controls) control.disabled = disabled.get(control) ?? false;
                    for (const [editor, editable] of editors) editor.contentEditable = editable;
                }
            }
        }
    }

    /** Close only this form's modal so the preparation underneath remains available. */
    private onClick = (event: MouseEvent): void => {
        if (!(event.target instanceof Element) || !event.target.closest("[data-action='cancel']")) return;
        if (!this.element.dispatchEvent(new CustomEvent("bloomerp:signing-cancel", { bubbles: true, cancelable: true }))) return;
        const modal = this.element.closest<HTMLElement>('[bloomerp-component="modal"]');
        if (modal) (getComponent(modal) as Modal)?.close();
    };

    /** Cancel pending recipient searches when HTMX removes the form or its modal. */
    private onCleanup = (event: Event): void => {
        const target = (event as CustomEvent<{ elt?: HTMLElement }>).detail?.elt;
        if (target?.contains(this.element)) this.destroy();
    };

    /** Release lookup timers, requests, and listeners owned by this composition form. */
    public override destroy(): void {
        this.lifecycle.abort();
        super.destroy();
    }
}
