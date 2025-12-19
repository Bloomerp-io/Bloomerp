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
    filter(args:Record<any, any>, resetParameters:boolean=false) : void {
        let url = resetParameters?this.baseUrl:this.fullPath;

        htmx.ajax(
            'get',
            url,
            {
                target:this.target,
                swap:'innerHTML',
            }
        )
    }
}