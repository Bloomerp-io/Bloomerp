import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";

export class CalendarCell extends BaseDataViewCell {
	rightClick(event: MouseEvent | PointerEvent): void {
		void event;
		// TODO: implement when calendar context menu exists
	}
}

export class Calendar extends BaseDataViewComponent {
    protected cellClass = CalendarCell;

    protected getCellsInRange(anchor: BaseDataViewCell, active: BaseDataViewCell): BaseDataViewCell[] {
        void anchor;
        return active ? [active] : [];
    }

    timeRange: string;

    public moveCellUp(): BaseDataViewCell {
        if (!this.currentCell) this.initFocus();
        if (!this.currentCell) {
            throw new Error("Calendar has no cells to navigate");
        }

        return this.currentCell;
    }

    public moveCellDown(): BaseDataViewCell {
        if (!this.currentCell) this.initFocus();
        if (!this.currentCell) {
            throw new Error("Calendar has no cells to navigate");
        }

        return this.currentCell;
    }

    public moveCellLeft(): BaseDataViewCell {
        if (!this.currentCell) this.initFocus();
        if (!this.currentCell) {
            throw new Error("Calendar has no cells to navigate");
        }

        return this.currentCell;
    }

    public moveCellRight(): BaseDataViewCell {
        if (!this.currentCell) this.initFocus();
        if (!this.currentCell) {
            throw new Error("Calendar has no cells to navigate");
        }

        return this.currentCell;
    }
    
    keyup(): void {
    }

    keydown(): void {
        
    }

    keyleft(): void {
        
    }

    keyright(): void {
        
    }

}