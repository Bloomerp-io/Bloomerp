import htmx from "htmx.org";
import { insertSkeleton } from "@/utils/animations";
import { createModalInstance } from "@/utils/modals";
import { requestContextHeaders } from "@/utils/requestContext";
import BaseComponent, { getComponent } from "../BaseComponent";
import type { Modal } from "../Modal";
import { DATAVIEW_ROOT } from "./DataViewContainer";

const MODAL_CREATE_HEADERS = { "X-Bloomerp-Modal-Create": "true" };

/** Find the create flow declared by the nearest Dataview. */
export function getDataviewCreate(opener: HTMLElement): DataviewCreate | null {
    const root = opener.closest(DATAVIEW_ROOT);
    const declaration = root?.querySelector<HTMLElement>(':scope > [bloomerp-component="dataview-create"]');
    const component = declaration ? getComponent(declaration) : null;
    return component instanceof DataviewCreate ? component : null;
}

/** Own one Dataview's create dialog and preserve its draft when dismissed. */
export class DataviewCreate extends BaseComponent {
    private lifecycle = new AbortController();
    private owner: HTMLElement | null = null;
    private modal: Modal | null = null;
    private formUrl: string | null = null;

    /** Bind toolbar triggers only inside this create flow's Dataview. */
    public override initialize(): void {
        this.owner = this.element.closest<HTMLElement>(DATAVIEW_ROOT);
        const options = { signal: this.lifecycle.signal };
        this.owner?.addEventListener("click", this.handleAddClick, options);
        this.element.addEventListener("htmx:beforeCleanupElement", this.handleCleanup, options);
    }

    /** Open a fresh form or resume the draft for the same endpoint and defaults. */
    public open(opener: HTMLElement, initialValues: Record<string, string> = {}): boolean {
        const baseUrl = this.element.dataset.createUrl;
        const owner = this.owner;
        if (!baseUrl || !owner?.isConnected || opener.closest(DATAVIEW_ROOT) !== owner) return false;
        const url = new URL(baseUrl, window.location.origin);
        for (const [field, value] of Object.entries(initialValues)) url.searchParams.set(field, value);

        if (!this.modal) {
            this.modal = createModalInstance("create-object-modal", opener, {
                disposable: false,
                onCloseEvent: "bloomerp:dataview-refresh",
                closeEventTarget: owner,
            });
            const options = { signal: this.lifecycle.signal };
            this.modal.element.addEventListener("bloomerp:modal-closed", this.handleModalClosed, options);
            this.modal.getBodyElement()?.addEventListener("htmx:responseError", this.handleLoadError, options);
        }
        const modal = this.modal;
        const body = modal.getBodyElement();
        if (!body) return false;
        modal.setOpener(opener);
        modal.open();

        const formUrl = url.toString();
        const headers = { ...MODAL_CREATE_HEADERS, ...requestContextHeaders(opener, url) };
        modal.element.setAttribute("hx-headers", JSON.stringify(headers));
        if (this.formUrl === formUrl) return true;
        htmx.trigger(body, "htmx:abort");
        this.formUrl = formUrl;
        insertSkeleton(body);
        void htmx.ajax("get", formUrl, {
            source: body, target: body, swap: "innerHTML", headers,
        }).catch((error: unknown): void => {
            if (this.formUrl === formUrl) this.formUrl = null;
            if (!this.lifecycle.signal.aborted) console.error("Failed to load create form:", error);
        });
        return true;
    }

    /** Open the dialog from an Add button belonging to this Dataview. */
    private handleAddClick = (event: MouseEvent): void => {
        if (!(event.target instanceof Element)) return;
        const button = event.target.closest<HTMLElement>("[data-dataview-create-button]");
        if (button && this.open(button)) event.preventDefault();
    };

    /** Discard the draft after its own modal reports a successful save. */
    private handleModalClosed = (event: Event): void => {
        if (event.target !== this.modal?.element) return;
        if ((event as CustomEvent<{ result?: string }>).detail?.result === "saved") this.formUrl = null;
    };

    /** Allow a form load to be retried after an unsuccessful GET. */
    private handleLoadError = (event: Event): void => {
        if (event.target === this.modal?.getBodyElement()) this.formUrl = null;
    };

    /** Dispose this create flow when HTMX removes its declaration. */
    private handleCleanup = (event: Event): void => {
        if (event.target === this.element) this.destroy();
    };

    /** Release the portaled dialog and its requests when the originating Dataview is removed. */
    public override destroy(): void {
        this.lifecycle.abort();
        this.modal?.destroy();
        this.modal?.element.remove();
        this.modal = null;
        super.destroy();
    }
}
