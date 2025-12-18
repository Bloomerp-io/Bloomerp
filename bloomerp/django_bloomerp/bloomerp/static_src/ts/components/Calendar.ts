import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { CalendarCell } from "./CalendarCell";

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