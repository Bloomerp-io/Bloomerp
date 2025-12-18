import BaseComponent from "./BaseComponent";


export abstract class BaseDataViewCell extends BaseComponent {

    
    /**
     * Highlights the current cell
     */
    highlight(): void {
        if (!this.element) return;
        this.element.classList.add('cell-selected');
    }

    /**
     * Unhighlights the current cell
     */
    unhighlight(): void {
        if (!this.element) return;
        this.element.classList.remove('cell-selected');
    }


    abstract rightClick(): void;

}