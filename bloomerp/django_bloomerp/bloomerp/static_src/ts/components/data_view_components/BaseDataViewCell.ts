import BaseComponent from "../BaseComponent";
import htmx from "htmx.org";

export abstract class BaseDataViewCell extends BaseComponent {
    private detailUrl : string;
    // Optional runtime click override. When set, `click()` will call this
    // instead of performing the default navigation behaviour.
    public onClickOverride: ((cell: BaseDataViewCell) => void) | null = null;
    public objectString: string | null = null;
    public objectId: string | null = null;

    public initialize(): void {

        // Get detail url
        this.detailUrl = this.element.dataset.detailUrl;

        // Handle the right click (only when implemented by subclass)
        if (this.rightClick !== BaseDataViewCell.prototype.rightClick) {
            this.handleRightClick();
        }

        // Setup object string
        this.objectString = this.element.dataset.objectString || null;
        this.objectId = this.element.dataset.objectId || null;

        // Handle click event
        this.setupEventListeners();
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
        this.element.classList.add('cell-focused');
    }

    /**
     * Unhighlights the current cell
     */
    unhighlight(): void {
        if (!this.element) return;
        this.element.classList.remove('cell-focused');
    }

    /**
     * Marks this cell as part of the current selection range.
     */
    select(): void {
        if (!this.element) return;
        this.element.classList.add('cell-selected');
    }

    /**
     * Removes this cell from the current selection range.
     */
    unselect(): void {
        if (!this.element) return;
        this.element.classList.remove('cell-selected');
        this.element.classList.remove('cell-focused');
    }

    // Default no-op; subclasses can override to enable right-click menus.
    public rightClick(event: MouseEvent | PointerEvent): void {
        void event;
    }

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

    /**
     * Click functionality:
     * a standard onClick will be provided that can be
     * overwritten.
     */
    public click(target?: string | HTMLElement): void {
        // If an override is provided, prefer that (useful for selection UIs).
        if (this.onClickOverride) {
            try {
                this.onClickOverride(this);
            } catch (err) {
                console.error('onClickOverride error', err);
            }
            return;
        }
        
        if (this.detailUrl) {
            const resolvedTarget = target ?? this.resolveDefaultTarget();
            const shouldPush = this.shouldPushUrl(resolvedTarget);
            htmx.ajax(
                'get',
                this.detailUrl,
                {
                    target: resolvedTarget,
                    push: shouldPush ? "true" : "false"
                }
            );
        }
    }

    private setupEventListeners() : void {
        if (!this.element) return;

        // Click event
        this.element.addEventListener('click', (event)=>{
            this.click()
        })
    }

    private resolveDefaultTarget(): string | HTMLElement {
        if (!this.element) return "#main-content";

        const container = this.element.closest<HTMLElement>('[data-split-view-enabled]');
        const splitViewEnabled = container?.dataset.splitViewEnabled === "True";
        if (!splitViewEnabled || !container) return "#main-content";

        const detailPane = container.querySelector<HTMLElement>('[data-split-view-detail-pane]');
        return detailPane ?? "#main-content";
    }

    private shouldPushUrl(target: string | HTMLElement): boolean {
        if (typeof target === "string") {
            return target === "#main-content";
        }

        const detailPane = target.closest<HTMLElement>('[data-split-view-detail-pane]');
        if (detailPane) return false;

        const mainContent = document.getElementById("main-content");
        if (mainContent && (target === mainContent || mainContent.contains(target))) {
            return true;
        }

        return false;
    }

    /**
     * Overwritable code that lets you construct
     * the context menu for a particular cell.
     */
    constructContextMenu():void {

    }

    
}
