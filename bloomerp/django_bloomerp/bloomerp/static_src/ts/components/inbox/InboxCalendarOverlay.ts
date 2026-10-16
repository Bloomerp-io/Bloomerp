import BaseComponent, { getComponent } from "../BaseComponent";
import { DataViewContainer } from "../data_view_components/DataViewContainer";

interface OverlayFilterGroup {
    connector: "AND" | "OR";
    conditions: { field_path: string; lookup_id: string; value: unknown }[];
}

/** Apply the inbox-specific OR filter while leaving grouping and rendering to the calendar dataview. */
export default class InboxCalendarOverlay extends BaseComponent {
    private lifecycle = new AbortController();

    /** Bind one dropdown's apply button without intercepting the shared calendar's navigation. */
    public initialize(): void {
        this.element.addEventListener("click", this.onClick, { signal: this.lifecycle.signal });
        this.element.addEventListener("keydown", this.onKeyDown, { signal: this.lifecycle.signal });
        document.addEventListener("click", this.onOutsideClick, { signal: this.lifecycle.signal });
    }

    /** Close the dropdown when focus stays elsewhere in the page. */
    private onOutsideClick = (event: MouseEvent): void => {
        if (event.target instanceof Node && !this.element.contains(event.target)) this.element.removeAttribute("open");
    };

    /** Let Escape dismiss this menu before it reaches an enclosing modal. */
    private onKeyDown = (event: KeyboardEvent): void => {
        if (event.key !== "Escape" || !this.element.hasAttribute("open")) return;
        event.preventDefault();
        event.stopPropagation();
        this.element.removeAttribute("open");
        this.element.querySelector<HTMLElement>("summary")?.focus();
    };

    /** Replace the inbox constraint while retaining search, period, and unrelated filters. */
    private onClick = (event: MouseEvent): void => {
        if (!(event.target instanceof Element) || !event.target.closest("[data-apply-overlay]")) return;
        const values = Array.from(this.element.querySelectorAll<HTMLInputElement>("[data-overlay-inbox]:checked"), this.inboxValue);
        const error = this.element.querySelector<HTMLElement>("[data-overlay-error]");
        if (error) error.hidden = values.length > 0;
        if (!values.length) return;
        const container = this.element.closest<HTMLElement>('[bloomerp-component="dataview-container"]');
        const dataview = container ? getComponent(container) as DataViewContainer : null;
        if (!dataview || !container) return;
        const groups = this.existingFilters(container);
        if (groups === null) return;
        const filters = groups.filter(this.isUnrelatedFilter);
        filters.push({ connector: "AND", conditions: [{ field_path: "inboxes", lookup_id: "values_in", value: values }] });
        this.element.removeAttribute("open");
        dataview.filter({
            inboxes: null,
            inboxes__in: null,
            filter: JSON.stringify(filters),
            calendar_color_field: "inboxes",
            calendar_color_values: values.join(","),
            calendar_color_preferred: this.element.dataset.preferredGroup || values[0],
        });
    };

    /** Preserve validated filter groups already present in the dataview URL. */
    private existingFilters(container: HTMLElement): OverlayFilterGroup[] | null {
        const query = new URL(container.dataset.url || location.href, location.origin).searchParams;
        try {
            const groups: OverlayFilterGroup[] = [];
            for (const raw of query.getAll("filter")) {
                const parsed = JSON.parse(raw) as OverlayFilterGroup[];
                if (!Array.isArray(parsed) || !parsed.every(this.isFilterGroup)) return null;
                groups.push(...parsed);
            }
            return groups;
        } catch { return null; }
    }

    /** Validate the structural boundary before preserving existing request constraints. */
    private isFilterGroup(group: OverlayFilterGroup): boolean {
        return Boolean(group) && ["AND", "OR"].includes(group.connector) && Array.isArray(group.conditions);
    }

    /** Replace only the dedicated inbox membership group, retaining all other constraints. */
    private isUnrelatedFilter(group: OverlayFilterGroup): boolean {
        const condition = group.conditions[0];
        return group.conditions.length !== 1 || condition.field_path !== "inboxes" || condition.lookup_id !== "values_in";
    }

    /** Extract a checkbox's effective source-inbox ID for the standard values-in lookup. */
    private inboxValue(input: HTMLInputElement): string {
        return input.value;
    }

    /** Release listeners when the dataview toolbar is replaced. */
    public destroy(): void {
        this.lifecycle.abort();
        super.destroy();
    }
}
