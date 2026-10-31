import htmx from "htmx.org";
import BaseComponent from "../BaseComponent";
import { getSdk } from "../../sdk/getSdk";
import { t } from "../../utils/i18n";

/** Materialize an idempotent request after an authorized role has been selected. */
export default class StartSelfSigning extends BaseComponent {
    private lifecycle = new AbortController();
    private busy = false;
    private initialized = false;

    /** Start single-role preparations immediately and otherwise wait for an explicit role choice. */
    public initialize(): void {
        if (!(this.element instanceof HTMLFormElement) || this.initialized) return;
        this.initialized = true;
        this.element.addEventListener("submit", this.onSubmit, { signal: this.lifecycle.signal });
        document.addEventListener("htmx:beforeCleanupElement", this.onCleanup, { signal: this.lifecycle.signal });
        if (this.element.dataset.singleRole === "true") void this.start();
    }

    /** Keep implicit form submission inside the authenticated component workflow. */
    private onSubmit = (event: Event): void => {
        event.preventDefault();
        void this.start();
    };

    /** Create or reopen the selected snapshot, then replace the chooser with its signing screen. */
    private async start(): Promise<void> {
        const form = this.element as HTMLFormElement;
        if (this.busy || !form.reportValidity()) return;
        const data = new FormData(form);
        const button = form.querySelector<HTMLButtonElement>("[data-start-signing]")!;
        const select = form.querySelector<HTMLSelectElement>('[name="role_key"]')!;
        const error = form.querySelector<HTMLElement>("[data-signing-error]")!;
        this.busy = true;
        button.disabled = true;
        select.disabled = true;
        form.setAttribute("aria-busy", "true");
        error.hidden = true;
        try {
            const result = await getSdk().client.request<{ url: string }>(form.dataset.startUrl!, {
                method: "POST", signal: this.lifecycle.signal,
                body: JSON.stringify({
                    preparation_id: data.get("preparation_id"), revision: Number(data.get("revision")),
                    role_key: data.get("role_key"),
                }),
            });
            const html = await getSdk().client.request<string>(result.url, {
                headers: { Accept: "text/html" }, signal: this.lifecycle.signal,
            });
            if (!this.lifecycle.signal.aborted && form.isConnected) {
                htmx.swap(form, html, { swapStyle: "outerHTML", swapDelay: 0, settleDelay: 0 });
            }
        } catch (reason) {
            if (!this.lifecycle.signal.aborted) {
                error.textContent = reason instanceof Error && !/<html|<!doctype/i.test(reason.message) && reason.message.length < 400
                    ? reason.message : t("The signing session could not be opened. Try again.");
                error.hidden = false;
            }
        } finally {
            if (!this.lifecycle.signal.aborted) {
                this.busy = false;
                button.disabled = false;
                select.disabled = false;
                form.setAttribute("aria-busy", "false");
            }
        }
    }

    /** Abort requests when HTMX removes this chooser or its containing modal. */
    private onCleanup = (event: Event): void => {
        const target = (event as CustomEvent<{ elt?: HTMLElement }>).detail?.elt;
        if (target?.contains(this.element)) this.destroy();
    };

    /** Release every listener and in-flight request owned by the chooser. */
    public override destroy(): void {
        this.lifecycle.abort();
        super.destroy();
    }
}
