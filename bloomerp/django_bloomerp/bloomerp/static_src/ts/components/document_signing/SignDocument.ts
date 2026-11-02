import htmx from "htmx.org";
import BaseComponent, { getComponent } from "../BaseComponent";
import type SignaturePad from "./SignaturePad";
import type { DrawnSignature } from "./SignaturePad";
import { getSdk } from "../../sdk/getSdk";
import { t } from "../../utils/i18n";
import PdfViewer from "./PdfViewer";
import "./SignDocument.css";

interface SigningConfig {
    requestId: string;
    pdfUrl: string;
    submitUrl: string;
    fields: { id: string; name: string; type: string }[];
}

/** Render one immutable request with native field controls and explicit signer consent. */
export default class SignDocument extends BaseComponent {
    private config: SigningConfig;
    private lifecycle = new AbortController();
    private pdfViewer: PdfViewer | null = null;
    private fields: HTMLElement[] = [];
    private signaturePads = new Map<string, SignaturePad>();
    private ready = false;
    private busy = false;
    private initialized = false;
    private nextField = 0;

    /** Bind a single form lifecycle before loading the authenticated PDF and native controls. */
    public initialize(): void {
        if (!(this.element instanceof HTMLFormElement) || this.initialized) return;
        const script = this.element.querySelector<HTMLScriptElement>(`#${this.element.dataset.configId}`);
        if (!script) return;
        this.initialized = true;
        this.config = JSON.parse(script.textContent || "{}");
        this.fields = Array.from(this.element.querySelectorAll<HTMLElement>("[data-signing-field]"));
        for (const element of this.element.querySelectorAll<HTMLElement>('[bloomerp-component="bloomerp:signature-pad"]')) {
            const input = element.querySelector<HTMLInputElement>("[data-signature-value]")!;
            this.signaturePads.set(input.name, getComponent(element) as SignaturePad);
        }
        const options = { signal: this.lifecycle.signal };
        this.element.addEventListener("submit", this.onSubmit, options);
        this.element.querySelector("[data-next-field]")?.addEventListener("click", this.onNextField, options);
        this.element.querySelector("[data-zoom-controls]")?.addEventListener("click", this.onZoomClick, options);
        this.element.querySelector("[data-zoom]")?.addEventListener("change", this.onZoomChange, options);
        document.addEventListener("htmx:beforeCleanupElement", this.onCleanup, options);
        void this.load();
    }

    /** Find an owned control without crossing into another modal or signing request. */
    private query<T extends HTMLElement = HTMLElement>(selector: string): T {
        return this.element.querySelector<T>(selector)!;
    }

    /** Load the matching PDF.js worker and page geometry before enabling signing. */
    private async load(): Promise<void> {
        try {
            this.pdfViewer = new PdfViewer({
                viewport: this.query("[data-signing-viewport]"), pages: this.query("[data-signing-pages]"),
                zoom: this.query<HTMLSelectElement>("[data-zoom]"), pageClass: "sign-document__page", padding: 32,
                onPage: this.onPdfPage, onError: this.onPdfError,
            });
            await this.pdfViewer.load(this.config.pdfUrl);
            if (this.lifecycle.signal.aborted) return;
            this.ready = true;
            this.query("[data-signing-loading]").hidden = true;
            this.query<HTMLButtonElement>("[data-finish-signing]").disabled = false;
            for (const control of this.element.querySelectorAll<HTMLButtonElement | HTMLSelectElement>("[data-zoom-control]")) control.disabled = false;
        } catch (error) {
            if (!this.lifecycle.signal.aborted) this.showError(error, t("The document could not be loaded. Close this window and try again."));
        }
    }

    /** Move the original field controls onto a PDF page so values and signature strokes survive reflow. */
    private onPdfPage = (number: number, surface: HTMLElement, scale: number): void => {
        surface.style.fontSize = `${12 * scale}px`;
        for (const field of this.fields) {
            if (Number(field.dataset.page) !== number) continue;
            for (const dimension of ["x", "y", "width", "height"] as const) {
                const property = dimension === "x" ? "left" : dimension === "y" ? "top" : dimension;
                field.style[property] = `${Number(field.dataset[dimension]) * 100}%`;
            }
            surface.append(field);
        }
    };

    /** Keep page-render errors inside the signer's existing status area. */
    private onPdfError = (error: unknown): void => {
        this.showError(error, t("A PDF page could not be displayed. Reopen the signing window."));
    };

    /** Apply bounded display zoom through the viewer while preserving in-progress form values. */
    private zoom(scale: number): void {
        if (!this.ready || this.busy) return;
        this.pdfViewer?.zoom(scale);
    }

    /** Adjust the PDF scale using the same plus and minus controls as preparation. */
    private onZoomClick = (event: MouseEvent): void => {
        if (!(event.target instanceof Element)) return;
        const action = event.target.closest<HTMLElement>("[data-action]")?.dataset.action;
        if (action === "zoom-in" || action === "zoom-out") this.zoom((this.pdfViewer?.scale ?? 1) + (action === "zoom-in" ? 0.25 : -0.25));
    };

    /** Switch between fit width and the selected percentage while preserving entered values. */
    private onZoomChange = (event: Event): void => {
        if (!this.ready || this.busy || !(event.target instanceof HTMLSelectElement)) return;
        if (event.target.value === "fit") {
            this.pdfViewer?.fitToWidth();
        } else this.zoom(Number(event.target.value));
    };

    /** Navigate field-by-field without depending on the PDF canvas for keyboard access. */
    private onNextField = (): void => {
        if (!this.fields.length) return;
        const field = this.fields[this.nextField++ % this.fields.length];
        field.scrollIntoView({ block: "center", behavior: "smooth" });
        field.querySelector<HTMLElement>("button, input:not([type='hidden']), select, textarea")?.focus({ preventScroll: true });
    };

    /** Prevent duplicate completion requests and preserve native field/consent validation. */
    private onSubmit = (event: Event): void => {
        event.preventDefault();
        if (!this.ready || this.busy || !(this.element as HTMLFormElement).reportValidity()) return;
        for (const pad of this.signaturePads.values()) if (!pad.validate()) return;
        void this.finish();
    };

    /** Submit only assigned field IDs and explicit consent, then show the saved completion result. */
    private async finish(): Promise<void> {
        const data = new FormData(this.element as HTMLFormElement);
        const values: Record<string, string | boolean | DrawnSignature | null> = {};
        for (const field of this.config.fields) {
            const value = data.get(field.name);
            values[field.id] = field.type === "signature" ? this.signaturePads.get(field.name)?.value ?? null
                : field.type === "checkbox" ? value !== null : typeof value === "string" ? value : null;
        }
        this.busy = true;
        this.element.setAttribute("aria-busy", "true");
        this.query("[data-signing-error]").hidden = true;
        const controls = this.element.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | HTMLButtonElement>("input, select, textarea, button");
        for (const control of controls) control.disabled = true;
        this.query("[data-signing-status]").textContent = t("Recording your signature…");
        let recorded = false;
        try {
            const result = await getSdk().client.request<{ url: string }>(this.config.submitUrl, {
                method: "POST", body: JSON.stringify({ values, consent: data.get("consent") !== null }), signal: this.lifecycle.signal,
            });
            recorded = true;
            this.element.dispatchEvent(new CustomEvent("bloomerp:signing-complete", {
                bubbles: true, detail: { request_id: this.config.requestId },
            }));
            const html = await getSdk().client.request<string>(result.url, { headers: { Accept: "text/html" }, signal: this.lifecycle.signal });
            if (!this.lifecycle.signal.aborted && this.element.isConnected) {
                htmx.swap(this.element, html, { swapStyle: "outerHTML", swapDelay: 0, settleDelay: 0 });
            }
        } catch (error) {
            if (!this.lifecycle.signal.aborted) this.showError(error, recorded
                ? t("Your signature was saved. Retry to open the confirmation.")
                : t("Your signature could not be recorded. Your entries are preserved; try again."), recorded);
        } finally {
            if (!this.lifecycle.signal.aborted) {
                this.busy = false;
                for (const control of controls) control.disabled = false;
                this.element.setAttribute("aria-busy", "false");
                this.query("[data-signing-status]").textContent = recorded ? t("Signature recorded") : t("Ready to retry");
            }
        }
    }

    /** Show bounded API validation errors while suppressing debug pages and internal server details. */
    private showError(error: unknown, fallback: string, useFallback: boolean = false): void {
        const notice = this.query("[data-signing-error]");
        notice.textContent = !useFallback && error instanceof Error && error.message.length < 400 && !/<html|<!doctype/i.test(error.message)
            ? error.message : fallback;
        notice.hidden = false;
    }

    /** Stop work when the signing form or its containing modal is removed. */
    private onCleanup = (event: Event): void => {
        const target = (event as CustomEvent<{ elt?: HTMLElement }>).detail?.elt;
        if (target?.contains(this.element)) this.destroy();
    };

    /** Release the PDF worker, rendering tasks, observers, timers, and completion requests. */
    public override destroy(): void {
        this.lifecycle.abort();
        this.pdfViewer?.destroy(); this.pdfViewer = null;
        for (const pad of this.signaturePads.values()) pad.destroy();
        this.signaturePads.clear();
        super.destroy();
    }
}
