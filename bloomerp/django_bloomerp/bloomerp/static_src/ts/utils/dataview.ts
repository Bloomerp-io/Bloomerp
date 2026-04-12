import htmx from "htmx.org";
import { DataViewContainer } from "@/components/data_view_components/DataViewContainer";
import { getComponent } from "@/components/BaseComponent";

export default function renderDataView(
    element: HTMLElement,
    contentTypeId: number|string
): Promise<DataViewContainer> {
    const url = `/components/data_view/${contentTypeId}/`;

    return htmx.ajax('get', url, {
        target: `#${element.id}`,
        swap: 'innerHTML',
    }).then(() => {
        // After the HTMX swap, find the dataview container inside the provided element
        const dataViewEl = element.querySelector<HTMLElement>(`[bloomerp-component="dataview-container"]`);
        if (!dataViewEl) throw new Error('DataViewContainer element not found after render');

        const comp = getComponent(dataViewEl) as DataViewContainer | null;
        if (!comp) throw new Error('Failed to initialize DataViewContainer');

        return comp;
    });
}