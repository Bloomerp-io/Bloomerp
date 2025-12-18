import BaseComponent from "./BaseComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";


export class KanbanCard extends BaseDataViewCell {
    public initialize(): void {
    }

    rightclick(): void {
        
    }

    moveRight() {

    }

    moveLeft() {
    }

    /**
     * Happens on rightclick of the cell
     */
    rightClick() {
        console.log('Righclick')
    }
}