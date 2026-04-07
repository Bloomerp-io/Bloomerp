import getGeneralModal, { openModal } from "@/utils/modals";
import { BaseDataViewCell } from "./BaseDataViewCell";
import { DataViewContainer } from "./DataViewContainer";
import { get } from "http";

export default class DocumentTemplateDataViewContainer extends DataViewContainer {


    protected override onAdd() : boolean {
        return true;
    }

    protected override onCellClick(cell: BaseDataViewCell) : boolean {
        // 1. Target the create document modal
        openModal("create-document-template-modal");

        // 2. User fills in the form and submits



        return true;
    }

    public onAfterSwap(): void {
        this.hideFilter('content_type');
        this.hideFilter('_component_id')
    }
}