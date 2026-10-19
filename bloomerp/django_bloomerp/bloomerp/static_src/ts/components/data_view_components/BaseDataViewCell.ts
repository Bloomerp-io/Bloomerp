import BaseComponent, { getComponent } from "../BaseComponent";
import { Drawer } from "../Drawer";
import htmx from "htmx.org";

export abstract class BaseDataViewCell extends BaseComponent {
    private detailUrl : string;
    // Optional runtime click override. When set, `click()` will call this
    // instead of performing the default navigation behaviour.
    public onClickOverride: ((cell: BaseDataViewCell) => boolean | void) | null = null;
    public dataViewClickOverride: ((cell: BaseDataViewCell) => boolean | void) | null = null;
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
        if (this.handleClickOverride(this.onClickOverride, 'onClickOverride')) return;
        if (this.handleClickOverride(this.dataViewClickOverride, 'dataViewClickOverride')) return;

        this.performDefaultClick(target);
    }

    private handleClickOverride(
        override: ((cell: BaseDataViewCell) => boolean | void) | null,
        name: string,
    ): boolean {
        if (!override) return false;

        try {
            const handled = override(this);
            if (handled !== false) {
                console.debug(`Click handled by ${name}`);
                return true;
            }
        } catch (err) {
            console.error(`${name} error`, err);
            return true;
        }

        return false;
    }

    public getDetailUrl(): string {
        return this.detailUrl;
    }

    /** Refresh cached navigation and object metadata after updating a cell's contents. */
    public override onAfterSwap(): void {
        if (!this.element) return;
        this.detailUrl = this.element.dataset.detailUrl ?? '';
        this.objectString = this.element.dataset.objectString ?? null;
        this.objectId = this.element.dataset.objectId ?? null;
    }

    protected performDefaultClick(target?: string | HTMLElement): void {
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

    /** Navigate on cell double-clicks while leaving embedded action controls independent. */
    private setupEventListeners() : void {
        if (!this.element) return;

        // Click event
        this.element.addEventListener('dblclick', (event: MouseEvent): void => {
            if (event.target instanceof Element && event.target.closest('[data-no-row-click]')) return;
            this.click()
        })
    }

    /** Open the shared drawer or use the split pane according to the saved view mode. */
    private resolveDefaultTarget(): string | HTMLElement {
        const container = this.element?.closest<HTMLElement>('[data-view-mode]');
        if (container?.dataset.viewMode === 'drawer') {
            container.querySelector<HTMLElement>('[data-detail-drawer-trigger]')?.classList.remove('hidden');
            const drawer = container.querySelector<HTMLElement>('[data-dataview-detail-drawer]');
            const pane = drawer?.querySelector<HTMLElement>('[data-drawer-detail-pane]');
            if (!this.element.hasAttribute('tabindex')) this.element.tabIndex = -1;
            if (drawer) (getComponent(drawer) as Drawer)?.open(this.element);
            return pane ?? '#main-content';
        }
        if (container?.dataset.viewMode === 'split') {
            return container.querySelector<HTMLElement>('[data-split-view-detail-pane]') ?? '#main-content';
        }
        return '#main-content';
    }

    /** Embedded detail navigation keeps the list URL unchanged. */
    private shouldPushUrl(target: string | HTMLElement): boolean {
        if (typeof target === "string") {
            return target === "#main-content";
        }

        const detailPane = target.closest<HTMLElement>('[data-split-view-detail-pane], [data-drawer-detail-pane]');
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
