import BaseComponent from "../BaseComponent";
import { getCsrfToken } from "../../utils/cookies";

const MAIN_SELECTOR = "#main";
const DESKTOP_MEDIA_QUERY = "(min-width: 1280px)";

export default class DetailViewFrame extends BaseComponent {
    private resizeHandler: (() => void) | null = null;
    private resizeObserver: ResizeObserver | null = null;
    private sidebarPreferenceSaveQueue: Promise<void> = Promise.resolve();
    private readonly sidebarClickHandler = (event: Event) => this.saveSidebarView(event);

    public initialize(): void {
        if (!this.element) return;

        this.element.addEventListener("click", this.sidebarClickHandler);

        this.resizeHandler = () => this.fitToMainBottom();
        window.addEventListener("resize", this.resizeHandler);
        window.visualViewport?.addEventListener("resize", this.resizeHandler);

        this.setupResizeObserver();
        this.reapplyAfterLayout();
    }

    public destroy(): void {
        this.element?.removeEventListener("click", this.sidebarClickHandler);

        if (this.resizeHandler) {
            window.removeEventListener("resize", this.resizeHandler);
            window.visualViewport?.removeEventListener("resize", this.resizeHandler);
        }

        this.resizeObserver?.disconnect();
        this.resizeHandler = null;
        this.resizeObserver = null;
        super.destroy();
    }

    private saveSidebarView(event: Event): void {
        const target = event.target as HTMLElement | null;
        const button = target?.closest<HTMLElement>("[data-detail-sidebar-view]");
        const saveUrl = this.element?.dataset.sidebarPreferenceUrl;
        const view = button?.dataset.detailSidebarView;

        if (!button || !saveUrl || !view) return;

        this.sidebarPreferenceSaveQueue = this.sidebarPreferenceSaveQueue
            .then(async () => {
                const csrfToken = getCsrfToken();
                const response = await fetch(saveUrl, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: csrfToken ? { "X-CSRFToken": csrfToken } : {},
                    body: new URLSearchParams({ view }),
                });

                if (!response.ok) {
                    throw new Error(`Preference request failed with status ${response.status}.`);
                }
            })
            .catch((error: unknown) => {
                console.error("Unable to save the detail sidebar preference.", error);
            });
    }

    /** Reveal a comment target after the Comments fragment loads. */
    public onAfterSwap(): void {
        this.revealLinkedComment();
        this.reapplyAfterLayout();
    }

    /** Scroll to a linked comment once HTMX has loaded the sidebar fragment. */
    private revealLinkedComment(): void {
        if (!this.element || !/^#comment-\d+$/.test(window.location.hash)) return;
        const comment = this.element.querySelector<HTMLElement>(window.location.hash);
        comment?.scrollIntoView({ block: "center", behavior: "smooth" });
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
