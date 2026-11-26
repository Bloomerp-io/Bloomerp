import Sortable from "sortablejs";
import BaseComponent from "../BaseComponent";

export default class OrderedFieldSelect extends BaseComponent {
    private sortable: Sortable | null = null;
    private lifecycle: AbortController | null = null;

    /** Enable handle-based reordering so the form submits fields in row order. */
    public override initialize(): void {
        const rows = this.element;
        if (!(rows instanceof HTMLTableSectionElement) || rows.rows.length < 2 || this.sortable) return;

        this.lifecycle = new AbortController();
        const options = { signal: this.lifecycle.signal };
        rows.addEventListener("keydown", this.handleReorderKey, options);
        rows.addEventListener("htmx:beforeCleanupElement", this.handleCleanup, options);
        this.sortable = Sortable.create(rows, {
            animation: 150,
            draggable: "tr[data-ordered-field-option]",
            handle: "[data-ordered-field-drag]",
            ghostClass: "opacity-50",
        });
    }

    /** Release the sortable and its listeners when the editor is removed. */
    public override destroy(): void {
        this.lifecycle?.abort();
        this.lifecycle = null;
        this.sortable?.destroy();
        this.sortable = null;
        super.destroy();
    }

    /** Clean up when HTMX replaces the table body or its enclosing form. */
    private handleCleanup = (event: Event): void => {
        if (event.target === this.element) this.destroy();
    };

    /** Move the focused field one row up or down and restore handle focus. */
    private handleReorderKey = (event: KeyboardEvent): void => {
        const handle = event.target;
        if (!(handle instanceof HTMLButtonElement) || !handle.matches("[data-ordered-field-drag]")) return;
        if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
        event.preventDefault();

        const row = handle.closest("tr");
        const sibling = event.key === "ArrowUp" ? row?.previousElementSibling : row?.nextElementSibling;
        if (!row || !sibling) return;

        if (event.key === "ArrowUp") sibling.before(row);
        else sibling.after(row);
        handle.focus();
    };
}
