import BaseComponent from "../BaseComponent";

export default class OrderedFieldSelect extends BaseComponent {
    private clickHandler: ((event: Event) => void) | null = null;

    public initialize(): void {
        if (!this.element) return;

        this.clickHandler = this.handleClick.bind(this);
        this.element.addEventListener("click", this.clickHandler);
        this.syncButtonState();
    }

    public destroy(): void {
        if (this.element && this.clickHandler) {
            this.element.removeEventListener("click", this.clickHandler);
        }
        this.clickHandler = null;
    }

    private handleClick(event: Event): void {
        const button = (event.target as HTMLElement | null)?.closest<HTMLButtonElement>("[data-ordered-field-move]");
        if (!button) return;

        const row = button.closest<HTMLElement>("[data-ordered-field-option]");
        if (!row) return;

        const direction = button.dataset.orderedFieldMove;
        if (direction === "up" && row.previousElementSibling) {
            row.parentElement?.insertBefore(row, row.previousElementSibling);
        }
        if (direction === "down" && row.nextElementSibling) {
            row.parentElement?.insertBefore(row.nextElementSibling, row);
        }
        this.syncButtonState();
    }

    private syncButtonState(): void {
        if (!this.element) return;

        const rows = Array.from(this.element.querySelectorAll<HTMLElement>("[data-ordered-field-option]"));
        rows.forEach((row, index) => {
            const upButton = row.querySelector<HTMLButtonElement>('[data-ordered-field-move="up"]');
            const downButton = row.querySelector<HTMLButtonElement>('[data-ordered-field-move="down"]');
            if (upButton) upButton.disabled = index === 0;
            if (downButton) downButton.disabled = index === rows.length - 1;
        });
    }
}
