import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { BaseDataViewCell } from "./BaseDataViewCell";
import { MessageType } from "../UiMessage";
import { getComponent } from "../BaseComponent";
import { getCsrfToken } from "../../utils/cookies";
import showMessage from "../../utils/messages";

type CalendarDirection = "up" | "down" | "left" | "right";
type CalendarDateUpdate = { object_id: string; start_ms?: number; end_ms?: number };
type CalendarDragPayload = {
    object_id: string;
    start_ms: number;
    end_ms?: number;
    grab_unit?: string;
};
type CalendarFocusBookmark = {
    objectId?: string;
    row?: string;
    column?: string;
};

export class CalendarCell extends BaseDataViewCell {
    private get section(): HTMLElement | null {
        if (this.element?.hasAttribute("data-calendar-event")) return this.element;
        return this.element?.closest<HTMLElement>("[data-calendar-unit-section]") ?? null;
    }

    public override highlight(): void {
        super.highlight();
        this.section?.classList.add("ring-2", "ring-inset", "ring-primary");
    }

    public override unhighlight(): void {
        super.unhighlight();
        this.section?.classList.remove("ring-2", "ring-inset", "ring-primary");
    }

    public override select(): void {
        super.select();
        this.section?.classList.add("bg-primary-50");
    }

    public override unselect(): void {
        super.unselect();
        this.section?.classList.remove("bg-primary-50");
    }

    public override click(target?: string | HTMLElement): void {
        if (this.element?.hasAttribute("data-calendar-load-more")) {
            this.element.click();
            return;
        }
        super.click(target);
    }
}

export class Calendar extends BaseDataViewComponent {
    protected cellClass = CalendarCell;
    private viewMode = "week";
    private pageOffset = 0;
    private mutationInFlight = false;
    private activeGestureController: AbortController | null = null;
    private activeGestureCleanup: (() => void) | null = null;

    /** Bind calendar navigation, preference changes, and event editing to this instance. */
    public override initialize(): void {
        if (!this.element) return;
        super.initialize();

        this.viewMode = this.element.dataset.calendarViewMode || "week";
        this.pageOffset = Number.parseInt(this.element.dataset.pageOffset || "0", 10) || 0;
        const controller = this.ensureAbortController();
        if (["day", "week", "month"].includes(this.viewMode) && this.dataViewContainer?.canCreate) {
            this.element.addEventListener("dblclick", this.onEmptyCellDoubleClick, { signal: controller.signal });
        }

        this.element.querySelectorAll<HTMLElement>("[data-calendar-nav]").forEach((button) => {
            button.addEventListener("click", () => {
                const action = button.dataset.calendarNav;
                if (action === "today") this.navigateTo(0);
                if (action === "prev") this.navigateTo(this.pageOffset - 1);
                if (action === "next") this.navigateTo(this.pageOffset + 1);
            }, { signal: controller.signal });
        });

        const modeSelect = this.element.querySelector<HTMLSelectElement>("[data-calendar-view-mode]");
        modeSelect?.addEventListener("change", (): void => {
            void this.persistViewMode(modeSelect);
        }, { signal: controller.signal });

        this.element.addEventListener("pointerdown", this.onEventPointerDown, {
            signal: controller.signal,
        });
        this.element.addEventListener("dragstart", this.onCalendarDragStart, {
            signal: controller.signal,
        });
        this.element.addEventListener("dragend", this.clearDropHighlights, {
            signal: controller.signal,
        });
        this.element.addEventListener("dragover", this.onGridDragOver, {
            signal: controller.signal,
        });
        this.element.addEventListener("dragleave", this.onGridDragLeave, {
            signal: controller.signal,
        });
        this.element.addEventListener("drop", this.onGridDrop, {
            signal: controller.signal,
        });

        this.element.addEventListener("keydown", (event) => {
            if (!event.metaKey || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
            event.preventDefault();
            event.stopImmediatePropagation();
            this.navigateTo(
                this.pageOffset + (event.key === "ArrowLeft" ? -1 : 1),
                true,
            );
        }, { capture: true, signal: controller.signal });

        this.restorePendingFocus();
    }

    public override destroy(): void {
        this.activeGestureController?.abort();
        this.activeGestureController = null;
        this.activeGestureCleanup?.();
        this.activeGestureCleanup = null;
        super.destroy();
    }

    public moveCellUp(): BaseDataViewCell {
        return this.move("up");
    }

    public moveCellDown(): BaseDataViewCell {
        return this.move("down");
    }

    public moveCellLeft(): BaseDataViewCell {
        return this.move("left");
    }

    public moveCellRight(): BaseDataViewCell {
        return this.move("right");
    }

    /** Create from empty date cells while leaving event double-click navigation untouched. */
    private onEmptyCellDoubleClick = (event: MouseEvent): void => {
        const target = event.target as HTMLElement | null;
        if (!target || target.closest("[data-calendar-event], [data-calendar-load-more], a, input, select, textarea")) return;
        const cell = target.closest<HTMLElement>("[data-calendar-unit-section]");
        if (!cell || !this.element?.contains(cell)) return;
        const values = this.getCreateInitialValues(cell);
        const opener = cell.querySelector<HTMLElement>("[data-calendar-unit-cell]") ?? cell;
        if (!values || !this.dataViewContainer?.openCreateForm(values, opener)) return;
        event.preventDefault();
        event.stopPropagation();
    };

    /** Map server-generated cell boundaries to the configured date or datetime field names. */
    private getCreateInitialValues(cell: HTMLElement): Record<string, string> | null {
        const data = this.element?.dataset;
        const startField = data?.calendarCreateStartField;
        const unit = cell.dataset.calendarUnit;
        if (!startField || !unit || !cell.dataset.calendarCreateStart || !cell.dataset.calendarCreateEnd) return null;
        const day = unit.slice(0, 10);
        const dateStart = data.calendarCreateStartDateField;
        const dateEnd = data.calendarCreateEndDateField;
        if (this.viewMode === "month" && dateStart && dateEnd) {
            return { [dateStart]: day, [dateEnd]: cell.dataset.calendarCreateEnd.slice(0, 10) };
        }
        const isDate = data.calendarStartFieldType === "DateField";
        const values = { [startField]: isDate ? day : cell.dataset.calendarCreateStart };
        const endField = data.calendarCreateEndField;
        if (endField) {
            values[endField] = isDate
                ? (startField === dateStart ? cell.dataset.calendarCreateEnd.slice(0, 10) : day)
                : cell.dataset.calendarCreateEnd;
        }
        return values;
    }

    /** Save the selected calendar period without relying on a display-options form. */
    private async persistViewMode(select: HTMLSelectElement): Promise<void> {
        const url = this.element?.dataset.calendarModeUrl;
        if (!url || select.disabled) return;
        select.disabled = true;
        const csrfToken = getCsrfToken();
        const signal = this.ensureAbortController().signal;
        try {
            const response = await fetch(url, {
                method: "POST",
                credentials: "same-origin",
                signal,
                headers: {
                    "Content-Type": "application/json",
                    ...(csrfToken ? { "X-CSRFToken": csrfToken } : {}),
                },
                body: JSON.stringify({ view_mode: select.value }),
            });
            if (!response.ok) throw new Error("Unable to save the calendar view mode.");
            const optionsSelect = this.dataViewContainer?.element?.querySelector<HTMLSelectElement>(
                '[data-display-options-form] [name="calendar_view_mode"]',
            );
            if (optionsSelect) optionsSelect.value = select.value;
            this.dataViewContainer?.filter({ calendar_page: null, calendar_view_mode: null });
        } catch (error) {
            if (signal.aborted) return;
            select.value = this.viewMode;
            showMessage("Unable to save the calendar view mode.", MessageType.ERROR);
            console.error("Failed to save the calendar view mode", error);
        } finally {
            select.disabled = false;
        }
    }

    private navigateTo(pageOffset: number, preserveFocus: boolean = false): void {
        if (preserveFocus) this.queueFocusRestore(false);
        this.dataViewContainer?.filter({ calendar_page: pageOffset });
    }

    private queueFocusRestore(
        followObject: boolean,
        fallbackObjectId?: string,
    ): void {
        const container = this.dataViewContainer?.element;
        if (!container) return;

        const currentElement = this.currentCell?.element;
        const currentEvent = currentElement?.closest<HTMLElement>("[data-calendar-event]");
        const section = this.sectionForElement(currentElement);
        const bookmark: CalendarFocusBookmark = {
            ...(followObject
                ? { objectId: currentEvent?.dataset.objectId ?? fallbackObjectId }
                : {}),
            ...(section?.dataset.calendarRow !== undefined
                ? { row: section.dataset.calendarRow }
                : {}),
            ...(section?.dataset.calendarColumn !== undefined
                ? { column: section.dataset.calendarColumn }
                : {}),
        };
        container.dataset.calendarFocusBookmark = JSON.stringify(bookmark);
    }

    private restorePendingFocus(): void {
        const container = this.dataViewContainer?.element;
        const rawBookmark = container?.dataset.calendarFocusBookmark;
        if (!container || !rawBookmark) return;
        delete container.dataset.calendarFocusBookmark;

        let bookmark: CalendarFocusBookmark;
        try {
            bookmark = JSON.parse(rawBookmark) as CalendarFocusBookmark;
        } catch {
            return;
        }

        window.requestAnimationFrame(() => {
            if (!this.element?.isConnected) return;
            let target: HTMLElement | null = null;
            if (bookmark.objectId) {
                target = this.element.querySelector<HTMLElement>(
                    `[data-calendar-event][data-object-id="${CSS.escape(bookmark.objectId)}"]`,
                );
            }
            if (!target && bookmark.row !== undefined && bookmark.column !== undefined) {
                const section = this.element.querySelector<HTMLElement>(
                    `[data-calendar-row="${CSS.escape(bookmark.row)}"]`
                    + `[data-calendar-column="${CSS.escape(bookmark.column)}"]`,
                );
                target = section?.querySelector<HTMLElement>("[data-calendar-unit-cell]") ?? null;
            }

            const component = target ? getComponent(target) : null;
            if (component instanceof CalendarCell) {
                this.focus(component);
                this.collapseSelectionToActive();
                this.element.focus({ preventScroll: true });
                return;
            }
            this.initFocus();
        });
    }

    private sectionForElement(element: HTMLElement | null | undefined): HTMLElement | null {
        if (!this.element || !element) return null;
        const direct = element.closest<HTMLElement>("[data-calendar-unit-section]");
        if (direct) return direct;
        const unit = element.dataset.calendarUnit;
        return unit
            ? this.element.querySelector<HTMLElement>(
                `[data-calendar-unit-section][data-calendar-unit="${CSS.escape(unit)}"]`,
            )
            : null;
    }

    protected override handleAltArrow(event: KeyboardEvent): boolean {
        if (!event.key.startsWith("Arrow")) return false;
        const direction = event.key.replace("Arrow", "").toLowerCase() as CalendarDirection;
        event.preventDefault();
        if (this.viewMode === "day" && (direction === "left" || direction === "right")) {
            return true;
        }
        if (!this.currentCell) this.initFocus();

        const selected = this.getSelectedCells().filter(
            (cell): cell is CalendarCell => cell instanceof CalendarCell,
        );
        const candidates = selected.length > 0
            ? selected
            : (this.currentCell instanceof CalendarCell ? [this.currentCell] : []);
        const itemsById = new Map<string, HTMLElement>();
        for (const cell of candidates) {
            const item = cell.element?.closest<HTMLElement>("[data-calendar-event]");
            const objectId = item?.dataset.objectId;
            if (item && objectId) itemsById.set(objectId, item);
        }
        if (itemsById.size === 0) return true;
        const items = Array.from(itemsById.values());
        if (!items.every((item) => this.canMoveEvent(item))) {
            showMessage("You do not have permission to move every selected record.", MessageType.ERROR);
            return true;
        }
        const updates = items
            .map((item) => this.buildMovedUpdate(item, direction))
            .filter((update): update is CalendarDateUpdate => update !== null);
        if (updates.length > 0) void this.persistDateUpdates(updates, true);
        return true;
    }

    private move(direction: CalendarDirection): BaseDataViewCell {
        if (!this.currentCell) this.initFocus();
        if (!this.currentCell) throw new Error("Calendar has no cells to navigate");

        const current = this.currentCell as CalendarCell;
        const unit = current.element?.dataset.calendarUnit;
        if (!unit) return current;

        const unitCells = this.cellsForUnit(unit);
        const itemIndex = unitCells.indexOf(current);
        const forward = direction === "down" || direction === "right";
        const cyclesItems = direction === "up"
            || direction === "down"
            || (this.viewMode !== "week" && this.viewMode !== "day");
        if (cyclesItems && forward && itemIndex >= 0 && itemIndex < unitCells.length - 1) {
            return unitCells[itemIndex + 1];
        }
        if (cyclesItems && !forward && itemIndex > 0) {
            return unitCells[itemIndex - 1];
        }

        const sections = this.getUnitSections();
        const currentSection = sections.find((section) => section.dataset.calendarUnit === unit);
        if (!currentSection) return current;
        const targetSection = this.targetSection(sections, currentSection, direction);
        if (!targetSection) return current;
        const targetUnit = targetSection.dataset.calendarUnit;
        return targetUnit ? (this.cellsForUnit(targetUnit)[0] ?? current) : current;
    }

    private cellsForUnit(unit: string): CalendarCell[] {
        return this.getCells().filter((cell): cell is CalendarCell => (
            cell instanceof CalendarCell && cell.element?.dataset.calendarUnit === unit
        ));
    }

    private getUnitSections(): HTMLElement[] {
        if (!this.element) return [];
        return Array.from(this.element.querySelectorAll<HTMLElement>(
            "[data-calendar-unit][data-calendar-row][data-calendar-column]",
        ));
    }

    private targetSection(
        sections: HTMLElement[],
        current: HTMLElement,
        direction: CalendarDirection,
    ): HTMLElement | null {
        const currentIndex = sections.indexOf(current);
        if (currentIndex < 0) return null;

        if (this.viewMode === "month") {
            const delta = direction === "up" ? -7 : direction === "down" ? 7 : direction === "left" ? -1 : 1;
            return sections[currentIndex + delta] ?? null;
        }

        if (this.viewMode === "week") {
            const row = Number(current.dataset.calendarRow);
            const column = Number(current.dataset.calendarColumn);
            const targetRow = row + (direction === "up" ? -1 : direction === "down" ? 1 : 0);
            const targetColumn = column + (direction === "left" ? -1 : direction === "right" ? 1 : 0);
            return sections.find((section) => (
                Number(section.dataset.calendarRow) === targetRow
                && Number(section.dataset.calendarColumn) === targetColumn
            )) ?? null;
        }

        if (direction === "left" || direction === "right") return null;
        return sections[currentIndex + (direction === "up" ? -1 : 1)] ?? null;
    }

    private canMoveEvent(item: HTMLElement): boolean {
        return item.dataset.calendarCanEditStart === "true"
            && (!this.hasEndField || item.dataset.calendarCanEditEnd === "true");
    }

    private get hasEndField(): boolean {
        return Boolean(this.element?.dataset.calendarEndFieldType);
    }

    /** Move both original boundaries using date-only or timed grid semantics for the event. */
    private buildMovedUpdate(
        item: HTMLElement,
        direction: CalendarDirection,
    ): CalendarDateUpdate | null {
        const objectId = item.dataset.objectId;
        const start = Number(item.dataset.calendarStart);
        const end = Number(item.dataset.calendarEnd);
        if (!objectId || !Number.isFinite(start)) return null;
        const update: CalendarDateUpdate = {
            object_id: objectId,
            start_ms: this.shiftTimestamp(start, direction, item.dataset.calendarAllDay === "true"),
        };
        if (this.hasEndField && Number.isFinite(end)) {
            update.end_ms = this.shiftTimestamp(end, direction, item.dataset.calendarAllDay === "true");
        }
        return update;
    }

    /** Move date-only events by calendar days and timed events by the current grid unit. */
    private shiftTimestamp(timestamp: number, direction: CalendarDirection, allDay: boolean = false): number {
        const shifted = new Date(timestamp);
        const amount = direction === "left" || direction === "up" ? -1 : 1;
        if (!allDay && this.viewMode === "week" && (direction === "up" || direction === "down")) {
            shifted.setHours(shifted.getHours() + amount);
        } else if (!allDay && this.viewMode === "day") {
            shifted.setHours(shifted.getHours() + amount);
        } else if (this.viewMode === "month" && (direction === "up" || direction === "down")) {
            shifted.setDate(shifted.getDate() + amount * 7);
        } else if (this.viewMode === "year") {
            shifted.setMonth(shifted.getMonth() + amount);
        } else {
            shifted.setDate(shifted.getDate() + amount);
        }
        return shifted.getTime();
    }

    /** Resize a permitted event boundary while retaining its inferred date or datetime semantics. */
    private onEventPointerDown = (event: PointerEvent): void => {
        if (!this.element || event.button !== 0 || this.mutationInFlight) return;
        const target = event.target as HTMLElement | null;
        const edge = target?.closest<HTMLElement>("[data-calendar-resize-start], [data-calendar-resize-end]");
        const item = target?.closest<HTMLElement>("[data-calendar-event]");
        if (!item) return;
        const component = getComponent(item);
        if (component instanceof CalendarCell) {
            this.focus(component);
            this.collapseSelectionToActive();
            this.element.focus({ preventScroll: true });
        }
        if (!edge) return;
        const isStart = edge.hasAttribute("data-calendar-resize-start");
        if (isStart && item.dataset.calendarCanEditStart !== "true") return;
        if (!isStart && item.dataset.calendarCanEditEnd !== "true") return;

        event.preventDefault();
        event.stopPropagation();
        const objectId = item.dataset.objectId;
        const original = Number(
            isStart ? item.dataset.calendarStart : item.dataset.calendarEnd,
        );
        if (!objectId || !Number.isFinite(original)) return;

        const vertical = this.viewMode === "day"
            || (this.viewMode === "week" && item.dataset.calendarUnit?.includes("T"));
        const origin = vertical ? event.clientY : event.clientX;
        const unit = item.dataset.calendarUnit;
        const section = item.closest<HTMLElement>("[data-calendar-unit-section]")
            ?? (
                unit
                    ? this.element.querySelector<HTMLElement>(
                        `[data-calendar-unit-section][data-calendar-unit="${CSS.escape(unit)}"]`,
                    )
                    : null
            );
        const unitPixels = vertical
            ? 80
            : Math.max(section?.getBoundingClientRect().width ?? 100, 1);
        const originalStyle = item.getAttribute("style");
        const originalRect = item.getBoundingClientRect();
        let units = 0;
        this.activeGestureController?.abort();
        this.activeGestureCleanup?.();
        const gesture = new AbortController();
        this.activeGestureController = gesture;
        const cleanup = (): void => {
            if (originalStyle === null) item.removeAttribute("style");
            else item.setAttribute("style", originalStyle);
            this.clearDropHighlights();
        };
        this.activeGestureCleanup = cleanup;
        const finishGesture = (): void => {
            gesture.abort();
            if (this.activeGestureController === gesture) {
                this.activeGestureController = null;
            }
            cleanup();
            if (this.activeGestureCleanup === cleanup) {
                this.activeGestureCleanup = null;
            }
        };

        window.addEventListener("pointermove", (moveEvent: PointerEvent) => {
            const position = vertical ? moveEvent.clientY : moveEvent.clientX;
            const delta = position - origin;
            moveEvent.preventDefault();
            units = Math.round(delta / unitPixels);

            if (originalStyle === null) item.removeAttribute("style");
            else item.setAttribute("style", originalStyle);
            const size = Math.max(
                (vertical ? originalRect.height : originalRect.width)
                + (isStart ? -delta : delta),
                8,
            );
            item.style.opacity = "0.7";
            item.style.pointerEvents = "none";
            item.style.zIndex = "30";
            if (vertical) {
                item.style.height = `${size}px`;
                if (isStart) item.style.transform = `translateY(${delta}px)`;
            } else {
                item.style.width = `${size}px`;
                if (isStart) item.style.transform = `translateX(${delta}px)`;
            }

            this.clearDropHighlights();
            this.findDropzone(moveEvent)?.classList.add(
                "ring-2",
                "ring-inset",
                "ring-primary",
            );
        }, { signal: gesture.signal });
        window.addEventListener("pointerup", () => {
            finishGesture();
            if (units === 0) return;
            let value = original;
            const direction: CalendarDirection = units < 0
                ? (vertical ? "up" : "left")
                : (vertical ? "down" : "right");
            for (let index = 0; index < Math.abs(units); index += 1) {
                value = this.shiftTimestamp(value, direction, item.dataset.calendarAllDay === "true");
            }
            const start = Number(item.dataset.calendarStart);
            const end = Number(item.dataset.calendarEnd);
            if ((isStart && Number.isFinite(end) && value >= end)
                || (!isStart && Number.isFinite(start) && value <= start)) return;
            void this.persistDateUpdates([{
                object_id: objectId,
                ...(isStart ? { start_ms: value } : { end_ms: value }),
            }], true);
        }, { signal: gesture.signal, once: true });
        window.addEventListener("pointercancel", () => {
            finishGesture();
        }, { signal: gesture.signal, once: true });
    };

    private onCalendarDragStart = (event: DragEvent): void => {
        const target = event.target as HTMLElement | null;
        if (target?.closest("[data-calendar-resize-start], [data-calendar-resize-end]")) {
            event.preventDefault();
            return;
        }

        const scheduledItem = target?.closest<HTMLElement>("[data-calendar-event]");
        if (scheduledItem) {
            if (!event.dataTransfer || !this.canMoveEvent(scheduledItem)) {
                event.preventDefault();
                return;
            }
            const objectId = scheduledItem.dataset.objectId;
            const start = Number(scheduledItem.dataset.calendarStart);
            const end = Number(scheduledItem.dataset.calendarEnd);
            if (!objectId || !Number.isFinite(start)) {
                event.preventDefault();
                return;
            }
            const grabUnit = this.findDropzone(event)?.dataset.calendarUnit;
            const payload: CalendarDragPayload = {
                object_id: objectId,
                start_ms: start,
                ...(Number.isFinite(end) ? { end_ms: end } : {}),
                ...(grabUnit ? { grab_unit: grabUnit } : {}),
            };
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData(
                "application/x-bloomerp-calendar-event",
                JSON.stringify(payload),
            );
            event.dataTransfer.setData("text/plain", objectId);
            return;
        }

        const item = target?.closest<HTMLElement>(
            "[data-calendar-unscheduled-event]",
        );
        if (!item || !event.dataTransfer || !this.canMoveEvent(item)) {
            event.preventDefault();
            return;
        }
        const objectId = item.dataset.objectId;
        if (!objectId) return;
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("application/x-bloomerp-calendar-object", objectId);
        event.dataTransfer.setData("text/plain", objectId);
    };

    private onGridDragOver = (event: DragEvent): void => {
        const dropzone = this.findDropzone(event);
        if (!dropzone || !event.dataTransfer) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        this.clearDropHighlights();
        dropzone.classList.add("ring-2", "ring-inset", "ring-primary");
    };

    private onGridDragLeave = (event: DragEvent): void => {
        const dropzone = this.findDropzone(event);
        if (!dropzone || dropzone.contains(event.relatedTarget as Node | null)) return;
        dropzone.classList.remove("ring-2", "ring-inset", "ring-primary");
    };

    private onGridDrop = (event: DragEvent): void => {
        if (!event.dataTransfer || this.mutationInFlight) return;
        const dropzone = this.findDropzone(event);
        const unit = dropzone?.dataset.calendarUnit;
        if (!dropzone || !unit) return;
        event.preventDefault();
        this.clearDropHighlights();
        const scheduledPayload = this.parseScheduledDrag(
            event.dataTransfer.getData("application/x-bloomerp-calendar-event"),
        );
        const start = this.timestampForUnit(unit);
        if (scheduledPayload && start !== null) {
            const unitDelta = scheduledPayload.grab_unit
                ? this.unitDelta(scheduledPayload.grab_unit, unit)
                : null;
            const movedStart = unitDelta === null
                ? start
                : this.shiftByUnits(scheduledPayload.start_ms, unitDelta, unit);
            const update: CalendarDateUpdate = {
                object_id: scheduledPayload.object_id,
                start_ms: movedStart,
            };
            if (this.hasEndField && scheduledPayload.end_ms !== undefined) {
                update.end_ms = unitDelta === null
                    ? movedStart + Math.max(
                        scheduledPayload.end_ms - scheduledPayload.start_ms,
                        1,
                    )
                    : this.shiftByUnits(scheduledPayload.end_ms, unitDelta, unit);
            }
            void this.persistDateUpdates([update], true);
            return;
        }

        const objectId = event.dataTransfer.getData("application/x-bloomerp-calendar-object")
            || event.dataTransfer.getData("text/plain");
        if (!objectId || start === null) return;
        const update: CalendarDateUpdate = { object_id: objectId, start_ms: start };
        if (this.hasEndField) {
            const direction: CalendarDirection = (
                (this.viewMode === "day" || this.viewMode === "week") && unit.includes("T")
            ) ? "down" : "right";
            update.end_ms = this.shiftTimestamp(start, direction);
        }
        void this.persistDateUpdates([update], true);
    };

    private findDropzone(event: DragEvent | PointerEvent): HTMLElement | null {
        const direct = (event.target as HTMLElement | null)?.closest<HTMLElement>(
            "[data-calendar-dropzone]",
        );
        if (direct) return direct;
        for (const element of document.elementsFromPoint(event.clientX, event.clientY)) {
            const dropzone = (element as HTMLElement).closest<HTMLElement>(
                "[data-calendar-dropzone]",
            );
            if (dropzone) return dropzone;
        }
        return null;
    }

    private parseScheduledDrag(rawPayload: string): CalendarDragPayload | null {
        if (!rawPayload) return null;
        try {
            const payload = JSON.parse(rawPayload) as Partial<CalendarDragPayload>;
            if (!payload.object_id || !Number.isFinite(payload.start_ms)) return null;
            if (payload.end_ms !== undefined && !Number.isFinite(payload.end_ms)) return null;
            if (payload.grab_unit !== undefined && typeof payload.grab_unit !== "string") return null;
            return payload as CalendarDragPayload;
        } catch {
            return null;
        }
    }

    private unitDelta(fromUnit: string, toUnit: string): number | null {
        const fromMonth = /^(\d{4})-(\d{2})$/.exec(fromUnit);
        const toMonth = /^(\d{4})-(\d{2})$/.exec(toUnit);
        if (fromMonth && toMonth) {
            return (
                (Number(toMonth[1]) - Number(fromMonth[1])) * 12
                + Number(toMonth[2]) - Number(fromMonth[2])
            );
        }

        const unitPattern = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}))?$/;
        const from = unitPattern.exec(fromUnit);
        const to = unitPattern.exec(toUnit);
        if (!from || !to || Boolean(from[4]) !== Boolean(to[4])) return null;
        const fromValue = Date.UTC(
            Number(from[1]),
            Number(from[2]) - 1,
            Number(from[3]),
            Number(from[4] ?? 0),
        );
        const toValue = Date.UTC(
            Number(to[1]),
            Number(to[2]) - 1,
            Number(to[3]),
            Number(to[4] ?? 0),
        );
        const unitMilliseconds = from[4] ? 60 * 60 * 1000 : 24 * 60 * 60 * 1000;
        return Math.round((toValue - fromValue) / unitMilliseconds);
    }

    private shiftByUnits(timestamp: number, units: number, unit: string): number {
        let value = timestamp;
        const direction: CalendarDirection = units < 0
            ? (unit.includes("T") ? "up" : "left")
            : (unit.includes("T") ? "down" : "right");
        for (let index = 0; index < Math.abs(units); index += 1) {
            value = this.shiftTimestamp(value, direction);
        }
        return value;
    }

    private timestampForUnit(unit: string): number | null {
        let value: Date;
        if (/^\d{4}-\d{2}$/.test(unit)) {
            value = new Date(`${unit}-01T00:00:00`);
        } else if (unit.includes("T")) {
            value = new Date(`${unit}:00:00`);
        } else {
            value = new Date(`${unit}T00:00:00`);
        }
        return Number.isNaN(value.getTime()) ? null : value.getTime();
    }

    private async persistDateUpdates(
        updates: CalendarDateUpdate[],
        refresh: boolean,
    ): Promise<void> {
        if (!this.element || this.mutationInFlight) return;
        const url = this.element.dataset.calendarUpdateUrl;
        if (!url) return;
        this.mutationInFlight = true;
        const csrfToken = getCsrfToken();
        try {
            const response = await fetch(url, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    ...(csrfToken ? { "X-CSRFToken": csrfToken } : {}),
                },
                body: JSON.stringify({ updates }),
            });
            if (!response.ok) {
                const message = response.status === 403
                    ? "You do not have permission to change these dates."
                    : "Unable to update the calendar dates.";
                showMessage(message, MessageType.ERROR);
                console.error("Failed to update calendar dates", await response.text());
                return;
            }
            if (refresh) {
                this.queueFocusRestore(true, updates[0]?.object_id);
                this.dataViewContainer?.refresh();
            }
        } catch (error) {
            showMessage("Unable to update the calendar dates.", MessageType.ERROR);
            console.error("Failed to update calendar dates", error);
        } finally {
            this.mutationInFlight = false;
        }
    }

    private clearDropHighlights = (): void => {
        if (!this.element) return;
        for (const dropzone of this.element.querySelectorAll<HTMLElement>(
            "[data-calendar-dropzone]",
        )) {
            dropzone.classList.remove("ring-2", "ring-inset", "ring-primary");
        }
    };
}
