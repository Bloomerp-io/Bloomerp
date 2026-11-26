import BaseComponent, { getComponent } from "../BaseComponent";
import { getCsrfToken } from "../../utils/cookies";
import { getDetailPageKey } from "../../utils/itemNavigation";
import { getTopModal } from "../../utils/modals";
import DetailTabs from "./DetailTabs";
import ObjectCRUDViewContainer from "./ObjectCRUDViewContainer";

const MAIN_SELECTOR = "#main";
const DESKTOP_MEDIA_QUERY = "(min-width: 1280px)";
const DETAIL_FRAME_SELECTOR = "[data-detail-view-grid]";
const EMBEDDED_PANE_SELECTOR = "[data-split-view-detail-pane], [data-drawer-detail-pane]";
const PAGE_KEY_EDITORS = [
    "textarea", "select", "[contenteditable='']", "[contenteditable='true' i]",
    "[contenteditable='plaintext-only' i]", "[role~='listbox']", "[role~='combobox']",
    "[role~='spinbutton']", "[role~='textbox']:not(input)", "[aria-expanded='true'][aria-autocomplete]",
    "input[type='number']", "input[type='date']", "input[type='time']", "input[type='datetime-local']",
    "input[type='month']", "input[type='week']", "input[type='range']",
].join(", ");

export default class DetailViewFrame extends BaseComponent {
    private resizeHandler: (() => void) | null = null;
    private resizeObserver: ResizeObserver | null = null;
    private sidebarPreferenceSaveQueue: Promise<void> = Promise.resolve();
    private focusedFieldHash = "";
    private readonly sidebarClickHandler = (event: Event) => this.saveSidebarView(event);

    /** Bind sidebar actions, resizing, and detail keyboard navigation. */
    public initialize(): void {
        if (!this.element) return;

        this.element.addEventListener("click", this.sidebarClickHandler);
        this.element.addEventListener("htmx:beforeCleanupElement", this.onCleanup);
        document.addEventListener("keydown", this.onDetailKeyDown);

        this.resizeHandler = () => this.fitToMainBottom();
        window.addEventListener("resize", this.resizeHandler);
        window.visualViewport?.addEventListener("resize", this.resizeHandler);

        this.setupResizeObserver();
        this.reapplyAfterLayout();
        this.focusLinkedField();
        window.addEventListener("hashchange", this.fieldHashHandler);
    }

    /** Release keyboard listeners and layout observers when the frame leaves the pane. */
    public destroy(): void {
        window.removeEventListener("hashchange", this.fieldHashHandler);
        this.element?.removeEventListener("click", this.sidebarClickHandler);
        this.element?.removeEventListener("htmx:beforeCleanupElement", this.onCleanup);
        document.removeEventListener("keydown", this.onDetailKeyDown);

        if (this.resizeHandler) {
            window.removeEventListener("resize", this.resizeHandler);
            window.visualViewport?.removeEventListener("resize", this.resizeHandler);
        }

        this.resizeObserver?.disconnect();
        this.resizeHandler = null;
        this.resizeObserver = null;
        super.destroy();
    }

    /** Release document listeners when HTMX removes this detail frame. */
    private readonly onCleanup = (event: Event): void => {
        if (event.target === this.element) this.destroy();
    };

    /** Move between tabs and fields after any focused editor has handled the event. */
    private readonly onDetailKeyDown = (event: KeyboardEvent): void => {
        if (event.defaultPrevented || event.isComposing || !(event.target instanceof Element)) return;
        const pageKey = getDetailPageKey(event);
        const tabShortcut = event.altKey && !event.ctrlKey && !event.metaKey && !event.shiftKey && event.code === "KeyT";
        if ((!pageKey && !tabShortcut) || !this.ownsKeyboardTarget(event.target)) return;

        const editorSelector = tabShortcut ? `input, ${PAGE_KEY_EDITORS}` : PAGE_KEY_EDITORS;
        for (const node of event.composedPath()) {
            if (node instanceof Element && node.matches(editorSelector)) return;
        }

        if (pageKey === "PageDown") {
            const layout = this.element.querySelector<HTMLElement>(
                '[data-detail-view-content] [bloomerp-component="object-crud-view-container"]',
            );
            const form = layout && getComponent(layout);
            if (form instanceof ObjectCRUDViewContainer && form.focusDetailFieldDown(event.target)) event.preventDefault();
            return;
        }

        const strip = this.element.querySelector<HTMLElement>("[data-tab-strip]");
        const tabs = strip && getComponent(strip);
        if (tabs instanceof DetailTabs && tabs.focusActiveTab()) event.preventDefault();
    };

    /** Resolve the focused detail, with fallbacks for its own page or overlay shell. */
    private ownsKeyboardTarget(target: Element): boolean {
        const frame = this.element;
        if (!frame?.isConnected || !frame.getClientRects().length || frame.closest("[inert]")) return false;

        let overlay = getTopModal()?.element;
        if (!overlay) {
            const drawers = document.querySelectorAll<HTMLElement>('[bloomerp-component="drawer"]:not(.hidden)');
            overlay = drawers[drawers.length - 1];
        }
        if (overlay && (!overlay.contains(frame) || !overlay.contains(target))) return false;

        const focusedFrame = target.closest(DETAIL_FRAME_SELECTOR);
        if (focusedFrame) return focusedFrame === frame;

        const pane = frame.closest(EMBEDDED_PANE_SELECTOR);
        if (target === pane) return true;
        if (overlay) return overlay.querySelector(DETAIL_FRAME_SELECTOR) === frame && !pane?.closest("[inert]");
        if (pane || frame.parentElement?.id !== "main-content") return false;

        return target === document.body || target === document.documentElement
            || target.matches("#main, #main-content")
            || target.closest("#htmx-addendum")?.parentElement === frame.parentElement;
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
        this.focusedFieldHash = "";
        this.focusLinkedField();
    };

    /** Resolve a field name without treating the URL fragment as a CSS selector. */
    private focusLinkedField(): void {
        const hash = window.location.hash;
        if (!this.element || !hash || hash === this.focusedFieldHash || this.element.closest(EMBEDDED_PANE_SELECTOR)) return;
        let name: string;
        try {
            name = decodeURIComponent(hash.slice(1));
        } catch {
            return;
        }
        const field = Array.from(this.element.querySelectorAll<HTMLElement>("[name]"))
            .find((element: HTMLElement): boolean => element.getAttribute("name") === name);
        if (!field || field.hasAttribute("disabled")) return;
        field.scrollIntoView({ block: "center" });
        field.focus({ preventScroll: true });
        if (document.activeElement === field) this.focusedFieldHash = hash;
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
