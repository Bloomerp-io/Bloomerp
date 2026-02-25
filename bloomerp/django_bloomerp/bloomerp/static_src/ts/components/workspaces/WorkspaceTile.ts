import BaseComponent from "../BaseComponent";

export default class WorkspaceTile extends BaseComponent {
    private colspan: number = 1;
    private icon: string = "";
    private title: string = "";
    private isEditMode: boolean = false;
    private maxCols: number = 4;

    public initialize(): void {
        if (!this.element) return;

        const parsedColspan = Number.parseInt(this.element.dataset.colspan ?? "1", 10);
        this.colspan = Number.isFinite(parsedColspan) ? parsedColspan : 1;

        const parsedMaxCols = Number.parseInt(this.element.dataset.maxCols ?? "4", 10);
        this.maxCols = Number.isFinite(parsedMaxCols) ? parsedMaxCols : 4;

        this.setColspan(this.colspan);
        this.initializeColspanInput();
        this.initializeResizeHandle();
    }

    public setMaxCols(maxCols: number): void {
        this.maxCols = Math.max(1, maxCols);
        this.setColspan(this.colspan);

        const input = this.element?.querySelector<HTMLInputElement>('[data-colspan-input]');
        if (input) {
            input.max = String(this.maxCols);
        }
    }

    /**
     * Sets the colspan of the workspace tile
     * @param colspan The number of columns the tile should span
     */
    public setColspan(colspan: number): void {
        if (!this.element) return;

        const next = Math.min(Math.max(1, Math.round(colspan)), this.maxCols);
        this.colspan = next;
        this.element.dataset.colspan = String(next);
        this.element.style.gridColumn = `span ${next} / span ${next}`;

        const input = this.element.querySelector<HTMLInputElement>('[data-colspan-input]');
        if (input) {
            input.value = String(next);
        }

        this.element.dispatchEvent(
            new CustomEvent('workspace:tile-colspan-change', {
                bubbles: true,
                detail: { tile: this, colspan: next },
            }),
        );
    }

    /**
     * Sets the icon of the workspace tile
     * @param icon The icon class (e.g. "fa-solid fa-dollar-sign")
     */
    public setIcon(icon: string): void {
        if (!this.element) return;

        this.icon = icon;
        const iconElement = this.element.querySelector<HTMLElement>('[data-tile-icon] i');
        if (iconElement) {
            iconElement.className = `fa ${icon}`;
        }
    }

    /**
     * Sets the title of the tile
     * @param title The title of the tile
     */
    public setTitle(title: string): void {
        if (!this.element) return;

        this.title = title;
        const titleElement = this.element.querySelector<HTMLElement>('[data-tile-title]');
        if (titleElement) {
            titleElement.textContent = title;
        }
    }

    /**
     * Sets the edit mode of the tile, allowing the user to remove the tile from the workspace
     */
    public setEditMode(isEditMode?: boolean): void {
        if (!this.element) return;

        this.isEditMode = typeof isEditMode === 'boolean' ? isEditMode : !this.isEditMode;

        this.element.classList.toggle('workspace-tile--editing', this.isEditMode);
        this.element.setAttribute('draggable', this.isEditMode ? 'true' : 'false');

        const controls = this.element.querySelector<HTMLElement>('[data-tile-controls]');
        if (controls) {
            controls.classList.toggle('hidden', !this.isEditMode);
            controls.classList.toggle('flex', this.isEditMode);
        }

        const resizeHandle = this.element.querySelector<HTMLElement>('[data-colspan-resize-handle]');
        if (resizeHandle) {
            resizeHandle.classList.toggle('hidden', !this.isEditMode);
        }
    }

    public getColspan(): number {
        return this.colspan;
    }

    public getTileId(): number {
        if (!this.element) return -1;
        return Number.parseInt(this.element.dataset.tileId ?? '-1', 10);
    }

    private initializeColspanInput(): void {
        if (!this.element) return;

        const input = this.element.querySelector<HTMLInputElement>('[data-colspan-input]');
        if (!input) return;

        input.min = '1';
        input.max = String(this.maxCols);
        input.value = String(this.colspan);

        input.addEventListener('change', () => {
            const parsed = Number.parseInt(input.value, 10);
            this.setColspan(Number.isFinite(parsed) ? parsed : this.colspan);
        });
    }

    private initializeResizeHandle(): void {
        if (!this.element) return;

        const handle = this.element.querySelector<HTMLElement>('[data-colspan-resize-handle]');
        if (!handle) return;

        handle.addEventListener('pointerdown', (event: PointerEvent) => {
            if (!this.isEditMode || !this.element) return;

            event.preventDefault();

            const tileSection = this.element.closest('#workspace-tiles-section') as HTMLElement | null;
            if (!tileSection) return;

            const gridStyle = window.getComputedStyle(tileSection);
            const templateCols = gridStyle.gridTemplateColumns
                .split(' ')
                .filter(Boolean).length;
            const totalCols = Math.max(1, templateCols || this.maxCols);

            const sectionRect = tileSection.getBoundingClientRect();
            const columnWidth = sectionRect.width / totalCols;
            const startX = event.clientX;
            const startColspan = this.colspan;

            const onPointerMove = (moveEvent: PointerEvent): void => {
                const deltaX = moveEvent.clientX - startX;
                const deltaCols = Math.round(deltaX / Math.max(1, columnWidth));
                this.setColspan(startColspan + deltaCols);
            };

            const onPointerUp = (): void => {
                document.removeEventListener('pointermove', onPointerMove);
                document.removeEventListener('pointerup', onPointerUp);
            };

            document.addEventListener('pointermove', onPointerMove);
            document.addEventListener('pointerup', onPointerUp);
        });
    }

}
