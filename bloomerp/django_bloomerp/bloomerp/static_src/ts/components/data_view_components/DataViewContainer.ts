import htmx from "htmx.org";
import BaseComponent from "../BaseComponent";
import { HtmxAjaxHelperContext } from "htmx.org";

export class DataViewContainer extends BaseComponent {
    private target:string = '#data-table-data-section'
    private baseUrl:string|null;
    private fullPath:string|null; // Includes query parameters

    public initialize(): void {
        this.baseUrl = this.element?.dataset.baseUrl;
        this.fullPath = this.element?.dataset.url;
    }

    /**
     * Filter's the current data view
     */
    filter(
        args: Record<string, string | number | boolean | null | undefined> = {},
        resetParameters: boolean = false
    ): void {
        console.log('Filtering')
        const base = resetParameters ? this.baseUrl : this.fullPath ?? this.baseUrl;
        console.log(base)
        if (!base) return;

        const baseUrl = new URL(base, window.location.origin);

        if (!resetParameters && this.fullPath) {
            const currentUrl = new URL(this.fullPath, window.location.origin);
            currentUrl.searchParams.forEach((value, key) => baseUrl.searchParams.set(key, value));
        }

        Object.entries(args).forEach(([key, value]) => {
            if (value === null || value === undefined || value === '') return;
            baseUrl.searchParams.set(key, String(value));
        });

        this.fullPath = baseUrl.toString();

        htmx.ajax('get', this.fullPath, {
            target: this.target,
            swap: 'innerHTML',
        });
    }
}