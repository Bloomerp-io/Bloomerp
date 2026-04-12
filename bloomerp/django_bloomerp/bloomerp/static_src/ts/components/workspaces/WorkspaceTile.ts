import BaseSectionedLayoutItem from "../layouts/BaseSectionedLayoutItem";

export default class WorkspaceTile extends BaseSectionedLayoutItem {
    private icon = "";
    private title = "";

    public initialize(): void {
        super.initialize();
        if (!this.element) return;

        const tileId = Number.parseInt(this.element.dataset.tileId ?? "-1", 10);
        if (Number.isFinite(tileId)) {
            this.itemId = tileId;
        }
    }

    public setIcon(icon: string): void {
        if (!this.element) return;

        this.icon = icon;
        const iconElement = this.element.querySelector<HTMLElement>("[data-tile-icon] i");
        if (iconElement) {
            iconElement.className = `fa ${icon}`;
        }
    }

    public setTitle(title: string): void {
        if (!this.element) return;

        this.title = title;
        const titleElement = this.element.querySelector<HTMLElement>("[data-tile-title]");
        if (titleElement) {
            titleElement.textContent = title;
        }
    }

    public getTileId(): number {
        return this.getLayoutItemId();
    }
}
