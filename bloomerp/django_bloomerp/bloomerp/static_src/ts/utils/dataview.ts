import htmx from "htmx.org";
import { DataViewContainer } from "@/components/data_view_components/DataViewContainer";
import { getComponent } from "@/components/BaseComponent";
import type { Filter } from "@/components/filters/definition";

/** Render and initialize a dataview with optional filters and an element-owned request. */
export default function renderDataView(
    element: HTMLElement,
    contentTypeId: number|string,
    componentId?: string,
    filters?: Filter[],
): Promise<DataViewContainer> {
    const url = new URL(`/components/dataview/${contentTypeId}/`, window.location.origin);
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
