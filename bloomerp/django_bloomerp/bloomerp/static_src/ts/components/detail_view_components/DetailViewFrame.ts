import BaseComponent from "../BaseComponent";
import { getCsrfToken } from "../../utils/cookies";

const MAIN_SELECTOR = "#main";
const DESKTOP_MEDIA_QUERY = "(min-width: 1280px)";

export default class DetailViewFrame extends BaseComponent {
    private resizeHandler: (() => void) | null = null;
    private resizeObserver: ResizeObserver | null = null;
    private sidebarPreferenceSaveQueue: Promise<void> = Promise.resolve();
    private readonly sidebarClickHandler = (event: Event) => this.saveSidebarView(event);

    /** Bind sidebar actions, resizing, and deep-link field focus. */
    public initialize(): void {
        if (!this.element) return;

        this.element.addEventListener("click", this.sidebarClickHandler);

        this.resizeHandler = () => this.fitToMainBottom();
        window.addEventListener("resize", this.resizeHandler);
        window.visualViewport?.addEventListener("resize", this.resizeHandler);

        this.setupResizeObserver();
        this.reapplyAfterLayout();
        this.focusLinkedField();
        window.addEventListener("hashchange", this.fieldHashHandler);
    }

    /** Release deep-link listeners and layout observers. */
    public destroy(): void {
        window.removeEventListener("hashchange", this.fieldHashHandler);
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

    /** Focus a visible, enabled field after a browser fragment changes. */
    private readonly fieldHashHandler = (): void => {
        this.focusLinkedField();
    };

    /** Resolve a field name without treating the URL fragment as a CSS selector. */
    private focusLinkedField(): void {
        if (!this.element || !window.location.hash) return;
        let name: string;
        try {
            name = decodeURIComponent(window.location.hash.slice(1));
        } catch {
            return;
        }
        const field = Array.from(this.element.querySelectorAll<HTMLElement>("[name]"))
            .find((element: HTMLElement): boolean => element.getAttribute("name") === name);
        if (!field || field.hasAttribute("disabled")) return;
        field.scrollIntoView({ block: "center" });
        field.focus({ preventScroll: true });
    }

    /** Reveal a comment target after the Comments fragment loads. */
    public onAfterSwap(): void {
        this.focusLinkedField();
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
