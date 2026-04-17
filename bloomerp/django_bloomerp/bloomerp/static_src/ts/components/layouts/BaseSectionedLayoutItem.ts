import BaseComponent from "../BaseComponent";

export default abstract class BaseSectionedLayoutItem extends BaseComponent {
    protected itemId = "";
    protected colspan = 1;
    protected maxCols = 4;
    protected isEditMode = false;

    public initialize(): void {
        if (!this.element) return;

        this.itemId = this.element.dataset.layoutItemId ?? "";

        const parsedColspan = Number.parseInt(this.element.dataset.colspan ?? "1", 10);
        this.colspan = Number.isFinite(parsedColspan) ? parsedColspan : 1;

        const parsedMaxCols = Number.parseInt(this.element.dataset.maxCols ?? "4", 10);
        this.maxCols = Number.isFinite(parsedMaxCols) ? parsedMaxCols : 4;

        this.setColspan(this.colspan);
        this.initializeColspanInput();
        this.initializeResizeHandle();
    }

    public getLayoutItemId(): string {
        return this.itemId;
    }

    public getColspan(): number {
        return this.colspan;
    }

    public setMaxCols(maxCols: number): void {
        this.maxCols = Math.max(1, maxCols);
        this.setColspan(this.colspan);

        const input = this.element?.querySelector<HTMLInputElement>("[data-layout-colspan-input]");
        if (input) {
            input.max = String(this.maxCols);
        }
    }

    public setColspan(colspan: number): void {
        if (!this.element) return;

        const next = Math.min(Math.max(1, Math.round(colspan)), this.maxCols);
        const previous = this.colspan;
        this.colspan = next;
        this.element.dataset.colspan = String(next);
        this.element.style.gridColumn = `span ${next} / span ${next}`;

        const input = this.element.querySelector<HTMLInputElement>("[data-layout-colspan-input]");
        if (input) {
            input.value = String(next);
        }

        if (previous !== next) {
            this.element.dispatchEvent(
                new CustomEvent("layout:item-colspan-change", {
                    bubbles: true,
                    detail: { item: this, colspan: next },
                }),
            );
        }
    }

    public setEditMode(isEditMode?: boolean): void {
        if (!this.element) return;

        this.isEditMode = typeof isEditMode === "boolean" ? isEditMode : !this.isEditMode;
        this.element.classList.toggle("workspace-tile--editing", this.isEditMode);
        this.element.setAttribute("draggable", this.isEditMode ? "true" : "false");

        const controls = this.element.querySelector<HTMLElement>("[data-layout-item-controls]");
        if (controls) {
            controls.classList.toggle("hidden", !this.isEditMode);
            controls.classList.toggle("flex", this.isEditMode);
        }

        const resizeHandle = this.element.querySelector<HTMLElement>("[data-layout-colspan-resize-handle]");
        if (resizeHandle) {
            resizeHandle.classList.toggle("hidden", !this.isEditMode);
        }
    }

    public focusPrimaryTarget(): void {
        this.element?.focus();
    }

    public focusReadModeTarget(): void {
        this.focusPrimaryTarget();
    }

    public focusEditModeTarget(): void {
        this.element?.focus();
    }

    public getReadModeActions(): string[] {
        return [];
    }

    private initializeColspanInput(): void {
        if (!this.element) return;

        const input = this.element.querySelector<HTMLInputElement>("[data-layout-colspan-input]");
        if (!input) return;

        input.min = "1";
        input.max = String(this.maxCols);
        input.value = String(this.colspan);

        input.addEventListener("change", () => {
            const parsed = Number.parseInt(input.value, 10);
            this.setColspan(Number.isFinite(parsed) ? parsed : this.colspan);
        });
    }

    private initializeResizeHandle(): void {
        if (!this.element) return;

        const handle = this.element.querySelector<HTMLElement>("[data-layout-colspan-resize-handle]");
        if (!handle) return;

        handle.addEventListener("pointerdown", (event: PointerEvent) => {
            if (!this.isEditMode || !this.element) return;

            event.preventDefault();

            const grid = this.element.closest<HTMLElement>("[data-layout-grid]");
            if (!grid) return;

            const gridStyle = window.getComputedStyle(grid);
            const templateCols = gridStyle.gridTemplateColumns.split(" ").filter(Boolean).length;
            const totalCols = Math.max(1, templateCols || this.maxCols);
            const sectionRect = grid.getBoundingClientRect();
            const columnWidth = sectionRect.width / totalCols;
            const startX = event.clientX;
            const startColspan = this.colspan;

            const onPointerMove = (moveEvent: PointerEvent): void => {
                const deltaX = moveEvent.clientX - startX;
                const deltaCols = Math.round(deltaX / Math.max(1, columnWidth));
                this.setColspan(startColspan + deltaCols);
            };

            const onPointerUp = (): void => {
                document.removeEventListener("pointermove", onPointerMove);
                document.removeEventListener("pointerup", onPointerUp);
            };

            document.addEventListener("pointermove", onPointerMove);
            document.addEventListener("pointerup", onPointerUp);
        });
    }
}
