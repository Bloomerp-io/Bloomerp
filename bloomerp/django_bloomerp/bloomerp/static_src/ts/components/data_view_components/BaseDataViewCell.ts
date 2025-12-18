import BaseComponent from "./BaseComponent";

export abstract class BaseDataViewCell extends BaseComponent {

    public initialize(): void {
        
        // Handle the right click
        this.handleRightClick()
    }

    public destroy(): void {
        if (!this.element) return;
        this.element.removeEventListener('contextmenu', this.onContextMenu, true);
    }
    
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

    abstract rightClick(event: MouseEvent | PointerEvent): void;

    private onContextMenu = (event: MouseEvent): void => {
        // Treat right-click (and keyboard context-menu) as a component action.
        // Use a flag to prevent duplicate handling when a parent delegates.
        const anyEvent = event as unknown as { _bloomerpCellHandled?: boolean };
        if (anyEvent._bloomerpCellHandled) return;
        anyEvent._bloomerpCellHandled = true;

        event.preventDefault();
        this.rightClick(event);
    };

    private handleRightClick(): void {
        if (!this.element) return;
        // Capture phase so descendants can't easily swallow it.
        this.element.addEventListener('contextmenu', this.onContextMenu, true);
    }

}