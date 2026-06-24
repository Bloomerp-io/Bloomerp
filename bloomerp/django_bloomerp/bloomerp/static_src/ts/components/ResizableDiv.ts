import BaseComponent from "./BaseComponent";
import { getCookie, setCookie } from "../utils/cookies";

const DEFAULT_START_WIDTH = "320px";
const MIN_WIDTH = 0;
const MAX_WIDTH_RATIO = 0.5;
const DESKTOP_MEDIA_QUERY = "(min-width: 1280px)";
const HANDLE_SELECTOR = "[data-resizable-div-handle]";
const PANEL_SELECTOR = "[data-resizable-div-panel]";
const MAIN_SELECTOR = "#main";

function parseWidth(value: string | undefined): string {
    const width = value?.trim();
    return width || DEFAULT_START_WIDTH;
}

export default class ResizableDiv extends BaseComponent {
    private handle: HTMLElement | null = null;
    private pointerDownHandler: ((event: PointerEvent) => void) | null = null;
    private handleDoubleClickHandler: ((event: MouseEvent) => void) | null = null;
    private resizeObserver: ResizeObserver | null = null;
    private resizeHandler: (() => void) | null = null;
    private cookieKey = "";
    private currentWidth = "";

    public initialize(): void {
        if (!this.element) return;

        const id = this.element.dataset.id?.trim() || this.element.id || "default";
        this.cookieKey = `bloomerp_resizable_div_width_v3_${id}`;
        this.currentWidth = parseWidth(getCookie(this.cookieKey) || this.element.dataset.startWidth);

        this.applyWidth(this.currentWidth);
        this.element.style.minWidth = `${MIN_WIDTH}px`;

        this.ensureHandle();
        this.reapplyAfterLayout();
        this.setupResizeObserver();
        this.setupHeightFitting();

        this.pointerDownHandler = (event: PointerEvent) => {
            if (!this.element) return;
            const target = event.target;
            if (!(target instanceof Element) || !target.closest(HANDLE_SELECTOR)) return;

            event.preventDefault();
            event.stopPropagation();
            const startX = event.clientX;
            const startWidthPx = this.element.getBoundingClientRect().width;

            const onMove = (moveEvent: PointerEvent): void => {
                if (!this.element) return;

                const delta = startX - moveEvent.clientX;
                const nextWidth = this.clampWidth(startWidthPx + delta);
                this.applyWidth(`${nextWidth}px`);
            };

            const onUp = (): void => {
                if (this.element) {
                    const width = `${Math.round(this.clampWidth(this.element.getBoundingClientRect().width))}px`;
                    this.applyWidth(width);
                    setCookie(this.cookieKey, width, 30);
                }

                document.body.classList.remove("select-none");
                document.body.style.cursor = "";
                document.removeEventListener("pointermove", onMove);
                document.removeEventListener("pointerup", onUp);
            };

            document.body.classList.add("select-none");
            document.body.style.cursor = "col-resize";
            document.addEventListener("pointermove", onMove);
            document.addEventListener("pointerup", onUp);
        };

        this.element.addEventListener("pointerdown", this.pointerDownHandler);
    }

    public destroy(): void {
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
        this.cookieKey = "";
        super.destroy();
    }

    public onAfterSwap(): void {
        this.reapplyAfterLayout();
    }

    private applyWidth(width: string): void {
        if (!this.element) return;

        this.currentWidth = width;

        if (!window.matchMedia(DESKTOP_MEDIA_QUERY).matches) {
            this.element.style.width = "";
            this.element.style.flexBasis = "";
            this.element.style.maxWidth = "";
            return;
        }

        const numericWidth = Number.parseFloat(width);
        const unit = width.replace(String(numericWidth), "").trim();
        const nextWidth = Number.isFinite(numericWidth) && unit === "px"
            ? `${this.clampWidth(numericWidth)}px`
            : width;

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

    private clampWidth(width: number): number {
        const container = this.element?.closest<HTMLElement>("[data-detail-view-grid]");
        const containerWidth = container?.getBoundingClientRect().width || window.innerWidth;
        const maxWidth = Math.max(MIN_WIDTH, containerWidth * MAX_WIDTH_RATIO);
        return Math.min(Math.max(width, MIN_WIDTH), maxWidth);
    }

    private setupResizeObserver(): void {
        const container = this.element?.closest<HTMLElement>("[data-detail-view-grid]");
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

    private toggleCollapsedWidth(): void {
        if (!this.element) return;

        const currentWidthPx = this.clampWidth(this.element.getBoundingClientRect().width);
        const nextWidth = Math.round(currentWidthPx) <= MIN_WIDTH
            ? parseWidth(this.element.dataset.startWidth)
            : `${MIN_WIDTH}px`;

        this.applyWidth(nextWidth);
        setCookie(this.cookieKey, nextWidth, 30);
    }

    private ensureHandle(): void {
        if (!this.element) return;

        this.element.querySelectorAll(HANDLE_SELECTOR).forEach((existingHandle) => existingHandle.remove());

        const panel = this.element.querySelector<HTMLElement>(PANEL_SELECTOR);
        panel?.classList.add("relative");
        this.element.classList.add("relative");

        const handle = document.createElement("div");
        handle.className = [
            "absolute",
            "left-0",
            "top-0",
            "z-50",
            "h-full",
            "w-3",
            "-translate-x-1/2",
            "cursor-col-resize",
            "transition-colors",
            "hover:bg-primary-500/25",
        ].join(" ");
        handle.setAttribute("aria-label", "Resize panel");
        handle.setAttribute("role", "separator");
        handle.setAttribute("data-resizable-div-handle", "true");

        this.handleDoubleClickHandler = (event: MouseEvent) => {
            event.preventDefault();
            event.stopPropagation();
            this.toggleCollapsedWidth();
        };
        handle.addEventListener("dblclick", this.handleDoubleClickHandler);

        this.element.appendChild(handle);
        this.handle = handle;
    }
}
