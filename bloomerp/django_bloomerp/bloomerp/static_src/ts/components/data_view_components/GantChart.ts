import { componentIdentifier, getComponent } from "../BaseComponent";
import { MessageType } from "../UiMessage";
import { getCsrfToken } from "../../utils/cookies";
import showMessage from "../../utils/messages";
import { BaseDataViewCell } from "./BaseDataViewCell";
import { BaseDataViewComponent } from "./BaseDataViewComponent";
import { attachObjectPreviewTooltip } from "../../utils/objectPreviewTooltip";

const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;
const MONTH = 30.4375 * DAY;
const DEFAULT_SIDEBAR_WIDTH = 320;

type TickUnit = 'month' | 'week' | 'day' | 'hour';
type GantFieldType = 'DateField' | 'DateTimeField';
type BarDragMode = 'move' | 'start' | 'end';

interface GantDateUpdate {
    object_id: string;
    start_ms?: number;
    end_ms?: number;
}

interface GantDateUpdateResponse {
    object_id: string;
    start_ms: number;
    end_ms: number;
}

interface ZoomLevel {
    pixelsPerMs: number;
    tickUnit: TickUnit;
    paddingMs: number;
}

const ZOOM_LEVELS: ZoomLevel[] = [
    { pixelsPerMs: 72 / MONTH, tickUnit: 'month', paddingMs: 2 * MONTH },
    { pixelsPerMs: 56 / WEEK, tickUnit: 'week', paddingMs: 3 * WEEK },
    { pixelsPerMs: 36 / DAY, tickUnit: 'day', paddingMs: 4 * DAY },
    { pixelsPerMs: 104 / DAY, tickUnit: 'day', paddingMs: 2 * DAY },
    { pixelsPerMs: 84 / HOUR, tickUnit: 'hour', paddingMs: 6 * HOUR },
];

class GantPreviewCell extends BaseDataViewCell {
    private previewCleanup: (() => void) | null = null;

    /** Attach navigation and an accessible object preview to this Gantt record. */
    public initialize(): void {
        super.initialize();
        const contentTypeId = this.element.closest<HTMLElement>('[data-content-type-id]')?.dataset.contentTypeId;
        const objectId = this.element.dataset.objectId;
        if (contentTypeId && objectId) {
            this.previewCleanup = attachObjectPreviewTooltip({
                element: this.element,
                contentTypeId,
                objectId,
            });
        }
    }

    /** Release tooltip listeners when a Gantt record is removed. */
    public destroy(): void {
        this.previewCleanup?.();
        this.previewCleanup = null;
        super.destroy();
    }
}

export class GantChartItem extends GantPreviewCell {}

export class GantChartSidebarItem extends GantPreviewCell {}

export class GantChart extends BaseDataViewComponent {
    protected cellClass = GantChartItem;
    private resizeObserver: ResizeObserver | null = null;
    private sidebarResizeObserver: ResizeObserver | null = null;
    private drawFrame: number | null = null;
    private zoomIndex = 0;
    private rangeStart = 0;
    private rangeEnd = 0;
    private canvasWidth = 0;
    private dataStart = 0;
    private dataEnd = 0;
    private sidebarWidth = DEFAULT_SIDEBAR_WIDTH;
    private extendingTimeline = false;
    private mutationInFlight = false;
    private activeGestureController: AbortController | null = null;

    public initialize(): void {
        if (!this.element) return;

        super.initialize();
        this.dataStart = Number(this.element.dataset.gantStart);
        this.dataEnd = Number(this.element.dataset.gantEnd);
        if (!Number.isFinite(this.dataStart) || !Number.isFinite(this.dataEnd)) return;

        const sidebarPanel = this.element.querySelector<HTMLElement>('[data-gant-sidebar]');
        const sidebar = sidebarPanel?.closest<HTMLElement>('[bloomerp-component="resizable-div"]')
            ?? sidebarPanel;

        const abortController = this.ensureAbortController();
        const zoomSelect = this.element.querySelector<HTMLSelectElement>('[data-gant-zoom]');
        const savedZoom = this.readSavedZoom();
        this.zoomIndex = savedZoom ?? this.getAutomaticZoom();
        if (zoomSelect) zoomSelect.value = String(this.zoomIndex);

        zoomSelect?.addEventListener('change', this.onZoomChange, { signal: abortController.signal });
        this.element.querySelector('[data-gant-zoom-out]')?.addEventListener(
            'click',
            () => this.changeZoom(-1),
            { signal: abortController.signal },
        );
        this.element.querySelector('[data-gant-zoom-in]')?.addEventListener(
            'click',
            () => this.changeZoom(1),
            { signal: abortController.signal },
        );
        this.element.querySelector('[data-gant-today]')?.addEventListener(
            'click',
            () => this.focusTimestamp(Date.now()),
            { signal: abortController.signal },
        );
        this.element.addEventListener('scroll', this.handleScroll, {
            signal: abortController.signal,
            passive: true,
        });
        this.element.addEventListener('htmx:afterSwap', this.handleHtmxSwap, {
            signal: abortController.signal,
        });
        this.element.addEventListener('pointerdown', this.onBarPointerDown, {
            signal: abortController.signal,
        });
        this.element.addEventListener('dragstart', this.onUnscheduledDragStart, {
            signal: abortController.signal,
        });
        this.element.addEventListener('dragend', this.clearDropHighlights, {
            signal: abortController.signal,
        });
        this.element.addEventListener('dragover', this.onTimelineDragOver, {
            signal: abortController.signal,
        });
        this.element.addEventListener('dragleave', this.onTimelineDragLeave, {
            signal: abortController.signal,
        });
        this.element.addEventListener('drop', this.onTimelineDrop, {
            signal: abortController.signal,
        });
        window.addEventListener('resize', this.onResize, { signal: abortController.signal });

        this.resizeObserver = new ResizeObserver(this.onResize);
        this.resizeObserver.observe(this.element);
        if (sidebar) {
            this.sidebarResizeObserver = new ResizeObserver(this.onSidebarResize);
            this.sidebarResizeObserver.observe(sidebar);
        }
        this.applyZoom(false);
        window.requestAnimationFrame(() => {
            this.syncSidebarChrome();
            const initialTarget = Date.now() >= this.rangeStart && Date.now() <= this.rangeEnd
                ? Date.now()
                : this.dataStart;
            this.scrollToTimestamp(initialTarget);
        });
    }

    public override destroy(): void {
        this.activeGestureController?.abort();
        this.activeGestureController = null;
        if (this.drawFrame !== null) {
            window.cancelAnimationFrame(this.drawFrame);
            this.drawFrame = null;
        }
        this.resizeObserver?.disconnect();
        this.sidebarResizeObserver?.disconnect();
        this.resizeObserver = null;
        this.sidebarResizeObserver = null;
        super.destroy();
    }

    public moveCellUp(): BaseDataViewCell {
        return this.getAdjacentItem(-1) ?? this.currentCell!;
    }

    public moveCellDown(): BaseDataViewCell {
        return this.getAdjacentItem(1) ?? this.currentCell!;
    }

    public moveCellRight(): BaseDataViewCell {
        return this.currentCell!;
    }

    public moveCellLeft(): BaseDataViewCell {
        return this.currentCell!;
    }

    protected override handleAltArrow(event: KeyboardEvent): boolean {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return false;
        event.preventDefault();
        if (!this.currentCell) this.initFocus();

        const selected = this.getSelectedCells().filter(
            (cell): cell is GantChartItem => cell instanceof GantChartItem,
        );
        const cells = selected.length > 0
            ? selected
            : (this.currentCell instanceof GantChartItem ? [this.currentCell] : []);
        const items = cells
            .map((cell) => cell.element)
            .filter((element): element is HTMLElement => Boolean(element));
        if (items.length === 0) return true;
        if (!items.every((item) => this.canMoveItem(item))) {
            showMessage('You do not have permission to move every selected record.', MessageType.ERROR);
            return true;
        }
        if (!this.canUseCurrentGranularity()) {
            showMessage('Hour-level movement requires DateTime fields.', MessageType.INFO);
            return true;
        }

        void this.moveItemsByUnits(items, event.key === 'ArrowLeft' ? -1 : 1);
        return true;
    }

    private getAutomaticZoom(): number {
        const duration = Math.max(this.dataEnd - this.dataStart, HOUR);
        for (let index = ZOOM_LEVELS.length - 1; index >= 0; index -= 1) {
            if (duration * ZOOM_LEVELS[index].pixelsPerMs <= 2400) return index;
        }
        return 0;
    }

    private readSavedZoom(): number | null {
        try {
            const storedValue = window.localStorage.getItem(`bloomerp-gant-zoom-${this.contentTypeId}`);
            if (storedValue === null) return null;
            const value = Number(storedValue);
            return Number.isInteger(value) && value >= 0 && value < ZOOM_LEVELS.length ? value : null;
        } catch {
            return null;
        }
    }

    private saveZoom(): void {
        try {
            window.localStorage.setItem(`bloomerp-gant-zoom-${this.contentTypeId}`, String(this.zoomIndex));
        } catch {
            // Storage may be disabled; zoom still works for the current view.
        }
    }

    private onZoomChange = (event: Event): void => {
        const value = Number((event.currentTarget as HTMLSelectElement).value);
        if (!Number.isInteger(value) || value < 0 || value >= ZOOM_LEVELS.length) return;
        this.zoomIndex = value;
        this.saveZoom();
        this.applyZoom(true);
    };

    private changeZoom(delta: number): void {
        const nextZoom = Math.max(0, Math.min(ZOOM_LEVELS.length - 1, this.zoomIndex + delta));
        if (nextZoom === this.zoomIndex) return;
        this.zoomIndex = nextZoom;
        const zoomSelect = this.element?.querySelector<HTMLSelectElement>('[data-gant-zoom]');
        if (zoomSelect) zoomSelect.value = String(this.zoomIndex);
        this.saveZoom();
        this.applyZoom(true);
    }

    private applyZoom(preserveCenter: boolean): void {
        if (!this.element) return;

        const oldCenter = preserveCenter && this.canvasWidth > 0
            ? this.getViewportCenterTimestamp()
            : null;
        const zoom = ZOOM_LEVELS[this.zoomIndex];
        const viewportWidth = this.getTimelineViewportWidth();
        const center = oldCenter ?? (
            Date.now() >= this.dataStart && Date.now() <= this.dataEnd
                ? Date.now()
                : (this.dataStart + this.dataEnd) / 2
        );
        const minimumSpan = Math.max(viewportWidth / zoom.pixelsPerMs * 6, zoom.paddingMs * 2);
        this.rangeStart = Math.min(this.dataStart - zoom.paddingMs, center - minimumSpan / 2);
        this.rangeEnd = Math.max(this.dataEnd + zoom.paddingMs, center + minimumSpan / 2);
        this.updateTimelineGeometry();

        this.scrollToTimestamp(center);
    }

    private updateTimelineGeometry(): void {
        if (!this.element) return;
        const zoom = ZOOM_LEVELS[this.zoomIndex];
        this.canvasWidth = Math.max((this.rangeEnd - this.rangeStart) * zoom.pixelsPerMs, 1);
        for (const layout of this.element.querySelectorAll<HTMLElement>('[data-gant-layout]')) {
            layout.style.gridTemplateColumns = `${this.sidebarWidth}px ${this.canvasWidth}px`;
            layout.style.width = `${this.sidebarWidth + this.canvasWidth}px`;
        }

        const grid = this.element.querySelector<HTMLElement>('[data-gant-grid]');
        if (grid) {
            grid.style.left = `${this.sidebarWidth}px`;
            grid.style.width = `${this.canvasWidth}px`;
        }

        const unscheduledTray = this.element.querySelector<HTMLElement>('[data-gant-unscheduled-tray]');
        if (unscheduledTray) unscheduledTray.style.width = `${this.element.clientWidth}px`;

        for (const item of this.element.querySelectorAll<HTMLElement>('[data-gant-item]')) {
            this.positionItem(item);
        }

        this.renderAxis();
        this.updateVisibleRange();
        this.syncSidebarChrome();
        this.scheduleDependencyDraw();
    }

    private syncSidebarChrome(): void {
        if (!this.element) return;

        const collapsed = this.sidebarWidth <= 1;
        const sidebarCells = this.element.querySelectorAll<HTMLElement>(
            '[data-gant-sidebar], [bloomerp-component="gant-chart-sidebar-item"]',
        );
        for (const cell of sidebarCells) {
            cell.style.visibility = collapsed ? 'hidden' : '';
            cell.style.paddingInline = collapsed ? '0' : '';
            cell.style.borderInlineEndWidth = collapsed ? '0' : '';
            cell.style.pointerEvents = collapsed ? 'none' : '';
            if (collapsed) cell.setAttribute('aria-hidden', 'true');
            else cell.removeAttribute('aria-hidden');
        }

        const handle = this.element.querySelector<HTMLElement>('[data-resizable-div-handle]');
        const rows = this.element.querySelector<HTMLElement>('[data-gant-rows]');
        if (!handle || !rows) return;

        const handleTop = handle.getBoundingClientRect().top;
        const rowsBottom = rows.getBoundingClientRect().bottom;
        const minimumHeight = handle.parentElement?.getBoundingClientRect().height ?? 0;
        handle.style.height = `${Math.max(minimumHeight, rowsBottom - handleTop)}px`;
    }

    private renderAxis(): void {
        if (!this.element) return;
        const header = this.element.querySelector<HTMLElement>('[data-gant-timeline-header]');
        const grid = this.element.querySelector<HTMLElement>('[data-gant-grid]');
        if (!header || !grid) return;
        header.replaceChildren();
        grid.replaceChildren();

        const zoom = ZOOM_LEVELS[this.zoomIndex];
        const roughCount = Math.ceil((this.rangeEnd - this.rangeStart) / this.tickDuration(zoom.tickUnit));
        const tickMultiplier = Math.max(1, Math.ceil(roughCount / 400));
        let tick = this.floorTick(new Date(this.rangeStart), zoom.tickUnit);
        let previousMajor = '';

        while (tick.getTime() <= this.rangeEnd) {
            const timestamp = tick.getTime();
            if (timestamp >= this.rangeStart) {
                const left = this.positionForTimestamp(timestamp);
                const labels = this.tickLabels(tick, zoom.tickUnit);
                const majorLabel = labels.major === previousMajor ? '' : labels.major;
                previousMajor = labels.major;

                const headerTick = document.createElement('div');
                headerTick.className = 'absolute inset-y-0 border-l border-gray-200 px-2 pt-1';
                headerTick.style.left = `${left}px`;
                const major = document.createElement('div');
                major.className = 'whitespace-nowrap text-[10px] font-medium uppercase tracking-wide text-gray-500';
                major.textContent = majorLabel;
                const minor = document.createElement('div');
                minor.className = 'mt-1 whitespace-nowrap text-xs text-gray-500';
                minor.textContent = labels.minor;
                headerTick.append(major, minor);
                header.appendChild(headerTick);

                const gridLine = document.createElement('div');
                gridLine.className = 'absolute inset-y-0 border-l border-gray-200';
                gridLine.style.left = `${left}px`;
                grid.appendChild(gridLine);
            }
            tick = this.addTicks(tick, zoom.tickUnit, tickMultiplier);
        }

        const now = Date.now();
        if (now >= this.rangeStart && now <= this.rangeEnd) {
            const left = this.positionForTimestamp(now);
            const todayLine = document.createElement('div');
            todayLine.className = 'absolute inset-y-0 border-l border-primary';
            todayLine.dataset.gantTodayLine = 'true';
            todayLine.style.left = `${left}px`;
            grid.appendChild(todayLine);

            const todayMarker = document.createElement('div');
            todayMarker.className = 'absolute inset-y-0 border-l border-primary';
            todayMarker.dataset.gantTodayMarker = 'true';
            todayMarker.style.left = `${left}px`;
            const todayLabel = document.createElement('span');
            todayLabel.className = 'absolute -left-7 top-1 rounded-xl bg-primary px-2 py-0.5 text-[10px] font-medium text-white';
            todayLabel.textContent = this.element.querySelector<HTMLElement>('[data-gant-today]')?.textContent?.trim() ?? 'Today';
            todayMarker.appendChild(todayLabel);
            header.appendChild(todayMarker);
        }
    }

    private tickDuration(unit: TickUnit): number {
        if (unit === 'month') return MONTH;
        if (unit === 'week') return WEEK;
        if (unit === 'day') return DAY;
        return HOUR;
    }

    private floorTick(value: Date, unit: TickUnit): Date {
        const tick = new Date(value);
        tick.setMinutes(0, 0, 0);
        if (unit === 'hour') return tick;
        tick.setHours(0);
        if (unit === 'day') return tick;
        if (unit === 'week') {
            const day = tick.getDay() || 7;
            tick.setDate(tick.getDate() - day + 1);
            return tick;
        }
        tick.setDate(1);
        return tick;
    }

    private addTicks(value: Date, unit: TickUnit, amount: number): Date {
        const next = new Date(value);
        if (unit === 'month') next.setMonth(next.getMonth() + amount);
        else if (unit === 'week') next.setDate(next.getDate() + 7 * amount);
        else if (unit === 'day') next.setDate(next.getDate() + amount);
        else next.setHours(next.getHours() + amount);
        return next;
    }

    private tickLabels(value: Date, unit: TickUnit): { major: string; minor: string } {
        if (unit === 'month') {
            return {
                major: new Intl.DateTimeFormat(undefined, { year: 'numeric' }).format(value),
                minor: new Intl.DateTimeFormat(undefined, { month: 'short' }).format(value),
            };
        }
        if (unit === 'hour') {
            return {
                major: new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(value),
                minor: new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(value),
            };
        }
        if (unit === 'day' && this.zoomIndex === 3) {
            return {
                major: new Intl.DateTimeFormat(undefined, { month: 'short', year: 'numeric' }).format(value),
                minor: new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric' }).format(value),
            };
        }
        return {
            major: new Intl.DateTimeFormat(undefined, { month: 'short', year: 'numeric' }).format(value),
            minor: new Intl.DateTimeFormat(undefined, { day: 'numeric' }).format(value),
        };
    }

    private positionForTimestamp(timestamp: number): number {
        return ((timestamp - this.rangeStart) / (this.rangeEnd - this.rangeStart)) * this.canvasWidth;
    }

    private positionItem(item: HTMLElement): void {
        const start = Number(item.dataset.start);
        const end = Number(item.dataset.end);
        if (!Number.isFinite(start) || !Number.isFinite(end)) return;
        const left = this.positionForTimestamp(start);
        const width = Math.max(this.positionForTimestamp(end) - left, 4);
        item.style.left = `${left}px`;
        item.style.width = `${width}px`;
    }

    private scrollToTimestamp(timestamp: number): void {
        if (!this.element) return;
        const position = this.positionForTimestamp(timestamp);
        const viewportWidth = this.getTimelineViewportWidth();
        this.element.scrollLeft = Math.max(0, position - viewportWidth / 2);
        this.updateVisibleRange();
    }

    private focusTimestamp(timestamp: number): void {
        if (!this.element) return;
        if (timestamp < this.rangeStart || timestamp > this.rangeEnd) {
            const zoom = ZOOM_LEVELS[this.zoomIndex];
            const visibleDuration = this.getTimelineViewportWidth() / zoom.pixelsPerMs;
            this.rangeStart = Math.min(this.rangeStart, timestamp - visibleDuration * 3);
            this.rangeEnd = Math.max(this.rangeEnd, timestamp + visibleDuration * 3);
            this.updateTimelineGeometry();
        }
        this.scrollToTimestamp(timestamp);
    }

    private getTimelineViewportWidth(): number {
        if (!this.element) return 640;
        return Math.max(this.element.clientWidth - this.sidebarWidth, 320);
    }

    private getViewportCenterTimestamp(): number {
        if (!this.element || this.canvasWidth <= 0) return (this.dataStart + this.dataEnd) / 2;
        const canvasCenter = this.element.scrollLeft + this.getTimelineViewportWidth() / 2;
        return this.rangeStart + (canvasCenter / this.canvasWidth) * (this.rangeEnd - this.rangeStart);
    }

    private updateVisibleRange = (): void => {
        if (!this.element || this.canvasWidth <= 0) return;
        const viewportWidth = this.getTimelineViewportWidth();
        const visibleStart = this.rangeStart + (
            Math.max(this.element.scrollLeft, 0) / this.canvasWidth
        ) * (this.rangeEnd - this.rangeStart);
        const visibleEnd = this.rangeStart + (
            Math.min(this.element.scrollLeft + viewportWidth, this.canvasWidth) / this.canvasWidth
        ) * (this.rangeEnd - this.rangeStart);
        const label = this.element.querySelector<HTMLElement>('[data-gant-visible-range]');
        if (!label) return;
        const options: Intl.DateTimeFormatOptions = this.zoomIndex === ZOOM_LEVELS.length - 1
            ? { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
            : { month: 'short', day: 'numeric', year: 'numeric' };
        const formatter = new Intl.DateTimeFormat(undefined, options);
        label.textContent = `${formatter.format(visibleStart)} – ${formatter.format(visibleEnd)}`;
    };

    private handleScroll = (): void => {
        this.updateVisibleRange();
        this.extendTimelineNearEdge();
        this.syncSidebarChrome();
    };

    private extendTimelineNearEdge(): void {
        if (!this.element || this.extendingTimeline) return;
        const viewportWidth = this.getTimelineViewportWidth();
        const threshold = viewportWidth * 0.75;
        const nearStart = this.element.scrollLeft < threshold;
        const nearEnd = this.element.scrollLeft + viewportWidth > this.canvasWidth - threshold;
        if (!nearStart && !nearEnd) return;

        this.extendingTimeline = true;
        const zoom = ZOOM_LEVELS[this.zoomIndex];
        const extensionMs = Math.max(
            viewportWidth * 2 / zoom.pixelsPerMs,
            this.tickDuration(zoom.tickUnit) * 8,
        );
        const previousScrollLeft = this.element.scrollLeft;
        let prependedWidth = 0;
        if (nearStart) {
            this.rangeStart -= extensionMs;
            prependedWidth = extensionMs * zoom.pixelsPerMs;
        }
        if (nearEnd) this.rangeEnd += extensionMs;

        this.updateTimelineGeometry();
        this.element.scrollLeft = previousScrollLeft + prependedWidth;
        window.requestAnimationFrame(() => {
            this.extendingTimeline = false;
            this.updateVisibleRange();
        });
    }

    private handleHtmxSwap = (): void => {
        this.applyZoom(true);
    };

    private onResize = (): void => {
        this.applyZoom(true);
    };

    private onSidebarResize = (entries: ResizeObserverEntry[]): void => {
        if (!this.element || entries.length === 0) return;
        const nextWidth = Math.max(0, Math.round(entries[0].contentRect.width));
        if (nextWidth === this.sidebarWidth) return;
        const center = this.getViewportCenterTimestamp();
        this.sidebarWidth = nextWidth;
        this.updateTimelineGeometry();
        this.scrollToTimestamp(center);
    };

    private getAdjacentItem(delta: number): GantChartItem | null {
        if (!this.element || !this.currentCell?.element) return null;

        const itemElements = Array.from(
            this.element.querySelectorAll<HTMLElement>(`[${componentIdentifier}="gant-chart-item"]`),
        );
        const currentIndex = itemElements.indexOf(this.currentCell.element);
        if (currentIndex < 0 || itemElements.length === 0) return null;

        const nextIndex = Math.max(0, Math.min(itemElements.length - 1, currentIndex + delta));
        return getComponent(itemElements[nextIndex]) as GantChartItem | null;
    }

    private get startFieldType(): GantFieldType {
        return this.element?.dataset.gantStartFieldType === 'DateTimeField'
            ? 'DateTimeField'
            : 'DateField';
    }

    private get endFieldType(): GantFieldType {
        return this.element?.dataset.gantEndFieldType === 'DateTimeField'
            ? 'DateTimeField'
            : 'DateField';
    }

    private canUseCurrentGranularity(fieldType?: GantFieldType): boolean {
        if (this.zoomIndex !== ZOOM_LEVELS.length - 1) return true;
        if (fieldType) return fieldType === 'DateTimeField';
        return this.startFieldType === 'DateTimeField' && this.endFieldType === 'DateTimeField';
    }

    private canMoveItem(item: HTMLElement): boolean {
        return item.dataset.gantCanEditStart === 'true'
            && item.dataset.gantCanEditEnd === 'true';
    }

    private shiftTimestamp(timestamp: number, units: number): number {
        const shifted = new Date(timestamp);
        if (this.zoomIndex === ZOOM_LEVELS.length - 1) {
            shifted.setMinutes(shifted.getMinutes() + units * 15);
        } else if (this.zoomIndex <= 1) {
            shifted.setDate(shifted.getDate() + units * 7);
        } else {
            shifted.setDate(shifted.getDate() + units);
        }
        return shifted.getTime();
    }

    private stepPixelWidth(timestamp: number): number {
        return Math.max(
            Math.abs(this.positionForTimestamp(this.shiftTimestamp(timestamp, 1)) - this.positionForTimestamp(timestamp)),
            1,
        );
    }

    private buildMovedUpdate(item: HTMLElement, units: number): GantDateUpdate | null {
        const objectId = item.dataset.objectId;
        const start = Number(item.dataset.start);
        const end = Number(item.dataset.end);
        if (!objectId || !Number.isFinite(start) || !Number.isFinite(end)) return null;
        return {
            object_id: objectId,
            start_ms: this.shiftTimestamp(start, units),
            end_ms: this.shiftTimestamp(end, units),
        };
    }

    private async moveItemsByUnits(items: HTMLElement[], units: number): Promise<void> {
        if (this.mutationInFlight || units === 0) return;
        const updates = items
            .map((item) => this.buildMovedUpdate(item, units))
            .filter((update): update is GantDateUpdate => update !== null);
        if (updates.length === 0) return;

        const originals = this.captureDates(items);
        this.previewUpdates(updates);
        const response = await this.persistDateUpdates(updates);
        if (response) this.applyResponseUpdates(response);
        else this.restoreDates(originals);
    }

    private captureDates(items: HTMLElement[]): Map<HTMLElement, { start: number; end: number }> {
        const originals = new Map<HTMLElement, { start: number; end: number }>();
        for (const item of items) {
            originals.set(item, {
                start: Number(item.dataset.start),
                end: Number(item.dataset.end),
            });
        }
        return originals;
    }

    private previewUpdates(updates: GantDateUpdate[]): void {
        if (!this.element) return;
        for (const update of updates) {
            const item = this.element.querySelector<HTMLElement>(
                `[data-gant-item][data-object-id="${CSS.escape(update.object_id)}"]`,
            );
            if (!item) continue;
            if (update.start_ms !== undefined) item.dataset.start = String(update.start_ms);
            if (update.end_ms !== undefined) item.dataset.end = String(update.end_ms);
            this.positionItem(item);
        }
        this.scheduleDependencyDraw();
    }

    private restoreDates(originals: Map<HTMLElement, { start: number; end: number }>): void {
        for (const [item, dates] of originals) {
            item.dataset.start = String(dates.start);
            item.dataset.end = String(dates.end);
            this.positionItem(item);
        }
        this.scheduleDependencyDraw();
    }

    private async persistDateUpdates(updates: GantDateUpdate[]): Promise<GantDateUpdateResponse[] | null> {
        if (!this.element || this.mutationInFlight) return null;
        const url = this.element.dataset.gantUpdateUrl;
        if (!url) return null;

        this.mutationInFlight = true;
        const csrfToken = getCsrfToken();
        try {
            const response = await fetch(url, {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
                },
                body: JSON.stringify({ updates }),
            });
            if (!response.ok) {
                const message = response.status === 403
                    ? 'You do not have permission to change these dates.'
                    : 'Unable to update the Gantt dates.';
                showMessage(message, MessageType.ERROR);
                console.error('Failed to update Gantt dates', await response.text());
                return null;
            }
            const payload = await response.json() as { updates?: GantDateUpdateResponse[] };
            return Array.isArray(payload.updates) ? payload.updates : [];
        } catch (error) {
            showMessage('Unable to update the Gantt dates.', MessageType.ERROR);
            console.error('Failed to update Gantt dates', error);
            return null;
        } finally {
            this.mutationInFlight = false;
        }
    }

    private applyResponseUpdates(updates: GantDateUpdateResponse[]): void {
        if (!this.element) return;
        for (const update of updates) {
            const item = this.element.querySelector<HTMLElement>(
                `[data-gant-item][data-object-id="${CSS.escape(update.object_id)}"]`,
            );
            if (!item) continue;
            item.dataset.start = String(update.start_ms);
            item.dataset.end = String(update.end_ms);
            this.dataStart = Math.min(this.dataStart, update.start_ms);
            this.dataEnd = Math.max(this.dataEnd, update.end_ms);
            if (update.start_ms < this.rangeStart) this.rangeStart = update.start_ms - ZOOM_LEVELS[this.zoomIndex].paddingMs;
            if (update.end_ms > this.rangeEnd) this.rangeEnd = update.end_ms + ZOOM_LEVELS[this.zoomIndex].paddingMs;
        }
        this.updateTimelineGeometry();
    }

    private onBarPointerDown = (event: PointerEvent): void => {
        if (!this.element || event.button !== 0 || this.mutationInFlight) return;
        const target = event.target as HTMLElement | null;
        const item = target?.closest<HTMLElement>('[data-gant-item]');
        if (!item || !this.element.contains(item)) return;

        const mode: BarDragMode = target?.closest('[data-gant-resize-start]')
            ? 'start'
            : (target?.closest('[data-gant-resize-end]') ? 'end' : 'move');
        if (mode === 'move' && !this.canMoveItem(item)) return;
        if (mode === 'start' && item.dataset.gantCanEditStart !== 'true') return;
        if (mode === 'end' && item.dataset.gantCanEditEnd !== 'true') return;
        const fieldType = mode === 'start' ? this.startFieldType : this.endFieldType;
        if (!this.canUseCurrentGranularity(mode === 'move' ? undefined : fieldType)) {
            showMessage('Hour-level dragging requires a DateTime field.', MessageType.INFO);
            return;
        }

        const component = getComponent(item);
        if (!(component instanceof GantChartItem)) return;
        this.element.focus({ preventScroll: true });
        const selected = this.getSelectedCells();
        if (mode !== 'move' || !selected.includes(component)) {
            this.focus(component);
            this.collapseSelectionToActive();
        }
        const dragItems = mode === 'move'
            ? this.getSelectedCells()
                .filter((cell): cell is GantChartItem => cell instanceof GantChartItem)
                .map((cell) => cell.element)
                .filter((element): element is HTMLElement => Boolean(element))
            : [item];
        if (mode === 'move' && !dragItems.every((dragItem) => this.canMoveItem(dragItem))) {
            showMessage('You do not have permission to move every selected record.', MessageType.ERROR);
            return;
        }
        const originals = this.captureDates(dragItems);
        const anchor = originals.get(item);
        if (!anchor) return;

        const startX = event.clientX;
        const stepWidth = this.stepPixelWidth(mode === 'end' ? anchor.end : anchor.start);
        let units = 0;
        this.activeGestureController?.abort();
        const gestureController = new AbortController();
        this.activeGestureController = gestureController;

        window.addEventListener('pointermove', (moveEvent: PointerEvent) => {
            const nextUnits = Math.round((moveEvent.clientX - startX) / stepWidth);
            if (nextUnits === units) return;
            moveEvent.preventDefault();
            units = nextUnits;
            const updates = this.buildDragUpdates(dragItems, originals, mode, units);
            this.restoreDates(originals);
            this.previewUpdates(updates);
        }, { signal: gestureController.signal });

        window.addEventListener('pointerup', () => {
            gestureController.abort();
            if (this.activeGestureController === gestureController) this.activeGestureController = null;
            if (units === 0) return;
            const updates = this.buildDragUpdates(dragItems, originals, mode, units);
            if (updates.length === 0) {
                this.restoreDates(originals);
                return;
            }
            void this.persistDateUpdates(updates).then((response) => {
                if (response) this.applyResponseUpdates(response);
                else this.restoreDates(originals);
            });
        }, { signal: gestureController.signal, once: true });

        window.addEventListener('pointercancel', () => {
            gestureController.abort();
            if (this.activeGestureController === gestureController) this.activeGestureController = null;
            this.restoreDates(originals);
        }, { signal: gestureController.signal, once: true });
    };

    private buildDragUpdates(
        items: HTMLElement[],
        originals: Map<HTMLElement, { start: number; end: number }>,
        mode: BarDragMode,
        units: number,
    ): GantDateUpdate[] {
        const updates: GantDateUpdate[] = [];
        for (const item of items) {
            const original = originals.get(item);
            const objectId = item.dataset.objectId;
            if (!original || !objectId) continue;
            if (mode === 'move') {
                updates.push({
                    object_id: objectId,
                    start_ms: this.shiftTimestamp(original.start, units),
                    end_ms: this.shiftTimestamp(original.end, units),
                });
                continue;
            }
            if (mode === 'start') {
                const start = this.shiftTimestamp(original.start, units);
                if (start < original.end) updates.push({ object_id: objectId, start_ms: start });
                continue;
            }
            const end = this.shiftTimestamp(original.end, units);
            if (end > original.start) updates.push({ object_id: objectId, end_ms: end });
        }
        return updates;
    }

    private onUnscheduledDragStart = (event: DragEvent): void => {
        const item = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-gant-unscheduled-item]');
        if (!item || !event.dataTransfer || !this.canMoveItem(item)) {
            event.preventDefault();
            return;
        }
        const objectId = item.dataset.objectId;
        if (!objectId) return;
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('application/x-bloomerp-gant-object', objectId);
        event.dataTransfer.setData('text/plain', objectId);
    };

    private onTimelineDragOver = (event: DragEvent): void => {
        const dropzone = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-gant-dropzone]');
        if (!dropzone || !event.dataTransfer) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        this.clearDropHighlights();
        dropzone.classList.add('ring-2', 'ring-primary');
    };

    private onTimelineDragLeave = (event: DragEvent): void => {
        const dropzone = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-gant-dropzone]');
        if (!dropzone || dropzone.contains(event.relatedTarget as Node | null)) return;
        dropzone.classList.remove('ring-2', 'ring-primary');
    };

    private onTimelineDrop = (event: DragEvent): void => {
        if (!this.element || !event.dataTransfer || this.mutationInFlight) return;
        const dropzone = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-gant-dropzone]');
        if (!dropzone) return;
        event.preventDefault();
        this.clearDropHighlights();
        if (!this.canUseCurrentGranularity()) {
            showMessage('Hour-level scheduling requires DateTime fields.', MessageType.INFO);
            return;
        }
        const objectId = event.dataTransfer.getData('application/x-bloomerp-gant-object')
            || event.dataTransfer.getData('text/plain');
        if (!objectId) return;

        const rootRect = this.element.getBoundingClientRect();
        const canvasX = event.clientX - rootRect.left + this.element.scrollLeft - this.sidebarWidth;
        const rawTimestamp = this.rangeStart + (
            Math.max(0, Math.min(canvasX, this.canvasWidth)) / this.canvasWidth
        ) * (this.rangeEnd - this.rangeStart);
        const start = this.snapDropTimestamp(rawTimestamp);
        const end = this.shiftTimestamp(start, 1);
        void this.persistDateUpdates([{ object_id: objectId, start_ms: start, end_ms: end }]).then(
            (response) => {
                if (response) this.dataViewContainer?.refresh();
            },
        );
    };

    private snapDropTimestamp(timestamp: number): number {
        const value = new Date(timestamp);
        if (this.zoomIndex === ZOOM_LEVELS.length - 1) {
            value.setSeconds(0, 0);
            value.setMinutes(Math.round(value.getMinutes() / 15) * 15);
            return value.getTime();
        }
        value.setHours(0, 0, 0, 0);
        return value.getTime();
    }

    private clearDropHighlights = (): void => {
        if (!this.element) return;
        for (const dropzone of this.element.querySelectorAll<HTMLElement>('[data-gant-dropzone]')) {
            dropzone.classList.remove('ring-2', 'ring-primary');
        }
    };

    private scheduleDependencyDraw = (): void => {
        if (this.drawFrame !== null) window.cancelAnimationFrame(this.drawFrame);
        this.drawFrame = window.requestAnimationFrame(() => {
            this.drawFrame = null;
            this.drawDependencies();
        });
    };

    private drawDependencies(): void {
        if (!this.element) return;

        const svg = this.element.querySelector<SVGSVGElement>('[data-gant-dependencies]');
        const lineGroup = svg?.querySelector<SVGGElement>('[data-gant-dependency-lines]');
        if (!svg || !lineGroup) return;

        const rows = this.element.querySelector<HTMLElement>('[data-gant-rows]');
        const width = this.sidebarWidth + this.canvasWidth;
        const height = rows ? rows.offsetTop + rows.scrollHeight : this.element.clientHeight;
        svg.setAttribute('width', String(width));
        svg.setAttribute('height', String(height));
        svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
        svg.style.width = `${width}px`;
        svg.style.height = `${height}px`;
        lineGroup.replaceChildren();

        const items = Array.from(
            this.element.querySelectorAll<HTMLElement>(`[${componentIdentifier}="gant-chart-item"]`),
        );
        const itemsById = new Map(items.map((item) => [item.dataset.objectId ?? '', item]));
        const drawn = new Set<string>();

        for (const item of items) {
            const objectId = item.dataset.objectId;
            const dependencyFromId = item.dataset.dependencyFromId;
            const dependencyForId = item.dataset.dependencyForId;

            if (objectId && dependencyFromId) {
                this.appendDependency(lineGroup, itemsById.get(dependencyFromId), item, `${dependencyFromId}:${objectId}`, drawn);
            }
            if (objectId && dependencyForId) {
                this.appendDependency(lineGroup, item, itemsById.get(dependencyForId), `${objectId}:${dependencyForId}`, drawn);
            }
        }
    }

    private appendDependency(
        lineGroup: SVGGElement,
        source: HTMLElement | undefined,
        target: HTMLElement | undefined,
        key: string,
        drawn: Set<string>,
    ): void {
        if (!this.element || !source || !target || drawn.has(key)) return;
        drawn.add(key);

        const rootRect = this.element.getBoundingClientRect();
        const sourceRect = source.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        const startX = sourceRect.right - rootRect.left + this.element.scrollLeft;
        const startY = sourceRect.top + sourceRect.height / 2 - rootRect.top + this.element.scrollTop;
        const endX = targetRect.left - rootRect.left + this.element.scrollLeft;
        const endY = targetRect.top + targetRect.height / 2 - rootRect.top + this.element.scrollTop;
        const curve = Math.max(24, Math.abs(endX - startX) / 2);

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', `M ${startX} ${startY} C ${startX + curve} ${startY}, ${endX - curve} ${endY}, ${endX} ${endY}`);
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', 'currentColor');
        path.setAttribute('stroke-width', '2');
        path.setAttribute('class', 'text-primary');
        path.setAttribute('marker-end', `url(#gant-arrow-${this.contentTypeId})`);
        lineGroup.appendChild(path);
    }
}
