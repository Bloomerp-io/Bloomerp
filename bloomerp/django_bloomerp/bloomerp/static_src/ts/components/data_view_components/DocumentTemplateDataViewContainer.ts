import { openModal } from "@/utils/modals";
import { BaseDataViewCell } from "./BaseDataViewCell";
import { DataViewContainer } from "./DataViewContainer";
import htmx from "htmx.org";


export default class DocumentTemplateDataViewContainer extends DataViewContainer {

    protected override onAdd() : boolean {
        return true;
    }

    protected override onCellClick(cell: BaseDataViewCell) : boolean {
        // 1. Target the create document modal
        openModal("create-document-template-modal");

        // 2. User fills in the form and submits
        const url = this.constructUrl(cell.objectId)
        if (!url) {
            return false;
        }

        htmx.ajax(
            'get',
            url,
            {
                target : '#create-document-template-modal-body'
            }
        )
        this.element.dispatchEvent(new CustomEvent("document-template-dataview:load-template", {
            detail: { objectId: cell.objectId, url },
        }));
        
        return true
    }

    public onAfterSwap(): void {
        this.hideFilter('content_type');
        this.hideFilter('_component_id')
    }

    private constructUrl(objectId:string) : string {
        const url = this.element.dataset.generateTemplateUrl;
        if (!url) {
            return "";
        }
        return url.replace('INSERT_ID', objectId)
    }
}
