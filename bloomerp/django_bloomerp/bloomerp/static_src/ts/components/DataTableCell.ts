import BaseComponent from "./BaseComponent";
import { getComponent } from "./BaseComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";

import type { DataTable } from "./DataTable";

export class DataTableCell extends BaseDataViewCell {
    public datatable: DataTable | null = null;

    public columnIndex: number = -1;
    public rowIndex: number = -1;

    public initialize(): void {
        if (!this.element) return;

        // Column/row indices are provided by the template via data attributes
        const colAttr = this.element.getAttribute('data-column-index');
        const col = colAttr ? Number.parseInt(colAttr, 10) : NaN;
        this.columnIndex = Number.isFinite(col) ? col : -1;

        const rowAttr = this.element.getAttribute('data-row-index');
        const rowIndex = rowAttr ? Number.parseInt(rowAttr, 10) : NaN;
        this.rowIndex = Number.isFinite(rowIndex) ? rowIndex : -1;

        // Add rightclick event listener

    }

    // Shows context menu
    showContextMenu() : void {
        console.log('Context menu shown')
    }

    
    /**
     * Happens on rightclick of the cell
     */
    rightClick() {
        console.log('Righclick')
    }




}