import BaseComponent, { getComponent } from "../BaseComponent";
import type PrepareSign from "./PrepareSign";
import { getSdk } from "../../sdk/getSdk";
import { t } from "../../utils/i18n";
import showMessage from "../../utils/messages";
import { MessageType } from "../UiMessage";

/** Coordinate existing signing components with the shared server-side wizard navigation. */
export default class SigningWizard extends BaseComponent {
    private lifecycle = new AbortController();
    private form: HTMLFormElement | null = null;
    private prepared = false;
    private saving = false;
    private submissionTimer: ReturnType<typeof setTimeout> | null = null;
    private submitter: HTMLButtonElement | null = null;

    /** Save preparation before Continue and leave final forms under their own components. */
    public initialize(): void {
        const root = this.element.closest<HTMLElement>("#wizard-root");
        this.form = root?.querySelector<HTMLFormElement>("form[hx-post]") ?? null;
        const options = { signal: this.lifecycle.signal };
        if (this.element.hasAttribute("data-prepare-step")) {
            this.form?.addEventListener("submit", this.onSubmit, { ...options, capture: true });
        }
        this.element.addEventListener("bloomerp:signing-complete", this.onComplete, options);
        this.element.addEventListener("bloomerp:signing-cancel", this.onCancel, options);
        this.element.addEventListener("htmx:responseError", this.onLoadError, options);
        document.addEventListener("htmx:beforeCleanupElement", this.onCleanup, options);
        const completed = this.element.dataset.completedRequestId;
        if (completed) void this.rememberCompletion(completed);
    }

    /** Intercept only forward navigation, allowing Back without saving pending edits. */
    private onSubmit = (event: SubmitEvent): void => {
        const submitter = event.submitter as HTMLButtonElement | null;
        if (submitter?.value === "back" || this.prepared) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        if (!this.saving && this.submissionTimer === null) void this.saveAndContinue(submitter);
    };

    /** Persist the builder snapshot, then submit its identity through normal wizard validation. */
    private async saveAndContinue(submitter: HTMLButtonElement | null): Promise<void> {
        const element = this.element.querySelector<HTMLElement>('[bloomerp-component="bloomerp:prepare-sign"]');
        if (!element || !this.form) {
            showMessage(t("Wait for the document to finish loading."), MessageType.INFO);
            return;
        }
        this.saving = true;
        if (submitter) submitter.disabled = true;
        try {
            const snapshot = await (getComponent(element) as PrepareSign).saveForWizard();
            if (this.lifecycle.signal.aborted || !snapshot || !this.element.isConnected) return;
            this.element.querySelector<HTMLInputElement>("[data-wizard-preparation]")!.value = snapshot.id;
            this.element.querySelector<HTMLInputElement>("[data-wizard-revision]")!.value = String(snapshot.revision);
            this.submitter = submitter;
            // A saved draft resolves immediately; browsers ignore reentrant requestSubmit calls.
            this.submissionTimer = setTimeout(this.submitPrepared, 0);
        } catch {
            if (!this.lifecycle.signal.aborted) {
                showMessage(t("The preparation could not be saved. Try again."), MessageType.ERROR);
            }
        } finally {
            this.saving = false;
            if (submitter && !this.lifecycle.signal.aborted) submitter.disabled = false;
        }
    }

    /** Resume submission in a new browser task after the original submit event has finished. */
    private submitPrepared = (): void => {
        this.submissionTimer = null;
        if (this.lifecycle.signal.aborted || !this.form?.isConnected) return;
        this.prepared = true;
        try {
            this.form.requestSubmit(this.submitter ?? undefined);
        } finally {
            this.prepared = false;
            this.submitter = null;
        }
    };

    /** Validate the persisted operation before resetting the wizard and refreshing the page. */
    private onComplete = (event: Event): void => {
        const button = this.form?.querySelector<HTMLButtonElement>('[name="_wizard_action"][value="back"]');
        if (button) button.hidden = true;
        const identity = (event as CustomEvent<{ request_id?: string }>).detail?.request_id;
        if (identity) void this.rememberCompletion(identity);
    };

    /** Clear the completed wizard on the server, then reload the current page. */
    private async rememberCompletion(identity: string): Promise<void> {
        if (!this.form) return;
        const data = new FormData(this.form);
        data.set("_wizard_action", "completed");
        data.set("request_id", identity);
        try {
            await getSdk().client.request<string>(this.form.getAttribute("hx-post")!, {
                method: "POST", body: data, signal: this.lifecycle.signal,
                headers: { Accept: "text/html", "HX-Request": "true", "HX-Target": "wizard-root" },
            });
            if (!this.lifecycle.signal.aborted) window.location.reload();
        } catch {
            if (!this.lifecycle.signal.aborted) {
                showMessage(t("The request was saved. Reload the page to continue."), MessageType.INFO);
            }
        }
    }

    /** Treat a child form's Cancel as returning to action selection rather than closing the wizard. */
    private onCancel = (event: Event): void => {
        const button = this.form?.querySelector<HTMLButtonElement>('[name="_wizard_action"][value="back"]');
        if (!button || button.hidden) return;
        event.preventDefault();
        this.form?.requestSubmit(button);
    };

    /** Surface failed component loads without replacing the wizard or exposing a debug response. */
    private onLoadError = (): void => {
        showMessage(t("This step could not be loaded. Go back and try again."), MessageType.ERROR);
    };

    /** Release listeners when a wizard step or its containing modal is removed. */
    private onCleanup = (event: Event): void => {
        const target = (event as CustomEvent<{ elt?: HTMLElement }>).detail?.elt;
        if (target?.contains(this.element)) this.destroy();
    };

    /** Cancel outstanding navigation callbacks and detach every listener owned by this step. */
    public override destroy(): void {
        this.lifecycle.abort();
        if (this.submissionTimer !== null) clearTimeout(this.submissionTimer);
        this.submissionTimer = null;
        this.submitter = null;
        super.destroy();
    }
}
