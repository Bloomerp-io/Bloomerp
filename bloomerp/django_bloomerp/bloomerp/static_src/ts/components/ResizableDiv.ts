import BaseComponent from "./BaseComponent";
import { getShortcutManager } from "../utils/shortcutManager";
import { formatShortcutForAria, formatShortcutForDisplay, parseShortcut } from "../utils/shortcuts";
import { t } from "../utils/i18n";
import { getCookie, setCookie } from "../utils/cookies";
import { getLocalStorageValue, setLocalStorageValue } from "../utils/localStorage";

const DEFAULT_START_WIDTH = "320px";
const MIN_WIDTH = 0;
const MAX_WIDTH_RATIO = 0.75;
const DESKTOP_MEDIA_QUERY = "(min-width: 1280px)";
const HANDLE_SELECTOR = "[data-resizable-div-handle]";
const PANEL_SELECTOR = "[data-resizable-div-panel]";
const MAIN_SELECTOR = "#main";

/** Resolve a configured or stored width, using the standard panel default. */
function parseWidth(value: string | undefined): string {
    const width = value?.trim();
    return width || DEFAULT_START_WIDTH;
}

export default class ResizableDiv extends BaseComponent {
    private handle: HTMLElement | null = null;
    private unregisterShortcut: (() => void) | null = null;
    private shortcutHint: HTMLElement | null = null;
    private expandedWidth = "";
    private pointerDownHandler: ((event: PointerEvent) => void) | null = null;
    private handleDoubleClickHandler: ((event: MouseEvent) => void) | null = null;
    private resizeObserver: ResizeObserver | null = null;
    private resizeHandler: (() => void) | null = null;
    private storageKey = "";
    private currentWidth = "";
    private resizeFrom: "left" | "right" = "left";
    private dragCleanup: (() => void) | null = null;
    /** Reconcile widths only when this panel participated in an HTMX swap. */
    private readonly settleHandler = (event: Event): void => this.handleSettle(event);
    /** Release this instance before HTMX removes its root element. */
    private readonly cleanupHandler = (event: Event): void => {
        if (event.target === this.element) this.destroy();
    };

    /** Restore configured sizing and persistence, then bind this panel's resize interaction. */
    public initialize(): void {
        if (!this.element) return;

        const id = this.element.dataset.id?.trim() || this.element.id || "default";
        this.resizeFrom = this.element.dataset.resizeFrom === "right" ? "right" : "left";
        this.storageKey = this.element.dataset.storageKey || `bloomerp_resizable_div_width_v3_${id}`;
        const localWidth = this.element.dataset.storage === "local"
            ? getLocalStorageValue<number | null>(this.storageKey, null) : null;
        const storedWidth = this.element.dataset.storage === "local"
            ? localWidth !== null && Number.isFinite(localWidth) ? `${localWidth}px` : undefined
            : getCookie(this.storageKey);
        this.currentWidth = parseWidth(storedWidth || this.element.dataset.startWidth);
        if (this.element.dataset.forceOpen === "true" && Number.parseFloat(this.currentWidth) === 0) {
            this.currentWidth = parseWidth(this.element.dataset.startWidth);
            this.saveWidth(this.currentWidth);
        }

        this.applyWidth(this.currentWidth);
        this.element.style.minWidth = `${this.numberOption("minWidth", MIN_WIDTH)}px`;

        this.ensureHandle();
        this.setupToggleShortcut();
        this.reapplyAfterLayout();
        this.setupResizeObserver();
        this.setupHeightFitting();

        /** Start a drag owned by this panel and release any interrupted prior drag. */
        this.pointerDownHandler = (event: PointerEvent): void => {
            if (!this.element) return;
            const target = event.target;
            if (!(target instanceof Element) || !target.closest(HANDLE_SELECTOR)) return;
            if (target.closest(HANDLE_SELECTOR)?.closest('[bloomerp-component="resizable-div"]') !== this.element) return;
            this.dragCleanup?.();

            event.preventDefault();
            event.stopPropagation();
            const startX = event.clientX;
            const startWidthPx = this.element.getBoundingClientRect().width;

            /** Follow the pointer using the configured resize edge and sizing limits. */
            const onMove = (moveEvent: PointerEvent): void => {
                if (!this.element) return;

                const delta = this.resizeFrom === "right"
                    ? moveEvent.clientX - startX
                    : startX - moveEvent.clientX;
                const nextWidth = this.clampWidth(startWidthPx + delta);
                this.applyWidth(`${nextWidth}px`);
            };

            /** Persist the final width and release all drag resources. */
            const onUp = (): void => {
                if (this.element) {
                    const width = `${Math.round(this.clampWidth(this.element.getBoundingClientRect().width))}px`;
                    this.applyWidth(width);
                    this.saveWidth(width);
                }
                this.dragCleanup?.();
            };
            /** Stop this drag, including when the panel is removed during a request. */
            this.dragCleanup = (): void => {
                document.body.classList.remove("select-none");
                document.body.style.cursor = "";
                document.removeEventListener("pointermove", onMove);
                document.removeEventListener("pointerup", onUp);
                this.dragCleanup = null;
            };

            document.body.classList.add("select-none");
            document.body.style.cursor = "col-resize";
            document.addEventListener("pointermove", onMove);
            document.addEventListener("pointerup", onUp);
        };

        this.element.addEventListener("pointerdown", this.pointerDownHandler);
        this.element.addEventListener("htmx:beforeCleanupElement", this.cleanupHandler);
        document.body.addEventListener("htmx:afterSettle", this.settleHandler);
    }

    /** Release resize listeners and the optional panel toggle shortcut. */
    public destroy(): void {
        this.dragCleanup?.();
        this.element?.removeEventListener("htmx:beforeCleanupElement", this.cleanupHandler);
        document.body.removeEventListener("htmx:afterSettle", this.settleHandler);
        this.unregisterShortcut?.();
        this.unregisterShortcut = null;
        this.shortcutHint?.remove();
        this.shortcutHint = null;
        if (this.element && this.pointerDownHandler) {
            this.element.removeEventListener("pointerdown", this.pointerDownHandler);
        }
        if (this.handle && this.handleDoubleClickHandler) {
            this.handle.removeEventListener("dblclick", this.handleDoubleClickHandler);
        }

        this.resizeObserver?.disconnect();
        if (this.resizeHandler) {
            window.removeEventListener("resize", this.resizeHandler);
            window.visualViewport?.removeEventListener("resize", this.resizeHandler);
        }
        this.handle?.remove();
        this.handle = null;
        this.resizeObserver = null;
        this.resizeHandler = null;
        this.pointerDownHandler = null;
        this.handleDoubleClickHandler = null;
        this.currentWidth = "";
        this.storageKey = "";
        this.resizeFrom = "left";
        super.destroy();
    }

    /** Reconcile layout when the panel or its descendants have changed. */
    public onAfterSwap(): void {
        this.reapplyAfterLayout();
    }

    /** Apply responsive panel sizing and remember the last nonzero width. */
    private applyWidth(width: string): void {
        if (!this.element) return;

        this.currentWidth = width;
        if (Number.parseFloat(width) > 0) this.expandedWidth = width;

        if (!this.isResizableLayout()) {
            this.element.style.width = "";
            this.element.style.flexBasis = "";
            this.element.style.maxWidth = "";
            return;
        }

        const numericWidth = Number.parseFloat(width);
        const unit = width.replace(String(numericWidth), "").trim();
        const pixelWidth = unit === "%"
            ? (this.getResizeContainer()?.clientWidth ?? window.innerWidth) * numericWidth / 100
            : numericWidth;
        const nextWidth = Number.isFinite(pixelWidth) && (unit === "px" || unit === "%")
            ? `${this.clampWidth(pixelWidth)}px` : width;

        this.element.style.width = nextWidth;
        this.element.style.flexBasis = nextWidth;
        this.element.style.maxWidth = nextWidth;
    }

    private reapplyAfterLayout(): void {
        window.requestAnimationFrame(() => {
            window.requestAnimationFrame(() => {
                if (!this.currentWidth) return;
                this.applyWidth(this.currentWidth);
                this.fitHeightToMainBottom();
            });
        });
    }

    /** Clamp the panel while reserving configured space for its neighboring pane. */
    private clampWidth(width: number): number {
        const container = this.getResizeContainer();
        const containerWidth = container?.getBoundingClientRect().width || window.innerWidth;
        const minWidth = this.numberOption("minWidth", MIN_WIDTH);
        const maxWidth = Math.max(minWidth, Math.min(
            containerWidth * this.numberOption("maxWidthRatio", MAX_WIDTH_RATIO),
            containerWidth - this.numberOption("minRemainingWidth", 0),
        ));
        return Math.min(Math.max(width, minWidth), maxWidth);
    }

    /** Read a nonnegative sizing option without accepting invalid numeric values. */
    private numberOption(name: string, fallback: number): number {
        const value = Number(this.element?.dataset[name] ?? fallback);
        return Number.isFinite(value) && value >= 0 ? value : fallback;
    }

    /** Keep split panes resizable at every viewport size when requested. */
    private isResizableLayout(): boolean {
        return this.element?.dataset.responsive?.toLowerCase() === "false" || window.matchMedia(DESKTOP_MEDIA_QUERY).matches;
    }

    /** Persist pixel widths in the selected storage backend, preserving legacy keys. */
    private saveWidth(width: string): void {
        if (this.element?.dataset.storage === "local") {
            setLocalStorageValue(this.storageKey, Number.parseFloat(width));
        } else {
            setCookie(this.storageKey, width, 30);
        }
    }

    /** Restore inline sizing after HTMX settles replacement panel attributes. */
    private handleSettle(event: Event): void {
        const target = event instanceof CustomEvent ? event.detail?.target : null;
        if (!this.element?.isConnected || !(target instanceof HTMLElement) || !target.contains(this.element)) return;
        this.applyWidth(this.currentWidth);
        this.fitHeightToMainBottom();
    }

    private setupResizeObserver(): void {
        const container = this.getResizeContainer();
        const main = document.querySelector<HTMLElement>(MAIN_SELECTOR);
        if (!container || typeof ResizeObserver === "undefined") return;

        this.resizeObserver = new ResizeObserver(() => {
            if (!this.currentWidth) return;
            this.applyWidth(this.currentWidth);
            this.fitHeightToMainBottom();
        });
        this.resizeObserver.observe(container);
        if (main && main !== container) {
            this.resizeObserver.observe(main);
        }
    }

    private getResizeContainer(): HTMLElement | null {
        return this.element?.closest<HTMLElement>(
            "[data-resizable-div-container], [data-detail-view-grid]",
        ) ?? null;
    }

    private setupHeightFitting(): void {
        if (!this.shouldFitHeightToMainBottom()) return;

        this.resizeHandler = () => this.reapplyAfterLayout();
        window.addEventListener("resize", this.resizeHandler);
        window.visualViewport?.addEventListener("resize", this.resizeHandler);
        this.fitHeightToMainBottom();
    }

    private fitHeightToMainBottom(): void {
        if (!this.element || !this.shouldFitHeightToMainBottom()) return;

        if (!window.matchMedia(DESKTOP_MEDIA_QUERY).matches) {
            this.element.style.height = "";
            this.element.style.maxHeight = "";
            return;
        }

        const main = document.querySelector<HTMLElement>(MAIN_SELECTOR);
        if (!main) return;

        const elementRect = this.element.getBoundingClientRect();
        const mainRect = main.getBoundingClientRect();
        const bottom = Math.min(mainRect.bottom, window.innerHeight);
        const availableHeight = Math.max(0, Math.floor(bottom - elementRect.top));

        this.element.style.height = `${availableHeight}px`;
        this.element.style.maxHeight = `${availableHeight}px`;
    }

    private shouldFitHeightToMainBottom(): boolean {
        return this.element?.dataset.fitToMainBottom === "true";
    }

    /** Collapse an eligible panel or restore its most recent expanded width. */
    private toggleCollapsedWidth(): void {
        if (!this.element) return;

        if (!this.isResizableLayout() || this.numberOption("minWidth", MIN_WIDTH) > 0) return;
        const currentWidthPx = this.clampWidth(this.element.getBoundingClientRect().width);
        const nextWidth = Math.round(currentWidthPx) <= MIN_WIDTH
            ? this.expandedWidth || parseWidth(this.element.dataset.startWidth)
            : `${MIN_WIDTH}px`;

        this.applyWidth(nextWidth);
        this.saveWidth(nextWidth);
    }

    /** Register a scoped toggle and advertise it on the panel's resize handle. */
    private setupToggleShortcut(): void {
        this.unregisterShortcut?.();
        this.shortcutHint?.remove();
        const shortcut = parseShortcut(this.element.dataset.toggleShortcut || "");
        if (!shortcut || !this.handle) return;
        const label = `${t("Toggle side panel")} (${formatShortcutForDisplay(shortcut)})`;
        this.handle.title = label;
        this.handle.setAttribute("aria-keyshortcuts", formatShortcutForAria(shortcut));
        this.shortcutHint = document.createElement("div");
        this.shortcutHint.className = "absolute right-2 top-2 z-50 w-max rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-900 shadow-sm pointer-events-none";
        this.shortcutHint.textContent = label;
        this.shortcutHint.hidden = true;
        this.handle.appendChild(this.shortcutHint);
        this.unregisterShortcut = getShortcutManager().register({
            rootElement: this.handle,
            shortcut,
            showHint: this.showShortcutHint,
            hideHint: this.hideShortcutHint,
            performAction: this.toggleCollapsedWidth.bind(this),
        });
    }

    /** Show the toggle hint while shortcut discovery mode is active. */
    private showShortcutHint = (): void => {
        if (this.shortcutHint) this.shortcutHint.hidden = false;
    };

    /** Hide the toggle hint after shortcut discovery or component cleanup. */
    private hideShortcutHint = (): void => {
        if (this.shortcutHint) this.shortcutHint.hidden = true;
    };

    /** Create the drag handle with optional instance-specific handle and line styling. */
    private ensureHandle(): void {
        if (!this.element) return;

        for (const existingHandle of this.element.querySelectorAll<HTMLElement>(HANDLE_SELECTOR)) {
            if (existingHandle.closest('[bloomerp-component="resizable-div"]') === this.element) {
                existingHandle.remove();
            }
        }

        const panel = this.element.querySelector<HTMLElement>(PANEL_SELECTOR);
        panel?.classList.add("relative");
        if (window.getComputedStyle(this.element).position === "static") {
            this.element.classList.add("relative");
        }

        const handle = document.createElement("div");
        handle.className = this.element.dataset.handleClass || [
            "absolute",
            this.resizeFrom === "right" ? "right-0" : "left-0",
            "top-0",
            "z-40",
            "h-full",
            "group",
            "w-2",
            this.resizeFrom === "right" ? "translate-x-1/2" : "-translate-x-1/2",
            "cursor-col-resize",
        ].join(" ");
        handle.setAttribute("aria-label", "Resize panel");
        handle.setAttribute("role", "separator");
        handle.setAttribute("data-resizable-div-handle", "true");

        const handleLine = document.createElement("div");
        handleLine.className = this.element.dataset.handleLineClass || [
            "pointer-events-none",
            "absolute",
            "inset-y-0",
            "left-1/2",
            "w-px",
            "-translate-x-1/2",
            "bg-gray-200",
            "transition-colors",
            "group-hover:bg-primary",
        ].join(" ");
        handleLine.setAttribute("aria-hidden", "true");
        handle.appendChild(handleLine);

        /** Toggle collapsible panels without affecting a parent component. */
        this.handleDoubleClickHandler = (event: MouseEvent): void => {
            event.preventDefault();
            event.stopPropagation();
            this.toggleCollapsedWidth();
        };
        handle.addEventListener("dblclick", this.handleDoubleClickHandler);

        this.element.appendChild(handle);
        this.handle = handle;
    }
}
