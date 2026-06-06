import htmx from "htmx.org";
import BaseSectionedLayoutItem from "../layouts/BaseSectionedLayoutItem";
import getGeneralModal from "@/utils/modals";

export default class WorkspaceTile extends BaseSectionedLayoutItem {
    private icon = "";
    private title = "";

    public initialize(): void {
        super.initialize();
        if (!this.element) return;

        const tileId = this.element.dataset.tileId ?? "";
        if (tileId) {
            this.itemId = tileId;
        }

        // Set settings button
        this.element.querySelector('[data-update-tile]').addEventListener('click', ()=> {
            const url = this.element.dataset.updateUrl
            const modal = getGeneralModal()
            modal.setSize('full')
            modal.setTitle('Update Tile')

            htmx.ajax(
                'get',
                url,
                {
                    target: modal.getBodyElement()
                }
            ).then(()=> {modal.open()})
        })
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

    public getTileId(): string {
        return this.getLayoutItemId();
    }
}
