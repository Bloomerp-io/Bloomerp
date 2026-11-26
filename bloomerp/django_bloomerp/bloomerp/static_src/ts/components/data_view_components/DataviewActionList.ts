import BaseComponent, { getComponent } from "../BaseComponent";
import { DATAVIEW_ROOT, DataViewContainer } from "./DataViewContainer";

interface DataviewActionRequest {
    elt?: HTMLElement;
    path?: string;
    parameters: Record<string, unknown>;
}

/** Supply the originating Dataview's current context to its configured actions. */
export class DataviewActionList extends BaseComponent {
    private initialQueryKeys: string[] = [];

    /** Bind actions to the filters that were active when their endpoints were rendered. */
    public override initialize(): void {
        const root = this.element.closest<HTMLElement>(DATAVIEW_ROOT);
        if (!root) return;
        const initialUrl = new URL(root.dataset.url || location.href, location.origin);
        this.initialQueryKeys = Array.from(new Set(initialUrl.searchParams.keys()));
        this.element.addEventListener("htmx:configRequest", this.configureRequest);
        this.element.addEventListener("htmx:beforeCleanupElement", this.handleCleanup);
    }

    /** Send checked IDs and replace stale filters for the originating dataview. */
    private configureRequest = (event: Event): void => {
        const detail = (event as CustomEvent<DataviewActionRequest>).detail;
        const source = detail?.elt;
        if (!source?.closest("[data-dataview-action]")) return;

        const root = this.element.closest<HTMLElement>(DATAVIEW_ROOT);
        if (!root || source.closest(DATAVIEW_ROOT) !== root) return;
        const dataview = getComponent(root);
        if (!(dataview instanceof DataViewContainer)) return;
        detail.parameters.selected_ids = dataview.getActionSelection();

        if (!detail.path || !root.dataset.url) return;
        const actionUrl = new URL(detail.path, location.origin);
        const currentUrl = new URL(root.dataset.url, location.origin);
        for (const key of this.initialQueryKeys) {
            actionUrl.searchParams.delete(key);
        }
        for (const key of new Set(currentUrl.searchParams.keys())) {
            if (key === "page" || key === "selected_ids") continue;
            actionUrl.searchParams.delete(key);
            for (const value of currentUrl.searchParams.getAll(key)) actionUrl.searchParams.append(key, value);
        }
        detail.path = `${actionUrl.pathname}${actionUrl.search}`;
    };

    /** Unbind only when HTMX removes this action list itself. */
    private handleCleanup = (event: Event): void => {
        if (event.target === this.element) this.destroy();
    };

    /** Release the request hooks owned by this action list. */
    public override destroy(): void {
        this.element.removeEventListener("htmx:configRequest", this.configureRequest);
        this.element.removeEventListener("htmx:beforeCleanupElement", this.handleCleanup);
        super.destroy();
    }
}
