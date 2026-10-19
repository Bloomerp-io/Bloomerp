import htmx from "htmx.org";
import { DataViewContainer } from "@/components/data_view_components/DataViewContainer";
import { getComponent } from "@/components/BaseComponent";
import type { Filter } from "@/components/filters/definition";

export interface RenderDataviewOptions {
    queryParams?: Record<string, string | number | boolean>;
    args?: Record<string, string | number | boolean>;
    permissionToken?: string | null;
    hideFilters?: boolean;
    syncUrl?: boolean;
}

/** Render a dataview with optional filters, shell arguments, capability, and URL synchronization. */
export default function renderDataview(
    element: HTMLElement,
    contentTypeId: number|string,
    componentId?: string,
    filters?: Filter[],
    options: RenderDataviewOptions = {},
): Promise<DataViewContainer> {
    const url = new URL(`/components/dataview/${contentTypeId}/`, window.location.origin);
    for (const [key, value] of Object.entries(options.queryParams ?? {})) {
        url.searchParams.set(key, String(value));
    }
    for (const [key, value] of Object.entries(options.args ?? {})) {
        url.searchParams.set(`_arg_${key}`, String(value));
    }
    if (options.hideFilters !== undefined) {
        url.searchParams.set('_arg_hide_filters', String(options.hideFilters));
    }
    if (options.permissionToken !== undefined) {
        url.searchParams.delete('_permission_token');
        if (options.permissionToken) url.searchParams.set('_permission_token', options.permissionToken);
    }
    if (componentId) {
        url.searchParams.set('_component_id', componentId);
    }
    if (filters?.length) {
        url.searchParams.set('filter', JSON.stringify(filters));
    }
    const requestUrl = `${url.pathname}${url.search}`;

    return htmx.ajax('get', requestUrl, {
        source: element,
        target: element,
        swap: 'innerHTML',
        ...(options.syncUrl !== undefined ? {
            headers: { 'X-Bloomerp-Sync-Url': String(options.syncUrl) },
        } : {}),
    }).then(() => {
        // After the HTMX swap, find the dataview container inside the provided element
        const dataViewEl = element.querySelector<HTMLElement>(
            `[bloomerp-component="${componentId || 'dataview-container'}"]`,
        );
        if (!dataViewEl) throw new Error('DataViewContainer element not found after render');

        const comp = getComponent(dataViewEl) as DataViewContainer | null;
        if (!comp) throw new Error('Failed to initialize DataViewContainer');

        return comp;
    });
}
