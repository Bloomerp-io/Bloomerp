import BaseComponent from "../BaseComponent";

const MAIN_SELECTOR = "#main";
const DESKTOP_MEDIA_QUERY = "(min-width: 1280px)";

export default class DetailViewFrame extends BaseComponent {
    private resizeHandler: (() => void) | null = null;
    private resizeObserver: ResizeObserver | null = null;

    public initialize(): void {
        if (!this.element) return;

        this.resizeHandler = () => this.fitToMainBottom();
        window.addEventListener("resize", this.resizeHandler);
        window.visualViewport?.addEventListener("resize", this.resizeHandler);

        this.setupResizeObserver();
        this.reapplyAfterLayout();
    }

    public destroy(): void {
        if (this.resizeHandler) {
            window.removeEventListener("resize", this.resizeHandler);
            window.visualViewport?.removeEventListener("resize", this.resizeHandler);
        }

        this.resizeObserver?.disconnect();
        this.resizeHandler = null;
        this.resizeObserver = null;
        super.destroy();
    }

    public onAfterSwap(): void {
        this.reapplyAfterLayout();
    }

    private reapplyAfterLayout(): void {
        window.requestAnimationFrame(() => {
            window.requestAnimationFrame(() => this.fitToMainBottom());
        });
    }

    private fitToMainBottom(): void {
        if (!this.element) return;

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

    private setupResizeObserver(): void {
        if (typeof ResizeObserver === "undefined") return;

        const main = document.querySelector<HTMLElement>(MAIN_SELECTOR);
        if (!main) return;

        this.resizeObserver = new ResizeObserver(() => this.reapplyAfterLayout());
        this.resizeObserver.observe(main);
    }
}
