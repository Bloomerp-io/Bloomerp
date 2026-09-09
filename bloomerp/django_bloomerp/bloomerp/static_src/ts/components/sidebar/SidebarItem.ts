import BaseComponent from "../BaseComponent";

export class SidebarItem extends BaseComponent {
    private isFolder = false;
    private itemId: string | null = null;
    private sidebarId: string | null = null;

    public initialize(): void {
        if (!this.element) return;

        this.isFolder = this.element.dataset.isFolder?.toLowerCase() === 'true';
        this.itemId = this.element.dataset.sidebarItemId ?? null;
        this.sidebarId = this.element.dataset.sidebarId ?? null;

        if (!this.isFolder || !this.itemId || !this.sidebarId) return;

        this.setExpanded(this.readExpandedFolderIds().has(this.itemId));
        this.element.addEventListener('click', this.onClick);
    }

    public override destroy(): void {
        this.element?.removeEventListener('click', this.onClick);
    }

    private readonly onClick = (event: MouseEvent): void => {
        if (!this.element || !(event.target instanceof HTMLElement)) return;

        const itemRoot = event.target.closest<HTMLElement>('[data-sidebar-item-root]');
        const toggle = event.target.closest<HTMLElement>('[data-sidebar-folder-toggle]');
        if (itemRoot !== this.element || !toggle || event.target.closest('[data-ignore-toggle]')) return;

        const children = this.getChildrenElement();
        if (!children) return;

        this.setExpanded(children.hidden);
    };

    private setExpanded(expanded: boolean): void {
        const children = this.getChildrenElement();
        if (!children || !this.itemId) return;

        children.hidden = !expanded;

        const button = this.element?.querySelector<HTMLButtonElement>('[data-sidebar-folder-button]');
        button?.setAttribute('aria-expanded', String(expanded));

        const caret = this.element?.querySelector<HTMLElement>('[data-sidebar-folder-caret]');
        caret?.classList.toggle('fa-caret-down', expanded);
        caret?.classList.toggle('fa-caret-right', !expanded);

        const expandedFolderIds = this.readExpandedFolderIds();
        if (expanded) {
            expandedFolderIds.add(this.itemId);
        } else {
            expandedFolderIds.delete(this.itemId);
        }
        this.writeExpandedFolderIds(expandedFolderIds);
    }

    private getChildrenElement(): HTMLUListElement | null {
        return this.element?.querySelector<HTMLUListElement>(':scope > [data-sidebar-children]') ?? null;
    }

    private get storageKey(): string | null {
        return this.sidebarId ? `bloomerp_sidebar_expanded_folders:${this.sidebarId}` : null;
    }

    private readExpandedFolderIds(): Set<string> {
        if (!this.storageKey) return new Set();

        try {
            const storedValue = window.localStorage.getItem(this.storageKey);
            if (!storedValue) return new Set();

            const parsedValue: unknown = JSON.parse(storedValue);
            if (!Array.isArray(parsedValue)) return new Set();

            return new Set(parsedValue.filter((value): value is string => typeof value === 'string'));
        } catch {
            return new Set();
        }
    }

    private writeExpandedFolderIds(expandedFolderIds: Set<string>): void {
        if (!this.storageKey) return;

        try {
            window.localStorage.setItem(this.storageKey, JSON.stringify([...expandedFolderIds]));
        } catch {
            // The sidebar still works when storage is unavailable (for example in private browsing).
        }
    }

}
