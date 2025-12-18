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

    timeRange: string;
    
    keyup(): void {
    }

    keydown(): void {
        
    }

    keyleft(): void {
        
    }

    keyright(): void {
        
    }

}