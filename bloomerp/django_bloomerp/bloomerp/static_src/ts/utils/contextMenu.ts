import { t as _ } from "./i18n";

export type ContextMenuItem = {
    label: string;
    icon?: string;
    onClick?: (context: ContextMenuContext) => void | Promise<void>;
    disabled?: boolean;
    submenu?: ContextMenuSubmenu | (() => ContextMenuSubmenu);
};

export type ContextMenuSubmenu = {
    label: string;
    items?: ContextMenuItem[];
    search?: {
        placeholder: string;
        load: (query: string, signal: AbortSignal) => Promise<ContextMenuItem[]>;
    };
    onOpen?: () => void;
};

export type ContextMenuContext = {
    trigger: HTMLElement;
    event: MouseEvent | KeyboardEvent;
    hide: () => void;
};

export type ContextMenuShowOptions = { hideOnViewportChange?: boolean };

export type ContextMenuController = {
    element: HTMLDivElement;
    show: (event: MouseEvent | KeyboardEvent, trigger: HTMLElement, items: ContextMenuItem[]) => void;
    showAt: (position: { x: number; y: number }, trigger: HTMLElement, items: ContextMenuItem[], options?: ContextMenuShowOptions) => void;
    showSubmenu: (submenu: ContextMenuSubmenu, trigger: HTMLElement) => void;
    hide: () => void;
    destroy: () => void;
};

interface MenuPage {
    items: ContextMenuItem[];
    submenu?: ContextMenuSubmenu;
    query: string;
}

const menuCache = new Map<string, ContextMenuController>();
let activeMenu: ContextMenuController | null = null;

/** Own reusable menu navigation, searchable pages, and cancellable loading. */
class ContextMenu implements ContextMenuController {
    public readonly element: HTMLDivElement;
    private readonly lifecycle = new AbortController();
    private readonly list = document.createElement("ul");
    private readonly header = document.createElement("div");
    private readonly status = document.createElement("p");
    private pages: MenuPage[] = [];
    private trigger: HTMLElement | null = null;
    private position = { x: 0, y: 0 };
    private index = -1;
    private searchInput: HTMLInputElement | null = null;
    private request?: AbortController;
    private timer?: ReturnType<typeof setTimeout>;
    private hideOnViewportChange = true;

    /** Connect one reusable menu to outside clicks and keyboard navigation. */
    public constructor(private readonly id: string) {
        this.element = document.createElement("div");
        this.element.id = id;
        this.element.className = "fixed hidden bg-white shadow-lg rounded-lg border border-gray-200 z-50 min-w-[140px] max-w-sm";
        this.element.setAttribute("role", "group");
        this.list.className = "py-1 max-h-80 overflow-y-auto";
        this.status.className = "px-3 py-2 text-xs text-gray-500";
        this.status.setAttribute("role", "status");
        this.element.append(this.header, this.status, this.list);
        document.body.append(this.element);
        this.element.addEventListener("click", this.onClick, { signal: this.lifecycle.signal });
        this.element.addEventListener("mousedown", this.onMouseDown, { signal: this.lifecycle.signal });
        document.addEventListener("click", this.onOutsideClick, { signal: this.lifecycle.signal });
        document.addEventListener("keydown", this.onKeyDown, { capture: true, signal: this.lifecycle.signal });
        window.addEventListener("scroll", this.onViewportChange, { capture: true, signal: this.lifecycle.signal });
        window.addEventListener("resize", this.onViewportChange, { signal: this.lifecycle.signal });
    }

    /** Display a root menu at its triggering pointer or control. */
    public show(event: MouseEvent | KeyboardEvent, trigger: HTMLElement, items: ContextMenuItem[]): void {
        const rect = trigger.getBoundingClientRect();
        this.showAt({ x: "clientX" in event ? event.clientX : rect.left, y: "clientY" in event ? event.clientY : rect.bottom }, trigger, items);
    }

    /** Replace the root page while keeping all state local to this menu. */
    public showAt(position: { x: number; y: number }, trigger: HTMLElement, items: ContextMenuItem[], options: ContextMenuShowOptions = {}): void {
        // Editor selection changes must not overwrite a submenu while its search has focus.
        if (activeMenu === this && this.pages.at(-1)?.submenu) return;
        if (activeMenu && activeMenu !== this) activeMenu.hide();
        this.trigger = trigger;
        this.position = position;
        this.hideOnViewportChange = options.hideOnViewportChange ?? true;
        this.pages = [{ items, query: "" }];
        this.renderPage();
    }

    /** Enter a child page or open a searchable page directly from a toolbar. */
    public showSubmenu(submenu: ContextMenuSubmenu, trigger: HTMLElement): void {
        if (activeMenu !== this) {
            activeMenu?.hide();
            this.pages = [];
            const rect = trigger.getBoundingClientRect();
            this.position = { x: rect.left, y: rect.bottom + 4 };
            this.trigger = trigger;
        }
        submenu.onOpen?.();
        this.pages.push({ items: submenu.items ?? [], submenu, query: "" });
        this.renderPage();
    }

    /** Abort work belonging to the previous page before changing menu state. */
    private cancelSearch(): void {
        clearTimeout(this.timer);
        this.request?.abort();
    }

    /** Render the current page, optional back control, and reusable search field. */
    private renderPage(): void {
        this.cancelSearch();
        this.header.replaceChildren();
        this.searchInput = null;
        const page = this.pages.at(-1)!;
        this.element.setAttribute("aria-label", page.submenu?.label ?? _("Actions"));
        if (page.submenu) {
            const back = document.createElement("button");
            back.type = "button";
            back.dataset.menuBack = "true";
            back.className = "w-full px-3 py-2 text-left text-sm border-b border-gray-200";
            back.textContent = "‹ " + page.submenu.label;
            back.setAttribute("aria-label", _("Back"));
            this.header.append(back);
        }
        if (page.submenu?.search) {
            this.searchInput = document.createElement("input");
            this.searchInput.type = "search";
            this.searchInput.className = "input input-sm w-full";
            this.searchInput.placeholder = page.submenu.search.placeholder;
            this.searchInput.setAttribute("aria-label", page.submenu.search.placeholder);
            this.searchInput.value = page.query;
            this.searchInput.addEventListener("input", this.onSearch);
            const searchWrapper = document.createElement("div");
            searchWrapper.className = "p-2";
            searchWrapper.append(this.searchInput);
            this.header.append(searchWrapper);
        }
        this.element.classList.remove("hidden");
        activeMenu = this;
        const modal = this.trigger?.closest<HTMLElement>('[bloomerp-component="modal"]');
        const zIndex = modal ? Number.parseInt(getComputedStyle(modal).zIndex, 10) : 50;
        this.element.style.zIndex = String((Number.isFinite(zIndex) ? zIndex : 100) + 1);
        this.renderItems();
        this.reposition();
        if (page.submenu?.search) {
            void this.load();
            queueMicrotask(this.focusSearch);
        }
    }

    /** Focus search after the invoking editor's handlers have completed. */
    private focusSearch = (): void => {
        if (activeMenu === this) this.searchInput?.focus({ preventScroll: true });
    };

    /** Draw safe text labels and disclose items that lead to a child page. */
    private renderItems(): void {
        const page = this.pages.at(-1)!;
        this.list.replaceChildren();
        this.index = -1;
        this.status.textContent = page.items.length ? "" : _("No results.");
        this.status.hidden = Boolean(page.items.length);
        for (const [index, item] of page.items.entries()) {
            const li = document.createElement("li");
            const button = document.createElement("button");
            button.type = "button";
            button.dataset.contextMenuItem = String(index);
            button.className = "w-full text-left px-3 py-2 text-xs hover:bg-gray-50 disabled:opacity-50 flex items-center gap-1.5";
            button.disabled = Boolean(item.disabled);
            if (item.icon) {
                const icon = document.createElement("i");
                icon.className = item.icon;
                icon.setAttribute("aria-hidden", "true");
                button.append(icon);
            }
            button.append(document.createTextNode(item.label));
            if (item.submenu) {
                button.setAttribute("aria-haspopup", "true");
                const arrow = document.createElement("span");
                arrow.className = "ml-auto";
                arrow.textContent = "›";
                arrow.setAttribute("aria-hidden", "true");
                button.append(arrow);
            }
            li.append(button);
            this.list.append(li);
        }
        this.reposition();
    }

    /** Keep long menus inside the viewport. */
    private reposition(): void {
        const rect = this.element.getBoundingClientRect();
        this.element.style.left = Math.max(8, Math.min(this.position.x, window.innerWidth - rect.width - 8)) + "px";
        this.element.style.top = Math.max(8, Math.min(this.position.y, window.innerHeight - rect.height - 8)) + "px";
    }

    /** Clear stale results immediately and debounce search requests. */
    private onSearch = (): void => {
        this.cancelSearch();
        const page = this.pages.at(-1)!;
        page.query = this.searchInput!.value;
        page.items = [];
        this.renderItems();
        this.status.hidden = false;
        this.status.textContent = _("Loading…");
        this.timer = setTimeout(this.load, 180);
    };

    /** Load the current search, ignoring aborted results from older pages or queries. */
    private load = async (): Promise<void> => {
        const page = this.pages.at(-1)!;
        if (!page.submenu?.search) return;
        const controller = new AbortController();
        this.request = controller;
        this.status.hidden = false;
        this.status.textContent = _("Loading…");
        try {
            const items = await page.submenu.search.load(page.query, controller.signal);
            if (controller.signal.aborted || this.pages.at(-1) !== page) return;
            page.items = items;
            this.renderItems();
        } catch {
            if (!controller.signal.aborted) {
                this.status.hidden = false;
                this.status.textContent = _("Could not load results. Try searching again.");
            }
        }
    };

    /** Return to the parent page, or dismiss a directly opened submenu. */
    private back(): void {
        if (this.pages.length <= 1) {
            this.hide();
            this.trigger?.focus();
            return;
        }
        this.pages.pop();
        this.renderPage();
    }

    /** Activate leaves only after closing their menu, avoiding child-menu dismissal races. */
    private activate(index: number, event: MouseEvent | KeyboardEvent): void {
        const item = this.pages.at(-1)?.items[index];
        if (!item || item.disabled || !this.trigger) return;
        if (item.submenu) {
            this.showSubmenu(typeof item.submenu === "function" ? item.submenu() : item.submenu, this.trigger);
            return;
        }
        const context = { trigger: this.trigger, event, hide: this.hide.bind(this) };
        this.hide();
        void item.onClick?.(context);
    }

    /** Route clicks to back navigation or current-page items. */
    private onClick = (event: MouseEvent): void => {
        const target = event.target as HTMLElement;
        if (target.closest("[data-menu-back]")) this.back();
        else {
            const button = target.closest<HTMLElement>("[data-context-menu-item]");
            if (!button) return;
            this.activate(Number(button.dataset.contextMenuItem), event);
        }
        event.preventDefault();
        event.stopPropagation();
    };

    /** Preserve editor selection while allowing a submenu search field to receive focus. */
    private onMouseDown = (event: MouseEvent): void => {
        if ((event.target as HTMLElement).closest("button")) event.preventDefault();
    };

    /** Dismiss only when clicking outside both the menu and its owning trigger. */
    private onOutsideClick = (event: MouseEvent): void => {
        if (activeMenu === this && !this.element.contains(event.target as Node) && !this.trigger?.contains(event.target as Node)) this.hide();
    };

    /** Ignore scrolling inside results while dismissing menus on external viewport changes. */
    private onViewportChange = (event: Event): void => {
        if (event.target instanceof Node && this.element.contains(event.target)) return;
        if (activeMenu !== this) return;
        if (this.pages.at(-1)?.submenu) this.reposition();
        else if (this.hideOnViewportChange) this.hide();
    };

    /** Navigate enabled items and enter or leave submenus with the keyboard. */
    private onKeyDown = (event: KeyboardEvent): void => {
        if (activeMenu !== this) return;
        const searching = event.target === this.searchInput;
        if (event.key === "Escape" || (event.key === "ArrowLeft" && !searching)) this.back();
        else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            const buttons = Array.from(this.list.querySelectorAll<HTMLButtonElement>("button"));
            const direction = event.key === "ArrowDown" ? 1 : -1;
            let next = this.index < 0 ? (direction > 0 ? 0 : buttons.length - 1) : this.index + direction;
            while (buttons[next]?.disabled) next += direction;
            if (buttons[next]) this.index = next;
            for (const [index, button] of buttons.entries()) {
                button.classList.toggle("bg-gray-50", index === this.index);
                if (index === this.index) button.scrollIntoView({ block: "nearest" });
            }
        } else if (event.key === "Enter" || (event.key === "ArrowRight" && !searching)) {
            const index = this.index < 0 ? 0 : this.index;
            if (event.key === "Enter" || this.pages.at(-1)?.items[index]?.submenu) this.activate(index, event);
            else return;
        } else if (event.key === "Tab") {
            this.hide();
            return;
        } else return;
        event.preventDefault();
        event.stopPropagation();
    };

    /** Dismiss every page and cancel asynchronous work. */
    public hide(): void {
        this.cancelSearch();
        this.element.classList.add("hidden");
        this.element.style.zIndex = "";
        this.pages = [];
        if (activeMenu === this) activeMenu = null;
    }

    /** Remove owned listeners, markup, requests, and the cached controller. */
    public destroy(): void {
        this.hide();
        this.lifecycle.abort();
        this.element.remove();
        menuCache.delete(this.id);
    }
}

/** Return an instance-local controller for the named reusable context menu. */
export function getContextMenu(id = "bloomerp-context-menu"): ContextMenuController {
    let menu = menuCache.get(id);
    if (!menu) {
        menu = new ContextMenu(id);
        menuCache.set(id, menu);
    }
    return menu;
}

/** Expose the open controller for integrations that intentionally navigate its pages. */
export function getActiveContextMenu(): ContextMenuController | null {
    return activeMenu;
}
