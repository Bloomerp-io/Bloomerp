import BaseComponent from "./BaseComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";
import { getComponent } from "./BaseComponent";

export abstract class BaseDataViewComponent extends BaseComponent {
    // Selected cell is the current cell
    public currentCell: BaseDataViewCell | null = null;

    // Each dataview must define what its unit cell component is
    protected abstract cellClass: typeof BaseDataViewCell;

    // Key listeners
    abstract keyup(): void;
    abstract keydown(): void;
    abstract keyleft(): void;
    abstract keyright(): void;


    // Handles arrow down clicks
    protected handleArrowKey(event: KeyboardEvent): void {
        switch (event.key) {
            case 'ArrowDown':
                event.preventDefault();

                // First interaction: initialize focus onto the first available cell
                if (!this.currentCell) {
                    this.initFocus();
                    break;
                }

                this.keydown();
                break;
            case 'ArrowUp':
                event.preventDefault();
                this.keyup();
                break;
            case 'ArrowRight':
                event.preventDefault();
                this.keyright();
                break;
            case 'ArrowLeft':
                event.preventDefault();
                this.keyleft();
                break;
        }
    }

    // Shift + key listener    


    // Cmnd / ctrl + key listeners


    /**
     * Initializes focus onto the data view component.
     */
    protected initFocus(): void {
        if (!this.element) return;

        // Find the first child component element within this dataview
        const candidates = this.element.querySelectorAll<HTMLElement>('[bloomerp-component]');

        for (const el of Array.from(candidates)) {
            const component = getComponent(el);

            if (component && component instanceof this.cellClass) {
                this.focus(component);
                return;
            }
        }
    }

    /**
     * Focus a cell: unhighlight previous, set new, highlight.
     */
    protected focus(cell: BaseDataViewCell | null): void {
        if (this.currentCell) {
            this.currentCell.unhighlight();
        }

        this.currentCell = cell;

        if (this.currentCell) {
            this.currentCell.highlight();
        }
    }
}