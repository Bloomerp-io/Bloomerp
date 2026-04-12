import BaseComponent from "./BaseComponent";

export default class SearchSection extends BaseComponent {
    private searchInput: HTMLInputElement | null = null;
    private searchItems: HTMLElement[] = [];
    private searchHandler: ((event: Event) => void) | null = null;

    public initialize(): void {
        if (!this.element) return;

        this.searchInput = this.element.querySelector<HTMLInputElement>('input[name="q"]');
        this.searchItems = Array.from(this.element.querySelectorAll<HTMLElement>("[search-item]"));

        if (!this.searchInput || this.searchItems.length === 0) return;

        this.searchHandler = () => {
            this.applySearch(this.searchInput?.value || "");
        };

        this.searchInput.addEventListener("input", this.searchHandler);
        this.applySearch(this.searchInput.value || "");
    }

    public destroy(): void {
        if (this.searchInput && this.searchHandler) {
            this.searchInput.removeEventListener("input", this.searchHandler);
        }

        this.searchHandler = null;
        this.searchInput = null;
        this.searchItems = [];
    }

    private applySearch(rawQuery: string): void {
        const query = rawQuery.trim().toLowerCase();

        this.searchItems.forEach((item) => {
            const searchableNodes = Array.from(item.querySelectorAll<HTMLElement>("[search-item-text]"));
            const searchableText = searchableNodes.length > 0
                ? searchableNodes.map((node) => node.textContent || "").join(" ")
                : (item.textContent || "");

            const matches = !query || searchableText.toLowerCase().includes(query);
            item.classList.toggle("hidden", !matches);
        });
    }
}
