import BaseComponent from "./BaseComponent";
import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { KanbanCard } from "./KanbanCard";

export class KanbanBoard extends BaseDataViewComponent {
    protected cellClass = KanbanCard;

    unitComponent: typeof BaseComponent = KanbanCard;
    
    keyup(): void {
        // Move to the kanban card card above
    }
    
    keydown(): void {
        // Move to the kanban card down
    }

    keyleft(): void {
        // Move to the kanban card on the left
    }

    keyright(): void {
        // Move to the kanban card on the right
    }
}