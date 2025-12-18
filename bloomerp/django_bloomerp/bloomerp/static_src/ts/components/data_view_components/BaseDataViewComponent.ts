import BaseComponent from "./BaseComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";
import { getComponent } from "./BaseComponent";
import { componentIdentifier } from "./BaseComponent";

export abstract class BaseDataViewComponent extends BaseComponent {
    protected abortController: AbortController | null = null;

    // Selected cell is the current cell
    public currentCell: BaseDataViewCell | null = null;

    // Whether in split view
    public splitView : boolean = false;

    // Each dataview must define what its unit cell component is
    protected abstract cellClass: typeof BaseDataViewCell;

    // attributes for multiselect mode
    private inMultiSelectMode : boolean = false;
    private selectedCells : Array<BaseDataViewCell>

    // Key listeners
    abstract keyup(): void;
    abstract keydown(): void;
    abstract keyleft(): void;
    abstract keyright(): void;


    /**
     * Main keyboard dispatcher for dataviews.
     * - Arrow keys: movement
     * - Shift + Arrow: selection/extend behavior (override shift* methods)
     * - Cmd/Ctrl + Arrow: jump/navigation behavior (override cmnd* methods)
     */
    protected handleKeyDown(event: KeyboardEvent): void {
        const isArrow =
            event.key === 'ArrowDown' ||
            event.key === 'ArrowUp' ||
            event.key === 'ArrowLeft' ||
            event.key === 'ArrowRight';
        if (!isArrow) return;

        // First interaction: initialize focus onto the first available cell.
        // Do not also perform movement in the same keystroke.
        if (!this.currentCell) {
            event.preventDefault();
            this.initFocus();
            return;
        }

        if (event.shiftKey) {
            this.handleShiftArrowKey(event);
            return;
        }

        if (event.metaKey || event.ctrlKey) {
            this.handleCmndArrowKey(event);
            return;
        }

        this.handleArrowKey(event);
    }

    // Handles plain arrow movement
    protected handleArrowKey(event: KeyboardEvent): void {
        switch (event.key) {
            case 'ArrowDown':
                event.preventDefault();
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
    shiftUp():void{}
    shiftDown():void{}
    shiftLeft():void{}
    shiftRight():void{}

    protected handleShiftArrowKey(event:KeyboardEvent):void {
        console.log('Shift+Arrow', event.key);
        switch (event.key) {
            case 'ArrowDown':
                event.preventDefault();
                this.shiftDown();
                break;
            case 'ArrowUp':
                event.preventDefault();
                this.shiftUp();
                break;
            case 'ArrowRight':
                event.preventDefault();
                this.shiftRight();
                break;
            case 'ArrowLeft':
                event.preventDefault();
                this.shiftLeft();
                break;
        }
    }

    // Cmd/Ctrl + key listeners (override in subclasses as needed)
    cmndUp(): void {}
    cmndDown(): void {}
    cmndLeft(): void {}
    cmndRight(): void {}

    protected handleCmndArrowKey(event: KeyboardEvent): void {
        console.log(event.metaKey ? 'Cmd+Arrow' : 'Ctrl+Arrow', event.key);
        switch (event.key) {
            case 'ArrowDown':
                event.preventDefault();
                this.cmndDown();
                break;
            case 'ArrowUp':
                event.preventDefault();
                this.cmndUp();
                break;
            case 'ArrowRight':
                event.preventDefault();
                this.cmndRight();
                break;
            case 'ArrowLeft':
                event.preventDefault();
                this.cmndLeft();
                break;
        }
    }

    /**
     * Initializes focus onto the data view component.
     */
    protected initFocus(): void {
        if (!this.element) return;

        // Find the first child component element within this dataview
        const candidates = this.element.querySelectorAll<HTMLElement>(`[${componentIdentifier}]`);

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

            const el = this.currentCell.element;
            if (el) {
                el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
            }
        }
    }

    protected ensureAbortController(): AbortController {
        if (!this.abortController) {
            this.abortController = new AbortController();
        }

        return this.abortController;
    }

    public override destroy(): void {
        if (this.abortController) {
            this.abortController.abort();
            this.abortController = null;
        }

        if (this.currentCell) {
            this.currentCell.unhighlight();
        }
    }
}